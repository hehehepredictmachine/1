"""1.46 arch, fix-all group "ml_training": D6 (one champion-promotion policy for the bot's ML job and the offline ML training) and D7
(TEST_INSTALACJI / --no-activate: ML, Monte Carlo and master models never activate anything).

D6: the bot's training job (ml/service.py _handle_result) registered every result with promotion allowed - a model trained on APPROX labels
(backfill OHLC, ml.use_backfill_approx / include_approx) or on the terminal simulator could become the champion that drives the ML gate in
ASSIST; ml/offline.py already refused that. Both paths now call training/promotion.ml_champion_policy.
D7: the profile TEST_INSTALACJI ("modele NIGDY nie są aktywowane") ran `training ml-offline`, `montecarlo validate` and `mm train` without
any flag - each step promoted / activated its artifact (ML champion, active Monte Carlo calibrator, SHADOW pointer of the master models).
Offline, synthetic or mocked data only; nothing here touches MT5, orders or execution."""
from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
from _env import TempData


# ============================================================================= helpers
def _fake_result(td: Path, snapshot: str):
    """Result dict shaped like trainer.run(); both models pass the default promotion rules."""
    from masterquo.config import MLConfig
    test = {"n": 400, "pos": 200, "neg": 200, "brier": 0.20, "brier_gain": 0.05, "brier_gain_se": 0.005, "ece": 0.02, "log_loss": 0.6, "pr_auc": 0.6}
    models = {}
    for fam, b in (("DECISION_TREE", 0.21), ("XGBOOST", 0.20)):
        mid = f"{fam[:2]}-T-{b}"
        models[fam] = {"model_id": mid, "path": str(td / "models" / mid), "train": {}, "threshold": 0.5, "calibration": "ISOTONIC",
                       "test": dict(test, brier=b), "raw_test_brier": b, "policy": {"avg_r": 0.3, "max_dd_r": 1.0, "trades": 50},
                       "policy_bootstrap": {}, "by_strategy": {}, "by_direction": {}, "by_session": {}, "by_regime": {}}
    return {"status": "DONE", "snapshot": snapshot, "validation": {"windows": {"test": ["2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z"]},
                                                                   "test_sample_ids": []},
            "baselines": {"base_rate": {"brier": 0.25}, "no_ml_policy": {"avg_r": 0.1, "max_dd_r": 1.0}}, "models": models,
            "feature_schema_version": "MQ-FEAT-1.2.0"}, MLConfig().promotion.model_dump()


class _Bridge:
    account_key = "T:1"

    def __init__(self, synthetic: bool):
        self.synthetic = synthetic
        self.symbol_info = {"point": 0.01, "trade_contract_size": 100.0, "spread": 12}
        self.clock = SimpleNamespace(offset=0)
        self._lock = threading.RLock()
        self.deals = []

    def account_status(self):
        return {"server": "T", "login": 1, "trade_mode": "DEMO"}

    def quote_status(self):
        return {"bid": 2000.0, "ask": 2000.1, "spread": 0.1, "age_seconds": 1.0}

    def bars(self, tf, include_forming=True):
        return []


class _Proc:
    returncode = None

    def poll(self):
        return None

    def kill(self):
        self.returncode = -9

    terminate = kill

    def wait(self, timeout=None):
        return 0


