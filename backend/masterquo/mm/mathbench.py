"""Math Engine Fidelity Benchmark - Python exporter + float64 reference (PMW-MM-MATHBENCH-1). BENCHMARK (no market data, no trading).

Fixed contract: MLP 8-16-8-1, ReLU / ReLU / linear, weights in x out (W1 8x16, b1 16, W2 16x8, b2 8, W3 8x1, b3 1); y = relu(relu(xW1+b1)W2+b2)W3+b3.
Trained ONCE in float64 (full-batch Adam, fixed seed) on a documented SYNTHETIC regression target (not market data):
    y = sin(x0) + 0.5 x1 x2 - 0.3 x3^2 + 0.2 x4 + 0.1 cos(3 x5) + 0.05 x6 x7,   x ~ U(-1.5, 1.5)^8
Outputs: model_weights.csv (tagged sections #W1,8,16 ... row-major, 17 significant digits = exact float64 round-trip), test_vectors.csv
(#vectors,8,<n> then 8 inputs + float64 reference per row), model.onnx (Gemm/Relu graph, float32 initializers and float32 I/O [1,8]->[1,1],
opset 13, IR 7, written by a small built-in protobuf encoder - no `onnx` package needed; validated with onnx.checker / onnxruntime when
those are installed, as a SEPARATE Python-side check), manifest.json (seed, training config, shapes, versions, sha256).
The MQL5 side (mql5/MathFidelity) loads the same files; all three engines use these exact weights.
"""
from __future__ import annotations

import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np

VERSION = "PMW-MM-MATHBENCH-1"
SHAPES = {"W1": (8, 16), "b1": (1, 16), "W2": (16, 8), "b2": (1, 8), "W3": (8, 1), "b3": (1, 1)}


def target(X: np.ndarray) -> np.ndarray:
    return np.sin(X[:, 0]) + 0.5 * X[:, 1] * X[:, 2] - 0.3 * X[:, 3] ** 2 + 0.2 * X[:, 4] + 0.1 * np.cos(3 * X[:, 5]) + 0.05 * X[:, 6] * X[:, 7]


def forward(P: dict, X: np.ndarray) -> np.ndarray:
    h1 = np.maximum(X @ P["W1"] + P["b1"], 0.0)
    h2 = np.maximum(h1 @ P["W2"] + P["b2"], 0.0)
    return (h2 @ P["W3"] + P["b3"])[:, 0]


def train(seed: int = 20261025, n: int = 4000, steps: int = 3000, lr: float = 3e-3) -> tuple[dict, dict]:
    g = np.random.Generator(np.random.PCG64(seed))
    X = g.uniform(-1.5, 1.5, (n, 8))
    y = target(X)
    P = {k: (g.normal(0, np.sqrt(2.0 / s[0]), s) if k.startswith("W") else np.zeros(s)) for k, s in SHAPES.items()}
    m = {k: np.zeros_like(v) for k, v in P.items()}
    v = {k: np.zeros_like(x) for k, x in P.items()}
    hist = []
    for t in range(1, steps + 1):
        z1 = X @ P["W1"] + P["b1"]
        h1 = np.maximum(z1, 0)
        z2 = h1 @ P["W2"] + P["b2"]
        h2 = np.maximum(z2, 0)
        out = (h2 @ P["W3"] + P["b3"])[:, 0]
        e = out - y
        d3 = (2 * e / n)[:, None]
        G = {"W3": h2.T @ d3, "b3": d3.sum(0, keepdims=True)}
        d2 = (d3 @ P["W3"].T) * (z2 > 0)
        G["W2"], G["b2"] = h1.T @ d2, d2.sum(0, keepdims=True)
        d1 = (d2 @ P["W2"].T) * (z1 > 0)
        G["W1"], G["b1"] = X.T @ d1, d1.sum(0, keepdims=True)
        for k in P:
            m[k] = 0.9 * m[k] + 0.1 * G[k]
            v[k] = 0.999 * v[k] + 0.001 * G[k] ** 2
            P[k] = P[k] - lr * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v[k] / (1 - 0.999 ** t)) + 1e-8)
        if t % 500 == 0:
            hist.append({"step": t, "mse": float(np.mean(e ** 2))})
    return P, {"seed": seed, "n_train": n, "steps": steps, "lr": lr, "optimizer": "Adam(0.9,0.999,1e-8) full batch float64", "history": hist,
               "target": "sin(x0)+0.5x1x2-0.3x3^2+0.2x4+0.1cos(3x5)+0.05x6x7, x~U(-1.5,1.5)^8 (synthetic)"}


