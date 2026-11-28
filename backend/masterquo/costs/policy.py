"""Cost policies of the decision tracks (PMW-COSTS-1) - declarations of TODAY's behaviour, nothing switchable.

ETAP2_PROJEKT §4 (row "Koszty"): >= 4 spread conventions, 3 commission sources, 3 slippage units and 4 policies for an unknown
commission lived inside the tracks' code. Each track now names its policy here (one source of truth: `POLICIES`) and computes its
cost through `costs.resolver` - the same formulas in the same order of operations as before Etap 4 (bit for bit, proven by
tests/test_arch146_e4_costs.py: the old code vs the resolver on random inputs).

Neutral version: the declarations describe what the code did before Etap 4, including the known inconsistencies, and there is NO
flag and NO setter that changes a policy. Changing one is a trading decision of the owner:
  * O7 / D2 - SH counts the spread as a cost line although it enters at Ask / Bid, and the SH sizing counts the commission twice
    (in round_trip_price AND again as 2 x commission per lot);
  * D3 - one sizing function and one `cost_price` semantics of SetupCandidate (cost outside the price + cost_includes_spread).
The resolver accepts only the values declared below; any other value raises ValueError (no silent fallback to another policy).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache

SCHEMA = "PMW-COSTS-1"

# ---- tracks (tor) ----------------------------------------------------------------------------------------------------------------
ACTIVE = "ACTIVE"                          # path A risk gate: risk/engine.evaluate via risk/costs.active_cost_per_lot (money / 1 lot)
EVALUATION_ACTIVE = "EVALUATION_ACTIVE"    # evaluation/service._active_cost: cost of an S01-S12 candidate in price units (SHADOW)
SH = "SH"                                  # path B: sh/setup round_trip_price + sh/risk sizing (loss per lot)
EVALUATION_SH = "EVALUATION_SH"            # evaluation/service._sh: extra cost of an SH candidate in price units (SHADOW)
SCALP = "SCALP"                            # scalp economics gate / outcome costs (scalp/strategy.cost_extra, scalp/service)
QUANT_LABEL = "QUANT_LABEL"                # quant/events.spec_from_candidate: cost of the Quant event labels

# ---- spread_policy ---------------------------------------------------------------------------------------------------------------
SPREAD_IN_FILL = "IN_FILL"                 # entry at Ask (BUY) / Bid (SELL): the spread is inside the fill, no separate cost line
SPREAD_AS_COST = "AS_COST"                 # the spread is a cost line of the round trip although the entry is at Ask / Bid (O7, D2)
SPREAD_REMOVED = "REMOVED_FROM_ROUND_TRIP"  # the producer's round trip minus its spread, floored at 0 (evaluation of SH candidates)
SPREAD_INHERITED = "INHERITED"             # the candidate's cost_price as given (ACTIVE / scalp: without, SH: with the spread)

# ---- unknown_commission_policy ---------------------------------------------------------------------------------------------------
UNKNOWN_REASON_CODE = "ZERO_IN_COST_REASON_CODE"   # 0 in the cost + reason COST_MODEL_UNKNOWN_COMMISSION, rr_complete False (ACTIVE)
UNKNOWN_FLAG = "ZERO_IN_COST_FLAG_UNKNOWN"         # 0 in the cost, commission_known False -> COMMISSION_UNKNOWN (evaluation)
UNKNOWN_WARNING = "ZERO_IN_COST_WARNING"           # 0 in the cost + a warning on the setup, the sizing adds 0 (SH; gate withdrawn 1.39)
UNKNOWN_GATE_BLOCKS = "GATE_BLOCKS_ZERO_IN_COST"   # the 'prowizja znana' gate blocks; cost / label computed with 0 and marked (scalp)
UNKNOWN_NO_LABEL = "NO_NET_LABEL"                  # cost_price None -> no net label (net_r None), never a zero cost (Quant events)
UNKNOWN_INHERITED = "INHERITED"                    # the producer's round trip and commission_known as given (evaluation of SH)

# ---- unknown_slippage_policy -----------------------------------------------------------------------------------------------------
SLIP_UNKNOWN_REASON_CODE = "ZERO_IN_COST_REASON_CODE"  # 0 in the cost + reason SLIPPAGE_STRESS_NOT_CONFIGURED (ACTIVE)
SLIP_UNKNOWN_ZERO = "ZERO"                             # a missing setting counts as 0 (evaluation ACTIVE, SH)
SLIP_UNKNOWN_NOT_APPLICABLE = "NOT_APPLICABLE"         # the setting is always set (scalp) or the cost comes from the producer

# ---- commission_source -----------------------------------------------------------------------------------------------------------
SOURCE_COSTS_CONFIG = "COSTS_CONFIG_OR_DEAL_HISTORY"   # config.costs CONFIGURED / FROM_DEAL_HISTORY (costs.commission.resolve_commission)
SOURCE_SH_PROFILE = "SH_INSTRUMENT_PROFILE"            # SH instrument profile commission_per_lot_side
SOURCE_SCALP_CONFIG = "SCALP_CONFIG"                   # config.scalp.commission_per_lot_side
SOURCE_PRODUCER = "PRODUCER"                           # whatever the producer / candidate carries

# ---- commission_conversion (account currency per lot per side -> cost unit) ----------------------------------------------------
CONV_MONEY = "MONEY_PER_LOT"                           # 2 x commission (account money per 1 lot) - ACTIVE
CONV_TICK_VALUE = "TICK_VALUE_PER_TICK_SIZE"           # 2 x com / (tick_value / tick_size); not convertible -> 0 (evaluation)
CONV_MONEY_PER_PRICE = "MONEY_PER_PRICE"               # 2 x com / spec.money_per_price(1.0), given only when tick_value > 0 (SH)
CONV_MAX_CONTRACT_TICK = "MAX_CONTRACT_SIZE_OR_TICK_VALUE"  # 2 x max(com / contract size, com / money per price) (scalp, I0738)
CONV_CONTRACT_SIZE = "CONTRACT_SIZE"                   # 2 x com / contract size (scalp: the cost before 1.46 arch, 2nd gate check)
CONV_NONE = "NONE"                                     # nothing to convert: the producer's cost is already in the cost unit

# ---- slippage_unit ---------------------------------------------------------------------------------------------------------------
SLIP_POINTS_BROKER = "POINTS_BROKER_CALC"  # slippage_stress_points x point valued by the broker calculator, x 2 sides (ACTIVE)
SLIP_POINTS = "POINTS"                     # slippage_stress_points x point x 2 (price units) (evaluation ACTIVE)
SLIP_PRICE = "PRICE"                       # slippage_usd (a price move) x 2 (SH)
SLIP_TICKS = "TICKS"                       # slippage_ticks x tick size x 2 (scalp)
SLIP_NONE = "NONE"                         # the producer's cost already holds it

# ---- sizing_commission -----------------------------------------------------------------------------------------------------------
SIZING_ONCE = "ONCE"                                   # the sizing loss holds the commission once (ACTIVE, scalp)
SIZING_TWICE = "IN_ROUND_TRIP_AND_AGAIN_IN_MONEY"      # SH: in round_trip_price AND + 2 x commission per lot (D2 - unchanged)
SIZING_NOT_APPLICABLE = "NOT_APPLICABLE"               # the track does not size (SHADOW evaluation, labels)

# ---- cost_unit -------------------------------------------------------------------------------------------------------------------
UNIT_MONEY_PER_LOT = "ACCOUNT_MONEY_PER_LOT"
UNIT_PRICE = "PRICE_PER_UNIT_VOLUME"


@dataclass(frozen=True)
class CostPolicy:
    """Today's cost policy of one track (no instrument-specific policy exists today)."""
    spread_policy: str
    unknown_commission_policy: str
    unknown_slippage_policy: str
    commission_source: str
    commission_conversion: str
    slippage_unit: str
    sizing_commission: str
    cost_unit: str
    known_requires_conversion: bool          # commission_known = known AND convertible (evaluation) vs known as configured (SH quirk)
    where: str                               # the code that applies the policy
    decisions: tuple[str, ...] = ()          # owner decisions that would change it (not implemented here)
    gate_check_conversion: str | None = None  # a second commission conversion the track's gate ALSO requires (scalp: before 1.46 arch)


