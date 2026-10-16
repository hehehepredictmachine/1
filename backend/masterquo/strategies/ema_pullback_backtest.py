"""Bar-level backtester for the EMA20 Pullback + 2.5R strategy (ORIGINAL / FIXED / candidates).

Execution models (chosen explicitly, reported with every result):
  PINE_DEFAULT  emulation of the Pine broker defaults the original strategy declares: market orders placed at the close
                of the signal bar fill at the NEXT bar's open +- `slippage_ticks`; SL/TP are the absolute prices computed
                from the signal close; commission = `commission_pct` of traded value per side; no spread (single price
                series); quantity in instrument units = risk money / (signal close - SL); intrabar order of high/low
                follows the TradingView heuristic (the extreme closer to the open is visited first).
  MT5           realistic MT5 model: BUY fills at Ask = next open + spread (+slippage), SELL at Bid (-slippage); the
                strategy's SL stays structural, TP = fill +- rr x |fill - SL| (the instruction's rule: TP from your own
                entry); volume in lots = risk money / (|fill-SL| x contract_size x value_per_price_unit), rounded DOWN to
                the volume step - if it is below the minimum lot the entry is REJECTED (risk is never increased);
                a fill already beyond the SL (gap) cancels the trade; long exits on Bid, short exits on Ask (Bid+spread);
                SL and TP touched in the same bar = SL (conservative, no tick data); gaps fill at the open;
                commission per lot per side in account money, optional swap per lot per night.
All prices are Bid OHLC (as MT5 delivers them). Results are deterministic for a given input.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from . import ema_pullback_core as core

BT_VERSION = "MQ-EMA-PULLBACK-BT-1.0.0"


@dataclass
class ExecModel:
    mode: str = "MT5"                    # MT5 | PINE_DEFAULT
    initial_capital: float = 10000.0
    risk_pct: float = 1.0
    tick_size: float = 0.01
    slippage_ticks: int = 3
    spread_price: float | None = None    # None = use the bar's spread field (points x point) when present, else 0
    point: float = 0.01
    commission_pct: float = 0.02         # PINE_DEFAULT only (% of value per side)
    commission_per_lot_side: float = 0.0 # MT5 (account money per lot per side; "Zero" accounts are NOT assumed free)
    swap_per_lot_night: float = 0.0
    contract_size: float = 100.0         # XAUUSD: 100 oz per lot (read from symbol_info.trade_contract_size live)
    value_per_price_unit: float = 1.0    # account money per 1.0 price move per contract unit (USD account, USD quote)
    volume_min: float = 0.01
    volume_step: float = 0.01
    volume_max: float = 100.0
    min_risk_ticks: int = 5              # a stop closer than this is not a valid trade
    entry_delay_bars: int = 0            # stress test: fill N bars later than the next open
    same_bar_policy: str = "SL_FIRST"    # SL_FIRST (conservative) | PINE_HEURISTIC

    def as_dict(self):
        return asdict(self)


@dataclass
class Trade:
    direction: str
    setup_id: int
    signal_i: int
    signal_price: float
    fill_i: int
    fill_price: float
    stop: float
    target: float
    qty: float                  # lots (MT5) or units (PINE_DEFAULT)
    risk_money: float
    exit_i: int | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    gross: float = 0.0
    costs: float = 0.0
    net: float = 0.0
    r: float = 0.0
    time_open: str | None = None
    time_close: str | None = None


def _spread(bar: dict, m: ExecModel) -> float:
    if m.mode == "PINE_DEFAULT":
        return 0.0
    if m.spread_price is not None:
        return m.spread_price
    sp = bar.get("spread")
    return float(sp) * m.point if sp else 0.0


def _round_tick(x: float, t: float) -> float:
    return round(round(x / t) * t, 10)


def simulate(bars: list[dict], machine: core.MachineResult, p: core.Params, m: ExecModel, variant: str) -> dict:
    """bars: closed Bid bars with t (iso), o, h, l, c, optional spread (points). machine: events on the same bars."""
    o = [b["o"] for b in bars]
    h = [b["h"] for b in bars]
    lo = [b["l"] for b in bars]
    c = [b["c"] for b in bars]
    by_i: dict[int, list[core.Event]] = {}
    for e in machine.events:
        if e.kind == "CONFIRM":
            by_i.setdefault(e.i, []).append(e)
    equity = m.initial_capital
    trades: list[Trade] = []
    pos: Trade | None = None
    pending: tuple | None = None              # (fill_bar, event)
    last_fill_i = -10**9
    last_entry_signal_i = -10**9
    eq_curve, peak, max_dd, in_pos_bars = [], equity, 0.0, 0
    diag = {"signals": 0, "blocked_position": 0, "blocked_cooldown": 0, "rejected_min_lot": 0, "rejected_gap_beyond_sl": 0,
            "rejected_small_risk": 0, "rejected_no_margin": 0, "fills": 0, "same_bar_sl_tp": 0, "gap_exits": 0}
    for i in range(len(bars)):
        sp = _spread(bars[i], m)
        slip = m.slippage_ticks * m.tick_size
        # ---- 1. pending entry fills at this bar's open
        if pending and pending[0] == i:
            ev = pending[1]
            pending = None
            long = ev.direction == "LONG"
            if pos is not None and m.mode == "PINE_DEFAULT":         # strategy.entry in the other direction reverses
                px = o[i] - slip if pos.direction == "LONG" else o[i] + slip
                _close(pos, i, px, "REVERSAL", bars, m)
                equity += pos.net
                trades.append(pos)
                pos = None
            fill = (o[i] + slip) if long else (o[i] - slip)
            if m.mode == "MT5":
                fill = (o[i] + sp + slip) if long else (o[i] - slip)
                fill = _round_tick(fill, m.tick_size)
                stop = _round_tick(ev.stop, m.tick_size)
                risk = (fill - stop) if long else (stop - fill)
                if risk <= 0:
                    diag["rejected_gap_beyond_sl"] += 1
                    continue_entry = False
                elif risk < m.min_risk_ticks * m.tick_size:
                    diag["rejected_small_risk"] += 1
                    continue_entry = False
                else:
                    continue_entry = True
                if continue_entry:
                    target = _round_tick(fill + (risk * p.rr if long else -risk * p.rr), m.tick_size)
                    risk_money = equity * m.risk_pct / 100.0
                    per_lot = risk * m.contract_size * m.value_per_price_unit
                    lots = math.floor((risk_money / per_lot) / m.volume_step + 1e-9) * m.volume_step if per_lot > 0 else 0.0
                    lots = min(round(lots, 8), m.volume_max)
                    if lots < m.volume_min - 1e-12:
                        diag["rejected_min_lot"] += 1
                    else:
                        pos = Trade(ev.direction, ev.setup_id, ev.i, ev.ref_price, i, fill, stop, target, lots, lots * per_lot,
                                    time_open=bars[i].get("t"))
                        pos.costs += m.commission_per_lot_side * lots
                        diag["fills"] += 1
                        last_fill_i = i
            else:
                stop, ref = ev.stop, ev.ref_price
                risk_sig = (ref - stop) if long else (stop - ref)
                if risk_sig > 0:
                    target = ref + risk_sig * p.rr if long else ref - risk_sig * p.rr
                    qty = (equity * m.risk_pct / 100.0) / risk_sig
                    pos = Trade(ev.direction, ev.setup_id, ev.i, ref, i, fill, stop, target, qty,
                                qty * abs(fill - stop), time_open=bars[i].get("t"))
                    pos.costs += fill * qty * m.commission_pct / 100.0
                    diag["fills"] += 1
                    last_fill_i = i
        # ---- 2. exits during this bar (including the fill bar)
        if pos is not None:
            res = _exit_in_bar(pos, i, o[i], h[i], lo[i], sp, slip, m)
            if res:
                px, why = res
                if why.endswith("SAME_BAR"):
                    diag["same_bar_sl_tp"] += 1
                if why.startswith("GAP"):
                    diag["gap_exits"] += 1
                _close(pos, i, px, why, bars, m)
                equity += pos.net
                trades.append(pos)
                pos = None
        if pos is not None:
            in_pos_bars += 1
        # ---- 3. signals of this bar (decided on its close)
        for ev in by_i.get(i, []):
            diag["signals"] += 1
            if m.mode == "PINE_DEFAULT":
                cooldown_ok = (i - last_entry_signal_i) >= p.cooldown_bars
                free = (pos is None) if p.only_one_position else True
                if not free:
                    diag["blocked_position"] += 1
                    continue
                if not cooldown_ok:
                    diag["blocked_cooldown"] += 1
                    continue
                if pos is not None and pos.direction == ev.direction:
                    continue                                  # pyramiding=0: same-direction entry ignored by the emulator
                pending = (i + 1 + m.entry_delay_bars, ev)    # if both directions fire, the later one (SHORT) wins - as in Pine
                last_entry_signal_i = i
            else:
                if pos is not None or pending is not None:
                    diag["blocked_position"] += 1             # the confirmed setup is consumed, never executed later
                    continue
                if i - last_fill_i < p.cooldown_bars:
                    diag["blocked_cooldown"] += 1
                    continue
                if ev.stop is None or ev.ref_price is None:
                    continue
                pending = (i + 1 + m.entry_delay_bars, ev)
        # ---- equity (mark to market at the close) and drawdown
        mtm = equity
        if pos is not None:
            px = c[i] if pos.direction == "LONG" else c[i] + sp
            mtm += _gross(pos, px, m) - pos.costs
        eq_curve.append(mtm)
        peak = max(peak, mtm)
        max_dd = max(max_dd, (peak - mtm) / peak if peak > 0 else 0.0)
    if pos is not None:                                       # open at the end: closed at the last close for reporting
        _close(pos, len(bars) - 1, c[-1], "END_OF_DATA", bars, m)
        equity += pos.net
        trades.append(pos)
    return {"variant": variant, "model": m.as_dict(), "params": p.as_dict(), "trades": trades, "diag": diag,
            "final_equity": equity, "max_dd_pct": round(100 * max_dd, 2), "exposure_pct": round(100 * in_pos_bars / max(1, len(bars)), 2),
            "bars": len(bars), "machine_counts": machine.counts, "equity_curve": eq_curve}


def _gross(t: Trade, px: float, m: ExecModel) -> float:
    d = (px - t.fill_price) if t.direction == "LONG" else (t.fill_price - px)
    if m.mode == "MT5":
        return d * t.qty * m.contract_size * m.value_per_price_unit
    return d * t.qty


def _exit_in_bar(t: Trade, i: int, o: float, h: float, lo: float, sp: float, slip: float, m: ExecModel):
    long = t.direction == "LONG"
    # prices that trigger exits: long on Bid, short on Ask (= Bid + spread)
    hi, low, op = (h, lo, o) if long else (h + sp, lo + sp, o + sp)
    if long:
        if op <= t.stop:
            return op - slip, "GAP_SL"
        if op >= t.target:
            return op, "GAP_TP"
        hit_sl, hit_tp = low <= t.stop, hi >= t.target
    else:
        if op >= t.stop:
            return op + slip, "GAP_SL"
        if op <= t.target:
            return op, "GAP_TP"
        hit_sl, hit_tp = hi >= t.stop, low <= t.target
    if hit_sl and hit_tp:
        high_first = abs(h - o) < abs(o - lo)          # TradingView heuristic: the extreme closer to the open comes first
        tp_first = high_first if long else not high_first
        if m.same_bar_policy == "PINE_HEURISTIC" and tp_first:
            return t.target, "TP_SAME_BAR"
        return (t.stop - slip if long else t.stop + slip), "SL_SAME_BAR"
    if hit_sl:
        return (t.stop - slip if long else t.stop + slip), "SL"
    if hit_tp:
        return t.target, "TP"
    return None


def _close(t: Trade, i: int, px: float, why: str, bars, m: ExecModel) -> None:
    t.exit_i, t.exit_price, t.exit_reason = i, px, why
    t.time_close = bars[i].get("t")
    t.gross = _gross(t, px, m)
    if m.mode == "MT5":
        t.costs += m.commission_per_lot_side * t.qty
        nights = _nights(bars[t.fill_i].get("t"), bars[i].get("t"))
        t.costs += m.swap_per_lot_night * t.qty * nights
    else:
        t.costs += px * t.qty * m.commission_pct / 100.0
    t.net = t.gross - t.costs
    t.r = t.net / t.risk_money if t.risk_money > 0 else 0.0


def _nights(a: str | None, b: str | None) -> int:
    if not a or not b:
        return 0
    da = datetime.fromisoformat(a.replace("Z", "+00:00")).astimezone(timezone.utc).date()
    db = datetime.fromisoformat(b.replace("Z", "+00:00")).astimezone(timezone.utc).date()
    return max(0, (db - da).days)


# ------------------------------------------------------------------------------------------------ metrics
def metrics(trades: list[Trade], initial: float, be_tol_r: float = 0.05) -> dict:
    """Closed trades after costs. Win = net R > be_tol_r, loss = net R < -be_tol_r, breakeven reported separately.
    PF = sum(net>0) / |sum(net<0)| (None when there is no losing trade - never 'infinite'). ROI = net / initial capital."""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "note": "BRAK_TRANSAKCJI"}
    wins = [t for t in trades if t.r > be_tol_r]
    losses = [t for t in trades if t.r < -be_tol_r]
    be = n - len(wins) - len(losses)
    gp = sum(t.net for t in trades if t.net > 0)
    gl = -sum(t.net for t in trades if t.net < 0)
    net = sum(t.net for t in trades)
    streak = cur = 0
    for t in trades:
        cur = cur + 1 if t.r < -be_tol_r else 0
        streak = max(streak, cur)
    return {"trades": n, "wins": len(wins), "losses": len(losses), "breakeven": be,
            "winrate_pct": round(100 * len(wins) / (len(wins) + len(losses)), 2) if (wins or losses) else None,
            "profit_factor": round(gp / gl, 3) if gl > 0 else None, "net": round(net, 2), "roi_pct": round(100 * net / initial, 2),
            "expectancy_money": round(net / n, 2), "expectancy_r": round(sum(t.r for t in trades) / n, 4),
            "avg_win": round(sum(t.net for t in wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(t.net for t in losses) / len(losses), 2) if losses else None,
            "max_losing_streak": streak, "costs": round(sum(t.costs for t in trades), 2),
            "long": sum(1 for t in trades if t.direction == "LONG"), "short": sum(1 for t in trades if t.direction == "SHORT")}


def block_bootstrap(rs: list[float], n_boot: int = 2000, block: int | None = None, seed: int = 7) -> dict:
    """Moving-block bootstrap of the trade R sequence (keeps serial dependence inside blocks). 90% intervals."""
    n = len(rs)
    if n < 10:
        return {"note": "ZA_MALO_TRANSAKCJI", "n": n}
    b = block or max(2, int(round(n ** (1 / 3))))
    rnd = random.Random(seed)
    exp_s, wr_s, pf_s = [], [], []
    for _ in range(n_boot):
        sample: list[float] = []
        while len(sample) < n:
            k = rnd.randrange(0, n - b + 1)
            sample += rs[k:k + b]
        sample = sample[:n]
        exp_s.append(sum(sample) / n)
        w = sum(1 for x in sample if x > 0.05)
        lo_ = sum(1 for x in sample if x < -0.05)
        wr_s.append(100 * w / (w + lo_) if w + lo_ else float("nan"))
        gp, gl = sum(x for x in sample if x > 0), -sum(x for x in sample if x < 0)
        pf_s.append(gp / gl if gl > 0 else float("nan"))

    def q(xs, a):
        xs = sorted(x for x in xs if not math.isnan(x))
        return round(xs[int(a * (len(xs) - 1))], 4) if xs else None
    return {"n": n, "block": b, "expectancy_r_90": [q(exp_s, 0.05), q(exp_s, 0.95)], "winrate_90": [q(wr_s, 0.05), q(wr_s, 0.95)],
            "pf_90": [q(pf_s, 0.05), q(pf_s, 0.95)], "p_expectancy_le_0": round(sum(1 for x in exp_s if x <= 0) / len(exp_s), 4)}


def run(bars: list[dict], p: core.Params, m: ExecModel, variant: str, h8_trend=None) -> dict:
    o = [b["o"] for b in bars]
    h = [b["h"] for b in bars]
    lo = [b["l"] for b in bars]
    c = [b["c"] for b in bars]
    ind = core.indicators(o, h, lo, c, p)
    mach = core.run_original(o, h, lo, c, p, ind) if variant.startswith("ORIGINAL") else core.run_fixed(o, h, lo, c, p, ind, h8_trend)
    res = simulate(bars, mach, p, m, variant)
    res["metrics"] = metrics(res["trades"], m.initial_capital)
    res["bootstrap"] = block_bootstrap([t.r for t in res["trades"]])
    return res
