"""MQ_SPIKE_BRAIN_FINANCE_V1 (PMW-UPD-09 R20) - small own financial adaptation of spiking + attention + sparse MoE ideas.

NOT the SpikingBrain LLM and not the legacy M02 (LEGACY_RULE_ROUTED_SNN = lab/nets.SEWSNN, its fixed volatility routing is not a learned
MoE). One engine; later profile names (e.g. MQ_SPIKE_MARKET_V1) are configurations of THIS engine.

Encoder (deterministic, one implementation for dataset and runtime, NOT differentiable - the gradient boundary):
  per channel: z_t = (x_t - mu_prev) / sd_prev from EW statistics known BEFORE t (score-before-update; warm-up / low dispersion masked,
  clip +-5 flagged); signed-delta accumulator a = a_prev + z; adaptive threshold theta_t = clip(1 + 0.5*activity_prev, 0.5, 3);
  ON / OFF channels emit floor(|a|/theta) impulses (COUNT4: at most 4, residual kept + overflow counted; BINARY1: at most 1);
  activity EW decays with real dt (32 bars / 5 s). BAR_EVENT_V1: every closed M1 is a step (no spike still decays). QUOTE_EVENT_V1:
  token on a meaningful spike or HEARTBEAT on a real quote >= 1 s after the last token; never a fabricated quote.
Network (d_model 32, 2 blocks, 2 heads x 8):
  block: h += W_s * s, s = adaptive LIF(h W_lif) [u = exp(-dt/tau_m) v_prev + I; adapt = exp(-dt/tau_a) adapt_prev + b s_prev;
         theta = theta_base + adapt; s = H(u - theta) (arctan surrogate, alpha 2); v = u - stop_grad(s) theta]
         h += W_o * attention(LN(h))  LINEAR (phi = ELU+1, gated decay lambda = exp(-dt/tau) sigmoid(w_g h + b_g)), SLIDING (softmax over
         the last 32 positions only - never a full T x T matrix), HYBRID (learned sigmoid mix per head)
         h += MoE(LN(h)): shared expert + top-1 of 4 routed FFN 32-64-32 on MEANINGFUL tokens, output p_selected * expert(h) (the kept
         router weight carries the gradient), aux loss 0.01 E sum(f_e mean p_e) over routed tokens, training-only capacity with shared-only
         overflow (reported). Masked (padding) steps neither update state nor receive weight; dt only advances on valid steps.
Heads: as STRUCTURE_MOVE_M1_V1 (3 classes + ordered quantiles per horizon), CE + 0.5 pinball, missing labels masked.
Telemetry: spike rates, expert shares, router entropy, overflow, latency p50/p95/p99. Sparse impulses on dense NumPy do NOT prove lower
latency or energy (energy_j = null, NOT_MEASURED).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from . import autodiff as A

ARCH_ID = "MQ_SPIKE_BRAIN_FINANCE_V1"
VERSION = "MQ-SPIKE-BRAIN-1.0.0"
ENCODERS = ("BAR_EVENT_V1", "QUOTE_EVENT_V1")
ATTENTION = ("LINEAR", "SLIDING", "HYBRID")
CLASSES = ("DOWN", "FLAT", "UP")
QUANTS = (0.1, 0.5, 0.9)
CFG = {"d_model": 32, "blocks": 2, "heads": 2, "d_k": 8, "window": 32, "experts": 4, "expert_hidden": 64, "attention": "HYBRID", "alpha": 2.0,
       "tau_m": 8.0, "tau_a": 32.0, "adapt_b": 0.1, "tau_head": 128.0, "gate_bias": 4.6, "eps": 1e-8, "aux_w": 0.01, "w_q": 0.5,
       "capacity_factor": 1.25, "horizons": [3, 5, 15], "encoder": "BAR_EVENT_V1", "lr": 1e-3, "clip": 1.0, "weight_decay": 1e-4}
QUOTE_TIMES = {"tau_m": 2.0, "tau_a": 10.0, "tau_head": 60.0}


# ===================================================================== encoder
class EventEncoder:
    def __init__(self, n_channels: int, profile: str = "BAR_EVENT_V1", count_mode: str = "COUNT4", theta0=1.0, k=0.5, theta_min=0.5, theta_max=3.0,
                 tau_act: float | None = None, tau_norm: float | None = None, warmup: int = 20, min_sd=1e-9, clip=5.0):
        if profile not in ENCODERS or count_mode not in ("COUNT4", "BINARY1"):
            raise ValueError("ENCODER_PROFILE_INVALID")
        self.C, self.profile, self.count_mode = n_channels, profile, count_mode
        bar = profile == "BAR_EVENT_V1"
        self.tau_act = tau_act or (32.0 if bar else 5.0)
        self.tau_norm = tau_norm or (100.0 if bar else 60.0)
        self.theta0, self.k, self.tmin, self.tmax, self.warmup, self.min_sd, self.clipv = theta0, k, theta_min, theta_max, warmup, min_sd, clip
        self.max_n = 4 if count_mode == "COUNT4" else 1
        self.reset()

    def reset(self):
        self.mu = np.zeros(self.C)
        self.var = np.zeros(self.C)
        self.n = np.zeros(self.C, dtype=int)
        self.acc = np.zeros(self.C)
        self.activity = np.zeros(self.C)
        self.overflow = 0
        self.last_t = None

    def step(self, x: np.ndarray, t: float) -> dict:
        """x: raw channel values (nan = missing). Returns ON/OFF counts (2C), flags; statistics updated AFTER scoring."""
        dt = 0.0 if self.last_t is None else max(0.0, t - self.last_t)          # equal timestamp -> dt 0, never invented
        self.last_t = t
        dec_a = math.exp(-dt / self.tau_act) if dt > 0 else 1.0
        on, off = np.zeros(self.C), np.zeros(self.C)
        flags = []
        for c in range(self.C):
            v = x[c]
            if not np.isfinite(v):
                flags.append(f"MISSING_{c}")
                continue
            sd = math.sqrt(self.var[c]) if self.n[c] > 0 else 0.0
            if self.n[c] >= self.warmup and sd > self.min_sd:
                z = (v - self.mu[c]) / sd
                if abs(z) > self.clipv:
                    flags.append(f"CLIP_{c}")
                    z = math.copysign(self.clipv, z)
                theta = min(self.tmax, max(self.tmin, self.theta0 + self.k * self.activity[c]))
                a = self.acc[c] + z
                cnt = int(abs(a) // theta)
                if cnt > self.max_n:
                    self.overflow += cnt - self.max_n
                    cnt = self.max_n
                if cnt:
                    a -= math.copysign(cnt * theta, a)
                    (on if z > 0 or a > 0 and z == 0 else off)[c] = cnt
                self.acc[c] = a
            elif self.n[c] >= self.warmup:
                flags.append(f"LOW_DISPERSION_{c}")
            # update AFTER scoring (EW mean/var with real-dt decay)
            w = 1.0 - math.exp(-(dt if dt > 0 else 1.0) / self.tau_norm)
            if self.n[c] == 0:
                self.mu[c], self.var[c] = v, 0.0
            else:
                d = v - self.mu[c]
                self.mu[c] += w * d
                self.var[c] = (1 - w) * (self.var[c] + w * d * d)
            self.n[c] += 1
        self.activity = self.activity * dec_a + on + off
        return {"tokens": np.concatenate([on, off]), "meaningful": bool((on + off).sum() > 0), "dt": dt, "flags": flags}

    def run(self, X: np.ndarray, t: np.ndarray) -> dict:
        """One pass over a whole stream (dataset): identical to stepping live - overlapping windows never re-run the encoder."""
        out = [self.step(X[i], float(t[i])) for i in range(len(X))]
        return {"tokens": np.array([o["tokens"] for o in out]).reshape(len(out), 2 * self.C), "meaningful": np.array([o["meaningful"] for o in out]),
                "dt": np.array([o["dt"] for o in out]), "overflow": self.overflow}


def quote_tokens(ticks: list[dict], enc: EventEncoder, tick_size: float = 1.0) -> dict:
    """QUOTE_EVENT_V1 stream from REAL quotes: channels log-return of mid, dBid ticks, dAsk ticks, spread ticks; a token on a meaningful
    spike or HEARTBEAT (>= 1 s since the last token) - every token is a real quote."""
    toks, ts, kinds = [], [], []
    last_tok_t, prev = None, None
    for k in ticks:
        t = k["t_ms"] / 1000.0
        if prev is None:
            prev = k
            continue
        mid, pm = (k["bid"] + k["ask"]) / 2, (prev["bid"] + prev["ask"]) / 2
        x = np.array([math.log(mid / pm) if pm > 0 else np.nan, (k["bid"] - prev["bid"]) / tick_size, (k["ask"] - prev["ask"]) / tick_size,
                      (k["ask"] - k["bid"]) / tick_size])
        e = enc.step(x, t)
        if e["meaningful"] or last_tok_t is None or t - last_tok_t >= 1.0:
            toks.append(e["tokens"])
            ts.append(t)
            kinds.append("EVENT" if e["meaningful"] else "HEARTBEAT")
            last_tok_t = t
        prev = k
    return {"tokens": np.array(toks).reshape(len(toks), 2 * enc.C), "t": np.array(ts), "kind": kinds}


# ===================================================================== network
class SpikeBrain:
    def __init__(self, n_in: int, cfg: dict | None = None, seed: int = 11):
        c = dict(CFG, **(cfg or {}))
        if c["encoder"] == "QUOTE_EVENT_V1":
            c = dict(c, **{k: (cfg or {}).get(k, v) for k, v in QUOTE_TIMES.items()})
        if c["attention"] not in ATTENTION:
            raise ValueError("ATTENTION_MODE_INVALID")
        self.cfg, self.n_in, self.seed = c, n_in, seed
        self.smooth_reference, self.reset_reference = False, True
        self.capacity_training = False
        rng = np.random.default_rng(seed)
        D, H, dk, E, Fh = c["d_model"], c["heads"], c["d_k"], c["experts"], c["expert_hidden"]

        def W(*shape, fan=None):
            return A.T(rng.normal(0, math.sqrt(1.0 / (fan or shape[0])), shape))
        p = {"W_in": W(n_in, D), "b_in": A.T(np.zeros(D))}
        for b in range(c["blocks"]):
            p.update({f"W_lif{b}": W(D, D), f"theta{b}": A.T(np.full(D, 1.0)), f"W_s{b}": W(D, D),
                      f"W_q{b}": W(D, H * dk), f"W_k{b}": W(D, H * dk), f"W_v{b}": W(D, H * dk), f"W_g{b}": W(D, H), f"b_g{b}": A.T(np.full(H, c["gate_bias"])),
                      f"mix{b}": A.T(np.zeros(H)), f"W_o{b}": W(H * dk, D), f"W_r{b}": W(D, E), f"b_r{b}": A.T(np.zeros(E)),
                      f"W_e1{b}": A.T(rng.normal(0, math.sqrt(1.0 / D), (E, D, Fh))), f"b_e1{b}": A.T(np.zeros((E, Fh))),
                      f"W_e2{b}": A.T(rng.normal(0, math.sqrt(1.0 / Fh), (E, Fh, D))), f"b_e2{b}": A.T(np.zeros((E, D))),
                      f"W_sh{b}": W(D, D), f"b_sh{b}": A.T(np.zeros(D))})
        nh = len(c["horizons"])
        p["W_head"], p["b_head"] = W(2 * D, 6 * nh), A.T(np.zeros(6 * nh))
        self.p = p
        self.last_tel: dict = {}

    # ---------------------------------------------------------------- pieces
    def _spike(self, x):
        if self.smooth_reference:                               # integral of the surrogate (gradient-check reference only)
            return A.T(np.arctan(math.pi / 2 * self.cfg["alpha"] * x.data) / math.pi + 0.5, (x,),
                       lambda g: (g * (self.cfg["alpha"] / 2) / (1 + (math.pi / 2 * self.cfg["alpha"] * x.data) ** 2),))
        return A.spike(x, self.cfg["alpha"])

    def _lif(self, I, mask, dt, b, tel):
        """Adaptive LIF over time. I (N,T,D) T-node; mask (N,T); dt (N,T)."""
        c = self.cfg
        N, T_, D = I.shape
        v = A.T(np.zeros((N, D)))
        adapt = A.T(np.zeros((N, D)))
        s_prev = A.T(np.zeros((N, D)))
        outs, rate = [], 0.0
        th = self.p[f"theta{b}"]
        for t in range(T_):
            m = mask[:, t:t + 1]
            dm = np.exp(-dt[:, t:t + 1] / c["tau_m"])
            da = np.exp(-dt[:, t:t + 1] / c["tau_a"])
            adapt_n = adapt * da + s_prev * c["adapt_b"]
            u = v * dm + I[:, t, :]
            theta = th + adapt_n
            s = self._spike(u - theta) * m
            v_n = u - (A.detach(s) * theta if self.reset_reference else 0.0)
            # masked step: state unchanged
            v = v_n * m + v * (1 - m)
            adapt = adapt_n * m + adapt * (1 - m)
            s_prev = s * m + s_prev * (1 - m)
            outs.append(s)
            rate += float(s.data.mean())
        tel[f"spike_rate_block{b}"] = rate / max(1, T_)
        return A.stack(outs, axis=1)

    def _attention(self, h, mask, dt, b, tel):
        c = self.cfg
        N, T_, D = h.shape
        H, dk = c["heads"], c["d_k"]
        x = A.layernorm(h)
        q = (x @ self.p[f"W_q{b}"]).reshape(N, T_, H, dk)
        k = (x @ self.p[f"W_k{b}"]).reshape(N, T_, H, dk)
        v = (x @ self.p[f"W_v{b}"]).reshape(N, T_, H, dk)
        mode = c["attention"]
        out_lin = out_sl = None
        if mode in ("LINEAR", "HYBRID"):
            gate = A.sigmoid(x @ self.p[f"W_g{b}"] + self.p[f"b_g{b}"])                 # (N,T,H)
            pq, pk = A.elu1(q), A.elu1(k)
            S = A.T(np.zeros((N, H, dk, dk)))
            z = A.T(np.zeros((N, H, dk)))
            outs = []
            for t in range(T_):
                m = mask[:, t][:, None]
                lam = gate[:, t, :] * np.exp(-dt[:, t][:, None] / c["tau_head"])            # (N,H)
                lam_e = lam * m + (1 - m)                                                   # masked: no decay, no update
                kt = pk[:, t, :, :] * m[:, :, None]
                vt = v[:, t, :, :]
                S = S * lam_e.reshape(N, H, 1, 1) + kt.reshape(N, H, dk, 1) * vt.reshape(N, H, 1, dk)
                z = z * lam_e.reshape(N, H, 1) + kt
                qt = pq[:, t, :, :]
                num = (qt.reshape(N, H, 1, dk) @ S).reshape(N, H, dk)
                den = (qt * z).sum(axis=-1).reshape(N, H, 1) + c["eps"]
                outs.append(num / den)
            out_lin = A.stack(outs, axis=1)                                                 # (N,T,H,dk)
        if mode in ("SLIDING", "HYBRID"):
            W_ = c["window"]
            pos = np.arange(T_)[:, None] - np.arange(W_ - 1, -1, -1)[None, :]                # (T, W) positions t-W+1..t
            valid = (pos >= 0)[None, :, :] & np.take_along_axis(np.broadcast_to(mask[:, None, :], (N, T_, T_)), np.clip(pos, 0, T_ - 1)[None].repeat(N, 0), axis=2).astype(bool)
            pc = np.clip(pos, 0, T_ - 1)
            Kw = k[:, pc]                                                                   # (N,T,W,H,dk)
            Vw = v[:, pc]
            sc = (q.reshape(N, T_, 1, H, dk) * Kw).sum(axis=-1) * (1.0 / math.sqrt(dk))     # (N,T,W,H)
            bias = np.where(valid, 0.0, -1e9)[:, :, :, None]
            p_ = A.softmax(sc + bias, axis=2)
            out_sl = (p_.reshape(N, T_, W_, H, 1) * Vw).sum(axis=2)                         # (N,T,H,dk)
        if mode == "HYBRID":
            g = A.sigmoid(self.p[f"mix{b}"]).reshape(1, 1, H, 1)
            out = out_lin * g + out_sl * (1.0 - g)
            tel[f"hybrid_mix_block{b}"] = (0.5 * (1 + np.tanh(0.5 * self.p[f"mix{b}"].data))).tolist()
        else:
            out = out_lin if mode == "LINEAR" else out_sl
        out = out * mask[:, :, None, None]
        return out.reshape(N, T_, H * dk) @ self.p[f"W_o{b}"]

    def _moe(self, h, meaningful, mask, b, tel):
        c = self.cfg
        N, T_, D = h.shape
        E = c["experts"]
        x = A.layernorm(h).reshape(N * T_, D)
        shared = A.tanh(x @ self.p[f"W_sh{b}"] + self.p[f"b_sh{b}"])
        logits = x @ self.p[f"W_r{b}"] + self.p[f"b_r{b}"]
        pr = A.softmax(logits, axis=-1)                                                     # (M,E)
        sel = np.argmax(pr.data, axis=1)                                                    # ties -> lowest expert id
        routed = (meaningful & mask.astype(bool)).reshape(-1)
        M = N * T_
        cap = int(math.ceil(c["capacity_factor"] * max(1, routed.sum()) / E)) if self.capacity_training else None
        out = A.T(np.zeros((M, D)))
        counts, overflow = np.zeros(E, int), 0
        for e in range(E):
            rows = np.where(routed & (sel == e))[0]
            if cap is not None and len(rows) > cap:
                overflow += len(rows) - cap
                rows = rows[:cap]
            counts[e] = len(rows)
            if not len(rows):
                continue
            xe = x[rows]
            he = A.relu(xe @ self.p[f"W_e1{b}"][e] + self.p[f"b_e1{b}"][e])
            ye = he @ self.p[f"W_e2{b}"][e] + self.p[f"b_e2{b}"][e]
            pe = pr[rows, e].reshape(len(rows), 1)                                          # kept router weight -> gradient to W_r
            out = A.scatter_rows(out, rows, ye * pe)
        nr = int(routed.sum())
        if nr:
            f = counts / max(1, counts.sum())                                               # stop-gradient fractions
            mp = pr[np.where(routed)[0]].mean(axis=0)
            aux = (mp * f).sum() * (c["aux_w"] * E)
        else:
            aux = A.T(0.0)
        ent = float(-(pr.data[routed] * np.log(pr.data[routed] + 1e-12)).sum(axis=1).mean()) if nr else None
        tel[f"experts_block{b}"] = {"share": (counts / max(1, counts.sum())).tolist(), "routed_tokens": nr, "router_entropy": ent,
                                    "overflow_ratio": overflow / max(1, nr), "zero_routed": nr == 0}
        return (shared + out).reshape(N, T_, D), aux

    # ---------------------------------------------------------------- forward / loss
    def forward(self, tokens, meaningful, mask, dt):
        """tokens (N,T,C) numpy; meaningful/mask (N,T) bool/0-1; dt (N,T) real time per valid step (bars or seconds)."""
        c = self.cfg
        mask = mask.astype(float)
        dt = np.where(mask > 0, dt, 0.0)
        tel = {}
        h = A.T(tokens) @ self.p["W_in"] + self.p["b_in"]
        aux_total = A.T(0.0)
        for b in range(c["blocks"]):
            s = self._lif(h @ self.p[f"W_lif{b}"], mask, dt, b, tel)
            h = h + s @ self.p[f"W_s{b}"]
            h = h + self._attention(h, mask, dt, b, tel)
            mo, aux = self._moe(h, meaningful.astype(bool), mask, b, tel)
            h = h + mo
            aux_total = aux_total + aux
        N, T_, D = h.shape
        last_idx = np.array([np.max(np.where(mask[i] > 0)[0]) if mask[i].any() else T_ - 1 for i in range(N)])
        last = h[np.arange(N), last_idx]
        mean = (h * mask[:, :, None]).sum(axis=1) * (1.0 / np.maximum(1.0, mask.sum(axis=1)))[:, None]
        feat = A.concat([last, mean], axis=-1)
        o = (feat @ self.p["W_head"] + self.p["b_head"]).reshape(N, len(c["horizons"]), 6)
        self.last_tel = tel
        return o, aux_total

    def loss(self, tokens, meaningful, mask, dt, y, r):
        c = self.cfg
        o, aux = self.forward(tokens, meaningful, mask, dt)
        N, Hh, _ = o.shape
        logits = o[:, :, 0:3]
        lp = A.log_softmax(logits, axis=-1)
        m = (y >= 0).astype(float)
        yy = np.where(y >= 0, y, 0)
        onehot = np.eye(3)[yy] * m[:, :, None]
        ce = -(lp * onehot).sum() * (1.0 / max(1.0, m.sum()))
        q50 = o[:, :, 4]
        q10 = q50 - A.softplus(o[:, :, 3])
        q90 = q50 + A.softplus(o[:, :, 5])
        mr = np.isfinite(r).astype(float)
        rr = np.where(mr > 0, r, 0.0)
        pin = A.T(0.0)
        for tau, q in zip(QUANTS, (q10, q50, q90)):
            e = A.T(rr) - q
            pos = (e.data >= 0).astype(float)
            pin = pin + (e * (tau * pos + (tau - 1) * (1 - pos)) * mr).sum() * (1.0 / max(1.0, mr.sum()) / 3)
        total = ce + pin * c["w_q"] + aux
        return total, {"loss": float(total.data), "ce": float(ce.data), "pinball": float(pin.data), "aux": float(aux.data)}

    def predict(self, tokens, meaningful, mask, dt) -> dict:
        t0 = time.perf_counter()
        o, _ = self.forward(tokens, meaningful, mask, dt)
        d = o.data
        z = d[:, :, 0:3] - d[:, :, 0:3].max(axis=-1, keepdims=True)
        P = np.exp(z) / np.exp(z).sum(axis=-1, keepdims=True)
        sp = lambda x: np.where(x > 20, x, np.log1p(np.exp(np.minimum(x, 20))))  # noqa: E731
        Q = np.stack([d[:, :, 4] - sp(d[:, :, 3]), d[:, :, 4], d[:, :, 4] + sp(d[:, :, 5])], axis=-1)
        return {"proba": P, "quantiles": Q, "telemetry": dict(self.last_tel, latency_ms=(time.perf_counter() - t0) * 1000)}

    # ---------------------------------------------------------------- artefact
    def manifest(self) -> dict:
        return {"architecture_id": ARCH_ID, "version": VERSION, "n_in": self.n_in, "cfg": self.cfg, "seed": self.seed, "classes": list(CLASSES),
                "quantiles": list(QUANTS), "encoder": self.cfg["encoder"], "attention": self.cfg["attention"], "state_policy": "RESET_EACH_WINDOW",
                "lif": {"reset": "SUBTRACT_DETACHED_SPIKE", "surrogate": f"arctan alpha={self.cfg['alpha']}", "adaptive": True},
                "moe": {"experts": self.cfg["experts"], "top_k": 1, "shared_expert": True, "capacity": "TRAINING_ONLY"},
                "legacy": "M02 = LEGACY_RULE_ROUTED_SNN (lab/nets.SEWSNN), nie alias", "energy_j": None}

    def save(self, d: Path) -> dict:
        d = Path(d)
        d.mkdir(parents=True, exist_ok=False)
        np.savez(d / "weights.npz", **{k: v.data for k, v in self.p.items()})
        man = dict(self.manifest(), weights_sha256=hashlib.sha256((d / "weights.npz").read_bytes()).hexdigest())
        (d / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
        return man

    @classmethod
    def load(cls, d: Path, expect: dict | None = None) -> "SpikeBrain":
        d = Path(d)
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if man.get("architecture_id") != ARCH_ID:
            raise ValueError("ARCHITECTURE_MISMATCH")
        if hashlib.sha256((d / "weights.npz").read_bytes()).hexdigest() != man["weights_sha256"]:
            raise ValueError("WEIGHTS_HASH_MISMATCH")
        for k, v in (expect or {}).items():
            if man.get(k) != v:
                raise ValueError(f"INCOMPATIBLE_ARTIFACT: {k}")
        net = cls(man["n_in"], man["cfg"], man["seed"])
        with np.load(d / "weights.npz", allow_pickle=False) as z:
            for k in net.p:
                if z[k].shape != net.p[k].data.shape:
                    raise ValueError(f"SHAPE_MISMATCH: {k}")
                net.p[k] = A.T(z[k].copy())
        return net


def fit(net: SpikeBrain, batches, val=None, *, epochs=10, lr=1e-3, patience=4, seed=11, ckpt_dir: Path | None = None, cancel=None, budget_s=None, log=None) -> dict:
    """batches(epoch_rng) -> iterable of (tokens, meaningful, mask, dt, y, r); val = same tuple or None. Adam + clip; checkpoint per epoch
    (weights, optimizer moments/step, RNG state, epoch, early-stop state) -> resume continues identically; TRAINED only after the loop."""
    opt = A.Adam(net.p, lr=lr, wd=net.cfg["weight_decay"])
    rng = np.random.default_rng(seed)
    start, hist, best, best_p, bad = 0, [], None, None, 0
    ck = Path(ckpt_dir) / "checkpoint.npz" if ckpt_dir else None
    if ck is not None and ck.exists():
        with np.load(ck, allow_pickle=False) as z:
            st = json.loads(str(z["meta"]))
            for k in net.p:
                net.p[k].data = z[f"p__{k}"].copy()
            opt.load_state({kk[5:]: z[kk] for kk in z.files if kk.startswith("opt__")} | {"t": st["opt_t"]})
            rng.bit_generator.state = st["rng"]
            start, hist, best, bad = st["epoch"], st["history"], st["best"], st["bad"]
    status = "TRAINED"
    net.capacity_training = True
    t0 = time.monotonic()
    for ep in range(start, epochs):
        if cancel is not None and cancel():
            status = "CANCELLED"
            break
        tot, nb = 0.0, 0
        for bt in batches(rng):
            L, parts = net.loss(*bt)
            if not math.isfinite(parts["loss"]):
                status = "NAN_LOSS"
                break
            L.backward()
            opt.step(net.cfg["clip"])
            tot += parts["loss"]
            nb += 1
        rec = {"epoch": ep + 1, "train_loss": tot / max(1, nb)}
        if val is not None:
            net.capacity_training = False
            _, pv = net.loss(*val)
            net.capacity_training = True
            rec["val_loss"] = pv["loss"]
            if best is None or pv["loss"] < best - 1e-6:
                best, best_p, bad = pv["loss"], {k: v.data.copy() for k, v in net.p.items()}, 0
            else:
                bad += 1
        hist.append(rec)
        if log:
            log(rec)
        if ck is not None:
            ck.parent.mkdir(parents=True, exist_ok=True)
            meta = json.dumps({"epoch": ep + 1, "history": hist, "best": best, "bad": bad, "opt_t": opt.t, "rng": rng.bit_generator.state}, default=int)
            tmp = ck.with_name("checkpoint.tmp.npz")
            np.savez(tmp, meta=np.array(meta), **{f"p__{k}": v.data for k, v in net.p.items()},
                     **{f"opt__{k}": v for k, v in opt.state().items() if k != "t"})
            tmp.replace(ck)
        if status != "TRAINED" or (val is not None and bad >= patience):
            break
        if budget_s is not None and time.monotonic() - t0 > budget_s:
            status = "BUDGET_EXCEEDED"
            break
    net.capacity_training = False
    if best_p is not None and status == "TRAINED":
        for k, v in best_p.items():
            net.p[k].data = v
    return {"status": status, "history": hist, "epochs_run": len(hist)}
