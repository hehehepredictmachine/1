//+------------------------------------------------------------------+
//| MathEngineAlglib.mqh - engine 2: ALGLIB CMatrixDouble weights,     |
//| double biases/activations, the SAME explicit multiply-accumulate  |
//| order as the native engine (container/indexing comparison, not an |
//| optimised GEMM). CMatrixDouble comes from the ALGLIB port bundled |
//| with MetaTrader 5 (MQL5\Include\Math\Alglib\matrix.mqh): Resize(r,c)|
//| / Set(i,j,v) / Get(i,j) / Rows() / Cols(). Verify on compile - the |
//| bundled ALGLIB is versioned with the terminal build.               |
//+------------------------------------------------------------------+
#ifndef PMW_BENCH_ENGINE_ALGLIB_MQH
#define PMW_BENCH_ENGINE_ALGLIB_MQH
#include <Math\Alglib\matrix.mqh>
#include "WeightLoader.mqh"

class CMathEngineAlglib
  {
private:
   CMatrixDouble  m_W1, m_W2, m_W3;
   double         m_b1[], m_b2[], m_b3[], m_h1[], m_h2[];
   bool           m_ready;
   void           Fill(CMatrixDouble &M, const double &src[], const int r, const int c)
     {
      M.Resize(r, c);
      for(int i = 0; i < r; i++) for(int j = 0; j < c; j++) M.Set(i, j, src[i * c + j]);
     }
public:
                  CMathEngineAlglib() : m_ready(false) {}
   string         Name() const { return "ALGLIB_CMATRIXDOUBLE"; }
   bool           Init(const BenchWeights &w, string &err)
     {
      m_ready = false;
      if(!w.valid) { err = "WEIGHTS_NOT_VALID"; return false; }
      Fill(m_W1, w.W1, BENCH_INPUT_DIM, BENCH_HIDDEN1_DIM); Fill(m_W2, w.W2, BENCH_HIDDEN1_DIM, BENCH_HIDDEN2_DIM); Fill(m_W3, w.W3, BENCH_HIDDEN2_DIM, BENCH_OUTPUT_DIM);
      if((int)m_W1.Rows() != BENCH_INPUT_DIM || (int)m_W1.Cols() != BENCH_HIDDEN1_DIM || (int)m_W2.Rows() != BENCH_HIDDEN1_DIM
         || (int)m_W2.Cols() != BENCH_HIDDEN2_DIM || (int)m_W3.Rows() != BENCH_HIDDEN2_DIM || (int)m_W3.Cols() != BENCH_OUTPUT_DIM)
        { err = "ALGLIB_SHAPE_MISMATCH"; return false; }
      // orientation check with a known element of every matrix (row-major in x out)
      if(m_W1.Get(1, 2) != w.W1[1 * BENCH_HIDDEN1_DIM + 2] || m_W2.Get(3, 1) != w.W2[3 * BENCH_HIDDEN2_DIM + 1] || m_W3.Get(5, 0) != w.W3[5])
        { err = "ALGLIB_ORIENTATION_MISMATCH"; return false; }
      ArrayCopy(m_b1, w.b1); ArrayCopy(m_b2, w.b2); ArrayCopy(m_b3, w.b3);
      ArrayResize(m_h1, BENCH_HIDDEN1_DIM); ArrayResize(m_h2, BENCH_HIDDEN2_DIM);
      m_ready = true;
      return true;
     }
   int            Predict(const double &x[], const int off, double &y)
     {
      if(!m_ready) return BENCH_ERR_NOT_INITIALISED;
      if(off < 0 || off + BENCH_INPUT_DIM > ArraySize(x)) return BENCH_ERR_SHAPE;
      for(int j = 0; j < BENCH_HIDDEN1_DIM; j++)
        {
         double s = m_b1[j];
         for(int i = 0; i < BENCH_INPUT_DIM; i++) s += x[off + i] * m_W1.Get(i, j);
         m_h1[j] = s > 0.0 ? s : 0.0;
        }
      for(int j = 0; j < BENCH_HIDDEN2_DIM; j++)
        {
         double s = m_b2[j];
         for(int i = 0; i < BENCH_HIDDEN1_DIM; i++) s += m_h1[i] * m_W2.Get(i, j);
         m_h2[j] = s > 0.0 ? s : 0.0;
        }
      double s = m_b3[0];
      for(int i = 0; i < BENCH_HIDDEN2_DIM; i++) s += m_h2[i] * m_W3.Get(i, 0);
      if(!MathIsValidNumber(s)) return BENCH_ERR_NON_FINITE_OUTPUT;
      y = s;
      return BENCH_OK;
     }
   void           Release() { m_ready = false; }
  };
#endif
