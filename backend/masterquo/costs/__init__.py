"""PMW-COSTS-1 (1.46 arch, Etap 4 pkt 4): one cost resolver with a declared policy per decision track (ETAP2_PROJEKT §3 / §4 / §5).

  costs.policy      CostProfile(tor, instrument) with spread_policy, unknown_commission_policy, commission source / conversion,
                    slippage unit and sizing commission - TODAY's policy of every track (ACTIVE, EVALUATION_ACTIVE, SH, EVALUATION_SH,
                    SCALP, QUANT_LABEL); no flag, no setter (O7 / D2 / D3 are owner decisions, not part of this step)
  costs.resolver    resolve(profile, ...) -> CostBreakdown and the per-track helpers (SH sizing, SH-candidate extra cost, Quant label
                    cost) - the formulas of the tracks before Etap 4, bit for bit (tests/test_arch146_e4_costs.py)
  costs.commission  commission source of the cost config (CONFIGURED / FROM_DEAL_HISTORY), moved from risk/costs.py (alias there)

Standard library only (layer L0 of tools/cycles.py): every track - risk / sh (L3), scalp / evaluation / quant (L4) - imports it
without an upward edge.
"""
from .commission import (
    DEAL_ENTRY_IN,
    DEAL_ENTRY_INOUT,
    DEAL_ENTRY_OUT,
    DEAL_ENTRY_OUT_BY,
    DEAL_TYPE_BUY,
    DEAL_TYPE_SELL,
    commission_from_history,
    resolve_commission,
)
from .policy import (
    ACTIVE,
    EVALUATION_ACTIVE,
    EVALUATION_SH,
    POLICIES,
    QUANT_LABEL,
    SCALP,
    SCHEMA,
    SH,
    SPREAD_AS_COST,
    SPREAD_IN_FILL,
    SPREAD_INHERITED,
    SPREAD_REMOVED,
    TRACKS,
    CostPolicy,
    CostProfile,
    policies,
    profile,
)
from .resolver import (
    CostBreakdown,
    be_offset,
    commission_price_side,
    extra_from_round_trip,
    label_cost,
    resolve,
    sizing_loss_per_lot,
)

__all__ = [
    "ACTIVE",
    "DEAL_ENTRY_IN",
    "DEAL_ENTRY_INOUT",
    "DEAL_ENTRY_OUT",
    "DEAL_ENTRY_OUT_BY",
    "DEAL_TYPE_BUY",
    "DEAL_TYPE_SELL",
    "EVALUATION_ACTIVE",
    "EVALUATION_SH",
    "POLICIES",
    "QUANT_LABEL",
    "SCALP",
    "SCHEMA",
    "SH",
    "SPREAD_AS_COST",
    "SPREAD_INHERITED",
    "SPREAD_IN_FILL",
    "SPREAD_REMOVED",
    "TRACKS",
    "CostBreakdown",
    "CostPolicy",
    "CostProfile",
    "be_offset",
    "commission_from_history",
    "commission_price_side",
    "extra_from_round_trip",
    "label_cost",
    "policies",
    "profile",
    "resolve",
    "resolve_commission",
    "sizing_loss_per_lot",
]
