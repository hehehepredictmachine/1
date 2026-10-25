"""Binary hyperdimensional computing (PMW-MM-HDC-1). ONLINE_LEARNER (integer accumulators = learned state).

Representation: D bits packed little-endian into ceil(D/64) uint64 words; bit j lives in word j//64 at position j%64. Padding bits of the
last word are always 0 (masked after every op) and never take part in rotation, distance or bundling.
  bind(a,b)    = a XOR b                                   (self-inverse, preserves Hamming distance)
  bundle(vs)   = per-bit majority; ties -> a seeded tie vector (no unseeded randomness; empty bundle = error)
  permute(v,k) = cyclic rotation of the full D-bit string by k (k mod D; positive = towards higher bit index)
  hamming      = popcount(a XOR b) over the D meaningful bits; similarity = 1 - 2H/D in [-1, 1]
Encoding: role vector per feature (seeded), level vectors per quantised level (level 0 random; level l flips the first
round(l*D/(2(L-1))) positions of a seeded permutation -> neighbouring levels are similar, extremes ~orthogonal). Quantiser bounds are
fitted on TRAINING rows only (q_lo/q_hi trimmed quantiles, clip outside). record = bundle_f bind(role_f, level(x_f)); a NaN feature is
left out of the bundle. Sequence (window r_0 oldest .. r_{n-1} newest) = bundle_k permute(r_k, n-1-k): the NEWEST record has rotation 0.
Classifier: per class an int32 accumulator of bipolar votes (+1 for a set bit, -1 for a clear bit). Prototype = acc > 0, acc == 0 -> tie
vector bit. Online update of one labelled example == full rebuild on the same rows/order when corrections are disabled (bit-exact).
Optional perceptron corrections (separate stage): for a misclassified training row acc[y] += x, acc[pred] -= x.
Null model: similarity of independent random vectors ~ N(0, 1/D) (sd = 1/sqrt(D)); the margin (difference of two such similarities against
independent prototypes) has sd = sqrt(2/D). The null threshold is z * sd. This is NOT a calibrated probability of a trained classifier.
Labels: `update(x, y, label_available_at, watermark)` refuses rows whose label is not yet available.
"""
from __future__ import annotations

import math
import time

import numpy as np

VERSION = "PMW-MM-HDC-1"
_POP = getattr(np, "bitwise_count", None)


def _popcount(a: np.ndarray) -> int:
    if _POP is not None:
        return int(_POP(a).sum())
    return int(np.unpackbits(a.view(np.uint8)).sum())


class Space:
    def __init__(self, D: int, seed: int = 20261025):
        if not (isinstance(D, int) and 64 <= D <= 1_000_000):
            raise ValueError("HDC_DIMENSION_INVALID")
        self.D, self.W, self.seed = D, (D + 63) // 64, seed
        pad = self.W * 64 - D
        self.mask = np.full(self.W, np.uint64(0xFFFFFFFFFFFFFFFF), dtype=np.uint64)
        if pad:
            self.mask[-1] = np.uint64((1 << (64 - pad)) - 1)
        self.tie = self.random(seed ^ 0x5EED)

    # ------------------------------------------------------------------ conversions
    def to_bits(self, v: np.ndarray) -> np.ndarray:
        return np.unpackbits(v.view(np.uint8), bitorder="little")[: self.D]

    def from_bits(self, bits: np.ndarray) -> np.ndarray:
        full = np.zeros(self.W * 64, dtype=np.uint8)
        full[: self.D] = bits.astype(np.uint8)
        return np.packbits(full, bitorder="little").view(np.uint64).copy()

    def random(self, seed: int) -> np.ndarray:
        g = np.random.Generator(np.random.PCG64(seed))
        return g.integers(0, np.iinfo(np.uint64).max, size=self.W, dtype=np.uint64, endpoint=True) & self.mask

    # ------------------------------------------------------------------ algebra
    def bind(self, a, b):
        return (a ^ b) & self.mask

    def permute(self, v, k: int):
        k %= self.D
        if k == 0:
            return v.copy()
        return self.from_bits(np.roll(self.to_bits(v), k))

    def bundle(self, vs: list[np.ndarray]) -> np.ndarray:
        if not vs:
            raise ValueError("HDC_EMPTY_BUNDLE")
        if len(vs) == 1:
            return vs[0].copy()
        cnt = np.sum([self.to_bits(v).astype(np.int32) for v in vs], axis=0)
        n = len(vs)
        tie = self.to_bits(self.tie)
        bits = np.where(2 * cnt > n, 1, np.where(2 * cnt < n, 0, tie))
        return self.from_bits(bits)

    def hamming(self, a, b) -> int:
        return _popcount((a ^ b) & self.mask)

    def similarity(self, a, b) -> float:
        return 1.0 - 2.0 * self.hamming(a, b) / self.D

    # ------------------------------------------------------------------ null model
    def null(self, z: float = 3.0) -> dict:
        sd = 1.0 / math.sqrt(self.D)
        return {"similarity_sd": sd, "similarity_threshold": z * sd, "margin_sd": math.sqrt(2.0 / self.D), "margin_threshold": z * math.sqrt(2.0 / self.D),
                "z": z, "assumption": "independent fair bits; correlated prototypes / large bundles change the real distractor distribution",
                "formula": "sim = 1-2H/D, Var = 1/D; margin of two independent sims, Var = 2/D"}


