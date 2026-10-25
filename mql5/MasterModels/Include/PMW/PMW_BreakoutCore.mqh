//+------------------------------------------------------------------+
//| PMW_BreakoutCore.mqh - confirmed swing breakout zones engine       |
//| (port of backend/masterquo/mm/breakout_zones.py, PMW-MM-BREAKOUT-1)|
//| Feed CLOSED bars in chronological order with Update(); a bar time  |
//| <= the last one is ignored (replay == incremental). Breakouts are  |
//| evaluated against zones known BEFORE this bar's swing confirmation.|
//| Zones keep their member swings (centre = mean of members, bounds = |
//| min/max of members -/+ frozen pad), a less extreme swing within    |
//| min_sep bars is not a new touch, a more extreme one replaces it.   |
//+------------------------------------------------------------------+
#ifndef PMW_BREAKOUT_CORE_MQH
#define PMW_BREAKOUT_CORE_MQH

enum ENUM_PMW_CONFIRM { PMW_CONF_SESSION_VWAP = 0, PMW_CONF_SMA = 1, PMW_CONF_SMMA = 2, PMW_CONF_NONE = 3 };
enum ENUM_PMW_ZSTATE { ZS_PROVISIONAL = 0, ZS_QUAL_RES, ZS_QUAL_SUP, ZS_BROKEN_UP, ZS_BROKEN_DOWN, ZS_INVALIDATED, ZS_EXPIRED };

struct PmwZone
  {
   int      id, kind, state, touches, created_bar, last_touch_bar;   // kind +1 resistance, -1 support
   double   pad, center, lower, upper;
   datetime created_t;
  };

struct PmwBzEvent
  {
   string   id;
   datetime bar_t;
   int      dir, zone, touches;
   double   lower, upper, close, ref;
   bool     accepted;
   string   why;
  };

