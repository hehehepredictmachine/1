//+------------------------------------------------------------------+
//| MQ_FlowSelfTest.mq5 - native self-test of the shared MA kernel    |
//| (PMW-UPD-11 FF06/T47). Hand-derived values; result line           |
//| "PMW_FLOW_SELFTEST RESULT=PASS|FAIL" in Experts log and           |
//| MQL5\Files\PMW\flow_selftest.txt. No trading.                      |
//+------------------------------------------------------------------+
#property strict
#include <PMW\PMW_FlowMA.mqh>

int g_fail = 0, g_h = INVALID_HANDLE;
void Check(const bool ok, const string what) { if(!ok) g_fail++; string s = (ok ? "PASS " : "FAIL ") + what; Print(s); if(g_h != INVALID_HANDLE) FileWriteString(g_h, s + "\r\n"); }

void OnStart()
  {
   FolderCreate("PMW");
   g_h = FileOpen("PMW\\flow_selftest.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
   double x[] = {1, 2, 3, 4, 5};
   double o[5], S[5], W[5];
   for(int i = 0; i < 5; i++) MAStep(3, 3, 0, x, i, o, S, W);
   Check(MathAbs(o[2] - (1 + 4 + 9) / 6.0) < 1e-12, "LWMA(3) weights oldest->newest");
   Check(MathAbs(o[1] - (1 + 4) / 3.0) < 1e-12, "LWMA partial prefix m=2");
   for(int i = 0; i < 5; i++) MAStep(1, 3, 1, x, i, o, S, W);
   Check(o[1] == EMPTY_VALUE && MathAbs(o[2] - 2.0) < 1e-12 && MathAbs(o[4] - 4.0) < 1e-12, "SMA FULL_SEED");
   for(int i = 0; i < 5; i++) MAStep(0, 3, 0, x, i, o, S, W);
   Check(MathAbs(o[0] - 1.0) < 1e-12 && MathAbs(o[2] - 2.0) < 1e-12 && MathAbs(o[3] - 3.0) < 1e-12, "EMA PARTIAL_PREFIX seed = SMA_P, then alpha 0.5");
   double before = o[4];
   MAStep(0, 3, 0, x, 4, o, S, W);
   Check(o[4] == before, "recomputing the same (forming) bar does not double-update");
   Check(FlowClampPeriod(0) == 1 && FlowClampPeriod(20000) == 10000, "period clamp 1..10000");
   Print("PMW_FLOW_SELFTEST RESULT=", g_fail == 0 ? "PASS" : "FAIL", " failures=", g_fail);
   if(g_h != INVALID_HANDLE) { FileWriteString(g_h, StringFormat("PMW_FLOW_SELFTEST RESULT=%s\r\n", g_fail == 0 ? "PASS" : "FAIL")); FileClose(g_h); }
  }
