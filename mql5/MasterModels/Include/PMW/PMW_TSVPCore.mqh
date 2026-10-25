//+------------------------------------------------------------------+
//| PMW_TSVPCore.mqh - tick session volume profile core               |
//| (port of backend/masterquo/mm/tsvp.py, PMW-MM-TSVP-1)              |
//| Open-addressing hash map bucket key -> value/count, multiset      |
//| reconciliation of overlapping inclusive CopyTicksRange reads,     |
//| render state machine FULL_REBUILD > FULL_REDRAW > PARTIAL > CLEAN,|
//| POC = largest bucket value, ties -> lower price bucket.           |
//+------------------------------------------------------------------+
#ifndef PMW_TSVP_CORE_MQH
#define PMW_TSVP_CORE_MQH

enum ENUM_PMW_VP_SOURCE { VP_TICK_ACTIVITY_PROXY = 0, VP_ACTUAL_TRADE_VOLUME = 1 };
enum ENUM_PMW_VP_BUCKET { VP_BUCKET_MANUAL = 0, VP_BUCKET_ATR = 1 };
enum ENUM_PMW_VP_STATE  { VP_CLEAN = 0, VP_PARTIAL_UPDATE_PENDING = 1, VP_FULL_REDRAW_REQUIRED = 2, VP_FULL_REBUILD_REQUIRED = 3 };

string PmwVpStateName(const int s)
  {
   switch(s)
     {
      case VP_CLEAN: return "CLEAN";
      case VP_PARTIAL_UPDATE_PENDING: return "PARTIAL_UPDATE_PENDING";
      case VP_FULL_REDRAW_REQUIRED: return "FULL_REDRAW_REQUIRED";
     }
   return "FULL_REBUILD_REQUIRED";
  }

class CPmwBucketMap
  {
public:
   long   keys[];
   double vals[];
   int    cnts[];
   bool   used[], dirty[];
   int    cap, n, rehashes;
          CPmwBucketMap() : cap(0), n(0), rehashes(0) {}
   void   Init(const int c0) { cap = 64; while(cap < c0) cap <<= 1; Alloc(); n = 0; rehashes = 0; }
   void   Alloc() { ArrayResize(keys, cap); ArrayResize(vals, cap); ArrayResize(cnts, cap); ArrayResize(used, cap); ArrayResize(dirty, cap);
                    ArrayInitialize(vals, 0); ArrayInitialize(cnts, 0); ArrayInitialize(used, false); ArrayInitialize(dirty, false); ArrayInitialize(keys, 0); }
   int    Slot(const long k)
     {
      ulong hsh = ((ulong)k * (ulong)0x9E3779B97F4A7C15) & (ulong)(cap - 1);
      int s = (int)hsh;
      while(used[s] && keys[s] != k) s = (s + 1) & (cap - 1);
      return s;
     }
   bool   Grow()
     {
      long ok[]; double ov[]; int oc[]; bool od[];
      ArrayCopy(ok, keys); ArrayCopy(ov, vals); ArrayCopy(oc, cnts); ArrayCopy(od, dirty);
      bool ou[]; ArrayCopy(ou, used);
      int old = cap, moved = 0;
      cap *= 2; Alloc(); n = 0; rehashes++;
      for(int i = 0; i < old; i++)
        {
         if(!ou[i]) continue;
         int s = Slot(ok[i]);
         used[s] = true; keys[s] = ok[i]; vals[s] = ov[i]; cnts[s] = oc[i]; dirty[s] = od[i]; n++; moved++;
        }
      return moved == n;                                                // REHASH_LOST_BUCKET otherwise
     }
   double Add(const long k, const double v, bool &ok)
     {
      ok = true;
      if((n + 1) > 0.6 * cap) ok = Grow();
      int s = Slot(k);
      if(!used[s]) { used[s] = true; keys[s] = k; n++; }
      vals[s] += v; cnts[s]++; dirty[s] = true;
      return vals[s];
     }
  };

