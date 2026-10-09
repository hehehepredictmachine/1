"""Trade-cycle reconstruction from MT5 deals and the win ratio used by MasterQUO (MQ-WINRATIO-1.0.0).

Definition shown in the UI:
    win_ratio = 100 x wins / (wins + losses)
* unit = a COMPLETED trade cycle (not an order or a single deal);
* result = NET: profit + commission + swap + fee of the deals of that cycle;
* neutral = |net| <= half of the smallest currency unit (10^-digits / 2) -> shown separately, excluded from the denominator;
* open and partially closed cycles are not counted; deposits/withdrawals/credits/corrections and other non-trade deals are
  excluded by deal TYPE; separately booked costs (daily commission etc.) without a deal->position link are NOT spread over
  trades - they are reported as `unattributed_costs`;
* no wins and no losses -> None (shown as N/A, never 0%).

Cycle reconstruction per position_id (MT5 deal properties): deals sorted by time and ticket, signed open volume tracked;
ENTRY_IN opens/increases, ENTRY_OUT / OUT_BY reduce (partial closes stay in the same cycle), ENTRY_INOUT (netting
reversal) is split: the part that closes the current volume ends the cycle (it carries the deal profit), the rest opens a
new cycle; commission/swap/fee of the INOUT deal are split proportionally to the two volumes (documented assignment).
A position whose first known deal is not an entry (history starts later) gives an INCOMPLETE cycle.
"""
from __future__ import annotations

from collections import defaultdict

VERSION = "MQ-WINRATIO-1.0.0"
TRADE_TYPES = (0, 1)                 # DEAL_TYPE_BUY / DEAL_TYPE_SELL
NON_TRADE = {2: "BALANCE", 3: "CREDIT", 4: "CHARGE", 5: "CORRECTION", 6: "BONUS", 7: "COMMISSION", 8: "COMMISSION_DAILY",
             9: "COMMISSION_MONTHLY", 10: "COMMISSION_AGENT_DAILY", 11: "COMMISSION_AGENT_MONTHLY", 12: "INTEREST",
             13: "BUY_CANCELED", 14: "SELL_CANCELED", 15: "DIVIDEND", 16: "DIVIDEND_FRANKED", 17: "TAX"}
COST_TYPES = (7, 8, 9, 10, 11, 12, 17)
ENTRY_IN, ENTRY_OUT, ENTRY_INOUT, ENTRY_OUT_BY = 0, 1, 2, 3
EPS = 1e-9


def reconstruct(deals: list[dict], bot_magic: int | None) -> list[dict]:
    """deals: rows of trade_deals. Returns cycle dicts (cycle_id, position_id, status, ...)."""
    by_pos: dict[str, list[dict]] = defaultdict(list)
    for d in deals:
        if d["type"] in TRADE_TYPES and d.get("position_id") not in (None, "", "0"):
            by_pos[str(d["position_id"])].append(d)
    cycles = []
    for pid, ds in by_pos.items():
        ds.sort(key=lambda d: (d["time_ms"], int(d["ticket"]) if str(d["ticket"]).isdigit() else 0))
        pos = 0.0            # signed open volume (+ long, - short)
        cur = None
        n = 0

        def new_cycle(d, vol, sign, incomplete=False):
            nonlocal n
            n += 1
            return {"cycle_id": f"{pid}:{n}", "position_id": pid, "symbol": d.get("symbol"), "direction": "LONG" if sign > 0 else "SHORT",
                    "open_ms": d["time_ms"], "close_ms": None, "volume": vol, "gross": 0.0, "commission": 0.0, "swap": 0.0, "fee": 0.0,
                    "status": "INCOMPLETE" if incomplete else "OPEN", "bot": int(bot_magic is not None and d.get("magic") == bot_magic),
                    "note": "HISTORY_STARTS_AFTER_ENTRY" if incomplete else None}

        def add_cost(c, d, share=1.0):
            c["commission"] += share * float(d["commission"] or 0)
            c["swap"] += share * float(d["swap"] or 0)
            c["fee"] += share * float(d["fee"] or 0)

        for d in ds:
            sign = 1.0 if d["type"] == 0 else -1.0
            v = float(d["volume"])
            e = d["entry"]
            if e == ENTRY_IN:
                if cur is None or abs(pos) < EPS:
                    cur = new_cycle(d, 0.0, sign)
                    pos = 0.0
                pos += sign * v
                cur["volume"] += v
                add_cost(cur, d)
            elif e in (ENTRY_OUT, ENTRY_OUT_BY):
                if cur is None:                                   # exit without a known entry: earlier history missing
                    cur = new_cycle(d, v, -sign, incomplete=True)
                    pos = -sign * v
                cur["gross"] += float(d["profit"] or 0)
                add_cost(cur, d)
                pos += sign * v
                if abs(pos) < EPS:
                    cur["close_ms"] = d["time_ms"]
                    if cur["status"] == "OPEN":
                        cur["status"] = "COMPLETE"
                    cycles.append(cur)
                    cur, pos = None, 0.0
            elif e == ENTRY_INOUT:
                if cur is None:
                    cur = new_cycle(d, 0.0, -sign, incomplete=True)
                    pos = 0.0
                closing = min(abs(pos), v) if abs(pos) > EPS else 0.0
                opening = v - closing
                share = closing / v if v > EPS else 0.0
                cur["gross"] += float(d["profit"] or 0)
                add_cost(cur, d, share)
                cur["close_ms"] = d["time_ms"]
                if cur["status"] == "OPEN":
                    cur["status"] = "COMPLETE"
                cur["note"] = (cur["note"] or "") + "REVERSAL_SPLIT;"
                cycles.append(cur)
                cur, pos = None, 0.0
                if opening > EPS:
                    cur = new_cycle(d, opening, sign)
                    add_cost(cur, d, 1 - share)
                    cur["note"] = "OPENED_BY_REVERSAL;"
                    pos = sign * opening
        if cur is not None:
            cycles.append(cur)                                    # still open (or incomplete and open)
    for c in cycles:
        c["net"] = c["gross"] + c["commission"] + c["swap"] + c["fee"]
    return cycles


