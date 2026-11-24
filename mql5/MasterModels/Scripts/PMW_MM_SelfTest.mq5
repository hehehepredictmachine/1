//+------------------------------------------------------------------+
//| PMW_MM_SelfTest.mq5 - native parity self-test of the master       |
//| models against the frozen Python references.                      |
//| 1) python -m masterquo mm export-fixtures --out <dir>             |
//| 2) copy the CSV files to <MT5 data folder>\MQL5\Files\PMW_MM\     |
//| 3) run this script on any chart                                   |
//| 4) copy PMW_MM\PMW_MM_NATIVE.txt back and run                     |
//|    python -m masterquo mm export-fixtures --parity <file>         |
//| Sections: kalman, gpr (fixed hyper-parameters), gpr_tune (LML grid |
//| search = indicator default), hdc (raw words), hdc_acc (class      |
//| accumulators), breakout (NONE) + breakout_modes (all 4 modes),    |
//| tsvp (core on a tick fixture), stack (state stack CPU / OpenCL).  |
//| The script writes RAW values only; every gate is computed by the  |
//| Python side (all_pass of hdc is informational).                   |
//| Uses SYNTHETIC fixture data only (code parity, not market data).  |
//| No trading functions are used.                                    |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs
#include <PMW\PMW_Kalman.mqh>
#include <PMW\PMW_GPR.mqh>
#include <PMW\PMW_HDC.mqh>
#include <PMW\PMW_BreakoutCore.mqh>
#include <PMW\PMW_TSVPCore.mqh>
#include <PMW\PMW_StateStack.mqh>

input string InpDir = "PMW_MM";

string Num(const double x) { if(!MathIsValidNumber(x) || x == EMPTY_VALUE) return "null"; return StringFormat("%.17g", x); }
string JB(const bool x) { return x ? "true" : "false"; }

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

bool ParseFloats(const string s, const int n, float &out[])
  {
   string p[];
   if(StringSplit(s, ' ', p) != n) return false;
   ArrayResize(out, n);
   for(int i = 0; i < n; i++) out[i] = (float)StringToDouble(p[i]);
   return true;
  }

string FloatList(const float &a[])
  {
   string s = "[";
   for(int i = 0; i < ArraySize(a); i++) s += (i ? "," : "") + Num((double)a[i]);
   return s + "]";
  }

string IntList(const int &a[])
  {
   string s = "[";
   for(int i = 0; i < ArraySize(a); i++) s += (i ? "," : "") + IntegerToString(a[i]);
   return s + "]";
  }

//--- HDC class accumulators (CPmwHDCAcc) against mm/hdc.Classifier: updates, prototypes, class + margin + similarities of the queries
string HdcAccJson()
  {
   string ra[];
   if(!ReadLines("mm_ref_hdc_acc.csv", ra)) return "null";
   int D = (int)StringToInteger(Field(ra, "D")), C = (int)StringToInteger(Field(ra, "C"));
   int nu = (int)StringToInteger(Field(ra, "n_updates")), nq = (int)StringToInteger(Field(ra, "n_queries"));
   CPmwHV atie;
   bool parsed = D > 0 && C > 1 && PmwHexToHV(Field(ra, "tie"), D, atie);
   CPmwHDCAcc acc;
   int done = 0;
   if(parsed)
     {
      acc.Init(D, C);
      for(int u = 0; u < nu; u++)
        {
         CPmwHV uv;
         if(!PmwHexToHV(Field(ra, StringFormat("u%d_v", u)), D, uv)) { parsed = false; break; }
         if(acc.Update(uv, (int)StringToInteger(Field(ra, StringFormat("u%d_y", u))))) done++;
        }
     }
   string o = StringFormat("{\"parsed\":%s,\"updates\":%d,\"protos\":[", JB(parsed), done);
   CPmwHV protos[];
   if(parsed)
     {
      ArrayResize(protos, C);
      for(int k = 0; k < C; k++) { acc.Prototype(k, atie, protos[k]); o += (k ? "," : "") + "\"" + HexOf(protos[k]) + "\""; }
     }
   o += "],\"queries\":[";
   if(parsed)
      for(int j = 0; j < nq; j++)
        {
         CPmwHV qv;
         if(!PmwHexToHV(Field(ra, StringFormat("q%d", j)), D, qv)) break;
         double sim[]; ArrayResize(sim, C);
         int best = 0;
         for(int k = 0; k < C; k++) { sim[k] = PmwSimilarity(qv, protos[k]); if(sim[k] > sim[best]) best = k; }   // ties -> lowest class
         double second = -DBL_MAX;
         for(int k = 0; k < C; k++) if(k != best && sim[k] > second) second = sim[k];
         o += (j ? "," : "") + StringFormat("[%d,%s", best, Num(sim[best] - second));
         for(int k = 0; k < C; k++) o += "," + Num(sim[k]);
         o += "]";
        }
   return o + "]}";
  }

