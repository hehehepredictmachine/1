//+------------------------------------------------------------------+
//| PMW_MR2_Core.mqh - MQ_MINIROCKET_UNIVARIATE_V2 (PMW-UPD-09 R21)   |
//| Clean-room MQL5 port of backend/masterquo/lab/minirocket_v2.py.   |
//| Configure -> Fit -> Transform; layout pinned (dilation->kernel->  |
//| quantile), 84 kernels (six -1, three +2), global low-discrepancy  |
//| float32 quantiles, SplitMix64 fit windows, FULL padded conv for   |
//| biases, PPV strict '>' with denominator L or L-8d (centre-only).  |
//| float32 accumulation order (pinned): alpha = -x[c]; then taps     |
//| -4d..-1d, +1d..+4d; conv = ((alpha + g_a) + g_b) + g_c.           |
//| No trading functions. NOT compiled in the build environment.      |
//+------------------------------------------------------------------+
#ifndef PMW_MR2_CORE_MQH
#define PMW_MR2_CORE_MQH

#define MR2_OK                 0
#define MR2_NOT_CONFIGURED    -1
#define MR2_NOT_FITTED        -2
#define MR2_INPUT_TOO_SHORT   -3
#define MR2_BUDGET_TOO_SMALL  -4
#define MR2_NON_FINITE        -5
#define MR2_LENGTH_MISMATCH   -6
#define MR2_BAD_INDICES       -7
#define MR2_EMPTY_SEGMENT     -8

string MR2ErrorText(const int e)
  {
   switch(e)
     {
      case MR2_OK: return "OK";
      case MR2_NOT_CONFIGURED: return "NOT_CONFIGURED";
      case MR2_NOT_FITTED: return "NOT_FITTED";
      case MR2_INPUT_TOO_SHORT: return "INPUT_TOO_SHORT";
      case MR2_BUDGET_TOO_SMALL: return "FEATURE_BUDGET_TOO_SMALL";
      case MR2_NON_FINITE: return "NON_FINITE_INPUT";
      case MR2_LENGTH_MISMATCH: return "LENGTH_MISMATCH";
      case MR2_BAD_INDICES: return "FIT_INDICES_INVALID";
      case MR2_EMPTY_SEGMENT: return "EMPTY_SEGMENT";
     }
   return "UNKNOWN";
  }

//--- SplitMix64 (identical sequence to the Python class SplitMix64)
class CSplitMix64
  {
private:
   ulong             m_s;
public:
                     CSplitMix64(const ulong seed) { m_s = seed; }
   ulong             Next()
     {
      m_s += 0x9E3779B97F4A7C15;
      ulong z = m_s;
      z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9;
      z = (z ^ (z >> 27)) * 0x94D049BB133111EB;
      return z ^ (z >> 31);
     }
   int               Below(const int n) { return (int)(Next() % (ulong)n); }
  };

