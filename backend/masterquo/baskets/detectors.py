"""Shared detectors of the 90-strategy baskets (spec section 4) - computed ONCE per market context / timeframe / closed bar and shared
by every strategy (DET-1). Bars: closed only, oldest first, {t, o, h, l, c, tv, v?}. Index i = the last closed signal bar.
Nothing here reads a bar after i: pivots are usable only from confirmed_at = pivot + 2, levels / zones are frozen at detection,
percentiles use observations BEFORE the evaluated bar.

Conventions (DET-1, versioned): ATR14 Wilder; b = max(2 * quantum, 0.10 * ATR); BB20/2 with population std (ddof 0);
ADX14 Wilder; RSI2 Wilder; EMA seeded with the first value; RVOL = real volume / median of the previous 20 (None without real volume).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

VERSION = "DET-1"


def ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty_like(x, dtype=float)
    if not len(x):
        return out
    out[0] = x[0]
    for k in range(1, len(x)):
        out[k] = a * x[k] + (1 - a) * out[k - 1]
    return out


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = np.nanmean(x[:n])
    for k in range(n, len(x)):
        out[k] = (out[k - 1] * (n - 1) + x[k]) / n
    return out


def rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up, dn = wilder(np.maximum(d, 0), n), wilder(np.maximum(-d, 0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = up / dn
        out = 100 - 100 / (1 + rs)
    out[(dn == 0) & (up > 0)] = 100.0
    out[(dn == 0) & (up == 0)] = 50.0
    return out


@dataclass
class Pivot:
    k: int                    # bar index of the pivot
    price: float
    kind: str                 # "H" / "L"
    confirmed_at: int         # k + 2: first bar at whose close the pivot is known


@dataclass
class Feat:
    """Feature set of one context / TF at the last closed bar. Arrays cover the whole window (oldest first); every accessor takes
    the evaluation index and only looks at data <= that index."""
    bars: list
    quantum: float
    o: np.ndarray = field(init=False)
    h: np.ndarray = field(init=False)
    l: np.ndarray = field(init=False)
    c: np.ndarray = field(init=False)
    t: np.ndarray = field(init=False)

    def __post_init__(self):
        b = self.bars
        self.t = np.array([float(x["t"]) for x in b])
        self.o, self.h, self.l, self.c = (np.array([float(x[k]) for x in b]) for k in "ohlc")
        self.v = np.array([float(x["v"]) if x.get("v") is not None else np.nan for x in b])          # REAL volume (None in FX / OTC)
        self.tv = np.array([float(x.get("tv") or 0.0) for x in b])                                    # tick activity (MT5)
        n = len(b)
        self.n = n
        tr = np.maximum(self.h - self.l, np.maximum(np.abs(self.h - np.roll(self.c, 1)), np.abs(self.l - np.roll(self.c, 1))))
        if n:
            tr[0] = self.h[0] - self.l[0]
        self.tr = tr
        self.atr = wilder(tr, 14)
        self.ema9, self.ema20, self.ema21, self.ema50 = ema(self.c, 9), ema(self.c, 20), ema(self.c, 21), ema(self.c, 50)
        self.rsi2 = rsi(self.c, 2)
        self._adx = None
        self._piv = None

    # ------------------------------------------------------------------ basics
    @property
    def i(self) -> int:
        return self.n - 1

    def A(self, i: int | None = None) -> float | None:
        i = self.i if i is None else i
        v = self.atr[i] if 0 <= i < self.n else np.nan
        return float(v) if np.isfinite(v) and v > 0 else None

    def b(self, i: int | None = None) -> float | None:
        a = self.A(i)
        return None if a is None else max(2 * self.quantum, 0.10 * a)

    def HH(self, n: int, i: int | None = None) -> float | None:
        i = self.i if i is None else i
        return float(self.h[i - n:i].max()) if i - n >= 0 else None

    def LL(self, n: int, i: int | None = None) -> float | None:
        i = self.i if i is None else i
        return float(self.l[i - n:i].min()) if i - n >= 0 else None

    def body(self, i: int) -> float:
        return abs(self.c[i] - self.o[i])

    def bull(self, i: int) -> bool:
        return self.c[i] > self.o[i]

    def bear(self, i: int) -> bool:
        return self.c[i] < self.o[i]

    def close_pos(self, i: int) -> float:
        r = self.h[i] - self.l[i]
        return 0.5 if r <= 0 else (self.c[i] - self.l[i]) / r

    def displacement(self, i: int, side: int, k_body: float = 1.0, extreme: float = 0.2) -> bool:
        a = self.A(i)
        if a is None:
            return False
        if side > 0:
            return self.bull(i) and self.body(i) >= k_body * a and self.close_pos(i) >= 1 - extreme
        return self.bear(i) and self.body(i) >= k_body * a and self.close_pos(i) <= extreme

    # ------------------------------------------------------------------ swings / structure
    def pivots(self) -> list[Pivot]:
        if self._piv is None:
            out = []
            h, l = self.h, self.l
            for k in range(2, self.n - 2):
                if h[k] > max(h[k - 1], h[k - 2]) and h[k] >= max(h[k + 1], h[k + 2]):
                    out.append(Pivot(k, float(h[k]), "H", k + 2))
                if l[k] < min(l[k - 1], l[k - 2]) and l[k] <= min(l[k + 1], l[k + 2]):
                    out.append(Pivot(k, float(l[k]), "L", k + 2))
            self._piv = out
        return self._piv

    def swings(self, i: int, kind: str, n: int = 4) -> list[Pivot]:
        """Last n pivots of kind confirmed at or before bar i (newest last)."""
        return [p for p in self.pivots() if p.kind == kind and p.confirmed_at <= i][-n:]

    def trend(self, i: int | None = None) -> tuple[int, str]:
        """+1 / -1 / 0 from the two last confirmed HH/HL or LH/LL sequences, else the declared EMA20/50 + EMA50 slope variant."""
        i = self.i if i is None else i
        hs, ls = self.swings(i, "H", 2), self.swings(i, "L", 2)
        if len(hs) == 2 and len(ls) == 2:
            if hs[1].price > hs[0].price and ls[1].price > ls[0].price:
                return 1, "SWINGS_HH_HL"
            if hs[1].price < hs[0].price and ls[1].price < ls[0].price:
                return -1, "SWINGS_LH_LL"
        if i >= 52:
            up = self.ema20[i] > self.ema50[i] and self.ema50[i] > self.ema50[i - 3]
            dn = self.ema20[i] < self.ema50[i] and self.ema50[i] < self.ema50[i - 3]
            return (1 if up else -1 if dn else 0), "EMA20_50"
        return 0, "WARMUP"

    def structure_break(self, i: int, side: int) -> dict | None:
        """BOS / CHoCH at bar i: close beyond the last confirmed swing (H for side +1) by b. CHoCH when the structure before i was
        opposite. Returns {kind, level, pivot_k} or None."""
        b = self.b(i)
        if b is None:
            return None
        sw = self.swings(i, "H" if side > 0 else "L", 1)
        if not sw:
            return None
        lvl = sw[-1].price
        broke = self.c[i] > lvl + b if side > 0 else self.c[i] < lvl - b
        prev = self.c[i - 1] <= lvl + b if side > 0 else self.c[i - 1] >= lvl - b
        if not (broke and prev):
            return None
        tr, _ = self.trend(i - 1)
        return {"kind": "CHOCH" if tr == -side else "BOS", "level": lvl, "pivot_k": sw[-1].k, "at": i}

    def last_break(self, i: int, side: int, within: int, kinds=("BOS", "CHOCH"), start: int | None = None) -> dict | None:
        lo = max(1, i - within if start is None else start)
        for k in range(i, lo - 1, -1):
            sb = self.structure_break(k, side)
            if sb and sb["kind"] in kinds:
                return sb
        return None

    def sweep(self, i: int, level: float, side: int) -> bool:
        """side +1: low pierces level by b and the close returns above it (sweep of sell-side liquidity)."""
        b = self.b(i)
        if b is None:
            return False
        return (self.l[i] < level - b and self.c[i] > level) if side > 0 else (self.h[i] > level + b and self.c[i] < level)

    def swept_swing(self, i: int, side: int, within: int) -> tuple[int, float] | None:
        """Newest bar j in (i-within, i] that swept the last swing (L for side +1) confirmed before j."""
        for j in range(i, max(2, i - within), -1):
            sw = self.swings(j - 1, "L" if side > 0 else "H", 1)
            if sw and self.sweep(j, sw[-1].price, side):
                return j, sw[-1].price
        return None

    def equal_levels(self, i: int, side: int) -> float | None:
        """EQL (side +1) / EQH: two confirmed pivots >= 3 bars apart, |diff| <= max(2q, 0.10 A) -> the level (the lower / higher)."""
        a = self.A(i)
        if a is None:
            return None
        tol = max(2 * self.quantum, 0.10 * a)
        ps = self.swings(i, "L" if side > 0 else "H", 6)
        for x in range(len(ps) - 1, 0, -1):
            for y in range(x - 1, -1, -1):
                if abs(ps[x].k - ps[y].k) >= 3 and abs(ps[x].price - ps[y].price) <= tol:
                    return min(ps[x].price, ps[y].price) if side > 0 else max(ps[x].price, ps[y].price)
        return None

    # ------------------------------------------------------------------ zones
    def fvgs(self, i: int, side: int, within: int = 30, need_disp: bool = False) -> list[dict]:
        """FVGs formed at bars t in [i-within, i] (available after close[t]); bullish: low[t] > high[t-2] -> zone [high[t-2], low[t]]."""
        out = []
        for t in range(max(2, i - within), i + 1):
            if side > 0 and self.l[t] > self.h[t - 2]:
                z = {"t": t, "lo": float(self.h[t - 2]), "hi": float(self.l[t]), "side": 1}
            elif side < 0 and self.h[t] < self.l[t - 2]:
                z = {"t": t, "lo": float(self.h[t]), "hi": float(self.l[t - 2]), "side": -1}
            else:
                continue
            if need_disp and not self.displacement(t - 1, side):
                continue
            out.append(z)
        return out

    def order_block(self, disp_i: int, side: int) -> dict | None:
        """Last opposite candle in the 5 bars before the displacement bar disp_i (bullish OB = last bearish candle)."""
        for k in range(disp_i - 1, max(-1, disp_i - 6), -1):
            if (side > 0 and self.bear(k)) or (side < 0 and self.bull(k)):
                return {"k": k, "lo": float(self.l[k]), "hi": float(self.h[k]), "mid": float((self.l[k] + self.h[k]) / 2), "side": side}
        return None

    def touched(self, k: int, lo: float, hi: float) -> bool:
        return self.l[k] <= hi and self.h[k] >= lo

    def confirmed_retest(self, k: int, lo: float, hi: float, side: int, invalid: float) -> bool:
        """Spec 4.11: bar k touches the zone, does not close beyond the invalidation, closes bullish on the continuation side."""
        if not self.touched(k, lo, hi):
            return False
        if side > 0:
            return self.c[k] > invalid and self.bull(k) and self.c[k] >= lo
        return self.c[k] < invalid and self.bear(k) and self.c[k] <= hi

    def dealing_range(self, i: int) -> dict | None:
        hs, ls = self.swings(i, "H", 1), self.swings(i, "L", 1)
        if not hs or not ls:
            return None
        hi, lo = hs[-1].price, ls[-1].price
        if hi <= lo:
            return None
        return {"hi": hi, "lo": lo, "mid": (hi + lo) / 2}

    # ------------------------------------------------------------------ oscillators / bands
    def adx14(self) -> np.ndarray:
        if self._adx is None:
            up = np.diff(self.h, prepend=self.h[0])
            dn = -np.diff(self.l, prepend=self.l[0])
            pdm = np.where((up > dn) & (up > 0), up, 0.0)
            ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
            atr = wilder(self.tr, 14)
            with np.errstate(divide="ignore", invalid="ignore"):
                pdi = 100 * wilder(pdm, 14) / atr
                ndi = 100 * wilder(ndm, 14) / atr
                dx = 100 * np.abs(pdi - ndi) / (pdi + ndi)
            self._adx = wilder(np.nan_to_num(dx, nan=0.0), 14)
        return self._adx

    def ADX(self, i: int) -> float | None:
        v = self.adx14()[i]
        return float(v) if np.isfinite(v) else None

    def bb(self, i: int, n: int = 20, k: float = 2.0) -> dict | None:
        if i + 1 < n:
            return None
        w = self.c[i + 1 - n:i + 1]
        m, sd = float(w.mean()), float(w.std(ddof=0))
        return {"mid": m, "up": m + k * sd, "lo": m - k * sd, "bw": (2 * k * sd) / m if m > 0 else None}

    def rvol(self, i: int) -> float | None:
        if i < 20 or not np.isfinite(self.v[i - 20:i + 1]).all():
            return None
        med = float(np.median(self.v[i - 20:i]))
        return float(self.v[i]) / med if med > 0 else None

    def vwap(self, i: int, anchor_t: float, use_tick_proxy: bool = False) -> tuple[float | None, str]:
        """VWAP from anchor_t to bar i on typical price. Real volume, or the declared TICK_ACTIVITY_PROXY (FX) when allowed.
        Partial history up to the anchor -> None (no unmarked VWAP from incomplete data)."""
        idx = [k for k in range(i + 1) if self.t[k] >= anchor_t]
        if not idx or self.t[0] > anchor_t:
            return None, "INCOMPLETE_HISTORY"
        vol = self.v if not use_tick_proxy else self.tv
        w = vol[idx]
        if not np.isfinite(w).all() or w.sum() <= 0:
            return None, "NO_VOLUME"
        tp = (self.h[idx] + self.l[idx] + self.c[idx]) / 3
        return float((tp * w).sum() / w.sum()), ("TICK_ACTIVITY_PROXY_VWAP" if use_tick_proxy else "REAL_VOLUME_VWAP")

    def pct_rank_before(self, arr: np.ndarray, i: int, lookback: int) -> float | None:
        """Percentile rank of arr[i] among the `lookback` observations BEFORE i (no future)."""
        if i - lookback < 0:
            return None
        ref = arr[i - lookback:i]
        ref = ref[np.isfinite(ref)]
        if len(ref) < lookback * 0.9:
            return None
        return float((ref < arr[i]).mean())


def build(bars: list[dict], quantum: float) -> Feat:
    return Feat(bars, float(quantum or 0.0))


def beta(ret_x: np.ndarray, ret_h: np.ndarray) -> dict:
    """beta_XH = Cov(r_X, r_H) / Var(r_H) on synchronised closed returns (spec 9.1); None when variance is zero / data short."""
    if len(ret_x) != len(ret_h) or len(ret_x) < 20:
        return {"beta": None, "corr": None, "n": len(ret_x), "reason": "ZA_MALO_ZWROTOW"}
    vh = float(np.var(ret_h, ddof=1))
    if vh <= 0:
        return {"beta": None, "corr": None, "n": len(ret_x), "reason": "ZEROWA_WARIANCJA"}
    cov = float(np.cov(ret_x, ret_h, ddof=1)[0, 1])
    sx = float(np.std(ret_x, ddof=1))
    corr = cov / (sx * math.sqrt(vh)) if sx > 0 else None
    return {"beta": cov / vh, "corr": corr, "n": len(ret_x), "reason": None}


def sync_returns(a: list[dict], b: list[dict], n: int) -> tuple[np.ndarray, np.ndarray]:
    """Log returns of the bars common to both series (same open time), the last n."""
    bm = {float(x["t"]): float(x["c"]) for x in b}
    common = [(float(x["t"]), float(x["c"]), bm[float(x["t"])]) for x in a if float(x["t"]) in bm]
    common = common[-(n + 1):]
    if len(common) < 3:
        return np.array([]), np.array([])
    ca, cb = np.array([x[1] for x in common]), np.array([x[2] for x in common])
    if (ca <= 0).any() or (cb <= 0).any():
        return np.array([]), np.array([])
    return np.diff(np.log(ca)), np.diff(np.log(cb))
