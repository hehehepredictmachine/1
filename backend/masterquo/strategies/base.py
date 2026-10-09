"""Common strategy contract (MQ-STRATEGY-CONTRACT-1.0.0).

A strategy is a pure function of a MarketView (closed bars per TF + the forming bar + quote +
regime) and its parameters. It returns Drafts: recognised structures with their own necessary
conditions, phase (WATCH / EARLY / TRIGGER), plan, invalidation and score components.
I/O (MT5, Claude, DB) never happens inside a strategy, so live scanning and replay share the code.

Stage rules (applied by `finalize`, identical for all strategies):
* score < watch threshold                      -> not published (counted as SCORE_BELOW_WATCH)
* phase WATCH                                  -> WATCH
* phase EARLY  (or TRIGGER on a forming bar)   -> EARLY if score >= early threshold, else WATCH
* phase TRIGGER on a CLOSED bar                -> CONFIRMED if score >= confirmed threshold, else EARLY
CONFIRMED therefore always needs the strategy's real trigger; the score alone never confirms.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from . import indicators as ind

CONTRACT_VERSION = "MQ-STRATEGY-CONTRACT-1.0.0"
SCHEMA_VERSION = "mq-setup-1.0.0"
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
STAGES = ("WATCH", "EARLY", "CONFIRMED")
# ACTIVE score categories (points). Deterministic rules in `score`.
WEIGHTS = {"structure": 25, "formation": 25, "momentum": 20, "trigger": 15, "htf": 10, "extra": 5}


class TFView:
    """Closed bars of one timeframe as parallel lists + the forming bar (closed=False) if any."""

    def __init__(self, tf: str, bars: list[dict]):
        self.tf = tf
        closed = [b for b in bars if b.get("closed") and b.get("open_utc")]
        self.t = [b["open_utc"] for b in closed]
        self.o = [float(b["o"]) for b in closed]
        self.h = [float(b["h"]) for b in closed]
        self.l = [float(b["l"]) for b in closed]
        self.c = [float(b["c"]) for b in closed]
        self.tv = [float(b.get("tv") or 0.0) for b in closed]     # broker tick count (CFD activity proxy, not exchange volume)
        fb = next((b for b in reversed(bars) if not b.get("closed")), None)
        self.forming = {"open_utc": fb["open_utc"], "o": float(fb["o"]), "h": float(fb["h"]), "l": float(fb["l"]), "c": float(fb["c"])} if fb else None
        self._cache: dict = {}

    def __len__(self) -> int:
        return len(self.c)

    @property
    def last(self) -> int:
        return len(self.c) - 1

    def get(self, key: str, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def atr(self, n: int = 14):
        return self.get(f"atr{n}", lambda: ind.atr(self.h, self.l, self.c, n))

    def ema(self, n: int):
        return self.get(f"ema{n}", lambda: ind.ema(self.c, n))

    def rsi(self, n: int = 14):
        return self.get(f"rsi{n}", lambda: ind.rsi(self.c, n))

    def macd_hist(self):
        return self.get("macdh", lambda: ind.macd_hist(self.c))

    def pivots(self, left: int = 3, right: int = 3):
        return self.get(f"piv{left}_{right}", lambda: ind.pivots(self.h, self.l, left, right))


@dataclass
class MarketView:
    symbol: str
    as_of: str
    tfs: dict[str, TFView]
    bid: float | None
    ask: float | None
    point: float | None
    regime: dict = field(default_factory=dict)
    session: dict = field(default_factory=dict)
    synthetic: bool = False
    mirrored: bool = False
    center: float = 0.0          # mirror centre: p' = 2*center - p (set on mirrored views only)

    @property
    def mid(self) -> float | None:
        return None if self.bid is None or self.ask is None else (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return 0.0 if self.bid is None or self.ask is None else max(0.0, self.ask - self.bid)


@dataclass
class Draft:
    strategy_id: str
    direction: str                 # LONG / SHORT
    timeframe: str                 # setup timeframe
    phase: str                     # WATCH / EARLY / TRIGGER
    structure_key: str             # identity of the structure/zone (stable across refreshes)
    event_key: str                 # shared by strategies describing the same market event
    anchor_time: str | None        # open_utc of the bar that defines the structure
    entry_plan: dict | None
    invalidation_level: float | None
    invalidation_rule: str = "CLOSE_BEYOND"   # CLOSE_BEYOND (closed setup-TF bar) / TOUCH (quote)
    stop_loss: float | None = None
    targets: list[dict] = field(default_factory=list)
    exit_rules: dict = field(default_factory=dict)
    expires_bars: int = 12
    components: dict = field(default_factory=dict)   # structure/formation/trigger in 0..1
    momentum_mode: str = "CONTINUATION"              # CONTINUATION / REVERSAL
    reason_codes: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    trigger_on_forming: bool = False
    countertrend: bool = False
    horizon: str = "INTRADAY"
    facts: dict = field(default_factory=dict)        # measured values (evidence for UI/agent)


class Strategy:
    id = "S00"
    name = "BASE"
    version = "1.0.0-EXPERIMENTAL"
    family = "BASE"
    horizon = "INTRADAY"
    setup_tfs: tuple[str, ...] = ("M5", "M15")
    context_tf: str | None = "H1"
    required_tfs: tuple[str, ...] = ("M5", "M15")
    min_bars = 80
    regime_fit: dict[str, float] = {}
    params: dict = {}
    validation_status = "FUNCTIONAL_ONLY_OOS_NOT_RUN"

    def config_hash(self, p: dict) -> str:
        return hashlib.sha256(json.dumps({"id": self.id, "v": self.version, "p": p}, sort_keys=True).encode()).hexdigest()[:12]

    def check_data(self, view: MarketView) -> tuple[str, list[str]]:
        """OK / DATA_MISSING / WARMING_UP for this strategy's own required TFs only."""
        miss, warm = [], []
        for tf in self.required_tfs:
            v = view.tfs.get(tf)
            if v is None or len(v) == 0:
                miss.append(f"{tf}_MISSING")
            elif len(v) < self.min_bars:
                warm.append(f"{tf}_WARMING_UP_{len(v)}/{self.min_bars}")
        if miss:
            return "DATA_MISSING", miss
        if warm:
            return "WARMING_UP", warm
        return "OK", []

    def detect_long(self, view: MarketView, p: dict) -> list[Draft]:  # pragma: no cover - interface
        """Rules written for LONG. SHORT is evaluated with the same code on the price-mirrored view."""
        raise NotImplementedError

    def detect(self, view: MarketView, p: dict) -> list[Draft]:
        out = list(self.detect_long(view, p))
        mv = mirror_view(view)
        out += [unmirror_draft(d, mv.center) for d in self.detect_long(mv, p)]
        for d in out:
            d.strategy_id = self.id
        return out

    # ---- helpers shared by implementations
    @staticmethod
    def tick_round(x: float | None, point: float | None) -> float | None:
        if x is None:
            return None
        if not point:
            return round(x, 2)
        return round(round(x / point) * point, 8)


