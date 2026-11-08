"""Extended adapters of EXISTING live outputs to PMW-PRED-2 (PMW-QUANT-ADAPT-1) - for producers outside modelhub.adapters.all_predictions.

Single owner rule: an adapter READS the cached result of the service that owns the computation (MM loop, SH context, indicators, zones,
lab loop, Monte Carlo). Only producers WITHOUT their own cycle are computed by the Quant scheduler itself: the Event GRU (no live path
existed - the family adapter SEQ_GRU_EVENT returned None and the MM service only listed the artifact) and scalp task A (computed only on
a panel request). A missing source is a state with a reason, never a value; every adapter failure becomes an ERROR record, never silence.

Setup-scoped models (sh_tp_model, legacy_ml, scalp_B, ml_scalp, nss, indicator_context) have no standalone prediction: their output
exists per strategy candidate and reaches the evaluation ledger. They are listed by `setup_scoped()` with the live probe state - no
invented standalone record.
"""
from __future__ import annotations

import math
import threading
import time

from ..modelhub import contract as C
from ..timeutil import iso

VERSION = "PMW-QUANT-ADAPT-1"
SETUP_SCOPED = ("sh_tp_model", "legacy_ml", "scalp_B", "ml_scalp", "nss", "indicator_context")


def clean(d, depth: int = 0):
    """State payload safe for the contract: strings / finite numbers / nested dicts / numeric lists; bool -> 'TAK'/'NIE' text, None and
    non-finite dropped (a missing value is absent, never 0)."""
    if depth > 4:
        return None
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            if isinstance(v, bool):
                out[str(k)] = "TAK" if v else "NIE"
            elif isinstance(v, (int, float)):
                if math.isfinite(v):
                    out[str(k)] = v
            elif isinstance(v, str):
                out[str(k)] = v[:200]
            elif isinstance(v, dict):
                c = clean(v, depth + 1)
                if c:
                    out[str(k)] = c
            elif isinstance(v, (list, tuple)) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v):
                out[str(k)] = list(v)[:50]
        return out
    return None


def _p(**kw) -> dict:
    cid = kw.pop("canonical_id")
    extra = kw.pop("extra", None) or {}
    extra = {"canonical_id": cid, "model_key": cid, **extra}
    kw.setdefault("model_version", None)
    kw.setdefault("symbol", None)
    if kw.get("state") == "READY" and not kw.get("data_time"):
        kw.update(state="BLOCKED_DATA", result=None, unavailable_reason="brak czasu danych wyniku (nie można ocenić świeżości)")
    return C.make(extra=extra, **kw)


def _err(cid, inst, tf, task_type, task, unit, exc, horizon=None) -> dict:
    return _p(canonical_id=cid, instrument=inst, timeframe=tf, model_name=cid, task_type=task_type, task=task, horizon_bars=horizon, unit=unit,
              state="ERROR", unavailable_reason=f"adapter: {type(exc).__name__}: {exc}"[:200])


