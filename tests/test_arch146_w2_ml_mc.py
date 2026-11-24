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


if __name__ == "__main__":
    unittest.main()
