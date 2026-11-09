"""Shared causal features of the 20 SH variants (one generation per symbol / TF / last closed bar; every variant reads the same cache).

* Only CLOSED bars enter (`closed` and complete; a resampled M3 with a missing minute is excluded, never padded). Element i of every
  series uses inputs 0..i only; warm-up positions are None (WARMING_UP), never back-filled.
* SELL is the exact mirror of BUY: a mirrored view negates prices and swaps high/low (o'=-o, h'=-l, l'=-h, c'=-c), so every rule is
  written once for BUY and evaluated on the mirror for SELL (all inequalities, highs/lows, signs and indicator sides flip together).
  Levels returned by a rule on the mirror are mapped back with level_out().
* Indicators: EMA (SMA seed), Wilder ATR/ADX/RSI, BB(20,2) + BandWidth, Stochastic(14,3,3), MACD(12,26,9), Donchian of PRIOR bars,
  confirmed pivots 2/2 (known only after the two right bars closed), session VWAP from an anchor (tick volume = feed activity, not global
  gold volume; zero volume -> NO_DATA, never replaced by ones), std of log returns.
"""
from __future__ import annotations

import bisect
import math
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from ...strategies import indicators as I

TF_S = {"M1": 60, "M3": 180, "M5": 300, "M15": 900, "H1": 3600}