# ------------------------------------------------------------------------------------------------ CSV
def write_weights(P: dict, path: Path) -> None:
    lines = []
    for k, (r, c) in SHAPES.items():
        a = np.asarray(P[k], np.float64).reshape(r, c)
        if not np.all(np.isfinite(a)):
            raise ValueError(f"NON_FINITE_WEIGHTS:{k}")
        lines.append(f"#{k},{r},{c}")
        lines += [",".join(f"{x:.17g}" for x in row) for row in a]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def read_weights(path: Path) -> dict:
    """Strict loader (same contract as the MQL5 WeightLoader): tags in order, declared shapes, exact counts, finite values."""
    rows = [ln.strip() for ln in path.read_text(encoding="ascii").splitlines() if ln.strip()]
    out, i = {}, 0
    for k, (r, c) in SHAPES.items():
        if i >= len(rows) or not rows[i].startswith("#"):
            raise ValueError(f"MISSING_SECTION:{k}")
        tag = rows[i][1:].split(",")
        if tag[0] != k or int(tag[1]) != r or int(tag[2]) != c:
            raise ValueError(f"BAD_SECTION_HEADER:{rows[i]}")
        vals = []
        for j in range(r):
            parts = rows[i + 1 + j].split(",")
            if len(parts) != c:
                raise ValueError(f"BAD_ROW_WIDTH:{k}:{j}")
            vals.append([float(x) for x in parts])
        a = np.array(vals)
        if not np.all(np.isfinite(a)):
            raise ValueError(f"NON_FINITE:{k}")
        out[k] = a
        i += 1 + r
    if i != len(rows):
        raise ValueError("TRAILING_DATA")
    return out


def write_vectors(X: np.ndarray, ref: np.ndarray, path: Path) -> None:
    lines = [f"#vectors,8,{len(X)}"] + [",".join(f"{v:.17g}" for v in list(x) + [r]) for x, r in zip(X, ref)]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


# ------------------------------------------------------------------------------------------------ ONNX (minimal protobuf writer)
def _varint(n: int) -> bytes:
    out = bytearray()
    n &= (1 << 64) - 1
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _key(f: int, w: int) -> bytes:
    return _varint((f << 3) | w)


def _ld(f: int, payload: bytes) -> bytes:
    return _key(f, 2) + _varint(len(payload)) + payload


def _s(f: int, s: str) -> bytes:
    return _ld(f, s.encode())


def _i(f: int, v: int) -> bytes:
    return _key(f, 0) + _varint(v)


def _tensor(name: str, a: np.ndarray) -> bytes:
    a = np.ascontiguousarray(a, dtype=np.float32)
    return b"".join(_i(1, d) for d in a.shape) + _i(2, 1) + _s(8, name) + _ld(9, a.tobytes())   # dims, FLOAT, name, raw_data (LE)


def _value_info(name: str, dims) -> bytes:
    shape = b"".join(_ld(1, _i(1, d)) for d in dims)
    tensor = _i(1, 1) + _ld(2, shape)
    return _s(1, name) + _ld(2, _ld(1, tensor))


def _node(op: str, ins, outs, name: str) -> bytes:
    return b"".join(_s(1, x) for x in ins) + b"".join(_s(2, x) for x in outs) + _s(3, name) + _s(4, op)


def onnx_bytes(P: dict) -> bytes:
    nodes = [_node("Gemm", ["input", "W1", "b1"], ["z1"], "gemm1"), _node("Relu", ["z1"], ["h1"], "relu1"),
             _node("Gemm", ["h1", "W2", "b2"], ["z2"], "gemm2"), _node("Relu", ["z2"], ["h2"], "relu2"),
             _node("Gemm", ["h2", "W3", "b3"], ["output"], "gemm3")]
    inits = [_tensor(k, np.asarray(P[k]).reshape(SHAPES[k][1]) if k.startswith("b") else P[k]) for k in SHAPES]
    graph = b"".join(_ld(1, n) for n in nodes) + _s(2, "pmw_mlp_8_16_8_1") + b"".join(_ld(5, t) for t in inits) \
        + _ld(11, _value_info("input", (1, 8))) + _ld(12, _value_info("output", (1, 1)))
    return _i(1, 7) + _s(2, "PepeMarketWizard-mathbench") + _s(3, VERSION) + _ld(7, graph) + _ld(8, _s(1, "") + _i(2, 13))


