//+------------------------------------------------------------------+
//| PWM_VAMD.mq5 - Volatility-Adjusted Momentum Decay line            |
//| (PWM_VAMD_ATR_WILDER_SMA_v1, PMW-UPD-14). Closed bars only: bar0  |
//| stays EMPTY (no forming preview in buffers). Buffers:             |
//|  0 vamd_y (line, colour by sign)  1 colour index  2 alpha (DATA,  |
//|  DRAW_NONE)  3 m target (CALCULATIONS). Sign = momentum, not a    |
//| probability; no trading functions.                                |
//+------------------------------------------------------------------+
#property strict
#property indicator_separate_window
#property indicator_buffers 4
#property indicator_plots   2
#property indicator_type1   DRAW_COLOR_LINE
#property indicator_color1  clrSeaGreen, clrTomato, clrGray
#property indicator_width1  2
#property indicator_label1  "VAMD y"
#property indicator_type2   DRAW_NONE
#property indicator_label2  "alpha"
#property indicator_level1  0.0
#include <PMW\PMW_ContextCore.mqh>

input int    InpP = 10;            // momentum lookback P
input int    InpA = 14;            // Wilder ATR period A
input int    InpB = 50;            // ATR baseline SMA B
input double InpBaseDecay = 0.15;  // base decay
input double InpMaxDecay  = 0.90;  // max decay (< 1)

double By[], Bc[], Ba[], Bm[];
CPmwVamd g_v;
int g_done = -1;                    // last processed closed bar index (as-series false)

int OnInit()
  {
   if(InpP < 1 || InpA < 1 || InpB < 1 || InpBaseDecay <= 0 || InpBaseDecay > InpMaxDecay || InpMaxDecay >= 1) return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0, By, INDICATOR_DATA); SetIndexBuffer(1, Bc, INDICATOR_COLOR_INDEX);
   SetIndexBuffer(2, Ba, INDICATOR_DATA); SetIndexBuffer(3, Bm, INDICATOR_CALCULATIONS);
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE); PlotIndexSetDouble(1, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   IndicatorSetString(INDICATOR_SHORTNAME, StringFormat("PWM_VAMD(%d,%d,%d,%.2f)", InpP, InpA, InpB, InpBaseDecay));
   IndicatorSetInteger(INDICATOR_DIGITS, 4);
   g_v.Init(InpP, InpA, InpB, InpBaseDecay, InpMaxDecay);
   return INIT_SUCCEEDED;
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   ArraySetAsSeries(high, false); ArraySetAsSeries(low, false); ArraySetAsSeries(close, false);
   ArraySetAsSeries(By, false); ArraySetAsSeries(Bc, false); ArraySetAsSeries(Ba, false); ArraySetAsSeries(Bm, false);
   if(prev_calculated == 0 || g_done >= rates_total - 1)       // first run or history rebuilt -> new segment from bar 0
     {
      g_v.Init(InpP, InpA, InpB, InpBaseDecay, InpMaxDecay); g_done = -1;
      ArrayInitialize(By, EMPTY_VALUE); ArrayInitialize(Bc, 2); ArrayInitialize(Ba, EMPTY_VALUE); ArrayInitialize(Bm, EMPTY_VALUE);
     }
   for(int i = g_done + 1; i <= rates_total - 2; i++)          // closed bars only
     {
      if(g_v.Update(high[i], low[i], close[i])) { By[i] = g_v.out_y; Bc[i] = g_v.out_y > 0 ? 0 : (g_v.out_y < 0 ? 1 : 2); Ba[i] = g_v.out_alpha; Bm[i] = g_v.out_m; }
      else { By[i] = EMPTY_VALUE; Ba[i] = EMPTY_VALUE; Bm[i] = EMPTY_VALUE; Bc[i] = 2; }
      g_done = i;
     }
   By[rates_total - 1] = EMPTY_VALUE; Ba[rates_total - 1] = EMPTY_VALUE;
   return rates_total;
  }
