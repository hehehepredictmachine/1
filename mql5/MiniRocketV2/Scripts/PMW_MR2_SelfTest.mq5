//+------------------------------------------------------------------+
//| PMW_MR2_SelfTest.mq5 - native self-test (PMW-UPD-09 T110-T114,   |
//| T117 native column). No trading. Results -> Experts log and      |
//| MQL5\Files\PMW\mr2_selftest.txt. Exit code via log line          |
//| "PMW_MR2_SELFTEST RESULT=PASS|FAIL".                             |
//| Fixture: MQL5\Files\PMW\PMW_MR2_FIXTURE.bin exported by          |
//|   python -m masterquo structure-intelligence minirocket export-fixture |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict
#include <PMW\PMW_MR2_Format.mqh>

input string InpFixture = "PMW\\PMW_MR2_FIXTURE.bin";

int g_fail = 0;
int g_h = INVALID_HANDLE;
void Log(const string s) { Print(s); if(g_h != INVALID_HANDLE) FileWriteString(g_h, s + "\r\n"); }
void Check(const bool ok, const string what) { if(!ok) g_fail++; Log((ok ? "PASS " : "FAIL ") + what); }

void OnStart()
  {
   FolderCreate("PMW");
   g_h = FileOpen("PMW\\mr2_selftest.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
   CMiniRocketV2 mr;
   // T110: kernels
   bool kok = true;
   for(int k = 0; k < 84; k++)
     {
      int w[9]; ArrayInitialize(w, -1);
      for(int j = 0; j < 3; j++) w[mr.m_k[k][j]] = 2;
      int s = 0, plus = 0;
      for(int j = 0; j < 9; j++) { s += w[j]; if(w[j] == 2) plus++; }
      if(s != 0 || plus != 3) kok = false;
     }
   Check(kok && mr.m_k[0][0] == 0 && mr.m_k[0][1] == 1 && mr.m_k[0][2] == 2 && mr.m_k[83][0] == 6 && mr.m_k[83][2] == 8, "84 kernels lexicographic, six -1 / three +2, sum 0");
   // T111: golden layout
   Check(mr.Configure(128, 10000, 32) == MR2_OK, "Configure L128/10000/32");
   int gold[15] = {30, 19, 12, 12, 8, 4, 8, 4, 4, 3, 3, 3, 3, 3, 3};
   bool lok = (mr.m_nd == 15 && mr.m_F == 9996);
   for(int i = 0; i < 15 && lok; i++) lok = (mr.m_dil[i] == i + 1 && mr.m_cnt[i] == gold[i]);
   Check(lok, "golden layout F=9996 dilations 1..15 counts [30,19,12,12,8,4,8,4,4,3,3,3,3,3,3]");
   // T109: refusals
   float x[]; ArrayResize(x, 128); ArrayInitialize(x, 0.0f);
   double ppv[];
   Check(mr.Transform(x, ppv) == MR2_NOT_FITTED, "Transform before Fit -> NOT_FITTED");
   CMiniRocketV2 m2;
   Check(m2.Configure(8, 10000, 32) == MR2_INPUT_TOO_SHORT, "L<9 refused");
   // SplitMix64 reference values (seed 0)
   CSplitMix64 r(0);
   ulong v1 = r.Next();
   Check(v1 == 0xE220A8397B1DCDAF, "SplitMix64 seed0 first value");
   // fixture parity (frozen biases -> exact hit counts)
   uchar buf[]; string err, sha;
   if(!MR2ReadFile(InpFixture, false, buf, err)) { Log("SKIP fixture parity: " + err); }
   else
     {
      MR2Section secs[];
      if(!MR2Index(buf, secs, err, sha)) Check(false, "fixture index: " + err);
      else
        {
         int sm = MR2Find(secs, "META"), sx = MR2Find(secs, "XWIN"), sb = MR2Find(secs, "BIAS"), sh = MR2Find(secs, "HITS");
         int L = MR2RdI4(buf, secs[sm].offset), F = MR2RdI4(buf, secs[sm].offset + 4), n = MR2RdI4(buf, secs[sm].offset + 8);
         CMiniRocketV2 mf;
         mf.Configure(L, 10000, 32);
         Check(mf.m_F == F, "fixture layout F");
         ArrayResize(mf.m_bias, F);
         for(int i = 0; i < F; i++) mf.m_bias[i] = MR2RdF4(buf, secs[sb].offset + 4 * i);
         mf.m_fitted = true;
         int mism = 0, firstRow = -1, firstF = -1;
         for(int w = 0; w < n; w++)
           {
            float xw[]; ArrayResize(xw, L);
            for(int t = 0; t < L; t++) xw[t] = MR2RdF4(buf, secs[sx].offset + 4 * (w * L + t));
            int hits[], den[];
            mf.Counts(xw, hits, den);
            for(int f = 0; f < F; f++)
               if(hits[f] != MR2RdI4(buf, secs[sh].offset + 4 * (w * F + f))) { mism++; if(firstRow < 0) { firstRow = w; firstF = f; } }
           }
         Check(mism == 0, StringFormat("FROZEN_STATE_PARITY hit counts (%d windows): mismatches=%d first=(%d,%d)", n, mism, firstRow, firstF));
        }
     }
   Log(StringFormat("PMW_MR2_SELFTEST RESULT=%s failures=%d build=%d", g_fail == 0 ? "PASS" : "FAIL", g_fail, (int)TerminalInfoInteger(TERMINAL_BUILD)));
   if(g_h != INVALID_HANDLE) FileClose(g_h);
  }
