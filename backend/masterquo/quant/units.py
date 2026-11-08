"""Units, costs and expected value (PMW-QUANT-UNITS-1).

Price units come from the broker specification (MT5 symbol_info: point, trade_tick_size, trade_tick_value, trade_contract_size,
volume_min/step/max). A "pip" exists only when the specification defines it (`pip_size`); nothing assumes a fixed XAUUSD pip value.
A 2.5 USD price move is not 2.5 USD of account P/L: money = price_move / tick_size * tick_value * lots, and only when tick_value is in
the account currency (`tick_value_ccy`) - otherwise the money figure is unavailable.

Costs carry their basis (`cost_basis`):
* spread_in_prices=True  - entry/exit prices are on the executable side (bid/ask), the spread is already inside the distances and is
                           NOT subtracted again;
* commission per lot per side (known / unknown), slippage in ticks per fill, swap / financing (known / unknown);
* a cost that is unknown makes the net result SCENARIO (named assumption) or unavailable - never NET_VALIDATED.
R is defined ONCE from the initial plan risk |entry - SL| (executable side) and is never redefined after a move of SL to BE.

EV
  binary plan (one target, no partials / BE / timeout):  EV = p * G - (1 - p) * L ;  p* = L / (G + L)   (G, L > 0, net, in R)
  disjoint complete scenarios:                            EV = sum_k P_k * E[net R | k]   (probabilities must sum to 1 within 1e-6)
P(TP2 before SL) alone is not a payoff distribution of a partial-exit plan: such an EV is refused (EV_NEEDS_SCENARIOS).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

VERSION = "PMW-QUANT-UNITS-1"


class UnitsError(ValueError):
    pass


def _fin(x, what) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise UnitsError(f"NOT_FINITE:{what}")
    return float(x)


@dataclass
class InstrumentSpec:
    symbol: str
    point: float
    tick_size: float
    tick_value: float | None = None          # account currency per tick per 1 lot
    tick_value_ccy: str | None = None
    contract_size: float | None = None
    volume_min: float | None = None
    volume_step: float | None = None
    volume_max: float | None = None
    pip_size: float | None = None            # explicit definition of the UI "pip" (None = no pip unit)
    source: str = "UNKNOWN"                  # MT5_SYMBOL_INFO | CONFIG | TEST

    @classmethod
    def from_mt5(cls, symbol: str, info: dict, *, account_ccy: str | None = None, pip_size: float | None = None) -> "InstrumentSpec":
        pt = float(info.get("point") or 0)
        ts = float(info.get("trade_tick_size") or pt or 0)
        if not (pt > 0 and ts > 0):
            raise UnitsError("SPEC_POINT_OR_TICK_MISSING")
        tv = info.get("trade_tick_value")
        return cls(symbol=symbol, point=pt, tick_size=ts, tick_value=float(tv) if tv else None,
                   tick_value_ccy=account_ccy if tv else None, contract_size=info.get("trade_contract_size"), volume_min=info.get("volume_min"),
                   volume_step=info.get("volume_step"), volume_max=info.get("volume_max"), pip_size=pip_size, source="MT5_SYMBOL_INFO")

    def quantize_price(self, price: float, mode: str = "nearest") -> float:
        p = _fin(price, "price") / self.tick_size
        q = {"nearest": round(p), "down": math.floor(p + 1e-9), "up": math.ceil(p - 1e-9)}[mode]
        return round(q * self.tick_size, 10)

    def quantize_volume(self, lots: float) -> float | None:
        """Down to the broker step; None when below volume_min (never rounded up into more risk)."""
        if not self.volume_step:
            raise UnitsError("VOLUME_STEP_UNKNOWN")
        v = math.floor(_fin(lots, "lots") / self.volume_step + 1e-9) * self.volume_step
        v = round(v, 8)
        if self.volume_min and v < self.volume_min - 1e-12:
            return None
        if self.volume_max:
            v = min(v, self.volume_max)
        return v

    def points(self, price_move: float) -> float:
        return _fin(price_move, "move") / self.point

    def pips(self, price_move: float) -> float:
        if not self.pip_size:
            raise UnitsError("PIP_UNDEFINED_IN_SPEC")
        return _fin(price_move, "move") / self.pip_size

    def money(self, price_move: float, lots: float, account_ccy: str | None = None) -> float:
        if self.tick_value is None:
            raise UnitsError("TICK_VALUE_UNKNOWN")
        if account_ccy and self.tick_value_ccy and account_ccy != self.tick_value_ccy:
            raise UnitsError("CURRENCY_CONVERSION_UNKNOWN")
        return _fin(price_move, "move") / self.tick_size * self.tick_value * _fin(lots, "lots")


@dataclass
class CostModel:
    spread_in_prices: bool = True            # executable-side prices: spread already inside the distances
    spread_price: float | None = None        # only used when spread_in_prices is False
    commission_per_lot_side: float | None = None   # account currency; None = unknown
    slippage_ticks_per_fill: float = 0.0
    swap_per_lot_day: float | None = 0.0     # None = unknown
    source: dict = field(default_factory=dict)

    def basis(self) -> dict:
        unknown = [k for k, v in (("commission", self.commission_per_lot_side), ("swap", self.swap_per_lot_day)) if v is None]
        if not self.spread_in_prices and self.spread_price is None:
            unknown.append("spread")
        return {"spread": "IN_PRICES (bid/ask)" if self.spread_in_prices else "SUBTRACTED", "unknown": unknown,
                "status": "KNOWN" if not unknown else "PARTIAL", **asdict(self)}

    def price_cost_per_unit(self, spec: InstrumentSpec, fills: int = 2, lots: float = 1.0) -> dict:
        """Cost in PRICE units per 1 unit of position over `fills` fills (entry + exits), each component named; None if unknown."""
        comp = {"slippage": self.slippage_ticks_per_fill * spec.tick_size * fills}
        comp["spread"] = 0.0 if self.spread_in_prices else (self.spread_price if self.spread_price is not None else None)
        if self.commission_per_lot_side is None:
            comp["commission"] = None
        elif spec.tick_value:
            comp["commission"] = self.commission_per_lot_side * fills / (spec.tick_value / spec.tick_size)   # money/lot -> price/unit
        else:
            comp["commission"] = None
        total = None if any(v is None for v in comp.values()) else sum(comp.values())
        return {"components": comp, "total": total, "known": total is not None, "fills": fills}


def r_value(entry: float, sl: float) -> float:
    r = abs(_fin(entry, "entry") - _fin(sl, "sl"))
    if r <= 0:
        raise UnitsError("R_NOT_POSITIVE")
    return r


def binary_ev(p: float, gain_r: float, loss_r: float) -> dict:
    p, g, l_ = _fin(p, "p"), _fin(gain_r, "G"), _fin(loss_r, "L")
    if not 0 <= p <= 1:
        raise UnitsError("PROBABILITY_OUT_OF_RANGE")
    if g <= 0 or l_ <= 0:
        raise UnitsError("G_AND_L_MUST_BE_POSITIVE")
    return {"ev_r": p * g - (1 - p) * l_, "break_even_p": l_ / (g + l_), "method": "BINARY", "p": p, "G": g, "L": l_}


def scenario_ev(scenarios: list[dict]) -> dict:
    """[{"name", "p", "net_r"}] disjoint and complete -> EV_net; explicit tolerance 1e-6, never renormalised silently."""
    if not scenarios:
        raise UnitsError("NO_SCENARIOS")
    names = [s["name"] for s in scenarios]
    if len(set(names)) != len(names):
        raise UnitsError("SCENARIOS_NOT_DISJOINT")
    tot = sum(_fin(s["p"], f"p[{s['name']}]") for s in scenarios)
    if any(s["p"] < 0 or s["p"] > 1 for s in scenarios):
        raise UnitsError("PROBABILITY_OUT_OF_RANGE")
    if abs(tot - 1.0) > 1e-6:
        raise UnitsError(f"SCENARIOS_NOT_COMPLETE:sum={tot:.6f}")
    ev = sum(s["p"] * _fin(s["net_r"], f"net_r[{s['name']}]") for s in scenarios)
    return {"ev_r": ev, "method": "SCENARIOS", "scenarios": scenarios}


def plan_is_binary(targets: list[dict], be_after: str | None, timeout: bool) -> bool:
    return len(targets) == 1 and not be_after and not timeout


def ev_for_plan(*, p_event: float | None, event_id: str, targets: list[dict], be_after: str | None, timeout: bool, gain_r: float | None,
                loss_r: float | None, cost_known: bool) -> dict:
    """EV only where it is defined: a binary plan whose event is exactly 'the single TP before SL'. Otherwise EV_NEEDS_SCENARIOS."""
    if p_event is None:
        return {"ev_r": None, "status": "NO_PROBABILITY", "reason": "brak skalibrowanego prawdopodobieństwa nazwanego zdarzenia"}
    if not plan_is_binary(targets, be_after, timeout) or event_id != "TP_BEFORE_SL":
        return {"ev_r": None, "status": "EV_NEEDS_SCENARIOS", "reason": "plan z częściowymi wyjściami / BE / timeoutem – P(jednego TP) nie jest "
                "rozkładem wypłat planu; potrzebny rozkład scenariuszy lub model E[net R]"}
    r = binary_ev(p_event, gain_r, loss_r)
    r["status"] = "NET_VALIDATED_COSTS" if cost_known else "SCENARIO_UNKNOWN_COSTS"
    if not cost_known:
        r["reason"] = "koszt nieznany – wynik scenariuszowy (założenie: brak nieznanego składnika), nie NET_VALIDATED"
    return r
