"""Monte Carlo of price PATHS (PMW-MC-1) for one instrument - built from closed broker bars known before the forecast time.

A simulated path is a sequence of whole bars (gap from the previous close, high / low / close relative to the open, spread), so a
plan can be checked against the path's highs and lows - not only its end point (the existing flow-context MarkovDiff simulates
close-to-close sums and is kept as the "endpoint" comparison). Variants (chosen by validation, not by complexity):
  IID     - bars drawn independently from the window (simple baseline);
  BLOCK   - moving-block bootstrap of consecutive bars (keeps short-term volatility clustering and session shape);
  REGIME  - blocks in ATR units whose start matches the current volatility regime and session hour, rescaled to the current ATR
            (filtered historical simulation); falls back to BLOCK when fewer than MIN_REGIME_BLOCKS candidates exist.

Events are explicit: for a plan (side, entry, SL, TP levels, horizon in bars) each path is walked bar by bar. Chart OHLC is Bid:
a BUY closes at Bid (TP when high >= TP, SL when low <= SL), a SELL closes at Ask = Bid + spread (TP when low + spread <= TP, SL when
high + spread >= SL). A bar that touches both TP and SL is AMBIGUOUS - the order inside it is unknown and NOT guessed: the result
gives P(TP first) conservative (ambiguous = SL first, the declared rule of the replay/labels) and optimistic, plus P(ambiguous).
Probabilities here are probabilities IN THE SIMULATED MODEL; the error from the number of paths (binomial, 95%) is not the market
uncertainty. A calibrated probability exists only when validate.py produced a calibrator on out-of-sample data of the user."""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

VERSION = "PMW-MC-1"
VARIANTS = ("IID", "BLOCK", "REGIME")
MIN_BARS = 300
MIN_REGIME_BLOCKS = 40
TF_S = {"M1": 60, "M5": 300, "M15": 900}


def _ts(x) -> float:
    return x if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class History:
    """Closed bars known at as_of, cleaned and checked. All prices in instrument price units (Bid chart)."""
    tf: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    spread: np.ndarray                      # price units; NaN when the bar has no spread value
    flags: list = field(default_factory=list)
    dropped: int = 0
    data_hash: str = ""

    @property
    def n(self) -> int:
        return len(self.c)


def history(bars: list[dict], as_of: float, tf: str = "M1", point: float = 0.01, window: int = 6000, stale_after_s: float | None = None) -> History:
    """Bars with open + tf <= as_of only (closed before the forecast - no look-ahead). Invalid OHLC dropped and counted; a stale last bar,
    gaps and jumps are flagged (the caller decides; nothing is silently repaired)."""
    step = TF_S[tf]
    rows = []
    dropped = 0
    for b in bars:
        if not (b.get("open_utc") or b.get("t")):
            dropped += 1                                    # bar without a verified UTC time (clock not measured yet)
            continue
        t = _ts(b.get("open_utc") or b.get("t"))
        if t + step > as_of + 1e-6:
            continue
        o, h, lo, c = (float(b[k]) for k in ("o", "h", "l", "c"))
        if not (o > 0 and h >= max(o, c) and lo <= min(o, c) and h >= lo and all(math.isfinite(x) for x in (o, h, lo, c))):
            dropped += 1
            continue
        sp = b.get("spread_price")
        if sp is None and b.get("spread") is not None:
            sp = float(b["spread"]) * point
        rows.append((t, o, h, lo, c, float(sp) if sp is not None else math.nan))
    rows.sort(key=lambda r: r[0])
    rows = rows[-window:]
    if not rows:
        return History(tf, *(np.zeros(0) for _ in range(6)), flags=["NO_DATA"], dropped=dropped)
    a = np.array(rows, float)
    flags = []
    gaps = np.diff(a[:, 0])
    if (gaps > 3 * 86400).any():
        flags.append("LONG_GAP_IN_WINDOW")
    stale = stale_after_s if stale_after_s is not None else 10 * step
    if as_of - (a[-1, 0] + step) > stale and not _weekend(as_of):
        flags.append("STALE_LAST_BAR")
    rng = a[:, 2] - a[:, 3]
    med = float(np.median(rng)) if len(rng) else 0.0
    jumps = np.abs(a[1:, 1] - a[:-1, 4])                                            # open vs previous close
    if med > 0 and (jumps > 25 * med).any():
        flags.append("PRICE_JUMP_GT_25_MEDIAN_RANGES")
    hsh = hashlib.sha256(a.tobytes()).hexdigest()[:16]
    return History(tf, a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5], flags=flags, dropped=dropped, data_hash=hsh)


def _weekend(t: float) -> bool:
    d = datetime.fromtimestamp(t, timezone.utc)
    return d.weekday() == 5 or (d.weekday() == 6 and d.hour < 22) or (d.weekday() == 4 and d.hour >= 21)


