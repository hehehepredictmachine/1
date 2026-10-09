"""Versioned, incremental labelling of setup samples (MQ-LABEL-1.0.0, cost model MQ-COST-1.0.0).

Target (both models): does THIS setup, executed with the policy fixed when the sample was created,
end with a positive NET result?  label = 1 if net R > 0, 0 if net R <= 0.  Also stored: R, MFE, MAE, exit reason.
This is not "probability that price rises".

Policy (stored in every sample's entry_json):
* earliest fill = OPEN of the first M1 bar that opens at/after the decision time (signal availability);
  LONG buys at Ask = Bid open + spread (+ slippage), SHORT sells at Bid (- slippage);
* no fill within `entry_window_minutes` -> NO_ENTRY; fill already beyond the stop -> NO_ENTRY (ENTRY_BEYOND_STOP);
* exits follow the setup plan: SL, targets with their weights (partial), stop to break-even after TP1 if the plan says so,
  time exit at the horizon (strategy's time_exit_bars x setup TF) at the bar close; LONG exits on Bid, SHORT on Ask;
* costs: spread at fill, slippage on fill and stop exits, commission per side (price units per unit volume);
* if one M1 bar touches the stop AND a target, the recorded quotes of that minute decide the order;
  without quotes the sample becomes AMBIGUOUS (never silently a loss);
* a data gap of 15-50 minutes inside the window -> MISSING_DATA; >= 50 min is a session break (daily maintenance, weekend) and the trade is held through it;
* the label is known only when the exit bar has closed (`label_known_utc` >= `label_end_utc`).
State is persisted after every step, so a restart continues where it stopped and never labels twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

LABEL_POLICY_VERSION = "MQ-LABEL-1.0.0"
COST_MODEL_VERSION = "MQ-COST-1.0.0"
UTC = timezone.utc
GAP_MISSING_MIN, GAP_SESSION_MIN = 15, 50


def _p(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def new_state(spec: dict) -> dict:
    return {"phase": "WAIT_ENTRY", "last_bar": None, "entry": None, "entry_time": None, "risk": None, "stop": spec["stop_loss"],
            "remaining": 1.0, "pnl": 0.0, "targets_left": [[t["price"], t["weight"]] for t in spec["targets"]], "mfe": 0.0, "mae": 0.0}


def _touch(spec, bar, stop, tgt):
    d, spr = spec["direction"], spec["spread"]
    if d == "LONG":
        return bar["l"] <= stop, (tgt is not None and bar["h"] >= tgt)
    return bar["h"] + spr >= stop, (tgt is not None and bar["l"] + spr <= tgt)


def _order_by_ticks(spec, bar, stop, tgt, ticks):
    """Return 'STOP' / 'TARGET' / None using recorded quotes of this minute."""
    t0 = _p(bar["open_utc"]).timestamp()
    for ts, bid, ask in ticks:
        if ts < t0 or ts >= t0 + 60:
            continue
        if spec["direction"] == "LONG":
            if bid <= stop:
                return "STOP"
            if bid >= tgt:
                return "TARGET"
        else:
            if ask >= stop:
                return "STOP"
            if ask <= tgt:
                return "TARGET"
    return None


def step(spec: dict, state: dict, bars: list[dict], ticks: list[tuple], now: datetime) -> tuple[dict, dict | None]:
    """Advance the label state with newly CLOSED M1 bars (sorted). Returns (state, final_result or None)."""
    asof = _p(spec["asof_utc"])
    d = spec["direction"]
    sgn = 1 if d == "LONG" else -1
    for bar in bars:
        bt = _p(bar["open_utc"])
        if state["last_bar"] and bt <= _p(state["last_bar"]):
            continue
        if bt < asof:
            continue
        if state["last_bar"]:
            gap = (bt - _p(state["last_bar"])).total_seconds() / 60
            if GAP_MISSING_MIN < gap < GAP_SESSION_MIN and state["phase"] == "IN_TRADE":
                return state, {"status": "MISSING_DATA", "exit_reason": f"GAP_{int(gap)}MIN"}
        state["last_bar"] = bar["open_utc"]
        if state["phase"] == "WAIT_ENTRY":
            if bt > asof + timedelta(minutes=spec["entry_window_minutes"]):
                return state, {"status": "NO_ENTRY", "exit_reason": "NO_BAR_IN_ENTRY_WINDOW"}
            entry = bar["o"] + (spec["spread"] + spec["slippage"] if d == "LONG" else -spec["slippage"])
            risk = (entry - spec["stop_loss"]) * sgn
            if risk <= 0:
                return state, {"status": "NO_ENTRY", "exit_reason": "ENTRY_BEYOND_STOP"}
            state.update(phase="IN_TRADE", entry=entry, entry_time=bar["open_utc"], risk=risk)
            state["horizon_end"] = _iso(bt + timedelta(minutes=spec["horizon_minutes"]))
        # in trade: excursions (bar extremes, approximate)
        entry, risk = state["entry"], state["risk"]
        fav = ((bar["h"] - entry) if d == "LONG" else (entry - (bar["l"] + spec["spread"]))) / risk
        adv = ((entry - bar["l"]) if d == "LONG" else ((bar["h"] + spec["spread"]) - entry)) / risk
        state["mfe"], state["mae"] = max(state["mfe"], fav), max(state["mae"], adv)
        while True:
            tgt = state["targets_left"][0][0] if state["targets_left"] else None
            stop_hit, tgt_hit = _touch(spec, bar, state["stop"], tgt)
            if stop_hit and tgt_hit:
                who = _order_by_ticks(spec, bar, state["stop"], tgt, ticks)
                if who is None:
                    return state, {"status": "AMBIGUOUS", "exit_reason": "SL_AND_TP_IN_ONE_M1_BAR_WITHOUT_QUOTES"}
                stop_hit, tgt_hit = who == "STOP", who == "TARGET"
            if stop_hit:
                px = state["stop"]
                state["pnl"] += state["remaining"] * ((px - entry) * sgn - spec["slippage"])
                state["remaining"] = 0.0
                reason = "STOP" if abs(state["stop"] - spec["stop_loss"]) < 1e-9 else "BREAKEVEN_STOP"
                return state, _final(spec, state, bar, reason)
            if tgt_hit:
                price, w = state["targets_left"].pop(0)
                w = min(w, state["remaining"])
                state["pnl"] += w * (price - entry) * sgn
                state["remaining"] -= w
                if spec.get("be_after_tp1", True):
                    state["stop"] = entry
                if state["remaining"] <= 1e-9:
                    return state, _final(spec, state, bar, "TARGETS")
                continue
            break
        bar_close = bt + timedelta(minutes=1)
        if bar_close >= _p(state["horizon_end"]):
            exit_px = bar["c"] if d == "LONG" else bar["c"] + spec["spread"]
            state["pnl"] += state["remaining"] * (exit_px - entry) * sgn
            state["remaining"] = 0.0
            return state, _final(spec, state, bar, "TIME")
    # nothing final yet
    limit = asof + timedelta(minutes=spec["entry_window_minutes"] + spec["horizon_minutes"]) + timedelta(days=3)
    if now > limit:
        return state, {"status": "UNRESOLVED", "exit_reason": "NO_DATA_UNTIL_DEADLINE"}
    return state, None


def _final(spec, state, bar, reason) -> dict:
    net = state["pnl"] - 2 * spec["commission"]
    r = net / state["risk"]
    end = _p(bar["open_utc"]) + timedelta(minutes=1)
    return {"status": "LABELED", "label": 1 if r > 0 else 0, "outcome_r": round(r, 4), "mfe_r": round(state["mfe"], 3), "mae_r": round(state["mae"], 3),
            "exit_reason": reason, "label_end_utc": _iso(end), "entry_time": state["entry_time"], "entry_price": round(state["entry"], 5)}


def make_spec(rec: dict, asof: str, *, spread: float, slippage: float, commission: float, cost_flags: list[str]) -> dict:
    """Entry/exit policy fixed at sample creation from the setup plan."""
    from ..strategies.base import TF_SECONDS
    tf_min = TF_SECONDS[rec["timeframe"]] // 60
    ex = rec.get("exit_rules") or {}
    return {"direction": rec["direction"], "asof_utc": asof, "stop_loss": rec["stop_loss"],
            "targets": [{"price": t["price"], "weight": t["weight"]} for t in rec.get("targets") or []],
            "be_after_tp1": bool(ex.get("be_after_tp1", True)), "horizon_minutes": int(ex.get("time_exit_bars", 24)) * tf_min,
            "entry_window_minutes": 3 * tf_min, "spread": spread, "slippage": slippage, "commission": commission,
            "label_policy_version": LABEL_POLICY_VERSION, "cost_model_version": COST_MODEL_VERSION, "cost_flags": cost_flags}
