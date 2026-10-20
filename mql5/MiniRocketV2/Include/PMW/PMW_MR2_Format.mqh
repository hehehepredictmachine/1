//+------------------------------------------------------------------+
//| PMW_MR2_Format.mqh - portable model.bin loader + result writer    |
//| model.bin: magic PMWMR2\0\0, u32 version=1, u32 endian 0x01020304,|
//| u32 nsec, sections [tag4][u32 dtype 1=i4 2=f4 3=f8][u32 count]     |
//| [u64 nbytes][data LE], trailer SHA-256 of all preceding bytes.    |
//| Sizes are validated BEFORE allocation; any error keeps the        |
//| previously loaded model (atomic swap by the caller).              |
//| Result PMW_MR2_RESULT.bin: magic PMWMRRES, u32 ver, u64 seq,      |
//| i64 bar_time, i64 computed_at_utc, 32B model sha, 32B symbol,     |
//| 8B tf, 24B clock_basis, u32 n, f64[n], SHA-256 trailer; written to|
//| tmp then FileMove(FILE_REWRITE).                                  |
//+------------------------------------------------------------------+
#ifndef PMW_MR2_FORMAT_MQH
#define PMW_MR2_FORMAT_MQH
#include "PMW_MR2_Core.mqh"
#include "PMW_MR2_Ridge.mqh"

#define MR2_MAX_MODEL_BYTES (64 * 1024 * 1024)

union MR2U4 { uchar b[4]; uint u; int i; float f; };
union MR2U8 { uchar b[8]; ulong u; long l; double d; };

uint  MR2RdU4(const uchar &a[], const int o) { MR2U4 x; for(int k = 0; k < 4; k++) x.b[k] = a[o + k]; return x.u; }
int   MR2RdI4(const uchar &a[], const int o) { MR2U4 x; for(int k = 0; k < 4; k++) x.b[k] = a[o + k]; return x.i; }
float MR2RdF4(const uchar &a[], const int o) { MR2U4 x; for(int k = 0; k < 4; k++) x.b[k] = a[o + k]; return x.f; }
ulong MR2RdU8(const uchar &a[], const int o) { MR2U8 x; for(int k = 0; k < 8; k++) x.b[k] = a[o + k]; return x.u; }
double MR2RdF8(const uchar &a[], const int o) { MR2U8 x; for(int k = 0; k < 8; k++) x.b[k] = a[o + k]; return x.d; }

void MR2WrU4(uchar &a[], const uint v) { MR2U4 x; x.u = v; int n = ArraySize(a); ArrayResize(a, n + 4); for(int k = 0; k < 4; k++) a[n + k] = x.b[k]; }
void MR2WrU8(uchar &a[], const ulong v) { MR2U8 x; x.u = v; int n = ArraySize(a); ArrayResize(a, n + 8); for(int k = 0; k < 8; k++) a[n + k] = x.b[k]; }
void MR2WrF8(uchar &a[], const double v) { MR2U8 x; x.d = v; int n = ArraySize(a); ArrayResize(a, n + 8); for(int k = 0; k < 8; k++) a[n + k] = x.b[k]; }
void MR2WrBytes(uchar &a[], const uchar &src[], const int len)
  {
   int n = ArraySize(a); ArrayResize(a, n + len);
   for(int k = 0; k < len; k++) a[n + k] = (k < ArraySize(src)) ? src[k] : 0;
  }
void MR2WrStr(uchar &a[], const string s, const int len)
  {
   uchar t[]; StringToCharArray(s, t, 0, WHOLE_ARRAY, CP_UTF8);
   int L = ArraySize(t); if(L > 0 && t[L - 1] == 0) ArrayResize(t, L - 1);
   MR2WrBytes(a, t, len);
  }

bool MR2Sha256(const uchar &data[], uchar &out[])
  {
   uchar key[];
   return CryptEncode(CRYPT_HASH_SHA256, data, key, out) == 32;
  }

string MR2Hex(const uchar &b[])
  {
   string s = "";
   for(int i = 0; i < ArraySize(b); i++) s += StringFormat("%02x", b[i]);
   return s;
  }

//--- read a whole binary file from MQL5\Files (or Common when common=true)
bool MR2ReadFile(const string name, const bool common, uchar &buf[], string &err)
  {
   int h = FileOpen(name, FILE_READ | FILE_BIN | (common ? FILE_COMMON : 0));
   if(h == INVALID_HANDLE) { err = "FILE_NOT_FOUND"; return false; }
   ulong sz = FileSize(h);
   if(sz > MR2_MAX_MODEL_BYTES) { FileClose(h); err = "MODEL_FILE_TOO_LARGE"; return false; }
   ArrayResize(buf, (int)sz);
   uint got = FileReadArray(h, buf, 0, (int)sz);
   FileClose(h);
   if(got != sz) { err = "MODEL_FILE_TRUNCATED"; return false; }
   return true;
  }

