"""1.46 arch (Etap 3): behaviour-neutral bug fixes found by the model verification, each test fails on 1.46.0.

* Studio RUNNER_GROUP (diagnoza funkcje_do_zachowania#0, K): studio/pipeline._train_runner passed the runner profile 'quick' / 'standard',
  the runner only knows TEST_INSTALACJI / PELNY_TRENING (config/training_profiles_v1.json) -> KeyError for EVERY one of the 28 Studio
  runner-group tasks (the existing tests mocked build_plan). Studio still never activates and never reloads the bot.
* trainhub registry.json (same defect as registry_io, diagnoza trening#0): every writer re-read an unreadable registry as EMPTY under
  reg_lock and saved it back - all versions, active packages and the history were lost; the Studio importer wrote it without reg_lock.
* TSFM worker failure (Chronos-2 / Granite TTM / TiRex-2) was never written to the event log: tsfm/service.ModelWorker.fail called
  applog.warning(), AppLog only has warn() - the AttributeError was swallowed by the surrounding except.
* Kronos ledger (diagnoza ledgery, W): a re-forecast of the same bar got a new random forecast_id, INSERT OR IGNORE kept the first row,
  but `latest`, the PMW-PRED-2 record (result.forecast_id) and the listeners carried the new id that is in no table. Now the same as TSFM
  (1.46): an identical re-forecast takes the stored id (SAME_AS_RECORDED), a different one is marked REFORECAST_NOT_RECORDED. Forecast
  values, direction and publication order are unchanged.
* Model catalog of the panel (/api/v1/models/catalog, diagnoza rejestry_modeli W): the MM module rows were joined to the SH rows by the
  'mm_' prefix, so breakout appeared twice - mm_breakout READY and mm_breakout_zones DISABLED. Rows are now joined by canonical id.
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


class TestTsfmFailureIsLogged(unittest.TestCase):
    def test_worker_failure_reaches_the_event_log(self):
        from types import SimpleNamespace

        from masterquo.events import AppLog
        from masterquo.tsfm import service as TS
        log = mock.create_autospec(AppLog, instance=True)                      # only the real AppLog methods exist
        w = TS.ModelWorker(SimpleNamespace(applog=log), "chronos2")
        self.assertFalse(w.fail("WORKER_START_FAILED", "brak środowiska"))
        log.warn.assert_called_once()
        self.assertEqual(log.warn.call_args.args[:2], ("TSFM", "WORKER_START_FAILED"))
        self.assertEqual(w.state["status"], "ERROR")


def _kronos_fc(fid: str, pred_c: float) -> dict:
    return {"id": fid, "created_at": "2026-03-04T08:00:00Z", "instrument": "XAUUSD", "symbol": "XAUUSD-", "timeframe": "M5", "horizon_bars": 1,
            "last_bar_open_utc": "2026-03-04T07:55:00Z", "last_close": 2650.0, "pred_close_h": pred_c, "delta_price": pred_c - 2650.0,
            "direction": "UP" if pred_c > 2650.2 else "FLAT", "neutral_band": 0.2, "pred": [{"t_utc": "2026-03-04T08:00:00Z", "c": pred_c}],
            "uncertainty": None, "model": {"revision": "r1"}, "tokenizer": {"revision": "t1"}, "device": "cpu", "compute_ms": 5,
            "data_kind": "SYNTHETIC_TEST", "quality": {"volume_source": "tick", "status": "OK"}, "sampling": {"T": 1.0}, "timestamp_basis": "UTC"}


class TestKronosReforecastId(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_reforecast_of_the_same_bar_resolves_to_the_stored_row(self):
        from types import SimpleNamespace

        from masterquo.db.database import Database
        from masterquo.kronos.service import KronosService
        db = Database()
        svc = SimpleNamespace(db=db)
        rec = KronosService.record.__get__(svc)
        first = _kronos_fc("KR-1", 2651.0)
        rec(first)
        same = _kronos_fc("KR-2", 2651.0)                                     # restart / refresh: the same forecast of the same bar
        rec(same)
        ids = {r["forecast_id"] for r in db.query("SELECT forecast_id FROM kronos_forecasts")}
        self.assertEqual(ids, {"KR-1"})
        self.assertEqual(same["id"], "KR-1")                                  # 1.46.0: 'KR-2' - in no table
        self.assertEqual(same["ledger"]["status"], "SAME_AS_RECORDED")
        diff = _kronos_fc("KR-3", 2649.0)                                     # a DIFFERENT re-forecast of the same bar
        rec(diff)
        self.assertEqual(diff["ledger"]["status"], "REFORECAST_NOT_RECORDED")
        self.assertEqual(diff["ledger"]["recorded_forecast_id"], "KR-1")
        self.assertEqual((diff["pred_close_h"], diff["direction"]), (2649.0, "FLAT"))   # the forecast itself is untouched
        self.assertEqual(first["ledger"]["status"], "RECORDED")


class TestCatalogOneRowPerProducer(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_no_producer_appears_twice(self):
        from collections import Counter

        from masterquo.modelhub import catalog as CAT
        from masterquo.quant import ids as I
        rows = CAT.build(None, "XAUUSD")["items"]
        canon = [I.resolve(r["id"]) or I.resolve("mm:" + r["id"].removeprefix("mm_")) or r["id"] for r in rows]
        dup = {k: [r["id"] for r, c in zip(rows, canon) if c == k] for k, n in Counter(canon).items() if n > 1}
        self.assertEqual(dup, {})                                              # 1.46.0: mm:breakout_zones -> mm_breakout + mm_breakout_zones
        by = {r["id"]: r for r in rows}
        self.assertEqual(by["mm_breakout"]["source"], "sh/models.REGISTRY")    # the SH row (live state) stays, ids unchanged


if __name__ == "__main__":
    unittest.main()
