//+------------------------------------------------------------------+
//| PMW_MM_SelfTest.mq5 - native parity self-test of the master       |
//| models against the frozen Python references.                      |
//| 1) python -m masterquo mm export-fixtures --out <dir>             |
//| 2) copy the CSV files to <MT5 data folder>\MQL5\Files\PMW_MM\     |
//| 3) run this script on any chart                                   |
//| 4) copy PMW_MM\PMW_MM_NATIVE.txt back and run                     |
//|    python -m masterquo mm export-fixtures --parity <file>         |
//| Uses SYNTHETIC fixture bars only (code parity, not market data).  |
//| No trading functions are used.                                    |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs
#include <PMW\PMW_Kalman.mqh>
#include <PMW\PMW_GPR.mqh>
#include <PMW\PMW_HDC.mqh>
#include <PMW\PMW_BreakoutCore.mqh>

input string InpDir = "PMW_MM";

string Num(const double x) { if(!MathIsValidNumber(x) || x == EMPTY_VALUE) return "null"; return StringFormat("%.17g", x); }

bool ReadLines(const string name, string &rows[])
  {
   int h = FileOpen(InpDir + "\\" + name, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) { PrintFormat("PMW_MM_SelfTest: cannot open %s (err %d)", name, GetLastError()); return false; }
   ArrayResize(rows, 0);
   while(!FileIsEnding(h))
     {
      string s = FileReadString(h);
      StringTrimRight(s); StringTrimLeft(s);
      if(StringLen(s) == 0) continue;
      int n = ArraySize(rows); ArrayResize(rows, n + 1, 4096); rows[n] = s;
     }
   FileClose(h);
   return true;
  }

string HexOf(const CPmwHV &v)
  {
   string s = "";
   for(int i = 0; i < v.W; i++) s += (i ? " " : "") + StringFormat("%016I64x", v.w[i]);
   return s;
  }

string Field(const string &rows[], const string key)
  {
   for(int i = 0; i < ArraySize(rows); i++)
     {
      int p = StringFind(rows[i], ",");
      if(p > 0 && StringSubstr(rows[i], 0, p) == key) return StringSubstr(rows[i], p + 1);
     }
   return "";
  }

