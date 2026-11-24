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
* STE-FlowNet artifact (models check --smoke, area mm): when VAL picked the no_temporal_weighting variant, the artifact stored the
  normalisation of the WEIGHTED samples - reloading it did not reproduce the evaluated model. Now the picked variant's normalisation and
  the sample weighting are stored. (No live path - training / artifact only.)
* NLP_SENTIMENT family: headlines older than ~7 days made the decayed weights sum below 1e-12, the aggregate was divided by 1e-12 instead
  of the sum - the distribution did not sum to 1, the contract rejected it and the family published ERROR. A stale record is now a
  normalised distribution with its real (old) data time - stale downstream, as before; weights that underflow to 0 -> BLOCKED_DATA.
* Native MiniRocket V2 feed (SHADOW_AUDIT): the indicator writes MQL5\\Files\\PMW\\PMW_MR2_RESULT.bin (InpOutDir "PMW"), the launchers set
  MQ_MT5_FILES_DIR = MQL5\\Files (the same variable locates PMW\\native_status.json), but the importer read <dir>\\PMW_MR2_RESULT.bin -
  /api/v1/structure-intelligence/native-status was always NATIVE_FEED_UNAVAILABLE.
* Flow context Markov3 / MarkovDiff (models check --smoke, area lab): a model fitted on SYNTHETIC_TEST data (role TEST_ONLY) was loaded
  into the Structure Intelligence M1 cell without any provenance. The run now stores its data kind / role and the cell shows it (panel
  only - no decision reads Markov3). Whether TEST_ONLY should be loaded at all is decision D23 (loading unchanged).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
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


class TestSteFlownetArtifactRoundtrip(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_picked_unweighted_variant_is_reproduced_from_the_artifact(self):
        import numpy as np
        from masterquo.mm import artifacts as AR
        from masterquo.mm import jobs as J
        from masterquo.mm import splits
        from masterquo.mm import ste_flownet as SF
        from masterquo.modelhub import smoke as S
        from masterquo.modelhub.smoke import mm as SM
        ctx = S.Ctx("XAUUSD")
        oc = SM._orch(ctx)
        with mock.patch.object(J, "min", create=True, new=lambda res, key: "no_temporal_weighting"):
            r = J.job_ste_flownet(oc)
        self.assertEqual(r["picked"], "no_temporal_weighting")
        st, man = AR.load("XAUUSD", "ste_flownet_ret", r["artifact_id"])
        self.assertIs(man.get("sample_weighting"), False)                      # 1.46.0: no flag - the loader could not know
        acc, fe, _, _ = J._events(oc)
        smp = SF.build_samples(acc, fe, 8, 16, 32, weighting=False)
        ref = SF.build_samples(acc, fe, 8, 16, 32)
        okk = np.where(np.isfinite(ref["y"]))[0]
        sp = splits.chrono_split(ref["t_obs"][okk], ref["t_label"][okk], (0.6, 0.2, 0.2), 0.0)
        ts = okk[sp["test"]]
        X = (smp["X"] - np.asarray(st["x_mu"], float)) / np.asarray(st["x_sd"], float)
        fresh = SF.reg_metrics(SF.STEModel.from_state(st).predict(X[ts]), ref["y"][ts])
        rec = man["metrics"]["test_once"]
        self.assertLessEqual(max(abs(float(fresh[k]) - float(rec[k])) for k in rec if isinstance(rec[k], (int, float))), 1e-9)


class TestNlpStaleHeadlines(unittest.TestCase):
    def test_old_headlines_give_a_normalised_distribution_or_blocked_data(self):
        import time as _time

        import numpy as np
        from masterquo.modelhub.families import base as B
        from masterquo.modelhub.families import registry
        f = registry()["NLP_SENTIMENT"]

        def items(age_days):
            t = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(_time.time() - age_days * 86400))
            return {"news": [{"headline": f"gold headline {i}", "first_seen_at": t} for i in range(3)]}
        P = np.array([[0.2, 0.3, 0.5], [0.1, 0.6, 0.3], [0.3, 0.3, 0.4]])
        with mock.patch.object(type(f), "score", return_value=P):
            out = f.predict({}, items(8))                                      # 1.46.0: sums to ~0.7 -> DISTRIBUTION_NOT_NORMALISED -> ERROR
            self.assertAlmostEqual(sum(out["sentiment"].values()), 1.0, places=9)
            with self.assertRaises(B.Unavailable) as cm:
                f.predict({}, items(400))                                      # weights underflow to exactly 0
            self.assertEqual(cm.exception.state, "BLOCKED_DATA")


class TestMiniRocketNativeFeedPath(unittest.TestCase):
    def test_result_written_by_the_indicator_is_found(self):
        import os
        import tempfile
        import time as _time
        from pathlib import Path
        from types import SimpleNamespace

        import numpy as np
        from masterquo.lab import minirocket_v2 as MR
        from masterquo.lab.si_service import StructureIntelligenceService
        with tempfile.TemporaryDirectory() as d:
            files = Path(d) / "MQL5" / "Files"
            (files / "PMW").mkdir(parents=True)
            now = int(_time.time())
            MR.write_result(files / "PMW" / MR.NativeResultImporter.NAME, 5, "ab" * 32, "XAUUSD-", "M1", now - 60, now, "UTC", np.zeros(3))
            stub = SimpleNamespace(native_importer=None, cfg=SimpleNamespace(get=lambda: SimpleNamespace(assets=SimpleNamespace(symbols={}))))
            with mock.patch.dict(os.environ, {"MQ_MT5_FILES_DIR": str(files), "MQ_MINIROCKET_EXPORT_DIR": str(Path(d) / "none")}):
                res = StructureIntelligenceService.native_status(stub, "XAUUSD")
            self.assertEqual(res["feed"]["status"], "IMPORTED", res["feed"])         # 1.46.0: NATIVE_FEED_UNAVAILABLE (wrong folder)
            self.assertEqual(res["feed"]["seq"], 5)
            self.assertEqual(res["feed"]["role"], "SHADOW_AUDIT")


class TestMarkovProvenance(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_loaded_markov_carries_its_provenance(self):
        from masterquo.lab.flow_context import cli as FC
        from masterquo.lab.flow_context import service as FS
        from masterquo.modelhub import smoke as S
        dev = S.Ctx("XAUUSD").bars("M1", 2500, history_days=10)
        out = FC.train_markov("XAUUSD", dev, 0.01, 0.01, {"data_kind": "SYNTHETIC_TEST"})
        self.assertEqual(out["role"], "TEST_ONLY")
        meta = json.loads((Path(out["dir"]) / "meta.json").read_text(encoding="utf-8"))   # 1.46.0: no provenance stored
        self.assertEqual((meta["data_kind"], meta["role"]), ("SYNTHETIC_TEST", "TEST_ONLY"))
        fs = FS.FlowSections()
        k = fs.update("XAUUSD", "M1", dev[-900:], 0.01, 0.01)
        self.assertIsNotNone(k.m3)                                              # loading unchanged (D23)
        m3 = fs.summary(k)["markov3"]
        self.assertEqual((m3.get("model_role"), m3.get("data_kind")), ("TEST_ONLY", "SYNTHETIC_TEST"))
        (Path(out["dir"]) / "meta.json").unlink()                               # a run of 1.46.0: provenance unknown, still loaded
        k = FS._Key("XAUUSD", "M1", 0.01, 0.01)
        self.assertEqual(k.model_meta["role"], "UNKNOWN")

if __name__ == "__main__":
    unittest.main()
