//+------------------------------------------------------------------+
//| MathEngineOnnx.mqh - engine 3: ONNX Runtime through OnnxRun() with |
//| the deliberately float32 graph model.onnx (Gemm/Relu, opset 13).   |
//| Lifecycle: OnnxCreate(file in MQL5\Files) -> type/shape checks ->  |
//| OnnxSetInputShape([1,8]) / OnnxSetOutputShape([1,1]) -> OnnxRun()  |
//| with ONNX_NO_CONVERSION and matrixf buffers -> OnnxRelease().      |
//| The shared double input is cast to float32 INSIDE this engine; the |
//| float32 output is widened to double only for reporting (this does  |
//| not restore precision). A failed run returns BENCH_ERR_ONNX_RUN -  |
//| never 0.0 as a sentinel.                                          |
//+------------------------------------------------------------------+
#ifndef PMW_BENCH_ENGINE_ONNX_MQH
#define PMW_BENCH_ENGINE_ONNX_MQH
#include "BenchmarkConfig.mqh"

class CMathEngineOnnx
  {
private:
   long           m_h;
   matrixf        m_in, m_out;
   bool           m_ready;
   int            m_last_error;
public:
                  CMathEngineOnnx() : m_h(INVALID_HANDLE), m_ready(false), m_last_error(0) {}
                 ~CMathEngineOnnx() { Release(); }
   string         Name() const { return "ONNX_FLOAT32"; }
   int            LastError() const { return m_last_error; }
   bool           Init(const string file, string &err)
     {
      Release();
      ResetLastError();
      m_h = OnnxCreate(file, ONNX_DEFAULT);
      if(m_h == INVALID_HANDLE) { m_last_error = GetLastError(); err = StringFormat("%s:OnnxCreate(%s) err=%d", BenchErrName(BENCH_ERR_ONNX_CREATE), file, m_last_error); return false; }
      if(OnnxGetInputCount(m_h) != 1 || OnnxGetOutputCount(m_h) != 1) { err = "ONNX_IO_COUNT_MISMATCH"; Release(); return false; }
      OnnxTypeInfo ti, to;
      if(!OnnxGetInputTypeInfo(m_h, 0, ti) || !OnnxGetOutputTypeInfo(m_h, 0, to)) { m_last_error = GetLastError(); err = StringFormat("ONNX_TYPEINFO_FAILED err=%d", m_last_error); Release(); return false; }
      if(ti.type != ONNX_TYPE_TENSOR || to.type != ONNX_TYPE_TENSOR || ti.tensor.data_type != ONNX_DATA_TYPE_FLOAT || to.tensor.data_type != ONNX_DATA_TYPE_FLOAT)
        { err = BenchErrName(BENCH_ERR_ONNX_TYPE) + ": expected float32 tensors"; Release(); return false; }
      if(ArraySize(ti.tensor.dimensions) != 2 || ti.tensor.dimensions[1] != BENCH_INPUT_DIM || ArraySize(to.tensor.dimensions) != 2 || to.tensor.dimensions[1] != BENCH_OUTPUT_DIM)
        { err = "ONNX_GRAPH_SHAPE_MISMATCH"; Release(); return false; }
      ulong ish[] = {1, BENCH_INPUT_DIM}, osh[] = {1, BENCH_OUTPUT_DIM};
      ResetLastError();
      if(!OnnxSetInputShape(m_h, 0, ish) || !OnnxSetOutputShape(m_h, 0, osh))
        { m_last_error = GetLastError(); err = StringFormat("%s err=%d", BenchErrName(BENCH_ERR_ONNX_SHAPE), m_last_error); Release(); return false; }
      m_in.Init(1, BENCH_INPUT_DIM); m_out.Init(1, BENCH_OUTPUT_DIM);
      m_ready = true;
      return true;
     }
   int            Predict(const double &x[], const int off, double &y)
     {
      if(!m_ready) return BENCH_ERR_NOT_INITIALISED;
      if(off < 0 || off + BENCH_INPUT_DIM > ArraySize(x)) return BENCH_ERR_SHAPE;
      for(int i = 0; i < BENCH_INPUT_DIM; i++)
        {
         if(!MathIsValidNumber(x[off + i])) return BENCH_ERR_NON_FINITE_INPUT;
         m_in[0][i] = (float)x[off + i];                              // intentional float64 -> float32 cast
        }
      ResetLastError();
      if(!OnnxRun(m_h, ONNX_NO_CONVERSION, m_in, m_out)) { m_last_error = GetLastError(); return BENCH_ERR_ONNX_RUN; }
      double v = (double)m_out[0][0];
      if(!MathIsValidNumber(v)) return BENCH_ERR_NON_FINITE_OUTPUT;
      y = v;
      return BENCH_OK;
     }
   void           Release()
     {
      if(m_h != INVALID_HANDLE) OnnxRelease(m_h);
      m_h = INVALID_HANDLE; m_ready = false;
     }
  };
#endif
