"""Event ingestion, validation, features and unit sequences (PMW-MM-EVENTS-1) - shared by the event-driven engine, STFS and STE-FlowNet.

Ingestion policy (identical for live and replay): events are accepted in ARRIVAL order and never re-sorted. Rejected: non-finite, bid <= 0,
ask < bid (crossed), exact duplicate of the previous accepted event (same t, bid, ask), late (t < last accepted t). Equal timestamps with
different quotes are accepted (MT5 has several quotes per ms). A gap > gap_reset_s or a symbol change starts a new SEGMENT: recurrent /
stack state is reset at segment boundaries in training and inference alike. Source time (t) and receive time (received_at) are kept.

Per accepted event e (features use events <= e only):
  dt_log   = log1p(t_e - t_{e-1})                    TIMING
  dmid     = mid_e - mid_{e-1}  (price units)         PRICE      mid = (bid+ask)/2 (bid/ask valid)
  abs_dmid = |dmid|                                   PRICE
  sgn      = sign(dmid) - an INFERRED polarity (no aggressor side in MT5 quote ticks)     PRICE
  spread   = ask - bid, dspread = change              SPREAD     (NaN source -> 0 with spread_ok = 0: marked unavailable)
  act_log  = log1p(activity)                          ACTIVITY   (tick count of a bar for BAR_CLOSE_EVENTS, 1 for quote ticks)
  spread_ok                                           QUALITY
Scaler: per-feature median / IQR fitted on TRAINING units only.
Units: count-based blocks of `n` consecutive events inside one segment; a unit is available at its last event time.
"""
from __future__ import annotations

import math

import numpy as np

VERSION = "PMW-MM-EVENTS-1"
FEATURES = ["dt_log", "dmid", "abs_dmid", "sgn", "spread", "dspread", "act_log", "spread_ok"]
GROUPS = {"TIMING": ["dt_log"], "PRICE": ["dmid", "abs_dmid", "sgn"], "SPREAD": ["spread", "dspread", "spread_ok"], "ACTIVITY": ["act_log"]}


class Ingestor:
    def __init__(self, symbol: str, gap_reset_s: float = 900.0):
        self.symbol, self.gap = symbol, gap_reset_s
        self.last = None
        self.segment = 0
        self.counts = {"accepted": 0, "non_finite": 0, "non_positive": 0, "crossed": 0, "duplicate": 0, "late": 0, "gap_reset": 0, "symbol_change": 0}

    def push(self, ev: dict) -> dict:
        if ev.get("symbol", self.symbol) != self.symbol:
            self.counts["symbol_change"] += 1
            self.symbol, self.last, self.segment = ev["symbol"], None, self.segment + 1
        t, bid, ask = ev.get("t"), ev.get("bid"), ev.get("ask")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (t, bid, ask)):
            self.counts["non_finite"] += 1
            return {"status": "REJECTED", "reason": "NON_FINITE"}
        if bid <= 0 or ask <= 0:
            self.counts["non_positive"] += 1
            return {"status": "REJECTED", "reason": "NON_POSITIVE"}
        if ask < bid:
            self.counts["crossed"] += 1
            return {"status": "REJECTED", "reason": "CROSSED"}
        if self.last is not None:
            if t < self.last["t"]:
                self.counts["late"] += 1
                return {"status": "REJECTED", "reason": "LATE"}
            if t == self.last["t"] and bid == self.last["bid"] and ask == self.last["ask"]:
                self.counts["duplicate"] += 1
                return {"status": "REJECTED", "reason": "DUPLICATE"}
            if t - self.last["t"] > self.gap:
                self.counts["gap_reset"] += 1
                self.segment += 1
        self.last = {"t": float(t), "bid": float(bid), "ask": float(ask)}
        self.counts["accepted"] += 1
        return {"status": "ACCEPTED", "segment": self.segment, "received_at": ev.get("received_at", t)}


def from_arrays(ev: dict, symbol: str, gap_reset_s: float = 900.0) -> dict:
    """Run a source event dict (data.events_from_*) through the Ingestor; spread NaN is kept as 'unavailable'."""
    ing = Ingestor(symbol, gap_reset_s)
    keep, seg = [], []
    sp_nan = ~np.isfinite(ev["spread"])
    bid = np.where(sp_nan, ev["mid"], ev["bid"])
    ask = np.where(sp_nan, ev["mid"], ev["ask"])
    for k in range(len(ev["t"])):
        r = ing.push({"t": float(ev["t"][k]), "bid": float(bid[k]), "ask": float(ask[k]), "received_at": float(ev["received_at"][k])})
        if r["status"] == "ACCEPTED":
            keep.append(k)
            seg.append(r["segment"])
    k = np.asarray(keep, dtype=int)
    return {"t": ev["t"][k], "mid": ev["mid"][k], "spread": ev["spread"][k], "activity": ev["activity"][k], "segment": np.asarray(seg, dtype=int),
            "counts": ing.counts, "source": ev["source"], "limits": ev.get("limits")}


