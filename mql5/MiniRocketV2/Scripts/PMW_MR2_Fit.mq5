//+------------------------------------------------------------------+
//| PMW_MR2_Fit.mq5 - small native Fit (transform biases + ridge)     |
//| on a TRAIN file exported by Python (`minirocket export-train`):   |
//| sections XWIN (n*L f4), YCLS (n*H i4, -1 missing), RVAL (n*H f8). |
//| DUAL Cholesky only when n <= 2048; otherwise blocked CG with a    |
//| diagonal preconditioner; non-convergence -> SOLVER_NOT_CONVERGED |
//| and NO model file is written (no activation). Data are never     |
//| silently truncated to 2048. Output: MQL5\Files\PMW\native_fit.txt |
//| with status, iterations and residuals. No trading.               |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict
#include <PMW\PMW_MR2_Format.mqh>

input string InpTrain = "PMW\\PMW_MR2_TRAIN.bin";
input double InpLambda = 100.0;
input double InpTol = 1e-6;
input int    InpMaxIter = 300;

void OnStart()
  {
   uchar buf[]; MR2Section secs[]; string err, sha;
   if(!MR2ReadFile(InpTrain, false, buf, err) || !MR2Index(buf, secs, err, sha)) { Print("PMW_MR2_FIT FAIL ", err); return; }
   int sm = MR2Find(secs, "META"), sx = MR2Find(secs, "XWIN"), sy = MR2Find(secs, "YCLS"), sr = MR2Find(secs, "RVAL");
   if(sm < 0 || sx < 0 || sy < 0 || sr < 0) { Print("PMW_MR2_FIT FAIL missing section"); return; }
   int L = MR2RdI4(buf, secs[sm].offset), n = MR2RdI4(buf, secs[sm].offset + 8), H = MR2RdI4(buf, secs[sm].offset + 12);
   float X[]; ArrayResize(X, n * L);
   for(int i = 0; i < n * L; i++) X[i] = MR2RdF4(buf, secs[sx].offset + 4 * i);
   CMiniRocketV2 mr;
   mr.Configure(L, 10000, 32);
   int frozen[];
   int e = mr.Fit(X, n, 1, frozen);
   if(e != MR2_OK) { Print("PMW_MR2_FIT FAIL transform fit ", MR2ErrorText(e)); return; }
   // features as uchar hit counts (bounded memory: n*F bytes)
   uchar hits[]; int den[];
   if(ArrayResize(hits, n * mr.m_F) != n * mr.m_F) { Print("PMW_MR2_FIT FAIL MEMORY_LIMIT"); return; }
   for(int w = 0; w < n; w++)
     {
      float x[]; ArrayResize(x, L); ArrayCopy(x, X, 0, w * L, L);
      int hh[], dd[];
      mr.Counts(x, hh, dd);
      for(int f = 0; f < mr.m_F; f++) hits[w * mr.m_F + f] = (uchar)hh[f];
      if(w == 0) ArrayCopy(den, dd);
     }
   CRidgeHeadV2 head; head.m_H = H; head.m_D = mr.m_F;
   head.FitScaler(hits, den, n);
   int fh = FileOpen("PMW\\native_fit.txt", FILE_WRITE | FILE_TXT | FILE_ANSI);
   bool allOk = true;
   for(int hd = 0; hd < H && allOk; hd++)
     {
      // targets: 3 class indicators + r, centred (rows with missing labels get the column mean -> zero contribution)
      double Y[]; ArrayResize(Y, n * 4); ArrayInitialize(Y, 0.0);
      double mean[4] = {0, 0, 0, 0}; int cntv = 0;
      for(int i = 0; i < n; i++)
        {
         int y = MR2RdI4(buf, secs[sy].offset + 4 * (i * H + hd));
         double rv = MR2RdF8(buf, secs[sr].offset + 8 * (i * H + hd));
         if(y < 0 || !MathIsValidNumber(rv)) continue;
         Y[i * 4 + y] = 1.0; Y[i * 4 + 3] = rv; cntv++;
         for(int k = 0; k < 4; k++) mean[k] += Y[i * 4 + k];
        }
      for(int k = 0; k < 4; k++) mean[k] /= MathMax(1, cntv);
      for(int i = 0; i < n; i++) for(int k = 0; k < 4; k++) Y[i * 4 + k] -= mean[k];
      double W[];
      string method;
      if(n <= MR2_DUAL_MAX_N)
        {
         method = "DUAL_CHOLESKY";
         if(!head.SolveDual(hits, den, n, Y, 4, InpLambda, W)) { allOk = false; FileWriteString(fh, "head " + IntegerToString(hd) + " DUAL_FAILED\r\n"); }
        }
      else
        {
         method = "CG_DIAG_PRECOND";
         ArrayResize(W, mr.m_F * 4);
         for(int k = 0; k < 4 && allOk; k++)
           {
            double y[], w[]; ArrayResize(y, n);
            for(int i = 0; i < n; i++) y[i] = Y[i * 4 + k];
            int it; double rr;
            bool ok = head.SolveCG(hits, den, n, y, InpLambda, w, InpTol, InpMaxIter, it, rr);
            FileWriteString(fh, StringFormat("head %d out %d %s iters=%d relres=%.3e\r\n", hd, k, ok ? "CONVERGED" : "SOLVER_NOT_CONVERGED", it, rr));
            if(!ok) allOk = false;
            for(int f = 0; f < mr.m_F; f++) W[f * 4 + k] = w[f];
           }
        }
      FileWriteString(fh, StringFormat("head %d method %s rows %d\r\n", hd, method, cntv));
     }
   FileWriteString(fh, allOk ? "STATUS=TRAINED_NATIVE_SMALL (no model activation; export/import via Python registry)\r\n" : "STATUS=SOLVER_NOT_CONVERGED (no model written)\r\n");
   FileClose(fh);
   Print("PMW_MR2_FIT ", allOk ? "OK" : "SOLVER_NOT_CONVERGED", " n=", n, " F=", mr.m_F);
  }
