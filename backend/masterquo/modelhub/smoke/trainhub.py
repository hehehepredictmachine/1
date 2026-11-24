"""Smoke of the Training Center models (trainhub TH_*) and of Monte Carlo (paths + isotonic calibrator) - area `trainhub`.

TH_*: ONE synthetic export (ctx.store: FakeMT5 -> marketdata exporter, M5/M15/M30) and ONE shared trainhub.pipeline.stage_train with the
`smoke` profile and models=[all 6] (the pipeline trains a list of models in one call) -> per model: registry.activate (compatibility +
prediction test = load roundtrip of the saved package) -> TrainhubInference.predict (the bot's inference service, bars of the same
synthetic terminal) -> PMW-PRED-2 record, canonical id and modelhub.adapters.all_predictions.

Monte Carlo: forecast.export.export_candles with the synthetic terminal as MetaTrader5 (M1 dataset) -> montecarlo.validate.validate
(walk-forward, isotonic calibrator on CAL) -> validate.save / active_calibrator (registry roundtrip) -> MonteCarloService.compute (demo
mode and the calibrated path) -> quant.adapters.analysis (the Quant record of analysis:montecarlo).
"""
from __future__ import annotations

from . import check, fail, ok, skip, unverified

TH_MODELS = ("TH_BASELINE", "TH_LOGREG", "TH_HGB", "TH_XGB", "TH_RF", "TH_SVM")


# ---------------------------------------------------------------------------------------------------------------- helpers
def _where(exc: BaseException) -> str:
    """file:line of the deepest frame of the exception inside the project (evidence for a FAIL)."""
    import traceback
    frames = traceback.extract_tb(exc.__traceback__)
    for fr in reversed(frames):
        fn = fr.filename.replace("\\", "/")
        if "/masterquo/" in fn:
            return f"{fn[fn.rindex('/masterquo/') + 1:]}:{fr.lineno}"
    return f"{frames[-1].filename}:{frames[-1].lineno}" if frames else "?"


def _guard(ctx, out: dict, step: str, fn) -> bool:
    """Run one step; an exception is a FAIL of that step with file:line (the other steps of the producer are still reported)."""
    ctx.step = step
    try:
        out[step] = fn()
    except Exception as exc:  # noqa: BLE001 - any exception is a FAIL of the step being executed
        out[step] = fail(f"{type(exc).__name__}: {exc} | {_where(exc)}")
    return out[step]["status"] == "OK"


def _src_line(module, needle: str) -> str:
    """masterquo/<file>:<line> of the first source line containing `needle` (line numbers stay right when the file changes)."""
    import inspect
    from pathlib import Path
    lines, _ = inspect.getsourcelines(module)
    f = Path(inspect.getsourcefile(module)).as_posix()
    rel = f[f.rindex("/masterquo/") + 1:] if "/masterquo/" in f else f
    for i, ln in enumerate(lines):
        if needle in ln:
            return f"{rel}:{i + 1}"
    return f"{rel}:?"


class _Bridge:
    """Read-only view of the synthetic terminal (ctx.fake) with the MarketBridge methods and row format the two services call:
    symbol_bars / symbol_meta (TrainhubInference), bars('M1', include_forming=False) / symbol_info / quote_status (MonteCarloService).
    Closed bars only, UTC open_utc from the terminal offset (ctx.bars)."""

    def __init__(self, ctx):
        self.ctx = ctx
        f = ctx.fake()
        info = f.symbol_info(f.symbol)
        self.symbol_info = {"point": getattr(info, "point", None), "trade_tick_size": getattr(info, "trade_tick_size", None)}

    def symbol_bars(self, symbol: str, tf: str, count: int) -> list[dict]:
        return self.ctx.bars(tf, int(count)) if symbol == self.ctx.fake().symbol else []

    def symbol_meta(self, symbol: str, *a, **kw) -> dict | None:
        return dict(self.symbol_info) if symbol == self.ctx.fake().symbol else None

    def bars(self, tf: str, limit: int | None = None, include_forming: bool = True) -> list[dict]:
        return self.ctx.bars(tf, int(limit or 3000))

    def quote_status(self) -> dict | None:
        f = self.ctx.fake()
        t = f.symbol_info_tick(f.symbol)
        return {"bid": float(t.bid), "ask": float(t.ask)} if t else None


