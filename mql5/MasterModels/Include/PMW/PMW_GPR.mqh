//+------------------------------------------------------------------+
//| PMW_GPR.mqh - native Gaussian process regression (PMW-MM-GPR-1)   |
//| Same contract as backend/masterquo/mm/gpr.py:                     |
//|  x_k = ln(C[k]/C[k-1]), y_k = ln(C[k+h]/C[k]) on CHRONOLOGICAL     |
//|  closed bars (index 0 = oldest; the caller copies with shift 1).  |
//|  Matern 3/2, population-std standardisation (floor -> scale 1),   |
//|  K = k(X,X)+noise I, Cholesky with a fresh-copy jitter ladder,    |
//|  alpha by two triangular solves, latent var = k** - v.v,          |
//|  observed var = latent + noise (normalised), back-transform y_std^2|
//|  LML = -0.5 y.alpha - sum log Lii - n/2 log 2pi; grid search with  |
//|  a PURE scorer; the winning fit is built in a temporary object and |
//|  copied into the committed state only after validation.           |
//+------------------------------------------------------------------+
#ifndef PMW_GPR_MQH
#define PMW_GPR_MQH
#define PMW_GPR_VERSION "PMW-MM-GPR-1"

double PmwMatern32(const double a, const double b, const double ell, const double sv)
  {
   double s = MathSqrt(3.0) * MathAbs(a - b) / ell;
   return sv * (1.0 + s) * MathExp(-s);
  }

// shared sample builder (indicator + EA use exactly this): c[] chronological, T = index of the last CLOSED bar used
bool PmwGprSamples(const double &c[], const int T, const int window, const int h, double &x[], double &y[])
  {
   int hi = T - h, lo = hi - window + 1;
   if(lo < 1 || hi >= ArraySize(c))
      return false;
   ArrayResize(x, window); ArrayResize(y, window);
   for(int j = 0; j < window; j++)
     {
      int k = lo + j;
      if(c[k - 1] <= 0.0 || c[k] <= 0.0 || c[k + h] <= 0.0)
         return false;
      x[j] = MathLog(c[k] / c[k - 1]);
      y[j] = MathLog(c[k + h] / c[k]);
      if(!MathIsValidNumber(x[j]) || !MathIsValidNumber(y[j]))
         return false;
     }
   return true;
  }

class CPmwGPFit
  {
public:
   int      n;
   double   xn[], yn[], L[], alpha[];
   double   xm, xs, ym, ys, ell, sv, nv, jitter, lml;
   int      rung;
   bool     degenerate, valid;
   datetime fit_time;
            CPmwGPFit() : n(0), xm(0), xs(1), ym(0), ys(1), ell(0), sv(0), nv(0), jitter(0), lml(0), rung(0), degenerate(false), valid(false), fit_time(0) {}
   void     CopyFrom(const CPmwGPFit &o)                           // explicit deep copy (arrays) - used for the atomic commit
     {
      n = o.n; ArrayCopy(xn, o.xn); ArrayCopy(yn, o.yn); ArrayCopy(L, o.L); ArrayCopy(alpha, o.alpha);
      xm = o.xm; xs = o.xs; ym = o.ym; ys = o.ys; ell = o.ell; sv = o.sv; nv = o.nv; jitter = o.jitter; lml = o.lml; rung = o.rung;
      degenerate = o.degenerate; valid = o.valid; fit_time = o.fit_time;
     }
  };

bool PmwStd(const double &v[], const double floor_, double &m, double &s)
  {
   int n = ArraySize(v);
   m = 0; for(int i = 0; i < n; i++) m += v[i]; m /= n;
   double q = 0; for(int i = 0; i < n; i++) q += (v[i] - m) * (v[i] - m);
   s = MathSqrt(q / n);
   if(s <= floor_) { s = 1.0; return true; }                     // degenerate window flag
   return false;
  }

// Cholesky of A (n x n, row-major) into L; false if not PD
bool PmwCholesky(const double &A[], const int n, double &L[])
  {
   ArrayResize(L, n * n); ArrayInitialize(L, 0.0);
   for(int i = 0; i < n; i++)
      for(int j = 0; j <= i; j++)
        {
         double s = A[i * n + j];
         for(int k = 0; k < j; k++) s -= L[i * n + k] * L[j * n + k];
         if(i == j)
           {
            if(!(s > 0.0) || !MathIsValidNumber(s)) return false;
            L[i * n + i] = MathSqrt(s);
           }
         else L[i * n + j] = s / L[j * n + j];
        }
   return true;
  }

void PmwSolveLower(const double &L[], const int n, const double &b[], double &out[])
  {
   ArrayResize(out, n);
   for(int i = 0; i < n; i++) { double s = b[i]; for(int k = 0; k < i; k++) s -= L[i * n + k] * out[k]; out[i] = s / L[i * n + i]; }
  }

void PmwSolveUpperT(const double &L[], const int n, const double &b[], double &out[])
  {
   ArrayResize(out, n);
   for(int i = n - 1; i >= 0; i--) { double s = b[i]; for(int k = i + 1; k < n; k++) s -= L[k * n + i] * out[k]; out[i] = s / L[i * n + i]; }
  }

