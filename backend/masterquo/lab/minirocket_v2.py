"""MQ_MINIROCKET_UNIVARIATE_V2 transform + MQ_MINIROCKET_RIDGE_V2 head (PMW-UPD-09 R21). Clean-room implementation from the published
method description (Dempster, Schmidt, Webb 2021); the authors' GPL-3.0 code and sktime source were NOT copied. The legacy profile
MINIROCKET-NP-1.0.0 (lab/minirocket.py) stays untouched for old multichannel artefacts.

Lifecycle: configure(L, requested, max_dilations) -> fit(X_train[, fit_window_indices]) -> transform(X); reconfigure invalidates fit;
transform before fit = NOT_FITTED; empty / NaN / mixed length / L<9 are refused (never a vector of zeros).
Layout (pinned, carried in the artefact and to MQL5, never re-guessed at load):
  F = 84*floor(requested/84); per kernel fpk = F/84; dilations = unique(int32(logspace(0, log2((L-1)/8), min(fpk, max_dil), base 2)))
  with their repeat counts * (fpk/true_max) truncated, remainder distributed round-robin from the smallest dilation.
  L=128, requested 10000, max 32 -> F 9996, dilations 1..15, counts [30,19,12,12,8,4,8,4,4,3,3,3,3,3,3] (golden, test T111).
  order dilation -> kernel (84 lexicographic triples of 0..8, weights six -1 and three +2) -> quantile.
  quantiles: ONE global low-discrepancy sequence q_k = frac(k * phi), k = 1..F, float32 (not restarted per kernel).
Fit: for every (dilation, kernel) its OWN training window (portable SplitMix64 PRNG -> fit_window_indices, exported); bias b = quantile
  (numpy 'linear' interpolation) of the FULL zero-padded convolution (length L) even for centre-only features.
Transform: PPV = #(conv > b) / denominator (strict >, equality is not a hit); padded features use all L positions, centre-only ones
  (alternation (dilation_index + kernel_index) odd) use L - 8d positions. Shared terms per dilation: alpha = -sum of nine taps
  (float32, pinned order centre, -4d..-1d, +1d..+4d), gamma_j = 3 x tap_j; conv(kernel) = ((alpha + gamma_a) + gamma_b) + gamma_c.
Input profile PRICE_PATH_ATR_V1: (C_j - C_first) / max(ATR_decision, tick) over the last 128 closes - ATR and C_first known at decision.
Ridge head: scaler fitted on FIT rows; ridge with an UNPENALISED intercept (centred data); per horizon 3 class indicator scores + the
  normalised move r_h; L2 chosen inside FIT/TUNE only; dual Cholesky solve for N <= 2048, otherwise blocked normal-equation CG with a
  diagonal preconditioner (no explicit inverse, no N x N Gram for large N); non-convergence -> SOLVER_NOT_CONVERGED (no activation).
  Raw scores are NOT probabilities: temperature calibration on CALIBRATION, otherwise UNCALIBRATED; intervals
  CALIBRATED_RESIDUAL_LOCATION_V1 q_a = f(x) + Q_a(y - f(x)) from CALIBRATION (no conformal guarantee for dependent data).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import time
from itertools import combinations
from pathlib import Path

import numpy as np

TRANSFORM_ID = "MQ_MINIROCKET_UNIVARIATE_V2"
HEAD_ID = "MQ_MINIROCKET_RIDGE_V2"
VERSION = "MQ-MINIROCKET-2.0.0"
INPUT_PROFILE = "PRICE_PATH_ATR_V1"
KERNELS = np.array(list(combinations(range(9), 3)), dtype=np.int32)       # 84 x 3, lexicographic
PHI = (math.sqrt(5.0) + 1.0) / 2.0
FORMAT_MAGIC = b"PMWMR2\x00\x00"
FORMAT_VERSION = 1
RESULT_MAGIC = b"PMWMRRES"
MAX_MODEL_BYTES = 64 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024
DUAL_MAX_N = 2048
PARITY_STATES = ("ALGORITHM_VALIDATED", "FROZEN_STATE_PARITY", "FIT_LAYOUT_PARITY", "FIT_RANDOM_SELECTION_PARITY", "HEAD_PARITY",
                 "NATIVE_COMPILED", "NATIVE_EXECUTED")


class MRError(ValueError):
    pass


# ===================================================================== layout / PRNG
def layout(L: int, requested: int = 10000, max_dilations: int = 32) -> dict:
    if L < 9:
        raise MRError("INPUT_TOO_SHORT: L<9")
    if requested < 84:
        raise MRError("FEATURE_BUDGET_TOO_SMALL: requested<84")
    if max_dilations < 1:
        raise MRError("MAX_DILATIONS_INVALID")
    fpk = requested // 84
    true_max = min(fpk, max_dilations)
    mult = fpk / true_max
    max_exp = math.log2((L - 1) / 8) if L > 9 else 0.0
    d, cnt = np.unique(np.logspace(0, max_exp, true_max, base=2).astype(np.int32), return_counts=True)
    cnt = (cnt * mult).astype(np.int32)
    rem = fpk - int(cnt.sum())
    i = 0
    while rem > 0:
        cnt[i] += 1
        rem -= 1
        i = (i + 1) % len(cnt)
    F = 84 * int(cnt.sum())
    q = np.array([(k * PHI) % 1 for k in range(1, F + 1)], dtype=np.float32)
    pad = [(di + k) % 2 == 0 for di in range(len(d)) for k in range(84)]
    return {"L": int(L), "requested": int(requested), "max_dilations": int(max_dilations), "F": F, "dilations": d.tolist(),
            "counts": cnt.tolist(), "quantiles": q, "padded": pad, "order": "dilation->kernel->quantile",
            "quantile_dtype": "float32", "interpolation": "linear", "features_per_kernel": fpk}


class SplitMix64:
    """Portable PRNG (same sequence in Python and MQL5 - ulong arithmetic mod 2^64)."""
    M = (1 << 64) - 1

    def __init__(self, seed: int):
        self.s = seed & self.M

    def next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & self.M
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.M
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.M
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        return self.next() % n


def fit_window_indices(n_examples: int, n_dilations: int, seed: int) -> np.ndarray:
    r = SplitMix64(seed)
    return np.array([r.below(n_examples) for _ in range(n_dilations * 84)], dtype=np.int32)


# ===================================================================== convolution (shared terms)
def _terms(x: np.ndarray, d: int) -> tuple[np.ndarray, np.ndarray]:
    """x (n, L) float32 -> alpha (n, L) = -sum of nine zero-padded taps, gamma (9, n, L) = 3*tap_j. Output position t is centred:
    tap j reads x[t + (j-4) d] (zero outside)."""
    n, L = x.shape
    gam = np.zeros((9, n, L), dtype=np.float32)
    for j in range(9):
        s = (j - 4) * d
        if s >= 0:
            if s < L:
                gam[j, :, :L - s] = x[:, s:]
        else:
            if -s < L:
                gam[j, :, -s:] = x[:, :L + s]
    alpha = -gam[4]                                       # pinned float32 accumulation order: centre, taps -4d..-1d, then +1d..+4d
    for j in (0, 1, 2, 3, 5, 6, 7, 8):
        alpha = alpha - gam[j]
    return alpha, gam * np.float32(3.0)


def conv_full(x: np.ndarray, d: int, k: int, terms=None) -> np.ndarray:
    a, g = terms if terms is not None else _terms(x, d)
    i0, i1, i2 = KERNELS[k]
    return a + g[i0] + g[i1] + g[i2]


def _check_X(X) -> np.ndarray:
    if X is None:
        raise MRError("EMPTY_INPUT")
    if isinstance(X, list):
        if not X:
            raise MRError("EMPTY_INPUT")
        if len({len(r) for r in X}) != 1:
            raise MRError("MIXED_LENGTH")
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2 or X.shape[0] == 0 or X.shape[1] == 0:
        raise MRError("EMPTY_OR_NOT_2D")
    if X.shape[1] < 9:
        raise MRError("INPUT_TOO_SHORT: L<9")
    if not np.isfinite(X).all():
        raise MRError("NON_FINITE_INPUT (brak imputacji zerami)")
    return X.astype(np.float32)


class MiniRocketV2:
    def __init__(self):
        self.lay = None
        self.biases = None
        self.fit_idx = None
        self.fit_info = None

    # ---------------------------------------------------------------- lifecycle
    def configure(self, L: int, requested: int = 10000, max_dilations: int = 32) -> "MiniRocketV2":
        self.lay = layout(L, requested, max_dilations)
        self.biases = self.fit_idx = self.fit_info = None                   # reconfigure invalidates Fit
        return self

    def reset(self) -> None:
        self.lay = self.biases = self.fit_idx = self.fit_info = None

    def validate_state(self) -> dict:
        if self.lay is None:
            return {"status": "NOT_CONFIGURED"}
        if self.biases is None:
            return {"status": "NOT_FITTED", "F": self.lay["F"]}
        ok = len(self.biases) == self.lay["F"] and np.isfinite(self.biases).all()
        return {"status": "READY" if ok else "INCOMPATIBLE", "F": self.lay["F"], "bias_sha256": self.bias_hash()}

    def bias_hash(self) -> str:
        return hashlib.sha256(np.ascontiguousarray(self.biases, dtype="<f4").tobytes()).hexdigest()

    def fit(self, X, seed: int = 0, indices: np.ndarray | None = None, mode: str = "PER_KERNEL_RANDOM") -> "MiniRocketV2":
        """X: TRAIN windows only. mode PER_KERNEL_RANDOM (portable SplitMix64 indices, or given frozen `indices`) or SINGLE_WINDOW
        (all kernels from window 0 - removes random selection; reported separately, it is not the full Fit)."""
        if self.lay is None:
            raise MRError("NOT_CONFIGURED")
        X = _check_X(X)
        if X.shape[1] != self.lay["L"]:
            raise MRError(f"LENGTH_MISMATCH: {X.shape[1]} != {self.lay['L']}")
        nd = len(self.lay["dilations"])
        if indices is not None:
            idx = np.asarray(indices, dtype=np.int32)
            if idx.shape != (nd * 84,) or idx.min() < 0 or idx.max() >= len(X):
                raise MRError("FIT_INDICES_INVALID")
            src = "FROZEN_INDICES"
        elif mode == "SINGLE_WINDOW":
            idx = np.zeros(nd * 84, dtype=np.int32)
            src = "SINGLE_WINDOW"
        else:
            idx = fit_window_indices(len(X), nd, seed)
            src = "SPLITMIX64"
        q = self.lay["quantiles"]
        b = np.zeros(self.lay["F"], dtype=np.float32)
        f0 = 0
        for di, d in enumerate(self.lay["dilations"]):
            nf = self.lay["counts"][di]
            for k in range(84):
                xw = X[idx[di * 84 + k]][None, :]
                c = conv_full(xw, d, k)[0]                               # FULL padded output even for centre-only features
                b[f0:f0 + nf] = np.quantile(c, q[f0:f0 + nf].astype(np.float64)).astype(np.float32)
                f0 += nf
        self.biases, self.fit_idx = b, idx
        self.fit_info = {"source": src, "seed": seed if src == "SPLITMIX64" else None, "n_train_windows": int(len(X)),
                         "fit_indices_sha256": hashlib.sha256(idx.astype("<i4").tobytes()).hexdigest(), "bias_sha256": self.bias_hash()}
        return self

    def counts(self, X) -> tuple[np.ndarray, np.ndarray]:
        """(hit_count (n, F) int32, denominator (F,) int32) - diagnostic integer form of PPV."""
        if self.lay is None:
            raise MRError("NOT_CONFIGURED")
        if self.biases is None:
            raise MRError("NOT_FITTED")
        X = _check_X(X)
        L = self.lay["L"]
        if X.shape[1] != L:
            raise MRError(f"LENGTH_MISMATCH: {X.shape[1]} != {L}")
        n, F = len(X), self.lay["F"]
        H = np.zeros((n, F), dtype=np.int32)
        den = np.zeros(F, dtype=np.int32)
        f0 = 0
        for di, d in enumerate(self.lay["dilations"]):
            nf = self.lay["counts"][di]
            terms = _terms(X, d)
            p = (8 * d) // 2
            for k in range(84):
                c = conv_full(X, d, k, terms)
                if (di + k) % 2 == 1:
                    c = c[:, p:L - p]
                    if c.shape[1] <= 0:
                        raise MRError("EMPTY_SEGMENT")
                bb = self.biases[f0:f0 + nf]
                H[:, f0:f0 + nf] = (c[:, :, None] > bb[None, None, :]).sum(axis=1)
                den[f0:f0 + nf] = c.shape[1]
                f0 += nf
        return H, den

    def transform(self, X) -> np.ndarray:
        H, den = self.counts(X)
        return (H / den[None, :]).astype(np.float32)

    def state(self) -> dict:
        lay = {k: v for k, v in (self.lay or {}).items() if k != "quantiles"}
        return {"transform_id": TRANSFORM_ID, "version": VERSION, "layout": lay, "fit": self.fit_info}


# ===================================================================== input profile
def price_path_atr(c: np.ndarray, end: int, atr_end: float, tick: float, L: int = 128) -> np.ndarray | None:
    """Window of the last L closes ending at `end` (inclusive), normalised by the ATR known at `end`."""
    if end - L + 1 < 0 or not np.isfinite(atr_end):
        return None
    w = np.asarray(c[end - L + 1:end + 1], dtype=np.float64)
    return (w - w[0]) / max(float(atr_end), float(tick))


# ===================================================================== ridge
def cg_solve(matvec, b: np.ndarray, diag: np.ndarray, tol: float = 1e-6, max_iter: int = 500) -> tuple[np.ndarray, dict]:
    """Preconditioned CG for an SPD operator (one right-hand side)."""
    x = np.zeros_like(b)
    r = b.copy()
    z = r / diag
    p = z.copy()
    rz = float(r @ z)
    bn = float(np.linalg.norm(b)) or 1.0
    it = 0
    for it in range(1, max_iter + 1):
        Ap = matvec(p)
        a = rz / float(p @ Ap)
        x += a * p
        r -= a * Ap
        rel = float(np.linalg.norm(r)) / bn
        if rel <= tol:
            return x, {"converged": True, "iterations": it, "rel_residual": rel}
        z = r / diag
        rz_n = float(r @ z)
        p = z + (rz_n / rz) * p
        rz = rz_n
    return x, {"converged": False, "iterations": it, "rel_residual": float(np.linalg.norm(r)) / bn}


def ridge_solve(Xs: np.ndarray, Y: np.ndarray, lam: float, method: str = "AUTO", tol: float = 1e-8, max_iter: int = 1000, chunk: int = 4096) -> tuple[np.ndarray, dict]:
    """Xs (N, D) CENTRED/standardised, Y (N, K) centred. Returns W (D, K). DUAL: (Xs Xs^T + lam I) A = Y (Cholesky), W = Xs^T A;
    CG: blocked operator v -> Xs^T (Xs v) + lam v with diagonal preconditioner, chunked over rows (no D x D, no N x N)."""
    N, D = Xs.shape
    if method == "AUTO":
        method = "DUAL" if N <= DUAL_MAX_N else "CG"
    if method == "DUAL":
        if N > DUAL_MAX_N:
            raise MRError("DUAL_N_LIMIT")
        K = Xs @ Xs.T
        K[np.diag_indices(N)] += lam
        Lc = np.linalg.cholesky(K)
        A = np.linalg.solve(Lc.T, np.linalg.solve(Lc, Y))
        W = Xs.T @ A
        res = float(np.linalg.norm(Xs.T @ (Y - Xs @ W) - lam * W)) / (float(np.linalg.norm(Xs.T @ Y)) or 1.0)
        return W, {"method": "DUAL_CHOLESKY", "converged": True, "rel_residual": res, "cond_est": float(np.linalg.cond(K)) if N <= 512 else None}

    def mv(v):
        out = lam * v
        for s in range(0, N, chunk):
            xb = Xs[s:s + chunk]
            out = out + xb.T @ (xb @ v)
        return out
    diag = lam + sum(((Xs[s:s + chunk] ** 2).sum(axis=0) for s in range(0, N, chunk)))
    W = np.zeros((D, Y.shape[1]))
    infos = []
    for k in range(Y.shape[1]):
        bk = sum((Xs[s:s + chunk].T @ Y[s:s + chunk, k] for s in range(0, N, chunk)))
        W[:, k], inf = cg_solve(mv, bk, diag, tol, max_iter)
        infos.append(inf)
    ok = all(i["converged"] for i in infos)
    return W, {"method": "CG_DIAG_PRECOND", "converged": ok, "iterations": [i["iterations"] for i in infos],
               "rel_residual": max(i["rel_residual"] for i in infos), "status": None if ok else "SOLVER_NOT_CONVERGED"}


def _softmax(z):
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


class RidgeHeadV2:
    """Scaler (FIT) + ridge per horizon: outputs (N, H, 3) raw class scores and (N, H) r_h regression."""
    LAMBDAS = (1e-1, 1.0, 10.0, 100.0, 1000.0)

    def __init__(self, n_heads: int):
        self.H = n_heads
        self.mu = self.sd = None
        self.W = self.b = None                           # W (H, D, 4), b (H, 4)
        self.lam = [None] * n_heads
        self.solver = [None] * n_heads
        self.res_q = None
        self.status = "NOT_FITTED"

    def _z(self, Z):
        return (np.asarray(Z, dtype=np.float64) - self.mu) / self.sd

    @staticmethod
    def _targets(y, r):
        T = np.zeros((len(y), 4))
        T[np.arange(len(y)), y] = 1.0
        T[:, 3] = r
        return T

    def fit(self, Z, Y, R, fit, tune, method: str = "AUTO") -> "RidgeHeadV2":
        Zf = np.asarray(Z[fit], dtype=np.float64)
        self.mu = Zf.mean(axis=0)
        sd = Zf.std(axis=0)
        self.sd = np.where(sd > 1e-9, sd, 1.0)                               # constant PPV columns: centred to 0, not amplified
        D = Z.shape[1]
        self.W, self.b = np.zeros((self.H, D, 4)), np.zeros((self.H, 4))
        for j in range(self.H):
            mf = fit[(Y[fit, j] >= 0) & np.isfinite(R[fit, j])]
            mt = tune[(Y[tune, j] >= 0) & np.isfinite(R[tune, j])] if tune is not None and len(tune) else np.array([], int)
            if len(mf) < 10:
                self.solver[j] = {"status": "INSUFFICIENT_ROWS"}
                continue
            Xf = self._z(Z[mf])
            Tf = self._targets(Y[mf, j], R[mf, j])
            tm = Tf.mean(axis=0)
            best = None
            for lam in (self.LAMBDAS if len(mt) >= 10 else (100.0,)):
                W, info = ridge_solve(Xf, Tf - tm, lam * len(mf) / 100.0, method)
                if not info["converged"]:
                    continue
                if len(mt):
                    pt = self._z(Z[mt]) @ W + tm
                    mse = float(np.mean((pt - self._targets(Y[mt, j], R[mt, j])) ** 2))
                else:
                    mse = 0.0
                if best is None or mse < best[0]:
                    best = (mse, lam, W, info)
            if best is None:
                self.solver[j] = {"status": "SOLVER_NOT_CONVERGED"}
                continue
            self.W[j], self.b[j], self.lam[j], self.solver[j] = best[2], tm, best[1], dict(best[3], tune_mse=best[0])
        bad = [j for j in range(self.H) if (self.solver[j] or {}).get("status") in ("SOLVER_NOT_CONVERGED", "INSUFFICIENT_ROWS")]
        self.status = "TRAINED" if not bad else ("SOLVER_NOT_CONVERGED" if any(self.solver[j]["status"] == "SOLVER_NOT_CONVERGED" for j in bad) else "PARTIAL")
        return self

    def raw(self, Z) -> tuple[np.ndarray, np.ndarray]:
        X = self._z(Z)
        out = np.einsum("nd,hdk->nhk", X, self.W) + self.b[None]
        return out[:, :, :3], out[:, :, 3]

    def fit_residuals(self, Z, Y, R, cal) -> None:
        _, f = self.raw(Z[cal])
        self.res_q = np.zeros((self.H, 3))
        for j in range(self.H):
            m = np.isfinite(R[cal, j])
            e = R[cal, j][m] - f[m, j]
            self.res_q[j] = np.quantile(e, (0.1, 0.5, 0.9)) if len(e) >= 10 else (np.nan, np.nan, np.nan)

    def predict(self, Z) -> tuple[np.ndarray, np.ndarray]:
        """P (N, H, 3) = softmax(raw scores) - UNCALIBRATED until a temperature is applied by the caller; Q (N, H, 3) residual-location."""
        S, f = self.raw(Z)
        P = _softmax(S)
        rq = self.res_q if self.res_q is not None else np.zeros((self.H, 3))
        Q = f[:, :, None] + rq[None]
        Q = np.sort(Q, axis=-1)
        return P, Q


# ===================================================================== portable binary format (Python <-> MQL5)
_DT = {"i4": (1, "<i4"), "f4": (2, "<f4"), "f8": (3, "<f8")}
_DT_REV = {v[0]: (k, v[1]) for k, v in _DT.items()}


def _section(tag: str, arr: np.ndarray, dt: str) -> bytes:
    a = np.ascontiguousarray(arr, dtype=_DT[dt][1]).ravel()
    body = a.tobytes()
    return tag.encode("ascii").ljust(4, b" ")[:4] + struct.pack("<IIQ", _DT[dt][0], a.size, len(body)) + body


def model_arrays(mr: MiniRocketV2, head: RidgeHeadV2, temps: list[float]) -> dict:
    return {"DILS": (np.array(mr.lay["dilations"]), "i4"), "CNTS": (np.array(mr.lay["counts"]), "i4"), "QUAN": (mr.lay["quantiles"], "f4"),
            "BIAS": (mr.biases, "f4"), "FIDX": (mr.fit_idx, "i4"), "SCMU": (head.mu, "f8"), "SCSD": (head.sd, "f8"),
            "COEF": (head.W, "f8"), "ICPT": (head.b, "f8"), "TEMP": (np.array(temps, dtype=np.float64), "f8"),
            "RESQ": (head.res_q if head.res_q is not None else np.full((head.H, 3), np.nan), "f8"),
            "META": (np.array([mr.lay["L"], mr.lay["F"], head.H, 3], dtype=np.int32), "i4")}


def write_model_bin(path: Path, arrays: dict) -> str:
    body = FORMAT_MAGIC + struct.pack("<III", FORMAT_VERSION, 0x01020304, len(arrays))
    for tag, (a, dt) in arrays.items():
        body += _section(tag, a, dt)
    digest = hashlib.sha256(body).digest()
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(body + digest)
    os.replace(tmp, path)
    return digest.hex()


def read_model_bin(path: Path, max_bytes: int = MAX_MODEL_BYTES) -> dict:
    """Validates size, magic, version, endian marker, every section length (before allocation) and the SHA-256 trailer."""
    size = path.stat().st_size
    if size > max_bytes:
        raise MRError("MODEL_FILE_TOO_LARGE")
    raw = path.read_bytes()
    if len(raw) < 8 + 12 + 32:
        raise MRError("MODEL_FILE_TRUNCATED")
    body, digest = raw[:-32], raw[-32:]
    if hashlib.sha256(body).digest() != digest:
        raise MRError("CHECKSUM_MISMATCH")
    if body[:8] != FORMAT_MAGIC:
        raise MRError("BAD_MAGIC")
    ver, endian, nsec = struct.unpack_from("<III", body, 8)
    if ver != FORMAT_VERSION:
        raise MRError(f"UNSUPPORTED_VERSION:{ver}")
    if endian != 0x01020304:
        raise MRError("ENDIAN_MISMATCH")
    off, out = 20, {}
    for _ in range(nsec):
        if off + 20 > len(body):
            raise MRError("MODEL_FILE_TRUNCATED")
        tag = body[off:off + 4].decode("ascii").strip()
        code, count, nbytes = struct.unpack_from("<IIQ", body, off + 4)
        if code not in _DT_REV:
            raise MRError(f"BAD_DTYPE:{tag}")
        item = np.dtype(_DT_REV[code][1]).itemsize
        if nbytes != count * item or off + 20 + nbytes > len(body):
            raise MRError(f"BAD_SECTION_LENGTH:{tag}")
        out[tag] = np.frombuffer(body, dtype=_DT_REV[code][1], count=count, offset=off + 20).copy()
        off += 20 + nbytes
    if off != len(body):
        raise MRError("TRAILING_BYTES")
    return out


def export_native(model_dir: Path, mr: MiniRocketV2, head: RidgeHeadV2, temps: list[float], meta: dict) -> dict:
    """Atomic export: build in <dir>.tmp, then swap; the previous export is kept as <dir>.prev (last compatible model)."""
    out = Path(model_dir)
    tmp = out.with_name(out.name + ".tmp")
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    sha = write_model_bin(tmp / "model.bin", model_arrays(mr, head, temps))
    man = {"schema": "PMW-MR2-NATIVE-1", "format_version": FORMAT_VERSION, "endian": "little", "transform_id": TRANSFORM_ID, "head_id": HEAD_ID,
           "version": VERSION, "input_profile": INPUT_PROFILE, "layout": {k: v for k, v in mr.lay.items() if k != "quantiles"}, "fit": mr.fit_info,
           "class_order": ["DOWN", "FLAT", "UP"], "horizons": meta.get("horizons"), "calibration": meta.get("calibration_status", "UNCALIBRATED"),
           "intervals": "CALIBRATED_RESIDUAL_LOCATION_V1" if head.res_q is not None else "NONE", "model_bin_sha256": sha,
           "source_model": meta.get("model_hash"), "instrument": meta.get("instrument"), "role": meta.get("role"),
           "sections": {k: {"dtype": dt, "shape": list(np.shape(a))} for k, (a, dt) in model_arrays(mr, head, temps).items()}}
    (tmp / "manifest.json").write_text(json.dumps(man, indent=1, default=float), encoding="utf-8")
    prev = out.with_name(out.name + ".prev")
    if out.exists():
        import shutil
        if prev.exists():
            shutil.rmtree(prev)
        out.rename(prev)
    tmp.rename(out)
    return man


def import_native(model_dir: Path) -> tuple[MiniRocketV2, RidgeHeadV2, list[float], dict]:
    man = json.loads((Path(model_dir) / "manifest.json").read_text(encoding="utf-8"))
    if man.get("schema") != "PMW-MR2-NATIVE-1" or man.get("format_version") != FORMAT_VERSION:
        raise MRError("UNSUPPORTED_MANIFEST")
    a = read_model_bin(Path(model_dir) / "model.bin")
    if hashlib.sha256((Path(model_dir) / "model.bin").read_bytes()[:-32]).hexdigest() != man["model_bin_sha256"]:
        raise MRError("MANIFEST_SHA_MISMATCH")
    L, F, H, _ = (int(x) for x in a["META"])
    mr = MiniRocketV2().configure(L, man["layout"]["requested"], man["layout"]["max_dilations"])
    if mr.lay["dilations"] != a["DILS"].tolist() or mr.lay["counts"] != a["CNTS"].tolist() or mr.lay["F"] != F:
        raise MRError("LAYOUT_MISMATCH")
    if a["BIAS"].size != F or a["COEF"].size != H * F * 4:
        raise MRError("SHAPE_MISMATCH")
    mr.biases, mr.fit_idx, mr.fit_info = a["BIAS"].astype(np.float32), a["FIDX"], man.get("fit")
    head = RidgeHeadV2(H)
    head.mu, head.sd = a["SCMU"], a["SCSD"]
    head.W, head.b = a["COEF"].reshape(H, F, 4), a["ICPT"].reshape(H, 4)
    rq = a["RESQ"].reshape(H, 3)
    head.res_q = None if np.isnan(rq).all() else rq
    head.status = "TRAINED"
    return mr, head, a["TEMP"].tolist(), man


# ===================================================================== native result importer (read-only, SHADOW audit)
class NativeResultImporter:
    """Reads PMW_MR2_RESULT.bin written atomically by the MQL5 indicator into the MT5 Files sandbox. Whitelisted directory only,
    size limit, SHA-256 trailer, model hash, context, monotonic sequence and max age; never overrides the main forecast or the Lock."""
    NAME = "PMW_MR2_RESULT.bin"

    def __init__(self, files_dir: str | None, expected_model_sha: str | None, symbol: str, tf: str = "M1", max_age_s: float = 180.0):
        self.dir = Path(files_dir) if files_dir else None
        self.model_sha, self.symbol, self.tf, self.max_age = expected_model_sha, symbol, tf, max_age_s
        self.last_seq = -1
        self.last: dict | None = None

    def poll(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        if self.dir is None or not self.dir.is_dir():
            return {"status": "NATIVE_FEED_UNAVAILABLE", "reason": "brak skonfigurowanego folderu MT5 Files (MQ_MT5_FILES_DIR)"}
        p = (self.dir / self.NAME).resolve()
        if p.parent != self.dir.resolve():
            return {"status": "REJECTED", "reason": "PATH_NOT_WHITELISTED"}
        if not p.exists():
            return {"status": "NATIVE_FEED_UNAVAILABLE", "reason": "brak pliku wyniku wskaźnika"}
        try:
            r = parse_result(p.read_bytes() if p.stat().st_size <= MAX_RESULT_BYTES else b"")
        except MRError as exc:
            return {"status": "REJECTED", "reason": str(exc)}
        if self.model_sha and r["model_sha256"] != self.model_sha:
            return {"status": "REJECTED", "reason": "MODEL_MISMATCH"}
        if r["symbol"] != self.symbol or r["tf"] != self.tf:
            return {"status": "REJECTED", "reason": "CONTEXT_MISMATCH"}
        if r["seq"] <= self.last_seq:
            return {"status": "STALE_SEQUENCE", "seq": r["seq"], "last_seq": self.last_seq, "last": self.last}
        if now - r["computed_at_utc"] > self.max_age:
            return {"status": "REJECTED", "reason": "RESULT_TOO_OLD", "age_s": now - r["computed_at_utc"]}
        self.last_seq = r["seq"]
        self.last = dict(r, status="IMPORTED", role="SHADOW_AUDIT")
        return self.last


def write_result(path: Path, seq: int, model_sha: str, symbol: str, tf: str, bar_time_utc: int, computed_at_utc: int, clock_basis: str,
                 scores: np.ndarray) -> None:
    """Python writer of the same binary record the MQL5 indicator writes (fixtures/tests)."""
    s = np.ascontiguousarray(scores, dtype="<f8").ravel()
    body = (RESULT_MAGIC + struct.pack("<IQqq", 1, seq, bar_time_utc, computed_at_utc) + bytes.fromhex(model_sha)
            + symbol.encode()[:32].ljust(32, b"\0") + tf.encode()[:8].ljust(8, b"\0") + clock_basis.encode()[:24].ljust(24, b"\0")
            + struct.pack("<I", s.size) + s.tobytes())
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(body + hashlib.sha256(body).digest())
    os.replace(tmp, path)


def parse_result(raw: bytes) -> dict:
    if len(raw) < 8 + 28 + 32 + 32 + 8 + 24 + 4 + 32:
        raise MRError("RESULT_TRUNCATED_OR_TOO_LARGE")
    body, dg = raw[:-32], raw[-32:]
    if hashlib.sha256(body).digest() != dg:
        raise MRError("RESULT_CHECKSUM_MISMATCH")
    if body[:8] != RESULT_MAGIC:
        raise MRError("RESULT_BAD_MAGIC")
    ver, seq, bt, ct = struct.unpack_from("<IQqq", body, 8)
    if ver != 1:
        raise MRError("RESULT_UNSUPPORTED_VERSION")
    o = 36
    sha = body[o:o + 32].hex()
    o += 32
    sym = body[o:o + 32].rstrip(b"\0").decode(errors="replace")
    o += 32
    tf = body[o:o + 8].rstrip(b"\0").decode(errors="replace")
    o += 8
    cb = body[o:o + 24].rstrip(b"\0").decode(errors="replace")
    o += 24
    (n,) = struct.unpack_from("<I", body, o)
    o += 4
    if o + 8 * n != len(body) or n > 1024:
        raise MRError("RESULT_BAD_LENGTH")
    sc = np.frombuffer(body, dtype="<f8", count=n, offset=o)
    if not np.isfinite(sc).all():
        raise MRError("RESULT_NON_FINITE")
    return {"seq": seq, "bar_time_utc": bt, "computed_at_utc": ct, "model_sha256": sha, "symbol": sym, "tf": tf, "clock_basis": cb,
            "scores": sc.tolist()}


# ===================================================================== benchmark
def benchmark(requested: int = 10000, L: int = 128, warmup: int = 20, n: int = 1000, seed: int = 5) -> dict:
    """Python CPU timings (Configure / Fit / Transform per window / head), steady perf_counter; synthetic random-walk windows used ONLY
    as timing input (no market claim)."""
    import platform
    rng = np.random.default_rng(seed)
    X = np.cumsum(rng.normal(0, 1, (max(64, warmup + n), L)), axis=1)
    t = time.perf_counter()
    mr = MiniRocketV2().configure(L, requested, 32)
    t_conf = time.perf_counter() - t
    t = time.perf_counter()
    mr.fit(X[:64], seed=1)
    t_fit = time.perf_counter() - t
    for i in range(warmup):
        mr.transform(X[i:i + 1])
    tim = []
    for i in range(n):
        x = X[(warmup + i) % len(X)][None]
        t = time.perf_counter()
        mr.transform(x)
        tim.append((time.perf_counter() - t) * 1000)
    a = np.array(tim)
    return {"family": TRANSFORM_ID, "platform": "PYTHON_NUMPY", "cpu": platform.processor() or platform.machine(), "os": platform.platform(),
            "numpy": np.__version__, "F": mr.lay["F"], "L": L, "configure_ms": t_conf * 1000, "fit_64_windows_ms": t_fit * 1000, "warmup": warmup,
            "n": n, "transform_ms": {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)), "p99": float(np.percentile(a, 99))},
            "raw_ms": [round(x, 4) for x in tim], "note": "pomiar Python na tej maszynie; native MQL5 mierzy skrypt benchmark w terminalu (NATIVE_NOT_EXECUTED tutaj)"}


# ===================================================================== fixtures / parity (T111-T117, T120, T122)
def export_fixture(path: Path, mr: MiniRocketV2, X: np.ndarray) -> dict:
    """PMW_MR2_FIXTURE.bin for the native self-test: windows, frozen biases and the expected integer hit counts."""
    H, den = mr.counts(X)
    arrays = {"META": (np.array([mr.lay["L"], mr.lay["F"], len(X), 0], dtype=np.int32), "i4"), "XWIN": (np.asarray(X, np.float32), "f4"),
              "BIAS": (mr.biases, "f4"), "HITS": (H, "i4"), "DENS": (den, "i4")}
    sha = write_model_bin(Path(path), arrays)
    return {"path": str(path), "sha256": sha, "windows": int(len(X)), "F": mr.lay["F"]}


def export_train(path: Path, X: np.ndarray, Y: np.ndarray, R: np.ndarray) -> dict:
    """PMW_MR2_TRAIN.bin for the native small Fit script (train rows only, chosen by the Python protocol)."""
    arrays = {"META": (np.array([X.shape[1], 0, len(X), Y.shape[1]], dtype=np.int32), "i4"), "XWIN": (np.asarray(X, np.float32), "f4"),
              "YCLS": (np.asarray(Y, np.int32), "i4"), "RVAL": (np.asarray(R, np.float64), "f8")}
    return {"path": str(path), "sha256": write_model_bin(Path(path), arrays), "rows": int(len(X))}


def oracle_counts(x: np.ndarray, d: int, k: int, b: float, centre: bool) -> tuple[int, int]:
    """Independent naive convolution (nine multiplications, float64, explicit zero padding) - test oracle only, not a production path."""
    L = len(x)
    w = np.full(9, -1.0)
    w[list(KERNELS[k])] = 2.0
    out = []
    for t in range(L):
        s = 0.0
        for j in range(9):
            u = t + (j - 4) * d
            if 0 <= u < L:
                s += w[j] * float(x[u])
        out.append(s)
    out = np.array(out)
    if centre:
        p = 4 * d
        out = out[p:L - p]
    return int((out > b).sum()), len(out)


def native_status(status_file: Path | None) -> dict:
    """Native compile/execute evidence written by 27_MINIROCKET_NATIVE.bat (EX5 hash + build + log). Without it: NOT_COMPILED."""
    if status_file is None or not Path(status_file).exists():
        return {"NATIVE_COMPILED": "NOT_COMPILED_NO_METAEDITOR", "NATIVE_EXECUTED": "NATIVE_NOT_EXECUTED",
                "reason": "brak dowodu kompilacji/uruchomienia w terminalu MT5 (środowisko budowy nie ma MetaEditor)"}
    st = json.loads(Path(status_file).read_text(encoding="utf-8"))
    ok_c = st.get("compile_errors") == 0 and bool(st.get("ex5_sha256")) and st.get("source_sha256") is not None
    return {"NATIVE_COMPILED": "PASS" if ok_c else "FAIL", "NATIVE_EXECUTED": st.get("selftest_result", "NATIVE_NOT_EXECUTED"),
            "build": st.get("terminal_build"), "ex5_sha256": st.get("ex5_sha256"), "source_sha256": st.get("source_sha256"), "log": st.get("log")}


def parity(fixtures: Path, reference_python: str | None = None, native_scores: Path | None = None, model_dir: Path | None = None,
           native_status_file: Path | None = None) -> dict:
    """Separate results per scope; nothing is PASS without the actual comparison having run."""
    import subprocess
    import tempfile
    fixtures = Path(fixtures)
    out: dict = {k: "NOT_RUN" for k in PARITY_STATES}
    details: dict = {}
    fx = fixtures / "sktime_fixture.npz"
    prov = fixtures / "provenance.json"
    if reference_python:                                              # live run of the pinned reference in its own interpreter
        tmp = Path(tempfile.mkdtemp(prefix="mr2_ref_"))
        tool = Path(__file__).resolve().parents[3] / "tools" / "minirocket_sktime_reference.py"
        r = subprocess.run([reference_python, str(tool), str(tmp)], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            details["reference_run"] = {"status": "BLOCKED", "stderr": r.stderr[-500:]}
        else:
            fx, prov = tmp / "sktime_fixture.npz", tmp / "provenance.json"
            details["reference_run"] = {"status": "RAN_LIVE"}
    if not fx.exists():
        details["sktime"] = {"status": "SKIP", "reason": "brak fixture sktime i brak --reference-python z przypiętym sktime"}
    else:
        z = np.load(fx)
        X, ref = z["X"], z["features"]
        L = X.shape[1]
        mr = MiniRocketV2().configure(L, 10000, 32)
        lay_ok = mr.lay["dilations"] == z["dilations"].tolist() and mr.lay["counts"] == z["counts"].tolist()
        out["FIT_LAYOUT_PARITY"] = "PASS" if lay_ok else "FAIL"
        mr.biases = z["biases"].astype(np.float32)
        mr.fit_idx = np.zeros(len(mr.lay["dilations"]) * 84, np.int32)
        H, den = mr.counts(X)
        ref_counts = np.rint(ref.astype(np.float64) * den[None, :]).astype(np.int64)
        mism = np.argwhere(H != ref_counts)
        out["FROZEN_STATE_PARITY"] = "PASS" if not len(mism) else "FAIL"
        details["frozen_state"] = {"windows": int(len(X)), "features": int(H.shape[1]), "count_mismatches": int(len(mism)),
                                   "first_mismatch": mism[0].tolist() if len(mism) else None, "dtype": "float32 conv, int hit counts",
                                   "ppv_exact_float32": bool((H / den[None, :]).astype(np.float32).tobytes() == ref.astype(np.float32).tobytes())}
        if "biases_single_window2" in z.files:
            m2 = MiniRocketV2().configure(L, 10000, 32).fit(X[2:3], mode="SINGLE_WINDOW")
            dlt = np.abs(m2.biases.astype(np.float64) - z["biases_single_window2"].astype(np.float64))
            scale = float(np.abs(z["biases_single_window2"]).max()) or 1.0
            details["single_window_fit"] = {"max_abs_diff": float(dlt.max()), "n_diff": int((dlt > 0).sum()), "max_rel_to_bias_scale": float(dlt.max()) / scale,
                                            "note": "referencja numba fastmath; różnice zaokrągleń kwantyla raportowane, nie ukrywane"}
        out["FIT_RANDOM_SELECTION_PARITY"] = "NOT_CLAIMED"
        details["fit_random_selection"] = "sktime losuje okna Fit generatorem numba; własny przenośny SplitMix64 (fit_window_indices w artefakcie)"
        details["provenance"] = json.loads(prov.read_text(encoding="utf-8")) if prov.exists() else None
        # clean-room oracle on a sample of (window, dilation, kernel)
        rng = np.random.default_rng(0)
        bad = 0
        checks = 0
        f0s = np.cumsum([0] + [84 * c for c in mr.lay["counts"]])
        for _ in range(60):
            w, di, k = int(rng.integers(len(X))), int(rng.integers(len(mr.lay["dilations"]))), int(rng.integers(84))
            nf = mr.lay["counts"][di]
            f = int(f0s[di] + k * nf)
            hc, dn = oracle_counts(X[w], mr.lay["dilations"][di], k, float(mr.biases[f]), (di + k) % 2 == 1)
            checks += 1
            if hc != H[w, f] or dn != den[f]:
                bad += 1
        out["ALGORITHM_VALIDATED"] = "PASS" if bad == 0 else f"FAIL ({bad}/{checks}, near-tie float32 vs float64 oracle możliwy)"
        details["oracle"] = {"checks": checks, "mismatch": bad}
    if native_scores and model_dir and Path(native_scores).exists():
        mr2, head, temps, man = import_native(model_dir)
        zf = np.load(fx) if fx.exists() else None
        if zf is not None:
            S, f = head.raw(mr2.transform(zf["X"]))
            py = np.concatenate([S, f[:, :, None]], axis=-1).reshape(len(zf["X"]), -1)
            nat = np.loadtxt(native_scores, delimiter=",")[:, 1:]
            err = float(np.abs(py - nat).max())
            out["HEAD_PARITY"] = "PASS" if err <= 1e-6 else f"FAIL max_abs={err:.3g}"
            details["head"] = {"max_abs_err": err, "tolerance": 1e-6}
    ns = native_status(native_status_file)
    out["NATIVE_COMPILED"], out["NATIVE_EXECUTED"] = ns["NATIVE_COMPILED"], ns["NATIVE_EXECUTED"]
    details["native"] = ns
    return {"transform_id": TRANSFORM_ID, "version": VERSION, "results": out, "details": details,
            "note": "bit-exact dotyczy wyłącznie sprawdzonego fixture/dtype/buildu; brak gwarancji globalnej zgodności float32/float64"}
