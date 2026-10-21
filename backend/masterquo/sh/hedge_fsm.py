"""HEDGING basket state machine: one PRIMARY position (with its TP1/TP2/TP3 life cycle) and at most one bounded HEDGE leg on
the same instrument. Pure logic: events in, actions out; the executor confirms or rejects every action.

States: IDLE -> PRIMARY_OPEN -> HEDGE_PENDING -> HEDGED -> UNWINDING -> PRIMARY_OPEN ... -> EXIT_PENDING -> CLOSED, ERROR.
* A hedge is requested only on a defined market event (adverse excursion >= trigger, structure not invalidated) AND after the
  decision rule says hedging is better than reducing/closing AND risk checks pass (ratio cap, max activations, margin, basket
  loss budget). No martingale: the hedge volume is a bounded fraction of the CURRENT primary volume, never increased after a loss.
* A rejected hedge order returns to PRIMARY_OPEN (never "HEDGED" without a confirmed fill); a partial fill records the real volume.
* After the CONFIRMED TP2 of the primary: BE of the primary remainder AND the hedge is unwound - no lone opposite position.
* Basket exit (all legs) on: basket loss limit, primary SL / invalidation, hedge time limit with the primary still losing,
  time limit of the basket. Results are reported per leg and for the basket (realized / unrealized).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .lifecycle import Position

STATES = ("IDLE", "PRIMARY_OPEN", "HEDGE_PENDING", "HEDGED", "UNWINDING", "EXIT_PENDING", "CLOSED", "ERROR")


@dataclass
class HedgeConfig:
    trigger_adverse_usd: float          # adverse move of the primary (price units) that defines the hedge event
    ratio: float = 0.5                  # hedge volume / current primary volume (0 < ratio <= max_ratio)
    max_ratio: float = 1.0
    max_activations: int = 1
    max_hedge_minutes: float = 60.0
    unwind_recovery_usd: float = 1.0    # unwind when price recovers this much from the hedge entry toward the primary direction
    basket_loss_limit_money: float = 0.0   # 0 = disabled (then only primary SL / time limits apply)
    basket_max_minutes: float = 480.0


@dataclass
class Leg2:
    side: str
    volume: float
    entry: float
    opened_at: float
    realized_money: float = 0.0
    status: str = "OPEN"


@dataclass
class Basket:
    basket_id: str
    primary: Position
    cfg: HedgeConfig
    money_per_price_per_lot: float
    opened_at: float
    state: str = "PRIMARY_OPEN"
    hedge: Leg2 | None = None
    activations: int = 0
    hedge_realized_money: float = 0.0
    seen: set = field(default_factory=set)
    issued: set = field(default_factory=set)
    transitions: list = field(default_factory=list)

    # ------------------------------------------------------------------ helpers
    def _go(self, new: str, why: str, t: float) -> None:
        self.transitions.append({"t": t, "from": self.state, "to": new, "why": why})
        self.state = new

    def _act(self, kind: str, key: str, **kw) -> dict | None:
        aid = f"{self.basket_id}:{kind}:{key}"
        if aid in self.issued:
            return None
        self.issued.add(aid)
        return {"action_id": aid, "kind": kind, "basket_id": self.basket_id, **kw}

    def primary_unrealized(self, bid: float, ask: float) -> float:
        p = self.primary
        px = bid if p.side == "BUY" else ask
        return (px - p.entry) * (1 if p.side == "BUY" else -1) * p.remaining * self.money_per_price_per_lot

    def hedge_unrealized(self, bid: float, ask: float) -> float:
        h = self.hedge
        if not h or h.status != "OPEN":
            return 0.0
        px = bid if h.side == "BUY" else ask
        return (px - h.entry) * (1 if h.side == "BUY" else -1) * h.volume * self.money_per_price_per_lot

    def primary_realized(self) -> float:
        return sum(r["volume"] * r["move"] for r in self.primary.realized) * self.money_per_price_per_lot

    def report(self, bid: float, ask: float, costs_money: float = 0.0) -> dict:
        pu, hu = self.primary_unrealized(bid, ask), self.hedge_unrealized(bid, ask)
        pr, hr = self.primary_realized(), self.hedge_realized_money
        p = self.primary
        protected = "SL_AT_BE" if p.be_status == "SET" else ("SL" if p.sl else "BRAK_SL")
        return {"basket_id": self.basket_id, "state": self.state,
                "primary": {"realized": pr, "unrealized": pu, "remaining": p.remaining, "sl": p.sl, "protection": protected},
                "hedge": {"realized": hr, "unrealized": hu, "volume": self.hedge.volume if self.hedge and self.hedge.status == "OPEN" else 0.0,
                          "activations": self.activations},
                "basket": {"realized": pr + hr, "unrealized": pu + hu, "net_after_costs": pr + hr + pu + hu - costs_money,
                           "gross_exposure_lots": p.remaining + (self.hedge.volume if self.hedge and self.hedge.status == "OPEN" else 0.0),
                           "net_exposure_lots": (p.remaining if p.side == "BUY" else -p.remaining)
                           + ((self.hedge.volume if self.hedge.side == "BUY" else -self.hedge.volume) if self.hedge and self.hedge.status == "OPEN" else 0.0)},
                "note": "SL pozycji głównej na BE nie oznacza, że koszyk jest zabezpieczony na zero (koszty, luka, noga hedge)",
                "transitions": self.transitions[-20:]}

    # ------------------------------------------------------------------ decision rule
    def hedge_decision(self, bid: float, ask: float, *, structure_valid: bool, risk_ok: bool, risk_reason: str,
                       hedge_cost_price: float, reduce_cost_price: float) -> dict:
        """Event + justification: hedge only if the primary is in adverse excursion >= trigger, its structure is still valid
        (otherwise the right answer is to exit, not to hedge), the hedge costs less than reducing, activations remain and risk
        allows. Returns the decision with reasons (HOLD / HEDGE / REDUCE / EXIT)."""
        p = self.primary
        px = bid if p.side == "BUY" else ask
        adverse = (p.entry - px) if p.side == "BUY" else (px - p.entry)
        if adverse < self.cfg.trigger_adverse_usd:
            return {"decision": "HOLD", "reason": f"brak zdarzenia: niekorzystny ruch {adverse:.2f} < {self.cfg.trigger_adverse_usd:.2f}"}
        if not structure_valid:
            return {"decision": "EXIT", "reason": "struktura setupu unieważniona – zabezpieczanie straty nie ma uzasadnienia"}
        if self.activations >= self.cfg.max_activations:
            return {"decision": "HOLD", "reason": f"wykorzystano limit aktywacji hedge ({self.cfg.max_activations})"}
        if not risk_ok:
            return {"decision": "REDUCE", "reason": f"kontrola ryzyka nie pozwala na hedge: {risk_reason}"}
        if hedge_cost_price >= reduce_cost_price:
            return {"decision": "REDUCE", "reason": f"koszt hedge {hedge_cost_price:.3f} ≥ koszt redukcji {reduce_cost_price:.3f}"}
        return {"decision": "HEDGE", "reason": f"zdarzenie: niekorzystny ruch {adverse:.2f} ≥ {self.cfg.trigger_adverse_usd:.2f}, struktura ważna, hedge tańszy niż redukcja"}

    def hedge_volume(self, floor_volume) -> float:
        r = min(self.cfg.ratio, self.cfg.max_ratio)
        return floor_volume(self.primary.remaining * r)

    # ------------------------------------------------------------------ events
    def request_hedge(self, t: float, volume: float, why: str) -> list[dict]:
        if self.state != "PRIMARY_OPEN" or volume <= 0:
            return []
        a = self._act("OPEN_HEDGE", f"H{self.activations + 1}", side="SELL" if self.primary.side == "BUY" else "BUY", volume=volume, reason=why)
        if not a:
            return []
        self._go("HEDGE_PENDING", why, t)
        return [a]

    def on_hedge_result(self, event_id: str, t: float, ok: bool, volume: float = 0.0, price: float = 0.0, reason: str = "") -> list[dict]:
        if event_id in self.seen:
            return []
        self.seen.add(event_id)
        if self.state != "HEDGE_PENDING":
            return []
        if not ok or volume <= 0:
            self._go("PRIMARY_OPEN", f"hedge odrzucony: {reason}", t)        # never 'HEDGED' without a confirmed fill
            self.issued.discard(f"{self.basket_id}:OPEN_HEDGE:H{self.activations + 1}")
            self.activations += 1                                         # a failed attempt consumes an activation (no retry storm)
            return []
        self.activations += 1
        self.hedge = Leg2(side="SELL" if self.primary.side == "BUY" else "BUY", volume=volume, entry=price, opened_at=t)
        self._go("HEDGED", f"hedge wykonany {volume} @ {price}" + (" (częściowe wykonanie)" if reason == "PARTIAL" else ""), t)
        return []

    def on_quote(self, t: float, bid: float, ask: float, *, structure_valid: bool = True) -> list[dict]:
        out = []
        if self.state in ("CLOSED", "ERROR", "EXIT_PENDING", "IDLE"):
            return out
        # basket-level exits first (risk has priority over everything)
        total = self.primary_realized() + self.hedge_realized_money + self.primary_unrealized(bid, ask) + self.hedge_unrealized(bid, ask)
        if self.cfg.basket_loss_limit_money and total <= -abs(self.cfg.basket_loss_limit_money):
            return self._exit_all(t, f"limit straty koszyka {total:.2f} ≤ -{abs(self.cfg.basket_loss_limit_money):.2f}")
        if (t - self.opened_at) / 60.0 >= self.cfg.basket_max_minutes:
            return self._exit_all(t, "limit czasu koszyka")
        if not structure_valid and self.state in ("HEDGED", "PRIMARY_OPEN") and self.primary.state not in ("TP2_DONE",):
            return self._exit_all(t, "unieważnienie struktury pozycji głównej")
        # primary partials (TP1/TP2/TP3) on the executable side
        out += self.primary.on_quote(bid, ask)
        if self.state == "HEDGED" and self.hedge:
            h = self.hedge
            px_h_close = ask if h.side == "SELL" else bid
            # rec > 0: the market moved back in the PRIMARY direction since the hedge entry
            rec = (px_h_close - h.entry) if h.side == "SELL" else (h.entry - px_h_close)
            if rec >= self.cfg.unwind_recovery_usd:
                out += self._unwind(t, f"odbicie {rec:.2f} ≥ {self.cfg.unwind_recovery_usd:.2f} – powrót do ekspozycji kierunkowej")
            elif (t - h.opened_at) / 60.0 >= self.cfg.max_hedge_minutes:
                if self.primary_unrealized(bid, ask) < 0:
                    out += self._exit_all(t, "limit czasu hedge przy stratnej pozycji głównej")
                else:
                    out += self._unwind(t, "limit czasu hedge")
        return [a for a in out if a]

    def on_primary_fill(self, event_id: str, t: float, leg: str, volume: float, price: float) -> list[dict]:
        acts = self.primary.on_fill(event_id, leg, volume, price)
        out = list(acts)
        if leg == "TP2" and self.primary.state == "TP2_DONE" and self.hedge and self.hedge.status == "OPEN":
            out += self._unwind(t, "TP2 pozycji głównej potwierdzony – zamknięcie hedge (brak samodzielnej pozycji przeciwnej)")
        if self.primary.state == "CLOSED":
            out += self._close_hedge_if_any(t, "pozycja główna zamknięta")
        return out

    def on_primary_closed(self, event_id: str, t: float, volume: float, price: float, reason: str) -> list[dict]:
        self.primary.on_closed(event_id, volume, price, reason)
        out = []
        if self.primary.state == "CLOSED":
            out += self._close_hedge_if_any(t, f"pozycja główna zamknięta ({reason})")
            if not (self.hedge and self.hedge.status in ("OPEN", "CLOSING")):
                self._go("CLOSED", f"koszyk zamknięty ({reason})", t)
        return out

    def on_hedge_closed(self, event_id: str, t: float, volume: float, price: float, ok: bool = True, reason: str = "") -> list[dict]:
        if event_id in self.seen:
            return []
        self.seen.add(event_id)
        h = self.hedge
        if not h:
            return []
        if not ok:
            # closing the hedge failed: stay in a state that keeps retrying; never report it as closed
            self.issued.discard(f"{self.basket_id}:CLOSE_HEDGE:{self.activations}")
            self._go("ERROR" if self.state == "EXIT_PENDING" else self.state, f"zamknięcie hedge odrzucone: {reason}", t)
            return []
        sign = 1 if h.side == "BUY" else -1
        self.hedge_realized_money += sign * (price - h.entry) * volume * self.money_per_price_per_lot
        h.volume = round(h.volume - volume, 8)
        if h.volume <= 1e-9:
            h.status = "CLOSED"
            if self.primary.state == "CLOSED":
                self._go("CLOSED", "koszyk zamknięty", t)
            elif self.state in ("UNWINDING", "HEDGED"):
                self._go("PRIMARY_OPEN", "hedge zamknięty", t)
        return []

    # ------------------------------------------------------------------ internal transitions
    def _unwind(self, t: float, why: str) -> list[dict]:
        if not self.hedge or self.hedge.status != "OPEN":
            return []
        a = self._act("CLOSE_HEDGE", str(self.activations), volume=self.hedge.volume, reason=why)
        if a:
            self.hedge.status = "CLOSING"
            self._go("UNWINDING", why, t)
        return [a] if a else []

    def _close_hedge_if_any(self, t: float, why: str) -> list[dict]:
        if self.hedge and self.hedge.status == "OPEN":
            return self._unwind(t, why)
        return []

    def _exit_all(self, t: float, why: str) -> list[dict]:
        out = []
        if self.primary.remaining > 1e-9:
            a = self._act("CLOSE_PRIMARY", "EXIT", volume=self.primary.remaining, reason=why)
            if a:
                out.append(a)
        if self.hedge and self.hedge.status == "OPEN":
            a = self._act("CLOSE_HEDGE", str(self.activations), volume=self.hedge.volume, reason=why)
            if a:
                self.hedge.status = "CLOSING"
                out.append(a)
        if out:
            self._go("EXIT_PENDING", why, t)
        return out
