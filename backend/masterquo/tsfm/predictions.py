"""Chronos-2 / Granite TTM in the prediction contract (PMW-PRED-2), in the decision coordinator (ACTIVE) and in SCALPING / HEDGING (1.37, 1.40).

Contract rows: task_type REGRESSION, unit "price", task TSFM_CLOSE_H{H}_{TF}; result = point forecast of the close after H bars
(Chronos-2: median, Granite TTM: point - `point_kind`), median, the model quantiles at H (Chronos-2 only), change in price units and %, direction by the
explicit neutral band rule, forecast id. Calibration UNCALIBRATED (model quantiles were never calibrated on the user's data); no
probability is derived. READY only when the process is loaded AND the forecast belongs to the CURRENT last closed bar; otherwise
result = null with the exact reason (never 0, never a neutral vote, never an older value marked as fresh).

Roles (settings.models[mid].use[path]: path = ACTIVE | SCALPING | HEDGING) - each model / condition is applied ONCE:
  OBSERVE  (default) information only - recorded in the DecisionRecord with influence NONE.
  ASSIST   a FRESH forecast whose direction is AGAINST the setup side holds the entry (ACTIVE: ENTER -> BLOCKED MODEL_ASSIST_HOLD in the
           coordinator; SH: READY -> WAIT in the SH receiver below). Stale / missing / FLAT -> no effect (an optional model never
           blocks the system). Valid only while its approval matches the current binding; otherwise no effect + reason.
  REQUIRED unavailable / stale / FLAT / against the side / approval no longer matching -> the entry is held (ACTIVE: coordinator reason
           codes MODEL_REQUIRED_*; SH: READY -> WAIT with the reason). Never creates a setup, never changes side, size, SL / TP, risk
           limits, STOP or the execution mode.
ACTIVE is evaluated by decision/coordinator.evaluate_models (rows from coordinator_rows()); SH by apply_to_setup() in sh/service.cycle -
the SH DecisionRecord then lists these models as already applied (role OBSERVE there), so nothing is counted twice. Kronos keeps its own
SH condition (kronos/predictions.py); in the coordinator Kronos is recorded as OBSERVE only (`no_required`), never a second gate.
"""
from __future__ import annotations

from ..modelhub import contract as C
from .service import NAMES

USE_PL = {"OBSERVE": "tylko obserwacja (SHADOW) – bez wpływu na decyzje i zlecenia",
          "ASSIST": "ASSIST (po walidacji) – świeża prognoza przeciwna do strony setupu może tylko wstrzymać wejście",
          "REQUIRED": "warunek wymagany (po walidacji) – brak / nieaktualna / bocznie / przeciwna prognoza wstrzymuje wejście"}
SERVICE_STATE = {"NOT_INSTALLED": "DISABLED", "NO_WEIGHTS": "DISABLED", "DISABLED": "DISABLED", "INSTALLING": "DISABLED", "IDLE": "ERROR",
                 "STARTING": "ERROR", "LOADING": "ERROR", "READY": "READY", "ERROR": "ERROR"}
INCOMPATIBLE_CODES = ("INCOMPATIBLE", "CHECKSUM", "MISSING_DEPENDENCY")
KNOWS_ONLY = "Chronos-2 i Granite TTM widzą wyłącznie ceny close zamkniętych świec (Chronos-2 w profilu OHLCV także open/high/low/wolumen) – " \
             "nie znają poziomów płynności, newsów, spreadu, kosztów ani pozycji"


def _state(svc, k: tuple) -> tuple[str, str | None]:
    mid = k[0]
    w = svc.workers[mid]
    st, code = w.state.get("status"), w.state.get("code")
    tv = svc.target_view(k)
    if tv["forecast_current"]:
        return "READY", None
    if st not in ("READY", "IDLE"):
        mapped = "INCOMPATIBLE" if (st == "ERROR" and code in INCOMPATIBLE_CODES) else SERVICE_STATE.get(st, "ERROR")
        return mapped, w.state.get("reason") or st
    if tv["state"] == "NO_SYMBOL":
        return "DISABLED", tv["reason"]
    if tv["state"] == "RESOURCE_PAUSED":                          # 1.40 Memory Governor: not computed now -> STALE with the reason, no value
        return "STALE", f"{tv['state_pl']}: {tv['reason'] or ''}"
    if tv["state"] in ("QUEUED", "RUNNING", "WAITING"):
        return "STALE", f"{tv['state_pl']}: poprzednia prognoza nie dotyczy już ostatniej zamkniętej świecy"
    if tv["state"] in ("STALE", "WARMUP", "BLOCK", "MT5_DISCONNECTED"):
        return "BLOCKED_DATA" if tv["state"] != "STALE" else "STALE", f"{tv['state_pl']}: {tv['reason'] or ''}"
    return "ERROR", f"{tv['state_pl']}: {tv['reason'] or 'brak aktualnej prognozy dla ostatniej zamkniętej świecy'}"


