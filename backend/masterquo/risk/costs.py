"""Cost model of the ACTIVE track. "Zero" is a declared account profile, not proof of zero cost.

Spread is NOT a separate cost line: entries are priced at Ask (BUY) / Bid (SELL) and exits at the opposite side, so the spread is
already inside the broker profit calculation (M11 §3).
Separate cost lines: commission (per lot per side), slippage stress, swap (if held overnight).

Etap 4 (PMW-COSTS-1): the ACTIVE track declares this policy in costs.policy (track ACTIVE: spread IN_FILL, unknown commission = 0 in
the cost + reason COST_MODEL_UNKNOWN_COMMISSION, slippage stress in points valued by the broker calculator) and computes the cost
through costs.resolver (active_cost_per_lot below, used by risk/engine.evaluate). The commission source (commission_from_history,
resolve_commission) and the MT5 deal constants were moved to masterquo.costs.commission - the names below are compatibility aliases.
"""
from __future__ import annotations

from collections.abc import Callable

from .. import costs as C
from ..costs.commission import (  # noqa: F401 - przeniesione do costs.commission (Etap 4), alias zgodności
    DEAL_ENTRY_IN,
    DEAL_ENTRY_INOUT,
    DEAL_ENTRY_OUT,
    DEAL_ENTRY_OUT_BY,
    DEAL_TYPE_BUY,
    DEAL_TYPE_SELL,
    commission_from_history,
    resolve_commission,
)

COST_TRACK = C.ACTIVE


def active_cost_per_lot(per_lot_per_side: float | None, slippage_stress_points: float | None, point: float | None,
                        move_value: Callable[[float], float | None], symbol: str | None = None) -> C.CostBreakdown:
    """COST_STRESS of 1.0 lot in account money (risk/engine): 2 x commission + slippage stress valued by the broker calculator
    (move_value(delta) = profit of a price move of `delta` against the position for 1 lot). Unknown parts are None in the breakdown,
    0 in the total, with the reason codes COST_MODEL_UNKNOWN_COMMISSION / SLIPPAGE_STRESS_NOT_CONFIGURED."""
    return C.resolve(C.profile(COST_TRACK, symbol), commission_per_lot_side=per_lot_per_side, slippage=slippage_stress_points,
                     point=point, move_value=move_value)
