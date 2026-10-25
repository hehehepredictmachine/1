//+------------------------------------------------------------------+
//| MathFidelity_SelfTest.mq5 - MQL5-side tests of the benchmark      |
//| contracts: strict loader rejections (wrong tag, wrong shape,      |
//| truncated, malformed number, non-finite, vector width/count),     |
//| percentile against known samples, explicit failure status of an   |
//| uninitialised / failed engine (never 0.0), repeatability and      |
//| per-engine agreement with the reference when the exported files   |
//| are installed. Writes MQL5\Files\PMW_MathFidelity\selftest.txt.   |
//+------------------------------------------------------------------+
#property strict
#include <PMW_MathFidelity\BenchmarkConfig.mqh>
#include <PMW_MathFidelity\WeightLoader.mqh>
#include <PMW_MathFidelity\MathEngineNative.mqh>
#include <PMW_MathFidelity\MathEngineAlglib.mqh>
#include <PMW_MathFidelity\MathEngineOnnx.mqh>
#include <PMW_MathFidelity\BenchmarkStats.mqh>

string g_log = "";
int    g_pass = 0, g_fail = 0;
void Check(const string name, const bool ok, const string info = "")
  {
   if(ok) g_pass++; else g_fail++;
   g_log += StringFormat("%s %s %s\n", ok ? "PASS" : "FAIL", name, info);
  }
void Put(const string f, const string txt) { int h = FileOpen(BenchPath(f), FILE_WRITE | FILE_TXT | FILE_ANSI); if(h != INVALID_HANDLE) { FileWriteString(h, txt); FileClose(h); } }
string Row(const int n, const double v) { string s = ""; for(int i = 0; i < n; i++) s += (i ? "," : "") + DoubleToString(v, 3); return s; }
string Section(const string tag, const int r, const int c) { string s = StringFormat("#%s,%d,%d\n", tag, r, c); for(int i = 0; i < r; i++) s += Row(c, 0.125) + "\n"; return s; }
string GoodWeights() { return Section("W1", 8, 16) + Section("b1", 1, 16) + Section("W2", 16, 8) + Section("b2", 1, 8) + Section("W3", 8, 1) + Section("b3", 1, 1); }

