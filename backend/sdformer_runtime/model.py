"""SDformerFlow PyTorch port (PMW_SDFORMERFLOW_TORCH_PORT_V1) of the MQL5 implementation of article 20404 (D. Gizlyk) of the
published SDformerFlow (spatiotemporal Swin spikeformer for event-based flow), adapted to 1-D market sequences.

Layer graph = Trajectory.mqh CreateDescriptions (read from the downloaded source):
  input [120 bars x 9 descriptors] -> BatchNorm (+ noise in training) -> ConcatDiff (values + first differences, 18 ch)
  -> calendar embedding (D1 / MN1 phases, Mamba4Cast embedding position of the source) -> 64 channels (NSkills)
  -> SDformerFlow block: channels [64 -> 128 -> 64 | 64, 32, 16, 16], 2 spiking conv blocks, 3 MS-ResBlocks, then the nested U-structure
     of 4 levels with SDSA layers [2, 2, 6, 2], heads [3, 6, 12, 24], key dimension 32; each level = SDSA encoder -> spiking patch merge
     (stride 2) -> neck (next level, the deepest = MS-ResBlock) -> upsample -> concat with the encoder output -> spiking conv decoder
  -> STFS head: [64 x 120] -> [9 x 24] (tanh, BatchNorm) = forecast of the next 24 bar descriptors (self-supervised target).
Spiking neurons: single-step LIF (Heaviside with a sigmoid surrogate gradient) as in the spike-driven attention of the source;
SDSA = spike-driven self-attention (Q * column-sum(K * V), no softmax) inside shifted windows along time.
The native MQL5/OpenCL weights are NOT interchangeable with this port (different library, layout and kernels): own identity / checkpoints.
The source's Actor / Critic (RL on simulated account states) are not ported - PMW uses the encoder representation and the STFS forecast.
"""
from __future__ import annotations

import torch
from torch import nn

ARCH = {"history": 120, "descr": 9, "forecast": 24, "skills": 64, "conv_channels": [128, 64], "res_blocks": 3,
        "level_channels": [64, 32, 16, 16], "sdsa_layers": [2, 2, 6, 2], "heads": [3, 6, 12, 24], "dim_k": 32, "window": 8, "time_feats": 4}


class _Spike(torch.autograd.Function):
    @staticmethod
    def forward(ctx, v, alpha):
        ctx.save_for_backward(v)
        ctx.alpha = alpha
        return (v > 0).to(v.dtype)

    @staticmethod
    def backward(ctx, g):
        (v,) = ctx.saved_tensors
        s = torch.sigmoid(ctx.alpha * v)
        return g * ctx.alpha * s * (1 - s), None


class LIF(nn.Module):
    def __init__(self, threshold: float = 0.5, alpha: float = 4.0):
        super().__init__()
        self.th, self.alpha = threshold, alpha

    def forward(self, x):
        return _Spike.apply(x - self.th, self.alpha)