def _result(fc: dict) -> dict:
    last = fc["path"][-1]
    out = {"last_close": fc["last_close"], "pred_close": fc["pred_close_h"], "point_kind": fc["point_kind"], "median": fc.get("median_close_h"),
           "quantiles_h": {k[1:]: v for k, v in last.items() if k.startswith("q") and v is not None}, "delta_price": fc["delta_price"],
           "delta_pct": fc["delta_pct"], "direction": fc["direction"], "neutral_band": fc["neutral_band"], "forecast_id": fc["id"],
           "snapshot_id": fc["snapshot_id"], "target_time": fc["target_times"][-1]}
    if out["median"] is None:                       # point-only model (Granite TTM): no median exists - the field is absent, not null
        out.pop("median")
    return out


def contract_predictions(svc, inst: str) -> list[dict]:
    if svc is None:
        return []
    s = svc.settings.get()
    out = []
    for mid, c in s.models.items():
        for tf in c.timeframes:
            k = (mid, inst, tf)
            H = int(s.horizon_bars[tf])
            state, why = _state(svc, k) if inst in c.instruments else ("DISABLED", f"{inst} nie jest włączony dla {NAMES[mid]}")
            if not c.enabled:
                state, why = "DISABLED", f"{NAMES[mid]} wyłączony w ustawieniach"
            fc = svc.latest.get(k)
            from tsfm_runtime import lock as L
            pin = L.model(mid)
            common = dict(instrument=inst, symbol=(fc or {}).get("symbol") or svc.target_view(k).get("symbol"), timeframe=tf, model_name=NAMES[mid],
                          model_version=pin["revision"], feature_schema=f"TSFM_{c.profile}", task_type="REGRESSION", task=f"TSFM_CLOSE_H{H}_{tf}",
                          horizon_bars=H, unit="price", calibration={"method": None, "status": "UNCALIBRATED"},
                          extra={"model_key": f"{mid}_{tf}", "model_id": f"tsfm:{mid}", "fingerprint": L.fingerprint(mid),
                                 "checkpoint_revision": f"{pin['revision']}" + ("" if c.checkpoint == "BASE" else f"+{c.checkpoint}"),
                                 "data_profile": c.profile, "validation_status": _validation(svc, mid, inst, tf),
                                 "role": USE_PL[c.use["SCALPING"].use], "decision_use": {p: u.use for p, u in c.use.items()}})
            if state != "READY":
                out.append(C.make(**common, state=state, unavailable_reason=why or state))
                continue
            base_extra = common.pop("extra")
            out.append(C.make(**common, state="READY", data_time=fc["last_bar_close_utc"], compute_ms=fc["compute_ms"], run_id=fc["id"],
                              data_quality={"OK": "OK", "DEGRADED": "DEGRADED"}.get(fc["quality"]["status"], fc["quality"]["status"]),
                              data_kind="SYNTHETIC" if fc["data_kind"] == "SYNTHETIC" else "REAL", available_at=fc["data_available_at"],
                              result=_result(fc), extra={**base_extra, "snapshot_id": fc["snapshot_id"], "latency_ms": fc["compute_ms"],
                                                         "freshness": {"current": True, "last_bar_open_utc": fc["last_bar_open_utc"],
                                                                       "valid_until": fc["valid_until"]}}))
    return out


