"""EventSpec and the plan simulator / labeler (PMW-QUANT-EVENT-1).

EventSpec (versioned, hashed) names exactly what a probability refers to: instrument, strategy, direction, entry rule and price, SL,
targets with partial weights, BE rule (default: after the CONFIRMED TP2, active from the NEXT bar - the existing SH rule), horizon /
timeout, costs (price units per unit of position, round trip, with their basis) and the policy for an ambiguous bar (TP and SL inside
the same OHLC bar). A change of any of these is a NEW prediction task (new hash, new label version).

Simulation on CLOSED bars after the decision (bars are bid OHLC as delivered by MT5; a SHORT exits on the ask = bid + bar spread when the
spread is known, otherwise the spread is reported unknown):
* gap through the stop at the bar open -> filled at the OPEN (worse than SL), scenario flag GAP; a gap through a target -> filled at the
  target (conservative for a limit order);
* ambiguous bar -> policy fixed BEFORE labelling: SL_FIRST (conservative, default), TP_FIRST, or BOUNDS (label = SL_FIRST, the
  TP_FIRST result kept as the upper bound) - the favourable order is never picked after seeing the outcome;
* R = |entry - SL| at the decision, never redefined after BE; costs are subtracted ONCE for the whole position (partials do not
  multiply them); unknown costs -> gross R only, net R None;
* window shorter than the horizon (bars not yet closed) -> mature=False: not a loss, not a timeout.
Outcome scenarios are disjoint and complete: TP{k}_{SL|BE|TIMEOUT|ALL} (k = number of targets filled before the remainder ended).
Event flags: TP{k}_BEFORE_STOP for every k, SL_FIRST, TIMEOUT, NET_R_POSITIVE.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

VERSION = "PMW-QUANT-EVENT-1"
LABEL_VERSION = "QEV1"
AMBIGUITY = ("SL_FIRST", "TP_FIRST", "BOUNDS")


class EventError(ValueError):
    pass


@dataclass(frozen=True)
class EventSpec:
    instrument: str
    strategy: str
    direction: str                      # LONG | SHORT
    entry: float
    sl: float
    targets: tuple                      # ((price, weight), ...) in execution order, weights sum to 1
    horizon_s: float
    entry_rule: str = "MARKET_ON_CONFIRMATION"
    be_after: str | None = "TP2"        # None | TP1 | TP2 ...
    be_offset_price: float = 0.0        # BE price = entry +/- offset (costs), toward profit
    cost_price: float | None = None     # round-trip cost per unit in price units (commission + slippage), None = unknown
    spread_in_prices: bool = True
    ambiguity: str = "SL_FIRST"
    timeout_rule: str = "CLOSE_AT_LAST_CLOSE"
    event_id: str = "TP2_BEFORE_STOP"   # the binary event the probability head is trained on
    label_version: str = LABEL_VERSION
    meta: dict = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self):
        if self.direction not in ("LONG", "SHORT"):
            raise EventError("DIRECTION_INVALID")
        if self.ambiguity not in AMBIGUITY:
            raise EventError("AMBIGUITY_POLICY_INVALID")
        if not self.targets:
            raise EventError("NO_TARGETS")
        w = sum(float(t[1]) for t in self.targets)
        if abs(w - 1.0) > 1e-6:
            raise EventError(f"TARGET_WEIGHTS_SUM:{w:.6f}")
        sgn = 1 if self.direction == "LONG" else -1
        if sgn * (self.entry - self.sl) <= 0:
            raise EventError("SL_ON_WRONG_SIDE")
        for p, _ in self.targets:
            if sgn * (float(p) - self.entry) <= 0:
                raise EventError("TARGET_ON_WRONG_SIDE")
        if self.horizon_s <= 0:
            raise EventError("HORIZON_INVALID")

    @property
    def R(self) -> float:
        return abs(self.entry - self.sl)

    def task_dict(self) -> dict:
        """The definition of the prediction TASK (prices relative to entry in R, so the same plan shape on another price is the same task)."""
        R = self.R
        sgn = 1 if self.direction == "LONG" else -1
        return {"instrument": self.instrument, "strategy": self.strategy, "entry_rule": self.entry_rule,
                "targets_r": [round(sgn * (float(p) - self.entry) / R, 4) for p, _ in self.targets], "weights": [round(float(w), 4) for _, w in self.targets],
                "be_after": self.be_after, "horizon_s": float(self.horizon_s), "ambiguity": self.ambiguity, "timeout_rule": self.timeout_rule,
                "event_id": self.event_id, "label_version": self.label_version, "spread_in_prices": self.spread_in_prices}

    def task_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.task_dict(), sort_keys=True).encode()).hexdigest()[:16]

    def plan_hash(self) -> str:
        d = {**self.task_dict(), "direction": self.direction, "entry": self.entry, "sl": self.sl, "targets": [list(map(float, t)) for t in self.targets],
             "cost_price": self.cost_price, "be_offset_price": self.be_offset_price}
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["targets"] = [list(map(float, t)) for t in self.targets]
        d["task_hash"], d["plan_hash"] = self.task_hash(), self.plan_hash()
        return d


def _exit_side(bar: dict, direction: str) -> tuple[float, float, float, float, bool]:
    """(o, h, l, c) on the side the position EXITS: LONG sells at bid (bar prices), SHORT buys at ask = bid + spread."""
    o, h, l_, c = (float(bar[k]) for k in ("o", "h", "l", "c"))
    if direction == "LONG":
        return o, h, l_, c, True
    sp = bar.get("spread_price")
    if sp is None:
        return o, h, l_, c, False
    sp = float(sp)
    return o + sp, h + sp, l_ + sp, c + sp, True


def simulate(spec: EventSpec, bars: list[dict], decision_ts: float, *, tf_s: float = 60.0, available_until: float | None = None,
             _policy: str | None = None) -> dict:
    """bars: closed bars [{t (open UTC s), o, h, l, c, spread_price?}] in time order. Uses only bars that OPEN at/after the decision.
    available_until: close time of the newest closed bar known to the caller - when it is past the horizon end the window is complete
    even if the market was closed (session gap); otherwise completeness is judged from the bars themselves."""
    policy = _policy or ("SL_FIRST" if spec.ambiguity == "BOUNDS" else spec.ambiguity)
    sgn = 1 if spec.direction == "LONG" else -1
    R, end_ts = spec.R, decision_ts + spec.horizon_s
    win = [b for b in bars if float(b["t"]) >= decision_ts - 1e-9 and float(b["t"]) + tf_s <= end_ts + 1e-9]
    complete = (available_until is not None and available_until >= end_ts) or (bool(win) and float(win[-1]["t"]) + tf_s >= end_ts - tf_s + 1e-9)
    targets = [(float(p), float(w)) for p, w in spec.targets]
    rem, k, realized, sl_cur, be_pending = 1.0, 0, 0.0, spec.sl, False
    fills, ambiguous, gap, spread_known = [], False, False, True
    mfe = mae = 0.0
    end_how = None
    for b in win:
        if be_pending:                                                   # BE active from the NEXT bar after the confirmed fill
            sl_cur, be_pending = spec.entry + sgn * spec.be_offset_price, False
        o, h, l_, c, ok = _exit_side(b, spec.direction)
        spread_known &= ok
        fav, adv = (h, l_) if sgn > 0 else (l_, h)
        mfe, mae = max(mfe, sgn * (fav - spec.entry) / R), max(mae, -sgn * (adv - spec.entry) / R)
        if sgn * (o - sl_cur) <= 0:                                       # gap through the stop at the open
            realized += rem * sgn * (o - spec.entry)
            fills.append({"t": b["t"], "kind": "STOP_GAP", "price": o, "w": rem})
            gap, rem, end_how = True, 0.0, ("BE" if sl_cur != spec.sl else "SL")
            break
        stop_hit = sgn * (adv - sl_cur) <= 0
        hits = []
        for j in range(k, len(targets)):
            if sgn * (fav - targets[j][0]) >= 0:
                hits.append(j)
            else:
                break
        if stop_hit and hits:
            ambiguous = True
        if stop_hit and (not hits or policy == "SL_FIRST"):
            realized += rem * sgn * (sl_cur - spec.entry)
            fills.append({"t": b["t"], "kind": "STOP", "price": sl_cur, "w": rem, "ambiguous": bool(hits)})
            rem, end_how = 0.0, ("BE" if sl_cur != spec.sl else "SL")
            break
        for j in hits:
            p, w = targets[j]
            realized += w * sgn * (p - spec.entry)
            rem -= w
            k = j + 1
            fills.append({"t": b["t"], "kind": f"TP{k}", "price": p, "w": w})
            if spec.be_after == f"TP{k}":
                be_pending = True
        if rem <= 1e-9:
            rem, end_how = 0.0, "ALL"
            break
        if stop_hit:                                                     # TP_FIRST policy: the remainder still stops in this bar (old SL)
            realized += rem * sgn * (sl_cur - spec.entry)
            fills.append({"t": b["t"], "kind": "STOP", "price": sl_cur, "w": rem, "ambiguous": True})
            rem, end_how = 0.0, ("BE" if sl_cur != spec.sl else "SL")
            break
    if rem > 0:
        if not complete:
            return {"mature": False, "reason": "okno horyzontu jeszcze otwarte (brak zamkniętych świec do końca horyzontu)", "label_version": spec.label_version,
                    "task_hash": spec.task_hash(), "bars_seen": len(win)}
        if not win:
            return {"mature": True, "scenario": "NO_BARS", "reason": "brak świec w oknie (rynek zamknięty) – wynik nieznany", "label_version": spec.label_version,
                    "task_hash": spec.task_hash(), "y_event": None, "net_r": None, "gross_r": None, "events": {}}
        last = _exit_side(win[-1], spec.direction)[3]
        realized += rem * sgn * (last - spec.entry)
        fills.append({"t": win[-1]["t"], "kind": "TIMEOUT", "price": last, "w": rem})
        end_how = "TIMEOUT"
    gross_r = realized / R
    net_r = None if spec.cost_price is None else (realized - spec.cost_price) / R
    events = {f"TP{j + 1}_BEFORE_STOP": k >= j + 1 for j in range(len(targets))}
    events.update({"SL_FIRST": k == 0 and end_how == "SL", "TIMEOUT": end_how == "TIMEOUT", "NET_R_POSITIVE": None if net_r is None else net_r > 0})
    out = {"mature": True, "scenario": f"TP{k}_{end_how}", "targets_filled": k, "end": end_how, "events": events, "gross_r": round(gross_r, 6),
           "net_r": None if net_r is None else round(net_r, 6), "cost_r": None if spec.cost_price is None else round(spec.cost_price / R, 6),
           "cost_status": "KNOWN" if spec.cost_price is not None else "UNKNOWN", "ambiguous": ambiguous, "gap": gap, "policy": policy,
           "spread_known": spread_known, "mfe_r": round(mfe, 6), "mae_r": round(mae, 6), "fills": fills, "label_version": spec.label_version,
           "task_hash": spec.task_hash(), "event_id": spec.event_id, "y_event": bool(events.get(spec.event_id, False)) if spec.event_id in events else None}
    if spec.ambiguity == "BOUNDS" and _policy is None and ambiguous:
        alt = simulate(spec, bars, decision_ts, tf_s=tf_s, available_until=available_until, _policy="TP_FIRST")
        out["net_r_bounds"] = [out["net_r"], alt.get("net_r")]
        out["gross_r_bounds"] = [out["gross_r"], alt.get("gross_r")]
    return out


def spec_from_candidate(c: dict, *, be_after: str | None = None, ambiguity: str = "SL_FIRST", event_id: str | None = None) -> EventSpec:
    """EventSpec of an evaluation SetupCandidate (dict). The SH plans keep their BE after TP2; other engines declare no BE unless given."""
    ec = c.get("execution_context") or {}
    eng = c.get("engine") or "?"
    be = be_after if be_after is not None else ("TP2" if eng.startswith("SH_") and len(c.get("targets") or []) >= 2 else None)
    tg = tuple((float(t["price"]), float(t["weight"])) for t in c.get("targets") or [])
    ev = event_id or (f"TP{min(2, len(tg))}_BEFORE_STOP" if tg else "TP1_BEFORE_STOP")
    cost = ec.get("cost_price")
    known = ec.get("commission_known")
    return EventSpec(instrument=str(c.get("instrument") or c.get("symbol")), strategy=f"{eng}/{c.get('strategy_id')}", direction=str(c["direction"]),
                     entry=float(c["entry_price"]), sl=float(c["stop_loss"]), targets=tg, horizon_s=float(c["horizon_s"]),
                     entry_rule=str(c.get("entry_type") or "MARKET"), be_after=be, be_offset_price=float(cost or 0.0) if be else 0.0,
                     cost_price=(float(cost) if cost is not None and known is not False else None), ambiguity=ambiguity, event_id=ev)
