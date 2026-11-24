"""1.46 arch, fix-all group "ml_training": D6 (one champion-promotion policy for the bot's ML job and the offline ML training) and D7
(TEST_INSTALACJI / --no-activate: ML, Monte Carlo and master models never activate anything).

D6: the bot's training job (ml/service.py _handle_result) registered every result with promotion allowed - a model trained on APPROX labels
(backfill OHLC, ml.use_backfill_approx / include_approx) or on the terminal simulator could become the champion that drives the ML gate in
ASSIST; ml/offline.py already refused that. Both paths now call training/promotion.ml_champion_policy.
D7: the profile TEST_INSTALACJI ("modele NIGDY nie są aktywowane") ran `training ml-offline`, `montecarlo validate` and `mm train` without
any flag - each step promoted / activated its artifact (ML champion, active Monte Carlo calibrator, SHADOW pointer of the master models).
Offline, synthetic or mocked data only; nothing here touches MT5, orders or execution."""
from __future__ import annotations

import io
import json
import os
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

    def test_cli_flag_no_activate_and_alias(self):
        from masterquo.ml import offline
        from masterquo.training import cli
        for flag in ("--no-activate", "--no-promote"):
            with self.subTest(flag=flag), mock.patch.object(offline, "train", return_value={"status": "DONE"}) as tr, \
                    mock.patch("sys.stdout", io.StringIO()):
                rc = cli.main(["ml-offline", "--instrument", "XAUUSD", "--dataset", "D", "--out", str(Path(self.td.dir) / "o.json"), flag])
                self.assertEqual(rc, 0)
                self.assertIs(tr.call_args.kwargs["activate"], False)
        with mock.patch.object(offline, "train", return_value={"status": "DONE"}) as tr, mock.patch("sys.stdout", io.StringIO()):
            cli.main(["ml-offline", "--instrument", "XAUUSD", "--dataset", "D", "--out", str(Path(self.td.dir) / "o.json")])
        self.assertIs(tr.call_args.kwargs["activate"], True)                  # default unchanged (contract of the CLI)


# ============================================================================= D7 Monte Carlo
def _mc_rep():
    return {"status": "DONE", "data_kind": "REAL_USER_DATA", "verdict": "PRZEWAGA_NAD_BAZOWYM", "instrument": "XAUUSD", "chosen_variant": "IID",
            "calibrator": {"x": [0.0, 1.0], "y": [0.0, 1.0]}, "dataset_id": "D",
            "test": {"n": 100, "calibrated": {"brier": 0.20}, "base": {"brier": 0.25}, "ambiguous_share": 0.1},
            "brier_diff_calibrated_minus_base_ci95": [-0.08, -0.01]}