# ----------------------------------------------------------------------------- mirroring
_MIRROR_STATE = {"TREND_UP": "TREND_DOWN", "TREND_DOWN": "TREND_UP"}
_MIRROR_DIR = {"UP": "DOWN", "DOWN": "UP"}


def _mirror_tf(v: TFView, k: float) -> TFView:
    bars = [{"open_utc": t, "o": k - o, "h": k - lo, "l": k - h, "c": k - c, "tv": tv, "closed": True}
            for t, o, h, lo, c, tv in zip(v.t, v.o, v.h, v.l, v.c, v.tv)]
    if v.forming:
        f = v.forming
        bars.append({"open_utc": f["open_utc"], "o": k - f["o"], "h": k - f["l"], "l": k - f["h"], "c": k - f["c"], "closed": False})
    return TFView(v.tf, bars)


def _mirror_regime(reg: dict) -> dict:
    if not reg:
        return reg
    per = {tf: {**r, "state": _MIRROR_STATE.get(r.get("state"), r.get("state")), "direction": _MIRROR_DIR.get(r.get("direction"), r.get("direction"))}
           for tf, r in (reg.get("per_tf") or {}).items()}
    return {**reg, "state": _MIRROR_STATE.get(reg.get("state"), reg.get("state")), "per_tf": per}


def mirror_center(view: MarketView) -> float:
    """Centre of reflection: latest close of the lowest available TF (prices stay positive, same magnitude,
    so ratio indicators such as Bollinger width/mean remain valid)."""
    for tf in ("M1", "M5", "M15", "H1", "H4", "D1"):
        v = view.tfs.get(tf)
        if v is not None and v.c:
            return float(v.c[-1])
    return view.mid or 0.0


def mirror_view(view: MarketView) -> MarketView:
    """Price-reflected view (p' = 2C - p): highs become lows; LONG rules applied to it detect SHORT setups."""
    c = mirror_center(view)
    k = 2 * c
    return MarketView(symbol=view.symbol, as_of=view.as_of, tfs={tf: _mirror_tf(v, k) for tf, v in view.tfs.items()},
                      bid=None if view.ask is None else k - view.ask, ask=None if view.bid is None else k - view.bid, point=view.point,
                      regime=_mirror_regime(view.regime), session=view.session, synthetic=view.synthetic, mirrored=True, center=c)


