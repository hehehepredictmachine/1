//+------------------------------------------------------------------+
//| PMW_TickSessionVP.mq5 - tick session volume profile (MT5 ticks).  |
//| Session = two draggable vertical lines (start <= t <= end, closed |
//| interval). Ticks come from CopyTicksRange (COPY_TICKS_ALL for the |
//| TICK ACTIVITY proxy, COPY_TICKS_TRADE for ACTUAL TRADE VOLUME);   |
//| overlapping inclusive reads are reconciled by PMW_TSVPCore.mqh.   |
//| Rendering runs in OnTimer with a row budget per pass:             |
//| FULL_REBUILD (session/bucket change) > FULL_REDRAW (new maximum)  |
//| > PARTIAL_UPDATE (dirty buckets only) > CLEAN.                    |
//| Bars are OBJ_RECTANGLE anchored in time/price, so scrolling and   |
//| zooming need no recomputation; width = value / max * InpWidthBars.|
//| The proxy is labelled as tick activity, never as traded volume.   |
//| No trading functions are used.                                    |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_plots 0
#include <PMW\PMW_TSVPCore.mqh>

input string             InpInstance = "1";                 // instance id (several profiles per chart)
input ENUM_PMW_VP_SOURCE InpSource = VP_TICK_ACTIVITY_PROXY;
input ENUM_PMW_VP_BUCKET InpBucketMode = VP_BUCKET_MANUAL;
input int                InpBucketTicks = 50;
input double             InpAtrMult = 0.25;
input int                InpAtrPeriod = 14;
input bool               InpProxyAnyQuote = false;          // false = count bid changes only
input int                InpSessionHours = 8;               // initial session length when the lines do not exist yet
input int                InpWidthBars = 40;
input int                InpRowsPerPass = 400;
input int                InpTimerMs = 250;
input int                InpChunkMinutes = 60;
input color              InpBarColor = C'60,90,140', InpPocColor = clrGold;

CPmwTSVP g_vp;
string   g_pfx, g_l0, g_l1;
int      g_atr = INVALID_HANDLE;
bool     g_need_rebuild = true, g_loaded = false;
string   g_status = "LOADING";

int OnInit()
  {
   if(InpBucketTicks < 1 || InpAtrMult <= 0 || InpWidthBars < 1 || InpRowsPerPass < 1 || InpTimerMs < 50 || InpChunkMinutes < 1) return INIT_PARAMETERS_INCORRECT;
   g_pfx = StringFormat("PMW_SVP_%I64d_%s_", ChartID(), InpInstance);
   g_l0 = g_pfx + "START"; g_l1 = g_pfx + "END";
   datetime now = TimeCurrent();
   if(ObjectFind(0, g_l0) < 0) { ObjectCreate(0, g_l0, OBJ_VLINE, 0, now - InpSessionHours * 3600, 0); }
   if(ObjectFind(0, g_l1) < 0) { ObjectCreate(0, g_l1, OBJ_VLINE, 0, now + PeriodSeconds() * 10, 0); }
   string ln[2]; ln[0] = g_l0; ln[1] = g_l1;
   for(int i = 0; i < 2; i++)
     {
      ObjectSetInteger(0, ln[i], OBJPROP_SELECTABLE, true); ObjectSetInteger(0, ln[i], OBJPROP_COLOR, clrSilver);
      ObjectSetInteger(0, ln[i], OBJPROP_STYLE, STYLE_DASH); ObjectSetString(0, ln[i], OBJPROP_TOOLTIP, i == 0 ? "TSVP session start" : "TSVP session end");
     }
   if(InpBucketMode == VP_BUCKET_ATR) g_atr = iATR(_Symbol, PERIOD_CURRENT, InpAtrPeriod);
   EventSetMillisecondTimer(InpTimerMs);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_atr != INVALID_HANDLE) IndicatorRelease(g_atr);
   if(reason == REASON_REMOVE) ObjectsDeleteAll(0, g_pfx);          // removal deletes everything this instance owns
   else { ObjectsDeleteAll(0, g_pfx + "B"); ObjectDelete(0, g_pfx + "POC"); ObjectDelete(0, g_pfx + "INFO"); }   // keep the user's lines
  }