# ---------------------------------------------------------------------------------------------------------------- rules (SH context)
def rules(rt, inst: str) -> list[dict]:
    out = []
    sh = getattr(rt, "sh", None)
    snap = getattr(sh, "snapshot", None) if sh is not None else None
    if not snap:
        for cid in ("rule:regime_v2", "rule:structure_v2", "rule:atr_vol", "rule:data_quality"):
            out.append(_p(canonical_id=cid, instrument=inst, timeframe="M5", model_name=cid, task_type="STATE", task=cid.split(":")[1].upper(),
                          horizon_bars=None, unit="state", state="BLOCKED_DATA", unavailable_reason="brak migawki kontekstu SH (pierwszy cykl po starcie / brak danych)"))
        return out
    dt = iso(snap.get("computed_at")) if isinstance(snap.get("computed_at"), (int, float)) else snap.get("computed_at")
    for cid, key, tf, unit in (("rule:regime_v2", "regime", "M5", "state"), ("rule:data_quality", "data", None, "state"), ("rule:atr_vol", "vol", "M5", "price")):
        v = snap.get(key)
        res = clean(v) if isinstance(v, dict) else None
        ok = bool(res) and str((v or {}).get("status", "OK")).upper() not in ("ERROR", "WARMUP")
        out.append(_p(canonical_id=cid, instrument=inst, timeframe=tf, model_name=cid, task_type="STATE", task=cid.split(":")[1].upper(), horizon_bars=None,
                      unit=unit, state="READY" if ok else ("ERROR" if (v or {}).get("status") == "ERROR" else "BLOCKED_DATA"), result=res if ok else None,
                      data_time=dt, unavailable_reason=None if ok else f"{(v or {}).get('status', 'brak')}: {(v or {}).get('reason') or 'rozgrzewanie / brak świec'}",
                      source="sh.context", extra={"analytic_role": "CONTEXT_FEATURE" if cid != "rule:data_quality" else "GATE_EXISTING"}))
    st = {tf: snap.get(f"structure_{tf}") for tf in ("M5", "M15", "H1")}
    res = {tf: clean(v) for tf, v in st.items() if isinstance(v, dict) and v.get("status") not in ("ERROR", "WARMUP")}
    res = {k: v for k, v in res.items() if v}
    out.append(_p(canonical_id="rule:structure_v2", instrument=inst, timeframe="M5", model_name="rule:structure_v2", task_type="STATE", task="STRUCTURE_V2",
                  horizon_bars=None, unit="state", state="READY" if res else "BLOCKED_DATA", result=res or None, data_time=dt,
                  unavailable_reason=None if res else "struktura w rozgrzewaniu / błąd", source="sh.context", extra={"analytic_role": "CONTEXT_FEATURE"}))
    news = getattr(rt, "news", None)
    if news is not None:
        try:
            s = news.summary() or {}
            out.append(_p(canonical_id="rule:news", instrument=inst, timeframe=None, model_name="rule:news", task_type="STATE", task="NEWS_BLACKOUT",
                          horizon_bars=None, unit="state", state="READY", result=clean({k: s.get(k) for k in ("status", "blackout", "next_event_in_s")}) or {"status": "?"},
                          data_time=iso(time.time()), source="news", extra={"analytic_role": "GATE_EXISTING"}))
        except Exception as exc:  # noqa: BLE001
            out.append(_err("rule:news", inst, None, "STATE", "NEWS_BLACKOUT", "state", exc))
    return out


