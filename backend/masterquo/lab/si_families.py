"""PMW-UPD-09 adapters of MQ_MINIROCKET_RIDGE_V2 and MQ_SPIKE_BRAIN_FINANCE_V1 for the shared Structure Intelligence trainer
(lab/structure_task: same task/labels/folds/calibration/registry as every other family - no second trainer or queue).

MiniRocket: PRICE_PATH_ATR_V1 windows (last 128 closes / ATR at decision), transform Fit on FIT rows only (SplitMix64 windows per kernel),
ridge head on FIT with L2 chosen on TUNE, residual quantiles on CALIBRATION; temperature by the caller on CALIBRATION.
SpikingBrain BAR_EVENT_V1: the deterministic encoder is run ONCE over the causal bar stream (score-before-update), windows take the last
128 tokens; QUOTE_EVENT_V1: encoder run once over the REAL quote archive (lab/tick_store), per bar the last <=256 tokens from the last
900 s with event time strictly before the M1 close (a quote that already belongs to the next bar never leaks into the old one); no tick
archive -> BLOCKED_NO_QUOTE_HISTORY (only this profile is blocked).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from . import minirocket_v2 as MR
from . import spike_brain as SB

MR_FAMILY = "MQ_MINIROCKET_RIDGE_V2"
SB_FAMILY = "MQ_SPIKE_BRAIN_FINANCE_V1"
FAMILIES = (MR_FAMILY, SB_FAMILY)
BAR_CHANNELS = ["log_return", "range_atr", "spread_atr_change", "trend_internal"]
QUOTE_CHANNELS = ["mid_log_return", "d_bid_ticks", "d_ask_ticks", "spread_ticks"]
QUOTE_MAX_TOKENS, QUOTE_MAX_AGE_S = 256, 900.0


# ===================================================================== MiniRocket
def mr_windows(data: dict, bars: np.ndarray, tick: float, L: int = 128) -> np.ndarray:
    c, atr = data["fe"]["c"], data["fe"]["atr"]
    out = np.empty((len(bars), L), dtype=np.float32)
    for k, b in enumerate(bars):
        w = MR.price_path_atr(c, int(b), float(atr[b]), tick, L)
        if w is None:
            raise MR.MRError("WINDOW_UNAVAILABLE")
        out[k] = w
    return out


def mr_transform(mr: MR.MiniRocketV2, data: dict, bars: np.ndarray, tick: float, chunk: int = 256) -> np.ndarray:
    return np.concatenate([mr.transform(mr_windows(data, bars[s:s + chunk], tick)) for s in range(0, len(bars), chunk)]) \
        if len(bars) else np.zeros((0, mr.lay["F"]), np.float32)


def fit_minirocket(data: dict, bars: np.ndarray, Y: np.ndarray, R: np.ndarray, blocks: dict, prof: dict, seed: int, tick: float):
    fit, tune, cal = blocks["FIT"], blocks["TUNE"], blocks["CALIBRATION"]
    cap = prof.get("mr_max_fit_rows")
    note = None
    if cap and len(fit) > cap:
        note = f"budżet profilu: Fit na ostatnich {cap} z {len(fit)} wierszy FIT (jawnie zapisany)"
        fit = fit[-cap:]
    mr = MR.MiniRocketV2().configure(128, int(prof.get("mr_requested", 10000)), 32)
    mr.fit(mr_windows(data, bars[fit], tick), seed=seed)
    rows = np.concatenate([fit, tune])
    Z = mr_transform(mr, data, bars[rows], tick)
    head = MR.RidgeHeadV2(Y.shape[1])
    head.fit(Z, Y[rows], R[rows], np.arange(len(fit)), np.arange(len(fit), len(rows)))
    if head.status == "SOLVER_NOT_CONVERGED":
        return None, {"status": "SOLVER_NOT_CONVERGED", "solver": head.solver}
    if len(cal):
        head.fit_residuals(mr_transform(mr, data, bars[cal], tick), Y[cal], R[cal], np.arange(len(cal)))
    return ("MR2", mr, head), {"status": "TRAINED" if head.status == "TRAINED" else head.status, "solver": head.solver, "lambda": head.lam,
                               "transform": mr.state(), "budget_note": note}


def predict_minirocket(model, data: dict, bars: np.ndarray, tick: float):
    _, mr, head = model
    P, Q = [], []
    for s in range(0, len(bars), 512):
        p, q = head.predict(mr_transform(mr, data, bars[s:s + 512], tick))
        P.append(p)
        Q.append(q)
    return (np.concatenate(P), np.concatenate(Q)) if P else (np.zeros((0, head.H, 3)), np.zeros((0, head.H, 3)))


def save_minirocket(d: Path, model) -> dict:
    _, mr, head = model
    d.mkdir(parents=True, exist_ok=True)
    arr = MR.model_arrays(mr, head, [])
    MR.write_model_bin(d / "model.bin", arr)
    return {"transform": mr.state(), "head": {"solver": head.solver, "lambda": head.lam, "status": head.status,
                                               "intervals": "CALIBRATED_RESIDUAL_LOCATION_V1" if head.res_q is not None else "NONE"},
            "input_profile": MR.INPUT_PROFILE, "requested": mr.lay["requested"], "max_dilations": mr.lay["max_dilations"]}


def load_minirocket(d: Path, meta: dict):
    a = MR.read_model_bin(d / "model.bin")
    L, F, H, _ = (int(x) for x in a["META"])
    mm = meta.get("mr") or {}
    mr = MR.MiniRocketV2().configure(L, mm.get("requested", 10000), mm.get("max_dilations", 32))
    if mr.lay["dilations"] != a["DILS"].tolist() or mr.lay["counts"] != a["CNTS"].tolist():
        raise ValueError("INCOMPATIBLE_ARTIFACT: layout")
    mr.biases, mr.fit_idx, mr.fit_info = a["BIAS"].astype(np.float32), a["FIDX"], (mm.get("transform") or {}).get("fit")
    head = MR.RidgeHeadV2(H)
    head.mu, head.sd, head.W, head.b = a["SCMU"], a["SCSD"], a["COEF"].reshape(H, F, 4), a["ICPT"].reshape(H, 4)
    rq = a["RESQ"].reshape(H, 3)
    head.res_q = None if np.isnan(rq).all() else rq
    head.status = "TRAINED"
    return ("MR2", mr, head)


# ===================================================================== SpikingBrain - bar profile
def bar_channels(data: dict) -> np.ndarray:
    from .structure_task import TAB
    F, c = data["fe"]["F"], data["fe"]["c"]
    n = len(c)
    X = np.full((n, 4), np.nan)
    X[1:, 0] = np.log(c[1:] / c[:-1])
    X[:, 1] = F[:, TAB.index("range_atr")]
    sp = np.where(F[:, TAB.index("spread_known")] > 0, F[:, TAB.index("spread_atr")], np.nan)
    X[1:, 2] = sp[1:] - sp[:-1]                                         # unknown spread -> NaN mask, never a fabricated 0 change
    X[:, 3] = F[:, TAB.index("trend_int")]
    return X


def bar_stream(data: dict, enc_cfg: dict | None = None) -> dict:
    """Deterministic encoder over the whole causal stream, cached on the dataset dict (identical for every window and fold)."""
    key = "_sb_bar_" + hashlib.sha256(json.dumps(enc_cfg or {}, sort_keys=True).encode()).hexdigest()[:8]
    if key not in data:
        enc = SB.EventEncoder(4, "BAR_EVENT_V1", **(enc_cfg or {}))
        t_bars = data["fe"]["t"] / 60.0                                   # time unit = bars (M1)
        st = enc.run(bar_channels(data), t_bars)
        data[key] = st
    return data[key]


def bar_windows(data: dict, bars: np.ndarray, enc_cfg: dict | None = None, T: int = 128):
    st = bar_stream(data, enc_cfg)
    idx = np.stack([np.arange(b - T + 1, b + 1) for b in bars])
    tok = st["tokens"][idx]
    mean = st["meaningful"][idx]
    dt = st["dt"][idx].copy()
    dt[:, 0] = 1.0
    mask = np.ones(idx.shape)
    return tok, mean, mask, dt


# ===================================================================== SpikingBrain - quote profile
def quote_stream(inst: str, data: dict, enc_cfg: dict | None = None) -> dict | None:
    key = "_sb_quote"
    if key in data:
        return data[key]
    from . import tick_store
    t = data["fe"]["t"]
    ticks = tick_store.load(inst, int((t[0] - QUOTE_MAX_AGE_S) * 1000), int((t[-1] + 60) * 1000))
    if len(ticks) < 10:
        data[key] = None
        return None
    tick_size = float(data.get("tick") or 0.01)
    enc = SB.EventEncoder(4, "QUOTE_EVENT_V1", **(enc_cfg or {}))
    qs = SB.quote_tokens(ticks, enc, tick_size)                         # bid/ask/spread channels in ticks
    tokens = qs["tokens"].copy()
    data[key] = {"tokens": tokens, "t": qs["t"], "kind": qs["kind"], "overflow": enc.overflow, "n_ticks": len(ticks), "tick_size": tick_size,
                 "range": [ticks[0]["t_ms"], ticks[-1]["t_ms"]]}
    return data[key]


def quote_windows(qs: dict, data: dict, bars: np.ndarray):
    """Per M1 bar b (decision at close = t_b + 60): tokens with event time < close, within 900 s, at most 256 (left padded + mask)."""
    T = QUOTE_MAX_TOKENS
    C = qs["tokens"].shape[1]
    N = len(bars)
    tok, mean, mask, dt = np.zeros((N, T, C)), np.zeros((N, T), bool), np.zeros((N, T)), np.zeros((N, T))
    span = np.zeros(N)
    for k, b in enumerate(bars):
        close = data["fe"]["t"][b] + 60.0
        hi = int(np.searchsorted(qs["t"], close, side="left"))           # strictly before the right edge of bar b
        lo = int(np.searchsorted(qs["t"], close - QUOTE_MAX_AGE_S, side="left"))
        lo = max(lo, hi - T)
        n = hi - lo
        if n <= 0:
            continue
        tok[k, T - n:] = qs["tokens"][lo:hi]
        mean[k, T - n:] = [kd == "EVENT" for kd in qs["kind"][lo:hi]]
        mask[k, T - n:] = 1.0
        tt = qs["t"][lo:hi]
        d = np.diff(tt, prepend=tt[0])
        d[0] = 1.0
        dt[k, T - n:] = d
        span[k] = tt[-1] - tt[0]
    return tok, mean, mask, dt, span


# ===================================================================== SpikingBrain fit / predict
def _sb_batches(data, bars, Y, R, pos, prof, enc_cfg, quote):
    bs = int(prof.get("batch") or 32)

    def gen(rng):
        order = rng.permutation(len(pos))
        for s in range(0, len(order), bs):
            p = pos[order[s:s + bs]]
            w = quote_windows(quote, data, bars[p])[:4] if quote is not None else bar_windows(data, bars[p], enc_cfg)
            yield (*w, Y[p], R[p])
    return gen


def fit_spike(inst: str, data: dict, bars: np.ndarray, Y: np.ndarray, R: np.ndarray, blocks: dict, prof: dict, seed: int, budget_s: float,
              cancel=None, ckpt_dir: Path | None = None):
    cfg = dict(prof.get("spike_cfg") or {})
    encoder = cfg.get("encoder", "BAR_EVENT_V1")
    enc_cfg = prof.get("encoder_cfg") or {}
    quote = None
    if encoder == "QUOTE_EVENT_V1":
        quote = quote_stream(inst, data, enc_cfg)
        if quote is None:
            return None, {"status": "BLOCKED_NO_QUOTE_HISTORY", "reason": "brak archiwum rzeczywistych ticków (R19) - trening profilu quote zablokowany"}
    fit, tune = blocks["FIT"], blocks["TUNE"]
    cap = prof.get("spike_max_fit_rows") or prof.get("max_fit_rows")
    if cap:
        fit = fit[-cap:]
    cfg["horizons"] = list(range(Y.shape[1])) if Y.shape[1] != 3 else [3, 5, 15]
    net = SB.SpikeBrain(4 * 2, cfg, seed)
    val = None
    if len(tune):
        tp = tune[-min(len(tune), 256):]
        w = quote_windows(quote, data, bars[tp])[:4] if quote is not None else bar_windows(data, bars[tp], enc_cfg)
        val = (*w, Y[tp], R[tp])
    info = SB.fit(net, _sb_batches(data, bars, Y, R, fit, prof, enc_cfg, quote), val, epochs=prof["epochs"], lr=prof["lr"], patience=prof["patience"],
                  seed=seed, ckpt_dir=ckpt_dir, cancel=cancel, budget_s=budget_s)
    info["encoder"] = encoder
    info["encoder_cfg"] = enc_cfg or "DEFAULT_UNCALIBRATED"
    if quote is not None:
        info["quote_archive"] = {k: quote[k] for k in ("n_ticks", "overflow", "range")}
    return ("SB", net, enc_cfg, encoder), info


def predict_spike(model, inst: str, data: dict, bars: np.ndarray):
    _, net, enc_cfg, encoder = model
    quote = quote_stream(inst, data, enc_cfg) if encoder == "QUOTE_EVENT_V1" else None
    P, Q, tel = [], [], []
    for s in range(0, len(bars), 128):
        b = bars[s:s + 128]
        if quote is not None:
            w = quote_windows(quote, data, b)[:4]
        elif encoder == "QUOTE_EVENT_V1":
            raise ValueError("BLOCKED_NO_QUOTE_HISTORY")
        else:
            w = bar_windows(data, b, enc_cfg)
        out = net.predict(*w)
        P.append(out["proba"])
        Q.append(out["quantiles"])
        tel.append(out["telemetry"])
    model_tel = tel[-1] if tel else {}
    if tel:
        lat = [x["latency_ms"] for x in tel]
        model_tel = dict(model_tel, batch_latency_ms={"p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95)),
                                                      "p99": float(np.percentile(lat, 99))})
    net.last_tel = model_tel
    H = len(net.cfg["horizons"])
    return (np.concatenate(P), np.concatenate(Q)) if P else (np.zeros((0, H, 3)), np.zeros((0, H, 3)))


def save_spike(d: Path, model) -> dict:
    _, net, enc_cfg, encoder = model
    man = net.save(d / "net")
    return {"net": man, "encoder": encoder, "encoder_cfg": enc_cfg}


def load_spike(d: Path, meta: dict):
    net = SB.SpikeBrain.load(d / "net", {"architecture_id": SB.ARCH_ID})
    sb = meta.get("sb") or {}
    return ("SB", net, sb.get("encoder_cfg") or {}, sb.get("encoder", "BAR_EVENT_V1"))


# ===================================================================== benchmark (CLI `benchmark`)
def benchmark(families: list[str], n: int = 200) -> dict:
    out = {}
    if MR_FAMILY in families:
        out[MR_FAMILY] = MR.benchmark(n=max(n, 1000))
        out[MR_FAMILY].pop("raw_ms", None)
    if SB_FAMILY in families:
        rng = np.random.default_rng(3)
        res = {}
        for mode in SB.ATTENTION:
            net = SB.SpikeBrain(8, {"attention": mode}, 1)
            tok = rng.integers(0, 2, (1, 128, 8)).astype(float)
            mean, mask, dt = tok.sum(-1) > 0, np.ones((1, 128)), np.ones((1, 128))
            for _ in range(3):
                net.predict(tok, mean, mask, dt)
            lat = []
            enc_t = []
            for _ in range(max(20, n // 10)):
                t0 = time.perf_counter()
                e = SB.EventEncoder(4)
                e.run(rng.normal(0, 1, (128, 4)), np.arange(128.0))
                enc_t.append((time.perf_counter() - t0) * 1000)
                lat.append(net.predict(tok, mean, mask, dt)["telemetry"]["latency_ms"])
            a = np.array(lat)
            res[mode] = {"inference_ms": {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)), "p99": float(np.percentile(a, 99))},
                         "encoder_128_steps_ms_p50": float(np.percentile(enc_t, 50)), "experts": net.last_tel.get("experts_block0")}
        out[SB_FAMILY] = {"platform": "PYTHON_NUMPY", "T": 128, "modes": res, "energy_j": None,
                          "note": "rzadkie impulsy na gęstych tablicach NumPy nie dowodzą mniejszej latencji ani energii"}
    return out
