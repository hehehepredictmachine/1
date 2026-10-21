"""Instrument units for SCALPING / HEDGING.

Targets are ABSOLUTE PRICE MOVES of an instrument quoted in USD (e.g. TP1 = 2.50 USD from the actual fill price): not a percent,
not MT5 points, not account profit. A symbol quoted in another currency is refused unless the profile declares an explicit
unit conversion. Prices are snapped to the tick grid; the snapped distance is reported next to the requested one.
Volumes respect volume_min / volume_step / volume_max; a split that cannot give every leg a valid volume is reported, never
silently rescaled."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

EPS = 1e-9


class UnitError(ValueError):
    pass


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    tick_size: float
    tick_value: float                     # account-currency value of one tick for 1 lot (from the terminal)
    contract_size: float
    volume_min: float
    volume_step: float
    volume_max: float
    digits: int
    currency_profit: str
    currency_base: str = ""
    stops_level_points: int = 0
    point: float = 0.0
    margin_mode: str = "UNKNOWN"          # HEDGING / NETTING / EXCHANGE / UNKNOWN (account level)
    source: str = "TERMINAL"              # TERMINAL / PROFILE / TEST

    @classmethod
    def from_mt5(cls, info: dict, account: dict | None = None, source: str = "TERMINAL") -> "SymbolSpec":
        mm = (account or {}).get("margin_mode")
        mode = {0: "NETTING", 1: "EXCHANGE", 2: "HEDGING"}.get(mm, "UNKNOWN") if mm is not None else "UNKNOWN"
        tick = float(info.get("trade_tick_size") or info.get("point") or 0)
        if tick <= 0:
            raise UnitError("TICK_SIZE_INVALID")
        return cls(symbol=str(info.get("name") or ""), tick_size=tick, tick_value=float(info.get("trade_tick_value") or 0),
                   contract_size=float(info.get("trade_contract_size") or 0), volume_min=float(info.get("volume_min") or 0),
                   volume_step=float(info.get("volume_step") or 0), volume_max=float(info.get("volume_max") or 0),
                   digits=int(info.get("digits") or 2), currency_profit=str(info.get("currency_profit") or "").upper(),
                   currency_base=str(info.get("currency_base") or "").upper(), stops_level_points=int(info.get("trade_stops_level") or 0),
                   point=float(info.get("point") or tick), margin_mode=mode, source=source)

    def check_usd(self, conversion: float | None = None) -> None:
        """Targets are USD price moves; another quote currency needs an explicit, configured conversion."""
        if self.currency_profit not in ("USD",) and conversion is None:
            raise UnitError(f"QUOTE_CURRENCY_{self.currency_profit or 'UNKNOWN'}_NEEDS_EXPLICIT_UNIT_CONVERSION")

    # ------------------------------------------------------------------ prices
    def ticks(self, price: float) -> float:
        return price / self.tick_size

    def snap(self, price: float, mode: str = "nearest") -> float:
        q = price / self.tick_size
        n = math.floor(q + EPS) if mode == "down" else math.ceil(q - EPS) if mode == "up" else math.floor(q + 0.5)
        return round(n * self.tick_size, max(self.digits, 0))

    def target(self, entry: float, side: str, distance_usd: float, *, conservative: bool = True) -> dict:
        """TP at entry +/- distance on the tick grid. conservative=True never places a target CLOSER than requested
        (BUY rounds up, SELL rounds down); the difference is reported."""
        if side not in ("BUY", "SELL"):
            raise UnitError("SIDE_INVALID")
        raw = entry + distance_usd if side == "BUY" else entry - distance_usd
        mode = ("up" if side == "BUY" else "down") if conservative else "nearest"
        px = self.snap(raw, mode)
        return {"price": px, "requested_distance": distance_usd, "actual_distance": round(abs(px - entry), 10),
                "rounding_diff": round(abs(px - entry) - distance_usd, 10), "unit": "USD_PRICE_MOVE"}

    def stop(self, entry: float, side: str, distance_usd: float) -> float:
        """SL never closer than requested (BUY rounds down, SELL rounds up)."""
        raw = entry - distance_usd if side == "BUY" else entry + distance_usd
        return self.snap(raw, "down" if side == "BUY" else "up")

    def stops_level_ok(self, price: float, ref: float) -> bool:
        return self.stops_level_points <= 0 or abs(price - ref) >= self.stops_level_points * (self.point or self.tick_size) - EPS

    # ------------------------------------------------------------------ money
    def money_per_price(self, volume: float) -> float:
        """Account-currency P/L for a 1.0 price move with `volume` lots (tick_value / tick_size)."""
        if self.tick_value <= 0:
            raise UnitError("TICK_VALUE_UNKNOWN")
        return volume * self.tick_value / self.tick_size

    # ------------------------------------------------------------------ volumes
    def floor_volume(self, v: float) -> float:
        if self.volume_step <= 0:
            raise UnitError("VOLUME_STEP_INVALID")
        n = math.floor(v / self.volume_step + EPS)
        dec = max(0, -int(math.floor(math.log10(self.volume_step))) if self.volume_step < 1 else 0)
        return round(n * self.volume_step, dec + 2)

    def volume_ok(self, v: float) -> bool:
        if v < self.volume_min - EPS or (self.volume_max and v > self.volume_max + EPS):
            return False
        k = v / self.volume_step
        return abs(k - round(k)) < 1e-6

    def split(self, total: float, shares: list[float]) -> dict:
        """Partial-close volumes for shares summing to 1.0. Every leg >= volume_min and on the step grid; rounding residue
        goes to the LAST leg (the runner), so the legs always sum to the total. Infeasible -> status + reason, no rescale."""
        if abs(sum(shares) - 1.0) > 1e-6 or any(s <= 0 for s in shares):
            return {"status": "INVALID_SHARES", "reason": "udziały muszą być dodatnie i sumować się do 100 %"}
        if not self.volume_ok(total):
            return {"status": "INVALID_TOTAL", "reason": f"wolumen {total} poza siatką/limitem (min {self.volume_min}, krok {self.volume_step})"}
        legs = [self.floor_volume(total * s) for s in shares[:-1]]
        legs.append(round(total - sum(legs), 8))                # residue to the runner; total and legs are on the grid
        bad = [i for i, v in enumerate(legs) if v < self.volume_min - EPS]
        if bad or abs(sum(legs) - total) > 1e-6:
            return {"status": "INFEASIBLE", "legs": legs,
                    "reason": f"przy wolumenie {total} i min. lot {self.volume_min} (krok {self.volume_step}) nie każda część osiąga minimum"}
        return {"status": "OK", "legs": legs}


@dataclass
class Costs:
    """Per-instrument cost model in PRICE units (USD per unit of price) - measured, never assumed zero because of an account
    name. commission_per_lot_side is in account currency."""
    spread_price: float
    commission_per_lot_side: float | None
    slippage_price: float = 0.0
    swap_per_lot_day: float | None = None
    source: dict = field(default_factory=dict)

    def round_trip_price(self, spec: SymbolSpec, volume: float = 1.0) -> float | None:
        """Total round-trip cost expressed as a PRICE move (spread + 2x slippage + 2x commission converted)."""
        if self.commission_per_lot_side is None:
            return None
        mpp = spec.money_per_price(volume)
        return self.spread_price + 2 * self.slippage_price + (2 * self.commission_per_lot_side * volume / mpp if mpp else 0.0)