# ---------------------------------------------------------------------------------------------------------------- indicators / DXY / zones / MC
def analysis(rt, inst: str) -> list[dict]:
    out = []
    ind = getattr(rt, "indicators", None)
    if ind is not None:
        try:
            s = ind.current()
            if not s:
                raise LookupError("brak migawki PMW-IND-1")
            cp = ind.compact(s)
            as_of = cp.get("as_of")
            body = clean({k: cp.get(k) for k in ("avwap", "semivar", "spread", "profile", "microstructure")}) or None
            out.append(_p(canonical_id="analysis:indicators", instrument=inst, timeframe="M1", model_name="analysis:indicators", task_type="STATE",
                          task="INDICATORS_PMW_IND_1", horizon_bars=None, unit="mixed", state="READY" if body else "BLOCKED_DATA", result=body, data_time=as_of,
                          unavailable_reason=None if body else "migawka bez wartości", source="indicators", extra={"analytic_role": "CONTEXT_FEATURE"}))
            dx = clean(cp.get("dxy"))
            out.append(_p(canonical_id="analysis:dxy_correlation", instrument=inst, timeframe="H1", model_name="analysis:dxy_correlation", task_type="STATE",
                          task="XAU_DXY_RELATION_H1", horizon_bars=None, unit="mixed", state="READY" if dx else "BLOCKED_DATA", result=dx or None, data_time=as_of,
                          unavailable_reason=None if dx else "brak źródła DXY (stan danych, nie zero)", source="indicators.dxy",
                          extra={"analytic_role": "CONTEXT_FEATURE"}))
        except LookupError as exc:
            for cid, tf in (("analysis:indicators", "M1"), ("analysis:dxy_correlation", "H1")):
                out.append(_p(canonical_id=cid, instrument=inst, timeframe=tf, model_name=cid, task_type="STATE", task=cid.split(":")[1].upper(), horizon_bars=None,
                              unit="mixed", state="BLOCKED_DATA", unavailable_reason=str(exc)))
        except Exception as exc:  # noqa: BLE001
            out.append(_err("analysis:indicators", inst, "M1", "STATE", "INDICATORS_PMW_IND_1", "mixed", exc))
    zs = getattr(rt, "zones", None)
    if zs is not None:
        try:
            zm = zs.current()
            summ = clean((zm or {}).get("summary") or {})
            ok = bool(zm) and bool(summ) and not zm.get("restored")
            out.append(_p(canonical_id="analysis:zones", instrument=inst, timeframe="M5", model_name="analysis:zones", task_type="STATE", task="ZONE_MAP_SUMMARY",
                          horizon_bars=None, unit="state", state="READY" if ok else "BLOCKED_DATA", result=summ if ok else None,
                          data_time=(zm or {}).get("as_of") or (zm or {}).get("map_as_of"), source="zones",
                          unavailable_reason=None if ok else "brak bieżącej mapy stref (lub mapa odtworzona – STALE)", extra={"analytic_role": "CONTEXT_FEATURE"}))
        except Exception as exc:  # noqa: BLE001
            out.append(_err("analysis:zones", inst, "M5", "STATE", "ZONE_MAP_SUMMARY", "state", exc))
    mc = getattr(rt, "montecarlo", None)
    if mc is not None:
        try:
            st = mc.status() or {}
            last = st.get("last") or st.get("result")
            ok = isinstance(last, dict) and last.get("status") in ("OK", "READY", "DONE")
            out.append(_p(canonical_id="analysis:montecarlo", instrument=inst, timeframe=None, model_name="analysis:montecarlo", task_type="STATE",
                          task="PATH_SIMULATION_MODEL_SIMULATED", horizon_bars=None, unit="mixed", state="READY" if ok else "DISABLED",
                          result=clean({k: last.get(k) for k in ("p_tp_first", "p_sl_first", "n_paths", "seed", "horizon_bars", "method")}) if ok else None,
                          data_time=(last or {}).get("as_of") if ok else None,
                          unavailable_reason=None if ok else "symulacja uruchamiana na żądanie (brak bieżącego wyniku); wynik MODEL_SIMULATED ≠ skalibrowane p",
                          source="montecarlo", calibration={"method": None, "status": "UNCALIBRATED"} if ok else None,
                          extra={"analytic_role": "SIMULATION", "probability_kind": "MODEL_SIMULATED"}))
        except Exception as exc:  # noqa: BLE001
            out.append(_err("analysis:montecarlo", inst, None, "STATE", "PATH_SIMULATION_MODEL_SIMULATED", "mixed", exc))
    return out


