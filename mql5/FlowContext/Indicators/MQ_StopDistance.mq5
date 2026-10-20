//+------------------------------------------------------------------+
//| MQ_StopDistance.mq5 - MQ_STOP_DISTANCE_V1 (PMW-UPD-11 FF05)       |
//| Buffers (all in SYMBOL POINTS): 0 range=(H-L)/point (blue histo), |
//| 1 average SMA/EMA FULL_SEED (red), 2 suggested=avg*factor (green  |
//| dashed). Range excludes the gap to the previous close (not ATR).  |
//| Points are NOT a price: SL price = entry -/+ points*point rounded |
//| outward to trade tick size by the bot. No trading functions.      |
//+------------------------------------------------------------------+
#property strict
#property indicator_separate_window
#property indicator_buffers 3
#property indicator_plots   3
#property indicator_type1 DRAW_HISTOGRAM
#property indicator_color1 clrDodgerBlue
#property indicator_label1 "Range (points)"
#property indicator_type2 DRAW_LINE
#property indicator_color2 clrRed
#property indicator_label2 "Average (points)"
#property indicator_type3 DRAW_LINE
#property indicator_color3 clrLimeGreen
#property indicator_style3 STYLE_DASH
#property indicator_label3 "Suggested (points)"
#include <PMW\PMW_FlowMA.mqh>

input int    InpPeriod = 20;
input int    InpMethod = 1;      // 1=SMA 0=EMA
input double InpFactor = 1.5;

double R[], A[], G[];
double sS[], sW[];

int OnInit()
  {
   if(_Point <= 0 || InpFactor <= 0 || !MathIsValidNumber(InpFactor) || (InpMethod != 0 && InpMethod != 1)) return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0, R, INDICATOR_DATA); ArraySetAsSeries(R, false);
   SetIndexBuffer(1, A, INDICATOR_DATA); ArraySetAsSeries(A, false);
   SetIndexBuffer(2, G, INDICATOR_DATA); ArraySetAsSeries(G, false);
   for(int p = 0; p < 3; p++) PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   IndicatorSetString(INDICATOR_SHORTNAME, StringFormat("MQ_StopDistance(%d,%s,%.2f) points", FlowClampPeriod(InpPeriod), InpMethod == 1 ? "SMA" : "EMA", InpFactor));
   return INIT_SUCCEEDED;
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   int P = FlowClampPeriod(InpPeriod);
   ArrayResize(sS, rates_total); ArrayResize(sW, rates_total);
   int start = (prev_calculated <= 0) ? 0 : prev_calculated - 1;
   for(int i = start; i < rates_total; i++)
     {
      if(high[i] < low[i]) { R[i] = A[i] = G[i] = EMPTY_VALUE; continue; }
      R[i] = (high[i] - low[i]) / _Point;
      double a = MAStep(InpMethod, P, 1, R, i, A, sS, sW);          // FULL_SEED: EMPTY until P values, EMA seeded with SMA
      G[i] = (a == EMPTY_VALUE) ? EMPTY_VALUE : a * InpFactor;
     }
   return rates_total;
  }
