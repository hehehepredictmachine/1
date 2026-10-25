//+------------------------------------------------------------------+
//| PMW_GPR_Forecast.mq5 - GP forecast of the h-bar log return drawn  |
//| as price bands (PMW-MM-GPR-1). Value computed at the last CLOSED  |
//| bar i is plotted h bars ahead with PLOT_SHIFT = InpHorizon.       |
//| forecast = base*exp(m); +-1/2 sigma = base*exp(m +- k*sqrt(obs)).|
//| Gaussian coverage is an assumption to calibrate (EA CSV), not a   |
//| guarantee. Refit only on a new closed bar; failed fit -> EMPTY.   |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 5
#property indicator_plots   5
#property indicator_label1 "GP forecast"
#property indicator_type1  DRAW_LINE
#property indicator_color1 clrGold
#property indicator_label2 "GP +1 sigma"
#property indicator_type2  DRAW_LINE
#property indicator_color2 clrSkyBlue
#property indicator_label3 "GP -1 sigma"
#property indicator_type3  DRAW_LINE
#property indicator_color3 clrSkyBlue
#property indicator_label4 "GP +2 sigma"
#property indicator_type4  DRAW_LINE
#property indicator_color4 clrSlateBlue
#property indicator_label5 "GP -2 sigma"
#property indicator_type5  DRAW_LINE
#property indicator_color5 clrSlateBlue
#include <PMW\PMW_GPR.mqh>

input int    InpWindow = 120;
input int    InpHorizon = 3;
input bool   InpAutoTune = true;
input int    InpRetuneEvery = 24;
input double InpEll = 4.0;
input double InpSignalVar = 0.1;
input double InpNoiseVar = 0.5;
input int    InpBackfill = 30;          // closed bars recomputed on load (each is a full refit)

double BF[], BU1[], BL1[], BU2[], BL2[];
CPmwGP g_gp;
datetime g_last = 0;
int g_since = 1000000;

int OnInit()
  {
   if(InpWindow < 10 || InpHorizon < 1 || InpRetuneEvery < 1 || InpEll <= 0 || InpSignalVar <= 0 || InpNoiseVar <= 0)
      return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0, BF); SetIndexBuffer(1, BU1); SetIndexBuffer(2, BL1); SetIndexBuffer(3, BU2); SetIndexBuffer(4, BL2);
   for(int p = 0; p < 5; p++) { PlotIndexSetInteger(p, PLOT_SHIFT, InpHorizon); PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE); }
   ArraySetAsSeries(BF, false); ArraySetAsSeries(BU1, false); ArraySetAsSeries(BL1, false); ArraySetAsSeries(BU2, false); ArraySetAsSeries(BL2, false);
   return INIT_SUCCEEDED;
  }

void Clear(const int i) { BF[i] = EMPTY_VALUE; BU1[i] = EMPTY_VALUE; BL1[i] = EMPTY_VALUE; BU2[i] = EMPTY_VALUE; BL2[i] = EMPTY_VALUE; }

void Compute(const double &close[], const int T)
  {
   double x[], y[];
   Clear(T);
   if(!PmwGprSamples(close, T, InpWindow, InpHorizon, x, y)) return;
   bool tune = InpAutoTune && g_since >= InpRetuneEvery;
   double e0 = g_gp.fit.valid ? g_gp.fit.ell : InpEll, s0 = g_gp.fit.valid ? g_gp.fit.sv : InpSignalVar, n0 = g_gp.fit.valid ? g_gp.fit.nv : InpNoiseVar;
   if(!InpAutoTune) { e0 = InpEll; s0 = InpSignalVar; n0 = InpNoiseVar; }
   if(!g_gp.Refit(x, y, tune, e0, s0, n0)) return;                  // failed fit -> EMPTY_VALUE (no stale band)
   g_since = tune ? 0 : g_since + 1;
   double m, lv, ov;
   if(!g_gp.Predict(MathLog(close[T] / close[T - 1]), m, lv, ov)) return;
   double sd = MathSqrt(ov), b = close[T];
   BF[T] = b * MathExp(m); BU1[T] = b * MathExp(m + sd); BL1[T] = b * MathExp(m - sd); BU2[T] = b * MathExp(m + 2 * sd); BL2[T] = b * MathExp(m - 2 * sd);
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   ArraySetAsSeries(time, false); ArraySetAsSeries(close, false);
   if(rates_total < InpWindow + InpHorizon + 5) return 0;
   int T = rates_total - 2;                                          // last CLOSED bar
   if(prev_calculated <= 0)
     {
      for(int i = 0; i < rates_total; i++) Clear(i);
      g_since = 1000000;
      for(int i = MathMax(InpWindow + InpHorizon + 2, T - InpBackfill + 1); i <= T; i++) Compute(close, i);
      g_last = time[T];
      return rates_total;
     }
   if(time[T] != g_last) { Compute(close, T); g_last = time[T]; }   // one refit per new closed bar, never per tick
   Clear(rates_total - 1);
   return rates_total;
  }
