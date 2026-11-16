"""Cellular Feature Graph - port of CellularNeuralNet10K.mqh (Yevgeniy Koshtenko, https://www.mql5.com/en/articles/23135,
sha256 ea961179...). Implementation id PMW_GRAPH50_PORT_V1. What is ported and what PMW changes (and why):

  features   50 named columns (PMW_GRAPH50_V1) with the source's formulas, computed on CLOSED bars only (the source used the forming
             bar rates[0]); a missing input (no volume / short history) -> mask 1, value 0 is not invented for real-volume features;
  graph      50x50 edge weights, deterministic INITIAL topology of the source (local d=1: 0.22, d=5: 0.12, chord j=(13i+7)%50: 0.10),
             two message-passing steps: 65 % node + 25 % graph mean + 10 % contrast, tanh(1.25 x .); meta features 45..47.
             PMW: NO self-loops (the source kept a diagonal 1.0 clamped to [0.35, 1] - the node's own value is already the 65 % term);
             off-diagonal weights bounded [-0.75, 0.75], NaN/Inf -> 0, edges |w| < 0.015 skipped (source rule).
  learning   Hebbian rule of the source (decay 0.0008, lr 0.018, reward = sign agreement x min(1, 2|pred|)), applied ONLY when the
             label of THAT prediction matured: the input frozen at prediction time is stored with its prediction id and target; a
             restart / duplicate never updates the same (prediction_id, target, model_version) twice. The source used the LAST feature
             vector for every update - PMW does not.
  cells      vectorised CA (numpy arrays, no Python object per cell): N cells (config, default 10 000 = 100x100 torus), 4 geometric +
             4 graph neighbours (source construction), 10 strategies, 12 evolution rules, 6 CA ticks, weighted vote -> raw score in
             [-1, 1] (DIRECTION_SCORE_RAW - not a probability, not calibrated). The source's random strategy switch uses a seeded RNG.
  targets    NEXT_BAR_DIRECTION and BPC10 (sign of the move over the next 10 bars of the same TF) keep SEPARATE graph + cell states.
No grid execution, no lot multipliers, no risk evolution from the source EA - the score is an input to analysis only.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

import numpy as np

VERSION = "PMW_GRAPH50_PORT_V1"
SCHEMA = "PMW_GRAPH50_V1"
NF = 50
TARGETS = {"NEXT_BAR_DIRECTION": 1, "BPC10": 10}
NAMES = ([f"mom_{p}" for p in (5, 10, 20, 50, 100)] + [f"trend_dm_{p}" for p in (5, 10, 14, 20, 50)] + [f"atr_rel_{p}" for p in (5, 10, 14, 20, 50)]
         + [f"rsi_{p}" for p in (7, 14, 21)] + ["macd_8_17", "macd_12_26", "macd_5_13"] + [f"bb_pos_{p}" for p in (10, 20, 50)]
         + [f"tickvol_ratio_{p}" for p in (5, 10, 20)] + [f"autocorr_lag{p}" for p in (1, 2, 5)] + [f"mean_rev_{p}" for p in (20, 50, 100)]
         + [f"range_pos_{p}" for p in (20, 50, 100)] + ["hurst_30", "hurst_100", "body_ratio", "upper_shadow", "lower_shadow", "gap_open",
                                                        "mom_accel", "vol_change", "trend_change", "graph_regime", "graph_coherence",
                                                        "graph_energy", "hour_sin", "hour_cos"])
assert len(NAMES) == NF
ORDER_HASH = hashlib.sha256("|".join(NAMES).encode()).hexdigest()[:12]
VOLUME_COLS = (24, 25, 26)


def extract(bars: list[dict], lookback: int = 200) -> tuple[np.ndarray, np.ndarray] | None:
    """bars oldest-first, CLOSED. Returns (raw features before the graph layer, masks). Source formulas with r[0] = newest closed."""
    if len(bars) < 110:
        return None
    r = list(reversed(bars[-(lookback + 20):]))
    nb = min(lookback, len(r) - 5)
    c = np.array([float(x["c"]) for x in r])
    o = np.array([float(x["o"]) for x in r])
    h = np.array([float(x["h"]) for x in r])
    lo = np.array([float(x["l"]) for x in r])
    tv = np.array([float(x.get("tv") or 0.0) for x in r])
    f = np.zeros(NF)
    m = np.zeros(NF)
    rets = np.where(c[1:nb + 1] > 0, (c[:nb] - c[1:nb + 1]) / c[1:nb + 1], 0.0)
    cs = np.concatenate([[0.0], np.cumsum(rets)])
    cq = np.concatenate([[0.0], np.cumsum(rets * rets)])
    tr = np.empty(nb)
    tr[:-1] = np.maximum(h[:nb - 1] - lo[:nb - 1], np.maximum(np.abs(h[:nb - 1] - c[1:nb]), np.abs(lo[:nb - 1] - c[1:nb])))
    tr[-1] = h[nb - 1] - lo[nb - 1]
    tcs = np.concatenate([[0.0], np.cumsum(tr)])
    for k, p in enumerate((5, 10, 20, 50, 100)):
        w = min(p, nb)
        mean = cs[w] / w
        sd = math.sqrt(max(cq[w] / w - mean * mean, 1e-16))
        f[k] = math.tanh(cs[w] / (w * max(sd, 1e-8)))
    for k, p in enumerate((5, 10, 14, 20, 50)):
        w = min(p, nb - 1)
        hd = h[:w] - h[1:w + 1]
        ld = lo[1:w + 1] - lo[:w]
        dp = np.where((hd > ld) & (hd > 0), hd, 0).sum()
        dm = np.where((ld > hd) & (ld > 0), ld, 0).sum()
        ts = tr[:w].sum()
        f[5 + k] = math.tanh((dp - dm) / ts * 3.0) if ts > 1e-10 else 0.0
    for k, p in enumerate((5, 10, 14, 20, 50)):
        w = max(1, min(p, nb - 1))
        atr_n = (tcs[w] / w) / c[0] if c[0] > 0 else 0.0
        f[10 + k] = math.tanh(atr_n * 1000.0 - 1.0)
    for k, p in enumerate((7, 14, 21)):
        w = min(p, nb - 1)
        d = c[:w] - c[1:w + 1]
        g, l_ = d[d > 0].sum(), -d[d < 0].sum()
        f[15 + k] = ((100.0 * g / (g + l_) if g + l_ > 0 else 50.0) - 50.0) / 50.0
    es0 = min(30, nb - 1)
    for k, (kf, ks) in enumerate(((2 / 9, 2 / 18), (2 / 13, 2 / 27), (2 / 6, 2 / 14))):
        ef = es = c[es0]
        for i in range(es0 - 1, -1, -1):
            ef = c[i] * kf + ef * (1 - kf)
            es = c[i] * ks + es * (1 - ks)
        f[18 + k] = math.tanh((ef - es) / c[0] * 10000.0) if c[0] > 0 else 0.0
    for k, p in enumerate((10, 20, 50)):
        w = min(p, nb)
        sma = c[:w].mean()
        dev = math.sqrt(((c[:w] - sma) ** 2).mean())
        f[21 + k] = math.tanh((c[0] - sma) / (2 * dev) * 2.0) if dev > 0 else 0.0
    if tv[:21].sum() > 0:
        for k, p in enumerate((5, 10, 20)):
            w = max(1, min(p, nb - 1))
            avg = tv[1:w + 1].mean()
            f[24 + k] = math.tanh(tv[0] / avg - 1.0) if avg > 0 else 0.0
    else:
        m[list(VOLUME_COLS)] = 1                               # no tick activity in the feed: masked, never "zero volume"
    mean_r = cs[min(30, nb)] / max(1, min(30, nb))
    for k, lag in enumerate((1, 2, 5)):
        w = min(30, nb - lag)
        if w < 2:
            m[27 + k] = 1
            continue
        d0 = rets[:w] - mean_r
        d1 = rets[lag:w + lag] - mean_r
        var = (d0 * d0).sum()
        f[27 + k] = math.tanh((d0 * d1).sum() / var * 3.0) if var > 1e-10 else 0.0
    for k, p in enumerate((20, 50, 100)):
        w = min(p, nb)
        sma = c[:w].mean()
        f[30 + k] = math.tanh((c[0] - sma) / sma * 100.0) if sma > 0 else 0.0
    for k, p in enumerate((20, 50, 100)):
        w = min(p, nb)
        hi_, lo_ = max(h[0], h[:w].max()), min(lo[0], lo[:w].min())
        f[33 + k] = 2.0 * (c[0] - lo_) / (hi_ - lo_) - 1.0 if hi_ > lo_ else 0.0
    for k, p in enumerate((30, 100)):
        w = min(p, nb)
        if w < 10:
            m[36 + k] = 1
            continue
        mw = cs[w] / w
        sd = math.sqrt(max(cq[w] / w - mw * mw, 1e-16))
        cd = np.cumsum(rets[:w] - mw)
        rng = cd.max() - cd.min()
        srs = sd * math.sqrt(w)
        hu = math.log(rng / srs) / math.log(w) if srs > 0 and rng > 0 else 0.5
        f[36 + k] = (max(0.2, min(0.8, hu)) - 0.5) * 2.0
    body, hl = abs(c[0] - o[0]), h[0] - lo[0]
    f[38] = (body / hl) * 2.0 - 1.0 if hl > 0 else 0.0
    f[39] = math.tanh(((h[0] - max(o[0], c[0])) / hl) * 4.0 - 1.0) if hl > 0 else 0.0
    f[40] = math.tanh(((min(o[0], c[0]) - lo[0]) / hl) * 4.0 - 1.0) if hl > 0 else 0.0
    f[41] = math.tanh((o[0] - c[1]) / c[1] * 10000.0) if c[1] > 0 else 0.0
    f[42] = math.tanh((cs[min(5, nb)] - (rets[5:min(10, nb)].sum() if nb > 10 else 0.0)) * 100.0)
    vn = np.abs(rets[:min(10, nb)]).mean()
    vo = np.abs(rets[10:10 + max(0, min(10, nb - 10))]).mean() if nb > 10 else 0.0
    f[43] = math.tanh(vn / vo - 1.0) if vo > 1e-10 else 0.0
    f[44] = math.tanh((f[5] - f[9]) * 2.0)
    t0 = datetime.fromtimestamp(float(r[0]["t"]), timezone.utc)
    ang = t0.hour / 24.0 * 2 * math.pi
    f[48], f[49] = math.sin(ang), math.cos(ang)
    f[~np.isfinite(f)] = 0.0
    return f, m


def initial_graph() -> np.ndarray:
    W = np.zeros((NF, NF))
    for i in range(NF):
        for j in range(NF):
            if i == j:
                continue                                     # PMW: no self-loop (see module doc)
            d = abs(i - j)
            d = min(d, NF - d)
            if d == 1:
                W[i, j] = 0.22
            elif d == 5:
                W[i, j] = 0.12
            elif j == (i * 13 + 7) % NF:
                W[i, j] = 0.10
    return W


def graph_layer(W: np.ndarray, feat: np.ndarray) -> np.ndarray:
    """Two message-passing steps of the source (self term = the 65 % node share, no diagonal edge); meta features 45..47."""
    Wm = np.where(np.abs(W) < 0.015, 0.0, W)
    np.fill_diagonal(Wm, 0.0)
    src = feat.copy()
    for _ in range(2):
        msg = Wm @ src
        norm = 1e-8 + np.abs(Wm).sum(axis=1) + 1.0                # +1.0: the node's own weight in the source's normaliser
        gm = (msg + src) / norm
        dst = np.tanh(1.25 * (0.65 * src + 0.25 * gm + 0.10 * (src - gm)))
        src = dst
    out = src.copy()
    low = out.mean()
    high = np.abs(out - np.roll(out, -1)).mean()
    energy = float(out @ W @ out) / (NF * NF)
    out[45] = math.tanh(low * 3.0)
    out[46] = math.tanh((abs(low) - high) * 4.0)
    out[47] = math.tanh(energy * 12.0)
    out[~np.isfinite(out)] = 0.0
    return out


def hebbian(W: np.ndarray, frozen: np.ndarray, prediction: float, actual_move: float, lr: float = 0.018, decay: float = 0.0008) -> np.ndarray:
    if abs(prediction) < 0.001 or abs(actual_move) < 1e-12:
        return W
    reward = (1.0 if prediction * actual_move > 0 else -1.0) * min(1.0, abs(prediction) * 2.0)
    co = np.outer(frozen, frozen)
    upd = np.where(np.abs(co) < 0.0005, 0.0, lr * reward * co)
    Wn = W * np.where(np.abs(co) < 0.0005, 1.0, 1.0 - decay) + upd
    np.fill_diagonal(Wn, 0.0)
    Wn = np.clip(Wn, -0.75, 0.75)
    Wn[~np.isfinite(Wn)] = 0.0
    return Wn


class CellGrid:
    """Vectorised CA of the source (10 strategies, 12 rules, Moore + graph neighbours, weighted vote)."""

    def __init__(self, n_cells: int = 10000, seed: int = 20261116):
        side = int(round(math.sqrt(n_cells)))
        self.n, self.w = side * side, side
        self.rng = np.random.default_rng(seed)
        n = self.n
        self.state = np.zeros(n)
        self.capital = np.full(n, 0.5)
        self.pnl = np.zeros(n)
        self.weight = np.ones(n)
        self.strategy = np.arange(n) % 10
        self.feat_idx = (np.arange(n) // 10) % NF
        self.losses = np.zeros(n, dtype=int)
        self.bias, self.long_cnt, self.short_cnt = 0.0, 0, 0
        self.lr = 0.02
        y, x = np.divmod(np.arange(n), side)
        nb = []
        for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1)):                 # 4 geometric neighbours (first four of the Moore loop)
            nb.append(((y + dy) % side) * side + (x + dx) % side)
        same_feat = np.array([self._same_feat(i) for i in range(n)])
        bucket = np.arange(n) // NF
        adj = (bucket * NF + (self.feat_idx + 1) % NF) % n
        same_strat = (self.strategy + 10 * ((np.arange(n) // 10 + 37) % max(1, n // 10))) % n
        chord = (np.arange(n) * 37 + 101) % n
        self.nb = np.stack(nb + [same_feat, adj, same_strat, chord], axis=1)

    def _same_feat(self, i: int) -> int:
        n = self.n
        j = (i + NF * 17) % n
        for _ in range(n):
            if j != i and self.feat_idx[j] == self.feat_idx[i]:
                return j
            j = (j + NF) % n
        return (i + 1) % n

    def _strat(self, f: np.ndarray, nb_mean: np.ndarray) -> np.ndarray:
        S = np.array([0.5 * f[0] + 0.3 * f[5] + 0.2 * f[10], 0.5 * f[2] + 0.3 * f[7] + 0.2 * f[16], 0.5 * f[3] + 0.3 * f[9] + 0.2 * f[23],
                      -0.4 * f[16] - 0.4 * f[22] + 0.2 * f[30], 0.5 * f[1] + 0.3 * f[25] + 0.2 * f[27], -0.5 * f[31] - 0.3 * f[17] + 0.2 * f[37],
                      0.5 * f[12] + 0.3 * f[42] + 0.2 * f[38], 0.5 * f[25] + 0.3 * f[43] + 0.2 * f[2], 0.4 * f[38] + 0.2 * f[39] + 0.2 * f[40] + 0.2 * f[41], 0.0])
        out = S[self.strategy]
        return np.where(self.strategy == 9, nb_mean * 0.7 + f[0] * 0.3, out)

    def vote(self) -> float:
        wt = self.weight.sum()
        if wt < 1e-10:
            return 0.0
        return math.tanh(((self.state * self.weight).sum() / wt + self.bias) * 2.0)

    def step(self, f: np.ndarray, consensus: float) -> None:
        s = self.state[self.nb]
        nb_mean = s.mean(axis=1)
        pos, neg = (s > 0.05).sum(axis=1), (s < -0.05).sum(axis=1)
        agree = np.maximum(pos, neg) / 8.0
        new = f[self.feat_idx] * 0.5 + self._strat(f, nb_mean) * 0.3 + nb_mean * 0.2
        new = np.where(self.pnl > 0, new * (1 + 0.2 * np.minimum(self.pnl, 1.0)),
                       np.where(self.pnl < 0, new * np.maximum(0.4, 1 + 0.3 * np.maximum(self.pnl, -1.0)), new))
        msign = np.where(pos > neg, 1.0, -1.0)
        new = np.where(agree >= 5 / 8, new * (1 - agree * 0.4) + msign * np.abs(new) * agree * 0.4, new)
        if f[12] > 0.3:
            new = new * max(0.4, 1 - f[12] * 0.4)
        if f[7] * f[2] > 0.05:
            new = new + (1.0 if f[7] > 0 else -1.0) * min(0.3, abs(f[7]) * 0.4)
        new = np.where(self.losses >= 3, new * 0.3, new)
        if abs(consensus) > 0.7:
            new = 0.6 * new + 0.4 * (1.0 if consensus > 0 else -1.0) * np.abs(new)
        if abs(f[42]) > 0.3:
            new = new + (1.0 if f[42] > 0 else -1.0) * 0.1 * abs(f[42])
        if f[25] > 0.3:
            new = np.where(np.abs(new) > 0.1, new * (1 + 0.15 * f[25]), new)
        ta = f[5] * f[7]
        if ta > 0.1:
            new = new * (1 + 0.1 * min(ta, 0.5))
        if f[36] > 0.2:
            new = 0.7 * new + 0.3 * self.state
        new = new * self.capital + nb_mean * (1 - self.capital) * 0.3
        new = np.tanh(new * 1.5)
        new[~np.isfinite(new)] = 0.0
        self.state = new

    def predict(self, f: np.ndarray, ticks: int = 6) -> float:
        cons = self.vote()
        for _ in range(ticks):
            self.step(f, cons)
            cons = self.vote()
        p = self.vote()
        if p > 0.001:
            self.long_cnt += 1
        elif p < -0.001:
            self.short_cnt += 1
        tot = self.long_cnt + self.short_cnt
        if tot > 200:
            self.bias = 0.15 * (self.short_cnt - self.long_cnt) / tot
        return p

    def learn(self, cell_states: np.ndarray, prediction: float, actual_move: float) -> None:
        """Cell PnL update with the frozen cell states of THAT prediction (source UpdateCellPnL, seeded strategy switch)."""
        res = np.where(cell_states * actual_move > 0, abs(actual_move), -abs(actual_move)) * np.abs(cell_states)
        self.pnl += res
        win = res > 0
        self.capital = np.where(win, np.minimum(1.0, self.capital + self.lr * 1.5), np.maximum(0.05, self.capital - self.lr * 1.5))
        self.losses = np.where(win, 0, self.losses + 1)
        sw = self.losses >= 3
        if sw.any():
            self.strategy = np.where(sw, (self.strategy + 1 + self.rng.integers(0, 3, self.n)) % 10, self.strategy)
            self.losses = np.where(sw, 0, self.losses)
        self.weight = self.capital * (1 + np.maximum(0.0, self.pnl) * 0.005)
        self.weight = np.where(np.isfinite(self.weight) & (self.weight > 0), self.weight, 0.05)

    def to_dict(self) -> dict:
        return {k: getattr(self, k).tolist() for k in ("state", "capital", "pnl", "weight", "strategy", "losses")} | {
            "bias": self.bias, "long_cnt": self.long_cnt, "short_cnt": self.short_cnt, "n": self.n, "rng": self.rng.bit_generator.state}

    @classmethod
    def from_dict(cls, d: dict) -> "CellGrid":
        g = cls(int(d["n"]))
        for k in ("state", "capital", "pnl", "weight"):
            setattr(g, k, np.asarray(d[k], dtype=float))
        g.strategy, g.losses = np.asarray(d["strategy"], dtype=int), np.asarray(d["losses"], dtype=int)
        g.bias, g.long_cnt, g.short_cnt = float(d["bias"]), int(d["long_cnt"]), int(d["short_cnt"])
        g.rng.bit_generator.state = d["rng"]
        return g


class TargetState:
    """Graph + cells + pending-label queue of ONE target / horizon of ONE market context."""

    def __init__(self, target: str, n_cells: int = 10000):
        self.target, self.h = target, TARGETS[target]
        self.W = initial_graph()
        self.cells = CellGrid(n_cells)
        self.version = 0
        self.pending: list[dict] = []                         # {pid, bar_t, close, frozen_feat, cell_states, prediction}
        self.applied: set[str] = set()                        # (pid|target|version) keys already used for an update

    def predict(self, pid: str, bar_t: float, close: float, raw: np.ndarray) -> dict:
        g = graph_layer(self.W, raw)
        p = self.cells.predict(g)
        self.pending.append({"pid": pid, "bar_t": bar_t, "close": close, "frozen": g.tolist(), "cells": self.cells.state.tolist(), "prediction": p,
                             "version": self.version})
        self.pending = self.pending[-2000:]
        return {"raw_score": float(p), "graph_features": g, "version": self.version}

    def mature(self, closes_by_t: dict, bar_times: list[float]) -> int:
        """Update with every prediction whose label (close h bars later) is now known; each (pid, target, version) once."""
        n = 0
        idx = {t: i for i, t in enumerate(bar_times)}
        keep = []
        for pr in self.pending:
            i = idx.get(pr["bar_t"])
            if i is None or i + self.h >= len(bar_times):
                keep.append(pr)
                continue
            key = f"{pr['pid']}|{self.target}|{pr['version']}"
            if key in self.applied:
                continue
            move = closes_by_t[bar_times[i + self.h]] - pr["close"]
            self.W = hebbian(self.W, np.asarray(pr["frozen"]), pr["prediction"], move)
            self.cells.learn(np.asarray(pr["cells"]), pr["prediction"], move)
            self.applied.add(key)
            self.version += 1
            n += 1
        self.pending = keep
        if len(self.applied) > 20000:
            self.applied = set(list(self.applied)[-10000:])
        return n

    def top_edges(self, k: int = 12) -> list[dict]:
        W = self.W.copy()
        np.fill_diagonal(W, 0.0)
        flat = [(abs(W[i, j]), i, j) for i in range(NF) for j in range(NF) if i != j and W[i, j] != 0]
        flat.sort(reverse=True)
        return [{"from": NAMES[i], "to": NAMES[j], "weight": round(float(W[i, j]), 4)} for _, i, j in flat[:k]]   # unique (i, j) pairs

    def to_dict(self) -> dict:
        return {"target": self.target, "W": self.W.tolist(), "cells": self.cells.to_dict(), "version": self.version, "pending": self.pending[-500:],
                "applied": sorted(self.applied)[-5000:], "schema": SCHEMA, "order_hash": ORDER_HASH, "implementation": VERSION}

    @classmethod
    def from_dict(cls, d: dict) -> "TargetState":
        s = cls(d["target"], int(d["cells"]["n"]))
        s.W = np.asarray(d["W"], dtype=float)
        np.fill_diagonal(s.W, 0.0)
        s.cells = CellGrid.from_dict(d["cells"])
        s.version, s.pending, s.applied = int(d["version"]), list(d["pending"]), set(d["applied"])
        return s


def state_hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]
