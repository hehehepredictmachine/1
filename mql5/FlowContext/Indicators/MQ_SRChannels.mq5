//+------------------------------------------------------------------+
//| MQ_SRChannels.mq5 - MQ_SR_CHANNELS_V1 (PMW-UPD-11 FF04) own code  |
//| Pivots 10/10 (wick), eligible 290 bars after CONFIRMATION, width  |
//| cap 5% of the 300-bar range, score 20*pivots + touch bars over    |
//| loopback, greedy non-overlapping top 10 (draw 6). 6 DRAW_NONE     |
//| buffers = nearest support lo/hi, resistance lo/hi, inside lo/hi   |
//| relative to each CLOSED bar's own close (historical values are    |
//| computed as known then). Current map drawn as own-prefix objects; |
//| only own objects are removed. Score is geometry, not P(bounce).   |
//| No trading functions.                                              |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 6
#property indicator_plots   6
#property indicator_type1 DRAW_NONE
#property indicator_type2 DRAW_NONE
#property indicator_type3 DRAW_NONE
#property indicator_type4 DRAW_NONE
#property indicator_type5 DRAW_NONE
#property indicator_type6 DRAW_NONE

input int    InpDepth = 10;
input int    InpRetention = 290;
input int    InpLoopback = 300;
input double InpWidthPct = 5.0;
input int    InpMaxSelected = 10;
input int    InpVisible = 6;
input string InpPrefix = "MQSRC_";

double SupLo[], SupHi[], ResLo[], ResHi[], InLo[], InHi[];

struct Band { double lo; double hi; int npiv; int touch; int score; int lastConf; };

int OnInit()
  {
   if(InpDepth < 1 || InpDepth > 50 || InpLoopback < 100 || InpLoopback > 400 || InpWidthPct < 1 || InpWidthPct > 8) return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0, SupLo, INDICATOR_DATA); SetIndexBuffer(1, SupHi, INDICATOR_DATA);
   SetIndexBuffer(2, ResLo, INDICATOR_DATA); SetIndexBuffer(3, ResHi, INDICATOR_DATA);
   SetIndexBuffer(4, InLo, INDICATOR_DATA);  SetIndexBuffer(5, InHi, INDICATOR_DATA);
   ArraySetAsSeries(SupLo, false); ArraySetAsSeries(SupHi, false); ArraySetAsSeries(ResLo, false);
   ArraySetAsSeries(ResHi, false); ArraySetAsSeries(InLo, false); ArraySetAsSeries(InHi, false);
   for(int p = 0; p < 6; p++) PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { ObjectsDeleteAll(0, InpPrefix); }

bool IsPivotH(const double &h[], const int i, const int d)
  {
   for(int k = i - d; k < i; k++) if(!(h[i] > h[k])) return false;
   for(int k = i + 1; k <= i + d; k++) if(!(h[i] >= h[k])) return false;
   return true;
  }
bool IsPivotL(const double &l[], const int i, const int d)
  {
   for(int k = i - d; k < i; k++) if(!(l[i] < l[k])) return false;
   for(int k = i + 1; k <= i + d; k++) if(!(l[i] <= l[k])) return false;
   return true;
  }

