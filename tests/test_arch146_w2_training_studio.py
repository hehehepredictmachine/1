"""Fala 2, grupa „training_studio” (trening: runner / Centrum Pepe / Studio / trainhub / rodziny / composition root).

I0131 (+I0067) jeden rejestr zadań treningowych (training/tasks.py), I0133 walidacja --tasks, I0134 jedno mapowanie profili,
I0073 sh_pack BTC = nie dotyczy (kod wyjścia 0), I0704 Studio nie oferuje sh_pack BTC, I0625 scalp_B aktywny tylko z modelem B,
I0646 TH_BASELINE bez fikcyjnej kalibracji, I0643 (+I0648/I0653/I0661/I0668/I0675) import Studio z metadanymi wersji,
I0010 jeden stan trainhub, I0101 (wariant bezpieczny) history.json Centrum, I0100 zatrzymanie procesów treningu przy STOP,
I0064 DatasetRef w manifestach, I0069 jeden budżet RAM procesów treningu.

Każdy test nie przechodzi na kodzie sprzed poprawki (HEAD 5c679ab) i przechodzi po niej; bez MT5 i bez sieci, osobny folder danych."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

import _env
from _env import TempData

PY = sys.executable


def _h(x) -> str:
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


class _Data(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.data = Path(self.td.dir)
        self._env = mock.patch.dict(os.environ, {"MQ_NO_BROWSER": "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.td.close()

    def plan_run(self, tasks=None, insts=("XAUUSD",), profile="PELNY_TRENING"):
        from masterquo.training import core, runner
        plan, ts = runner.build_plan(instruments=list(insts), profile=profile, symbols={i: f"{i}-" for i in insts}, commissions={},
                                     months=1, synthetic=False, tasks=tasks)
        return core.Run.create(plan, ts)


# ================================================================================================ I0131 (+I0067) rejestr zadań
# zamrożone kopie z HEAD 5c679ab (przed refaktorem): kolejność + skrót pełnej treści
FROZEN_TASK_IDS = ("export", "quality", "forecast", "scalp_A", "scalp_B", "scalp_C", "ml", "lab", "indicator_context", "ml_scalp", "neural_scalp",
                   "structure_intelligence", "flow_context", "context_indicators", "sh_models", "sh_pack", "monte_carlo", "master_models",
                   "activate", "bot")
FROZEN_TASKS_H = "35acc96e429e43ce"
FROZEN_PIPELINE_H = "8a7d1af6691808fe"
FROZEN_EXTRA_H = "54467f828311876f"
FROZEN_RUNNER_GROUPS_H = "3b326216aa5fa344"
FROZEN_RUNNER_GROUP_KEYS = ("forecast", "scalp_A", "ml", "lab", "indicator_context", "ml_scalp", "neural_scalp", "structure_intelligence",
                            "flow_context", "context_indicators", "sh_models", "sh_pack", "monte_carlo", "master_models")
FROZEN_REQUIREMENTS_H = "7edfb2447aedf71a"
# row order of check_dataset() in 1.46.0 (API data readiness, export report) - NOT the runner order (master_models before monte_carlo)
FROZEN_REQUIREMENTS_KEYS = ("forecast", "scalp", "ml", "lab", "indicator_context", "ml_scalp", "neural_scalp", "structure_intelligence",
                            "flow_context", "context_indicators", "sh_models", "sh_pack", "master_models", "monte_carlo")
FROZEN_TRAIN_ALL = (("forecast", "skip_candles"), ("scalp_A", "skip_candles"), ("ml", "skip_ml"), ("lab", "skip_lab"),
                    ("indicator_context", "skip_candles"), ("ml_scalp", "skip_ml"), ("neural_scalp", "skip_lab"),
                    ("structure_intelligence", "skip_lab"), ("flow_context", "skip_lab"), ("context_indicators", "skip_lab"))


class TestI0131TrainingTaskRegistry(unittest.TestCase):
    def test_lists_are_derived_from_one_registry(self):
        from masterquo.studio import registry as SR
        from masterquo.training import pepe_center as PC
        from masterquo.training import requirements as RQ
        from masterquo.training import runner as RN
        from masterquo.training import (
            tasks as TT,  # HEAD: ModuleNotFoundError (6 hand-written copies)
        )
        self.assertEqual(RN.TASKS, TT.runner_tasks())
        self.assertEqual(PC.PIPELINE, TT.center_pipeline())
        self.assertEqual(SR.RUNNER_GROUPS, TT.studio_runner_groups())
        self.assertEqual(RQ.REQUIREMENTS, TT.requirements())

    def test_contents_identical_to_head(self):
        from masterquo.studio import registry as SR
        from masterquo.training import pepe_center as PC
        from masterquo.training import requirements as RQ
        from masterquo.training import runner as RN
        self.assertEqual(tuple(k for k, _ in RN.TASKS), FROZEN_TASK_IDS)          # same order: activate second to last, bot last
        self.assertEqual(_h([list(t) for t in RN.TASKS]), FROZEN_TASKS_H)
        self.assertEqual(_h([list(t) for t in PC.PIPELINE]), FROZEN_PIPELINE_H)
        self.assertEqual(_h([list(t) for t in PC.EXTRA]), FROZEN_EXTRA_H)
        self.assertEqual(tuple(SR.RUNNER_GROUPS), FROZEN_RUNNER_GROUP_KEYS)
        self.assertEqual(_h({k: list(v) for k, v in SR.RUNNER_GROUPS.items()}), FROZEN_RUNNER_GROUPS_H)
        self.assertEqual(_h({k: {a: (list(b) if isinstance(b, tuple) else b) for a, b in v.items()} for k, v in RQ.REQUIREMENTS.items()}),
                         FROZEN_REQUIREMENTS_H)
        self.assertIn("scalp", RQ.REQUIREMENTS)                                   # readiness key unchanged (alias only on input)
        self.assertNotIn("scalp_A", RQ.REQUIREMENTS)
        self.assertEqual(set(RN.STEPS), {k for k, _ in RN.TASKS} - {"scalp_B", "scalp_C"})

    def test_train_all_set_unchanged_and_never_live_writers(self):
        from masterquo.training import tasks as TT
        self.assertEqual(TT.train_all_tasks(), [k for k, _ in FROZEN_TRAIN_ALL])
        for k, flag in FROZEN_TRAIN_ALL:
            self.assertNotIn(k, TT.train_all_tasks({flag: True}))
        for k in ("sh_models", "sh_pack", "monte_carlo", "master_models"):
            self.assertNotIn(k, TT.train_all_tasks())
        from masterquo import train_all as TA
        seen = []
        a = SimpleNamespace(instruments="XAUUSD", quick=True, skip_candles=False, skip_ml=True, skip_lab=False, months=None, commission=None,
                            commission_btc=None, ml_days=None, lab_bars=None, min_events=None, ml_no_approx=False, demo=False)
        with mock.patch("masterquo.training.cli.main", side_effect=lambda argv: seen.append(argv) or 0), mock.patch("sys.stdout", io.StringIO()):
            TA.train_all(a)
        tasks = seen[0][seen[0].index("--tasks") + 1].split(",")
        self.assertEqual(tasks, [k for k, f in FROZEN_TRAIN_ALL if f != "skip_ml"])
        a.skip_candles = a.skip_lab = True
        with mock.patch("masterquo.training.cli.main", side_effect=lambda argv: seen.append(argv) or 0), mock.patch("sys.stdout", io.StringIO()):
            TA.train_all(a)
        self.assertEqual(seen[1][seen[1].index("--tasks") + 1], "none")

    def test_readiness_row_order_identical_to_head(self):
        # recenzja: sort_keys w hashu nie widzi kolejności – po refaktorze wiersze szły w kolejności runnera (monte_carlo przed master_models)
        from masterquo.training import requirements as RQ
        self.assertEqual(tuple(RQ.REQUIREMENTS), FROZEN_REQUIREMENTS_KEYS)
        rows = RQ.check_dataset(Path(_env.ROOT / "tests"))["models"]
        self.assertEqual(tuple(r["kind"] for r in rows), FROZEN_REQUIREMENTS_KEYS)

    def test_readiness_alias_on_input_only(self):
        from masterquo.training import requirements as RQ
        d = Path(_env.ROOT / "tests")                                     # any folder: the export state is MISSING, only kinds are checked
        rows = RQ.check_dataset(d, kinds=["scalp_A"])["models"]
        self.assertEqual([r["kind"] for r in rows], ["scalp"])

    def test_registry_module_has_no_side_effects(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import masterquo.training.tasks; "
                "print(sorted(m for m in sys.modules if m.startswith('masterquo')))")
        r = subprocess.run([PY, "-c", code, str(_env.ROOT / "backend")], capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        # masterquo/__init__ imports only masterquo.version (a constant module)
        self.assertEqual(r.stdout.strip(), "['masterquo', 'masterquo.training', 'masterquo.training.tasks', 'masterquo.version']")


# ================================================================================================ I0133 walidacja --tasks
class TestI0133BuildPlanValidatesTasks(_Data):
    def test_typo_is_refused(self):
        with self.assertRaises(ValueError) as cm:                         # HEAD: plan with export + quality + activate + bot only
            self.plan_run(tasks=["sh_modelz"])
        self.assertIn("BAD_TASKS", str(cm.exception))
        self.assertIn("sh_modelz", str(cm.exception))

    def test_none_means_no_model_task(self):
        run = self.plan_run(tasks=["none"])
        self.assertEqual(run.state["plan"]["requested_tasks"], [])
        for t in run.state["tasks"]:
            if t["kind"] in ("export", "quality", "activate", "bot"):
                self.assertEqual(t["execution"], "NIE_URUCHOMIONE")
            else:
                self.assertEqual((t["execution"], t["detail"]), ("POMINIETE", "nie wybrano w planie"))

    def test_cli_returns_2_before_mt5(self):
        from masterquo.training import cli
        ns = cli.parser().parse_args(["run", "--instruments", "XAUUSD", "--profile", "TEST_INSTALACJI", "--tasks", "forecast,sh_modelz"])
        out = io.StringIO()
        with mock.patch.object(cli, "detect", side_effect=AssertionError("MT5 contacted")), mock.patch("sys.stdout", out), \
                mock.patch("masterquo.training.runner.execute", side_effect=AssertionError("run started")):
            rc = cli.cmd_run(ns)
        self.assertEqual(rc, 2)
        self.assertIn("sh_modelz", out.getvalue())

    def test_valid_names_unchanged(self):
        run = self.plan_run(tasks=["scalp_B"])
        self.assertEqual(run.state["plan"]["requested_tasks"], ["scalp_B", "scalp_A", "scalp_C"])     # A/B/C one unit, as before


# ================================================================================================ I0134 profile
class TestI0134ProfileMapping(unittest.TestCase):
    def test_one_mapping_module(self):
        from masterquo.training import core
        from masterquo.training import profiles as P  # HEAD: ModuleNotFoundError
        for sp in ("smoke", "research", "full"):
            self.assertIn(P.runner_profile_for_studio(sp), core.profiles())
        self.assertEqual(P.runner_profile_for_studio("smoke"), "TEST_INSTALACJI")
        self.assertEqual(P.runner_profile_for_studio("research"), "PELNY_TRENING")
        self.assertEqual(P.runner_profile_for_studio("full"), "PELNY_TRENING")
        for rp in core.profiles():
            self.assertIn(P.module_profile({"profile": rp, "synthetic": False}), ("quick", "standard"))
        self.assertEqual(P.module_profile({"profile": "TEST_INSTALACJI", "synthetic": False}), "quick")
        self.assertEqual(P.module_profile({"profile": "PELNY_TRENING", "synthetic": False}), "standard")
        self.assertEqual(P.module_profile({"profile": "PELNY_TRENING", "synthetic": True}), "quick")

    def test_no_hand_written_mapping_left(self):
        src = (_env.ROOT / "backend" / "masterquo" / "training" / "runner.py").read_text(encoding="utf-8")
        self.assertNotIn('"quick" if plan', src)                          # HEAD: 4 copies
        self.assertNotIn('plan["profile"] == "TEST_INSTALACJI"', src)     # HEAD: 3 more copies of the same rule
        st = (_env.ROOT / "backend" / "masterquo" / "studio" / "pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn('if ctx.profile == "smoke" else', st)


# ================================================================================================ I0073 sh_pack BTC – kod wyjścia
class TestI0073RunnerExitCodeNotApplicable(_Data):
    def _execute(self, run, fail_kind=None):
        from masterquo.training import core, report, runner

        def done(kind):
            def f(r, inst):
                if kind == fail_kind and inst == "BTC":
                    return runner._skip(r, f"{inst}:{kind}", "brak wybranego symbolu brokera dla BTC")
                for k in ((kind,) if kind != "scalp_A" else ("scalp_A", "scalp_B", "scalp_C")):
                    r.set(f"{inst}:{k}", execution="UKONCZONE")
            return f
        steps = {k: done(k) for k in runner.STEPS}
        fake_pack = steps["sh_pack"]
        steps["sh_pack"] = lambda r, inst: runner.t_sh_pack(r, inst) if inst == "BTC" else fake_pack(r, inst)   # the real BTC branch
        with mock.patch.dict(runner.STEPS, steps), mock.patch.object(core, "acquire_lock", lambda rid: None), \
                mock.patch.object(core, "release_lock", lambda rid: None), mock.patch.object(report, "write", lambda r: None), \
                mock.patch("sys.stdout", io.StringIO()):
            return runner.execute(run)

    def test_full_btc_run_exits_0(self):
        run = self.plan_run(insts=("XAUUSD", "BTC"))
        rc = self._execute(run)
        t = run.task("BTC:sh_pack")
        self.assertEqual(t["execution"], "POMINIETE")
        self.assertEqual(t["quality"], "NIE_DOTYCZY")
        self.assertTrue(t["detail"].startswith("nie dotyczy instrumentu"), t["detail"])
        self.assertEqual(rc, 0)                                           # HEAD: 4 ("część pominięta") for every full BTC run
        self.assertEqual(run.task("XAUUSD:sh_pack")["execution"], "UKONCZONE")

    def test_a_real_skip_still_exits_4(self):
        run = self.plan_run(insts=("XAUUSD", "BTC"))
        self.assertEqual(self._execute(run, fail_kind="ml"), 4)

    def test_exit_code_function(self):
        from masterquo.training import runner
        st = {"status": "FINISHED", "tasks": [{"kind": "sh_pack", "execution": "POMINIETE", "detail": "nie dotyczy instrumentu: x", "not_applicable": True},
                                               {"kind": "ml", "execution": "UKONCZONE"}]}
        self.assertEqual(runner.exit_code(st), 0)
        st["tasks"].append({"kind": "lab", "execution": "POMINIETE", "detail": "za mało RAM"})
        self.assertEqual(runner.exit_code(st), 4)
        st["tasks"].append({"kind": "forecast", "execution": "BLAD_TECHNICZNY"})
        self.assertEqual(runner.exit_code(st), 1)
        st["status"] = "CANCELLED"
        self.assertEqual(runner.exit_code(st), 3)


# ================================================================================================ I0704 Studio: sh_pack BTC
class TestI0704StudioShPackBtc(unittest.TestCase):
    def test_btc_pack_not_offered(self):
        from masterquo.studio import registry as SR
        ts = {(t["instrument"], t["task_id"]): t for t in SR.tasks() if t["adapter"] == "RUNNER_GROUP"}
        btc, xau = ts[("BTC", "sh_pack")], ts[("XAUUSD", "sh_pack")]
        self.assertNotEqual(btc["state"], "SUPPORTED")                    # HEAD: SUPPORTED (export, then BLOCKED_DEPENDENCY)
        self.assertTrue(btc["reason"])
        self.assertEqual(SR.operations(btc), [])
        self.assertEqual(xau["state"], "SUPPORTED")
        self.assertEqual(ts[("BTC", "sh_models")]["state"], "SUPPORTED")  # other runner groups unchanged
        # the task key does not depend on state / reason (queue entries of older versions keep matching)
        self.assertTrue(btc["task_key"].startswith("RUNNER:sh_pack:BTC:M1:HNone:"))


# ================================================================================================ I0625 scalp_B
class TestI0625ScalpBIntegration(_Data):
    def _activated(self, b: dict):
        from masterquo.training import runner
        run = self.plan_run()
        run.set("XAUUSD:scalp_A", execution="UKONCZONE", quality="ZWALIDOWANY_SHADOW", model_id="SR-1", integration="ZAPISANY_DO_BADAN")
        run.set("XAUUSD:scalp_B", execution="UKONCZONE", model_id="SR-1", **b)
        ok = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=ok), mock.patch("sys.stdout", io.StringIO()):
            runner.t_activate(run, "XAUUSD")
        return run

    def test_b_without_model_is_not_active(self):
        run = self._activated({"quality": "BRAK_PRZESLANEK", "detail": "INSUFFICIENT_DATA: cykle z cechami: dev 3", "integration": "ZAPISANY_DO_BADAN"})
        self.assertEqual(run.task("XAUUSD:scalp_A")["integration"], "AKTYWNY_W_REJESTRZE")
        self.assertNotEqual(run.task("XAUUSD:scalp_B")["integration"], "AKTYWNY_W_REJESTRZE")    # HEAD: AKTYWNY_W_REJESTRZE

    def test_b_with_model_is_active(self):
        for b in ({"quality": "ZWALIDOWANY_SHADOW", "detail": "FILTER_HELPS_IN_HOLDOUT: ", "integration": "ZAPISANY_DO_BADAN"},
                  {"quality": "ODRZUCONY", "detail": "x", "setup_model_saved": True, "integration": "ZAPISANY_DO_BADAN"}):
            with self.subTest(b=b):
                run = self._activated(b)
                self.assertEqual(run.task("XAUUSD:scalp_B")["integration"], "AKTYWNY_W_REJESTRZE")

    def test_scalp_step_records_whether_b_was_saved(self):
        import mq_instruments
        from masterquo.training import core, runner
        run = self.plan_run()
        ds = self.data / "ds"
        ds.mkdir()
        (ds / "source_metadata.json").write_text(json.dumps({"dataset_id": "D1", "instrument": "XAUUSD", "costs": {}}), encoding="utf-8")
        run.set("XAUUSD:export", execution="UKONCZONE", dataset_dir=str(ds), data_kind="REAL_USER_DATA")
        run.set("XAUUSD:quality", execution="UKONCZONE", quality="NIE_DOTYCZY")
        for sm, want in ((None, "NIEZAPISANY"), ({"file": "setup_model_LR.json", "threshold": 0.5}, "ZAPISANY_DO_BADAN")):
            reg = {"runs": {"R1": {"run_id": "R1", "run_dir": str(self.data / "r1"), "dataset_id": "D1", "created_at_utc": "2026-01-01T00:00:00Z",
                                   "task_a_status": "TRAINED_SHADOW", "horizon_status": {}, "costs": {"commission_per_lot_side": 7, "commission_source": "x"},
                                   "task_b_status": "INSUFFICIENT_DATA" if sm is None else "FILTER_HELPS_IN_HOLDOUT", "task_c_status": "INSUFFICIENT_DATA",
                                   "setup_model": sm}}}
            (mq_instruments.root("scalp", "XAUUSD") / "registry.json").write_text(json.dumps(reg), encoding="utf-8")
            with mock.patch.object(core, "ensure_candles", lambda r: ("py", None)), mock.patch.object(core, "run_child", lambda *a, **k: (0, "")):
                runner.t_scalp(run, "XAUUSD")
            with self.subTest(setup_model=sm):
                self.assertEqual(run.task("XAUUSD:scalp_B")["integration"], want)
                self.assertEqual(run.task("XAUUSD:scalp_B")["setup_model_saved"], sm is not None)


# ================================================================================================ I0646 kalibracja TH_BASELINE
class TestI0646BaselineCalibrationStatus(unittest.TestCase):
    def test_baseline_is_not_described_as_calibrated(self):
        from masterquo.trainhub.inference import TrainhubInference
        cfg = SimpleNamespace(get=lambda: SimpleNamespace(assets=SimpleNamespace(mappings={})))
        inf = TrainhubInference(cfg, None)
        p = inf._pred("XAUUSD", "TH_BASELINE_M5_H6", "v", {"model_id": "TH_BASELINE", "base_tf": "M5", "horizon": 6}, "DISABLED", "x")
        self.assertEqual(p["calibration"]["status"], "NOT_APPLICABLE")    # HEAD: CALIBRATED_DEV (T=1.0 never fitted)
        q = inf._pred("XAUUSD", "TH_LOGREG_M5_H6", "v", {"model_id": "TH_LOGREG", "base_tf": "M5", "horizon": 6}, "DISABLED", "x")
        self.assertEqual(q["calibration"]["status"], "CALIBRATED_DEV")
        r = inf._pred("XAUUSD", "TH_LOGREG_M5_H6", "v", None, "ERROR", "x")
        self.assertEqual(r["calibration"]["status"], "NOT_APPLICABLE")


# ================================================================================================ I0643 (+I0648/I0653/I0661/I0668/I0675) import Studio
KEY, VER = "TH_LOGREG_M5_H6", "20260101T000000Z-abcdef-123456"
WF = {"dev_skill_vs_baseline": 0.0123, "folds_beating_baseline": 3, "folds": [{"k": 1}]}


def _th_package(d: Path, data_kind: str = "SYNTHETIC") -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps({"model_id": "TH_LOGREG", "base_tf": "M5", "horizon": 6, "model_key": KEY, "version": VER}))
    (d / "metrics.json").write_text(json.dumps({"model_id": "TH_LOGREG", "holdout": {"log_loss": 1.0, "skill_vs_baseline": 0.01},
                                                "walk_forward": WF, "trading_eval_holdout": {"trades": 5}}))
    (d / "data_manifest.json").write_text(json.dumps({"instrument": "XAUUSD", "data_kind": data_kind}))
    (d / "package_manifest.json").write_text(json.dumps({"created_at": "2026-01-01T00:00:00Z", "files": {}}))


class TestI0643StudioImportCarriesMetrics(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.data = Path(self.td.dir)

    def tearDown(self):
        self.td.close()

    def _pkg(self) -> Path:
        pkg = self.data / "pkg"
        (pkg / "evaluation" / "verify_loader").mkdir(parents=True)
        (pkg / "evaluation" / "verify_loader" / "loader.json").write_text(json.dumps({"ok": True}))
        (pkg / "artifact" / "train").mkdir(parents=True)
        (pkg / "artifact" / "train" / "train_result.json").write_text(json.dumps({"kind": "TRAINHUB", "model_key": KEY, "version": VER}))
        _th_package(pkg / "artifact" / "train" / "trainhub" / KEY / VER)
        (pkg / "manifest.json").write_text(json.dumps({"task": {"instrument": "XAUUSD", "task_key": "k", "model_id": "TH_LOGREG"},
                                                       "stages": {"train": {"status": "COMMITTED", "dir": "artifact/train", "files": {}}}}))
        return pkg

    def test_import_registers_the_full_version_entry(self):
        from masterquo.modelhub import aggregate as AG
        from masterquo.studio import importer as IM
        from masterquo.trainhub import registry as R
        r = IM.import_package(self._pkg())
        self.assertTrue(r["ok"], r)
        v = R.registry("XAUUSD")["versions"][KEY][0]
        self.assertEqual((v["source"], v["import_id"]), ("STUDIO", r["import_id"]))
        self.assertEqual(v.get("data_kind"), "SYNTHETIC")                 # HEAD: missing - a SYNTHETIC Studio package was not marked
        self.assertEqual((v.get("model_id"), v.get("base_tf"), v.get("horizon")), ("TH_LOGREG", "M5", 6))
        self.assertEqual(v["walk_forward"]["dev_skill_vs_baseline"], 0.0123)
        self.assertNotIn("folds", v["walk_forward"])                      # the same entry as save_package (folds stay in metrics.json)
        self.assertEqual(v["holdout"]["skill_vs_baseline"], 0.01)
        self.assertEqual(AG.dev_skill("XAUUSD", KEY, VER), 0.0123)        # HEAD: None -> weight 0 / last in the evidence group
        self.assertIsInstance(v["created_at"], str)

    def test_old_import_entry_is_completed_from_the_package(self):
        from masterquo.modelhub import aggregate as AG
        from masterquo.trainhub import registry as R
        _th_package(R.package_dir("XAUUSD", KEY, VER), data_kind="REAL")
        R.register_imported_version("XAUUSD", KEY, {"version": VER, "created_at": "2026-02-01T00:00:00Z", "source": "STUDIO", "import_id": "IMP-1",
                                                    "package": "x"})
        before = R._reg_path("XAUUSD").read_bytes()
        self.assertEqual(AG.dev_skill("XAUUSD", KEY, VER), 0.0123)        # HEAD: None
        row = R.summary("XAUUSD")["versions"][0]
        self.assertEqual((row["data_kind"], row["created_at"], row["source"]), ("REAL", "2026-02-01T00:00:00Z", "STUDIO"))
        self.assertEqual(R._reg_path("XAUUSD").read_bytes(), before)       # read only - registry.json is not rewritten

    def test_trained_package_entry_unchanged(self):
        from masterquo.trainhub import registry as R
        res = {"model_id": "TH_LOGREG", "holdout": {"a": 1}, "walk_forward": WF, "trading_eval_holdout": {"t": 1}}
        e = R.version_entry(version="v", created_at="c", model_id="TH_LOGREG", base_tf="M5", horizon=6, data_kind="REAL", metrics=res, path="p")
        self.assertEqual(list(e), ["version", "created_at", "model_id", "base_tf", "horizon", "data_kind", "holdout", "walk_forward",
                                   "trading_eval_holdout", "path"])        # the keys save_package wrote in 1.46.0
        self.assertEqual(e["walk_forward"], {"dev_skill_vs_baseline": 0.0123, "folds_beating_baseline": 3})


# ================================================================================================ I0010 jeden stan trainhub
class TestI0010TrainhubStatusSingleSource(_Data):
    def setUp(self):
        super().setUp()
        from masterquo.trainhub import registry as R
        R._save_reg("XAUUSD", {"versions": {"TH_LOGREG_M5_H6": [{"version": "v1"}], "TH_RF_M5_H6": [{"version": "r1"}, {"version": "r2"}]},
                               "active": {"TH_LOGREG_M5_H6": "v1"}, "history": []})
        self.preds: list = []
        self.rt = SimpleNamespace(trainhub=None, trainhub_inference=SimpleNamespace(predictions=lambda inst: list(self.preds)))

    def _views(self, rt):
        from masterquo.modelhub import catalog as CAT
        from masterquo.quant import inventory as QI
        from masterquo.sh import models as SM
        cat = next(r for r in CAT._th_entries("XAUUSD", rt) if r["id"] == "th_logreg")
        sh = SM.probe(next(i for i in SM.REGISTRY if i["id"] == "th_direction"), rt, "XAUUSD")
        e = {"id": "trainhub:TH_LOGREG"}
        QI._probe([e], rt, "XAUUSD")
        return cat["state"], sh["status"], e["runtime_state"]

    def test_active_version_without_prediction_is_one_state(self):
        self.assertEqual(self._views(self.rt), ("BLOCKED_DATA", "DATA_MISSING", "DATA_MISSING"))   # HEAD: BLOCKED_DATA / SHADOW_ONLY / SHADOW_ONLY

    def test_ready_prediction(self):
        self.preds = [{"model_key": "TH_LOGREG_M5_H6", "state": "READY"}]
        self.assertEqual(self._views(self.rt), ("READY", "SHADOW_ONLY", "SHADOW_ONLY"))

    def test_stale_prediction(self):
        self.preds = [{"model_key": "TH_LOGREG_M5_H6", "state": "ERROR", "unavailable_reason": "dane nieaktualne"}]
        self.assertEqual(self._views(self.rt), ("ERROR", "ERROR", "ERROR"))

    def test_without_live_view_unchanged(self):
        # the SH cycle builds its own matrix with rt=None and the inventory report is generated without a bot: as in 1.46
        cat, sh, q = self._views(None)
        self.assertEqual((cat, sh, q), ("DISABLED", "SHADOW_ONLY", "SHADOW_ONLY"))

    def test_family_view_uses_the_same_source(self):
        from masterquo.modelhub.families import registry as famreg
        from masterquo.trainhub import registry as R
        th = famreg()["TH_RF"].trainhub_state("XAUUSD")
        st = R.status_of("XAUUSD", "TH_RF")
        self.assertEqual((th["artifact"], th["versions"], th["use"]), ("CANDIDATE", 2, "OFF"))    # artifact / use unchanged
        self.assertEqual((th.get("state"), th.get("reason")), (st["state"], st["reason"]))      # HEAD: no trainhub state in the family view

    def test_family_view_active_package_has_no_false_state(self):
        # recenzja: widok rodzin nie ma rt – dla aktywnej paczki status_of daje DISABLED „serwis inferencji … nie działa”
        # (cause NO_LIVE_VIEW), także gdy bot działa, a katalog pokazuje READY; widok rodzin tego stanu nie podaje
        from masterquo.modelhub.families import registry as famreg
        from masterquo.trainhub import learn as L
        from masterquo.trainhub import registry as R
        reg = R.registry("XAUUSD")
        reg["active"]["TH_RF_M5_H6"] = "r2"
        R._save_reg("XAUUSD", reg)
        with mock.patch.object(L, "available", return_value={"TH_RF": True}):
            self.assertEqual(R.status_of("XAUUSD", "TH_RF")["cause"], "NO_LIVE_VIEW")
            th = famreg()["TH_RF"].trainhub_state("XAUUSD")
            self.assertEqual((th["artifact"], th["versions"], th["use"], th["active"]), ("CANDIDATE", 2, "SHADOW", {"TH_RF_M5_H6": "r2"}))
            self.assertNotIn("state", th)                                     # przed poprawką recenzji: DISABLED
            self.assertNotIn("reason", th)
            self.preds = [{"model_key": "TH_RF_M5_H6", "state": "READY"}]
            self.assertEqual(R.status_of("XAUUSD", "TH_RF", self.rt)["state"], "READY")   # live state: the model catalog's
        with mock.patch.object(L, "available", return_value={"TH_RF": False}):
            th = famreg()["TH_RF"].trainhub_state("XAUUSD")                  # a state that needs no live view stays
            self.assertEqual((th["state"], th["reason"]), ("DISABLED", "biblioteka modelu niedostępna w tym środowisku"))


# ================================================================================================ I0101 (wariant bezpieczny) history.json
class TestI0101PepeHistoryNotList(_Data):
    def test_object_history_does_not_stop_the_start(self):
        from masterquo.training import pepe_center as PC
        (PC.center_dir() / "history.json").write_text("{}", encoding="utf-8")
        c = PC.PepeTrainingCenter(SimpleNamespace())                     # HEAD: KeyError slice(-100, None) -> Runtime() -> exit 5
        self.assertEqual(c.history, [])
        kept = list(PC.center_dir().glob("history.json.corrupt-*"))
        self.assertEqual(len(kept), 1)                                    # the user's file is kept, not overwritten by _remember()
        self.assertEqual(kept[0].read_text(encoding="utf-8"), "{}")
        c._remember({"id": "x", "unit": "trainhub", "state": "DONE"})
        self.assertEqual(kept[0].read_text(encoding="utf-8"), "{}")

    def _not_utf8(self, raw: bytes) -> None:
        from masterquo.training import pepe_center as PC
        (PC.center_dir() / "history.json").write_bytes(raw)
        c = PC.PepeTrainingCenter(SimpleNamespace())                     # przed poprawką recenzji: UnicodeDecodeError -> Runtime() -> exit 5
        self.assertEqual(c.history, [])
        kept = list(PC.center_dir().glob("history.json.corrupt-*"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_bytes(), raw)                       # bajty użytkownika zachowane bez zmian
        c._remember({"id": "x", "unit": "trainhub", "state": "DONE"})
        self.assertEqual(kept[0].read_bytes(), raw)
        self.assertEqual(json.loads((PC.center_dir() / "history.json").read_text(encoding="utf-8"))[0]["id"], "x")

    def test_cp1250_history_does_not_stop_the_start(self):
        # Notatnik „ANSI”: polski tekst z historii (przerwany zamknięciem…, Główny trening) zapisany w cp1250
        items = [{"id": "q1", "unit": "runner", "name": "Główny trening", "state": "CANCELLED", "detail": "przerwany zamknięciem aplikacji"}]
        self._not_utf8(json.dumps(items, ensure_ascii=False).encode("cp1250"))

    def test_invalid_byte_history_does_not_stop_the_start(self):
        self._not_utf8(b'[{"id": "q1", "name": "\xff"}]')

    def test_list_history_unchanged(self):
        from masterquo.training import pepe_center as PC
        items = [{"id": f"i{i}", "unit": "trainhub"} for i in range(130)]
        (PC.center_dir() / "history.json").write_text(json.dumps(items), encoding="utf-8")
        self.assertEqual(PC.PepeTrainingCenter(SimpleNamespace()).history, items[-100:])
        self.assertEqual(list(PC.center_dir().glob("history.json.corrupt-*")), [])


# ================================================================================================ I0100 procesy treningu przy STOP
def _sleeper(**kw) -> subprocess.Popen:
    return subprocess.Popen([PY, "-c", "import time; time.sleep(60)"], **kw)


def _end(p: subprocess.Popen) -> None:
    if p.poll() is None:
        p.kill()
    p.wait(10)


def _gone(pid: int, tries: int = 50) -> bool:
    import time as _t
    for _ in range(tries):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        _t.sleep(0.1)
    return False


class TestI0100TrainingStopsWithRuntime(_Data):
    def test_family_service_stop_ends_its_training_processes(self):
        import time as _t

        from masterquo.modelhub.families.service import FamilyService
        svc = FamilyService(SimpleNamespace(get=lambda: None))
        p = _sleeper(start_new_session=True)
        self.addCleanup(_end, p)
        svc.procs["KALMAN_LS__XAUUSD"] = p
        jf = svc._job_file("KALMAN_LS", "XAUUSD")
        jf.write_text(json.dumps({"state": "RUNNING", "family": "KALMAN_LS", "instrument": "XAUUSD", "pid": p.pid}), encoding="utf-8")
        t0 = _t.monotonic()
        out = svc.stop()                                                  # HEAD: AttributeError - no stop(), training survives STOP
        self.assertLess(_t.monotonic() - t0, 5.0)
        self.assertIsNotNone(p.poll())
        self.assertEqual(out["stopped"], ["KALMAN_LS__XAUUSD"])
        j = json.loads(jf.read_text(encoding="utf-8"))
        self.assertEqual((j["state"], j["reason"]), ("CANCELLED", "przerwany zamknięciem aplikacji"))
        self.assertEqual(svc.submit("KALMAN_LS", "XAUUSD")["status"], "STOPPING")   # nothing new after stop
        self.assertEqual(svc.status("KALMAN_LS", "XAUUSD")["artifact"], "NOT_TRAINED")  # status() still works

    def test_pepe_center_stop_ends_its_own_pipeline_process_only(self):
        from masterquo.training import pepe_center as PC
        c = PC.PepeTrainingCenter(SimpleNamespace())
        p = _sleeper(start_new_session=True)
        self.addCleanup(_end, p)
        cur = {"id": "PTC-1", "unit": "pipeline", "instruments": ["XAUUSD"], "state": "RUNNING", "_proc": p, "_before": set()}
        c.current, c._proc = cur, p
        c.queue = [{"id": "PTC-2", "unit": "trainhub", "instruments": ["XAUUSD"], "state": "QUEUED"}]
        out = c.stop()                                                    # HEAD: AttributeError - `training run` survived STOP
        self.assertIsNotNone(p.poll())
        self.assertEqual(out["stopped"], ["pepe-center:pipeline"])
        self.assertEqual(len(c.queue), 1)                                 # not cancel(): the queue is not cleared
        h = c.history[-1]
        self.assertEqual((h["id"], h["state"], h["detail"]), ("PTC-1", "CANCELLED", "przerwany zamknięciem aplikacji"))
        saved = json.loads((PC.center_dir() / "history.json").read_text(encoding="utf-8"))
        self.assertEqual(saved[-1]["state"], "CANCELLED")
        self.assertEqual(c.stop(), {"stopped": []})                       # idempotent

    def test_stop_order_after_the_trading_path(self):
        from masterquo.runtime import Runtime
        order = list(Runtime._STOP_ORDER)
        for part in ("pepe_training", "families", "procs"):
            self.assertIn(part, order)                                    # HEAD: missing - Runtime.stop() never reached them
            self.assertGreater(order.index(part), order.index("engine"))
            self.assertGreater(order.index(part), order.index("manager"))
            self.assertLess(order.index(part), order.index("bridge"))
            self.assertLess(order.index(part), order.index("worker"))


class TestI0100ProcessRegistry(unittest.TestCase):
    def test_only_training_kinds(self):
        from masterquo import procs as PR
        reg = PR.ProcessRegistry()
        p = _sleeper()
        self.addCleanup(_end, p)
        with self.assertRaises(ValueError):
            reg.register("mt5-worker", p, "worker")                     # the MT5 worker / bridge are never registered
        reg.register("api:x", p, "training")
        self.assertEqual(list(reg.running()), ["api:x"])

    @unittest.skipIf(os.name == "nt", "POSIX process groups")
    def test_stop_all_ends_the_group_of_a_session_leader(self):
        from masterquo import procs as PR
        reg = PR.ProcessRegistry()
        code = ("import subprocess, sys, time; c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                "print(c.pid, flush=True); time.sleep(60)")
        p = subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(_end, p)
        self.addCleanup(p.stdout.close)
        child = int(p.stdout.readline())
        reg.register("api:tree", p, "training")
        self.assertEqual(reg.stop_all(timeout_s=3.0), ["api:tree"])
        self.assertIsNotNone(p.poll())
        self.assertTrue(_gone(child))                                     # the grandchild is in the same group -> ended too

    @unittest.skipIf(os.name == "nt", "POSIX process groups")
    def test_child_in_our_group_is_terminated_not_the_group(self):
        from masterquo import procs as PR
        p = _sleeper()                                                    # same process group as the test runner
        self.addCleanup(_end, p)
        with mock.patch("os.killpg", side_effect=AssertionError("killpg of a group this child does not lead")):
            PR.kill_tree(p)
        p.wait(5)
        self.assertIsNotNone(p.poll())

    def test_windows_tree_never_contains_the_mt5_terminal(self):
        from masterquo import procs as PR
        procs = [(100, 1, "python.exe"), (101, 100, "python.exe"), (102, 101, "terminal64.exe"), (103, 102, "python.exe"),
                 (104, 100, "pythonw.exe"), (105, 100, "MetaTrader 5.exe"), (106, 100, "conhost.exe"), (107, 100, "python.exe")]
        start = {100: 10, 101: 11, 104: 12, 107: 5}                       # 107: older than its "parent" -> a reused parent pid
        self.assertEqual(sorted(PR._python_tree(100, procs, start.get)), [101, 104])

    def test_api_and_panel_export_register_their_children(self):
        api = (_env.ROOT / "backend" / "masterquo" / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn('REGISTRY.register(f"api:{kind}", train_procs[kind], "training")', api)
        ex = (_env.ROOT / "backend" / "masterquo" / "training" / "export_job.py").read_text(encoding="utf-8")
        self.assertIn('REGISTRY.register(f"export:{p.pid}", p, "export")', ex)

# ================================================================================================ I0064 DatasetRef w manifestach
class TestI0064DatasetRefLineage(_Data):
    def test_runner_task_records_the_export_it_trained_on(self):
        from masterquo.training import core, report, runner
        run = self.plan_run(tasks=["forecast"])
        ds = self.data / "ds"
        ds.mkdir()
        meta = {"dataset_id": "D1", "instrument": "XAUUSD", "symbol": "XAUUSD-", "data_kind": "SYNTHETIC_TEST", "costs": {},
                "range_utc": ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"], "files_sha256": {"XAUUSD_M5.csv": "aa", "XAUUSD_M30.csv": "bb"}}
        (ds / "source_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (ds / "DATA_QUALITY_REPORT.json").write_text(json.dumps({"sufficiency": {"status": "OK"}}), encoding="utf-8")
        run.set("XAUUSD:export", execution="UKONCZONE", dataset_dir=str(ds), data_kind="SYNTHETIC_TEST")
        run.set("XAUUSD:quality", execution="UKONCZONE", quality="NIE_DOTYCZY")

        def fake_forecast(r, inst):
            r.set(f"{inst}:forecast", execution="UKONCZONE", quality="TEST_TECHNICZNY")
        steps = {k: (lambda r, inst: None) for k in runner.STEPS}
        steps["forecast"] = fake_forecast
        with mock.patch.dict(runner.STEPS, steps), mock.patch.object(core, "acquire_lock", lambda rid: None), \
                mock.patch.object(core, "release_lock", lambda rid: None), mock.patch.object(report, "write", lambda r: None), \
                mock.patch("sys.stdout", io.StringIO()):
            runner.execute(run)
        ref = run.task("XAUUSD:forecast").get("dataset_ref")                # HEAD: None - no lineage of the training set
        self.assertIsNotNone(ref)
        self.assertEqual((ref["source"], ref["data_kind"], ref["instrument"]), ("MT5_EXPORT_RUN", "SYNTHETIC_TEST", "XAUUSD"))
        self.assertEqual(len(ref["sha256"]), 64)
        self.assertEqual(ref["range_utc"], meta["range_utc"])
        self.assertEqual(ref["quality"]["status"], "OK")
        self.assertIsNone(run.task("XAUUSD:ml").get("dataset_ref"))       # a task that did not train gets nothing

    def test_trainhub_package_manifest(self):
        from masterquo.trainhub import registry as R
        res = {"model_id": "TH_BASELINE", "params": {}, "temperature": 1.0, "decision_threshold": None, "holdout": {"log_loss": 1.0},
               "walk_forward": {"dev_skill_vs_baseline": 0.0, "folds": []}, "trading_eval_holdout": {}, "sample": {"X": [], "p_raw": []}}
        cfg = {"base_tf": "M5", "horizon": 6, "k_atr": 0.25}
        desc = {"hash": "f" * 64, "range_utc": ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"], "rows_usable": 100, "data_kind": "SYNTHETIC"}
        out = R.save_package("XAUUSD", cfg, {"model": {"m": 1}, "result": res}, desc, {"data_kind": "SYNTHETIC", "symbol": "XAUUSD-"})
        dm = json.loads((Path(out["path"]) / "data_manifest.json").read_text(encoding="utf-8"))
        ref = dm.get("dataset_ref")                                         # HEAD: missing
        self.assertIsNotNone(ref)
        self.assertEqual((ref["source"], ref["sha256"], ref["data_kind"], ref["rows"]), ("MARKETDATA_STORE", "f" * 64, "SYNTHETIC", 100))
        self.assertTrue(R.verify_package("XAUUSD", out["model_key"], out["version"])["ok"])   # checksums cover the new field

    def test_family_run_manifest(self):
        from masterquo.modelhub.families import base as FB
        from masterquo.modelhub.families import run as RUN

        class Fake(FB.Family):
            ID, NAME, TF = "FAKE", "fake", "M5"
            DATA: ClassVar[dict] = {"kind": "BARS", "tf": "M5", "min_bars": 5}

            def fit(self, data, cfg, tmp, budget):
                (tmp / "model.json").write_text("{}", encoding="utf-8")
                return {"metrics": {}, "validation": {"status": "CANDIDATE"}}
        bars = [{"t": 1_767_225_600 + 300 * i, "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.0 + i * 1e-3, "v": 1} for i in range(10)]
        data = {"instrument": "XAUUSD", "bars": bars, "data_kind": "SYNTHETIC_TEST", "symbol": "XAUUSD-", "source": "MT5_LIVE_BRIDGE"}
        with mock.patch("masterquo.modelhub.families.registry", lambda: {"FAKE": Fake()}):
            r = RUN.train("FAKE", "XAUUSD", "smoke", {}, data=data, store=FB.Store(self.data / "fam"))
        self.assertEqual(r["state"], "DONE", r)
        man = json.loads((Path(r["dir"]) / "manifest.json").read_text(encoding="utf-8"))
        ref = man.get("dataset_ref")                                        # HEAD: missing
        self.assertIsNotNone(ref)
        self.assertEqual((ref["source"], ref["data_kind"], ref["sha256"], ref["rows"]), ("MT5_LIVE_BRIDGE", "SYNTHETIC_TEST", man["data"]["hash"], 10))
        self.assertEqual(ref["range_utc"][0], "2026-01-01T00:00:00Z")


# ================================================================================================ I0069 nadzór procesów treningu
class TestI0069OneRamBudget(_Data):
    def test_budget_has_one_source(self):
        from masterquo.training import core
        prof = core.profiles()["PELNY_TRENING"]["ram_budget_mb"]
        with mock.patch.dict(os.environ, {"MQ_RAM_BUDGET_MB": ""}):
            self.assertEqual(core.ram_budget_mb(), prof)                    # HEAD: TypeError (plan required) - TrainHub used 6144
        with mock.patch.dict(os.environ, {"MQ_RAM_BUDGET_MB": "5000"}):
            self.assertEqual(core.ram_budget_mb(), 5000)
            self.assertEqual(core.ram_budget_mb({"profile_params": {"ram_budget_mb": 9000}}), 5000)
        src = (_env.ROOT / "backend" / "masterquo" / "trainhub" / "jobs.py").read_text(encoding="utf-8")
        self.assertNotIn("6144", src)

    def test_family_and_ml_children_get_the_same_memory_cap(self):
        from masterquo.ml import service as MS
        from masterquo.modelhub.families import service as FS
        from masterquo.training import core
        seen = []
        fake = SimpleNamespace(pid=4242, poll=lambda: None)
        with mock.patch.object(core, "limit_child", side_effect=lambda p, **k: seen.append(p)), \
                mock.patch.object(MS.subprocess, "Popen", return_value=fake):
            MS.MLService._spawn_process(SimpleNamespace(cfg=SimpleNamespace(xgb_threads=1)), self.data / "job.json")
        self.assertEqual(seen, [fake])                                      # HEAD: no memory cap for the ML trainer
        svc = FS.FamilyService(SimpleNamespace(get=lambda: SimpleNamespace(families=SimpleNamespace(pairs=[], basket=[], nlp_transformer_path=None))))
        with mock.patch.object(core, "limit_child", side_effect=lambda p, **k: seen.append(p)), \
                mock.patch.object(FS.subprocess, "Popen", return_value=fake), mock.patch.object(svc, "_live_bars_file", lambda f, i: None):
            r = svc.submit("KALMAN_LS", "XAUUSD")
        self.assertTrue(r["ok"], r)
        self.assertEqual(seen, [fake, fake])                                # HEAD: no memory cap for family processes
        st = (_env.ROOT / "backend" / "masterquo" / "studio" / "queue.py").read_text(encoding="utf-8")
        self.assertIn("limit_child(self.proc", st)


class TestI0069QuantTrainOutOfProcess(_Data):
    def test_training_runs_in_a_child_process(self):
        import threading
        import time as _t

        from masterquo.quant import service as QS
        from test_quant_core import StubRt
        q = QS.QuantService(StubRt())
        calls = []

        class FakeProc:
            pid, returncode = 4343, 0

            def __init__(self, cmd, **kw):
                calls.append(cmd)
                out = Path(cmd[cmd.index("--job-out") + 1])
                out.write_text(json.dumps({"results": [{"task_hash": "t", "status": "INSUFFICIENT_EVIDENCE"}]}), encoding="utf-8")

            def wait(self, timeout=None):
                return 0

            def poll(self):
                return 0
        before = {t.name for t in threading.enumerate()}
        with mock.patch.object(QS.subprocess, "Popen", FakeProc):
            job = q.train("XAUUSD", background=True)
            for _ in range(100):
                if q.jobs[job["job_id"]]["state"] != "RUNNING":
                    break
                _t.sleep(0.05)
        self.assertEqual(len(calls), 1)                                     # HEAD: no process - training in a bot thread
        self.assertEqual(calls[0][1:5], ["-m", "masterquo", "quant", "train"])
        self.assertIn("--instrument", calls[0])
        self.assertNotIn("quant-train", {t.name for t in threading.enumerate()} - before)
        j = q.jobs[job["job_id"]]
        self.assertEqual(j["state"], "DONE")
        self.assertEqual(j["results"][0]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue((q.base / "jobs" / f"{job['job_id']}.json").exists())

    def test_cli_writes_the_job_result(self):
        from masterquo.quant import cli
        out = self.data / "job_out.json"
        with mock.patch("masterquo.quant.service.train_from_ledger", return_value=[{"task_hash": "t", "status": "INSUFFICIENT_EVIDENCE"}]), \
                mock.patch("sys.stdout", io.StringIO()):
            rc = cli.main(["train", "--instrument", "XAUUSD", "--job-out", str(out)])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["results"][0]["task_hash"], "t")

class TestI0064TrainhubPipelineLineage(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_stage_train_records_the_store_and_its_quality_report(self):
        from masterquo.marketdata import export as EX
        from masterquo.marketdata.sources import DirectSource
        from masterquo.marketdata.store import Store
        from masterquo.mt5.fake import FakeMT5
        from masterquo.trainhub import pipeline as P
        f = FakeMT5(history_days=40)
        f.initialize()
        st = Store()
        EX.run(DirectSource(f, offset=3 * 3600, offset_basis="TEST"), st, "XAUUSD", "XAUUSD-", timeframes=("M5", "M15", "M30"),
               lookback_days=30, sleep=lambda s: None)
        cfg = P.config({"models": ["TH_BASELINE"]}, st.manifest("XAUUSD"))
        out = P.stage_train(st, "XAUUSD", cfg)
        pk = out["packages"][0]
        dm = json.loads((Path(pk["path"]) / "data_manifest.json").read_text(encoding="utf-8"))
        ref = dm["dataset_ref"]                                             # HEAD: KeyError
        self.assertEqual((ref["source"], ref["data_kind"]), ("MARKETDATA_STORE", "SYNTHETIC_TEST"))
        self.assertEqual(ref["quality"]["report"], str(st.inst_dir("XAUUSD") / "quality_report.json"))
        self.assertTrue(ref["quality"]["status"])
        self.assertEqual(ref["sha256"], dm["dataset"]["hash"])              # the dataset hash of exactly this training set
        self.assertTrue(ref["sha256"])

if __name__ == "__main__":
    unittest.main()