//--- TSVP: one range read of the tick fixture (rows of mm_fixture_ticks.csv with this read id)
bool LoadRead(const string &rows[], const int read_id, MqlTick &out[], long &until)
  {
   ArrayResize(out, 0); until = -1;
   for(int i = 1; i < ArraySize(rows); i++)                          // row 0 = header
     {
      string p[];
      if(StringSplit(rows[i], ',', p) != 9) return false;
      if((int)StringToInteger(p[0]) != read_id) continue;
      until = StringToInteger(p[1]);
      MqlTick tk;
      ZeroMemory(tk);
      tk.time_msc = StringToInteger(p[2]); tk.time = (datetime)(tk.time_msc / 1000);
      tk.bid = StringToDouble(p[3]); tk.ask = StringToDouble(p[4]); tk.last = StringToDouble(p[5]);
      tk.volume = (ulong)StringToInteger(p[6]); tk.volume_real = StringToDouble(p[7]); tk.flags = (uint)StringToInteger(p[8]);
      int m = ArraySize(out); ArrayResize(out, m + 1, 1024); out[m] = tk;
     }
   return true;
  }

// render pass with an unlimited row budget - the state machine of PMW_TickSessionVP.mq5 RenderPass / tsvp.Profile.render_pass without
// chart objects; returns the number of buckets drawn
int VpRender(CPmwTSVP &vp)
  {
   if(vp.state == VP_CLEAN) return 0;
   if(vp.state >= VP_FULL_REDRAW_REQUIRED)
     {
      for(int s = 0; s < vp.map.cap; s++) if(vp.map.used[s]) vp.map.dirty[s] = true;
      vp.state = VP_PARTIAL_UPDATE_PENDING;
     }
   int drawn = 0;
   for(int s = 0; s < vp.map.cap; s++) if(vp.map.used[s] && vp.map.dirty[s]) { vp.map.dirty[s] = false; drawn++; }
   vp.state = VP_CLEAN;
   return drawn;
  }

string TsvpRun(const string &rt[], const string &tk_rows[], const string name)
  {
   CPmwTSVP vp;
   if(!vp.Setup((int)StringToInteger(Field(rt, name + "_source")), (int)StringToInteger(Field(rt, name + "_bucket_mode")),
                (int)StringToInteger(Field(rt, name + "_bucket_ticks")), StringToDouble(Field(rt, name + "_atr_mult")),
                StringToDouble(Field(rt, name + "_atr")), StringToDouble(Field(rt, "tick")), StringToInteger(Field(rt, name + "_any_quote")) != 0,
                StringToInteger(Field(rt, "start_ms")), StringToInteger(Field(rt, "end_ms"))))
      return "null";
   int nreads = (int)StringToInteger(Field(rt, "n_reads"));
   string o = "{\"reads\":[";
   for(int r = 0; r < nreads; r++)
     {
      MqlTick tk[];
      long until = -1;
      if(!LoadRead(tk_rows, r, tk, until)) return "null";
      int added = vp.Ingest(tk, ArraySize(tk), until);
      string st = PmwVpStateName(vp.state);
      int drawn = VpRender(vp);
      o += (r ? "," : "") + StringFormat("[%d,\"%s\",%d,\"%s\"]", added, st, drawn, vp.Status());
     }
   long ks[];
   ArrayResize(ks, 0);
   for(int s = 0; s < vp.map.cap; s++) if(vp.map.used[s]) { int m = ArraySize(ks); ArrayResize(ks, m + 1, 256); ks[m] = vp.map.keys[s]; }
   ArraySort(ks);
   o += "],\"buckets\":[";
   for(int i = 0; i < ArraySize(ks); i++)
     {
      int s = vp.map.Slot(ks[i]);
      o += (i ? "," : "") + StringFormat("[%I64d,%s,%d]", ks[i], Num(vp.map.vals[s]), vp.map.cnts[s]);
     }
   string poc = vp.has_poc ? StringFormat("%I64d", vp.poc) : "null";
   o += StringFormat("],\"poc\":%s,\"max\":%s,\"total\":%s,\"counted\":%I64d,\"ignored\":[%I64d,%I64d,%I64d,%I64d],\"rehashes\":%d,\"size\":%s,\"status\":\"%s\"}",
                     poc, Num(vp.max_val), Num(vp.total), vp.counted, vp.ign_outside, vp.ign_not_eligible, vp.ign_invalid, vp.ign_duplicate,
                     vp.map.rehashes, Num(vp.size), vp.Status());
   return o;
  }

