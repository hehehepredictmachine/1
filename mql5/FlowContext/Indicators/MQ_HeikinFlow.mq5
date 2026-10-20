//+------------------------------------------------------------------+
//| MQ_HeikinFlow.mq5 - MQ_HEIKIN_FLOW_V1 (PMW-UPD-11 FF03), own code |
//| (QCL Heikin Flow original NOT read; source parity UNVERIFIED).    |
//| Stage1 MA1/P1 on raw O/H/L/C -> raw HA (recursion on raw HA) ->   |
//| Stage2 MA2/P2 on HA O/H/L/C. ABI: 24 buffers / 7 plots:           |
//|  0..3 bull, 4..7 bear, 8..11 neutral (DRAW_CANDLES, exactly one   |
//|  complete set per bar, others EMPTY - no ghost candles),          |
//|  12..15 canonical O/H/L/C (DRAW_NONE, CopyBuffer shift>=1),       |
//|  16..19 stage1 (CALCULATIONS), 20..23 raw HA (CALCULATIONS).      |
//| Each bar is computed from the committed state of bar i-1 only, so |
//| re-running the forming bar on every tick never double-updates.    |
//| Synthetic prices - never fill prices. No trading functions.       |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 24
#property indicator_plots   7
#property indicator_type1 DRAW_CANDLES
#property indicator_color1 clrSeaGreen
#property indicator_label1 "HF bull"
#property indicator_type2 DRAW_CANDLES
#property indicator_color2 clrFireBrick
#property indicator_label2 "HF bear"
#property indicator_type3 DRAW_CANDLES
#property indicator_color3 clrGray
#property indicator_label3 "HF neutral"
#property indicator_type4 DRAW_NONE
#property indicator_label4 "HF open"
#property indicator_type5 DRAW_NONE
#property indicator_label5 "HF high"
#property indicator_type6 DRAW_NONE
#property indicator_label6 "HF low"
#property indicator_type7 DRAW_NONE
#property indicator_label7 "HF close"
#include <PMW\PMW_FlowMA.mqh>

input int    InpMA1 = 0;        // 0=EMA 1=SMA 2=SMMA 3=LWMA
input int    InpP1 = 10;
input int    InpMA2 = 0;
input int    InpP2 = 5;
input double InpDeadbandPoints = 1.0;

double BuO[], BuH[], BuL[], BuC[], BeO[], BeH[], BeL[], BeC[], NeO[], NeH[], NeL[], NeC[];
double FO[], FH[], FL[], FC[], S1O[], S1H[], S1L[], S1C[], HAO[], HAH[], HAL[], HAC[];

struct MAState { double S[]; double W[]; };
MAState g_st[8];                // 0..3 stage1 O/H/L/C, 4..7 stage2 O/H/L/C
int g_p1, g_p2;

void Bind(const int idx, double &buf[], const ENUM_INDEXBUFFER_TYPE t)
  {
   SetIndexBuffer(idx, buf, t);
   ArraySetAsSeries(buf, false);
  }

