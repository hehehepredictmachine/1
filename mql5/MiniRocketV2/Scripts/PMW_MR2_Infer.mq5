//+------------------------------------------------------------------+
//| PMW_MR2_Infer.mq5 - native inference on an exported model and   |
//| fixture windows (round-trip T120). Loads MQL5\Files\PMW\model.bin|
//| (exported by `minirocket export-native`), transforms every window |
//| of PMW_MR2_FIXTURE.bin and writes raw scores to                   |
//| MQL5\Files\PMW\mr2_infer_scores.csv for comparison in Python      |
//| (`minirocket parity --native-scores ...`). No trading.            |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict
#include <PMW\PMW_MR2_Format.mqh>

input string InpModel = "PMW\\model.bin";
input string InpFixture = "PMW\\PMW_MR2_FIXTURE.bin";

void OnStart()
  {
   CMiniRocketV2 mr; CRidgeHeadV2 head; string err, sha;
   if(!MR2LoadModel(InpModel, false, mr, head, err, sha)) { Print("PMW_MR2_INFER FAIL load ", err); return; }
   uchar buf[]; MR2Section secs[]; string fsha;
   if(!MR2ReadFile(InpFixture, false, buf, err) || !MR2Index(buf, secs, err, fsha)) { Print("PMW_MR2_INFER FAIL fixture ", err); return; }
   int sm = MR2Find(secs, "META"), sx = MR2Find(secs, "XWIN");
   int L = MR2RdI4(buf, secs[sm].offset), n = MR2RdI4(buf, secs[sm].offset + 8);
   if(L != mr.m_L) { Print("PMW_MR2_INFER FAIL L mismatch"); return; }
   int h = FileOpen("PMW\\mr2_infer_scores.csv", FILE_WRITE | FILE_TXT | FILE_ANSI);
   for(int w = 0; w < n; w++)
     {
      float x[]; ArrayResize(x, L);
      for(int t = 0; t < L; t++) x[t] = MR2RdF4(buf, secs[sx].offset + 4 * (w * L + t));
      double ppv[], sc[];
      int e = mr.Transform(x, ppv);
      if(e != MR2_OK) { Print("PMW_MR2_INFER FAIL transform ", MR2ErrorText(e)); break; }
      head.Raw(ppv, sc);
      string line = IntegerToString(w);
      for(int i = 0; i < ArraySize(sc); i++) line += "," + DoubleToString(sc[i], 12);
      FileWriteString(h, line + "\r\n");
     }
   FileClose(h);
   Print("PMW_MR2_INFER OK model_sha=", sha, " windows=", n);
  }
