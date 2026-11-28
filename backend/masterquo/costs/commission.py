"""Commission source of the cost config (config.costs: CONFIGURED / FROM_DEAL_HISTORY) - costs.policy.SOURCE_COSTS_CONFIG.

Moved here from risk/costs.py in Etap 4 (PMW-COSTS-1) without any change of code: risk/costs.py keeps the old import path as a
compatibility alias. Used by the ACTIVE track (risk/engine, engine/service, execution paper / manual, ML) and EVALUATION_ACTIVE.
"Zero" is a declared account profile, not proof of zero cost.
"""
from __future__ import annotations

import statistics

DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT = 0, 1, 2
DEAL_ENTRY_OUT_BY = 3                     # closed by an opposite position (Close By) - realized P/L of both legs
DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1


def commission_from_history(deals: list[dict], symbol: str, min_samples: int = 3) -> dict:
    """Commission per lot per side from the account's deals on `symbol`.

    Tariffs differ: per side, round-turn charged at open, or charged at close. When both opening (IN) and closing (OUT)
    deals are available the round-turn = median(IN) + median(OUT) and per side = round-turn / 2 - a plain median over all
    deals would show 0 for an open-only or close-only tariff.

    w2 (I0735): the deal `fee` is a cost too (commission + fee per lot). Without at least `min_samples` IN AND OUT deals the
    tariff is unresolved: per side = the LARGER of the two sides' medians (an open-only / close-only tariff is then counted on
    both sides - conservative; never below the former median over all deals). When that is 0 the history proves nothing
    (e.g. 3 openings of a close-only tariff): per side None with source DEAL_HISTORY_UNRESOLVED_ZERO instead of a "known" 0.0."""
    per, ins, outs = [], [], []
    for d in deals:
        if d.get("symbol") != symbol or d.get("type") not in (DEAL_TYPE_BUY, DEAL_TYPE_SELL):
            continue
        vol = d.get("volume") or 0
        if vol <= 0 or d.get("entry") not in (DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT):
            continue
        v = (abs(float(d.get("commission") or 0.0)) + abs(float(d.get("fee") or 0.0))) / vol
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
    side_max = max(statistics.median(ins) if ins else 0.0, statistics.median(outs) if outs else 0.0)
    value = max(side_max, statistics.median(per))                 # never below the former median over all deals
    if value <= 0:
        return {"per_lot_per_side": None, "samples": len(per), "source": "DEAL_HISTORY_UNRESOLVED_ZERO", "tariff": "UNRESOLVED",
                "note": "Za mało otwarć i zamknięć do ustalenia taryfy, a obserwowana prowizja to 0 – zero nie jest przyjmowane jako "
                        "znana prowizja; ustaw prowizję ręcznie w ustawieniach."}
    return {"per_lot_per_side": round(value, 4), "round_turn_per_lot": round(2 * value, 4), "samples": len(per),
            "source": "DEAL_HISTORY_PARTIAL_CONSERVATIVE", "tariff": "UNRESOLVED",
            "note": "Za mało otwarć/zamknięć do ustalenia taryfy: większa z median stron liczona po obu stronach (konserwatywnie). "
                    "Taryfa może się zmienić."}


def resolve_commission(cost_cfg, deals: list[dict], symbol: str) -> dict:
    if cost_cfg.commission_mode == "CONFIGURED" and cost_cfg.commission_per_lot_per_side is not None:
        return {"per_lot_per_side": float(cost_cfg.commission_per_lot_per_side), "samples": None, "source": "CONFIGURED"}
    if cost_cfg.commission_mode == "FROM_DEAL_HISTORY":
        r = commission_from_history(deals, symbol)
        if r["per_lot_per_side"] is None and cost_cfg.commission_per_lot_per_side is not None:
            # w2 (I0735): an unresolved zero (was a "known" 0.0 DEAL_HISTORY_MEDIAN) falls back to the configured value under its own
            # source name - unknown to the Manual Pad map (commission UNKNOWN there, exactly as DEAL_HISTORY_MEDIAN was)
            src = "CONFIGURED_FALLBACK_UNRESOLVED_HISTORY" if r.get("source") == "DEAL_HISTORY_UNRESOLVED_ZERO" else "CONFIGURED_FALLBACK"
            return {"per_lot_per_side": float(cost_cfg.commission_per_lot_per_side), "samples": r["samples"], "source": src}
        return r
    return {"per_lot_per_side": None, "samples": None, "source": "UNKNOWN"}