class TestMonteCarloNoActivate(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_save_without_activation_keeps_active(self):
        from masterquo.montecarlo import validate as V
        first = V.save("XAUUSD", _mc_rep())
        self.assertTrue(first["activated"])
        s = V.save("XAUUSD", dict(_mc_rep(), dataset_id="D2"), activate=False)        # another report (run id = time + report hash)
        self.assertEqual((s["activated"], s["eligible"]), (False, True))
        reg = json.loads((V.root("XAUUSD") / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(reg["active"], first["run_id"])                      # previous calibrator stays active
        self.assertEqual(reg["runs"][s["run_id"]]["activation"], "NOT_ACTIVATED_BY_PLAN")
        self.assertFalse((V.root("XAUUSD") / "runs" / s["run_id"] / "calibrator.json").exists())

    def test_cli_no_activate(self):
        from masterquo.montecarlo import cli
        from masterquo.montecarlo import validate as V
        with mock.patch.object(V, "validate", return_value=_mc_rep()), mock.patch("sys.stdout", io.StringIO()):
            rc = cli.main(["validate", "--dataset", "D", "--no-activate"])
        self.assertEqual(rc, 0)
        reg = json.loads((V.root("XAUUSD") / "registry.json").read_text(encoding="utf-8"))
        self.assertIsNone(reg["active"])
        with mock.patch.object(V, "validate", return_value=_mc_rep()), mock.patch("sys.stdout", io.StringIO()):
            cli.main(["validate", "--dataset", "D"])
        reg = json.loads((V.root("XAUUSD") / "registry.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(reg["active"])                                   # without the flag: as before


# ============================================================================= D7 master models
class TestMasterModelsNoActivate(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _ctx(self, activate: bool):
        import numpy as np  # noqa: F401
        snap = SimpleNamespace(snapshot_id="SNAP", data_kind="REAL_USER_DATA")
        return SimpleNamespace(inst="XAUUSD", synthetic=False, snap=snap, seed=1, profile="quick", activate=activate, promoted=[],
                               log=lambda m: None)

    def test_validated_artifact_does_not_move_pointer(self):
        import numpy as np
        from masterquo.mm import artifacts, jobs
        aid, st = jobs._save(self._ctx(False), "gpr_logret", {"w": np.zeros(3)}, {"model_type": "T"}, True)
        self.assertEqual(st, "VALIDATED_SHADOW")
        self.assertEqual(artifacts.load("XAUUSD", "gpr_logret", aid)[1]["status"], "VALIDATED_SHADOW")   # artifact kept for inspection
        self.assertEqual(artifacts.read_pointer("XAUUSD")["active"], {})       # HEAD: {'gpr_logret': aid}
        ctx = self._ctx(True)
        aid2, _ = jobs._save(ctx, "gpr_logret", {"w": np.zeros(3)}, {"model_type": "T"}, True)
        self.assertEqual(artifacts.read_pointer("XAUUSD")["active"], {"gpr_logret": aid2})
        self.assertEqual(ctx.promoted, ["gpr_logret"])

    def test_cli_and_orchestrator_flag(self):
        from masterquo.mm import cli, orchestrator
        with mock.patch.object(orchestrator, "run", return_value={"status": "FINISHED", "jobs": {}}) as run, mock.patch("sys.stdout", io.StringIO()):
            cli.main(["train", "--dataset", "D", "--instrument", "XAUUSD", "--out", "O", "--no-activate"])
        self.assertIs(run.call_args.kwargs["activate"], False)
        with mock.patch.object(orchestrator, "run", return_value={"status": "FINISHED", "jobs": {}}) as run, mock.patch("sys.stdout", io.StringIO()):
            cli.main(["train", "--dataset", "D", "--instrument", "XAUUSD", "--out", "O"])
        self.assertIs(run.call_args.kwargs["activate"], True)

    def test_orchestrator_report_records_activation(self):
        from masterquo.mm import orchestrator
        rep = orchestrator.run(str(Path(self.td.dir) / "missing"), "XAUUSD", str(Path(self.td.dir) / "out"), "quick", activate=False)
        self.assertEqual(rep["status"], "BLOCKED_DATA_QUALITY")               # no dataset: blocked before any job
        self.assertIs(rep["activate"], False)


# ============================================================================= D7 runner (TEST_INSTALACJI)
class TestRunnerTestInstalacjiNeverActivates(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.data = Path(self.td.dir)
        self._env = mock.patch.dict(os.environ, {"MQ_NO_BROWSER": "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.td.close()

    def _run(self, profile: str):
        from masterquo.training import core, runner
        plan, ts = runner.build_plan(instruments=["XAUUSD"], profile=profile, symbols={"XAUUSD": "XAUUSD-"}, commissions={}, months=1,
                                     synthetic=False)
        run = core.Run.create(plan, ts)
        ds = self.data / "ds" / run.run_id
        ds.mkdir(parents=True)
        (ds / "source_metadata.json").write_text(json.dumps({"dataset_id": "D1", "instrument": "XAUUSD", "costs": {}}), encoding="utf-8")
        run.set("XAUUSD:export", execution="UKONCZONE", dataset_dir=str(ds), data_kind="REAL_USER_DATA")
        run.set("XAUUSD:quality", execution="UKONCZONE", quality="NIE_DOTYCZY")
        return run

    def _cmds(self, profile: str) -> tuple[dict, object]:
        from masterquo.training import core, runner
        run = self._run(profile)
        cmds = {}
        mm_rep = {"run_id": "MMRUN-1", "jobs": {"gpr": {"status": "SUCCEEDED", "training_executed": True, "validation_passed": True}}}

        def child(run_, tid, cmd, env, timeout, log):
            cmds[tid.split(":")[1]] = cmd
            if "--out" in cmd:
                out = Path(cmd[cmd.index("--out") + 1])
                if tid.endswith("master_models"):
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "REPORT.json").write_text(json.dumps(mm_rep), encoding="utf-8")
                else:
                    out.write_text(json.dumps({"status": "INSUFFICIENT_DATA", "reason": "test"}), encoding="utf-8")
            return 0, ""
        with mock.patch.object(core, "run_child", child), mock.patch.object(core, "ram_gate", lambda plan: (1.0, None)), \
                mock.patch("sys.stdout", io.StringIO()):
            runner.t_ml(run, "XAUUSD")
            runner.t_monte_carlo(run, "XAUUSD")
            runner.t_master_models(run, "XAUUSD")
        return cmds, run

    def test_test_instalacji_passes_no_activate_to_every_step(self):
        cmds, run = self._cmds("TEST_INSTALACJI")
        self.assertEqual(set(cmds), {"ml", "monte_carlo", "master_models"})
        for k, cmd in cmds.items():
            with self.subTest(step=k):
                self.assertIn("--no-activate", cmd)                           # HEAD: no flag -> the step activated its artifact
        self.assertEqual(run.task("XAUUSD:master_models")["integration"], "ZAPISANY_DO_BADAN")   # HEAD: AKTYWNY_W_REJESTRZE

    def test_full_training_unchanged(self):
        cmds, run = self._cmds("PELNY_TRENING")
        for k, cmd in cmds.items():
            with self.subTest(step=k):
                self.assertNotIn("--no-activate", cmd)
        self.assertEqual(run.task("XAUUSD:master_models")["integration"], "AKTYWNY_W_REJESTRZE")


if __name__ == "__main__":
    unittest.main()
