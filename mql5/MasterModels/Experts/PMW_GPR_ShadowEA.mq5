//+------------------------------------------------------------------+
//| PMW_GPR_ShadowEA.mq5 - SHADOW forecast consumer (no trading).     |
//| Per new CLOSED bar: 1) score matured pending forecasts (exactly    |
//| once, close-to-close on the same basis as the target), 2) refit   |
//| (transactional), 3) forecast + diagnostics, 4) log EVERY forecast |
//| regardless of any confidence gate. Pending forecasts are a queue  |
//| (several outstanding when h > 1); they are not persisted across a |
//| restart - unscored ones are written as UNSCORED_RESTART on deinit.|
//| Files: MQL5\Files\PMW\gpr_forecasts.csv, PMW\gpr_scored.csv.      |
//| No OrderSend / CTrade / trade include anywhere in this program.  |
//+------------------------------------------------------------------+
#property strict
#include <PMW\PMW_GPR.mqh>

input int    InpWindow = 120;
input int    InpHorizon = 3;
input bool   InpAutoTune = true;
input int    InpRetuneEvery = 24;
input double InpZGate = 1.0;               // analytical eligibility |m|/sd >= z (diagnostic only)

struct PmwPending { long id; datetime t; double base, mean, sd; int bars_left; };
PmwPending g_q[];
CPmwGP g_gp;
datetime g_last = 0;
int g_since = 1000000, g_ff = INVALID_HANDLE, g_fs = INVALID_HANDLE;
long g_id = 0;
int g_scored = 0, g_in1 = 0, g_in2 = 0;

int OpenCsv(const string name, const string header)
  {
   int h = FileOpen(name, FILE_CSV | FILE_READ | FILE_WRITE | FILE_ANSI | FILE_SHARE_READ, ',');
   if(h == INVALID_HANDLE) { Print("PMW_GPR_ShadowEA: cannot open ", name, " err ", GetLastError()); return h; }
   if(FileSize(h) == 0) FileWriteString(h, header + "\r\n");
   FileSeek(h, 0, SEEK_END);
   return h;
  }

int OnInit()
  {
   if(InpWindow < 10 || InpHorizon < 1) return INIT_PARAMETERS_INCORRECT;
   FolderCreate("PMW");
   g_ff = OpenCsv("PMW\\gpr_forecasts.csv", "forecast_id,bar_time,symbol,tf,horizon,base_close,mean_logret,latent_var,observed_var,lo1,hi1,lo2,hi2,ell,signal_var,noise_var,jitter,n,x_mean,x_std,y_mean,y_std,lml,fit_status,health,z,eligible,version");
   g_fs = OpenCsv("PMW\\gpr_scored.csv", "forecast_id,bar_time,target_time,realized_logret,z_error,in_1sd,in_2sd,status");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   for(int i = 0; i < ArraySize(g_q); i++)
      if(g_fs != INVALID_HANDLE) FileWrite(g_fs, (string)g_q[i].id, TimeToString(g_q[i].t), "", "", "", "", "", "UNSCORED_RESTART");
   if(g_ff != INVALID_HANDLE) FileClose(g_ff);
   if(g_fs != INVALID_HANDLE) FileClose(g_fs);
  }

void ScorePending(const double close_now, const datetime t_now)
  {
   for(int i = ArraySize(g_q) - 1; i >= 0; i--)
     {
      g_q[i].bars_left--;
      if(g_q[i].bars_left > 0) continue;
      double real = MathLog(close_now / g_q[i].base);
      double z = g_q[i].sd > 0 ? (real - g_q[i].mean) / g_q[i].sd : EMPTY_VALUE;
      bool in1 = z != EMPTY_VALUE && MathAbs(z) <= 1, in2 = z != EMPTY_VALUE && MathAbs(z) <= 2;
      g_scored++; g_in1 += in1 ? 1 : 0; g_in2 += in2 ? 1 : 0;
      if(g_fs != INVALID_HANDLE)
        { FileWrite(g_fs, (string)g_q[i].id, TimeToString(g_q[i].t), TimeToString(t_now), DoubleToString(real, 12), DoubleToString(z, 6), in1 ? "1" : "0", in2 ? "1" : "0", "SCORED"); FileFlush(g_fs); }
      ArrayRemove(g_q, i, 1);                                        // scored exactly once
     }
  }