# ---------------------------------------------------------------------------------------------------------------- MM (read the MM loop cache)
def mm(rt, inst: str) -> list[dict]:
    svc = getattr(rt, "mm", None)
    if svc is None:
        return []
    ids = ("mm:kalman_cross", "mm:breakout_zones", "mm:multi_indicator", "mm:smc_fvg", "mm:align_mean", "mm:gpr_logret")
    c = (getattr(svc, "_cache", {}) or {}).get(inst)
    v = (c or {}).get("value") if c else None
    if not v or v.get("status") != "OK":
        why = (v or {}).get("reason") or "pętla MM nie policzyła jeszcze zamkniętej świecy M5 dla instrumentu"
        return [_p(canonical_id=cid, instrument=inst, timeframe="M5", model_name=cid, task_type="REGRESSION" if cid.endswith("gpr_logret") else "STATE",
                   task=cid.split(":")[1].upper(), horizon_bars=3 if cid.endswith("gpr_logret") else None, unit="log_return" if cid.endswith("gpr_logret") else "state",
                   state="BLOCKED_DATA", unavailable_reason=why[:200]) for cid in ids]
    dt = iso(float(v["last_closed_m5"]))
    av = iso(float(v["last_closed_m5"]) + 300)
    kind = "SYNTHETIC" if v.get("data_quality") == "SYNTHETIC_TEST" else "REAL"
    out = []

    def st(cid, task, tt, res, why_missing):
        ok = bool(res)
        if tt == "FILTER_STATE" and ok and not isinstance(res.get("state"), str):
            ok = False
        out.append(_p(canonical_id=cid, instrument=inst, timeframe="M5", model_name=cid, task_type=tt, task=task, horizon_bars=None, unit="state",
                      state="READY" if ok else "BLOCKED_DATA", result=res if ok else None, data_time=dt, available_at=av, data_kind=kind, source="mm.service",
                      unavailable_reason=None if ok else why_missing, extra={"analytic_role": "CONTEXT_FEATURE"}))
    try:
        k = v.get("kalman") or {}
        st("mm:kalman_cross", "KALMAN_CROSS_STATE", "FILTER_STATE", clean({k2: k.get(k2) for k2 in ("state", "fast", "slow", "K_fast", "K_slow", "events_in_window")}),
           "brak stanu Kalmana")
        bz = (v.get("breakout") or {}).get("panel") or {}
        st("mm:breakout_zones", "BREAKOUT_ZONES_STATE", "FILTER_STATE", clean({"state": bz.get("direction"), **{x: bz.get(x) for x in bz if x != "direction"}}),
           "brak panelu wybicia")
        mi = v.get("multi_indicator") or {}
        st("mm:multi_indicator", "MULTI_INDICATOR_DECISION", "STATE", clean({"decision": mi.get("decision"), "status": mi.get("status")}), "brak decyzji reguł")
        sf = v.get("smc_fvg") or {}
        st("mm:smc_fvg", "SMC_FVG_STATE", "STATE", clean({"trend": sf.get("trend"), "live_setups": len(sf.get("live_setups") or [])}), "brak stanu SMC")
        am = {}
        for ch in (v.get("align_mean") or {}).get("charts") or []:
            if ch.get("status") != "NO_DATA":
                for kk, vv in ch.items():
                    if kk.startswith("dist") and isinstance(vv, (int, float)) and not isinstance(vv, bool) and math.isfinite(vv):
                        am[f"{ch.get('tf')}_{kk}"] = vv
        st("mm:align_mean", "ALIGN_MEAN_DISTANCE", "STATE", am, "brak odległości od średniej")
    except Exception as exc:  # noqa: BLE001
        out.append(_err("mm:context", inst, "M5", "STATE", "MM_CONTEXT", "state", exc))
    g = v.get("gpr") or {}
    try:
        if g.get("status") in ("OK", "DEGRADED") and C.is_num(g.get("mean_logret")) and C.is_num(g.get("sd")):
            cal = (g.get("live_calibration") or {})
            out.append(_p(canonical_id="mm:gpr_logret", instrument=inst, timeframe="M5", model_name="mm:gpr_logret", model_version="PMW-MM-GPR-1",
                          task_type="REGRESSION", task="LOG_RETURN_H3_M5", horizon_bars=int(g.get("horizon_bars") or 3), unit="log_return", state="READY",
                          result={"mean": float(g["mean_logret"]), "sd": float(g["sd"]), "lo": float(g["mean_logret"]) - float(g["sd"]),
                                  "hi": float(g["mean_logret"]) + float(g["sd"])},
                          data_time=dt, available_at=av, data_kind=kind, source="mm.service",
                          calibration={"method": "pokrycie 1σ na żywo (ledger SHADOW)", "status": "UNCALIBRATED"},
                          extra={"analytic_role": "BASE_FORECAST", "live_coverage_1sd": cal.get("coverage_1sd"), "n_scored": cal.get("n_scored"),
                                 "note": "rozkład terminalny log-zwrotu – nie P(TP przed SL)"}))
        else:
            out.append(_p(canonical_id="mm:gpr_logret", instrument=inst, timeframe="M5", model_name="mm:gpr_logret", task_type="REGRESSION", task="LOG_RETURN_H3_M5",
                          horizon_bars=3, unit="log_return", state="BLOCKED_DATA" if g.get("status") != "ERROR" else "ERROR",
                          unavailable_reason=f"GPR: {g.get('status')}: {g.get('reason') or ''}"[:200]))
    except Exception as exc:  # noqa: BLE001
        out.append(_err("mm:gpr_logret", inst, "M5", "REGRESSION", "LOG_RETURN_H3_M5", "log_return", exc, 3))
    return out


