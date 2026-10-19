"""PMW-UPD-02 (IQ Gold Gann / IQ Star Lines / PAL02M / Parabolic SAR). Synthetic data only for code tests (fixture_only);
MT5 / MetaEditor / the paid products are not available here -> exporter compile, iSAR parity and real mappings are NOT_RUN."""
from __future__ import annotations

import json
import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env
from _env import TempData

UTC = timezone.utc


class TestSar(unittest.TestCase):
    def setUp(self):
        from masterquo.scalp import indicators as ind
        self.ind = ind

    def test_reference_and_flip(self):
        p = self.ind.sar_points([10, 11, 12, 13, 14], [9, 10, 11, 12, 13])
        self.assertAlmostEqual(p[-1]["sar"], 9.3528, places=10)
        self.assertEqual(p[-1]["trend"], "UP")
        q = self.ind.sar_points([10, 11, 12, 13, 14, 13], [9, 10, 11, 12, 13, 8.5])
        self.assertEqual((q[-1]["sar"], q[-1]["trend"], q[-1]["flip"], q[-1]["ep"], q[-1]["af"]), (14, "DOWN", True, 8.5, 0.02))
        self.assertEqual(self.ind.sar([10, 11, 12, 13, 14], [9, 10, 11, 12, 13])[-1], {"sar": p[-1]["sar"], "trend": "UP", "flip": False})  # legacy adapter

    def test_equality_is_not_a_cross_and_down_market(self):
        h = [20, 19, 18, 17, 16, 15]
        lo = [19, 18, 17, 16, 15, 14]
        p = self.ind.sar_points(h, lo)
        self.assertEqual(p[-1]["trend"], "DOWN")
        cand = p[-1]["sar"] + p[-1]["af"] * (p[-1]["ep"] - p[-1]["sar"])
        cand = max(cand, h[-1], h[-2])
        q = self.ind.sar_points(h + [cand], lo + [cand - 1])          # high == candidate -> no flip
        self.assertFalse(q[-1]["flip"])

    def test_validation(self):
        for args in (([1, 2], [0, 1], 0.2, 0.1), ([1, 2], [0, 1], 0, 0.2), ([1, 2], [0], 0.02, 0.2), ([1, float("nan")], [0, 1], 0.02, 0.2),
                     ([1, 0], [0, 1], 0.02, 0.2)):
            with self.assertRaises(self.ind.SarInputError):
                self.ind.sar_points(*args)
        self.assertEqual(self.ind.sar_points([1], [0]), [None])

    def test_flat_is_not_a_trend(self):
        d = self.ind.sar_diagnostics([100.0] * 10, [100.0] * 10, [100.0] * 10, None)
        self.assertEqual((d["raw_trend"], d["interpretation"]), ("UP", "NO_DIRECTIONAL_EVIDENCE"))

    def test_prefix_chunks_and_restart(self):
        import random
        r = random.Random(3)
        c = [100.0]
        for _ in range(300):
            c.append(c[-1] + r.gauss(0, 1))
        h = [x + abs(r.gauss(0, 0.5)) for x in c]
        lo = [x - abs(r.gauss(0, 0.5)) for x in c]
        full = self.ind.sar_points(h, lo)
        self.assertEqual(self.ind.sar_points(h[:150], lo[:150]), full[:150])           # prefix invariance (causal)
        st = self.ind.SarState()
        for a, b in zip(h[:120], lo[:120]):
            st.update(a, b)
        st2 = self.ind.SarState.restore(json.loads(json.dumps(st.checkpoint())))      # restart from a persisted checkpoint
        tail = [st2.update(a, b) for a, b in zip(h[120:], lo[120:])]
        self.assertEqual(tail, full[120:])
        with self.assertRaises(self.ind.SarInputError):
            self.ind.SarState.restore(dict(st.checkpoint(), profile="OTHER"))