string TsvpJson()
  {
   string rt[], tk_rows[];
   if(!ReadLines("mm_ref_tsvp.csv", rt) || !ReadLines("mm_fixture_ticks.csv", tk_rows)) return "null";
   string names[];
   int nn = StringSplit(Field(rt, "configs"), ' ', names);
   string o = "{";
   for(int i = 0; i < nn; i++) o += (i ? "," : "") + "\"" + names[i] + "\":" + TsvpRun(rt, tk_rows, names[i]);
   return o + "}";
  }

//--- state stack (PMW_StateStack.mqh) against mm/event_engine.StateStack: push the fixture descriptors, correlate at the checkpoints
string StackRun(const string &rs[], const bool try_cl)
  {
   int S = (int)StringToInteger(Field(rs, "S")), D = (int)StringToInteger(Field(rs, "D")), np = (int)StringToInteger(Field(rs, "n_push"));
   string cks[];
   int nck = StringSplit(Field(rs, "checks"), ' ', cks);
   float q[];
   if(S < 1 || D < 1 || np < 1 || nck < 1 || !ParseFloats(Field(rs, "q"), D, q)) return "null";
   CPmwStateStack st;
   if(!st.Init(S, D, try_cl)) return "null";
   string o = "{\"checks\":[";
   int done = 0;
   for(int i = 1; i <= np; i++)
     {
      float d[];
      if(!ParseFloats(Field(rs, "p" + IntegerToString(i - 1)), D, d) || !st.Push(d)) return "null";
      bool check = false;
      for(int k = 0; k < nck; k++) if((int)StringToInteger(cks[k]) == i) check = true;
      if(!check) continue;
      float raw[], l2[];
      if(!st.Corr(q, false, raw) || !st.Corr(q, true, l2)) return "null";
      o += (done ? "," : "") + "[" + IntegerToString(i) + "," + FloatList(raw) + "," + FloatList(l2) + "," + (st.cl ? "null" : IntList(st.valid)) + "]";
      done++;
     }
   return o + "],\"backend\":\"" + st.backend_used + "\"}";
  }

