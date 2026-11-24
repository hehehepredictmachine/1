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
import io
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


# ===================================================================================================== I0785 dopuszczenie REQUIRED
class TestI0785RequiredMissingReport(_SvcCase):
    """Dziś raport z validation_report, którego nie da się odczytać (usunięty / uszkodzony), był pomijany (continue) i REQUIRED
    przechodził (fail-open). Teraz brak dokładnie jednego czytelnego raportu instrumentu = STALE_APPROVAL -> WAIT."""

    def _required(self, rid):
        return self.make(strategy_use={"SCALPING": {"use": "REQUIRED", "timeframe": "M5", "validation_report": rid, "confirmed_at": None}})

    def test_deleted_report_holds(self):
        from masterquo.kronos import predictions as KP
        svc = self._required("XAUUSD_M5_deleted")
        self.forecast(delta=+2.0)                                                   # UP, zgodna z BUY, zwykła prognoza
        ctx = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual(ctx["state"], "STALE_APPROVAL", ctx["reason"])
        self.assertIn("niedostępny lub nieczytelny", ctx["reason"])
        self.assertEqual(KP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)["status"], "WAIT")

    def test_corrupted_report_holds(self):
        from masterquo.kronos import predictions as KP
        from masterquo.kronos import validation as V
        svc = self._required("XAUUSD_M5_20260101T000000Z")
        (V.reports_dir() / "XAUUSD_M5_20260101T000000Z.json").write_text('{"report_id": "XAUUSD_M5_2026', encoding="utf-8")
        self.forecast(delta=+2.0)
        ctx = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual(ctx["state"], "STALE_APPROVAL")

    def test_valid_report_still_confirms(self):
        from masterquo.kronos import predictions as KP
        from masterquo.kronos import validation as V
        svc = self._required("XAUUSD_M5_ok")
        rep = {"report_id": "XAUUSD_M5_ok", "instrument": "XAUUSD", "timeframe": "M5", "binding": V.binding(svc, "XAUUSD", "M5")}
        (V.reports_dir() / "XAUUSD_M5_20260102T000000Z.json").write_text(json.dumps(rep), encoding="utf-8")
        self.forecast(delta=+2.0)
        ctx = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual(ctx["state"], "READY", ctx["reason"])
        self.assertEqual(KP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)["status"], "READY")

    def test_other_instrument_report_does_not_count(self):
        from masterquo.kronos import predictions as KP
        from masterquo.kronos import validation as V
        svc = self._required("BTC_M5_ok")
        rep = {"report_id": "BTC_M5_ok", "instrument": "BTC", "timeframe": "M5", "binding": V.binding(svc, "BTC", "M5")}
        (V.reports_dir() / "BTC_M5_20260102T000000Z.json").write_text(json.dumps(rep), encoding="utf-8")
        self.forecast(delta=+2.0)
        self.assertEqual(KP.context(svc, "XAUUSD", "SCALPING", side="BUY")["state"], "STALE_APPROVAL")


class _InProcStub:
    """Dubler workera do mechaniki walk-forward: prognoza = ostatnia cena + 0,01 (bez modelu)."""
    def ask(self, req, timeout):
        if req["cmd"] == "load":
            return {"ok": True, "info": {"device": "cpu"}}
        if req["cmd"] == "predict":
            last = req["candles"]["close"][-1]
            return {"ok": True, "pred": {"close": [last + 0.01] * req["pred_len"]}, "ms": 1.0}
        return {"ok": True}

    def close(self):
        pass