@dataclass(frozen=True)
class CostProfile:
    """CostProfile(tor, instrument): the policy of `track` bound to an instrument (informational - the policy is per track today)."""
    track: str
    instrument: str | None
    spread_policy: str
    unknown_commission_policy: str
    unknown_slippage_policy: str
    commission_source: str
    commission_conversion: str
    slippage_unit: str
    sizing_commission: str
    cost_unit: str
    known_requires_conversion: bool
    where: str
    decisions: tuple[str, ...] = ()
    gate_check_conversion: str | None = None
    schema: str = SCHEMA


POLICIES: dict[str, CostPolicy] = {
    ACTIVE: CostPolicy(
        spread_policy=SPREAD_IN_FILL, unknown_commission_policy=UNKNOWN_REASON_CODE, unknown_slippage_policy=SLIP_UNKNOWN_REASON_CODE,
        commission_source=SOURCE_COSTS_CONFIG, commission_conversion=CONV_MONEY, slippage_unit=SLIP_POINTS_BROKER,
        sizing_commission=SIZING_ONCE, cost_unit=UNIT_MONEY_PER_LOT, known_requires_conversion=False,
        where="risk/engine.evaluate (COST_STRESS = 2 x commission + slippage stress per 1 lot) via risk/costs.active_cost_per_lot",
        decisions=("D3",)),
    EVALUATION_ACTIVE: CostPolicy(
        spread_policy=SPREAD_IN_FILL, unknown_commission_policy=UNKNOWN_FLAG, unknown_slippage_policy=SLIP_UNKNOWN_ZERO,
        commission_source=SOURCE_COSTS_CONFIG, commission_conversion=CONV_TICK_VALUE, slippage_unit=SLIP_POINTS,
        sizing_commission=SIZING_NOT_APPLICABLE, cost_unit=UNIT_PRICE, known_requires_conversion=True,
        where="evaluation/service._active_cost (commission both sides + slippage stress in price units for 1 lot)",
        decisions=("D3",)),
    SH: CostPolicy(
        spread_policy=SPREAD_AS_COST, unknown_commission_policy=UNKNOWN_WARNING, unknown_slippage_policy=SLIP_UNKNOWN_ZERO,
        commission_source=SOURCE_SH_PROFILE, commission_conversion=CONV_MONEY_PER_PRICE, slippage_unit=SLIP_PRICE,
        sizing_commission=SIZING_TWICE, cost_unit=UNIT_PRICE, known_requires_conversion=False,
        where="sh/setup.evaluate step 7 (round_trip_price, net RR, BE offset) and sh/risk.evaluate sizing (loss per lot)",
        decisions=("O7", "D2", "D3")),
    EVALUATION_SH: CostPolicy(
        spread_policy=SPREAD_REMOVED, unknown_commission_policy=UNKNOWN_INHERITED, unknown_slippage_policy=SLIP_UNKNOWN_NOT_APPLICABLE,
        commission_source=SOURCE_PRODUCER, commission_conversion=CONV_NONE, slippage_unit=SLIP_NONE,
        sizing_commission=SIZING_NOT_APPLICABLE, cost_unit=UNIT_PRICE, known_requires_conversion=False,
        where="evaluation/service._sh (extra = max(0, SH round_trip_price - spread))",
        decisions=("D3",)),
    SCALP: CostPolicy(
        spread_policy=SPREAD_IN_FILL, unknown_commission_policy=UNKNOWN_GATE_BLOCKS, unknown_slippage_policy=SLIP_UNKNOWN_NOT_APPLICABLE,
        commission_source=SOURCE_SCALP_CONFIG, commission_conversion=CONV_MAX_CONTRACT_TICK, slippage_unit=SLIP_TICKS,
        sizing_commission=SIZING_ONCE, cost_unit=UNIT_PRICE, known_requires_conversion=False,
        where="scalp/strategy.cost_extra -> scalp/service.economics_gate / commission_price (economics cost_extra; "
              "the cost/TP1 ratio of scalp/strategy.economics adds the spread to the extra cost; the gate also requires the "
              "economics at the cost before 1.46 arch = commission / contract size)",
        decisions=("D3",), gate_check_conversion=CONV_CONTRACT_SIZE),
    QUANT_LABEL: CostPolicy(
        spread_policy=SPREAD_INHERITED, unknown_commission_policy=UNKNOWN_NO_LABEL, unknown_slippage_policy=SLIP_UNKNOWN_NOT_APPLICABLE,
        commission_source=SOURCE_PRODUCER, commission_conversion=CONV_NONE, slippage_unit=SLIP_NONE,
        sizing_commission=SIZING_NOT_APPLICABLE, cost_unit=UNIT_PRICE, known_requires_conversion=False,
        where="quant/events.spec_from_candidate (EventSpec.cost_price and the BE offset of the label simulation)",
        decisions=("D3",)),
}

TRACKS: tuple[str, ...] = tuple(POLICIES)


@lru_cache(maxsize=512)
def profile(track: str, instrument: str | None = None) -> CostProfile:
    """The declared (today's) cost profile of `track` for `instrument`. An undeclared track raises KeyError (never a default policy)."""
    try:
        pol = POLICIES[track]
    except KeyError:
        raise KeyError(f"COST_TRACK_NOT_DECLARED:{track}") from None
    return CostProfile(track=track, instrument=instrument, **asdict(pol))


def policies() -> list[dict]:
    """Read-only listing of the declared policies (documentation / diagnostics)."""
    return [{"track": t, "schema": SCHEMA, **asdict(p)} for t, p in POLICIES.items()]