void OnChartEvent(const int id, const long &lp, const double &dp, const string &sp)
  {
   if(id == CHARTEVENT_OBJECT_DRAG && (sp == g_l0 || sp == g_l1)) { g_need_rebuild = true; g_vp.Request(VP_FULL_REBUILD_REQUIRED); }
  }

bool Rebuild()
  {
   datetime a = (datetime)ObjectGetInteger(0, g_l0, OBJPROP_TIME), b = (datetime)ObjectGetInteger(0, g_l1, OBJPROP_TIME);
   if(a > b) { datetime x = a; a = b; b = x; }
   double atr = 0;
   if(InpBucketMode == VP_BUCKET_ATR)
     {
      double buf[];
      if(g_atr == INVALID_HANDLE || CopyBuffer(g_atr, 0, 1, 1, buf) != 1) { g_status = "ATR_UNAVAILABLE"; return false; }   // closed bar ATR
      atr = buf[0];
     }
   if(!g_vp.Setup(InpSource, InpBucketMode, InpBucketTicks, InpAtrMult, atr, SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE),
                  InpProxyAnyQuote, (long)a * 1000, (long)b * 1000 + 999)) { g_status = "SETUP_INVALID"; return false; }
   ObjectsDeleteAll(0, g_pfx + "B");
   long now_ms = (long)TimeCurrent() * 1000 + 999;
   MqlTick last; if(SymbolInfoTick(_Symbol, last)) now_ms = MathMax(now_ms, last.time_msc);
   long until = MathMin(now_ms, g_vp.end_ms), step = (long)InpChunkMinutes * 60000;
   uint flags = InpSource == VP_ACTUAL_TRADE_VOLUME ? COPY_TICKS_TRADE : COPY_TICKS_ALL;
   for(long f = g_vp.start_ms; f <= until; f += step)
     {
      long to = MathMin(f + step, until);
      MqlTick tk[];
      ResetLastError();
      int n = CopyTicksRange(_Symbol, tk, flags, (ulong)f, (ulong)to);
      if(n < 0) { g_status = StringFormat("TICKS_NOT_READY err=%d", GetLastError()); return false; }   // history still syncing, retry
      g_vp.Ingest(tk, n, to);
     }
   g_vp.Request(VP_FULL_REDRAW_REQUIRED);
   return true;
  }

void Poll()
  {
   long now_ms = (long)TimeCurrent() * 1000 + 999;
   MqlTick last; if(SymbolInfoTick(_Symbol, last)) now_ms = MathMax(now_ms, last.time_msc);
   long from = g_vp.tail_ms >= 0 ? g_vp.tail_ms : g_vp.start_ms, to = MathMin(now_ms, g_vp.end_ms);
   if(from > to) return;
   MqlTick tk[];
   int n = CopyTicksRange(_Symbol, tk, InpSource == VP_ACTUAL_TRADE_VOLUME ? COPY_TICKS_TRADE : COPY_TICKS_ALL, (ulong)from, (ulong)to);
   if(n > 0) g_vp.Ingest(tk, n, -1);                                 // the newest ms stays open: a later read may add ticks to it
  }

void DrawBucket(const int s, const datetime t0, const int span)
  {
   long k = g_vp.map.keys[s];
   string n = g_pfx + "B" + IntegerToString(k);
   double lo = g_vp.Lower(k), hi = lo + g_vp.size;
   datetime t1 = t0 + (datetime)MathMax(1.0, span * g_vp.map.vals[s] / g_vp.max_val);
   if(ObjectFind(0, n) < 0)
     {
      ObjectCreate(0, n, OBJ_RECTANGLE, 0, t0, hi, t1, lo);
      ObjectSetInteger(0, n, OBJPROP_FILL, true); ObjectSetInteger(0, n, OBJPROP_BACK, true); ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
     }
   else { ObjectMove(0, n, 0, t0, hi); ObjectMove(0, n, 1, t1, lo); }
   ObjectSetInteger(0, n, OBJPROP_COLOR, (g_vp.has_poc && k == g_vp.poc) ? InpPocColor : InpBarColor);
   g_vp.map.dirty[s] = false;
  }

