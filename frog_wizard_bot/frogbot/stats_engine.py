"""Frog Wizard statistics engine - pure functions over MT5 deal history (no I/O, no network, no trading).

Methodology (version METHOD_VERSION, documented in docs/METODOLOGIA.md):

Deal classification (MT5 ENUM_DEAL_TYPE):
* TRADING deals: BUY (0), SELL (1). Grouped into completed trades (below).
* EXTERNAL cash flows: BALANCE (2) = deposit (>0) / withdrawal (<0); CREDIT (3), CHARGE (4), CORRECTION (5), BONUS (6).
  They are NEVER trading profit or loss and never a win/loss. Only BALANCE counts as deposit/withdrawal in the report;
  CREDIT/CHARGE/CORRECTION/BONUS are reported as "other balance adjustments".
* ACCOUNT-LEVEL trading costs/income not attributable to one trade: COMMISSION (7..11), INTEREST (12), DIVIDEND (15, 16),
  TAX (17). Included in Net Trading Profit (ROI), excluded from per-trade classification, shown separately.
* CANCELED deals (13, 14) are ignored.

Completed trade = one position life cycle, built from deals with the same position_id in time order:
* signed net volume: BUY deal +volume, SELL deal -volume. A cycle starts when the net volume leaves 0 and is COMPLETE when it
  returns to exactly 0 (within 1e-9 lots). Partial closes therefore stay inside one trade (never counted separately).
* Hedging accounts: every position has its own position_id -> one cycle per position. Close-by (entry OUT_BY) is a closing deal.
* Netting accounts: one position_id can hold several cycles; a reversal deal (entry INOUT, or any deal crossing 0) closes the
  current cycle and opens a new one with the remaining volume. MT5 books the realized profit of a reversal deal on the closing
  part; its commission/swap/fee are assigned to the CLOSED cycle (documented approximation).
* A cycle whose first known deal is a closing deal (opened before the available history) is INCOMPLETE_HISTORY: not
  classified, counted and reported as a warning.
* A cycle that is still open is an OPEN position: excluded from win rate.

Trade net P&L = sum(profit + commission + swap + fee) of its deals (realized, after costs as booked by MT5).
Classification: WIN if net > +tolerance, LOSS if net < -tolerance, BREAK_EVEN otherwise; default tolerance = half of the
smallest currency unit (0.005 for 2 decimals), i.e. "zero at currency precision".
Win rate = wins / (wins + losses) x 100 ; break-even trades shown separately ; no eligible trade -> None (N/A).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

METHOD_VERSION = "FROG-STATS-1.0.0"
TRADING = (0, 1)
EXTERNAL = (2, 3, 4, 5, 6)
ACCOUNT_COSTS = (7, 8, 9, 10, 11, 12, 15, 16, 17)
CANCELED = (13, 14)
ENTRY_IN, ENTRY_OUT, ENTRY_INOUT, ENTRY_OUT_BY = 0, 1, 2, 3
EPS_VOL = 1e-9


def money(d: dict) -> float:
    return float(d.get("profit") or 0) + float(d.get("commission") or 0) + float(d.get("swap") or 0) + float(d.get("fee") or 0)


@dataclass
class Trade:
    account: str
    position_id: int
    cycle: int
    symbol: str
    side: str                        # BUY / SELL (direction of the opening deal)
    deals: list = field(default_factory=list)
    status: str = "OPEN"             # OPEN / COMPLETE / INCOMPLETE_HISTORY
    open_time: float | None = None
    close_time: float | None = None

    @property
    def key(self) -> str:
        return f"{self.account}:{self.position_id}:{self.cycle}"

    def sums(self) -> dict:
        g = sum(float(d.get("profit") or 0) for d in self.deals)
        c = sum(float(d.get("commission") or 0) for d in self.deals)
        s = sum(float(d.get("swap") or 0) for d in self.deals)
        f = sum(float(d.get("fee") or 0) for d in self.deals)
        ins = [d for d in self.deals if d["_role"] == "IN"]
        outs = [d for d in self.deals if d["_role"] == "OUT"]

        def vwap(ds):
            v = sum(float(d["_vol"]) for d in ds)
            return sum(float(d["price"]) * float(d["_vol"]) for d in ds) / v if v > 0 else None
        return {"gross": g, "commission": c, "swap": s, "fee": f, "net": g + c + s + f,
                "volume": sum(float(d["_vol"]) for d in ins), "closed_volume": sum(float(d["_vol"]) for d in outs),
                "entry_price": vwap(ins), "exit_price": vwap(outs)}


def build_trades(deals: list[dict], account: str = "A") -> list[Trade]:
    """Group trading deals into position life cycles (see module doc). `deals`: MT5 deal dicts (ticket, time, type, entry,
    position_id, volume, price, profit, commission, swap, fee, symbol). Duplicates (same ticket) are ignored."""
    seen, trading = set(), []
    for d in deals:
        if int(d.get("type", -1)) not in TRADING or d.get("ticket") in seen:
            continue
        seen.add(d.get("ticket"))
        trading.append(d)
    trading.sort(key=lambda d: (float(d.get("time") or 0), d.get("time_msc") or 0, d.get("ticket") or 0))
    state: dict[int, dict] = {}
    out: list[Trade] = []
    for d in trading:
        pid = int(d.get("position_id") or d.get("ticket") or 0)
        sgn = 1.0 if int(d["type"]) == 0 else -1.0
        vol = float(d.get("volume") or 0)
        st = state.setdefault(pid, {"net": 0.0, "cur": None, "cycles": 0, "first": True})
        entry = int(d.get("entry", ENTRY_IN))
        if st["cur"] is None:
            if st.get("inc") is not None and entry in (ENTRY_OUT, ENTRY_OUT_BY):
                st["inc"].deals.append({**d, "_role": "OUT", "_vol": vol})       # further closes of the pre-history position
                st["inc"].close_time = float(d["time"])
                continue
            st["inc"] = None
            if st["first"] and entry in (ENTRY_OUT, ENTRY_OUT_BY):
                # first deal seen for this position is a close: the opening is outside the available history
                t = Trade(account, pid, st["cycles"], d.get("symbol") or "", "SELL" if sgn > 0 else "BUY", status="INCOMPLETE_HISTORY",
                          close_time=float(d["time"]))
                t.deals.append({**d, "_role": "OUT", "_vol": vol})
                out.append(t)
                st["first"], st["inc"] = False, t
                continue
            st["cycles"] += 1
            t = Trade(account, pid, st["cycles"], d.get("symbol") or "", "BUY" if sgn > 0 else "SELL", open_time=float(d["time"]))
            st["cur"] = t
            out.append(t)
        st["first"] = False
        t = st["cur"]
        before = st["net"]
        after = before + sgn * vol
        if abs(before) < EPS_VOL or (before > 0) == (sgn > 0):
            t.deals.append({**d, "_role": "IN", "_vol": vol})          # opening / adding
            st["net"] = after
            continue
        closing = min(vol, abs(before))
        t.deals.append({**d, "_role": "OUT", "_vol": closing})
        if abs(after) < EPS_VOL or (after > 0) != (before > 0):     # back to zero, or reversal through zero
            t.status, t.close_time = "COMPLETE", float(d["time"])
            st["cur"], st["net"] = None, 0.0
            rest = vol - closing
            if rest > EPS_VOL:                                       # netting reversal: the remainder opens a new cycle
                st["cycles"] += 1
                n = Trade(account, pid, st["cycles"], d.get("symbol") or "", "BUY" if sgn > 0 else "SELL", open_time=float(d["time"]))
                n.deals.append({**d, "profit": 0.0, "commission": 0.0, "swap": 0.0, "fee": 0.0, "_role": "IN", "_vol": rest})
                st["cur"], st["net"] = n, sgn * rest
                out.append(n)
        else:
            st["net"] = after                                        # partial close: same trade
    return out


def classify(net: float, tolerance: float) -> str:
    if net > tolerance:
        return "WIN"
    if net < -tolerance:
        return "LOSS"
    return "BREAK_EVEN"


def default_tolerance(digits: int = 2) -> float:
    return 0.5 * 10 ** (-digits)


# ------------------------------------------------------------------------------------------------ periods
def period_bounds(period: str, now_utc: datetime, tz_offset_minutes: int = 0) -> tuple[float | None, float, str]:
    """(start_utc_epoch | None for all, end_utc_epoch, label). Calendar boundaries in the reporting time zone (offset from UTC);
    the week starts on Monday."""
    tz = timezone(timedelta(minutes=tz_offset_minutes))
    local = now_utc.astimezone(tz)
    day0 = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        start = day0
    elif period == "week":
        start = day0 - timedelta(days=local.weekday())
    elif period == "month":
        start = day0.replace(day=1)
    elif period == "all":
        return None, now_utc.timestamp(), "all"
    else:
        raise ValueError("UNKNOWN_PERIOD")
    return start.timestamp(), now_utc.timestamp(), period


# ------------------------------------------------------------------------------------------------ account statistics
def account_stats(deals: list[dict], *, account: str, currency: str, digits: int = 2, tolerance: float | None = None,
                  start: float | None, end: float, balance_now: float | None, equity_now: float | None,
                  history_from: float | None, open_positions: int | None, snapshots: list[dict] | None = None,
                  server_offset_s: float = 0.0, roi_method: str = "auto") -> dict:
    """Statistics of ONE account for [start, end). Deal times are MT5 server times; server_offset_s converts them to UTC
    (utc = server - offset). history_from: UTC time from which the stored history is complete (None = unknown)."""
    tol = default_tolerance(digits) if tolerance is None else float(tolerance)
    ds = [{**d, "time": float(d["time"]) - server_offset_s} for d in deals if int(d.get("type", -1)) not in CANCELED]
    warnings: list[str] = []
    trades = build_trades(ds, account)
    in_period = (lambda t: (start is None or t >= start) and t < end)
    done = [t for t in trades if t.status == "COMPLETE" and in_period(t.close_time)]
    incomplete = [t for t in trades if t.status == "INCOMPLETE_HISTORY" and in_period(t.close_time)]
    open_cycles = [t for t in trades if t.status == "OPEN"]
    res = {"WIN": 0, "LOSS": 0, "BREAK_EVEN": 0}
    rows = []
    for t in done:
        s = t.sums()
        c = classify(s["net"], tol)
        res[c] += 1
        rows.append({"key": t.key, "position_id": t.position_id, "symbol": t.symbol, "side": t.side, "open_time": t.open_time,
                     "close_time": t.close_time, **{k: round(v, 10) if isinstance(v, float) else v for k, v in s.items()}, "classification": c})
    wl = res["WIN"] + res["LOSS"]
    if incomplete:
        warnings.append(f"INCOMPLETE_HISTORY:{len(incomplete)}")
    # money flows in the period
    pd = [d for d in ds if in_period(float(d["time"]))]
    trade_net = sum(r["net"] for r in rows)
    trading_all = sum(money(d) for d in pd if int(d["type"]) in TRADING)       # incl. partial closes of still-open trades
    acc_costs = sum(money(d) for d in pd if int(d["type"]) in ACCOUNT_COSTS)
    deposits = sum(money(d) for d in pd if int(d["type"]) == 2 and money(d) > 0)
    withdrawals = -sum(money(d) for d in pd if int(d["type"]) == 2 and money(d) < 0)
    other_adj = sum(money(d) for d in pd if int(d["type"]) in (3, 4, 5, 6))
    net_trading_profit = trading_all + acc_costs
    out = {"account": account, "currency": currency, "method_version": METHOD_VERSION, "period_start": start, "period_end": end,
           "completed_trades": len(done), "wins": res["WIN"], "losses": res["LOSS"], "break_even": res["BREAK_EVEN"],
           "win_rate": round(res["WIN"] / wl * 100, 2) if wl else None,
           "deals": sum(1 for d in pd if int(d["type"]) in TRADING),
           "net_closed_trades": round(trade_net, 2), "net_trading_profit": round(net_trading_profit, 2),
           "account_costs": round(acc_costs, 2), "deposits": round(deposits, 2), "withdrawals": round(withdrawals, 2),
           "other_adjustments": round(other_adj, 2), "incomplete_trades": len(incomplete), "open_positions": open_positions,
           "open_cycles_in_history": len(open_cycles), "balance": balance_now, "equity": equity_now,
           "floating": None if balance_now is None or equity_now is None else round(equity_now - balance_now, 2),
           "trades": rows, "tolerance": tol, "warnings": warnings}
    # history coverage
    covered = history_from is not None and (start is None or history_from <= start)
    if start is None and history_from is not None:
        covered = True
    if not covered:
        warnings.append("HISTORY_NOT_COVERING_PERIOD")
    out["history_covered"] = covered
    out["roi"] = roi(ds, start=start, end=end, balance_now=balance_now, covered=covered, snapshots=snapshots or [], method=roi_method,
                     net_trading_profit=net_trading_profit)
    out["max_drawdown"] = max_drawdown(snapshots or [], start, end, ds)
    return out


# ------------------------------------------------------------------------------------------------ ROI
def _balance_at(ds: list[dict], t: float, balance_now: float, end: float) -> float:
    """Balance at time t reconstructed backwards from the current balance: every booked deal after t changed the balance by
    its profit + commission + swap + fee. Requires complete history from t to now."""
    return balance_now - sum(money(d) for d in ds if float(d["time"]) >= t)


def roi(ds: list[dict], *, start: float | None, end: float, balance_now: float | None, covered: bool, snapshots: list[dict],
        method: str, net_trading_profit: float) -> dict:
    """ROI with external cash flows removed.
    * SIMPLE: net trading profit / starting capital (no flows in the period).
    * MODIFIED_DIETZ (default when deposits/withdrawals exist): net trading profit / (V0 + sum(w_i * F_i)), w_i = share of the
      period remaining after flow i. Balance-based (realized) valuation - labelled as an approximation of a time-weighted return.
    * TWR: chained sub-period returns between external flows using EQUITY snapshots taken by the bot right before each flow
      (only when every flow has a snapshot within 15 minutes before it and a snapshot exists at the period start/end).
    Starting capital for 'all' = sum of external flows booked before the first trading deal."""
    lim: list[str] = []
    base = {"value": None, "method": None, "capital_base": None, "net_profit": round(net_trading_profit, 2), "limitations": lim}
    if balance_now is None:
        lim.append("NO_ACCOUNT_BALANCE")
        return base
    if not covered:
        lim.append("HISTORY_INCOMPLETE_FOR_PERIOD")
        return base
    flows = sorted([d for d in ds if int(d["type"]) in EXTERNAL and (start is None or float(d["time"]) >= start) and float(d["time"]) < end],
                   key=lambda d: float(d["time"]))
    if start is None:
        first_trade = min((float(d["time"]) for d in ds if int(d["type"]) in TRADING), default=None)
        if first_trade is None:
            lim.append("NO_TRADES")
            return base
        t0 = first_trade
        v0 = sum(money(d) for d in ds if int(d["type"]) in EXTERNAL and float(d["time"]) < t0)
        flows = [d for d in flows if float(d["time"]) >= t0]
    else:
        t0 = start
        v0 = _balance_at(ds, t0, balance_now, end)
    base["capital_base"] = round(v0, 2)
    if v0 <= 0:
        lim.append("STARTING_CAPITAL_ZERO_OR_NEGATIVE")
        return base
    span = max(1.0, end - t0)
    if not flows:
        base.update(value=round(net_trading_profit / v0 * 100, 2), method="SIMPLE")
        return base
    if method in ("auto", "twr"):
        tw = _twr(flows, snapshots, t0, end)
        if tw is not None:
            base.update(value=round(tw * 100, 2), method="TWR", capital_base=round(v0, 2))
            return base
        if method == "twr":
            lim.append("TWR_NEEDS_EQUITY_SNAPSHOTS_AT_EACH_FLOW")
    denom = v0 + sum(money(d) * (end - float(d["time"])) / span for d in flows)
    if denom <= 0:
        lim.append("DIETZ_DENOMINATOR_NOT_POSITIVE")
        return base
    base.update(value=round(net_trading_profit / denom * 100, 2), method="MODIFIED_DIETZ", capital_base=round(denom, 2))
    lim.append("APPROXIMATION: balance-based Modified Dietz (time-weighted capital), floating P&L excluded")
    return base


def _twr(flows: list[dict], snaps: list[dict], t0: float, end: float, tol_s: float = 900.0) -> float | None:
    snaps = sorted(snaps, key=lambda s: s["t"])
    if not snaps:
        return None

    def at(t, before=True):
        c = [s for s in snaps if (s["t"] <= t if before else s["t"] >= t) and abs(s["t"] - t) <= tol_s]
        return (c[-1] if before else c[0]) if c else None
    s0, s1 = at(t0, before=False) or at(t0), at(end)
    if not s0 or not s1:
        return None
    total, v_start = 1.0, s0["equity"]
    for f in flows:
        b = at(float(f["time"]))
        if not b or v_start <= 0:
            return None
        total *= b["equity"] / v_start
        v_start = b["equity"] + money(f)
    if v_start <= 0:
        return None
    total *= s1["equity"] / v_start
    return total - 1.0


def max_drawdown(snaps: list[dict], start: float | None, end: float, ds: list[dict], min_points: int = 20) -> dict:
    """Peak-to-trough decline of EQUITY snapshots adjusted for external flows (equity minus cumulative flows since the first
    snapshot), in % of the running peak. Needs >= min_points snapshots spanning the period, otherwise N/A."""
    s = sorted([x for x in snaps if (start is None or x["t"] >= start) and x["t"] < end and x.get("equity") is not None], key=lambda x: x["t"])
    if len(s) < min_points:
        return {"value": None, "reason": f"INSUFFICIENT_EQUITY_HISTORY ({len(s)} < {min_points} snapshots)"}
    if start is not None and s[0]["t"] - start > 3600:
        return {"value": None, "reason": "EQUITY_HISTORY_STARTS_AFTER_PERIOD_START"}
    flows = sorted([d for d in ds if int(d["type"]) in EXTERNAL], key=lambda d: float(d["time"]))
    peak, mdd = -math.inf, 0.0
    for x in s:
        adj = x["equity"] - sum(money(f) for f in flows if s[0]["t"] < float(f["time"]) <= x["t"])
        peak = max(peak, adj)
        if peak > 0:
            mdd = max(mdd, (peak - adj) / peak)
    return {"value": round(mdd * 100, 2), "reason": None, "points": len(s)}


# ------------------------------------------------------------------------------------------------ multi-account aggregate
def aggregate(per_account: list[dict]) -> dict:
    """Counts add up across accounts; money only within ONE currency (no FX conversion without a documented rate source)."""
    agg = {k: sum(a.get(k) or 0 for a in per_account) for k in ("completed_trades", "wins", "losses", "break_even", "deals", "incomplete_trades")}
    agg["open_positions"] = sum(a.get("open_positions") or 0 for a in per_account) if all(a.get("open_positions") is not None for a in per_account) else None
    wl = agg["wins"] + agg["losses"]
    agg["win_rate"] = round(agg["wins"] / wl * 100, 2) if wl else None
    agg["accounts"] = len(per_account)
    by_ccy: dict[str, dict] = {}
    for a in per_account:
        c = by_ccy.setdefault(a["currency"], {"net_trading_profit": 0.0, "deposits": 0.0, "withdrawals": 0.0, "capital": 0.0, "accounts": 0,
                                             "roi_ok": True})
        c["net_trading_profit"] += a["net_trading_profit"]
        c["deposits"] += a["deposits"]
        c["withdrawals"] += a["withdrawals"]
        c["accounts"] += 1
        r = a.get("roi") or {}
        if r.get("value") is None or not r.get("capital_base"):
            c["roi_ok"] = False
        else:
            c["capital"] += r["capital_base"]
    for c in by_ccy.values():
        c["roi"] = round(c["net_trading_profit"] / c["capital"] * 100, 2) if c["roi_ok"] and c["capital"] > 0 else None
        for k in ("net_trading_profit", "deposits", "withdrawals", "capital"):
            c[k] = round(c[k], 2)
    agg["by_currency"] = by_ccy
    agg["single_currency"] = len(by_ccy) == 1
    agg["warnings"] = sorted({w for a in per_account for w in a.get("warnings", [])})
    return agg
