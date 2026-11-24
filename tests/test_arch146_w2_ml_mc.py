"""1.46 arch, fala 2, grupa "ml_mc": legacy ML (Decision Tree / XGBoost, ml/), Scalp ML (ml_scalp) and Monte Carlo (montecarlo/).

I0789  registry: an impossible comparison with the current champion (exception, no test ids, empty test set) promoted the candidate
       without beating the champion - now CHAMPION_COMPARISON_UNAVAILABLE = not promoted, the champion stays.
I0326  (NIE_NAPRAWIONY, S0: nowe wejście) the ASSIST rank bonus stays as it is; the prediction contract only states WHERE the features
       came from (feature_source SAMPLE / ASOF_NOW) - the train/serve gap is visible, no ranking changes.
I0330  ml.mode=OFF (legacy DT/XGB switch) no longer switches off the Scalp ML inference (its own selection decides; SHADOW only).
I0337  one Scalp ML prediction per (sample, model hash) - a re-evaluated candidate (MT5 reconnect) is not stored / published again.
I0331  scalp_status: live quality of the Scalp ML models from the labelled live samples (Brier, log loss, ECE, SHADOW filter net_R).
I0681  Monte Carlo runtime: no guessed point 0.01 - spread in points without a known point is unknown (SELL NOT_VERIFIED).
I0687  Monte Carlo validation: no guessed point 0.01 for a dataset without spec.point / tick_size (BLOCKED_DATA / DATASET_POINT_UNKNOWN).
I0027  docstrings / labels of the feature schemas match the constants.
I0048  ML labels: one cost function for the offline backfill and the bot's collector (slippage, commission conversion), cost model
       MQ-COST-1.2.0; samples of the old offline cost basis are never mixed into a snapshot.
I0061  offline ML: the snapshot is the run's own dataset (feed + time window), its composition is reported, backfill duplicates
       of one market event across feeds are dropped.
Offline, synthetic or generated data only; nothing here touches MT5, orders or execution."""
from __future__ import annotations

import json
import math
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData


def _fake_result(td: Path, snapshot: str, test_ids=None):
    """Result dict shaped like trainer.run(); both models pass the default promotion rules."""
    from masterquo.config import MLConfig
    test = {"n": 400, "pos": 200, "neg": 200, "brier": 0.20, "brier_gain": 0.05, "brier_gain_se": 0.005, "ece": 0.02, "log_loss": 0.6, "pr_auc": 0.6}
    models = {}
    for fam, b in (("DECISION_TREE", 0.21), ("XGBOOST", 0.20)):
        mid = f"{fam[:2]}-T-{b}"
        models[fam] = {"model_id": mid, "path": str(td / "models" / mid), "train": {}, "threshold": 0.5, "calibration": "ISOTONIC",
                       "test": dict(test, brier=b), "raw_test_brier": b, "policy": {"avg_r": 0.3, "max_dd_r": 1.0, "trades": 50},
                       "policy_bootstrap": {}, "by_strategy": {}, "by_direction": {}, "by_session": {}, "by_regime": {}}
    val = {"windows": {"test": ["2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z"]}}
    if test_ids is not None:
        val["test_sample_ids"] = test_ids
    return {"status": "DONE", "snapshot": snapshot, "validation": val,
            "baselines": {"base_rate": {"brier": 0.25}, "no_ml_policy": {"avg_r": 0.1, "max_dd_r": 1.0}}, "models": models,
            "feature_schema_version": "MQ-FEAT-1.3.0"}, MLConfig().promotion.model_dump()


# ============================================================================= I0789 registry: comparison unavailable = no promotion
class TestRegistryNoPromotionWithoutComparison(unittest.TestCase):
    def setUp(self):
        from masterquo.db.database import Database
        self.td = TempData()
        self.root = Path(self.td.dir)
        self.db = Database(self.root / "reg.sqlite")

    def tearDown(self):
        self.db.close()
        self.td.close()

    def _register_with_champion(self, result, prom):
        from masterquo.ml.registry import Registry
        reg = Registry(self.db, self.root / "models")
        with mock.patch.object(Registry, "reload"), mock.patch.object(Registry, "promote") as promote:
            reg.champion, reg.champion_id = object(), "CHAMP-OLD"           # a loaded champion (comparison needed)
            dec = reg.register(result, "SNAP", prom)
        return reg, dec, promote

    def test_missing_test_ids_keep_champion(self):
        import gzip
        snap = self.root / "snap.jsonl.gz"
        with gzip.open(snap, "wt", encoding="utf-8") as fh:            # a readable snapshot - only the test ids are missing
            fh.write(json.dumps({"sample_id": "S1:1", "features_json": "{}", "label": 1}) + "\n")
        res, prom = _fake_result(self.root, str(snap), test_ids=None)
        reg, dec, promote = self._register_with_champion(res, prom)
        promote.assert_not_called()                                    # HEAD: promote(XGB, PASSED_RULES_AND_BEAT_CHAMPION)
        best = dec["XG-T-0.2"]
        self.assertFalse(best["passed"])
        self.assertIn("CHAMPION_COMPARISON_UNAVAILABLE:NO_TEST_SAMPLE_IDS", best["reasons"])
        st = {r["model_id"]: r["status"] for r in self.db.query("SELECT model_id, status FROM ml_models")}
        self.assertEqual(st["XG-T-0.2"], "REJECTED")
        self.assertEqual(st["DE-T-0.21"], "CHALLENGER")                 # the other passing model stays shadow-scored, as before
        self.assertIn("CHAMPION_COMPARISON_UNAVAILABLE", {e["kind"] for e in reg.events(20)})

    def test_comparison_exception_is_logged_and_blocks(self):
        res, prom = _fake_result(self.root, str(self.root / "missing.jsonl.gz"), test_ids=["S1:1"])   # snapshot file missing -> exception
        with self.assertLogs("masterquo.ml", level="ERROR"):
            _reg, dec, promote = self._register_with_champion(res, prom)
        promote.assert_not_called()
        self.assertTrue(any(r.startswith("CHAMPION_COMPARISON_UNAVAILABLE:") for r in dec["XG-T-0.2"]["reasons"]))

    def test_first_champion_and_better_candidate_unchanged(self):
        from masterquo.ml.registry import Registry
        res, prom = _fake_result(self.root, str(self.root / "none.jsonl.gz"), test_ids=[])
        reg = Registry(self.db, self.root / "models")
        with mock.patch.object(Registry, "promote") as promote:          # no champion: nothing to compare -> first champion as before
            reg.register(res, "SNAP", prom)
        promote.assert_called_once()
        res2, _ = _fake_result(self.root, str(self.root / "none.jsonl.gz"), test_ids=[])
        for m in res2["models"].values():
            m["model_id"] += "-2"
        with mock.patch.object(Registry, "_champion_brier_on", return_value=0.30):
            _reg, dec2, promote2 = self._register_with_champion(res2, prom)
        promote2.assert_called_once()                                  # a candidate that beats the champion is promoted as before
        self.assertTrue(dec2["XG-T-0.2-2"]["passed"])