class TestI0786ValidatedBandBinding(_SvcCase):
    """Dziś binding raportu zapisywał pasmo z ustawień z chwili walidacji, a test walidacji liczył z k wybranym na DEV; set_strategy_use
    wymaga k == pasmo w ustawieniach -> po ustawieniu zwalidowanego pasma binding_diff zgłaszał zmianę (VALIDATION_STALE) i REQUIRED nie
    dawał się włączyć. Teraz binding = zatwierdzone pasmo k (pole informacyjne: pasmo ustawień w chwili walidacji)."""

    def setUp(self):
        super().setUp()
        self.bridge.bars_by[("XAUUSD-", "M5")] = K.make_bars(300, WED_1200, 20)

    def test_binding_holds_the_validated_band_and_required_can_be_enabled(self):
        from masterquo.kronos import validation as V
        svc = self.make(direction_band_atr=0.25)
        rep = V.run(svc, "XAUUSD", "M5", max_origins=60, client_factory=_InProcStub)
        self.assertEqual(rep["status"], "DONE")
        k = rep["dev"]["chosen_band_k"]
        self.assertNotEqual(k, 0.25)
        self.assertEqual(rep["binding"]["direction_band_atr"], k)
        self.assertEqual(rep["binding_settings_band_at_validation"], 0.25)
        # pozytywny werdykt (tylko na potrzeby testu mechaniki dopuszczenia) - zapis jak raport z rynku
        f = V.reports_dir() / f"{rep['report_id']}.json"
        saved = json.loads(f.read_text(encoding="utf-8"))
        saved["verdict"] = {"positive": True, "reason": "test"}
        f.write_text(json.dumps(saved), encoding="utf-8")
        r = svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)                # pasmo w ustawieniach ≠ zwalidowane
        self.assertFalse(r["ok"])
        self.assertIn("pasmo neutralne", r["reason"])
        svc.settings.update({"direction_band_atr": k})                                # „ustaw zwalidowane pasmo”
        r = svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(V.binding_diff(saved["binding"], V.binding(svc, "XAUUSD", "M5")), [])

    def test_old_report_with_settings_band_keeps_todays_rule(self):
        """Raport sprzed poprawki (binding = pasmo ustawień b0, zwalidowane k ≠ b0): REQUIRED dalej się nie włącza - ani przy b0, ani przy k."""
        from masterquo.kronos import validation as V
        svc = self.make(direction_band_atr=0.25)
        b0 = V.binding(svc, "XAUUSD", "M5")
        rep = {"report_id": "XAUUSD_M5_old", "instrument": "XAUUSD", "timeframe": "M5", "data_kind": "MT5_DEMO", "verdict": {"positive": True},
               "binding": b0, "dev": {"chosen_band_k": 0.5}}
        (V.reports_dir() / "XAUUSD_M5_20260103T000000Z.json").write_text(json.dumps(rep), encoding="utf-8")
        self.assertFalse(svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)["ok"])
        svc.settings.update({"direction_band_atr": 0.5})
        self.assertFalse(svc.set_strategy_use("SCALPING", "REQUIRED", confirm=True)["ok"])


# ===================================================================================================== I0853 / I0854 kalendarz sesji
def _raw(y, mo, d, h=0, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=UTC).timestamp())        # czas SERWERA zapisany jak epoka (jak t_raw z MT5)