def featurize(acc: dict) -> dict:
    t, mid, sp, act, seg = acc["t"], acc["mid"], acc["spread"], acc["activity"], acc["segment"]
    n = len(t)
    F = np.zeros((n, len(FEATURES)))
    new_seg = np.r_[True, seg[1:] != seg[:-1]]
    dt = np.r_[np.nan, np.diff(t)]
    dm = np.r_[np.nan, np.diff(mid)]
    spok = np.isfinite(sp)
    spv = np.where(spok, sp, 0.0)
    dsp = np.r_[0.0, np.diff(spv)]
    dsp[~spok | ~np.r_[True, spok[:-1]]] = 0.0
    F[:, 0] = np.log1p(np.where(new_seg, np.nan, dt))
    F[:, 1] = np.where(new_seg, np.nan, dm)
    F[:, 2] = np.abs(F[:, 1])
    F[:, 3] = np.sign(F[:, 1])
    F[:, 4] = spv
    F[:, 5] = dsp
    F[:, 6] = np.log1p(np.maximum(act, 0))
    F[:, 7] = spok.astype(float)
    valid = np.isfinite(F).all(axis=1)                               # the first event of every segment has no delta
    return {"F": F, "valid": valid, "names": FEATURES}


class Scaler:
    def __init__(self):
        self.med = self.iqr = None

    def fit(self, X: np.ndarray):
        X = X.reshape(-1, X.shape[-1])
        self.med = np.median(X, axis=0)
        q75, q25 = np.percentile(X, [75, 25], axis=0)
        tol = 1e-9 * np.maximum(1.0, np.abs(self.med))
        sd = np.std(X, axis=0)
        # degenerate (constant) feature -> scale 1: a near-zero scale would amplify float round-off into large inputs
        self.iqr = np.where(q75 - q25 > tol, q75 - q25, np.where(sd > tol, sd, 1.0))
        for j, n in enumerate(FEATURES):
            if n in ("sgn", "spread_ok"):                            # categorical-like: not rescaled
                self.med[j], self.iqr[j] = 0.0, 1.0
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        return np.clip((X - self.med) / self.iqr, -10, 10)


def units(acc: dict, feats: dict, n: int) -> dict:
    """Count-based unit sequences of n consecutive valid events inside one segment."""
    F, valid, seg, t, mid = feats["F"], feats["valid"], acc["segment"], acc["t"], acc["mid"]
    idx = np.where(valid)[0]
    out_X, ts, te, mend, useg, first = [], [], [], [], [], []
    k = 0
    while k + n <= len(idx):
        blk = idx[k:k + n]
        if seg[blk[0]] != seg[blk[-1]] or np.any(np.diff(blk) != 1):
            k += 1                                                   # never across a segment boundary / invalid event
            continue
        out_X.append(F[blk])
        ts.append(t[blk[0]])
        te.append(t[blk[-1]])
        mend.append(mid[blk[-1]])
        useg.append(seg[blk[0]])
        first.append(blk[0])
        k += n
    return {"X": np.asarray(out_X), "t_start": np.asarray(ts), "t_end": np.asarray(te), "mid_end": np.asarray(mend), "segment": np.asarray(useg),
            "first_event": np.asarray(first), "n": n, "available_at": np.asarray(te)}


def unit_targets(u: dict, k_ahead: int = 2, band: float | None = None) -> dict:
    """DOWN/FLAT/UP of r = ln(mid_end[u+k]/mid_end[u]) within the same segment; band defaults to 0.25 * median |r| of the series
    (a fixed dispersion statistic; the dataset builder recomputes it on TRAIN units only)."""
    m, seg = u["mid_end"], u["segment"]
    n = len(m)
    r = np.full(n, np.nan)
    ok = np.zeros(n, dtype=bool)
    for i in range(n - k_ahead):
        if seg[i + k_ahead] == seg[i]:
            r[i] = math.log(m[i + k_ahead] / m[i])
            ok[i] = True
    t_label = np.full(n, np.nan)
    t_label[: n - k_ahead] = u["t_end"][k_ahead:]
    return {"r": r, "ok": ok, "t_label": t_label, "k_ahead": k_ahead, "band": band}


def classify(r: np.ndarray, band: float) -> np.ndarray:
    return np.where(r < -band, 0, np.where(r > band, 2, 1))
