//+------------------------------------------------------------------+
//| PMW_AlignMeanCore.mqh - Align Mean core (PMW-MM-ALIGNMEAN-1),     |
//| port of backend/masterquo/mm/align_mean.compute. Shared by the    |
//| chart indicator PMW_AlignMean.mq5 and the native self-test        |
//| PMW_MM_SelfTest.mq5 (parity with the Python reference through the |
//| fixture mm_ref_align.csv - 1.46 arch I0501). Parameters instead   |
//| of inputs; closed bars only, arrays oldest -> newest, time[] =    |
//| bar OPEN time, tfs = bar seconds. EMPTY_VALUE = NOT_READY.        |
//| No trading functions.                                             |
//+------------------------------------------------------------------+
#ifndef PMW_ALIGNMEANCORE_MQH
#define PMW_ALIGNMEANCORE_MQH

enum ENUM_AM_MODE { AM_ROLLING_MEAN = 0, AM_FIXED_ANCHORED_MEAN = 1, AM_SESSION_MEAN = 2 };
enum ENUM_AM_SRC  { AM_CLOSE = 0, AM_TYPICAL = 1, AM_MEDIAN = 2, AM_WEIGHTED_CLOSE = 3 };
enum ENUM_AM_LB   { AM_LB_BARS = 0, AM_LB_ELAPSED_TIME = 1, AM_LB_SESSION = 2 };

double PmwAmPx(const int src, const double h, const double l, const double c)
  {
   switch(src)
     {
      case AM_CLOSE: return c;
      case AM_TYPICAL: return (h + l + c) / 3.0;
      case AM_MEDIAN: return (h + l) / 2.0;
     }
   return (h + l + 2.0 * c) / 4.0;
  }

// 1.46: a session owns the CLOSE times (start, start + 1 day] - like mm/align_mean.session_id (was MathFloor: a bar closing exactly
// at the session start opened the NEW session)
long PmwAmSid(const double t_close, const int start_min, const int tz_min) { return (long)MathCeil((t_close + tz_min * 60.0 - start_min * 60.0) / 86400.0) - 1; }

//--- mean of the closed bars 0..n-1 into out[0..n-1] (full recompute with prefix sums: the anchored / session rules stay exact)
void PmwAmCompute(const datetime &time[], const double &high[], const double &low[], const double &close[], const int n, const int tfs,
                  const int mode, const int src, const int lb, const int bars, const int seconds, const int start_min, const int tz_min,
                  double &out[])
  {
   ArrayResize(out, n);
   if(n < 1) return;
   double cs[]; ArrayResize(cs, n + 1); cs[0] = 0;
   for(int i = 0; i < n; i++) cs[i + 1] = cs[i] + PmwAmPx(src, high[i], low[i], close[i]);
   ArrayInitialize(out, EMPTY_VALUE);
   int a = 0;
   for(int i = 0; i < n; i++)
     {
      double tc = (double)time[i] + tfs;
      if(lb == AM_LB_BARS)
        {
         if(i + 1 >= bars) out[i] = (cs[i + 1] - cs[i + 1 - bars]) / bars;
        }
      else if(lb == AM_LB_ELAPSED_TIME)
        {
         while((double)time[a] + tfs <= tc - seconds) a++;
         double covered = tc - (double)time[a];
         if(a > 0 || covered >= seconds * 0.999) out[i] = (cs[i + 1] - cs[a]) / (i + 1 - a);   // else NOT_READY (missing history)
        }
      else
        {
         if(i > 0 && PmwAmSid(tc, start_min, tz_min) != PmwAmSid((double)time[i - 1] + tfs, start_min, tz_min)) a = i;
         out[i] = (cs[i + 1] - cs[a]) / (i + 1 - a);
        }
     }
   if(mode == AM_FIXED_ANCHORED_MEAN)
     {
      double cur = EMPTY_VALUE; long cur_sid = LONG_MIN;
      for(int i = 0; i < n; i++)
        {
         long s = PmwAmSid((double)time[i] + tfs, start_min, tz_min);
         if(s != cur_sid) { cur_sid = s; cur = EMPTY_VALUE; }
         if(cur == EMPTY_VALUE && out[i] != EMPTY_VALUE) cur = out[i];
         out[i] = cur;
        }
     }
  }

//--- Wilder ATR(period) of the latest closed bar n-1 (= mm/align_mean.atr_wilder at index n-1); EMPTY_VALUE when n < period
double PmwAmAtr(const double &high[], const double &low[], const double &close[], const int n, const int period)
  {
   if(period < 1 || n < period) return EMPTY_VALUE;
   double s = 0;
   for(int i = 0; i < period; i++) s += (i == 0) ? high[0] - low[0] : MathMax(high[i] - low[i], MathMax(MathAbs(high[i] - close[i - 1]), MathAbs(low[i] - close[i - 1])));
   double atr = s / period;
   for(int i = period; i < n; i++)
      atr = (atr * (period - 1) + MathMax(high[i] - low[i], MathMax(MathAbs(high[i] - close[i - 1]), MathAbs(low[i] - close[i - 1])))) / period;
   return atr;
  }
#endif
