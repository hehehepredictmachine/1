"""The one cost resolver (PMW-COSTS-1): a track's CostProfile + its inputs -> its cost, with TODAY's formulas.

Every branch reproduces the expression the track used before Etap 4 with the same operands in the same order (IEEE addition is
commutative, so `slippage + commission` equals the old `commission + slippage`; no association is changed), including the old
treatment of None / 0 / an unconvertible commission. The resolver does no I/O and reads no settings: each track gathers its own
inputs (commission source, symbol info, profile) and keeps its gates - the resolver only computes and reports.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import policy as P

MSG_SH_COMMISSION_UNKNOWN = "prowizja nieznana – koszt bez prowizji (AUTO wymaga znanej prowizji)"
REASON_COMMISSION_UNKNOWN = "COST_MODEL_UNKNOWN_COMMISSION"
REASON_SLIPPAGE_UNKNOWN = "SLIPPAGE_STRESS_NOT_CONFIGURED"


@dataclass(frozen=True)
class CostBreakdown:
    """Round-trip cost of 1 lot (ACCOUNT_MONEY_PER_LOT) or of 1 unit of volume (PRICE_PER_UNIT_VOLUME), per `profile.cost_unit`.
    commission / slippage = the round-trip parts (None = unknown or not convertible); spread = the spread part (None when the
    policy keeps the spread inside the fill)."""
    profile: P.CostProfile
    total: float
    spread: float | None
    commission: float | None
    slippage: float | None
    commission_known: bool
    slippage_known: bool
    reason_codes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _bad(p: P.CostProfile, field: str):
    return ValueError(f"COST_POLICY_UNSUPPORTED:{p.track}:{field}={getattr(p, field)}")


def commission_price_side(com: float, contract_size: float, money_per_price: float | None) -> float:
    """Scalp (I0738): commission per lot side (account currency) in price units per unit volume - the larger of com / contract size
    (quote currency = account currency, the value before 1.46 arch) and com / money_per_price (MT5 conversion)."""
    old = com / contract_size if contract_size > 0 else 0.0
    return max(old, com / money_per_price) if money_per_price else old


def _commission(p: P.CostProfile, conv: str | None, com: float | None, money_per_price: float | None,
                contract_size: float | None) -> float | None:
    if conv == P.CONV_MONEY:                                      # ACTIVE: 2 * comm if comm is not None else None
        return 2 * com if com is not None else None
    if conv == P.CONV_TICK_VALUE:                                 # evaluation: 2 * comm / mpp if comm is not None and mpp else 0.0
        return 2 * com / money_per_price if com is not None and money_per_price else None
    if conv == P.CONV_MONEY_PER_PRICE:                            # SH: cost += 2 * comm / spec.money_per_price(1.0) (tick_value > 0)
        return 2 * com / money_per_price if com is not None and money_per_price is not None else None
    if conv == P.CONV_MAX_CONTRACT_TICK:                          # scalp: 2 * commission_price(com, contract_size, mpp)
        return 2 * commission_price_side(com, contract_size, money_per_price) if com is not None else None
    if conv == P.CONV_CONTRACT_SIZE:                              # scalp before 1.46 arch: 2 * com / contract_size
        return 2 * com / contract_size if com is not None else None
    raise ValueError(f"COST_POLICY_UNSUPPORTED:{p.track}:commission_conversion={conv}")


def _slippage(p: P.CostProfile, slippage: float | None, point: float | None, tick: float | None,
              move_value: Callable[[float], float | None] | None) -> float | None:
    unit = p.slippage_unit
    if unit == P.SLIP_POINTS_BROKER:                              # ACTIVE: broker value of slip_pts * point, both sides
        if slippage is not None and point:
            delta = slippage * point
            v = move_value(delta)
            return 2 * abs(v) if v is not None else None
        return None
    if unit == P.SLIP_POINTS:                                     # evaluation: (pts or 0.0) * point * 2
        return (slippage or 0.0) * point * 2
    if unit == P.SLIP_PRICE:                                      # SH: 2 * (slippage_usd or 0.0)
        return 2 * (slippage or 0.0)
    if unit == P.SLIP_TICKS:                                      # scalp: 2 * slippage_ticks * tick
        return 2 * slippage * tick
    raise _bad(p, "slippage_unit")


def resolve(p: P.CostProfile, *, spread: float | None = None, commission_per_lot_side: float | None = None,
            slippage: float | None = None, point: float | None = None, tick: float | None = None, money_per_price: float | None = None,
            contract_size: float | None = None, move_value: Callable[[float], float | None] | None = None,
            gate_check: bool = False) -> CostBreakdown:
    """Round-trip cost of the track `p` (ACTIVE, EVALUATION_ACTIVE, SH, SCALP).

    Inputs as the track gathered them: commission per lot per side (account currency; None = unknown), the slippage setting in the
    unit of the policy, point / tick size, money per 1.0 of price per lot (SH: spec.money_per_price(1.0) only when tick_value > 0),
    contract size (scalp), move_value(delta) = broker value of a price move of `delta` for 1 lot (ACTIVE).
    gate_check=True: the same cost with the policy's `gate_check_conversion` (scalp: the cost before 1.46 arch its gate also requires)."""
    com = commission_per_lot_side
    known_raw = com is not None
    if com is None and p.unknown_commission_policy == P.UNKNOWN_GATE_BLOCKS:
        com = 0.0                                                 # scalp: the gate blocks; the cost is computed with 0 (`com or 0.0`)
    elif p.unknown_commission_policy not in (P.UNKNOWN_REASON_CODE, P.UNKNOWN_FLAG, P.UNKNOWN_WARNING, P.UNKNOWN_GATE_BLOCKS):
        raise _bad(p, "unknown_commission_policy")
    conv = p.gate_check_conversion if gate_check else p.commission_conversion
    if conv is None:
        raise _bad(p, "gate_check_conversion")
    comm = _commission(p, conv, com, money_per_price, contract_size)
    slip = _slippage(p, slippage, point, tick, move_value)
    reasons: list[str] = []
    warnings: list[str] = []
    if p.spread_policy == P.SPREAD_AS_COST:                       # SH (O7): cost = spread + 2 * slip [+ 2 * comm / mpp]
        sp = spread or 0.0
        total = sp + slip
        if comm is not None:
            total += comm
    elif p.spread_policy == P.SPREAD_IN_FILL:                     # ACTIVE / evaluation / scalp: slippage + commission
        sp = None
        total = (slip if slip is not None else 0.0) + (comm if comm is not None else 0.0)
    else:
        raise _bad(p, "spread_policy")
    if p.unknown_commission_policy == P.UNKNOWN_REASON_CODE and com is None:
        reasons.append(REASON_COMMISSION_UNKNOWN)
    if p.unknown_slippage_policy == P.SLIP_UNKNOWN_REASON_CODE and slip is None:
        reasons.append(REASON_SLIPPAGE_UNKNOWN)
    if p.unknown_commission_policy == P.UNKNOWN_WARNING and comm is None:
        warnings.append(MSG_SH_COMMISSION_UNKNOWN)
    known = (known_raw and money_per_price is not None) if p.known_requires_conversion else known_raw
    return CostBreakdown(profile=p, total=total, spread=sp, commission=comm, slippage=slip, commission_known=known,
                         slippage_known=slip is not None, reason_codes=tuple(reasons), warnings=tuple(warnings))


