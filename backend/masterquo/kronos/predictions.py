"""Kronos in the unified prediction contract (PMW-PRED-1) and in SCALPING / HEDGING (separate, described context).

Contract: task_type REGRESSION, unit "price", task KRONOS_CLOSE_PATH_H{H}_{TF}; the result is the price forecast of the close after H
bars (+ change in price units and %, direction by the explicit band rule). Calibration NOT_APPLICABLE: a single sampled path is not a
probability. READY only when the model is loaded AND the forecast belongs to the current last closed bar; otherwise no value + reason.

Strategy context (sh/service.cycle): every SCALPING / HEDGING evaluation gets su["kronos"] with the forecast of the configured timeframe,
its relation to the setup side, to the other READY models (listed, never averaged - different units / horizons) and to the market
structure of the same timeframe. Kronos sees ONLY the OHLC (+ tick volume) and times of the bars: no liquidity levels, no news, no
spread, costs or positions - the context says so.
  use = OBSERVE (default): information only - nothing in the evaluation changes.
  use = REQUIRED (only after a positive walk-forward report on real data + explicit confirmation): an additional entry condition that can
        only TAKE AWAY a READY status (-> WAIT) when the forecast is unavailable, stale, FLAT or against the side. It never creates a
        setup, never changes the side, size, TP / SL, risk limits, the STOP switch or the execution mode; a model failure is never BUY,
        SELL or a permission.
"""
from __future__ import annotations

from ..modelhub import contract as C


def model_name() -> str:
    """Name of the PINNED (currently loaded) checkpoint - 1.37: Kronos-base. History rows keep their own revision / name."""
    from kronos_runtime import lock as LK
    return LK.MODEL_NAME

SERVICE_STATE = {"NOT_INSTALLED": "DISABLED", "NO_WEIGHTS": "DISABLED", "DISABLED": "DISABLED", "INSTALLING": "DISABLED", "STARTING": "ERROR",
                 "LOADING": "ERROR", "READY": "READY", "ERROR": "ERROR"}
INCOMPATIBLE_CODES = ("INCOMPATIBLE", "CHECKSUM", "CHECKSUM_MISMATCH", "MISSING_DEPENDENCY")
USE_PL = {"OBSERVE": "tylko obserwacja (SHADOW) – nie wpływa na decyzje ani zlecenia",
          "REQUIRED": "dodatkowy warunek wymagany (włączony po walidacji) – może tylko wstrzymać setup, nigdy nie otwiera pozycji"}
KNOWS_ONLY = ("Kronos widzi wyłącznie OHLC (+ tick volume jako wolumen) i czasy zamkniętych świec – nie zna poziomów likwidacji, newsów, "
              "spreadu, prowizji, poślizgu ani pozycji")
INDEPENDENCE = ("Kronos i pozostałe modele liczą na tych samych świecach z MT5 – zgodność nie jest niezależnym potwierdzeniem; "
                "wyniki o innych jednostkach / horyzontach są tylko zestawiane, nie uśredniane")


def _state(svc, k: tuple) -> tuple[str, str | None]:
    st = svc.state.get("status")
    code = svc.state.get("code")
    tv = svc.target_view(k)
    if st != "READY":
        mapped = "INCOMPATIBLE" if (st == "ERROR" and code in INCOMPATIBLE_CODES) else SERVICE_STATE.get(st, "ERROR")
        if mapped != "READY":
            return mapped, svc.state.get("reason") or st
    if tv["state"] == "NO_SYMBOL":
        return "DISABLED", tv["reason"]
    if tv["state"] == "RESOURCE_PAUSED":                          # 1.40 Memory Governor: not computed now -> STALE with the reason, no value
        return "STALE", f"{tv['state_pl']}: {tv['reason'] or ''}"
    if not tv["forecast_current"]:
        return "ERROR", f"{tv['state_pl']}: {tv['reason'] or 'brak aktualnej prognozy dla ostatniej zamkniętej świecy'}"
    return "READY", None


