"""1.46 arch (Etap 3): behaviour-neutral bug fixes found by the model verification, each test fails on 1.46.0.

* Studio RUNNER_GROUP (diagnoza funkcje_do_zachowania#0, K): studio/pipeline._train_runner passed the runner profile 'quick' / 'standard',
  the runner only knows TEST_INSTALACJI / PELNY_TRENING (config/training_profiles_v1.json) -> KeyError for EVERY one of the 28 Studio
  runner-group tasks (the existing tests mocked build_plan). Studio still never activates and never reloads the bot.
* trainhub registry.json (same defect as registry_io, diagnoza trening#0): every writer re-read an unreadable registry as EMPTY under
  reg_lock and saved it back - all versions, active packages and the history were lost; the Studio importer wrote it without reg_lock.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

import _env
from test_audit_146_b_studio_th_1 import StudioEnv, _FakeRun


class TestStudioRunnerGroupProfile(StudioEnv):
    def _ctx(self, profile: str):
        from masterquo.studio import pipeline as P
        from masterquo.studio.package import RAW
        task = {"model_id": "RUNNER:forecast", "task_id": "forecast", "instrument": "XAUUSD", "base_tf": "M5", "task_key": "K",
                "adapter": "RUNNER_GROUP", "broker_symbol": "XAUUSD-", "sources": [{"kind": "BARS_RUNNER_EXPORT", "tf": "M5"}]}
        pkg = self.package(task)
        d = pkg.dir / RAW / "runner_dataset"
        d.mkdir(parents=True, exist_ok=True)
        (d / "source_metadata.json").write_text(json.dumps({"instrument": "XAUUSD", "symbol": "XAUUSD-", "data_kind": "SYNTHETIC"}))
        return P.Ctx(task, pkg, source={"mode": "SYNTHETIC"}, profile=profile)

    def test_real_build_plan_accepts_the_studio_profiles_and_never_activates(self):
        from masterquo.studio import pipeline as P
        for profile, want in (("smoke", "TEST_INSTALACJI"), ("full", "PELNY_TRENING")):
            seen = {}

            def execute(run, seen=seen):
                seen["plan"] = run.plan
                seen["tasks"] = {t["kind"]: t.get("execution") for t in run.state["tasks"]}
                for t in run.state["tasks"]:
                    if t["kind"] in ("export", "quality", "forecast"):
                        t["execution"] = "UKONCZONE"
                return 0
            with self.subTest(profile=profile), mock.patch("masterquo.training.core.Run.create", side_effect=lambda plan, tasks: _FakeRun(plan, tasks)), \
                    mock.patch("masterquo.training.runner.execute", side_effect=execute):
                res = P._train_runner(self._ctx(profile))                 # 1.46.0: KeyError 'quick' / 'standard' from core.profiles()
                self.assertEqual(res["kind"], "RUNNER_GROUP")
                self.assertEqual(seen["plan"]["profile"], want)
                self.assertFalse(seen["plan"]["activate"])                 # Studio never inherits activation
                self.assertEqual(seen["tasks"]["activate"], "POMINIETE")
                self.assertEqual(seen["tasks"]["bot"], "POMINIETE")


class TestTrainhubRegistryStrict(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_unreadable_registry_is_not_rewritten(self):
        from masterquo import registry_io as RIO
        from masterquo.trainhub import registry as R
        p = R._reg_path("XAUUSD")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"versions": {"TH_LOGREG_M5_H6": [{"version": "v1"}]}, "active": {"TH_LOG', encoding="utf-8")
        before = p.read_bytes()
        for fn in (lambda: R.deactivate("XAUUSD", "TH_LOGREG_M5_H6"), lambda: R.remove_version("XAUUSD", "TH_LOGREG_M5_H6", "v0"),
                   lambda: R.register_imported_version("XAUUSD", "TH_LOGREG_M5_H6", {"version": "v2"})):
            with self.assertRaises(RIO.RegistryUnreadable):
                fn()
            self.assertEqual(p.read_bytes(), before)
        self.assertEqual(R.summary("XAUUSD").get("versions") or [], [])            # display side: empty view, no crash

    def test_studio_import_writes_through_the_locked_function(self):
        from masterquo.trainhub import registry as R
        held = []
        real = R.reg_lock

        from contextlib import contextmanager

        @contextmanager
        def spy(inst, *a, **k):
            with real(inst, *a, **k):
                held.append(inst)
                yield
                held.pop()
        saved = []
        orig_save = R._save_reg
        with mock.patch.object(R, "reg_lock", spy), mock.patch.object(R, "_save_reg", side_effect=lambda i, r: (saved.append(bool(held)), orig_save(i, r))):
            R.register_imported_version("XAUUSD", "TH_LOGREG_M5_H6", {"version": "v1", "source": "STUDIO"})
        self.assertEqual(saved, [True])
        self.assertEqual([v["version"] for v in R._reg("XAUUSD")["versions"]["TH_LOGREG_M5_H6"]], ["v1"])
        src = (_env.ROOT / "backend" / "masterquo" / "studio" / "importer.py").read_text(encoding="utf-8")
        self.assertNotIn("R._save_reg(", src)                                    # 1.46.0: read-modify-write without reg_lock


if __name__ == "__main__":
    unittest.main()