def _bars_24x5(first_raw, last_raw, tf=3600, price=2000.0):
    """Synthetic 24/5 bars (closed Saturday + Sunday server time) from first_raw to last_raw (+ the forming bar)."""
    out, i, t = [], 0, first_raw
    while t <= last_raw + tf:
        if (t // 86400 + 3) % 7 not in (5, 6):
            c = price + 3 * ((i % 40) - 20) / 20 + i * 0.001
            out.append({"t_raw": t, "open_utc": K.iso(t - K.OFF), "o": c - 0.2, "h": c + 0.5, "l": c - 0.5, "c": c, "tv": 50, "rv": 0,
                        "closed": t <= last_raw})
            i += 1
        t += tf
    return out


WED1_1400 = _raw(2026, 10, 14, 14)        # pierwsza świeca historii: środa 14:00 (czas serwera) - pierwszy dzień niepełny
WED3_0900 = _raw(2026, 10, 28, 9)         # ostatnia zamknięta świeca H1: środa 09:00 (dzień bieżący)


class TestI0853CalendarFirstPartialDay(unittest.TestCase):
    def setUp(self):
        from masterquo.kronos import calendar as CAL
        self.CAL = CAL
        self.cal = CAL.Calendar([b["t_raw"] for b in _bars_24x5(WED1_1400, WED3_0900) if b["closed"]], 3600)

    def test_first_partial_day_made_the_slot_ambiguous(self):
        wed_1000 = WED3_0900 + 3600
        self.assertEqual(self.cal.state(wed_1000), ("AMBIGUOUS", 0.5))                       # reguła pierwotna - bez zmian
        self.assertEqual(self.cal.state(wed_1000, exclude_first_partial=True), ("OPEN", 1.0))

    def test_live_future_resolves_only_with_the_flag(self):
        y, info = self.cal.future(WED3_0900, 3600, 6)                                         # walidacja / TSFM: jak dziś
        self.assertIsNone(y)
        self.assertEqual(info["status"], "CALENDAR_UNCERTAIN")
        y, info = self.cal.future(WED3_0900, 3600, 6, resolve_first_day=True)                 # serwis na żywo
        self.assertEqual(info["status"], "OK")
        self.assertEqual(y, [WED3_0900 + 3600 * (i + 1) for i in range(6)])
        self.assertEqual(len(info["first_day_resolved"]), 4)                                   # 10:00-13:00 środy

    def test_resolution_never_changes_or_removes_todays_timestamps(self):
        """Gdy reguła pierwotna daje czasy, wynik z resolve_first_day jest identyczny (CLOSED zostaje CLOSED, OPEN zostaje OPEN)."""
        rng = np.random.default_rng(11)
        checked = 0
        for _trial in range(25):
            first = _raw(2026, 9, 1) + int(rng.integers(0, 14 * 24)) * 3600
            bars = [b["t_raw"] for b in _bars_24x5(first, first + int(rng.integers(8, 30)) * 86400) if b["closed"]]
            keep = [t for t in bars if rng.random() > 0.15 or t == bars[-1]]                 # losowe dziury w historii
            cal = self.CAL.Calendar(keep, 3600)
            for back in range(0, 72, 5):
                last = keep[-1] - back * 3600
                a, ia = cal.future(last, 3600, 6)
                b, ib = cal.future(last, 3600, 6, resolve_first_day=True)
                if a is not None:
                    checked += 1
                    self.assertEqual(a, b)
                    self.assertNotIn("first_day_resolved", ib)
                elif b is not None:
                    self.assertTrue(ib.get("first_day_resolved"))
        self.assertGreater(checked, 50)

    def test_quality_gap_count_keeps_the_original_rule(self):
        ts = [b["t_raw"] for b in _bars_24x5(WED1_1400, WED3_0900) if b["closed"]]
        self.assertEqual(self.cal.expected_missing(ts, 3600), {"missing_open_slots": 0, "ambiguous_slots": 0})


class _FakeWorkerSvcCase(_SvcCase):
    """KronosService z dublerem odpowiedzi workera (bez procesu): prognoza = ostatnia cena - 0,5 na krok."""

    def make(self, **settings):
        svc = super().make(**settings)
        svc.ensure_worker = lambda: svc.state.update(status="READY") or True
        svc.env_status = lambda: {"python_found": True, "weights_installed": True, "weights_reason": None}

        def ask(req, timeout):
            last = req["candles"]["close"][-1]
            cl = [last - 0.5 * (i + 1) for i in range(req["pred_len"])]
            return {"ok": True, "pred": {"open": cl, "high": [c + 0.1 for c in cl], "low": [c - 0.1 for c in cl], "close": cl, "volume": None},
                    "ms": 1.0, "device": "cpu", "device_note": None, "seed": req["seed"], "sampling": {}, "context_bars": len(req["candles"]["close"]),
                    "paths": None}
        svc._ask = ask
        return svc

    def cycle(self, inst="XAUUSD", tf="M5"):
        svc = self.svc
        svc._target((inst, tf))["next_check"] = 0
        svc.tick()
        out = None
        while svc.queue:
            _k, job = svc.queue.popitem(last=False)
            out = svc.run_job(job)
        return out


class TestI0853LiveForecastLimited(_FakeWorkerSvcCase):
    def test_first_day_resolved_forecast_is_limited(self):
        from masterquo.kronos import predictions as KP
        self.bridge.bars_by[("XAUUSD-", "H1")] = _bars_24x5(WED1_1400, WED3_0900)
        self.now[0] = WED3_0900 - K.OFF + 3600 + 30
        svc = self.make(timeframes=["H1"], strategy_use={"SCALPING": {"use": "ASSIST", "timeframe": "H1", "validation_report": None,
                                                                      "confirmed_at": None}})
        fc = self.cycle(tf="H1")
        self.assertIsNotNone(fc, svc.targets)                                             # dziś: CALENDAR_UNCERTAIN, brak prognozy
        self.assertEqual(fc["decision_limited"]["codes"], ["CALENDAR_FIRST_DAY"])
        self.assertEqual(fc["direction"], "DOWN")
        self.assertEqual(KP.contract_predictions(svc, "XAUUSD")[0]["state"], "ERROR")        # Quant / koordynator: jak dziś
        ctx = KP.context(svc, "XAUUSD", "SCALPING", side="BUY")
        self.assertEqual(KP.apply_to_setup({"status": "READY", "side": "BUY"}, ctx)["status"], "WAIT")   # ASSIST: tylko wstrzymanie
        svc.settings.update({"strategy_use": {"SCALPING": {"use": "OBSERVE", "timeframe": "H1", "validation_report": None, "confirmed_at": None}}})
        self.assertFalse(KP.context(svc, "XAUUSD", "SCALPING", side="BUY")["available"])


class TestI0854UnusableCalendarCache(_FakeWorkerSvcCase):
    """Dziś nieużywalny kalendarz (pusta / krótka historia) był trzymany 6 h: przez 6 h CALENDAR_INSUFFICIENT. Teraz ponowny odczyt po
    5 min; prognozy z kalendarza odczytanego w dawnym oknie 6 h są ograniczone (ASSIST / informacja), po oknie - jak dziś."""

    def test_unusable_calendar_is_reread_after_five_minutes(self):
        svc = self.make()
        self.bridge.bars_by[("XAUUSD-", "M5")] = K.make_bars(300, self.now[0], 2)
        cal, err = svc._calendar("XAUUSD-", "M5")
        self.assertFalse(cal.usable()[0])
        n0 = len(self.bridge.calls)
        self.now[0] += 120
        svc._calendar("XAUUSD-", "M5")
        self.assertEqual(len(self.bridge.calls), n0)                                       # w ciągu 5 min - z pamięci
        self.bridge.bars_by[("XAUUSD-", "M5")] = K.make_bars(300, self.now[0], 30)
        self.now[0] += 200
        cal, err = svc._calendar("XAUUSD-", "M5")
        self.assertEqual(len(self.bridge.calls), n0 + 1)
        self.assertTrue(cal.usable()[0])
        self.assertTrue(svc._calendar_limited("XAUUSD-", "M5"))

    def test_forecasts_inside_the_old_window_are_limited_and_after_it_identical(self):
        from masterquo.kronos import predictions as KP
        t0 = self.now[0]
        self.bridge.bars_by[("XAUUSD-", "M5")] = K.make_bars(300, t0, 2)
        svc = self.make(strategy_use={"SCALPING": {"use": "REQUIRED", "timeframe": "M5", "validation_report": "x", "confirmed_at": None}})
        self.assertIsNone(self.cycle())
        self.assertEqual(svc.targets[("XAUUSD", "M5")]["state"], "CALENDAR_INSUFFICIENT")
        self.now[0] = t0 + 600
        self.bridge.bars_by[("XAUUSD-", "M5")] = K.make_bars(300, self.now[0], 30)
        fc = self.cycle()
        self.assertIsNotNone(fc, svc.targets)                                             # dziś: CALENDAR_INSUFFICIENT do t0 + 6 h
        self.assertEqual(fc["decision_limited"]["codes"], ["CALENDAR_LEGACY_WINDOW"])
        self.assertFalse(KP.context(svc, "XAUUSD", "SCALPING", side="SELL")["available"])  # REQUIRED: niedostępna jak dziś
        n_calls = len(self.bridge.calls)
        self.now[0] = t0 + 6 * 3600 + 60                                                   # koniec dawnego okna: nowy odczyt jak dziś
        self.bridge.bars_by[("XAUUSD-", "M5")] = K.make_bars(300, self.now[0], 30)
        fc = self.cycle()
        self.assertIsNotNone(fc)
        self.assertIsNone(fc["decision_limited"])
        self.assertIn(("XAUUSD-", "M5", int(min(8100, 28 * 86400 // 300))), self.bridge.calls[n_calls:])
        self.assertFalse(svc._calendar_limited("XAUUSD-", "M5"))

    def test_tsfm_borrowed_calendar_cache_unchanged(self):
        """TsfmService pożycza KronosService._calendar - poprawka I0854 dotyczy tylko Kronos; TSFM zachowuje dzisiejsze 6 h."""
        from masterquo.db.database import Database
        from masterquo.tsfm.service import TsfmService
        from masterquo.tsfm.settings import SettingsStore
        st = SettingsStore(self.dir / "tsfm" / "settings.json")
        db = Database(self.dir / "tsfm.sqlite")
        try:
            svc = TsfmService(self.cfg, self.bridge, db, K.Bus(), K.Log(), clock=lambda: self.now[0], settings=st)
            self.bridge.bars_by[("XAUUSD-", "M5")] = K.make_bars(300, self.now[0], 2)
            self.assertFalse(svc._calendar("XAUUSD-", "M5")[0].usable()[0])
            n0 = len(self.bridge.calls)
            self.bridge.bars_by[("XAUUSD-", "M5")] = K.make_bars(300, self.now[0], 30)
            self.now[0] += 6 * 3600 - 1
            self.assertFalse(svc._calendar("XAUUSD-", "M5")[0].usable()[0])               # jak dziś: z pamięci przez 6 h
            self.assertEqual(len(self.bridge.calls), n0)
            self.now[0] += 1
            self.assertTrue(svc._calendar("XAUUSD-", "M5")[0].usable()[0])
        finally:
            db.close()

    def test_usable_calendar_cache_unchanged(self):
        svc = self.make()
        self.bridge.bars_by[("XAUUSD-", "M5")] = K.make_bars(300, self.now[0], 30)
        svc._calendar("XAUUSD-", "M5")
        n0 = len(self.bridge.calls)
        self.now[0] += 6 * 3600 - 1
        svc._calendar("XAUUSD-", "M5")
        self.assertEqual(len(self.bridge.calls), n0)
        self.now[0] += 1
        svc._calendar("XAUUSD-", "M5")
        self.assertEqual(len(self.bridge.calls), n0 + 1)
        self.assertFalse(svc._calendar_limited("XAUUSD-", "M5"))


# ===================================================================================================== I0035 scorecard: tylko bieżący horyzont
class TestI0035ScorecardHorizonFilter(_SvcCase):
    """Dziś scorecard Kronos / TSFM uśredniał błędy prognoz o różnych horyzontach (H=12 abs_err 1,0 i H=24 abs_err 9,0 -> settled 2,
    mae_h 5,0). Teraz tylko bieżące H z ustawień; inne H policzone osobno. Tylko wyświetlanie."""

    def _kronos_row(self, svc, fid, H, err, bar):
        svc.db.execute("""INSERT INTO kronos_forecasts(forecast_id, created_at, instrument, symbol, timeframe, horizon_bars, last_bar_open_utc,
                          last_close, pred_close_h, delta_price, direction, path_json, data_kind, outcome_status, abs_err_h, naive_abs_err_h,
                          direction_hit) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (fid, "2026-10-28T10:00:00Z", "XAUUSD", "XAUUSD-", "M5", H, bar, 2000.0, 2001.0, 1.0, "UP", "[]", "MT5_DEMO", "SETTLED",
                        err, 2.0, 1))

    def test_kronos_scorecard_uses_only_the_current_horizon(self):
        svc = self.make(horizon_bars={"M1": 15, "M3": 10, "M5": 12, "M15": 8, "M30": 8, "H1": 6})
        self._kronos_row(svc, "a", 12, 1.0, "2026-10-28T09:00:00Z")
        self._kronos_row(svc, "b", 24, 9.0, "2026-10-28T09:05:00Z")
        sc = svc.scorecard("XAUUSD", "M5")["REAL"]
        self.assertEqual((sc["settled"], sc["mae_h"]), (1, 1.0))
        self.assertEqual((sc["horizon_bars"], sc["other_horizons"]), (12, {"24": 1}))
        svc.settings.update({"horizon_bars": {"M1": 15, "M3": 10, "M5": 24, "M15": 8, "M30": 8, "H1": 6}})
        sc = svc.scorecard("XAUUSD", "M5")["REAL"]
        self.assertEqual((sc["settled"], sc["mae_h"], sc["other_horizons"]), (1, 9.0, {"12": 1}))

    def test_tsfm_scorecard_uses_only_the_current_horizon(self):
        from masterquo.db.database import Database
        from masterquo.tsfm.service import TsfmService, ledger_fingerprint
        from masterquo.tsfm.settings import SettingsStore
        from tsfm_runtime import lock as L
        st = SettingsStore(self.dir / "tsfm" / "settings.json")
        db = Database(self.dir / "tsfm.sqlite")
        try:
            svc = TsfmService(self.cfg, self.bridge, db, K.Bus(), K.Log(), clock=lambda: self.now[0], settings=st)
            H = int(st.get().horizon_bars["M5"])
            fp = ledger_fingerprint(L.fingerprint("chronos2"), st.get().models["chronos2"].checkpoint)
            for fid, h, err, bar in (("a", H, 1.0, "2026-10-28T09:00:00Z"), ("b", 2 * H, 9.0, "2026-10-28T09:05:00Z")):
                db.execute("""INSERT INTO tsfm_forecasts(forecast_id, model_id, model_name, model_revision, fingerprint, profile, snapshot_id,
                              created_at, instrument, symbol, timeframe, horizon_bars, context_bars, last_bar_open_utc, last_close, point_kind,
                              pred_close_h, delta_price, direction, path_json, data_kind, outcome_status, abs_err_h, naive_abs_err_h)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (fid, "chronos2", "Chronos-2", "r", fp, "p", "s", "2026-10-28T10:00:00Z", "XAUUSD", "XAUUSD-", "M5", h, 512, bar,
                            2000.0, "median", 2001.0, 1.0, "UP", "[]", "MT5_DEMO", "SETTLED", err, 2.0))
            sc = svc.scorecard("chronos2", "XAUUSD", "M5")["REAL"]
            self.assertEqual((sc["settled"], sc["mae_h"], sc["horizon_bars"], sc["other_horizons"]), (1, 1.0, H, {str(2 * H): 1}))
        finally:
            db.close()


# ===================================================================================================== I0194 przypięte sha256 wag Kronos
class _HubCase(unittest.TestCase):
    """Dubler huggingface_hub (moduł w sys.modules) + _fetch zapisujący bajty - kronos_runtime.install.download bez sieci."""

    CONTENT = {"config.json": b'{"d_model": 1}', "model.safetensors": b"\x01" * 4096, "README.md": b"---\nlicense: mit\n---\n"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kr_pin_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _hub(self):
        from kronos_runtime import lock
        from kronos_runtime import manifest as M
        src = self.tmp / "src"
        src.mkdir(exist_ok=True)
        for n, b in self.CONTENT.items():
            (src / n).write_bytes(b)

        class Sib:
            def __init__(self, name):
                p = src / name
                lfs = name == "model.safetensors"
                self.rfilename, self.size = name, p.stat().st_size
                self.lfs = {"sha256": M.sha256_file(p)} if lfs else None          # źródło (HF) zgodne z plikiem
                self.blob_id = None if lfs else M.git_blob_sha1(p)

        names = list(self.CONTENT)

        class HfApi:
            def model_info(self, repo, revision=None, files_metadata=False):
                assert any(c["repo"] == repo for c in lock.COMPONENTS)
                return types.SimpleNamespace(sha=revision, siblings=[Sib(n) for n in names])

        hub = types.ModuleType("huggingface_hub")
        hub.HfApi, hub.__version__ = HfApi, "test"

        def fetch(url, part, size, label, rep, step, retries=4):
            Path(part).write_bytes(self.CONTENT[url.rsplit("/", 1)[1]])
        return hub, fetch

    def _download(self, dest, fetch=None):
        from kronos_runtime import install as I
        hub, fetch0 = self._hub()
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"huggingface_hub": hub}), mock.patch.object(I, "_fetch", side_effect=fetch or fetch0), \
                mock.patch.dict(os.environ, {"HF_HUB_OFFLINE": "0"}), contextlib.redirect_stdout(out):
            rc = I.download(str(dest), None)
        res = json.loads(next(x for x in out.getvalue().splitlines() if x.startswith("RESULT "))[7:])
        return rc, res


class TestI0194KronosPinnedSha(_HubCase):
    """Dziś sumy sha256 wag w lock.py czytał tylko test: instalator ufał metadanym LFS z HF, verify - własnemu manifestowi. Teraz pin jest
    wymuszany w obu miejscach (wyjątek: manifest fixture testów, przyjmowany tylko z MQ_KRONOS_ALLOW_FIXTURE=1)."""

    def test_download_refuses_source_file_that_differs_from_the_pin(self):
        from kronos_runtime import manifest as M
        rc, res = self._download(self.tmp / "w")
        self.assertEqual((rc, res["code"]), (1, "CHECKSUM_MISMATCH"))
        self.assertIn("przypięty w lock.py", res["error"])
        self.assertIsNone(M.read(self.tmp / "w"))                                         # nic nie zostaje oznaczone jako zainstalowane

    def test_download_with_the_pinned_files_installs(self):
        from kronos_runtime import lock
        from kronos_runtime import manifest as M
        pin = __import__("hashlib").sha256(self.CONTENT["model.safetensors"]).hexdigest()
        with mock.patch.dict(lock.MODEL["sha256"], {"model.safetensors": pin}), mock.patch.dict(lock.TOKENIZER["sha256"], {"model.safetensors": pin}):
            rc, res = self._download(self.tmp / "w")
            self.assertEqual((rc, res["code"]), (0, None), res)
            self.assertTrue(M.verify(self.tmp / "w")["ok"])
        with self.assertRaises(M.ManifestError) as cm:                                     # te same pliki, prawdziwe piny lock.py
            M.verify(self.tmp / "w")
        self.assertEqual(cm.exception.code, "CHECKSUM")
        self.assertIn("przypięty", cm.exception.detail)

    def test_fixture_manifest_is_exempt_only_as_a_fixture(self):
        from kronos_runtime import manifest as M
        wd = K.fixture_weights(self.tmp / "fx")
        with mock.patch.dict(os.environ, {"MQ_KRONOS_ALLOW_FIXTURE": "1"}):
            self.assertTrue(M.verify(wd)["ok"])
        man = M.read(wd)
        man.pop("fixture")
        M.write(wd, man)
        with mock.patch.dict(os.environ, {"MQ_KRONOS_ALLOW_FIXTURE": "1"}), self.assertRaises(M.ManifestError):
            M.verify(wd)

    @unittest.skipUnless(os.environ.get("MQ_KRONOS_WEIGHTS_DIR"), "oficjalne wagi Kronos niedostępne (MQ_KRONOS_WEIGHTS_DIR)")
    def test_official_installation_matches_the_pins(self):
        from kronos_runtime import manifest as M
        self.assertTrue(M.verify(os.environ["MQ_KRONOS_WEIGHTS_DIR"])["ok"])


class TestP003KronosNetworkHost(_HubCase):
    """Przy blokadzie hosta CDN (huggingface.co przekierowuje pliki LFS / xet np. na us.aws.cdn.hf.co) instalator kazał „odblokować
    huggingface.co” i nie podawał faktycznego hosta. Teraz wynik pobierania ma hosts, a podpowiedź kronos_setup je wymienia."""

    def test_download_reports_the_redirect_host(self):
        import urllib.error
        from kronos_runtime import install as I

        def blocked(url, part, size, label, rep, step, retries=4):
            if url.endswith("model.safetensors"):
                raise urllib.error.URLError(OSError(11001, "getaddrinfo failed"))
            Path(part).write_bytes(self.CONTENT[url.rsplit("/", 1)[1]])
        with mock.patch.object(I, "_redirect_host", return_value="us.aws.cdn.hf.co") as probe:
            rc, res = self._download(self.tmp / "w", fetch=blocked)
        self.assertEqual((rc, res["code"]), (1, "NETWORK"))
        self.assertEqual(res["hosts"], ["huggingface.co", "us.aws.cdn.hf.co"])
        self.assertIn("us.aws.cdn.hf.co", res["error"])
        self.assertTrue(probe.call_args[0][0].startswith("https://huggingface.co/NeoQuasar/"))

    def test_redirect_probe_reads_the_location(self):
        import urllib.error
        from kronos_runtime import install as I
        url = "https://huggingface.co/NeoQuasar/Kronos-small/resolve/x/model.safetensors"
        err = urllib.error.HTTPError(url, 302, "Found", {"Location": "https://us.aws.cdn.hf.co/repos/ab/cd/file?x=1"}, None)
        opener = types.SimpleNamespace(open=mock.Mock(side_effect=err))
        with mock.patch("urllib.request.build_opener", return_value=opener):
            self.assertEqual(I._redirect_host(url), "us.aws.cdn.hf.co")
        with mock.patch("urllib.request.build_opener", return_value=types.SimpleNamespace(open=mock.Mock(side_effect=OSError("x")))):
            self.assertIsNone(I._redirect_host(url))
        final = urllib.error.HTTPError("https://cas-bridge.xethub.hf.co/f", 503, "busy", {}, None)
        self.assertEqual(I.network_hosts(url, final), ["huggingface.co", "cas-bridge.xethub.hf.co"])

    def test_setup_hint_names_the_hosts(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import kronos_setup as KS
        with mock.patch.dict(KS.CHILD, {"result": {"code": "NETWORK", "error": "URLError: getaddrinfo failed",
                                                   "hosts": ["huggingface.co", "us.aws.cdn.hf.co"]}}):
            code, msg = KS.child_error("")
        self.assertEqual(code, "NETWORK")
        self.assertIn("us.aws.cdn.hf.co", msg)
        self.assertIn("odblokuj te hosty", msg)
        with mock.patch.dict(KS.CHILD, {"result": {"code": "NETWORK", "error": "URLError"}}):        # starszy wynik bez hosts
            self.assertIn("huggingface.co", KS.child_error("")[1])


class TestI0127ResearchScriptsPortable(unittest.TestCase):
    """tools/research/tsfm_eval miały wpisane ścieżki scratchpada innej sesji i /home/user/1/backend oraz `from common import *`."""

    RESEARCH = ROOT / "tools" / "research"

    def test_no_session_paths_and_no_star_imports(self):
        import ast
        files = sorted(self.RESEARCH.rglob("*.py"))
        self.assertTrue(files)
        for f in files:
            text = f.read_text(encoding="utf-8")
            for bad in ("/tmp/claude-", "/home/user/", "scratchpad"):
                self.assertNotIn(bad, text, f"{f.name}: {bad}")
            stars = [n.module for n in ast.walk(ast.parse(text)) if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)]
            self.assertEqual(stars, [], f.name)

    def test_ruff_pyflakes_clean(self):
        import shutil
        import subprocess
        try:
            r = subprocess.run([sys.executable, "-m", "ruff", "check", "--select", "F", "--output-format", "concise", str(self.RESEARCH)],
                               capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            self.skipTest("ruff niedostępny")
        if r.returncode not in (0, 1) or ("No module named ruff" in r.stderr and not shutil.which("ruff")):
            self.skipTest("ruff niedostępny")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_prep_and_common_work_on_given_folders(self):
        sys.path.insert(0, str(self.RESEARCH / "tsfm_eval"))
        try:
            import common
            import prep
        finally:
            sys.path.remove(str(self.RESEARCH / "tsfm_eval"))
        self.assertEqual(common.BACKEND, ROOT / "backend")
        with tempfile.TemporaryDirectory() as d:
            csv_path = Path(d) / "m1.csv"
            t0 = datetime(2025, 10, 1)
            lines = []
            for i in range(3 * 24 * 60):
                t = t0 + timedelta(minutes=i)
                c = 2000 + (i % 97) * 0.1
                lines.append(f"{t:%Y.%m.%d},{t:%H:%M},{c - 0.2:.2f},{c + 0.5:.2f},{c - 0.5:.2f},{c:.2f}")
            csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                prep.main(["--csv", str(csv_path), "--out", d])
            t, o, h, low, c = common.load(d, "M5")
            self.assertEqual(len(t), 3 * 24 * 12)
            orig = common.origins(t, 12, ctx=100)
            r = common.score("naive", [c[i] for i in orig], orig, h, low, c, 12)
            self.assertEqual((r["n"], r["skill_vs_naive"]), (len(orig), 0.0))
            out = common.save([r], str(Path(d) / "res.json"), "unused.json")
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))[0]["model"], "naive")

    def test_eval_kronos_takes_paths_from_arguments(self):
        sys.path.insert(0, str(self.RESEARCH / "tsfm_eval"))
        try:
            import eval_kronos
        finally:
            sys.path.remove(str(self.RESEARCH / "tsfm_eval"))
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as cm:
            eval_kronos.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--weights", out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            eval_kronos.main([])                                                       # --data / --weights są wymagane


class TestI0197KronosDocs(unittest.TestCase):
    def test_installer_and_runtime_test_describe_the_pinned_pair(self):
        from kronos_runtime import install as I
        from kronos_runtime import lock
        self.assertIn(lock.MODEL["repo"], I.__doc__)
        self.assertNotIn("1.37: NeoQuasar/Kronos-base +", I.__doc__)
        doc = (Path(__file__).resolve().parent / "test_kronos_runtime.py").read_text(encoding="utf-8").split('"""')[1]
        self.assertNotIn("test_foundation_real", doc)                               # tam nie ma testów Kronos


class TestI0785ValidationSaveAtomic(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_report_written_through_a_temporary_file(self):
        from masterquo.kronos import validation as V
        with mock.patch.object(V.os, "replace", side_effect=OSError("dysk pełny")), self.assertRaises(OSError):
            V._save({"instrument": "XAUUSD", "timeframe": "M5", "status": "DONE"})
        self.assertEqual(list(V.reports_dir().glob("*.json")), [])                  # nigdy niepełny raport pod nazwą końcową
        rep = V._save({"instrument": "XAUUSD", "timeframe": "M5", "status": "DONE"})
        self.assertEqual(V.report_by_id(rep["report_id"])["status"], "DONE")
        self.assertEqual([f.name for f in V.reports_dir().iterdir() if not f.name.endswith(".json")], [])


if __name__ == "__main__":
    unittest.main()
