"""Math Fidelity Benchmark - exporter (PMW-MM-MATHBENCH-1).

Trains the fixed 8-16-8-1 MLP once in float64 (fixed seed, synthetic target - not market data), writes
model_weights.csv / test_vectors.csv / model.onnx (float32 graph) / manifest.json and runs the Python-side checks
(CSV round-trip, float32 expectation, onnx.checker and onnxruntime when installed - labelled separately from MT5).

    python mql5/MathFidelity/train_export_model.py --out <dir>
    then copy <dir>/* to <MT5 data folder>/MQL5/Files/PMW_MathFidelity/

The implementation lives in backend/masterquo/mm/mathbench.py (same code the bot's `mm mathbench-export` uses).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from masterquo.mm import mathbench  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261025)
    ap.add_argument("--vectors", type=int, default=200)
    a = ap.parse_args()
    man = mathbench.export(Path(a.out), seed=a.seed, n_vectors=a.vectors)
    chk = mathbench.python_checks(Path(a.out))
    print(json.dumps({"files_sha256": man["files_sha256"], "training": man["training"]["history"][-1], "checks": chk}, indent=1, ensure_ascii=False))
    return 0 if chk["reload_max_abs_diff"] == 0.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
