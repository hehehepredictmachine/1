//+------------------------------------------------------------------+
//| PMW_MR2_Ridge.mqh - MQ_MINIROCKET_RIDGE_V2 head (PMW-UPD-09 R21)  |
//| Scaler fitted on train rows, ridge with UNPENALISED intercept     |
//| (centred data), outputs per horizon: 3 class scores + r_h.        |
//| Small native Fit: DUAL Cholesky (N <= 2048, memory checked).      |
//| Larger: blocked normal-equation operator + diagonal-preconditioned|
//| CG on uchar hit counts (no N x N Gram, no explicit inverse).      |
//| Non-convergence -> SOLVER_NOT_CONVERGED, model is NOT activated.  |
//| Features are stored as uchar hit counts (PPV = hits/den).         |
//+------------------------------------------------------------------+
#ifndef PMW_MR2_RIDGE_MQH
#define PMW_MR2_RIDGE_MQH

#define MR2_DUAL_MAX_N 2048

class CRidgeHeadV2
  {
public:
   int               m_H, m_D, m_K;          // heads, features, outputs per head (4)
   double            m_mu[], m_sd[];
   double            m_W[];                  // H*D*K
   double            m_b[];                  // H*K
   double            m_T[];                  // temperatures per head (calibration, 0 = UNCALIBRATED)
   double            m_resq[];               // H*3 residual quantiles (NaN = none)
   string            m_status;

                     CRidgeHeadV2() { m_K = 4; m_status = "NOT_FITTED"; }

   double            Feat(const uchar &hits[], const int &den[], const int row, const int f)
     {
      return (double)hits[row * m_D + f] / den[f];
     }

   //--- scaler on all rows given (train only, caller's responsibility)
   void              FitScaler(const uchar &hits[], const int &den[], const int n)
     {
      ArrayResize(m_mu, m_D); ArrayResize(m_sd, m_D);
      for(int f = 0; f < m_D; f++)
        {
         double s = 0, s2 = 0;
         for(int r = 0; r < n; r++) s += Feat(hits, den, r, f);
         double mu = s / n;
         for(int r = 0; r < n; r++) { double e = Feat(hits, den, r, f) - mu; s2 += e * e; }
         double sd = MathSqrt(s2 / n);
         m_mu[f] = mu;
         m_sd[f] = (sd > 1e-9) ? sd : 1.0;
        }
     }

   double            Z(const uchar &hits[], const int &den[], const int row, const int f)
     {
      return (Feat(hits, den, row, f) - m_mu[f]) / m_sd[f];
     }

   //--- dual: (Xs Xs^T + lam I) A = Y via Cholesky, W = Xs^T A. Y centred (n x m). Returns false if not SPD / memory.
   bool              SolveDual(const uchar &hits[], const int &den[], const int n, const double &Y[], const int m, const double lam, double &W[])
     {
      if(n > MR2_DUAL_MAX_N) return false;
      double K[];
      if(ArrayResize(K, n * n) != n * n) return false;
      for(int i = 0; i < n; i++)
         for(int j = 0; j <= i; j++)
           {
            double s = 0;
            for(int f = 0; f < m_D; f++) s += Z(hits, den, i, f) * Z(hits, den, j, f);
            K[i * n + j] = s; K[j * n + i] = s;
           }
      for(int i = 0; i < n; i++) K[i * n + i] += lam;
      // Cholesky in place (lower)
      for(int j = 0; j < n; j++)
        {
         double s = K[j * n + j];
         for(int k = 0; k < j; k++) s -= K[j * n + k] * K[j * n + k];
         if(s <= 0) return false;
         double d = MathSqrt(s);
         K[j * n + j] = d;
         for(int i = j + 1; i < n; i++)
           {
            double t = K[i * n + j];
            for(int k = 0; k < j; k++) t -= K[i * n + k] * K[j * n + k];
            K[i * n + j] = t / d;
           }
        }
      ArrayResize(W, m_D * m);
      ArrayInitialize(W, 0.0);
      double a[];
      ArrayResize(a, n);
      for(int c = 0; c < m; c++)
        {
         for(int i = 0; i < n; i++)                 // forward  L z = y
           {
            double t = Y[i * m + c];
            for(int k = 0; k < i; k++) t -= K[i * n + k] * a[k];
            a[i] = t / K[i * n + i];
           }
         for(int i = n - 1; i >= 0; i--)            // backward L^T a = z
           {
            double t = a[i];
            for(int k = i + 1; k < n; k++) t -= K[k * n + i] * a[k];
            a[i] = t / K[i * n + i];
           }
         for(int f = 0; f < m_D; f++)
           {
            double s = 0;
            for(int i = 0; i < n; i++) s += Z(hits, den, i, f) * a[i];
            W[f * m + c] = s;
           }
        }
      return true;
     }

   //--- CG on (Xs^T Xs + lam I) w = Xs^T y, one output column; blocked over rows
   bool              SolveCG(const uchar &hits[], const int &den[], const int n, const double &y[], const double lam, double &w[],
                             const double tol, const int maxIter, int &iters, double &relres)
     {
      double diag[], b[], r[], z[], p[], Ap[], xv[];
      ArrayResize(diag, m_D); ArrayResize(b, m_D); ArrayResize(r, m_D); ArrayResize(z, m_D); ArrayResize(p, m_D); ArrayResize(Ap, m_D);
      ArrayResize(w, m_D); ArrayInitialize(w, 0.0); ArrayResize(xv, n);
      for(int f = 0; f < m_D; f++)
        {
         double s = 0, sb = 0;
         for(int i = 0; i < n; i++) { double v = Z(hits, den, i, f); s += v * v; sb += v * y[i]; }
         diag[f] = lam + s; b[f] = sb;
        }
      double bn = 0;
      for(int f = 0; f < m_D; f++) { r[f] = b[f]; z[f] = r[f] / diag[f]; p[f] = z[f]; bn += b[f] * b[f]; }
      bn = MathSqrt(bn); if(bn == 0) bn = 1;
      double rz = 0;
      for(int f = 0; f < m_D; f++) rz += r[f] * z[f];
      for(iters = 1; iters <= maxIter; iters++)
        {
         for(int i = 0; i < n; i++) { double s = 0; for(int f = 0; f < m_D; f++) s += Z(hits, den, i, f) * p[f]; xv[i] = s; }
         double pAp = 0;
         for(int f = 0; f < m_D; f++)
           {
            double s = lam * p[f];
            for(int i = 0; i < n; i++) s += Z(hits, den, i, f) * xv[i];
            Ap[f] = s; pAp += p[f] * s;
           }
         double a = rz / pAp, rn = 0;
         for(int f = 0; f < m_D; f++) { w[f] += a * p[f]; r[f] -= a * Ap[f]; rn += r[f] * r[f]; }
         relres = MathSqrt(rn) / bn;
         if(relres <= tol) return true;
         double rzn = 0;
         for(int f = 0; f < m_D; f++) { z[f] = r[f] / diag[f]; rzn += r[f] * z[f]; }
         for(int f = 0; f < m_D; f++) p[f] = z[f] + (rzn / rz) * p[f];
         rz = rzn;
        }
      return false;
     }

   //--- raw scores for one transformed window: scores[H*4]
   void              Raw(const double &ppv[], double &scores[])
     {
      ArrayResize(scores, m_H * m_K);
      for(int h = 0; h < m_H; h++)
         for(int k = 0; k < m_K; k++)
           {
            double s = m_b[h * m_K + k];
            for(int f = 0; f < m_D; f++) s += ((ppv[f] - m_mu[f]) / m_sd[f]) * m_W[(h * m_D + f) * m_K + k];
            scores[h * m_K + k] = s;
           }
     }

   //--- probabilities (temperature softmax) - only when calibrated, otherwise caller reports UNCALIBRATED raw scores
   bool              Proba(const double &scores[], const int h, double &p[])
     {
      if(ArraySize(m_T) <= h || !(m_T[h] > 0)) return false;
      ArrayResize(p, 3);
      double mx = -DBL_MAX;
      for(int k = 0; k < 3; k++) mx = MathMax(mx, scores[h * m_K + k] / m_T[h]);
      double s = 0;
      for(int k = 0; k < 3; k++) { p[k] = MathExp(scores[h * m_K + k] / m_T[h] - mx); s += p[k]; }
      for(int k = 0; k < 3; k++) p[k] /= s;
      return true;
     }
  };
#endif
