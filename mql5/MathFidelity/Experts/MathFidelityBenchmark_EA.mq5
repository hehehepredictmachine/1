//+------------------------------------------------------------------+
//| MathFidelityBenchmark_EA.mq5 - diagnostic runner (no trading).    |
//| Same MLP 8-16-8-1, same weights, same vectors, same float64 Python |
//| reference for three engines: NATIVE matrix<double>, ALGLIB         |
//| CMatrixDouble (double), ONNX float32 via OnnxRun().                |
//| Inputs never come from the chart: results depend only on the files |
//| in MQL5\Files\PMW_MathFidelity\ and on this machine/terminal.      |
//| Output: benchmark_results.csv, error_detail.csv, run_manifest.json,|
//| benchmark_status.txt (RUNNING -> COMPLETE / INCOMPLETE / FAILED).  |
//| The benchmark runs once (from a one-shot timer after OnInit when   |
//| InpRunOnInit = true); OnTick does nothing.                         |
//+------------------------------------------------------------------+
#property strict
#include <PMW_MathFidelity\BenchmarkConfig.mqh>
#include <PMW_MathFidelity\WeightLoader.mqh>
#include <PMW_MathFidelity\MathEngineNative.mqh>
#include <PMW_MathFidelity\MathEngineAlglib.mqh>
#include <PMW_MathFidelity\MathEngineOnnx.mqh>
#include <PMW_MathFidelity\BenchmarkStats.mqh>

enum ENUM_BENCH_ORDER { ORDER_NATIVE_ALGLIB_ONNX = 0, ORDER_ONNX_ALGLIB_NATIVE = 1, ORDER_ALGLIB_ONNX_NATIVE = 2 };

input bool             InpRunOnInit = true;
input int              InpWarmupPasses = BENCH_DEFAULT_WARMUP;
input int              InpTimedPasses = BENCH_DEFAULT_TIMED;
input double           InpAbsTolDouble = 1e-9;      // NATIVE / ALGLIB vs float64 reference
input double           InpRelTolDouble = 1e-9;
input double           InpAbsTolOnnx = 1e-4;        // float32 graph: measured, tolerance only classifies
input double           InpRelTolOnnx = 1e-4;
input ENUM_BENCH_ORDER InpOrder = ORDER_NATIVE_ALGLIB_ONNX;
input int              InpBatchPasses = 500;        // batched timing cross-check (labelled separately)

#define NE 3
CMathEngineNative g_nat;
CMathEngineAlglib g_alg;
CMathEngineOnnx   g_onx;
BenchWeights      g_w;
double            g_X[], g_ref[];
int               g_n = 0;
bool              g_ready = false, g_done = false;
string            g_init_err = "", g_run_id = "";
string            g_names[NE] = {"NATIVE_MATRIX_DOUBLE", "ALGLIB_CMATRIXDOUBLE", "ONNX_FLOAT32"};

int PredictE(const int e, const int off, double &y)
  {
   if(e == 0) return g_nat.Predict(g_X, off, y);
   if(e == 1) return g_alg.Predict(g_X, off, y);
   return g_onx.Predict(g_X, off, y);
  }

void WriteText(const string f, const string txt)
  {
   int h = FileOpen(BenchPath(f), FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE) { PrintFormat("MathFidelity: cannot write %s err=%d", f, GetLastError()); return; }
   FileWriteString(h, txt);
   FileClose(h);
  }
void Status(const string state, const string msg)
  {
   WriteText(BENCH_STATUS_FILE, StringFormat("run_id=%s\nstate=%s\nupdated=%s\nversion=%s\nmessage=%s\n", g_run_id, state,
                                             TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS), BENCH_VERSION, msg));
  }
