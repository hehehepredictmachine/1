"""Versioned, incremental labelling of setup samples (MQ-LABEL-1.1.0, cost model MQ-COST-1.1.0, exit policy MQ-EXIT-POLICY-1.0.0).

Target (both models): does THIS setup, executed with the policy fixed when the sample was created,
end with a positive NET result?  label = 1 if net R > 0, 0 if net R <= 0.  Also stored: R, MFE, MAE, exit reason.
This is not "probability that price rises".

Policy (stored in every sample's entry_json) = the same exit policy live / PAPER / replay use (execution/policy.py):
* earliest fill = OPEN of the first M1 bar that opens at/after the decision time (signal availability);
  LONG buys at Ask = Bid open + spread (+ slippage), SHORT sells at Bid (- slippage);
* no fill within `entry_window_minutes` -> NO_ENTRY; fill already beyond the stop -> NO_ENTRY (ENTRY_BEYOND_STOP);
* exits: SL, targets with the plan's weights (partial), stop to break-even after TP1 only if the plan says so,
  time exit only if the plan has one (time_exit_bars x setup TF) - a plan WITHOUT a time exit (S11) is held until SL/TP
  and becomes UNRESOLVED after `max_hold_minutes` (never an invented 24-bar exit);
  tp_rule RR_FROM_FILL: the target is recomputed from the simulated fill (fill +- rr x risk), like the live position;
  LONG exits on Bid, SHORT on Ask;
* costs: spread at fill, slippage on fill and stop exits, commission per side (price units per unit volume, converted with
  the broker profit calculator); an unknown commission marks the sample COST_UNKNOWN (excluded from training);
* order inside one M1 bar: the recorded quotes of that minute decide (cursor from the last event); after TP1 only what
  happens AFTER the TP1 moment can hit the new (BE) stop - the bar's low/high that happened BEFORE TP1 never does.
  Without enough quotes the sample becomes AMBIGUOUS (never silently a loss); recorded quotes are samples (~0.5 s), not the
  full tick history - the resolution is marked `intrabar: SAMPLED_QUOTES`;
* a data gap of 15-50 minutes inside the window -> MISSING_DATA; >= 50 min is treated as a session break (daily maintenance,
  weekend) and the trade is held through it - an assumption flagged in the result (`session_gap_assumed`);
* the label is known only when the exit bar has closed (`label_known_utc` >= `label_end_utc`).
State is persisted after every step, so a restart continues where it stopped and never labels twice.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

LABEL_POLICY_VERSION = "MQ-LABEL-1.1.0"
COST_MODEL_VERSION = "MQ-COST-1.1.0"
MAX_HOLD_MINUTES_NO_TIME_EXIT = 14400      # 10 days: plans without a time exit become UNRESOLVED after this (explicit, not a label)
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


def _hit(spec, bid, ask, stop, tgt) -> str | None:
    if spec["direction"] == "LONG":
        if bid <= stop:
            return "STOP"
        if tgt is not None and bid >= tgt:
            return "TARGET"
    else:
        if ask >= stop:
            return "STOP"
        if tgt is not None and ask <= tgt:
            return "TARGET"
    return None


def _bar_ticks(bar, ticks):
    t0 = _p(bar["open_utc"]).timestamp()
    return [(ts, bid, ask) for ts, bid, ask in ticks if t0 <= ts < t0 + 60]


def _order_by_ticks(spec, bar, stop, tgt, ticks, after: float | None = None) -> tuple[str | None, float | None]:
    """First of STOP / TARGET in the recorded quotes of this minute strictly after `after` (cursor). (who, timestamp)."""
    for ts, bid, ask in _bar_ticks(bar, ticks):
        if after is not None and ts <= after:
            continue
        who = _hit(spec, bid, ask, stop, tgt)
        if who:
            return who, ts
    return None, None


def _explained_before(spec, bar, kind: str, ticks, cursor: float) -> bool:
    """True if the bar's extreme on the side of `kind` was printed by a recorded quote AT/BEFORE the cursor - i.e. the bar's
    reach to that level is explained by what happened before the last event."""
    pre = [(b, a) for ts, b, a in _bar_ticks(bar, ticks) if ts <= cursor]
    if not pre:
        return False
    tol = 1e-9
    long_ = spec["direction"] == "LONG"
    if (kind == "STOP") == long_:          # LONG stop / SHORT target -> the bar LOW side
        lo = min(b for b, _ in pre)
        return lo <= bar["l"] + tol
    hi = max(b for b, _ in pre)
    return hi >= bar["h"] - tol


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
            if gap >= GAP_SESSION_MIN and state["phase"] == "IN_TRADE":
                state["session_gap_assumed"] = True
        state["last_bar"] = bar["open_utc"]
        if state["phase"] == "WAIT_ENTRY":
            if bt > asof + timedelta(minutes=spec["entry_window_minutes"]):
                return state, {"status": "NO_ENTRY", "exit_reason": "NO_BAR_IN_ENTRY_WINDOW"}
            entry = bar["o"] + (spec["spread"] + spec["slippage"] if d == "LONG" else -spec["slippage"])
            risk = (entry - spec["stop_loss"]) * sgn
            if risk <= 0:
                return state, {"status": "NO_ENTRY", "exit_reason": "ENTRY_BEYOND_STOP"}
            state.update(phase="IN_TRADE", entry=entry, entry_time=bar["open_utc"], risk=risk)
            if spec.get("tp_rule") == "RR_FROM_FILL" and spec.get("rr"):
                state["targets_left"] = [[entry + sgn * float(spec["rr"]) * risk, 1.0]]
                state["tp_rebased_on_fill"] = True
            hm = spec.get("horizon_minutes")
            state["horizon_end"] = _iso(bt + timedelta(minutes=hm)) if hm is not None else None
        # in trade: excursions (bar extremes, approximate)
        entry, risk = state["entry"], state["risk"]
        fav = ((bar["h"] - entry) if d == "LONG" else (entry - (bar["l"] + spec["spread"]))) / risk
        adv = ((entry - bar["l"]) if d == "LONG" else ((bar["h"] + spec["spread"]) - entry)) / risk
        state["mfe"], state["mae"] = max(state["mfe"], fav), max(state["mae"], adv)
        cursor = None                                     # moment of the last event inside this bar (None = bar start)
        while True:
            tgt = state["targets_left"][0][0] if state["targets_left"] else None
            ev_ts = None
            if cursor is None:
                stop_hit, tgt_hit = _touch(spec, bar, state["stop"], tgt)
                if stop_hit and tgt_hit:
                    who, ev_ts = _order_by_ticks(spec, bar, state["stop"], tgt, ticks)
                    if who is None:
                        return state, {"status": "AMBIGUOUS", "exit_reason": "SL_AND_TP_IN_ONE_M1_BAR_WITHOUT_QUOTES"}
                    stop_hit, tgt_hit = who == "STOP", who == "TARGET"
                    state["intrabar"] = "SAMPLED_QUOTES"
                elif tgt_hit:
                    _, ev_ts = _order_by_ticks(spec, bar, state["stop"], tgt, ticks)
            else:
                who, ev_ts = _order_by_ticks(spec, bar, state["stop"], tgt, ticks, after=cursor)
                if who is None:
                    reach_stop, reach_tgt = _touch(spec, bar, state["stop"], tgt)
                    if (reach_stop and not _explained_before(spec, bar, "STOP", ticks, cursor)) or \
                       (reach_tgt and not _explained_before(spec, bar, "TARGET", ticks, cursor)):
                        return state, {"status": "AMBIGUOUS", "exit_reason": "ORDER_AFTER_TP_IN_ONE_M1_BAR_UNKNOWN"}
                    break
                stop_hit, tgt_hit = who == "STOP", who == "TARGET"
                state["intrabar"] = "SAMPLED_QUOTES"
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
                if state["remaining"] <= 1e-9:
                    return state, _final(spec, state, bar, "TARGETS")
                if spec.get("be_after_tp1", True):
                    state["stop"] = entry
                if ev_ts is None:
                    # target reached in this bar but WHEN is unknown: anything else inside the bar cannot be ordered
                    nxt = state["targets_left"][0][0] if state["targets_left"] else None
                    reach_stop, reach_next = _touch(spec, bar, state["stop"], nxt)
                    if reach_stop or reach_next:
                        return state, {"status": "AMBIGUOUS", "exit_reason": "ORDER_AFTER_TP_IN_ONE_M1_BAR_WITHOUT_QUOTES"}
                    break
                cursor = ev_ts
                continue
            break
        bar_close = bt + timedelta(minutes=1)
        if state.get("horizon_end") and bar_close >= _p(state["horizon_end"]):
            exit_px = bar["c"] if d == "LONG" else bar["c"] + spec["spread"]
            state["pnl"] += state["remaining"] * (exit_px - entry) * sgn
            state["remaining"] = 0.0
            return state, _final(spec, state, bar, "TIME")
    # nothing final yet
    hm = spec.get("horizon_minutes")
    hold = hm if hm is not None else spec.get("max_hold_minutes", MAX_HOLD_MINUTES_NO_TIME_EXIT)
    limit = asof + timedelta(minutes=spec["entry_window_minutes"] + hold) + timedelta(days=3)
    if now > limit:
        return state, {"status": "UNRESOLVED", "exit_reason": "NO_DATA_UNTIL_DEADLINE" if hm is not None else "NO_TIME_EXIT_OPEN_BEYOND_MAX_HOLD"}
    if hm is None and state["phase"] == "IN_TRADE" and state.get("entry_time") and \
       now > _p(state["entry_time"]) + timedelta(minutes=hold) and state.get("last_bar") and \
       _p(state["last_bar"]) >= _p(state["entry_time"]) + timedelta(minutes=hold):
        return state, {"status": "UNRESOLVED", "exit_reason": "NO_TIME_EXIT_OPEN_BEYOND_MAX_HOLD"}
    return state, None


def _final(spec, state, bar, reason) -> dict:
    net = state["pnl"] - 2 * spec["commission"]
    r = net / state["risk"]
    end = _p(bar["open_utc"]) + timedelta(minutes=1)
    return {"status": "LABELED", "label": 1 if r > 0 else 0, "outcome_r": round(r, 4), "mfe_r": round(state["mfe"], 3), "mae_r": round(state["mae"], 3),
            "exit_reason": reason, "label_end_utc": _iso(end), "entry_time": state["entry_time"], "entry_price": round(state["entry"], 5),
            "intrabar": state.get("intrabar", "BAR_EXTREMES"), "session_gap_assumed": bool(state.get("session_gap_assumed"))}


def make_spec(rec: dict, asof: str, *, spread: float, slippage: float, commission: float, cost_flags: list[str]) -> dict:
    """Entry/exit policy fixed at sample creation from the setup plan - the same policy object live/PAPER use."""
    from ..execution import policy as exit_policy
    from ..strategies.base import TF_SECONDS
    tf_min = TF_SECONDS[rec["timeframe"]] // 60
    pol = exit_policy.from_plan(side=rec["direction"], stop_loss=rec["stop_loss"], targets=rec.get("targets") or [],
                                exit_rules=rec.get("exit_rules") or {}, timeframe=rec["timeframe"])
    return {"direction": rec["direction"], "asof_utc": asof, "stop_loss": rec["stop_loss"],
            "targets": [{"price": t["price"], "weight": t["weight"]} for t in pol["targets"]],
            "be_after_tp1": pol["be_after_tp1"], "horizon_minutes": pol["time_exit_minutes"], "tp_rule": pol["tp_rule"], "rr": pol.get("rr"),
            "max_hold_minutes": MAX_HOLD_MINUTES_NO_TIME_EXIT if pol["time_exit_minutes"] is None else None,
            "entry_window_minutes": 3 * tf_min, "spread": spread, "slippage": slippage, "commission": commission,
            "label_policy_version": LABEL_POLICY_VERSION, "cost_model_version": COST_MODEL_VERSION, "exit_policy_version": pol["version"],
            "cost_flags": cost_flags}