# ---------------------------------------------------------------------------------------------------------------- Event GRU (owner: Quant)
class EventGRU:
    """Live inference of the ACTIVE event_engine_dir3 artifact (MM pointer). The event source is the one the artifact was trained on
    (manifest event_source: REAL_TICKS -> bridge.ticks, BAR_CLOSE_EVENTS -> closed M1 bars); a different source is INCOMPATIBLE.
    Stateless per call (the whole recent window is re-encoded) - no hidden state crosses instruments or artifacts."""
    CID = "mm:event_engine_dir3"

    def __init__(self):
        self._lock = threading.Lock()
        self._loaded: dict = {}
        self.latest: dict[str, dict] = {}

    def _none(self, inst, state, why, ver=None) -> dict:
        return _p(canonical_id=self.CID, instrument=inst, timeframe="EVENT", model_name=self.CID, model_version=ver, task_type="CLASS_PROBABILITIES",
                  task="EVENT_UNITS_DIR3", horizon_bars=2, unit="probability", state=state, unavailable_reason=why[:200],
                  extra={"family": "SEQ_GRU_EVENT", "use": "SHADOW"})

    def predict(self, rt, inst: str) -> dict:
        import numpy as np

        from ..mm import artifacts as MA
        from ..mm import data as D
        from ..mm import event_engine as EE
        from ..mm import events as EV
        try:
            aid = (MA.read_pointer(inst).get("active") or {}).get("event_engine_dir3")
        except Exception as exc:  # noqa: BLE001
            return self._none(inst, "ERROR", f"wskaźnik artefaktów MM: {type(exc).__name__}")
        if not aid:
            p = self._none(inst, "NOT_TRAINED", "brak aktywnego artefaktu event_engine_dir3 (trening w Centrum MM + walidacja VALIDATED_SHADOW)")
            self.latest[inst] = p
            return p
        try:
            with self._lock:
                if (inst, aid) not in self._loaded:
                    st, man = MA.load(inst, "event_engine_dir3", aid)
                    m = EE.EventModel.from_state(st)
                    sc = EV.Scaler()
                    sc.med, sc.iqr = np.asarray(st["scaler_med"], float), np.asarray(st["scaler_iqr"], float)
                    self._loaded = {(inst, aid): (m, sc, man)}           # one artifact in memory (switching drops the old one)
                m, sc, man = self._loaded[(inst, aid)]
        except Exception as exc:  # noqa: BLE001
            p = self._none(inst, "INCOMPATIBLE", f"artefakt {aid}: {type(exc).__name__}: {exc}", aid)
            self.latest[inst] = p
            return p
        src = man.get("event_source") or "BAR_CLOSE_EVENTS"
        br = rt.bridge
        t0 = time.perf_counter()
        try:
            if src == "REAL_TICKS":
                sym = getattr(getattr(br, "cfg", None), "symbol", None)
                tk = br.ticks(sym, seconds=1800)
                if not tk.get("ticks"):
                    raise LookupError(f"brak ticków ({tk.get('reason') or tk.get('status')})")
                ev = D.events_from_ticks(tk["ticks"])
            else:
                from ..mm.service import _to_bars
                b1 = _to_bars(br.bars("M1", include_forming=False), "M1")
                if b1 is None or len(b1) < 16 * 3 + 2:
                    raise LookupError("za mało zamkniętych świec M1")
                pt = float((getattr(br, "symbol_info", None) or {}).get("point") or 0.01)
                ev = D.events_from_bars(b1, pt)
            acc = EV.from_arrays(ev, inst, 900)
            u = EV.units(acc, EV.featurize(acc), 16)
            if not len(u["X"]):
                raise LookupError("brak pełnej jednostki 16 zdarzeń")
            P = EE.predict(m, sc.transform(u["X"]), u["segment"])[-1]
        except LookupError as exc:
            p = self._none(inst, "BLOCKED_DATA", f"{src}: {exc}", aid)
            self.latest[inst] = p
            return p
        except Exception as exc:  # noqa: BLE001
            p = self._none(inst, "ERROR", f"{type(exc).__name__}: {exc}", aid)
            self.latest[inst] = p
            return p
        res = {"DOWN": float(P[0]), "FLAT": float(P[1]), "UP": float(P[2])}
        tot = sum(res.values())
        if abs(tot - 1.0) > 1e-6:                                 # never renormalised silently: a broken softmax is an error
            p = self._none(inst, "ERROR", f"rozkład nie sumuje się do 1 ({tot:.8f})", aid)
        else:
            t_end = float(u["t_end"][-1])
            p = _p(canonical_id=self.CID, instrument=inst, timeframe="EVENT", model_name=self.CID, model_version=aid, task_type="CLASS_PROBABILITIES",
                   task="EVENT_UNITS_DIR3", horizon_bars=2, unit="probability", state="READY", result=res, data_time=iso(t_end), available_at=iso(t_end),
                   data_kind="SYNTHETIC" if getattr(br, "synthetic", False) else "REAL", source=src, feature_schema=man.get("feature_schema"),
                   calibration={"method": "temperature (walidacja MM)", "status": "CALIBRATED_DEV"}, ttl_s=900.0,
                   compute_ms=round((time.perf_counter() - t0) * 1000, 2),
                   extra={"family": "SEQ_GRU_EVENT", "use": "SHADOW", "analytic_role": "BASE_FORECAST", "event_source": src,
                          "note": "kierunek jednostki zdarzeń (2 jednostki naprzód) – nie P(TP przed SL)"})
        self.latest[inst] = p
        return p


