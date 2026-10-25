# Math Fidelity Benchmark (PMW-MM-MATHBENCH-1)

Diagnostic computation benchmark — **no trading logic, no order execution, no market data as input.**
One MLP 8-16-8-1 (ReLU / ReLU / linear, weights `in × out`), trained once in Python float64, runs through three MQL5 engines:

| Engine | Container / precision | File |
|---|---|---|
| NATIVE_MATRIX_DOUBLE | `matrix<double>` / `vector<double>`, float64, explicit multiply-accumulate loops | `Include/PMW_MathFidelity/MathEngineNative.mqh` |
| ALGLIB_CMATRIXDOUBLE | ALGLIB `CMatrixDouble` (bundled `Math\Alglib\matrix.mqh`), float64, the same loop order | `Include/PMW_MathFidelity/MathEngineAlglib.mqh` |
| ONNX_FLOAT32 | `OnnxCreate` / `OnnxSetInputShape` / `OnnxSetOutputShape` / `OnnxRun(ONNX_NO_CONVERSION)` with a deliberately float32 graph | `Include/PMW_MathFidelity/MathEngineOnnx.mqh` |

The float32 ONNX path is a measurement dimension of THIS benchmark, not a property of every ONNX model.

## 1. Export (Python)

```
python mql5/MathFidelity/train_export_model.py --out out_mathbench
# or from the bot: python -m masterquo mm mathbench-export --out out_mathbench
```
Writes `model_weights.csv` (tagged sections `#W1,8,16` `#b1,1,16` `#W2,16,8` `#b2,1,8` `#W3,8,1` `#b3,1,1`, row-major, 17 significant digits),
`test_vectors.csv` (`#vectors,8,200` then 8 inputs + float64 reference per row), `model.onnx` (Gemm/Relu, opset 13, IR 7, float32 I/O `[1,8]→[1,1]`)
and `manifest.json` (seed, training, shapes, versions, sha256). Python-side checks: CSV reload == reference (exact), float32 expectation,
`onnx.checker` and `onnxruntime` when installed (these are **not** a substitute for `OnnxRun()` in MT5).

## 2. Install

Copy the four files to `<MT5 data folder>\MQL5\Files\PMW_MathFidelity\` (File → Open Data Folder).
Copy `Include\PMW_MathFidelity\*` to `MQL5\Include\PMW_MathFidelity\`, `Experts\*`, `Indicators\*`, `Scripts\*` to the matching MQL5 folders and compile in MetaEditor.

## 3. Run

1. `Scripts\MathFidelity_SelfTest` — loader rejections, percentile convention, explicit failure status, engine vs reference → `selftest.txt`.
2. Attach `Experts\MathFidelityBenchmark_EA` to any chart (`InpRunOnInit=true`, defaults: 200 warm-up passes, 5,000 timed passes × 200 vectors = 1,000,000 timed calls per engine).
   Results do not depend on the chart symbol. If any engine fails to initialise the EA stops with the stage and error code (no partial comparison).
3. Attach `Indicators\FidelityMonitor` for the read-only summary.

Outputs in `MQL5\Files\PMW_MathFidelity\`: `benchmark_results.csv` (one row per engine: mean/median/p95/p99/min/max µs, samples, zero-µs samples,
batched cross-check, abs/rel error, RMSE, vectors passed, failed calls, determinism, tolerances, statuses), `error_detail.csv` (every vector, every engine,
full precision), `run_manifest.json` (terminal/compiler build, cores, RAM, file sha256, counts, engine order, timer, percentile convention),
`benchmark_status.txt` (`RUNNING` → `COMPLETE` / `INCOMPLETE` / `FAILED`).

## 4. Interpretation

* Fidelity is computed over the 200 **unique** vectors; the 1,000,000 timed calls are latency samples, not independent accuracy examples.
* Relative error uses the denominator `max(|ref|, 1e-6)`; absolute error is always reported.
* Latency: `GetMicrosecondCount()` around exactly one `Predict()` call (input prepared outside). Percentiles: linear interpolation at rank `p·(n−1)`.
  Sub-microsecond calls produce many 0 µs samples — they are kept and counted (`zero_us_samples`); the batched figure is a separately labelled cross-check.
* A failed engine call is a status (`ONNX_RUN_FAILED`, …), never a `0.0` prediction.
* Latency is specific to the machine, CPU frequency, OS load and terminal build.

## 5. Status of this package (evidence)

| Component | Status |
|---|---|
| Python exporter + reference + ONNX writer | PYTHON_TESTED (tests/test_mm_core.py, onnx.checker + onnxruntime in a separate venv) |
| MQL5 loader / engines / stats / EA / monitor / self-test | IMPLEMENTED — not compiled here (no MetaEditor in the build environment) |
| MT5 runtime benchmark | BLOCKED until run in a terminal — no MT5 numbers are claimed |

## 6. Troubleshooting

* `FILE_OPEN_FAILED` — files not in `MQL5\Files\PMW_MathFidelity\` (or opened from the Common folder).
* `ONNX_CREATE_FAILED err=…` — terminal build without ONNX support or wrong path; `ONNX_TYPE_MISMATCH` — the graph is not float32 `[1,8]→[1,1]`.
* ALGLIB compile errors — the bundled ALGLIB version differs; check `MQL5\Include\Math\Alglib\matrix.mqh` for `Resize/Set/Get`.
