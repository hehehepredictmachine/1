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

if __name__ == "__main__":
    unittest.main()
