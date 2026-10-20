"""Minimal reverse-mode autodiff on NumPy (PMW-UPD-09, used by MQ_SPIKE_BRAIN_FINANCE_V1).

Every op stores its parents and a closure computing the vector-Jacobian product. `spike` is the only non-smooth op: forward Heaviside,
backward the adopted arctan surrogate (alpha) - verified in tests against its own formula, never by finite differences of the step.
`detach` stops the gradient (used for the reset term of LIF). No pickle, no global state; float64 for gradient checks.
"""
from __future__ import annotations

import math

import numpy as np


class T:
    __slots__ = ("data", "grad", "_parents", "_vjp", "name")

    def __init__(self, data, parents=(), vjp=None, name=None):
        self.data = np.asarray(data, dtype=np.float64)
        self.grad = None
        self._parents = parents
        self._vjp = vjp
        self.name = name

    # ---------------------------------------------------------------- graph
    def backward(self, g=None):
        topo, seen = [], set()
        stack = [(self, False)]
        while stack:                                            # iterative topological sort (deep BPTT graphs)
            n, done = stack.pop()
            if done:
                topo.append(n)
                continue
            if id(n) in seen:
                continue
            seen.add(id(n))
            stack.append((n, True))
            for p in n._parents:
                if id(p) not in seen:
                    stack.append((p, False))
        self.grad = np.ones_like(self.data) if g is None else g
        for n in reversed(topo):
            if n._vjp is None or n.grad is None:
                continue
            gs = n._vjp(n.grad)
            for p, gp in zip(n._parents, gs):
                if gp is None:
                    continue
                gp = _unbroadcast(gp, p.data.shape)
                p.grad = gp if p.grad is None else p.grad + gp

    @property
    def shape(self):
        return self.data.shape

    # ---------------------------------------------------------------- operators
    def __add__(self, o):
        o = _t(o)
        return T(self.data + o.data, (self, o), lambda g: (g, g))

    __radd__ = __add__

    def __sub__(self, o):
        o = _t(o)
        return T(self.data - o.data, (self, o), lambda g: (g, -g))

    def __rsub__(self, o):
        return _t(o) - self

    def __mul__(self, o):
        o = _t(o)
        a, b = self.data, o.data
        return T(a * b, (self, o), lambda g: (g * b, g * a))

    __rmul__ = __mul__

    def __truediv__(self, o):
        o = _t(o)
        a, b = self.data, o.data
        return T(a / b, (self, o), lambda g: (g / b, -g * a / (b * b)))

    def __neg__(self):
        return T(-self.data, (self,), lambda g: (-g,))

    def __matmul__(self, o):
        o = _t(o)
        a, b = self.data, o.data

        def vjp(g):
            ga = g @ np.swapaxes(b, -1, -2)
            gb = np.swapaxes(a, -1, -2) @ g
            return ga, gb
        return T(a @ b, (self, o), vjp)

    def __getitem__(self, idx):
        shp = self.data.shape

        def vjp(g):
            z = np.zeros(shp)
            np.add.at(z, idx, g)
            return (z,)
        return T(self.data[idx], (self,), vjp)

    def sum(self, axis=None, keepdims=False):
        shp = self.data.shape

        def vjp(g):
            if axis is not None and not keepdims:
                g = np.expand_dims(g, axis)
            return (np.broadcast_to(g, shp).copy(),)
        return T(self.data.sum(axis=axis, keepdims=keepdims), (self,), vjp)

    def mean(self, axis=None, keepdims=False):
        n = self.data.size if axis is None else self.data.shape[axis]
        return self.sum(axis, keepdims) * (1.0 / n)

    def reshape(self, *shape):
        shp = self.data.shape
        return T(self.data.reshape(*shape), (self,), lambda g: (g.reshape(shp),))

    def transpose(self, *axes):
        inv = np.argsort(axes)
        return T(self.data.transpose(*axes), (self,), lambda g: (g.transpose(*inv),))


def _t(x) -> T:
    return x if isinstance(x, T) else T(x)


def _unbroadcast(g, shape):
    while g.ndim > len(shape):
        g = g.sum(axis=0)
    for i, s in enumerate(shape):
        if s == 1 and g.shape[i] != 1:
            g = g.sum(axis=i, keepdims=True)
    return g


# -------------------------------------------------------------------- functions
def exp(x: T) -> T:
    y = np.exp(x.data)
    return T(y, (x,), lambda g: (g * y,))


def log(x: T) -> T:
    return T(np.log(x.data), (x,), lambda g: (g / x.data,))


def tanh(x: T) -> T:
    y = np.tanh(x.data)
    return T(y, (x,), lambda g: (g * (1 - y * y),))


def sigmoid(x: T) -> T:
    y = 0.5 * (1 + np.tanh(0.5 * x.data))
    return T(y, (x,), lambda g: (g * y * (1 - y),))


def relu(x: T) -> T:
    m = x.data > 0
    return T(x.data * m, (x,), lambda g: (g * m,))


