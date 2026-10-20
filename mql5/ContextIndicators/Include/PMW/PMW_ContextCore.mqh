//+------------------------------------------------------------------+
//| PMW_ContextCore.mqh - PMW-UPD-14 native cores, step-for-step port  |
//| of backend/masterquo/lab/context_ind/{vamd,fractal,smc}.py:        |
//|   PWM_VAMD_ATR_WILDER_SMA_v1, PWM_KATZ_BOUNDED_v1,                  |
//|   PWM_PULLBACK_CLOSED_v1, PWM_SMC_PULLBACK_BAR_ATOMIC_v1.           |
//| Closed bars only, oldest -> newest, one Update per bar. Sums run    |
//| oldest -> newest like the Python reference (parity on the same      |
//| OHLC is checked by PWM_ContextSelfTest + context-indicators         |
//| native-parity). No trading functions anywhere.                     |
//+------------------------------------------------------------------+
#ifndef PMW_CONTEXT_CORE_MQH
#define PMW_CONTEXT_CORE_MQH

#define PMW_EV_BOS_UP      1
#define PMW_EV_BOS_DOWN    2
#define PMW_EV_CHOCH_UP    4
#define PMW_EV_CHOCH_DOWN  8
#define PMW_EV_IDM         16
#define PMW_EV_X_H         32
#define PMW_EV_X_L         64
#define PMW_EV_ANCHOR      128
#define PMW_EV_STRUCT_H    256
#define PMW_EV_STRUCT_L    512
#define PMW_EV_FALLBACK    1024

//==================================================================== VAMD
class CPmwVamd
  {
public:
   int      P, A, B;
   double   base_decay, max_decay;
   double   closes[];   int nc;          // ring of P+1 closes (stored oldest->newest by shifting)
   double   trseed[];   int nseed;
   double   atrs[];     int natr;        // last B ATR values oldest->newest
   double   atr;        bool has_atr;
   double   y;          bool has_y;
   double   prev_close; bool has_prev;
   // last result
   bool     ready;
   double   out_y, out_m, out_alpha, out_ratio, out_atr, out_base;

   void Init(const int p, const int a, const int b, const double bd, const double md)
     {
      P = p; A = a; B = b; base_decay = bd; max_decay = md;
      ArrayResize(closes, P + 1); ArrayResize(trseed, A); ArrayResize(atrs, B);
      Reset();
     }
   void Reset() { nc = 0; nseed = 0; natr = 0; has_atr = false; has_y = false; has_prev = false; ready = false; }

   bool Update(const double h, const double lo, const double c)
     {
      ready = false;
      if(!MathIsValidNumber(h) || !MathIsValidNumber(lo) || !MathIsValidNumber(c) || h < lo) return false;
      double tr = h - lo;
      if(has_prev) tr = MathMax(h - lo, MathMax(MathAbs(h - prev_close), MathAbs(lo - prev_close)));
      prev_close = c; has_prev = true;
      if(nc < P + 1) closes[nc++] = c;
      else { for(int k = 0; k < P; k++) closes[k] = closes[k + 1]; closes[P] = c; }
      if(!has_atr)
        {
         trseed[nseed++] = tr;
         if(nseed == A) { double s = 0; for(int k = 0; k < A; k++) s += trseed[k]; atr = s / A; has_atr = true; }
        }
      else atr = (atr * (A - 1) + tr) / A;
      out_atr = atr;
      if(!has_atr) return false;
      if(natr < B) atrs[natr++] = atr;
      else { for(int k = 0; k < B - 1; k++) atrs[k] = atrs[k + 1]; atrs[B - 1] = atr; }
      if(natr < B || nc < P + 1) return false;
      double s = 0; for(int k = 0; k < B; k++) s += atrs[k];
      double base = s / B;
      if(atr <= 0 || base <= 0) return false;                 // FLAT_NO_MOTION: no value, never an epsilon
      double raw = closes[P] - closes[0];
      double m = raw / atr, r = atr / base;
      double a = MathMin(max_decay, MathMax(0.0, base_decay * r));
      if(!has_y) { y = m; has_y = true; } else y = y + a * (m - y);
      ready = true; out_y = y; out_m = m; out_alpha = a; out_ratio = r; out_base = base;
      return true;
     }
  };