def sizing_loss_per_lot(p: P.CostProfile, *, stop_distance: float, round_trip_price: float, money_per_price: float,
                        commission_per_lot_side: float | None) -> float:
    """SH sizing: loss per lot at the SL in account money = (SL distance + round_trip_price) x money per price + 2 x commission
    (the commission is already inside round_trip_price - counted twice, decision D2, unchanged)."""
    if p.sizing_commission != P.SIZING_TWICE:
        raise _bad(p, "sizing_commission")
    com = commission_per_lot_side
    return (stop_distance + round_trip_price) * money_per_price + (2 * com if com is not None else 0.0)


def extra_from_round_trip(p: P.CostProfile, round_trip_price, spread) -> float | None:
    """Evaluation of SH candidates: the cost outside the Ask / Bid entry = max(0, producer round trip - its spread); None = unknown."""
    if p.spread_policy != P.SPREAD_REMOVED:
        raise _bad(p, "spread_policy")
    if round_trip_price is None:
        return None
    return max(0.0, float(round_trip_price) - float(spread or 0.0))


def label_cost(p: P.CostProfile, cost_price, commission_known) -> float | None:
    """Quant event labels: the candidate's cost_price; an explicitly unknown commission (False) or no cost = no net label (None)."""
    if p.unknown_commission_policy != P.UNKNOWN_NO_LABEL:
        raise _bad(p, "unknown_commission_policy")
    return float(cost_price) if cost_price is not None and commission_known is not False else None


def be_offset(p: P.CostProfile, cost_price) -> float:
    """Quant event labels: the break-even offset after costs = the candidate's cost_price (0 when absent), commission known or not."""
    if p.spread_policy != P.SPREAD_INHERITED:
        raise _bad(p, "spread_policy")
    return float(cost_price or 0.0)