def _env_body(adapter="IQ_GOLD_GANN", seq=1, gen=1, objects=None, symbol="XAUUSD-", basis="UTC", ver="1.0"):
    return {"schema_version": "pmw-extind-1", "producer_version": "test", "adapter_id": adapter, "product": {"version": ver},
            "terminal_fingerprint": "Srv:001", "chart_id": "77", "symbol": symbol, "tf": "PERIOD_M5", "time_basis": basis,
            "captured_at_server": 1_800_000_000, "generation": gen, "sequence": seq, "complete": True,
            "objects": objects if objects is not None else [{"name": "IQG_major_1", "type": "HLINE", "prices": [2650.0], "times": []},
                                                              {"name": "IQG_minor_1", "type": "HLINE", "prices": [2640.5], "times": []},
                                                              {"name": "user_line", "type": "HLINE", "prices": [2600.0], "times": []}]}


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.config import ConfigStore
        from masterquo.extind import contract, mapping, service
        self.c, self.m, self.s = contract, mapping, service
        self.db = Database()
        self.svc = service.ExtIndService(ConfigStore(), self.db)

    def tearDown(self):
        self.td.close()

    def test_contract(self):
        c = self.c
        raw = c.wrap(_env_body())
        self.assertEqual(c.validate(raw)["objects"][0]["prices"], [2650.0])
        with self.assertRaises(c.EnvelopeError):
            c.validate(raw[: len(raw) // 2])                                      # partial write
        bad = json.loads(raw)
        bad["checksum"] = "0" * 64
        with self.assertRaises(c.EnvelopeError):
            c.validate(json.dumps(bad).encode())
        b = _env_body(objects=[{"name": "osc", "type": "OTHER", "prices": [0.0, 1.7976931348623157e308], "times": []}])
        o = c.validate(c.wrap(b))["objects"][0]
        self.assertEqual(o["prices"], [0.0, None])                                # zero is a value, EMPTY_VALUE is null
        txt = json.dumps(_env_body(objects=[{"name": "x", "type": "HLINE", "prices": [float("nan")], "times": []}]), separators=(",", ":"))
        with self.assertRaises(c.EnvelopeError):
            c.validate(json.dumps({"envelope": c.SCHEMA, "checksum": c.checksum(txt), "body": txt}).encode())
        with self.assertRaises(c.EnvelopeError):
            c.validate(c.wrap(_env_body(objects=[{"name": "t", "type": "TREND", "prices": [1.0], "times": [1]}])))
        with self.assertRaises(c.EnvelopeError):
            c.validate(b"x" * (c.MAX_BYTES + 1))

    def test_archive_mapping_duplicates_and_as_of(self):
        t0 = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
        self.assertEqual(self.svc.ingest_bytes(self.c.wrap(_env_body()), now=t0), 1)
        self.assertEqual(self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", t0), None)          # no approved mapping -> nothing usable
        with self.assertRaises(ValueError):
            self.m.save_mapping("IQ_GOLD_GANN", {"rules": [{"prefix": "IQG_", "type": "HLINE", "kind": "LEVEL"}], "approved": True})  # no verified numbers
        self.m.save_mapping("IQ_GOLD_GANN", {"product_version": "1.0", "approved": True, "verified_examples": [{"name": "IQG_major_1", "chart": 2650.0}],
                                             "rules": [{"prefix": "IQG_major", "type": "HLINE", "kind": "LEVEL", "role": "MAJOR"},
                                                       {"prefix": "IQG_minor", "type": "HLINE", "kind": "LEVEL", "role": "MINOR"}]})
        hb = dict(self.svc.heartbeat["IQ_GOLD_GANN"])
        self.assertEqual(self.svc.ingest_bytes(self.c.wrap(_env_body()), now=t0 + timedelta(seconds=30)), 0)   # duplicate sequence
        self.assertEqual(self.svc.heartbeat["IQ_GOLD_GANN"]["at"], hb["at"])                                     # not refreshed
        self.svc.ingest_bytes(self.c.wrap(_env_body(seq=2)), now=t0 + timedelta(minutes=1))
        s = self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", t0 + timedelta(minutes=2))
        self.assertEqual(sorted((x["role"], x["price"]) for x in s["levels"]), [("MAJOR", 2650.0), ("MINOR", 2640.5)])   # user line not adopted
        self.assertIsNone(self.svc.as_of("IQ_GOLD_GANN", "XAUUSD", t0 + timedelta(seconds=59)))                       # not yet received
        self.svc.ingest_bytes(self.c.wrap(_env_body(seq=3, ver="2.0")), now=t0 + timedelta(minutes=3))
        st = self.svc.status("XAUUSD", t0 + timedelta(minutes=3))["adapters"]
        self.assertEqual(st["IQ_GOLD_GANN"]["mapping_status"], "MAPPING_APPROVED")
        self.assertEqual(self.db.one("SELECT mapping_status FROM extind_snapshots WHERE sequence=3")["mapping_status"], "MAPPING_VERSION_CHANGED")
        self.assertEqual(st["PAL02M"]["identity_status"], "BLOCKED_IDENTITY_REQUIRED")
        self.assertEqual(st["PAL02M"]["runtime_status"], "NOT_READY")
        self.assertEqual(st["IQ_STAR_LINES"]["source_status"], "SOURCE_MISSING")

    def test_star_windows_time_basis(self):
        self.m.save_mapping("IQ_STAR_LINES", {"approved": True, "verified_examples": [{"x": 1}],
                                              "rules": [{"prefix": "STAR_win", "type": "RECTANGLE", "kind": "TIME_WINDOW", "role": "ASPECT"}]})
        objs = [{"name": "STAR_win_1", "type": "RECTANGLE", "prices": [1.0, 2.0], "times": [1_800_003_600, 1_800_000_000]}]
        self.svc.ingest_bytes(self.c.wrap(_env_body("IQ_STAR_LINES", objects=objs, basis="BROKER_SERVER")))
        r = self.db.one("SELECT time_status, windows FROM extind_snapshots WHERE adapter='IQ_STAR_LINES'")
        self.assertEqual(r["time_status"], "TIME_BASIS_UNVERIFIED")                 # no verified server offset -> no precise countdown
        self.assertIsNone(json.loads(r["windows"])[0]["scheduled_start_utc"])


class TestComposerAndAgent(unittest.TestCase):
    def test_composer_causal_and_missing(self):
        from masterquo.extind import features as F
        t = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        bars = []
        for k in range(120):
            o = t - timedelta(minutes=5 * (120 - k))
            bars.append({"open_utc": o.isoformat().replace("+00:00", "Z"), "o": 100 + k * 0.1, "h": 100.5 + k * 0.1, "l": 99.5 + k * 0.1, "c": 100.2 + k * 0.1})
        spec = F.default_spec(("BASE", "SAR", "IQ_GOLD_GANN", "PAL02M"))
        snap = {"decision_time": t, "side": "BUY", "price": 112.0, "atr_m5": 1.0, "base": {}, "bars": {"M5": bars, "M15": bars}, "ext": {}}
        a = F.build_indicator_context_features(snap, spec)
        late = bars + [{"open_utc": t.isoformat().replace("+00:00", "Z"), "o": 1, "h": 999, "l": 0.5, "c": 1}]       # bar not closed at t
        b = F.build_indicator_context_features(dict(snap, bars={"M5": late, "M15": late}), spec)
        self.assertEqual({k: v for k, v in a["features"].items() if k.startswith("sar_")}, {k: v for k, v in b["features"].items() if k.startswith("sar_")})
        self.assertTrue(math.isnan(a["features"]["gann_up_dist_atr"]) and a["missing"]["gann_up_dist_atr"])
        self.assertEqual(a["groups"]["IQ_GOLD_GANN"], "MISSING_NO_APPROVED_SNAPSHOT_AS_OF")
        self.assertEqual(a["groups"]["PAL02M"], "BLOCKED_IDENTITY_REQUIRED")
        self.assertEqual(list(a["features"]), F.feature_names(spec))

    def test_agent_knowledge_loaded_from_code(self):
        from masterquo.agent.service import load_prompt
        from masterquo.agent.tools import TOOL_DEFS
        body, ver = load_prompt()
        self.assertIn("PMW-IND-KNOWLEDGE-1.0.0", ver)
        for k in range(1, 13):
            self.assertIn(f"IND-K{k:02d}", body)
        self.assertIn("get_indicator_context", {t["name"] for t in TOOL_DEFS})


class TestTrainingPipeline(unittest.TestCase):
    """Synthetic export (FakeMT5) -> replay -> composer -> FIT/TUNE/CAL/POLICY/HOLDOUT -> artefacts in fixture_runs, parity,
    never activatable. Proves the code path only."""
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        sys.modules.pop("MetaTrader5", None)
        self.td.close()

    def test_fixture_pipeline(self):
        from masterquo.mt5.fake import FakeMT5
        sys.modules["MetaTrader5"] = FakeMT5()
        from masterquo.forecast.export import export_candles
        ds = Path(self.td.dir) / "ds"
        self.assertEqual(export_candles(1, str(ds), "AUTO", ("M1", "M5", "M15", "M30", "H1"), "training", "XAUUSD", "XAUUSD-"), 0)
        from masterquo.db.database import Database
        from masterquo.extind import trainer
        rep = trainer.train("XAUUSD", ds, commission=0.5, db=Database(), log=lambda m: None)
        self.assertEqual(rep["role"], "fixture_only")
        self.assertIn("fixture_runs", rep["plan"] and str(next(iter(json.loads((trainer.root("XAUUSD") / "registry.json").read_text())["runs"].values()))["run_dir"]))
        self.assertEqual(rep["variants"]["BASE+PAL02M"]["status"], "BLOCKED_IDENTITY_REQUIRED")
        self.assertIn(rep["variants"].get("BASE+IQ_GOLD_GANN", {}).get("status", "BLOCKED_NO_ARCHIVE"), ("BLOCKED_NO_ARCHIVE",))
        self.assertEqual(rep["edge_status"] if rep["status"] == "EVALUATED" else "NO_VALIDATED_EDGE", "NO_VALIDATED_EDGE")
        if rep["status"] == "EVALUATED":
            rid = rep["run_id"]
            rd = Path(json.loads((trainer.root("XAUUSD") / "registry.json").read_text())["runs"][rid]["run_dir"])
            man = json.loads((rd / "model_BASE+SAR.json").read_text())
            self.assertEqual(man["parity"]["status"], "OK")
            with self.assertRaises(ValueError):
                trainer.activate("XAUUSD", rid, "BASE+SAR")                       # fixture never activatable
            m = trainer.load_artifact(rd, "BASE+SAR")
            self.assertEqual(m.predict({}, "BTC")["status"], "ABSTAIN")
        else:
            self.assertEqual(rep["status"], "INSUFFICIENT_DATA")


class TestProtocolUnits(unittest.TestCase):
    """Protocol on a generated table (code path of FIT/TUNE/CAL/POLICY/HOLDOUT, purge, parity, abstain) - fixture only."""
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_split_purge_and_variant(self):
        import numpy as np
        from masterquo.extind import trainer
        from masterquo.scalp.strategy import SETUP_FEATURES
        rng = np.random.default_rng(5)
        t0 = datetime(2026, 1, 5, tzinfo=UTC)
        rows = []
        for k in range(400):
            t = t0 + timedelta(hours=3 * k)
            base = {f: float(rng.normal()) for f in SETUP_FEATURES}
            y = int(rng.random() < 1 / (1 + math.exp(-1.5 * base["er10"])))
            rows.append({"side": "BUY" if k % 2 else "SELL", "decision_time": t.isoformat(), "exit_time": (t + timedelta(minutes=20)).isoformat(),
                         "price": 100.0, "atr_m5": 1.0, "base": base, "y": y, "net_r": 1.0 if y else -1.0, "ext": {}})
        sp = trainer.split(rows)
        self.assertEqual(sum(len(v) for v in sp.values()) <= 400, True)
        order = [max(parse_t(rows[i]["exit_time"]) for i in sp["FIT"])] if len(sp["FIT"]) else []
        self.assertLess(order[0], min(parse_t(rows[i]["decision_time"]) for i in sp["TUNE"]))          # purge: FIT labels close before TUNE
        data = {"rows": rows, "bars": {"M5": [], "M15": []}, "symbol": "X", "dataset_id": "fx", "data_kind": "SYNTHETIC_TEST", "profile_id": "p"}
        r = trainer.run_variant(data, ("BASE",), sp)
        self.assertEqual(r["status"], "EVALUATED")
        self.assertLess(r["holdout"]["log_loss"], r["holdout"]["baseline_log_loss"])                   # a real signal in the fixture is found
        self.assertEqual(trainer.run_variant(data, ("BASE", "SAR"), sp)["status"], "BLOCKED_NO_ARCHIVE")     # no bars -> SAR missing, no fake zeros
        rd = Path(self.td.dir) / "run"
        rd.mkdir()
        trainer._save_artifact(rd, "XAUUSD", r, data, {"role": "fixture_only"})
        man = json.loads((rd / "model_BASE.json").read_text())
        self.assertEqual(man["parity"]["status"], "OK")
        m = trainer.load_artifact(rd, "BASE")
        self.assertEqual(m.predict({"decision_time": t0, "side": "BUY", "price": 1, "atr_m5": 1, "base": rows[0]["base"], "bars": {}, "ext": {}}, "BTC")["status"], "ABSTAIN")
        ok = m.predict({"decision_time": t0, "side": "BUY", "price": 1, "atr_m5": 1, "base": rows[0]["base"], "bars": {}, "ext": {}}, "XAUUSD")
        self.assertEqual(ok["status"], "READY_INFERENCE")
        (rd / "model_BASE.pkl").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            trainer.load_artifact(rd, "BASE")


def parse_t(s):
    return datetime.fromisoformat(s)


if __name__ == "__main__":
    unittest.main()