//==================================================================== bounded Katz FD
class CPmwFractal
  {
public:
   int      N, S;
   double   th_trend, th_chop, tol;
   double   win[];  int nw;
   double   seed[]; int ns;
   double   ema;    bool has_ema;
   // last result
   bool     has_bounded, has_raw, saturated, clipped, flat;
   double   out_raw, out_bounded;
   int      zone;                                  // 0 none / NO_MOTION, 1 TREND, 2 NEUTRAL, 3 CHOP

   void Init(const int n, const int s, const double trend, const double chop, const double tick, const double tol_ticks)
     {
      N = n; S = s; th_trend = trend; th_chop = chop; tol = tol_ticks * tick;
      ArrayResize(win, N); ArrayResize(seed, S); nw = 0; ns = 0; has_ema = false;
     }
   int Zone(const double v) const { return v <= th_trend ? 1 : (v >= th_chop ? 3 : 2); }

   void Katz()
     {
      int n = N - 1;
      double L = 0, d = 0;
      for(int j = 1; j < N; j++) L += MathAbs(win[j] - win[j - 1]);
      for(int j = 0; j < N; j++) d = MathMax(d, MathAbs(win[j] - win[0]));
      has_raw = false; has_bounded = false; saturated = false; clipped = false; flat = false;
      if(L <= tol || d <= tol) { flat = true; return; }
      double den = MathLog(n) + MathLog(d / L);
      if(den <= 1e-12) { has_bounded = true; out_bounded = 2.0; saturated = true; return; }
      double raw = MathLog(n) / den;
      if(!MathIsValidNumber(raw)) { has_bounded = true; out_bounded = 2.0; saturated = true; return; }
      has_raw = true; out_raw = raw;
      out_bounded = MathMin(2.0, MathMax(1.0, raw)); has_bounded = true; clipped = (out_bounded != raw);
     }

   // returns true when a smoothed value exists
   bool Update(const double p)
     {
      zone = 0; has_bounded = false; has_raw = false;
      if(!MathIsValidNumber(p)) return false;
      if(nw < N) win[nw++] = p; else { for(int k = 0; k < N - 1; k++) win[k] = win[k + 1]; win[N - 1] = p; }
      if(nw < N) return false;
      Katz();
      if(!has_bounded) { ns = 0; has_ema = false; zone = 0; return false; }      // flat: reset smoothing segment
      if(!has_ema)
        {
         seed[ns++] = out_bounded;
         if(ns == S) { double s = 0; for(int k = 0; k < S; k++) s += seed[k]; ema = s / S; has_ema = true; }
        }
      else ema = ema + (2.0 / (S + 1)) * (out_bounded - ema);
      if(has_ema) zone = Zone(ema);
      return has_ema;
     }
  };

//==================================================================== pullback swings
struct PmwSwing { int side; double price; int origin; int confirming; int seq; };   // side +1 = H, -1 = L

class CPmwPullback
  {
public:
   bool     wick;            // true WICK, false CLOSE
   double   tick;
   int      side;            // 0 none, +1 HIGH leg, -1 LOW leg
   double   ext, ref; int ext_bar, ref_bar;
   int      last_bar;
   PmwSwing ledger[]; int nled;

   void Init(const bool wick_mode, const double tk) { wick = wick_mode; tick = tk; side = 0; last_bar = -1; nled = 0; ArrayResize(ledger, 0, 4096); }
   long Q(const double x) const { return (long)MathRound(x / tick); }

   int Confirm(const int s, const double price, const int origin, const int i)
     {
      ArrayResize(ledger, nled + 1, 4096);
      ledger[nled].side = s; ledger[nled].price = price; ledger[nled].origin = origin; ledger[nled].confirming = i; ledger[nled].seq = nled;
      return nled++;
     }
   // returns index of the confirmed swing in ledger or -1
   int Update(const int i, const double h, const double lo, const double c)
     {
      if(last_bar >= 0 && i <= last_bar) return -1;
      last_bar = i;
      if(side == 0) { side = 1; ext = h; ext_bar = i; ref = lo; ref_bar = i; return -1; }
      int out = -1;
      if(side == 1)
        {
         bool nw = Q(h) > Q(ext);
         bool br = wick ? (Q(lo) < Q(ref)) : (Q(c) < Q(ref));
         if(br)
           {
            out = nw ? Confirm(1, h, i, i) : Confirm(1, ext, ext_bar, i);
            side = -1; ext = lo; ext_bar = i; ref = h; ref_bar = i;
           }
         else if(nw) { ext = h; ext_bar = i; ref = lo; ref_bar = i; }
        }
      else
        {
         bool nw = Q(lo) < Q(ext);
         bool br = wick ? (Q(h) > Q(ref)) : (Q(c) > Q(ref));
         if(br)
           {
            out = nw ? Confirm(-1, lo, i, i) : Confirm(-1, ext, ext_bar, i);
            side = 1; ext = h; ext_bar = i; ref = lo; ref_bar = i;
           }
         else if(nw) { ext = lo; ext_bar = i; ref = h; ref_bar = i; }
        }
      return out;
     }
  };

