"""Plan views for the chart layers (read-only): current SH evaluation + open plans + recent plan history of the active symbol and
account. Nothing here sends, modifies or cancels orders."""
from __future__ import annotations

import time

from . import contract as PC


def _meta_su(row: dict) -> dict:
    """Frozen plan row -> setup-shaped dict (the plan levels exactly as they were frozen at opening)."""
    p = row.get("plan") or {}
    su = dict(p.get("setup") or {})
    su.update(strategy=row.get("strategy"), side=row.get("side"), symbol=row.get("symbol"), instrument=row.get("instrument"),
              signal_id=row.get("signal_id"), created_at=p.get("created_at") or row.get("created_at"), status="READY",
              config_hash=row.get("config_hash"))
    return su


# 1.46: plans still open (the SH store's own definition, SHStore.open_plans) - always part of a chart answer
OPEN_SQL = " AND state NOT IN ('CLOSED','ERROR_CLOSED','REJECTED')"


def _rows(sh, sql: str, args: tuple, history: int) -> list[dict]:
    """The `history` newest plans + EVERY plan still open with the same filters (deduplicated by plan_id).

    1.46: only `ORDER BY created_at DESC LIMIT history` was read - an open position older than `history` newer (e.g. closed) plans
    vanished from the answer, and with it its SL / TP / FILL lines on the chart."""
    rows = [dict(r) for r in sh.store.db.query(sql + " ORDER BY created_at DESC LIMIT ?", (*args, int(history)))]
    have = {r["plan_id"] for r in rows}
    for r in sh.store.db.query(sql + OPEN_SQL + " ORDER BY created_at DESC", tuple(args)):
        if r["plan_id"] not in have:
            have.add(r["plan_id"])
            rows.append(dict(r))
    return rows


def _basket_report(o, q: dict | None) -> dict:
    """Basket report also without a quote. 1.46: without bid/ask there was no report at all, so the hedge leg (side / entry / status /
    volume / activations - known from the state machine) read NOT_ACTIVE with 0 activations; now only the P&L that needs a quote
    (unrealized / net) is null and the report says the quote is UNAVAILABLE."""
    if q:
        return o.report(q["bid"], q["ask"])
    r = o.report(o.primary.entry, o.primary.entry)            # quote-independent fields only; the P&L below is cleared
    r["primary"]["unrealized"] = None
    r["hedge"]["unrealized"] = None
    r["basket"].update(unrealized=None, net_after_costs=None)
    r["quote"] = "UNAVAILABLE"
    return r


def collect(sh, strategy: str, *, now: float | None = None, history: int = 10) -> dict:
    now = now if now is not None else time.time()
    st = sh.state if hasattr(sh, "state") else {}
    symbol = st.get("symbol") or sh.cfg_store.get().mt5.symbol
    mm = st.get("account_margin_mode")
    q = getattr(sh.bridge, "quote", None)
    acct = getattr(sh.bridge, "account_key", None)
    digits = (getattr(sh.bridge, "symbol_info", None) or {}).get("digits")
    plans = []
    seen_signals = set()
    rows = _rows(sh, "SELECT * FROM sh_plans WHERE strategy=? AND strategy_id IS NULL AND symbol=? AND (account_key IS NULL OR account_key=?)",
                 (strategy, symbol, acct), history)                                                # 1.38: variant plans -> layer PACK
    for r in rows:
        row = sh.store._plan_row(dict(r))
        o = row.get("fsm_obj")
        pos = basket = None
        if o is not None:
            from ..sh.hedge_fsm import Basket
            if isinstance(o, Basket):
                pos = o.primary.snapshot()
                basket = _basket_report(o, q)
            else:
                pos = o.snapshot()
        plans.append(PC.from_setup(_meta_su(row), now=now, plan_row=row, position=pos, basket=basket, account_margin_mode=mm, digits=digits))
        seen_signals.add(row.get("signal_id"))
    cur = (getattr(sh, "last_eval", None) or {}).get(strategy)
    if cur and cur.get("symbol") == symbol and cur.get("signal_id") not in seen_signals:
        plans.append(PC.from_setup(cur, now=now, account_margin_mode=mm, digits=digits))
    out = PC.chart_payload(plans, symbol=symbol, account_key=acct)
    out.update(strategy=strategy, layer=PC.LAYERS[strategy][1], generated_at=now)
    return out