void RenderPass()
  {
   if(g_vp.state == VP_CLEAN) return;
   if(g_vp.state >= VP_FULL_REDRAW_REQUIRED)                         // every bucket becomes dirty once; drawing then proceeds in budgeted passes
     {
      for(int s = 0; s < g_vp.map.cap; s++) if(g_vp.map.used[s]) g_vp.map.dirty[s] = true;
      g_vp.state = VP_PARTIAL_UPDATE_PENDING;
     }
   if(g_vp.max_val <= 0) { g_vp.state = VP_CLEAN; return; }
   datetime t0 = (datetime)(g_vp.start_ms / 1000);
   int span = InpWidthBars * PeriodSeconds(), drawn = 0, left = 0;
   for(int s = 0; s < g_vp.map.cap; s++)
     {
      if(!g_vp.map.used[s] || !g_vp.map.dirty[s]) continue;
      if(drawn >= InpRowsPerPass) { left++; continue; }
      DrawBucket(s, t0, span); drawn++;
     }
   if(left == 0) g_vp.state = VP_CLEAN;
   string pn = g_pfx + "POC";
   if(g_vp.has_poc)
     {
      double pc = g_vp.Lower(g_vp.poc) + g_vp.size / 2;
      if(ObjectFind(0, pn) < 0) { ObjectCreate(0, pn, OBJ_TREND, 0, t0, pc, t0 + span, pc); ObjectSetInteger(0, pn, OBJPROP_SELECTABLE, false); }
      else { ObjectMove(0, pn, 0, t0, pc); ObjectMove(0, pn, 1, t0 + span, pc); }
      ObjectSetInteger(0, pn, OBJPROP_COLOR, InpPocColor); ObjectSetInteger(0, pn, OBJPROP_RAY_RIGHT, false);
     }
  }

void Info()
  {
   string n = g_pfx + "INFO";
   if(ObjectFind(0, n) < 0) { ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0); ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
                              ObjectSetInteger(0, n, OBJPROP_ANCHOR, ANCHOR_RIGHT_UPPER); ObjectSetInteger(0, n, OBJPROP_XDISTANCE, 10);
                              ObjectSetInteger(0, n, OBJPROP_YDISTANCE, 20 + 16 * (int)StringToInteger(InpInstance)); }
   string lab = InpSource == VP_TICK_ACTIVITY_PROXY ? "TICK ACTIVITY (proxy, not volume)" : "ACTUAL TRADE VOLUME";
   string poc = g_vp.has_poc ? DoubleToString(g_vp.Lower(g_vp.poc) + g_vp.size / 2, _Digits) : "-";
   ObjectSetString(0, n, OBJPROP_TEXT, StringFormat("TSVP %s | %s | %s | POC %s | buckets %d | ticks %I64d | dup %I64d | %s", InpInstance, lab,
                   g_loaded ? g_vp.Status() : g_status, poc, g_vp.map.n, g_vp.counted, g_vp.ign_duplicate, PmwVpStateName(g_vp.state)));
   ObjectSetInteger(0, n, OBJPROP_COLOR, clrSilver);
  }

void OnTimer()
  {
   if(g_need_rebuild)
     {
      g_loaded = Rebuild();
      g_need_rebuild = !g_loaded;
     }
   else if(g_loaded) Poll();
   if(g_loaded) RenderPass();
   Info();
  }

int OnCalculate(const int rates_total, const int prev_calculated, const int begin, const double &price[]) { return rates_total; }