# ---------------------------------------------------------------------------------------------------------------- scalp A (owner: Quant)
def scalp_a(rt, inst: str) -> list[dict]:
    sc = getattr(rt, "scalp", None)
    cid = "scalp:A_direction"
    if sc is None:
        return []
    try:
        reg = sc.registry()
    except Exception as exc:  # noqa: BLE001
        return [_err(cid, inst, "M1", "CLASS_PROBABILITIES", "SCALP_DIRECTION_H1M_M1", "probability", exc, 1)]
    if not reg.get("active"):
        return [_p(canonical_id=cid, instrument=inst, timeframe="M1", model_name=cid, task_type="CLASS_PROBABILITIES", task="SCALP_DIRECTION_H1M_M1",
                   horizon_bars=1, unit="probability", state="NOT_TRAINED", unavailable_reason="brak aktywnego modelu zadania A (trening: 17_TRENING_SCALP_ML.bat)")]
    ans = sc.forecasts()
    if ans.get("status") != "SHADOW":
        return [_p(canonical_id=cid, instrument=inst, timeframe="M1", model_name=cid, task_type="CLASS_PROBABILITIES", task="SCALP_DIRECTION_H1M_M1",
                   horizon_bars=1, unit="probability", state="BLOCKED_DATA" if ans.get("status") in ("WARMUP", "UNAVAILABLE") else "ERROR",
                   unavailable_reason=str(ans.get("reason") or ans.get("status"))[:200])]
    out = []
    for hz, r in (ans.get("horizons") or {}).items():
        mins = int("".join(ch for ch in str(hz) if ch.isdigit()) or 1)
        res = {"DOWN": r.get("p_down"), "FLAT": r.get("p_flat"), "UP": r.get("p_up")}
        tot = sum(x for x in res.values() if C.is_num(x)) if all(C.is_num(x) for x in res.values()) else None
        if tot is None or abs(tot - 1.0) > 2e-4:                 # worker rounds to 4 decimals: explicit rounding tolerance, then exact renorm
            out.append(_p(canonical_id=cid, instrument=inst, timeframe="M1", model_name=cid, task_type="CLASS_PROBABILITIES", task=f"SCALP_DIRECTION_H{mins}_M1",
                          horizon_bars=mins, unit="probability", state="ERROR", unavailable_reason=f"rozkład spoza tolerancji zaokrągleń (suma={tot})"))
            continue
        res = {k: float(v) / tot for k, v in res.items()}
        out.append(_p(canonical_id=cid, instrument=inst, timeframe="M1", model_name=cid, model_version=ans.get("run_id"), task_type="CLASS_PROBABILITIES",
                      task=f"SCALP_DIRECTION_H{mins}_M1", horizon_bars=mins, unit="probability", state="READY", result=res, data_time=ans.get("feature_time_utc"),
                      source="forecast worker (.venv_candles)", calibration={"method": None, "status": "UNCALIBRATED"},
                      extra={"analytic_role": "BASE_FORECAST", "normalisation": "zaokrąglenie 4 miejsc – jawna renormalizacja w tolerancji 2e-4"}))
    return out


