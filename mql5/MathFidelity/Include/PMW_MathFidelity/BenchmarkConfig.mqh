//+------------------------------------------------------------------+
//| BenchmarkConfig.mqh - shared contract of the Math Fidelity        |
//| benchmark (PMW-MM-MATHBENCH-1). One MLP 8-16-8-1 (ReLU/ReLU/linear,|
//| weights in x out), one set of test vectors and one Python float64  |
//| reference for all engines. Files live in MQL5\Files\<BENCH_DIR>\. |
//| Diagnostic only: no trading logic, no market data as input.       |
//+------------------------------------------------------------------+
#ifndef PMW_BENCH_CONFIG_MQH
#define PMW_BENCH_CONFIG_MQH

#define BENCH_VERSION        "PMW-MM-MATHBENCH-1"
#define BENCH_INPUT_DIM      8
#define BENCH_HIDDEN1_DIM    16
#define BENCH_HIDDEN2_DIM    8
#define BENCH_OUTPUT_DIM     1
#define BENCH_DIR            "PMW_MathFidelity"
#define BENCH_WEIGHTS_FILE   "model_weights.csv"
#define BENCH_VECTORS_FILE   "test_vectors.csv"
#define BENCH_ONNX_FILE      "model.onnx"
#define BENCH_RESULTS_FILE   "benchmark_results.csv"
#define BENCH_DETAIL_FILE    "error_detail.csv"
#define BENCH_MANIFEST_FILE  "run_manifest.json"
#define BENCH_STATUS_FILE    "benchmark_status.txt"
#define BENCH_MAX_VECTORS    100000
#define BENCH_DEFAULT_VECTORS 200
#define BENCH_DEFAULT_WARMUP 200
#define BENCH_DEFAULT_TIMED  5000
#define BENCH_REL_FLOOR      1e-6           // relative error denominator floor: max(|ref|, BENCH_REL_FLOOR)

string BenchPath(const string f) { return BENCH_DIR + "\\" + f; }

// error stages reported by every engine (never a numeric sentinel)
enum ENUM_BENCH_ERR
  {
   BENCH_OK = 0,
   BENCH_ERR_NOT_INITIALISED,
   BENCH_ERR_SHAPE,
   BENCH_ERR_NON_FINITE_INPUT,
   BENCH_ERR_NON_FINITE_OUTPUT,
   BENCH_ERR_ONNX_CREATE,
   BENCH_ERR_ONNX_SHAPE,
   BENCH_ERR_ONNX_TYPE,
   BENCH_ERR_ONNX_RUN
  };

string BenchErrName(const int e)
  {
   switch(e)
     {
      case BENCH_OK: return "OK";
      case BENCH_ERR_NOT_INITIALISED: return "NOT_INITIALISED";
      case BENCH_ERR_SHAPE: return "SHAPE_MISMATCH";
      case BENCH_ERR_NON_FINITE_INPUT: return "NON_FINITE_INPUT";
      case BENCH_ERR_NON_FINITE_OUTPUT: return "NON_FINITE_OUTPUT";
      case BENCH_ERR_ONNX_CREATE: return "ONNX_CREATE_FAILED";
      case BENCH_ERR_ONNX_SHAPE: return "ONNX_SHAPE_FAILED";
      case BENCH_ERR_ONNX_TYPE: return "ONNX_TYPE_MISMATCH";
      case BENCH_ERR_ONNX_RUN: return "ONNX_RUN_FAILED";
     }
   return "UNKNOWN";
  }
#endif
