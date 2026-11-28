"""Cost policies of the decision tracks (PMW-COSTS-1) - declarations of TODAY's behaviour, nothing switchable.

ETAP2_PROJEKT §4 (row "Koszty"): >= 4 spread conventions, 3 commission sources, 3 slippage units and 4 policies for an unknown
commission lived inside the tracks' code. Etap 4 routed the six decision tracks of §4 (`TRACKS`: ACTIVE, EVALUATION_ACTIVE, SH setup /
sizing, EVALUATION_SH, the SCALP economics gate, QUANT_LABEL): each names its policy here (`POLICIES`) and computes that cost through
`costs.resolver` - the same formulas in the same order of operations as before Etap 4 (bit for bit, proven by
tests/test_arch146_e4_costs.py: the old code vs the resolver on random inputs).

This is NOT yet the one source of truth for every cost of the code: `OUTSIDE_RESOLVER` lists the cost formulas that still compute
their own cost - the replay / outcome arithmetic (scalp, SH, SH pack), the LIVE hedge cost and the execution sizing, the training
labels ML / trainhub / extind named in ETAP2 §5, the panel calculators - each with its own convention, its own treatment of an unknown
commission and the reason it was not moved in Etap 4 (not_done). Moving one is a step of its own: a declared policy here, a resolver
branch and an old-vs-new equality proof.

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
from types import MappingProxyType

SCHEMA = "PMW-COSTS-1"

# ---- tracks (tor) ----------------------------------------------------------------------------------------------------------------
ACTIVE = "ACTIVE"                          # path A risk gate: risk/engine.evaluate via risk/costs.active_cost_per_lot (money / 1 lot)
EVALUATION_ACTIVE = "EVALUATION_ACTIVE"    # evaluation/service._active_cost: cost of an S01-S12 candidate in price units (SHADOW)
SH = "SH"                                  # path B: sh/setup round_trip_price + sh/risk sizing (loss per lot)
EVALUATION_SH = "EVALUATION_SH"            # evaluation/service._sh: extra cost of an SH candidate in price units (SHADOW)
SCALP = "SCALP"                            # scalp economics gate (scalp/strategy.cost_extra, scalp/service.economics_gate); the
                                           # replay / outcome costs dict of scalp is OUTSIDE_RESOLVER
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


# read-only mapping of frozen records: a policy cannot be switched at run time (a change is a code change with its own review)
POLICIES: MappingProxyType[str, CostPolicy] = MappingProxyType({
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
        where="scalp/strategy.cost_extra -> scalp/service.economics_gate / commission_price (economics cost_extra of the live "
              "gate; the cost/TP1 ratio of scalp/strategy.economics adds the spread to the extra cost; the gate also requires the "
              "economics at the cost before 1.46 arch = commission / contract size). NOT the replay / outcome costs dict "
              "(scalp/replay, scalp/service outcome risk) - see OUTSIDE_RESOLVER",
        decisions=("D3",), gate_check_conversion=CONV_CONTRACT_SIZE),
    QUANT_LABEL: CostPolicy(
        spread_policy=SPREAD_INHERITED, unknown_commission_policy=UNKNOWN_NO_LABEL, unknown_slippage_policy=SLIP_UNKNOWN_NOT_APPLICABLE,
        commission_source=SOURCE_PRODUCER, commission_conversion=CONV_NONE, slippage_unit=SLIP_NONE,
        sizing_commission=SIZING_NOT_APPLICABLE, cost_unit=UNIT_PRICE, known_requires_conversion=False,
        where="quant/events.spec_from_candidate (EventSpec.cost_price and the BE offset of the label simulation)",
        decisions=("D3",)),
})

TRACKS: tuple[str, ...] = tuple(POLICIES)      # the decision tracks routed through the resolver in Etap 4 (not every cost site)


# ---- cost formulas outside the resolver (Etap 4 not_done) ---------------------------------------------------------------------
GROUP_REPLAY_OUTCOME = "REPLAY_OUTCOME"       # replay / outcome / validation arithmetic (results, labels of replays, variant choice)
GROUP_LIVE_EXECUTION = "LIVE_EXECUTION"       # LIVE decision / execution paths (Etap 4: LIVE untouched)
GROUP_TRAINING_LABEL = "TRAINING_LABEL"       # training labels with their own versioned cost basis (ETAP2 §5 "etykiety ML/trainhub/extind")
GROUP_PANEL = "PANEL"                         # calculators shown to the user (no decision)


@dataclass(frozen=True)
class CostSite:
    """A cost formula of the code that does NOT go through the resolver: what it computes, its own convention and policy for an unknown
    commission, and why it was not moved in Etap 4. `marker` = a fragment of the formula as it stands in `path` (the test checks it is
    still there, so a site that is moved or changed must update this inventory)."""
    path: str                                # under backend/masterquo
    marker: str
    group: str
    computes: str
    unknown_commission: str
    reason: str


_R_OUTCOME = ("replay / outcome arithmetic on the costs dict already converted per side (commission_price_side, slippage_price) that "
              "walk / pnl / be_offset / the 1.5x stress of scalp/replay share; routing one line would leave the identical lines next to it "
              "outside, and its producers use different conversions (scalp/service._costs: the resolver's commission_price_side; "
              "scalp/cli, extind/trainer: commission / contract size) - the costs dict as a whole is a step of its own")
_R_LABEL = ("a training label cost with its own versioned basis stored with the data (cost_model_version / cost_policy / the replay "
            "costs of the dataset) and its own unknown-commission policy; ETAP2 §4 counted the conventions of the decision tracks - "
            "moving a label basis is a step of its own (resolver branch + equality proof on the label paths, which the golden replay "
            "does not cover)")
_R_LIVE = ("LIVE decision / execution path - Etap 4 leaves LIVE untouched (brief: execution and order paths not changed); the formula "
           "differs from every declared policy, so routing it needs a new resolver branch")
_R_PACK = ("SH pack (path B) plan / replay cost with a convention of its own - spread outside the cost, the unknown commission as a "
           "scenario value (a fifth unknown-commission policy) - not a decision track of ETAP2 §4; the golden replay B covers it, a "
           "resolver branch of its own and the solver, pack replay and CLI move together")
_R_PANEL = "a calculator shown to the user (no trading decision), in account money per volume - not a decision track of ETAP2 §4"

OUTSIDE_RESOLVER: tuple[CostSite, ...] = (
    CostSite("scalp/replay.py", 'extra = 2 * costs.get("commission_price_side", 0.0) + 2 * slip', GROUP_REPLAY_OUTCOME,
             "replay economics extra (2 x commission_price_side + 2 x slippage_price) and the same sum as be_offset, walk / pnl exits, "
             "1.5x cost stress", "whatever the producer of the costs dict put in (0.0 when the key is missing)", _R_OUTCOME),
    CostSite("scalp/service.py", 'abs(fill - plan["sl"]) + 2 * costs["commission_price_side"] + 2 * slip', GROUP_REPLAY_OUTCOME,
             "scalp shadow outcome: risk fallback |fill - SL| + 2 x commission_price_side + 2 x slippage_price, net_R via replay.pnl",
             "computed with commission 0 (`or 0.0` in _costs) and marked cost_status COMMISSION_UNKNOWN (not a training label)",
             _R_OUTCOME),
    CostSite("scalp/cli.py", '"commission_price_side": k * a.commission_per_lot_side / cs', GROUP_REPLAY_OUTCOME,
             "scalp replay CLI costs dict: k x commission / contract size, k x slippage_ticks x tick", "a required CLI argument",
             _R_OUTCOME),
    CostSite("extind/trainer.py", 'costs = {"commission_price_side": com / cs, "slippage_price": 2.0 * tick}', GROUP_TRAINING_LABEL,
             "indicator-context training replay costs: commission / contract size per side, slippage 2 x tick",
             "refused (ValueError COMMISSION_UNKNOWN)", _R_LABEL),
    CostSite("ml/labels.py", "comm = float(per_lot) / float(value_1)", GROUP_TRAINING_LABEL,
             "ML label costs (MQ-COST-1.2.0): spread, slippage_stress_points x point per fill, commission / value of a 1.0 move per "
             "lot per side", "flag COMMISSION_UNKNOWN, commission 0 placeholder, the sample is COST_UNKNOWN (never trained on)", _R_LABEL),
    CostSite("trainhub/pipeline.py", 'comm_status = "USER_ASSUMPTION" if comm is not None else "UNKNOWN_ZERO_USED"',
             GROUP_TRAINING_LABEL, "trainhub package costs (COST_POLICY): 2 x commission / (tick_value / tick_size), slippage points x "
             "point x 2 fills", "0 used and reported UNKNOWN_ZERO_USED (labelled; not convertible -> CONVERSION_UNKNOWN blocker)",
             _R_LABEL),
    CostSite("sh/replay.py", "comm_price = (2 * commission_side / spec.money_per_price(1.0)) if commission_side is not None else 0.0",
             GROUP_REPLAY_OUTCOME, "SH replay simulate_scalp / simulate_hedge: spread of the next bar + 2 x slippage + 2 x commission / "
             "money_per_price(1.0) (its validation file feeds sh/service.validated_variant, which can turn a LIVE HEDGE "
             "into REDUCE / HOLD)",
             "0 with commission_known False (no tick_value > 0 guard, unlike the SH policy)", _R_OUTCOME),
    CostSite("sh/service.py", 'cost = q["spread"] + 2 * float(ic.get("slippage_usd") or 0)', GROUP_LIVE_EXECUTION,
             "SH hedge decision cost: live spread + 2 x slippage_usd (no commission) against the hedge cost cap",
             "not part of the cost", _R_LIVE),
    CostSite("sh/service.py", "comm_money = (2 * float(comm) * (vols + hedge_vol)) if comm is not None else None",
             GROUP_LIVE_EXECUTION, "SH realised result: 2 x commission x (volume + hedge volume) in account money",
             "commission_money None, net result with 0 and commission_known False", _R_LIVE),
    CostSite("sh/pack/solver.py", 'cpx, status = float(common.get("commission_scenario_price_rt", 0.10)), "ESTIMATED_SCENARIO"',
             GROUP_REPLAY_OUTCOME, "SH pack plan cost: 2 x slippage + 2 x commission / money per price, the spread OUTSIDE the cost "
             "(entry at Ask / Bid)", "the scenario commission_scenario_price_rt (default 0.10 price per round trip), ESTIMATED_SCENARIO",
             _R_PACK),
    CostSite("sh/pack/replay.py", "c_rt = 2 * slip + (commission_price_rt if commission_price_rt is not None",
             GROUP_REPLAY_OUTCOME, "SH pack replay round trip: 2 x slippage + commission_price_rt", "the 0.10 scenario (as the solver)",
             _R_PACK),
    CostSite("sh/train_cli.py", "cpx = 2 * a.commission_per_lot_side / (tv / ts)", GROUP_REPLAY_OUTCOME,
             "SH pack-replay CLI: commission_price_rt = 2 x commission / (tick_value / tick_size)",
             "a given commission without tick value is refused; none known -> the scenario of the pack replay", _R_PACK),
    CostSite("sh/scenario.py", "cm_cost = 2 * comm * vol_for_money if comm is not None else None", GROUP_PANEL,
             "SH scenario calculator per level: 2 x slippage x money per price x volume, 2 x commission x volume",
             "no net value (net_account None)", _R_PANEL),
    CostSite("execution/manual.py", "return lp + sc + (2 * com_side * vol if com_side is not None else 0.0)", GROUP_LIVE_EXECUTION,
             "Manual Pad sizing: broker loss at SL + broker value of slippage + 2 x commission x volume (account money)",
             "reason COMMISSION_UNKNOWN, 0 in the sizing, net risk None", _R_LIVE),
    CostSite("execution/paper.py", "return None if c is None else round(c * vol, 2)", GROUP_LIVE_EXECUTION,
             "PAPER commission per side = commission per lot x volume (account money, 2 decimals)", "None (never assumed 0)", _R_LIVE),
    CostSite("lab/edge.py", "comm = 2 * commission_per_lot_side * lots", GROUP_PANEL,
             "lab edge calculator: 2 x commission x lots (account money), contract-size P&L", "a required finite input", _R_PANEL),
    CostSite("strategies/ema_pullback_backtest.py", "pos.costs += fill * qty * m.commission_pct / 100.0", GROUP_PANEL,
             "research backtest of the EMA pullback strategy: commission_pct of the traded value per side, no spread",
             "a fixed percentage (PINE_DEFAULT)", _R_PANEL),
)


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