def _atr(h: History, n: int = 14) -> np.ndarray:
    prev = np.concatenate([[h.o[0]], h.c[:-1]])
    tr = np.maximum(h.h - h.lo, np.maximum(np.abs(h.h - prev), np.abs(h.lo - prev)))
    out = np.empty_like(tr)
    a = tr[0]
    for i, x in enumerate(tr):
        a = x if i == 0 else (a * (n - 1) + x) / n
        out[i] = a
    return out


@dataclass
class Plan:
    side: str                               # BUY | SELL
    entry: float                            # fill price (BUY: Ask, SELL: Bid)
    sl: float
    tps: list                               # price levels, ascending in profit direction
    horizon: int                            # bars of the history timeframe


def simulate(h: History, n_paths: int = 2000, horizon: int = 60, variant: str = "BLOCK", seed: int = 7, block: int = 30) -> dict:
    """Paths of `horizon` bars as arrays (n_paths, horizon): open, high, low, close relative to the last close, spread."""
    if variant not in VARIANTS:
        raise ValueError(f"UNKNOWN_VARIANT:{variant}")
    if h.n < MIN_BARS:
        raise ValueError(f"INSUFFICIENT_DATA: {h.n} świec < {MIN_BARS}")
    rng = np.random.default_rng(seed)
    prev_c = np.concatenate([[h.o[0]], h.c[:-1]])
    gap, up, dn, cl = h.o - prev_c, h.h - h.o, h.lo - h.o, h.c - h.o
    sp = np.where(np.isfinite(h.spread), h.spread, np.nan)
    n = h.n
    scale = np.ones(n)
    info: dict = {"variant": variant}
    if variant == "IID":
        idx = rng.integers(1, n, size=(n_paths, horizon))
    else:
        L = max(1, min(block, horizon))
        nb = int(math.ceil(horizon / L))
        starts_all = np.arange(1, n - L)
        starts = starts_all
        if variant == "REGIME":
            atr = _atr(h)
            ref = np.median(atr[-500:]) if n >= 500 else np.median(atr)
            reg = np.digitize(atr / max(ref, 1e-12), [0.75, 1.33])                      # LOW / NORMAL / HIGH volatility
            hour = ((h.t // 3600) % 24).astype(int)
            cur_reg, cur_hour = int(reg[-1]), int(((h.t[-1] + TF_S[h.tf]) // 3600) % 24)
            cand = starts_all[(reg[starts_all] == cur_reg) & (np.abs(((hour[starts_all] - cur_hour + 12) % 24) - 12) <= 1)]
            info.update(current_regime=["LOW", "NORMAL", "HIGH"][cur_reg], session_hour_utc=cur_hour, matching_blocks=int(len(cand)))
            if len(cand) >= MIN_REGIME_BLOCKS:
                starts = cand
                scale = atr[-1] / np.maximum(atr, 1e-12)                                 # sampled moves expressed in today's ATR
            else:
                info["fallback"] = "BLOCK (za mało bloków w tym reżimie/sesji)"
        b0 = rng.choice(starts, size=(n_paths, nb))
        idx = (b0[:, :, None] + np.arange(L)[None, None, :]).reshape(n_paths, nb * L)[:, :horizon]
        info["block"] = L
    s = scale[idx] if variant == "REGIME" and "fallback" not in info else 1.0
    g, u, d, cc = gap[idx] * s, up[idx] * s, dn[idx] * s, cl[idx] * s
    opens = np.cumsum(g + np.concatenate([np.zeros((n_paths, 1)), cc[:, :-1]], axis=1), axis=1)
    closes = opens + cc
    spr = sp[idx]
    fallback_sp = float(np.nanmedian(sp)) if np.isfinite(sp).any() else math.nan
    spr = np.where(np.isfinite(spr), spr, fallback_sp)
    return {"open": opens, "high": opens + u, "low": opens + d, "close": closes, "spread": spr, "info": info}


def _first_hit(mask: np.ndarray) -> np.ndarray:
    """Index of the first True per row, horizon (=len) when never."""
    any_ = mask.any(axis=1)
    first = mask.argmax(axis=1)
    return np.where(any_, first, mask.shape[1])


def evaluate(paths: dict, base: float, plan: Plan) -> dict:
    """Events of one plan on simulated paths (prices relative to `base` = last closed Bid close)."""
    H = min(plan.horizon, paths["close"].shape[1])
    hi, lo, sp = base + paths["high"][:, :H], base + paths["low"][:, :H], paths["spread"][:, :H]
    if plan.side == "BUY":
        sl_hit = lo <= plan.sl
        tp_hit = [hi >= tp for tp in plan.tps]
    else:
        sl_hit = hi + sp >= plan.sl
        tp_hit = [lo + sp <= tp for tp in plan.tps]
    n = hi.shape[0]
    fs = _first_hit(sl_hit)
    out = {"n_paths": n, "horizon": H, "sl_within_h": float((fs < H).mean()), "levels": []}
    for tp, m in zip(plan.tps, tp_hit):
        ft = _first_hit(m)
        tp_first = ft < fs
        same = (ft == fs) & (ft < H)                                                  # same bar: order unknown
        p_cons, p_opt, p_amb = float(tp_first.mean()), float((tp_first | same).mean()), float(same.mean())
        se = math.sqrt(max(p_cons * (1 - p_cons), 1e-12) / n)
        out["levels"].append({"tp": tp, "distance": abs(tp - plan.entry), "p_tp_before_sl_conservative": p_cons,
                              "p_tp_before_sl_optimistic": p_opt, "p_ambiguous_same_bar": p_amb, "p_tp_within_h": float((ft < H).mean()),
                              "mc_error_95": 1.96 * se, "median_bars_to_tp": float(np.median(ft[ft < H])) if (ft < H).any() else None})
    end = paths["close"][:, H - 1]
    out["end_move_quantiles"] = dict(zip(("q05", "q25", "q50", "q75", "q95"), np.quantile(end, (0.05, 0.25, 0.5, 0.75, 0.95)).round(5).tolist()))
    fav = (paths["high"][:, :H].max(axis=1) if plan.side == "BUY" else -paths["low"][:, :H].min(axis=1))
    adv = (-paths["low"][:, :H].min(axis=1) if plan.side == "BUY" else paths["high"][:, :H].max(axis=1))
    out["max_favourable_q50"] = float(np.median(fav))
    out["max_adverse_q50"] = float(np.median(adv))
    return out


def move_scenarios(paths: dict, levels=(2.5, 3.0, 5.0, 7.5, 10.0), horizon: int | None = None) -> dict:
    """P(price reaches +X / -X from the last close within the horizon) - price MOVE, not account profit; both directions."""
    H = horizon or paths["close"].shape[1]
    up = paths["high"][:, :H].max(axis=1)
    dn = -paths["low"][:, :H].min(axis=1)
    return {"horizon_bars": H, "levels_price": list(levels),
            "p_up_reach": [float((up >= x).mean()) for x in levels], "p_down_reach": [float((dn >= x).mean()) for x in levels],
            "note": "ruch ceny instrumentu (np. 2,5 USD za uncję), nie wynik rachunku"}


def run(bars: list[dict], as_of: float, plans: list[Plan] | None = None, *, tf: str = "M1", point: float = 0.01, variant: str = "BLOCK",
        n_paths: int = 2000, horizon: int = 60, seed: int = 7, synthetic: bool = False, calibrator: dict | None = None,
        levels=(2.5, 3.0, 5.0, 7.5, 10.0)) -> dict:
    t0 = time.perf_counter()
    h = history(bars, as_of, tf, point)
    base = {"version": VERSION, "tf": tf, "as_of": _iso(as_of), "variant": variant, "n_paths": n_paths, "horizon_bars": horizon, "seed": seed,
            "data": {"bars": h.n, "first": _iso(h.t[0]) if h.n else None, "last_closed_open": _iso(h.t[-1]) if h.n else None,
                     "dropped_invalid": h.dropped, "flags": h.flags, "hash": h.data_hash, "kind": "SYNTHETIC_TEST" if synthetic else "REAL_USER_DATA"},
            "probability_kind": "MODEL_SIMULATED", "calibrated": False}
    if h.n < MIN_BARS:
        return dict(base, status="INSUFFICIENT_DATA", reason=f"{h.n} zamkniętych świec {tf} < {MIN_BARS}")
    paths = simulate(h, n_paths, horizon, variant, seed)
    last = float(h.c[-1])
    res = dict(base, status="OK", last_close=last, sim=paths["info"], scenarios=move_scenarios(paths, levels, horizon), plans=[])
    for p in plans or []:
        ev = evaluate(paths, last, p)
        if calibrator and calibrator.get("status") == "ACTIVE" and calibrator.get("variant") == variant and not synthetic:
            from .validate import apply_calibrator
            for lv in ev["levels"]:
                lv["p_calibrated"] = apply_calibrator(calibrator, lv["p_tp_before_sl_conservative"])
            ev["calibrated_by"] = calibrator.get("run_id")
        res["plans"].append({"side": p.side, "entry": p.entry, "sl": p.sl, "tps": p.tps, **ev})
    if any("p_calibrated" in lv for pl in res["plans"] for lv in pl["levels"]):
        res["calibrated"] = True
    res["compute_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if synthetic:
        res["warning"] = "DANE SYNTETYCZNE – wynik nie może zasilać prawdziwych decyzji"
    if h.flags:
        res["warning"] = (res.get("warning", "") + " " + ", ".join(h.flags)).strip()
    return res