# ============================================================================= D6 policy function
class TestPromotionPolicyFunction(unittest.TestCase):
    def test_truth_table(self):
        from masterquo.training.promotion import ml_champion_policy as P
        self.assertEqual((P(approx=False, synthetic=False)["allow_promotion"], P(approx=False, synthetic=False)["role"]),
                         (True, "ELIGIBLE_FOR_CHAMPION"))
        for kw, role, event in (({"approx": True, "synthetic": False}, "RESEARCH_APPROX", "NOT_PROMOTED_APPROX"),
                                ({"approx": False, "synthetic": True}, "FIXTURE_ONLY", "NOT_PROMOTED_SYNTHETIC"),
                                ({"approx": True, "synthetic": True}, "FIXTURE_ONLY", "NOT_PROMOTED_SYNTHETIC"),
                                ({"approx": False, "synthetic": False, "activate": False}, "ELIGIBLE_NOT_ACTIVATED", "NOT_PROMOTED_NO_ACTIVATE"),
                                ({"approx": None, "synthetic": False}, "PROVENANCE_UNKNOWN", "NOT_PROMOTED_PROVENANCE_UNKNOWN"),
                                ({"approx": False, "synthetic": None}, "PROVENANCE_UNKNOWN", "NOT_PROMOTED_PROVENANCE_UNKNOWN")):
            with self.subTest(**kw):
                p = P(**kw)
                self.assertEqual((p["allow_promotion"], p["role"], p["event"]), (False, role, event))
                self.assertTrue(p["reason"])

    def test_registry_uses_policy_event_and_reason(self):
        """A blocked passing model is RESEARCH_APPROX (never champion, never a shadow-scored CHALLENGER) and the event names the real cause."""
        from masterquo.db.database import Database
        from masterquo.ml.registry import Registry
        from masterquo.training.promotion import ml_champion_policy
        td = TempData()
        try:
            root = Path(td.dir)
            db = Database(root / "reg.sqlite")
            try:
                reg = Registry(db, root / "models")
                res, prom = _fake_result(root, str(root / "none.jsonl.gz"))
                with mock.patch.object(Registry, "promote") as promote:
                    reg.register(res, "SNAP", prom, policy=ml_champion_policy(approx=False, synthetic=True))
                promote.assert_not_called()
                st = {r["status"] for r in db.query("SELECT status FROM ml_models")}
                self.assertEqual(st, {"RESEARCH_APPROX"})
                ev = [e for e in reg.events() if e["kind"].startswith("NOT_PROMOTED")]
                self.assertEqual({e["kind"] for e in ev}, {"NOT_PROMOTED_SYNTHETIC"})
                self.assertIn("syntetyczne", json.loads(ev[0]["detail_json"])["reason"])
                prom_json = json.loads(db.one("SELECT promotion_json FROM ml_models LIMIT 1")["promotion_json"])
                self.assertEqual(prom_json["not_promoted"]["role"], "FIXTURE_ONLY")
            finally:
                db.close()
        finally:
            td.close()


