"""1.46 arch, fala 2 - grupa „tsfm” (Chronos-2 / Granite TTM / TiRex-2, TabICLv2 runtime): testy regresji pozycji

I0200 (+I0204)  błąd CUDA w predict: proces zostawał na zepsutym GPU, błąd przy każdej świecy - teraz restart na CPU (tylko po
                potwierdzonym trwałym błędzie kontekstu CUDA); prognoza awaryjna jest WYŁĄCZNIE do wstrzymań w odbiorniku SH (REQUIRED
                nadal czeka, ASSIST SH może wstrzymać); wiersz kontraktu (Quant/prezentacja) i wiersze ACTIVE koordynatora (każda rola,
                także REQUIRED z config.json decision.required_models - uwaga recenzenta S0) nadal niedostępne jak dziś
I0201           docstringi tsfm_runtime / service: TiRex-2 aktywny, FinCast tylko jako wycofany
I0205           Granite TTM: zła konfiguracja (context_len ≠ 512, profil, lookback < 512, horyzont > 96) odrzucana przy zapisie;
                istniejący plik -> stan CONFIG procesu tylko gdy model nie odpowiada na ŻADEN cel (context_len < 512, lookback < 512,
                profil), horyzont > 96 = CONFIG tylko tego celu (uwaga recenzenta S0: pozostałe TF i ich wstrzymania ASSIST jak dziś)
I0207           TiRex2Engine: load / predict / _direct / selftest na podstawionych modułach tirex2 + torch (+ wariant z prawdziwym
                TiRex-2 pod MQ_TIREX2_PYTHON + MQ_TSFM_WEIGHTS_ROOT, bez środowiska SKIP)
I0213           TabICLv2 z prawdziwym tabicl i checkpointem (proces tabicl_runtime.worker; bez .venv_tabicl / wag SKIP)
I0540           tabicl_runtime.engine.Engine: walidacje fit / predict / selftest na podstawionych modułach tabicl + torch
I0834 / I0844   checkpoint Granite poza zakresem dotrenowania (instrument / TF / horyzont): prognoza nie może POTWIERDZIĆ roli
                REQUIRED - z ustawień TSFM i z config.json decision.required_models (ASSIST i wejścia Quant bez zmian - wariant
                wyłącznie zaostrzający)
I0835           approval_ok: REQUIRED bez raportu dopuszczenia DLA TEGO instrumentu -> nieaktualne (ASSIST bez zmian)
I0836           ścieżka ACTIVE: REQUIRED przy wyłączonym modelu / instrumencie / TF / braku prognozy -> wiersz niedostępny (jak SH)
I0845           werdykt dotrenowania IMPROVED_VS_BASE tylko przy >= 100 oknach testowych (INSUFFICIENT_TEST), aktywacja też to sprawdza
P001            komunikat CHECKSUM rozmiaru podaje rozmiar przypięty (nie 'rozmiar 2 B ≠ 2 B z manifestu')
P002            offline verify() porównuje git blob sha1 plików przypiętych tak (config.json / LICENSE / NOTICE) z lock.py

Procesy modeli w testach usługi to TEST DOUBLE (tests/tsfm_stub_worker.py) - ich liczby nie są prognozami."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import _env
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kronos_testkit as K
from test_tsfm_bot import POSIX, WED_1200, fixture_weights, stub_python

BACKEND = _env.ROOT / "backend"


# ======================================================================================================== service fixture (stub workers)
class _Svc(unittest.TestCase):
    """Real TsfmService, stub model processes (tests/tsfm_stub_worker.py), fake MT5 bridge with M5 + M15 bars, isolated data dir."""

    def setUp(self):
        # the model environment variables (env_all.sh: MQ_<MODEL>_PYTHON) win over python_path in find_python - the stub worker of
        # these tests must be the process, so they are removed for the duration of each test (restored afterwards)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        for m in ("CHRONOS2", "GRANITE_TTM", "TIREX2"):
            os.environ.pop(f"MQ_{m}_PYTHON", None)
        self.td = TempData()
        self.dir = Path(self.td.dir)
        os.environ["MQ_TSFM_ALLOW_FIXTURE"] = "1"
        self.bridge = K.FakeBridge({("XAUUSD-", "M5"): K.make_bars(300, WED_1200, 10), ("XAUUSD-", "M15"): K.make_bars(900, WED_1200, 20)})
        self.cfg = K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-")}))
        self.svc = None

    def tearDown(self):
        os.environ.pop("MQ_TSFM_ALLOW_FIXTURE", None)
        if self.svc is not None:
            self.svc.stop()
        self.td.close()

    def make(self, mode="ok", tfs=("M5",), pre: dict | None = None, **models):
        from masterquo.db.database import Database
        from masterquo.tsfm.service import TsfmService
        from masterquo.tsfm.settings import SettingsStore
        p = self.dir / "tsfm" / "settings.json"
        if pre is not None:                                       # a settings file that already exists on disk (written by an older build)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(pre), encoding="utf-8")
        st = SettingsStore(p)
        root = self.dir / "w"
        for m in ("chronos2", "granite_ttm"):
            fixture_weights(root, m)
        py = stub_python(self.dir, mode)
        mc = {m: {"python_path": py, "timeframes": list(tfs), "instruments": ["XAUUSD"], "request_timeout_s": 5.0, **models.get(m, {})}
              for m in ("chronos2", "granite_ttm", "tirex2")}
        st.update({"weights_root": str(root), "models": mc})
        self.svc = TsfmService(self.cfg, self.bridge, Database(self.dir / "t.sqlite"), K.Bus(), K.Log(), clock=lambda: WED_1200, settings=st)
        return self.svc

    def run_queue(self):
        out = []
        while self.svc.queue:
            _k, job = self.svc.queue.popitem(last=False)
            out.append(self.svc.run_job(job))
        return out

    def approve(self, mid: str, path: str, tf: str, use: str = "REQUIRED", inst: str = "XAUUSD") -> str:
        """A positive walk-forward report bound to the CURRENT settings + the role written as set_use would (VALIDATION policy)."""
        from masterquo.tsfm import validation as V
        rep = V._save({"schema": V.SCHEMA, "instrument": inst, "timeframe": tf, "status": "DONE", "bindings": {mid: V.binding(self.svc, mid, inst, tf)},
                       "models": {mid: {"verdict": {"positive": True, "reason": "test"}}}})
        self.svc.settings.update({"models": {mid: {"use": {path: {"use": use, "timeframe": tf, "validation_report": rep["report_id"],
                                                                  "confirmed_at": "2026-11-24T00:00:00Z", "activation_policy": "VALIDATION"}}}}})
        return rep["report_id"]

    @staticmethod
    def ev(rows, side, required=()):
        from masterquo.decision.coordinator import evaluate_models
        return evaluate_models(rows, side, required=set(required), assist_threshold=0.6, max_age_s=10 ** 9, now=WED_1200 + 60)

    def required_models(self, *ids):
        """decision.required_models of config.json (the coordinator's second source of the REQUIRED role - role_of)."""
        self.cfg.get().decision = types.SimpleNamespace(enabled=True, required_models=list(ids), required_max_age_s=10 ** 9, assist_on_active=True)


# ======================================================================================================== I0200 (+I0204) GPU -> CPU
GPU_ERR = {"ok": False, "code": "EXCEPTION", "error": "AcceleratorError: CUDA error: an illegal memory access was encountered"}


class _GpuSvc(_Svc):
    def _gpu_broken(self, w, healthy=False, record=None):
        orig = w.ask

        def ask(req, timeout):
            if record is not None:
                record.append(req["cmd"])
            if req["cmd"] == "predict":
                return dict(GPU_ERR)
            if req["cmd"] == "cuda_check":
                return {"ok": True, "device": "cuda:0", "healthy": healthy, "error": None if healthy else GPU_ERR["error"]}
            return orig(req, timeout)
        w.ask = ask
        return orig

    def _loaded_on_gpu(self, svc):
        svc.tick()
        self.run_queue()
        w = svc.workers["chronos2"]
        self.assertEqual(w.state["status"], "READY")
        w.load_info["device"] = "cuda:0"                         # the stub reports cpu; the real engine reports the torch device
        return w

    def _fallback_forecast(self, **models):
        """chronos2 on a GPU whose CUDA context breaks -> replaced by the CPU process -> a READY fallback forecast (direction UP)."""
        svc = self.make(tfs=("M5",), chronos2={"use": {"ACTIVE": {"timeframe": "M5"}}, **models})
        w = self._loaded_on_gpu(svc)
        orig = self._gpu_broken(w)
        svc.refresh("chronos2", "XAUUSD", "M5")
        self.run_queue()
        w.ask, w.retry_at = orig, 0.0
        svc.refresh("chronos2", "XAUUSD", "M5")
        self.run_queue()
        self.assertTrue(w.load_info["gpu_fallback"])
        self.assertEqual(svc.latest[("chronos2", "XAUUSD", "M5")]["direction"], "UP")
        return svc, w


@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell wrapper")
class TestI0200GpuFallback(_GpuSvc):
    def test_sticky_cuda_error_restarts_the_process_on_cpu(self):
        from masterquo.tsfm import predictions as TP
        svc = self.make()
        w = self._loaded_on_gpu(svc)
        orig = self._gpu_broken(w)
        self.assertTrue(svc.refresh("chronos2", "XAUUSD", "M5")["ok"])
        self.run_queue()
        # before the fix: EXCEPTION -> only ms ERROR, the broken GPU process stayed (READY) and failed again at every bar
        self.assertEqual((w.state["status"], w.state["code"]), ("ERROR", "GPU_ERROR"), w.state)
        self.assertIsNone(w.proc)
        self.assertIn("CUDA", (w.gpu_fallback or {}).get("reason", ""))
        loads = []

        def rec(req, timeout):
            if req["cmd"] == "load":
                loads.append(dict(req))
            return orig(req, timeout)
        w.ask, w.retry_at = rec, 0.0
        self.assertTrue(svc.refresh("chronos2", "XAUUSD", "M5")["ok"])
        self.run_queue()
        self.assertEqual([x["device"] for x in loads], ["CPU"])                  # the replacement process runs on CPU
        self.assertTrue(w.load_info["gpu_fallback"])
        self.assertTrue(w.load_info["device_note"].startswith("GPU_ERROR_FALLBACK_CPU"))
        fc = svc.latest[("chronos2", "XAUUSD", "M5")]
        self.assertEqual(fc["use_restriction"]["code"], "GPU_FALLBACK_CPU")
        # contract row (Quant FEAT-2 inputs, presentation): unavailable exactly as during the GPU error - Quant inputs unchanged
        row = next(r for r in TP.contract_predictions(svc, "XAUUSD") if r["model_id"] == "tsfm:chronos2" and r["timeframe"] == "M5")
        self.assertEqual((row["state"], row["result"]), ("STALE", None))
        self.assertIn("GPU", row["unavailable_reason"])
        # the process lives as long as the broken GPU process would have: any later kill -> the configured device again (as today)
        w.kill()
        self.assertIsNone(w.gpu_fallback)
        loads.clear()
        w.retry_at = 0.0
        self.assertTrue(w.ensure())
        self.assertEqual([x["device"] for x in loads], ["AUTO"])

    def test_fallback_forecast_only_holds(self):
        """Entry direction: REQUIRED is not satisfied by the CPU fallback (today: ERROR -> WAIT / MODEL_REQUIRED_UNAVAILABLE - unchanged);
        SH ASSIST may hold on a contrary fallback forecast (today: no forecast -> no hold) = only fewer entries; the ACTIVE rows stay
        unavailable for EVERY role exactly as during today's GPU error (review: the REQUIRED role can also come from config.json)."""
        from masterquo.tsfm import predictions as TP
        svc, _w = self._fallback_forecast()
        self.approve("chronos2", "SCALPING", "M5")
        ctx = TP.context(svc, "chronos2", "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual((ctx["available"], ctx["state"]), (False, "GPU_FALLBACK_CPU"))
        self.assertEqual(TP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)["status"], "WAIT")
        self.approve("chronos2", "ACTIVE", "M5")
        rows = [r for r in TP.coordinator_rows(svc, "XAUUSD") if r["family"] == "tsfm:chronos2"]
        self.assertEqual([(r["use"], r["state"]) for r in rows], [("REQUIRED", "STALE")])
        self.assertEqual(self.ev(rows, "BUY")[1], ["MODEL_REQUIRED_UNAVAILABLE:tsfm:chronos2"])
        self.assertTrue(svc.set_use("chronos2", "HEDGING", "ASSIST", timeframe="M5", confirm=True)["ok"])
        ctx = TP.context(svc, "chronos2", "XAUUSD", "HEDGING", side="SELL")
        self.assertEqual(TP.apply_to_setup({"status": "READY", "side": "SELL"}, ctx)["status"], "WAIT")    # contrary fallback holds
        self.assertTrue(svc.set_use("chronos2", "ACTIVE", "ASSIST", timeframe="M5", confirm=True)["ok"])
        rows = [r for r in TP.coordinator_rows(svc, "XAUUSD") if r["family"] == "tsfm:chronos2"]
        self.assertEqual([(r["use"], r["state"], r["result"]) for r in rows], [("ASSIST", "STALE", None)])    # as today's ERROR row
        self.assertIn("GPU", rows[0]["unavailable_reason"])
        self.assertEqual(self.ev(rows, "SELL")[1], [])                                    # no hold - exactly as today (no forecast)

    def test_transient_error_keeps_todays_behaviour(self):
        svc = self.make()
        w = self._loaded_on_gpu(svc)
        cmds = []
        self._gpu_broken(w, healthy=True, record=cmds)
        proc = w.proc
        svc.refresh("chronos2", "XAUUSD", "M5")
        self.run_queue()
        self.assertEqual(cmds, ["predict", "cuda_check"])
        self.assertIs(w.proc, proc)                              # CUDA context healthy -> the process stays, the next bar retries on GPU
        self.assertIsNone(w.gpu_fallback)
        self.assertEqual(w.state["status"], "READY")
        self.assertEqual(svc.mstate[("chronos2", "XAUUSD", "M5")]["state"], "ERROR")

    def test_cpu_exception_is_not_a_gpu_error(self):
        svc = self.make()
        svc.tick()
        self.run_queue()
        w = svc.workers["chronos2"]                              # device cpu (stub)
        cmds = []
        self._gpu_broken(w, record=cmds)
        svc.refresh("chronos2", "XAUUSD", "M5")
        self.run_queue()
        self.assertEqual(cmds, ["predict"])                      # no CUDA check, no restart - exactly as before
        self.assertIsNone(w.gpu_fallback)
        self.assertIsNotNone(w.proc)

    def test_device_setting_change_clears_the_fallback(self):
        svc = self.make()
        w = self._loaded_on_gpu(svc)
        orig = self._gpu_broken(w)
        svc.refresh("chronos2", "XAUUSD", "M5")
        self.run_queue()
        self.assertIsNotNone(w.gpu_fallback)
        svc.settings.update({"models": {"chronos2": {"device": "CUDA"}}})
        w.ask, w.retry_at = orig, 0.0
        self.assertTrue(w.ensure())
        self.assertIsNone(w.gpu_fallback)
        self.assertFalse(w.load_info.get("gpu_fallback"))


@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell wrapper")
class TestI0200ReviewRequiredModels(_GpuSvc):
    """Review (S0): the coordinator gives the REQUIRED role ALSO through config.json decision.required_models ('tsfm:<model>', role_of).
    With the TSFM role OBSERVE / ASSIST the fallback row was READY and that REQUIRED PASSED - today the broken GPU process answers ERROR
    at every bar -> MODEL_REQUIRED_UNAVAILABLE. The ACTIVE rows of a fallback forecast are now unavailable for every role (as today)."""

    def _gate(self, svc, side="BUY"):
        from masterquo.decision.coordinator import DecisionCoordinator
        from masterquo.tsfm import predictions as TP
        dc = DecisionCoordinator(svc.db, self.cfg, instrument_fn=lambda: "XAUUSD", clock=lambda: WED_1200 + 60)
        dc.extra_providers = [lambda inst: TP.coordinator_rows(svc, inst)]
        return dc.model_gate_active({"direction": "LONG" if side == "BUY" else "SHORT"})

    def test_required_models_with_observe_role(self):
        svc, _w = self._fallback_forecast()
        self.required_models("tsfm:chronos2")
        g = self._gate(svc, "BUY")
        self.assertEqual(g["codes"], ["MODEL_REQUIRED_UNAVAILABLE:tsfm:chronos2"])   # before: [] (REQUIRED PASS) = a new ACTIVE entry
        m = next(x for x in g["models"] if x["model_id"] == "tsfm:chronos2")
        self.assertEqual((m["role"], m["state"], m["influence"]), ("REQUIRED", "STALE", "BLOCK"))

    def test_required_models_with_assist_role(self):
        svc, _w = self._fallback_forecast()
        self.assertTrue(svc.set_use("chronos2", "ACTIVE", "ASSIST", timeframe="M5", confirm=True)["ok"])
        self.required_models("tsfm:chronos2")
        for side in ("BUY", "SELL"):
            self.assertEqual(self._gate(svc, side)["codes"], ["MODEL_REQUIRED_UNAVAILABLE:tsfm:chronos2"], side)

    def test_healthy_forecast_and_required_models_unchanged(self):
        svc = self.make(tfs=("M5",), chronos2={"use": {"ACTIVE": {"timeframe": "M5"}}})
        svc.tick()
        self.run_queue()
        self.required_models("tsfm:chronos2")
        self.assertEqual(self._gate(svc, "BUY")["codes"], [])                         # a normal forecast UP confirms BUY (as today)
        self.assertEqual(self._gate(svc, "SELL")["codes"], ["MODEL_REQUIRED_CONTRARY:tsfm:chronos2"])

    def test_key_change_during_the_fallback_restarts_once_on_the_configured_device(self):
        svc, w = self._fallback_forecast()
        loads = []
        orig = w.ask

        def rec(req, timeout):
            if req["cmd"] == "load":
                loads.append(req["device"])
            return orig(req, timeout)
        w.ask = rec
        n = 1 if svc.threads_for("chronos2", svc.settings.get().models["chronos2"]) != 1 else 2
        svc.settings.update({"models": {"chronos2": {"cpu_threads": n}}})       # a new process key (e.g. threads of a governor profile)
        self.assertTrue(w.ensure())
        self.assertTrue(w.ensure())
        # before: ["CPU", "AUTO"] - kill() ended the fallback, the new process still started on CPU marked as a fallback, and the
        # next ensure() restarted it again on the configured device
        self.assertEqual(loads, ["AUTO"])
        self.assertIsNone(w.gpu_fallback)
        self.assertFalse(w.load_info.get("gpu_fallback"))


class TestI0200CudaCheck(unittest.TestCase):
    def test_engine_cuda_check(self):
        from tsfm_runtime import engines as E
        self.assertTrue(E.cuda_check("cpu")["healthy"])

        class Boom:
            @staticmethod
            def ones(*a, **k):
                raise RuntimeError("CUDA error: an illegal memory access was encountered")
        with mock.patch.dict(sys.modules, {"torch": Boom}):
            r = E.cuda_check("cuda:0")
        self.assertFalse(r["healthy"])
        self.assertIn("illegal memory access", r["error"])

    def test_gpu_error_signature(self):
        from masterquo.tsfm import service as S
        for txt in (GPU_ERR["error"], "OutOfMemoryError: CUDA out of memory. Tried to allocate", "cuDNN error: CUDNN_STATUS_INTERNAL_ERROR",
                    "RuntimeError: CUBLAS_STATUS_EXECUTION_FAILED", "device-side assert triggered"):
            self.assertTrue(S.gpu_error(txt), txt)
        for txt in ("ValueError: shapes (1,512) and (2,) not aligned", None, ""):
            self.assertFalse(S.gpu_error(txt), txt)


# ======================================================================================================== I0201 docstrings
class TestI0201Docstrings(unittest.TestCase):
    def test_active_models_and_fincast_retired(self):
        import importlib
        for name in ("tsfm_runtime", "tsfm_runtime.manifest", "tsfm_runtime.install", "tsfm_runtime.engines", "tsfm_runtime.worker",
                     "masterquo.tsfm.service"):
            doc = importlib.import_module(name).__doc__ or ""
            head = doc.split("\n\n")[0]
            for model in ("Chronos-2", "Granite TTM", "TiRex-2"):
                self.assertIn(model, head, name)
            self.assertNotIn(".venv_fincast", doc, name)
            if "FinCast" in doc:
                self.assertRegex(doc, r"FinCast[^.]{0,60}(wycofany|RETIRED|retired)", name)


# ======================================================================================================== I0205 Granite configuration
class TestI0205GraniteConfigOnSave(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.tsfm.settings import SettingsStore
        self.p = Path(self.td.dir) / "tsfm" / "settings.json"
        self.SS = SettingsStore

    def tearDown(self):
        self.td.close()

    def test_bad_granite_config_is_refused(self):
        st = self.SS(self.p)
        for patch, why in (({"models": {"granite_ttm": {"context_len": 256}}}, "512"),
                           ({"models": {"granite_ttm": {"profile": "CLOSE_OHLCV_PAST_V1"}}}, "CLOSE_V1"),
                           ({"lookback": 300}, "lookback"),
                           ({"horizon_bars": {"M5": 120}}, "96")):
            with self.assertRaises(ValueError) as cm:                       # before: accepted -> WARMUP / PROFILE_UNSUPPORTED at every bar
                st.update(patch)
            self.assertIn(why, str(cm.exception), patch)
            self.assertIn("GRANITE_CONFIG", str(cm.exception))
        s = st.get()
        self.assertEqual((s.models["granite_ttm"].context_len, s.lookback), (512, 560))           # nothing written
        st.update({"models": {"chronos2": {"context_len": 1024, "profile": "CLOSE_OHLCV_PAST_V1"}}})   # other models: no such limit
        st.update({"horizon_bars": {"H1": 120}})                                                     # TF Granite does not compute

    def test_disabled_granite_is_not_checked_until_enabled(self):
        st = self.SS(self.p)
        st.update({"models": {"granite_ttm": {"enabled": False}}})
        st.update({"models": {"granite_ttm": {"context_len": 256}}})
        with self.assertRaises(ValueError):
            st.update({"models": {"granite_ttm": {"enabled": True}}})

    def test_existing_bad_file_loads_and_unrelated_changes_pass(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        self.p.write_text(json.dumps({"models": {"granite_ttm": {"context_len": 256}}}), encoding="utf-8")
        st = self.SS(self.p)
        self.assertIsNone(st.load_error)                                   # the file contract is unchanged on read
        self.assertEqual(st.get().models["granite_ttm"].context_len, 256)
        st.update({"models": {"chronos2": {"enabled": False}}})              # an unrelated change is not blocked by the old value
        with self.assertRaises(ValueError):
            st.update({"models": {"granite_ttm": {"context_len": 300}}})   # another wrong value: refused
        st.update({"models": {"granite_ttm": {"context_len": 512}}})       # repair: accepted


@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell wrapper")
class TestI0205GraniteConfigState(_Svc):
    def test_config_state_and_no_worker_call(self):
        from masterquo.tsfm import predictions as TP
        svc = self.make(pre={"models": {"granite_ttm": {"context_len": 256}}})
        svc.tick()
        self.assertEqual(set(svc.queue), {("chronos2", "XAUUSD", "M5")})    # before: granite queued -> WARMUP from the model at every bar
        ms = svc.mstate[("granite_ttm", "XAUUSD", "M5")]
        self.assertEqual(ms["state"], "CONFIG")
        self.assertIn("512", ms["reason"])
        w = svc.workers["granite_ttm"]
        self.assertIsNone(w.proc)                                          # the model process is never asked
        self.assertEqual((w.state["status"], w.state["code"]), ("CONFIG", "CONFIG"))
        self.run_queue()
        row = next(r for r in TP.contract_predictions(svc, "XAUUSD") if r["model_id"] == "tsfm:granite_ttm")
        self.assertEqual((row["state"], row["result"]), ("ERROR", None))   # the same class as today's model error: decisions unchanged
        self.assertIn("512", row["unavailable_reason"])
        svc.settings.update({"models": {"granite_ttm": {"context_len": 512}}})
        self.assertTrue(svc.refresh("granite_ttm", "XAUUSD", "M5")["ok"])     # repaired: queued again (state back to IDLE)
        self.assertIn(("granite_ttm", "XAUUSD", "M5"), svc.queue)
        self.assertEqual(w.state["status"], "IDLE")


class TestI0205ReviewProcessLevel(unittest.TestCase):
    def test_process_level_only_where_the_model_never_answers(self):
        from masterquo.tsfm.settings import (
            TsfmSettings,
            process_config_problems,
            target_config_problems,
        )

        def S(**kw):
            return TsfmSettings.model_validate(kw)
        self.assertEqual(process_config_problems(S(), "granite_ttm"), [])
        for kw in ({"models": {"granite_ttm": {"context_len": 256}}}, {"lookback": 300},
                   {"models": {"granite_ttm": {"profile": "CLOSE_OHLCV_PAST_V1"}}}):
            self.assertTrue(process_config_problems(S(**kw), "granite_ttm"), kw)          # WARMUP / PROFILE_UNSUPPORTED at every bar today
        for kw in ({"models": {"granite_ttm": {"context_len": 1024}}, "lookback": 512},       # effective context 512: computed today
                   {"models": {"granite_ttm": {"context_len": 1024}}},                        # 512 bars in the window: computed today
                   {"horizon_bars": {"M15": 100}}):                                           # only the M15 target fails today
            self.assertEqual(process_config_problems(S(**kw), "granite_ttm"), [], kw)
        self.assertIn("96", target_config_problems(S(horizon_bars={"M15": 100}), "granite_ttm", "M15")[0])
        self.assertEqual(target_config_problems(S(horizon_bars={"M15": 100}), "granite_ttm", "M5"), [])
        self.assertEqual(process_config_problems(S(models={"chronos2": {"context_len": 256}}), "chronos2"), [])
        self.assertEqual(target_config_problems(S(horizon_bars={"M15": 100}), "chronos2", "M15"), [])


@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell wrapper")
class TestI0205ReviewPartialConfig(_Svc):
    """Review (S0): the whole Granite TTM in CONFIG also for settings it partly answers today - its other forecasts and their ASSIST
    holds disappeared. Now CONFIG of the PROCESS only where it never answers; horizon > 96 is a CONFIG of that target only."""

    def test_horizon_above_96_on_one_timeframe_keeps_the_others(self):
        from masterquo.tsfm import predictions as TP
        svc = self.make(tfs=("M5", "M15"), pre={"horizon_bars": {"M15": 100}})       # a file accepted until 1.46 (horizon 1..128)
        svc.tick()
        w = svc.workers["granite_ttm"]
        self.assertNotEqual(w.state["status"], "CONFIG")                              # before the review fix: CONFIG - no forecast at all
        self.assertIn(("granite_ttm", "XAUUSD", "M5"), svc.queue)
        self.assertNotIn(("granite_ttm", "XAUUSD", "M15"), svc.queue)                 # the model is never asked for H 100
        ms = svc.mstate[("granite_ttm", "XAUUSD", "M15")]
        self.assertEqual(ms["state"], "CONFIG")
        self.assertIn("96", ms["reason"])
        self.run_queue()
        self.assertEqual(svc.latest[("granite_ttm", "XAUUSD", "M5")]["direction"], "UP")
        rows = {r["timeframe"]: r for r in TP.contract_predictions(svc, "XAUUSD") if r["model_id"] == "tsfm:granite_ttm"}
        self.assertEqual(rows["M5"]["state"], "READY")
        self.assertEqual((rows["M15"]["state"], rows["M15"]["result"]), ("ERROR", None))   # as today's CONFIG answer of the model
        self.assertIn("96", rows["M15"]["unavailable_reason"])
        self.assertTrue(svc.set_use("granite_ttm", "SCALPING", "ASSIST", timeframe="M5", confirm=True)["ok"])
        ctx = TP.context(svc, "granite_ttm", "XAUUSD", "SCALPING", side="SELL")
        self.assertEqual(TP.apply_to_setup({"status": "READY", "side": "SELL"}, ctx)["status"], "WAIT")   # the ASSIST hold as today
        svc.settings.update({"horizon_bars": {"M15": 8}})                             # repaired: the target is computed again
        svc.refresh("granite_ttm", "XAUUSD", "M15")
        self.assertIn(("granite_ttm", "XAUUSD", "M15"), svc.queue)

    def test_context_above_512_with_lookback_512_is_computed(self):
        svc = self.make(pre={"lookback": 512, "models": {"granite_ttm": {"context_len": 1024}}})
        svc.tick()
        self.assertNotEqual(svc.workers["granite_ttm"].state["status"], "CONFIG")   # before the review fix: CONFIG (context_len != 512)
        self.assertIn(("granite_ttm", "XAUUSD", "M5"), svc.queue)
        self.run_queue()
        self.assertEqual(svc.latest[("granite_ttm", "XAUUSD", "M5")]["state"], "READY")

    def test_sh_model_status_shows_the_config_state(self):
        from masterquo.sh import models as SM
        svc = self.make(pre={"models": {"granite_ttm": {"context_len": 256}}})
        svc.tick()
        it = next(x for x in SM.REGISTRY if x["id"] == "granite_ttm")
        st = SM.probe(it, types.SimpleNamespace(tsfm=svc), "XAUUSD")
        self.assertEqual(st["status"], "ERROR")                                       # before: SHADOW_ONLY ('przetrenowany model ...')
        self.assertIn("512", st["reason"])
        self.assertEqual(st["detail"]["service"], "CONFIG")


# ======================================================================================================== I0207 TiRex2Engine
class _FT:
    """Fake torch tensor (numpy inside)."""

    def __init__(self, arr):
        import numpy as np
        self.arr = np.asarray(arr)

    def unsqueeze(self, d):
        return _FT(self.arr[None] if d == 0 else self.arr[..., None])

    def reshape(self, *s):
        return _FT(self.arr.reshape(*s))

    def double(self):
        return _FT(self.arr.astype("float64"))

    def cpu(self):
        return self

    def numpy(self):
        return self.arr


def fake_torch(cuda: bool = False):
    import numpy as np
    t = types.ModuleType("torch")
    t._dynamo = types.SimpleNamespace(config=types.SimpleNamespace(disable=False))
    t.float32 = "float32"
    t._threads = [1]
    t.set_num_threads = lambda n: t._threads.__setitem__(0, int(n))
    t.get_num_threads = lambda: t._threads[0]
    t.cuda = types.SimpleNamespace(is_available=lambda: cuda)
    t.tensor = lambda data, dtype=None: _FT(np.asarray(data, dtype=np.float32 if dtype == "float32" else None))
    t.inference_mode = contextlib.nullcontext
    return t


LEVELS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def fake_tirex2(nan: bool = False):
    import numpy as np
    m = types.ModuleType("tirex2")
    m.calls = []

    class Inner:
        def eval(self):
            return self

        def parameters(self):
            return [types.SimpleNamespace(numel=lambda: 7)]

    class Model:
        model = Inner()

        def _quantile_levels(self):
            return list(LEVELS)

        def forecast(self, series, prediction_length, output_type="numpy", batch_size=None):
            out = []
            for ts in series:
                last = float(np.asarray(ts.target.arr, dtype=np.float64).reshape(-1)[-1])
                a = np.asarray([[last + 0.1 * (h + 1) + (q - 0.5) * 2.0 for h in range(prediction_length)] for q in LEVELS])
                if nan:
                    a[0, 0] = float("nan")
                out.append(a if output_type == "numpy" else _FT(a))
            return out

    def load_model(path, device="cpu", compile=False, cuda_graphs=None):
        m.calls.append({"path": path, "device": device, "compile": compile, "cuda_graphs": cuda_graphs})
        return Model()
    m.load_model = load_model
    m.TimeseriesType = lambda target, past_covariates=None, future_covariates=None: types.SimpleNamespace(target=target)
    return m


class TestI0207TiRex2Engine(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.root = Path(self.td.dir) / "w"
        fixture_weights(self.root, "tirex2")
        self.env = mock.patch.dict(os.environ, {"MQ_TSFM_ALLOW_FIXTURE": "1"})
        self.env.start()
        os.environ.pop("PMW_TIREX_COMPILE", None)
        os.environ.pop("TORCHDYNAMO_DISABLE", None)

    def tearDown(self):
        self.env.stop()
        self.td.close()

    def engine(self, nan=False):
        from tsfm_runtime import engines as E
        self.torch, self.tx = fake_torch(), fake_tirex2(nan)
        mods = mock.patch.dict(sys.modules, {"torch": self.torch, "tirex2": self.tx})
        mods.start()
        self.addCleanup(mods.stop)
        e = E.make("tirex2")
        self.info = e.load(str(self.root), device="AUTO", threads=3, verify_files=False)
        return e, E

    def req(self, n=600, **kw):
        return {"close": [2000.0 + 0.5 * i for i in range(n)], "pred_len": 12, "context_len": 512, "profile": "CLOSE_V1",
                "quantiles": [0.1, 0.5, 0.9], "freq_tf": "M5", **kw}

    def test_load_plain_inference_on_cpu(self):
        _e, _E = self.engine()
        self.assertEqual(self.tx.calls, [{"path": str(_E.M.model_dir(self.root, "tirex2")), "device": "cpu", "compile": False, "cuda_graphs": None}])
        self.assertEqual(os.environ.get("TORCHDYNAMO_DISABLE"), "1")              # 1.42.1: no TorchInductor without PMW_TIREX_COMPILE
        self.assertTrue(self.torch._dynamo.config.disable)
        self.assertEqual((self.info["device"], self.info["threads"], self.info["trained_quantiles"]), ("cpu", 3, LEVELS))
        self.assertEqual(self.info["model_context_length"], 2048)

    def test_compile_override(self):
        os.environ["PMW_TIREX_COMPILE"] = "1"
        self.engine()
        self.assertNotIn("TORCHDYNAMO_DISABLE", os.environ)
        self.assertFalse(self.torch._dynamo.config.disable)

    def test_predict_median_and_quantile_blocks(self):
        e, _E = self.engine()
        r = e.predict(self.req())
        self.assertEqual((r["point_kind"], len(r["point"]), r["context_bars"]), ("median", 12, 512))
        self.assertEqual(r["point"], r["median"])
        self.assertEqual(r["point"], r["quantiles"]["values"]["0.5"])
        self.assertEqual(sorted(r["quantiles"]["values"]), ["0.1", "0.5", "0.9"])
        self.assertEqual(r["quantiles"]["crossing_steps"], 0)
        last = 2000.0 + 0.5 * 599                                                  # only the last 512 closes; the forecast follows the last one
        self.assertAlmostEqual(r["point"][0], last + 0.1, places=3)
        self.assertAlmostEqual(r["quantiles"]["values"]["0.9"][0] - r["point"][0], 0.8, places=6)

    def test_errors(self):
        e, E = self.engine()
        bad = self.req()
        bad["close"][10] = float("nan")
        for req, code in ((self.req(quantiles=[0.15]), "CONFIG"), (bad, "NON_FINITE_INPUT"), (self.req(n=20, context_len=20), "CONFIG"),
                          (self.req(pred_len=0), "CONFIG"), (self.req(context_len=4096), "CONFIG")):
            with self.assertRaises(E.EngineError) as cm:
                e.predict(req)
            self.assertEqual(cm.exception.code, code, req.get("quantiles"))
        e2, E = self.engine(nan=True)
        with self.assertRaises(E.EngineError) as cm:
            e2.predict(self.req())
        self.assertEqual(cm.exception.code, "NON_FINITE")
        with self.assertRaises(E.EngineError) as cm:
            E.make("tirex2").predict(self.req())
        self.assertEqual(cm.exception.code, "NOT_LOADED")

    def test_direct_parity_and_selftest(self):
        e, _E = self.engine()
        close = self.req()["close"][-512:]
        got = e.predict(self.req())
        ref = e._direct(close, 12, [0.1, 0.5, 0.9])
        self.assertEqual(got["point"], ref["point"])
        self.assertEqual([got["quantiles"]["values"][k] for k in ("0.1", "0.5", "0.9")], ref["quantiles"])
        st = e.selftest()
        self.assertTrue(st["smoke"]["ok"])
        self.assertEqual(st["parity"]["status"], "PASS")


def _real_python(env_key: str, venv: str) -> str | None:
    for x in (os.environ.get(env_key), str(_env.ROOT / venv / "bin" / "python"), str(_env.ROOT / venv / "Scripts" / "python.exe")):
        if x and Path(x).is_file():
            return x
    return None


def _run_worker(argv: list[str], reqs: list[dict], timeout: float) -> dict:
    """The real JSON-lines worker in its own environment: requests (with ids) -> {id: response}."""
    env = dict(os.environ, PYTHONPATH=str(BACKEND), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", OMP_NUM_THREADS="2")
    env.pop("MQ_TSFM_ALLOW_FIXTURE", None)
    data = "".join(json.dumps({**r, "id": str(i)}) + "\n" for i, r in enumerate(reqs)) + json.dumps({"cmd": "quit", "id": "q"}) + "\n"
    p = subprocess.run(argv, input=data, capture_output=True, text=True, check=False, encoding="utf-8", cwd=str(BACKEND), env=env, timeout=timeout)
    out = {}
    for ln in p.stdout.splitlines():
        try:
            m = json.loads(ln)
        except ValueError:
            continue
        out[m.get("id")] = m
    return out


TIREX_PY = _real_python("MQ_TIREX2_PYTHON", ".venv_tirex2")
WROOT = os.environ.get("MQ_TSFM_WEIGHTS_ROOT")


def _tirex_installed() -> bool:
    if not (TIREX_PY and WROOT):
        return False
    from tsfm_runtime import manifest as M
    return bool(M.summary(WROOT, "tirex2")["installed"])


@unittest.skipUnless(_tirex_installed(), "TiRex-2: MQ_TIREX2_PYTHON (.venv_tirex2) + MQ_TSFM_WEIGHTS_ROOT z zainstalowanymi wagami")
class TestI0207TiRex2Real(unittest.TestCase):
    def test_real_worker_load_predict_selftest(self):
        close = [2650.0 + 3.0 * ((i % 40) - 20) / 20 + 0.01 * i for i in range(600)]
        r = _run_worker([TIREX_PY, "-m", "tsfm_runtime.worker", "--model", "tirex2"],
                        [{"cmd": "hello"}, {"cmd": "load", "weights_root": WROOT, "device": "CPU", "threads": 2, "verify_files": True},
                         {"cmd": "predict", "close": close, "pred_len": 12, "context_len": 512, "profile": "CLOSE_V1", "quantiles": [0.1, 0.5, 0.9],
                          "freq_tf": "M5"},
                         {"cmd": "predict", "close": close, "pred_len": 12, "context_len": 512, "quantiles": [0.25]},
                         {"cmd": "selftest"}], timeout=900)
        self.assertTrue(r["1"]["ok"], r["1"])
        from tsfm_runtime import lock as L
        self.assertEqual((r["1"]["info"]["params"], r["1"]["info"]["revision"]), (L.model("tirex2")["params_measured"], L.model("tirex2")["revision"]))
        p = r["2"]
        self.assertTrue(p["ok"], p)
        self.assertEqual((p["point_kind"], len(p["point"])), ("median", 12))
        self.assertEqual(p["point"], p["quantiles"]["values"]["0.5"])
        self.assertTrue(all(a <= b <= c for a, b, c in zip(*(p["quantiles"]["values"][k] for k in ("0.1", "0.5", "0.9")))))
        self.assertEqual((r["3"]["ok"], r["3"]["code"]), (False, "CONFIG"))             # 0.25 is not a TiRex-2 level - never interpolated
        self.assertTrue(r["4"]["ok"], r["4"])
        self.assertTrue(r["4"]["smoke"]["ok"])
        self.assertEqual(r["4"]["parity"]["status"], "PASS", r["4"]["parity"])


# ======================================================================================================== I0213 real TabICLv2
TABICL_PY = _real_python("MQ_TABICL_PYTHON", ".venv_tabicl")


def _tabicl_root() -> str | None:
    if not TABICL_PY:
        return None
    from tabicl_runtime import install as TI
    for root in (WROOT, str(_env.ROOT / "data" / "tsfm" / "models")):
        if root and TI.verify(root)["ok"]:
            return root
    return None


TABICL_ROOT = _tabicl_root()


@unittest.skipUnless(TABICL_ROOT, "TabICLv2: MQ_TABICL_PYTHON / .venv_tabicl + zweryfikowany checkpoint (MQ_TSFM_WEIGHTS_ROOT)")
class TestI0213TabiclReal(unittest.TestCase):
    def test_real_fit_predict_selftest(self):
        import numpy as np
        from tabicl_runtime import lock as TL
        rng = np.random.default_rng(7)
        X = rng.normal(size=(160, 5))
        y = (X[:, 0] - 0.5 * X[:, 2] + rng.normal(0, 0.5, 160) > 0).astype(int)
        r = _run_worker([TABICL_PY, "-m", "tabicl_runtime.worker"],
                        [{"cmd": "hello"}, {"cmd": "load", "weights_root": TABICL_ROOT, "threads": 2, "verify_files": True},
                         {"cmd": "fit", "context_id": "C1", "X": X[:128].tolist(), "y": y[:128].tolist(), "names": [f"f{i}" for i in range(5)]},
                         {"cmd": "predict", "context_id": "C1", "X": X[128:].tolist()},
                         {"cmd": "predict", "context_id": "C1", "X": X[128:, :4].tolist()},
                         {"cmd": "fit", "context_id": "C2", "X": X[:50].tolist(), "y": [0] * 50},
                         {"cmd": "selftest"}], timeout=900)
        self.assertTrue(r["1"]["ok"], r["1"])
        self.assertEqual(r["1"]["info"]["fingerprint"], TL.fingerprint())
        self.assertEqual((r["2"]["n"], r["2"]["dim"], r["2"]["classes"]), (128, 5, [0, 1]))
        p = r["3"]
        self.assertTrue(p["ok"], p)
        self.assertEqual(len(p["p_event_raw"]), 32)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in p["p_event_raw"]))
        hits = sum(int((v > 0.5) == bool(t)) for v, t in zip(p["p_event_raw"], y[128:]))
        self.assertGreater(hits, 16)                                                # a real in-context classifier, not a constant
        self.assertEqual((r["4"]["ok"], r["4"]["code"]), (False, "SHAPE"))                 # another feature schema than the context
        self.assertEqual((r["5"]["ok"], r["5"]["code"]), (False, "SINGLE_CLASS"))
        self.assertTrue(r["6"]["ok"], r["6"])
        self.assertTrue(r["6"]["ok"] and r["6"]["single_class_refused"])
        self.assertEqual(r["6"]["parity"]["status"], "PASS", r["6"]["parity"])


# ======================================================================================================== I0540 tabicl_runtime.engine
def fake_tabicl(nan=False, positive=1):
    import numpy as np
    m = types.ModuleType("tabicl")
    m.made = []

    class TabICLClassifier:
        def __init__(self, **kw):
            m.made.append(kw)

        def fit(self, X, y):
            self.classes_ = np.unique(y)
            return self

        def predict_proba(self, X):
            p = 1.0 / (1.0 + np.exp(-np.asarray(X)[:, 0]))
            if nan:
                p = p * float("nan")
            cols = [p if c == positive else 1.0 - p for c in self.classes_]
            return np.stack(cols, axis=1)
    m.TabICLClassifier = TabICLClassifier
    return m


class TestI0540TabiclEngine(unittest.TestCase):
    def engine(self, **kw):
        from tabicl_runtime import engine as TE
        tb = fake_tabicl(**kw)
        mods = mock.patch.dict(sys.modules, {"torch": fake_torch(), "tabicl": tb})
        mods.start()
        self.addCleanup(mods.stop)
        e = TE.Engine()
        info = e.load("/nonexistent-weights", threads=3, verify_files=False)
        return e, TE, tb, info

    def test_load_and_official_settings(self):
        from tabicl_runtime import lock as TL
        e, _TE, tb, info = self.engine()
        self.assertEqual((info["fingerprint"], info["threads"], info["device"]), (TL.fingerprint(), 3, "cpu"))
        self.assertTrue(str(e.ckpt).endswith(TL.PIN["checkpoint"]))
        e.fit("C", [[0.0, 1.0], [1.0, 0.0], [2.0, 1.0]], [0, 1, 1])
        kw = tb.made[-1]
        self.assertEqual((kw["allow_auto_download"], kw["device"], kw["n_jobs"], kw["checkpoint_version"]), (False, "cpu", 1, TL.PIN["checkpoint"]))
        self.assertEqual(kw["n_estimators"], TL.PIN["inference"]["n_estimators"])

    def test_fit_and_predict_validation(self):
        e, TE, _tb, _ = self.engine()
        X = [[float(i), float(i % 3)] for i in range(10)]
        y = [i % 2 for i in range(10)]
        for args, code in ((([1.0, 2.0], [0, 1]), "SHAPE"), ((X, y[:5]), "SHAPE"), (([[1.0, float("inf")], [2.0, 1.0]], [0, 1]), "NON_FINITE_INPUT"),
                           ((X, [1] * 10), "SINGLE_CLASS"), (([], []), "SHAPE")):
            with self.assertRaises(TE.EngineError) as cm:
                e.fit("C", *args)
            self.assertEqual(cm.exception.code, code, args)
        r = e.fit("C", X, y, names=["a", "b"])
        self.assertEqual((r["n"], r["dim"], r["classes"]), (10, 2, [0, 1]))
        p = e.predict("C", [[0.0, 0.0], [3.0, 1.0]])
        self.assertAlmostEqual(p["p_event_raw"][0], 0.5)
        self.assertGreater(p["p_event_raw"][1], 0.9)
        with self.assertRaises(TE.EngineError) as cm:
            e.predict("OTHER", [[0.0, 0.0]])
        self.assertEqual(cm.exception.code, "NO_CONTEXT")
        with self.assertRaises(TE.EngineError) as cm:
            e.predict("C", [[0.0, 0.0, 1.0]])
        self.assertEqual(cm.exception.code, "SHAPE")
        e.fit("D", X, [0, 2] * 5)                                                   # classes without the positive class 1
        with self.assertRaises(TE.EngineError) as cm:
            e.predict("D", [[0.0, 0.0]])
        self.assertEqual(cm.exception.code, "NO_POSITIVE_CLASS")
        self.assertNotIn("C", e.contexts)                                            # one context in RAM (the newest)
        e2 = TE.Engine()
        with self.assertRaises(TE.EngineError) as cm:
            e2.fit("C", X, y)
        self.assertEqual(cm.exception.code, "NOT_LOADED")

    def test_non_finite_output_and_positive_column(self):
        e, TE, _tb, _ = self.engine(nan=True)
        e.fit("C", [[0.0], [1.0]], [0, 1])
        with self.assertRaises(TE.EngineError) as cm:
            e.predict("C", [[0.5]])
        self.assertEqual(cm.exception.code, "NON_FINITE")
        e, TE, _tb, _ = self.engine(positive=0)                                      # proba columns follow classes_: column of class 1 is used
        e.fit("C", [[0.0], [1.0]], [0, 1])
        self.assertLess(e.predict("C", [[3.0]])["p_event_raw"][0], 0.1)

    def test_selftest_deterministic_stub(self):
        e, _TE, _tb, _ = self.engine()
        st = e.selftest()
        self.assertTrue(st["ok"], st)
        self.assertEqual((st["parity"]["status"], st["single_class_refused"]), ("PASS", True))
        self.assertNotIn("_selftest", e.contexts)


# ======================================================================================================== I0834 / I0844 checkpoint scope
FT = {"run_id": "GTR-test01", "data": {"instrument": "XAUUSD", "timeframe": "M5"}, "train": {"horizon": 12}}


class TestI0844FinetuneScope(unittest.TestCase):
    def test_scope_function(self):
        from tsfm_runtime import engines as E
        self.assertTrue(E.finetune_scope(FT, instrument="XAUUSD", timeframe="M5", horizon=12)["in_scope"])
        self.assertTrue(E.finetune_scope(FT, instrument="XAUUSD", timeframe="M5", horizon=6)["in_scope"])
        for kw, word in (({"instrument": "BTC", "timeframe": "M5", "horizon": 12}, "BTC"), ({"instrument": "XAUUSD", "timeframe": "M15", "horizon": 8}, "M15"),
                         ({"instrument": "XAUUSD", "timeframe": "M5", "horizon": 13}, "13")):
            s = E.finetune_scope(FT, **kw)
            self.assertFalse(s["in_scope"], kw)
            self.assertIn(word, s["reason"])
        self.assertFalse(E.finetune_scope({"run_id": "GTR-x"}, timeframe="M5", horizon=1)["in_scope"])   # unknown scope = out of scope
        self.assertTrue(E.finetune_scope(FT, timeframe="M5", horizon=12)["in_scope"])                     # engine: no instrument in the request

    def test_engine_reports_scope_without_refusing(self):
        import numpy as np
        from tsfm_runtime import engines as E
        e = E.GraniteTTMEngine()
        e.loaded, e.info = True, {"checkpoint": "GTR-test01", "finetune": FT}
        e._forward = lambda z: np.zeros(96)
        req = {"close": [2000.0 + (i % 7) for i in range(512)], "context_len": 512, "profile": "CLOSE_V1"}
        r = e.predict({**req, "pred_len": 12, "freq_tf": "M5"})
        self.assertTrue(r["finetune_scope"]["in_scope"])
        for kw in ({"pred_len": 24, "freq_tf": "M5"}, {"pred_len": 6, "freq_tf": "M15"}):
            r = e.predict({**req, **kw})
            self.assertFalse(r["finetune_scope"]["in_scope"], kw)               # value still computed (ASSIST holds unchanged)
            self.assertEqual(len(r["point"]), kw["pred_len"])
        e.info = {"checkpoint": "BASE", "finetune": None}
        self.assertIsNone(e.predict({**req, "pred_len": 12, "freq_tf": "M5"})["finetune_scope"])


@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell wrapper")
class TestI0834CheckpointScopeDecisions(_Svc):
    def _svc(self):
        svc = self.make(tfs=("M5", "M15"), granite_ttm={"checkpoint": "GTR-test01"})
        w = svc.workers["granite_ttm"]
        self.assertTrue(w.ensure())
        w.load_info.update(checkpoint="GTR-test01", finetune=dict(FT))         # what the real engine reports for an activated fine-tune
        svc.tick()
        self.run_queue()
        return svc

    def test_out_of_scope_forecast_is_flagged(self):
        svc = self._svc()
        self.assertIsNone(svc.latest[("granite_ttm", "XAUUSD", "M5")]["use_restriction"])      # trained XAUUSD M5, H 12
        r = svc.latest[("granite_ttm", "XAUUSD", "M15")]["use_restriction"]
        self.assertEqual(r["code"], "CHECKPOINT_SCOPE")
        self.assertIn("M15", r["reason"])
        self.assertIsNone(svc.latest[("chronos2", "XAUUSD", "M15")]["use_restriction"])
        svc.settings.update({"horizon_bars": {"M5": 20}})                       # horizon above the trained one (I0844)
        svc.refresh("granite_ttm", "XAUUSD", "M5")
        self.run_queue()
        self.assertEqual(svc.latest[("granite_ttm", "XAUUSD", "M5")]["use_restriction"]["code"], "CHECKPOINT_SCOPE")

    def test_required_is_not_confirmed_assist_and_quant_unchanged(self):
        from masterquo.tsfm import predictions as TP
        svc = self._svc()
        self.assertEqual(svc.latest[("granite_ttm", "XAUUSD", "M15")]["direction"], "UP")
        self.approve("granite_ttm", "ACTIVE", "M15")
        rows = [r for r in TP.coordinator_rows(svc, "XAUUSD") if r["family"] == "tsfm:granite_ttm"]
        self.assertEqual([(r["use"], r["state"]) for r in rows], [("REQUIRED", "STALE")])         # before: READY -> BUY passed
        self.assertEqual(self.ev(rows, "BUY")[1], ["MODEL_REQUIRED_UNAVAILABLE:tsfm:granite_ttm"])
        self.approve("granite_ttm", "SCALPING", "M15")
        ctx = TP.context(svc, "granite_ttm", "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual((ctx["available"], ctx["state"]), (False, "CHECKPOINT_SCOPE"))
        self.assertEqual(TP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)["status"], "WAIT")
        self.approve("granite_ttm", "HEDGING", "M5")                                                # in scope: unchanged
        ctx = TP.context(svc, "granite_ttm", "XAUUSD", "HEDGING", side="BUY")
        self.assertEqual(TP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)["status"], "READY")
        self.assertTrue(svc.set_use("granite_ttm", "ACTIVE", "ASSIST", timeframe="M15", confirm=True)["ok"])
        rows = [r for r in TP.coordinator_rows(svc, "XAUUSD") if r["family"] == "tsfm:granite_ttm"]
        self.assertEqual([(r["use"], r["state"]) for r in rows], [("ASSIST", "READY")])
        self.assertEqual(self.ev(rows, "SELL")[1], ["MODEL_ASSIST_HOLD:tsfm:granite_ttm"])          # holds exactly as before
        row = next(r for r in TP.contract_predictions(svc, "XAUUSD") if r["model_id"] == "tsfm:granite_ttm" and r["timeframe"] == "M15")
        self.assertEqual(row["state"], "READY")                                                    # Quant FEAT-2 inputs unchanged
        self.assertEqual(row["use_restriction"]["code"], "CHECKPOINT_SCOPE")

    def test_required_models_config_out_of_scope_not_confirmed(self):
        """Review: REQUIRED through config.json decision.required_models is not confirmed by an out-of-scope checkpoint either
        (before: READY -> the REQUIRED of the coordinator PASSED); ASSIST holds and the in-scope pair stay as they were."""
        from masterquo.tsfm import predictions as TP
        svc = self._svc()
        req = {"tsfm:granite_ttm"}

        def rows():
            return [r for r in TP.coordinator_rows(svc, "XAUUSD") if r["family"] == "tsfm:granite_ttm"]
        self.required_models(*req)
        self.assertEqual([(r["use"], r["state"]) for r in rows()], [("SHADOW", "STALE")])       # ACTIVE M15 (default): out of scope
        self.assertEqual(self.ev(rows(), "BUY", req)[1], ["MODEL_REQUIRED_UNAVAILABLE:tsfm:granite_ttm"])
        self.assertTrue(svc.set_use("granite_ttm", "ACTIVE", "ASSIST", timeframe="M15", confirm=True)["ok"])
        self.assertEqual([(r["use"], r["state"]) for r in rows()], [("ASSIST", "STALE")])       # role_of: REQUIRED wins over ASSIST
        self.assertEqual(self.ev(rows(), "SELL", req)[1], ["MODEL_REQUIRED_UNAVAILABLE:tsfm:granite_ttm"])
        self.required_models()                                                                     # no config REQUIRED: ASSIST as before
        self.assertEqual([(r["use"], r["state"]) for r in rows()], [("ASSIST", "READY")])
        self.assertEqual(self.ev(rows(), "SELL")[1], ["MODEL_ASSIST_HOLD:tsfm:granite_ttm"])
        self.required_models(*req)
        self.assertTrue(svc.set_use("granite_ttm", "ACTIVE", "OBSERVE", timeframe="M5")["ok"])  # in scope (XAUUSD M5, H 12): unchanged
        self.assertEqual([(r["use"], r["state"]) for r in rows()], [("SHADOW", "READY")])
        self.assertEqual(self.ev(rows(), "BUY", req)[1], [])


# ======================================================================================================== I0835 approval per instrument
@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell wrapper")
class TestI0835ApprovalRequiresInstrumentReport(_Svc):
    def test_required_without_report_of_the_instrument(self):
        from masterquo.tsfm import predictions as TP
        svc = self.make()
        self.approve("chronos2", "SCALPING", "M5")                        # report of XAUUSD only
        self.assertEqual(TP.approval_ok(svc, "chronos2", "XAUUSD", "SCALPING"), (True, None))
        ok, why = TP.approval_ok(svc, "chronos2", "BTC", "SCALPING")       # before: (True, None) - no report for BTC was skipped
        self.assertFalse(ok)
        self.assertIn("BTC", why)
        self.approve("chronos2", "HEDGING", "M5", use="ASSIST")            # ASSIST (VALIDATION): unchanged - a stale ASSIST would drop holds
        self.assertEqual(TP.approval_ok(svc, "chronos2", "BTC", "HEDGING"), (True, None))
        svc.settings.update({"models": {"chronos2": {"instruments": ["XAUUSD", "BTC"]}}})
        ctx = TP.context(svc, "chronos2", "BTC", "SCALPING", side="BUY")
        self.assertEqual(ctx["state"], "STALE_APPROVAL")
        self.assertEqual(TP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)["status"], "WAIT")


# ======================================================================================================== I0836 REQUIRED rows on ACTIVE
@unittest.skipUnless(POSIX, "stub worker uses a POSIX shell wrapper")
class TestI0836RequiredRowsActive(_Svc):
    def _rows(self, svc, inst="XAUUSD"):
        from masterquo.tsfm import predictions as TP
        return [r for r in TP.coordinator_rows(svc, inst) if r["family"] == "tsfm:chronos2"]

    def test_required_disabled_model_blocks_like_sh(self):
        svc = self.make(tfs=("M5", "M15"))
        svc.tick()
        self.run_queue()
        self.approve("chronos2", "ACTIVE", "M15")
        self.assertEqual([(r["use"], r["state"]) for r in self._rows(svc)], [("REQUIRED", "READY")])
        svc.settings.update({"models": {"chronos2": {"enabled": False}}})
        rows = self._rows(svc)                                               # before: [] -> nothing blocked the ACTIVE entry
        self.assertEqual([(r["use"], r["state"], r["result"]) for r in rows], [("REQUIRED", "DISABLED", None)])
        self.assertIn("wyłączony", rows[0]["unavailable_reason"])
        self.assertEqual(self.ev(rows, "BUY")[1], ["MODEL_REQUIRED_UNAVAILABLE:tsfm:chronos2"])

    def test_required_instrument_or_timeframe_not_computed(self):
        svc = self.make(tfs=("M5", "M15"))
        svc.tick()
        self.run_queue()
        self.approve("chronos2", "ACTIVE", "M15")
        rows = self._rows(svc, "BTC")
        self.assertEqual([(r["use"], r["state"]) for r in rows], [("REQUIRED", "DISABLED")])
        self.assertEqual(self.ev(rows, "SELL")[1], ["MODEL_REQUIRED_UNAVAILABLE:tsfm:chronos2"])
        svc.settings.update({"models": {"chronos2": {"timeframes": ["M5"]}}})
        rows = self._rows(svc)
        self.assertEqual([(r["use"], r["state"]) for r in rows], [("REQUIRED", "DISABLED")])
        self.assertIn("M15", rows[0]["unavailable_reason"])

    def test_observe_and_assist_unchanged(self):
        svc = self.make(tfs=("M5", "M15"))
        svc.settings.update({"models": {"chronos2": {"enabled": False}}})
        self.assertEqual(self._rows(svc), [])
        self.assertTrue(svc.set_use("chronos2", "ACTIVE", "ASSIST", timeframe="M5", confirm=True)["ok"])
        self.assertEqual(self._rows(svc), [])
        self.assertEqual(self._rows(svc, "BTC"), [])


# ======================================================================================================== I0845 verdict minimum sample
class TestI0845VerdictMinSample(unittest.TestCase):
    def test_verdict(self):
        import inspect

        from tsfm_runtime import granite_finetune as GF
        self.assertEqual(GF.verdict(3, {"mae_h": 1.0}, {"mae_h": 1.1}, 26), "INSUFFICIENT_TEST")   # before: IMPROVED_VS_BASE on 26 windows
        self.assertEqual(GF.verdict(3, {"mae_h": 1.0}, {"mae_h": 1.1}, 150), "IMPROVED_VS_BASE")
        self.assertEqual(GF.verdict(0, {"mae_h": 1.0}, {"mae_h": 1.1}, 150), "NOT_BETTER_THAN_BASE")
        self.assertEqual(GF.verdict(2, {"mae_h": 1.2}, {"mae_h": 1.1}, 150), "NOT_BETTER_THAN_BASE")
        self.assertEqual(GF.verdict(2, {"mae_h": 1.2}, {"mae_h": 1.1}, 10), "NOT_BETTER_THAN_BASE")
        self.assertEqual(GF.MIN_TEST_WINDOWS, 100)
        self.assertIn("verdict(best_epoch", inspect.getsource(GF.main))

    def test_activation_refuses_a_small_test_sample(self):
        import hashlib

        from masterquo.tsfm import granite_train as G
        from masterquo.tsfm.settings import SettingsStore
        from tsfm_runtime import lock as L
        td = TempData()
        try:
            class W:
                def kill(self):
                    pass

            class Log:
                def info(self, *a):
                    pass
            svc = types.SimpleNamespace(settings=SettingsStore(Path(td.dir) / "tsfm" / "settings.json"), workers={"granite_ttm": W()}, applog=Log())
            for rid, metrics, train in (("GTR-SMALL01", {"verdict": "IMPROVED_VS_BASE", "test_windows": 26}, {"horizon": 12}),
                                        ("GTR-NOCNT01", {"verdict": "IMPROVED_VS_BASE"}, {"horizon": 12}),
                                        ("GTR-OLDWIN1", {"verdict": "IMPROVED_VS_BASE"}, {"horizon": 12, "windows": {"test": 140}}),
                                        ("GTR-BIG0001", {"verdict": "IMPROVED_VS_BASE", "test_windows": 150}, {"horizon": 12})):
                d = G.finetune_dir() / rid
                d.mkdir(parents=True, exist_ok=True)
                files = []
                for name in ("config.json", "model.safetensors"):
                    (d / name).write_bytes(name.encode())
                    files.append({"name": name, "sha256": hashlib.sha256(name.encode()).hexdigest()})
                (d / "granite_finetune.json").write_text(json.dumps({"run_id": rid, "base_fingerprint": L.fingerprint("granite_ttm"), "files": files,
                                                                     "data": {"timeframe": "M5"}, "train": train, "metrics": metrics}), encoding="utf-8")
            r = G.activate(svc, "GTR-SMALL01")
            self.assertFalse(r["ok"])                                            # before: activated on 26 test windows
            self.assertIn("26", r["reason"])
            self.assertFalse(G.activate(svc, "GTR-NOCNT01")["ok"])
            self.assertEqual(svc.settings.get().models["granite_ttm"].checkpoint, "BASE")
            self.assertTrue(G.activate(svc, "GTR-OLDWIN1")["ok"])               # count from train.windows (manifests of 1.40-1.45)
            self.assertTrue(G.activate(svc, "GTR-BIG0001")["ok"])
            self.assertEqual(svc.settings.get().models["granite_ttm"].checkpoint, "GTR-BIG0001")
        finally:
            td.close()


# ======================================================================================================== P001 / P002 manifest verify
class _Pin(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.root = Path(self.td.dir) / "w"
        self.src = Path(self.td.dir) / "src"
        self.src.mkdir()
        from tsfm_runtime import lock as L
        from tsfm_runtime import manifest as M
        self.L, self.M = L, M
        self._orig = json.loads(json.dumps(L.MODELS["chronos2"]))
        (self.src / "config.json").write_bytes(b'{"a": 1}')
        (self.src / "model.safetensors").write_bytes(b"\1" * 1000)
        L.MODELS["chronos2"]["files"] = [{"name": "config.json", "size": 8, "git_blob_sha1": M.git_blob_sha1(self.src / "config.json")},
                                         {"name": "model.safetensors", "size": 1000, "sha256": M.sha256_file(self.src / "model.safetensors")}]
        from tsfm_runtime import install as I
        self.assertTrue(I.download("chronos2", str(self.root), from_dir=str(self.src))["ok"])

    def tearDown(self):
        self.L.MODELS["chronos2"] = self._orig
        self.td.close()


class TestP001SizeMessage(_Pin):
    def test_message_names_the_pinned_size(self):
        self.L.MODELS["chronos2"]["files"][0]["size"] = 9                      # the pin differs, the manifest matches the file
        with self.assertRaises(self.M.ManifestError) as cm:
            self.M.verify(self.root, "chronos2")
        self.assertEqual(cm.exception.code, "CHECKSUM")
        self.assertNotIn("8 B ≠ 8 B", cm.exception.detail)                    # before: 'rozmiar 8 B ≠ 8 B z manifestu'
        self.assertIn("9 B", cm.exception.detail)
        self.assertIn("przypięt", cm.exception.detail)

    def test_manifest_size_message_unchanged(self):
        f = self.M.model_dir(self.root, "chronos2") / "config.json"
        f.write_bytes(b'{"a": 12}')
        with self.assertRaises(self.M.ManifestError) as cm:
            self.M.verify(self.root, "chronos2")
        self.assertIn("9 B ≠ 8 B z manifestu", cm.exception.detail)


class TestP002GitBlobPin(_Pin):
    def test_git_blob_pinned_file_checked_against_the_pin(self):
        self.assertTrue(self.M.verify(self.root, "chronos2")["ok"])
        f = self.M.model_dir(self.root, "chronos2") / "config.json"
        f.write_bytes(b'{"b": 2}')                                              # same size, other content
        man = self.M.read(self.root, "chronos2")
        for x in man["files"]:
            if x["name"] == "config.json":
                x["sha256"] = self.M.sha256_file(f)                             # manifest rewritten to match (hand edit / other copy)
        self.M.write(self.root, "chronos2", man)
        with self.assertRaises(self.M.ManifestError) as cm:                    # before: passed (sha256 compared with the manifest only)
            self.M.verify(self.root, "chronos2")
        self.assertEqual(cm.exception.code, "CHECKSUM")
        self.assertIn("git blob", cm.exception.detail)


if __name__ == "__main__":
    unittest.main()
