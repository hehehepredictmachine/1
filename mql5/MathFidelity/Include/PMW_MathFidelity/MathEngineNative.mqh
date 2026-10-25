//+------------------------------------------------------------------+
//| MathEngineNative.mqh - engine 1: built-in matrix<double> /        |
//| vector<double>, float64. Shapes are created with Init(rows, cols) |
//| and filled element by element (no reliance on Assign() keeping a  |
//| 2-D shape). The dense layer is an explicit loop: for each output j|
//| s = b[j]; s += x[i] * W[i][j] for i = 0..in-1 (same order as the   |
//| ALGLIB engine). ReLU on hidden layers only, linear output.        |
//| Predict() returns a status; the number is valid only on BENCH_OK. |
//+------------------------------------------------------------------+
#ifndef PMW_BENCH_ENGINE_NATIVE_MQH
#define PMW_BENCH_ENGINE_NATIVE_MQH
#include "WeightLoader.mqh"

class CMathEngineNative
  {
private:
   matrix<double> m_W1, m_W2, m_W3;
   vector<double> m_b1, m_b2, m_b3, m_h1, m_h2;
   bool           m_ready;
   void           Fill(matrix<double> &M, const double &src[], const int r, const int c)
     {
      M.Init(r, c);
      for(int i = 0; i < r; i++) for(int j = 0; j < c; j++) M[i][j] = src[i * c + j];
     }
   void           FillV(vector<double> &v, const double &src[], const int n) { v.Init(n); for(int i = 0; i < n; i++) v[i] = src[i]; }
public:
                  CMathEngineNative() : m_ready(false) {}
   string         Name() const { return "NATIVE_MATRIX_DOUBLE"; }
   bool           Init(const BenchWeights &w, string &err)
     {
      m_ready = false;
      if(!w.valid) { err = "WEIGHTS_NOT_VALID"; return false; }
      Fill(m_W1, w.W1, BENCH_INPUT_DIM, BENCH_HIDDEN1_DIM); Fill(m_W2, w.W2, BENCH_HIDDEN1_DIM, BENCH_HIDDEN2_DIM); Fill(m_W3, w.W3, BENCH_HIDDEN2_DIM, BENCH_OUTPUT_DIM);
      FillV(m_b1, w.b1, BENCH_HIDDEN1_DIM); FillV(m_b2, w.b2, BENCH_HIDDEN2_DIM); FillV(m_b3, w.b3, BENCH_OUTPUT_DIM);
      if(m_W1.Rows() != BENCH_INPUT_DIM || m_W1.Cols() != BENCH_HIDDEN1_DIM || m_W2.Rows() != BENCH_HIDDEN1_DIM || m_W2.Cols() != BENCH_HIDDEN2_DIM
         || m_W3.Rows() != BENCH_HIDDEN2_DIM || m_W3.Cols() != BENCH_OUTPUT_DIM || m_b1.Size() != BENCH_HIDDEN1_DIM || m_b2.Size() != BENCH_HIDDEN2_DIM
         || m_b3.Size() != BENCH_OUTPUT_DIM) { err = "NATIVE_SHAPE_MISMATCH"; return false; }
      m_h1.Init(BENCH_HIDDEN1_DIM); m_h2.Init(BENCH_HIDDEN2_DIM);
      m_ready = true;
      return true;
     }
   // x: BENCH_INPUT_DIM doubles starting at x[off]
   int            Predict(const double &x[], const int off, double &y)
     {
      if(!m_ready) return BENCH_ERR_NOT_INITIALISED;
      if(off < 0 || off + BENCH_INPUT_DIM > ArraySize(x)) return BENCH_ERR_SHAPE;
      for(int j = 0; j < BENCH_HIDDEN1_DIM; j++)
        {
         double s = m_b1[j];
         for(int i = 0; i < BENCH_INPUT_DIM; i++) s += x[off + i] * m_W1[i][j];
         m_h1[j] = s > 0.0 ? s : 0.0;
        }
      for(int j = 0; j < BENCH_HIDDEN2_DIM; j++)
        {
         double s = m_b2[j];
         for(int i = 0; i < BENCH_HIDDEN1_DIM; i++) s += m_h1[i] * m_W2[i][j];
         m_h2[j] = s > 0.0 ? s : 0.0;
        }
      double s = m_b3[0];
      for(int i = 0; i < BENCH_HIDDEN2_DIM; i++) s += m_h2[i] * m_W3[i][0];
      if(!MathIsValidNumber(s)) return BENCH_ERR_NON_FINITE_OUTPUT;
      y = s;
      return BENCH_OK;
     }
   void           Release() { m_ready = false; }
  };
#endif
