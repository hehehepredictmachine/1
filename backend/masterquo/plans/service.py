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
    rows = sh.store.db.query("SELECT * FROM sh_plans WHERE strategy=? AND symbol=? AND (account_key IS NULL OR account_key=?) "
                             "ORDER BY created_at DESC LIMIT ?", (strategy, symbol, acct, int(history)))
    for r in rows:
        row = sh.store._plan_row(dict(r))
        o = row.get("fsm_obj")
        pos = basket = None
        if o is not None:
            from ..sh.hedge_fsm import Basket
            if isinstance(o, Basket):
                pos = o.primary.snapshot()
                basket = o.report(q["bid"], q["ask"]) if q else None
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
    sql = "SELECT * FROM sh_plans WHERE strategy_id IS NOT NULL AND symbol=? AND (account_key IS NULL OR account_key=?)"
    args: list = [sym, acct]
    for col, val in (("strategy_id", strategy_id), ("strategy", family), ("signal_tf", tf), ("plan_id", plan_id)):
        if val:
            sql += f" AND {col}=?"
            args.append(val)
    rows = sh.store.db.query(sql + " ORDER BY created_at DESC LIMIT ?", (*args, int(history)))
    plans, seen = [], set()
    from ..sh.hedge_fsm import Basket
    for r in rows:
        row = sh.store._plan_row(dict(r))
        o = row.get("fsm_obj")
        pos = basket = pol = None
        if isinstance(o, Basket):
            pos, basket, pol = o.primary.snapshot(), (o.report(q["bid"], q["ask"]) if q else None), o.policy
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