# ============================================================================= Scalp ML (ml/service.py on_scalp_candidate / scalp_status)
class _Bus:
    def __init__(self):
        self.ev = []

    def publish(self, k, v):
        self.ev.append((k, v))


class _StubScalpBundle:
    """Stands for a selected Scalp ML bundle (ml/scalp_task.ScalpBundle.predict contract)."""

    def __init__(self, model_hash="MH1", p=0.7):
        self.model_hash, self.p, self.calls = model_hash, p, 0

    def predict(self, feats, *, instrument, profile_hash, side):
        self.calls += 1
        return {"status": "READY_INFERENCE", "task_id": "T", "model_hash": self.model_hash, "raw_margin": 0.5, "calibrated_probability": self.p,
                "expected_net_r": 0.2, "calibration_status": "FITTED_ON_CALIBRATION", "policy": {"p_min": 0.6, "ev_min": 0.0},
                "proposed_filter": True, "role": "OBSERVE"}


def _scalp_plan(setup_id="SET-1", side="BUY"):
    from masterquo.scalp.strategy import NET_FEATURES
    return {"setup_id": setup_id, "direction": side, "decision_ts": 1767600000, "decision_time": "2026-01-05T08:00:00+00:00", "sl": 99.0,
            "tp1": 101.0, "tp2": 102.0, "entry_mode": "MARKET", "net_features": {k: 0.0 for k in NET_FEATURES}}