# ---------------------------------------------------------------------------------------------------------------- lab (read the lab loop state)
def lab(rt, inst: str) -> list[dict]:
    lb = getattr(rt, "lab", None)
    if lb is None:
        return []
    try:
        asset = lb.assets.asset_of(inst) if getattr(lb, "assets", None) and hasattr(lb.assets, "asset_of") else inst
    except Exception:  # noqa: BLE001
        asset = inst
    st = (getattr(lb, "state", {}) or {}).get(asset) or (getattr(lb, "state", {}) or {}).get(inst)
    if not st:
        return [_p(canonical_id="lab:models", instrument=inst, timeframe="M5", model_name="lab:models", task_type="SCORE", task="TRIPLE_BARRIER_LONG_SCORE",
                   horizon_bars=None, unit="ratio", state="BLOCKED_DATA", unavailable_reason="pętla lab nie policzyła jeszcze instrumentu")]
    out = []
    for m in st.get("models") or []:
        fam = m.get("family") or "?"
        cid = f"lab:{fam}"
        h = m.get("horizon") or "M5x1"
        try:
            hb = int(str(h).split("x")[1])
        except (IndexError, ValueError):
            hb = None
        if m.get("status") == "ready" and C.is_num(m.get("raw_score")):
            out.append(_p(canonical_id=cid, instrument=inst, timeframe="M5", model_name=cid, model_version=m.get("model_id"), task_type="SCORE",
                          task=f"TRIPLE_BARRIER_{m.get('side', 'LONG')}_SCORE_H{hb}", horizon_bars=hb, unit="ratio", state="READY",
                          result={"raw_score": float(m["raw_score"])}, data_time=st.get("as_of"), source="lab.service",
                          data_kind="SYNTHETIC" if st.get("data_mode") == "fixture" else "REAL",
                          extra={"analytic_role": "BASE_FORECAST", "event": m.get("event"), "note": "score nieskalibrowany innego zdarzenia – nie p(win)"}))
        else:
            out.append(_p(canonical_id=cid, instrument=inst, timeframe="M5", model_name=cid, model_version=m.get("model_id"), task_type="SCORE",
                          task="TRIPLE_BARRIER_SCORE", horizon_bars=hb, unit="ratio", state="ERROR" if m.get("status") == "error" else "BLOCKED_DATA",
                          unavailable_reason=f"{m.get('status')}: {m.get('reason') or ''}"[:200]))
    if not out:
        md = st.get("model") or {}
        out.append(_p(canonical_id="lab:models", instrument=inst, timeframe="M5", model_name="lab:models", task_type="SCORE", task="TRIPLE_BARRIER_LONG_SCORE",
                      horizon_bars=None, unit="ratio", state="NOT_TRAINED" if md.get("status") == "no_model" else "BLOCKED_DATA",
                      unavailable_reason=str(md.get("reason") or md.get("status") or "brak modeli lab")[:200]))
    return out


def setup_scoped(rt, inst: str) -> list[dict]:
    from ..sh import models as SM
    from . import ids as I
    out = []
    for it in SM.REGISTRY:
        if it["id"] in SETUP_SCOPED:
            st = SM.probe(it, rt, inst)
            out.append({"canonical_id": I.resolve(it["id"]), "sh_id": it["id"], "status": st["status"], "reason": st.get("reason"), "output": it["output"],
                        "receiver": "evaluation (prawdopodobieństwo per kandydat)" if it["id"] in ("sh_tp_model", "legacy_ml") else "scalp (per plan)",
                        "note": "wynik istnieje tylko dla konkretnego kandydata setupu – brak samodzielnej predykcji"})
    return out


def extended(rt, inst: str, event_gru: EventGRU | None = None, *, with_scalp: bool = True) -> list[dict]:
    out: list[dict] = []
    for fn in (rules, analysis, mm, lab):
        try:
            out += fn(rt, inst)
        except Exception as exc:  # noqa: BLE001
            out.append(_err(f"adapter:{fn.__name__}", inst, None, "STATE", fn.__name__.upper(), "state", exc))
    if event_gru is not None:
        out.append(event_gru.predict(rt, inst))
    if with_scalp:
        try:
            out += scalp_a(rt, inst)
        except Exception as exc:  # noqa: BLE001
            out.append(_err("scalp:A_direction", inst, "M1", "CLASS_PROBABILITIES", "SCALP_DIRECTION_H1M_M1", "probability", exc, 1))
    return out