def _validation(svc, mid: str, inst: str, tf: str) -> str:
    """Status of the latest walk-forward report for THIS model / instrument / TF (NOT_VALIDATED when none) - information, not a gate."""
    try:
        from . import validation as V
        r = V.latest_report(inst, tf)
        v = (((r or {}).get("models") or {}).get(mid) or {}).get("verdict") or {}
        if not r:
            return "NOT_VALIDATED"
        return "POSITIVE" if v.get("positive") else "NEGATIVE" if v else "NOT_VALIDATED"
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def approval_ok(svc, mid: str, inst: str, path: str) -> tuple[bool, str | None]:
    """ASSIST / REQUIRED is valid only while the stored report(s) match the CURRENT binding (fingerprint, symbol, TF, horizon, ...)."""
    from . import validation as V
    u = svc.settings.get().models[mid].use[path]
    if not u.validation_report:
        return False, "brak raportu dopuszczenia"
    bad = []
    try:
        cur = V.binding(svc, mid, inst, u.timeframe)
        for rid in str(u.validation_report).split(","):
            r = V.report_by_id(rid) if rid else None
            if r is None or r.get("instrument") != inst:
                continue
            bad += V.binding_diff((r.get("bindings") or {}).get(mid), cur)
    except Exception as exc:  # noqa: BLE001 - an approval that cannot be checked is not valid
        return False, f"nie można sprawdzić dopuszczenia: {type(exc).__name__}"
    return (not bad), ("; ".join(bad)[:220] if bad else None)


def coordinator_rows(svc, inst: str) -> list[dict]:
    """Rows for decision/coordinator (ACTIVE path): the timeframe of the ACTIVE role, `use` = OBSERVE / ASSIST / REQUIRED (ASSIST / REQUIRED
    only with a valid approval; a REQUIRED whose approval no longer matches stays REQUIRED and is reported unavailable = fail-closed)."""
    if svc is None:
        return []
    s = svc.settings.get()
    preds = {(p["model_id"], p["timeframe"]): p for p in contract_predictions(svc, inst)}
    out = []
    for mid, c in s.models.items():
        if not c.enabled or inst not in c.instruments:
            continue
        u = c.use["ACTIVE"]
        p = preds.get((f"tsfm:{mid}", u.timeframe))
        if p is None:
            continue
        use, note = u.use, None
        if use in ("ASSIST", "REQUIRED"):
            ok, why = approval_ok(svc, mid, inst, "ACTIVE")
            if not ok and use == "ASSIST":
                use, note = "SHADOW", f"ASSIST nieaktywny – dopuszczenie nieaktualne ({why})"
            elif not ok:
                p = {**p, "state": "STALE", "result": None, "unavailable_reason": f"dopuszczenie REQUIRED nieaktualne ({why})"}
        out.append({**p, "family": f"tsfm:{mid}", "use": use if use != "OBSERVE" else "SHADOW", "max_age_s": TF_AGE(u.timeframe, s),
                    "unavailable_reason": p.get("unavailable_reason") or note})
    return out


def TF_AGE(tf: str, s) -> float:
    from ..timeutil import TF_SECONDS
    return float(TF_SECONDS[tf] * (1 + s.max_staleness_bars))


def kronos_rows(kr, inst: str) -> list[dict]:
    """Kronos in the coordinator: information only (its condition belongs to the SH receiver of kronos/predictions.py)."""
    if kr is None:
        return []
    from ..kronos import predictions as KP
    try:
        rows = KP.contract_predictions(kr, inst)
    except Exception:  # noqa: BLE001
        return []
    return [{**p, "family": f"kronos:{KP.model_name()}@{p.get('timeframe')}", "use": "SHADOW", "no_required": True} for p in rows]


def context(svc, mid: str, inst: str, strategy: str, *, side: str | None = None) -> dict:
    s = svc.settings.get()
    c = s.models[mid]
    u = c.use[strategy]
    tf = u.timeframe
    k = (mid, inst, tf)
    state, why = _state(svc, k)
    if not c.enabled:
        state, why = "DISABLED", f"{NAMES[mid]} wyłączony w ustawieniach"
    elif tf not in c.timeframes or inst not in c.instruments:
        state, why = "DISABLED", f"{NAMES[mid]} nie liczy {inst} {tf}"
    use = u.use
    approval = None
    if use in ("ASSIST", "REQUIRED"):
        ok, aw = approval_ok(svc, mid, inst, strategy)
        approval = {"ok": ok, "reason": aw}
        if not ok:
            if use == "ASSIST":
                use = "OBSERVE"
                why = (why + "; " if why else "") + f"ASSIST nieaktywny – dopuszczenie nieaktualne ({aw})"
            else:
                state, why = "STALE_APPROVAL", f"dopuszczenie REQUIRED nieaktualne ({aw}) – powtórz walidację albo przełącz na OBSERVE"
    fc = svc.latest.get(k) if state == "READY" else None
    d = fc["direction"] if fc else None
    rel = "BRAK"
    if d and side in ("BUY", "SELL"):
        rel = "NEUTRALNY" if d == "FLAT" else ("ZGODNY" if (d == "UP") == (side == "BUY") else "PRZECIWNY")
    return {"model": mid, "name": NAMES[mid], "timeframe": tf, "use": use, "use_configured": u.use, "use_pl": USE_PL[use],
            "validation_report": u.validation_report, "approval": approval, "available": state == "READY", "state": state, "reason": why,
            "forecast": None if not fc else {x: fc[x] for x in ("id", "direction", "direction_pl", "delta_price", "delta_pct", "last_close", "pred_close_h",
                                                              "point_kind", "horizon_bars", "last_bar_open_utc", "created_at", "neutral_band",
                                                              "snapshot_id", "data_source")},
            "setup_side": side, "relation": rel, "knows_only": KNOWS_ONLY}


