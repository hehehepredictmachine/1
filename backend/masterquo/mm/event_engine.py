"""Event-driven market intelligence engine (PMW-MM-EVENTENGINE-1). TRAINABLE (GRU encoder + head) with a RECURSIVE state stack.

Pipeline: EVENTS -> validation (mm.events.Ingestor) -> features -> count-based unit sequences -> temporal encoder (GRU over the events of
a unit; descriptor q = last hidden state, H dims) -> STATE STACK (last S descriptors of the same segment; slot 0 = newest) ->
STACK CORRELATION corr_j = dot(q, s_j) over valid slots (raw dot; cosine only as an explicit variant) -> direction head
logits = q W_q + (corr * valid) W_c + valid W_v + b -> softmax -> temperature-scaled probabilities (T fitted on VALIDATION).
Target: class of r = ln(mid_end[u+k]/mid_end[u]) with a neutral band (band = 0.25 x median |r| of TRAINING units); label available at
the end of unit u+k. Gradient semantics: the stack holds DETACHED descriptors (fixed memory). The loss gradient reaches the current
descriptor (top) through q W_q and through corr (d corr_j / d q = s_j) - historical slots never receive gradient. This is NOT
back-propagation through time across units (BPTT runs only inside a unit, over its events).
Backends: the stack shift + correlation run on OpenCL (mm/kernels/state_stack.cl via pyopencl) when a device is available, else on the
CPU reference with identical semantics; `backend_used` reports the real one.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

from ..lab import autodiff as A
from . import events as EV
from .stfs import STFS, label_smoothed_ce, triplet_batch_hard

VERSION = "PMW-MM-EVENTENGINE-1"
KERNEL = Path(__file__).with_name("kernels") / "state_stack.cl"


# ----------------------------------------------------------------------------------------------- state stack
class StateStack:
    def __init__(self, S: int, D: int, backend: str = "auto"):
        if S < 1 or D < 1:
            raise ValueError("STACK_DIMENSIONS_INVALID")
        self.S, self.D = S, D
        self.backend_used = "CPU"
        self.cl_error = None
        self.reset_cpu()
        if backend in ("auto", "opencl"):
            try:
                self._init_cl(gpu_only=(backend == "auto"))
                self.backend_used = "OPENCL"
            except Exception as exc:  # noqa: BLE001 - no pyopencl / no device -> CPU reference (reported)
                self.cl_error = f"{type(exc).__name__}: {exc}"[:200]
                if backend == "opencl":
                    raise

    def reset_cpu(self):
        self.buf = np.zeros((self.S, self.D), dtype=np.float32)
        self.valid = np.zeros(self.S, dtype=np.int32)

    def _init_cl(self, gpu_only: bool):
        """auto -> only a GPU device (on a CPU OpenCL device such as POCL the numpy reference was measured faster: 22 us vs 943 us per
        push+corr for S=8, D=16); backend='opencl' forces any OpenCL device (used by the parity tests)."""
        import pyopencl as cl  # type: ignore
        self.cl = cl
        devs = [d for p in cl.get_platforms() for d in p.get_devices() if (not gpu_only or d.type & cl.device_type.GPU)]
        if not devs:
            raise RuntimeError("NO_OPENCL_GPU_DEVICE" if gpu_only else "NO_OPENCL_DEVICE")
        self.ctx = cl.Context([devs[0]])
        self.device_name = devs[0].name
        self.q = cl.CommandQueue(self.ctx)
        self.prg = cl.Program(self.ctx, KERNEL.read_text(encoding="utf-8")).build()
        self.k_push, self.k_corr = cl.Kernel(self.prg, "stack_push"), cl.Kernel(self.prg, "stack_corr")
        mf = cl.mem_flags
        nb = self.S * self.D * 4
        self.d_buf = [cl.Buffer(self.ctx, mf.READ_WRITE, nb), cl.Buffer(self.ctx, mf.READ_WRITE, nb)]
        self.d_val = [cl.Buffer(self.ctx, mf.READ_WRITE, self.S * 4), cl.Buffer(self.ctx, mf.READ_WRITE, self.S * 4)]
        self.d_desc = cl.Buffer(self.ctx, mf.READ_WRITE, self.D * 4)
        self.d_out = cl.Buffer(self.ctx, mf.READ_WRITE, self.S * 4)
        self.cur = 0
        self.reset()

    def reset(self):
        self.reset_cpu()
        if self.backend_used == "OPENCL" or hasattr(self, "cl"):
            for b in self.d_buf:
                self.cl.enqueue_copy(self.q, b, self.buf)
            for b in self.d_val:
                self.cl.enqueue_copy(self.q, b, self.valid)
            self.q.finish()

    def push(self, desc: np.ndarray):
        d = np.asarray(desc, dtype=np.float32).reshape(-1)
        if d.shape[0] != self.D or not np.all(np.isfinite(d)):
            raise ValueError("STACK_DESCRIPTOR_INVALID")
        if self.backend_used == "OPENCL":
            cl = self.cl
            cl.enqueue_copy(self.q, self.d_desc, d)
            src, dst = self.cur, 1 - self.cur
            self.k_push(self.q, (self.S * self.D,), None, self.d_buf[src], self.d_val[src], self.d_desc, self.d_buf[dst], self.d_val[dst],
                        np.int32(self.S), np.int32(self.D))
            self.cur = dst
            return
        self.buf[1:] = self.buf[:-1].copy()
        self.valid[1:] = self.valid[:-1].copy()
        self.buf[0], self.valid[0] = d, 1

    def corr(self, q: np.ndarray, l2: bool = False) -> np.ndarray:
        qq = np.asarray(q, dtype=np.float32).reshape(-1)
        if qq.shape[0] != self.D:
            raise ValueError("STACK_QUERY_DIMENSION")
        if self.backend_used == "OPENCL":
            cl = self.cl
            cl.enqueue_copy(self.q, self.d_desc, qq)
            self.k_corr(self.q, (self.S,), None, self.d_desc, self.d_buf[self.cur], self.d_val[self.cur], self.d_out, np.int32(self.S),
                        np.int32(self.D), np.int32(1 if l2 else 0))
            out = np.empty(self.S, dtype=np.float32)
            cl.enqueue_copy(self.q, out, self.d_out)
            self.q.finish()
            return out.astype(float)
        return stack_corr_ref(qq, self.buf, self.valid, l2)

    def snapshot(self) -> tuple[np.ndarray, np.ndarray]:
        if self.backend_used == "OPENCL":
            b = np.empty((self.S, self.D), dtype=np.float32)
            v = np.empty(self.S, dtype=np.int32)
            self.cl.enqueue_copy(self.q, b, self.d_buf[self.cur])
            self.cl.enqueue_copy(self.q, v, self.d_val[self.cur])
            self.q.finish()
            return b, v
        return self.buf.copy(), self.valid.copy()


def stack_corr_ref(q, buf, valid, l2: bool = False) -> np.ndarray:
    q = np.asarray(q, float)
    b = np.asarray(buf, float)
    raw = b @ q
    if l2:
        den = np.linalg.norm(b, axis=1) * np.linalg.norm(q) + 1e-12
        raw = raw / den
    return np.where(np.asarray(valid) > 0, raw, 0.0)


# ----------------------------------------------------------------------------------------------- model
class EventModel:
    def __init__(self, F: int, H: int = 16, S: int = 8, n_cls: int = 3, seed: int = 3, use_stack: bool = True):
        g = np.random.Generator(np.random.PCG64(seed))
        sc = lambda a, b: g.normal(0, 1 / math.sqrt(a), (a, b))  # noqa: E731
        self.F, self.H, self.S, self.C, self.use_stack = F, H, S, n_cls, use_stack
        self.p = {k: A.T(v) for k, v in {
            "Wz": sc(F, H), "Uz": sc(H, H), "bz": np.zeros(H), "Wr": sc(F, H), "Ur": sc(H, H), "br": np.zeros(H),
            "Wn": sc(F, H), "Un": sc(H, H), "bn": np.zeros(H), "Wq": sc(H, n_cls) * 0.1, "Wc": np.zeros((S, n_cls)), "Wv": np.zeros((S, n_cls)),
            "b": np.zeros(n_cls)}.items()}
        self.temperature = 1.0

    def n_params(self) -> int:
        return int(sum(v.data.size for v in self.p.values()))

    # autodiff path (training)
    def encode(self, X: np.ndarray) -> tuple[A.T, list[A.T]]:
        p = self.p
        B, n, _ = X.shape
        h = A.T(np.zeros((B, self.H)))
        hs = []
        for t in range(n):
            x = A.T(X[:, t, :])
            z = A.sigmoid(x @ p["Wz"] + h @ p["Uz"] + p["bz"])
            r = A.sigmoid(x @ p["Wr"] + h @ p["Ur"] + p["br"])
            c = A.tanh(x @ p["Wn"] + (r * h) @ p["Un"] + p["bn"])
            h = (1.0 - z) * c + z * h
            hs.append(h)
        return h, hs

    def logits(self, q: A.T, stack: np.ndarray, valid: np.ndarray) -> A.T:
        p = self.p
        out = q @ p["Wq"] + p["b"]
        if self.use_stack:
            Sd = A.T(stack)                                                  # detached memory (no gradient to historical slots)
            corr = (Sd @ q.reshape(q.data.shape[0], self.H, 1)).reshape(q.data.shape[0], self.S)
            out = out + (corr * valid) @ p["Wc"] + A.T(valid) @ p["Wv"]
        return out

    # numpy path (inference; identical math)
    def encode_np(self, X: np.ndarray) -> np.ndarray:
        P = {k: v.data for k, v in self.p.items()}
        sg = lambda v: 0.5 * (1 + np.tanh(0.5 * v))  # noqa: E731
        h = np.zeros((X.shape[0], self.H))
        for t in range(X.shape[1]):
            x = X[:, t, :]
            z = sg(x @ P["Wz"] + h @ P["Uz"] + P["bz"])
            r = sg(x @ P["Wr"] + h @ P["Ur"] + P["br"])
            c = np.tanh(x @ P["Wn"] + (r * h) @ P["Un"] + P["bn"])
            h = (1 - z) * c + z * h
        return h

    def logits_np(self, q: np.ndarray, corr: np.ndarray, valid: np.ndarray) -> np.ndarray:
        P = {k: v.data for k, v in self.p.items()}
        out = q @ P["Wq"] + P["b"]
        if self.use_stack:
            out = out + (corr * valid) @ P["Wc"] + valid @ P["Wv"]
        return out

    def state(self) -> dict:
        return {**{k: v.data for k, v in self.p.items()}, "temperature": np.array([self.temperature]),
                "dims": np.array([self.F, self.H, self.S, self.C, int(self.use_stack)])}

    @classmethod
    def from_state(cls, st: dict) -> "EventModel":
        F, H, S, C, us = (int(x) for x in st["dims"])
        m = cls(F, H, S, C, use_stack=bool(us))
        for k in m.p:
            m.p[k] = A.T(np.asarray(st[k], float))
        m.temperature = float(st["temperature"][0])
        return m


def build_stacks(D: np.ndarray, segment: np.ndarray, S: int) -> tuple[np.ndarray, np.ndarray]:
    """For each unit u: descriptors of units u-1..u-S of the SAME segment (slot 0 = u-1), plus validity."""
    n, H = D.shape
    st = np.zeros((n, S, H))
    va = np.zeros((n, S))
    for u in range(n):
        for j in range(S):
            v = u - 1 - j
            if v < 0 or segment[v] != segment[u]:
                break
            st[u, j], va[u, j] = D[v], 1.0
    return st, va


def _softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit_temperature(logits: np.ndarray, y: np.ndarray) -> float:
    best, bt = math.inf, 1.0
    for T in np.exp(np.linspace(math.log(0.25), math.log(8.0), 60)):
        p = _softmax(logits / T)
        ll = -np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1)))
        if ll < best:
            best, bt = ll, float(T)
    return bt


def metrics(p: np.ndarray, y: np.ndarray, n_cls: int = 3) -> dict:
    pred = p.argmax(axis=1)
    cm = np.zeros((n_cls, n_cls), dtype=int)
    for a, b in zip(y, pred):
        cm[a, b] += 1
    rec = [cm[k, k] / cm[k].sum() if cm[k].sum() else math.nan for k in range(n_cls)]
    prec = [cm[k, k] / cm[:, k].sum() if cm[:, k].sum() else math.nan for k in range(n_cls)]
    conf = p.max(axis=1)
    bins = np.clip((conf * 10).astype(int), 0, 9)
    ece = float(sum(abs(conf[bins == b].mean() - (pred[bins == b] == y[bins == b]).mean()) * (bins == b).mean() for b in range(10) if (bins == b).any()))
    oh = np.eye(n_cls)[y]
    return {"n": int(len(y)), "accuracy": float((pred == y).mean()), "balanced_accuracy": float(np.nanmean(rec)), "precision": prec, "recall": rec,
            "log_loss": float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1)))), "brier": float(((p - oh) ** 2).sum(axis=1).mean()),
            "ece_top_label": ece, "confusion": cm.tolist(), "class_share": np.bincount(y, minlength=n_cls).tolist()}


def train(Xtr, ytr, segtr, Xva, yva, segva, *, H=16, S=8, epochs=12, lr=3e-3, batch=128, seed=3, use_stack=True, stfs: STFS | None = None,
          lam=(0.3, 0.3, 0.3), ls_eps=0.1, margin=0.2, patience=3, cancel=None, log=None) -> dict:
    """Chronological training; descriptors for the stack are recomputed (detached) at the start of every epoch."""
    m = EventModel(Xtr.shape[2], H, S, 3, seed, use_stack)
    opt = A.Adam(m.p, lr=lr)
    rng = np.random.Generator(np.random.PCG64(seed))
    best, best_state, wait, hist = math.inf, None, 0, []
    t0 = time.perf_counter()
    for ep in range(epochs):
        if cancel and cancel():
            break
        Dtr = m.encode_np(Xtr)
        St, Va = build_stacks(Dtr, segtr, S)
        order = rng.permutation(len(Xtr))
        tl, nb, ntrip = 0.0, 0, 0
        for k in range(0, len(order), batch):
            ix = order[k:k + batch]
            q, hs = m.encode(Xtr[ix])
            lg = m.logits(q, St[ix], Va[ix])
            loss = label_smoothed_ce(lg, ytr[ix], 0.0)
            if stfs is not None:
                Hm = A.stack(hs, axis=1)
                v = stfs.views(Hm, np.ones((len(ix), Xtr.shape[1]), dtype=bool), training=True)
                for w, key in zip(lam, ("temporal", "feature", "global")):
                    lv = v[key] @ m.p["Wq"] + m.p["b"]                     # shared existing head (descriptor block)
                    loss = loss + label_smoothed_ce(lv, ytr[ix], ls_eps) * w
                    tr, nv = triplet_batch_hard(v[key], ytr[ix], margin)
                    ntrip += nv
                    loss = loss + tr * w
            loss.backward()
            opt.step(clip=1.0)
            tl += float(loss.data)
            nb += 1
        Dva = m.encode_np(Xva)
        Sv, Vv = build_stacks(Dva, segva, S)
        lv = m.logits_np(Dva, (Sv @ Dva[:, :, None])[:, :, 0], Vv)
        pv = _softmax(lv)
        vl = float(-np.mean(np.log(np.clip(pv[np.arange(len(yva)), yva], 1e-12, 1))))
        hist.append({"epoch": ep, "train_loss": tl / max(1, nb), "val_log_loss": vl, "triplets": ntrip})
        if log:
            log(f"epoch {ep}: train {tl / max(1, nb):.4f} val {vl:.4f}")
        if vl < best - 1e-4:
            best, best_state, wait = vl, {k: v.data.copy() for k, v in m.p.items()}, 0
        else:
            wait += 1
            if wait >= patience:
                break
    if best_state is not None:
        for k, v in best_state.items():
            m.p[k] = A.T(v)
    Dva = m.encode_np(Xva)
    Sv, Vv = build_stacks(Dva, segva, S)
    m.temperature = fit_temperature(m.logits_np(Dva, (Sv @ Dva[:, :, None])[:, :, 0], Vv), yva)
    return {"model": m, "history": hist, "train_s": time.perf_counter() - t0, "best_val_log_loss": best, "n_params": m.n_params(),
            "stfs_params": 0 if stfs is not None else None}


def predict(m: EventModel, X, seg) -> np.ndarray:
    D = m.encode_np(X)
    St, Va = build_stacks(D, seg, m.S)
    return _softmax(m.logits_np(D, (St @ D[:, :, None])[:, :, 0], Va) / m.temperature)


# ----------------------------------------------------------------------------------------------- online runtime (SHADOW)
class Runtime:
    """Streaming inference: one event at a time; a prediction is produced when a unit completes. No order path exists here."""

    def __init__(self, m: EventModel, scaler: EV.Scaler, n_per_unit: int, symbol: str, model_version: str, gap_reset_s=900.0, backend="auto"):
        self.m, self.sc, self.n, self.symbol, self.ver = m, scaler, n_per_unit, symbol, model_version
        self.ing = EV.Ingestor(symbol, gap_reset_s)
        self.stack = StateStack(m.S, m.H, backend)
        self.buf: list[np.ndarray] = []
        self.prev = None
        self.seg = 0
        self.lat = {k: [] for k in ("validate", "features", "encode", "corr", "stack_push", "head")}
        self.generation = 0

    def push(self, ev: dict) -> dict | None:
        t0 = time.perf_counter_ns()
        r = self.ing.push(ev)
        self.lat["validate"].append((time.perf_counter_ns() - t0) / 1000)
        if r["status"] != "ACCEPTED":
            return {"status": "REJECTED", "reason": r["reason"]}
        t1 = time.perf_counter_ns()
        if r["segment"] != self.seg:                                         # gap / symbol change: state reset
            self.seg, self.prev, self.buf = r["segment"], None, []
            self.stack.reset()
            self.generation += 1
        mid, sp = (ev["bid"] + ev["ask"]) / 2, ev["ask"] - ev["bid"]
        act = ev.get("activity", 1.0)
        spok = 1.0 if ev.get("spread_ok", True) else 0.0
        if self.prev is None:
            self.prev = (ev["t"], mid, sp)
            return None
        dt, dm, dsp = ev["t"] - self.prev[0], mid - self.prev[1], (sp - self.prev[2]) if spok else 0.0
        self.prev = (ev["t"], mid, sp)
        f = np.array([math.log1p(dt), dm, abs(dm), float(np.sign(dm)), sp if spok else 0.0, dsp, math.log1p(max(act, 0)), spok])
        self.buf.append(self.sc.transform(f))
        self.lat["features"].append((time.perf_counter_ns() - t1) / 1000)
        if len(self.buf) < self.n:
            return None
        X = np.asarray(self.buf)[None]
        self.buf = []
        t2 = time.perf_counter_ns()
        q = self.m.encode_np(X)[0]
        t3 = time.perf_counter_ns()
        corr = self.stack.corr(q)
        _, valid = self.stack.snapshot()
        t4 = time.perf_counter_ns()
        lg = self.m.logits_np(q[None], corr[None], valid[None].astype(float))
        p = _softmax(lg / self.m.temperature)[0]
        t5 = time.perf_counter_ns()
        self.stack.push(q)                                                   # history updated AFTER the comparison
        t6 = time.perf_counter_ns()
        for k, a, b in (("encode", t2, t3), ("corr", t3, t4), ("head", t4, t5), ("stack_push", t5, t6)):
            self.lat[k].append((b - a) / 1000)
        return {"status": "OK", "symbol": self.symbol, "source_ts": ev["t"], "processed_ts": time.time(), "model_version": self.ver,
                "prediction_type": "CLASS_PROBABILITIES(DOWN,FLAT,UP) temperature-scaled", "probs": p.tolist(),
                "backend_used": self.stack.backend_used, "state_generation": self.generation, "execution_allowed": False}

    def latency(self) -> dict:
        return {k: {"n": len(v), "median_us": float(np.median(v)), "p95_us": float(np.percentile(v, 95))} for k, v in self.lat.items() if v}