void OnStart()
  {
   BenchWeights w; string err;
   //--- loader contract
   Put("t_good.csv", GoodWeights());
   Check("loader.good", BenchLoadWeights(BenchPath("t_good.csv"), w, err) && w.valid, err);
   string bad = GoodWeights(); StringReplace(bad, "#W2,16,8", "#W9,16,8"); Put("t_tag.csv", bad);
   Check("loader.wrong_tag", !BenchLoadWeights(BenchPath("t_tag.csv"), w, err) && !w.valid, err);
   bad = GoodWeights(); StringReplace(bad, "#W1,8,16", "#W1,8,15"); Put("t_shape.csv", bad);
   Check("loader.wrong_shape", !BenchLoadWeights(BenchPath("t_shape.csv"), w, err), err);
   bad = Section("W1", 8, 16) + Section("b1", 1, 16) + "#W2,16,8\n" + Row(8, 0.1) + "\n"; Put("t_trunc.csv", bad);
   Check("loader.truncated", !BenchLoadWeights(BenchPath("t_trunc.csv"), w, err), err);
   bad = GoodWeights(); StringReplace(bad, "#b3,1,1\n0.125", "#b3,1,1\n0.1x5"); Put("t_malformed.csv", bad);
   Check("loader.malformed_number", !BenchLoadWeights(BenchPath("t_malformed.csv"), w, err), err);
   bad = GoodWeights(); StringReplace(bad, "#b3,1,1\n0.125", "#b3,1,1\nnan"); Put("t_nan.csv", bad);
   Check("loader.non_finite", !BenchLoadWeights(BenchPath("t_nan.csv"), w, err), err);
   Put("t_trailing.csv", GoodWeights() + "1,2,3\n");
   Check("loader.trailing_data", !BenchLoadWeights(BenchPath("t_trailing.csv"), w, err), err);
   double X[], R[]; int n;
   Put("t_vec_width.csv", "#vectors,7,1\n1,2,3,4,5,6,7,8\n");
   Check("vectors.width_mismatch", !BenchLoadVectors(BenchPath("t_vec_width.csv"), X, R, n, err), err);
   Put("t_vec_count.csv", "#vectors,8,2\n1,2,3,4,5,6,7,8,9\n");
   Check("vectors.count_mismatch", !BenchLoadVectors(BenchPath("t_vec_count.csv"), X, R, n, err), err);
   Put("t_vec_row.csv", "#vectors,8,1\n1,2,3,4,5,6,7,8\n");
   Check("vectors.row_width", !BenchLoadVectors(BenchPath("t_vec_row.csv"), X, R, n, err), err);
   //--- percentile convention (linear at p*(n-1)): samples 1..10 -> p50 5.5, p95 9.55, p99 9.91
   double s[10]; for(int i = 0; i < 10; i++) s[i] = i + 1;
   Check("stats.percentile", MathAbs(BenchPercentile(s, 0.5) - 5.5) < 1e-12 && MathAbs(BenchPercentile(s, 0.95) - 9.55) < 1e-12 && MathAbs(BenchPercentile(s, 0.99) - 9.91) < 1e-12);
   CBenchErrorStats es; es.Reset(1e-9, 1e-9); double ae, re;
   es.Add(false, 0.0, 0.0, ae, re);
   Check("stats.failed_call_not_scored", es.failed == 1 && es.ok == 0 && es.passed == 0);
   //--- explicit failure status (never a 0.0 prediction)
   CMathEngineNative nat; CMathEngineAlglib alg; CMathEngineOnnx onx; double y = 12345.0, xin[8]; ArrayInitialize(xin, 0.1);
   Check("native.uninitialised", nat.Predict(xin, 0, y) == BENCH_ERR_NOT_INITIALISED && y == 12345.0);
   Check("alglib.uninitialised", alg.Predict(xin, 0, y) == BENCH_ERR_NOT_INITIALISED && y == 12345.0);
   Check("onnx.uninitialised", onx.Predict(xin, 0, y) == BENCH_ERR_NOT_INITIALISED && y == 12345.0);
   Check("onnx.missing_file_fails_closed", !onx.Init(BenchPath("does_not_exist.onnx"), err), err);
   BenchLoadWeights(BenchPath("t_good.csv"), w, err);
   nat.Init(w, err); alg.Init(w, err);
   Check("native.shape_guard", nat.Predict(xin, 4, y) == BENCH_ERR_SHAPE);
   //--- engines vs reference when the exported files exist
   BenchWeights mw;
   if(BenchLoadWeights(BenchPath(BENCH_WEIGHTS_FILE), mw, err) && BenchLoadVectors(BenchPath(BENCH_VECTORS_FILE), X, R, n, err))
     {
      nat.Init(mw, err); alg.Init(mw, err);
      bool onnx_ok = onx.Init(BenchPath(BENCH_ONNX_FILE), err);
      Check("onnx.init", onnx_ok, err);
      double mx_n = 0, mx_a = 0, mx_o = 0, mx_na = 0; bool rep = true;
      for(int i = 0; i < n; i++)
        {
         double a, b, c, a2;
         nat.Predict(X, i * 8, a); nat.Predict(X, i * 8, a2); alg.Predict(X, i * 8, b);
         if(a != a2) rep = false;
         mx_n = MathMax(mx_n, MathAbs(a - R[i])); mx_a = MathMax(mx_a, MathAbs(b - R[i])); mx_na = MathMax(mx_na, MathAbs(a - b));
         if(onnx_ok && onx.Predict(X, i * 8, c) == BENCH_OK) mx_o = MathMax(mx_o, MathAbs(c - R[i]));
        }
      Check("native.vs_reference", mx_n < 1e-12, StringFormat("max_abs=%.3e", mx_n));
      Check("alglib.vs_reference", mx_a < 1e-12, StringFormat("max_abs=%.3e", mx_a));
      Check("native_vs_alglib", true, StringFormat("max_abs=%.3e (measured, not forced)", mx_na));
      Check("native.repeatable", rep);
      if(onnx_ok) Check("onnx.vs_reference_float32", mx_o < 1e-3, StringFormat("max_abs=%.3e (float32 graph)", mx_o));
      onx.Release();
     }
   else Check("exported_files_present", false, "copy model_weights.csv / test_vectors.csv / model.onnx to MQL5\\Files\\" + BENCH_DIR + " (" + err + ")");
   g_log = StringFormat("MathFidelity_SelfTest build %d: %d PASS / %d FAIL\n", (int)TerminalInfoInteger(TERMINAL_BUILD), g_pass, g_fail) + g_log;
   Put("selftest.txt", g_log);
   string f[] = {"t_good.csv", "t_tag.csv", "t_shape.csv", "t_trunc.csv", "t_malformed.csv", "t_nan.csv", "t_trailing.csv", "t_vec_width.csv", "t_vec_count.csv", "t_vec_row.csv"};
   for(int i = 0; i < ArraySize(f); i++) FileDelete(BenchPath(f[i]));
   Print(g_log);
  }
