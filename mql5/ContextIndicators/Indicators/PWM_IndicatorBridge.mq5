//+------------------------------------------------------------------+
//| PWM_IndicatorBridge.mq5 - continuous export of ONE mapped buffer   |
//| of an indicator already on this chart (PMW-UPD-14 VS06). Export    |
//| only for mappings saved in the bot (mapping_id + mapper_version);  |
//| the bot accepts rows only when its mapping is VERIFIED_TECHNICAL   |
//| and treats them as AVAILABLE_UNVALIDATED (diagnostic / SHADOW).    |
//| Closed bars only (shift >= 1); observed time = export time, never  |
//| back-dated to an arrow's origin. Envelope pmw-bufbridge-1 in       |
//| MQL5\Files\PMW\PWM_BUFFER_BRIDGE.json (tmp + move). No plots, no   |
//| trading, no change of the source indicator.                        |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0
#include <PMW\PMW_ContextCore.mqh>

input string InpShortName = "";         // short name of the source indicator on this chart (exact)
input int    InpWindow = 0;             // chart sub-window of the source indicator
input int    InpBuffer = 0;             // buffer index (from the mapping)
input string InpMappingId = "";         // BM-... from the bot panel
input int    InpMapperVersion = 1;      // mapper_version from the bot panel
input int    InpRows = 50;              // closed bars per export
input int    InpTimerSec = 5;

long g_seq = 0, g_epoch = 0;
datetime g_lastBar = 0;

int OnInit()
  {
   if(InpShortName == "" || InpMappingId == "" || InpBuffer < 0 || InpBuffer > 511) return INIT_PARAMETERS_INCORRECT;
   g_epoch = (long)TimeGMT();                                   // new epoch per load -> bot resets its seq tracking
   IndicatorSetString(INDICATOR_SHORTNAME, "PWM_IndicatorBridge(" + InpMappingId + ")");
   EventSetTimer(MathMax(1, InpTimerSec));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason) { EventKillTimer(); }

int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[], const double &high[],
                const double &low[], const double &close[], const long &tick_volume[], const long &volume[], const int &spread[])
  { return rates_total; }

void OnTimer()
  {
   int h = ChartIndicatorGet(0, InpWindow, InpShortName);
   if(h == INVALID_HANDLE) { Print("PWM_IndicatorBridge SOURCE_NOT_FOUND ", InpShortName); return; }
   double v[]; datetime t[];
   ArraySetAsSeries(v, true); ArraySetAsSeries(t, true);
   int got = CopyBuffer(h, InpBuffer, 1, InpRows, v);
   int gt = CopyTime(_Symbol, _Period, 1, InpRows, t);
   IndicatorRelease(h);
   if(got <= 0 || gt != got) { Print("PWM_IndicatorBridge READ_FAILED err=", GetLastError()); return; }
   string rows = "[";
   for(int k = got - 1; k >= 0; k--)
     {
      string raw = (v[k] == EMPTY_VALUE || !MathIsValidNumber(v[k])) ? "null" : DoubleToString(v[k], 10);
      rows += StringFormat("%s{\"source_bar\":%I64d,\"raw\":%s}", k == got - 1 ? "" : ",", (long)t[k], raw);
     }
   rows += "]";
   g_seq++;
   string body = StringFormat("{\"schema_version\":\"pmw-bufbridge-1\",\"mapping_id\":\"%s\",\"mapper_version\":%d,\"source\":\"%s\",\"buffer\":%d,"
                              "\"symbol\":\"%s\",\"tf\":\"%s\",\"epoch\":%I64d,\"seq\":%I64d,\"heartbeat_utc\":%I64d,\"rows\":%s}",
                              PmwJsonEsc(InpMappingId), InpMapperVersion, PmwJsonEsc(InpShortName), InpBuffer, _Symbol, StringSubstr(EnumToString(_Period), 7),
                              g_epoch, g_seq, (long)TimeGMT(), rows);
   if(!PmwWriteEnvelope("pmw-bufbridge-1", body, "PMW\\PWM_BUFFER_BRIDGE.tmp", "PMW\\PWM_BUFFER_BRIDGE.json")) Print("PWM_IndicatorBridge WRITE_FAILED");
  }
