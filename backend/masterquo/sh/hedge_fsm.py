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
* An exit decision is final: EXIT_PENDING never returns to PRIMARY_OPEN / HEDGED. A definitively rejected close of a leg is retried
  (new attempt id, >= EXIT_RETRY_SECONDS apart; the primary only when no close of it is in flight); the hedge leg at most
  HEDGE_CLOSE_MAX_TRIES times, then ERROR (HEDGE_CLOSE_FAILED). A close whose outcome is unknown (CLOSING) is never resent.
* A rejected unwind of a hedge that must close (primary closed / after its TP2) is retried the same way; any other rejected unwind returns
  to HEDGED, where the unwind condition is evaluated again (spaced, bounded).
* A close of the hedge leg that did not complete in one go (definitive rejection, partial fill; not the pack ratio-cap reduction) uses up
  the activation budget: the retries still close the leg, but no new leg is opened afterwards (before 1.46 such a basket stayed UNWINDING /
  ERROR and never hedged again - a retried close must not turn into a second hedge).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .lifecycle import Position

STATES = ("IDLE", "PRIMARY_OPEN", "HEDGE_PENDING", "HEDGED", "UNWINDING", "EXIT_PENDING", "CLOSED", "ERROR")
HEDGE_CLOSE_MAX_TRIES = 5          # rejected closes of the hedge leg (exit / unwind) before giving up (EXIT_PENDING -> ERROR)
EXIT_RETRY_SECONDS = 5.0           # minimum spacing of close retries (no order storm every tick)


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
    policy: dict = field(default_factory=dict)       # 1.38 pack: variant hedge-policy state (MFE, armed flags, intent ids) - persisted
    exit_retries: int = 0          # rejected closes of the hedge leg since the last exit decision / successful close
    exit_round: int = 0            # attempt counter of retried closes (unique action ids)
    last_exit_try: float = 0.0     # time of the last close attempt / rejection (retry spacing)

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
                          "activations": self.activations, "entry": self.hedge.entry if self.hedge else None,
                          "side": self.hedge.side if self.hedge else None, "status": self.hedge.status if self.hedge else None},
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
        if self.hedge and self.hedge.status in ("OPEN", "CLOSING"):
            return []                                                     # never a second leg next to an open / closing one
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

    def on_quote(self, t: float, bid: float, ask: float, *, structure_valid: bool = True, primary_close_ok: bool = False,
                 limits: tuple[float | None, float | None] | None = None) -> list[dict]:
        """primary_close_ok: no close of the primary is in flight (SENT / UNKNOWN) - only then may EXIT_PENDING re-request it.
        limits: (volume_step, volume_min) for the primary's partial closes (see Position.on_quote)."""
        out = []
        if self.state == "EXIT_PENDING":
            return self._exit_retry(t, primary_close_ok)
        if self.state in ("CLOSED", "ERROR", "IDLE"):
            return out
        if self.state == "UNWINDING" and self.hedge and self.hedge.status == "OPEN":
            out += self._retry_unwind(t)                                  # a decided unwind whose close was rejected / partially filled
        # basket-level exits first (risk has priority over everything)
        total = self.primary_realized() + self.hedge_realized_money + self.primary_unrealized(bid, ask) + self.hedge_unrealized(bid, ask)
        if self.cfg.basket_loss_limit_money and total <= -abs(self.cfg.basket_loss_limit_money):
            return out + self._exit_all(t, f"limit straty koszyka {total:.2f} ≤ -{abs(self.cfg.basket_loss_limit_money):.2f}")
        if (t - self.opened_at) / 60.0 >= self.cfg.basket_max_minutes:
            return out + self._exit_all(t, "limit czasu koszyka")
        if not structure_valid and self.state in ("HEDGED", "PRIMARY_OPEN") and self.primary.state not in ("TP2_DONE",):
            return out + self._exit_all(t, "unieważnienie struktury pozycji głównej")
        # primary partials (TP1/TP2/TP3) on the executable side
        out += self.primary.on_quote(bid, ask, limits=limits)
        if self.state == "HEDGED" and self.hedge:
            h = self.hedge
            px_h_close = ask if h.side == "SELL" else bid
            # rec > 0: the market moved back in the PRIMARY direction since the hedge entry
            rec = (px_h_close - h.entry) if h.side == "SELL" else (h.entry - px_h_close)
            if rec >= self.cfg.unwind_recovery_usd:
                out += self._unwind(t, f"odbicie {rec:.2f} ≥ {self.cfg.unwind_recovery_usd:.2f} – powrót do ekspozycji kierunkowej", gated=True)
            elif (t - h.opened_at) / 60.0 >= self.cfg.max_hedge_minutes:
                if self.primary_unrealized(bid, ask) < 0:
                    out += self._exit_all(t, "limit czasu hedge przy stratnej pozycji głównej")
                else:
                    out += self._unwind(t, "limit czasu hedge", gated=True)
        return [a for a in out if a]

    def on_primary_fill(self, event_id: str, t: float, leg: str, volume: float, price: float, *, retry_rest: bool = False,
                        requested: float | None = None) -> list[dict]:
        acts = self.primary.on_fill(event_id, leg, volume, price, retry_rest=retry_rest, requested=requested)
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

    def on_hedge_closed(self, event_id: str, t: float, volume: float, price: float, ok: bool = True, reason: str = "",
                        action_id: str | None = None) -> list[dict]:
        """Confirmed close of (part of) the hedge leg, or its definitive rejection (ok=False). action_id = the action answered: a rejected id
        is released (without it: the unwind / exit id CLOSE_HEDGE:<activations>, as before)."""
        if event_id in self.seen:
            return []
        self.seen.add(event_id)
        h = self.hedge
        if not h:
            return []
        cap = ":CLOSE_HEDGE:CAP" in (action_id or event_id)
        if not ok:
            # closing the hedge failed: never reported as closed; the close is retried (spaced, bounded) - see on_quote
            aid = action_id or f"{self.basket_id}:CLOSE_HEDGE:{self.activations}"
            self.issued.discard(aid)
            if cap:                                                       # ratio-cap reduction (pack): the service retries it, spaced
                n = int(self.policy.get("cap_rejects") or 0) + 1
                self.policy["cap_rejects"], self.policy["cap_last_reject"] = n, t
                self._go(self.state, f"redukcja hedge (limit po częściowym zamknięciu bazy) odrzucona ({n}): {reason}", t)
                return []
            self._no_new_hedge(t, f"zamknięcie nogi hedge odrzucone: {reason}")
            self.exit_retries += 1
            self.last_exit_try = t
            n, mx = self.exit_retries, HEDGE_CLOSE_MAX_TRIES
            if self.state == "EXIT_PENDING":
                if n >= mx:
                    self._go("ERROR", f"HEDGE_CLOSE_FAILED: zamknięcie hedge odrzucone {n} razy: {reason}", t)
                else:
                    self._go("EXIT_PENDING", f"zamknięcie hedge odrzucone ({n}/{mx}) – ponowienie: {reason}", t)
            elif self.state == "UNWINDING" and self.primary.state not in ("CLOSED", "TP2_DONE"):
                self._go("HEDGED", f"odwrócenie hedge odrzucone ({n}/{mx}) – warunek oceniany ponownie: {reason}", t)
            else:
                self._go(self.state, f"zamknięcie hedge odrzucone ({n}/{mx})" + (" – ponowienie" if n < mx else " – bez dalszych prób")
                         + f": {reason}", t)
            return []
        sign = 1 if h.side == "BUY" else -1
        self.hedge_realized_money += sign * (price - h.entry) * volume * self.money_per_price_per_lot
        h.volume = round(h.volume - volume, 8)
        if h.volume > 1e-9 and not cap:
            self._no_new_hedge(t, f"zamknięcie nogi hedge wykonane częściowo ({volume})")
        if h.volume <= 1e-9:
            h.status = "CLOSED"
            self.exit_retries = 0
            if self.primary.state == "CLOSED":
                self._go("CLOSED", "koszyk zamknięty", t)
            elif self.state in ("UNWINDING", "HEDGED"):
                self._go("PRIMARY_OPEN", "hedge zamknięty", t)
        return []

    def on_primary_close_rejected(self, t: float, action_id: str, reason: str = "") -> None:
        """A close of the primary (exit / runner / reduction) was rejected or blocked: its id is released. After an exit decision the
        basket stays EXIT_PENDING (re-requested by on_quote) - it never returns to PRIMARY_OPEN / HEDGED (no new hedge after an exit)."""
        self.issued.discard(action_id)
        self.primary.issued.discard(action_id)
        if self.state == "EXIT_PENDING":
            self.last_exit_try = t
            self._go("EXIT_PENDING", f"zamknięcie pozycji głównej odrzucone – ponowienie: {reason}", t)

    # ------------------------------------------------------------------ internal transitions
    def _no_new_hedge(self, t: float, why: str) -> None:
        """A close of the hedge leg needed a retry: the remaining activations are used up (no second leg after a retried close)."""
        if self.activations < self.cfg.max_activations:
            self.activations = self.cfg.max_activations
            self.transitions.append({"t": t, "from": self.state, "to": self.state,
                                     "why": f"limit aktywacji hedge wykorzystany – bez nowej nogi po ponawianym zamknięciu: {why}"})

    def _close_retry_ok(self, t: float) -> bool:
        """After a rejected close of the hedge: next attempt only EXIT_RETRY_SECONDS later and at most HEDGE_CLOSE_MAX_TRIES in total."""
        return not self.exit_retries or (self.exit_retries < HEDGE_CLOSE_MAX_TRIES and t - self.last_exit_try >= EXIT_RETRY_SECONDS)

    def _close_hedge_act(self, why: str) -> dict | None:
        """Close of the whole (remaining) hedge leg. The id CLOSE_HEDGE:<activations> is reused after a rejection (released); after a
        partial close it is answered DONE, so the rest gets a new attempt id."""
        key = str(self.activations)
        if f"{self.basket_id}:CLOSE_HEDGE:{key}" in self.issued:
            self.exit_round += 1
            key = f"{self.activations}R{self.exit_round}"
        return self._act("CLOSE_HEDGE", key, volume=self.hedge.volume, reason=why)

    def _unwind(self, t: float, why: str, *, gated: bool = False) -> list[dict]:
        """gated = a re-evaluated unwind condition (spacing / limit after a rejected close); event unwinds (TP2, primary closed) are not."""
        if not self.hedge or self.hedge.status != "OPEN":
            return []
        if gated and not self._close_retry_ok(t):
            return []
        a = self._close_hedge_act(why)
        if a:
            self.hedge.status = "CLOSING"
            self._go("UNWINDING", why, t)
        return [a] if a else []

    def _retry_unwind(self, t: float) -> list[dict]:
        if not self._close_retry_ok(t):
            return []
        a = self._close_hedge_act("ponowienie zamknięcia hedge (odwrócenie)")
        if a:
            self.hedge.status = "CLOSING"
            self.last_exit_try = t
        return [a] if a else []

    def _exit_retry(self, t: float, primary_close_ok: bool) -> list[dict]:
        """EXIT_PENDING: re-request what is still open after a rejected / partial close - the primary only when no close of it is in flight
        (primary_close_ok), the hedge only when it is OPEN again (a definitive rejection; CLOSING = outcome unknown, never resent)."""
        if t - self.last_exit_try < EXIT_RETRY_SECONDS:
            return []
        hedge_open = bool(self.hedge and self.hedge.status == "OPEN")
        prim = self.primary.remaining > 1e-9 and primary_close_ok
        if not (hedge_open or prim):
            return []
        self.exit_round += 1
        out = []
        if prim:
            a = self._act("CLOSE_PRIMARY", f"EXIT_R{self.exit_round}", volume=self.primary.remaining, reason="ponowienie wyjścia koszyka")
            if a:
                out.append(a)
        if hedge_open:
            a = self._act("CLOSE_HEDGE", f"{self.activations}R{self.exit_round}", volume=self.hedge.volume, reason="ponowienie wyjścia koszyka")
            if a:
                self.hedge.status = "CLOSING"
                out.append(a)
        if out:
            self.last_exit_try = t
        return out

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
            a = self._close_hedge_act(why)
            if a:
                self.hedge.status = "CLOSING"
                out.append(a)
        if out:
            if self.state != "EXIT_PENDING":
                self.exit_retries = 0                                     # a new exit decision: its own retry budget
            self.last_exit_try = t
            self._go("EXIT_PENDING", why, t)
        return out