# ---------------------------------------------------------------------------------------------------------------- TH_* (shared training)
def _th_shared(ctx) -> dict:
    """One export + one stage_train of all six models per area process (cached on ctx)."""
    sh = getattr(ctx, "_trainhub_shared", None)
    if sh is not None:
        return sh
    sh = {}
    ctx._trainhub_shared = sh
    import time
    try:
        ctx.step = "train"
        from ...config import ConfigStore
        from ...trainhub import pipeline as P
        from ...trainhub.inference import TrainhubInference
        t0 = time.monotonic()
        st = ctx.store(timeframes=("M5", "M15", "M30"), lookback_days=30, history_days=40)
        sh["export_s"] = round(time.monotonic() - t0, 1)
        man = st.manifest(ctx.inst)
        sh["data_kind"] = man.get("data_kind")
        cfg = P.config({"profile": "smoke", "models": list(TH_MODELS)}, man)
        t1 = time.monotonic()
        out = P.stage_train(st, ctx.inst, cfg)
        sh["train_s"] = round(time.monotonic() - t1, 1)
        sh["out"] = out
        sh["skipped"] = {s["model"]: s["reason"] for s in out.get("skipped") or []}
        sh["inf"] = TrainhubInference(ConfigStore(), _Bridge(ctx))
    except Exception as exc:  # noqa: BLE001 - reported by every TH_* id as a FAIL of the step that broke
        sh["error"] = (ctx.step, f"{type(exc).__name__}: {exc} | {_where(exc)}")
    return sh


def _pkg_of(sh: dict, mid: str) -> dict | None:
    for p in sh["out"]["packages"]:
        if p["model_key"].startswith(mid + "_"):
            return p
    return None