// channels known at closed bar t (only bars <= t)
int Channels(const int t, const double &high[], const double &low[], Band &sel[])
  {
   ArrayResize(sel, 0);
   double price[]; int conf[]; int np = 0;
   int first = MathMax(InpDepth, t - InpRetention - InpDepth);
   for(int i = first; i <= t - InpDepth; i++)
     {
      int c = i + InpDepth;
      if(t - c > InpRetention) continue;
      if(IsPivotH(high, i, InpDepth)) { ArrayResize(price, np + 1); ArrayResize(conf, np + 1); price[np] = high[i]; conf[np] = c; np++; }
      if(IsPivotL(low, i, InpDepth))  { ArrayResize(price, np + 1); ArrayResize(conf, np + 1); price[np] = low[i];  conf[np] = c; np++; }
     }
   if(np == 0) return 0;
   int w0 = MathMax(0, t - 299);
   double hi = high[w0], lo = low[w0];
   for(int k = w0; k <= t; k++) { hi = MathMax(hi, high[k]); lo = MathMin(lo, low[k]); }
   double W = (hi - lo) * InpWidthPct / 100.0;
   Band cand[]; int nc = 0;
   for(int s = np - 1; s >= 0; s--)                      // newest first
     {
      Band b; b.lo = price[s]; b.hi = price[s]; b.npiv = 1; b.lastConf = conf[s];
      for(int j = np - 1; j >= 0; j--)
        {
         if(j == s) continue;
         if(MathMax(b.hi, price[j]) - MathMin(b.lo, price[j]) <= W + 1e-12)
           { b.lo = MathMin(b.lo, price[j]); b.hi = MathMax(b.hi, price[j]); b.npiv++; b.lastConf = MathMax(b.lastConf, conf[j]); }
        }
      bool dup = false;
      for(int q = 0; q < nc; q++) if(cand[q].lo == b.lo && cand[q].hi == b.hi && cand[q].npiv == b.npiv) dup = true;
      if(dup) continue;
      int l0 = MathMax(0, t - InpLoopback + 1);
      b.touch = 0;
      for(int k = l0; k <= t; k++) if((high[k] >= b.lo && high[k] <= b.hi) || (low[k] >= b.lo && low[k] <= b.hi)) b.touch++;
      b.score = 20 * b.npiv + b.touch;
      ArrayResize(cand, nc + 1); cand[nc++] = b;
     }
   // greedy: score desc, more pivots, newer, narrower
   bool used[]; ArrayResize(used, nc); ArrayInitialize(used, false);
   int ns = 0;
   while(ns < InpMaxSelected)
     {
      int best = -1;
      for(int q = 0; q < nc; q++)
        {
         if(used[q]) continue;
         bool ov = false;
         for(int z = 0; z < ns; z++) if(!(cand[q].hi < sel[z].lo || cand[q].lo > sel[z].hi)) { ov = true; break; }
         if(ov) { used[q] = true; continue; }
         if(best < 0 || cand[q].score > cand[best].score || (cand[q].score == cand[best].score && (cand[q].npiv > cand[best].npiv ||
            (cand[q].npiv == cand[best].npiv && (cand[q].lastConf > cand[best].lastConf || (cand[q].lastConf == cand[best].lastConf &&
            cand[q].hi - cand[q].lo < cand[best].hi - cand[best].lo)))))) best = q;
        }
      if(best < 0) break;
      used[best] = true;
      ArrayResize(sel, ns + 1); sel[ns++] = cand[best];
     }
   return ns;
  }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  {
   int last = rates_total - 2;                           // closed bars only
   int start = (prev_calculated <= 0) ? MathMax(2 * InpDepth + 1, last - 2000) : MathMax(prev_calculated - 2, 0);
   Band sel[];
   for(int t = start; t <= last; t++)
     {
      SupLo[t] = SupHi[t] = ResLo[t] = ResHi[t] = InLo[t] = InHi[t] = EMPTY_VALUE;
      int n = Channels(t, high, low, sel);
      double px = close[t], bs = DBL_MAX, br = DBL_MAX;
      for(int k = 0; k < n; k++)
        {
         if(sel[k].hi < px && px - sel[k].hi < bs) { bs = px - sel[k].hi; SupLo[t] = sel[k].lo; SupHi[t] = sel[k].hi; }
         if(sel[k].lo > px && sel[k].lo - px < br) { br = sel[k].lo - px; ResLo[t] = sel[k].lo; ResHi[t] = sel[k].hi; }
         if(sel[k].lo <= px && px <= sel[k].hi && InLo[t] == EMPTY_VALUE) { InLo[t] = sel[k].lo; InHi[t] = sel[k].hi; }
        }
      if(t == last)                                      // current map (full width, labelled) - own objects only
        {
         ObjectsDeleteAll(0, InpPrefix);
         for(int k = 0; k < MathMin(n, InpVisible); k++)
           {
            string nm = InpPrefix + IntegerToString(k);
            if(sel[k].hi - sel[k].lo < _Point)
               ObjectCreate(0, nm, OBJ_HLINE, 0, 0, sel[k].lo);
            else
               ObjectCreate(0, nm, OBJ_RECTANGLE, 0, time[MathMax(0, last - 1000)], sel[k].hi, time[last], sel[k].lo);
            ObjectSetInteger(0, nm, OBJPROP_BACK, true);
            ObjectSetInteger(0, nm, OBJPROP_FILL, true);
            ObjectSetInteger(0, nm, OBJPROP_COLOR, sel[k].lo > px ? clrMistyRose : (sel[k].hi < px ? clrHoneydew : clrLightYellow));
            ObjectSetString(0, nm, OBJPROP_TOOLTIP, StringFormat("bieżąca mapa: rank %d score %d (20x%d + %d)", k + 1, sel[k].score, sel[k].npiv, sel[k].touch));
           }
        }
     }
   return rates_total;
  }