# ============================================================================= D6 bot job (ml/service.py)
class TestMLBotPromotionPolicy(unittest.TestCase):
    """The bot's own training job applies the same rule as ml/offline.py: APPROX labels / synthetic samples -> never champion."""

    def setUp(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.events import AppLog, EventBus
        self.td = TempData()
        self.cfg = ConfigStore()
        self.cfg.update({"ml": {"min_block_samples": 15, "min_block_per_class": 3}})
        self.db = Database()
        self.bus = EventBus()
        self.log = AppLog(self.db, self.bus)

    def tearDown(self):
        self.db.close()
        self.td.close()

    def _samples(self, n: int, *, synthetic: bool, quality: str, prefix: str = "S"):
        for i in range(n):
            t = f"2026-01-{1 + i // 40:02d}T{(i % 40) // 2:02d}:{(i % 2) * 30:02d}:00Z"
            self.db.execute("""INSERT INTO ml_samples(sample_id, setup_id, setup_version, group_id, event_id, symbol, feed_id, strategy_id,
                               strategy_version, direction, timeframe, asof_utc, feature_schema_version, features_json, entry_json, cost_model_version,
                               label_policy_version, source, quality, status, label, outcome_r, label_end_utc, label_known_utc, synthetic, created_at,
                               updated_at) VALUES (?,?,1,?,?,'XAUUSD-','T','S01','1','LONG','M15',?,'MQ-FEAT-1.2.0','{}','{}','c','l','TEST',?,'LABELED',
                               ?,?,?,?,?,?,?)""",
                            (f"{prefix}{i}:1", f"{prefix}{i}", f"{prefix}{i}", f"E{prefix}{i}", t, quality, i % 2, 1.0 if i % 2 else -1.0, t, t,
                             1 if synthetic else 0, t, t))

    def _run_job(self, *, synthetic: bool, include_approx: bool | None = None):
        from masterquo.ml.registry import Registry
        from masterquo.ml.service import MLService
        ml = MLService(self.cfg, self.db, _Bridge(synthetic), self.bus, self.log, root=Path(self.td.dir) / "ml", spawn=lambda f: _Proc())
        st = ml.start_training("TEST", force=True, include_approx=include_approx)
        self.assertTrue(st["started"], st)
        res, _ = _fake_result(Path(self.td.dir), ml._job["snapshot"])
        with mock.patch.object(Registry, "promote") as promote:
            ml._handle_result(ml._job, res)
        job = self.db.one("SELECT status, detail_json FROM ml_jobs WHERE job_id=?", (st["job_id"],))
        self.assertEqual(job["status"], "DONE", job)
        statuses = {r["status"] for r in self.db.query("SELECT status FROM ml_models")}
        return promote, statuses, json.loads(job["detail_json"])

    def test_synthetic_job_never_promotes(self):
        self._samples(80, synthetic=True, quality="HIGH")
        promote, statuses, det = self._run_job(synthetic=True)
        promote.assert_not_called()                               # HEAD: promote(<XGB>, PASSED_RULES_FIRST_CHAMPION)
        self.assertEqual(statuses, {"RESEARCH_APPROX"})
        self.assertEqual(det["promotion_policy"]["role"], "FIXTURE_ONLY")

    def test_approx_labels_never_promote(self):
        self._samples(60, synthetic=False, quality="HIGH")
        self._samples(30, synthetic=False, quality="APPROX", prefix="B")
        promote, statuses, det = self._run_job(synthetic=False, include_approx=True)
        promote.assert_not_called()
        self.assertEqual(statuses, {"RESEARCH_APPROX"})
        self.assertEqual(det["promotion_policy"]["role"], "RESEARCH_APPROX")

    def test_approx_flag_without_approx_rows_still_eligible(self):
        """ml.use_backfill_approx / include_approx with no APPROX row in the snapshot: HIGH labels only -> eligible as before."""
        self._samples(80, synthetic=False, quality="HIGH")
        promote, _statuses, det = self._run_job(synthetic=False, include_approx=True)
        promote.assert_called_once()
        self.assertEqual(det["promotion_policy"]["role"], "ELIGIBLE_FOR_CHAMPION")

    def test_real_high_labels_promote_as_before(self):
        self._samples(80, synthetic=False, quality="HIGH")
        promote, _statuses, _det = self._run_job(synthetic=False, include_approx=False)
        promote.assert_called_once()

    def test_old_job_file_uses_snapshot_manifest_and_unknown_blocks(self):
        from masterquo.ml.service import MLService
        pol = MLService._promotion_policy
        self.assertTrue(pol({"manifest": {"include_approx": False, "synthetic": False}})["allow_promotion"])
        self.assertFalse(pol({"manifest": {"include_approx": True, "synthetic": False}})["allow_promotion"])
        self.assertFalse(pol({"manifest": {"include_approx": False, "synthetic": True}})["allow_promotion"])
        self.assertEqual(pol({})["role"], "PROVENANCE_UNKNOWN")


# ============================================================================= D6 + D7 offline ML (ml/offline.py, training ml-offline)
class TestOfflinePolicyAndNoActivate(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _dataset(self, kind="REAL_USER_DATA") -> Path:
        ds = Path(self.td.dir) / "ds"
        ds.mkdir(exist_ok=True)
        meta = {"instrument": "XAUUSD", "symbol": "XAUUSD-", "file_prefix": "XAUUSD", "data_kind": kind, "tick_size": 0.01,
                "spec": {"point": 0.01, "trade_contract_size": 100.0}, "dataset_id": "T"}
        (ds / "source_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        for tf in ("M1", "M5", "M15", "H1", "H4", "D1"):
            (ds / f"XAUUSD_{tf}.csv").write_text("time_open_utc,open,high,low,close,tick_volume,spread_points\n"
                                                 "2026-03-02T08:00:00Z,1,2,0.5,1.5,10,12\n", encoding="utf-8")
        return ds

    def _train(self, **kw):
        from masterquo.ml import backfill, offline, trainer
        from masterquo.ml.dataset import SampleStore
        from masterquo.ml.registry import Registry
        res, _ = _fake_result(Path(self.td.dir), str(Path(self.td.dir) / "none.jsonl.gz"))
        with mock.patch.object(backfill, "run", return_value={"created": 0}), \
                mock.patch.object(SampleStore, "counts", return_value={"labeled": 10_000, "by_status": {}}), \
                mock.patch.object(trainer, "run", return_value=res), mock.patch.object(Registry, "promote") as promote:
            out = offline.train("XAUUSD", self._dataset(), commission=0.5, log=lambda m: None, **kw)
        return out, promote

    def test_real_data_promotes_by_default(self):
        out, promote = self._train(include_approx=False)
        promote.assert_called_once()
        self.assertEqual(out["role"], "ELIGIBLE_FOR_CHAMPION")

    def test_no_activate_keeps_champion(self):
        out, promote = self._train(include_approx=False, activate=False)
        promote.assert_not_called()
        self.assertEqual(out["role"], "ELIGIBLE_NOT_ACTIVATED")
        self.assertFalse(out["activate"])


if __name__ == "__main__":
    unittest.main()
