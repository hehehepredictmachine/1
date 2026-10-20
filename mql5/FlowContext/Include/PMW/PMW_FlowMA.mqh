//+------------------------------------------------------------------+
//| PMW_FlowMA.mqh - shared MA kernel (PMW-UPD-11 FF03/FF05)          |
//| Methods 0=EMA 1=SMA 2=SMMA 3=LWMA; seed 0=PARTIAL_PREFIX_V1,      |
//| 1=FULL_SEED. Arrays oldest->newest (ArraySetAsSeries false).       |
//| MAStep computes out[i] from committed i-1 state only (S/W prefix  |
//| arrays), so recomputing the forming bar never double-updates.     |
//| Same contract as backend/masterquo/lab/flow_context/ma.py.        |
//+------------------------------------------------------------------+
#ifndef PMW_FLOW_MA_MQH
#define PMW_FLOW_MA_MQH

int FlowClampPeriod(const int p) { return (p <= 0) ? 1 : ((p > 10000) ? 10000 : p); }

// x[]: input; out[]: MA; S[]/W[]: running sum / weighted sum (size >= i+1). Returns EMPTY_VALUE when undefined (FULL_SEED warmup).
double MAStep(const int method, const int P, const int seed, const double &x[], const int i, double &out[], double &S[], double &W[])
  {
   int mOld = MathMin(P, i);                       // window size at i-1
   double Sprev = (i > 0) ? S[i - 1] : 0.0, Wprev = (i > 0) ? W[i - 1] : 0.0;
   double v;
   if(method == 1 || method == 3)
     {
      bool full = (mOld == P);
      double xold = full ? x[i - P] : 0.0;
      S[i] = Sprev - xold + x[i];
      int m = full ? P : mOld + 1;
      W[i] = full ? (Wprev - Sprev + P * x[i]) : (Wprev + m * x[i]);
      if(seed == 1 && m < P) { out[i] = EMPTY_VALUE; return EMPTY_VALUE; }
      v = (method == 1) ? S[i] / m : W[i] / (m * (m + 1) / 2.0);
      out[i] = v;
      return v;
     }
   double a = (method == 0) ? 2.0 / (P + 1) : 1.0 / P;
   if(i + 1 <= P)
     {
      S[i] = Sprev + x[i];
      W[i] = 0;
      double st = S[i] / (i + 1);
      // EMA/SMMA state is stored in W[] (prefix mean while i < P), so FULL_SEED can hide it without losing it
      if(seed == 1 && i + 1 < P) { out[i] = EMPTY_VALUE; W[i] = st; return EMPTY_VALUE; }
      out[i] = st; W[i] = st;
      return st;
     }
   S[i] = Sprev;
   double prev = W[i - 1];                         // committed EMA/SMMA state (also valid when FULL_SEED hid the prefix)
   v = prev + a * (x[i] - prev);
   W[i] = v;
   out[i] = v;
   return v;
  }
#endif