def real_price(view: MarketView, level: float) -> float:
    """Price in real (unmirrored) coordinates - identities/buckets must never depend on the mirror centre."""
    return 2 * view.center - level if view.mirrored else level


_CODE_SWAP = {"ABOVE": "BELOW", "BELOW": "ABOVE", "HIGH": "LOW", "LOW": "HIGH", "UP": "DOWN", "DOWN": "UP", "TOP": "BOTTOM",
              "BOTTOM": "TOP", "RISING": "FALLING", "FALLING": "RISING", "BULLISH": "BEARISH", "BEARISH": "BULLISH",
              "UPPER": "LOWER", "LOWER": "HIGHER", "LONG": "SHORT", "SHORT": "LONG", "HIGHER": "LOWER"}
_TEXT_SWAP = [("powyżej", "poniżej"), ("poniżej", "powyżej"), ("wzrostowo", "spadkowo"), ("spadkowo", "wzrostowo"), ("górnej", "dolnej"),
              ("dolnej", "górnej"), ("high", "low"), ("low", "high"), ("niższego szczytu", "wyższego dołka"),
              ("zawraca z poziomu ≤", "zawraca z poziomu ≥"), ("rosnącej", "malejącej")]


def mirror_code(code: str) -> str:
    return "_".join(_CODE_SWAP.get(t, t) for t in code.split("_"))


def mirror_text(text: str) -> str:
    """Swap direction words in one pass (placeholders avoid swapping twice)."""
    out = text
    for i, (a, _b) in enumerate(_TEXT_SWAP):
        out = out.replace(a, f"\x00{i}\x00")
    for i, (_a, b) in enumerate(_TEXT_SWAP):
        out = out.replace(f"\x00{i}\x00", b)
    return out


def unmirror_draft(d: Draft, center: float) -> Draft:
    k = 2 * center

    def back(x):
        return None if x is None else k - x
    d.direction = "SHORT"
    d.missing = [mirror_code(m) for m in d.missing]
    d.reason_codes = [mirror_code(m) for m in d.reason_codes]
    d.invalidation_level = back(d.invalidation_level)
    d.stop_loss = back(d.stop_loss)
    d.targets = [{**t, "price": k - t["price"], "basis": mirror_code(str(t.get("basis", "")))} for t in d.targets]
    if d.entry_plan:
        ep = dict(d.entry_plan)
        ep["reference_price"] = back(ep.get("reference_price"))
        ep["trigger_level"] = back(ep.get("trigger_level"))
        ep["trigger"] = mirror_text(ep.get("trigger") or "")
        if ep.get("zone"):
            ep["zone"] = sorted(k - z for z in ep["zone"])
        d.entry_plan = ep
    facts = {}
    for key, v in d.facts.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and key.endswith("_px"):
            v = round(k - v, 5)
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and key.endswith("_sgn"):
            v = -v
        facts[key] = v
    d.facts = facts
    d.structure_key = "S|" + d.structure_key
    d.event_key = d.event_key.replace("LONG", "SHORT")
    return d


def long_stop(view: MarketView, level: float, buffer: float) -> float:
    """Stop for the LONG rule; on the mirrored view it becomes a SHORT stop that includes the spread."""
    return level - buffer - (view.spread if view.mirrored else 0.0)


# ----------------------------------------------------------------------------- scoring
def momentum_component(v: TFView, direction: str, mode: str) -> tuple[float | None, dict]:
    """One momentum category (20 pts) from RSI, MACD histogram and EMA20 slope.

    These indicators are strongly correlated, so they are NOT counted as three confirmations:
    the category value is the median of their individual 0/0.5/1 votes.
    CONTINUATION: momentum in the setup direction. REVERSAL: momentum turning toward the setup
    direction (histogram rising for LONG / falling for SHORT, RSI leaving the extreme zone).
    """
    i = v.last
    r, mh, e20, a = v.rsi(), v.macd_hist(), v.ema(20), v.atr()
    if i < 3 or r[i] is None or mh[i] is None or mh[i - 1] is None or e20[i] is None or not a[i]:
        return None, {"known": False}
    sgn = 1 if direction == "LONG" else -1
    votes = []
    sl = ind.slope_atr(e20, a, i, 3)
    if mode == "CONTINUATION":
        votes.append(1.0 if sgn * (r[i] - 50) > 5 else (0.5 if sgn * (r[i] - 50) > -5 else 0.0))
        votes.append(1.0 if sgn * mh[i] > 0 and sgn * (mh[i] - mh[i - 1]) >= 0 else (0.5 if sgn * mh[i] > 0 else 0.0))
        votes.append(0.0 if sl is None else (1.0 if sgn * sl > 0.05 else (0.5 if sgn * sl > -0.02 else 0.0)))
    else:
        prev = r[i - 1] if r[i - 1] is not None else r[i]
        turning = sgn * (r[i] - prev) > 0
        from_extreme = prev < 40 if direction == "LONG" else prev > 60
        votes.append(1.0 if turning and from_extreme else (0.5 if turning else 0.0))
        votes.append(1.0 if sgn * (mh[i] - mh[i - 1]) > 0 and sgn * (mh[i - 1] - (mh[i - 2] or mh[i - 1])) > 0 else (0.5 if sgn * (mh[i] - mh[i - 1]) > 0 else 0.0))
        votes.append(0.0 if sl is None else (1.0 if sgn * sl > -0.02 else 0.5 if sgn * sl > -0.1 else 0.0))
    votes.sort()
    return votes[1], {"known": True, "rsi": round(r[i], 1), "macd_hist": round(mh[i], 4), "ema20_slope_atr": None if sl is None else round(sl, 3), "votes": votes}