void OnTick()
  {
   datetime t1 = iTime(_Symbol, _Period, 1);
   if(t1 == 0 || t1 == g_last) return;                              // one cycle per new closed bar
   g_last = t1;
   double c[];
   ArraySetAsSeries(c, false);
   int need = InpWindow + InpHorizon + 3;
   int n = CopyClose(_Symbol, _Period, 1, need, c);                  // shift 1 = closed bars only, oldest first
   if(n < need) return;                                              // incomplete history: no forecast
   ScorePending(c[n - 1], t1);
   double x[], y[];
   int T = n - 1;
   string fit_status = "FIT_FAILED";
   if(PmwGprSamples(c, T, InpWindow, InpHorizon, x, y))
     {
      bool tune = InpAutoTune && g_since >= InpRetuneEvery;
      double e0 = g_gp.fit.valid ? g_gp.fit.ell : 4.0, s0 = g_gp.fit.valid ? g_gp.fit.sv : 0.1, n0 = g_gp.fit.valid ? g_gp.fit.nv : 0.5;
      if(g_gp.Refit(x, y, tune, e0, s0, n0)) { fit_status = "FITTED"; g_since = tune ? 0 : g_since + 1; }
     }
   double m = 0, lv = 0, ov = 0;
   if(fit_status != "FITTED" || !g_gp.Predict(MathLog(c[T] / c[T - 1]), m, lv, ov))
     {
      Comment("PMW GPR SHADOW (no trading)\nno forecast this bar: " + fit_status);
      return;                                                        // never a stale forecast presented as current
     }
   double sd = MathSqrt(ov), z = sd > 0 ? MathAbs(m) / sd : EMPTY_VALUE;
   string health = (g_gp.fit.jitter >= 1e-4 || g_gp.fit.degenerate) ? "DEGRADED" : "OK";
   g_id++;
   if(g_ff != INVALID_HANDLE)
     {
      FileWrite(g_ff, (string)g_id, TimeToString(t1, TIME_DATE | TIME_SECONDS), _Symbol, EnumToString((ENUM_TIMEFRAMES)_Period), IntegerToString(InpHorizon),
                DoubleToString(c[T], _Digits), DoubleToString(m, 12), DoubleToString(lv, 14), DoubleToString(ov, 14), DoubleToString(m - sd, 12),
                DoubleToString(m + sd, 12), DoubleToString(m - 2 * sd, 12), DoubleToString(m + 2 * sd, 12), DoubleToString(g_gp.fit.ell, 4),
                DoubleToString(g_gp.fit.sv, 8), DoubleToString(g_gp.fit.nv, 8), DoubleToString(g_gp.fit.jitter, 12), IntegerToString(g_gp.fit.n),
                DoubleToString(g_gp.fit.xm, 12), DoubleToString(g_gp.fit.xs, 12), DoubleToString(g_gp.fit.ym, 12), DoubleToString(g_gp.fit.ys, 12),
                DoubleToString(g_gp.fit.lml, 6), fit_status, health, DoubleToString(z, 4), (z != EMPTY_VALUE && z >= InpZGate) ? "ELIGIBLE_SHADOW" : "NOT_ELIGIBLE",
                PMW_GPR_VERSION);
      FileFlush(g_ff);
     }
   int k = ArraySize(g_q);
   ArrayResize(g_q, k + 1);
   g_q[k].id = g_id; g_q[k].t = t1; g_q[k].base = c[T]; g_q[k].mean = m; g_q[k].sd = sd; g_q[k].bars_left = InpHorizon;
   double edge = c[T] * (MathExp(m) - 1.0);
   Comment(StringFormat("PMW GPR SHADOW (no trading)\nmean %.2f bp  sd %.2f bp  z %.2f  edge %.5f\nscored %d  cov1 %.1f%%  cov2 %.1f%% (nominal 68.3/95.4)",
                        m * 1e4, sd * 1e4, z, edge, g_scored, g_scored ? 100.0 * g_in1 / g_scored : 0, g_scored ? 100.0 * g_in2 / g_scored : 0));
  }
