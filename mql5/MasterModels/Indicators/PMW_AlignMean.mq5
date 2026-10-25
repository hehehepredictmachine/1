//+------------------------------------------------------------------+
//| PMW_AlignMean.mq5 - one mean-reference definition for every chart |
//| (port of backend/masterquo/mm/align_mean.py, PMW-MM-ALIGNMEAN-1). |
//| Closed bars only (the forming bar gets EMPTY_VALUE). Modes:       |
//| ROLLING / FIXED_ANCHORED (first ready value of each session,      |
//| frozen until the next session) / SESSION; sources CLOSE, TYPICAL, |
//| MEDIAN, WEIGHTED_CLOSE; lookback BARS / ELAPSED_TIME / SESSION.   |
//| Put the same inputs on every chart -> the same definition.        |
//| Distance in points, % of mean and / ATR(n) of the same chart is   |
//| context only, not a signal and not a probability. The optional   |
//| P&L line reads the account (equity, open profit of this symbol)   |
//| and never changes anything.                                       |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 1
#property indicator_plots   1
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrGoldenrod
#property indicator_width1  2
#property indicator_label1  "PMW AlignMean"

enum ENUM_AM_MODE { AM_ROLLING_MEAN = 0, AM_FIXED_ANCHORED_MEAN = 1, AM_SESSION_MEAN = 2 };
enum ENUM_AM_SRC  { AM_CLOSE = 0, AM_TYPICAL = 1, AM_MEDIAN = 2, AM_WEIGHTED_CLOSE = 3 };
enum ENUM_AM_LB   { AM_LB_BARS = 0, AM_LB_ELAPSED_TIME = 1, AM_LB_SESSION = 2 };

input ENUM_AM_MODE InpMode = AM_ROLLING_MEAN;
input ENUM_AM_SRC  InpSource = AM_TYPICAL;
input ENUM_AM_LB   InpLookback = AM_LB_ELAPSED_TIME;
input int          InpBars = 48;
input int          InpSeconds = 14400;
input int          InpSessionStartMin = 0;
input int          InpSessionTzOffsetMin = 0;
input int          InpAtrPeriod = 14;
input bool         InpShowPnL = true;

double g_mean[];
string g_lab;

int OnInit()
  {
   if(InpMode == AM_SESSION_MEAN && InpLookback != AM_LB_SESSION) return INIT_PARAMETERS_INCORRECT;    // ALIGN_SESSION_MODE_REQUIRES_SESSION_LOOKBACK
   if(InpMode == AM_ROLLING_MEAN && InpLookback == AM_LB_SESSION) return INIT_PARAMETERS_INCORRECT;    // ALIGN_ROLLING_MODE_NEEDS_BARS_OR_TIME
   if(InpBars < 1 || InpSeconds < 60 || InpSessionStartMin < 0 || InpSessionStartMin >= 1440 || MathAbs(InpSessionTzOffsetMin) > 840 || InpAtrPeriod < 1)
      return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0, g_mean, INDICATOR_DATA);
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   g_lab = StringFormat("PMW_AM_%I64d_INFO", ChartID());
   return INIT_SUCCEEDED;
  }
void OnDeinit(const int reason) { ObjectDelete(0, g_lab); }

double Px(const double h, const double l, const double c)
  {
   switch(InpSource)
     {
      case AM_CLOSE: return c;
      case AM_TYPICAL: return (h + l + c) / 3.0;
      case AM_MEDIAN: return (h + l) / 2.0;
     }
   return (h + l + 2.0 * c) / 4.0;
  }
