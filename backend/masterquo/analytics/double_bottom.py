"""Double Bottom structural validator (DB-1.0.0) + causal scanner.

Own implementation of an explicit specification. The functional idea follows the MQL5 article series (Part 84 structural
validation, Part 85 review of one validated sample, Part 86 library-wide validation); NO code of those articles is copied
(their source was not used). Statuses and their meaning:

  INVALID    no admissible pair of bottoms (reason given) - not a pattern
  CANDIDATE  admissible pair, no decisive close yet after the second bottom
  CONFIRMED  the FIRST decisive close after the second bottom is ABOVE the neckline
  FAILED     the FIRST decisive close after the second bottom is BELOW the lower of the two bottoms
The first decisive close fixes the classification; a later false breakout never changes it (it may change a separate
scenario state, which is not stored here). The geometry score is a shape-compliance measure, NOT a probability of profit.

Rules (parameters in DEFAULT, all recorded in the result and its config_hash):
  pivots: a low at i is a pivot if it is the minimum of [i-left, i+right]; it becomes KNOWN only at the close of bar i+right
  pair:   separation between bottoms in [min_separation, max_separation] bars
  neckline = highest high strictly between the bottoms; depth = neckline - min(bottom1, bottom2)
  depth >= min_depth_pct % of price (mode SOURCE_COMPAT) and, in mode EXTENDED (DB-1.1.0-EXT), also >= min_depth_atr * ATR14
  similarity |b1 - b2| <= max_bottom_diff_frac * depth
  symmetry: bars(b1 -> neck) / bars(neck -> b2) within [1/max_asymmetry, max_asymmetry]
  prior decline: the highest high in `prior_bars` before b1 is >= b1 + prior_move_frac * depth
  pair choice (deterministic): most recent second bottom, then the deepest structure, then the earliest first bottom
pattern_id = hash(symbol, tf, time of b1, time of b2, rules version) - stable for de-duplication of overlays and alerts.
Modes: `offline_full_sample` (validate a stored sample with all its bars) and `causal_as_of` (only bars closed at t; pivots
only after their right-side bars are closed; every state change is an event with its available_at).
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from . import contract
from .ta import TF_SEC, atr14

VERSION = "DB-1.0.0"
VERSION_EXT = "DB-1.1.0-EXT"
VERSION_BUF = "DB-1.2.0-BUF"          # PMW-UPD-07 R07: explicit breakout / failure buffers (x ATR14) and pair choice; old versions unchanged
DEFAULT = {"mode": "SOURCE_COMPAT", "pivot_left": 3, "pivot_right": 3, "min_separation": 5, "max_separation": 60, "min_depth_pct": 0.05,
           "min_depth_atr": 1.0, "max_bottom_diff_frac": 0.25, "max_asymmetry": 3.0, "prior_bars": 20, "prior_move_frac": 0.5}
STATUSES = ("INVALID", "CANDIDATE", "CONFIRMED", "FAILED")


def _iso_plus(t: str, sec: int) -> str:
    v = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() + sec
    return datetime.fromtimestamp(v, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_bars(bars: list[dict]) -> str | None:
    """Data errors are NOT pattern failures: they produce an execution error result."""
    if not bars:
        return "EMPTY_SAMPLE"
    prev = None
    for b in bars:
        try:
            o, h, lo, c = float(b["o"]), float(b["h"]), float(b["l"]), float(b["c"])
        except (KeyError, TypeError, ValueError):
            return "MALFORMED_BAR"
        if not all(map(lambda v: v == v and abs(v) != float("inf"), (o, h, lo, c))) or h < max(o, c) or lo > min(o, c):
            return f"INVALID_OHLC at {b.get('open_utc')}"
        if prev is not None and b["open_utc"] <= prev:
            return f"UNSORTED_OR_DUPLICATE at {b['open_utc']}"
        prev = b["open_utc"]
    return None


def pivot_lows(lo: list[float], left: int, right: int, upto: int | None = None) -> list[int]:
    """Pivot lows KNOWN at bar index `upto` (i + right <= upto)."""
    n = len(lo) if upto is None else upto + 1
    out = []
    for i in range(left, n - right):
        w = lo[i - left: i + right + 1]
        if lo[i] == min(w) and (not left or lo[i] < min(lo[i - left: i])):       # ties: the earliest bar of a flat bottom
            out.append(i)
    return out


def validate(bars: list[dict], cfg: dict | None = None, *, symbol: str | None = None, tf: str | None = None, upto: int | None = None,
             mode_label: str = "offline_full_sample") -> dict:
    """Validate the structure in `bars` (indices 0..upto when causal). Returns the contract with values: status, coordinates,
    measurements, reason. Coordinates are the exact bars used - the renderer never searches again."""
    t0 = time.perf_counter()
    cfg = {**DEFAULT, **(cfg or {})}
    version = VERSION_BUF if cfg["mode"] == "BUFFERED" else VERSION_EXT if cfg["mode"] == "EXTENDED" else VERSION
    if cfg["mode"] not in ("SOURCE_COMPAT", "EXTENDED", "BUFFERED") or cfg.get("pair_choice", "RECENT_DEEPEST_EARLIEST") not in ("RECENT_DEEPEST_EARLIEST", "DEEPEST_RECENT"):
        return contract.result("double_bottom", version, cfg, symbol=symbol, tf=tf, bars=[], status="error", reason="CONFIG_INVALID", t0=t0,
                               extra={"mode": mode_label})
    # only the passed PREFIX is validated / analysed: a damaged future bar can never change an earlier result
    bad = check_bars(bars if upto is None else bars[: upto + 1])
    if bad:
        return contract.result("double_bottom", version, cfg, symbol=symbol, tf=tf, bars=bars if isinstance(bars, list) else [], status="error",
                               reason=f"DATA_ERROR: {bad}", t0=t0, extra={"mode": mode_label})
    end = len(bars) - 1 if upto is None else upto
    h, lo, c = [b["h"] for b in bars], [b["l"] for b in bars], [b["c"] for b in bars]
    a = atr14(h, lo, c) if cfg["mode"] in ("EXTENDED", "BUFFERED") else None
    piv = pivot_lows(lo, int(cfg["pivot_left"]), int(cfg["pivot_right"]), end)
    R = int(cfg["pivot_right"])
    cands, rejects = [], {}

    def rej(k):
        rejects[k] = rejects.get(k, 0) + 1
    for x in range(len(piv)):
        for y in range(x + 1, len(piv)):
            i1, i2 = piv[x], piv[y]
            sep = i2 - i1
            if sep < cfg["min_separation"]:
                rej("SEPARATION_TOO_SMALL")
                continue
            if sep > cfg["max_separation"]:
                rej("SEPARATION_TOO_LARGE")
                continue
            inner = range(i1 + 1, i2)
            ineck = max(inner, key=lambda k: (h[k], -k))
            neck = h[ineck]
            low = min(lo[i1], lo[i2])
            depth = neck - low
            if depth <= 0 or depth < cfg["min_depth_pct"] / 100.0 * low:
                rej("DEPTH_TOO_SMALL")
                continue
            if cfg["mode"] == "EXTENDED" and (a[i2] is None or depth < cfg["min_depth_atr"] * a[i2]):
                rej("DEPTH_BELOW_ATR")
                continue
            diff = abs(lo[i1] - lo[i2])
            if diff > cfg["max_bottom_diff_frac"] * depth:
                rej("BOTTOMS_NOT_SIMILAR")
                continue
            l_, r_ = ineck - i1, i2 - ineck
            asym = max(l_, r_) / max(1, min(l_, r_))
            if asym > cfg["max_asymmetry"]:
                rej("ASYMMETRIC")
                continue
            pb = range(max(0, i1 - int(cfg["prior_bars"])), i1)
            prior_high = max((h[k] for k in pb), default=None)
            if prior_high is None or prior_high < lo[i1] + cfg["prior_move_frac"] * depth:
                rej("NO_PRIOR_DECLINE")
                continue
            # rule: the second bottom must not be undercut decisively between the bottoms (only lows between pivots)
            cands.append({"i1": i1, "i2": i2, "ineck": ineck, "neck": neck, "low": low, "depth": depth, "diff": diff, "asym": asym, "sep": sep,
                          "prior_high": prior_high})
    if not cands:
        why = max(rejects, key=rejects.get) if rejects else ("NO_PIVOT_PAIR" if len(piv) < 2 else "NO_ADMISSIBLE_PAIR")
        return contract.result("double_bottom", version, cfg, symbol=symbol, tf=tf, bars=bars[: end + 1], status="ready", t0=t0,
                               values={"status": "INVALID", "reason": why, "rejections": rejects, "pivots": len(piv), "coordinates": None},
                               tf_seconds=TF_SEC.get(tf or ""), extra={"mode": mode_label})
    order = (lambda z: (-z["depth"], -z["i2"], z["i1"])) if cfg.get("pair_choice") == "DEEPEST_RECENT" else (lambda z: (-z["i2"], -z["depth"], z["i1"]))
    best = sorted(cands, key=order)[0]
    i1, i2 = best["i1"], best["i2"]
    status, ev = "CANDIDATE", None
    buf = cfg["mode"] == "BUFFERED"
    for k in range(i2 + 1, end + 1):
        bb = (float(cfg.get("breakout_buffer_atr", 0.1)) * (a[k] or 0.0)) if buf else 0.0
        fb = (float(cfg.get("failure_buffer_atr", 0.1)) * (a[k] or 0.0)) if buf else 0.0
        if c[k] > best["neck"] + bb:
            status, ev = "CONFIRMED", k
            break
        if c[k] < best["low"] - fb:
            status, ev = "FAILED", k
            break
    tsec = TF_SEC.get(tf or "", 0)
    T = lambda k: bars[k]["open_utc"]  # noqa: E731
    known2 = i2 + R
    score = max(0.0, 1.0 - best["diff"] / (cfg["max_bottom_diff_frac"] * best["depth"])) * 0.5 + max(0.0, 1.0 - (best["asym"] - 1) / (cfg["max_asymmetry"] - 1 or 1)) * 0.5
    pid = "DB-" + hashlib.sha256(f"{symbol}|{tf}|{T(i1)}|{T(i2)}|{version}".encode()).hexdigest()[:12]
    rp = lambda v: round(float(v), 5)  # noqa: E731
    coords = {"bottom1": {"index": i1, "time": T(i1), "price": rp(lo[i1])}, "bottom2": {"index": i2, "time": T(i2), "price": rp(lo[i2])},
              "neckline": {"index": best["ineck"], "time": T(best["ineck"]), "price": rp(best["neck"])},
              "decisive": None if ev is None else {"index": ev, "time": T(ev), "close": rp(c[ev]), "kind": "BREAK_ABOVE_NECKLINE" if status == "CONFIRMED" else "BREAK_BELOW_BOTTOMS"}}
    avail = {"bottom2_pivot_known_at": _iso_plus(T(known2), tsec) if known2 <= end and tsec else None,
             "decisive_known_at": _iso_plus(T(ev), tsec) if ev is not None and tsec else None}
    # the result is usable only after max(pivot known, decisive bar closed); the historical decisive coordinate is kept as is
    known_list = [x for x in (avail["bottom2_pivot_known_at"], avail["decisive_known_at"]) if x]
    usable_at = max(known_list) if known_list and avail["bottom2_pivot_known_at"] else None
    flags = []
    if ev is not None and ev < known2:
        flags.append("DECISIVE_EVENT_PRECEDED_RECOGNITION")
    vals = {"status": status, "pattern_id": pid, "coordinates": coords, "available": avail, "usable_at": usable_at, "flags": flags,
            "decisive_event_time": T(ev) if ev is not None else None,
            "measurements": {"depth": round(best["depth"], 5), "depth_pct": round(100 * best["depth"] / best["low"], 4), "bottom_diff": round(best["diff"], 5),
                             "bottom_diff_frac": round(best["diff"] / best["depth"], 4), "separation_bars": best["sep"], "asymmetry": round(best["asym"], 3),
                             "prior_high": rp(best["prior_high"])},
            "geometry_score": round(score, 3), "score_note": "zgodność kształtu – nie prawdopodobieństwo zysku",
            "hypotheses": {"retest_zone": [round(best["neck"] - 0.25 * best["depth"], 5), round(best["neck"], 5)],
                           "measured_move_target": round(best["neck"] + best["depth"], 5), "note": "hipotezy, nie gwarantowany ruch"},
            "reason": {"CONFIRMED": "pierwsze rozstrzygające zamknięcie powyżej neckline", "FAILED": "pierwsze rozstrzygające zamknięcie poniżej dołków",
                       "CANDIDATE": "brak rozstrzygającego zamknięcia po drugim dołku"}[status],
            "alternatives": len(cands), "rejections": rejects}
    r = contract.result("double_bottom", version, cfg, symbol=symbol, tf=tf, bars=bars[: end + 1], status="ready", values=vals, t0=t0,
                        tf_seconds=TF_SEC.get(tf or ""), extra={"mode": mode_label})
    if mode_label == "causal_as_of":
        r["available_at"] = r["as_of"]
    return r


def scan_causal(bars: list[dict], cfg: dict | None = None, *, symbol: str | None = None, tf: str | None = None, lookback: int = 150) -> dict:
    """Current structure from the last `lookback` CLOSED bars only (live / replay step). Same validator, mode causal_as_of."""
    w = bars[-lookback:]
    return validate(w, cfg, symbol=symbol, tf=tf, mode_label="causal_as_of")