def htf_component(view: MarketView, direction: str, tfs: tuple[str, ...] = ("H1", "H4")) -> tuple[float | None, dict, bool]:
    """HTF context (10 pts): average of per-TF alignment (aligned 1, neutral 0.5, opposite 0).

    Uses the regime engine's per-TF direction. Unknown TFs give no points (and stay in the
    denominator). Returns (value, detail, countertrend) - countertrend = every known HTF opposite.
    """
    per = (view.regime or {}).get("per_tf") or {}
    vals, detail, opp, known = [], {}, 0, 0
    for tf in tfs:
        d = (per.get(tf) or {}).get("direction")
        detail[tf] = d
        if d in ("UP", "DOWN"):
            known += 1
            aligned = (d == "UP") == (direction == "LONG")
            vals.append(1.0 if aligned else 0.0)
            opp += 0 if aligned else 1
        elif d == "FLAT":
            known += 1
            vals.append(0.5)
        else:
            vals.append(0.0)
    if known == 0:
        return None, detail, False
    return sum(vals) / len(tfs), detail, opp > 0 and opp == sum(1 for tf in tfs if (per.get(tf) or {}).get("direction") in ("UP", "DOWN"))


def score(draft: Draft, view: MarketView, extra: float | None = None) -> dict:
    """Deterministic 0-100 ACTIVE score. Unknown components give 0 points (no denominator shrink)."""
    v = view.tfs[draft.timeframe]
    mom, mom_detail = momentum_component(v, draft.direction, draft.momentum_mode)
    htf, htf_detail, counter = htf_component(view, draft.direction)
    comp = {"structure": draft.components.get("structure"), "formation": draft.components.get("formation"),
            "momentum": mom, "trigger": draft.components.get("trigger"), "htf": htf, "extra": extra}
    pts, known = {}, 0
    for k, w in WEIGHTS.items():
        val = comp[k]
        if val is None:
            pts[k] = 0.0
        else:
            known += w
            pts[k] = round(w * max(0.0, min(1.0, float(val))), 1)
    total = round(sum(pts.values()), 1)
    return {"total": total, "points": pts, "weights": WEIGHTS, "completeness": round(known / 100, 2),
            "momentum": mom_detail, "htf": htf_detail, "htf_countertrend": counter, "scale": "ACTIVE-0-100 (heurystyka, nie prawdopodobieństwo)"}


def finalize(draft: Draft, sc: dict, thresholds: dict) -> tuple[str | None, list[str]]:
    """Stage from phase + score. Returns (stage or None when below WATCH, extra missing codes)."""
    s = sc["total"]
    miss: list[str] = []
    if s < thresholds["watch"]:
        return None, ["SCORE_BELOW_WATCH"]
    phase = draft.phase
    if phase == "TRIGGER" and draft.trigger_on_forming:
        phase = "EARLY"
        miss.append("TRIGGER_BAR_NOT_CLOSED")
    if phase == "TRIGGER":
        if s >= thresholds["confirmed"]:
            return "CONFIRMED", miss
        miss.append(f"SCORE_BELOW_CONFIRMED_{thresholds['confirmed']}")
        return ("EARLY" if s >= thresholds["early"] else "WATCH"), miss
    if phase == "EARLY":
        if s >= thresholds["early"]:
            return "EARLY", miss
        miss.append(f"SCORE_BELOW_EARLY_{thresholds['early']}")
        return "WATCH", miss
    return "WATCH", miss


def r_targets(direction: str, entry: float, stop: float, rs: tuple[float, ...], basis: str) -> list[dict]:
    """Targets at fixed multiples of the initial risk (used only where the strategy hypothesis has no structural target)."""
    risk = abs(entry - stop)
    sgn = 1 if direction == "LONG" else -1
    w = 1.0 / len(rs)
    return [{"price": entry + sgn * r * risk, "weight": round(w, 4), "basis": f"{basis}_{r}R"} for r in rs]
