//+------------------------------------------------------------------+
//| PMW_MR2_Indicator.mq5 - native MiniRocket V2 SHADOW indicator    |
//| (PMW-UPD-09 R21). Same terminal, own chart context, NO order_send |
//| and no trading functions. Computes once per NEW CLOSED bar:       |
//| PRICE_PATH_ATR_V1 window (last 128 closes, ATR14 as in the bot),  |
//| transform + ridge head, writes PMW_MR2_RESULT.bin atomically into |
//| MQL5\Files\PMW (read-only importer in the bot: audit comparison  |
//| with Python, never overrides the main forecast or the Lock).      |
//| Bar times are broker wall time: clock_basis=BROKER_WALL_TIME.     |
//+------------------------------------------------------------------+
#property strict
#property indicator_separate_window
#property indicator_buffers 3
#property indicator_plots   3
#property indicator_label1  "UP-DOWN h3 (raw)"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrGold
#property indicator_label2  "UP-DOWN h5 (raw)"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrDodgerBlue
#property indicator_label3  "UP-DOWN h15 (raw)"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrSilver
#include <PMW\PMW_MR2_Format.mqh>

input string InpModel = "PMW\\model.bin";
input string InpOutDir = "PMW";

double B1[], B2[], B3[];
CMiniRocketV2 g_mr;
CRidgeHeadV2 g_head;
string g_sha = "";
bool g_ready = false;
ulong g_seq = 0;
datetime g_lastBar = 0;

int OnInit()
  {
   SetIndexBuffer(0, B1); SetIndexBuffer(1, B2); SetIndexBuffer(2, B3);
   string err;
   g_ready = MR2LoadModel(InpModel, false, g_mr, g_head, err, g_sha);
   if(!g_ready) Print("PMW_MR2_INDICATOR model not loaded: ", err, " (NOT_FITTED / INCOMPATIBLE) - indicator idle");
   g_seq = (ulong)TimeGMT();          // monotonic across restarts
   return INIT_SUCCEEDED;
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   if(!g_ready || rates_total < g_mr.m_L + 20) return rates_total;
   int last = rates_total - 2;                               // last CLOSED bar (rates_total-1 is forming); arrays are oldest->newest
   if(time[last] == g_lastBar) return rates_total;            // once per new closed bar, not per tick
   g_lastBar = time[last];
   double atr = MR2Atr(high, low, close, last, 14);
   float x[];
   if(atr == EMPTY_VALUE || !MR2PricePath(close, last, atr, SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE), g_mr.m_L, x)) return rates_total;
   double ppv[], sc[];
   if(g_mr.Transform(x, ppv) != MR2_OK) return rates_total;
   g_head.Raw(ppv, sc);
   if(g_head.m_H >= 1) B1[last] = sc[2] - sc[0];
   if(g_head.m_H >= 2) B2[last] = sc[4 + 2] - sc[4 + 0];
   if(g_head.m_H >= 3) B3[last] = sc[8 + 2] - sc[8 + 0];
   string err;
   g_seq++;
   if(!MR2WriteResult(InpOutDir, g_seq, (long)time[last], (long)TimeGMT(), g_sha, _Symbol, "M1", "BROKER_WALL_TIME", sc, err))
      Print("PMW_MR2_INDICATOR write failed: ", err);
   return rates_total;
  }