def apply_to_setup(su: dict, ctx: dict) -> dict:
    """SH receiver for ONE model: OBSERVE = checklist info; ASSIST = READY -> WAIT on a fresh contrary forecast; REQUIRED = READY -> WAIT
    unless available and agreeing. Never upgrades, never changes side / size / levels."""
    su.setdefault("tsfm", {})[ctx["model"]] = ctx
    cl = su.setdefault("checklist", [])
    f = ctx["forecast"]
    detail_fc = (f"{f['direction_pl']} {f['delta_price']:+.3f} w {f['horizon_bars']} świecach {ctx['timeframe']} ({f['point_kind']}) – relacja do "
                 f"strony setupu: {ctx['relation']}") if f else f"niedostępny: {ctx['reason']}"
    lid = f"tsfm_{ctx['model']}"
    if ctx["use"] == "OBSERVE":
        cl.append({"id": lid, "label": f"{ctx['name']} {ctx['timeframe']} (obserwacja SHADOW – bez wpływu)", "status": "INFO", "detail": detail_fc})
        return su
    label = f"{ctx['name']} {ctx['timeframe']} ({ctx['use']})"
    if su.get("status") != "READY":
        cl.append({"id": lid, "label": label, "status": "INFO", "detail": "setup nie jest gotowy – warunek nie był potrzebny; " + detail_fc})
        return su
    if ctx["use"] == "ASSIST":
        if ctx["available"] and ctx["relation"] == "PRZECIWNY":
            cl.append({"id": lid, "label": label, "status": "FAIL", "detail": f"prognoza {f['direction_pl']} przeciwna do {su.get('side')} – wstrzymanie"})
            su.update(status="WAIT", status_reason=f"{ctx['name']} (ASSIST): prognoza {f['direction_pl']} przeciwna do {su.get('side')}"[:300])
        else:
            cl.append({"id": lid, "label": label, "status": "PASS" if ctx["available"] else "INFO", "detail": detail_fc})
        return su
    if not ctx["available"]:
        cl.append({"id": lid, "label": label, "status": "WAIT", "detail": f"model niedostępny: {ctx['reason']}"})
        su.update(status="WAIT", status_reason=f"{ctx['name']} (warunek wymagany) niedostępny – setup wstrzymany: {ctx['reason']}"[:300])
    elif ctx["relation"] != "ZGODNY":
        cl.append({"id": lid, "label": label, "status": "FAIL", "detail": f"prognoza {f['direction_pl']} nie potwierdza {su.get('side')}"})
        su.update(status="WAIT", status_reason=f"{ctx['name']} (warunek wymagany): prognoza {f['direction_pl']} nie potwierdza {su.get('side')}")
    else:
        cl.append({"id": lid, "label": label, "status": "PASS", "detail": f"prognoza {f['direction_pl']} zgodna z {su.get('side')}"})
    return su


def sh_record_rows(su: dict) -> list[dict]:
    """For the SH DecisionRecord: the models were ALREADY applied by apply_to_setup - recorded as OBSERVE with the applied effect."""
    out = []
    for mid, ctx in (su.get("tsfm") or {}).items():
        f = ctx.get("forecast") or {}
        out.append({"family": f"tsfm:{mid}", "state": "READY" if ctx.get("available") else "ERROR", "use": "SHADOW", "task_type": "REGRESSION",
                    "result": {"direction": f.get("direction"), "pred_close": f.get("pred_close_h"), "forecast_id": f.get("id")} if ctx.get("available") else None,
                    "no_required": True, "unavailable_reason": f"rola {ctx.get('use')} zastosowana w odbiorniku SH; relacja {ctx.get('relation')}"
                    + ("" if ctx.get("available") else f"; {ctx.get('reason')}")})
    return out
