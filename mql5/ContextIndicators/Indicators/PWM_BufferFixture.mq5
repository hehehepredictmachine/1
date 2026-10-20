//+------------------------------------------------------------------+
//| PWM_BufferFixture.mq5 - capability fixture for the Buffer          |
//| Inspector (PMW-UPD-14 VS06). Known, declared buffer types:         |
//|  0 dense DATA line        1 COLOR_INDEX of plot 0 (legal 0)        |
//|  2 CALCULATIONS           3 DATA/DRAW_NONE with valid zeros        |
//|  4 sparse arrows (EMPTY_VALUE between events)                     |
//|  5 arrows with declared custom empty 0 (PLOT_EMPTY_VALUE = 0)     |
//|  6 line with PLOT_SHIFT = +3                                       |
//| Readiness is delayed: values appear only after InpDelayCalls      |
//| OnCalculate calls (BarsCalculated stays low meanwhile). Values    |
//| are synthetic geometry for capability tests, never a signal.      |
//+------------------------------------------------------------------+
#property strict
#property indicator_separate_window
#property indicator_buffers 7
#property indicator_plots   5
#property indicator_type1   DRAW_COLOR_LINE
#property indicator_color1  clrSteelBlue, clrOrange
#property indicator_label1  "dense"
#property indicator_type2   DRAW_NONE
#property indicator_label2  "zeros_valid"
#property indicator_type3   DRAW_ARROW
#property indicator_label3  "sparse_empty_value"
#property indicator_type4   DRAW_ARROW
#property indicator_label4  "sparse_empty_zero"
#property indicator_type5   DRAW_LINE
#property indicator_label5  "shifted_+3"

input int InpDelayCalls = 3;

double D0[], C1[], K2[], Z3[], S4[], E5[], P6[];
int g_calls = 0;

int OnInit()
  {
   SetIndexBuffer(0, D0, INDICATOR_DATA); SetIndexBuffer(1, C1, INDICATOR_COLOR_INDEX); SetIndexBuffer(2, K2, INDICATOR_CALCULATIONS);
   SetIndexBuffer(3, Z3, INDICATOR_DATA); SetIndexBuffer(4, S4, INDICATOR_DATA); SetIndexBuffer(5, E5, INDICATOR_DATA); SetIndexBuffer(6, P6, INDICATOR_DATA);
   PlotIndexSetDouble(2, PLOT_EMPTY_VALUE, EMPTY_VALUE); PlotIndexSetDouble(3, PLOT_EMPTY_VALUE, 0.0);
   PlotIndexSetInteger(2, PLOT_ARROW, 159); PlotIndexSetInteger(3, PLOT_ARROW, 159);
   PlotIndexSetInteger(4, PLOT_SHIFT, 3);
   IndicatorSetString(INDICATOR_SHORTNAME, "PWM_BufferFixture");
   return INIT_SUCCEEDED;
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   ArraySetAsSeries(close, false);
   if(++g_calls <= InpDelayCalls) return 0;                         // delayed readiness: nothing calculated yet
   for(int i = (prev_calculated > 0 ? prev_calculated - 1 : 0); i < rates_total; i++)
     {
      D0[i] = close[i];
      C1[i] = (i > 0 && close[i] < close[i - 1]) ? 1 : 0;             // legal colour index 0
      K2[i] = i;
      Z3[i] = (i % 4 == 0) ? 0.0 : 1.0;                               // zeros are valid data here
      S4[i] = (i % 37 == 0) ? close[i] : EMPTY_VALUE;
      E5[i] = (i % 41 == 0) ? close[i] : 0.0;                          // declared custom empty 0
      P6[i] = close[i];
     }
   return rates_total;
  }