void OnStart()
  {
   string rb[];
   if(!ReadLines("mm_fixture_bars.csv", rb)) return;
   int n = ArraySize(rb) - 1;
   datetime t[]; double o[], h[], l[], c[], tv[];
   ArrayResize(t, n); ArrayResize(o, n); ArrayResize(h, n); ArrayResize(l, n); ArrayResize(c, n); ArrayResize(tv, n);
   for(int i = 0; i < n; i++)
     {
      string p[]; StringSplit(rb[i + 1], ',', p);
      t[i] = (datetime)StringToInteger(p[0]); o[i] = StringToDouble(p[1]); h[i] = StringToDouble(p[2]); l[i] = StringToDouble(p[3]);
      c[i] = StringToDouble(p[4]); tv[i] = StringToDouble(p[5]);
     }
   string js = "{\"version\":\"PMW-MM-NATIVE-1\",\"bars\":" + IntegerToString(n);
   //--- Kalman (CrossConfig defaults: Qf 1, Qs 0.005, R 0.2, P0 1, confirm 2, tol 0, warmup 20, no startup signal)
   CPmwKalmanCross kx;
   kx.Setup(1.0, 0.2, 0.005, 0.2, 1.0, 2, 0.0, 20, false);
   js += ",\"kalman\":[";
   for(int i = 0; i < n; i++)
     {
      int ev = kx.Update(t[i], c[i]);
      js += (i ? "," : "") + StringFormat("[%I64d,%s,%s,%s,%s,%s,%s,\"%s\"]", (long)t[i], Num(kx.fast.x), Num(kx.slow.x), Num(kx.fast.K), Num(kx.slow.K),
                                          Num(kx.fast.P), Num(kx.slow.P), ev > 0 ? "BULLISH" : ev < 0 ? "BEARISH" : "");
     }
   js += "]";
   //--- GPR with fixed hyper-parameters (window 60, horizon 3, ell 4, signal 0.1, noise 0.5)
   int probes[4] = {300, 700, 1200, 1499};
   js += ",\"gpr\":[";
   for(int q = 0; q < 4; q++)
     {
      int T = probes[q];
      double x[], y[], mean = 0, lat = 0, obs = 0;
      CPmwGP gp;
      bool ok = PmwGprSamples(c, T, 60, 3, x, y) && gp.Refit(x, y, false, 4.0, 0.1, 0.5) && gp.Predict(MathLog(c[T] / c[T - 1]), mean, lat, obs);
      js += (q ? "," : "") + StringFormat("[%d,4,0.1,0.5,%s,%s,%s,%s]", T, ok ? Num(mean) : "null", ok ? Num(lat) : "null", ok ? Num(obs) : "null",
                                          ok ? Num(gp.fit.lml) : "null");
     }
   js += "]";
   //--- HDC primitives against the Python words
   string rh[];
   bool hdc_ok = ReadLines("mm_ref_hdc.csv", rh);
   int D = hdc_ok ? (int)StringToInteger(Field(rh, "D")) : 0;
   CPmwHV a, b, cc, tie, r;
   bool parsed = hdc_ok && D > 0 && PmwHexToHV(Field(rh, "a"), D, a) && PmwHexToHV(Field(rh, "b"), D, b) && PmwHexToHV(Field(rh, "c"), D, cc)
                 && PmwHexToHV(Field(rh, "tie"), D, tie);
   bool ham = false, bind = false, perm = false, b3 = false, b2 = false;
   if(parsed)
     {
      ham = PmwHamming(a, b) == (int)StringToInteger(Field(rh, "hamming_ab"));
      PmwBind(a, b, r); bind = HexOf(r) == Field(rh, "bind_ab");
      PmwPermute(a, 77, r); perm = HexOf(r) == Field(rh, "perm_a_77");
      CPmwHV v3[3]; v3[0].Init(D); v3[1].Init(D); v3[2].Init(D);
      ArrayCopy(v3[0].w, a.w); ArrayCopy(v3[1].w, b.w); ArrayCopy(v3[2].w, cc.w);
      PmwBundle(v3, 3, tie, r); b3 = HexOf(r) == Field(rh, "bundle_abc");
      PmwBundle(v3, 2, tie, r); b2 = HexOf(r) == Field(rh, "bundle_ab_tie");
     }
   js += StringFormat(",\"hdc\":{\"parsed\":%s,\"hamming\":%s,\"bind\":%s,\"permute\":%s,\"bundle3\":%s,\"bundle2_tie\":%s,\"all_pass\":%s}",
                      parsed ? "true" : "false", ham ? "true" : "false", bind ? "true" : "false", perm ? "true" : "false", b3 ? "true" : "false",
                      b2 ? "true" : "false", (parsed && ham && bind && perm && b3 && b2) ? "true" : "false");
   //--- Breakout zones, confirmation NONE (accepted events)
   CPmwBreakout bz;
   bz.Setup(3, 3, 3, 0.5, 14, 0.35, 10.0, 0.10, 2, 600, 0.0, PMW_CONF_NONE, 20, 20, 0, 0, 0.01, 300);
   for(int i = 0; i < n; i++) bz.Update(t[i], o[i], h[i], l[i], c[i], tv[i]);
   js += ",\"breakout\":[";
   int m = 0;
   for(int k = 0; k < ArraySize(bz.ev); k++)
     {
      if(!bz.ev[k].accepted) continue;
      js += (m ? "," : "") + StringFormat("[%I64d,\"%s\",%s,%s]", (long)bz.ev[k].bar_t, bz.ev[k].dir > 0 ? "BULLISH" : "BEARISH", Num(bz.ev[k].lower), Num(bz.ev[k].upper));
      m++;
     }
   js += "]";
   js += StringFormat(",\"terminal\":{\"build\":%d,\"opencl\":%s}}", (int)TerminalInfoInteger(TERMINAL_BUILD),
                      TerminalInfoInteger(TERMINAL_OPENCL_SUPPORT) > 0 ? "true" : "false");
   int fh = FileOpen(InpDir + "\\PMW_MM_NATIVE.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE) { PrintFormat("PMW_MM_SelfTest: cannot write output (err %d)", GetLastError()); return; }
   FileWriteString(fh, js);
   FileClose(fh);
   PrintFormat("PMW_MM_SelfTest: wrote %s\\PMW_MM_NATIVE.txt (bars %d, breakout events %d, hdc %s)", InpDir, n, m, (parsed && ham && bind && perm && b3 && b2) ? "PASS" : "FAIL");
  }
