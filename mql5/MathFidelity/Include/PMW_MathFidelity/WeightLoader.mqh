//+------------------------------------------------------------------+
//| WeightLoader.mqh - strict loaders for model_weights.csv and       |
//| test_vectors.csv. Lines are read as text (FILE_TXT) and split on  |
//| ',' explicitly, so '#W1,8,16' headers can never be confused with  |
//| numeric payload. Fail closed: a set of weights is handed out only |
//| when every section validated (tags in order, declared shapes ==   |
//| contract, exact counts, finite values, no trailing data).         |
//+------------------------------------------------------------------+
#ifndef PMW_BENCH_WEIGHT_LOADER_MQH
#define PMW_BENCH_WEIGHT_LOADER_MQH
#include "BenchmarkConfig.mqh"

struct BenchWeights
  {
   double W1[], b1[], W2[], b2[], W3[], b3[];       // row-major, in x out
   bool   valid;
  };

bool BenchReadLines(const string path, string &rows[], string &err)
  {
   ResetLastError();
   int h = FileOpen(path, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) { err = StringFormat("FILE_OPEN_FAILED:%s:err=%d", path, GetLastError()); return false; }
   ArrayResize(rows, 0);
   while(!FileIsEnding(h))
     {
      string s = FileReadString(h);
      StringTrimLeft(s); StringTrimRight(s);
      if(StringLen(s) == 0) continue;
      int n = ArraySize(rows); ArrayResize(rows, n + 1, 1024); rows[n] = s;
     }
   FileClose(h);
   return true;
  }

// strict number parser: optional sign, digits, '.', exponent; StringToDouble alone accepts garbage as 0
bool BenchParseNum(string s, double &v)
  {
   StringTrimLeft(s); StringTrimRight(s);
   int n = StringLen(s);
   if(n == 0) return false;
   int i = 0, digits = 0;
   ushort ch = StringGetCharacter(s, 0);
   if(ch == '+' || ch == '-') i++;
   for(; i < n; i++) { ch = StringGetCharacter(s, i); if(ch >= '0' && ch <= '9') digits++; else break; }
   if(i < n && StringGetCharacter(s, i) == '.') { i++; for(; i < n; i++) { ch = StringGetCharacter(s, i); if(ch >= '0' && ch <= '9') digits++; else break; } }
   if(digits == 0) return false;
   if(i < n && (StringGetCharacter(s, i) == 'e' || StringGetCharacter(s, i) == 'E'))
     {
      i++;
      if(i < n && (StringGetCharacter(s, i) == '+' || StringGetCharacter(s, i) == '-')) i++;
      int ed = 0;
      for(; i < n; i++) { ch = StringGetCharacter(s, i); if(ch >= '0' && ch <= '9') ed++; else break; }
      if(ed == 0) return false;
     }
   if(i != n) return false;
   v = StringToDouble(s);
   return MathIsValidNumber(v);
  }

bool BenchSection(const string &rows[], int &pos, const string tag, const int r, const int c, double &out[], string &err)
  {
   if(pos >= ArraySize(rows)) { err = "MISSING_SECTION:" + tag; return false; }
   string hp[];
   if(StringSplit(rows[pos], ',', hp) != 3 || hp[0] != "#" + tag) { err = "BAD_SECTION_TAG:" + rows[pos]; return false; }
   if(StringToInteger(hp[1]) != r || StringToInteger(hp[2]) != c) { err = StringFormat("BAD_SECTION_SHAPE:%s declared %sx%s expected %dx%d", tag, hp[1], hp[2], r, c); return false; }
   ArrayResize(out, r * c);
   for(int i = 0; i < r; i++)
     {
      int li = pos + 1 + i;
      if(li >= ArraySize(rows) || StringGetCharacter(rows[li], 0) == '#') { err = StringFormat("TRUNCATED_SECTION:%s row %d", tag, i); return false; }
      string p[];
      if(StringSplit(rows[li], ',', p) != c) { err = StringFormat("BAD_ROW_WIDTH:%s row %d", tag, i); return false; }
      for(int j = 0; j < c; j++)
        {
         double v;
         if(!BenchParseNum(p[j], v)) { err = StringFormat("MALFORMED_OR_NON_FINITE:%s[%d,%d]='%s'", tag, i, j, p[j]); return false; }
         out[i * c + j] = v;
        }
     }
   pos += 1 + r;
   return true;
  }