class CPmwBreakout
  {
public:
   int        left, right, min_sep, atr_n, min_touches, expire, sma_n, smma_n, sess_start_min, sess_off_min, conf, max_zones, tfs;
   double     prom_atr, tol_atr, tol_floor, pad_atr, buf_atr, point;
   double     t[], h[], l[], c[], v[], atr[];
   double     sw_px[], sw_atr[];                 // confirmed swings
   int        sw_bar[], sw_conf[];
   datetime   sw_avail[];
   int        last_sw[2];                        // [0] highs, [1] lows (index into sw_*), -1 none
   PmwZone    z[];
   int        mz[], ms[];                        // zone members: zone slot, swing index (insertion order)
   PmwBzEvent ev[];
   int        nzone, n_qualified;
   double     sma_sum, smma, pv, vol, vwap, sma_v, tr_acc;
   long       sess;
   int        latest_dir;
   datetime   latest_t;

   void Setup(const int L, const int R, const int sep, const double prom, const int atrn, const double tol, const double tolfloor, const double pad,
              const int mint, const int exp, const double buf, const int confirm, const int sman, const int smman, const int sstart, const int soff,
              const double pt, const int tf_seconds)
     {
      left = L; right = R; min_sep = sep; prom_atr = prom; atr_n = atrn; tol_atr = tol; tol_floor = tolfloor; pad_atr = pad; min_touches = mint;
      expire = exp; buf_atr = buf; conf = confirm; sma_n = sman; smma_n = smman; sess_start_min = sstart; sess_off_min = soff; point = pt;
      tfs = tf_seconds; max_zones = 200;
      Reset();
     }
   void Reset()
     {
      ArrayResize(t, 0); ArrayResize(h, 0); ArrayResize(l, 0); ArrayResize(c, 0); ArrayResize(v, 0); ArrayResize(atr, 0);
      ArrayResize(sw_px, 0); ArrayResize(sw_atr, 0); ArrayResize(sw_bar, 0); ArrayResize(sw_conf, 0); ArrayResize(sw_avail, 0);
      ArrayResize(z, 0); ArrayResize(mz, 0); ArrayResize(ms, 0); ArrayResize(ev, 0);
      last_sw[0] = -1; last_sw[1] = -1; nzone = 0; n_qualified = 0;
      sma_sum = 0; smma = EMPTY_VALUE; pv = 0; vol = 0; vwap = EMPTY_VALUE; sma_v = EMPTY_VALUE; sess = LONG_MIN; tr_acc = 0;
      latest_dir = 0; latest_t = 0;
     }
   static bool Live(const int s) { return s == ZS_PROVISIONAL || s == ZS_QUAL_RES || s == ZS_QUAL_SUP; }
   void PushD(double &a[], const double x) { int n = ArraySize(a); ArrayResize(a, n + 1, 4096); a[n] = x; }

   //--- causal indicators of the newest closed bar
   void Indicators()
     {
      int i = ArraySize(c) - 1;
      double tr = (i == 0) ? h[i] - l[i] : MathMax(h[i] - l[i], MathMax(MathAbs(h[i] - c[i - 1]), MathAbs(l[i] - c[i - 1])));
      if(i + 1 < atr_n) { tr_acc += tr; PushD(atr, EMPTY_VALUE); }
      else if(i + 1 == atr_n) PushD(atr, (tr_acc + tr) / atr_n);
      else PushD(atr, (atr[i - 1] * (atr_n - 1) + tr) / atr_n);
      sma_sum += c[i];
      if(i >= sma_n) sma_sum -= c[i - sma_n];
      sma_v = (i + 1 >= sma_n) ? sma_sum / sma_n : EMPTY_VALUE;
      if(i + 1 == smma_n) { double s = 0; for(int k = i - smma_n + 1; k <= i; k++) s += c[k]; smma = s / smma_n; }
      else if(i + 1 > smma_n) smma = (smma * (smma_n - 1) + c[i]) / smma_n;
      long sid = (long)MathFloor((t[i] + tfs + sess_off_min * 60.0 - sess_start_min * 60.0) / 86400.0);
      if(sid != sess) { sess = sid; pv = 0; vol = 0; }
      pv += (h[i] + l[i] + c[i]) / 3.0 * v[i];                         // tick volume = activity proxy, not traded volume
      vol += v[i];
      vwap = vol > 0 ? pv / vol : EMPTY_VALUE;
     }

   //--- zones
   void Refresh(const int k)
     {
      double s = 0, lo = DBL_MAX, hi = -DBL_MAX; int n = 0, lt = -1;
      for(int m = 0; m < ArraySize(mz); m++)
        {
         if(mz[m] != k) continue;
         double p = sw_px[ms[m]];
         s += p; n++; lo = MathMin(lo, p); hi = MathMax(hi, p); lt = MathMax(lt, sw_conf[ms[m]]);
        }
      z[k].touches = n; z[k].center = s / n; z[k].lower = lo - z[k].pad; z[k].upper = hi + z[k].pad; z[k].last_touch_bar = lt;
      int want = n >= min_touches ? (z[k].kind > 0 ? ZS_QUAL_RES : ZS_QUAL_SUP) : ZS_PROVISIONAL;
      if(want != z[k].state)
        {
         if(want != ZS_PROVISIONAL && z[k].state == ZS_PROVISIONAL) n_qualified++;
         z[k].state = want;
        }
     }

   void AddMember(const int k, const int s) { int n = ArraySize(mz); ArrayResize(mz, n + 1, 1024); ArrayResize(ms, n + 1, 1024); mz[n] = k; ms[n] = s; }

   void Merge(const int k)
     {
      for(int o = 0; o < ArraySize(z); o++)
        {
         if(o == k || z[o].kind != z[k].kind || !Live(z[o].state)) continue;
         if(z[o].lower <= z[k].upper && z[k].lower <= z[o].upper)
           {
            int keep = z[o].created_bar < z[k].created_bar ? o : k, gone = (keep == o) ? k : o;
            for(int m = 0; m < ArraySize(mz); m++) if(mz[m] == gone) mz[m] = keep;
            z[keep].pad = MathMin(z[keep].pad, z[gone].pad);
            z[gone].state = ZS_INVALIDATED;
            Refresh(keep);
            Merge(keep);
            return;
           }
        }
     }

   // drop dead zones (never evaluated again) once there are more than max_zones of them; live zone order is preserved
   void Compact()
     {
      int dead = 0;
      for(int k = 0; k < ArraySize(z); k++) if(!Live(z[k].state)) dead++;
      if(dead <= max_zones) return;
      int map[]; ArrayResize(map, ArraySize(z));
      PmwZone nz[]; int n = 0;
      for(int k = 0; k < ArraySize(z); k++)
        {
         map[k] = -1;
         if(!Live(z[k].state)) continue;
         ArrayResize(nz, n + 1); nz[n] = z[k]; map[k] = n; n++;
        }
      int nmz[], nms[]; int q = 0;
      for(int m = 0; m < ArraySize(mz); m++)
        {
         if(map[mz[m]] < 0) continue;
         ArrayResize(nmz, q + 1, 1024); ArrayResize(nms, q + 1, 1024); nmz[q] = map[mz[m]]; nms[q] = ms[m]; q++;
        }
      ArrayFree(z); ArrayResize(z, n); for(int k = 0; k < n; k++) z[k] = nz[k];
      ArrayFree(mz); ArrayFree(ms); ArrayCopy(mz, nmz); ArrayCopy(ms, nms);
     }

   int NewSwing(const int side, const int j, const double px, const double a)
     {
      int n = ArraySize(sw_px);
      ArrayResize(sw_px, n + 1, 1024); ArrayResize(sw_atr, n + 1, 1024); ArrayResize(sw_bar, n + 1, 1024); ArrayResize(sw_conf, n + 1, 1024);
      ArrayResize(sw_avail, n + 1, 1024);
      int i = ArraySize(c) - 1;
      sw_px[n] = px; sw_atr[n] = a; sw_bar[n] = j; sw_conf[n] = i; sw_avail[n] = (datetime)(t[i] + tfs);
      return n;
     }

   void AddSwing(const int side, const int j, const double px, const double a)     // side 0 = high, 1 = low
     {
      int last = last_sw[side];
      if(last >= 0 && j - sw_bar[last] < min_sep)
        {
         bool better = (side == 0) ? px > sw_px[last] : px < sw_px[last];
         if(!better) return;                                           // same visit, less extreme: not a new touch
         int s = NewSwing(side, j, px, a);
         last_sw[side] = s;
         for(int m = 0; m < ArraySize(mz); m++)
           {
            if(ms[m] == last && Live(z[mz[m]].state)) { ms[m] = s; Refresh(mz[m]); return; }   // TOUCH_REPLACED_MORE_EXTREME
           }
         ClusterSide(s, side);
         return;
        }
      int s = NewSwing(side, j, px, a);
      last_sw[side] = s;
      ClusterSide(s, side);
     }

   void ClusterSide(const int s, const int side)
     {
      int kind = side == 0 ? +1 : -1;
      double tol = MathMax(tol_atr * sw_atr[s], tol_floor * point);
      int best = -1; double bd = DBL_MAX;
      for(int k = 0; k < ArraySize(z); k++)
        {
         if(z[k].kind != kind || !Live(z[k].state)) continue;
         double dd = MathAbs(z[k].center - sw_px[s]);
         if(best < 0 || dd < bd || (dd == bd && z[k].created_bar < z[best].created_bar)) { bd = dd; best = k; }
        }
      if(best >= 0 && bd <= tol) { AddMember(best, s); Refresh(best); Merge(best); return; }
      int n = ArraySize(z); ArrayResize(z, n + 1, 256);
      nzone++;
      z[n].id = nzone; z[n].kind = kind; z[n].state = ZS_PROVISIONAL; z[n].pad = pad_atr * sw_atr[s];
      z[n].created_bar = ArraySize(c) - 1; z[n].created_t = sw_avail[s];
      AddMember(n, s);
      Refresh(n);
      Compact();
     }

   void Swings()
     {
      int n = ArraySize(c), j = n - 1 - right;
      if(j - left < 0) return;
      double a = atr[n - 1];
      if(a == EMPTY_VALUE) return;
      int s0 = j - left, s1 = j + right;
      bool isH = true, isL = true;
      double mn = l[s0], mx = h[s0];
      for(int k = s0; k <= s1; k++) { mn = MathMin(mn, l[k]); mx = MathMax(mx, h[k]); }
      for(int k = s0; k < j; k++) { if(!(h[k] < h[j])) isH = false; if(!(l[k] > l[j])) isL = false; }
      for(int k = j + 1; k <= s1; k++) { if(!(h[k] <= h[j])) isH = false; if(!(l[k] >= l[j])) isL = false; }
      if(isH && h[j] - mn >= prom_atr * a) AddSwing(0, j, h[j], a);
      if(isL && mx - l[j] >= prom_atr * a) AddSwing(1, j, l[j], a);
     }

   void Breakouts()
     {
      int i = ArraySize(c) - 1;
      double a = atr[i];
      bool bufok = (a != EMPTY_VALUE) || buf_atr == 0;
      double buf = (a != EMPTY_VALUE) ? buf_atr * a : 0.0;
      for(int k = 0; k < ArraySize(z); k++)
        {
         int dir = 0;
         if(bufok && z[k].state == ZS_QUAL_RES && c[i] > z[k].upper + buf) dir = 1;
         else if(bufok && z[k].state == ZS_QUAL_SUP && c[i] < z[k].lower - buf) dir = -1;
         if(dir == 0)
           {
            if(Live(z[k].state) && i - z[k].last_touch_bar > expire) z[k].state = ZS_EXPIRED;
            continue;
           }
         double ref = conf == PMW_CONF_SESSION_VWAP ? vwap : conf == PMW_CONF_SMA ? sma_v : conf == PMW_CONF_SMMA ? smma : 0.0;
         bool ok; string why;
         if(conf == PMW_CONF_NONE) { ok = true; why = "NONE"; }
         else if(ref == EMPTY_VALUE) { ok = false; why = "FILTER_NOT_READY"; }
         else { ok = dir > 0 ? c[i] > ref : c[i] < ref; why = ok ? "PASS" : "FILTER_REJECTED"; }
         z[k].state = dir > 0 ? ZS_BROKEN_UP : ZS_BROKEN_DOWN;          // consumed once, accepted or not
         int m = ArraySize(ev); ArrayResize(ev, m + 1, 256);
         ev[m].id = StringFormat("BZ%d@%I64d", z[k].id, (long)t[i]); ev[m].bar_t = (datetime)t[i]; ev[m].dir = dir; ev[m].zone = z[k].id;
         ev[m].touches = z[k].touches; ev[m].lower = z[k].lower; ev[m].upper = z[k].upper; ev[m].close = c[i]; ev[m].ref = ref;
         ev[m].accepted = ok; ev[m].why = why;
         if(ok) { latest_dir = dir; latest_t = (datetime)t[i]; }
        }
     }

   bool Update(const datetime bt, const double o, const double hh, const double ll, const double cc, const double vv)
     {
      int n = ArraySize(c);
      if(n > 0 && (double)bt <= t[n - 1]) return false;
      PushD(t, (double)bt); PushD(h, hh); PushD(l, ll); PushD(c, cc); PushD(v, vv);
      Indicators();
      Breakouts();
      Swings();
      return true;
     }
  };
#endif