def _th_factory(mid: str):
    cid = f"trainhub:{mid}"

    def _smoke(ctx) -> dict:
        import math
        import types
        sh = _th_shared(ctx)
        if "error" in sh:
            step, msg = sh["error"]
            return {step: fail(msg)}
        if mid in sh["skipped"]:
            why = sh["skipped"][mid]
            return {"train": unverified(f"{mid} pominięty przez stage_train: {why}") if "niedostępna" in why else fail(f"{mid} pominięty: {why}")}
        pk = _pkg_of(sh, mid)
        if pk is None:
            return {"train": fail(f"stage_train nie zwrócił paczki {mid} (pakiety: {[p['model_key'] for p in sh['out']['packages']]})")}
        out: dict = {}
        from ...trainhub import registry as R
        key, ver = pk["model_key"], pk["version"]

        def _train():
            ho, sp = pk.get("holdout") or {}, sh["out"]["split"]
            ll, base = ho.get("log_loss"), ho.get("baseline_log_loss")
            good = isinstance(ll, (int, float)) and math.isfinite(ll) and isinstance(base, (int, float)) and sp["holdout"] > 0
            return check(good, f"pipeline.stage_train profil smoke, wspólny trening 6 modeli ({sh['train_s']} s, eksport {sh['export_s']} s, "
                               f"{sh['data_kind']}): {key} wersja {ver[-13:]}, dev {sp['dev']} / holdout {sp['holdout']}, foldy {sp['folds']}; "
                               f"holdout log_loss {ll} (bazowy {base}) – test techniczny, nie jakość",
                         f"paczka {key} bez metryk holdout: {ho} (split {sp})")
        _guard(ctx, out, "train", _train)

        def _artifact():
            a = R.activate(ctx.inst, key, ver, reason="models check --smoke")
            pt = a.get("prediction_test") or {}
            reg_ok = (R.registry(ctx.inst).get("active") or {}).get(key) == ver
            extra = ""
            if mid == "TH_XGB":
                from pathlib import Path
                extra = f"; natywny model_xgb.json {'jest' if (Path(pk['path']) / 'model_xgb.json').is_file() else 'BRAK'}"
            if mid == "TH_SVM":
                obj, _, _ = R.load(ctx.inst, key, ver)
                est = obj["estimator"]
                if getattr(est, "svm", None) is None:
                    from ...trainhub import learn as L
                    return fail(f"TH_SVM po wczytaniu jest Prior (brak klas w bloku kalibracji) – de facto baseline pod nazwą SVM "
                                f"({_src_line(L, 'self.svm, self.cal, self.prior = None')})")
                extra = f"; SVM kernel {getattr(est, 'used_kernel', '?')} + mapa logistyczna (nie Prior)"
            good = a.get("status") == "ACTIVE" and pt.get("ok") is True and reg_ok and "max_abs_diff_final" in pt
            return check(good, f"zapis paczki (joblib + sha256 manifest) -> registry.activate: zgodność OK, test predykcji po wczytaniu "
                               f"max_abs_diff {pt.get('max_abs_diff')} / końcowe {pt.get('max_abs_diff_final')} ({pt.get('rows')} wierszy), "
                               f"ACTIVE w registry.json{extra}",
                         f"aktywacja {key}: {a.get('status')} {a.get('reason') or ''} test {pt} (registry active={reg_ok})")
        art_ok = _guard(ctx, out, "artifact", _artifact)

        if not art_ok:
            out["predict"] = skip("paczka nieaktywna – inferencja bota czyta tylko aktywne wersje")
            return out
        rec: dict = {}

        def _predict():
            p = sh["inf"].predict(ctx.inst, key, ver, force=True)
            rec.update(p)
            res = p.get("result") or {}
            vals = [res.get(k) for k in ("DOWN", "FLAT", "UP")]
            good = (p.get("state") == "READY" and all(isinstance(v, (int, float)) and 0.0 <= v <= 1.0 for v in vals)
                    and abs(sum(vals) - 1.0) < 1e-5)
            return check(good, f"TrainhubInference.predict (paczka aktywna, cechy features.last_row ze świec terminala): READY {p.get('task')} "
                               f"P(DOWN/FLAT/UP)={vals}, dane {p.get('data_time')} świeżość {p.get('freshness_s')} s, {p.get('compute_ms')} ms",
                         f"inferencja {key}: {p.get('state')} {p.get('unavailable_reason') or ''} wynik {res}")
        pred_ok = _guard(ctx, out, "predict", _predict)

        if pred_ok:
            def _contract():
                from ...quant import ids as I
                from .. import adapters as AD
                c = ctx.contract_step([rec])
                can = I.canonical(rec)
                rt = types.SimpleNamespace(trainhub_inference=sh["inf"])
                seen = [p for p in AD.all_predictions(rt, ctx.inst) if p.get("model_key") == key and p.get("model_version") == ver]
                if c["status"] != "OK":
                    return c
                return check(can == cid and len(seen) == 1,
                             f"{c['detail']}; canonical {can}; rekord w modelhub.adapters.all_predictions; kalibracja "
                             f"{(rec.get('calibration') or {}).get('status')}",
                             f"canonical {can} (oczekiwane {cid}), rekordów w all_predictions: {len(seen)}")
            _guard(ctx, out, "contract", _contract)
        return out

    _smoke.__name__ = f"_smoke_{mid.lower()}"
    return _smoke


# ---------------------------------------------------------------------------------------------------------------- Monte Carlo
def _mc_dataset(ctx):
    """Synthetic M1 dataset written by the real exporter (forecast.export.export_candles, kind=training) with the area's synthetic
    terminal installed as the MetaTrader5 module; the terminal is re-initialised afterwards (the exporter shuts its connection)."""
    import contextlib
    import io
    import sys
    f = ctx.fake()
    ds = ctx.data_dir / "smoke_montecarlo" / "dataset"
    prev = sys.modules.get("MetaTrader5")
    sys.modules["MetaTrader5"] = f
    buf = io.StringIO()
    try:
        from ...forecast.export import export_candles
        with contextlib.redirect_stdout(buf):
            rc = export_candles(1, str(ds), "AUTO", ("M1",), "training", ctx.inst, f.symbol, tick_days=0.5)
    finally:
        if prev is None:
            sys.modules.pop("MetaTrader5", None)
        else:
            sys.modules["MetaTrader5"] = prev
        f.initialize()
    if rc != 0:
        tail = " | ".join(x for x in buf.getvalue().strip().splitlines()[-3:])
        raise RuntimeError(f"export_candles kod {rc}: {tail}"[:300])
    return ds


