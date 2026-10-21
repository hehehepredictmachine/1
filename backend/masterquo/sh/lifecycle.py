"""Position life cycle of one SCALPING / HEDGING primary position: partial targets, breakeven, runner, exits.

Pure logic (no I/O): feed it events, it returns ACTIONS. The executor performs actions and feeds back confirmations.
* Targets are crossed on the executable side of the quote (BUY closes at Bid, SELL closes at Ask) - a chart touch of the mid
  or of the other side is not a fill.
* A partial is DONE only after a confirmed fill event (deal) - requesting it is not enough.
* Breakeven of the remaining volume is requested only after the CONFIRMED fill of TP2's partial; a rejected SL modification
  is retried, and if the price is already beyond the BE level the remainder is closed (configurable) - the plan never widens SL.
* Every action has a deterministic id (plan_id:kind:leg): repeating an event can never open/close twice.
* A gap that jumps over several targets produces the pending partials in order (TP1 then TP2), each once.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

STATES = ("PENDING_ENTRY", "OPEN", "TP1_DONE", "TP2_DONE", "CLOSED", "ERROR")


@dataclass
class Leg:
    name: str                 # TP1 / TP2 / TP3
    price: float
    volume: float             # volume closed at this target (TP3 = runner, closed by the broker TP or the bot)
    status: str = "PENDING"   # PENDING / REQUESTED / DONE / SKIPPED
    fill_price: float | None = None
    fill_volume: float = 0.0
    deal_id: str | None = None


@dataclass
class Position:
    plan_id: str
    side: str
    entry: float              # ACTUAL fill price
    volume: float
    sl: float
    legs: list[Leg]
    be_rule: str = "ENTRY"    # ENTRY or ENTRY_PLUS_COSTS
    be_offset: float = 0.0    # price offset added for ENTRY_PLUS_COSTS (round-trip costs / remaining volume)
    be_reject_policy: str = "RETRY_THEN_CLOSE"
    state: str = "OPEN"
    remaining: float = 0.0
    be_status: str = "NOT_REQUESTED"     # NOT_REQUESTED / REQUESTED / SET / REJECTED
    be_attempts: int = 0
    realized: list = field(default_factory=list)
    seen_events: set = field(default_factory=set)
    issued: set = field(default_factory=set)
    log: list = field(default_factory=list)

    def __post_init__(self):
        if not self.remaining:
            self.remaining = self.volume

    # ------------------------------------------------------------------ helpers
    def _sign(self) -> int:
        return 1 if self.side == "BUY" else -1

    def be_price(self) -> float:
        return self.entry + self._sign() * (self.be_offset if self.be_rule == "ENTRY_PLUS_COSTS" else 0.0)

    def _act(self, kind: str, key: str, **kw) -> dict | None:
        aid = f"{self.plan_id}:{kind}:{key}"
        if aid in self.issued:
            return None
        self.issued.add(aid)
        return {"action_id": aid, "kind": kind, "plan_id": self.plan_id, **kw}

    def snapshot(self) -> dict:
        d = copy.deepcopy({k: v for k, v in self.__dict__.items() if k not in ("seen_events", "issued", "log")})
        d["legs"] = [vars(x) for x in self.legs]
        d["be_price"] = self.be_price()
        d["be_definition"] = ("cena wejścia" if self.be_rule == "ENTRY" else "cena wejścia + koszty (BE po kosztach)") + \
            " – stop nie gwarantuje braku straty przy luce lub poślizgu"
        return d

    # ------------------------------------------------------------------ events
    def on_quote(self, bid: float, ask: float) -> list[dict]:
        """Price update: partial-close requests for crossed targets (in order), never more than once per leg."""
        if self.state in ("CLOSED", "ERROR", "PENDING_ENTRY"):
            return []
        px = bid if self.side == "BUY" else ask                      # executable side for closing
        out = []
        for leg in self.legs:
            if leg.status != "PENDING":
                continue
            hit = (px >= leg.price) if self.side == "BUY" else (px <= leg.price)
            if not hit:
                break                                                 # targets are ordered; later ones need earlier ones
            if leg.name == "TP3":
                a = self._act("CLOSE_RUNNER", leg.name, volume=self.remaining, reason="TP3")
            else:
                a = self._act("CLOSE_PARTIAL", leg.name, volume=leg.volume, reason=leg.name)
            if a:
                leg.status = "REQUESTED"
                out.append(a)
        return out

    def on_fill(self, event_id: str, leg_name: str, volume: float, price: float, deal_id: str | None = None) -> list[dict]:
        """Confirmed partial/close fill (from the deal / order result). Idempotent on event_id."""
        if event_id in self.seen_events:
            return []
        self.seen_events.add(event_id)
        leg = next((x for x in self.legs if x.name == leg_name), None)
        if leg is None:
            self.log.append(f"fill for unknown leg {leg_name}")
            return []
        leg.fill_volume += volume
        leg.fill_price = price
        leg.deal_id = deal_id
        self.remaining = round(self.remaining - volume, 8)
        self.realized.append({"leg": leg_name, "volume": volume, "price": price, "move": self._sign() * (price - self.entry)})
        if leg.fill_volume + 1e-9 >= leg.volume or leg_name == "TP3":
            leg.status = "DONE"
        out = []
        if self.remaining <= 1e-9:
            self.state = "CLOSED"
            return out
        if leg_name == "TP1" and leg.status == "DONE":
            self.state = "TP1_DONE"
        if leg_name == "TP2" and leg.status == "DONE":
            self.state = "TP2_DONE"
            self.be_status = "REQUESTED"
            self.be_attempts += 1
            a = self._act("MODIFY_SL", f"BE{self.be_attempts}", sl=self.be_price(), reason="BE_AFTER_CONFIRMED_TP2")
            if a:
                out.append(a)
        return out

    def on_partial_rejected(self, event_id: str, leg_name: str, reason: str) -> list[dict]:
        """A partial close was rejected: the leg returns to PENDING so the next quote retries it (new attempt id)."""
        if event_id in self.seen_events:
            return []
        self.seen_events.add(event_id)
        leg = next((x for x in self.legs if x.name == leg_name), None)
        if leg and leg.status == "REQUESTED":
            leg.status = "PENDING"
            self.issued.discard(f"{self.plan_id}:CLOSE_PARTIAL:{leg_name}")
            self.log.append(f"{leg_name} rejected: {reason}")
        return []

    def on_sl_result(self, event_id: str, ok: bool, bid: float, ask: float, reason: str = "") -> list[dict]:
        """Result of the BE modification. Rejected -> retry once; if the price is already beyond BE (or retries are used up)
        the policy closes the remainder instead of leaving it without the promised protection."""
        if event_id in self.seen_events:
            return []
        self.seen_events.add(event_id)
        if ok:
            self.be_status = "SET"
            self.sl = self.be_price()
            return []
        self.be_status = "REJECTED"
        self.log.append(f"BE rejected: {reason}")
        px = bid if self.side == "BUY" else ask
        beyond = (px <= self.be_price()) if self.side == "BUY" else (px >= self.be_price())
        if beyond or self.be_attempts >= 2 or self.be_reject_policy == "CLOSE":
            a = self._act("CLOSE_RUNNER", "BE_FALLBACK", volume=self.remaining, reason=f"BE_REJECTED:{reason}")
            return [a] if a else []
        self.be_attempts += 1
        a = self._act("MODIFY_SL", f"BE{self.be_attempts}", sl=self.be_price(), reason="BE_RETRY")
        return [a] if a else []

    def on_closed(self, event_id: str, volume: float, price: float, reason: str) -> list[dict]:
        """Position (remainder) closed by the broker (SL / TP3 / stop-out) or by the bot - confirmed."""
        if event_id in self.seen_events:
            return []
        self.seen_events.add(event_id)
        if volume > 0:
            self.realized.append({"leg": reason, "volume": volume, "price": price, "move": self._sign() * (price - self.entry)})
            self.remaining = round(max(0.0, self.remaining - volume), 8)
        for leg in self.legs:
            if leg.status in ("PENDING", "REQUESTED") and self.remaining <= 1e-9:
                leg.status = "DONE" if leg.name == "TP3" and reason == "TP3" else "SKIPPED"
        if self.remaining <= 1e-9:
            self.state = "CLOSED"
        return []

    # ------------------------------------------------------------------ results
    def result(self, money_per_price_per_lot: float | None = None, costs_money: float = 0.0) -> dict:
        """Whole-cycle result (one trade, not three wins): volume-weighted price move and, if the money rate is known,
        net money after costs."""
        closed = sum(r["volume"] for r in self.realized)
        wmove = sum(r["volume"] * r["move"] for r in self.realized) / closed if closed else 0.0
        out = {"closed_volume": closed, "avg_move_price": wmove, "legs": [vars(x) for x in self.legs], "state": self.state}
        if money_per_price_per_lot is not None:
            gross = sum(r["volume"] * r["move"] for r in self.realized) * money_per_price_per_lot
            out.update(gross_money=gross, costs_money=costs_money, net_money=gross - costs_money)
        return out
