//+------------------------------------------------------------------+
//| PMW_StateStack.mqh - state stack shift + dot-product correlation  |
//| on OpenCL with a CPU reference of identical semantics             |
//| (PMW-MM-EVENTENGINE-1; kernel source identical to                 |
//| backend/masterquo/mm/kernels/state_stack.cl). Slot 0 = newest.    |
//| Push uses two device buffers (ping-pong): no cell is read and     |
//| written in the same launch. backend_used reports what really ran. |
//+------------------------------------------------------------------+
#ifndef PMW_STATESTACK_MQH
#define PMW_STATESTACK_MQH

const string PMW_STACK_CL =
   "__kernel void stack_push(__global const float* src, __global const int* vsrc, __global const float* desc,"
   " __global float* dst, __global int* vdst, const int S, const int D)"
   "{ const int gid = get_global_id(0); if (gid >= S * D) return; const int s = gid / D, d = gid - s * D;"
   "  dst[gid] = (s == 0) ? desc[d] : src[(s - 1) * D + d]; if (d == 0) vdst[s] = (s == 0) ? 1 : vsrc[s - 1]; }"
   "__kernel void stack_corr(__global const float* q, __global const float* stack, __global const int* valid,"
   " __global float* out, const int S, const int D, const int l2norm)"
   "{ const int s = get_global_id(0); if (s >= S) return; if (!valid[s]) { out[s] = 0.0f; return; }"
   "  float acc = 0.0f, nq = 0.0f, ns = 0.0f; for (int d = 0; d < D; d++) { const float a = q[d], b = stack[s * D + d]; acc += a * b; nq += a * a; ns += b * b; }"
   "  out[s] = l2norm ? acc / (sqrt(nq) * sqrt(ns) + 1e-12f) : acc; }";

