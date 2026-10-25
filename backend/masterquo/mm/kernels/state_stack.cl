// PMW-MM-STATESTACK-CL-1 - state stack shift + stack correlation (OpenCL C 1.2, float32).
// Layout: stack row-major [S][D], slot 0 = TOP = newest descriptor, slot S-1 = oldest. valid[S] (int, 1 = slot holds a state).
// Push uses TWO buffers (src -> dst, ping-pong on the host): no work-item reads a cell another work-item writes in the same launch,
// so no intra-launch race and no barrier beyond the launch boundary is needed. The oldest slot is dropped (S-1 <- S-2).
__kernel void stack_push(__global const float* src, __global const int* vsrc, __global const float* desc,
                         __global float* dst, __global int* vdst, const int S, const int D)
{
    const int gid = get_global_id(0);
    if (gid >= S * D) return;
    const int s = gid / D, d = gid - s * D;
    dst[gid] = (s == 0) ? desc[d] : src[(s - 1) * D + d];
    if (d == 0) vdst[s] = (s == 0) ? 1 : vsrc[s - 1];
}

// corr[s] = dot(q, stack[s]) for valid slots (raw dot product); l2norm != 0 -> cosine (explicit variant). Invalid slot -> 0.
__kernel void stack_corr(__global const float* q, __global const float* stack, __global const int* valid,
                         __global float* out, const int S, const int D, const int l2norm)
{
    const int s = get_global_id(0);
    if (s >= S) return;
    if (!valid[s]) { out[s] = 0.0f; return; }
    float acc = 0.0f, nq = 0.0f, ns = 0.0f;
    for (int d = 0; d < D; d++) { const float a = q[d], b = stack[s * D + d]; acc += a * b; nq += a * a; ns += b * b; }
    out[s] = l2norm ? acc / (sqrt(nq) * sqrt(ns) + 1e-12f) : acc;
}
