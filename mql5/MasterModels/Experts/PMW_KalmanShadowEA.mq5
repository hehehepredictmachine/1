//+------------------------------------------------------------------+
//| PMW_KalmanShadowEA.mq5 - NON-TRADING shadow monitor of the same   |
//| Kalman crossover (shared PMW_Kalman.mqh). One CSV row per CLOSED  |
//| bar (not per tick) for calibration: MQL5\Files\PMW\<file>.        |
//| On start it rebuilds the recursive state from the last InpBars    |
//| closed bars (identical to the indicator), then updates exactly    |
//| once per newly closed bar. This program contains no OrderSend,    |
//| no CTrade and includes no trade library.                          |
//+------------------------------------------------------------------+
#property strict
#include <PMW\PMW_Kalman.mqh>

input double InpQFast = 1.000;
input double InpQSlow = 0.005;
input double InpR     = 0.200;
input double InpP0    = 1.0;
input int    InpConfirmBars = 2;
input double InpTolerance = 0.0;
input int    InpWarmup = 20;
input int    InpBars = 3000;                 // history used to rebuild the state on start
input bool   InpLogCsv = true;
input string InpCsvName = "PMW\\kalman_shadow.csv";

CPmwKalmanCross g_kx;
datetime g_last = 0;
int g_fh = INVALID_HANDLE;

void LogRow(const datetime t, const double c, const int ev)
  {
   if(g_fh == INVALID_HANDLE)
      return;
   FileWrite(g_fh, TimeToString(t, TIME_DATE | TIME_SECONDS), _Symbol, EnumToString((ENUM_TIMEFRAMES)_Period), DoubleToString(c, _Digits),
             DoubleToString(g_kx.fast.x, 10), DoubleToString(g_kx.slow.x, 10), DoubleToString(g_kx.fast.K, 10), DoubleToString(g_kx.slow.K, 10),
             DoubleToString(g_kx.fast.P, 12), DoubleToString(g_kx.slow.P, 12), DoubleToString(InpQFast, 6), DoubleToString(InpQSlow, 6),
             DoubleToString(InpR, 6), IntegerToString(g_kx.cand_n), ev > 0 ? "BULLISH" : ev < 0 ? "BEARISH" : "", PmwKxStateName(g_kx.state),
             "OK", PMW_KX_VERSION);
   FileFlush(g_fh);
  }

int OnInit()
  {
   if(!g_kx.Setup(InpQFast, InpR, InpQSlow, InpR, InpP0, InpConfirmBars, InpTolerance, InpWarmup, false))
      return INIT_PARAMETERS_INCORRECT;
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, _Period, 1, InpBars, r);                 // shift 1: closed bars only, oldest first
   if(n <= 0)
     {
      Print("PMW_KalmanShadowEA: history not available yet (", GetLastError(), ")");
      return INIT_SUCCEEDED;                                           // OnTick retries the rebuild
     }
   for(int i = 0; i < n; i++)
      g_kx.Update(r[i].time, r[i].close);
   g_last = r[n - 1].time;
   if(InpLogCsv)
     {
      FolderCreate("PMW");
      g_fh = FileOpen(InpCsvName, FILE_CSV | FILE_READ | FILE_WRITE | FILE_ANSI | FILE_SHARE_READ, ',');
      if(g_fh == INVALID_HANDLE)
         Print("PMW_KalmanShadowEA: CSV open failed ", GetLastError());
      else
        {
         if(FileSize(g_fh) == 0)
            FileWrite(g_fh, "time", "symbol", "tf", "close", "fast", "slow", "K_fast", "K_slow", "P_fast", "P_slow", "Q_fast", "Q_slow", "R",
                      "confirm_count", "event", "state", "quality", "version");
         FileSeek(g_fh, 0, SEEK_END);
        }
     }
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(g_fh != INVALID_HANDLE)
      FileClose(g_fh);
  }

void OnTick()
  {
   datetime t1 = iTime(_Symbol, _Period, 1);                          // last CLOSED bar
   if(t1 == 0 || t1 == g_last)
      return;                                                          // same bar: no second update
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, _Period, g_last == 0 ? (datetime)0 : g_last + 1, t1, r);
   if(n <= 0)
      return;
   for(int i = 0; i < n; i++)
     {
      if(r[i].time > t1)
         break;
      int ev = g_kx.Update(r[i].time, r[i].close);
      if(ev != -9)
         LogRow(r[i].time, r[i].close, ev);
     }
   g_last = t1;
   Comment(StringFormat("PMW Kalman SHADOW (no trading)\n%s  fast %.5f  slow %.5f\nlast event: %s %s", PmwKxStateName(g_kx.state), g_kx.fast.x,
                        g_kx.slow.x, g_kx.last_event_dir > 0 ? "BULLISH" : g_kx.last_event_dir < 0 ? "BEARISH" : "-",
                        g_kx.last_event_time > 0 ? TimeToString(g_kx.last_event_time) : ""));
  }