string Sha256(const string f)
  {
   int h = FileOpen(BenchPath(f), FILE_READ | FILE_BIN);
   if(h == INVALID_HANDLE) return "UNAVAILABLE";
   uchar data[], key[], out[];
   FileReadArray(h, data);
   FileClose(h);
   if(CryptEncode(CRYPT_HASH_SHA256, data, key, out) <= 0) return "UNAVAILABLE";
   string s = "";
   for(int i = 0; i < ArraySize(out); i++) s += StringFormat("%02x", out[i]);
   return s;
  }
string G(const double x) { return (x == EMPTY_VALUE || !MathIsValidNumber(x)) ? "" : StringFormat("%.17g", x); }

int OnInit()
  {
   MathSrand((uint)GetMicrosecondCount());
   g_run_id = StringFormat("%s-%05d", TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS), MathRand() % 100000);
   StringReplace(g_run_id, ".", ""); StringReplace(g_run_id, ":", ""); StringReplace(g_run_id, " ", "T");
   if(InpWarmupPasses < 0 || InpTimedPasses < 1 || InpTimedPasses > 100000 || InpBatchPasses < 0) return INIT_PARAMETERS_INCORRECT;
   string err;
   if(!BenchLoadWeights(BenchPath(BENCH_WEIGHTS_FILE), g_w, err)) g_init_err = "WEIGHTS:" + err;
   else if(!BenchLoadVectors(BenchPath(BENCH_VECTORS_FILE), g_X, g_ref, g_n, err)) g_init_err = "VECTORS:" + err;
   else if(!g_nat.Init(g_w, err)) g_init_err = "ENGINE NATIVE:" + err;
   else if(!g_alg.Init(g_w, err)) g_init_err = "ENGINE ALGLIB:" + err;
   else if(!g_onx.Init(BenchPath(BENCH_ONNX_FILE), err)) g_init_err = "ENGINE ONNX:" + err;
   if(g_init_err != "")
     {
      PrintFormat("MathFidelity: INIT FAILED - %s (no partial three-engine comparison is run)", g_init_err);
      Status("FAILED", g_init_err);
      return INIT_FAILED;
     }
   g_ready = true;
   PrintFormat("MathFidelity: ready - %d vectors, warm-up %d passes, timed %d passes (%I64d calls per engine)", g_n, InpWarmupPasses, InpTimedPasses,
               (long)InpTimedPasses * g_n);
   Status("READY", "attached; benchmark " + (InpRunOnInit ? "scheduled" : "not scheduled (InpRunOnInit=false)"));
   if(InpRunOnInit) EventSetTimer(1);
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { EventKillTimer(); g_onx.Release(); g_nat.Release(); g_alg.Release(); }
void OnTick() {}
void OnTimer()
  {
   EventKillTimer();
   if(g_ready && !g_done) { g_done = true; Run(); }
  }

