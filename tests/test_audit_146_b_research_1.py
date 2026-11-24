"""1.46 audit, group B_research_1: research/components.py, research/service.py, research/g7.py, research/etc.py, tsfm/granite_train.py.

chunk_28#14 / focus_X1#5  component ZIP import: unpacked size checked BEFORE anything is read (zip bomb), the checkpoint streamed to disk
                          (hash computed on the fly, same version id as before), a malformed manifest / transform / sdformer_run.json is a
                          ValueError (400) instead of AttributeError / TypeError (500); status() survives a non-dict sdformer_run.json.
chunk_28#15  start_job (TRAIN fine_tune / resume): the checkpoint is a version id directly in the SDformerFlow folder with last.pt -
             also when it comes from a legacy settings.json (active_run).
chunk_28#16  two concurrent ETC OPTIMIZE starts run ONE job (check + registration under the lock).
chunk_28#5   SDformerFlow training asks the Memory Governor with the REAL trading state (AUTO_* -> refused unless confirmed), the profile's
             heavy_allowed (LOW_MEMORY_8GB: SDformerFlow training off) applies, a refused bootstrap is not reported as TRAINING.
chunk_28#6   a bad sdformer setting / an IO error / a Popen error between the governor admission and the process start releases the slot.
chunk_28#7   PUT research-modules/settings: wrong types / ranges of every section are a ValueError (400); active_run must be an existing
             version; a legacy settings.json with an outside active_run is never inferred.
chunk_28#12  predictions(inst) / latest(inst) of an instrument the main context does not compute are not READY records.
chunk_28#13  _activate_sdformer: timeout / unreadable RESULT -> activation FAILED (no exception, no dead training thread); same env flags
             as the live inference.
chunk_28#17  parallel settings writers (panel, optimiser, ETC activation, SDformerFlow activation) lose nothing and never collide on the
             temp file.
chunk_38#3   granite_train.start: an exception after the governor admission (export, argv, process start) releases the training slot.
chunk_28#29  G7 zones: available_at / events at the bar CLOSE (bridge bars carry no tf_s).
chunk_28#23  the SDformerFlow inference file has a stable name per context (no new file after every restart).
chunk_28#30  snapshot generation keeps growing after the 3000-snapshot cap.
All market data below is SYNTHETIC (random walk / hand-made candles); nothing here is a forecast or a backtest."""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

import _env  # noqa: F401
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))


def walk(n: int, seed: int = 7, start: float = 2000.0, step: float = 300.0, t0: float = 1.7e9) -> list[dict]:
    rng = np.random.default_rng(seed)
    c = start + np.cumsum(rng.normal(0, 1.5, n))
    out = []
    for k in range(n):
        o = c[k - 1] if k else c[0]
        h, l_ = max(o, c[k]) + abs(rng.normal(0, 0.8)), min(o, c[k]) - abs(rng.normal(0, 0.8))
        out.append({"t": t0 + k * step, "o": float(o), "h": float(h), "l": float(l_), "c": float(c[k]), "tv": 100.0})
    return out


def zbytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return buf.getvalue()


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def rt(self, mode=None):
        rt = types.SimpleNamespace(demo=True, bridge=None, sh=types.SimpleNamespace(instrument=lambda: "XAUUSD"))
        if mode is not None:
            rt.modes = types.SimpleNamespace(mode=mode)
        return rt

    def svc(self, rt=None):
        from masterquo.research import service as RS
        return RS.ResearchModulesService(rt or self.rt(), data_dir=Path(self.td.dir) / "research")

    def ctx(self, svc, m5=None, h1=None):
        from masterquo.research import service as RS
        m5, h1 = m5 or [], h1 or []
        c = RS.Context("K", "XAUUSD", lambda tf, n=1500: (m5 if tf == "M5" else h1 if tf == "H1" else [])[-n:])
        svc.contexts = {"K": c}
        svc.ensure_main_context = lambda: c
        return c


