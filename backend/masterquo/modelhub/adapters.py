"""Adapters of EXISTING live model outputs to the unified prediction contract (PMW-PRED-1).

gold_candles (forecast/ForecastService, SHADOW): one prediction per horizon (5/15/30 min) - P(DOWN/FLAT/UP) of the close relative to
the neutral band, timeframe M5; states mapped from the service status (NO_MODEL -> NOT_TRAINED, CONTRACT_MISMATCH / MODEL_FROM_FUTURE
-> INCOMPATIBLE, DISABLED / NO_CANDLE_ENV / SYMBOL_SPEC -> DISABLED, STALE_DATA / NO_DATA / WARMUP / FORECAST_UNAVAILABLE -> ERROR).
Only a SHADOW status with probabilities is READY. The service's own calibration is not asserted here (status UNCALIBRATED unless the
report says otherwise). Kronos-small (kronos/predictions.py): REGRESSION of the close after H bars in price units, SHADOW. Other models (SH tp-model, scalp, legacy ML, lab, PMW-MM) publish task-specific payloads through their own
panels; their state is in the catalog (catalog.py) - they are not re-labelled as something they are not.
"""
from __future__ import annotations

from . import contract as C

FORECAST_STATE = {"SHADOW": "READY", "NO_MODEL": "NOT_TRAINED", "CONTRACT_MISMATCH": "INCOMPATIBLE", "MODEL_FROM_FUTURE": "INCOMPATIBLE",
                  "DISABLED": "DISABLED", "NO_CANDLE_ENV": "DISABLED", "SYMBOL_SPEC": "DISABLED", "UNSUPPORTED_ASSET": "DISABLED",
                  "STALE_DATA": "ERROR", "NO_DATA": "ERROR", "WARMUP": "ERROR", "FORECAST_UNAVAILABLE": "ERROR", "STARTING": "ERROR"}


def forecast_predictions(rt, inst: str) -> list[dict]:
    fs = getattr(rt, "forecast", None) if rt is not None else None
    if fs is None:
        return []
    st = fs.public()
    if st.get("instrument") not in (None, inst):
        return [C.make(instrument=inst, symbol=None, timeframe="M5", model_name="gold_candles", model_version=None, task_type="CLASS_PROBABILITIES",
                       task="CANDLE_CLOSE_DIRECTION_H1_M5", horizon_bars=1, unit="probability", state="DISABLED",
                       unavailable_reason=f"prognozy liczone dla aktywnego instrumentu ({st.get('instrument')})")]
    status = st.get("status") or "FORECAST_UNAVAILABLE"
    state = FORECAST_STATE.get(status, "ERROR")
    rep = st.get("report") or {}
    fc = rep.get("forecast") or {}
    model = st.get("model") or {}
    probs = fc.get("probabilities") or {}
    if state != "READY" or not probs:
        return [C.make(instrument=inst, symbol=None, timeframe="M5", model_name="gold_candles", model_version=model.get("run_id"),
                       task_type="CLASS_PROBABILITIES", task="CANDLE_CLOSE_DIRECTION_H1_M5", horizon_bars=1, unit="probability",
                       state=state if state != "READY" else "ERROR",
                       unavailable_reason=st.get("status_pl") or st.get("reason") or status if state != "READY" else "brak prognoz w raporcie")]
    out = []
    for h in probs.values():
        p = h.get("probabilities") or {}
        mins = int(h.get("horizon_minutes") or 5)
        tot = sum(float(p.get(k, 0)) for k in ("DOWN", "FLAT", "UP")) or 1.0
        res = {k: float(p.get(k, 0)) / tot for k in ("DOWN", "FLAT", "UP")}
        out.append(C.make(instrument=inst, symbol=rep.get("symbol"), timeframe="M5", model_name="gold_candles", model_version=model.get("run_id"),
                          task_type="CLASS_PROBABILITIES", task=f"CANDLE_CLOSE_DIRECTION_H{max(1, mins // 5)}_M5", horizon_bars=max(1, mins // 5),
                          unit="probability", state="READY", result=res, data_time=fc.get("feature_time_utc"),
                          calibration={"method": model.get("calibration"), "status": "CALIBRATED_DEV" if model.get("calibration") else "UNCALIBRATED"},
                          extra={"model_key": f"gold_candles_{mins}m", "role": "SHADOW (obserwacja)"}))
    return out


def all_predictions(rt, inst: str) -> list[dict]:
    out = []
    inf = getattr(rt, "trainhub_inference", None) if rt is not None else None
    if inf is not None:
        out += inf.predictions(inst)
    kr = getattr(rt, "kronos", None) if rt is not None else None
    if kr is not None:
        try:
            from ..kronos import predictions as KP
            out += KP.contract_predictions(kr, inst)                   # Kronos-small: REGRESSION in price units (SHADOW)
        except Exception as exc:  # noqa: BLE001 - an adapter failure is an ERROR prediction, never silence or a value
            out.append(C.make(instrument=inst, symbol=None, timeframe="M5", model_name="Kronos-small", model_version=None, task_type="REGRESSION",
                              task="KRONOS_CLOSE_PATH_H1_M5", horizon_bars=1, unit="price", state="ERROR",
                              unavailable_reason=f"adapter Kronos: {type(exc).__name__}: {exc}"[:200]))
    try:
        out += forecast_predictions(rt, inst)
    except Exception as exc:  # noqa: BLE001 - an adapter failure is shown as an ERROR prediction, never as silence or a value
        out.append(C.make(instrument=inst, symbol=None, timeframe="M5", model_name="gold_candles", model_version=None, task_type="CLASS_PROBABILITIES",
                          task="CANDLE_CLOSE_DIRECTION_H1_M5", horizon_bars=1, unit="probability", state="ERROR",
                          unavailable_reason=f"adapter: {type(exc).__name__}: {exc}"[:200]))
    return out
