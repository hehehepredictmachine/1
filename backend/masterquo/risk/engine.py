"""Deterministic risk engine (port of M11 v1.0.0-CANDIDATE rules).

Independent of the AI agent: it receives only engine levels, broker data and configured limits.
  BUDGET_PER_TRADE = equity * risk_fraction
  AVAILABLE        = min(budget, daily_limit - daily_used, portfolio_cap - open_risk)
  per 1.0 lot: STOP_LOSS_GROSS = |broker_profit(entry -> SL)|, COST_STRESS = 2*commission + slippage stress
  RAW_LOTS = AVAILABLE / (STOP_LOSS_GROSS + COST_STRESS); LOTS = floor_to_step(min(RAW, volume_max))
  LOTS < volume_min -> BLOCKED (never rounded up)
  RR_NET = (sum w_i * profit(entry -> TP_i) - cost) / (|profit(entry -> SL)| + cost)
  RR_NET < rr_block_below -> BLOCKED; < rr_pass_from -> CONDITIONAL (no execution); else PASS.
Unknown inputs are null with a reason; a missing required component blocks (never treated as 0).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Callable

from .costs import DEAL_ENTRY_IN, DEAL_ENTRY_OUT

ProfitFn = Callable[[str, float, float, float], "float | None"]
MarginFn = Callable[[str, float, float], "float | None"]


def floor_to_step(x: float, step: float, vmin: float) -> float:
    if step <= 0:
        return 0.0
    n = math.floor((x - 0.0) / step + 1e-9)
    v = round(n * step, 8)
    return v if v >= vmin - 1e-12 else 0.0


def limits_configured(limits) -> list[str]:
    missing = []
    for k in ("risk_per_trade_pct", "max_total_open_risk_pct", "daily_loss_limit_pct", "max_drawdown_pct", "max_open_positions"):
        if getattr(limits, k) is None:
            missing.append(k)
    return missing


def daily_loss_used(deals: list[dict], day_start_raw: float | None, floating: float) -> dict:
    """Realized net P/L of trading deals since the broker-day start + negative floating P/L.

    Deposits/withdrawals (balance deals) are excluded; floating *profit* never enlarges the limit.
    """
    if day_start_raw is None:
        return {"status": "UNKNOWN", "used": None, "realized_today": None, "floating": floating}
    realized = 0.0
    for d in deals:
        if d.get("type") not in (0, 1) or (d.get("time") or 0) < day_start_raw:
            continue
        if d.get("entry") not in (DEAL_ENTRY_IN, DEAL_ENTRY_OUT, 2):
            continue
        realized += float(d.get("profit") or 0) + float(d.get("commission") or 0) + float(d.get("swap") or 0) + float(d.get("fee") or 0)
    used = max(0.0, -realized) + max(0.0, -floating)
    return {"status": "OK", "used": round(used, 2), "realized_today": round(realized, 2), "floating": round(floating, 2)}


def open_risk(positions: list[dict], profit_fn_any: Callable[[dict], "float | None"]) -> dict:
    total, unknown = 0.0, []
    for p in positions:
        if not p.get("sl"):
            unknown.append(p.get("ticket"))
            continue
        r = profit_fn_any(p)
        if r is None:
            unknown.append(p.get("ticket"))
            continue
        total += max(0.0, -r)
    return {"open_risk": round(total, 2), "positions_without_sl": unknown}


def evaluate(*, side: str, levels: dict, quote: dict | None, symbol_info: dict | None, account: dict | None,
             limits, costs_cfg, commission: dict, profit_fn: ProfitFn, margin_fn: MarginFn,
             positions: list[dict], deals: list[dict], day_start_raw: float | None, equity_peak: float | None,
             open_risk_info: dict, margin_mode: str | None, last_bot_loss_at: datetime | None, now: datetime,
             max_spread_points: float | None, symbol: str) -> dict:
    reasons: list[str] = []
    res: dict = {"engine": "M11-PORT-1.0.0", "side": side, "risk_gate": "BLOCKED", "sizing_status": "NO_SIZING",
                 "limits_missing": limits_configured(limits), "commission": commission}
    order_side = "BUY" if side == "LONG" else "SELL"
    if not quote or not symbol_info or not account:
        res["reason_codes"] = ["QUOTE_OR_SYMBOL_OR_ACCOUNT_UNAVAILABLE"]
        return res
    if levels.get("status") != "AVAILABLE":
        res["reason_codes"] = ["LEVELS_UNAVAILABLE"] + levels.get("reasons", [])
        return res
    entry = float(quote["ask"] if order_side == "BUY" else quote["bid"])
    sl = float(levels["stop_loss"])
    targets = levels["targets"]
    point = float(symbol_info.get("point") or 0) or None
    res.update(entry=entry, stop_loss=sl, targets=targets, quote_side="ASK" if order_side == "BUY" else "BID")
    # geometry vs live price
    if order_side == "BUY" and not (sl < entry < min(t["price"] for t in targets)):
        reasons.append("LIVE_PRICE_OUTSIDE_PLAN_GEOMETRY")
    if order_side == "SELL" and not (max(t["price"] for t in targets) < entry < sl):
        reasons.append("LIVE_PRICE_OUTSIDE_PLAN_GEOMETRY")
    stops_level = (symbol_info.get("trade_stops_level") or 0) * (point or 0)
    if point and (abs(entry - sl) < stops_level or any(abs(t["price"] - entry) < stops_level for t in targets)):
        reasons.append("STOPS_LEVEL_VIOLATION")
    spread_points = quote.get("spread_points")
    res["spread_points"] = spread_points
    if max_spread_points is not None and spread_points is not None and spread_points > max_spread_points:
        reasons.append("SPREAD_LIMIT")
    if symbol_info.get("trade_mode") != 4:
        reasons.append("SYMBOL_TRADE_MODE_NOT_FULL")
    # ---- per-lot economics through the broker calculator
    loss_1 = profit_fn(order_side, 1.0, entry, sl)
    gains_1 = [profit_fn(order_side, 1.0, entry, t["price"]) for t in targets]
    if loss_1 is None or any(g is None for g in gains_1):
        res["reason_codes"] = sorted(set(reasons + ["BROKER_PROFIT_CALC_UNAVAILABLE"]))
        return res
    stop_gross_1 = max(0.0, -loss_1)
    comm = commission.get("per_lot_per_side")
    comm_rt_1 = 2 * comm if comm is not None else None
    if comm is None:
        reasons.append("COST_MODEL_UNKNOWN_COMMISSION")
    slip_pts = costs_cfg.slippage_stress_points
    slip_1 = None
    if slip_pts is not None and point:
        delta = slip_pts * point
        v = profit_fn(order_side, 1.0, entry, entry - delta if order_side == "BUY" else entry + delta)
        slip_1 = 2 * abs(v) if v is not None else None
    if slip_1 is None:
        reasons.append("SLIPPAGE_STRESS_NOT_CONFIGURED")
    cost_1 = (comm_rt_1 or 0.0) + (slip_1 or 0.0)
    reward_1 = sum(t["weight"] * g for t, g in zip(targets, gains_1))
    if stop_gross_1 <= 0:
        res["reason_codes"] = sorted(set(reasons + ["STOP_RISK_NOT_POSITIVE"]))
        return res
    rr = (reward_1 - cost_1) / (stop_gross_1 + cost_1)
    res["per_lot"] = {"stop_loss_gross": round(stop_gross_1, 2), "commission_roundtrip": comm_rt_1,
                      "slippage_stress": None if slip_1 is None else round(slip_1, 2), "weighted_reward_gross": round(reward_1, 2),
                      "total_loss_stress": round(stop_gross_1 + cost_1, 2)}
    res["rr_net"] = round(rr, 3)
    res["rr_complete"] = comm is not None and slip_1 is not None
    if rr < limits.rr_block_below:
        reasons.append(f"RR_NET_BELOW_{limits.rr_block_below}")
        rr_gate = "BLOCKED"
    elif rr < limits.rr_pass_from:
        reasons.append(f"RR_NET_CONDITIONAL_BELOW_{limits.rr_pass_from}")
        rr_gate = "CONDITIONAL"
    else:
        rr_gate = "PASS"
    # ---- account & portfolio
    currency = account.get("currency")
    equity = float(account.get("equity") or 0)
    free_margin = float(account.get("free_margin") or 0)
    floating = sum(float(p.get("profit") or 0) + float(p.get("swap") or 0) for p in positions)
    daily = daily_loss_used(deals, day_start_raw, floating)
    res.update(currency=currency, equity=equity, free_margin=free_margin, daily=daily, open_risk=open_risk_info,
               positions_count=len(positions), margin_mode=margin_mode)
    if open_risk_info.get("positions_without_sl"):
        reasons.append("OPEN_POSITION_WITHOUT_SL_RISK_UNBOUNDED")
    if margin_mode == "NETTING" and any(p.get("symbol") == symbol for p in positions):
        reasons.append("NETTING_ACCOUNT_EXISTING_POSITION_ON_SYMBOL")
    if res["limits_missing"]:
        reasons.append("RISK_LIMITS_NOT_CONFIGURED")
        res["reason_codes"] = sorted(set(reasons))
        res["risk_gate"] = "BLOCKED"
        return res
    budget = equity * limits.risk_per_trade_pct / 100.0
    # balance at the broker-day start = equity - floating - realized today (documented approximation)
    day_base = equity - daily["floating"] - daily["realized_today"] if daily["status"] == "OK" else None
    daily_cap = day_base * limits.daily_loss_limit_pct / 100.0 if day_base else None
    portfolio_cap = equity * limits.max_total_open_risk_pct / 100.0
    avail = [budget, portfolio_cap - open_risk_info["open_risk"]]
    if daily_cap is None:
        reasons.append("DAILY_LOSS_STATE_UNKNOWN")
    else:
        avail.append(daily_cap - daily["used"])
        if daily["used"] >= daily_cap:
            reasons.append("DAILY_STOP")
    if equity_peak and limits.max_drawdown_pct is not None:
        dd = (equity_peak - equity) / equity_peak * 100 if equity_peak > 0 else 0
        res["drawdown_pct"] = round(dd, 2)
        if dd >= limits.max_drawdown_pct:
            reasons.append("DRAWDOWN_BREACH")
    if len(positions) >= limits.max_open_positions:
        reasons.append("MAX_OPEN_POSITIONS")
    if limits.cooldown_minutes_after_loss and last_bot_loss_at and now - last_bot_loss_at < timedelta(minutes=limits.cooldown_minutes_after_loss):
        reasons.append("COOLDOWN_AFTER_LOSS")
    available = min(avail)
    res.update(trade_budget=round(budget, 2), daily_cap=None if daily_cap is None else round(daily_cap, 2),
               portfolio_cap=round(portfolio_cap, 2), available_budget=round(available, 2))
    if available <= 0:
        reasons.append("NO_RISK_BUDGET_AVAILABLE")
    vmin, vmax, step = float(symbol_info["volume_min"]), float(symbol_info["volume_max"]), float(symbol_info["volume_step"])
    raw = available / (stop_gross_1 + cost_1) if available > 0 else 0.0
    lots = floor_to_step(min(raw, vmax), step, vmin)
    res.update(raw_lots=round(raw, 6), lots=lots, volume_min=vmin, volume_step=step)
    if lots <= 0:
        reasons.append("SIZE_BELOW_BROKER_MIN_LOT")
    else:
        loss_full = profit_fn(order_side, lots, entry, sl)
        gains_full = [profit_fn(order_side, lots, entry, t["price"]) for t in targets]
        margin = margin_fn(order_side, lots, entry)
        cost_full = cost_1 * lots
        if loss_full is None or margin is None or any(g is None for g in gains_full):
            reasons.append("BROKER_CALC_UNAVAILABLE_AFTER_ROUNDING")
        else:
            res.update(modeled_loss=round(abs(loss_full) + cost_full, 2),
                       modeled_reward=round(sum(t["weight"] * g for t, g in zip(targets, gains_full)) - cost_full, 2),
                       margin_required=round(margin, 2))
            if abs(loss_full) + cost_full > available + 1e-6:
                reasons.append("ROUNDED_SIZE_EXCEEDS_BUDGET")
            buf = (limits.min_free_margin_buffer_pct or 0) / 100.0
            if margin > free_margin * (1 - buf):
                reasons.append("INSUFFICIENT_FREE_MARGIN")
            res["sizing_status"] = "SIZED"
    blocking = [r for r in reasons if not r.startswith("RR_NET_CONDITIONAL")]
    if blocking or rr_gate == "BLOCKED":
        res["risk_gate"] = "BLOCKED"
    elif rr_gate == "CONDITIONAL":
        res["risk_gate"] = "CONDITIONAL"
    else:
        res["risk_gate"] = "PASS"
    res["reason_codes"] = sorted(set(reasons))
    return res