string StackJson()
  {
   string rs[];
   if(!ReadLines("mm_ref_stack.csv", rs)) return "null";
   return "{\"cpu\":" + StackRun(rs, false) + ",\"opencl\":" + StackRun(rs, true) + "}";
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
   //--- GPR with the LML grid search (auto-tune, the indicator default InpAutoTune=true): window 60, horizon 3, full 7x5x9 grid
   int tprobes[5] = {300, 700, 900, 1200, 1499};
   js += ",\"gpr_tune\":[";
   for(int q = 0; q < 5; q++)
     {
      int T = tprobes[q];
      double x[], y[], mean = 0, lat = 0, obs = 0;
      CPmwGP gp;
      bool ok = PmwGprSamples(c, T, 60, 3, x, y) && gp.Refit(x, y, true, 4.0, 0.1, 0.01) && gp.Predict(MathLog(c[T] / c[T - 1]), mean, lat, obs);
      js += (q ? "," : "") + StringFormat("[%d,%s,%s,%s,%s,%s,%s,%s]", T, ok ? Num(gp.fit.ell) : "null", ok ? Num(gp.fit.sv) : "null",
                                          ok ? Num(gp.fit.nv) : "null", ok ? Num(mean) : "null", ok ? Num(lat) : "null", ok ? Num(obs) : "null",
                                          ok ? Num(gp.fit.lml) : "null");
     }
   js += "]";
   //--- HDC primitives: raw words (compared by the Python side) + the script's own comparison (informational)
   string rh[];
   bool hdc_ok = ReadLines("mm_ref_hdc.csv", rh);
   int D = hdc_ok ? (int)StringToInteger(Field(rh, "D")) : 0;
   CPmwHV a, b, cc, tie, r;
   bool parsed = hdc_ok && D > 0 && PmwHexToHV(Field(rh, "a"), D, a) && PmwHexToHV(Field(rh, "b"), D, b) && PmwHexToHV(Field(rh, "c"), D, cc)
                 && PmwHexToHV(Field(rh, "tie"), D, tie);
   bool ham = false, bind = false, perm = false, b3 = false, b2 = false;
   int ham_ab = -1;
   string bind_ab = "", perm_77 = "", bundle3 = "", bundle2 = "";
   if(parsed)
     {
      ham_ab = PmwHamming(a, b); ham = ham_ab == (int)StringToInteger(Field(rh, "hamming_ab"));
      PmwBind(a, b, r); bind_ab = HexOf(r); bind = bind_ab == Field(rh, "bind_ab");
      PmwPermute(a, 77, r); perm_77 = HexOf(r); perm = perm_77 == Field(rh, "perm_a_77");
      CPmwHV v3[3]; v3[0].Init(D); v3[1].Init(D); v3[2].Init(D);
      ArrayCopy(v3[0].w, a.w); ArrayCopy(v3[1].w, b.w); ArrayCopy(v3[2].w, cc.w);
      PmwBundle(v3, 3, tie, r); bundle3 = HexOf(r); b3 = bundle3 == Field(rh, "bundle_abc");
      PmwBundle(v3, 2, tie, r); bundle2 = HexOf(r); b2 = bundle2 == Field(rh, "bundle_ab_tie");
     }
   bool hdc_all = parsed && ham && bind && perm && b3 && b2;
   js += StringFormat(",\"hdc\":{\"parsed\":%s,\"hamming\":%s,\"bind\":%s,\"permute\":%s,\"bundle3\":%s,\"bundle2_tie\":%s,\"all_pass\":%s,",
                      JB(parsed), JB(ham), JB(bind), JB(perm), JB(b3), JB(b2), JB(hdc_all));
   js += StringFormat("\"hamming_ab\":%d,\"bind_ab\":\"%s\",\"perm_a_77\":\"%s\",\"bundle_abc\":\"%s\",\"bundle_ab_tie\":\"%s\"}", ham_ab, bind_ab, perm_77,
                      bundle3, bundle2);
   js += ",\"hdc_acc\":" + HdcAccJson();
   //--- Breakout zones, confirmation NONE (accepted events; kept for older references)
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
   //--- Breakout zones in all four confirmation modes (the indicator default is SESSION_VWAP)
   string bz_names[4] = {"SESSION_VWAP", "SMA", "SMMA", "NONE"};
   int bz_modes[4] = {PMW_CONF_SESSION_VWAP, PMW_CONF_SMA, PMW_CONF_SMMA, PMW_CONF_NONE};
   js += ",\"breakout_modes\":{";
   for(int bm = 0; bm < 4; bm++)
     {
      CPmwBreakout bzm;
      bzm.Setup(3, 3, 3, 0.5, 14, 0.35, 10.0, 0.10, 2, 600, 0.0, bz_modes[bm], 20, 20, 0, 0, 0.01, 300);
      for(int i = 0; i < n; i++) bzm.Update(t[i], o[i], h[i], l[i], c[i], tv[i]);
      js += (bm ? "," : "") + "\"" + bz_names[bm] + "\":[";
      int mm = 0;
      for(int k = 0; k < ArraySize(bzm.ev); k++)
        {
         if(!bzm.ev[k].accepted) continue;
         js += (mm ? "," : "") + StringFormat("[%I64d,\"%s\",%s,%s]", (long)bzm.ev[k].bar_t, bzm.ev[k].dir > 0 ? "BULLISH" : "BEARISH", Num(bzm.ev[k].lower),
                                              Num(bzm.ev[k].upper));
         mm++;
        }
      js += "]";
     }
   js += "}";
   //--- TSVP core and state stack
   js += ",\"tsvp\":" + TsvpJson();
   js += ",\"stack\":" + StackJson();
   js += StringFormat(",\"terminal\":{\"build\":%d,\"opencl\":%s}}", (int)TerminalInfoInteger(TERMINAL_BUILD),
                      TerminalInfoInteger(TERMINAL_OPENCL_SUPPORT) > 0 ? "true" : "false");
   int fh = FileOpen(InpDir + "\\PMW_MM_NATIVE.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(fh == INVALID_HANDLE) { PrintFormat("PMW_MM_SelfTest: cannot write output (err %d)", GetLastError()); return; }
   FileWriteString(fh, js);
   FileClose(fh);
   PrintFormat("PMW_MM_SelfTest: wrote %s\\PMW_MM_NATIVE.txt (bars %d, breakout events %d, hdc self-check %s) - run the Python parity for the verdict",
               InpDir, n, m, hdc_all ? "PASS" : "FAIL");
  }