def outcome(net: float, digits: int) -> str:
    tol = 0.5 * 10 ** (-int(digits))
    return "WIN" if net > tol else "LOSS" if net < -tol else "NEUTRAL"


def win_ratio(cycles: list[dict], deals: list[dict], *, digits: int, since_ms: int | None, until_ms: int | None,
              scope: str = "ACCOUNT", symbol: str | None = None) -> dict:
    sel = []
    open_n = incomplete = 0
    for c in cycles:
        if symbol and c.get("symbol") != symbol:
            continue
        if scope == "BOT" and not c.get("bot"):
            continue
        if c["status"] == "OPEN":
            open_n += 1
            continue
        if c["status"] == "INCOMPLETE":
            if c.get("close_ms") is None or ((since_ms is None or c["close_ms"] >= since_ms) and (until_ms is None or c["close_ms"] < until_ms)):
                incomplete += 1
            continue
        if since_ms is not None and c["close_ms"] < since_ms:
            continue
        if until_ms is not None and c["close_ms"] >= until_ms:
            continue
        sel.append(c)
    w = l = nt = 0
    for c in sel:
        o = outcome(c["net"], digits)
        w += o == "WIN"
        l += o == "LOSS"
        nt += o == "NEUTRAL"
    in_range = [d for d in deals if (since_ms is None or d["time_ms"] >= since_ms) and (until_ms is None or d["time_ms"] < until_ms)]
    non_trade = defaultdict(int)
    unattributed = 0.0
    for d in in_range:
        if d["type"] not in TRADE_TYPES:
            non_trade[NON_TRADE.get(d["type"], f"TYPE_{d['type']}")] += 1
            if d["type"] in COST_TYPES:
                unattributed += float(d["profit"] or 0) + float(d["commission"] or 0) + float(d["fee"] or 0)
    return {"version": VERSION, "win_ratio": round(100.0 * w / (w + l), 2) if (w + l) else None, "wins": w, "losses": l, "neutral": nt,
            "open_cycles": open_n, "incomplete_cycles": incomplete, "excluded_non_trade": dict(non_trade),
            "unattributed_costs": round(unattributed, 2), "complete": incomplete == 0 and abs(unattributed) < 1e-9,
            "net_total": round(sum(c["net"] for c in sel), 2), "scope": scope, "symbol": symbol, "since_ms": since_ms, "until_ms": until_ms,
            "definition": "100 × wygrane / (wygrane + przegrane); wynik netto cyklu (zysk + prowizja + swap + opłaty); neutralne osobno"}
