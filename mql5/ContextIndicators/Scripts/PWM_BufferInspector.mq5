//+------------------------------------------------------------------+
//| PWM_BufferInspector.mq5 - one-off technical report of indicator    |
//| buffers on open charts (PMW-UPD-14 VS06). For every chart/window/  |
//| indicator instance: short name (duplicates flagged in Python),     |
//| buffer index scan InpFrom..InpTo with CopyBuffer at shift >= 1     |
//| (closed bars), READABLE / PENDING / UNREADABLE + a sample of       |
//| values (EMPTY_VALUE -> null) and bar times. Capability probe: the  |
//| PWM_BufferFixture with declared types. Output: envelope            |
//| pmw-bufreport-1 in MQL5\Files\PMW\PWM_BUFFER_REPORT.json, import   |
//| with `context-indicators buffers-verify` or the panel.            |
//| Heuristic types are hypotheses; a B-index is technical; colours   |
//| never become BUY/SELL. PLOT_SHIFT of foreign indicators cannot be |
//| read -> reported UNKNOWN. No trading, no chart modification.      |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs
#include <PMW\PMW_ContextCore.mqh>

input int  InpFrom = 0;              // first buffer index
input int  InpTo = 511;              // last buffer index (max 511)
input int  InpSample = 300;          // closed bars per buffer
input int  InpStopAfterFails = 0;    // 0 = full scan; N > 0 stops an instance after N consecutive UNREADABLE indices (PARTIAL_INDEX_RANGE)
input bool InpProbeFixture = true;   // capability probe with PWM_BufferFixture

string Arr(const double &v[], const int n)
  {
   string s = "[";
   for(int k = n - 1; k >= 0; k--)                                    // oldest -> newest (v is series)
     {
      if(k < n - 1) s += ",";
      s += (v[k] == EMPTY_VALUE || !MathIsValidNumber(v[k])) ? "null" : DoubleToString(v[k], 8);
     }
   return s + "]";
  }

string ScanHandle(const int h, const int from, const int to, int &lastIdx)
  {
   string out = "[";
   int fails = 0, cnt = 0, bc = BarsCalculated(h);
   lastIdx = from - 1;
   for(int b = from; b <= to; b++)
     {
      double v[]; ArraySetAsSeries(v, true); ResetLastError();
      int got = CopyBuffer(h, b, 1, InpSample, v);
      string st;
      if(got > 0) { st = "READABLE"; fails = 0; }
      else if(bc <= 0) st = "PENDING";
      else { st = "UNREADABLE"; fails++; }
      if(cnt > 0) out += ",";
      out += StringFormat("{\"index\":%d,\"status\":\"%s\",\"error\":%d,\"bars_calculated\":%d", b, st, GetLastError(), bc);
      if(got > 0) out += ",\"sample\":" + Arr(v, got);
      out += "}";
      cnt++; lastIdx = b;
      if(InpStopAfterFails > 0 && fails >= InpStopAfterFails) break;
     }
   return out + "]";
  }

void OnStart()
  {
   int from = MathMax(0, InpFrom), to = MathMin(511, InpTo);
   string inst = "[";
   int ni = 0, minLast = to;
   bool partial = false;
   for(long ch = ChartFirst(); ch >= 0; ch = ChartNext(ch))
     {
      int wins = (int)ChartGetInteger(ch, CHART_WINDOWS_TOTAL);
      for(int w = 0; w < wins; w++)
        {
         int tot = ChartIndicatorsTotal(ch, w);
         for(int k = 0; k < tot; k++)
           {
            string nm = ChartIndicatorName(ch, w, k);
            int h = ChartIndicatorGet(ch, w, nm);
            if(h == INVALID_HANDLE) continue;
            int last; string bufs = ScanHandle(h, from, to, last);
            if(last < to) { partial = true; minLast = MathMin(minLast, last); }
            if(ni > 0) inst += ",";
            inst += StringFormat("{\"chart_id\":%I64d,\"symbol\":\"%s\",\"tf\":\"%s\",\"window\":%d,\"short_name\":\"%s\",\"plot_shift\":\"UNKNOWN\",\"scanned_to\":%d,\"buffers\":%s}",
                                 ch, PmwJsonEsc(ChartSymbol(ch)), StringSubstr(EnumToString(ChartPeriod(ch)), 7), w, PmwJsonEsc(nm), last, bufs);
            IndicatorRelease(h);
            ni++;
           }
        }
     }
   inst += "]";
   string cap = "null";
   if(InpProbeFixture)
     {
      int fx = iCustom(_Symbol, _Period, "PMW\\PWM_BufferFixture", 0);
      if(fx != INVALID_HANDLE)
        {
         for(int t = 0; t < 40 && BarsCalculated(fx) <= 0; t++) Sleep(100);
         string names[] = {"DATA_DENSE", "COLOR_INDEX", "CALCULATIONS", "DRAW_NONE_ZEROS", "ARROW_EMPTY_VALUE", "ARROW_EMPTY_ZERO", "PLOT_SHIFT_3"};
         cap = "{";
         for(int b = 0; b < 7; b++)
           {
            double v[]; ArraySetAsSeries(v, true);
            int got = CopyBuffer(fx, b, 1, 50, v);
            cap += StringFormat("%s\"%s\":{\"index\":%d,\"read\":%s,\"copied\":%d,\"sample\":%s}", b ? "," : "", names[b], b, got > 0 ? "\"READABLE\"" : "\"UNREADABLE\"",
                                got, got > 0 ? Arr(v, got) : "[]");
           }
         cap += StringFormat(",\"bars_calculated\":%d}", BarsCalculated(fx));
         IndicatorRelease(fx);
        }
      else cap = "{\"status\":\"FIXTURE_NOT_INSTALLED\"}";
     }
   string body = StringFormat("{\"schema_version\":\"pmw-bufreport-1\",\"terminal_build\":%d,\"symbol\":\"%s\",\"tf\":\"%s\",\"created_utc\":%I64d,"
                              "\"scan_range\":{\"from\":%d,\"to\":%d},\"partial\":%s,\"sample_bars\":%d,\"capability\":%s,\"instances\":%s}",
                              (int)TerminalInfoInteger(TERMINAL_BUILD), _Symbol, StringSubstr(EnumToString(_Period), 7), (long)TimeGMT(), from,
                              partial ? minLast : to, partial ? "true" : "false", InpSample, cap, inst);
   bool ok = PmwWriteEnvelope("pmw-bufreport-1", body, "PMW\\PWM_BUFFER_REPORT.tmp", "PMW\\PWM_BUFFER_REPORT.json");
   Print("PWM_BufferInspector ", ok ? "OK" : "WRITE_FAILED", " instances=", ni, partial ? " (PARTIAL_INDEX_RANGE)" : "");
  }