class CPmwStateStack
  {
public:
   int    S, D;
   string backend_used;
   float  buf[];
   int    valid[];
   int    ctx, prg, kpush, kcorr, bbuf[2], bval[2], bdesc, bout, cur;
   bool   cl;
          CPmwStateStack() : S(0), D(0), backend_used("CPU"), ctx(INVALID_HANDLE), prg(INVALID_HANDLE), kpush(INVALID_HANDLE), kcorr(INVALID_HANDLE),
                             bdesc(INVALID_HANDLE), bout(INVALID_HANDLE), cur(0), cl(false)
     { bbuf[0] = bbuf[1] = bval[0] = bval[1] = INVALID_HANDLE; }
         ~CPmwStateStack() { Free(); }
   bool   Init(const int s, const int d, const bool try_opencl)
     {
      if(s < 1 || d < 1) return false;
      S = s; D = d; cl = false; backend_used = "CPU";
      ArrayResize(buf, S * D); ArrayInitialize(buf, 0.0f); ArrayResize(valid, S); ArrayInitialize(valid, 0);
      if(try_opencl) cl = InitCL();
      if(cl) backend_used = "OPENCL";
      return true;
     }
   bool   InitCL()
     {
      ctx = CLContextCreate(CL_USE_GPU_ONLY);
      if(ctx == INVALID_HANDLE) return false;
      string log;
      prg = CLProgramCreate(ctx, PMW_STACK_CL, log);
      if(prg == INVALID_HANDLE) { Print("PMW stack CL build: ", log); CLContextFree(ctx); return false; }
      kpush = CLKernelCreate(prg, "stack_push"); kcorr = CLKernelCreate(prg, "stack_corr");
      for(int k = 0; k < 2; k++) { bbuf[k] = CLBufferCreate(ctx, S * D * sizeof(float), CL_MEM_READ_WRITE); bval[k] = CLBufferCreate(ctx, S * sizeof(int), CL_MEM_READ_WRITE); }
      bdesc = CLBufferCreate(ctx, D * sizeof(float), CL_MEM_READ_WRITE);
      bout = CLBufferCreate(ctx, S * sizeof(float), CL_MEM_READ_WRITE);
      if(kpush == INVALID_HANDLE || kcorr == INVALID_HANDLE || bdesc == INVALID_HANDLE || bout == INVALID_HANDLE) { Free(); return false; }
      cur = 0;
      for(int k = 0; k < 2; k++) { CLBufferWrite(bbuf[k], buf); CLBufferWrite(bval[k], valid); }
      return true;
     }
   void   Free()
     {
      for(int k = 0; k < 2; k++)
        {
         if(bbuf[k] != INVALID_HANDLE) CLBufferFree(bbuf[k]);
         if(bval[k] != INVALID_HANDLE) CLBufferFree(bval[k]);
         bbuf[k] = INVALID_HANDLE; bval[k] = INVALID_HANDLE;
        }
      if(bdesc != INVALID_HANDLE) CLBufferFree(bdesc);
      if(bout != INVALID_HANDLE) CLBufferFree(bout);
      if(kpush != INVALID_HANDLE) CLKernelFree(kpush);
      if(kcorr != INVALID_HANDLE) CLKernelFree(kcorr);
      if(prg != INVALID_HANDLE) CLProgramFree(prg);
      if(ctx != INVALID_HANDLE) CLContextFree(ctx);
      bdesc = bout = kpush = kcorr = prg = ctx = INVALID_HANDLE;
      cl = false; backend_used = "CPU";
     }
   // GPU -> CPU fallback: the live state is in the current device buffers; read it back, or reset (reported) when that fails too
   void   FallbackToCPU()
     {
      bool ok = cl && CLBufferRead(bbuf[cur], buf) && CLBufferRead(bval[cur], valid);
      if(!ok) { ArrayInitialize(buf, 0.0f); ArrayInitialize(valid, 0); Print("PMW stack: OpenCL state lost, CPU stack reset"); }
      Free();
     }
   bool   Push(const float &desc[])
     {
      if(ArraySize(desc) != D) return false;
      for(int d = 0; d < D; d++) if(!MathIsValidNumber(desc[d])) return false;
      if(cl)
        {
         CLBufferWrite(bdesc, desc);
         int src = cur, dst = 1 - cur;
         CLSetKernelArgMem(kpush, 0, bbuf[src]); CLSetKernelArgMem(kpush, 1, bval[src]); CLSetKernelArgMem(kpush, 2, bdesc);
         CLSetKernelArgMem(kpush, 3, bbuf[dst]); CLSetKernelArgMem(kpush, 4, bval[dst]); CLSetKernelArg(kpush, 5, S); CLSetKernelArg(kpush, 6, D);
         uint off[1] = {0}, work[1]; work[0] = (uint)(S * D);
         if(!CLExecute(kpush, 1, off, work)) { Print("PMW stack push kernel failed ", GetLastError()); FallbackToCPU(); return Push(desc); }
         cur = dst;
         return true;
        }
      for(int s = S - 1; s >= 1; s--) { for(int d = 0; d < D; d++) buf[s * D + d] = buf[(s - 1) * D + d]; valid[s] = valid[s - 1]; }
      for(int d = 0; d < D; d++) buf[d] = desc[d];
      valid[0] = 1;
      return true;
     }
   bool   Corr(const float &q[], const bool l2, float &out[])
     {
      ArrayResize(out, S);
      if(cl)
        {
         CLBufferWrite(bdesc, q);
         CLSetKernelArgMem(kcorr, 0, bdesc); CLSetKernelArgMem(kcorr, 1, bbuf[cur]); CLSetKernelArgMem(kcorr, 2, bval[cur]); CLSetKernelArgMem(kcorr, 3, bout);
         CLSetKernelArg(kcorr, 4, S); CLSetKernelArg(kcorr, 5, D); CLSetKernelArg(kcorr, 6, l2 ? 1 : 0);
         uint off[1] = {0}, work[1]; work[0] = (uint)S;
         if(!CLExecute(kcorr, 1, off, work)) return false;
         return CLBufferRead(bout, out) > 0;
        }
      for(int s = 0; s < S; s++)
        {
         if(!valid[s]) { out[s] = 0.0f; continue; }
         double a = 0, nq = 0, ns = 0;
         for(int d = 0; d < D; d++) { a += q[d] * buf[s * D + d]; nq += q[d] * q[d]; ns += buf[s * D + d] * buf[s * D + d]; }
         out[s] = (float)(l2 ? a / (MathSqrt(nq) * MathSqrt(ns) + 1e-12) : a);
        }
      return true;
     }
  };
#endif