bool BenchLoadWeights(const string path, BenchWeights &w, string &err)
  {
   w.valid = false;
   string rows[];
   if(!BenchReadLines(path, rows, err)) return false;
   BenchWeights tmp;                                                  // never hand out a partially loaded set
   int pos = 0;
   if(!BenchSection(rows, pos, "W1", BENCH_INPUT_DIM, BENCH_HIDDEN1_DIM, tmp.W1, err)) return false;
   if(!BenchSection(rows, pos, "b1", 1, BENCH_HIDDEN1_DIM, tmp.b1, err)) return false;
   if(!BenchSection(rows, pos, "W2", BENCH_HIDDEN1_DIM, BENCH_HIDDEN2_DIM, tmp.W2, err)) return false;
   if(!BenchSection(rows, pos, "b2", 1, BENCH_HIDDEN2_DIM, tmp.b2, err)) return false;
   if(!BenchSection(rows, pos, "W3", BENCH_HIDDEN2_DIM, BENCH_OUTPUT_DIM, tmp.W3, err)) return false;
   if(!BenchSection(rows, pos, "b3", 1, BENCH_OUTPUT_DIM, tmp.b3, err)) return false;
   if(pos != ArraySize(rows)) { err = "TRAILING_DATA"; return false; }
   ArrayCopy(w.W1, tmp.W1); ArrayCopy(w.b1, tmp.b1); ArrayCopy(w.W2, tmp.W2); ArrayCopy(w.b2, tmp.b2); ArrayCopy(w.W3, tmp.W3); ArrayCopy(w.b3, tmp.b3);
   w.valid = true;
   return true;
  }

// X: n x BENCH_INPUT_DIM row-major, ref: n
bool BenchLoadVectors(const string path, double &X[], double &ref[], int &n, string &err)
  {
   n = 0;
   string rows[];
   if(!BenchReadLines(path, rows, err)) return false;
   if(ArraySize(rows) < 1) { err = "EMPTY_VECTORS_FILE"; return false; }
   string hp[];
   if(StringSplit(rows[0], ',', hp) != 3 || hp[0] != "#vectors") { err = "BAD_VECTORS_HEADER:" + rows[0]; return false; }
   if(StringToInteger(hp[1]) != BENCH_INPUT_DIM) { err = "VECTOR_WIDTH_MISMATCH:" + hp[1]; return false; }
   int m = (int)StringToInteger(hp[2]);
   if(m < 1 || m > BENCH_MAX_VECTORS) { err = "BAD_VECTOR_COUNT:" + hp[2]; return false; }
   if(ArraySize(rows) - 1 != m) { err = StringFormat("ROW_COUNT_MISMATCH:declared %d found %d", m, ArraySize(rows) - 1); return false; }
   double tx[], tr[];
   ArrayResize(tx, m * BENCH_INPUT_DIM); ArrayResize(tr, m);
   for(int i = 0; i < m; i++)
     {
      string p[];
      if(StringSplit(rows[i + 1], ',', p) != BENCH_INPUT_DIM + 1) { err = StringFormat("BAD_VECTOR_ROW_WIDTH:row %d", i); return false; }
      for(int j = 0; j <= BENCH_INPUT_DIM; j++)
        {
         double v;
         if(!BenchParseNum(p[j], v)) { err = StringFormat("MALFORMED_OR_NON_FINITE_VECTOR:row %d col %d", i, j); return false; }
         if(j < BENCH_INPUT_DIM) tx[i * BENCH_INPUT_DIM + j] = v; else tr[i] = v;
        }
     }
   ArrayCopy(X, tx); ArrayCopy(ref, tr); n = m;
   return true;
  }
#endif
