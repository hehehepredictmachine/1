"""PMW-UPD-14 section 11/12: runtime ContextSections (idempotent polls, revision -> new epoch, ledger ids, SHADOW would_block, as-of SMC
view), native export parity (tamper / context mismatch), golden fixture, CLI refusals. No MT5 connection, no orders."""
import json
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

from masterquo.lab.context_ind import cli as C
from masterquo.lab.context_ind import native as NV
from masterquo.lab.context_ind.service import ContextSections
from test_structure_intelligence import m1_bars, write_export

FIX = Path(__file__).resolve().parent / "fixtures" / "context_ind"


def m5(n=500, seed=4):
    bs = m1_bars(n * 5, seed)
    out = []
    for i in range(0, len(bs) - 4, 5):
        g = bs[i:i + 5]
        out.append({"open_utc": g[0]["open_utc"], "o": g[0]["o"], "h": max(b["h"] for b in g), "l": min(b["l"] for b in g), "c": g[-1]["c"]})
    return out


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_sections(self):
        bars = m5(500)
        cs = ContextSections()
        k = cs.update("XAUUSD", "M5", bars[:400], 0.01)
        h0, n0 = k.smc.state_hash(), len(k.vrows)
        cs.update("XAUUSD", "M5", bars[:400], 0.01)
        self.assertEqual((k.smc.state_hash(), len(k.vrows)), (h0, n0))           # repeated poll changes nothing
        k2 = cs.update("XAUUSD", "M5", bars[:450], 0.01)
        self.assertIs(k2, k)
        self.assertEqual(len(k.smc.bars), 450)
        s = cs.summary(k)
        self.assertEqual(s["status"], "OK")
        self.assertEqual(s["mode"], "OBSERVE_SHADOW")
        for side in ("BUY", "SELL"):
            self.assertIn(s["would_block"][side]["status"], ("WOULD_BLOCK", "NO_BLOCK", "UNKNOWN"))
        led = list((Path(self.td.dir) / "context_ind" / "XAUUSD" / "ledger").glob("*.jsonl"))
        ids = [json.loads(x)["ledger_id"] for x in led[0].read_text().splitlines()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), len(k.smc.events))
        # revision of history -> new epoch, rebuild
        rev = [dict(b) for b in bars[:450]]
        rev[-1]["c"] += 1.0
        k3 = cs.update("XAUUSD", "M5", rev, 0.01)
        self.assertIsNot(k3, k)
        self.assertEqual(k3.epoch, k.epoch + 1)
        # as-of view only shows what was published by then
        v = cs.smc(k3)
        if v["events"]:
            cut = v["events"][len(v["events"]) // 2]["available_at"]
            va = cs.smc(k3, as_of=cut)
            self.assertTrue(all(e["available_at"] <= cut for e in va["events"]))
            self.assertTrue(all(p["available_at"] <= cut for p in va["points"]))
            self.assertIsNone(va["provisional"])
        self.assertIn("preview", cs.vamd(k3, 10, preview_bar=dict(bars[460])))
        self.assertEqual(cs.fractal(k3, 5)["profile"], "PWM_KATZ_BOUNDED_v1")
        self.assertEqual(cs.external("XAUUSD-", "M5")["status"], "UNAVAILABLE")

    def test_would_block_rules(self):
        wb = ContextSections.would_block
        self.assertEqual(wb({"vamd": {"y": None}, "fd": {"zone": "TREND"}})["BUY"]["status"], "UNKNOWN")
        r = wb({"vamd": {"y": 0.3}, "fd": {"zone": "TREND"}, "smc": {"trend": "UP"}})
        self.assertEqual(r["BUY"]["status"], "NO_BLOCK")                       # no block is NOT a trigger
        self.assertIn("nie jest triggerem", r["BUY"]["note"])
        self.assertEqual(set(r["SELL"]["reasons"]), {"VAMD_AGAINST", "SMC_TREND_AGAINST"})
        self.assertIn("FD_CHOP", wb({"vamd": {"y": 0.3}, "fd": {"zone": "CHOP"}, "smc": {}})["BUY"]["reasons"])


class NativeTests(unittest.TestCase):
    def test_export_parity_and_golden(self):
        bars = NV.frozen_inputs(300)
        rows = NV.reference_rows(bars, None, None, None, 0.01, 300)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "native_export.txt"
            hdr = {"seq": 1, "symbol": "XAUUSD-", "tf": "M5", "tf_s": 300, "tick": 0.01, "seed_origin": rows[0]["bar_time"]}
            NV.write_export(p, hdr, rows)
            self.assertEqual(NV.compare(NV.parse_export(p.read_bytes()))["status"], "OWN_IMPLEMENTATIONS_MATCH")
            bad = [dict(r) for r in rows]
            bad[200]["event_mask"] = (bad[200]["event_mask"] or 0) ^ 1
            NV.write_export(p, hdr, bad)
            r = NV.compare(NV.parse_export(p.read_bytes()))
            self.assertEqual(r["status"], "MISMATCH")
            self.assertEqual(r["first"][0]["field"], "event_mask")
            NV.write_export(p, dict(hdr, seed_origin=0), rows)
            self.assertEqual(NV.compare(NV.parse_export(p.read_bytes()))["status"], "PARITY_CONTEXT_MISMATCH")
            p.write_bytes(p.read_bytes().replace(b"#sha256=", b"#sha256=0"))
            with self.assertRaises(NV.CtxExportError):
                NV.parse_export(p.read_bytes())
        self.assertEqual(sum(1 for r in rows if r["event_mask"]) > 0, True)
        par = NV.parity(FIX)
        self.assertEqual(par["PYTHON_VS_GOLDEN"]["status"], "PASS")
        self.assertEqual(par["NATIVE_COMPILED"], "NOT_EXECUTED_METAEDITOR_UNAVAILABLE")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_cli(self):
        import mq_instruments
        ds = mq_instruments.data_dir() / "exp"
        write_export(ds, m1_bars(4000, seed=8))
        self.assertEqual(C.main(["audit", "--dataset", str(ds)]), 2)                 # synthetic refused without the flag
        self.assertEqual(C.main(["audit", "--dataset", str(ds), "--allow-synthetic-fixture"]), 0)
        self.assertEqual(C.main(["replay", "--dataset", str(ds), "--allow-synthetic-fixture"]), 0)
        self.assertEqual(C.main(["train", "--dataset", str(ds), "--allow-synthetic-fixture"]), 2)   # no dataset yet
        with tempfile.TemporaryDirectory() as d:
            from masterquo.lab.context_ind import buffers as B
            rp = Path(d) / "r.json"
            rp.write_bytes(B.wrap(B.REPORT_SCHEMA, {"terminal_build": 1, "scan_range": {"from": 0, "to": 511}, "instances": []}))
            self.assertEqual(C.main(["buffers-verify", "--report", str(rp)]), 0)
            rp.write_bytes(b"junk")
            self.assertEqual(C.main(["buffers-verify", "--report", str(rp)]), 2)


if __name__ == "__main__":
    unittest.main()
