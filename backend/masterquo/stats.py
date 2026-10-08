"""Statistics from settled, stored events only - no demo numbers.

* bot statistics per mode (PAPER / DEMO_EXECUTION / LIVE_EXECUTION) from `trades`
  (one row per position; partial fills grouped; commission, swap, fee included);
* account statistics from MT5 deal history: trading result separated from balance operations
  (deposits/withdrawals are not strategy profit);
* equity curve from stored equity snapshots (labelled with the first snapshot date) - it is not
  reconstructed from closed P/L.
"""
from __future__ import annotations

from datetime import timedelta

from .timeutil import iso, parse_iso, utcnow

DEAL_TYPE_BALANCE = 2


def _agg(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"trades": 0, "net": 0.0, "win_rate": None, "profit_factor": None, "avg_r": None, "status": "NO_DATA"}
    wins = [r for r in rows if r["net_pnl"] > 0]
    gp = sum(r["net_pnl"] for r in wins)
    gl = -sum(r["net_pnl"] for r in rows if r["net_pnl"] < 0)
    rs = [r["r_multiple"] for r in rows if r.get("r_multiple") is not None]
    return {"trades": n, "net": round(sum(r["net_pnl"] for r in rows), 2), "win_rate": round(len(wins) / n * 100, 1),
            "profit_factor": round(gp / gl, 2) if gl > 0 else None, "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
            "commission": round(sum(r["commission"] for r in rows), 2), "swap": round(sum(r["swap"] for r in rows), 2),
            "avg_r": round(sum(rs) / len(rs), 3) if rs else None, "status": "OK" if n >= 30 else "SMALL_SAMPLE"}


def bot_stats(db, mode: str, account_key: str | None = None) -> dict:
    q = "SELECT * FROM trades WHERE mode=? AND source IN ('BOT','ADOPTED')"
    args: list = [mode]
    if mode != "PAPER" and account_key:
        q += " AND account_key=?"
        args.append(account_key)
    rows = db.query(q + " ORDER BY closed_at", args)
    now = utcnow()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week0 = day0 - timedelta(days=day0.weekday())
    month0 = day0.replace(day=1)

    def since(t):
        return [r for r in rows if parse_iso(r["closed_at"]) >= t]
    cur = rows[-1]["currency"] if rows else None
    return {"mode": mode, "currency": cur, "all": _agg(rows), "day": _agg(since(day0)), "week": _agg(since(week0)),
            "month": _agg(since(month0)), "recent": rows[-20:][::-1],
            "note": "Wyniki z rozliczonych transakcji bota w tym trybie. Mała próba nie pozwala wnioskować o skuteczności."}


def equity_curve(db, mode: str, account_key: str | None, days: int = 30) -> dict:
    frm = iso(utcnow() - timedelta(days=days))
    if mode == "PAPER":
        rows = db.query("SELECT ts, balance, equity FROM equity_snapshots WHERE mode='PAPER' AND ts>=? ORDER BY ts", (frm,))
    else:
        rows = db.query("SELECT ts, balance, equity FROM equity_snapshots WHERE mode='ACCOUNT' AND account_key=? AND ts>=? ORDER BY ts", (account_key, frm))
    if len(rows) > 600:
        step = len(rows) // 600 + 1
        rows = rows[::step] + [rows[-1]]
    first = db.one("SELECT MIN(ts) AS t FROM equity_snapshots WHERE mode=?" + ("" if mode == "PAPER" else " AND account_key=?"),
                   ("PAPER",) if mode == "PAPER" else ("ACCOUNT", account_key))
    return {"mode": mode, "points": rows, "first_snapshot": (first or {}).get("t"),
            "label": "Equity z zapisanych snapshotów (co 60 s, od " + str((first or {}).get("t") or "—") + ")",
            "status": "OK" if len(rows) >= 2 else "NO_DATA"}


def account_stats(deals: list[dict], symbol: str, day_start_raw: float | None) -> dict:
    trading = [d for d in deals if d.get("type") in (0, 1)]
    balance_ops = [d for d in deals if d.get("type") == DEAL_TYPE_BALANCE]

    def net(ds):
        return round(sum(float(d.get("profit") or 0) + float(d.get("commission") or 0) + float(d.get("swap") or 0) + float(d.get("fee") or 0) for d in ds), 2)
    today = [d for d in trading if day_start_raw is not None and d.get("time", 0) >= day_start_raw]
    return {"trading_net_all_symbols": net(trading), "trading_net_symbol": net([d for d in trading if d.get("symbol") == symbol]),
            "trading_net_today": net(today) if day_start_raw is not None else None,
            "balance_operations": round(sum(float(d.get("profit") or 0) for d in balance_ops), 2),
            "balance_operations_count": len(balance_ops), "deals": len(trading),
            "note": "Wpłaty/wypłaty (operacje balance) są wykazane osobno i nie są zyskiem strategii."}
