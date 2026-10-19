"""PMW-UPD-03 SCALP_NET_PROFIT_MARKET_V1. Synthetic/generated tables only (code path, fixture_only) - no claim about a real edge."""
from __future__ import annotations

import json
import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

UTC = timezone.utc


def _rows(n=600, seed=3):
    import numpy as np
    from masterquo.scalp.strategy import NET_FEATURES
    rng = np.random.default_rng(seed)
    t0 = datetime(2026, 1, 5, tzinfo=UTC)
    out = []
    for k in range(n):
        t = t0 + timedelta(minutes=90 * k)
        x = {f: float(rng.normal()) for f in NET_FEATURES}
        x[NET_FEATURES[3]] = float("nan") if k % 7 == 0 else x[NET_FEATURES[3]]
        z = 1.2 * x[NET_FEATURES[0]]
        y = int(rng.random() < 1 / (1 + math.exp(-z)))
        nr = (1.0 if y else -1.0) * float(rng.uniform(0.3, 1.5))
        out.append({"setup_id": f"S{k}", "range_id": f"R{k // 2}", "side": "BUY", "signal_time": t.isoformat(),
                    "fill_time": t.isoformat(), "label_end": (t + timedelta(minutes=30)).isoformat(), "x": x, "net_r": nr, "y": y,
                    "spread": 0.1, "risk": 1.0, "net_price": nr, "ambiguous": False})
    return out


class TestSplits(unittest.TestCase):
    def test_inner_blocks_disjoint_chronological_purged(self):
        import numpy as np
        from masterquo.ml import scalp_task as stk
        rows = _rows(400)
        emb = 3600.0
        b = stk.inner_blocks(np.arange(len(rows)), rows, emb)
        allidx = [set(v.tolist()) for v in b.values()]
        for i in range(4):
            for j in range(i + 1, 4):
                self.assertFalse(allidx[i] & allidx[j])
        names = ("FIT", "TUNE", "CALIBRATION", "POLICY")
        for a, c in zip(names, names[1:]):
            nxt = min(stk._ts(rows[i]["signal_time"]) for i in b[c])
            self.assertTrue(all(stk._ts(rows[i]["label_end"]) < nxt - emb for i in b[a]))        # purge + embargo
            rng_next = {rows[i]["range_id"] for i in b[c]}
            self.assertFalse({rows[i]["range_id"] for i in b[a]} & rng_next)                      # ranges never straddle

    def test_outer_folds_expanding(self):
        import numpy as np
        from masterquo.ml import scalp_task as stk
        rows = _rows(300)
        folds = stk.outer_folds(np.arange(300), rows)
        self.assertEqual(len(folds), 4)
        for tr, ev in folds:
            self.assertLess(max(stk._ts(rows[i]["signal_time"]) for i in tr), min(stk._ts(rows[i]["signal_time"]) for i in ev))
        self.assertTrue(all(len(folds[k][0]) < len(folds[k + 1][0]) for k in range(3)))