struct MR2Section { string tag; uint dtype; uint count; int offset; };

//--- validate + index sections (no allocation of section data yet)
bool MR2Index(const uchar &buf[], MR2Section &secs[], string &err, string &shaHex)
  {
   int n = ArraySize(buf);
   if(n < 20 + 32) { err = "MODEL_FILE_TRUNCATED"; return false; }
   uchar body[], dg[];
   ArrayCopy(body, buf, 0, 0, n - 32);
   if(!MR2Sha256(body, dg)) { err = "SHA256_UNAVAILABLE"; return false; }
   for(int k = 0; k < 32; k++) if(dg[k] != buf[n - 32 + k]) { err = "CHECKSUM_MISMATCH"; return false; }
   shaHex = MR2Hex(dg);
   string magic = CharArrayToString(buf, 0, 6, CP_ACP);
   if(magic != "PMWMR2" || buf[6] != 0 || buf[7] != 0) { err = "BAD_MAGIC"; return false; }
   if(MR2RdU4(buf, 8) != 1) { err = "UNSUPPORTED_VERSION"; return false; }
   if(MR2RdU4(buf, 12) != 0x01020304) { err = "ENDIAN_MISMATCH"; return false; }
   uint ns = MR2RdU4(buf, 16);
   if(ns > 64) { err = "TOO_MANY_SECTIONS"; return false; }
   ArrayResize(secs, (int)ns);
   int o = 20, end = n - 32;
   for(uint s = 0; s < ns; s++)
     {
      if(o + 20 > end) { err = "MODEL_FILE_TRUNCATED"; return false; }
      secs[s].tag = CharArrayToString(buf, o, 4, CP_ACP);
      StringTrimRight(secs[s].tag);
      secs[s].dtype = MR2RdU4(buf, o + 4);
      secs[s].count = MR2RdU4(buf, o + 8);
      ulong nb = MR2RdU8(buf, o + 12);
      uint item = (secs[s].dtype == 3) ? 8 : 4;
      if(secs[s].dtype < 1 || secs[s].dtype > 3) { err = "BAD_DTYPE:" + secs[s].tag; return false; }
      if(nb != (ulong)secs[s].count * item || (ulong)o + 20 + nb > (ulong)end) { err = "BAD_SECTION_LENGTH:" + secs[s].tag; return false; }
      secs[s].offset = o + 20;
      o += 20 + (int)nb;
     }
   if(o != end) { err = "TRAILING_BYTES"; return false; }
   return true;
  }

int MR2Find(const MR2Section &secs[], const string tag)
  {
   for(int i = 0; i < ArraySize(secs); i++) if(secs[i].tag == tag) return i;
   return -1;
  }