def contract_predictions(svc, inst: str) -> list[dict]:
    if svc is None:
        return []
    s = svc.settings.get()
    out = []
    for tf in s.timeframes:
        k = (inst, tf)
        H = int(s.horizon_bars[tf])
        state, why = _state(svc, k) if inst in s.instruments else ("DISABLED", f"{inst} nie jest włączony w ustawieniach Kronos")
        if not s.enabled:
            state, why = "DISABLED", "Kronos wyłączony w ustawieniach"
        fc = svc.latest.get(k)
        common = dict(instrument=inst, symbol=(fc or {}).get("symbol") or svc.target_view(k).get("symbol"), timeframe=tf, model_name=model_name(),
                      model_version=((fc or {}).get("model") or {}).get("revision"), feature_schema="KRONOS_OHLCV_TIME_V1", task_type="REGRESSION",
                      task=f"KRONOS_CLOSE_PATH_H{H}_{tf}", horizon_bars=H, unit="price", calibration={"method": None, "status": "NOT_APPLICABLE"},
                      extra={"model_key": f"kronos_{tf}", "role": USE_PL["OBSERVE"], "decision_use": {k2: v.use for k2, v in s.strategy_use.items()}})
        if state != "READY":
            out.append(C.make(**common, state=state, unavailable_reason=why or state))
            continue
        out.append(C.make(**common, state="READY", data_time=fc["last_bar_close_utc"], compute_ms=fc["compute_ms"],
                          data_quality={"OK": "OK", "DEGRADED": "DEGRADED"}.get(fc["quality"]["status"], fc["quality"]["status"]),
                          result={"last_close": fc["last_close"], "pred_close": fc["pred_close_h"], "delta_price": fc["delta_price"],
                                  "delta_pct": fc["delta_pct"], "direction": fc["direction"], "neutral_band": fc["neutral_band"],
                                  "forecast_id": fc["id"]}))
    return out


def _dominant(p: dict) -> str | None:
    r = p.get("result")
    if isinstance(r, dict) and {"UP", "DOWN"} <= set(r):
        return max(("UP", "DOWN", "FLAT"), key=lambda c: r.get(c, -1.0))
    return None