def elu1(x: T) -> T:
    """phi(x) = ELU(x) + 1 (strictly positive feature map of linear attention)."""
    d = x.data
    y = np.where(d > 0, d + 1.0, np.exp(np.minimum(d, 0)))
    return T(y, (x,), lambda g: (g * np.where(d > 0, 1.0, np.exp(np.minimum(d, 0))),))


def softplus(x: T) -> T:
    d = x.data
    y = np.where(d > 20, d, np.log1p(np.exp(np.minimum(d, 20))))
    s = 0.5 * (1 + np.tanh(0.5 * d))
    return T(y, (x,), lambda g: (g * s,))


def softmax(x: T, axis=-1) -> T:
    z = x.data - x.data.max(axis=axis, keepdims=True)
    e = np.exp(z)
    y = e / e.sum(axis=axis, keepdims=True)
    return T(y, (x,), lambda g: (y * (g - (g * y).sum(axis=axis, keepdims=True)),))


def log_softmax(x: T, axis=-1) -> T:
    z = x.data - x.data.max(axis=axis, keepdims=True)
    lse = np.log(np.exp(z).sum(axis=axis, keepdims=True))
    y = z - lse
    p = np.exp(y)
    return T(y, (x,), lambda g: (g - p * g.sum(axis=axis, keepdims=True),))


def layernorm(x: T, eps=1e-5) -> T:
    """Per-token LayerNorm over the last axis (no affine; affine params are applied by the caller)."""
    mu = x.data.mean(axis=-1, keepdims=True)
    xc = x.data - mu
    var = (xc * xc).mean(axis=-1, keepdims=True)
    inv = 1.0 / np.sqrt(var + eps)
    y = xc * inv
    n = x.data.shape[-1]

    def vjp(g):
        return (inv / n * (n * g - g.sum(axis=-1, keepdims=True) - y * (g * y).sum(axis=-1, keepdims=True)),)
    return T(y, (x,), vjp)


def concat(xs: list[T], axis=-1) -> T:
    sizes = [x.data.shape[axis] for x in xs]
    cuts = np.cumsum(sizes)[:-1]

    def vjp(g):
        return tuple(np.split(g, cuts, axis=axis))
    return T(np.concatenate([x.data for x in xs], axis=axis), tuple(xs), vjp)


def stack(xs: list[T], axis=0) -> T:
    def vjp(g):
        return tuple(np.take(g, i, axis=axis) for i in range(len(xs)))
    return T(np.stack([x.data for x in xs], axis=axis), tuple(xs), vjp)


def detach(x: T) -> T:
    return T(x.data.copy())


def spike(u_minus_theta: T, alpha: float = 2.0) -> T:
    """Forward H(x) (x >= 0 fires); backward d/dx = (alpha/2) / (1 + (pi/2 * alpha * x)^2)."""
    x = u_minus_theta.data
    s = (x >= 0).astype(np.float64)
    sg = (alpha / 2.0) / (1.0 + (math.pi / 2.0 * alpha * x) ** 2)
    return T(s, (u_minus_theta,), lambda g: (g * sg,))


def scatter_rows(base: T, idx: np.ndarray, rows: T) -> T:
    """base with rows[k] added at base[idx[k]] (2-D, row dispatch for sparse experts)."""
    out = base.data.copy()
    np.add.at(out, idx, rows.data)
    return T(out, (base, rows), lambda g: (g, g[idx]))


class Adam:
    def __init__(self, params: dict[str, T], lr=1e-3, b1=0.9, b2=0.999, eps=1e-8, wd=0.0):
        self.p, self.lr, self.b1, self.b2, self.eps, self.wd = params, lr, b1, b2, eps, wd
        self.m = {k: np.zeros_like(v.data) for k, v in params.items()}
        self.v = {k: np.zeros_like(v.data) for k, v in params.items()}
        self.t = 0

    def step(self, clip: float | None = 1.0) -> float:
        grads = {k: (v.grad if v.grad is not None else np.zeros_like(v.data)) for k, v in self.p.items()}
        norm = float(np.sqrt(sum(float((g * g).sum()) for g in grads.values())))
        sc = clip / (norm + 1e-12) if clip and norm > clip else 1.0
        self.t += 1
        for k, g in grads.items():
            g = g * sc + (self.wd * self.p[k].data if (self.wd and k.startswith("W")) else 0.0)
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * g * g
            mh = self.m[k] / (1 - self.b1 ** self.t)
            vh = self.v[k] / (1 - self.b2 ** self.t)
            self.p[k].data = self.p[k].data - self.lr * mh / (np.sqrt(vh) + self.eps)
            self.p[k].grad = None
        return norm

    def state(self) -> dict:
        return {"t": self.t, **{f"m__{k}": v for k, v in self.m.items()}, **{f"v__{k}": v for k, v in self.v.items()}}

    def load_state(self, st: dict) -> None:
        self.t = int(st["t"])
        for k in self.m:
            self.m[k], self.v[k] = np.array(st[f"m__{k}"]), np.array(st[f"v__{k}"])
