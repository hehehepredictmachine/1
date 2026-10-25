//+------------------------------------------------------------------+
//| PMW_Kalman.mqh - scalar local-level Kalman filter + closed-bar   |
//| fast/slow crossover state machine (PMW-MM-KALMAN-1).              |
//| ONE authoritative implementation shared by PMW_KalmanCross.mq5    |
//| (indicator) and PMW_KalmanShadowEA.mq5 (non-trading EA).          |
//| Python reference: backend/masterquo/mm/kalman.py (same equations, |
//| same state machine; parity via Scripts/PMW_MM_SelfTest.mq5).      |
//|   predict: x- = x, P- = P + Q                                    |
//|   update : K = P-/(P-+R), x = x- + K(y - x-), P = (1-K) P-       |
//| Q, R are variances in price units^2. First valid close: x = y,   |
//| P = P0 (no measurement update on the same observation).          |
//| No order function is used or included in this file.              |
//+------------------------------------------------------------------+
#ifndef PMW_KALMAN_MQH
#define PMW_KALMAN_MQH

#define PMW_KX_VERSION "PMW-MM-KALMAN-1"

enum ENUM_PMW_KX_STATE { KX_INITIALIZING = 0, KX_INSUFFICIENT_HISTORY, KX_NEUTRAL, KX_BULLISH_CANDIDATE, KX_BEARISH_CANDIDATE,
                         KX_BULLISH_CONFIRMED, KX_BEARISH_CONFIRMED, KX_INVALID_INPUT };

string PmwKxStateName(const int s)
  {
   switch(s)
     {
      case KX_INITIALIZING: return "INITIALIZING";
      case KX_INSUFFICIENT_HISTORY: return "INSUFFICIENT_HISTORY";
      case KX_NEUTRAL: return "NEUTRAL";
      case KX_BULLISH_CANDIDATE: return "BULLISH_CANDIDATE";
      case KX_BEARISH_CANDIDATE: return "BEARISH_CANDIDATE";
      case KX_BULLISH_CONFIRMED: return "BULLISH_CONFIRMED";
      case KX_BEARISH_CONFIRMED: return "BEARISH_CONFIRMED";
     }
   return "INVALID_INPUT";
  }

double PmwKxSteadyGain(const double Q, const double R)
  {
   double pp = (Q + MathSqrt(Q * Q + 4.0 * Q * R)) / 2.0;
   return pp / (pp + R);
  }

class CPmwLocalLevel
  {
public:
   double            Q, R, P0, x, P, K, Ppred;
   bool              init;
   int               n;
   string            err;
   bool              Setup(const double q, const double r, const double p0)
     {
      if(!MathIsValidNumber(q) || !MathIsValidNumber(r) || !MathIsValidNumber(p0) || q < 0.0 || r <= 0.0 || p0 < 0.0)
         return false;
      Q = q; R = r; P0 = p0;
      Reset();
      return true;
     }
   void              Reset() { init = false; x = 0.0; P = 0.0; K = EMPTY_VALUE; Ppred = EMPTY_VALUE; n = 0; err = ""; }
   // returns 0 = invalid input (state untouched), 1 = initialised, 2 = updated, -1 = numerical fault
   int               Step(const double y)
     {
      if(!MathIsValidNumber(y) || y <= 0.0)
         return 0;
      if(!init)
        {
         x = y; P = P0; init = true; n = 1; K = EMPTY_VALUE;
         return 1;
        }
      double xp = x, pp = P + Q;
      double den = pp + R;
      double k = pp / den;
      double nx = xp + k * (y - xp);
      double np = (1.0 - k) * pp;
      if(!MathIsValidNumber(nx) || !MathIsValidNumber(np) || !MathIsValidNumber(k) || np < -1e-15 || k < 0.0 || k > 1.0)
        {
         err = StringFormat("NUMERICAL_FAULT x=%.17g P=%.17g K=%.17g", nx, np, k);
         return -1;
        }
      x = nx; P = MathMax(np, 0.0); K = k; Ppred = pp; n++;
      return 2;
     }
  };

class CPmwKalmanCross
  {
public:
   CPmwLocalLevel    fast, slow;
   int               confirm_bars, warmup_bars;
   double            tolerance;
   bool              emit_startup;
   datetime          last_bar;
   int               state, cand_dir, cand_n, accepted, bars;
   bool              baseline_set;
   datetime          last_event_time;
   int               last_event_dir;

   bool              Setup(const double qf, const double rf, const double qs, const double rs, const double p0, const int confirm, const double tol,
                           const int warmup, const bool startup)
     {
      if(confirm < 1 || confirm > 50 || tol < 0.0 || warmup < 1)
         return false;
      if(!fast.Setup(qf, rf, p0) || !slow.Setup(qs, rs, p0))
         return false;
      confirm_bars = confirm; tolerance = tol; warmup_bars = warmup; emit_startup = startup;
      Reset();
      return true;
     }
   void              Reset()
     {
      fast.Reset(); slow.Reset();
      last_bar = 0; state = KX_INITIALIZING; cand_dir = 0; cand_n = 0; accepted = 0; bars = 0; baseline_set = false;
      last_event_time = 0; last_event_dir = 0;
     }
   // process ONE closed bar; returns +1/-1 when a crossover event is accepted on this bar, 0 otherwise, -9 if the bar was already processed
   int               Update(const datetime bar_time, const double close)
     {
      if(last_bar != 0 && bar_time <= last_bar)
         return -9;
      last_bar = bar_time;
      int a = fast.Step(close), b = slow.Step(close);
      if(a <= 0 || b <= 0)
        {
         state = KX_INVALID_INPUT; cand_dir = 0; cand_n = 0;
         return 0;
        }
      bars++;
      if(bars < warmup_bars)
        {
         state = KX_INSUFFICIENT_HISTORY;
         return 0;
        }
      double diff = fast.x - slow.x;
      int d = (MathAbs(diff) <= tolerance) ? 0 : (diff > 0 ? 1 : -1);
      int ev = 0;
      if(d == 0)
        {
         cand_dir = 0; cand_n = 0;
         state = (accepted == 0) ? KX_NEUTRAL : (accepted > 0 ? KX_BULLISH_CONFIRMED : KX_BEARISH_CONFIRMED);
        }
      else
         if(d == accepted)
           {
            cand_dir = 0; cand_n = 0;
           }
         else
           {
            cand_n = (d == cand_dir) ? cand_n + 1 : 1;
            cand_dir = d;
            state = (d > 0) ? KX_BULLISH_CANDIDATE : KX_BEARISH_CANDIDATE;
            if(cand_n >= confirm_bars)
              {
               bool silent = (!baseline_set && !emit_startup);
               accepted = d; baseline_set = true;
               state = (d > 0) ? KX_BULLISH_CONFIRMED : KX_BEARISH_CONFIRMED;
               cand_dir = 0; cand_n = 0;
               if(!silent)
                 {
                  ev = d; last_event_time = bar_time; last_event_dir = d;
                 }
              }
           }
      if(accepted != 0 && d == accepted)
         state = (d > 0) ? KX_BULLISH_CONFIRMED : KX_BEARISH_CONFIRMED;
      return ev;
     }
  };
#endif