def context(svc, inst: str, strategy: str, *, side: str | None = None, other_preds: list[dict] | None = None, snap: dict | None = None) -> dict:
    s = svc.settings.get()
    use = s.strategy_use[strategy]
    tf = use.timeframe
    k = (inst, tf)
    state, why = _state(svc, k)
    if not s.enabled:
        state, why = "DISABLED", "Kronos wyłączony w ustawieniach"
    if tf not in s.timeframes or inst not in s.instruments:
        state, why = "DISABLED", f"Kronos nie liczy {inst} {tf} (włącz w ustawieniach Kronos)"
    if use.use == "REQUIRED" and state == "READY":         # 1.33: an approval is valid only for the binding it was validated on
        try:
            from . import validation as V
            cur = V.binding(svc, inst, tf)
            bad = []
            for rid in str(use.validation_report or "").split(","):
                r = V.report_by_id(rid) if rid else None
                if r is None or r.get("instrument") != inst:
                    continue
                bad += V.binding_diff(r.get("binding"), cur)
            if not use.validation_report:
                bad.append("brak raportu dopuszczenia")
            if bad:
                state, why = "STALE_APPROVAL", "dopuszczenie REQUIRED nieaktualne (" + "; ".join(bad)[:220] + ") – powtórz walidację albo przełącz na OBSERVE"
        except Exception as exc:  # noqa: BLE001 - an approval that cannot be checked is not valid (fail-closed: REQUIRED may only hold)
            state, why = "STALE_APPROVAL", f"nie można sprawdzić dopuszczenia: {type(exc).__name__}"
    fc = svc.latest.get(k) if state == "READY" else None
    d = fc["direction"] if fc else None
    rel = "BRAK"
    if d and side in ("BUY", "SELL"):
        rel = "NEUTRALNY" if d == "FLAT" else ("ZGODNY" if (d == "UP") == (side == "BUY") else "PRZECIWNY")
    models = []
    for p in other_preds or []:
        if p.get("state") != "READY" or str(p.get("model_name", "")).startswith("Kronos"):
            continue
        dom = _dominant(p)
        if dom and d:
            models.append({"model": p.get("model_key") or p.get("model_name"), "task": p.get("task"), "timeframe": p.get("timeframe"),
                           "horizon_bars": (p.get("horizon") or {}).get("bars"), "dominant": dom,
                           "relation": "ZGODNY" if dom == d else ("NEUTRALNY" if "FLAT" in (dom, d) else "KONFLIKT")})
    struct = None
    if snap and d:
        st = snap.get(f"structure_{tf}") or {}
        if st.get("status") == "OK":
            tr = st.get("internal")
            struct = {"timeframe": tf, "trend_internal": tr, "trend_major": st.get("major"),
                      "relation": "BRAK" if tr not in ("UP", "DOWN") or d == "FLAT" else ("ZGODNY" if tr == d else "KONFLIKT")}
    return {"model": model_name(), "timeframe": tf, "use": use.use, "use_pl": USE_PL[use.use], "validation_report": use.validation_report,
            "available": state == "READY", "state": state, "reason": why,
            "forecast": None if not fc else {k2: fc[k2] for k2 in ("id", "direction", "direction_pl", "delta_price", "delta_pct", "last_close",
                                                                    "pred_close_h", "horizon_bars", "last_bar_open_utc", "created_at", "neutral_band",
                                                                    "data_source")},
            "setup_side": side, "relation": rel, "vs_models": models, "vs_structure": struct, "knows_only": KNOWS_ONLY, "independence": INDEPENDENCE}


def apply_to_setup(su: dict, ctx: dict) -> dict:
    """Attach the Kronos context to one SH evaluation. OBSERVE: information only. REQUIRED: may only turn READY into WAIT."""
    su["kronos"] = ctx
    cl = su.setdefault("checklist", [])
    if ctx["use"] != "REQUIRED":
        detail = (f"{ctx['forecast']['direction_pl']} {ctx['forecast']['delta_price']:+.3f} w {ctx['forecast']['horizon_bars']} świecach {ctx['timeframe']} "
                  f"– relacja do strony setupu: {ctx['relation']}") if ctx["forecast"] else f"niedostępny: {ctx['reason']}"
        cl.append({"id": "kronos", "label": f"Kronos {ctx['timeframe']} (obserwacja SHADOW – bez wpływu)", "status": "INFO", "detail": detail})
        return su
    label = f"Kronos {ctx['timeframe']} (warunek wymagany)"
    if su.get("status") != "READY":
        cl.append({"id": "kronos", "label": label, "status": "INFO", "detail": "setup nie jest gotowy – warunek nie był potrzebny"})
        return su
    if not ctx["available"]:
        cl.append({"id": "kronos", "label": label, "status": "WAIT", "detail": f"model niedostępny: {ctx['reason']}"})
        su.update(status="WAIT", status_reason=f"Kronos (warunek wymagany) niedostępny – setup wstrzymany: {ctx['reason']}"[:300])
    elif ctx["relation"] != "ZGODNY":
        f = ctx["forecast"]
        cl.append({"id": "kronos", "label": label, "status": "FAIL", "detail": f"prognoza {f['direction_pl']} ({f['delta_price']:+.3f}) nie potwierdza {su.get('side')}"})
        su.update(status="WAIT", status_reason=f"Kronos (warunek wymagany): prognoza {f['direction_pl']} nie potwierdza {su.get('side')}")
    else:
        f = ctx["forecast"]
        cl.append({"id": "kronos", "label": label, "status": "PASS", "detail": f"prognoza {f['direction_pl']} ({f['delta_price']:+.3f}) zgodna z {su.get('side')}"})
    return su
