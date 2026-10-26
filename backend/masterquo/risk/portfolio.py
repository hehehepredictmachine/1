"""Shared portfolio guard for BOTH execution paths (prompt §23, Definition of Done 8; PMW-RISK-PORTFOLIO-1).

Each path keeps its own sizing and limits (risk/engine.py for S01-S12, sh/risk.py for SCALPING/HEDGING). This guard adds what
neither of them sees alone: today's realised result of BOTH paths and the open positions of BOTH paths, checked against the
stricter of the two configured limits. It only stops NEW entries (reason codes returned through ModeManager.gate(path=...));
it never closes, resizes or modifies a position.

* Day = UTC calendar day; results in the account currency (net of commission when it is known).
* Unknown equity -> the daily check is not decided here (each path's own risk engine already refuses without equity).
* A limit missing in both configurations is not invented.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

VERSION = "PMW-RISK-PORTFOLIO-1"


def _day_start(now: float) -> float:
    d = datetime.fromtimestamp(now, timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def state(db, mode: str, account_key: str | None, now: float) -> dict:
    day0 = _day_start(now)
    day0_iso = datetime.fromtimestamp(day0, timezone.utc).isoformat().replace("+00:00", "Z")
    acct = mode != "PAPER" and account_key
    q = "SELECT net_pnl FROM trades WHERE mode=? AND source IN ('BOT','ADOPTED') AND status='CLOSED' AND closed_at >= ?"
    args: list = [mode, day0_iso]
    if acct:
        q += " AND account_key=?"
        args.append(account_key)
    active_today = sum(float(r["net_pnl"] or 0.0) for r in db.query(q, args))
    q = "SELECT result FROM sh_plans WHERE exec_mode=? AND state IN ('CLOSED','ERROR_CLOSED') AND closed_at >= ?"
    args = [mode, day0]
    if acct:
        q += " AND account_key=?"
        args.append(account_key)
    sh_today = 0.0
    for r in db.query(q, args):
        res = json.loads(r["result"]) if r.get("result") else {}
        if res.get("net_money") is not None:
            sh_today += float(res["net_money"])
    q = "SELECT COUNT(*) AS n FROM managed_positions WHERE state='OPEN' AND mode=?"
    args = [mode]
    if acct:
        q += " AND account_key=?"
        args.append(account_key)
    open_active = int(db.query(q, args)[0]["n"])
    q = "SELECT COUNT(*) AS n FROM sh_plans WHERE state NOT IN ('CLOSED','ERROR_CLOSED','REJECTED') AND exec_mode=?"
    args = [mode]
    if acct:
        q += " AND account_key=?"
        args.append(account_key)
    open_sh = int(db.query(q, args)[0]["n"])
    return {"realized_today": round(active_today + sh_today, 2), "realized_by_path": {"ACTIVE": round(active_today, 2), "SH": round(sh_today, 2)},
            "open_positions": open_active + open_sh, "open_by_path": {"ACTIVE": open_active, "SH": open_sh}, "day_start_utc": day0_iso}


def check(st: dict, *, equity: float | None, legacy_limits, sh_limits: dict | None) -> list[str]:
    """legacy_limits: config.RiskLimits (fields may be None); sh_limits: sh_strategies risk section."""
    sh_limits = sh_limits or {}
    reasons = []
    pcts = [float(x) for x in (getattr(legacy_limits, "daily_loss_limit_pct", None), sh_limits.get("daily_loss_limit_pct")) if x]
    if pcts and equity and float(equity) > 0 and st["realized_today"] <= -min(pcts) / 100.0 * float(equity):
        reasons.append("PORTFOLIO_DAILY_LOSS_LIMIT")
    caps = [int(x) for x in (getattr(legacy_limits, "max_open_positions", None), sh_limits.get("max_open_positions")) if x]
    if caps and st["open_positions"] >= min(caps):
        reasons.append("PORTFOLIO_MAX_OPEN_POSITIONS")
    return reasons
