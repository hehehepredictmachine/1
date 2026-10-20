//+------------------------------------------------------------------+
//| PWM_SMCStructure.mq5 - closed-bar pullback swings + BoS/CHoCH/IDM  |
//| structure with deferred sweep confirmation (PWM_PULLBACK_CLOSED_v1 |
//| + PWM_SMC_PULLBACK_BAR_ATOMIC_v1, PMW-UPD-14). bar0 is never        |
//| evaluated. Buffers (manifest):                                      |
//|  0 active_high   1 active_low  (DATA/DRAW_NONE, EMPTY while         |
//|                                  PENDING/UNSEEDED)                  |
//|  2 trend_code (-1 DOWN, 0 NONE, +1 UP)                              |
//|  3 event_mask (BOS_UP 1, BOS_DOWN 2, CHOCH_UP 4, CHOCH_DOWN 8,      |
//|    IDM 16, X_H 32, X_L 64, ANCHOR 128, STRUCTURE_H 256,             |
//|    STRUCTURE_L 512, FALLBACK 1024; 0 = no event; order/lineage      |
//|    come from the event export, not from the mask)                   |
//|  4 pullback_H_confirmed_here  5 pullback_L_confirmed_here           |
//|    (price on the CONFIRMING bar, not back-filled to the origin)     |
//|  6 structure_H_published_here 7 structure_L_published_here         |
//| Origin markers are drawn as objects (own prefix) = geometry only.   |
//| Rendering toggles never change buffers. No trading functions.       |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 8
#property indicator_plots   8
#property indicator_type1   DRAW_NONE
#property indicator_label1  "active_high"
#property indicator_type2   DRAW_NONE
#property indicator_label2  "active_low"
#property indicator_type3   DRAW_NONE
#property indicator_label3  "trend_code"
#property indicator_type4   DRAW_NONE
#property indicator_label4  "event_mask"
#property indicator_type5   DRAW_ARROW
#property indicator_color5  clrSilver
#property indicator_label5  "pullback H (confirmed here)"
#property indicator_type6   DRAW_ARROW
#property indicator_color6  clrSilver
#property indicator_label6  "pullback L (confirmed here)"
#property indicator_type7   DRAW_ARROW
#property indicator_color7  clrGold
#property indicator_width7  2
#property indicator_label7  "structure H (published here)"
#property indicator_type8   DRAW_ARROW
#property indicator_color8  clrGold
#property indicator_width8  2
#property indicator_label8  "structure L (published here)"
#include <PMW\PMW_ContextCore.mqh>

enum PmwBreak { PMW_WICK = 0, PMW_CLOSE = 1 };
input PmwBreak InpPullbackMode = PMW_WICK;
input PmwBreak InpIdmMode = PMW_WICK;
input bool     InpDetectSweeps = true;
input bool     InpDrawStructure = true;      // objects: structure zigzag (thick) between published points
input bool     InpDrawPullback = true;       // arrows of pullback confirmations (thin layer)
input int      InpMaxObjects = 300;
input color    InpColorStructure = clrGold;

double B0[], B1[], B2[], B3[], B4[], B5[], B6[], B7[];
CPmwSmc g_s;
int g_done = -1;
const string PFX = "PWMSMC_";

