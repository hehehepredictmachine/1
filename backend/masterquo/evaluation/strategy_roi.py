"""ROI Strategy Tracker (Apollo23 TASK 014) - read-only performance evaluator per exact scope. Reuses stats._outcome (BE band 0.05 R).

Scope = strategy_id | version | config_hash | market | instrument | venue | timeframe | environment | account | currency | source.
BACKTEST / REPLAY / SHADOW / PAPER / AUTO_DEMO / AUTO_LIVE are never merged. Only CLOSED settled outcomes enter metrics; OPEN_PARTIAL,
UNSETTLED, ambiguous and UNATTRIBUTED rows are reported separately. Strategy ROI needs an explicit capital base (Modified Dietz on the
strategy's virtual equity) - otherwise NO_CAPITAL_BASE (never 0 %, never account ROI). Return on Risk is a separate metric.
Retired OTC (TASK 020) rows stay readable in a separate RETIRED_SCOPE section and never enter the active ranking.
Influence on strategies / ranker / selector / risk / execution: HARD OFF.
"""
from __future__ import annotations

import math

from .. import stats as ST

ENVIRONMENTS = ("BACKTEST", "REPLAY", "SHADOW", "PAPER", "AUTO_DEMO", "AUTO_LIVE")
SCOPE_KEYS = ("strategy_id", "version", "config_hash", "market", "instrument", "venue", "timeframe", "environment", "account", "currency", "source")


def wilson95(w: int, n: int) -> list[float] | None:
    if n <= 0:
        return None
    z = 1.959963984540054
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def sample_status(n: int) -> str:
    return "NO_DATA" if n == 0 else ("SMALL_SAMPLE" if n < 30 else ("PROVISIONAL" if n < 100 else "OBSERVED"))


def metrics(rows: list[dict], capital: dict | None = None) -> dict:
    """rows: closed settled outcomes in close order {net_pnl, gross_pnl?, r_multiple?, initial_risk?, commission?, swap?, fees?, cost_complete?}."""
    n = len(rows)
    base = ST._agg(rows) if n else {"trades": 0}
    w, lo = base.get("wins", 0), base.get("losses", 0)
    risks = [(r["net_pnl"], r["initial_risk"]) for r in rows if r.get("initial_risk") not in (None, 0)]
    out = {**{k: v for k, v in base.items() if k != "definitions"}, "sample_status": sample_status(n),
           "win_rate_ci95": wilson95(w, w + lo) if (w + lo) else None,
           "expectancy_money": round(sum(r["net_pnl"] for r in rows) / n, 2) if n else None,
           "return_on_risk_pct": round(100 * sum(a for a, _ in risks) / sum(b for _, b in risks), 3) if risks else None,
           "return_on_risk_note": "Return on Risk ≠ Strategy ROI",
           "cost_coverage_pct": round(100 * sum(1 for r in rows if r.get("cost_complete", True)) / n, 1) if n else None}
    if not capital or not capital.get("start_equity"):
        out.update(strategy_roi_pct=None, strategy_roi_status="NO_CAPITAL_BASE")
    else:
        e0 = float(capital["start_equity"])
        flows = [(float(a), float(wt)) for a, wt in capital.get("flows", [])]
        e1 = e0 + sum(a for a, _ in flows) + sum(r["net_pnl"] for r in rows)
        roi = ST.roi_modified_dietz(e0, e1, flows)
        out.update(strategy_roi_pct=roi, strategy_roi_status="OK" if roi is not None else "INVALID_CAPITAL_BASE", strategy_roi_method="MODIFIED_DIETZ")
        eq = peak = e0
        dd = 0.0
        for r in rows:
            eq += r["net_pnl"]
            peak = max(peak, eq)
            dd = max(dd, (peak - eq) / peak if peak > 0 else 0)
        out["max_drawdown_pct"] = round(100 * dd, 3)
    return out


def scope_key(r: dict) -> tuple:
    return tuple(str(r.get(k) or "") for k in SCOPE_KEYS)