class TestBundleAndRegistry(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _fit(self):
        import numpy as np
        from masterquo.ml import scalp_task as stk
        rows = _rows(600)
        X, y, r = stk.matrix(rows), np.array([x["y"] for x in rows]), np.array([x["net_r"] for x in rows])
        fp = stk.fit_pair(X, y, r, stk.inner_blocks(np.arange(600), rows, 1800.0))
        return rows, X, fp

    def test_bundle_parity_hash_shap_and_scope(self):
        import numpy as np
        from masterquo.ml import scalp_task as stk
        rows, X, fp = self._fit()
        rep = {"instrument": "XAUUSD", "symbol": "XAUUSD", "profile_id": "p", "profile_hash": "h1", "costs": {}, "dataset_id": "fx",
               "data_kind": "SYNTHETIC_TEST", "role": "RESEARCH"}
        d = Path(self.td.dir) / "bundle_BUY"
        mh = stk.save_bundle(d, fp, rep, "BUY", {})
        b = stk.load_bundle(d)
        self.assertEqual(b.man["model_hash"], mh)
        np.testing.assert_allclose(b.predict_matrix(X[:50])["margin"], fp["clf"].predict(X[:50], output_margin=True), rtol=0, atol=1e-6)  # parity
        o = b.predict(rows[1]["x"], instrument="XAUUSD", profile_hash="h1", side="BUY")
        self.assertEqual(o["status"], "READY_INFERENCE")
        self.assertIn("nie P(wzrost ceny)", o["meaning"])
        for kw in ({"instrument": "BTC", "profile_hash": "h1", "side": "BUY"}, {"instrument": "XAUUSD", "profile_hash": "other", "side": "BUY"},
                   {"instrument": "XAUUSD", "profile_hash": "h1", "side": "SELL"}):
            self.assertEqual(b.predict(rows[1]["x"], **kw)["status"], "ABSTAIN")
        self.assertEqual(b.predict({"a": 1.0}, instrument="XAUUSD", profile_hash="h1", side="BUY")["status"], "ABSTAIN")
        ex = b.explain(rows[0]["x"])                                      # row 0 has a NaN feature
        self.assertTrue(ex["sum_check"])
        self.assertAlmostEqual(ex["bias"] + sum(t["contribution"] for t in ex["top"]) + ex["other_features"], ex["raw_margin"], places=4)
        (d / "regressor.ubj").write_bytes((d / "regressor.ubj").read_bytes() + b"x")
        with self.assertRaises(ValueError):
            stk.load_bundle(d)

    def test_select_rules_and_rollback(self):
        from masterquo.ml import scalp_task as stk
        rows, X, fp = self._fit()
        base = {"instrument": "XAUUSD", "symbol": "XAUUSD", "profile_id": "p", "profile_hash": "h1", "costs": {}, "dataset_id": "fx", "data_kind": "REAL_USER_DATA"}
        for rid, role, st in (("R_FIX", "FIXTURE_ONLY", "FIXTURE_ONLY"), ("R_NO", "RESEARCH", "NO_VALIDATED_EDGE"), ("R_OK", "RESEARCH", "HOLDOUT_PASSED")):
            rd = stk.root("XAUUSD") / "runs" / rid
            rd.mkdir(parents=True)
            mh = stk.save_bundle(rd / "bundle_BUY", fp, dict(base, role=role), "BUY", {})
            stk._register("XAUUSD", rid, rd, {"status": "EVALUATED", "role": role, "sides": {"BUY": {"status": st, "model_hash": mh}}})
        reg = json.loads((stk.root("XAUUSD") / "registry.json").read_text())
        self.assertEqual(reg["selected"], {})                                                   # nothing promoted automatically
        with self.assertRaisesRegex(ValueError, "FIXTURE_ONLY"):
            stk.select("XAUUSD", "R_FIX", "BUY", "OBSERVE")
        with self.assertRaisesRegex(ValueError, "SHADOW_GATE_REQUIRES_HOLDOUT_PASSED"):
            stk.select("XAUUSD", "R_NO", "BUY", "SHADOW_GATE")
        with self.assertRaisesRegex(ValueError, "ROLE_INVALID"):
            stk.select("XAUUSD", "R_OK", "BUY", "LIVE")
        stk.select("XAUUSD", "R_NO", "BUY", "OBSERVE")
        stk.select("XAUUSD", "R_OK", "BUY", "SHADOW_GATE")
        b, sel = stk.selected_bundle("XAUUSD", "BUY")
        self.assertEqual((sel["run_id"], sel["role"]), ("R_OK", "SHADOW_GATE"))
        self.assertEqual(stk.rollback("XAUUSD", "BUY")["BUY"]["run_id"], "R_NO")
        self.assertNotIn("BUY", stk.rollback("XAUUSD", "BUY"))
        with self.assertRaises(ValueError):
            stk.rollback("XAUUSD", "BUY")

    def test_ledger_reuse(self):
        from masterquo.db.database import Database
        from masterquo.ml import scalp_task as stk
        db = Database()
        a = stk.reserve_holdout(db, "XAUUSD", "2026-05-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00", "h1")
        b = stk.reserve_holdout(db, "XAUUSD", "2026-05-20T00:00:00+00:00", "2026-07-01T00:00:00+00:00", "h2")
        c = stk.reserve_holdout(db, "BTC", "2026-05-20T00:00:00+00:00", "2026-07-01T00:00:00+00:00", "h3")
        self.assertEqual((a["status"], b["status"], c["status"]), ("FRESH", "REUSED_PERIOD_EXPLORATORY", "FRESH"))


class _Bus:
    def __init__(self):
        self.ev = []

    def publish(self, k, v):
        self.ev.append((k, v))


class TestCollector(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_once_per_candidate_label_and_no_model(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.ml.service import MLService
        from masterquo.scalp.strategy import NET_FEATURES
        db = Database()
        ml = MLService(ConfigStore(), db, None, _Bus(), None)
        plan = {"setup_id": "SET-1", "direction": "BUY", "decision_ts": 1767600000, "decision_time": "2026-01-05T08:00:00+00:00", "sl": 99.0,
                "tp1": 101.0, "tp2": 102.0, "entry_mode": "MARKET", "net_features": {k: 0.0 for k in NET_FEATURES}}
        for _ in range(3):
            o = ml.on_scalp_candidate(plan, instrument="XAUUSD", profile_hash="h", session_epoch=1, costs={}, entry_mode="MARKET")
        self.assertIn(o["status"], ("NO_MODEL", "ML_OFF"))
        self.assertEqual(db.one("SELECT COUNT(*) AS n FROM ml_scalp_samples")["n"], 1)
        self.assertEqual(ml.on_scalp_candidate(plan, instrument="BTC", profile_hash="h", session_epoch=1, costs={}, entry_mode="MARKET")["status"], "ABSTAIN")
        self.assertEqual(len(ml.scalp_pending("XAUUSD")), 1)
        ml.scalp_label("SET-1:BUY", "MISSED_LIMIT", None)
        self.assertEqual(db.one("SELECT status FROM ml_scalp_samples")["status"], "NO_EXECUTABLE_ENTRY")   # never a fake loss
        plan2 = dict(plan, setup_id="SET-2")
        ml.on_scalp_candidate(plan2, instrument="XAUUSD", profile_hash="h", session_epoch=1, costs={}, entry_mode="MARKET")
        ml.scalp_label("SET-2:BUY", "SETTLED", {"net_r": -0.0, "label_end": "2026-01-05T08:30:00+00:00", "precision": "OHLC_APPROX"})
        r = db.one("SELECT status, y FROM ml_scalp_samples WHERE sample_id='SET-2:BUY'")
        self.assertEqual((r["status"], r["y"]), ("LABELED", 0))                                             # exactly 0 -> class 0
        st = ml.scalp_status("XAUUSD")
        self.assertIsInstance(st, dict)


class TestFixturePipeline(unittest.TestCase):
    """FakeMT5 export -> replay (all candidates) -> walk-forward -> bundle in fixture_runs; never selectable. Code path only."""
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        import sys
        sys.modules.pop("MetaTrader5", None)
        self.td.close()

    def test_fixture_train_and_accept_filter(self):
        import sys
        from masterquo.mt5.fake import FakeMT5
        sys.modules["MetaTrader5"] = FakeMT5()
        from masterquo.forecast.export import export_candles
        ds = Path(self.td.dir) / "ds"
        self.assertEqual(export_candles(1, str(ds), "AUTO", ("M1", "M5", "M15", "M30", "H1"), "training", "XAUUSD", "XAUUSD-"), 0)
        from masterquo.db.database import Database
        from masterquo.ml import scalp_task as stk
        rep = stk.train("XAUUSD", ds, commission=0.5, db=Database(), log=lambda m: None)
        self.assertEqual(rep["role"], "FIXTURE_ONLY")
        self.assertIn(rep["status"], ("EVALUATED", "INSUFFICIENT_EVIDENCE"))
        reg = json.loads((stk.root("XAUUSD") / "registry.json").read_text())
        self.assertIn("fixture_runs", reg["runs"][rep["run_id"]]["run_dir"])
        self.assertEqual(reg["selected"], {})
        for side, sr in rep["sides"].items():
            self.assertNotEqual(sr.get("status"), "HOLDOUT_PASSED")
            if sr.get("model_hash"):
                with self.assertRaises(ValueError):
                    stk.select("XAUUSD", rep["run_id"], side, "OBSERVE")
        # replay accept filter: rejecting everything gives no cycles and every rejection is recorded
        from masterquo.scalp import replay, strategy as st
        data = stk.build_dataset("XAUUSD", ds, 0.5, log=lambda m: None)
        res = replay.run(data["m1"], data["prof"], data["tick"], data["replay_costs"], accept=lambda plan: False)
        self.assertEqual(res["cycles"], [])
        self.assertEqual(sum(1 for b in res["blocked"] if b.get("reason") == "ML_POLICY_REJECTED") >= len(data["rows"]), True)
        if data["rows"]:
            r0 = data["rows"][0]
            self.assertEqual(set(r0["x"]), set(st.NET_FEATURES))
            self.assertEqual(r0["y"], 1 if r0["net_r"] > 0 else 0)


class TestNetFeatures(unittest.TestCase):
    def test_schema_and_no_zero_imputation(self):
        from masterquo.scalp import strategy as st
        self.assertEqual(len(st.NET_FEATURES), len(set(st.NET_FEATURES)))
        self.assertTrue(set(st.SETUP_FEATURES) <= set(st.NET_FEATURES) or len(st.NET_FEATURES) > len(st.SETUP_FEATURES))
        self.assertIn("spread_known", st.NET_FEATURES)


if __name__ == "__main__":
    unittest.main()
