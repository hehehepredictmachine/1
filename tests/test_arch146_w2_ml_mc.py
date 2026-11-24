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


if __name__ == "__main__":
    unittest.main()
