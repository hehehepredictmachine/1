//+------------------------------------------------------------------+
//| PMW_KalmanCross.mq5 - fast/slow scalar Kalman estimates of the    |
//| CLOSED-bar close + confirmed crossover arrows (PMW-MM-KALMAN-1).  |
//| Buffers: 0 fast, 1 slow, 2 bullish arrow, 3 bearish arrow,        |
//| 4 K fast (data only), 5 K slow (data only).                       |
//| The forming bar (rates_total-1) is never fed to the filters, so   |
//| no marker can appear on an incomplete bar. History refresh or     |
//| parameter change -> chronological rebuild (prev_calculated == 0). |
//| Analytical only: no trading functions exist in this program.      |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 6
#property indicator_plots   4
#property indicator_label1  "Kalman fast"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrDeepSkyBlue
#property indicator_width1  2
#property indicator_label2  "Kalman slow"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrOrange
#property indicator_width2  2
#property indicator_label3  "Bullish crossover (confirmed)"
#property indicator_type3   DRAW_ARROW
#property indicator_color3  clrLime
#property indicator_label4  "Bearish crossover (confirmed)"
#property indicator_type4   DRAW_ARROW
#property indicator_color4  clrRed
#include <PMW\PMW_Kalman.mqh>

input double InpQFast = 1.000;      // Q fast (price^2)
input double InpQSlow = 0.005;      // Q slow (price^2)
input double InpR     = 0.200;      // R shared (price^2)
input double InpP0    = 1.0;        // initial posterior variance
input int    InpConfirmBars = 2;    // consecutive CLOSED bars required
input double InpTolerance = 0.0;    // |fast-slow| <= tol -> neutral
input int    InpWarmup = 20;        // bars before crossover logic

double BFast[], BSlow[], BBull[], BBear[], BKf[], BKs[];
CPmwKalmanCross g_kx;

int OnInit()
  {
   if(!g_kx.Setup(InpQFast, InpR, InpQSlow, InpR, InpP0, InpConfirmBars, InpTolerance, InpWarmup, false))
     {
      Print("PMW_KalmanCross: invalid parameters");
      return INIT_PARAMETERS_INCORRECT;
     }
   SetIndexBuffer(0, BFast, INDICATOR_DATA);
   SetIndexBuffer(1, BSlow, INDICATOR_DATA);
   SetIndexBuffer(2, BBull, INDICATOR_DATA);
   SetIndexBuffer(3, BBear, INDICATOR_DATA);
   SetIndexBuffer(4, BKf, INDICATOR_CALCULATIONS);
   SetIndexBuffer(5, BKs, INDICATOR_CALCULATIONS);
   PlotIndexSetInteger(2, PLOT_ARROW, 233);
   PlotIndexSetInteger(3, PLOT_ARROW, 234);
   for(int p = 0; p < 4; p++)
      PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   ArraySetAsSeries(BFast, false); ArraySetAsSeries(BSlow, false); ArraySetAsSeries(BBull, false); ArraySetAsSeries(BBear, false);
   ArraySetAsSeries(BKf, false); ArraySetAsSeries(BKs, false);
   IndicatorSetString(INDICATOR_SHORTNAME, StringFormat("PMW Kalman %.3f/%.3f R%.3f c%d", InpQFast, InpQSlow, InpR, InpConfirmBars));
   return INIT_SUCCEEDED;
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   ArraySetAsSeries(time, false); ArraySetAsSeries(close, false);     // explicit chronological indexing: 0 = oldest
   if(rates_total < 3)
      return 0;
   int start;
   if(prev_calculated <= 0 || prev_calculated > rates_total)
     {
      g_kx.Reset();                                                    // history (re)load -> rebuild from the oldest bar
      for(int i = 0; i < rates_total; i++)
        { BFast[i] = EMPTY_VALUE; BSlow[i] = EMPTY_VALUE; BBull[i] = EMPTY_VALUE; BBear[i] = EMPTY_VALUE; BKf[i] = EMPTY_VALUE; BKs[i] = EMPTY_VALUE; }
      start = 0;
     }
   else
      start = MathMax(0, prev_calculated - 2);
   for(int i = start; i < rates_total - 1; i++)                        // closed bars only
     {
      int ev = g_kx.Update(time[i], close[i]);
      if(ev == -9)
         continue;                                                     // already processed (repeated call on the same bar)
      BFast[i] = g_kx.fast.init ? g_kx.fast.x : EMPTY_VALUE;
      BSlow[i] = g_kx.slow.init ? g_kx.slow.x : EMPTY_VALUE;
      BKf[i] = g_kx.fast.K; BKs[i] = g_kx.slow.K;
      BBull[i] = (ev > 0) ? low[i] : EMPTY_VALUE;
      BBear[i] = (ev < 0) ? high[i] : EMPTY_VALUE;
     }
   int f = rates_total - 1;                                            // forming bar: never a value, never a marker
   BFast[f] = EMPTY_VALUE; BSlow[f] = EMPTY_VALUE; BBull[f] = EMPTY_VALUE; BBear[f] = EMPTY_VALUE;
   return rates_total;
  }
