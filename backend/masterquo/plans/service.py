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