//==================================================================== SMC structure
struct PmwPoint { int side; double price; int origin; int version; };
struct PmwSlot  { int status; double level; int pid; int version; };                // 0 UNSEEDED, 1 ACTIVE, 2 PENDING
struct PmwSweep { bool on; int pid; int version; double level; double wick; int wick_bar; };

class CPmwSmc
  {
public:
   bool     idm_wick, sweeps_on;
   CPmwPullback pb;
   int      trend;                 // 0 NONE, +1 UP, -1 DOWN
   PmwSlot  slotH, slotL;
   PmwPoint pts[]; int npts;
   int      chain[]; int nchain;
   bool     pend; int p_side, p_break; double p_trail; int p_trail_bar; bool p_has_idm; double p_idm;
   PmwSweep swH, swL;
   int      lastH, lastL;          // ledger index of last confirmed pullback H / L (-1 none)
   double   bh[], bl[], bc[]; int nb;
   // per-bar outputs
   int      mask;
   bool     st_h_set, st_l_set, pb_h_set, pb_l_set;
   double   st_h, st_l, pb_h, pb_l;

   void Init(const bool idmWick, const bool sweeps, const bool pbWick, const double tick)
     {
      idm_wick = idmWick; sweeps_on = sweeps; pb.Init(pbWick, tick);
      trend = 0; slotH.status = 0; slotL.status = 0; npts = 0; nchain = 0; pend = false; swH.on = false; swL.on = false;
      lastH = -1; lastL = -1; nb = 0;
      ArrayResize(pts, 0, 1024); ArrayResize(chain, 0, 1024); ArrayResize(bh, 0, 8192); ArrayResize(bl, 0, 8192); ArrayResize(bc, 0, 8192);
     }

   void Publish(const int side, const double price, const int origin, const int reasonBits)
     {
      ArrayResize(pts, npts + 1, 1024);
      pts[npts].side = side; pts[npts].price = price; pts[npts].origin = origin; pts[npts].version = 1;
      ArrayResize(chain, nchain + 1, 1024); chain[nchain++] = npts;
      PmwSlot s; s.status = 1; s.level = price; s.pid = npts; s.version = 1;
      if(side == 1) { slotH = s; mask |= PMW_EV_STRUCT_H; st_h = price; st_h_set = true; }
      else          { slotL = s; mask |= PMW_EV_STRUCT_L; st_l = price; st_l_set = true; }
      mask |= reasonBits;
      npts++;
      swH.on = false; swL.on = false;
     }

   void HLRange(const int a, const int b, const int side, double &price, int &origin)
     {
      price = side == 1 ? bh[a] : bl[a]; origin = a;
      for(int j = a + 1; j <= b; j++)
        {
         if(side == 1 && bh[j] > price) { price = bh[j]; origin = j; }
         if(side == -1 && bl[j] < price) { price = bl[j]; origin = j; }
        }
     }

   void Update(const double h, const double lo, const double c)
     {
      int i = nb;
      ArrayResize(bh, nb + 1, 8192); ArrayResize(bl, nb + 1, 8192); ArrayResize(bc, nb + 1, 8192);
      bh[nb] = h; bl[nb] = lo; bc[nb] = c; nb++;
      mask = 0; st_h_set = false; st_l_set = false; pb_h_set = false; pb_l_set = false;
      int sw = pb.Update(i, h, lo, c);
      bool newH = false, newL = false;
      if(sw >= 0)
        {
         if(pb.ledger[sw].side == 1) { lastH = sw; newH = true; pb_h = pb.ledger[sw].price; pb_h_set = true; }
         else                        { lastL = sw; newL = true; pb_l = pb.ledger[sw].price; pb_l_set = true; }
        }
      // seed
      if(slotH.status == 0 && slotL.status == 0)
        {
         if(lastH >= 0 && lastL >= 0)
           {
            if(pb.ledger[lastH].price > pb.ledger[lastL].price)
              {
               int first = lastH, second = lastL;
               if(pb.ledger[lastL].origin < pb.ledger[lastH].origin || (pb.ledger[lastL].origin == pb.ledger[lastH].origin && pb.ledger[lastL].seq < pb.ledger[lastH].seq))
                 { first = lastL; second = lastH; }
               Publish(pb.ledger[first].side, pb.ledger[first].price, pb.ledger[first].origin, 0);
               Publish(pb.ledger[second].side, pb.ledger[second].price, pb.ledger[second].origin, 0);
              }
            else { lastH = -1; lastL = -1; }
           }
         return;
        }
      PmwSlot preH = slotH, preL = slotL;
      // pending trail, IDM ratchet, IDM test (never on the breaking bar)
      if(pend && i > p_break)
        {
         bool taken = false;
         if(p_side == 1)
           {
            if(h > p_trail) { p_trail = h; p_trail_bar = i; }
            if(newL)
              {
               double s = pb.ledger[lastL].price;
               bool protOk = slotL.status != 1 || s >= slotL.level;
               if(protOk && s <= p_trail && (!p_has_idm || s > p_idm)) { p_idm = s; p_has_idm = true; }
              }
            taken = p_has_idm && (idm_wick ? (lo <= p_idm) : (c < p_idm));
           }
         else
           {
            if(lo < p_trail) { p_trail = lo; p_trail_bar = i; }
            if(newH)
              {
               double s = pb.ledger[lastH].price;
               bool protOk = slotH.status != 1 || s <= slotH.level;
               if(protOk && s >= p_trail && (!p_has_idm || s < p_idm)) { p_idm = s; p_has_idm = true; }
              }
            taken = p_has_idm && (idm_wick ? (h >= p_idm) : (c > p_idm));
           }
         if(taken)
           {
            mask |= PMW_EV_IDM;
            double price; int origin; HLRange(p_break, i, p_side, price, origin);
            Publish(p_side, price, origin, 0);
            pend = false;
           }
        }
      // close breaks vs ACTIVE levels
      bool up = slotH.status == 1 && c > slotH.level;
      bool dn = slotL.status == 1 && c < slotL.level;
      if(up && dn) return;                                         // CORRUPT_STATE
      if(up || dn)
        {
         int d = up ? 1 : -1, side = d, opp = -d;
         if(pend && p_side == opp) { Publish(opp, p_trail, p_trail_bar, PMW_EV_FALLBACK); pend = false; }
         if(side == 1) swH.on = false; else swL.on = false;                    // same-side candidate rejected
         PmwSweep cand;
         if(opp == 1) cand = swH; else cand = swL;
         if(sweeps_on && cand.on && cand.wick_bar < i && cand.pid < npts && pts[cand.pid].version == cand.version)
           {
            pts[cand.pid].version++; pts[cand.pid].price = cand.wick; pts[cand.pid].origin = cand.wick_bar;
            mask |= (opp == 1 ? PMW_EV_X_H : PMW_EV_X_L);
            if(opp == 1 && slotH.pid == cand.pid && slotH.status == 1) { slotH.level = cand.wick; slotH.version = pts[cand.pid].version; }
            if(opp == -1 && slotL.pid == cand.pid && slotL.status == 1) { slotL.level = cand.wick; slotL.version = pts[cand.pid].version; }
           }
         swH.on = false; swL.on = false;
         bool bos = (trend == 0 || trend == d);
         mask |= bos ? (d == 1 ? PMW_EV_BOS_UP : PMW_EV_BOS_DOWN) : (d == 1 ? PMW_EV_CHOCH_UP : PMW_EV_CHOCH_DOWN);
         trend = d;
         if(side == 1) slotH.status = 2; else slotL.status = 2;
         if(nchain > 0 && pts[chain[nchain - 1]].side == side)
           {
            double price; int origin; HLRange(pts[chain[nchain - 1]].origin, i, opp, price, origin);
            Publish(opp, price, origin, PMW_EV_ANCHOR);
            if(side == 1) slotH.status = 2; else slotL.status = 2;
           }
         PmwSlot prot;
         if(opp == 1) prot = slotH; else prot = slotL;
         double trail = side == 1 ? h : lo;
         int ref = opp == 1 ? lastH : lastL;
         bool hasIdm = false; double idm = 0;
         if(ref >= 0 && prot.status == 1 && ((side == 1 && prot.level <= pb.ledger[ref].price && pb.ledger[ref].price <= trail) ||
                                              (side == -1 && trail <= pb.ledger[ref].price && pb.ledger[ref].price <= prot.level)))
           { idm = pb.ledger[ref].price; hasIdm = true; }
         else if(prot.status == 1) { idm = prot.level; hasIdm = true; }
         pend = true; p_side = side; p_break = i; p_trail = trail; p_trail_bar = i; p_has_idm = hasIdm; p_idm = idm;
         return;
        }
      // wick sweep candidates against levels ACTIVE before this bar and still current
      if(sweeps_on)
        {
         if(preH.status == 1 && slotH.status == 1 && slotH.pid == preH.pid && h > preH.level && c <= preH.level)
            if(!swH.on || h > swH.wick) { swH.on = true; swH.pid = preH.pid; swH.version = preH.version; swH.level = preH.level; swH.wick = h; swH.wick_bar = i; }
         if(preL.status == 1 && slotL.status == 1 && slotL.pid == preL.pid && lo < preL.level && c >= preL.level)
            if(!swL.on || lo < swL.wick) { swL.on = true; swL.pid = preL.pid; swL.version = preL.version; swL.level = preL.level; swL.wick = lo; swL.wick_bar = i; }
        }
     }
  };

