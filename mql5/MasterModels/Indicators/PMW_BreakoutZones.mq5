//+------------------------------------------------------------------+
//| PMW_BreakoutZones.mq5 - confirmed swing S/R zones, strict closed- |
//| bar breakouts with SESSION_VWAP (default) / SMA / SMMA / NONE      |
//| confirmation, blue (bullish) / red (bearish) rectangles + arrows, |
//| and a panel with ONLY the latest accepted breakout direction       |
//| (not a position, not an order). Object names are stable (prefix + |
//| zone id / event id): recalculation updates, never duplicates.     |
//| Transparency: OBJ_RECTANGLE has a single solid fill; this indicator|
//| draws it in the background (OBJPROP_BACK) with a muted colour so   |
//| candles stay readable - no native gradient is claimed.            |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_plots 0
#include <PMW\PMW_BreakoutCore.mqh>

input int    InpLeft = 3, InpRight = 3, InpMinSep = 3, InpAtr = 14, InpMinTouches = 2, InpExpireBars = 600;
input double InpProminenceATR = 0.5, InpToleranceATR = 0.35, InpToleranceFloorPts = 10, InpPadATR = 0.10, InpBufferATR = 0.0;
input ENUM_PMW_CONFIRM InpConfirmation = PMW_CONF_SESSION_VWAP;
input int    InpSMA = 20, InpSMMA = 20, InpSessionStartMin = 0, InpSessionOffsetMin = 0;
input int    InpMaxObjects = 300;
input color  InpBullColor = C'40,80,160', InpBearColor = C'150,40,50';

CPmwBreakout g_bz;
string g_pfx;
int g_drawn = 0;

int OnInit()
  {
   if(InpLeft < 1 || InpRight < 1 || InpMinTouches < 1 || InpAtr < 1) return INIT_PARAMETERS_INCORRECT;
   g_pfx = StringFormat("PMW_BZ_%I64d_", ChartID());
   g_bz.Setup(InpLeft, InpRight, InpMinSep, InpProminenceATR, InpAtr, InpToleranceATR, InpToleranceFloorPts, InpPadATR, InpMinTouches, InpExpireBars,
              InpBufferATR, InpConfirmation, InpSMA, InpSMMA, InpSessionStartMin, InpSessionOffsetMin, _Point, PeriodSeconds());
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { ObjectsDeleteAll(0, g_pfx); }      // only objects owned by this indicator

void DrawEvent(const PmwBzEvent &e)
  {
   if(!e.accepted || g_drawn >= InpMaxObjects) return;
   string rn = g_pfx + "Z" + e.id, an = g_pfx + "A" + e.id;
   color col = e.dir > 0 ? InpBullColor : InpBearColor;
   datetime t0 = e.bar_t - 20 * PeriodSeconds();
   if(ObjectFind(0, rn) < 0) { ObjectCreate(0, rn, OBJ_RECTANGLE, 0, t0, e.upper, e.bar_t, e.lower); g_drawn++; }
   ObjectSetInteger(0, rn, OBJPROP_COLOR, col); ObjectSetInteger(0, rn, OBJPROP_FILL, true); ObjectSetInteger(0, rn, OBJPROP_BACK, true);
   ObjectSetInteger(0, rn, OBJPROP_SELECTABLE, false);
   if(ObjectFind(0, an) < 0) ObjectCreate(0, an, e.dir > 0 ? OBJ_ARROW_UP : OBJ_ARROW_DOWN, 0, e.bar_t, e.dir > 0 ? e.lower : e.upper);
   ObjectSetInteger(0, an, OBJPROP_COLOR, e.dir > 0 ? clrDodgerBlue : clrTomato);
   ObjectSetInteger(0, an, OBJPROP_ANCHOR, e.dir > 0 ? ANCHOR_TOP : ANCHOR_BOTTOM);
  }

void Panel()
  {
   string n = g_pfx + "PANEL";
   if(ObjectFind(0, n) < 0) { ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0); ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
                              ObjectSetInteger(0, n, OBJPROP_XDISTANCE, 12); ObjectSetInteger(0, n, OBJPROP_YDISTANCE, 24); }
   string d = g_bz.latest_dir > 0 ? "BULLISH" : g_bz.latest_dir < 0 ? "BEARISH" : "NONE";
   ObjectSetString(0, n, OBJPROP_TEXT, "LATEST ACCEPTED BREAKOUT: " + d + (g_bz.latest_t > 0 ? "  " + TimeToString(g_bz.latest_t) : ""));
   ObjectSetInteger(0, n, OBJPROP_COLOR, g_bz.latest_dir > 0 ? clrDodgerBlue : g_bz.latest_dir < 0 ? clrTomato : clrSilver);
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   ArraySetAsSeries(time, false); ArraySetAsSeries(open, false); ArraySetAsSeries(high, false); ArraySetAsSeries(low, false);
   ArraySetAsSeries(close, false); ArraySetAsSeries(tick_volume, false);
   if(prev_calculated <= 0) { g_bz.Reset(); ObjectsDeleteAll(0, g_pfx); g_drawn = 0; }
   int ne0 = ArraySize(g_bz.ev);
   for(int i = 0; i < rates_total - 1; i++)                            // closed bars; Update() ignores already processed bars
      g_bz.Update(time[i], open[i], high[i], low[i], close[i], (double)tick_volume[i]);
   for(int k = ne0; k < ArraySize(g_bz.ev); k++) DrawEvent(g_bz.ev[k]);
   Panel();
   return rates_total;
  }