def ts(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def iso(t: float | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(float(t), timezone.utc).isoformat().replace("+00:00", "Z")


def adx(h, lo, c, n: int = 14) -> list[float | None]:
    """Wilder ADX."""
    L = len(c)
    out: list[float | None] = [None] * L
    if L < 2 * n + 1:
        return out
    tr = I.true_range(h, lo, c)
    pdm = [0.0] + [max(h[i] - h[i - 1], 0.0) if (h[i] - h[i - 1]) > (lo[i - 1] - lo[i]) else 0.0 for i in range(1, L)]
    ndm = [0.0] + [max(lo[i - 1] - lo[i], 0.0) if (lo[i - 1] - lo[i]) > (h[i] - h[i - 1]) else 0.0 for i in range(1, L)]
    atr_ = sum(tr[1:n + 1])
    p, m = sum(pdm[1:n + 1]), sum(ndm[1:n + 1])
    dx = []
    for i in range(n + 1, L + 1):
        if i > n + 1:
            atr_ = atr_ - atr_ / n + tr[i - 1]
            p = p - p / n + pdm[i - 1]
            m = m - m / n + ndm[i - 1]
        pdi = 100 * p / atr_ if atr_ else 0.0
        ndi = 100 * m / atr_ if atr_ else 0.0
        dx.append((i - 1, 0.0 if pdi + ndi == 0 else 100 * abs(pdi - ndi) / (pdi + ndi)))
    if len(dx) < n:
        return out
    a = sum(v for _, v in dx[:n]) / n
    out[dx[n - 1][0]] = a
    for idx, v in dx[n:]:
        a = (a * (n - 1) + v) / n
        out[idx] = a
    return out


def stoch(h, lo, c, k: int = 14, ks: int = 3, d: int = 3) -> tuple[list, list]:
    raw: list[float | None] = [None] * len(c)
    for i in range(k - 1, len(c)):
        hh, ll = max(h[i - k + 1:i + 1]), min(lo[i - k + 1:i + 1])
        raw[i] = 50.0 if hh == ll else 100 * (c[i] - ll) / (hh - ll)
    kk = _sma_none(raw, ks)
    return kk, _sma_none(kk, d)


def _sma_none(x: list, n: int) -> list:
    out: list[float | None] = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        if all(v is not None for v in w):
            out[i] = sum(w) / n
    return out


def macd(c, fast=12, slow=26, sig=9) -> tuple[list, list]:
    ef, es = I.ema(c, fast), I.ema(c, slow)
    line = [None if ef[i] is None or es[i] is None else ef[i] - es[i] for i in range(len(c))]
    return line, I.macd_hist(c, fast, slow, sig)


def bands(c, n=20, k=2.0) -> tuple[list, list, list, list]:
    m, s = I.sma(c, n), I.rolling_std(c, n)
    up = [None if m[i] is None or s[i] is None else m[i] + k * s[i] for i in range(len(c))]
    lo = [None if m[i] is None or s[i] is None else m[i] - k * s[i] for i in range(len(c))]
    # BandWidth on the absolute band distance (mirror-invariant: identical for BUY and SELL views)
    bw = [None if up[i] is None else up[i] - lo[i] for i in range(len(c))]
    return m, up, lo, bw


class TF:
    """Closed bars of one time frame (optionally mirrored) with lazily cached indicators."""

    def __init__(self, name: str, bars: list[dict], mirror: bool = False):
        self.name, self.mirror, self.tf_s = name, mirror, TF_S[name]
        good = [b for b in bars if b.get("open_utc") and b.get("closed", True) and b.get("complete") is not False]
        self.excluded = len(bars) - len(good)
        self.source = "RESAMPLED" if any(b.get("source") == "resampled" for b in good) else "NATIVE"
        sg = -1.0 if mirror else 1.0
        self.t = [ts(b["open_utc"]) for b in good]
        self.o = [sg * float(b["o"]) for b in good]
        self.c = [sg * float(b["c"]) for b in good]
        if mirror:
            self.h, self.l = [-float(b["l"]) for b in good], [-float(b["h"]) for b in good]
        else:
            self.h, self.l = [float(b["h"]) for b in good], [float(b["l"]) for b in good]
        self.tv = [float(b.get("tv") or 0) for b in good]
        self.N = len(good)              # full history held by the view
        self.n = self.N                 # VISIBLE closed bars (replay moves it forward; detectors never read index >= n)
        self._c: dict = {}
        self._ct = [x + self.tf_s for x in self.t]

    def cut(self, as_of: float) -> int:
        """Replay: show only bars CLOSED at or before as_of (causal series are computed once on the full history; element i depends on
        0..i only, so a value at i < n equals the value computed on the cut history)."""
        self.n = bisect.bisect_right(self._ct, as_of + 1e-6)
        return self.n

    def since(self, t0: float) -> int:
        """First visible index with bar open >= t0."""
        return bisect.bisect_left(self.t, t0 - 1e-6, 0, self.n)

    def out(self, x: float | None) -> float | None:
        """Level of this (possibly mirrored) view -> real price."""
        return None if x is None else (-x if self.mirror else x)

    def close_t(self, i: int) -> float:
        return self.t[i] + self.tf_s

    def _m(self, key, fn):
        if key not in self._c:
            self._c[key] = fn()
        return self._c[key]

    def ema(self, n: int):
        return self._m(("ema", n), lambda: I.ema(self.c, n))

    def atr(self, n: int = 14):
        return self._m(("atr", n), lambda: I.atr(self.h, self.l, self.c, n))

    def adx(self, n: int = 14):
        return self._m(("adx", n), lambda: adx(self.h, self.l, self.c, n))

    def rsi(self, n: int = 14):
        return self._m(("rsi", n), lambda: I.rsi(self.c, n))

    def bb(self, n: int = 20, k: float = 2.0):
        return self._m(("bb", n, k), lambda: bands(self.c, n, k))

    def stoch(self):
        return self._m(("stoch",), lambda: stoch(self.h, self.l, self.c))

    def macd(self):
        return self._m(("macd",), lambda: macd(self.c))

    def donchian(self, n: int):
        return self._m(("dc", n), lambda: I.donchian_prior(self.h, self.l, n))

    def pivots(self, left: int = 2, right: int = 2) -> list[dict]:
        def calc():
            out = []
            for p in range(left, self.N - right):
                if all(self.h[p] > self.h[p - k] for k in range(1, left + 1)) and all(self.h[p] >= self.h[p + k] for k in range(1, right + 1)):
                    out.append({"kind": "H", "i": p, "price": self.h[p], "known": p + right})
                if all(self.l[p] < self.l[p - k] for k in range(1, left + 1)) and all(self.l[p] <= self.l[p + k] for k in range(1, right + 1)):
                    out.append({"kind": "L", "i": p, "price": self.l[p], "known": p + right})
            return out
        return self._m(("piv", left, right), calc)

    def swings(self, kind: str, known_by: int, left: int = 2, right: int = 2, last: int = 300) -> list[dict]:
        """Confirmed pivots of `kind` ('H'/'L') known at bar index known_by (newest last; at most `last` of them)."""
        def split():
            ps = self.pivots(left, right)
            hs = [p for p in ps if p["kind"] == "H"]
            ls = [p for p in ps if p["kind"] == "L"]
            return {"H": (hs, [p["known"] for p in hs]), "L": (ls, [p["known"] for p in ls])}
        lst, keys = self._m(("pivk", left, right), split)[kind]
        j = bisect.bisect_right(keys, min(known_by, self.n - 1))
        return lst[max(0, j - last):j]

    def b(self, i: int, tick: float, cm: dict) -> float | None:
        a = self.atr()[i] if 0 <= i < self.n else None
        if a is None:
            return None
        return max(cm.get("b_tick_mult", 2.0) * tick, cm.get("b_atr_mult", 0.10) * a)

    def vwap(self, anchor_t: float) -> list[float | None]:
        """Anchored VWAP of typical price weighted by tick volume from the first bar opening at/after anchor_t (None before it)."""
        def calc():
            out: list[float | None] = [None] * self.N
            pv = vv = 0.0
            for i in range(self.N):
                if self.t[i] < anchor_t - 1e-6:
                    continue
                w = self.tv[i]
                pv += w * (self.h[i] + self.l[i] + self.c[i]) / 3.0
                vv += w
                out[i] = pv / vv if vv > 0 else None
            return out
        return self._m(("vwap", round(anchor_t)), calc)

    def sigma(self, window: int) -> list[float | None]:
        def calc():
            lr = [0.0] + [math.log(abs(self.c[i] / self.c[i - 1])) if self.c[i - 1] and self.c[i] / self.c[i - 1] > 0 else 0.0
                          for i in range(1, self.N)]
            out: list[float | None] = [None] * self.N
            for i in range(window, self.N):
                w = lr[i - window + 1:i + 1]
                m = sum(w) / window
                out[i] = math.sqrt(sum((v - m) ** 2 for v in w) / (window - 1))
            return out
        return self._m(("sigma", window), calc)


def warm_needed(tf: str, ema_max: int, mult: int = 5) -> int:
    return ema_max * mult


def trend_up(v: TF, i: int, htf: bool) -> bool | None:
    """TrendUp(H1): close > EMA50 > EMA200 and EMA50 rising over 3 bars; TrendUp(LTF): close > EMA20 > EMA50, EMA20 rising over 3 bars.
    None = not enough history (WARMING_UP), never 'neutral'."""
    a, b = (50, 200) if htf else (20, 50)
    ea, eb = v.ema(a), v.ema(b)
    if i < 3 or i >= v.n or ea[i] is None or eb[i] is None or ea[i - 3] is None:
        return None
    return v.c[i] > ea[i] > eb[i] and ea[i] > ea[i - 3]


def regime_range(v: TF, i: int) -> bool | None:
    """Range(M15): ADX14 < 20 and |EMA20[t] - EMA20[t-5]| < 0.25 ATR14."""
    ad, e, a = v.adx()[i] if i < v.n else None, v.ema(20), v.atr()
    if ad is None or i < 5 or e[i] is None or e[i - 5] is None or a[i] is None:
        return None
    return ad < 20 and abs(e[i] - e[i - 5]) < 0.25 * a[i]


# ---------------------------------------------------------------------------------------------------- sessions (IANA, DST)
def _hm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def trading_day_start(as_of: float, tz: str = "America/New_York", start: str = "17:00") -> float:
    """UTC start of the trading day containing as_of (17:00 New York, DST via zoneinfo)."""
    z = ZoneInfo(tz)
    loc = datetime.fromtimestamp(as_of, timezone.utc).astimezone(z)
    st = datetime.combine(loc.date(), _hm(start), z)
    if loc < st:
        st = datetime.combine(loc.date() - timedelta(days=1), _hm(start), z)
    return st.astimezone(timezone.utc).timestamp()


def or_window(w: dict, as_of: float) -> tuple[float, float] | None:
    """UTC [start, end) of the most recent opening-range window of `w` whose local date is today or yesterday (start <= as_of)."""
    z = ZoneInfo(w["tz"])
    loc = datetime.fromtimestamp(as_of, timezone.utc).astimezone(z).date()
    for d in (loc, loc - timedelta(days=1)):
        if date.weekday(d) >= 5:
            continue
        a = datetime.combine(d, _hm(w["start"]), z).astimezone(timezone.utc).timestamp()
        b = datetime.combine(d, _hm(w["end"]), z).astimezone(timezone.utc).timestamp()
        if a <= as_of:
            return a, b
    return None


class Context:
    """Everything the 20 detectors read in one cycle: closed bars per TF (plain + mirror), tick, config, as_of. Built once per cycle."""

    def __init__(self, bars: dict[str, list[dict]], *, tick: float, common: dict, as_of: float, symbol: str | None = None, instrument: str = "XAUUSD"):
        self.tick, self.cm, self.as_of, self.symbol, self.instrument = tick, common, as_of, symbol, instrument
        self.raw = bars
        self._v: dict = {}
        self._prof: dict = {}

    def tf(self, name: str, mirror: bool) -> TF:
        k = (name, mirror)
        if k not in self._v:
            self._v[k] = TF(name, self.raw.get(name) or [], mirror)
            if self.replay:
                self._v[k].cut(self.as_of)
        return self._v[k]

    replay = False

    def advance(self, as_of: float) -> None:
        """Replay: move the clock; every view shows only the bars closed by as_of."""
        self.as_of = as_of
        self.replay = True
        for v in self._v.values():
            v.cut(as_of)

    def prev_day_range(self, mirror: bool) -> tuple[float | None, float | None]:
        """High / low of the completed previous trading day from visible M5 bars (view units)."""
        td = self.cm.get("trading_day") or {}
        cur = trading_day_start(self.as_of, td.get("tz", "America/New_York"), td.get("start", "17:00"))
        prev = trading_day_start(cur - 1, td.get("tz", "America/New_York"), td.get("start", "17:00"))
        m5 = self.tf("M5", mirror)
        a, b = m5.since(prev), m5.since(cur)
        if b <= a:
            return None, None
        return max(m5.h[a:b]), min(m5.l[a:b])

    def prev_session_profile(self, value_area_pct: float = 0.70, bin_ticks: int = 10) -> dict:
        """Value area of the COMPLETED previous trading day (PMW-SVP-1 on closed M5 bars, tick activity). Frozen per trading day."""
        td = self.cm.get("trading_day") or {}
        cur = trading_day_start(self.as_of, td.get("tz", "America/New_York"), td.get("start", "17:00"))
        prev = trading_day_start(cur - 1, td.get("tz", "America/New_York"), td.get("start", "17:00"))
        key = (prev, value_area_pct, bin_ticks)
        if key not in self._prof:
            from ...svp import engine as SVP
            src = self.raw.get("M5") or []
            if self.replay:                                         # only the bars of [prev, cur) matter - avoid scanning the whole history
                m5 = self.tf("M5", False)
                a, b = m5.since(prev), m5.since(cur)
                src = [x for x in src[max(0, a - 2):b + 2]]
            bars = [b for b in src if b.get("closed", True)]
            try:
                p = SVP.compute(bars, "M5", prev, cur, as_of=min(self.as_of, cur), tick=self.tick, bin_ticks=bin_ticks, value_area_pct=value_area_pct,
                                instrument=self.instrument, symbol=self.symbol, mode="SESSION", label="PMW_PREV_TRADING_DAY")
            except Exception as exc:  # noqa: BLE001 - a broken profile is NO_DATA, never a fabricated level
                p = {"status": "NO_DATA", "reason": f"{type(exc).__name__}: {exc}"[:160]}
            p = {k: v for k, v in p.items() if k != "histogram"}
            p["session_start"], p["session_end"] = iso(prev), iso(cur)
            self._prof[key] = p
        return self._prof[key]