void Run()
  {
   Status("RUNNING", "benchmark in progress");
   datetime started = TimeLocal();
   int order[NE];
   if(InpOrder == ORDER_NATIVE_ALGLIB_ONNX) { order[0] = 0; order[1] = 1; order[2] = 2; }
   else if(InpOrder == ORDER_ONNX_ALGLIB_NATIVE) { order[0] = 2; order[1] = 1; order[2] = 0; }
   else { order[0] = 1; order[1] = 2; order[2] = 0; }
   //--- 1) fidelity over the unique vectors (+ repeat-call determinism)
   double pred[]; int st[]; ArrayResize(pred, NE * g_n); ArrayResize(st, NE * g_n);
   bool determ[NE];
   for(int e = 0; e < NE; e++)
     {
      determ[e] = true;
      for(int i = 0; i < g_n; i++)
        {
         double y = 0, y2 = 0;
         st[e * g_n + i] = PredictE(e, i * BENCH_INPUT_DIM, y);
         pred[e * g_n + i] = y;
         int s2 = PredictE(e, i * BENCH_INPUT_DIM, y2);
         if(s2 != st[e * g_n + i] || (s2 == BENCH_OK && y2 != y)) determ[e] = false;
        }
     }
   CBenchErrorStats es[NE];
   string detail = "vector,x0,x1,x2,x3,x4,x5,x6,x7,reference";
   for(int e = 0; e < NE; e++) detail += StringFormat(",%s_pred,%s_abs_err,%s_rel_err,%s_ok", g_names[e], g_names[e], g_names[e], g_names[e]);
   detail += "\n";
   for(int e = 0; e < NE; e++) es[e].Reset(e < 2 ? InpAbsTolDouble : InpAbsTolOnnx, e < 2 ? InpRelTolDouble : InpRelTolOnnx);
   for(int i = 0; i < g_n; i++)
     {
      string row = IntegerToString(i);
      for(int j = 0; j < BENCH_INPUT_DIM; j++) row += "," + G(g_X[i * BENCH_INPUT_DIM + j]);
      row += "," + G(g_ref[i]);
      for(int e = 0; e < NE; e++)
        {
         double ae, re;
         bool ok = st[e * g_n + i] == BENCH_OK;
         es[e].Add(ok, pred[e * g_n + i], g_ref[i], ae, re);
         row += StringFormat(",%s,%s,%s,%s", ok ? G(pred[e * g_n + i]) : "", G(ae), G(re), ok ? "1" : BenchErrName(st[e * g_n + i]));
        }
      detail += row + "\n";
     }
   WriteText(BENCH_DETAIL_FILE, detail);
   //--- 2) warm-up (untimed) and 3) timed per-call blocks, one engine at a time
   CBenchLatency lat[NE];
   double batch_us[NE];
   for(int k = 0; k < NE; k++)
     {
      int e = order[k];
      double y;
      for(int p = 0; p < InpWarmupPasses; p++) for(int i = 0; i < g_n; i++) PredictE(e, i * BENCH_INPUT_DIM, y);
      lat[e].Reset(InpTimedPasses * g_n);
      for(int p = 0; p < InpTimedPasses; p++)
         for(int i = 0; i < g_n; i++)
           {
            int off = i * BENCH_INPUT_DIM;                              // input prepared outside the timed section
            ulong t0 = GetMicrosecondCount();
            int s = PredictE(e, off, y);
            ulong t1 = GetMicrosecondCount();
            lat[e].Add(t1 - t0, s == BENCH_OK);
           }
      // batched cross-check (separate method, reported separately)
      batch_us[e] = EMPTY_VALUE;
      if(InpBatchPasses > 0)
        {
         ulong b0 = GetMicrosecondCount();
         for(int p = 0; p < InpBatchPasses; p++) for(int i = 0; i < g_n; i++) PredictE(e, i * BENCH_INPUT_DIM, y);
         batch_us[e] = (double)(GetMicrosecondCount() - b0) / ((double)InpBatchPasses * g_n);
        }
     }
   //--- 4) results
   string res = "engine,run_id,mean_us,median_us,p95_us,p99_us,min_us,max_us,latency_samples,zero_us_samples,batch_mean_us,abs_err_mean,abs_err_max,"
                "rel_err_mean_pct,rel_err_max_pct,rmse,vectors_checked,vectors_passed,failed_calls,deterministic,abs_tol,rel_tol,numeric_status,engine_status\n";
   bool complete = true;
   for(int e = 0; e < NE; e++)
     {
      double mean = EMPTY_VALUE, med = EMPTY_VALUE, p95 = EMPTY_VALUE, p99 = EMPTY_VALUE, mn = EMPTY_VALUE, mx = EMPTY_VALUE;
      bool has = lat[e].Summary(mean, med, p95, p99, mn, mx);
      int failed = es[e].failed + lat[e].failed;
      string num = es[e].failed > 0 ? "FAILED_CALLS" : (es[e].passed == es[e].n ? "WITHIN_TOLERANCE" : "OUTSIDE_TOLERANCE");
      string eng = (failed == 0 && has) ? "OK" : "ERRORS";
      if(failed > 0 || !has) complete = false;
      res += StringFormat("%s,%s,%s,%s,%s,%s,%s,%s,%d,%d,%s,%s,%s,%s,%s,%s,%d,%d,%d,%s,%s,%s,%s,%s\n", g_names[e], g_run_id, G(mean), G(med), G(p95), G(p99), G(mn), G(mx),
                          lat[e].n, lat[e].zeros, G(batch_us[e]), G(es[e].MeanAbs()), G(es[e].ok ? es[e].max_abs : EMPTY_VALUE),
                          G(es[e].ok ? 100.0 * es[e].MeanRel() : EMPTY_VALUE), G(es[e].ok ? 100.0 * es[e].max_rel : EMPTY_VALUE), G(es[e].Rmse()),
                          es[e].n, es[e].passed, failed, determ[e] ? "1" : "0", G(es[e].abs_tol), G(es[e].rel_tol), num, eng);
     }
   WriteText(BENCH_RESULTS_FILE, res);
   string ord = g_names[order[0]] + ">" + g_names[order[1]] + ">" + g_names[order[2]];
   string man = StringFormat("{\n \"version\": \"%s\",\n \"run_id\": \"%s\",\n \"terminal_build\": %d,\n \"compiler_build\": %d,\n \"x64\": %s,\n"
                             " \"cpu_cores\": %d,\n \"memory_physical_mb\": %d,\n \"architecture\": \"MLP 8-16-8-1 ReLU/ReLU/linear, weights in x out\",\n"
                             " \"onnx\": {\"dtype\": \"float32\", \"input\": [1,8], \"output\": [1,1], \"run_flags\": \"ONNX_NO_CONVERSION\"},\n"
                             " \"files_sha256\": {\"model_weights.csv\": \"%s\", \"test_vectors.csv\": \"%s\", \"model.onnx\": \"%s\"},\n"
                             " \"vectors\": %d,\n \"warmup_passes\": %d,\n \"timed_passes\": %d,\n \"samples_per_engine\": %I64d,\n \"engine_order\": \"%s\",\n"
                             " \"timer\": \"GetMicrosecondCount() around one Predict() call; batch cross-check = total/(passes*vectors)\",\n"
                             " \"percentile\": \"linear interpolation at rank p*(n-1)\",\n \"rel_err_floor\": %g,\n \"started\": \"%s\",\n \"finished\": \"%s\",\n"
                             " \"complete\": %s,\n \"note\": \"diagnostic computation benchmark - no trading, no market data; latency is machine/build specific\"\n}\n",
                             BENCH_VERSION, g_run_id, (int)TerminalInfoInteger(TERMINAL_BUILD), __MQLBUILD__, TerminalInfoInteger(TERMINAL_X64) ? "true" : "false",
                             (int)TerminalInfoInteger(TERMINAL_CPU_CORES), (int)TerminalInfoInteger(TERMINAL_MEMORY_PHYSICAL), Sha256(BENCH_WEIGHTS_FILE),
                             Sha256(BENCH_VECTORS_FILE), Sha256(BENCH_ONNX_FILE), g_n, InpWarmupPasses, InpTimedPasses, (long)InpTimedPasses * g_n, ord, BENCH_REL_FLOOR,
                             TimeToString(started, TIME_DATE | TIME_SECONDS), TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS), complete ? "true" : "false");
   WriteText(BENCH_MANIFEST_FILE, man);
   Status(complete ? "COMPLETE" : "INCOMPLETE", complete ? "all engines ran every call" : "one or more engines reported failed calls - see benchmark_results.csv");
   PrintFormat("MathFidelity: run %s %s - results in MQL5\\Files\\%s\\%s (full precision in %s)", g_run_id, complete ? "COMPLETE" : "INCOMPLETE",
               BENCH_DIR, BENCH_RESULTS_FILE, BENCH_DETAIL_FILE);
  }