def collect_pack(sh, *, strategy_id: str | None = None, family: str | None = None, tf: str | None = None, plan_id: str | None = None,
                 history: int = 10, symbol: str | None = None, now: float | None = None) -> dict:
    """PMW-PLAN-2 views of the 20 variants on the ACTIVE symbol and account only (never XAU levels on a BTC chart, never another account):
    frozen plans (sh_plans rows with a strategy_id) + current READY / EXPIRED / INVALIDATED candidates of the pack engine."""
    now = now if now is not None else time.time()
    st = sh.state if hasattr(sh, "state") else {}
    sym = st.get("symbol") or sh.cfg_store.get().mt5.symbol
    if symbol and symbol != sym:
        return {"contract": PC.VERSION2, "symbol": symbol, "plans": [], "primary": None,
                "note": f"symbol {symbol} nie jest aktywnym symbolem silnika ({sym}) – brak poziomów (bez rysowania obcych planów)"}
    mm = st.get("account_margin_mode")
    q = getattr(sh.bridge, "quote", None)
    acct = getattr(sh.bridge, "account_key", None)
    digits = (getattr(sh.bridge, "symbol_info", None) or {}).get("digits")
    # 1.46: LEGACY_SCALPING / LEGACY_HEDGING (accepted by the API) = plans without a variant, as in SHStore.recent_signals; the filter
    # strategy_id='LEGACY_X' together with strategy_id IS NOT NULL always gave an empty list
    legacy = strategy_id[len("LEGACY_"):] if strategy_id and strategy_id.startswith("LEGACY_") else None
    if legacy:
        sql = "SELECT * FROM sh_plans WHERE strategy_id IS NULL AND strategy=? AND symbol=? AND (account_key IS NULL OR account_key=?)"
        args: list = [legacy, sym, acct]
    else:
        sql = "SELECT * FROM sh_plans WHERE strategy_id IS NOT NULL AND symbol=? AND (account_key IS NULL OR account_key=?)"
        args = [sym, acct]
    for col, val in (("strategy_id", None if legacy else strategy_id), ("strategy", family), ("signal_tf", tf), ("plan_id", plan_id)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    rows = _rows(sh, sql, tuple(args), history)
    plans, seen = [], set()
    from ..sh.hedge_fsm import Basket
    for r in rows:
        row = sh.store._plan_row(dict(r))
        o = row.get("fsm_obj")
        pos = basket = pol = None
        if isinstance(o, Basket):
            pos, basket, pol = o.primary.snapshot(), _basket_report(o, q), o.policy
        elif o is not None:
            pos = o.snapshot()
        su = _meta_su(row)
        su.update(strategy_id=row.get("strategy_id"), pack=(row.get("plan") or {}).get("pack") or {}, tps=(row.get("plan") or {}).get("setup", {}).get("tps"))
        plans.append(PC.from_pack(su, now=now, plan_row=row, position=pos, basket=basket, basket_policy=pol, account_margin_mode=mm, digits=digits))
        seen.add(row.get("signal_id"))
    pk = getattr(sh, "pack", None)
    if pk is not None and not plan_id:
        for (vid, stf), su in list(pk.last.items()):
            if su.get("symbol") != sym or su.get("signal_id") in seen or su.get("status") not in ("READY", "EXPIRED", "INVALIDATED"):
                continue
            if (strategy_id and vid != strategy_id) or (family and su.get("strategy") != family) or (tf and stf != tf):
                continue
            plans.append(PC.from_pack(su, now=now, account_margin_mode=mm, digits=digits))
    order = sorted(plans, key=lambda p: (p.get("signal_time") or 0), reverse=True)
    pick = None
    if plan_id:
        pick = next((p["plan_key"] for p in order if p.get("plan_id") == plan_id), None)
    pick = pick or next((p["plan_key"] for p in order if p["state"] == "ACTIVE"), None) or \
        next((p["plan_key"] for p in order if p["state"] == "READY"), None) or (order[0]["plan_key"] if order else None)
    return {"contract": PC.VERSION2, "symbol": sym, "account_key": acct, "primary": pick, "plans": order, "generated_at": now,
            "filters": {"strategy_id": strategy_id, "family": family, "tf": tf, "plan_id": plan_id, "history": history},
            "note": "poziomy z planu wariantu i danych wykonania; przełączanie warstw nie zmienia zleceń"}