long Sid(const double t_close) { return (long)MathFloor((t_close + InpSessionTzOffsetMin * 60.0 - InpSessionStartMin * 60.0) / 86400.0); }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   ArraySetAsSeries(time, false); ArraySetAsSeries(high, false); ArraySetAsSeries(low, false); ArraySetAsSeries(close, false);
   ArraySetAsSeries(g_mean, false);
   int n = rates_total - 1, tfs = PeriodSeconds();                   // closed bars 0..n-1
   if(n < 1) return 0;
   // full recompute over closed bars (O(n) with prefix sums) keeps the anchored/session rules exact on history reloads
   double cs[]; ArrayResize(cs, n + 1); cs[0] = 0;
   for(int i = 0; i < n; i++) cs[i + 1] = cs[i] + Px(high[i], low[i], close[i]);
   double raw[]; ArrayResize(raw, n); ArrayInitialize(raw, EMPTY_VALUE);
   int a = 0;
   for(int i = 0; i < n; i++)
     {
      double tc = (double)time[i] + tfs;
      if(InpLookback == AM_LB_BARS)
        {
         if(i + 1 >= InpBars) raw[i] = (cs[i + 1] - cs[i + 1 - InpBars]) / InpBars;
        }
      else if(InpLookback == AM_LB_ELAPSED_TIME)
        {
         while((double)time[a] + tfs <= tc - InpSeconds) a++;
         double covered = tc - (double)time[a];
         if(a > 0 || covered >= InpSeconds * 0.999) raw[i] = (cs[i + 1] - cs[a]) / (i + 1 - a);   // else NOT_READY (missing history)
        }
      else
        {
         if(i > 0 && Sid(tc) != Sid((double)time[i - 1] + tfs)) a = i;
         raw[i] = (cs[i + 1] - cs[a]) / (i + 1 - a);
        }
     }
   if(InpMode == AM_FIXED_ANCHORED_MEAN)
     {
      double cur = EMPTY_VALUE; long cur_sid = LONG_MIN;
      for(int i = 0; i < n; i++)
        {
         long s = Sid((double)time[i] + tfs);
         if(s != cur_sid) { cur_sid = s; cur = EMPTY_VALUE; }
         if(cur == EMPTY_VALUE && raw[i] != EMPTY_VALUE) cur = raw[i];
         raw[i] = cur;
        }
     }
   for(int i = 0; i < n; i++) g_mean[i] = raw[i];
   g_mean[n] = EMPTY_VALUE;                                          // forming bar: never a value
   // latest closed bar context
   int k = n - 1;
   double atr = EMPTY_VALUE;
   if(n >= InpAtrPeriod)
     {
      double s = 0;
      for(int i = 0; i < InpAtrPeriod; i++) s += (i == 0) ? high[0] - low[0] : MathMax(high[i] - low[i], MathMax(MathAbs(high[i] - close[i - 1]), MathAbs(low[i] - close[i - 1])));
      atr = s / InpAtrPeriod;
      for(int i = InpAtrPeriod; i < n; i++)
         atr = (atr * (InpAtrPeriod - 1) + MathMax(high[i] - low[i], MathMax(MathAbs(high[i] - close[i - 1]), MathAbs(low[i] - close[i - 1])))) / InpAtrPeriod;
     }
   string txt;
   double m = g_mean[k];
   if(m == EMPTY_VALUE) txt = "ALIGN MEAN: NOT_READY";
   else if(m <= 0) txt = "ALIGN MEAN: INVALID_NORMALISATION";
   else
     {
      double d = close[k] - m;
      txt = StringFormat("ALIGN MEAN %s | dist %.0f pts | %.3f%% | %s ATR", DoubleToString(m, _Digits), d / _Point, 100.0 * d / m,
                         atr == EMPTY_VALUE || atr <= 0 ? "NOT_READY" : DoubleToString(d / atr, 2));
     }
   if(InpShowPnL)
     {
      double pr = 0;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         ulong tk = PositionGetTicket(i);
         if(tk > 0 && PositionGetString(POSITION_SYMBOL) == _Symbol) pr += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
        }
      txt += StringFormat(" | equity %.2f | open P&L %s %.2f (read-only)", AccountInfoDouble(ACCOUNT_EQUITY), _Symbol, pr);
     }
   if(ObjectFind(0, g_lab) < 0) { ObjectCreate(0, g_lab, OBJ_LABEL, 0, 0, 0); ObjectSetInteger(0, g_lab, OBJPROP_CORNER, CORNER_LEFT_LOWER);
                                  ObjectSetInteger(0, g_lab, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER); ObjectSetInteger(0, g_lab, OBJPROP_XDISTANCE, 10);
                                  ObjectSetInteger(0, g_lab, OBJPROP_YDISTANCE, 24); ObjectSetInteger(0, g_lab, OBJPROP_COLOR, clrGoldenrod); }
   ObjectSetString(0, g_lab, OBJPROP_TEXT, txt);
   return rates_total;
  }
