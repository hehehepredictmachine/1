"""Cost model. "Zero" is a declared account profile, not proof of zero cost.

Spread is NOT a separate cost line: entries are priced at Ask (BUY) / Bid (SELL) and exits at the
opposite side, so the spread is already inside the broker profit calculation (M11 §3).
Separate cost lines: commission (per lot per side), slippage stress, swap (if held overnight).
"""
from __future__ import annotations

import statistics

DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT = 0, 1, 2
DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1


def commission_from_history(deals: list[dict], symbol: str, min_samples: int = 3) -> dict:
    per = []
    for d in deals:
        if d.get("symbol") != symbol or d.get("type") not in (DEAL_TYPE_BUY, DEAL_TYPE_SELL):
            continue
        vol = d.get("volume") or 0
        if vol <= 0 or d.get("entry") not in (DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT):
            continue
        per.append(abs(float(d.get("commission") or 0.0)) / vol)
    if len(per) < min_samples:
        return {"per_lot_per_side": None, "samples": len(per), "source": "DEAL_HISTORY_INSUFFICIENT",
                "note": "Za mało transakcji na symbolu w historii; ustaw prowizję ręcznie w ustawieniach."}
    return {"per_lot_per_side": round(statistics.median(per), 4), "samples": len(per), "source": "DEAL_HISTORY_MEDIAN",
            "note": "Mediana z historii transakcji rachunku (pobierana per deal). Taryfa może się zmienić."}


def resolve_commission(cost_cfg, deals: list[dict], symbol: str) -> dict:
    if cost_cfg.commission_mode == "CONFIGURED" and cost_cfg.commission_per_lot_per_side is not None:
        return {"per_lot_per_side": float(cost_cfg.commission_per_lot_per_side), "samples": None, "source": "CONFIGURED"}
    if cost_cfg.commission_mode == "FROM_DEAL_HISTORY":
        r = commission_from_history(deals, symbol)
        if r["per_lot_per_side"] is None and cost_cfg.commission_per_lot_per_side is not None:
            return {"per_lot_per_side": float(cost_cfg.commission_per_lot_per_side), "samples": r["samples"],
                    "source": "CONFIGURED_FALLBACK"}
        return r
    return {"per_lot_per_side": None, "samples": None, "source": "UNKNOWN"}