def forward_f32(P: dict, X: np.ndarray) -> np.ndarray:
    """What the float32 graph computes (cast inputs and weights, float32 arithmetic) - Python-side expectation only."""
    Q = {k: np.asarray(v, np.float32) for k, v in P.items()}
    x = np.asarray(X, np.float32)
    h1 = np.maximum(x @ Q["W1"] + Q["b1"], np.float32(0))
    h2 = np.maximum(h1 @ Q["W2"] + Q["b2"], np.float32(0))
    return (h2 @ Q["W3"] + Q["b3"])[:, 0].astype(np.float64)


def export(out_dir: Path, seed: int = 20261025, n_vectors: int = 200) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    P, info = train(seed)
    g = np.random.Generator(np.random.PCG64(seed + 1))
    X = g.uniform(-1.5, 1.5, (n_vectors, 8))
    ref = forward(P, X)
    write_weights(P, out_dir / "model_weights.csv")
    write_vectors(X, ref, out_dir / "test_vectors.csv")
    (out_dir / "model.onnx").write_bytes(onnx_bytes(P))
    files = {f: hashlib.sha256((out_dir / f).read_bytes()).hexdigest() for f in ("model_weights.csv", "test_vectors.csv", "model.onnx")}
    man = {"version": VERSION, "architecture": "MLP 8-16-8-1 ReLU/ReLU/linear, weights in x out", "shapes": {k: list(v) for k, v in SHAPES.items()},
           "training": info, "n_vectors": n_vectors, "vector_seed": seed + 1, "onnx": {"opset": 13, "ir_version": 7, "dtype": "float32", "input": [1, 8],
           "output": [1, 1], "writer": "built-in protobuf encoder"}, "files_sha256": files, "exported_at": t0,
           "versions": {"python": platform.python_version(), "numpy": np.__version__}, "csv_precision": "17 significant digits (%.17g)",
           "note": "dane syntetyczne do pomiaru wierności numerycznej - nie dane rynkowe"}
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man


def python_checks(out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    P = read_weights(out_dir / "model_weights.csv")
    rows = (out_dir / "test_vectors.csv").read_text(encoding="ascii").splitlines()
    hdr = rows[0].split(",")
    data = np.array([[float(v) for v in r.split(",")] for r in rows[1:] if r.strip()])
    X, ref = data[:, :8], data[:, 8]
    res = {"vectors": int(hdr[2]), "rows_read": int(len(X)), "reload_max_abs_diff": float(np.max(np.abs(forward(P, X) - ref))),
           "float32_expected_max_abs_err": float(np.max(np.abs(forward_f32(P, X) - ref)))}
    try:
        import onnx  # type: ignore
        m = onnx.load(str(out_dir / "model.onnx"))
        onnx.checker.check_model(m)
        res["onnx_checker"] = "PASS"
        res["onnx_ops"] = [n.op_type for n in m.graph.node]
    except ImportError:
        res["onnx_checker"] = "NOT_RUN (pakiet onnx niezainstalowany)"
    except Exception as exc:  # noqa: BLE001
        res["onnx_checker"] = f"FAIL: {exc}"[:300]
    try:
        import onnxruntime as ort  # type: ignore
        s = ort.InferenceSession(str(out_dir / "model.onnx"), providers=["CPUExecutionProvider"])
        o = np.array([s.run(None, {"input": x[None].astype(np.float32)})[0][0, 0] for x in X], dtype=np.float64)
        res["onnxruntime_python"] = {"max_abs_err_vs_float64": float(np.max(np.abs(o - ref))), "max_abs_diff_vs_python_float32": float(np.max(np.abs(o - forward_f32(P, X)))),
                                     "note": "kontrola po stronie Pythona - NIE zastępuje testu OnnxRun() w MT5"}
    except ImportError:
        res["onnxruntime_python"] = "NOT_RUN (onnxruntime niezainstalowany)"
    return res


def percentile_linear(samples, p: float) -> float:
    """Percentile with linear interpolation at rank p*(n-1) (the convention used by the MQL5 BenchmarkStats)."""
    s = np.sort(np.asarray(samples, float))
    if not len(s):
        return float("nan")
    r = p * (len(s) - 1)
    lo, hi = int(np.floor(r)), int(np.ceil(r))
    return float(s[lo] + (s[hi] - s[lo]) * (r - lo))