class CMiniRocketV2
  {
public:
   int               m_L, m_requested, m_maxDil, m_F, m_nd;
   int               m_dil[];
   int               m_cnt[];
   float             m_q[];
   float             m_bias[];
   int               m_fitIdx[];
   int               m_k[84][3];
   bool              m_configured, m_fitted;

                     CMiniRocketV2() { m_configured = false; m_fitted = false; InitKernels(); }

   void              InitKernels()
     {
      int n = 0;
      for(int a = 0; a < 9; a++)
         for(int b = a + 1; b < 9; b++)
            for(int c = b + 1; c < 9; c++)
              { m_k[n][0] = a; m_k[n][1] = b; m_k[n][2] = c; n++; }
     }

   void              Reset() { m_configured = false; m_fitted = false; ArrayFree(m_bias); ArrayFree(m_fitIdx); }

   //--- layout (same rule as Python layout(); the exported model carries its layout, Load never re-guesses it)
   int               Configure(const int L, const int requested, const int maxDil)
     {
      Reset();
      if(L < 9) return MR2_INPUT_TOO_SHORT;
      if(requested < 84) return MR2_BUDGET_TOO_SMALL;
      if(maxDil < 1) return MR2_BUDGET_TOO_SMALL;
      int fpk = requested / 84;
      int tmax = MathMin(fpk, maxDil);
      double mult = (double)fpk / tmax;
      double maxExp = (L > 9) ? MathLog((L - 1) / 8.0) / MathLog(2.0) : 0.0;
      int raw[];
      ArrayResize(raw, tmax);
      for(int i = 0; i < tmax; i++)
        {
         double e = (tmax > 1) ? maxExp * i / (tmax - 1) : 0.0;
         if(i == tmax - 1) e = maxExp;
         raw[i] = (int)MathPow(2.0, e);
        }
      ArrayResize(m_dil, 0);
      ArrayResize(m_cnt, 0);
      for(int i = 0; i < tmax; i++)
        {
         int n = ArraySize(m_dil);
         if(n > 0 && m_dil[n - 1] == raw[i]) { m_cnt[n - 1]++; continue; }
         ArrayResize(m_dil, n + 1);
         ArrayResize(m_cnt, n + 1);
         m_dil[n] = raw[i];
         m_cnt[n] = 1;
        }
      m_nd = ArraySize(m_dil);
      int sum = 0;
      for(int i = 0; i < m_nd; i++) { m_cnt[i] = (int)(m_cnt[i] * mult); sum += m_cnt[i]; }
      int rem = fpk - sum, j = 0;
      while(rem > 0) { m_cnt[j]++; rem--; j = (j + 1) % m_nd; }
      m_F = 0;
      for(int i = 0; i < m_nd; i++) m_F += 84 * m_cnt[i];
      ArrayResize(m_q, m_F);
      double phi = (MathSqrt(5.0) + 1.0) / 2.0;
      for(int k = 1; k <= m_F; k++)
        {
         double v = k * phi;
         m_q[k - 1] = (float)(v - MathFloor(v));
        }
      m_L = L; m_requested = requested; m_maxDil = maxDil;
      m_configured = true;
      return MR2_OK;
     }

   //--- load a layout exported by Python (preferred over recomputation)
   int               SetLayout(const int L, const int &dil[], const int &cnt[], const float &q[])
     {
      Reset();
      m_L = L; m_nd = ArraySize(dil);
      ArrayCopy(m_dil, dil); ArrayCopy(m_cnt, cnt); ArrayCopy(m_q, q);
      m_F = 0;
      for(int i = 0; i < m_nd; i++) m_F += 84 * m_cnt[i];
      if(m_F != ArraySize(q)) return MR2_LENGTH_MISMATCH;
      m_configured = true;
      return MR2_OK;
     }

   //--- shared terms for one dilation: alpha[L], gamma[9*L] (float32, pinned order)
   void              Terms(const float &x[], const int d, float &alpha[], float &gam[])
     {
      int L = m_L;
      ArrayResize(alpha, L);
      ArrayResize(gam, 9 * L);
      ArrayInitialize(gam, 0.0f);
      for(int j = 0; j < 9; j++)
        {
         int s = (j - 4) * d;
         for(int t = 0; t < L; t++)
           {
            int src = t + s;
            if(src >= 0 && src < L) gam[j * L + t] = x[src];
           }
        }
      int order[9] = {4, 0, 1, 2, 3, 5, 6, 7, 8};
      for(int t = 0; t < L; t++)
        {
         float a = -gam[4 * L + t];
         for(int o = 1; o < 9; o++) a = a - gam[order[o] * L + t];
         alpha[t] = a;
        }
      for(int i = 0; i < 9 * L; i++) gam[i] = gam[i] * 3.0f;
     }

   void              Conv(const float &alpha[], const float &gam[], const int k, float &c[])
     {
      int L = m_L;
      ArrayResize(c, L);
      int i0 = m_k[k][0], i1 = m_k[k][1], i2 = m_k[k][2];
      for(int t = 0; t < L; t++)
        {
         float v = alpha[t] + gam[i0 * L + t];
         v = v + gam[i1 * L + t];
         v = v + gam[i2 * L + t];
         c[t] = v;
        }
     }

   static double     Quantile(float &sorted[], const double q)
     {
      int n = ArraySize(sorted);
      if(n == 1) return sorted[0];
      double pos = q * (n - 1);
      int lo = (int)MathFloor(pos);
      int hi = MathMin(lo + 1, n - 1);
      double fr = pos - lo;
      double a = (double)sorted[lo], b = (double)sorted[hi], dba = b - a;
      // numpy 'linear' lerp (same branch rule as numpy._lerp): a + d*t, or b - d*(1-t) for t >= 0.5
      return (fr >= 0.5) ? b - dba * (1.0 - fr) : a + dba * fr;
     }

   bool              CheckWindow(const float &x[], const int off)
     {
      for(int t = 0; t < m_L; t++)
         if(!MathIsValidNumber(x[off + t])) return false;
      return true;
     }

   //--- X flat (n x L) TRAIN windows only; indices: frozen (size nd*84) or empty -> SplitMix64(seed)
   int               Fit(const float &X[], const int n, const ulong seed, const int &frozen[])
     {
      if(!m_configured) return MR2_NOT_CONFIGURED;
      if(n <= 0 || ArraySize(X) != n * m_L) return MR2_LENGTH_MISMATCH;
      for(int i = 0; i < n; i++)
         if(!CheckWindow(X, i * m_L)) return MR2_NON_FINITE;
      ArrayResize(m_fitIdx, m_nd * 84);
      if(ArraySize(frozen) > 0)
        {
         if(ArraySize(frozen) != m_nd * 84) return MR2_BAD_INDICES;
         for(int i = 0; i < m_nd * 84; i++)
           {
            if(frozen[i] < 0 || frozen[i] >= n) return MR2_BAD_INDICES;
            m_fitIdx[i] = frozen[i];
           }
        }
      else
        {
         CSplitMix64 r(seed);
         for(int i = 0; i < m_nd * 84; i++) m_fitIdx[i] = r.Below(n);
        }
      ArrayResize(m_bias, m_F);
      float x[], alpha[], gam[], c[];
      ArrayResize(x, m_L);
      int f0 = 0;
      for(int di = 0; di < m_nd; di++)
        {
         int nf = m_cnt[di];
         for(int k = 0; k < 84; k++)
           {
            ArrayCopy(x, X, 0, m_fitIdx[di * 84 + k] * m_L, m_L);
            Terms(x, m_dil[di], alpha, gam);
            Conv(alpha, gam, k, c);                      // FULL padded output, also for centre-only features
            ArraySort(c);
            for(int f = 0; f < nf; f++) m_bias[f0 + f] = (float)Quantile(c, (double)m_q[f0 + f]);
            f0 += nf;
           }
        }
      m_fitted = true;
      return MR2_OK;
     }

   //--- one window -> hit counts (F) and denominators (F); PPV = hits/den
   int               Counts(const float &x[], int &hits[], int &den[])
     {
      if(!m_configured) return MR2_NOT_CONFIGURED;
      if(!m_fitted) return MR2_NOT_FITTED;
      if(ArraySize(x) != m_L) return MR2_LENGTH_MISMATCH;
      if(!CheckWindow(x, 0)) return MR2_NON_FINITE;
      ArrayResize(hits, m_F);
      ArrayResize(den, m_F);
      float alpha[], gam[], c[];
      int f0 = 0;
      for(int di = 0; di < m_nd; di++)
        {
         int d = m_dil[di], nf = m_cnt[di], p = (8 * d) / 2;
         Terms(x, d, alpha, gam);
         for(int k = 0; k < 84; k++)
           {
            Conv(alpha, gam, k, c);
            int a = 0, b = m_L;
            if((di + k) % 2 == 1) { a = p; b = m_L - p; }
            if(b - a <= 0) return MR2_EMPTY_SEGMENT;
            for(int f = 0; f < nf; f++)
              {
               float bb = m_bias[f0 + f];
               int h = 0;
               for(int t = a; t < b; t++) if(c[t] > bb) h++;
               hits[f0 + f] = h;
               den[f0 + f] = b - a;
              }
            f0 += nf;
           }
        }
      return MR2_OK;
     }

   int               Transform(const float &x[], double &ppv[])
     {
      int hits[], den[];
      int e = Counts(x, hits, den);
      if(e != MR2_OK) return e;
      ArrayResize(ppv, m_F);
      for(int f = 0; f < m_F; f++) ppv[f] = (double)((float)hits[f] / (float)den[f]);
      return MR2_OK;
     }
  };

//--- PRICE_PATH_ATR_V1 input: last L closes ending at closed bar `end` (series index arrays oldest->newest)
bool MR2PricePath(const double &close[], const int end, const double atrEnd, const double tick, const int L, float &x[])
  {
   if(end - L + 1 < 0 || !MathIsValidNumber(atrEnd)) return false;
   double den = MathMax(atrEnd, tick);
   ArrayResize(x, L);
   double first = close[end - L + 1];
   for(int t = 0; t < L; t++) x[t] = (float)((close[end - L + 1 + t] - first) / den);
   return true;
  }

//--- ATR as in analysis/structure_v2.atr_series: simple mean of the last n true ranges (n=14), oldest->newest arrays
double MR2Atr(const double &h[], const double &l[], const double &c[], const int i, const int n = 14)
  {
   if(i < n) return EMPTY_VALUE;
   double s = 0.0;
   for(int k = i - n + 1; k <= i; k++)
     {
      double tr = (k == 0) ? h[k] - l[k] : MathMax(h[k] - l[k], MathMax(MathAbs(h[k] - c[k - 1]), MathAbs(l[k] - c[k - 1])));
      s += tr;
     }
   return s / n;
  }
#endif