// PURE: builds a complete candidate fit into f (never touches a committed model)
bool PmwGprScore(const double &x[], const double &y[], const double ell, const double sv, const double nv, const double floor_, CPmwGPFit &f)
  {
   int n = ArraySize(x);
   f.valid = false;
   if(!(ell > 0 && sv > 0 && nv > 0)) return false;
   bool dx = PmwStd(x, floor_, f.xm, f.xs), dy = PmwStd(y, floor_, f.ym, f.ys);
   f.degenerate = dx || dy;
   ArrayResize(f.xn, n); ArrayResize(f.yn, n);
   for(int i = 0; i < n; i++) { f.xn[i] = (x[i] - f.xm) / f.xs; f.yn[i] = (y[i] - f.ym) / f.ys; }
   double K[]; ArrayResize(K, n * n);
   for(int i = 0; i < n; i++)
      for(int j = 0; j <= i; j++) { double v = PmwMatern32(f.xn[i], f.xn[j], ell, sv); K[i * n + j] = v; K[j * n + i] = v; }
   for(int i = 0; i < n; i++) K[i * n + i] += nv;
   double ladder[6] = {0.0, 1e-10, 1e-8, 1e-6, 1e-4, 1e-2};
   bool ok = false;
   for(int r = 0; r < 6 && !ok; r++)
     {
      double A[]; ArrayCopy(A, K);                                // fresh copy: jitter never accumulates
      for(int i = 0; i < n; i++) A[i * n + i] += ladder[r];
      if(PmwCholesky(A, n, f.L)) { ok = true; f.jitter = ladder[r]; f.rung = r; }
     }
   if(!ok) return false;
   double t[]; PmwSolveLower(f.L, n, f.yn, t); PmwSolveUpperT(f.L, n, t, f.alpha);
   double q = 0, ld = 0;
   for(int i = 0; i < n; i++) { q += f.yn[i] * f.alpha[i]; ld += MathLog(f.L[i * n + i]); }
   f.lml = -0.5 * q - ld - 0.5 * n * MathLog(2.0 * M_PI);
   if(!MathIsValidNumber(f.lml)) return false;
   f.n = n; f.ell = ell; f.sv = sv; f.nv = nv; f.valid = true; f.fit_time = TimeCurrent();
   return true;
  }

class CPmwGP
  {
public:
   CPmwGPFit fit;                                                   // committed state (valid only after a full successful fit)
   int       candidates, failed;
   double    best_lml, top5_spread;
             CPmwGP() : candidates(0), failed(0), best_lml(0), top5_spread(0) {}
   bool      Refit(const double &x[], const double &y[], const bool tune, const double ell0, const double sv0, const double nv0)
     {
      CPmwGPFit tmp;
      double ell = ell0, sv = sv0, nv = nv0;
      if(tune)
        {
         double ge[7] = {1, 2, 4, 8, 16, 32, 64};
         double gs[5] = {1e-4, 1e-3, 1e-2, 1e-1, 1};
         double gn[9] = {1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 0.3, 1.0, 3.0};   // extended noise grid (see gpr.py GRID_NOTE)
         candidates = 0; failed = 0; best_lml = -DBL_MAX;
         double scores[]; ArrayResize(scores, 0);
         for(int a = 0; a < 7; a++) for(int b = 0; b < 5; b++) for(int c = 0; c < 9; c++)
              {
               CPmwGPFit cand;
               candidates++;
               if(!PmwGprScore(x, y, ge[a], gs[b], gn[c], 1e-12, cand)) { failed++; continue; }
               int m = ArraySize(scores); ArrayResize(scores, m + 1); scores[m] = cand.lml;
               if(cand.lml > best_lml) { best_lml = cand.lml; ell = ge[a]; sv = gs[b]; nv = gn[c]; }
              }
         if(ArraySize(scores) == 0) return false;
         ArraySort(scores);
         int m = ArraySize(scores);
         top5_spread = scores[m - 1] - scores[MathMax(0, m - 5)];
        }
      if(!PmwGprScore(x, y, ell, sv, nv, 1e-12, tmp)) return false;  // previous committed fit stays untouched on failure
      fit.CopyFrom(tmp);                                             // commit only now
      return true;
     }
   // returns false on invalid state / numerical fault; outputs in RAW log-return units
   bool      Predict(const double xstar, double &mean, double &latent_var, double &obs_var)
     {
      if(!fit.valid) return false;
      int n = fit.n;
      double xs = (xstar - fit.xm) / fit.xs;
      double ks[]; ArrayResize(ks, n);
      double mn = 0;
      for(int i = 0; i < n; i++) { ks[i] = PmwMatern32(xs, fit.xn[i], fit.ell, fit.sv); mn += ks[i] * fit.alpha[i]; }
      double v[]; PmwSolveLower(fit.L, n, ks, v);
      double vv = 0; for(int i = 0; i < n; i++) vv += v[i] * v[i];
      double lat = fit.sv - vv;
      if(lat < -1e-9) return false;                                  // numerical fault, never clipped silently
      lat = MathMax(lat, 0.0);
      mean = mn * fit.ys + fit.ym;
      latent_var = lat * fit.ys * fit.ys;
      obs_var = (lat + fit.nv) * fit.ys * fit.ys;
      return MathIsValidNumber(mean) && obs_var >= 0;
     }
  };
#endif
