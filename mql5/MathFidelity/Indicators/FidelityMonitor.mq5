//+------------------------------------------------------------------+
//| FidelityMonitor.mq5 - read-only panel for the Math Fidelity        |
//| benchmark. Reads benchmark_status.txt + benchmark_results.csv;     |
//| shows results only when the status is COMPLETE/INCOMPLETE AND the  |
//| results carry the same run_id (a newer RUNNING/FAILED attempt is   |
//| never masked by an older successful file). Never runs the          |
//| benchmark, never touches engines, owns only PMW_MFM_<chart>_*.     |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_plots 0
#include <PMW_MathFidelity\BenchmarkConfig.mqh>
#include <PMW_MathFidelity\WeightLoader.mqh>

input int   InpRefreshSec = 5;
input color InpText = clrSilver, InpGood = clrMediumSeaGreen, InpBad = clrTomato;

string g_pfx;

int OnInit()
  {
   g_pfx = StringFormat("PMW_MFM_%I64d_", ChartID());
   EventSetTimer(MathMax(1, InpRefreshSec));
   Refresh();
   return INIT_SUCCEEDED;
  }
void OnDeinit(const int reason) { EventKillTimer(); ObjectsDeleteAll(0, g_pfx); }
void OnTimer() { Refresh(); }
int OnCalculate(const int rates_total, const int prev_calculated, const int begin, const double &price[]) { return rates_total; }

void Line(const int k, const string txt, const color col)
  {
   string n = g_pfx + IntegerToString(k);
   if(ObjectFind(0, n) < 0)
     {
      ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER); ObjectSetInteger(0, n, OBJPROP_XDISTANCE, 10);
      ObjectSetInteger(0, n, OBJPROP_YDISTANCE, 20 + 15 * k); ObjectSetString(0, n, OBJPROP_FONT, "Consolas"); ObjectSetInteger(0, n, OBJPROP_FONTSIZE, 9);
      ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
     }
   ObjectSetString(0, n, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, n, OBJPROP_COLOR, col);
  }

string Kv(const string &rows[], const string key)
  {
   for(int i = 0; i < ArraySize(rows); i++) if(StringFind(rows[i], key + "=") == 0) return StringSubstr(rows[i], StringLen(key) + 1);
   return "";
  }
string F(const string s, const int digits) { if(s == "") return "-"; return DoubleToString(StringToDouble(s), digits); }
string E(const string s) { if(s == "") return "-"; return StringFormat("%.2e", StringToDouble(s)); }

void Refresh()
  {
   string st[], res[], err;
   int k = 0;
   Line(k++, "MATH FIDELITY BENCHMARK (diagnostic, read-only)", InpText);
   if(!BenchReadLines(BenchPath(BENCH_STATUS_FILE), st, err)) { Line(k++, "RESULTS MISSING - run MathFidelityBenchmark_EA", InpBad); Clear(k); return; }
   string run = Kv(st, "run_id"), state = Kv(st, "state");
   Line(k++, StringFormat("run %s | state %s | %s", run, state, Kv(st, "updated")), state == "COMPLETE" ? InpGood : InpBad);
   if(state != "COMPLETE" && state != "INCOMPLETE") { Line(k++, "no current results: " + Kv(st, "message"), InpBad); Clear(k); return; }
   if(!BenchReadLines(BenchPath(BENCH_RESULTS_FILE), res, err) || ArraySize(res) < 2) { Line(k++, "RESULTS MALFORMED/MISSING: " + err, InpBad); Clear(k); return; }
   string hdr[]; int nh = StringSplit(res[0], ',', hdr);
   int ci[24]; string want[24] = {"engine", "run_id", "mean_us", "median_us", "p95_us", "p99_us", "latency_samples", "abs_err_mean", "abs_err_max",
                                  "rel_err_max_pct", "failed_calls", "numeric_status", "engine_status", "zero_us_samples", "batch_mean_us", "vectors_checked",
                                  "vectors_passed", "", "", "", "", "", "", ""};
   for(int w = 0; w < 17; w++) { ci[w] = -1; for(int h = 0; h < nh; h++) if(hdr[h] == want[w]) ci[w] = h; if(ci[w] < 0) { Line(k++, "RESULTS MALFORMED: missing column " + want[w], InpBad); Clear(k); return; } }
   Line(k++, "engine                 numeric            mean/med us      p95/p99 us      abs err mean/max    rel max %  n      zero  failed", InpText);
   for(int r = 1; r < ArraySize(res); r++)
     {
      string p[];
      if(StringSplit(res[r], ',', p) != nh) { Line(k++, "RESULTS MALFORMED: row width", InpBad); continue; }
      if(p[ci[1]] != run) { Line(k++, StringFormat("%s: STALE (run %s != status %s)", p[ci[0]], p[ci[1]], run), InpBad); continue; }
      bool good = p[ci[12]] == "OK" && p[ci[11]] == "WITHIN_TOLERANCE";
      Line(k++, StringFormat("%-22s %-18s %6s/%-6s  %6s/%-6s  %9s/%-9s  %9s  %-6s %-5s %s", p[ci[0]], p[ci[11]], F(p[ci[2]], 3), F(p[ci[3]], 3), F(p[ci[4]], 2),
                             F(p[ci[5]], 2), E(p[ci[7]]), E(p[ci[8]]), E(p[ci[9]]), p[ci[6]], p[ci[13]], p[ci[10]]), good ? InpGood : InpBad);
     }
   Line(k++, "latency = this machine/terminal only; ONNX path is float32 by design; no trading", InpText);
   Clear(k);
  }
void Clear(const int from) { for(int k = from; k < 40; k++) ObjectDelete(0, g_pfx + IntegerToString(k)); }
