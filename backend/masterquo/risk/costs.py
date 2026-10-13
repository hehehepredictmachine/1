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
    """Commission per lot per side from the account's deals on `symbol`.

    Tariffs differ: per side, round-turn charged at open, or charged at close. When both opening (IN) and closing (OUT)
    deals are available the round-turn = median(IN) + median(OUT) and per side = round-turn / 2 - a plain median over all
    deals would show 0 for an open-only or close-only tariff. Otherwise the median over all deals is used (flagged)."""
    per, ins, outs = [], [], []
    for d in deals:
        if d.get("symbol") != symbol or d.get("type") not in (DEAL_TYPE_BUY, DEAL_TYPE_SELL):
            continue
        vol = d.get("volume") or 0
        if vol <= 0 or d.get("entry") not in (DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT):
            continue
        v = abs(float(d.get("commission") or 0.0)) / vol
        per.append(v)
        (ins if d.get("entry") == DEAL_ENTRY_IN else outs).append(v)
    if len(ins) >= min_samples and len(outs) >= min_samples:
        mi, mo = statistics.median(ins), statistics.median(outs)
        tariff = "PER_SIDE" if abs(mi - mo) <= 1e-9 else ("AT_OPEN" if mo == 0 else ("AT_CLOSE" if mi == 0 else "ASYMMETRIC"))
        return {"per_lot_per_side": round((mi + mo) / 2, 4), "round_turn_per_lot": round(mi + mo, 4), "samples": len(per),
                "source": "DEAL_HISTORY_IN_OUT_MEDIAN", "tariff": tariff,
                "note": "Prowizja z historii rachunku: mediana otwarć + mediana zamknięć (round-turn) / 2. Taryfa może się zmienić."}
    if len(per) < min_samples:
        return {"per_lot_per_side": None, "samples": len(per), "source": "DEAL_HISTORY_INSUFFICIENT",
                "note": "Za mało transakcji na symbolu w historii; ustaw prowizję ręcznie w ustawieniach."}
    return {"per_lot_per_side": round(statistics.median(per), 4), "samples": len(per), "source": "DEAL_HISTORY_MEDIAN",
            "note": "Mediana z historii transakcji rachunku (pobierana per deal; za mało otwarć/zamknięć do ustalenia taryfy). Taryfa może się zmienić."}


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
