//+------------------------------------------------------------------+
//| PWM_FractalRegime.mq5 - bounded Katz fractal dimension regime      |
//| (PWM_KATZ_BOUNDED_v1, PMW-UPD-14). Closed bars only. Buffers:      |
//|  0 fd_smooth (line)  1 zone colour index (0 TREND, 1 NEUTRAL,      |
//|  2 CHOP - a colour, not a direction)  2 fd_bounded (DATA)          |
//|  3 quality code (0 OK, 1 CLIPPED, 2 SATURATED, 3 NO_MOTION,        |
//|  4 WARMING_UP). TREND carries no side. No trading functions.       |
//+------------------------------------------------------------------+
#property strict
#property indicator_separate_window
#property indicator_buffers 4
#property indicator_plots   3
#property indicator_type1   DRAW_COLOR_LINE
#property indicator_color1  clrDodgerBlue, clrSilver, clrOrange
#property indicator_width1  2
#property indicator_label1  "FD smooth"
#property indicator_type2   DRAW_NONE
#property indicator_label2  "FD bounded"
#property indicator_type3   DRAW_NONE
#property indicator_label3  "quality"
#property indicator_minimum 0.95
#property indicator_maximum 2.05
#include <PMW\PMW_ContextCore.mqh>

input int    InpN = 30;                 // window N (prices)
input int    InpS = 5;                  // EMA smoothing S
input double InpTrend = 1.40;           // <= TREND
input double InpChop = 1.65;            // >= CHOP
input ENUM_APPLIED_PRICE InpPrice = PRICE_CLOSE;
input double InpTolTicks = 0.5;         // flat tolerance in ticks

double Bs[], Bz[], Bb[], Bq[];
CPmwFractal g_f;
int g_done = -1;

double Px(const int i, const double &o[], const double &h[], const double &l[], const double &c[])
  {
   switch(InpPrice)
     {
      case PRICE_OPEN: return o[i];
      case PRICE_HIGH: return h[i];
      case PRICE_LOW: return l[i];
      case PRICE_MEDIAN: return (h[i] + l[i]) / 2;
      case PRICE_TYPICAL: return (h[i] + l[i] + c[i]) / 3;
      case PRICE_WEIGHTED: return (h[i] + l[i] + 2 * c[i]) / 4;
     }
   return c[i];
  }

int OnInit()
  {
   if(InpN < 3 || InpS < 1 || !(1 <= InpTrend && InpTrend < InpChop && InpChop <= 2)) return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0, Bs, INDICATOR_DATA); SetIndexBuffer(1, Bz, INDICATOR_COLOR_INDEX);
   SetIndexBuffer(2, Bb, INDICATOR_DATA); SetIndexBuffer(3, Bq, INDICATOR_DATA);
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE); PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, EMPTY_VALUE); PlotIndexSetDouble(2, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   IndicatorSetInteger(INDICATOR_LEVELS, 2);
   IndicatorSetDouble(INDICATOR_LEVELVALUE, 0, InpTrend); IndicatorSetDouble(INDICATOR_LEVELVALUE, 1, InpChop);
   IndicatorSetString(INDICATOR_SHORTNAME, StringFormat("PWM_FractalRegime(%d,%d)", InpN, InpS));
   IndicatorSetInteger(INDICATOR_DIGITS, 4);
   return INIT_SUCCEEDED;
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   ArraySetAsSeries(open, false); ArraySetAsSeries(high, false); ArraySetAsSeries(low, false); ArraySetAsSeries(close, false);
   ArraySetAsSeries(Bs, false); ArraySetAsSeries(Bz, false); ArraySetAsSeries(Bb, false); ArraySetAsSeries(Bq, false);
   if(prev_calculated == 0 || g_done >= rates_total - 1)
     {
      g_f.Init(InpN, InpS, InpTrend, InpChop, SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE), InpTolTicks); g_done = -1;
      ArrayInitialize(Bs, EMPTY_VALUE); ArrayInitialize(Bz, 1); ArrayInitialize(Bb, EMPTY_VALUE); ArrayInitialize(Bq, 4);
     }
   for(int i = g_done + 1; i <= rates_total - 2; i++)
     {
      bool sm = g_f.Update(Px(i, open, high, low, close));
      Bs[i] = sm ? g_f.ema : EMPTY_VALUE;
      Bz[i] = g_f.zone == 1 ? 0 : (g_f.zone == 3 ? 2 : 1);
      Bb[i] = g_f.has_bounded ? g_f.out_bounded : EMPTY_VALUE;
      Bq[i] = g_f.flat ? 3 : (!sm ? 4 : (g_f.saturated ? 2 : (g_f.clipped ? 1 : 0)));
      g_done = i;
     }
   Bs[rates_total - 1] = EMPTY_VALUE; Bb[rates_total - 1] = EMPTY_VALUE;
   return rates_total;
  }