def _grid_diff(c1: dict, c2: dict) -> float:
    from ...montecarlo import validate as V
    return max(abs(V.apply_calibrator(c1, k / 50) - V.apply_calibrator(c2, k / 50)) for k in range(51))


def _smoke_montecarlo(ctx) -> dict:
    import json
    import time
    import types

    from ...config import ConfigStore
    from ...montecarlo import engine as E
    from ...montecarlo import validate as V
    from ...montecarlo.service import MonteCarloService
    out: dict = {}
    mc: dict = {}

    def _train():
        t0 = time.monotonic()
        ds = _mc_dataset(ctx)
        t1 = time.monotonic()
        rep = V.validate(ds, max_points=80, n_paths=100, log=lambda m: None)
        mc["rep"] = rep
        cal = (rep.get("calibrator") or {}).get("calibrator") or {}
        good = (rep.get("status") == "DONE" and rep.get("verdict") == "TEST_TECHNICZNY" and cal.get("kind") == "ISOTONIC" and len(cal.get("x") or []) >= 2
                and rep.get("chosen_variant") in E.VARIANTS)
        return check(good, f"export_candles M1 1 mies. + ticki 0,5 dnia ({t1 - t0:.1f} s, {rep.get('data_kind')}) -> validate.validate walk-forward "
                           f"(80 punktów, 100 ścieżek, {time.monotonic() - t1:.1f} s): DONE, wariant {rep.get('chosen_variant')} wybrany na CAL, "
                           f"kalibrator ISOTONIC {len(cal.get('x') or [])} progów, werdykt TEST_TECHNICZNY (syntetyka)",
                     f"validate: {rep.get('status')} {rep.get('reason') or ''} werdykt {rep.get('verdict')} kalibrator {cal.get('kind')}")
    if not _guard(ctx, out, "train", _train):
        return out

    def _artifact():
        rep = mc["rep"]
        s = V.save(ctx.inst, rep)
        from pathlib import Path
        saved = json.loads((Path(s["dir"]) / "report.json").read_text(encoding="utf-8"))
        d_rep = _grid_diff(rep["calibrator"], saved["calibrator"])
        gate = s["activated"] is False and V.active_calibrator(ctx.inst) is None
        # the ACTIVE load path exists only for REAL_USER_DATA with an edge: a crafted copy of THIS report checks that loader, then rollback
        a = V.save(ctx.inst, dict(rep, data_kind="REAL_USER_DATA", verdict="PRZEWAGA_NAD_BAZOWYM"))
        act = V.active_calibrator(ctx.inst)
        mc["cal"] = act
        d_act = _grid_diff(rep["calibrator"], act) if act else None
        good = (gate and d_rep == 0.0 and a["activated"] and act is not None and act.get("status") == "ACTIVE" and d_act == 0.0
                and act.get("variant") == rep["chosen_variant"])
        return check(good, f"validate.save (synthetic): activated=False – odmowa aktywacji zgodnie z bramką (tylko REAL_USER_DATA z przewagą); "
                           f"report.json odczytany: różnica kalibratora {d_rep}; spreparowana kopia REAL -> active_calibrator: ACTIVE "
                           f"{act.get('variant') if act else None}, różnica {d_act} (cofnięta rollbackiem po predykcji)",
                     f"bramka {gate} (activated {s['activated']}), różnica report.json {d_rep}, kopia REAL activated {a['activated']}, "
                     f"odczyt {None if act is None else act.get('status')}, różnica {d_act}")
    _guard(ctx, out, "artifact", _artifact)

    bridge = _Bridge(ctx)
    demo = MonteCarloService(ConfigStore(), bridge, synthetic=True, n_paths=300)
    try:
        def _predict():
            r = demo.compute(None, horizon=60)
            mc["demo"] = r
            sc = r.get("scenarios") or {}
            pr = (sc.get("p_up_reach") or []) + (sc.get("p_down_reach") or [])
            good_demo = (r.get("status") == "OK" and r.get("probability_kind") == "MODEL_SIMULATED" and r.get("calibrated") is False
                         and r.get("variant") == "BLOCK" and pr and all(0.0 <= x <= 1.0 for x in pr))
            txt = (f"MonteCarloService.compute (tryb demo, {(r.get('data') or {}).get('bars')} świec M1, {r.get('n_paths')} ścieżek): {r.get('status')} "
                   f"{r.get('probability_kind')} wariant {r.get('variant')} (nie z walidacji), P(+2,5)={round(pr[0], 3) if pr else None}")
            if not good_demo:
                return fail(f"{txt}; {r.get('reason') or ''}")
            cal = mc.get("cal")
            if not cal:
                return ok(txt + "; ścieżka kalibratora nie sprawdzona (brak aktywnego kalibratora z kroku artefaktu)")
            svc = MonteCarloService(ConfigStore(), bridge, synthetic=False, n_paths=300)
            try:
                plan = svc.plan_for("BUY", 3.0, [2.5, 4.0], horizon=60)
                rc = svc.compute([plan], horizon=60)
            finally:
                svc.stop()
            lv = ((rc.get("plans") or [{}])[0].get("levels")) or []
            st = [x.get("calibration_status") for x in lv]
            p_cons = lv[0].get("p_tp_before_sl_conservative") if lv else None
            want = V.apply_calibrator(cal, p_cons) if p_cons is not None else None
            got = lv[0].get("p_calibrated") if lv else None
            good = (rc.get("status") == "OK" and rc.get("variant") == cal["variant"] and st == ["CALIBRATED", "CALIBRATOR_EVENT_MISMATCH"]
                    and got is not None and got == want)
            return check(good, f"{txt}; z aktywnym kalibratorem (serwis poza demo, dane FakeMT5): wariant {rc.get('variant')}, TP 2,5 CALIBRATED "
                               f"p_model {round(p_cons, 3)} -> p_cal {round(got, 3)}, TP 4,0 CALIBRATOR_EVENT_MISMATCH",
                         f"{txt}; ścieżka kalibratora: {rc.get('status')} wariant {rc.get('variant')} statusy {st} p_cal {got} oczekiwane {want}")
        try:
            _guard(ctx, out, "predict", _predict)
        finally:
            if mc.get("cal"):
                V.rollback(ctx.inst)
                if V.active_calibrator(ctx.inst) is not None:
                    out["artifact"] = fail("validate.rollback nie zdjął spreparowanego kalibratora")

        def _contract():
            from ...quant import adapters as QA
            r = mc.get("demo") or {}
            recs = [p for p in QA.analysis(types.SimpleNamespace(montecarlo=demo), ctx.inst) if p.get("canonical_id") == "analysis:montecarlo"]
            if len(recs) != 1:
                return fail(f"quant.adapters.analysis zwrócił {len(recs)} rekordów analysis:montecarlo")
            p = recs[0]
            errs = ctx.contract_errors(p)
            if errs:
                return fail("; ".join(errs))
            if r.get("status") == "OK" and p.get("state") != "READY":
                from ...montecarlo import service as MS
                st = demo.status()
                miss_st = [k for k in ("last", "result") if k not in st]
                miss_res = [k for k in ("p_tp_first", "p_sl_first", "method") if k not in r]
                line_last = _src_line(QA, 'st.get("last")').rsplit(":", 1)[1]
                where_adapter = f"{_src_line(QA, 'mc.status()')}-{line_last}"
                where_status = _src_line(MS, "def status(self)")
                return fail(f"{where_adapter}: rekord analysis:montecarlo = {p.get('state')} mimo compute OK – adapter czyta "
                            f"klucze {miss_st} nieobecne w MonteCarloService.status() ({where_status}); pól {miss_res} nie ma też w wyniku "
                            "engine.run – Quant nigdy nie dostaje wyniku MC (naprawa: decyzja D11); kontrakt PMW-PRED-2 rekordu poprawny")
            return check(p.get("state") == "READY" and bool(p.get("result")), f"PMW-PRED-2 analysis:montecarlo {p.get('state')} {p.get('result')}",
                         f"rekord analysis:montecarlo {p.get('state')} bez wyniku przy compute {r.get('status')}")
        _guard(ctx, out, "contract", _contract)
    finally:
        demo.stop()
    return out


SMOKES = {**{f"trainhub:{m}": _th_factory(m) for m in TH_MODELS}, "analysis:montecarlo": _smoke_montecarlo}
