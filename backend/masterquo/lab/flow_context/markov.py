"""Shared Markov core (FF01/FF02). Legacy M09 (lab/market.markov, P^64 row) stays untouched as LEGACY.

Core: counts N_ab with Dirichlet alpha per destination, P_ab = (N_ab + alpha)/(row + K alpha); rows without support -> NO_ROW_SUPPORT
(prior shown explicitly). Rolling ring of transitions (default 1000), prequential cycle: observe closed state -> score the previously
issued forecast -> issue the next one -> update(prev, cur) once per transition id. A gap breaks the chain (no transition across it).
Stationary: solve pi P = pi, sum 1 (least squares) with residual check; reducible/periodic/non-unique detected - never P^64.

MQ_MARKOV3_FLOW_V1: d_t = (C_t - C_{t-L})/point, tau = max(train quantile(|d|, .33), tick/point) frozen at Fit; DOWN d<-tau, UP d>tau.
MQ_MARKOV_DIFF_FLOW_V1: d_t = (C_t - C_{t-1})/point, K requested 9 (3..31), cuts = train quantiles j/K, side=right half-open bins,
  duplicate cuts merged (K_effective + mapping), emissions mu_b/nu_b from train samples of the DESTINATION state (min 30 per state for
  projection eligibility), Markov-reward DP moments of the cumulative change, empirical MC fan (2048 paths, deterministic seed).
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path

import numpy as np

M3 = "MQ_MARKOV3_FLOW_V1"
MD = "MQ_MARKOV_DIFF_FLOW_V1"
STATES3 = ("DOWN", "FLAT", "UP")


# ===================================================================== core
class MarkovCore:
    def __init__(self, K: int, alpha: float = 1.0, ring: int = 1000):
        self.K, self.alpha, self.ring_size = K, alpha, ring
        self.N = np.zeros((K, K))
        self.ring: deque = deque()
        self.seen: set = set()

    def add(self, a: int, b: int, tid=None) -> bool:
        if tid is not None:
            if tid in self.seen:
                return False                                      # dedup per transition id (restart / repeated poll)
            self.seen.add(tid)
        self.N[a, b] += 1
        self.ring.append((a, b, tid))
        if len(self.ring) > self.ring_size:
            oa, ob, otid = self.ring.popleft()
            self.N[oa, ob] -= 1
            self.seen.discard(otid)
        return True

    def P(self) -> np.ndarray:
        rows = self.N.sum(1, keepdims=True)
        return (self.N + self.alpha) / (rows + self.K * self.alpha)

    def support(self) -> list:
        return self.N.sum(1).astype(int).tolist()

    def forecast(self, s: int, H: int = 15) -> np.ndarray:
        H = min(int(H), 50)
        P = self.P()
        pi = np.eye(self.K)[s]
        out = []
        for _ in range(H):
            pi = pi @ P
            out.append(pi)
        return np.array(out)


def stationary(P: np.ndarray, tol: float = 1e-10) -> dict:
    K = P.shape[0]
    if not (np.isfinite(P).all() and (P >= -1e-15).all() and np.allclose(P.sum(1), 1, atol=1e-9)):
        return {"status": "INVALID_P"}
    adj = P > 0
    reach = adj.copy()
    for k in range(K):
        reach = reach | (reach[:, [k]] & reach[[k], :])
    irreducible = bool(reach.all())
    A = np.vstack([P.T - np.eye(K), np.ones((1, K))])
    b = np.zeros(K + 1)
    b[-1] = 1
    pi, *_ = np.linalg.lstsq(A, b, rcond=None)
    res = float(np.abs(pi @ P - pi).max())
    null_dim = K - np.linalg.matrix_rank(P.T - np.eye(K), tol=1e-9)
    if null_dim > 1:
        return {"status": "NON_UNIQUE", "irreducible": irreducible, "classes": int(null_dim)}
    if res > tol or (pi < -1e-12).any():
        return {"status": "NOT_IDENTIFIED", "residual": res}
    pi = np.clip(pi, 0, None)
    pi = pi / pi.sum()
    # period of an irreducible chain: gcd of return lengths to state 0 (bounded search)
    period = None
    if irreducible:
        from math import gcd
        g, Mk = 0, np.eye(K)
        for n in range(1, 2 * K * K + 2):
            Mk = (Mk @ adj.astype(float)) > 0
            if Mk[0, 0]:
                g = gcd(g, n)
        period = g or None
    st = "OK" if (irreducible and period == 1) else ("PERIODIC" if irreducible else "REDUCIBLE")
    return {"status": st, "pi": pi.tolist(), "residual": res, "irreducible": irreducible, "period": period,
            "note": "zbieżność do wspólnego pi nie oznacza równych prawdopodobieństw"}


def entropy(p) -> float:
    p = np.asarray(p, float)
    p = p[p > 0]
    return float(-(p * np.log(p)).sum() / np.log(3 if len(p) <= 3 else len(p))) if len(p) else 0.0


def _ts(x) -> float:
    from datetime import datetime
    return x if isinstance(x, (int, float)) else datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


# ===================================================================== FF01 Markov3
class Markov3:
    model_id = M3

    def __init__(self, point: float, tick: float | None = None, lag: int = 1, alpha: float = 1.0, ring: int = 1000, tf_s: int = 60):
        self.point, self.tick, self.L, self.tf_s = point, tick or point, lag, tf_s
        self.core = MarkovCore(3, alpha, ring)
        self.tau = None
        self.fit_info = None
        self.prev = None                     # (state, bar time)
        self.pending: dict | None = None     # last issued forecast (scored before update)
        self.scores: list = []

    def _d(self, c: list, i: int):
        return None if i - self.L < 0 else (c[i] - c[i - self.L]) / self.point

    def state(self, d: float) -> int:
        return 0 if d < -self.tau else (2 if d > self.tau else 1)

    def fit(self, bars: list[dict]) -> "Markov3":
        c = [b["c"] for b in bars]
        ds = [self._d(c, i) for i in range(len(c))]
        ad = np.abs([x for x in ds if x is not None])
        if len(ad) < 10:
            raise ValueError("INSUFFICIENT_EVIDENCE")
        self.tau = max(float(np.quantile(ad, 0.33)), self.tick / self.point)
        prev = None
        for i, b in enumerate(bars):
            if ds[i] is None:
                continue
            s = self.state(ds[i])
            if prev is not None and _ts(b["open_utc"]) - prev[1] == self.tf_s:
                self.core.add(prev[0], s, str(b["open_utc"]))
            prev = (s, _ts(b["open_utc"]))
        self.prev = prev
        self.fit_info = {"tau_points": self.tau, "train_bars": len(bars), "train_end": bars[-1]["open_utc"], "lag": self.L,
                         "tau_rule": "max(train q33(|d|), tick/point)"}
        return self

    def step(self, bars_tail: list[dict], H: int = 15) -> dict:
        """Prequential step on the newest CLOSED bar (bars_tail ends with it, contains >= L+1 bars)."""
        if self.tau is None:
            raise ValueError("NOT_FITTED")
        c = [b["c"] for b in bars_tail]
        b = bars_tail[-1]
        d = self._d(c, len(c) - 1)
        if d is None:
            return {"status": "WARMUP"}
        s = self.state(d)
        t = _ts(b["open_utc"])
        score = None
        if self.pending is not None and self.pending["for_t"] == t:
            p = self.pending["p_next"][s]
            score = {"logloss": float(-np.log(max(p, 1e-12))), "brier": float(((np.array(self.pending["p_next"]) - np.eye(3)[s]) ** 2).sum())}
            self.scores.append(score)
        if self.prev is not None and t - self.prev[1] == self.tf_s:
            self.core.add(self.prev[0], s, str(b["open_utc"]))
        elif self.prev is not None and t - self.prev[1] > self.tf_s:
            score = dict(score or {}, gap="GAP_NO_TRANSITION")
        self.prev = (s, t)
        fc = self.core.forecast(s, H)
        self.pending = {"for_t": t + self.tf_s, "p_next": fc[0].tolist()}
        P = self.core.P()
        sup = self.core.support()
        return {"model_id": M3, "state": STATES3[s], "d_points": d, "tau_points": self.tau, "P": P.tolist(), "counts": self.core.N.astype(int).tolist(),
                "support": sup, "row_status": ["NO_ROW_SUPPORT" if x == 0 else ("LOW_SUPPORT" if x < 30 else "OK") for x in sup],
                "next": dict(zip(STATES3, fc[0].tolist())), "state_at_h": [dict(zip(STATES3, r.tolist())) for r in fc],
                "entropy_next": entropy(fc[0]), "stationary": stationary(P), "score_prev": score,
                "note": "STATE_AT_H to rozkład stanu jednej zmiany w kroku h – nie skumulowany zwrot ani p(TP)"}

    # artefact
    def to_dict(self) -> dict:
        return {"model_id": M3, "point": self.point, "tick": self.tick, "lag": self.L, "tau": self.tau, "alpha": self.core.alpha,
                "ring": [[a, b, t] for a, b, t in self.core.ring], "ring_size": self.core.ring_size, "prev": self.prev, "fit": self.fit_info,
                "tf_s": self.tf_s}

    @classmethod
    def from_dict(cls, d: dict) -> "Markov3":
        if d.get("model_id") != M3:
            raise ValueError("INCOMPATIBLE_ARTIFACT")
        m = cls(d["point"], d["tick"], d["lag"], d["alpha"], d["ring_size"], d.get("tf_s", 60))
        m.tau, m.fit_info, m.prev = d["tau"], d["fit"], tuple(d["prev"]) if d["prev"] else None
        for a, b, t in d["ring"]:
            m.core.add(a, b, t)
        return m


# ===================================================================== FF02 difference buckets
def make_bins(d_train: np.ndarray, K: int = 9) -> dict:
    if not 3 <= K <= 31:
        raise ValueError("K_OUT_OF_RANGE (3..31)")
    cuts = np.quantile(d_train, [j / K for j in range(1, K)])
    uniq = []
    for x in cuts:
        if not uniq or x > uniq[-1]:
            uniq.append(float(x))
    return {"K_requested": K, "K_effective": len(uniq) + 1, "cuts": uniq, "rule": "side=right half-open; outer bins open (-inf, +inf)",
            "boundary_kind": "train_quantiles_j/K", "duplicates_merged": len(cuts) - len(uniq)}


def bin_of(d: float, cuts: list) -> int:
    return int(np.searchsorted(np.asarray(cuts), d, side="right"))


def dp_moments(P: np.ndarray, mu: np.ndarray, nu: np.ndarray, s0: int, H: int) -> list[dict]:
    """Markov-reward moments of S_h = sum of future rewards (reward depends on the DESTINATION state). Simultaneous update."""
    K = len(mu)
    pi = np.eye(K)[s0]
    M = np.zeros(K)
    Q = np.zeros(K)
    out = []
    for _ in range(H):
        pi_n = pi @ P
        MP = M @ P
        M_n = MP + pi_n * mu
        Q_n = Q @ P + 2 * MP * mu + pi_n * nu
        pi, M, Q = pi_n, M_n, Q_n
        mean = float(M.sum())
        var = float(Q.sum() - mean ** 2)
        status = "OK"
        if var < 0:
            if var < -1e-9 * max(1.0, float(Q.sum())):
                status = "NUMERIC_ERROR"
            var = 0.0
        out.append({"mean": mean, "var": var, "status": status, "pi": pi.tolist()})
    return out


class MarkovDiff:
    model_id = MD
    MIN_EMISSIONS = 30

    def __init__(self, point: float, K: int = 9, alpha: float = 1.0, ring: int = 1000, tf_s: int = 60, n_paths: int = 2048, seed: int = 7):
        self.point, self.Kreq, self.tf_s, self.n_paths, self.seed = point, K, tf_s, n_paths, seed
        self.alpha, self.ring_size = alpha, ring
        self.bins = None
        self.core = None
        self.emis: list = []
        self.prev = None
        self.fit_info = None

    def fit(self, bars: list[dict]) -> "MarkovDiff":
        c = np.array([b["c"] for b in bars], float)
        t = np.array([_ts(b["open_utc"]) for b in bars])
        ok = np.diff(t) == self.tf_s
        d = np.diff(c) / self.point
        dtr = d[ok]
        if len(dtr) < 50:
            raise ValueError("INSUFFICIENT_EVIDENCE")
        self.bins = make_bins(dtr, self.Kreq)
        K = self.bins["K_effective"]
        self.core = MarkovCore(K, self.alpha, self.ring_size)
        states = np.array([bin_of(x, self.bins["cuts"]) for x in d])
        self.emis = [d[ok & (states == k)] for k in range(K)]
        prev = None
        for i in range(len(d)):
            if not ok[i]:
                prev = None
                continue
            if prev is not None:
                self.core.add(prev, int(states[i]), str(bars[i + 1]["open_utc"]))
            prev = int(states[i])
        self.prev = (prev, float(t[-1])) if prev is not None else None
        self.fit_info = {"train_increments": int(len(dtr)), "train_end": bars[-1]["open_utc"], "bins": self.bins,
                         "train_min": float(dtr.min()), "train_max": float(dtr.max()), "train_std": float(dtr.std())}
        return self

    def emission_stats(self) -> list[dict]:
        return [{"state": k, "count": int(len(e)), "mu": float(e.mean()) if len(e) else None, "nu": float((e ** 2).mean()) if len(e) else None,
                 "min": float(e.min()) if len(e) else None, "max": float(e.max()) if len(e) else None} for k, e in enumerate(self.emis)]

    def eligibility(self) -> dict:
        if self.bins["K_effective"] == 1 or self.fit_info.get("train_std", 1.0) == 0:
            return {"eligible": False, "reason": "NO_VARIATION"}
        low = [k for k, e in enumerate(self.emis) if len(e) < self.MIN_EMISSIONS]
        if low:
            return {"eligible": False, "reason": "LOW_EMISSION_SUPPORT", "states": low, "min": self.MIN_EMISSIONS}
        return {"eligible": True}

    def forecast(self, state: int, last_close: float, H: int = 15, horizons=(1, 3, 5, 15), mc: bool = True) -> dict:
        if self.core is None:
            raise ValueError("NOT_FITTED")
        P = self.core.P()
        el = self.eligibility()
        dist = self.core.forecast(state, H)
        out = {"model_id": MD, "state": state, "K_effective": self.bins["K_effective"], "P": P.tolist(), "support": self.core.support(),
               "state_distributions": dist.tolist(), "eligibility": el, "emissions": self.emission_stats(), "bins": self.bins}
        if not el["eligible"]:
            out["projection"] = None
            return out
        mu = np.array([e.mean() for e in self.emis])
        nu = np.array([(e ** 2).mean() for e in self.emis])
        mom = dp_moments(P, mu, nu, state, H)
        sims = self.simulate(P, state, max(horizons), self.n_paths, np.random.default_rng(self.seed)) if mc else None
        proj = {}
        for h in horizons:
            if h > H:
                continue
            m = mom[h - 1]
            q = np.quantile(sims[:, h - 1], (0.1, 0.5, 0.9)) if sims is not None else None
            proj[str(h)] = {"mean_points": m["mean"], "var_points2": m["var"], "status": m["status"], "price_mean": last_close + self.point * m["mean"],
                            "price_sd": self.point * np.sqrt(m["var"]), "q_points": None if q is None else q.tolist(),
                            "price_q": None if q is None else (last_close + self.point * q).tolist(), "mc_paths": self.n_paths if mc else 0}
        out["projection"] = proj
        out["note"] = "przedziały dotyczą punktu końcowego, nie high/low ani bezpiecznego SL; zakłada stałe P"
        return out

    def simulate(self, P, s0, H, n, rng) -> np.ndarray:
        K = P.shape[0]
        cum = np.cumsum(P, axis=1)
        s = np.full(n, s0)
        tot = np.zeros(n)
        out = np.zeros((n, H))
        for h in range(H):
            u = rng.random(n)
            s = np.minimum((u[:, None] > cum[s]).sum(1), K - 1)
            for k in range(K):
                idx = np.where(s == k)[0]
                if len(idx):
                    tot[idx] += rng.choice(self.emis[k], len(idx))
            out[:, h] = tot
        return out

    def step(self, bars_tail: list[dict], H: int = 15, mc: bool = True) -> dict:
        b0, b1 = bars_tail[-2], bars_tail[-1]
        d = (b1["c"] - b0["c"]) / self.point
        s = bin_of(d, self.bins["cuts"])
        t = _ts(b1["open_utc"])
        flags = []
        if d < self.fit_info["train_min"] or d > self.fit_info["train_max"]:
            flags.append("TAIL_OUT_OF_SUPPORT")
        if self.prev is not None and t - self.prev[1] == self.tf_s:
            self.core.add(self.prev[0], s, str(b1["open_utc"]))
        elif self.prev is not None:
            flags.append("GAP_NO_TRANSITION")
        self.prev = (s, t)
        return dict(self.forecast(s, b1["c"], H, mc=mc), flags=flags, d_points=d)

    def save(self, d: Path) -> str:
        d = Path(d)
        d.mkdir(parents=True, exist_ok=False)
        np.savez(d / "emissions.npz", **{f"e{k}": e for k, e in enumerate(self.emis)})
        man = {"model_id": MD, "point": self.point, "K_requested": self.Kreq, "alpha": self.alpha, "ring_size": self.ring_size, "tf_s": self.tf_s,
               "n_paths": self.n_paths, "seed": self.seed, "bins": self.bins, "ring": [[a, b, t] for a, b, t in self.core.ring], "prev": self.prev,
               "fit": self.fit_info, "emissions_sha256": hashlib.sha256((d / "emissions.npz").read_bytes()).hexdigest()}
        (d / "manifest.json").write_text(json.dumps(man, default=float), encoding="utf-8")
        return man["emissions_sha256"]

    @classmethod
    def load(cls, d: Path) -> "MarkovDiff":
        d = Path(d)
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if man.get("model_id") != MD or hashlib.sha256((d / "emissions.npz").read_bytes()).hexdigest() != man["emissions_sha256"]:
            raise ValueError("INCOMPATIBLE_ARTIFACT")
        m = cls(man["point"], man["K_requested"], man["alpha"], man["ring_size"], man["tf_s"], man["n_paths"], man["seed"])
        m.bins, m.fit_info = man["bins"], man["fit"]
        K = m.bins["K_effective"]
        with np.load(d / "emissions.npz", allow_pickle=False) as z:
            m.emis = [z[f"e{k}"] for k in range(K)]
        m.core = MarkovCore(K, m.alpha, m.ring_size)
        for a, b, t in man["ring"]:
            if not (0 <= a < K and 0 <= b < K):
                raise ValueError("INCOMPATIBLE_ARTIFACT: state out of range")
            m.core.add(a, b, t)
        m.prev = tuple(man["prev"]) if man["prev"] else None
        P = m.core.P()
        if not np.allclose(P.sum(1), 1):
            raise ValueError("INVALID_P")
        return m