def h1_bars(n=700):
    return walk(n, step=3600)


# ------------------------------------------------------------------------------------------------------------- chunk_28#14, focus_X1#5
class ComponentImport(_Base):
    def man(self, cid):
        from masterquo.research.components import COMPONENTS
        return json.dumps({"component_id": cid, "implementation_id": COMPONENTS[cid]["implementation_id"]})

    def test_unpacked_size_is_checked_before_anything_is_read(self):
        from masterquo.research import components as CP
        svc = self.svc()
        data = zbytes({"manifest.json": self.man("TH_SDFORMERFLOW"), "last.pt": b"\0" * (3 << 20)})
        self.assertLess(len(data), 64 * 1024)                                     # 3 MB unpacked from a few KB upload
        with mock.patch.object(CP, "MAX_IMPORT_UNPACKED", 1 << 20, create=True), self.assertRaises(ValueError):
            svc.components.import_zip("TH_SDFORMERFLOW", data)
        self.assertEqual(list(svc._sdf_dir().iterdir()), [])                     # nothing written

    def test_checkpoint_is_streamed_with_the_same_version_id(self):
        svc = self.svc()
        blob = os.urandom(200_000)
        meta = {"epochs_done": 3, "ok": True}
        r = svc.components.import_zip("TH_SDFORMERFLOW", zbytes({"manifest.json": self.man("TH_SDFORMERFLOW"), "last.pt": blob,
                                                                  "sdformer_run.json": json.dumps(meta)}))
        self.assertEqual(r["version"], "SDF-IMP-" + hashlib.sha256(blob).hexdigest()[:10])
        d = svc._sdf_dir() / r["version"]
        self.assertEqual((d / "last.pt").read_bytes(), blob)
        self.assertEqual(json.loads((d / "sdformer_run.json").read_text(encoding="utf-8")), meta)
        self.assertEqual([p.name for p in svc._sdf_dir().iterdir()], [r["version"]])      # no temp file left behind
        ver = next(v for v in svc.components.status()["components"][0]["versions"] if v["version"] == r["version"])
        self.assertEqual(ver["epochs_done"], 3)

    def test_malformed_archives_are_value_errors(self):
        etc, sdf = self.man("ETC_LOG_CHANNEL"), self.man("TH_SDFORMERFLOW")
        good_p = {"price": "CLOSE", "window_set": "SHORT", "width": 2.0}
        cases = [
            ("ETC_LOG_CHANNEL", {"manifest.json": "[]", "etc_transform.json": json.dumps({"params": good_p})}),
            ("ETC_LOG_CHANNEL", {"manifest.json": etc, "etc_transform.json": json.dumps({"params": None})}),
            ("ETC_LOG_CHANNEL", {"manifest.json": etc, "etc_transform.json": "[]"}),
            ("ETC_LOG_CHANNEL", {"manifest.json": etc, "etc_transform.json": json.dumps({"params": {**good_p, "width": None}})}),
            ("ETC_LOG_CHANNEL", {"manifest.json": etc, "etc_transform.json": json.dumps({"params": {**good_p, "price": ["CLOSE"]}})}),
            ("ETC_LOG_CHANNEL", {"manifest.json": etc}),
            ("TH_SDFORMERFLOW", {"manifest.json": sdf, "last.pt": b"x", "sdformer_run.json": "[]"}),
            ("TH_SDFORMERFLOW", {"manifest.json": sdf, "last.pt": b"x", "sdformer_run.json": "{not json"}),
            ("TH_SDFORMERFLOW", {"manifest.json": sdf}),
            ("TH_SDFORMERFLOW", {"manifest.json": b"\xff\xfe"}),
        ]
        svc = self.svc()
        for cid, files in cases:
            with self.assertRaises(ValueError, msg=str(files)[:120]):
                svc.components.import_zip(cid, zbytes(files))
        self.assertEqual(list(svc._sdf_dir().iterdir()), [])
        self.assertEqual([v["version"] for v in svc.components.etc_versions()], ["ETC-INITIAL"])

    def test_status_survives_a_non_dict_run_file(self):
        svc = self.svc()
        d = svc._sdf_dir() / "SDF-OLD"
        d.mkdir()
        (d / "last.pt").write_bytes(b"x")
        (d / "sdformer_run.json").write_text("[]", encoding="utf-8")                # written by a 1.45 import
        st = svc.components.status()
        v = st["components"][0]["versions"][0]
        self.assertEqual((v["version"], v["has_checkpoint"], v["epochs_done"]), ("SDF-OLD", True, None))