int OnInit()
  {
   if(InpMA1 < 0 || InpMA1 > 3 || InpMA2 < 0 || InpMA2 > 3 || InpDeadbandPoints < 0) return INIT_PARAMETERS_INCORRECT;
   g_p1 = FlowClampPeriod(InpP1);
   g_p2 = FlowClampPeriod(InpP2);
   Bind(0, BuO, INDICATOR_DATA); Bind(1, BuH, INDICATOR_DATA); Bind(2, BuL, INDICATOR_DATA); Bind(3, BuC, INDICATOR_DATA);
   Bind(4, BeO, INDICATOR_DATA); Bind(5, BeH, INDICATOR_DATA); Bind(6, BeL, INDICATOR_DATA); Bind(7, BeC, INDICATOR_DATA);
   Bind(8, NeO, INDICATOR_DATA); Bind(9, NeH, INDICATOR_DATA); Bind(10, NeL, INDICATOR_DATA); Bind(11, NeC, INDICATOR_DATA);
   Bind(12, FO, INDICATOR_DATA); Bind(13, FH, INDICATOR_DATA); Bind(14, FL, INDICATOR_DATA); Bind(15, FC, INDICATOR_DATA);
   Bind(16, S1O, INDICATOR_CALCULATIONS); Bind(17, S1H, INDICATOR_CALCULATIONS); Bind(18, S1L, INDICATOR_CALCULATIONS); Bind(19, S1C, INDICATOR_CALCULATIONS);
   Bind(20, HAO, INDICATOR_CALCULATIONS); Bind(21, HAH, INDICATOR_CALCULATIONS); Bind(22, HAL, INDICATOR_CALCULATIONS); Bind(23, HAC, INDICATOR_CALCULATIONS);
   for(int p = 0; p < 7; p++) PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   for(int p = 3; p < 7; p++) PlotIndexSetInteger(p, PLOT_SHOW_DATA, false);
   IndicatorSetString(INDICATOR_SHORTNAME, StringFormat("MQ_HeikinFlow(%d/%d,%d/%d) synthetic", InpMA1, g_p1, InpMA2, g_p2));
   if(g_p1 != InpP1 || g_p2 != InpP2) Print("MQ_HeikinFlow CONFIG_CLAMPED requested ", InpP1, "/", InpP2, " effective ", g_p1, "/", g_p2);
   return INIT_SUCCEEDED;
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   if(rates_total < 2) return 0;
   for(int k = 0; k < 8; k++) { ArrayResize(g_st[k].S, rates_total); ArrayResize(g_st[k].W, rates_total); }
   int start = (prev_calculated <= 0) ? 0 : prev_calculated - 1;    // recompute the previously forming bar + new bars
   double db = InpDeadbandPoints * _Point;
   for(int i = start; i < rates_total; i++)
     {
      if(!(high[i] >= MathMax(open[i], close[i]) && low[i] <= MathMin(open[i], close[i]))) { FO[i] = FH[i] = FL[i] = FC[i] = EMPTY_VALUE; continue; }
      double o1 = MAStep(InpMA1, g_p1, 0, open, i, S1O, g_st[0].S, g_st[0].W);
      double h1 = MAStep(InpMA1, g_p1, 0, high, i, S1H, g_st[1].S, g_st[1].W);
      double l1 = MAStep(InpMA1, g_p1, 0, low, i, S1L, g_st[2].S, g_st[2].W);
      double c1 = MAStep(InpMA1, g_p1, 0, close, i, S1C, g_st[3].S, g_st[3].W);
      double hc = (o1 + h1 + l1 + c1) / 4.0;
      double ho = (i == 0) ? (o1 + c1) / 2.0 : (HAO[i - 1] + HAC[i - 1]) / 2.0;   // recursion on RAW HA open/close
      HAO[i] = ho; HAC[i] = hc;
      HAH[i] = MathMax(h1, MathMax(ho, hc));
      HAL[i] = MathMin(l1, MathMin(ho, hc));
      MAStep(InpMA2, g_p2, 0, HAO, i, FO, g_st[4].S, g_st[4].W);
      MAStep(InpMA2, g_p2, 0, HAH, i, FH, g_st[5].S, g_st[5].W);
      MAStep(InpMA2, g_p2, 0, HAL, i, FL, g_st[6].S, g_st[6].W);
      MAStep(InpMA2, g_p2, 0, HAC, i, FC, g_st[7].S, g_st[7].W);
      // clear all 12 display entries, then write exactly one complete set (no ghost candle on bull->bear change)
      BuO[i] = BuH[i] = BuL[i] = BuC[i] = BeO[i] = BeH[i] = BeL[i] = BeC[i] = NeO[i] = NeH[i] = NeL[i] = NeC[i] = EMPTY_VALUE;
      double body = FC[i] - FO[i];
      if(body > db)       { BuO[i] = FO[i]; BuH[i] = FH[i]; BuL[i] = FL[i]; BuC[i] = FC[i]; }
      else if(body < -db) { BeO[i] = FO[i]; BeH[i] = FH[i]; BeL[i] = FL[i]; BeC[i] = FC[i]; }
      else                { NeO[i] = FO[i]; NeH[i] = FH[i]; NeL[i] = FL[i]; NeC[i] = FC[i]; }
     }
   return rates_total;
  }