def report(outcomes: list[dict], capital_by_scope: dict | None = None) -> dict:
    from ..baskets import catalog as CAT
    groups: dict[tuple, list[dict]] = {}
    side = {"OPEN_PARTIAL": 0, "UNSETTLED": 0, "AMBIGUOUS": 0, "UNATTRIBUTED": 0, "UNKNOWN_ENVIRONMENT": 0}
    retired: dict[tuple, list[dict]] = {}
    for r in sorted(outcomes, key=lambda x: str(x.get("closed_at") or "")):
        st = r.get("status", "CLOSED")
        if st != "CLOSED":
            side[st if st in side else "AMBIGUOUS"] += 1
            continue
        if not r.get("strategy_id"):
            side["UNATTRIBUTED"] += 1
            continue
        if r.get("environment") not in ENVIRONMENTS:
            side["UNKNOWN_ENVIRONMENT"] += 1
            continue
        (retired if CAT.retired_reason(r["strategy_id"]) else groups).setdefault(scope_key(r), []).append(r)
    caps = capital_by_scope or {}
    items = [{"scope": dict(zip(SCOPE_KEYS, k)), **metrics(v, caps.get("|".join(k)))} for k, v in groups.items()]
    # 1.46: `or -1e9` turned an expectancy of exactly 0.0 into "no data" (ranked behind losing strategies); None sorts last explicitly
    items.sort(key=lambda x: (x["scope"]["environment"], x.get("expectancy_r") is None, -(x.get("expectancy_r") or 0.0), x["scope"]["strategy_id"]))
    return {"items": items, "excluded": side,
            "retired_scope": [{"scope": dict(zip(SCOPE_KEYS, k)), "label": "RETIRED_OTC (historia, tylko odczyt)", **metrics(v)} for k, v in retired.items()],
            "policy": {"environments_merged": False, "influence": "HARD_OFF", "be_band_r": ST.BE_BAND_R}}


def outcomes_from_db(db, mode: str, account_key: str | None = None) -> list[dict]:
    """Adapter over the existing canonical tables (trades + closed sh_plans) - read-only, no second ledger.
    1.46: only `trades` (S01-S12) was read although the docstring promised closed sh_plans - SCALPING / HEDGING pack variants and the
    FX basket plans routed through AUTO_SH were silently missing from the report. They are now a separate source SH_PLANS (one plan =
    one whole-cycle result, the same settlement rule as stats.engine_stats); ERROR_CLOSED / unsettled plans go to `excluded`."""
    env = {"PAPER": "PAPER", "AUTO_DEMO": "AUTO_DEMO", "AUTO_LIVE": "AUTO_LIVE"}.get(mode)
    out = []
    q = "SELECT * FROM trades WHERE mode=? AND source IN ('BOT','ADOPTED')"
    args: list = [mode]
    if mode != "PAPER" and account_key:
        q += " AND account_key=?"
        args.append(account_key)
    for r in db.query(q + " ORDER BY closed_at", args):
        out.append({"strategy_id": r.get("strategy_id") or None, "version": r.get("exit_policy_version"), "config_hash": None,
                     "market": "FOREX", "instrument": r.get("symbol"), "venue": "MT5", "timeframe": None, "environment": env,
                     "account": r.get("account_key"), "currency": r.get("currency"), "source": "ACTIVE_S01_S12", "status": r.get("status"),
                     "net_pnl": float(r.get("net_pnl") or 0.0), "r_multiple": r.get("r_multiple"), "commission": float(r.get("commission") or 0.0),
                     "swap": float(r.get("swap") or 0.0), "closed_at": r.get("closed_at"), "initial_risk": r.get("planned_risk_money"), "gross_pnl": r.get("gross_pnl"),
                     "cost_complete": '"commission_unknown":true' not in (r.get("deals_json") or "").replace(" ", "")})
    out += _sh_plan_outcomes(db, mode, env, account_key)
    return out


def _sh_plan_outcomes(db, mode: str, env: str | None, account_key: str | None) -> list[dict]:
    import json
    from datetime import UTC, datetime
    q = "SELECT * FROM sh_plans WHERE exec_mode=? AND state IN ('CLOSED','ERROR_CLOSED')"
    args: list = [mode]
    if mode != "PAPER" and account_key:
        q += " AND account_key=?"
        args.append(account_key)
    try:
        rows = db.query(q + " ORDER BY closed_at", args)
    except Exception:  # noqa: BLE001 - a database without the SH tables (older file) has no SH outcomes
        return []
    out = []
    for r in rows:
        try:
            res = json.loads(r.get("result") or "null") or {}
        except ValueError:
            res = {}
        settled = r.get("state") == "CLOSED" and isinstance(res, dict) and res.get("net_money") is not None
        res = res if isinstance(res, dict) else {}
        ca = r.get("closed_at")
        out.append({"strategy_id": r.get("strategy_id") or (f"LEGACY_{r['strategy']}" if r.get("strategy") else None),   # 0027: NULL = legacy
                    "version": None, "config_hash": r.get("config_hash"), "market": None, "instrument": r.get("symbol"), "venue": "MT5",
                    "timeframe": r.get("signal_tf"), "environment": env, "account": r.get("account_key"), "currency": None,
                    "source": "SH_PLANS", "status": "CLOSED" if settled else "UNSETTLED",
                    "net_pnl": float(res["net_money"]) if settled else None, "r_multiple": res.get("r_multiple"),
                    "commission": float(res.get("commission_money") or 0.0), "swap": 0.0,           # SH does not track swap (stats.engine_stats)
                    "closed_at": datetime.fromtimestamp(float(ca), UTC).isoformat().replace("+00:00", "Z") if ca is not None else None,
                    "initial_risk": None, "gross_pnl": res.get("gross_money"), "cost_complete": bool(res.get("commission_known"))})
    return out