# ------------------------------------------------------------------------------------------------------------- chunk_28#15
class CheckpointIsAVersion(_Base):
    def test_start_job_accepts_only_versions_in_the_sdf_folder(self):
        svc = self.svc()
        self.ctx(svc, h1=h1_bars())
        calls = []
        svc.start_training = lambda c, h1, **kw: calls.append(kw) or {"ok": True}
        sd = svc._sdf_dir()
        (sd / "SDF-GOOD").mkdir()
        (sd / "SDF-GOOD" / "last.pt").write_bytes(b"x")
        evil = sd.parent / "evil"
        evil.mkdir()
        (evil / "last.pt").write_bytes(b"x")
        for ck in ("../evil", str(evil), 5, "SDF-MISSING", "SDF GOOD"):
            with self.assertRaises(ValueError, msg=repr(ck)):
                svc.components.start_job("TH_SDFORMERFLOW", "TRAIN", {"op": "fine_tune", "checkpoint": ck})
        (svc.base / "settings.json").write_text(json.dumps({"sdformer": {"active_run": "../evil"}}), encoding="utf-8")   # legacy file
        with self.assertRaises(ValueError):
            svc.components.start_job("TH_SDFORMERFLOW", "TRAIN", {"op": "resume"})
        self.assertEqual(calls, [])
        svc.components.start_job("TH_SDFORMERFLOW", "TRAIN", {"op": "fine_tune", "checkpoint": "SDF-GOOD"})
        self.assertEqual(calls[-1]["checkpoint"], str(sd / "SDF-GOOD"))


