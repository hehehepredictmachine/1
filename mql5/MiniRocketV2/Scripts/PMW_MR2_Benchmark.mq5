//+------------------------------------------------------------------+
//| PMW_MR2_Benchmark.mq5 - native cold/warm benchmark (T122).       |
//| Configure, Fit (64 windows), warmup>=20, >=1000 measured         |
//| Transform calls on L=128/requested=10000, GetMicrosecondCount,    |
//| no I/O inside the timed region. Raw timings + p50/p95/p99 ->      |
//| MQL5\Files\PMW\mr2_benchmark.csv. Target warm p95 <= 5 ms is a     |
//| design target: PERFORMANCE_TARGET_NOT_MET is reported if missed.  |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict
#include <PMW\PMW_MR2_Format.mqh>

input int InpWarmup = 20;
input int InpN = 1000;

double Pct(double &a[], const double p)
  {
   double s[]; ArrayCopy(s, a); ArraySort(s);
   int n = ArraySize(s);
   double pos = p * (n - 1); int lo = (int)MathFloor(pos); int hi = MathMin(lo + 1, n - 1);
   return s[lo] + (pos - lo) * (s[hi] - s[lo]);
  }

void OnStart()
  {
   int L = 128, nfit = 64;
   float X[]; ArrayResize(X, (InpWarmup + InpN + nfit) * L);
   CSplitMix64 r(5);
   for(int w = 0; w < InpWarmup + InpN + nfit; w++)
     {
      double v = 0;
      for(int t = 0; t < L; t++) { v += ((double)(r.Next() % 2001) - 1000.0) / 1000.0; X[w * L + t] = (float)v; }
     }
   CMiniRocketV2 mr;
   ulong t0 = GetMicrosecondCount();
   mr.Configure(L, 10000, 32);
   ulong tConf = GetMicrosecondCount() - t0;
   int frozen[];
   t0 = GetMicrosecondCount();
   int e = mr.Fit(X, nfit, 1, frozen);
   ulong tFit = GetMicrosecondCount() - t0;
   if(e != MR2_OK) { Print("PMW_MR2_BENCH FAIL fit ", MR2ErrorText(e)); return; }
   float x[]; ArrayResize(x, L);
   double ppv[];
   for(int i = 0; i < InpWarmup; i++) { ArrayCopy(x, X, 0, (nfit + i) * L, L); mr.Transform(x, ppv); }
   double ms[]; ArrayResize(ms, InpN);
   for(int i = 0; i < InpN; i++)
     {
      ArrayCopy(x, X, 0, (nfit + InpWarmup + i) * L, L);
      ulong a = GetMicrosecondCount();
      mr.Transform(x, ppv);
      ms[i] = (GetMicrosecondCount() - a) / 1000.0;
     }
   double p50 = Pct(ms, 0.50), p95 = Pct(ms, 0.95), p99 = Pct(ms, 0.99);
   FolderCreate("PMW");
   int h = FileOpen("PMW\\mr2_benchmark.csv", FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h != INVALID_HANDLE)
     {
      FileWriteString(h, StringFormat("build,%d\r\ncpu_cores,%d\r\nconfigure_us,%I64u\r\nfit64_us,%I64u\r\nF,%d\r\np50_ms,%.4f\r\np95_ms,%.4f\r\np99_ms,%.4f\r\n",
                                      (int)TerminalInfoInteger(TERMINAL_BUILD), (int)TerminalInfoInteger(TERMINAL_CPU_CORES), tConf, tFit, mr.m_F, p50, p95, p99));
      for(int i = 0; i < InpN; i++) FileWriteString(h, StringFormat("raw_ms,%.4f\r\n", ms[i]));
      FileClose(h);
     }
   PrintFormat("PMW_MR2_BENCH F=%d p50=%.3f p95=%.3f p99=%.3f ms %s", mr.m_F, p50, p95, p99, p95 <= 5.0 ? "TARGET_MET" : "PERFORMANCE_TARGET_NOT_MET");
  }
