"""Structure-move networks (PMW-UPD-07 R10-R11) - pure numpy with exact, hand-written backward passes.

Three NEW families for the same task (STRUCTURE_MOVE_M1_V1; the old two-layer SEWSNN and ResNet1D in lab/nets.py stay unchanged):
  MQ_RESNEXT1D_V2       stem conv1x1 + ReLU, bottlenecks [1x1 reduce -> ReLU -> grouped causal Conv1D k=3 (dilation) -> ReLU -> 1x1 expand]
                        + shortcut (identity, or a 1x1 PROJECTION when the width changes), ReLU after the add. Baseline ANN.
  MQ_SEW_RESNET1D_V2    encoder = causal conv k=3 on the analogue inputs + LIF (spikes). Blocks: branch = LIF(1x1(LIF(conv k=3 dil(x))));
                        SEW ADD: out = shortcut + branch with NO threshold on the sum (values 0/1/2/... - not binary spikes).
  MQ_SEW_RESNEXT_EB_V1  the same SEW rules with a grouped bottleneck branch LIF(1x1 exp(LIF(gconv(LIF(1x1 red(x)))))) and an explicit
                        activity penalty lambda * sum_l w_l * mean(spikes_l) whose gradient flows to the right layers (energy-BALANCED here =
                        an explicit activity regulariser, not a measured energy saving).
Adaptation 1D for financial data (own design), not a faithful port of the ImageNet models. One SNN step = one real closed M1 bar.
Layout: tensors (N, C, T) inside the model; `to_nct` adapts (N, T, C) inputs explicitly (recorded in the manifest).
Causal convolutions: left padding only; receptive field recorded. Head: concat(last step, mean over steps) -> per horizon 3 logits
(DOWN/FLAT/UP) and quantiles with enforced order q10 = q50 - softplus(a), q90 = q50 + softplus(b).
LIF (default beta .9, theta 1, reset by subtraction, reset path DETACHED - a documented approximation):
  u_t = beta*v_(t-1) + I_t ; s_t = H(u_t - theta) ; v_t = u_t - stop_gradient(s_t)*theta
  surrogate dS/du = (alpha/2) / (1 + (pi/2*alpha*(u-theta))^2)  (derivative of 1/pi*atan(pi/2*alpha*x) + 1/2), alpha = 2.
State policy RESET_EACH_WINDOW: membranes start at 0 for every independent window (train and predict identical); nothing is carried
across overlapping windows, items or instruments. Zero input does NOT skip the decay / bias / shortcut.
connect_f: only "ADD" is implemented in this update (AND/IAND are a separate versioned update - the slot is in the manifest).
Loss per horizon with a valid label: CE(direction) + w_q * mean(pinball q10/q50/q90) on r_h/ATR, averaged over available heads.
Telemetry: params, dense MACs, estimated SynOps (spikes x fan-out of the consuming conv; proxy - numpy on CPU multiplies zeros too),
firing rates per LIF layer, latency p50/p95; energy_j = null, NOT_MEASURED (no hardware instrument).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from .nets import Adam, softmax
from .scalp_net import causal_cols, causal_uncols, clip_grads

VERSION = "MQ-STRUCT-NETS-1.0.0"
FAMILIES = ("MQ_RESNEXT1D_V2", "MQ_SEW_RESNET1D_V2", "MQ_SEW_RESNEXT_EB_V1")
CLASSES = ("DOWN", "FLAT", "UP")
QUANTS = (0.1, 0.5, 0.9)
CPU_PROFILE = {"widths": [32, 64, 64], "blocks_per_stage": 2, "cardinality": 4, "k": 3, "dilations": [1, 2, 4], "beta": 0.9, "theta": 1.0,
               "alpha": 2.0, "lambda": 0.0, "w_q": 0.5, "clip": 1.0, "weight_decay": 1e-4, "horizons": [3, 5, 15], "connect_f": "ADD",
               "state_policy": "RESET_EACH_WINDOW", "layout": "NCT"}


def to_nct(x: np.ndarray, layout: str) -> np.ndarray:
    if layout == "NCT":
        return x
    if layout == "NTC":
        return np.transpose(x, (0, 2, 1))
    raise ValueError("LAYOUT_UNKNOWN")


def softplus(x):
    return np.where(x > 20, x, np.log1p(np.exp(np.minimum(x, 20))))


def sigmoid(x):
    return 0.5 * (1 + np.tanh(0.5 * x))


# ----------------------------------------------------------------------------- grouped causal conv
def gconv_fwd(x, W, b, k, d, groups):
    n, c, L = x.shape
    f = W.shape[0]
    cg, fg = c // groups, f // groups
    outs, cols = [], []
    for g in range(groups):
        cl = causal_cols(x[:, g * cg:(g + 1) * cg], k, d)
        outs.append(np.einsum("fk,nkl->nfl", W[g * fg:(g + 1) * fg], cl))
        cols.append(cl)
    return np.concatenate(outs, axis=1) + b[None, :, None], cols


def gconv_bwd(dout, x, W, cols, k, d, groups):
    n, c, L = x.shape
    f = W.shape[0]
    cg, fg = c // groups, f // groups
    dx, dW = np.zeros_like(x), np.zeros_like(W)
    for g in range(groups):
        dg = dout[:, g * fg:(g + 1) * fg]
        dW[g * fg:(g + 1) * fg] = np.einsum("nfl,nkl->fk", dg, cols[g])
        dx[:, g * cg:(g + 1) * cg] = causal_uncols(np.einsum("fk,nfl->nkl", W[g * fg:(g + 1) * fg], dg), cg, L, k, d)
    return dx, dW, dout.sum(axis=(0, 2))


# ----------------------------------------------------------------------------- LIF with BPTT
def surrogate(u, theta, alpha):
    x = u - theta
    return (alpha / 2.0) / (1.0 + (math.pi / 2.0 * alpha * x) ** 2)


def lif_fwd(I, beta, theta, alpha, smooth=False, reset=True):
    """I (N,C,T) currents -> spikes (N,C,T), membrane u (N,C,T). smooth=True replaces H by the integral of the surrogate (reference
    mode for gradient tests only)."""
    n, c, L = I.shape
    s, u = np.zeros_like(I), np.zeros_like(I)
    v = np.zeros((n, c))
    for t in range(L):
        ut = beta * v + I[:, :, t]
        st = (np.arctan(math.pi / 2 * alpha * (ut - theta)) / math.pi + 0.5) if smooth else (ut >= theta).astype(float)
        v = ut - st * theta if reset else ut
        s[:, :, t], u[:, :, t] = st, ut
    return s, u


def lif_bwd(ds, u, beta, theta, alpha):
    """BPTT of the adopted backward: dv_t/du_t = 1 (reset detached), dv_(t-1) contribution beta*du_t."""
    n, c, L = ds.shape
    sg = surrogate(u, theta, alpha)
    dI = np.zeros_like(ds)
    dv = np.zeros((n, c))
    for t in range(L - 1, -1, -1):
        du = ds[:, :, t] * sg[:, :, t] + dv
        dI[:, :, t] = du
        dv = beta * du
    return dI


# ----------------------------------------------------------------------------- SEW merge operators (PMW-UPD-08 R18)
MERGE_VERSION = "SEW-MERGE-1.0.0"
CONNECT_F = ("ADD", "AND", "IAND")


def sew_merge_forward(A, S, op: str):
    """A = residual branch AFTER its spike, S = shortcut. Orientation is part of the API: IAND = (1 - A) * S (never (1 - S) * A)."""
    if op == "ADD":
        return A + S
    if op == "AND":
        return A * S
    if op == "IAND":
        return (1.0 - A) * S
    raise ValueError("CONNECT_F_INVALID")


def sew_merge_backward(dout, A, S, op: str):
    """Partial derivatives w.r.t. the independent arguments (A, S); the chain rule through the branch is applied by the caller."""
    if op == "ADD":
        return dout, dout
    if op == "AND":
        return dout * S, dout * A
    if op == "IAND":
        return -dout * S, dout * (1.0 - A)
    raise ValueError("CONNECT_F_INVALID")


def _binary(x) -> bool:
    return bool(np.all((x == 0.0) | (x == 1.0)))


# ----------------------------------------------------------------------------- model
class StructureNet:
    def __init__(self, family: str, c_in: int, cfg: dict | None = None, seed: int = 11):
        if family not in FAMILIES:
            raise ValueError("FAMILY_UNKNOWN")
        self.family, self.c_in, self.seed = family, c_in, seed
        self.cfg = dict(CPU_PROFILE, **(cfg or {}))
        c = self.cfg
        self.spiking = family != "MQ_RESNEXT1D_V2"
        self.op = c.get("connect_f", "ADD")
        if self.op not in CONNECT_F:
            raise ValueError("CONNECT_F_INVALID")
        if not self.spiking and self.op != "ADD":
            raise ValueError("CONNECT_F_ONLY_FOR_SEW (ANN ResNeXt ma zwykłe dodawanie residual)")
        self.smooth_reference, self.reset_reference = False, True
        rng = np.random.default_rng(seed)
        self.p: dict[str, np.ndarray] = {}
        self.blocks: list[dict] = []

        def conv(name, cin, cout, k, groups=1):
            if cin % groups or cout % groups:
                raise ValueError(f"CARDINALITY_NOT_DIVISOR: {groups} nie dzieli kanałów {cin}->{cout} (warstwa {name})")
            fan = cin // groups * k
            self.p["W_" + name] = rng.normal(0, math.sqrt(2.0 / fan), (cout, fan))
            self.p["b_" + name] = np.zeros(cout) + (0.5 if self.spiking else 0.0)    # SNN: small positive bias keeps neurons alive at start

        w0 = c["widths"][0]
        conv("stem", c_in, w0, 1 if not self.spiking else c["k"])
        cin, di = w0, 0
        for si, w in enumerate(c["widths"]):
            for bi in range(c["blocks_per_stage"]):
                name = f"s{si}b{bi}"
                d = c["dilations"][di % len(c["dilations"])]
                di += 1
                blk = {"name": name, "cin": cin, "cout": w, "d": d, "proj": cin != w}
                mid = w // 2                                    # bottleneck width = half of the stage width
                if family == "MQ_SEW_RESNET1D_V2":
                    blk["ops"] = [("conv", name + "_a", c["k"], d, 1), ("lif", name + "_a"), ("conv", name + "_b", 1, 1, 1), ("lif", name + "_b")]
                    conv(name + "_a", cin, w, c["k"])
                    conv(name + "_b", w, w, 1)
                else:
                    if mid % c["cardinality"]:
                        raise ValueError(f"CARDINALITY_NOT_DIVISOR: {c['cardinality']} nie dzieli bottleneck width {mid}")
                    act = "lif" if self.spiking else "relu"
                    blk["ops"] = [("conv", name + "_r", 1, 1, 1), (act, name + "_r"), ("conv", name + "_g", c["k"], d, c["cardinality"]), (act, name + "_g"),
                                  ("conv", name + "_e", 1, 1, 1)] + ([("lif", name + "_e")] if self.spiking else [])
                    conv(name + "_r", cin, mid, 1)
                    conv(name + "_g", mid, mid, c["k"], c["cardinality"])
                    conv(name + "_e", mid, w, 1)
                if blk["proj"]:
                    conv(name + "_p", cin, w, 1)
                    # AND/IAND: projection + SN keeps the shortcut binary (a dimension-change block, not identity)
                    blk["proj_ops"] = [("conv", name + "_p", 1, 1, 1)] + ([("lif", name + "_p")] if self.op != "ADD" else [])
                if self.spiking and c.get("identity_init", self.op != "ADD"):
                    last = [o for o in blk["ops"] if o[0] == "conv"][-1][1]
                    self.p["W_" + last][:] = 0.0                        # ADD/IAND: silent branch (A=0); AND: always-firing branch (A=1)
                    self.p["b_" + last][:] = 2.0 * c["theta"] if self.op == "AND" else -c["theta"]
                self.blocks.append(blk)
                cin = w
        self.width_out = cin
        H = len(c["horizons"])
        self.p["W_head"] = rng.normal(0, math.sqrt(1.0 / (2 * cin)), (2 * cin, 6 * H))
        self.p["b_head"] = np.zeros(6 * H)
        self.lif_layers = (["stem"] if self.spiking else []) + [op[1] for b in self.blocks for op in b["ops"] if op[0] == "lif"]
        # w_l = normalised downstream fan-out (frozen in config): spikes of a layer are consumed by the next conv
        fan = {}
        for b in self.blocks:
            for j, op in enumerate(b["ops"]):
                if op[0] == "lif":
                    nxt = next((o for o in b["ops"][j + 1:] if o[0] == "conv"), None)
                    fan[op[1]] = (self.p["W_" + nxt[1]].shape[0] * nxt[2] if nxt else b["cout"])
        if self.spiking:
            fan["stem"] = self.blocks[0]["cout"] * c["k"]
        tot = sum(fan.values()) or 1
        self.layer_w = {k: v / tot for k, v in fan.items()}

    # ---------------------------------------------------------------- helpers
    def _conv(self, name, x, k, d, groups, cache):
        y, cols = gconv_fwd(x, self.p["W_" + name], self.p["b_" + name], k, d, groups)
        cache.append(("conv", name, x, cols, k, d, groups))
        return y

    def _lif(self, name, x, cache, spikes):
        c = self.cfg
        s, u = lif_fwd(x, c["beta"], c["theta"], c["alpha"], smooth=self.smooth_reference, reset=self.reset_reference)
        cache.append(("lif", name, u))
        spikes[name] = s
        return s

    def forward(self, x):
        """x (N, C, T) -> (logits (N,H,3), quantiles (N,H,3), cache). State RESET_EACH_WINDOW (fresh membranes per call)."""
        c = self.cfg
        cache, spikes = [], {}
        st = []
        z = self._conv("stem", x, 1 if not self.spiking else c["k"], 1, 1, st)
        z = self._lif("stem", z, st, spikes) if self.spiking else np.maximum(z, 0)
        if not self.spiking:
            st.append(("relu", "stem", z))
        cache.append(("stem", st))
        for b in self.blocks:
            bc = []
            h = z
            for op in b["ops"]:
                if op[0] == "conv":
                    h = self._conv(op[1], h, op[2], op[3], op[4], bc)
                elif op[0] == "relu":
                    h = np.maximum(h, 0)
                    bc.append(("relu", op[1], h))
                else:
                    h = self._lif(op[1], h, bc, spikes)
            pc = []
            sc = z
            if b["proj"]:
                for op in b["proj_ops"]:
                    sc = self._conv(op[1], sc, op[2], op[3], op[4], pc) if op[0] == "conv" else self._lif(op[1], sc, pc, spikes)
            if self.op != "ADD" and not self.smooth_reference and not (_binary(h) and _binary(sc)):
                raise ValueError(f"DOMAIN_MISMATCH: {self.op} wymaga binarnych A i S (blok {b['name']})")
            out = sew_merge_forward(h, sc, self.op) if self.spiking else sc + h   # SEW merge: no threshold on the result
            if not self.spiking:
                out = np.maximum(out, 0)
            cache.append(("block", b, bc, pc, z, out, h, sc))
            z = out
        feat = np.concatenate([z[:, :, -1], z.mean(axis=2)], axis=1)
        o = feat @ self.p["W_head"] + self.p["b_head"]
        H = len(c["horizons"])
        o = o.reshape(-1, H, 6)
        logits = o[:, :, :3]
        q50 = o[:, :, 4]
        q10, q90 = q50 - softplus(o[:, :, 3]), q50 + softplus(o[:, :, 5])
        cache.append(("head", feat, o, z))
        return logits, np.stack([q10, q50, q90], axis=2), {"layers": cache, "spikes": spikes}

    def loss_grad(self, x, y, r, lam: float | None = None):
        """y (N,H) class index or -1 (missing label = masked, never a failure class); r (N,H) r_h/ATR or nan."""
        c = self.cfg
        lam = c["lambda"] if lam is None else lam
        logits, q, fc = self.forward(x)
        N, H = y.shape
        P = softmax(logits.reshape(-1, 3)).reshape(N, H, 3)
        m = (y >= 0).astype(float)
        mr = np.isfinite(r).astype(float)
        nh = max(1.0, float(m.sum()))
        nq = max(1.0, float(mr.sum()))
        yy = np.where(y >= 0, y, 0)
        ce = -np.sum(m * np.log(P[np.arange(N)[:, None], np.arange(H)[None, :], yy] + 1e-12)) / nh
        rr = np.where(mr > 0, r, 0.0)
        pin, dq = 0.0, np.zeros_like(q)
        for j, tau in enumerate(QUANTS):
            e = rr - q[:, :, j]
            pin += np.sum(mr * np.maximum(tau * e, (tau - 1) * e)) / nq / 3
            dq[:, :, j] = -mr * np.where(e >= 0, tau, tau - 1) / nq / 3 * c["w_q"]
        act = sum(self.layer_w.get(k, 0.0) * float(s.mean()) for k, s in fc["spikes"].items()) if self.spiking else 0.0
        loss = ce + c["w_q"] * pin + lam * act
        dlog = (P - np.eye(3)[yy]) * m[:, :, None] / nh
        o = fc["layers"][-1][2]
        do = np.zeros_like(o)
        do[:, :, :3] = dlog
        do[:, :, 4] = dq.sum(axis=2)
        do[:, :, 3] = -dq[:, :, 0] * sigmoid(o[:, :, 3])
        do[:, :, 5] = dq[:, :, 2] * sigmoid(o[:, :, 5])
        G = self._backward(do.reshape(N, -1), fc, lam)
        return {"loss": float(loss), "ce": float(ce), "pinball": float(pin), "activity": float(act)}, G

    def _backward(self, do, fc, lam):
        c = self.cfg
        G = {k: np.zeros_like(v) for k, v in self.p.items()}
        _, feat, o, z = fc["layers"][-1]
        G["W_head"] = feat.T @ do
        G["b_head"] = do.sum(axis=0)
        df = do @ self.p["W_head"].T
        C, T = z.shape[1], z.shape[2]
        dz = np.zeros_like(z)
        dz[:, :, -1] += df[:, :C]
        dz += (df[:, C:] / T)[:, :, None]
        spikes = fc["spikes"]

        def lif_back(name, u, dh):
            if lam and self.spiking:
                dh = dh + lam * self.layer_w.get(name, 0.0) / spikes[name].size      # gradient of the activity penalty
            return lif_bwd(dh, u, c["beta"], c["theta"], c["alpha"])

        def run_back(ops_cache, dh):
            for ent in reversed(ops_cache):
                if ent[0] == "conv":
                    _, name, xin, cols, k, d, groups = ent
                    dh, dW, db = gconv_bwd(dh, xin, self.p["W_" + name], cols, k, d, groups)
                    G["W_" + name] += dW
                    G["b_" + name] += db
                elif ent[0] == "relu":
                    dh = dh * (ent[2] > 0)
                else:
                    dh = lif_back(ent[1], ent[2], dh)
            return dh

        for ent in reversed(fc["layers"][1:-1]):
            _, b, bc, pc, zin, out, A, S_ = ent
            if not self.spiking:
                dz = dz * (out > 0)
            dA, dS = sew_merge_backward(dz, A, S_, self.op) if self.spiking else (dz, dz)
            dbranch = run_back(bc, dA.copy())
            dsc = run_back(pc, dS.copy()) if b["proj"] else dS
            dz = dbranch + dsc
        run_back(fc["layers"][0][1], dz)
        return G

    # ---------------------------------------------------------------- inference / description
    def predict(self, x) -> dict:
        """Pure inference: no weight or optimizer change."""
        logits, q, fc = self.forward(x)
        N, H, _ = logits.shape
        return {"proba": softmax(logits.reshape(-1, 3)).reshape(N, H, 3), "quantiles": q,
                "firing_rates": {k: float(s.mean()) for k, s in fc["spikes"].items()}}

    def block_stats(self, x) -> list[dict]:
        """Per block: branch firing (A), shortcut activity (S), mean output, fraction nonzero, dead / saturated units of the branch."""
        _, _, fc = self.forward(x)
        out = []
        for ent in fc["layers"][1:-1]:
            _, b, _, _, _, o, A, S_ = ent
            fr = A.mean(axis=(0, 2))
            out.append({"block": b["name"], "connect_f": self.op, "branch_firing": float(A.mean()), "shortcut_activity": float(np.mean(S_ != 0)),
                        "mean_output": float(o.mean()), "fraction_nonzero": float(np.mean(o != 0)), "dead_units": int(np.sum(fr == 0)),
                        "saturated_units": int(np.sum(fr == 1))})
        return out

    def n_params(self) -> int:
        return int(sum(v.size for v in self.p.values()))

    def macs(self, T: int) -> int:
        tot = 0
        for k, v in self.p.items():
            if k.startswith("W_") and k != "W_head":
                tot += v.size * T
        return int(tot + self.p["W_head"].size)

    def telemetry(self, x, repeats: int = 5) -> dict:
        lat = []
        for _ in range(max(1, repeats)):
            t0 = time.perf_counter()
            out = self.predict(x)
            lat.append((time.perf_counter() - t0) * 1000)
        T = x.shape[2]
        syn = None
        if self.spiking:
            _, _, fc = self.forward(x)
            syn = 0.0
            for b in self.blocks:
                for j, op in enumerate(b["ops"]):
                    if op[0] == "lif":
                        nxt = next((o for o in b["ops"][j + 1:] if o[0] == "conv"), None)
                        fan = self.p["W_" + nxt[1]].shape[0] * nxt[2] if nxt else 1     # ADD output: one accumulate per spike
                        syn += float(fc["spikes"][op[1]].sum()) * fan / x.shape[0]
        lat.sort()
        return {"params": self.n_params(), "dense_macs": self.macs(T), "synops_estimate": syn,
                "synops_rule": "spikes x fan-out of the consuming conv (+1 per ADD); encoder/shortcut/readout counted as dense MACs" if syn is not None else None,
                "firing_rates": out["firing_rates"], "latency_ms_p50": lat[len(lat) // 2], "latency_ms_p95": lat[min(len(lat) - 1, int(0.95 * len(lat)))],
                "energy_j": None, "energy_status": "NOT_MEASURED", "note": "SynOps to proxy; NumPy na CPU mnoży także zera"}

    def receptive_field(self) -> int:
        rf = 1 + ((self.cfg["k"] - 1) if self.spiking else 0)
        for b in self.blocks:
            for op in b["ops"]:
                if op[0] == "conv":
                    rf += (op[2] - 1) * op[3]
        return rf

    def manifest(self) -> dict:
        return {"architecture_id": self.family, "version": VERSION, "c_in": self.c_in, "cfg": self.cfg, "seed": self.seed, "classes": list(CLASSES),
                "quantiles": list(QUANTS), "layout": "NCT (adapter to_nct for NTC)", "receptive_field": self.receptive_field(), "params": self.n_params(),
                "lif": {"beta": self.cfg["beta"], "theta": self.cfg["theta"], "reset": "SUBTRACT_DETACHED", "surrogate": f"arctan alpha={self.cfg['alpha']}"}
                if self.spiking else None, "connect_f": self.op, "merge_version": MERGE_VERSION,
                "iand_orientation": "(1-A)*S" if self.op == "IAND" else None,
                "projection_profile": ("CONV1x1+LIF (binarny shortcut)" if self.op != "ADD" else "CONV1x1_ANALOG") if self.spiking else "CONV1x1",
                "input_domain": "BINARY_SPIKES" if self.op != "ADD" else "COUNT_VALUED (ADD sum)", "state_policy": self.cfg["state_policy"],
                "layer_weights": self.layer_w if self.spiking else None}

    def save(self, d: Path) -> dict:
        d = Path(d)
        d.mkdir(parents=True, exist_ok=False)                    # never overwrite an existing artefact
        np.savez(d / "weights.npz", **self.p)
        sha = hashlib.sha256((d / "weights.npz").read_bytes()).hexdigest()
        man = dict(self.manifest(), weights_sha256=sha)
        (d / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
        return man

    @classmethod
    def load(cls, d: Path, expect: dict | None = None) -> "StructureNet":
        d = Path(d)
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if hashlib.sha256((d / "weights.npz").read_bytes()).hexdigest() != man["weights_sha256"]:
            raise ValueError("WEIGHTS_HASH_MISMATCH")
        for k, v in (expect or {}).items():
            if man.get(k) != v:
                raise ValueError(f"INCOMPATIBLE_ARTIFACT: {k}")
        net = cls(man["architecture_id"], man["c_in"], man["cfg"], man["seed"])
        with np.load(d / "weights.npz", allow_pickle=False) as z:
            for k in net.p:
                if z[k].shape != net.p[k].shape:
                    raise ValueError(f"SHAPE_MISMATCH: {k}")
                net.p[k] = z[k].copy()
        return net


def fit(net: StructureNet, X: np.ndarray, Y: np.ndarray, R: np.ndarray, idx: np.ndarray, val_idx: np.ndarray | None = None, *, epochs: int = 60,
        batch: int = 64, lr: float = 1e-3, patience: int = 8, seed: int = 11, budget_s: float | None = None, log=None, cancel=None) -> dict:
    """Adam + clip_norm + weight decay; early stopping on a chronological inner fragment. Exceeding the time budget ends the trial with
    BUDGET_EXCEEDED and the best checkpoint (never a random model). NaN loss -> NAN_LOSS stop."""
    opt = Adam(net.p, lr=lr, wd=net.cfg["weight_decay"])
    rng = np.random.default_rng(seed)
    hist, best, best_p, bad, status = [], None, None, 0, "TRAINED"
    t0 = time.monotonic()
    for ep in range(epochs):
        if cancel is not None and cancel():
            status = "CANCELLED"
            break
        order = rng.permutation(idx)
        tot = 0.0
        for b0 in range(0, len(order), batch):
            bi = order[b0:b0 + batch]
            L, G = net.loss_grad(X[bi], Y[bi], R[bi])
            if not math.isfinite(L["loss"]):
                status = "NAN_LOSS"
                break
            clip_grads(G, net.cfg["clip"])
            opt.step(G)
            tot += L["loss"] * len(bi) / len(order)
        rec = {"epoch": ep + 1, "train_loss": tot}
        if val_idx is not None and len(val_idx):
            Lv, _ = net.loss_grad(X[val_idx], Y[val_idx], R[val_idx])
            rec["val_loss"] = Lv["loss"]
            if best is None or Lv["loss"] < best - 1e-6:
                best, best_p, bad = Lv["loss"], {k: v.copy() for k, v in net.p.items()}, 0
            else:
                bad += 1
        hist.append(rec)
        if log:
            log(rec)
        if status != "TRAINED" or (val_idx is not None and bad >= patience):
            break
        if budget_s is not None and time.monotonic() - t0 > budget_s:
            status = "BUDGET_EXCEEDED"
            break
    if best_p is not None:
        net.p.update(best_p)
    return {"status": status, "history": hist, "epochs_run": len(hist), "budget": {"epochs": epochs, "batch": batch, "lr": lr, "patience": patience}}
