"""EMA20 Pullback + 2.5R - pure core shared by the live strategy (S11), the backtester and the Pine comparison.

Source: the attached Pine Script v6 strategy "EMA20 Pullback + 2.5R Strategy — XAUUSD"
(strategies/pine/EMA20_Pullback_2.5R_ORIGINAL.pine, sha256 6c14dbd0...). The corrected Pine version is
strategies/pine/EMA20_Pullback_2.5R_FIXED.pine. Audit: AUDYT_MASTERQUO.md, section "Strategia EMA20 Pullback".

Indicators follow the Pine reference definitions (the reference examples of ta.ema / ta.rma / ta.atr / ta.dmi):
  ema  : alpha = 2/(n+1), first value = the first source value          (pine_ema example)
  rma  : alpha = 1/n,     first value = SMA of the first n values        (pine_rma example)
  tr   : high-low on the first bar, then max(h-l, |h-c[1]|, |l-c[1]|)
  atr  : rma(tr, n)
  dmi  : +DM/-DM from ta.change(high/low), DI = 100*rma(DM, len)/rma(tr, len), ADX = 100*rma(|DI+ - DI-|/(DI+ + DI-), smoothing)
The online Pine reference was not reachable from the build environment, so these definitions are reproduced from the
reference examples and are NOT claimed verified against TradingView output (see RAPORT_WYNIKOW.md).

Two state machines, evaluated bar by bar on CLOSED bars (index i = the bar that just closed):
  ORIGINAL  replicates the Pine logic including its defects (used only for the baseline comparison);
  FIXED     NONE -> TOUCHED/WAITING (setup id = first-touch bar) -> CONFIRMED | EXPIRED | INVALIDATED.
            order per bar: (1) invalidate on trend change, (2) expire after max_pullback_bars, (3) confirm on a LATER
            bar than the touch with the trend still valid, (4) a new touch opens a setup only when none is waiting.
Hypotheses (candidate variant, each switchable for ablation): zone touch with ATR tolerance + approach side + depth,
"reclaim" confirmation, EMA separation filter (no tangled EMAs), H8 trend filter (as-of, closed H8 bars only).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

CORE_VERSION = "MQ-EMA-PULLBACK-CORE-1.0.0"


# ------------------------------------------------------------------------------------------------ Pine-style indicators
def pine_ema(x: list[float], n: int) -> list[float]:
    a = 2.0 / (n + 1)
    out, s = [], None
    for v in x:
        s = v if s is None else a * v + (1 - a) * s
        out.append(s)
    return out


def pine_rma(x: list[float | None], n: int) -> list[float | None]:
    out: list[float | None] = []
    s, buf = None, []
    for v in x:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out.append(s)
            continue
        if s is None:
            buf.append(v)
            if len(buf) == n:
                s = sum(buf) / n
            out.append(s)
        else:
            s = (v + (n - 1) * s) / n
            out.append(s)
    return out


def pine_tr(h: list[float], lo: list[float], c: list[float]) -> list[float]:
    return [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, len(c))]


def pine_atr(h, lo, c, n):
    return pine_rma(pine_tr(h, lo, c), n)


def pine_dmi(h: list[float], lo: list[float], c: list[float], di_len: int, smooth: int):
    pdm: list[float | None] = [None]
    mdm: list[float | None] = [None]
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], -(lo[i] - lo[i - 1])
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
    trur = pine_rma(pine_tr(h, lo, c), di_len)
    rp, rm = pine_rma(pdm, di_len), pine_rma(mdm, di_len)
    plus, minus, last_p, last_m = [], [], None, None
    for i in range(len(c)):
        p = 100 * rp[i] / trur[i] if (rp[i] is not None and trur[i]) else None
        m = 100 * rm[i] / trur[i] if (rm[i] is not None and trur[i]) else None
        last_p = p if p is not None else last_p          # fixnan()
        last_m = m if m is not None else last_m
        plus.append(last_p)
        minus.append(last_m)
    dx = [None if (p is None or m is None) else abs(p - m) / ((p + m) if (p + m) != 0 else 1) for p, m in zip(plus, minus)]
    adx = [None if v is None else 100 * v for v in pine_rma(dx, smooth)]
    return plus, minus, adx


def lowest(x, i, n):
    return min(x[max(0, i - n + 1):i + 1])


def highest(x, i, n):
    return max(x[max(0, i - n + 1):i + 1])


# ------------------------------------------------------------------------------------------------ parameters
@dataclass
class Params:
    len_ema20: int = 20
    len_ema50: int = 50
    touch_tolerance_pct: float = 0.05
    max_pullback_bars: int = 20             # 0 = no limit
    require_green_red: bool = False
    cooldown_bars: int = 1
    use_adx: bool = True
    adx_len: int = 14
    adx_smoothing: int = 14
    adx_threshold: float = 20.0
    swing_lookback: int = 10
    atr_len: int = 14
    atr_buffer_mult: float = 0.1
    rr: float = 2.5
    only_one_position: bool = True
    # ---- hypotheses (candidate variant only; defaults = off / original semantics)
    touch_mode: str = "PCT"                 # PCT (original one-sided %) | ZONE_ATR (range intersects EMA20 +- tol x ATR)
    touch_tol_atr: float = 0.10
    require_approach: bool = False          # previous close on the trend side of the zone (a pullback, not a breakdown)
    max_depth_atr: float | None = None      # low may not pierce EMA20 by more than this many ATR
    confirm_mode: str = "CLOSE_BEYOND"      # CLOSE_BEYOND | RECLAIM (prior close at/inside the zone, this close beyond)
    min_ema_sep_atr: float | None = None    # |EMA20-EMA50| >= k x ATR (the instruction's "no tangled EMAs" rule)
    h8_trend_filter: bool = False           # EMA20 > EMA50 on the last CLOSED H8 bar (as-of join)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Event:
    i: int
    kind: str                   # TOUCH / CONFIRM / EXPIRED / INVALIDATED / BLOCKED_FILTER
    direction: str              # LONG / SHORT
    setup_id: int               # bar index of the first touch (FIXED); touch bar of the active wait (ORIGINAL)
    reason: str = ""
    ref_price: float | None = None     # close of the confirmation bar (signal reference, NOT a fill)
    stop: float | None = None
    swing: float | None = None


@dataclass
class MachineResult:
    events: list[Event] = field(default_factory=list)
    waiting: dict = field(default_factory=dict)        # direction -> {setup_id, touch_i} at the last bar (FIXED/ORIGINAL)
    ind: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)


def indicators(o, h, lo, c, p: Params) -> dict:
    e20, e50 = pine_ema(c, p.len_ema20), pine_ema(c, p.len_ema50)
    atr = pine_atr(h, lo, c, p.atr_len)
    dip, dim, adx = pine_dmi(h, lo, c, p.adx_len, p.adx_smoothing)
    return {"ema20": e20, "ema50": e50, "atr": atr, "adx": adx, "di_plus": dip, "di_minus": dim}


def warmup_bars(p: Params) -> int:
    """Bars before which no decision is made: EMA50 needs ~3x its length to forget the first-value seed;
    ADX needs di_len + smoothing bars to exist at all."""
    return max(3 * p.len_ema50, p.adx_len + p.adx_smoothing + 1, p.atr_len + 1, p.swing_lookback)


# ------------------------------------------------------------------------------------------------ ORIGINAL (Pine replica)
def run_original(o, h, lo, c, p: Params, ind: dict | None = None) -> MachineResult:
    """Bar-by-bar replica of the Pine state machine, defects included (see the audit for each one)."""
    ind = ind or indicators(o, h, lo, c, p)
    e20, e50, atr, adx = ind["ema20"], ind["ema50"], ind["atr"], ind["adx"]
    tol = 1.0 + p.touch_tolerance_pct / 100.0
    res = MachineResult(ind=ind)
    wl = ws = False
    bl = bs = 0
    tl_i = ts_i = -1
    counts = {"touch_long": 0, "touch_short": 0, "confirm_long": 0, "confirm_short": 0}
    for i in range(len(c)):
        trend_up, trend_dn = e20[i] > e50[i], e20[i] < e50[i]
        touch_l = trend_up and lo[i] <= e20[i] * tol
        touch_s = trend_dn and h[i] >= e20[i] / tol
        if touch_l and not wl:
            counts["touch_long"] += 1
            res.events.append(Event(i, "TOUCH", "LONG", i))
        if touch_s and not ws:
            counts["touch_short"] += 1
            res.events.append(Event(i, "TOUCH", "SHORT", i))
        was_l, was_s = wl, ws                         # snapshot BEFORE the touch handling
        if touch_l:
            wl, bl, tl_i = True, 0, i                 # every touch restarts the wait (defect 2)
        elif wl:
            bl += 1
        if touch_s:
            ws, bs, ts_i = True, 0, i
        elif ws:
            bs += 1
        if p.max_pullback_bars > 0 and bl > p.max_pullback_bars:
            wl = False                                # expiry evaluated, but the snapshot above still says waiting (defect 3)
        if p.max_pullback_bars > 0 and bs > p.max_pullback_bars:
            ws = False
        adx_ok = (not p.use_adx) or (adx[i] is not None and adx[i] >= p.adx_threshold)
        conf_l = was_l and c[i] > e20[i] and (not p.require_green_red or c[i] > o[i]) and adx_ok   # no trend re-check (defect 1)
        conf_s = was_s and c[i] < e20[i] and (not p.require_green_red or c[i] < o[i]) and adx_ok
        if conf_l:
            counts["confirm_long"] += 1
            wl = False
            sw = lowest(lo, i, p.swing_lookback)
            res.events.append(Event(i, "CONFIRM", "LONG", tl_i, ref_price=c[i], swing=sw,
                                    stop=None if atr[i] is None else sw - atr[i] * p.atr_buffer_mult))
        if conf_s:
            counts["confirm_short"] += 1
            ws = False
            sw = highest(h, i, p.swing_lookback)
            res.events.append(Event(i, "CONFIRM", "SHORT", ts_i, ref_price=c[i], swing=sw,
                                    stop=None if atr[i] is None else sw + atr[i] * p.atr_buffer_mult))
    res.waiting = {d: v for d, v in (("LONG", {"setup_id": tl_i, "touch_i": tl_i} if wl else None),
                                     ("SHORT", {"setup_id": ts_i, "touch_i": ts_i} if ws else None)) if v}
    res.counts = counts
    return res


# ------------------------------------------------------------------------------------------------ FIXED / candidate
def _touch(direction: str, i: int, o, h, lo, c, e20, atr, p: Params) -> tuple[bool, str]:
    s = 1 if direction == "LONG" else -1
    a = atr[i]
    if p.touch_mode == "ZONE_ATR":
        if not a:
            return False, "NO_ATR"
        tol = p.touch_tol_atr * a
        hit = lo[i] <= e20[i] + tol and h[i] >= e20[i] - tol           # bar range intersects the EMA20 zone
    else:
        t = 1.0 + p.touch_tolerance_pct / 100.0
        hit = lo[i] <= e20[i] * t if s > 0 else h[i] >= e20[i] / t
    if not hit:
        return False, ""
    if p.require_approach and i > 0:
        tol = (p.touch_tol_atr * a) if (p.touch_mode == "ZONE_ATR" and a) else e20[i - 1] * p.touch_tolerance_pct / 100.0
        if not (s * (c[i - 1] - e20[i - 1]) > tol):
            return False, "APPROACH_NOT_FROM_TREND_SIDE"
    if p.max_depth_atr is not None and a:
        pierce = (e20[i] - lo[i]) if s > 0 else (h[i] - e20[i])
        if pierce > p.max_depth_atr * a:
            return False, "PULLBACK_TOO_DEEP"
    return True, ""


def run_fixed(o, h, lo, c, p: Params, ind: dict | None = None, h8_trend: list[int | None] | None = None,
              start: int | None = None) -> MachineResult:
    """Corrected state machine. h8_trend[i] = +1/-1/0/None: trend of the last H8 bar CLOSED at or before the close
    of bar i (as-of join done by the caller); None = H8 missing -> setups that require it are BLOCKED (BRAK_DANYCH)."""
    ind = ind or indicators(o, h, lo, c, p)
    e20, e50, atr, adx = ind["ema20"], ind["ema50"], ind["atr"], ind["adx"]
    res = MachineResult(ind=ind)
    wait: dict[str, dict | None] = {"LONG": None, "SHORT": None}
    counts = {k: 0 for k in ("touch_long", "touch_short", "confirm_long", "confirm_short", "expired", "invalidated", "blocked_filter")}
    first = warmup_bars(p) if start is None else start
    for i in range(len(c)):
        if i < first or atr[i] is None or (p.use_adx and adx[i] is None):
            continue
        trend = {"LONG": e20[i] > e50[i], "SHORT": e20[i] < e50[i]}
        sep_ok = p.min_ema_sep_atr is None or (atr[i] and abs(e20[i] - e50[i]) >= p.min_ema_sep_atr * atr[i])
        adx_ok = (not p.use_adx) or adx[i] >= p.adx_threshold
        for d in ("LONG", "SHORT"):
            s = 1 if d == "LONG" else -1
            w = wait[d]
            # (1) context change invalidates an open setup
            if w and not trend[d]:
                res.events.append(Event(i, "INVALIDATED", d, w["setup_id"], "TREND_CHANGED"))
                counts["invalidated"] += 1
                wait[d] = w = None
            # (2) expiry BEFORE confirmation: confirmation allowed on bars touch+1 .. touch+max_pullback_bars
            if w and p.max_pullback_bars > 0 and i - w["touch_i"] > p.max_pullback_bars:
                res.events.append(Event(i, "EXPIRED", d, w["setup_id"], f"NO_CONFIRMATION_IN_{p.max_pullback_bars}_BARS"))
                counts["expired"] += 1
                wait[d] = w = None
            # (3) confirmation on a later closed bar, trend still valid
            if w and i > w["touch_i"]:
                beyond = s * (c[i] - e20[i]) > 0
                if p.confirm_mode == "RECLAIM":
                    zone = (p.touch_tol_atr * atr[i]) if p.touch_mode == "ZONE_ATR" else e20[i - 1] * p.touch_tolerance_pct / 100.0
                    beyond = beyond and s * (c[i - 1] - e20[i - 1]) <= zone
                candle_ok = (not p.require_green_red) or s * (c[i] - o[i]) > 0
                if beyond and candle_ok and adx_ok:
                    blocked = None
                    if not sep_ok:
                        blocked = "EMAS_TANGLED"
                    elif p.h8_trend_filter:
                        ht = None if h8_trend is None else h8_trend[i]
                        if ht is None:
                            blocked = "BRAK_DANYCH_H8"
                        elif ht != s:
                            blocked = "H8_TREND_AGAINST"
                    if blocked:
                        res.events.append(Event(i, "BLOCKED_FILTER", d, w["setup_id"], blocked))
                        counts["blocked_filter"] += 1
                    else:
                        sw = lowest(lo, i, p.swing_lookback) if s > 0 else highest(h, i, p.swing_lookback)
                        stop = sw - s * atr[i] * p.atr_buffer_mult
                        res.events.append(Event(i, "CONFIRM", d, w["setup_id"], ref_price=c[i], stop=stop, swing=sw))
                        counts["confirm_long" if s > 0 else "confirm_short"] += 1
                    wait[d] = None                         # the setup is consumed (confirmed or blocked) - never re-used later
                    continue                               # no new setup from the confirmation bar itself
            # (4) a touch opens a new setup only when none is waiting (first touch = setup id, no silent extension)
            if wait[d] is None and trend[d]:
                ok, _why = _touch(d, i, o, h, lo, c, e20, atr, p)
                if ok:
                    wait[d] = {"setup_id": i, "touch_i": i}
                    res.events.append(Event(i, "TOUCH", d, i))
                    counts["touch_long" if s > 0 else "touch_short"] += 1
    res.waiting = {d: w for d, w in wait.items() if w}
    res.counts = counts
    return res


def asof_h8_trend(times_close: list[float], h8_bars: list[dict], p: Params) -> list[int | None]:
    """+1/-1/0 trend of the last H8 bar whose CLOSE time <= the close time of each base bar; None when unavailable.
    h8_bars: dicts with close_ts (epoch seconds of the bar close), c. Only CLOSED H8 bars may be passed."""
    if not h8_bars:
        return [None] * len(times_close)
    cl = [b["c"] for b in h8_bars]
    e20, e50 = pine_ema(cl, p.len_ema20), pine_ema(cl, p.len_ema50)
    ready = 3 * p.len_ema50
    out, j = [], -1
    for t in times_close:
        while j + 1 < len(h8_bars) and h8_bars[j + 1]["close_ts"] <= t:
            j += 1
        if j < ready:
            out.append(None)
        else:
            out.append(1 if e20[j] > e50[j] else (-1 if e20[j] < e50[j] else 0))
    return out
