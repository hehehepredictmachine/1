"""Fala 2 (arch 1.46) - grupa „kronos": Kronos runtime (engine, install, manifest), serwis Kronos (kalendarz, scorecard, dopuszczenie
REQUIRED), scorecard TSFM, kronos_setup, skrypty tools/research/tsfm_eval.

Kierunek wejść (zasada fali 2): każda prognoza Kronos, której DZISIEJSZY kod by nie policzył (po awaryjnym przejściu GPU -> CPU, z
kalendarza pobranego w oknie, w którym dziś wisiał 6 h nieużywalny kalendarz, ze slotem pierwszego niepełnego dnia rozstrzygniętym
poprawioną regułą), jest oznaczona `decision_limited`: warunek REQUIRED, rekord PMW-PRED-1 (Quant, koordynator) i kontekst OBSERVE widzą
ją jak dziś - jako niedostępną; korzysta z niej tylko wstrzymanie ASSIST (READY -> WAIT przy prognozie przeciwnej) oraz panel / księga.
Wszystkie świece poniżej są SYNTETYCZNE; dublery modelu nie są prognozami.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import _env
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kronos_testkit as K  # noqa: E402

UTC = timezone.utc
ROOT = _env.ROOT
WED_1200 = datetime(2026, 10, 28, 12, 0, 30, tzinfo=UTC).timestamp()


# ===================================================================================================== dublery silnika Kronos (bez torch)
class _Rope:
    def __init__(self):
        self.seq_len_cached = self.cos_cached = self.sin_cached = None


class _KMod:
    def __init__(self, dev):
        self.dev, self.rope = dev, _Rope()

    def to(self, dev):
        self.dev = dev                         # jak nn.Module.to(): parametry przechodzą, atrybuty cache RoPE - nie
        return self

    def modules(self):
        return [self, self.rope]

    def run(self, seq_len):
        r = self.rope
        if r.seq_len_cached is not None and r.seq_len_cached == seq_len and r.cos_cached[1] != self.dev:
            raise RuntimeError(f"Expected all tensors to be on the same device, but found {self.dev} and {r.cos_cached[1]}")
        if seq_len != r.seq_len_cached:
            r.seq_len_cached, r.cos_cached, r.sin_cached = seq_len, ("cos", self.dev), ("sin", self.dev)


class _KPred:
    def __init__(self, dev="cuda:0", fail=()):
        self.device, self.model, self.tokenizer, self.fail = dev, _KMod(dev), _KMod(dev), set(fail)

    def _out(self, n, pred_len):
        for m in (self.tokenizer, self.model):
            m.run(n)
        return pd.DataFrame({k: np.full(pred_len, 100.0) for k in ("open", "high", "low", "close", "volume", "amount")})

    def predict(self, df, x_timestamp, y_timestamp, pred_len, **kw):
        if str(self.device).startswith("cuda") and "predict" in self.fail:
            self.tokenizer.run(len(df))
            self.model.run(len(df))
            raise RuntimeError("CUDA error: an illegal memory access was encountered")
        return self._out(len(df), pred_len)

    def predict_batch(self, dfs, xs, ys, pred_len, **kw):
        if str(self.device).startswith("cuda") and "predict_batch" in self.fail:
            self.tokenizer.run(len(dfs[0]))
            self.model.run(len(dfs[0]))
            raise RuntimeError("CUDA out of memory")
        return [self._out(len(d), pred_len) for d in dfs]


def _fake_torch():
    t = types.ModuleType("torch")
    t.manual_seed = lambda s: None
    t.inference_mode = contextlib.nullcontext
    return t


def _kronos_req(n=400, h=12, paths=0):
    t0 = datetime(2026, 1, 5, tzinfo=UTC)
    ts = [str(t0 + timedelta(minutes=5 * i)) for i in range(n + h)]
    c = list(2000 + np.cumsum(np.random.default_rng(2).normal(0, 1, n)))
    return {"candles": {"t": ts[:n], "open": c, "high": [x + 1 for x in c], "low": [x - 1 for x in c], "close": c}, "y_t": ts[n:],
            "pred_len": h, "seed": 7, "paths": paths}


def _engine(pred):
    from kronos_runtime import engine as E
    eng = E.Engine()
    eng.predictor = pred
    eng.info = {"device": pred.device, "device_note": None}
    return eng


class TestI0193KronosGpuFallback(unittest.TestCase):
    """I0193 / I0755: awaryjne przejście GPU -> CPU zeruje cache RoPE (ponowienie i kolejne prognozy działały tylko do restartu - błąd
    mieszania urządzeń), blok ścieżek (predict_batch) ma ten sam fallback."""

    def test_to_cpu_resets_rope_caches_and_the_retry_works(self):
        pred = _KPred(fail={"predict"})
        eng = _engine(pred)
        with mock.patch.dict(sys.modules, {"torch": _fake_torch()}):
            res = eng.predict(_kronos_req())
            self.assertEqual(res["device"], "cpu")
            self.assertTrue(res["device_note"].startswith("GPU_ERROR_FALLBACK_CPU"))
            self.assertEqual(len(res["pred"]["close"]), 12)
            self.assertEqual(eng.predict(_kronos_req())["device"], "cpu")       # kolejne prognozy też działają
        for m in (pred.model, pred.tokenizer):
            self.assertEqual(m.dev, "cpu")
            self.assertNotEqual((m.rope.cos_cached or ("", ""))[1], "cuda:0")

    def test_paths_gpu_error_keeps_the_main_forecast(self):
        """Dziś błąd GPU w bloku ścieżek kończył całą prognozę błędem; teraz prognoza główna wraca bez pasma (paths_error), urządzenie
        bez zmian (kolejna prognoza próbuje GPU jak dziś)."""
        pred = _KPred(fail={"predict_batch"})
        eng = _engine(pred)
        with mock.patch.dict(sys.modules, {"torch": _fake_torch()}):
            res = eng.predict(_kronos_req(paths=3))
            self.assertIsNone(res["paths"])
            self.assertTrue(res["paths_error"].startswith("GPU_ERROR_PATHS"))
            self.assertEqual((res["device"], str(pred.device)), ("cuda:0", "cuda:0"))
            self.assertEqual(len(res["pred"]["close"]), 12)
            pred.fail = set()
            ok = eng.predict(_kronos_req(paths=3))
        self.assertEqual(ok["paths"]["n"], 3)
        self.assertNotIn("paths_error", ok)

    def test_cpu_error_is_not_swallowed(self):
        pred = _KPred(dev="cpu")
        pred.predict = mock.Mock(side_effect=ValueError("zła ramka"))
        eng = _engine(pred)
        with mock.patch.dict(sys.modules, {"torch": _fake_torch()}), self.assertRaises(ValueError):
            eng.predict(_kronos_req())


# ===================================================================================================== serwis Kronos (bez procesu modelu)
class _SvcCase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.dir = Path(self.td.dir)
        self.now = [WED_1200]
        self.m5 = K.make_bars(300, WED_1200, 10)
        self.bridge = K.FakeBridge({("XAUUSD-", "M5"): self.m5})
        self.cfg = K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-")}))

    def tearDown(self):
        for svc in getattr(self, "_made", []):
            svc.db.close()
        self.td.close()

    def make(self, **settings):
        from masterquo.db.database import Database
        from masterquo.kronos.service import KronosService
        from masterquo.kronos.settings import SettingsStore
        st = SettingsStore(self.dir / "kronos" / "settings.json")
        st.update({"timeframes": ["M5"], "instruments": ["XAUUSD"], **settings})
        self.svc = KronosService(self.cfg, self.bridge, Database(self.dir / "t.sqlite"), K.Bus(), K.Log(), clock=lambda: self.now[0], settings=st)
        self._made = getattr(self, "_made", []) + [self.svc]
        return self.svc

    def forecast(self, *, delta=-2.0, device_note=None, job_extra=None, cinfo=None):
        """A forecast built by the service from a worker answer (delta = predicted close - last close)."""
        svc = self.svc
        s = svc.settings.get()
        bars = [b for b in self.m5 if b["closed"]][-200:]
        H = int(s.horizon_bars["M5"])
        last = bars[-1]
        off = int(last["t_raw"]) - int(datetime.fromisoformat(last["open_utc"].replace("Z", "+00:00")).timestamp())
        y_raw = [int(last["t_raw"]) + 300 * (i + 1) for i in range(H)]
        cl = [float(last["c"]) + delta * (i + 1) / H for i in range(H)]
        r = {"ok": True, "pred": {"open": cl, "high": [c + 0.1 for c in cl], "low": [c - 0.1 for c in cl], "close": cl, "volume": None},
             "ms": 1.0, "device": "cpu", "device_note": device_note, "seed": 1, "sampling": {}, "context_bars": len(bars), "paths": None}
        job = {"instrument": "XAUUSD", "timeframe": "M5", "symbol": "XAUUSD-", "bar_key": last["open_utc"], "bars": bars,
               "quality": {"status": "OK", "volume_source": "TICK_VOLUME"}, **(job_extra or {})}
        fc = svc._forecast(job, r, y_raw, off, H, s, cinfo or {"status": "OK"})
        k = ("XAUUSD", "M5")
        svc.state.update(status="READY")
        svc._target(k).update(state="READY", last_key=last["open_utc"])
        svc.latest[k] = fc
        return fc


class TestI0193DecisionLimitedAfterGpuFallback(_SvcCase):
    """Kierunek wejść: prognoza policzona po awaryjnym przejściu na CPU (dziś: ERROR do restartu procesu) nie potwierdza REQUIRED i nie
    trafia do PMW-PRED-1 (Quant / koordynator) - wstrzymuje tylko ASSIST."""

    def test_fallback_forecast_is_limited(self):
        from masterquo.kronos import predictions as KP
        svc = self.make()
        fc = self.forecast(device_note="GPU_ERROR_FALLBACK_CPU: RuntimeError: CUDA error")
        self.assertIn("GPU_FALLBACK_CPU", fc["decision_limited"]["codes"])
        p = KP.contract_predictions(svc, "XAUUSD")[0]
        self.assertEqual((p["state"], p["result"]), ("ERROR", None))                         # jak dziś: brak prognozy w rekordzie
        self.assertIn("GPU", p["unavailable_reason"])

    def test_required_holds_assist_holds_observe_unchanged(self):
        from masterquo.kronos import predictions as KP
        for use, exp_status, exp_avail in (("REQUIRED", "WAIT", False), ("ASSIST", "WAIT", True), ("OBSERVE", "READY", False)):
            with self.subTest(use=use):
                svc = self.make(strategy_use={"SCALPING": {"use": use, "timeframe": "M5", "validation_report": None, "confirmed_at": None}})
                self.forecast(delta=-2.0, device_note="GPU_ERROR_FALLBACK_CPU: RuntimeError: CUDA error")   # DOWN przeciw BUY
                ctx = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
                self.assertEqual(ctx["available"], exp_avail, ctx)
                su = KP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)
                self.assertEqual(su["status"], exp_status)

    def test_required_never_confirms_a_limited_forecast(self):
        from masterquo.kronos import predictions as KP
        svc = self.make(strategy_use={"SCALPING": {"use": "REQUIRED", "timeframe": "M5", "validation_report": "x", "confirmed_at": None}})
        self.forecast(delta=+2.0, device_note="GPU_ERROR_FALLBACK_CPU: x")                     # UP = zgodna z BUY
        su = KP.apply_to_setup({"status": "READY", "side": "BUY"}, KP.context(svc, "XAUUSD", "SCALPING", side="BUY"))
        self.assertEqual(su["status"], "WAIT")
        ctx = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
        self.assertIn("GPU", ctx["reason"])

    def test_assist_agreeing_limited_forecast_never_creates_ready(self):
        from masterquo.kronos import predictions as KP
        svc = self.make(strategy_use={"SCALPING": {"use": "ASSIST", "timeframe": "M5", "validation_report": None, "confirmed_at": None}})
        self.forecast(delta=+2.0, device_note="GPU_ERROR_FALLBACK_CPU: x")
        ctx = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual(KP.apply_to_setup({"status": "WAIT", "side": "BUY"}, ctx)["status"], "WAIT")
        self.assertEqual(KP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)["status"], "READY")

    def test_paths_error_forecast_is_limited(self):
        from masterquo.kronos import predictions as KP
        svc = self.make()
        fc = self.forecast(job_extra={}, device_note=None)
        self.assertIsNone(fc["decision_limited"])
        r_extra = {"paths_error": "GPU_ERROR_PATHS: RuntimeError: CUDA out of memory"}
        from masterquo.kronos.service import decision_limited
        lim = decision_limited(r_extra, {}, {"status": "OK"})
        self.assertEqual(lim["codes"], ["PATHS_GPU_ERROR"])
        svc.latest[("XAUUSD", "M5")]["decision_limited"] = lim
        self.assertEqual(KP.contract_predictions(svc, "XAUUSD")[0]["state"], "ERROR")

    def test_normal_forecast_unchanged(self):
        from masterquo.kronos import predictions as KP
        svc = self.make(strategy_use={"SCALPING": {"use": "ASSIST", "timeframe": "M5", "validation_report": None, "confirmed_at": None}})
        fc = self.forecast(device_note=None)
        self.assertIsNone(fc["decision_limited"])
        p = KP.contract_predictions(svc, "XAUUSD")[0]
        self.assertEqual(p["state"], "READY")
        ctx = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
        self.assertTrue(ctx["available"])
        self.assertIsNone(ctx.get("decision_limited"))


if __name__ == "__main__":
    unittest.main()