//--- load the full exported model into TEMPORARY objects; the caller swaps them in only on success
bool MR2LoadModel(const string name, const bool common, CMiniRocketV2 &mr, CRidgeHeadV2 &head, string &err, string &shaHex)
  {
   uchar buf[];
   if(!MR2ReadFile(name, common, buf, err)) return false;
   MR2Section secs[];
   if(!MR2Index(buf, secs, err, shaHex)) return false;
   string need[] = {"META", "DILS", "CNTS", "QUAN", "BIAS", "SCMU", "SCSD", "COEF", "ICPT", "TEMP", "RESQ"};
   for(int i = 0; i < ArraySize(need); i++) if(MR2Find(secs, need[i]) < 0) { err = "MISSING_SECTION:" + need[i]; return false; }
   int m = MR2Find(secs, "META");
   int L = MR2RdI4(buf, secs[m].offset), F = MR2RdI4(buf, secs[m].offset + 4), H = MR2RdI4(buf, secs[m].offset + 8);
   if(L < 9 || L > 4096 || F < 84 || F > 100000 || H < 1 || H > 16) { err = "META_OUT_OF_RANGE"; return false; }
   int s;
   int dil[], cnt[]; float q[];
   s = MR2Find(secs, "DILS"); ArrayResize(dil, (int)secs[s].count); for(uint i = 0; i < secs[s].count; i++) dil[i] = MR2RdI4(buf, secs[s].offset + 4 * i);
   s = MR2Find(secs, "CNTS"); ArrayResize(cnt, (int)secs[s].count); for(uint i = 0; i < secs[s].count; i++) cnt[i] = MR2RdI4(buf, secs[s].offset + 4 * i);
   s = MR2Find(secs, "QUAN"); if((int)secs[s].count != F) { err = "SHAPE_MISMATCH:QUAN"; return false; }
   ArrayResize(q, F); for(int i = 0; i < F; i++) q[i] = MR2RdF4(buf, secs[s].offset + 4 * i);
   if(ArraySize(dil) != ArraySize(cnt)) { err = "SHAPE_MISMATCH:LAYOUT"; return false; }
   if(mr.SetLayout(L, dil, cnt, q) != MR2_OK) { err = "LAYOUT_MISMATCH"; return false; }
   s = MR2Find(secs, "BIAS"); if((int)secs[s].count != F) { err = "SHAPE_MISMATCH:BIAS"; return false; }
   ArrayResize(mr.m_bias, F); for(int i = 0; i < F; i++) mr.m_bias[i] = MR2RdF4(buf, secs[s].offset + 4 * i);
   mr.m_fitted = true;
   head.m_H = H; head.m_D = F;
   s = MR2Find(secs, "SCMU"); if((int)secs[s].count != F) { err = "SHAPE_MISMATCH:SCMU"; return false; }
   ArrayResize(head.m_mu, F); for(int i = 0; i < F; i++) head.m_mu[i] = MR2RdF8(buf, secs[s].offset + 8 * i);
   s = MR2Find(secs, "SCSD"); if((int)secs[s].count != F) { err = "SHAPE_MISMATCH:SCSD"; return false; }
   ArrayResize(head.m_sd, F); for(int i = 0; i < F; i++) head.m_sd[i] = MR2RdF8(buf, secs[s].offset + 8 * i);
   s = MR2Find(secs, "COEF"); if((int)secs[s].count != H * F * 4) { err = "SHAPE_MISMATCH:COEF"; return false; }
   ArrayResize(head.m_W, H * F * 4); for(int i = 0; i < H * F * 4; i++) head.m_W[i] = MR2RdF8(buf, secs[s].offset + 8 * i);
   s = MR2Find(secs, "ICPT"); if((int)secs[s].count != H * 4) { err = "SHAPE_MISMATCH:ICPT"; return false; }
   ArrayResize(head.m_b, H * 4); for(int i = 0; i < H * 4; i++) head.m_b[i] = MR2RdF8(buf, secs[s].offset + 8 * i);
   s = MR2Find(secs, "TEMP"); ArrayResize(head.m_T, (int)secs[s].count); for(uint i = 0; i < secs[s].count; i++) head.m_T[i] = MR2RdF8(buf, secs[s].offset + 8 * i);
   s = MR2Find(secs, "RESQ"); ArrayResize(head.m_resq, (int)secs[s].count); for(uint i = 0; i < secs[s].count; i++) head.m_resq[i] = MR2RdF8(buf, secs[s].offset + 8 * i);
   head.m_status = "LOADED";
   return true;
  }

//--- atomic result write into MQL5\Files\<dir>\PMW_MR2_RESULT.bin
bool MR2WriteResult(const string dir, const ulong seq, const long barTime, const long computedUtc, const string modelShaHex,
                    const string symbol, const string tf, const string clockBasis, const double &scores[], string &err)
  {
   uchar body[];
   uchar magic[]; StringToCharArray("PMWMRRES", magic, 0, 8, CP_ACP);
   MR2WrBytes(body, magic, 8);
   MR2WrU4(body, 1); MR2WrU8(body, seq); MR2WrU8(body, (ulong)barTime); MR2WrU8(body, (ulong)computedUtc);
   uchar sha[]; ArrayResize(sha, 32);
   for(int i = 0; i < 32; i++) sha[i] = (uchar)StringToInteger("0x" + StringSubstr(modelShaHex, 2 * i, 2));
   MR2WrBytes(body, sha, 32);
   MR2WrStr(body, symbol, 32); MR2WrStr(body, tf, 8); MR2WrStr(body, clockBasis, 24);
   MR2WrU4(body, (uint)ArraySize(scores));
   for(int i = 0; i < ArraySize(scores); i++) MR2WrF8(body, scores[i]);
   uchar dg[];
   if(!MR2Sha256(body, dg)) { err = "SHA256_UNAVAILABLE"; return false; }
   MR2WrBytes(body, dg, 32);
   string tmp = dir + "\\PMW_MR2_RESULT.tmp", fin = dir + "\\PMW_MR2_RESULT.bin";
   int h = FileOpen(tmp, FILE_WRITE | FILE_BIN);
   if(h == INVALID_HANDLE) { err = "OPEN_TMP_FAILED"; return false; }
   uint w = FileWriteArray(h, body, 0, ArraySize(body));
   FileClose(h);
   if(w != (uint)ArraySize(body)) { err = "WRITE_FAILED"; return false; }
   if(!FileMove(tmp, 0, fin, FILE_REWRITE)) { err = "MOVE_FAILED"; return false; }
   return true;
  }
#endif