class Encoder:
    def __init__(self, space: Space, names: list[str], levels: int = 16, q_lo: float = 0.01, q_hi: float = 0.99, window: int = 1):
        if levels < 2 or not (0 <= q_lo < q_hi <= 1) or window < 1:
            raise ValueError("HDC_ENCODER_PARAM_INVALID")
        self.sp, self.names, self.L, self.q_lo, self.q_hi, self.window = space, list(names), levels, q_lo, q_hi, window
        self.roles = np.stack([space.random(space.seed + 101 + k) for k in range(len(names))])
        base = space.random(space.seed + 7)
        g = np.random.Generator(np.random.PCG64(space.seed + 13))
        perm = g.permutation(space.D)
        bb = space.to_bits(base)
        lv = []
        for l in range(levels):  # noqa: E741
            flips = int(round(l * space.D / (2.0 * (levels - 1))))
            b2 = bb.copy()
            b2[perm[:flips]] ^= 1
            lv.append(space.from_bits(b2))
        self.levels = np.stack(lv)
        self.lo = self.hi = None

    def fit(self, X_train: np.ndarray):
        X = np.asarray(X_train, float)
        self.lo = np.nanquantile(X, self.q_lo, axis=0)
        self.hi = np.nanquantile(X, self.q_hi, axis=0)
        same = self.hi <= self.lo
        self.hi = np.where(same, self.lo + 1e-12, self.hi)
        return self

    def quantize(self, x: np.ndarray) -> np.ndarray:
        if self.lo is None:
            raise RuntimeError("HDC_QUANTIZER_NOT_FITTED")
        q = np.floor((np.clip(x, self.lo, self.hi) - self.lo) / (self.hi - self.lo) * self.L)
        q = np.clip(q, 0, self.L - 1)
        return np.where(np.isfinite(x), q, -1).astype(int)

    def record(self, x: np.ndarray) -> np.ndarray:
        q = self.quantize(np.asarray(x, float))
        parts = [self.sp.bind(self.roles[f], self.levels[q[f]]) for f in range(len(q)) if q[f] >= 0]
        return self.sp.bundle(parts)

    def sequence(self, rows: np.ndarray) -> np.ndarray:
        n = len(rows)
        return self.sp.bundle([self.sp.permute(self.record(r), n - 1 - k) for k, r in enumerate(rows)])

    def encode(self, X: np.ndarray, i: int) -> np.ndarray:
        """Encoding of sample i using rows i-window+1 .. i (all available at i's close)."""
        return self.record(X[i]) if self.window == 1 else self.sequence(X[i - self.window + 1:i + 1])


class Classifier:
    ACC_LIMIT = 2 ** 31 - 2

    def __init__(self, space: Space, n_classes: int):
        self.sp, self.C = space, n_classes
        self.acc = np.zeros((n_classes, space.D), dtype=np.int32)
        self.updates = 0
        self.corrections = 0
        self.protos = None

    def reset(self):
        self.acc[:] = 0
        self.updates = self.corrections = 0
        self.protos = None

    def _bip(self, v) -> np.ndarray:
        return self.sp.to_bits(v).astype(np.int32) * 2 - 1

    def update(self, v: np.ndarray, y: int, label_available_at: float | None = None, watermark: float | None = None) -> bool:
        if label_available_at is not None and watermark is not None and label_available_at > watermark:
            return False                                              # label not observable yet - never trained on
        if self.updates >= self.ACC_LIMIT:
            raise OverflowError("HDC_ACCUMULATOR_LIMIT")
        self.acc[y] += self._bip(v)
        self.updates += 1
        self.protos = None
        return True

    def finalize(self) -> np.ndarray:
        tie = self.sp.to_bits(self.sp.tie)
        self.protos = np.stack([self.sp.from_bits(np.where(a > 0, 1, np.where(a < 0, 0, tie))) for a in self.acc])
        return self.protos

    def scores(self, v: np.ndarray) -> np.ndarray:
        if self.protos is None:
            self.finalize()
        return np.array([self.sp.similarity(v, p) for p in self.protos])

    def predict(self, v: np.ndarray) -> tuple[int, float, np.ndarray]:
        s = self.scores(v)
        o = np.argsort(-s, kind="stable")
        return int(o[0]), float(s[o[0]] - s[o[1]]), s

    def correct(self, V: list[np.ndarray], y: np.ndarray, passes: int = 1) -> int:
        """Optional perceptron correction stage (changes the model; not equivalent to a rebuild)."""
        n = 0
        for _ in range(passes):
            self.finalize()
            for v, yy in zip(V, y):
                p, _, _ = self.predict(v)
                if p != yy:
                    b = self._bip(v)
                    self.acc[yy] += b
                    self.acc[p] -= b
                    n += 1
                    self.protos = None
        self.corrections += n
        return n


def measure_update_latency(space: Space, enc: Encoder, X: np.ndarray, y: np.ndarray, n: int = 300) -> dict:
    clf = Classifier(space, int(y.max()) + 1)
    for i in range(min(50, len(X))):                                   # warm-up
        clf.update(enc.encode(X, max(i, enc.window - 1)), int(y[i]))
    lat = []
    for i in range(enc.window - 1, min(len(X), enc.window - 1 + n)):
        t0 = time.perf_counter_ns()
        clf.update(enc.encode(X, i), int(y[i]))
        lat.append((time.perf_counter_ns() - t0) / 1000)
    a = np.asarray(lat)
    import platform
    return {"n": int(len(a)), "median_us": float(np.median(a)), "p95_us": float(np.percentile(a, 95)), "D": space.D, "features": len(enc.names),
            "window": enc.window, "method": "perf_counter_ns around encode+update of one row (Python/numpy)", "cpu": platform.processor() or platform.machine(),
            "platform": platform.platform(), "reference": "artykuł MQL5 podaje ~337 µs w swoim środowisku - nie jest to cel ani gwarancja"}