//==================================================================== shared writer helpers
string PmwNum(const double v, const bool has) { return has && v != EMPTY_VALUE && MathIsValidNumber(v) ? DoubleToString(v, 10) : ""; }

bool PmwSha256Hex(const string text, string &hex, uchar &data[])
  {
   uchar key[], dg[];
   StringToCharArray(text, data, 0, StringLen(text), CP_UTF8);
   if(CryptEncode(CRYPT_HASH_SHA256, data, key, dg) != 32) return false;
   hex = "";
   for(int k = 0; k < 32; k++) hex += StringFormat("%02x", dg[k]);
   return true;
  }

bool PmwAtomicWrite(const string tmp, const string dst, uchar &a[], uchar &b[])
  {
   FolderCreate("PMW");
   int fh = FileOpen(tmp, FILE_WRITE | FILE_BIN);
   if(fh == INVALID_HANDLE) return false;
   FileWriteArray(fh, a, 0, ArraySize(a));
   if(ArraySize(b) > 0) FileWriteArray(fh, b, 0, ArraySize(b));
   FileClose(fh);
   return FileMove(tmp, 0, dst, FILE_REWRITE);
  }

string PmwJsonEsc(const string s)
  {
   string r = s;
   StringReplace(r, "\\", "\\\\"); StringReplace(r, "\"", "\\\""); StringReplace(r, "\n", " "); StringReplace(r, "\r", " "); StringReplace(r, "\t", " ");
   return r;
  }

// outer envelope {envelope, checksum = sha256(body text), body: "<json text>"} - same as extind.contract / context_ind.buffers.wrap
bool PmwWriteEnvelope(const string schema, const string body, const string tmp, const string dst)
  {
   string hex; uchar data[];
   if(!PmwSha256Hex(body, hex, data)) return false;
   string outer = "{\"envelope\":\"" + schema + "\",\"checksum\":\"" + hex + "\",\"body\":\"" + PmwJsonEsc(body) + "\"}";
   uchar o[], none[];
   StringToCharArray(outer, o, 0, StringLen(outer), CP_UTF8);
   return PmwAtomicWrite(tmp, dst, o, none);
  }
#endif
