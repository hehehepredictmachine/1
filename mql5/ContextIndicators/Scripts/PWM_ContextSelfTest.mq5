//+------------------------------------------------------------------+
//| PWM_ContextSelfTest.mq5 - native self-test + parity export         |
//| (PMW-UPD-14 VS07). 1) hand-derived Katz checks; 2) runs the native |
//| cores (default profiles) on the frozen OHLC from                   |
//| MQL5\Files\PMW\ctx_fixture_bars.csv (written by                    |
//| `context-indicators export-fixture --files-dir ...`) and writes    |
//| MQL5\Files\PMW\PWM_CONTEXT_EXPORT.txt for                          |
//| `context-indicators native-parity --export ...`.                   |
//| Result line "PMW_CTX_SELFTEST RESULT=PASS|FAIL" in                 |
//| Files\PMW\ctx_selftest.txt. No trading.                            |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs
#include <PMW\PMW_ContextCore.mqh>

input double InpTick = 0.01;      // tick of the frozen fixture (not the chart symbol)
input int    InpTfSeconds = 300;

int g_fail = 0, g_h = INVALID_HANDLE;
void Check(const bool ok, const string what) { if(!ok) g_fail++; string s = (ok ? "PASS " : "FAIL ") + what; Print(s); if(g_h != INVALID_HANDLE) FileWriteString(g_h, s + "\r\n"); }

void KatzCase(const double &p[], const bool expectSat, const double expectRaw, const string name)
  {
   CPmwFractal f; f.Init(ArraySize(p), 1, 1.4, 1.65, 1.0, 1e-12);
   for(int i = 0; i < ArraySize(p); i++) f.Update(p[i]);
   if(expectSat) Check(f.saturated && f.out_bounded == 2.0 && !f.has_raw, name);
   else Check(f.has_raw && MathAbs(f.out_raw - expectRaw) < 1e-12, name);
  }

void OnStart()
  {
   FolderCreate("PMW");
   g_h = FileOpen("PMW\\ctx_selftest.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
   double a[] = {0, 1, 2, 3}, b[] = {0, 1, 0, 1}, c[] = {0, 2, 1, 3};
   KatzCase(a, false, 1.0, "Katz monotonic L=d=3 -> 1");
   KatzCase(b, true, 0, "Katz L=3,d=1 -> den=0 -> saturation 2");
   KatzCase(c, false, MathLog(3) / (MathLog(3) + MathLog(3.0 / 5.0)), "Katz L=5,d=3 (d = max displacement, not endpoint)");
   CPmwVamd v; v.Init(1, 1, 1, 0.15, 0.9);
   v.Update(10, 10, 10); v.Update(11, 9, 10); bool r1 = v.Update(12, 10, 14);
   Check(r1 && MathAbs(v.out_m - 4.0 / v.out_atr) < 1e-12, "VAMD m=(C-C_P)/ATR");
   // ---- parity export on frozen bars
   int fh = FileOpen("PMW\\ctx_fixture_bars.csv", FILE_READ | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE) { Check(false, "ctx_fixture_bars.csv missing (run export-fixture --files-dir)"); }
   else
     {
      FileReadString(fh);                                   // header
      long t[]; double o[], h[], l[], cl[]; int n = 0;
      while(!FileIsEnding(fh))
        {
         string ln = FileReadString(fh); if(StringLen(ln) < 5) continue;
         string p[]; if(StringSplit(ln, ',', p) != 5) continue;
         ArrayResize(t, n + 1); ArrayResize(o, n + 1); ArrayResize(h, n + 1); ArrayResize(l, n + 1); ArrayResize(cl, n + 1);
         t[n] = StringToInteger(p[0]); o[n] = StringToDouble(p[1]); h[n] = StringToDouble(p[2]); l[n] = StringToDouble(p[3]); cl[n] = StringToDouble(p[4]); n++;
        }
      FileClose(fh);
      Check(n > 100, StringFormat("fixture bars read: %d", n));
      CPmwVamd vm; vm.Init(10, 14, 50, 0.15, 0.90);
      CPmwFractal fd; fd.Init(30, 5, 1.40, 1.65, InpTick, 0.5);
      CPmwSmc sm; sm.Init(true, true, true, InpTick);
      string body = StringFormat("{\"schema\":\"PMW-CTX-EXPORT-1\",\"seq\":%I64d,\"symbol\":\"FIXTURE\",\"tf\":\"M5\",\"tf_s\":%d,\"tick\":%.10f,"
                                 "\"seed_origin\":%I64d,\"build\":%d,\"vamd\":null,\"fd\":null,\"smc\":null}\n",
                                 (long)TimeGMT(), InpTfSeconds, InpTick, n > 0 ? t[0] : 0, (int)TerminalInfoInteger(TERMINAL_BUILD));
      for(int i = 0; i < n; i++)
        {
         bool vr = vm.Update(h[i], l[i], cl[i]);
         bool fr = fd.Update(cl[i]);
         sm.Update(h[i], l[i], cl[i]);
         int zone = fr ? fd.zone : 0;
         body += StringFormat("%I64d,%s,%s,%s,%s,%s,%s,%s,%s,%d,%d,%s,%s,%d,%s,%s,%s,%s\n", t[i], PmwNum(o[i], true), PmwNum(h[i], true), PmwNum(l[i], true),
                              PmwNum(cl[i], true), PmwNum(vm.out_y, vr), PmwNum(vm.out_alpha, vr), PmwNum(fd.out_bounded, fd.has_bounded),
                              PmwNum(fd.ema, fr), zone, sm.trend, PmwNum(sm.slotH.level, sm.slotH.status == 1), PmwNum(sm.slotL.level, sm.slotL.status == 1),
                              sm.mask, PmwNum(sm.pb_h, sm.pb_h_set), PmwNum(sm.pb_l, sm.pb_l_set), PmwNum(sm.st_h, sm.st_h_set), PmwNum(sm.st_l, sm.st_l_set));
        }
      string hex; uchar data[];
      if(!PmwSha256Hex(body, hex, data)) Check(false, "SHA256 unavailable");
      else
        {
         uchar tail[]; string ts = "#sha256=" + hex + "\n"; StringToCharArray(ts, tail, 0, StringLen(ts), CP_UTF8);
         Check(PmwAtomicWrite("PMW\\PWM_CONTEXT_EXPORT.tmp", "PMW\\PWM_CONTEXT_EXPORT.txt", data, tail), "export written atomically");
        }
     }
   Print("PMW_CTX_SELFTEST RESULT=", g_fail == 0 ? "PASS" : "FAIL", " failures=", g_fail);
   if(g_h != INVALID_HANDLE) { FileWriteString(g_h, StringFormat("PMW_CTX_SELFTEST RESULT=%s\r\n", g_fail == 0 ? "PASS" : "FAIL")); FileClose(g_h); }
  }