def conv_bn(ci, co, k=3, s=1):
    return nn.Sequential(nn.Conv1d(ci, co, k, s, padding=k // 2, bias=False), nn.BatchNorm1d(co))


class SpikeConvBlock(nn.Module):
    """LIF -> conv -> BN, LIF -> conv -> BN, residual (projected when channels change)."""

    def __init__(self, ci, co):
        super().__init__()
        self.a, self.b = nn.Sequential(LIF(), conv_bn(ci, co)), nn.Sequential(LIF(), conv_bn(co, co))
        self.skip = conv_bn(ci, co, 1) if ci != co else nn.Identity()

    def forward(self, x):
        return self.b(self.a(x)) + self.skip(x)


class MSResBlock(nn.Module):
    """Membrane-shortcut residual block (spikes on the branch, the membrane / real values on the shortcut)."""

    def __init__(self, c):
        super().__init__()
        self.f = nn.Sequential(LIF(), conv_bn(c, c), LIF(), conv_bn(c, c))

    def forward(self, x):
        return x + self.f(x)


class SDSA(nn.Module):
    """Spike-driven self-attention in (shifted) time windows + spiking MLP, both residual."""

    def __init__(self, c, heads, dk, window, shift):
        super().__init__()
        self.h, self.dk, self.w, self.shift = heads, dk, window, shift
        inner = heads * dk
        self.q = nn.Sequential(LIF(), conv_bn(c, inner, 1), LIF())
        self.k = nn.Sequential(LIF(), conv_bn(c, inner, 1), LIF())
        self.v = nn.Sequential(LIF(), conv_bn(c, inner, 1), LIF())
        self.attn_lif = LIF(threshold=0.5)
        self.proj = conv_bn(inner, c, 1)
        self.mlp = nn.Sequential(LIF(), conv_bn(c, 2 * c, 1), LIF(), conv_bn(2 * c, c, 1))

    def forward(self, x):
        B, C, L = x.shape
        s = self.w // 2 if self.shift else 0
        xs = torch.roll(x, -s, dims=2) if s else x
        pad = (-L) % self.w
        if pad:
            xs = nn.functional.pad(xs, (0, pad))
        Lp = xs.shape[2]
        q, k, v = (f(xs).view(B, self.h, self.dk, Lp // self.w, self.w) for f in (self.q, self.k, self.v))
        kv = (k * v).sum(dim=-1, keepdim=True)                   # column sum over the window (spike-driven, linear)
        a = self.attn_lif(q * kv).view(B, self.h * self.dk, Lp)
        a = self.proj(a)[:, :, :L]
        if s:
            a = torch.roll(a, s, dims=2)
        x = x + a
        return x + self.mlp(x)


class UBlock(nn.Module):
    def __init__(self, level, chans, layers, heads, dk, window):
        super().__init__()
        c = chans[level]
        self.enc = nn.Sequential(*[SDSA(c, heads[level], dk, window, shift=bool(i % 2)) for i in range(layers[level])])
        deepest = level == len(layers) - 1
        if deepest:
            self.down = self.neck = self.up = None
            self.core = MSResBlock(c)
        else:
            cn = chans[level + 1]
            self.down = nn.Sequential(LIF(), conv_bn(c, cn, 3, 2))           # spiking patch merge (stride 2)
            self.neck = UBlock(level + 1, chans, layers, heads, dk, max(2, window // 2))
            self.up = conv_bn(cn, c, 1)
            self.dec = SpikeConvBlock(2 * c, c)

    def forward(self, x):
        e = self.enc(x)
        if self.neck is None:
            return self.core(e)
        n = self.neck(self.down(e))
        u = self.up(nn.functional.interpolate(n, size=e.shape[2], mode="nearest"))
        return self.dec(torch.cat([e, u], dim=1))


class SDformerFlow(nn.Module):
    def __init__(self, arch: dict | None = None):
        super().__init__()
        a = {**ARCH, **(arch or {})}
        self.arch = a
        self.bn_in = nn.BatchNorm1d(a["descr"])
        self.embed = nn.Conv1d(2 * a["descr"] + a["time_feats"], a["skills"], 1)
        ch = [a["skills"]] + a["conv_channels"]
        self.stem = nn.Sequential(*[SpikeConvBlock(ch[i], ch[i + 1]) for i in range(len(a["conv_channels"]))],
                                  *[MSResBlock(ch[-1]) for _ in range(a["res_blocks"])])
        lc = a["level_channels"]
        self.to_level = conv_bn(ch[-1], lc[0], 1) if ch[-1] != lc[0] else nn.Identity()
        self.u = UBlock(0, lc, a["sdsa_layers"], a["heads"], a["dim_k"], a["window"])
        self.head_t = nn.Linear(a["history"], a["forecast"])
        self.head_c = nn.Conv1d(lc[0], a["descr"], 1)
        self.head_bn = nn.BatchNorm1d(a["descr"])
        self.noise = 0.01

    def encode(self, x, tf):
        """x [B, L, 9] (normalised descriptors), tf [B, L, 4] -> representation [B, 64, L]."""
        z = self.bn_in(x.transpose(1, 2))
        if self.training and self.noise > 0:
            z = z + self.noise * torch.randn_like(z)
        d = torch.diff(z, dim=2, prepend=z[:, :, :1])
        z = self.embed(torch.cat([z, d, tf.transpose(1, 2)], dim=1))
        return self.u(self.to_level(self.stem(z)))

    def forward(self, x, tf):
        r = self.encode(x, tf)
        y = torch.tanh(self.head_c(self.head_t(r)))               # [B, 9, 24]
        return self.head_bn(y).transpose(1, 2), r                # forecast [B, 24, 9], representation


def n_params(m: nn.Module) -> int:
    return sum(p.numel() for p in m.parameters())
