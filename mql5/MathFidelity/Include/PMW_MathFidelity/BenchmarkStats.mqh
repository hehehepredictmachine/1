//+------------------------------------------------------------------+
//| BenchmarkStats.mqh - numerical error and latency statistics.      |
//| Fidelity is computed over the UNIQUE test vectors; latency over   |
//| the raw per-call samples (timed passes x vectors). Percentiles use |
//| linear interpolation at rank p*(n-1) (same as                      |
//| masterquo.mm.mathbench.percentile_linear). Zero-microsecond samples |
//| are kept as measured and counted (timer resolution disclosure).    |
//+------------------------------------------------------------------+
#ifndef PMW_BENCH_STATS_MQH
#define PMW_BENCH_STATS_MQH
#include "BenchmarkConfig.mqh"

double BenchPercentile(const double &sorted[], const double p)
  {
   int n = ArraySize(sorted);
   if(n == 0) return EMPTY_VALUE;
   double r = p * (n - 1);
   int lo = (int)MathFloor(r), hi = (int)MathCeil(r);
   return sorted[lo] + (sorted[hi] - sorted[lo]) * (r - lo);
  }

class CBenchErrorStats
  {
public:
   int    n, ok, failed, passed;
   double sum_abs, max_abs, sum_rel, max_rel, sum_sq, abs_tol, rel_tol;
   void   Reset(const double atol, const double rtol) { n = 0; ok = 0; failed = 0; passed = 0; sum_abs = 0; max_abs = 0; sum_rel = 0; max_rel = 0; sum_sq = 0; abs_tol = atol; rel_tol = rtol; }
   // returns true when the vector is within tolerance (abs OR rel); a failed call is counted, never scored as 0
   bool   Add(const bool call_ok, const double pred, const double ref, double &abs_e, double &rel_e)
     {
      n++;
      if(!call_ok || !MathIsValidNumber(pred)) { failed++; abs_e = EMPTY_VALUE; rel_e = EMPTY_VALUE; return false; }
      ok++;
      abs_e = MathAbs(pred - ref);
      rel_e = abs_e / MathMax(MathAbs(ref), BENCH_REL_FLOOR);
      sum_abs += abs_e; sum_rel += rel_e; sum_sq += abs_e * abs_e;
      max_abs = MathMax(max_abs, abs_e); max_rel = MathMax(max_rel, rel_e);
      bool pass = abs_e <= abs_tol || rel_e <= rel_tol;
      if(pass) passed++;
      return pass;
     }
   double MeanAbs() const { return ok ? sum_abs / ok : EMPTY_VALUE; }
   double MeanRel() const { return ok ? sum_rel / ok : EMPTY_VALUE; }
   double Rmse() const { return ok ? MathSqrt(sum_sq / ok) : EMPTY_VALUE; }
  };

class CBenchLatency
  {
public:
   double samples[];
   int    n, failed, zeros;
   void   Reset(const int capacity) { ArrayResize(samples, 0, capacity); n = 0; failed = 0; zeros = 0; }
   void   Add(const ulong us, const bool call_ok)
     {
      if(!call_ok) { failed++; return; }                             // latency of failed calls is not mixed into the distribution
      int k = ArraySize(samples); ArrayResize(samples, k + 1, 1 << 20); samples[k] = (double)us; n++;
      if(us == 0) zeros++;
     }
   bool   Summary(double &mean, double &median, double &p95, double &p99, double &mn, double &mx)
     {
      if(n == 0) return false;
      double s[]; ArrayCopy(s, samples); ArraySort(s);
      double sum = 0; for(int i = 0; i < n; i++) sum += s[i];
      mean = sum / n; median = BenchPercentile(s, 0.5); p95 = BenchPercentile(s, 0.95); p99 = BenchPercentile(s, 0.99); mn = s[0]; mx = s[n - 1];
      return true;
     }
  };
#endif