# ------------------------------------------------------------------------------------------------------------- chunk_28#16
class OneEtcOptimisation(_Base):
    def test_two_concurrent_starts_run_one_job(self):
        svc = self.svc()
        m5 = walk(800)

        def slow_bars(tf, n=1500):
            time.sleep(0.3)                                                        # bridge lock + conversion of 3000 candles
            return m5[-n:] if tf == "M5" else []
        from masterquo.research import service as RS
        c = RS.Context("K", "XAUUSD", slow_bars)
        svc.ensure_main_context = lambda: c
        cp = svc.components
        started, release = [], threading.Event()

        def fake_opt(job, bars, body):
            started.append(job["job_id"])
            release.wait(10)
            job["state"] = "DONE"
        cp._etc_optimize = fake_opt
        res = []
        ths = [threading.Thread(target=lambda: res.append(cp.start_job("ETC_LOG_CHANNEL", "OPTIMIZE", {}))) for _ in range(2)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(10)
        release.set()
        self.assertEqual(sum(1 for r in res if r.get("ok")), 1, res)
        self.assertEqual(len(started), 1)


# ------------------------------------------------------------------------------------------------------------- chunk_28#5, chunk_28#6
class SdformerTrainingAndGovernor(_Base):
    def _svc(self, gov, mode):
        svc = self.svc(self.rt(mode))
        svc.governor = gov
        return svc

    def test_admission_gets_the_real_trading_state(self):
        from masterquo.research import service as RS
        calls = []
        gov = types.SimpleNamespace(admit_training=lambda name, kind, **k: (calls.append(k), (False, "nope"))[1],
                                    training_done=lambda n: None, register=lambda *a, **k: None)
        svc = self._svc(gov, "AUTO_DEMO")
        with mock.patch.object(RS, "torch_python", return_value=sys.executable):
            r = svc.start_training(types.SimpleNamespace(key="K"), [{"t": 1}], op="from_scratch", reason="test")
            self.assertFalse(r["ok"])
            svc.rt.modes.mode = "SIGNALS"
            svc.start_training(types.SimpleNamespace(key="K"), [{"t": 1}], op="from_scratch", reason="test", force=True)
        self.assertEqual([k["trading_active"] for k in calls], [True, False])
        self.assertTrue(calls[1].get("force"))

    def test_real_governor_refuses_during_auto_and_on_the_8gb_profile(self):
        from masterquo.research import service as RS

        from test_resources_governor import gov as mkgov
        popen = mock.MagicMock()
        for profile, total, mode, why in (("LOW_MEMORY_16GB", 16384, "AUTO_LIVE", "AUTO"), ("LOW_MEMORY_8GB", 8192, "SIGNALS", "sdformerflow")):
            g, _ = mkgov(profile=profile, total_mb=total)
            svc = self._svc(g, mode)
            with mock.patch.object(RS, "torch_python", return_value=sys.executable), mock.patch.object(RS.subprocess, "Popen", popen):
                r = svc.start_training(types.SimpleNamespace(key="K"), [{"t": 1}], op="from_scratch", reason="test")
            self.assertFalse(r["ok"], profile)
            self.assertIn(why, r["reason"])
            self.assertEqual(g.training, {})
        popen.assert_not_called()

    def test_refused_bootstrap_is_not_reported_as_training(self):
        from masterquo.research import service as RS
        svc = self.svc()
        c = self.ctx(svc, h1=h1_bars())
        with mock.patch.object(RS, "torch_python", return_value="/x/python"), \
                mock.patch.object(svc, "start_training", return_value={"ok": False, "reason": "RESOURCE: aktywny handel AUTO"}):
            svc._sdformer(c, h1_bars())
        self.assertEqual(c.sdf["state"], "MISSING")
        self.assertIn("AUTO", c.sdf["reason"])

    def test_panel_confirmation_is_forwarded(self):
        svc = self.svc()
        self.ctx(svc, h1=h1_bars())
        calls = []
        svc.start_training = lambda c, h1, **kw: calls.append(kw) or {"ok": True}
        svc.components.start_job("TH_SDFORMERFLOW", "TRAIN", {"op": "from_scratch", "confirm_during_trading": True})
        svc.components.start_job("TH_SDFORMERFLOW", "TRAIN", {"op": "from_scratch"})
        self.assertEqual([k.get("force") for k in calls], [True, False])

    def test_errors_after_admission_release_the_slot(self):
        from masterquo.research import service as RS

        from test_resources_governor import gov as mkgov
        g, _ = mkgov()
        svc = self._svc(g, "SIGNALS")
        ctx = types.SimpleNamespace(key="K")
        (svc.base / "settings.json").write_text(json.dumps({"sdformer": {"epochs": "abc"}}), encoding="utf-8")   # legacy, saved unvalidated
        with mock.patch.object(RS, "torch_python", return_value=sys.executable), mock.patch.object(RS.subprocess, "Popen") as popen:
            r = svc.start_training(ctx, [{"t": 1}], op="from_scratch", reason="test")
            self.assertFalse(r["ok"])
            self.assertEqual(g.training, {})
            popen.assert_not_called()
            (svc.base / "settings.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(RS, "_atomic", side_effect=OSError("disk full")):
                r = svc.start_training(ctx, [{"t": 1}], op="from_scratch", reason="test")
            self.assertFalse(r["ok"])
            self.assertEqual(g.training, {})
            popen.side_effect = ValueError("bad argument")
            r = svc.start_training(ctx, [{"t": 1}], op="from_scratch", reason="test")
            self.assertFalse(r["ok"])
            self.assertEqual(g.training, {})
            self.assertEqual(svc.jobs["sdformer_last"]["state"], "FAILED")
        self.assertTrue(g.admit_training("granite_train", "heavy", trading_active=False)[0])       # the next training can start


# ------------------------------------------------------------------------------------------------------------- chunk_28#7
class SettingsValidation(_Base):
    def test_wrong_types_and_ranges_are_value_errors(self):
        svc = self.svc()
        bad = [{"etc": {"width": None}}, {"etc": "x"}, {"etc": {"price": ["CLOSE"]}}, {"graph": {"cells": None}}, {"graph": "x"},
               {"g7": {"ob_lookback": 10}}, {"g7": {"impulse_factor": 0}}, {"g7": {"corr_periods": 2}}, {"g7": None},
               {"optimizer": {"coa_evals": "x"}}, {"optimizer": {"max_changed": 0}}, {"optimizer": {"deadline_s": float("nan")}},
               {"sdformer": {"epochs": "abc"}}, {"sdformer": {"batch": 0}}, {"sdformer": {"minutes": True}},
               {"sdformer": {"active_run": "../../x"}}, {"sdformer": {"active_run": "SDF-NOT-THERE"}}, {"sdformer": {"active_run": 5}},
               {"modules": {"g7_smc_radar": {"enabled": "no"}}}, {"modules": {"unknown": {"enabled": False}}}, {"modules": []},
               {"enabled": "yes"}]
        for patch in bad:
            with self.assertRaises(ValueError, msg=repr(patch)):
                svc.update_settings(patch)
        self.assertFalse((svc.base / "settings.json").exists())                   # nothing persisted
        d = svc._sdf_dir() / "SDF-20261101T000000"
        d.mkdir()
        (d / "last.pt").write_bytes(b"x")
        s = svc.update_settings({"modules": {"sdformerflow": {"enabled": False}}, "optimizer": {"min_interval_seconds": 0, "coa_evals": 40,
                                                                                               "bchimp_evals": 30}})
        self.assertFalse(s["modules"]["sdformerflow"]["enabled"])
        s = svc.update_settings({"sdformer": {"active_run": "SDF-20261101T000000", "previous_run": None, "epochs": 4}, "g7": {"ob_lookback": 15}})
        self.assertEqual((s["sdformer"]["active_run"], s["g7"]["ob_lookback"]), ("SDF-20261101T000000", 15))

    def test_a_legacy_value_does_not_block_other_sections(self):
        svc = self.svc()
        (svc.base / "settings.json").write_text(json.dumps({"g7": {"ob_lookback": 10}}), encoding="utf-8")
        s = svc.update_settings({"modules": {"bchimp": {"enabled": False}}})
        self.assertFalse(s["modules"]["bchimp"]["enabled"])

    def test_legacy_active_run_outside_the_folder_is_not_used(self):
        from masterquo.research import service as RS
        svc = self.svc()
        evil = svc.base / "evil"
        evil.mkdir()
        (evil / "last.pt").write_bytes(b"x")
        (svc.base / "settings.json").write_text(json.dumps({"sdformer": {"active_run": "../evil"}}), encoding="utf-8")
        c = self.ctx(svc, h1=h1_bars())
        called = []
        svc._sdf_infer = lambda *a: called.append("infer")
        svc.start_training = lambda *a, **k: called.append("train") or {"ok": True}
        with mock.patch.object(RS, "torch_python", return_value="/x/python"):
            svc._sdformer(c, h1_bars())
        self.assertEqual(called, [])
        self.assertEqual(c.sdf["state"], "ERROR")


# ------------------------------------------------------------------------------------------------------------- chunk_28#12
class PredictionsOfTheOwnInstrumentOnly(_Base):
    def test_other_instrument_gets_no_ready_records(self):
        svc = self.svc()
        c = svc.ensure_main_context()
        c.snaps.append({"t": 1.7e9 + 300, "bar_t": 1.7e9, "context": c.key, "generation": 1, "modules": {
            "cellular_feature_graph": {"targets": {"BPC10": {"raw_score": 0.2}}},
            "g7_smc_radar": {"rule_confluence_score": 30.0, "coverage": 0.75, "components": {"net_fvg": 1, "ob_h1": 0}},
            "sdformerflow": {"direction_score_raw": 0.1, "bar_t": 1.7e9 - 3600}}})
        own = svc.predictions("XAUUSD")
        self.assertEqual(len([p for p in own if p["state"] == "READY"]), 3)
        other = svc.predictions("BTC")
        self.assertEqual([p for p in other if p["state"] == "READY"], [])
        self.assertTrue(all(p["instrument"] == "BTC" and p["unavailable_reason"] for p in other))
        self.assertIsNone(svc.latest("BTC"))
        self.assertIs(svc.latest("XAUUSD"), c.snaps[-1])
        self.assertIs(svc.latest(), c.snaps[-1])


# ------------------------------------------------------------------------------------------------------------- chunk_28#13
class SdformerActivation(_Base):
    def test_timeout_and_unreadable_result_are_a_failed_activation(self):
        from masterquo.research import service as RS
        svc = self.svc()
        self.ctx(svc, h1=h1_bars(300))
        seen = []

        def run_timeout(argv, **kw):
            seen.append(kw)
            raise subprocess.TimeoutExpired(argv, 300)
        job = {"job_id": "J1", "base_active": None}
        with mock.patch.object(RS, "torch_python", return_value=sys.executable), mock.patch.object(RS.subprocess, "run", side_effect=run_timeout):
            svc._activate_sdformer("SDF-X", job)
        self.assertEqual(job["activation"]["state"], "FAILED")
        self.assertEqual(seen[0]["env"].get("PYTHONNOUSERSITE"), "1")
        self.assertIn("creationflags", seen[0])
        for out in ("RESULT {not json", "RESULT [1, 2]"):
            job = {"job_id": "J2", "base_active": None}
            with mock.patch.object(RS, "torch_python", return_value=sys.executable), \
                    mock.patch.object(RS.subprocess, "run", return_value=types.SimpleNamespace(stdout=out, stderr="", returncode=0)):
                svc._activate_sdformer("SDF-X", job)
            self.assertEqual(job["activation"]["state"], "FAILED", out)
        self.assertIsNone(svc.settings()["sdformer"]["active_run"])

    def test_activation_error_does_not_kill_the_training_thread(self):
        from masterquo.research import service as RS
        svc = self.svc()
        svc._activate_sdformer = mock.Mock(side_effect=RuntimeError("boom"))
        orig = subprocess.Popen
        with mock.patch.object(RS, "torch_python", return_value=sys.executable), \
                mock.patch.object(RS.subprocess, "Popen", lambda argv, **kw: orig([sys.executable, "-c", "print('RESULT {\"ok\": true, \"run_id\": \"SDF-T\"}')"], **kw)):
            r = svc.start_training(types.SimpleNamespace(key="K"), [{"t": 1}], op="from_scratch", reason="test")
            self.assertTrue(r["ok"], r)
            job = r["job"]
            t0 = time.time()
            while "activation" not in job and time.time() - t0 < 10:
                time.sleep(0.05)
        self.assertEqual(job["state"], "DONE")
        self.assertEqual(job.get("activation", {}).get("state"), "FAILED")
        self.assertIn("boom", job["activation"]["reason"])


# ------------------------------------------------------------------------------------------------------------- chunk_28#17
class ParallelSettingsWriters(_Base):
    def test_no_lost_update_and_no_temp_collision(self):
        from masterquo.research import service as RS
        svc = self.svc()
        errs, n = [], 12

        def toggle(m):
            try:
                for _ in range(n):
                    svc.update_settings({"modules": {m: {"enabled": False}}}, who=m)
            except Exception as exc:  # noqa: BLE001
                errs.append(repr(exc))

        def composite():
            try:
                for k in range(n):
                    svc._set_composite({"version": f"C{k}", "weights": [0.0, 1.0, 0.0, 0.0], "status": "TEST"}, who="opt")
            except Exception as exc:  # noqa: BLE001
                errs.append(repr(exc))
        ths = [threading.Thread(target=toggle, args=(m,)) for m in RS.MODULES] + [threading.Thread(target=composite)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(60)
        self.assertEqual(errs, [])
        s = svc.settings()
        self.assertEqual({m: s["modules"][m]["enabled"] for m in RS.MODULES}, {m: False for m in RS.MODULES})
        self.assertEqual(s["composite"]["version"], f"C{n - 1}")
        hist = json.loads((svc.base / "parameter_history.json").read_text(encoding="utf-8"))
        self.assertEqual(len(hist), n * (len(RS.MODULES) + 1))
        self.assertEqual([p.name for p in svc.base.iterdir() if p.name.endswith(".tmp")], [])

    def test_atomic_writers_of_one_file_do_not_collide(self):
        from masterquo.research import service as RS
        p = Path(self.td.dir) / "x.json"
        errs = []

        def w(k):
            try:
                for i in range(150):
                    RS._atomic(p, {"k": k, "i": i, "pad": "x" * 2000})
            except Exception as exc:  # noqa: BLE001
                errs.append(repr(exc))
        ths = [threading.Thread(target=w, args=(k,)) for k in range(4)]
        for t in ths:
            t.start()
        for t in ths:
            t.join(60)
        self.assertEqual(errs, [])
        self.assertIn(json.loads(p.read_text(encoding="utf-8"))["k"], range(4))


# ------------------------------------------------------------------------------------------------------------- chunk_38#3
class GraniteSlotAfterExportError(_Base):
    def _svc(self):
        from masterquo.tsfm.settings import SettingsStore

        from test_resources_governor import gov as mkgov

        class Log:
            def info(self, *a):
                pass

        class Svc:
            settings = SettingsStore(Path(self.td.dir) / "tsfm" / "settings.json")
            applog = Log()
            _job_procs = {}
        s = Svc()
        s.governor, _ = mkgov()
        s.weights_root = lambda: Path(self.td.dir)
        return s

    def test_exception_after_admission_releases_the_slot(self):
        from masterquo.tsfm import granite_train as G
        svc = self._svc()
        os.environ["MQ_GRANITE_TTM_PYTHON"] = sys.executable
        try:
            with mock.patch.object(G, "export", side_effect=ValueError("could not convert string to float: 'abc'")):
                r = G.start(svc, "XAUUSD", "M5", trading_active=False)
            self.assertFalse(r["ok"])
            self.assertIn("could not convert", r["reason"])
            self.assertEqual(svc.governor.training, {})
            ok_export = {"ok": True, "file": "x.json", "bars": 5200, "first": "a", "last": "b", "sha256": "h", "data_kind": "MT5_DEMO"}
            svc._run_job_proc = mock.Mock(side_effect=RuntimeError("spawn failed"))
            with mock.patch.object(G, "export", return_value=ok_export):
                r = G.start(svc, "XAUUSD", "M5", trading_active=False)
            self.assertFalse(r["ok"])
            self.assertEqual(svc.governor.training, {})
            svc._run_job_proc = mock.Mock(return_value={"ok": True, "job": {"state": "RUNNING"}})
            with mock.patch.object(G, "export", return_value=ok_export):
                r = G.start(svc, "XAUUSD", "M5", trading_active=False)
            self.assertTrue(r["ok"], r)                                            # slot free again -> admitted
            self.assertEqual(svc.governor.training, {"granite_train": "heavy"})      # held by the running process (released on_done)
        finally:
            os.environ.pop("MQ_GRANITE_TTM_PYTHON", None)


# ------------------------------------------------------------------------------------------------------------- chunk_28#29
class ZonesAtBarClose(unittest.TestCase):
    def test_available_at_and_events_use_the_close(self):
        from masterquo.research import g7 as G7
        t0 = 1.7e9
        bars = [{"t": t0, "o": 10.0, "h": 10.0, "l": 9.0, "c": 9.5},
                {"t": t0 + 300, "o": 9.5, "h": 10.0, "l": 9.0, "c": 9.8},
                {"t": t0 + 600, "o": 9.6, "h": 11.0, "l": 9.5, "c": 10.9},
                {"t": t0 + 900, "o": 10.5, "h": 12.0, "l": 10.5, "c": 11.8}]          # low[1] 10.5 > high[3] 10.0 -> bullish FVG 10.0..10.5
        zb = G7.ZoneBook("XAUUSD")
        zb.observe("M5", bars)
        self.assertEqual(len(zb.zones), 1)
        z = next(iter(zb.zones.values()))
        self.assertEqual(z["available_at"], bars[-1]["t"] + 300)
        self.assertEqual(zb.asof(bars[-1]["t"] + 299), [])                       # not known before the bar that formed it closed
        self.assertEqual(len(zb.asof(bars[-1]["t"] + 300)), 1)
        touch = {"t": t0 + 1200, "o": 11.0, "h": 11.2, "l": 10.2, "c": 10.8}          # dips into the gap 10.0..10.5, closes above it
        zb.observe("M5", bars[1:] + [touch])
        self.assertEqual(z["events"][-1], {"t": touch["t"] + 300, "event": "TOUCHED"})
        self.assertEqual(zb.asof(touch["t"] + 299)[0]["state"], "ACTIVE")
        self.assertEqual([x["state"] for x in zb.asof(touch["t"] + 300) if x["zone_id"] == z["zone_id"]], ["TOUCHED"])
        zb15 = G7.ZoneBook("XAUUSD")
        zb15.observe("M15", [{**b, "t": t0 + 900 * k} for k, b in enumerate(bars)])
        self.assertEqual(next(iter(zb15.zones.values()))["available_at"], t0 + 900 * 3 + 900)


# ------------------------------------------------------------------------------------------------------------- chunk_28#23
class StableInferenceFile(_Base):
    def test_name_does_not_depend_on_the_process_hash_seed(self):
        from masterquo.research import service as RS
        svc = self.svc()
        c = RS.Context("FOREX_MT5|MT5|SYNTHETIC|ACCOUNT|CFD|XAUUSD-", "XAUUSD", lambda *a, **k: [])
        seen = []
        with mock.patch.object(RS.subprocess, "run", side_effect=lambda argv, **kw: seen.append(argv) or
                               types.SimpleNamespace(stdout="", stderr="x", returncode=1)):
            svc._sdf_infer(c, [{"t": 1.0}], sys.executable, "SDF-X")
        bars_arg = Path(seen[0][seen[0].index("--bars") + 1])
        self.assertEqual(bars_arg.name, f"infer_{hashlib.sha256(c.key.encode()).hexdigest()[:12]}.json")


# ------------------------------------------------------------------------------------------------------------- chunk_28#30
class GenerationKeepsGrowing(_Base):
    def test_after_the_cap(self):
        from masterquo.research import service as RS
        svc = self.svc()
        svc.update_settings({"modules": {m: {"enabled": False} for m in RS.MODULES}, "optimizer": {"enabled": False}})
        m5 = walk(100)
        st = {"n": 50}
        c = self.ctx(svc)
        c.bars_fn = lambda tf, n=1500: m5[:st["n"]][-n:] if tf == "M5" else []
        c.snaps = [{"t": 0.0, "bar_t": 0.0, "generation": k + 1, "modules": {}} for k in range(3000)]
        c.gen = 3000                                                               # 3000 cycles so far
        gens = []
        for k in range(3):
            st["n"] = 50 + k
            svc._cycle_ctx(c)
            gens.append(c.snaps[-1]["generation"])
        self.assertEqual(gens, [3001, 3002, 3003])
        self.assertEqual(len(c.snaps), 3000)


if __name__ == "__main__":
    unittest.main()
