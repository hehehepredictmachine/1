"""PMW-UPD-11 FF06-FF08: native export importer/parity, runtime sections, CLI pipeline (TEST_ONLY synthetic export), reaction task,
holdout once, TEST_ONLY never SHADOW. No orders, no MT5 connection."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

import _env  # noqa: F401
from _env import TempData

from masterquo.lab.flow_context import heikin as HF
from masterquo.lab.flow_context import native as NV
from masterquo.lab.flow_context import stop_distance as SD
from test_structure_intelligence import m1_bars, write_export

FIX = Path(__file__).resolve().parent / "fixtures" / "flow_context"


class NativeTests(unittest.TestCase):
    def _export(self, d, bars, seed_origin=True, tamper=False):
        hf = HF.heikin_series(bars, {"ma1": "EMA", "p1": 10, "ma2": "EMA", "p2": 5}, 0.01)["rows"]
        sd = SD.series(bars, None, 0.01)
        rows = [{"bar_time": b["open_utc"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "ha_o": r["o"], "ha_h": r["h"], "ha_l": r["l"],
                 "ha_c": r["c"] + (0.5 if tamper and i == 50 else 0.0), "sd_range": s["range_points"], "sd_avg": s["average_points"],
                 "sd_sugg": s["suggested_points"]} for i, (b, r, s) in enumerate(zip(bars, hf, sd))]
        p = Path(d) / "PMW" / NV.FlowImporter.NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        NV.write_export(p, {"seq": 3, "symbol": "XAUUSD-", "tf": "M15", "point": 0.01, "tick": 0.01, "written_at_utc": time.time(),
                            "seed_origin": bars[0]["open_utc"] if seed_origin else None, "heikin": {"ma1": "EMA", "p1": 10, "ma2": "EMA", "p2": 5},
                            "stopdistance": {"period": 20, "method": "SMA", "factor": 1.5}}, rows)
        return p

    def test_t49_t50_import_and_parity(self):
        bars = NV.frozen_inputs(200)
        with tempfile.TemporaryDirectory() as d:
            p = self._export(d, bars)
            ex = NV.parse_export(p.read_bytes())
            self.assertEqual(NV.compare(ex)["status"], "OWN_IMPLEMENTATIONS_MATCH")
            imp = NV.FlowImporter(d, "XAUUSD-", "M15")
            self.assertEqual(imp.poll()["status"], "IMPORTED")
            self.assertEqual(imp.poll()["status"], "STALE_SEQUENCE")
            self.assertEqual(NV.FlowImporter(d, "BTCUSD", "M15").poll()["reason"], "CONTEXT_MISMATCH")
            p.write_bytes(p.read_bytes().replace(b"#sha256=", b"#sha256=00"))
            self.assertEqual(NV.FlowImporter(d, "XAUUSD-", "M15").poll()["status"], "REJECTED")
            p2 = self._export(d, bars, tamper=True)
            r = NV.compare(NV.parse_export(p2.read_bytes()))
            self.assertEqual(r["status"], "MISMATCH")
            self.assertEqual(r["first"][0]["field"], "ha_c")
            p3 = self._export(d, bars, seed_origin=False)
            self.assertEqual(NV.compare(NV.parse_export(p3.read_bytes()))["status"], "PARITY_CONTEXT_MISMATCH")
        self.assertEqual(NV.FlowImporter(None, "XAUUSD-").poll()["status"], "NATIVE_FEED_UNAVAILABLE")

    def test_t47_t52_native_status_and_golden(self):
        r = NV.parity(FIX)
        self.assertEqual(r["NATIVE_COMPILED"], "NOT_COMPILED_NO_METAEDITOR")
        self.assertEqual(r["OWN_IMPLEMENTATIONS"]["status"], "NOT_RUN")
        self.assertEqual(r["PYTHON_VS_GOLDEN"]["status"], "PASS")
        root = Path(__file__).resolve().parents[1] / "mql5" / "FlowContext"
        srcs = list(root.rglob("*.mq*"))
        self.assertGreaterEqual(len(srcs), 6)
        for f in srcs:
            t = f.read_text(encoding="utf-8")
            for bad in ("OrderSend", "CTrade", "#import", "WebRequest"):
                self.assertNotIn(bad, t, f)
        hf = (root / "Indicators" / "MQ_HeikinFlow.mq5").read_text(encoding="utf-8")
        self.assertIn("indicator_buffers 24", hf)
        self.assertIn("indicator_plots   7", hf)
        self.assertFalse(list(root.rglob("*.ex5")))


class KnowledgeTests(unittest.TestCase):
    def test_t59_agent_knowledge(self):
        from masterquo.agent.service import load_prompt
        from masterquo.analysis import structure_knowledge as sk
        text, ver = load_prompt()
        self.assertIn("F05", text)
        self.assertTrue("PMW-FLOW-KNOWLEDGE-1.0.0" in ver)
        snap = {"cells": {"M15": {"status": "OK", "structure": {}, "flow": {"status": "OK", "heikin": {"color": "BULL", "quality": "PARTIAL_STARTUP"},
                "stopdistance": {"average_points": 120.0, "suggested_points": 180.0, "suggested_price_distance": 1.8},
                "sr": {"nearest": {"support": {"lo": 1, "hi": 2, "id": "x"}, "resistance": None}}}}}, "forecast": {}}
        ex = sk.explain(snap)
        for r in ("F01", "F02", "F03", "F05"):
            self.assertIn(r, ex["rules"])
        self.assertNotIn("%", ex["text"])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_t53_t59_pipeline_and_runtime(self):
        import mq_instruments
        from masterquo.db.database import Database
        from masterquo.lab.flow_context import cli as C
        from masterquo.lab.flow_context import task as FT
        from masterquo.lab.flow_context.service import FlowSections
        db = Database()
        db.migrate()
        ds = write_export(mq_instruments.data_dir() / "exp", m1_bars(2600))
        self.assertEqual(C.main(["calibrate", "--asset", "XAUUSD", "--dataset", str(ds)]), 2)          # synthetic refused without the flag
        self.assertEqual(C.main(["calibrate", "--asset", "XAUUSD", "--dataset", str(ds), "--allow-synthetic-fixture",
                                 "--modules", "heikin,stopdistance"]), 0)
        self.assertEqual(FT.profile("XAUUSD")["source"], "CALIBRATED_ON_DEV")
        self.assertEqual(C.main(["train-markov", "--asset", "XAUUSD", "--dataset", str(ds), "--allow-synthetic-fixture"]), 0)
        self.assertEqual(C.main(["dataset", "--asset", "XAUUSD", "--dataset", str(ds), "--allow-synthetic-fixture"]), 0)
        rep = FT.train("XAUUSD", FT.latest("XAUUSD"), ["LOGREG"], "quick", db=db, log=lambda *a: None)
        self.assertEqual(rep["role"], "TEST_ONLY")
        self.assertEqual(rep["edge_status"], "NO_VALIDATED_EDGE")
        self.assertIn("+markov3", rep["ablations"])
        cid = rep["candidates"]["LOGREG"]["candidate_id"]
        with self.assertRaises(ValueError):
            FT.select_shadow("XAUUSD", cid)
        r1 = FT.evaluate_holdout("XAUUSD", cid, "SI-PROTO-1.0.0", db)
        r2 = FT.evaluate_holdout("XAUUSD", cid, "SI-PROTO-1.0.0", db)
        self.assertEqual((r1["status"], r2["status"]), ("EVALUATED_ONCE", "ALREADY_EVALUATED"))
        meta, m = FT.load_candidate(Path(rep["run_dir"]) / "models" / "LOGREG")
        self.assertEqual(meta["schema"], FT.SCHEMA)
        # profile change -> stale dataset refused
        pj = FT.root("XAUUSD") / "profile.json"
        pr = json.loads(pj.read_text())
        pr["heikin"]["p1"] = 7
        pj.write_text(json.dumps(pr))
        self.assertEqual(FT.train("XAUUSD", FT.latest("XAUUSD"), ["LOGREG"], "quick")["status"], "STALE_DATASET")
        # runtime: same producer, repeated poll does not change state, markov from the fitted artefact
        bars = m1_bars(900)
        fs = FlowSections()
        k = fs.update("XAUUSD", "M1", bars, 0.01, 0.01)
        n = len(k.ha)
        fs.update("XAUUSD", "M1", bars, 0.01, 0.01)
        self.assertEqual(len(k.ha), n)
        s = fs.summary(k)
        self.assertEqual(s["status"], "OK")
        self.assertIn(s["heikin"]["color"], ("BULL", "BEAR", "NEUTRAL"))
        self.assertNotEqual(s["markov3"].get("status"), "MODEL_MISSING")
        st = fs.stopdistance(k, 2000.0, "BUY", 50)
        self.assertLess(st["sl_price_proposal"], 2000.0)
        self.assertTrue(st["diagnostics"]["advisory"])
        ch = fs.channels(k, mode="HISTORY_AS_KNOWN")
        self.assertTrue(ch["snapshots"])


if __name__ == "__main__":
    unittest.main()