class CPmwTSVP
  {
public:
   int      source, bucket_mode, proxy_any;
   double   tick, size;
   long     start_ms, end_ms;
   CPmwBucketMap map;
   int      state;
   double   total, max_val;
   long     poc;
   bool     has_poc;
   long     watermark, tail_ms;
   string   tail_sig[];
   int      tail_cnt[];
   double   last_bid;
   long     counted, ign_outside, ign_not_eligible, ign_invalid, ign_duplicate;
   bool     fault;

            CPmwTSVP() : source(VP_TICK_ACTIVITY_PROXY), bucket_mode(VP_BUCKET_MANUAL), proxy_any(0), tick(0), size(0), start_ms(0), end_ms(0),
                         state(VP_FULL_REBUILD_REQUIRED), total(0), max_val(0), poc(0), has_poc(false), watermark(-1), tail_ms(-1), last_bid(0),
                         counted(0), ign_outside(0), ign_not_eligible(0), ign_invalid(0), ign_duplicate(0), fault(false) {}
   bool Setup(const int src, const int bmode, const int bucket_ticks, const double atr_mult, const double atr, const double tick_size,
              const bool any_quote, const long s_ms, const long e_ms)
     {
      if(tick_size <= 0 || bucket_ticks < 1 || atr_mult <= 0 || s_ms >= e_ms) return false;
      source = src; bucket_mode = bmode; tick = tick_size; proxy_any = any_quote ? 1 : 0; start_ms = s_ms; end_ms = e_ms;
      if(bmode == VP_BUCKET_ATR)
        {
         if(!MathIsValidNumber(atr) || atr <= 0) return false;                        // TSVP_ATR_UNAVAILABLE
         size = MathMax(tick, MathRound(atr * atr_mult / tick) * tick);               // frozen for this profile snapshot
        }
      else size = bucket_ticks * tick;
      map.Init(64);
      state = VP_FULL_REBUILD_REQUIRED; total = 0; max_val = 0; has_poc = false; poc = 0;
      watermark = -1; tail_ms = -1; ArrayResize(tail_sig, 0); ArrayResize(tail_cnt, 0); last_bid = 0;
      counted = 0; ign_outside = 0; ign_not_eligible = 0; ign_invalid = 0; ign_duplicate = 0; fault = false;
      return true;
     }
   long   Key(const double px) { return (long)MathFloor(px / size + 1e-9); }
   double Lower(const long k) { return k * size; }
   void   Request(const int st) { if(st > state) state = st; }         // a lower-priority request never downgrades a pending one

   static string Sig(const MqlTick &t)
     {
      return StringFormat("%.10g|%.10g|%.10g|%I64u|%.10g|%u", t.bid, t.ask, t.last, t.volume, t.volume_real, t.flags);
     }

   bool Eligible(const MqlTick &t, double &px, double &vol)
     {
      if(source == VP_ACTUAL_TRADE_VOLUME)
        {
         if((t.flags & TICK_FLAG_LAST) == 0 || (t.flags & TICK_FLAG_VOLUME) == 0) return false;
         vol = t.volume_real > 0 ? t.volume_real : (double)t.volume;
         px = t.last;
         return px > 0 && vol > 0;
        }
      if(t.bid <= 0) return false;
      if(proxy_any == 0 && (t.flags & TICK_FLAG_BID) == 0 && last_bid > 0 && t.bid == last_bid) return false;
      px = t.bid; vol = 1.0;
      return true;
     }

   int Count(const MqlTick &t)
     {
      if(t.time_msc < start_ms || t.time_msc > end_ms) { ign_outside++; return 0; }
      double px, v;
      bool e = Eligible(t, px, v);
      if(t.bid > 0) last_bid = t.bid;
      if(!e) { ign_not_eligible++; return 0; }
      if(!MathIsValidNumber(px) || !MathIsValidNumber(v)) { ign_invalid++; return 0; }
      long k = Key(px);
      bool ok;
      double val = map.Add(k, v, ok);
      if(!ok) { fault = true; Request(VP_FULL_REBUILD_REQUIRED); }
      total += v; counted++;
      if(val > max_val || (val == max_val && has_poc && k < poc))
        {
         bool new_max = val > max_val;
         max_val = val; poc = k; has_poc = true;
         if(new_max) Request(VP_FULL_REDRAW_REQUIRED);                 // every normalised width changes
        }
      Request(VP_PARTIAL_UPDATE_PENDING);
      return 1;
     }

   int TailFind(const string s) { for(int i = 0; i < ArraySize(tail_sig); i++) if(tail_sig[i] == s) return i; return -1; }

   // one chronologically ordered inclusive range read (oldest first); returns the number of newly counted ticks
   int Ingest(const MqlTick &ticks[], const int n, const long read_until_ms)
     {
      int added = 0, i = 0;
      while(i < n)
        {
         long ms = ticks[i].time_msc;
         int j = i;
         while(j < n && ticks[j].time_msc == ms) j++;
         if(watermark >= 0 && ms <= watermark) { ign_duplicate += j - i; i = j; continue; }      // already final
         if(ms == tail_ms)
           {
            // multiset reconciliation: count only the surplus occurrences of each signature
            string sg[]; int sc[]; ArrayResize(sg, 0); ArrayResize(sc, 0);
            for(int q = i; q < j; q++)
              {
               string s = Sig(ticks[q]); int f = -1;
               for(int r = 0; r < ArraySize(sg); r++) if(sg[r] == s) { f = r; break; }
               if(f < 0) { f = ArraySize(sg); ArrayResize(sg, f + 1); ArrayResize(sc, f + 1); sg[f] = s; sc[f] = 0; }
               sc[f]++;
               int seen_i = TailFind(s), seen = seen_i < 0 ? 0 : tail_cnt[seen_i];
               if(sc[f] > seen) added += Count(ticks[q]);
               else ign_duplicate++;
              }
            for(int r = 0; r < ArraySize(sg); r++)
              {
               int ti = TailFind(sg[r]);
               if(ti < 0) { ti = ArraySize(tail_sig); ArrayResize(tail_sig, ti + 1); ArrayResize(tail_cnt, ti + 1); tail_sig[ti] = sg[r]; tail_cnt[ti] = 0; }
               tail_cnt[ti] = MathMax(tail_cnt[ti], sc[r]);
              }
           }
         else
           {
            if(tail_ms >= 0 && ms > tail_ms) watermark = tail_ms;                                 // previous trailing ms is final
            tail_ms = ms; ArrayResize(tail_sig, 0); ArrayResize(tail_cnt, 0);
            for(int q = i; q < j; q++)
              {
               string s = Sig(ticks[q]); int ti = TailFind(s);
               if(ti < 0) { ti = ArraySize(tail_sig); ArrayResize(tail_sig, ti + 1); ArrayResize(tail_cnt, ti + 1); tail_sig[ti] = s; tail_cnt[ti] = 0; }
               tail_cnt[ti]++;
               added += Count(ticks[q]);
              }
           }
         i = j;
        }
      if(read_until_ms >= 0 && tail_ms >= 0 && read_until_ms > tail_ms) watermark = tail_ms;
      return added;
     }

   string Status()
     {
      if(fault) return "REHASH_FAULT";
      if(counted > 0) return "COMPLETE";
      return source == VP_ACTUAL_TRADE_VOLUME ? "ACTUAL_VOLUME_UNAVAILABLE" : "EMPTY";
     }
  };
#endif
