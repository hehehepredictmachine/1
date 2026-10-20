//+------------------------------------------------------------------+
//| MQ_FlowCollector.mq5 - read-only collector (PMW-UPD-11 FF06).     |
//| Creates own handles (iCustom) of MQ_HeikinFlow / MQ_StopDistance /|
//| MQ_SRChannels, checks BarsCalculated, copies CLOSED bars (shift   |
//| >= 1) with CopyTime/CopyBuffer (oldest-first), verifies the time  |
//| map before/after the batch (retry on change) and writes           |
//| MQL5\Files\PMW\PMW_FLOW_EXPORT.txt atomically (tmp + FileMove)    |
//| with a SHA-256 trailer. No orders, no DLL, no network.            |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input int    InpBars = 0;          // 0 = full history (needed for parity: seed origin = first chart bar)
input int    InpMA1 = 0;
input int    InpP1 = 10;
input int    InpMA2 = 0;
input int    InpP2 = 5;
input int    InpSDPeriod = 20;
input int    InpSDMethod = 1;
input double InpSDFactor = 1.5;

string Num(const double v) { return (v == EMPTY_VALUE || !MathIsValidNumber(v)) ? "" : DoubleToString(v, 10); }

bool CopyAll(const int h, const int buf, const int n, double &out[])
  {
   ArraySetAsSeries(out, false);
   return CopyBuffer(h, buf, 1, n, out) == n;
  }

void OnStart()
  {
   int hHF = iCustom(_Symbol, _Period, "PMW\\MQ_HeikinFlow", InpMA1, InpP1, InpMA2, InpP2, 1.0);
   int hSD = iCustom(_Symbol, _Period, "PMW\\MQ_StopDistance", InpSDPeriod, InpSDMethod, InpSDFactor);
   int hSR = iCustom(_Symbol, _Period, "PMW\\MQ_SRChannels");
   if(hHF == INVALID_HANDLE || hSD == INVALID_HANDLE || hSR == INVALID_HANDLE) { Print("MQ_FlowCollector HANDLE_FAILED ", GetLastError()); return; }
   for(int w = 0; w < 50 && (BarsCalculated(hHF) <= 0 || BarsCalculated(hSD) <= 0 || BarsCalculated(hSR) <= 0); w++) Sleep(200);
   int total = Bars(_Symbol, _Period);
   int n = (InpBars <= 0) ? total - 1 : MathMin(InpBars, total - 1);
   bool fromOrigin = (n == total - 1);
   for(int attempt = 0; attempt < 3; attempt++)
     {
      datetime t0[], t1[];
      MqlRates r[];
      ArraySetAsSeries(t0, false); ArraySetAsSeries(r, false);
      if(CopyTime(_Symbol, _Period, 1, n, t0) != n || CopyRates(_Symbol, _Period, 1, n, r) != n) { Print("MQ_FlowCollector COPY_FAILED"); return; }
      double ho[], hh[], hl[], hc[], sr[], sa[], sg[], s0[], s1[], s2[], s3[], s4[], s5[];
      bool ok = CopyAll(hHF, 12, n, ho) && CopyAll(hHF, 13, n, hh) && CopyAll(hHF, 14, n, hl) && CopyAll(hHF, 15, n, hc)
                && CopyAll(hSD, 0, n, sr) && CopyAll(hSD, 1, n, sa) && CopyAll(hSD, 2, n, sg)
                && CopyAll(hSR, 0, n, s0) && CopyAll(hSR, 1, n, s1) && CopyAll(hSR, 2, n, s2) && CopyAll(hSR, 3, n, s3) && CopyAll(hSR, 4, n, s4) && CopyAll(hSR, 5, n, s5);
      ArraySetAsSeries(t1, false);
      if(!ok || CopyTime(_Symbol, _Period, 1, n, t1) != n || t1[0] != t0[0] || t1[n - 1] != t0[n - 1]) { Sleep(500); continue; }   // bar changed -> retry
      string body = StringFormat("{\"schema\":\"PMW-FLOW-EXPORT-1\",\"seq\":%I64d,\"symbol\":\"%s\",\"tf\":\"%s\",\"point\":%.10f,\"tick\":%.10f,"
                                 "\"clock_basis\":\"BROKER_WALL_TIME\",\"written_at_utc\":%I64d,\"seed_origin\":%s,\"build\":%d,"
                                 "\"heikin\":{\"ma1\":\"%s\",\"p1\":%d,\"ma2\":\"%s\",\"p2\":%d},\"stopdistance\":{\"period\":%d,\"method\":\"%s\",\"factor\":%.6f}}\n",
                                 (long)TimeGMT(), _Symbol, StringSubstr(EnumToString(_Period), 7), _Point, SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE),
                                 (long)TimeGMT(), fromOrigin ? IntegerToString((long)t0[0]) : "null", (int)TerminalInfoInteger(TERMINAL_BUILD),
                                 InpMA1 == 0 ? "EMA" : InpMA1 == 1 ? "SMA" : InpMA1 == 2 ? "SMMA" : "LWMA", InpP1,
                                 InpMA2 == 0 ? "EMA" : InpMA2 == 1 ? "SMA" : InpMA2 == 2 ? "SMMA" : "LWMA", InpP2, InpSDPeriod, InpSDMethod == 1 ? "SMA" : "EMA", InpSDFactor);
      for(int i = 0; i < n; i++)
         body += StringFormat("%I64d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n", (long)t0[i], Num(r[i].open), Num(r[i].high), Num(r[i].low), Num(r[i].close),
                              Num(ho[i]), Num(hh[i]), Num(hl[i]), Num(hc[i]), Num(sr[i]), Num(sa[i]), Num(sg[i]), Num(s0[i]), Num(s1[i]), Num(s2[i]), Num(s3[i]), Num(s4[i]), Num(s5[i]));
      uchar data[], key[], dg[];
      StringToCharArray(body, data, 0, StringLen(body), CP_UTF8);
      CryptEncode(CRYPT_HASH_SHA256, data, key, dg);
      string hex = "";
      for(int k = 0; k < ArraySize(dg); k++) hex += StringFormat("%02x", dg[k]);
      FolderCreate("PMW");
      int fh = FileOpen("PMW\\PMW_FLOW_EXPORT.tmp", FILE_WRITE | FILE_BIN);
      if(fh == INVALID_HANDLE) { Print("MQ_FlowCollector OPEN_FAILED"); return; }
      FileWriteArray(fh, data, 0, ArraySize(data));
      uchar tail[]; string ts = "#sha256=" + hex + "\n"; StringToCharArray(ts, tail, 0, StringLen(ts), CP_UTF8);
      FileWriteArray(fh, tail, 0, ArraySize(tail));
      FileClose(fh);
      if(!FileMove("PMW\\PMW_FLOW_EXPORT.tmp", 0, "PMW\\PMW_FLOW_EXPORT.txt", FILE_REWRITE)) Print("MQ_FlowCollector MOVE_FAILED");
      else Print("MQ_FlowCollector OK rows=", n);
      return;
     }
   Print("MQ_FlowCollector INCOHERENT_BATCH (bar changed during copy, 3 attempts)");
  }