class _ScalpBase(unittest.TestCase):
    def setUp(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.ml.service import MLService
        self.td = TempData()
        self.cfg = ConfigStore()
        self.db = Database()
        self.bus = _Bus()
        self.ml = MLService(self.cfg, self.db, None, self.bus, None)

    def tearDown(self):
        self.db.close()
        self.td.close()

    def _call(self, plan, bundle, epoch=1):
        from masterquo.ml import scalp_task as stk
        with mock.patch.object(stk, "selected_bundle", return_value=(bundle, {"role": "OBSERVE", "model_hash": bundle.model_hash, "run_id": "R1"})):
            return self.ml.on_scalp_candidate(plan, instrument="XAUUSD", profile_hash="h", session_epoch=epoch, costs={}, entry_mode="MARKET")


class TestScalpMLNotCoupledToLegacyMode(_ScalpBase):
    """I0330: ml.mode is the switch of the legacy DT/XGB pipeline (MLConfig); Scalp ML has its own selection (OBSERVE/SHADOW_GATE)."""

    def test_ml_off_does_not_disable_scalp_inference(self):
        self.cfg.update({"ml": {"mode": "OFF"}})
        out = self._call(_scalp_plan(), _StubScalpBundle())
        self.assertEqual(out["status"], "READY_INFERENCE")              # HEAD: ML_OFF (no inference, no prediction row)
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM ml_scalp_predictions")["n"], 1)
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM ml_scalp_samples")["n"], 1)

    def test_no_selected_model_is_still_no_model(self):
        from masterquo.ml import scalp_task as stk
        self.cfg.update({"ml": {"mode": "OFF"}})
        with mock.patch.object(stk, "selected_bundle", return_value=(None, None)):
            out = self.ml.on_scalp_candidate(_scalp_plan(), instrument="XAUUSD", profile_hash="h", session_epoch=1, costs={}, entry_mode="MARKET")
        self.assertEqual(out["status"], "NO_MODEL")
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM ml_scalp_predictions")["n"], 0)

    def test_status_names_the_switch(self):
        st = self.ml.scalp_status("XAUUSD")
        self.assertIn("inference_switch", st)
        self.assertIn("selected", st["inference_switch"])


class TestScalpPredictionOncePerSampleAndModel(_ScalpBase):
    """I0337: a candidate re-evaluated after an MT5 reconnect (new ScalpMachine, deterministic setup_id) kept one sample (INSERT OR IGNORE)
    but got a new prediction row (new prediction_id) and a new bus message every time."""

    def test_prediction_once_per_sample_and_model(self):
        b = _StubScalpBundle()
        outs = [self._call(_scalp_plan(), b, epoch=e) for e in (1, 2, 2)]
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM ml_scalp_predictions")["n"], 1)     # HEAD: 3
        self.assertEqual(len([e for e in self.bus.ev if e[0] == "ml_scalp"]), 1)                     # HEAD: 3
        self.assertEqual({o["prediction_id"] for o in outs}, {outs[0]["prediction_id"]})
        self.assertTrue(outs[1].get("duplicate_of_stored_prediction"))
        self.assertEqual(outs[1]["calibrated_probability"], outs[0]["calibrated_probability"])
        self.assertEqual(outs[1]["status"], "READY_INFERENCE")
        self.assertEqual(b.calls, 1)

    def test_another_model_or_side_is_a_new_prediction(self):
        self._call(_scalp_plan(), _StubScalpBundle("MH1"))
        self._call(_scalp_plan(), _StubScalpBundle("MH2"))
        self._call(_scalp_plan(side="SELL"), _StubScalpBundle("MH1"))
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM ml_scalp_predictions")["n"], 3)


class TestScalpLiveMetrics(_ScalpBase):
    """I0331: labelled live samples + predictions -> live quality per (side, model hash) in scalp_status (monitoring only)."""

    def _labelled(self, ys, ps, nets=None, filt=None, model_hash="MH1", side="BUY"):
        nets = nets or [1.0 if y else -1.0 for y in ys]
        for k, (y, p) in enumerate(zip(ys, ps)):
            sid = f"S{k}:{side}"
            self.db.execute("""INSERT INTO ml_scalp_samples(sample_id, instrument, profile_hash, setup_id, side, signal_time, decision_time, session_epoch,
                               feature_schema, features, plan, snapshot_hash, costs, status, created_at, net_r, y) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (sid, "XAUUSD", "h", f"S{k}", side, "2026-01-05T08:00:00Z", "2026-01-05T08:00:00Z", "1", "F", "{}", "{}", "x", "{}",
                             "LABELED", "2026-01-05T08:00:00Z", nets[k], y))
            self.db.execute("""INSERT INTO ml_scalp_predictions(prediction_id, sample_id, model_hash, role, instrument, side, snapshot_hash, session_epoch,
                               as_of, computed_at, expires_at, status, raw_margin, p, expected_net_r, proposed_filter, detail)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (f"P{k}{model_hash}", sid, model_hash, "OBSERVE", "XAUUSD", side, "x", "1", "2026-01-05T08:00:00Z", "2026-01-05T08:00:01Z",
                             "2026-01-05T08:02:00Z", "READY_INFERENCE", 0.0, p, 0.1, None if filt is None else int(filt[k]), "{}"))

    def test_status_reports_live_brier(self):
        self._labelled([1, 0, 1, 0], [0.8, 0.3, 0.6, 0.4], nets=[1.0, -1.0, 0.5, -0.5], filt=[1, 0, 1, 1])
        st = self.ml.scalp_status("XAUUSD")
        m = st["live_metrics"]["BUY"]["MH1"]                              # HEAD: KeyError 'live_metrics'
        self.assertEqual(m["n"], 4)
        self.assertAlmostEqual(m["brier"], 0.1125, places=9)
        self.assertAlmostEqual(m["mean_p"], 0.525, places=9)
        self.assertAlmostEqual(m["base_rate"], 0.5, places=9)
        ll = -(math.log(0.8) + math.log(0.7) + math.log(0.6) + math.log(0.6)) / 4
        self.assertAlmostEqual(m["log_loss"], ll, places=9)
        self.assertIsNone(m["ece"])                                       # n < 100: no calibration error from 4 samples
        self.assertEqual(m["shadow_filter"]["take"]["n"], 3)
        self.assertAlmostEqual(m["shadow_filter"]["take"]["mean_net_r"], (1.0 + 0.5 - 0.5) / 3, places=9)
        self.assertEqual(m["shadow_filter"]["skip"]["n"], 1)

    def test_status_for_another_instrument_reads_only_the_db(self):
        """GET /api/v1/ml/scalp for a non-active instrument calls MLService.scalp_status(SimpleNamespace(db=db), inst)."""
        from types import SimpleNamespace

        from masterquo.ml.service import MLService
        self._labelled([1, 0], [0.9, 0.2])
        st = MLService.scalp_status(SimpleNamespace(db=self.db), "XAUUSD")
        self.assertEqual(st["live_metrics"]["BUY"]["MH1"]["n"], 2)

    def test_duplicates_and_unlabelled_are_not_counted(self):
        self._labelled([1, 0], [0.9, 0.2])
        self.db.execute("""INSERT INTO ml_scalp_predictions(prediction_id, sample_id, model_hash, role, instrument, side, snapshot_hash, session_epoch,
                           as_of, computed_at, expires_at, status, raw_margin, p, expected_net_r, proposed_filter, detail)
                           VALUES ('DUP','S0:BUY','MH1','OBSERVE','XAUUSD','BUY','x','2','2026-01-05T08:00:00Z','2026-01-05T09:00:00Z',
                           '2026-01-05T09:02:00Z','READY_INFERENCE',0.0,0.1,0.0,NULL,'{}')""")
        self.db.execute("UPDATE ml_scalp_samples SET status='PENDING' WHERE sample_id='S1:BUY'")
        m = self.ml.scalp_status("XAUUSD")["live_metrics"]["BUY"]["MH1"]
        self.assertEqual(m["n"], 1)
        self.assertAlmostEqual(m["brier"], (0.9 - 1) ** 2, places=9)       # the FIRST prediction of S0 (0.9), not the re-evaluation (0.1)



# ============================================================================= Monte Carlo: no guessed point (I0681 runtime, I0687 validation)
def _mc_bars(n=600, spread=20):
    from datetime import datetime

    import numpy as np
    r = np.random.default_rng(5)
    t0 = datetime(2026, 9, 1, tzinfo=UTC).timestamp()
    out, c = [], 2400.0
    for i in range(n):
        o = c
        c = o + r.normal(0, 0.3)
        out.append({"open_utc": datetime.fromtimestamp(t0 + i * 60, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o,
                    "h": max(o, c) + abs(r.normal(0, 0.3)), "l": min(o, c) - abs(r.normal(0, 0.3)), "c": c, "spread": spread})
    return out


class _MCBridge:
    def __init__(self, b, symbol_info=None):
        self.b, self.symbol_info = b, symbol_info

    def bars(self, tf, limit=None, include_forming=True):
        return self.b

    def quote_status(self):
        return {"bid": self.b[-1]["c"], "ask": self.b[-1]["c"] + 0.2}


class TestMCNoGuessedPoint(unittest.TestCase):
    """I0681: MonteCarloService._ctx used point 0.01 when the bridge had no symbol_info (symbol not selected yet, bars already buffered)
    - the bars' spread in POINTS became a price spread with a guessed point (a broker with point 0.001: Ask 10x too far, SELL P wrong)."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _svc(self, info):
        from masterquo.config import ConfigStore
        from masterquo.montecarlo.service import MonteCarloService
        return MonteCarloService(ConfigStore(), _MCBridge(_mc_bars(), info), synthetic=True, n_paths=300)

    def test_unknown_point_sell_not_verified(self):
        from masterquo.montecarlo import engine as E
        svc = self._svc(None)
        try:
            last = _mc_bars()[-1]["c"]
            r = svc.compute([E.Plan("SELL", last, last + 3.0, [last - 2.5], 60), E.Plan("BUY", last + 0.2, last - 2.8, [last + 2.7], 60)])
            self.assertEqual(r["status"], "OK", r)
            self.assertIn("NO_SPREAD_DATA", r["data"]["flags"])                 # HEAD: no flag, spread = 20 x 0.01 (guessed)
            self.assertIn("POINT_UNKNOWN", r["data"]["flags"])
            self.assertEqual(r["plans"][0]["status"], "NOT_VERIFIED")           # HEAD: OK with a guessed spread 0.2
            self.assertEqual(r["plans"][1]["status"], "OK")                     # BUY closes on Bid: still evaluated
        finally:
            svc.stop()

    def test_known_point_and_tick_size_fallback(self):
        from masterquo.montecarlo import engine as E
        for info in ({"point": 0.01}, {"trade_tick_size": 0.01}):
            svc = self._svc(info)
            try:
                last = _mc_bars()[-1]["c"]
                r = svc.compute([E.Plan("SELL", last, last + 3.0, [last - 2.5], 60)])
                self.assertEqual(r["plans"][0]["status"], "OK", info)
                self.assertNotIn("NO_SPREAD_DATA", r["data"]["flags"])
            finally:
                svc.stop()

    def test_engine_history_point_none(self):
        import math as _m

        from masterquo.montecarlo import engine as E
        b = _mc_bars(10)
        as_of = E._ts(b[-1]["open_utc"]) + 60
        h = E.history(b, as_of, "M1", None)
        self.assertTrue(all(_m.isnan(x) for x in h.spread))
        h2 = E.history([dict(x, spread_price=0.15) for x in b], as_of, "M1", None)      # a price spread needs no point
        self.assertTrue(all(abs(x - 0.15) < 1e-12 for x in h2.spread))
        self.assertAlmostEqual(float(E.history(b, as_of, "M1", 0.001).spread[0]), 0.02)

    def test_calibrator_match_without_point(self):
        from masterquo.montecarlo import engine as E
        cal = {"events": [{"side": "BUY", "tp": 2.5, "sl": 3.0}], "horizon_bars": 60}
        plan = E.Plan("BUY", 100.0, 97.0, [102.5], 60)
        self.assertTrue(E._calibrator_event_match(cal, plan, 102.5, 60, None))


class TestMonteCarloPointUnknown(unittest.TestCase):
    """I0687: validate.load_dataset / validate used point 0.01 when the export metadata had neither spec.point nor tick_size."""

    def setUp(self):
        self.td = TempData()
        self.ds = Path(self.td.dir) / "ds"
        self.ds.mkdir()

    def tearDown(self):
        self.td.close()

    def _write(self, meta):
        (self.ds / "source_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        rows = ["time_open_utc,open,high,low,close,tick_volume,spread_points"]
        for b in _mc_bars(50):
            rows.append(f"{b['open_utc']},{b['o']},{b['h']},{b['l']},{b['c']},10,20")
        (self.ds / "XAUUSD_M1.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def _usable(self):
        from masterquo.forecast import export
        return mock.patch.object(export, "dataset_state", return_value={"usable": True, "state": "COMPLETE"})

    def test_load_dataset_refuses_unknown_point(self):
        from masterquo.montecarlo import validate as V
        self._write({"instrument": "XAUUSD", "file_prefix": "XAUUSD", "data_kind": "REAL_USER_DATA", "spec": {}})
        with self._usable(), self.assertRaises(ValueError) as cm:
            V.load_dataset(self.ds)                                            # HEAD: spread_price = 20 x 0.01
        self.assertIn("DATASET_POINT_UNKNOWN", str(cm.exception))

    def test_validate_reports_blocked_data(self):
        from masterquo.montecarlo import validate as V
        self._write({"instrument": "XAUUSD", "file_prefix": "XAUUSD", "data_kind": "REAL_USER_DATA", "spec": {}, "dataset_id": "D1"})
        with self._usable():
            rep = V.validate(self.ds, log=lambda m: None)
        self.assertEqual(rep["status"], "BLOCKED_DATA")
        self.assertIn("point", rep["reason"])
        self.assertEqual(rep["dataset_id"], "D1")
        saved = V.save("XAUUSD", rep)                                          # recorded for research, never the active calibrator
        self.assertFalse(saved["activated"] or saved["eligible"])
        self.assertIsNone(V.active_calibrator("XAUUSD"))

    def test_point_order_spec_point_tick_size(self):
        from masterquo.montecarlo import validate as V
        self.assertEqual(V._point({"spec": {"point": 0.001, "trade_tick_size": 0.01}, "tick_size": 0.1}), 0.001)
        self.assertEqual(V._point({"spec": {"trade_tick_size": 0.01}, "tick_size": 0.1}), 0.01)
        self.assertEqual(V._point({"spec": {}, "tick_size": 0.1}), 0.1)
        self.assertIsNone(V._point({"spec": {}}))
        self.assertIsNone(V._point({}))
        self._write({"instrument": "XAUUSD", "file_prefix": "XAUUSD", "data_kind": "REAL_USER_DATA", "spec": {"point": 0.001}})
        with self._usable():
            rows, _meta = V.load_dataset(self.ds)
        self.assertAlmostEqual(rows[0]["spread_price"], 0.02)



# ============================================================================= I0027 docstrings / labels of the feature schemas
class TestFeatureDocstringsMatchConstants(unittest.TestCase):
    def test_ml_and_zone_feature_docs_name_the_current_schema(self):
        from masterquo.ml import features as mf
        from masterquo.zones import features as zf
        self.assertIn(mf.FEATURE_SCHEMA_VERSION, mf.__doc__)
        self.assertIn("FEATURE_SCHEMA_VERSION", mf.__doc__)
        self.assertIn("ml.features.FEATURE_SCHEMA_VERSION", zf.__doc__)        # HEAD: "(MQ-FEAT-1.1.0+)" only

    def test_metamodel_keeps_the_feat1_prefix_contract(self):
        """The MetaModel label keeps the FEAT-1 prefix that load() checks (the rows are FEAT-2 = FEAT-1 superset) - documented, unchanged."""
        import inspect

        from masterquo.quant import features as F
        from masterquo.quant import metamodel as M
        self.assertTrue(F.schema(["a"]).startswith(F.VERSION))
        src = inspect.getsource(M)
        self.assertIn("startswith(F.VERSION)", src)
        self.assertIn("F.build2", src)                                         # HEAD: the label / builder mismatch was undocumented



# ============================================================================= I0326 (NIE_NAPRAWIONY, S0) - feature provenance only
class _StubChampion:
    family, meta = "XGBOOST", {"trained_at": "T", "threshold": 0.5, "base_rate": 0.5}

    def __init__(self):
        from types import SimpleNamespace

        import numpy as np
        self.np = np
        self.prep = SimpleNamespace(numeric=[], cats={})
        self.calib = SimpleNamespace(kind="ISOTONIC", apply=lambda a: a * 0 + 0.9)

    def adapt(self, rows):
        return rows

    def raw(self, rows):
        return self.np.array([0.9] * len(rows))


class TestPredictionFeatureSource(unittest.TestCase):
    def setUp(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.ml.service import MLService
        self.td = TempData()
        self.cfg = ConfigStore()
        self.db = Database()
        self.ml = MLService(self.cfg, self.db, None, _Bus(), None, root=Path(self.td.dir) / "ml")
        self.ml.registry.champion, self.ml.registry.champion_id = _StubChampion(), "CH-1"

    def tearDown(self):
        self.db.close()
        self.td.close()

    def test_sample_vs_asof_now_and_rank_unchanged(self):
        from masterquo.ml import features as fe
        self.db.execute("""INSERT INTO ml_samples(sample_id, setup_id, setup_version, group_id, symbol, feed_id, strategy_id, strategy_version, direction,
                           timeframe, asof_utc, feature_schema_version, features_json, entry_json, cost_model_version, label_policy_version, source,
                           quality, status, synthetic, created_at, updated_at) VALUES ('C:1','C',1,'C','XAUUSD-','T','S01','1','LONG','M15',
                           '2026-01-05T08:00:00Z','MQ-FEAT-1.3.0','{"M15_rsi": 50}','{}','c','l','LIVE','HIGH','PENDING',0,'t','t')""")
        conf = {"setup_id": "C", "version": 1, "stage": "CONFIRMED", "record": {"strategy_id": "S01"}}
        early = {"setup_id": "E", "version": 1, "stage": "EARLY", "record": {"strategy_id": "S01"}}
        self.cfg.update({"ml": {"mode": "ASSIST"}})
        with mock.patch.object(fe, "compute", return_value={"M15_rsi": 50.0}):
            pc, pe = self.ml.predict(conf, object()), self.ml.predict(early, object())
            self.assertEqual(pc["feature_source"], "SAMPLE")                 # HEAD: no such key
            self.assertEqual(pe["feature_source"], "ASOF_NOW")
            # the ASSIST rank bonus is NOT changed (S0: a ranking change can move the AUTO selection to another executable setup)
            self.assertEqual(self.ml.rank_adjust(early, object()), self.ml.rank_adjust(conf, object()))
            self.assertEqual(self.ml.rank_adjust(early, object()), 40.0)



# ============================================================================= I0048 one label-cost function (offline backfill = bot collector)
def _insert_sample(db, sid, *, setup_id=None, feed_id="T", source="LIVE", quality="HIGH", asof="2026-03-02T08:00:00Z", cost_ver=None, label=1,
                   synthetic=0, status="LABELED"):
    from masterquo.ml import labels as lb
    setup_id = setup_id or sid.rsplit(":", 1)[0]
    db.execute("""INSERT INTO ml_samples(sample_id, setup_id, setup_version, group_id, event_id, symbol, feed_id, strategy_id, strategy_version,
                  direction, timeframe, asof_utc, feature_schema_version, features_json, entry_json, cost_model_version, label_policy_version, source,
                  quality, status, label, outcome_r, label_end_utc, label_known_utc, synthetic, created_at, updated_at)
                  VALUES (?,?,1,?,?,'XAUUSD-',?,'S01','1','LONG','M15',?,'MQ-FEAT-1.3.0','{}','{}',?,?,?,?,?,?,?,?,?,?,?,?)""",
               (sid, setup_id, setup_id, "E" + setup_id, feed_id, asof, cost_ver or lb.COST_MODEL_VERSION, lb.LABEL_POLICY_VERSION, source, quality,
                status, label, 1.0 if label else -1.0, asof, "2026-01-01T00:00:00Z", synthetic, asof, asof))


class _CostBridge:
    synthetic = False
    account_key = "T:1"

    def __init__(self):
        import threading
        from types import SimpleNamespace
        self.symbol_info = {"point": 0.01, "trade_contract_size": 100.0, "trade_tick_size": 0.01, "trade_tick_value": 1.0}
        self.clock = SimpleNamespace(offset=0)
        self._lock = threading.RLock()
        self.deals = []

    def account_status(self):
        return {"server": "T", "login": 1}

    def quote_status(self):
        return {"bid": 2000.0, "ask": 2000.1, "spread": 0.1}

    def calc_profit(self, side, vol, p0, p1):
        return (p1 - p0) * 100.0 * vol                                       # account currency = USD (quote currency)

    def bars(self, tf, include_forming=True):
        return []


class TestMLLabelCostParity(unittest.TestCase):
    """I0048: the offline backfill (ml/offline.cost_of: slippage 0, commission / contract size) and the bot's collector (MLService._cost:
    slippage_stress_points x point, commission through the broker calculator) labelled the same setups with different costs in the same
    sample database."""

    def setUp(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        self.td = TempData()
        self.cfg = ConfigStore()
        self.cfg.update({"costs": {"commission_mode": "CONFIGURED", "commission_per_lot_per_side": 0.5}})
        self.db = Database()

    def tearDown(self):
        self.db.close()
        self.td.close()

    def _costs(self):
        from masterquo.ml import offline
        from masterquo.ml.service import MLService
        meta = {"spec": {"point": 0.01, "trade_tick_size": 0.01, "trade_tick_value": 1.0, "trade_contract_size": 100.0}, "tick_size": 0.01,
                "_point": 0.01, "costs": {"commission_per_lot_side": 0.5, "source": "META"}}
        off = offline.cost_of(meta, None)
        bot = MLService(self.cfg, self.db, _CostBridge(), _Bus(), None, root=Path(self.td.dir) / "ml")._cost()
        return off, bot

    def test_offline_and_bot_costs_are_equal(self):
        off, bot = self._costs()
        self.assertAlmostEqual(bot["slippage"], 0.20)
        self.assertAlmostEqual(off["slippage"], bot["slippage"])                    # HEAD: offline 0.0 vs bot 0.20
        self.assertAlmostEqual(off["commission"], bot["commission"])                # 0.5 / 100 both (tick value / tick size = calc_profit)
        self.assertEqual(off["cost_model_version"], bot["cost_model_version"])
        self.assertEqual(off["cost_model_version"], "MQ-COST-1.2.0")

    def test_same_setup_same_net_r(self):
        from masterquo.ml import labels as lb
        off, bot = self._costs()
        t0 = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)
        rec = {"direction": "LONG", "stop_loss": 1995.0, "targets": [{"price": 2004.0, "weight": 1.0}], "timeframe": "M1",
               "exit_rules": {"time_exit_bars": 60}}
        bars = [{"open_utc": (t0 + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"), "o": 2000.0 + i, "h": 2001.0 + i, "l": 1999.5 + i,
                 "c": 2000.5 + i, "closed": True} for i in range(10)]
        out = []
        for c in (off, bot):
            spec = lb.make_spec(rec, t0.isoformat().replace("+00:00", "Z"), spread=0.1, slippage=c["slippage"], commission=c["commission"],
                                cost_flags=c["flags"])
            _st, res = lb.step(spec, lb.new_state(spec), bars, [], t0 + timedelta(hours=1))
            out.append(res["outcome_r"])
        self.assertEqual(out[0], out[1])                                             # HEAD: offline net_R higher (no slippage)

    def test_contract_size_fallback_is_flagged_like_the_bot(self):
        from masterquo.ml import offline
        meta = {"spec": {"point": 0.01, "trade_contract_size": 100.0}, "tick_size": 0.01, "_point": 0.01}
        c = offline.cost_of(meta, 0.5)
        self.assertAlmostEqual(c["commission"], 0.005)
        self.assertIn("PRICE_VALUE_FROM_CONTRACT_SIZE_ASSUMES_ACCOUNT_CCY_EQ_QUOTE_CCY", c["flags"])
        self.assertIn("COMMISSION_UNKNOWN", offline.cost_of({"spec": {"point": 0.01}, "_point": 0.01}, 0.5)["flags"])

    def test_legacy_offline_cost_basis_never_mixed(self):
        from masterquo.ml.dataset import SampleStore
        st = SampleStore(self.db)
        _insert_sample(self.db, "BF-OFFLINE_OLD-A:1", feed_id="BACKFILL:OFFLINE_OLD", source="BACKFILL_OFFLINE_OLD", quality="APPROX",
                       cost_ver="MQ-COST-1.1.0")
        _insert_sample(self.db, "BF-OFFLINE_NEW-B:1", feed_id="BACKFILL:OFFLINE_NEW", source="BACKFILL_OFFLINE_NEW", quality="APPROX")
        _insert_sample(self.db, "BF-MT5-C:1", feed_id="BACKFILL:MT5", source="BACKFILL_MT5", quality="APPROX", cost_ver="MQ-COST-1.1.0")
        _insert_sample(self.db, "L1:1", cost_ver="MQ-COST-1.1.0")
        ids = {r["sample_id"] for r in st.eligible(True, datetime(2030, 1, 1, tzinfo=UTC), False)}
        self.assertEqual(ids, {"BF-OFFLINE_NEW-B:1", "BF-MT5-C:1", "L1:1"})          # HEAD: the old offline basis mixed in
        cnt = st.counts(True, False)
        self.assertEqual(cnt["labeled"], 3)
        self.assertEqual(cnt["legacy_cost_basis_excluded"], 1)


# ============================================================================= I0061 offline snapshot = the run's own dataset
class TestOfflineSnapshotScope(unittest.TestCase):
    def setUp(self):
        from masterquo.db.database import Database
        self.td = TempData()
        self.db = Database()

    def tearDown(self):
        self.db.close()
        self.td.close()

    def _fill(self):
        for k, t in enumerate(("2026-03-02T08:00:00Z", "2026-03-03T08:00:00Z", "2026-03-04T08:00:00Z")):
            for feed in ("OFFLINE_A", "OFFLINE_B"):                               # overlapping exports: the same market events
                _insert_sample(self.db, f"BF-{feed}-X{k}:1", feed_id=f"BACKFILL:{feed}", source=f"BACKFILL_{feed}", quality="APPROX", asof=t)
        _insert_sample(self.db, "LIVE1:1", feed_id="MT5:srv:XAUUSD-", asof="2026-03-03T09:00:00Z")

    def test_snapshot_scoped_to_feed_and_window(self):
        from masterquo.ml.dataset import SampleStore, load_snapshot
        self._fill()
        st = SampleStore(self.db)
        snap = st.snapshot(Path(self.td.dir) / "snaps", include_approx=True, synthetic=False, feed_ids=["BACKFILL:OFFLINE_B"])
        rows = load_snapshot(snap["path"])
        self.assertEqual({r["sample_id"] for r in rows}, {"BF-OFFLINE_B-X0:1", "BF-OFFLINE_B-X1:1", "BF-OFFLINE_B-X2:1"})
        self.assertEqual(snap["composition"]["by_feed"], {"BACKFILL:OFFLINE_B": 3})
        self.assertEqual(snap["scope"]["feed_ids"], ["BACKFILL:OFFLINE_B"])
        win = st.snapshot(Path(self.td.dir) / "snaps", include_approx=True, synthetic=False, feed_ids=["BACKFILL:OFFLINE_B"],
                          since="2026-03-03T00:00:00Z", until="2026-03-03T23:59:59Z")
        self.assertEqual(win["rows"], 1)
        self.assertEqual(st.counts(True, False, feed_ids=["BACKFILL:OFFLINE_B"], since="2026-03-03T00:00:00Z")["labeled"], 2)

    def test_unscoped_snapshot_drops_cross_feed_duplicates_and_reports_composition(self):
        from masterquo.ml.dataset import SampleStore, load_snapshot
        self._fill()
        snap = SampleStore(self.db).snapshot(Path(self.td.dir) / "snaps", include_approx=True, synthetic=False)
        rows = load_snapshot(snap["path"])
        self.assertEqual(len(rows), 4)                                             # HEAD: 7 (every event twice + live)
        self.assertEqual(snap["composition"]["duplicates_dropped"], 3)
        self.assertEqual(snap["composition"]["by_quality"], {"APPROX": 3, "HIGH": 1})
        self.assertEqual(snap["composition"]["by_source"]["LIVE"], 1)
        hi = SampleStore(self.db).snapshot(Path(self.td.dir) / "snaps", include_approx=False, synthetic=False)
        self.assertEqual(hi["rows"], 1)                                            # HIGH-only snapshot (the bot's default) unchanged

    def test_offline_train_uses_only_its_dataset(self):
        from masterquo.ml import backfill, offline, trainer
        from masterquo.ml.dataset import SampleStore, load_snapshot
        from masterquo.ml.registry import Registry
        self._fill()
        ds = Path(self.td.dir) / "ds"
        ds.mkdir()
        meta = {"instrument": "XAUUSD", "symbol": "XAUUSD-", "file_prefix": "XAUUSD", "data_kind": "REAL_USER_DATA", "tick_size": 0.01,
                "spec": {"point": 0.01, "trade_contract_size": 100.0, "trade_tick_size": 0.01, "trade_tick_value": 1.0}, "dataset_id": "B"}
        (ds / "source_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        start = datetime(2026, 1, 20, tzinfo=UTC)
        for tf, step in (("M1", 60), ("M5", 300), ("M15", 900), ("H1", 3600), ("H4", 14400), ("D1", 86400)):
            lines = ["time_open_utc,open,high,low,close,tick_volume,spread_points"]
            t, end = start, datetime(2026, 3, 5, tzinfo=UTC)
            while t < end and len(lines) < 6000:
                lines.append(f"{t.isoformat().replace('+00:00', 'Z')},1,2,0.5,1.5,10,12")
                t += timedelta(seconds=step * (1 if tf != "M1" else 15))
            (ds / f"XAUUSD_{tf}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        seen = {}
        res, _ = _fake_result(Path(self.td.dir), "x", test_ids=[])

        def fake_run(snap_path, *a, **k):
            seen["rows"] = load_snapshot(snap_path)
            return dict(res, snapshot=snap_path)
        with mock.patch.object(backfill, "run", return_value={"created": 0}), \
                mock.patch.object(SampleStore, "counts", return_value={"labeled": 10_000, "by_status": {}}) as counts, \
                mock.patch.object(trainer, "run", side_effect=fake_run), mock.patch.object(Registry, "promote"):
            out = offline.train("XAUUSD", ds, commission=0.5, log=lambda m: None, days=180)
        self.assertEqual({r["feed_id"] for r in seen["rows"]}, {"BACKFILL:OFFLINE_B"})   # HEAD: every feed + the bot's live samples
        self.assertEqual(out["scope"]["feed_ids"], ["BACKFILL:OFFLINE_B"])
        self.assertEqual(out["snapshot"]["composition"]["by_feed"], {"BACKFILL:OFFLINE_B": 3})
        self.assertEqual(counts.call_args.kwargs.get("feed_ids"), ["BACKFILL:OFFLINE_B"])
        self.assertTrue(out["scope"]["since"].startswith("2026-02-19"))              # first M15 bar + 30 days of warm-up



class TestRunnerKeepsSnapshotScope(unittest.TestCase):
    """I0061 step 1: the training set of the offline ML step (scope + composition) is kept in the run's state.json."""

    def setUp(self):
        import os
        self.td = TempData()
        self._env = mock.patch.dict(os.environ, {"MQ_NO_BROWSER": "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.td.close()

    def test_scope_and_composition_in_state(self):
        import io

        from masterquo.training import core, runner
        plan, ts = runner.build_plan(instruments=["XAUUSD"], profile="PELNY_TRENING", symbols={"XAUUSD": "XAUUSD-"}, commissions={}, months=1,
                                     synthetic=False)
        run = core.Run.create(plan, ts)
        ds = Path(self.td.dir) / "ds" / run.run_id
        ds.mkdir(parents=True)
        (ds / "source_metadata.json").write_text(json.dumps({"dataset_id": "D1", "instrument": "XAUUSD", "costs": {}}), encoding="utf-8")
        run.set("XAUUSD:export", execution="UKONCZONE", dataset_dir=str(ds), data_kind="REAL_USER_DATA")
        run.set("XAUUSD:quality", execution="UKONCZONE", quality="NIE_DOTYCZY")
        comp = {"by_feed": {"BACKFILL:OFFLINE_D1": 900}, "by_source": {"BACKFILL_OFFLINE_D1": 900}, "by_quality": {"APPROX": 900},
                "duplicates_dropped": 0}
        res = {"status": "DONE", "counts": {"labeled": 900}, "role": "RESEARCH_APPROX", "champion": None, "costs": {},
               "models": {"DT-1": {"family": "DECISION_TREE", "passed_rules": True, "reasons": []}},
               "scope": {"feed_ids": ["BACKFILL:OFFLINE_D1"], "since": "2026-02-01T00:00:00Z", "until": "2026-03-01T00:00:00Z"},
               "snapshot": {"composition": comp}}

        def child(run_, tid, cmd, env, timeout, log):
            Path(cmd[cmd.index("--out") + 1]).write_text(json.dumps(res), encoding="utf-8")
            return 0, ""
        with mock.patch.object(core, "run_child", child), mock.patch.object(core, "ram_gate", lambda plan: (1.0, None)), \
                mock.patch("sys.stdout", io.StringIO()):
            runner.t_ml(run, "XAUUSD")
        r = run.task("XAUUSD:ml")["result"]
        self.assertEqual(r["snapshot_composition"], comp)                         # HEAD: KeyError (not kept)
        self.assertEqual(r["scope"]["feed_ids"], ["BACKFILL:OFFLINE_D1"])


if __name__ == "__main__":
    unittest.main()
