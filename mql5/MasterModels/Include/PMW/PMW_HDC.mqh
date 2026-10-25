//+------------------------------------------------------------------+
//| PMW_HDC.mqh - binary hypervectors on ulong words (PMW-MM-HDC-1).  |
//| Bit j -> word j/64, bit j%64 (little-endian, identical to the     |
//| Python reference mm/hdc.py). Padding bits of the last word are    |
//| kept at 0. bind = XOR, bundle = majority + tie vector, permute =  |
//| rotation of the FULL D-bit string, hamming over D bits, signed    |
//| similarity 1-2H/D, integer class accumulators (online update ==   |
//| rebuild when corrections are off). Codebooks are not generated   |
//| here: they are loaded from the artifact / fixture (the Python     |
//| PCG64 stream is not reproduced in MQL5).                          |
//+------------------------------------------------------------------+
#ifndef PMW_HDC_MQH
#define PMW_HDC_MQH

class CPmwHV
  {
public:
   int   D, W;
   ulong w[];
   ulong lastmask;
   void  Init(const int d)
     {
      D = d; W = (d + 63) / 64; ArrayResize(w, W); ArrayInitialize(w, 0);
      int pad = W * 64 - d;
      lastmask = (pad == 0) ? 0xFFFFFFFFFFFFFFFF : ((((ulong)1) << (64 - pad)) - 1);
     }
   void  Mask() { w[W - 1] &= lastmask; }
   bool  Get(const int j) const { return ((w[j >> 6] >> (j & 63)) & 1) == 1; }
   void  Set(const int j, const bool b) { if(b) w[j >> 6] |= ((ulong)1 << (j & 63)); else w[j >> 6] &= ~((ulong)1 << (j & 63)); }
  };

int PmwPopcount(ulong v) { int c = 0; while(v != 0) { v &= v - 1; c++; } return c; }

void PmwBind(const CPmwHV &a, const CPmwHV &b, CPmwHV &out)
  {
   out.Init(a.D);
   for(int i = 0; i < a.W; i++) out.w[i] = a.w[i] ^ b.w[i];
   out.Mask();
  }

int PmwHamming(const CPmwHV &a, const CPmwHV &b)
  {
   int h = 0;
   for(int i = 0; i < a.W; i++) { ulong x = a.w[i] ^ b.w[i]; if(i == a.W - 1) x &= a.lastmask; h += PmwPopcount(x); }
   return h;
  }

double PmwSimilarity(const CPmwHV &a, const CPmwHV &b) { return 1.0 - 2.0 * PmwHamming(a, b) / a.D; }

void PmwPermute(const CPmwHV &a, int k, CPmwHV &out)
  {
   int D = a.D;
   k %= D; if(k < 0) k += D;
   out.Init(D);
   for(int j = 0; j < D; j++) if(a.Get(j)) out.Set((j + k) % D, true);   // full D-bit rotation (crosses word boundaries)
  }

// majority over n vectors; ties take the bit of `tie` (deterministic, seeded upstream)
bool PmwBundle(const CPmwHV &vs[], const int n, const CPmwHV &tie, CPmwHV &out)
  {
   if(n <= 0) return false;
   int D = vs[0].D;
   out.Init(D);
   for(int j = 0; j < D; j++)
     {
      int c = 0;
      for(int k = 0; k < n; k++) if(vs[k].Get(j)) c++;
      bool b = (2 * c > n) ? true : (2 * c < n ? false : tie.Get(j));
      out.Set(j, b);
     }
   return true;
  }

bool PmwHexToHV(const string hex_words, const int D, CPmwHV &out)
  {
   out.Init(D);
   string p[];
   int m = StringSplit(hex_words, ' ', p);
   if(m != out.W) return false;
   for(int i = 0; i < m; i++)
     {
      ulong v = 0;
      for(int c = 0; c < StringLen(p[i]); c++)
        {
         ushort ch = StringGetCharacter(p[i], c);
         int d = (ch >= '0' && ch <= '9') ? ch - '0' : (ch >= 'a' && ch <= 'f') ? 10 + ch - 'a' : -1;
         if(d < 0) return false;
         v = (v << 4) | (ulong)d;
        }
      out.w[i] = v;
     }
   out.Mask();
   return true;
  }

class CPmwHDCAcc
  {
public:
   int D, C;
   int acc[];                                                        // C x D int accumulators (bipolar votes)
   long updates;
   void Init(const int d, const int c) { D = d; C = c; ArrayResize(acc, d * c); ArrayInitialize(acc, 0); updates = 0; }
   bool Update(const CPmwHV &v, const int y)
     {
      if(y < 0 || y >= C || updates >= 2147483646) return false;
      for(int j = 0; j < D; j++) acc[y * D + j] += v.Get(j) ? 1 : -1;
      updates++;
      return true;
     }
   void Prototype(const int y, const CPmwHV &tie, CPmwHV &out)
     {
      out.Init(D);
      for(int j = 0; j < D; j++) { int a = acc[y * D + j]; out.Set(j, a > 0 ? true : (a < 0 ? false : tie.Get(j))); }
     }
  };
#endif