int OnInit()
  {
   SetIndexBuffer(0, B0, INDICATOR_DATA); SetIndexBuffer(1, B1, INDICATOR_DATA); SetIndexBuffer(2, B2, INDICATOR_DATA); SetIndexBuffer(3, B3, INDICATOR_DATA);
   SetIndexBuffer(4, B4, INDICATOR_DATA); SetIndexBuffer(5, B5, INDICATOR_DATA); SetIndexBuffer(6, B6, INDICATOR_DATA); SetIndexBuffer(7, B7, INDICATOR_DATA);
   for(int p = 0; p < 8; p++) PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   PlotIndexSetInteger(4, PLOT_ARROW, 159); PlotIndexSetInteger(5, PLOT_ARROW, 159); PlotIndexSetInteger(6, PLOT_ARROW, 234); PlotIndexSetInteger(7, PLOT_ARROW, 233);
   if(!InpDrawPullback) { PlotIndexSetInteger(4, PLOT_DRAW_TYPE, DRAW_NONE); PlotIndexSetInteger(5, PLOT_DRAW_TYPE, DRAW_NONE); }
   IndicatorSetString(INDICATOR_SHORTNAME, StringFormat("PWM_SMCStructure(pb=%s,idm=%s,sw=%d)", InpPullbackMode == PMW_WICK ? "WICK" : "CLOSE",
                      InpIdmMode == PMW_WICK ? "WICK" : "CLOSE", (int)InpDetectSweeps));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { ObjectsDeleteAll(0, PFX); }

void DrawChain(const datetime &time[])
  {
   if(!InpDrawStructure) return;
   ObjectsDeleteAll(0, PFX);
   int from = MathMax(1, g_s.nchain - InpMaxObjects);
   for(int k = from; k < g_s.nchain; k++)
     {
      PmwPoint a = g_s.pts[g_s.chain[k - 1]];
      PmwPoint b = g_s.pts[g_s.chain[k]];
      string nm = PFX + IntegerToString(k);
      ObjectCreate(0, nm, OBJ_TREND, 0, time[a.origin], a.price, time[b.origin], b.price);
      ObjectSetInteger(0, nm, OBJPROP_COLOR, InpColorStructure); ObjectSetInteger(0, nm, OBJPROP_WIDTH, 2);
      ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, false); ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
      ObjectSetString(0, nm, OBJPROP_TOOLTIP, StringFormat("%s %.5f origin=%s v%d (geometria bieżąca; czas publikacji w buforach 6/7)",
                      b.side == 1 ? "H" : "L", b.price, TimeToString(time[b.origin]), b.version));
     }
   ChartRedraw();
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   ArraySetAsSeries(time, false); ArraySetAsSeries(high, false); ArraySetAsSeries(low, false); ArraySetAsSeries(close, false);
   ArraySetAsSeries(B0, false); ArraySetAsSeries(B1, false); ArraySetAsSeries(B2, false); ArraySetAsSeries(B3, false);
   ArraySetAsSeries(B4, false); ArraySetAsSeries(B5, false); ArraySetAsSeries(B6, false); ArraySetAsSeries(B7, false);
   if(prev_calculated == 0 || g_done >= rates_total - 1)
     {
      g_s.Init(InpIdmMode == PMW_WICK, InpDetectSweeps, InpPullbackMode == PMW_WICK, SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE)); g_done = -1;
      ArrayInitialize(B0, EMPTY_VALUE); ArrayInitialize(B1, EMPTY_VALUE); ArrayInitialize(B2, 0); ArrayInitialize(B3, 0);
      ArrayInitialize(B4, EMPTY_VALUE); ArrayInitialize(B5, EMPTY_VALUE); ArrayInitialize(B6, EMPTY_VALUE); ArrayInitialize(B7, EMPTY_VALUE);
     }
   bool changed = false;
   for(int i = g_done + 1; i <= rates_total - 2; i++)
     {
      g_s.Update(high[i], low[i], close[i]);
      B0[i] = g_s.slotH.status == 1 ? g_s.slotH.level : EMPTY_VALUE;
      B1[i] = g_s.slotL.status == 1 ? g_s.slotL.level : EMPTY_VALUE;
      B2[i] = g_s.trend; B3[i] = g_s.mask;
      B4[i] = g_s.pb_h_set ? g_s.pb_h : EMPTY_VALUE; B5[i] = g_s.pb_l_set ? g_s.pb_l : EMPTY_VALUE;
      B6[i] = g_s.st_h_set ? g_s.st_h : EMPTY_VALUE; B7[i] = g_s.st_l_set ? g_s.st_l : EMPTY_VALUE;
      if(g_s.mask != 0) changed = true;
      g_done = i;
     }
   int f = rates_total - 1;                                            // bar0 (forming) is never evaluated
   B0[f] = EMPTY_VALUE; B1[f] = EMPTY_VALUE; B2[f] = 0; B3[f] = 0; B4[f] = EMPTY_VALUE; B5[f] = EMPTY_VALUE; B6[f] = EMPTY_VALUE; B7[f] = EMPTY_VALUE;
   if(changed) DrawChain(time);
   return rates_total;
  }
