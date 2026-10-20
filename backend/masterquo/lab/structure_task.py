"""Structure Intelligence tasks (PMW-UPD-07 R04, R14): STRUCTURE_MOVE_M1_V1 and SCALP_STRUCTURE_CONTEXT_V1.

STRUCTURE_MOVE_M1_V1 - for EVERY qualifying closed M1 bar i (main cohort, not only "nice" patterns) the move after h = 3, 5, 15 following
full M1 bars of the same source: r_h = (BidClose[i+h] - BidClose[i]) / ATR14_i (ATR and close frozen at i). Classes: DOWN r < -b_h,
FLAT |r| <= b_h, UP r > b_h with b_h = 0.15*sqrt(h) ATR (explicit task definition, not an estimate of skill). Horizon in candles:
a window containing ANY time gap != 60 s is excluded from evaluation (conservative: unplanned gaps and session breaks alike).
label_end = open time of bar i+h, label_available_at = its close. Output per head: p_down/p_flat/p_up, quantiles q10/q50/q90 of r_h;
price levels C_i + ATR_i*q are a projection of the END-of-horizon distribution, not future highs/lows nor a path.
SCALP_STRUCTURE_CONTEXT_V1 - only real qualifying setups of the existing scalp strategy (replay of the profile, frozen plan, side, SL,
TP1 = M5 range MID): classes TP1_FIRST / SL_FIRST / TIMEOUT + net_R. No setup -> NO_SETUP (never a fake setup from a pattern name).
Features (FEATURE_SCHEMA SMF-1.0.0): ONE builder for training and inference, causal per bar (structure_v2 walk with swings known before
the bar, MITP trace, candle geometry, point-in-time M5/M15/H1 context = last bar CLOSED at the M1 close, session, data quality);
optional groups carry an availability mask (Black context: mask 0 unless a validated source exists - never imputed from today).
Protocol (frozen before tuning): last 20 % of time = untouched holdout (opened only by `evaluate_holdout`, once, logged in the shared
eval ledger); 4 expanding walk-forward folds on dev; purge by label end + embargo 15 bars; inside every training span FIT 60 / TUNE 15 /
CALIBRATION 15 / POLICY 10 (scalers, early stopping, class priors only on FIT/TUNE, temperature only on CALIBRATION).
Baselines: CLASS_FREQ, RULE_STRUCTURE (class frequency per internal-trend state), LOGREG, XGB (when installed) + the three networks
of lab/structure_nets on identical folds. Nothing here activates a model for execution; selection = SHADOW pointer only, by hand.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..analysis import mitp, structure_v2 as S
from . import si_families as SF
from . import structure_nets as SN

TASK_MOVE = "STRUCTURE_MOVE_M1_V1"
TASK_SETUP = "SCALP_STRUCTURE_CONTEXT_V1"
FEATURE_SCHEMA = "SMF-1.0.0"
LABELS_VERSION = "SML-1.0.0"
PROTOCOL_ID = "SI-PROTO-1.0.0"
HORIZONS = (3, 5, 15)
WINDOW = 128
WARMUP = 200
SETUP_CLASSES = ("TP1_FIRST", "SL_FIRST", "TIMEOUT")
TAB = ["ret1", "ret3", "ret5", "ret15", "body", "upper", "lower", "clv", "range_atr", "trend_int", "trend_maj", "trend_unknown", "dist_h", "dist_l",
       "ev_bos_up", "ev_bos_dn", "ev_chg_up", "ev_chg_dn", "ev_sweep_h", "ev_sweep_l", "bars_since_event", "mitp_buy", "mitp_sell", "mitp_vote",
       "mitp_held", "bb_pctb", "atr_ratio", "hour_sin", "hour_cos", "spread_atr", "spread_known", "m5_ret3", "m5_pos", "m15_ret3", "m15_pos",
       "h1_ret3", "h1_pos", "ctx_known", "black_known"]
SEQ = ["ret1", "body", "upper", "lower", "clv", "range_atr", "trend_int", "dist_h", "dist_l", "mitp_vote", "bb_pctb"]
SEQ_IDX = [TAB.index(x) for x in SEQ]
FAMILIES_ALL = ("LOGREG", "XGB") + SN.FAMILIES + SF.FAMILIES
EVIDENCE = {"min_rows": 20000, "min_sessions": 60, "min_per_class": 500, "min_setups": 600}
CRITERIA = {"logloss_gain_folds": 0.75, "min_mean_logloss_gain": 0.005, "max_ece": 0.10, "nominal_coverage": 0.80}
PROFILES = {"standard": {"epochs": 60, "batch": 64, "patience": 8, "lr": 1e-3, "seeds": [11, 23, 37], "net_cfg": {}, "max_fit_rows": None,
                         "trial_minutes": 120, "mr_requested": 10000, "mr_max_fit_rows": 20000, "spike_max_fit_rows": 20000},
            "quick": {"epochs": 2, "batch": 64, "patience": 2, "lr": 1e-3, "seeds": [11], "net_cfg": {"widths": [8, 16, 16], "blocks_per_stage": 1},
                      "max_fit_rows": 1500, "trial_minutes": 10, "max_folds": 1, "max_eval_rows": 1500, "mr_requested": 840,
                      "mr_max_fit_rows": 1500, "spike_max_fit_rows": 128}}
TF_S = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}


def root(inst: str) -> Path:
    import mq_instruments
    d = mq_instruments.data_dir() / "structure_intelligence" / inst
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ts(s) -> float:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def _iso(x: float) -> str:
    return datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def indicator_profile(inst: str) -> dict:
    """The active indicator profile (STRUCTURE_CAUSAL_V2 params + MITP profile); `calibrate-indicators` writes a new version."""
    p = root(inst) / "indicator_profile.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    prof = {"version": "DEFAULT", "structure": {"internal": [3, 3], "major": [5, 5]}, "mitp_profile": "GROUP_BALANCED", "source": "PACKAGE_DEFAULT"}
    prof["hash"] = hashlib.sha256(json.dumps({k: prof[k] for k in ("structure", "mitp_profile")}, sort_keys=True).encode()).hexdigest()[:16]
    return prof


# ------------------------------------------------------------------ labels
def labels(t: list[float], c: list[float], atr: list) -> tuple[np.ndarray, np.ndarray]:
    n = len(c)
    Y = np.full((n, len(HORIZONS)), -1, dtype=np.int8)
    R = np.full((n, len(HORIZONS)), np.nan, dtype=np.float32)
    ok_step = np.zeros(n, dtype=bool)
    ok_step[1:] = np.diff(np.asarray(t)) == 60
    run = np.zeros(n, dtype=np.int64)                     # number of consecutive 60-s steps ending at i
    for i in range(1, n):
        run[i] = run[i - 1] + 1 if ok_step[i] else 0
    for j, h in enumerate(HORIZONS):
        b = 0.15 * math.sqrt(h)
        for i in range(n - h):
            a = atr[i]
            if not a or a <= 0 or run[i + h] - run[i] != h:
                continue
            r = (c[i + h] - c[i]) / a
            R[i, j] = r
            Y[i, j] = 0 if r < -b else 2 if r > b else 1
    return Y, R


# ------------------------------------------------------------------ features (one builder: dataset + runtime)
def _ctx_tf(bars: list[dict], m1_close_ts: list[float], tf: str) -> np.ndarray:
    """(n, 2): ret3/ATR-free scale and position in the 20-bar range of the last bar CLOSED at each M1 close; nan when unknown."""
    out = np.full((len(m1_close_ts), 2), np.nan)
    if not bars:
        return out
    ts = [_ts(b["open_utc"]) + TF_S[tf] for b in bars]
    c = [b["c"] for b in bars]
    hh = [b["h"] for b in bars]
    ll = [b["l"] for b in bars]
    k = -1
    for i, T in enumerate(m1_close_ts):
        while k + 1 < len(ts) and ts[k + 1] <= T:
            k += 1
        if k >= 20:
            rng = max(hh[k - 19:k + 1]) - min(ll[k - 19:k + 1])
            if rng > 0:
                out[i, 0] = (c[k] - c[k - 3]) / rng
                out[i, 1] = (c[k] - min(ll[k - 19:k + 1])) / rng
    return out


def features(m1: list[dict], ctx: dict | None = None, tick: float = 0.01, profile: dict | None = None, point: float | None = None) -> dict:
    """Causal per-bar table F (n, len(TAB)) for closed M1 bars (oldest first)."""
    prof = profile or {"structure": {"internal": [3, 3], "major": [5, 5]}, "mitp_profile": "GROUP_BALANCED"}
    t = [b["open_utc"] for b in m1]
    ts = [_ts(x) for x in t]
    o = [b["o"] for b in m1]
    h = [b["h"] for b in m1]
    lo = [b["l"] for b in m1]
    c = [b["c"] for b in m1]
    n = len(c)
    atr = S.atr_series(h, lo, c)
    p = dict(S.PARAMS, internal=tuple(prof["structure"]["internal"]), major=tuple(prof["structure"]["major"]))
    _, _, tri = S.walk(t, h, lo, c, tick, p, "internal", trace=True)
    _, _, trm = S.walk(t, h, lo, c, tick, p, "major", trace=True)
    mt = mitp.trace(h, lo, c, prof["mitp_profile"])
    F = np.full((n, len(TAB)), np.nan, dtype=np.float64)
    since = 999
    cmap = {"UP": 1.0, "DOWN": -1.0}
    m1_close = [x + 60 for x in ts]
    cx = {tf: _ctx_tf((ctx or {}).get(tf) or [], m1_close, tf) for tf in ("M5", "M15", "H1")}
    for i in range(n):
        a = atr[i]
        if not a or a <= 0:
            continue
        f = F[i]
        for j, k in enumerate((1, 3, 5, 15)):
            if i >= k:
                f[j] = (c[i] - c[i - k]) / a
        rng = h[i] - lo[i]
        if rng > 0:
            f[4], f[5], f[6], f[7] = abs(c[i] - o[i]) / rng, (h[i] - max(o[i], c[i])) / rng, (min(o[i], c[i]) - lo[i]) / rng, (c[i] - lo[i]) / rng
        f[8] = rng / a
        ti, tm = tri[i], trm[i]
        f[9], f[10], f[11] = cmap.get(ti["trend"], 0.0), cmap.get(tm["trend"], 0.0), 1.0 if ti["trend"] == "UNKNOWN" else 0.0
        f[12] = (ti["last_h"] - c[i]) / a if ti["last_h"] is not None else np.nan
        f[13] = (c[i] - ti["last_l"]) / a if ti["last_l"] is not None else np.nan
        ev = ti["events"]
        f[14:20] = [float("BOS_UP" in ev), float("BOS_DOWN" in ev), float("STRUCTURE_CHANGE_UP" in ev), float("STRUCTURE_CHANGE_DOWN" in ev),
                    float("SWEEP_CANDIDATE_HIGH" in ev), float("SWEEP_CANDIDATE_LOW" in ev)]
        since = 0 if ev else min(since + 1, 999)
        f[20] = min(since, 120) / 120.0
        m = mt[i]
        f[21], f[22], f[23], f[24] = m["buy"] / 32.0, m["sell"] / 32.0, float(m["vote"] or 0), float(m["held"])
        if i >= 19:
            w = c[i - 19:i + 1]
            mu, sd = sum(w) / 20, (sum((x - sum(w) / 20) ** 2 for x in w) / 20) ** 0.5
            f[25] = (c[i] - (mu - 2 * sd)) / (4 * sd) if sd > 0 else 0.5
        if i >= 100 and atr[i - 100]:
            f[26] = a / (sum(x for x in atr[i - 99:i + 1] if x) / 100)
        hr = (ts[i] % 86400) / 3600.0
        f[27], f[28] = math.sin(2 * math.pi * hr / 24), math.cos(2 * math.pi * hr / 24)
        sp = m1[i].get("spread")
        f[29], f[30] = ((sp * (point or tick)) / a, 1.0) if sp is not None else (0.0, 0.0)
        known = 0
        for j, tf in enumerate(("M5", "M15", "H1")):
            v = cx[tf][i]
            if np.isfinite(v).all():
                f[31 + 2 * j], f[32 + 2 * j] = v
                known += 1
            else:
                f[31 + 2 * j], f[32 + 2 * j] = 0.0, 0.5
        f[37] = known / 3.0
        f[38] = 0.0                                           # Black context: no validated option source -> mask 0, not imputed
    return {"F": F, "t": np.array(ts), "c": np.array(c), "atr": np.array([x if x else np.nan for x in atr]), "schema": FEATURE_SCHEMA,
            "names": TAB, "seq": SEQ}


def contiguous_run(ts: np.ndarray) -> np.ndarray:
    run = np.zeros(len(ts), dtype=np.int64)
    for i in range(1, len(ts)):
        run[i] = run[i - 1] + 1 if ts[i] - ts[i - 1] == 60 else 0
    return run


def windows(F: np.ndarray, bars_idx: np.ndarray, sc: dict | None = None) -> np.ndarray:
    """Lazy (N, C, 128) windows for a batch of bar indices (never materialises the whole N x 128 x C set)."""
    X = np.stack([F[b - WINDOW + 1:b + 1, SEQ_IDX].T for b in bars_idx]).astype(np.float64)
    X = np.nan_to_num(X, nan=0.0)
    if sc:
        X = np.clip((X - sc["mu"][None, :, None]) / sc["sd"][None, :, None], -5, 5)
    return X


# ------------------------------------------------------------------ dataset
def build_move_dataset(inst: str, ds: Path, log=print) -> dict:
    from ..extind.trainer import _bars
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    if meta.get("instrument", "XAUUSD") != inst:
        raise ValueError(f"INSTRUMENT_MISMATCH:{meta.get('instrument')}!={inst}")
    prefix = meta.get("file_prefix") or "XAUUSD"
    tick = float(meta["tick_size"])
    point = float((meta.get("spec") or {}).get("point") or tick)
    m1 = _bars(ds, prefix, "M1")
    if len(m1) < WARMUP + WINDOW + 20:
        raise ValueError("BLOCKED_NO_HISTORY: za mało świec M1")
    ctx = {tf: _bars(ds, prefix, tf) for tf in ("M5", "M15", "H1")}
    prof = indicator_profile(inst)
    t0 = time.time()
    fe = features(m1, ctx, tick, prof, point)
    log(f"cechy {inst}: {len(m1)} M1 w {time.time() - t0:.0f}s")
    Y, R = labels(list(fe["t"]), list(fe["c"]), list(fe["atr"]))
    run = contiguous_run(fe["t"])
    eligible = np.where((np.arange(len(m1)) >= WARMUP) & (run >= WINDOW - 1) & np.isfinite(fe["atr"]))[0]
    return {"instrument": inst, "symbol": meta.get("symbol"), "dataset_id": meta.get("dataset_id"), "data_kind": meta.get("data_kind"), "tick": tick,
            "fe": fe, "Y": Y, "R": R, "rows_idx": eligible, "profile": prof, "raw": str(ds), "task": TASK_MOVE,
            "content_hash": hashlib.sha256(fe["F"].tobytes() + Y.tobytes()).hexdigest()[:16]}


def save_dataset(inst: str, data: dict) -> dict:
    did = f"SID-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:4]}"
    d = root(inst) / "datasets" / did
    d.mkdir(parents=True)
    np.savez(d / "data.npz", F=data["fe"]["F"], t=data["fe"]["t"], c=data["fe"]["c"], atr=data["fe"]["atr"], Y=data["Y"], R=data["R"],
             rows_idx=data["rows_idx"], **({"setup_y": data["setup_y"], "setup_r": data["setup_r"], "setup_idx": data["setup_idx"]} if "setup_y" in data else {}))
    man = {"dataset_id": did, "task": data["task"], "instrument": inst, "symbol": data["symbol"], "raw_dataset": data["raw"], "raw_dataset_id": data["dataset_id"],
           "data_kind": data["data_kind"], "feature_schema": FEATURE_SCHEMA, "labels_version": LABELS_VERSION, "indicator_profile": data["profile"],
           "tick": data["tick"], "rows": int(len(data["rows_idx"])), "content_hash": data["content_hash"], "created_at": datetime.now(timezone.utc).isoformat(),
           "time_convention": "UTC open time of M1; decision at bar close", "range": [_iso(data["fe"]["t"][0]), _iso(data["fe"]["t"][-1])],
           "knowledge_cutoff": _iso(data["fe"]["t"][-1] + 60), "sha256": hashlib.sha256((d / "data.npz").read_bytes()).hexdigest()}
    (d / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    idx = root(inst) / "datasets" / "index.json"
    lst = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []
    lst.append({"dataset_id": did, "task": data["task"], "created_at": man["created_at"], "profile_hash": data["profile"]["hash"]})
    idx.write_text(json.dumps(lst, indent=1), encoding="utf-8")
    return man


def latest_dataset(inst: str, task: str) -> Path | None:
    """--latest: the last REGISTERED dataset of this task (index order, never directory mtime)."""
    idx = root(inst) / "datasets" / "index.json"
    lst = [x for x in (json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []) if x["task"] == task]
    return root(inst) / "datasets" / lst[-1]["dataset_id"] if lst else None


def load_dataset(d: Path, task: str) -> dict:
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    if man["task"] != task:
        raise ValueError(f"TASK_MISMATCH: dataset {man['task']} != {task}")
    if hashlib.sha256((d / "data.npz").read_bytes()).hexdigest() != man["sha256"]:
        raise ValueError("DATASET_HASH_MISMATCH")
    with np.load(d / "data.npz", allow_pickle=False) as z:
        arr = {k: z[k] for k in z.files}
    return {"manifest": man, "fe": {"F": arr["F"], "t": arr["t"], "c": arr["c"], "atr": arr["atr"]}, "Y": arr["Y"], "R": arr["R"],
            "rows_idx": arr["rows_idx"], **({k: arr[k] for k in ("setup_y", "setup_r", "setup_idx")} if "setup_y" in arr else {})}


def build_setup_dataset(inst: str, ds: Path, commission: float | None = None, log=print) -> dict:
    """Real qualifying setups only (scalp replay with costs); no setups -> NO_SETUP."""
    from ..ml import scalp_task as stk
    base = stk.build_dataset(inst, ds, commission, log)
    data = build_move_dataset(inst, ds, log)
    tpos = {int(x): k for k, x in enumerate(data["fe"]["t"])}
    ev = {"TP1": 0, "SL": 1, "TIME": 2, "TIMEOUT": 2}
    sy, sr, si = [], [], []
    for r in base["rows"]:
        b = tpos.get(int(_ts(r["signal_time"])))
        k = ev.get(str(r.get("first_exit") or "").upper().split("_")[0])
        if b is None or k is None or b < WARMUP:
            continue
        sy.append(k)
        sr.append(r["net_r"])
        si.append(b)
    data.update(task=TASK_SETUP, setup_y=np.array(sy, np.int8), setup_r=np.array(sr, np.float32), setup_idx=np.array(si, np.int64),
                costs=base["costs"], profile_hash_scalp=base["profile_hash"])
    if not si:
        data["status"] = "NO_SETUP"
    return data


# ------------------------------------------------------------------ models
def _softmax(z):
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


class Tabular:
    """CLASS_FREQ / RULE_STRUCTURE / LOGREG / XGB per head; quantiles = q50 model + empirical residual quantiles from FIT (order enforced)."""

    def __init__(self, family: str, n_heads: int):
        self.family, self.H, self.p = family, n_heads, {}

    def fit(self, X, Y, R, fit, tune=None):
        self.mu = np.nanmean(X[fit], axis=0)
        self.sd = np.nanstd(X[fit], axis=0) + 1e-9
        Z = self._z(X)
        trend = X[:, TAB.index("trend_int")] if X.shape[1] == len(TAB) else np.zeros(len(X))
        for j in range(self.H):
            m = fit[(Y[fit, j] >= 0) & np.isfinite(R[fit, j])]
            y, r = Y[m, j].astype(int), R[m, j]
            if self.family == "CLASS_FREQ":
                self.p[j] = {"pri": (np.bincount(y, minlength=3) + 1) / (len(y) + 3), "q": np.quantile(r, SN.QUANTS) if len(r) else np.zeros(3)}
            elif self.family == "RULE_STRUCTURE":
                st = {}
                for s in (-1.0, 0.0, 1.0):
                    mm = trend[m] == s
                    st[s] = {"pri": (np.bincount(y[mm], minlength=3) + 1) / (mm.sum() + 3),
                             "q": np.quantile(r[mm], SN.QUANTS) if mm.sum() >= 10 else np.quantile(r, SN.QUANTS)}
                self.p[j] = st
            else:
                Zm = Z[m]
                if self.family == "XGB":
                    import xgboost as xgb
                    clf = xgb.XGBClassifier(objective="multi:softprob", num_class=3, max_depth=3, n_estimators=300, learning_rate=0.05, subsample=0.8,
                                            tree_method="hist", n_jobs=2, random_state=42, early_stopping_rounds=30 if tune is not None else None)
                    tm = tune[(Y[tune, j] >= 0)] if tune is not None else None
                    if tm is not None and len(tm) and len(set(Y[tm, j].tolist())) == 3 and len(set(y.tolist())) == 3:
                        clf.fit(Zm, y, eval_set=[(Z[tm], Y[tm, j].astype(int))], verbose=False)
                    else:
                        clf.set_params(early_stopping_rounds=None)
                        clf.fit(Zm, y, verbose=False)
                    W = clf
                else:
                    W = np.zeros((Z.shape[1] + 1, 3))
                    A = np.hstack([Zm, np.ones((len(Zm), 1))])
                    Yo = np.eye(3)[y]
                    for _ in range(300):
                        P = _softmax(A @ W)
                        g = A.T @ (P - Yo) / max(1, len(y)) + 1e-3 * np.vstack([W[:-1], np.zeros((1, 3))])
                        W -= 0.5 * g
                A1 = np.hstack([Zm, np.ones((len(Zm), 1))])
                beta = np.linalg.lstsq(A1.T @ A1 + 1e-2 * np.eye(A1.shape[1]), A1.T @ r, rcond=None)[0] if len(r) else np.zeros(A1.shape[1])
                res = r - A1 @ beta
                self.p[j] = {"W": W, "beta": beta, "res_q": np.quantile(res, SN.QUANTS) if len(res) else np.zeros(3)}
        return self

    def _z(self, X):
        return np.nan_to_num((X - self.mu) / self.sd, nan=0.0).clip(-8, 8)

    def predict(self, X):
        n = len(X)
        P = np.zeros((n, self.H, 3))
        Q = np.zeros((n, self.H, 3))
        Z = self._z(X)
        trend = X[:, TAB.index("trend_int")] if X.shape[1] == len(TAB) else np.zeros(n)
        for j in range(self.H):
            pj = self.p[j]
            if self.family == "CLASS_FREQ":
                P[:, j], Q[:, j] = pj["pri"], pj["q"]
            elif self.family == "RULE_STRUCTURE":
                for s, v in pj.items():
                    m = trend == s
                    P[m, j], Q[m, j] = v["pri"], v["q"]
            else:
                A = np.hstack([Z, np.ones((n, 1))])
                P[:, j] = pj["W"].predict_proba(Z) if self.family == "XGB" else _softmax(A @ pj["W"])
                q50 = A @ pj["beta"]
                rq = np.sort(pj["res_q"])
                Q[:, j] = q50[:, None] + (rq - rq[1])[None, :]
        return P, Q


def _temperature(P, y):
    m = y >= 0
    if m.sum() < 30 or len(set(y[m].tolist())) < 3:
        return {"T": 1.0, "status": "CALIBRATION_UNVERIFIED", "n": int(m.sum())}
    lp = np.log(np.clip(P[m], 1e-12, 1))
    yy = y[m].astype(int)
    grid = np.exp(np.linspace(np.log(0.25), np.log(4.0), 61))
    T = min(grid, key=lambda T: -np.mean(np.log(_softmax(lp / T)[np.arange(len(yy)), yy] + 1e-12)))
    return {"T": float(T), "status": "FITTED_ON_CALIBRATION", "n": int(m.sum())}


def _apply_T(P, T):
    return _softmax(np.log(np.clip(P, 1e-12, 1)) / T)


def metrics(P, Q, Y, R) -> list[dict]:
    out = []
    for j in range(Y.shape[1]):
        m = (Y[:, j] >= 0) & np.isfinite(R[:, j])
        if not m.any():
            out.append({"n": 0})
            continue
        y, r, p, q = Y[m, j].astype(int), R[m, j], np.clip(P[m, j], 1e-12, 1), Q[m, j]
        ll = float(-np.mean(np.log(p[np.arange(len(y)), y])))
        br = float(np.mean(np.sum((p - np.eye(3)[y]) ** 2, axis=1)))
        top, conf = p.argmax(1), p.max(1)
        ece = 0.0
        bins = []
        for b in range(10):
            mm = (conf >= b / 10) & (conf < (b + 1) / 10 if b < 9 else conf <= 1)
            if mm.any():
                ece += mm.mean() * abs((top[mm] == y[mm]).mean() - conf[mm].mean())
                bins.append({"bin": b, "n": int(mm.sum())})
        pin = {}
        for k, tau in enumerate(SN.QUANTS):
            e = r - q[:, k]
            pin[f"q{int(tau * 100)}"] = float(np.mean(np.maximum(tau * e, (tau - 1) * e)))
        recalls = [float((top[y == k] == k).mean()) for k in range(3) if (y == k).any()]
        out.append({"n": int(m.sum()), "class_counts": np.bincount(y, minlength=3).tolist(), "log_loss": ll, "brier": br, "ece": float(ece), "ece_bins": bins,
                    "balanced_accuracy": float(np.mean(recalls)) if recalls else None, "pinball": pin, "mae_q50": float(np.mean(np.abs(r - q[:, 1]))),
                    "coverage_10_90": float(np.mean((r >= q[:, 0]) & (r <= q[:, 2]))), "width_10_90": float(np.mean(q[:, 2] - q[:, 0])),
                    "share_flat_pred": float(np.mean(top == 1))})
    return out


# ------------------------------------------------------------------ protocol
def _rows(t: np.ndarray, idx: np.ndarray, hmax: int) -> list[dict]:
    return [{"signal_time": _iso(t[b] + 60), "label_end": _iso(t[min(b + hmax, len(t) - 1)] + 60), "range_id": None} for b in idx]


def split(data: dict) -> dict:
    from ..ml import scalp_task as stk
    t = data["fe"]["t"]
    idx = data["rows_idx"]
    hmax = max(HORIZONS) if data["manifest"]["task"] == TASK_MOVE else 60      # setup: max hold (60 M1 bars) as the label horizon
    rows_all = _rows(t, idx, hmax)
    ts = t[idx] + 60
    cut = ts.min() + 0.8 * (ts.max() - ts.min())
    emb = 60.0 * max(HORIZONS)
    pos_dev = stk._purged(np.where(ts < cut)[0], rows_all, cut, emb)
    pos_hold = np.where(ts >= cut)[0]
    folds = []
    for k, (tr, ev) in enumerate(stk.outer_folds(pos_dev, rows_all)):
        if len(ev):
            tr = stk._purged(tr, rows_all, _ts(rows_all[ev[0]]["signal_time"]), emb)     # purge + embargo before the outer evaluation
        folds.append({"fold": k, "train": tr, "eval": ev, "blocks": stk.inner_blocks(tr, rows_all, emb),
                      "eval_start": rows_all[ev[0]]["signal_time"] if len(ev) else None})
    return {"rows": rows_all, "dev": pos_dev, "hold": pos_hold, "cut": _iso(cut), "folds": folds, "embargo_s": emb,
            "hash": hashlib.sha256(pos_dev.tobytes() + pos_hold.tobytes()).hexdigest()[:16]}


def evidence(data: dict, sp: dict, task: str) -> dict:
    if task == TASK_SETUP:
        n = int(len(sp["dev"]))
        return {"status": "OK" if n >= EVIDENCE["min_setups"] else "INSUFFICIENT_EVIDENCE", "setups_dev": n, "min": EVIDENCE["min_setups"]}
    b = data["rows_idx"][sp["dev"]]
    Y = data["Y"][b]
    days = len(set((data["fe"]["t"][b] // 86400).tolist()))
    per = [np.bincount(Y[Y[:, j] >= 0, j], minlength=3).tolist() for j in range(Y.shape[1])]
    ok = len(b) >= EVIDENCE["min_rows"] and days >= EVIDENCE["min_sessions"] and all(min(x) >= EVIDENCE["min_per_class"] for x in per)
    return {"status": "OK" if ok else "INSUFFICIENT_EVIDENCE", "rows_dev": int(len(b)), "sessions_dev": days, "class_counts_dev": per, "thresholds": EVIDENCE,
            "note": "minima organizacyjne, nie dowód mocy statystycznej"}


def _task_arrays(data: dict, task: str):
    """(bar index per row, Y (n,H), R (n,H)) for the task."""
    if task == TASK_SETUP:
        return data["setup_idx"], data["setup_y"].astype(np.int64)[:, None], data["setup_r"].astype(np.float64)[:, None]
    b = data["rows_idx"]
    return b, data["Y"][b].astype(np.int64), data["R"][b].astype(np.float64)


def _fit_family(fam: str, data: dict, task: str, blocks: dict, prof: dict, seed: int, log, deadline: float, cancel=None):
    bars, Y, R = _task_arrays(data, task)
    F = data["fe"]["F"]
    H = Y.shape[1]
    if fam == SF.MR_FAMILY:
        return SF.fit_minirocket(data, bars, Y, R, blocks, prof, seed, float(data.get("tick") or data["manifest"]["tick"]))
    if fam == SF.SB_FAMILY:
        return SF.fit_spike(data["manifest"]["instrument"], data, bars, Y, R, blocks, prof, seed,
                            min(60 * prof["trial_minutes"], max(1.0, deadline - time.time())), cancel)
    fit, tune = blocks["FIT"], blocks["TUNE"]
    if prof["max_fit_rows"]:
        fit = fit[-prof["max_fit_rows"]:]
    if fam in ("CLASS_FREQ", "RULE_STRUCTURE", "LOGREG", "XGB"):
        if fam == "XGB":
            try:
                import xgboost  # noqa: F401
            except ImportError:
                return None, {"status": "NOT_AVAILABLE", "reason": "xgboost nie jest zainstalowany"}
        m = Tabular(fam, H).fit(F[bars], Y, R, fit, tune)
        return m, {"status": "TRAINED"}
    base, _, op = fam.partition("@")                     # PMW-UPD-08: "<family>@<connect_f>" variants of the SEW families
    cfg = dict(prof["net_cfg"], horizons=list(HORIZONS) if task == TASK_MOVE else [0], connect_f=op or "ADD")
    seq = F[bars[fit]][:, SEQ_IDX]
    sc = {"mu": np.nanmean(seq, axis=0), "sd": np.nanstd(seq, axis=0) + 1e-9}
    net = SN.StructureNet(base, len(SEQ), cfg, seed)

    class Lazy:                                    # windows built per batch from the feature table
        def __init__(self, src):
            self.src = src

        def __getitem__(self, k):
            return windows(F, bars[self.src[k]], sc)
    pos = np.arange(len(bars))
    Xl = Lazy(pos)
    info = SN.fit(net, Xl, Y, R, fit, tune[-2000:] if len(tune) else None, epochs=prof["epochs"], batch=prof["batch"], lr=prof["lr"],
                  patience=prof["patience"], seed=seed, budget_s=min(60 * prof["trial_minutes"], max(1.0, deadline - time.time())), log=None)
    return (net, sc), info


def _predict(model, fam: str, data: dict, task: str, pos: np.ndarray):
    bars, Y, R = _task_arrays(data, task)
    F = data["fe"]["F"]
    if isinstance(model, Tabular):
        return model.predict(F[bars[pos]])
    if model[0] == "MR2":
        return SF.predict_minirocket(model, data, bars[pos], float(data.get("tick") or data["manifest"]["tick"]))
    if model[0] == "SB":
        return SF.predict_spike(model, data["manifest"]["instrument"], data, bars[pos])
    net, sc = model
    P, Q = [], []
    for b0 in range(0, len(pos), 512):
        out = net.predict(windows(F, bars[pos[b0:b0 + 512]], sc))
        P.append(out["proba"])
        Q.append(out["quantiles"])
    return (np.concatenate(P), np.concatenate(Q)) if P else (np.zeros((0, Y.shape[1], 3)), np.zeros((0, Y.shape[1], 3)))


def expand_families(families: list[str], sew_operators: list[str] | None) -> list[str]:
    out = []
    for f in families:
        if f in SN.FAMILIES and f != "MQ_RESNEXT1D_V2" and sew_operators:
            out += [f if op == "ADD" else f"{f}@{op}" for op in sew_operators]
        elif f in FAMILIES_ALL:
            out.append(f)
    return out


def train(inst: str, dsdir: Path, task: str, families: list[str], profile: str = "standard", db=None, log=print, cancel=None,
          sew_operators: list[str] | None = None, spike_cfg: dict | None = None, transform: str | None = None) -> dict:
    if transform and transform != SF.MR.TRANSFORM_ID:
        return {"status": "INCOMPATIBLE", "reason": f"nieobsługiwana transformacja {transform} (dostępna {SF.MR.TRANSFORM_ID})"}
    data = load_dataset(dsdir, task)
    man = data["manifest"]
    prof_now = indicator_profile(inst)
    if man["indicator_profile"]["hash"] != prof_now["hash"]:
        return {"status": "STALE_DATASET", "reason": f"profil wskaźników zmieniony ({man['indicator_profile']['hash']} → {prof_now['hash']})",
                "rebuild": f"python -m masterquo structure-intelligence dataset --asset {inst} --task {task}"}
    if task == TASK_SETUP and not len(data.get("setup_idx", [])):
        return {"status": "NO_SETUP", "reason": "brak rzeczywistych setupów strategii w danych"}
    prof = dict(PROFILES[profile], spike_cfg=dict(spike_cfg or {}))
    if task == TASK_SETUP:
        data["rows_idx"] = data["setup_idx"]
    sp = split(data)
    synthetic = man["data_kind"] != "REAL_USER_DATA"
    rid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:4] + ("_FIXTURE" if synthetic else "")
    rd = root(inst) / ("fixture_runs" if synthetic else "runs") / rid
    rd.mkdir(parents=True)
    ev = evidence(data, sp, task)
    rep = {"run_id": rid, "task_id": task, "protocol_id": PROTOCOL_ID, "split_hash": sp["hash"], "dataset_id": man["dataset_id"], "data_kind": man["data_kind"],
           "feature_schema": FEATURE_SCHEMA, "labels_version": LABELS_VERSION, "indicator_profile": man["indicator_profile"], "profile": profile,
           "profile_note": "quick = niepełny smoke" if profile == "quick" else None, "families": families, "evidence": ev, "holdout_from": sp["cut"],
           "class_order": list(SN.CLASSES) if task == TASK_MOVE else list(SETUP_CLASSES), "horizons": list(HORIZONS) if task == TASK_MOVE else None,
           "role": "TEST_ONLY" if synthetic else "RESEARCH", "folds": [], "created_at": datetime.now(timezone.utc).isoformat(), "criteria": CRITERIA,
           "budget": {k: prof[k] for k in ("epochs", "batch", "patience", "lr", "seeds", "trial_minutes", "mr_requested", "mr_max_fit_rows",
                                            "spike_max_fit_rows")},
           "spike_profile": {"encoder": (spike_cfg or {}).get("encoder", "BAR_EVENT_V1"), "attention": (spike_cfg or {}).get("attention", "HYBRID")}
           if SF.SB_FAMILY in families else None, "transform": SF.MR.TRANSFORM_ID if SF.MR_FAMILY in families else None}
    deadline = time.time() + 60 * prof["trial_minutes"] * (len(families) + 2) * 5
    _, Yall, Rall = _task_arrays(data, task)
    families = expand_families(families, sew_operators)
    fams = ["CLASS_FREQ", "RULE_STRUCTURE"] + families
    for f in sp["folds"][-int(prof.get("max_folds") or 4):]:
        if prof.get("max_eval_rows"):
            f = dict(f, eval=f["eval"][: prof["max_eval_rows"]])
        if cancel and cancel():
            rep["status"] = "CANCELLED"
            break
        b = f["blocks"]
        if min(len(v) for v in b.values()) < 5 or not len(f["eval"]):
            rep["folds"].append({"fold": f["fold"], "status": "INSUFFICIENT_EVIDENCE"})
            continue
        fr = {"fold": f["fold"], "status": "OK", "sizes": {k: int(len(v)) for k, v in b.items()}, "eval_n": int(len(f["eval"])), "families": {}}
        for fam in fams:
            seeds = prof["seeds"] if (fam in SN.FAMILIES or fam in SF.FAMILIES) else [0]
            res = []
            for sd in seeds:
                model, info = _fit_family(fam, data, task, b, prof, sd, log, deadline, cancel)
                if model is None:
                    res.append({"seed": sd, **info})
                    continue
                Pc, _ = _predict(model, fam, data, task, b["CALIBRATION"])
                temps = [_temperature(Pc[:, j], Yall[b["CALIBRATION"], j]) for j in range(Yall.shape[1])] if fam != "CLASS_FREQ" else None
                P, Q = _predict(model, fam, data, task, f["eval"])
                if temps:
                    P = np.stack([_apply_T(P[:, j], temps[j]["T"]) for j in range(P.shape[1])], axis=1)
                res.append({"seed": sd, "status": info["status"], "epochs_run": info.get("epochs_run"), "calibration": temps,
                            "metrics": metrics(P, Q, Yall[f["eval"]], Rall[f["eval"]]),
                            **({"diagnostics": _diag(model, info)} if fam in SF.FAMILIES else {})})
            fr["families"][fam] = res
            log(f"fold {f['fold'] + 1} {fam}: {[r.get('status') for r in res]}")
        rep["folds"].append(fr)
    rep["comparison"] = _compare(rep)
    rep.setdefault("status", "EVALUATED_DEV" if ev["status"] == "OK" else "INSUFFICIENT_EVIDENCE")
    # final candidates on the whole dev (inner blocks), saved for SHADOW selection - holdout NOT opened here
    from ..ml import scalp_task as stk
    fb = stk.inner_blocks(sp["dev"], sp["rows"], sp["embargo_s"])
    rep["candidates"] = {}
    if rep["status"] != "CANCELLED" and min(len(v) for v in fb.values()) >= 5:
        for fam in families:
            model, info = _fit_family(fam, data, task, fb, prof, prof["seeds"][0], log, deadline, cancel)
            if model is None:
                rep["candidates"][fam] = info
                continue
            Pc, _ = _predict(model, fam, data, task, fb["CALIBRATION"])
            temps = [_temperature(Pc[:, j], Yall[fb["CALIBRATION"], j]) for j in range(Yall.shape[1])]
            cid = f"{rid}-{fam}"
            mh = save_candidate(rd / "models" / fam, fam, model, temps, rep, man, info)
            rep["candidates"][fam] = {"candidate_id": cid, "model_hash": mh, "status": info["status"], "calibration": temps,
                                      "holdout": "NOT_EVALUATED_ON_HOLDOUT_BY_DESIGN"}
    rep["run_dir"] = str(rd)
    (rd / "report.json").write_text(json.dumps(rep, indent=1, default=_jd), encoding="utf-8")
    reg = _reg(inst)
    reg["runs"][rid] = {"run_dir": str(rd), "task": task, "status": rep["status"], "role": rep["role"], "created_at": rep["created_at"]}
    _save_reg(inst, reg)
    return rep


def _jd(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, np.ndarray):
        return x.tolist()
    return str(x)


def _compare(rep: dict) -> dict:
    """Mean dev log loss per family (averaged over heads, folds, seeds) and the gain vs CLASS_FREQ per fold."""
    out = {}
    for f in rep["folds"]:
        if f.get("status") != "OK":
            continue
        base = f["families"].get("CLASS_FREQ", [{}])[0].get("metrics")
        for fam, res in f["families"].items():
            lls = [np.mean([m["log_loss"] for m in r["metrics"] if m.get("n")]) for r in res if r.get("metrics")]
            if not lls:
                continue
            o = out.setdefault(fam, {"fold_ll": [], "gains": []})
            o["fold_ll"].append(float(np.mean(lls)))
            if base:
                o["gains"].append(float(np.mean([m["log_loss"] for m in base if m.get("n")]) - np.mean(lls)))
    for fam, o in out.items():
        g = o["gains"]
        o["mean_ll"] = float(np.mean(o["fold_ll"]))
        o["share_folds_gain"] = float(np.mean([x >= CRITERIA["min_mean_logloss_gain"] for x in g])) if g else 0.0
        o["mean_gain"] = float(np.mean(g)) if g else None
        o["dev_criteria_met"] = bool(g) and o["share_folds_gain"] >= CRITERIA["logloss_gain_folds"] and (o["mean_gain"] or 0) >= CRITERIA["min_mean_logloss_gain"]
    return out


# ------------------------------------------------------------------ artefacts / registry
def _diag(model, info: dict) -> dict:
    """Model diagnostics shown in the panel (encoder/attention/router/experts or transform/solver) - from the real fitted object."""
    if model[0] == "SB":
        net = model[1]
        return {"architecture_id": SF.SB.ARCH_ID, "encoder": model[3], "attention": net.cfg["attention"], "telemetry": net.last_tel,
                "epochs_run": info.get("epochs_run"), "history_tail": (info.get("history") or [])[-3:], "energy_j": None}
    return {"transform": model[1].state(), "solver": info.get("solver"), "lambda": info.get("lambda"), "budget_note": info.get("budget_note")}


def save_candidate(d: Path, fam: str, model, temps: list, rep: dict, man: dict, info: dict | None = None) -> str:
    d.mkdir(parents=True, exist_ok=False)
    meta = {"task_id": rep["task_id"], "family": fam, "instrument": man["instrument"], "symbol": man["symbol"], "feature_schema": FEATURE_SCHEMA,
            "labels_version": LABELS_VERSION, "indicator_profile_hash": man["indicator_profile"]["hash"], "class_order": rep["class_order"],
            "horizons": rep["horizons"], "calibration": temps, "role": rep["role"], "protocol_id": PROTOCOL_ID, "dataset_id": man["dataset_id"],
            "created_at": datetime.now(timezone.utc).isoformat(), "state_policy": "RESET_EACH_WINDOW" if (fam in SN.FAMILIES or fam == SF.SB_FAMILY) else None}
    if fam == SF.MR_FAMILY:
        meta["mr"] = SF.save_minirocket(d / "mr2", model)
        meta["diagnostics"] = _diag(model, info or {})
    elif fam == SF.SB_FAMILY:
        meta["sb"] = SF.save_spike(d, model)
        meta["diagnostics"] = _diag(model, info or {})
    elif fam in SN.FAMILIES:
        net, sc = model
        nm = net.save(d / "net")
        np.savez(d / "scaler.npz", mu=sc["mu"], sd=sc["sd"])
        meta["net"] = nm
    else:
        arrs = {"mu": model.mu, "sd": model.sd}
        if fam == "XGB":
            for j, pj in model.p.items():
                pj["W"].save_model(str(d / f"xgb_h{j}.json"))
                arrs[f"beta_{j}"], arrs[f"resq_{j}"] = pj["beta"], pj["res_q"]
        else:
            for j, pj in model.p.items():
                arrs[f"W_{j}"], arrs[f"beta_{j}"], arrs[f"resq_{j}"] = pj["W"], pj["beta"], pj["res_q"]
        meta["n_heads"] = model.H
        np.savez(d / "tabular.npz", **arrs)
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    meta["model_hash"] = h.hexdigest()
    (d / "candidate.json").write_text(json.dumps(meta, indent=1, default=_jd), encoding="utf-8")
    return meta["model_hash"]


def load_candidate(d: Path, expect: dict | None = None):
    meta = json.loads((d / "candidate.json").read_text(encoding="utf-8"))
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name != "candidate.json":
            h.update(p.read_bytes())
    if h.hexdigest() != meta["model_hash"]:
        raise ValueError("MODEL_HASH_MISMATCH")
    for k, v in (expect or {}).items():
        if meta.get(k) != v:
            raise ValueError(f"INCOMPATIBLE_ARTIFACT: {k}={meta.get(k)} (oczekiwano {v})")
    fam = meta["family"]
    if fam == SF.MR_FAMILY:
        return meta, SF.load_minirocket(d / "mr2", meta)
    if fam == SF.SB_FAMILY:
        return meta, SF.load_spike(d, meta)
    if fam in SN.FAMILIES:
        net = SN.StructureNet.load(d / "net")
        with np.load(d / "scaler.npz", allow_pickle=False) as z:
            sc = {"mu": z["mu"], "sd": z["sd"]}
        return meta, (net, sc)
    m = Tabular(fam, meta["n_heads"])
    with np.load(d / "tabular.npz", allow_pickle=False) as z:
        m.mu, m.sd = z["mu"], z["sd"]
        for j in range(m.H):
            if fam == "XGB":
                import xgboost as xgb
                clf = xgb.XGBClassifier()
                clf.load_model(str(d / f"xgb_h{j}.json"))
                m.p[j] = {"W": clf, "beta": z[f"beta_{j}"], "res_q": z[f"resq_{j}"]}
            else:
                m.p[j] = {"W": z[f"W_{j}"], "beta": z[f"beta_{j}"], "res_q": z[f"resq_{j}"]}
    return meta, m


def _reg(inst: str) -> dict:
    p = root(inst) / "registry.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"runs": {}, "shadow": {}, "history": [], "holdout_access": {}}


def _save_reg(inst: str, reg: dict) -> None:
    p = root(inst) / "registry.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=1), encoding="utf-8")
    tmp.replace(p)


def select_shadow(inst: str, candidate_id: str) -> dict:
    """Manual SHADOW pointer (never execution). TEST_ONLY candidates are refused; the previous pointer is kept for rollback."""
    reg = _reg(inst)
    rid = next((r for r in reg["runs"] if candidate_id.startswith(r + "-")), None)
    if rid is None:
        raise ValueError("RUN_NOT_FOUND")
    fam, run = candidate_id[len(rid) + 1:], reg["runs"][rid]
    d = Path(run["run_dir"]) / "models" / fam
    meta, _ = load_candidate(d)                      # full compatibility + hash check before the pointer moves
    if meta["role"] == "TEST_ONLY":
        raise ValueError("TEST_ONLY_ARTIFACT: model z danych syntetycznych nie trafia do SHADOW")
    prev = reg["shadow"].get(meta["task_id"])
    reg["shadow"][meta["task_id"]] = {"candidate_id": candidate_id, "dir": str(d), "model_hash": meta["model_hash"], "at": datetime.now(timezone.utc).isoformat()}
    reg["history"].append({"task": meta["task_id"], "from": prev, "to": candidate_id, "at": datetime.now(timezone.utc).isoformat()})
    _save_reg(inst, reg)
    return {"ok": True, "shadow": reg["shadow"][meta["task_id"]], "previous": prev, "execution": "NEVER_AUTOMATIC"}


def rollback(inst: str, task: str) -> dict:
    reg = _reg(inst)
    hist = [h for h in reg["history"] if h["task"] == task]
    if not hist:
        raise ValueError("NO_HISTORY")
    prev = hist[-1]["from"]
    if prev is None:
        reg["shadow"].pop(task, None)
    else:
        reg["shadow"][task] = prev
    reg["history"].append({"task": task, "from": hist[-1]["to"], "to": prev["candidate_id"] if prev else None, "at": datetime.now(timezone.utc).isoformat(),
                           "rollback": True})
    _save_reg(inst, reg)
    return {"ok": True, "shadow": reg["shadow"].get(task)}


def evaluate_holdout(inst: str, candidate_id: str, protocol_id: str, db=None) -> dict:
    """ONE access per candidate: reserves the period in the shared eval ledger BEFORE reading labels, then stores the report; a second
    call returns the stored report (ALREADY_EVALUATED) - it never re-selects."""
    if protocol_id != PROTOCOL_ID:
        raise ValueError("PROTOCOL_MISMATCH")
    reg = _reg(inst)
    if candidate_id in reg["holdout_access"]:
        return dict(reg["holdout_access"][candidate_id], status="ALREADY_EVALUATED")
    rid = next((r for r in reg["runs"] if candidate_id.startswith(r + "-")), None)
    if rid is None:
        raise ValueError("RUN_NOT_FOUND")
    fam = candidate_id[len(rid) + 1:]
    rd = Path(reg["runs"][rid]["run_dir"])
    rep = json.loads((rd / "report.json").read_text(encoding="utf-8"))
    meta, model = load_candidate(rd / "models" / fam)
    data = load_dataset(root(inst) / "datasets" / rep["dataset_id"], rep["task_id"])
    if rep["task_id"] == TASK_SETUP:
        data["rows_idx"] = data["setup_idx"]
    sp = split(data)
    if sp["hash"] != rep["split_hash"]:
        raise ValueError("SPLIT_MISMATCH")
    hold = sp["hold"]
    if not len(hold):
        return {"status": "INSUFFICIENT_EVIDENCE", "reason": "pusty holdout"}
    from ..ml import scalp_task as stk
    led = stk.reserve_holdout(db, inst, sp["rows"][hold[0]]["signal_time"], sp["rows"][hold[-1]]["label_end"], meta["model_hash"], rep["task_id"]) \
        if db is not None else {"status": "LEDGER_UNAVAILABLE"}
    _, Y, R = _task_arrays(data, rep["task_id"])
    P, Q = _predict(model, fam, data, rep["task_id"], hold)
    P = np.stack([_apply_T(P[:, j], meta["calibration"][j]["T"]) for j in range(P.shape[1])], axis=1)
    out = {"candidate_id": candidate_id, "protocol_id": protocol_id, "ledger": led, "metrics": metrics(P, Q, Y[hold], R[hold]),
           "at": datetime.now(timezone.utc).isoformat(), "model_hash": meta["model_hash"], "role": meta["role"],
           "edge_status": "TEST_ONLY" if meta["role"] == "TEST_ONLY" else "NO_VALIDATED_EDGE_CLAIM (ruch ≠ rentowność)"}
    reg["holdout_access"][candidate_id] = out
    _save_reg(inst, reg)
    return dict(out, status="EVALUATED_ONCE")


# ------------------------------------------------------------------ runtime forecaster (SHADOW only)
class Forecaster:
    def __init__(self, inst: str):
        self.inst = inst
        reg = _reg(inst)
        s = reg["shadow"].get(TASK_MOVE)
        self.meta, self.model = (None, None)
        self.reason = "NO_SHADOW_MODEL"
        if s:
            try:
                self.meta, self.model = load_candidate(Path(s["dir"]), {"task_id": TASK_MOVE, "feature_schema": FEATURE_SCHEMA, "instrument": inst,
                                                                        "indicator_profile_hash": indicator_profile(inst)["hash"]})
                self.reason = None
            except (ValueError, OSError) as exc:
                self.reason = f"ARTIFACT_REJECTED: {exc}"

    def forecast(self, m1: list[dict], ctx: dict, tick: float) -> dict:
        if self.model is None:
            return {"forecast_status": "ABSTAIN", "reason": self.reason}
        if len(m1) < WARMUP + WINDOW:
            return {"forecast_status": "ABSTAIN", "reason": "INSUFFICIENT_HISTORY"}
        fe = features(m1, ctx, tick, indicator_profile(self.inst))
        run = contiguous_run(fe["t"])
        b = len(m1) - 1
        if run[b] < WINDOW - 1 or not np.isfinite(fe["atr"][b]):
            return {"forecast_status": "ABSTAIN", "reason": "DATA_GAP_IN_WINDOW"}
        fam = self.meta["family"]
        data = {"fe": fe, "rows_idx": np.array([b]), "Y": np.full((len(m1), 3), -1), "R": np.full((len(m1), 3), np.nan), "tick": tick,
                "manifest": {"instrument": self.inst, "tick": tick}}
        P, Q = _predict(self.model, fam, data, TASK_MOVE, np.array([0]))
        C, A = float(fe["c"][b]), float(fe["atr"][b])
        heads = []
        for j, hh in enumerate(HORIZONS):
            p = _apply_T(P[:, j], self.meta["calibration"][j]["T"])[0]
            q = Q[0, j]
            heads.append({"h_bars": hh, "p_down": float(p[0]), "p_flat": float(p[1]), "p_up": float(p[2]), "q10": float(q[0]), "q50": float(q[1]),
                          "q90": float(q[2]), "price_q10": C + A * float(q[0]), "price_q50": C + A * float(q[1]), "price_q90": C + A * float(q[2]),
                          "expected_end": _iso(fe["t"][b] + 60 * (hh + 1)), "calibration": self.meta["calibration"][j]["status"]})
        return {"forecast_status": "OK", "artifact_id": self.meta["model_hash"][:16], "family": fam, "as_of": _iso(fe["t"][b] + 60), "anchor_close": C,
                "anchor_atr": A, "heads": heads, "role": "SHADOW",
                "note": "rozkład końca horyzontu (nie trajektoria, nie high/low); kierunek ≠ zlecenie"}


# ------------------------------------------------------------------ indicator profile calibration (dev part ONLY)
def calibrate_indicators(inst: str, ds: Path | None = None, log=print) -> dict:
    """Choose the internal pivot pair and the MITP profile on the DEVELOPMENT part only (first 80 % of time; fit on its first 60 %,
    score on the rest): RULE_STRUCTURE log loss at h=5 vs CLASS_FREQ. Writes a NEW profile version; datasets built with the old
    hash become STALE (train refuses them with the rebuild command). Holdout data are never read here."""
    from ..extind.cli import _latest_real
    from ..extind.trainer import _bars
    ds = ds or _latest_real(inst)
    if ds is None:
        raise ValueError("BLOCKED_NO_HISTORY")
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    m1 = _bars(ds, meta.get("file_prefix") or "XAUUSD", "M1")
    if len(m1) < 2000:
        raise ValueError("BLOCKED_NO_HISTORY: za mało M1")
    ts = [_ts(b["open_utc"]) for b in m1]
    cut = ts[0] + 0.8 * (ts[-1] - ts[0])
    dev = [b for b, t in zip(m1, ts) if t < cut]
    tick = float(meta["tick_size"])
    trials = []
    for piv in ([2, 2], [3, 3], [4, 4]):
        for mp in ("GROUP_BALANCED", "STRICT_ALL"):
            prof = {"structure": {"internal": piv, "major": [5, 5]}, "mitp_profile": mp}
            fe = features(dev, None, tick, prof)
            Y, R = labels(list(fe["t"]), list(fe["c"]), list(fe["atr"]))
            ok = np.where(np.isfinite(fe["atr"]) & (np.arange(len(dev)) >= WARMUP) & (Y[:, 1] >= 0))[0]
            k = int(0.6 * len(ok))
            fit, ev = ok[:k], ok[k + 15:]
            if len(fit) < 100 or len(ev) < 100:
                continue
            base = Tabular("CLASS_FREQ", 3).fit(fe["F"], Y, R, fit)
            rule = Tabular("RULE_STRUCTURE", 3).fit(fe["F"], Y, R, fit)
            pb, _ = base.predict(fe["F"][ev])
            pr, _ = rule.predict(fe["F"][ev])
            ll = lambda P: float(-np.mean(np.log(np.clip(P[np.arange(len(ev)), 1, Y[ev, 1]], 1e-12, 1))))  # noqa: E731
            trials.append({"internal": piv, "mitp_profile": mp, "gain_h5": ll(pb) - ll(pr)})
            log(f"kalibracja {piv} {mp}: zysk log loss {trials[-1]['gain_h5']:.5f}")
    if not trials:
        raise ValueError("INSUFFICIENT_EVIDENCE: za mało danych dev do kalibracji")
    best = max(trials, key=lambda x: x["gain_h5"])
    prof = {"version": f"CAL-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}", "structure": {"internal": best["internal"], "major": [5, 5]},
            "mitp_profile": best["mitp_profile"], "source": "CALIBRATED_ON_DEV", "dev_end": _iso(cut), "raw_dataset": str(ds), "trials": trials,
            "data_kind": meta.get("data_kind")}
    prof["hash"] = hashlib.sha256(json.dumps({k: prof[k] for k in ("structure", "mitp_profile")}, sort_keys=True).encode()).hexdigest()[:16]
    p = root(inst) / "indicator_profile.json"
    if p.exists():
        hist = root(inst) / "indicator_profiles"
        hist.mkdir(exist_ok=True)
        (hist / f"{json.loads(p.read_text(encoding='utf-8')).get('version', 'OLD')}.json").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(json.dumps(prof, indent=1), encoding="utf-8")
    return prof


# ------------------------------------------------------------------ PMW-UPD-08 experiments (same protocol, separate manifests)
EXPERIMENTS = ("MQ_NEUTRAL_REACTION_V1", "MQ_QUOTE_CONTEXT_REACTION_V1")


def _neutral_variants(data: dict) -> tuple[dict, np.ndarray, dict]:
    """Causal (prequential) ROC20 neutralization over the bar stream; three research variants on the SAME rows."""
    from ..analysis import neutralization as NZ
    c = list(data["fe"]["c"])
    t = list(data["fe"]["t"])
    atr = data["fe"]["atr"]
    e = NZ._ema(c, 50)
    vol = [None if not np.isfinite(atr[i]) else float(atr[i] / c[i]) for i in range(len(c))]
    slope = [None if i < 5 or e[i] is None or e[i - 5] is None else (e[i] - e[i - 5]) / c[i] for i in range(len(c))]
    raw = NZ.roc20(c)
    rows = NZ.run_series(t, raw, {"volatility": vol, "trend_slope": slope}, "ROC20", "DETERMINISTIC", "dataset")
    n = len(c)
    elig = np.array([r.get("eligible", False) for r in rows])
    g = lambda k: np.array([np.nan if r.get(k) is None else float(r[k]) for r in rows])  # noqa: E731
    V = np.stack([np.array([np.nan if x is None else x for x in vol], float), np.array([np.nan if x is None else x for x in slope], float)], axis=1)
    raw_a = np.array([np.nan if x is None else x for x in raw], float)
    variants = {"RAW_FILTER": np.column_stack([g("z_raw"), V]), "NEUTRAL_FILTER": np.column_stack([g("z_residual"), g("residual"), V, g("fit_age_s"), g("r2_in_sample")]),
                "RAW_PLUS_FACTORS": np.column_stack([raw_a, V])}
    names = {"RAW_FILTER": ["z_raw", "volatility", "trend_slope"], "NEUTRAL_FILTER": ["z_residual", "residual", "volatility", "trend_slope", "fit_age_s", "r2_in_sample"],
             "RAW_PLUS_FACTORS": ["raw", "volatility", "trend_slope"]}
    diag = NZ.diagnostics(rows, ["volatility", "trend_slope"])
    return variants, elig, {"names": names, "diagnostics": diag}


def _quote_variants(inst: str, data: dict) -> tuple[dict | None, np.ndarray | None, dict]:
    from . import tick_store as TS
    d = TS.latest_replay(inst)
    if d is None:
        return None, None, {"status": "BLOCKED_NO_TICK_HISTORY", "reason": "brak archiwum ticków / replay (tick-export → tick-replay)"}
    with np.load(d / "quote_features.npz", allow_pickle=False) as z:
        qt, QF = z["t"], z["F"]
    pos = {int(round(x)): i for i, x in enumerate(qt)}
    n = len(data["fe"]["t"])
    QX = np.full((n, QF.shape[1]), np.nan)
    for i, t0 in enumerate(data["fe"]["t"]):
        j = pos.get(int(round(t0 + 60)))                         # quote state known at the M1 close
        if j is not None:
            QX[i] = QF[j]
    mask = np.isfinite(QX).all(axis=1) & (QX[:, -1] == 1.0)
    if mask.sum() < 1000:
        return None, None, {"status": "BLOCKED_NO_TICK_HISTORY", "reason": f"za mało M1 z kompletnym kontekstem ticków ({int(mask.sum())})", "replay": d.name}
    F = data["fe"]["F"]
    return ({"CORE": F, "ENRICHED": np.hstack([F, QX])}, mask,
            {"names": {"CORE": TAB, "ENRICHED": TAB + TS.FEATURES}, "replay": d.name, "rows_with_ticks": int(mask.sum())})


def train_experiment(inst: str, dsdir: Path, experiment: str, families: list[str], profile: str = "standard", db=None, log=print) -> dict:
    if experiment not in EXPERIMENTS:
        raise ValueError("EXPERIMENT_UNKNOWN")
    data = load_dataset(dsdir, TASK_MOVE)
    man = data["manifest"]
    if experiment == "MQ_NEUTRAL_REACTION_V1":
        variants, elig, info = _neutral_variants(data)
    else:
        variants, elig, info = _quote_variants(inst, data)
        if variants is None:
            return dict(info, experiment_id=experiment)
    base_rows = data["rows_idx"]
    keep = base_rows[elig[base_rows]]
    rejected = int(len(base_rows) - len(keep))
    data["rows_idx"] = keep                                      # the SAME rows for every variant (warm-up / failures reported)
    prof = PROFILES[profile]
    sp = split(data)
    synthetic = man["data_kind"] != "REAL_USER_DATA"
    rid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + uuid.uuid4().hex[:4] + "_" + experiment + ("_FIXTURE" if synthetic else "")
    rd = root(inst) / ("fixture_runs" if synthetic else "runs") / rid
    rd.mkdir(parents=True)
    Y, R = data["Y"][keep].astype(np.int64), data["R"][keep].astype(np.float64)
    rep = {"run_id": rid, "task_id": TASK_MOVE, "experiment_id": experiment, "protocol_id": PROTOCOL_ID, "dataset_id": man["dataset_id"], "split_hash": sp["hash"],
           "role": "TEST_ONLY" if synthetic else "RESEARCH", "rows": int(len(keep)), "rows_rejected_warmup_or_failure": rejected, "info": info,
           "evidence": evidence(data, sp, TASK_MOVE), "variants": {}, "created_at": datetime.now(timezone.utc).isoformat(), "profile": profile}
    fams = [f for f in families if f in ("LOGREG", "XGB")]
    for vname, X in variants.items():
        Xr = X[keep]
        vres = {}
        for fam in fams:
            folds = []
            for f in sp["folds"][-int(prof.get("max_folds") or 4):]:
                b = f["blocks"]
                if min(len(v) for v in b.values()) < 5 or not len(f["eval"]):
                    continue
                if fam == "XGB":
                    try:
                        import xgboost  # noqa: F401
                    except ImportError:
                        folds.append({"status": "NOT_AVAILABLE"})
                        break
                m = Tabular(fam, Y.shape[1]).fit(Xr, Y, R, b["FIT"], b["TUNE"])
                Pc, _ = m.predict(Xr[b["CALIBRATION"]])
                temps = [_temperature(Pc[:, j], Y[b["CALIBRATION"], j]) for j in range(Y.shape[1])]
                P, Qq = m.predict(Xr[f["eval"]])
                P = np.stack([_apply_T(P[:, j], temps[j]["T"]) for j in range(P.shape[1])], axis=1)
                base = Tabular("CLASS_FREQ", Y.shape[1]).fit(Xr, Y, R, b["FIT"])
                Pb, Qb = base.predict(Xr[f["eval"]])
                mm, mb = metrics(P, Qq, Y[f["eval"]], R[f["eval"]]), metrics(Pb, Qb, Y[f["eval"]], R[f["eval"]])
                folds.append({"fold": f["fold"], "metrics": mm, "logloss_gain_vs_class_freq": float(np.mean([b_["log_loss"] - a_["log_loss"] for a_, b_ in zip(mm, mb) if a_.get("n")]))})
            vres[fam] = {"folds": folds, "mean_gain": float(np.mean([x["logloss_gain_vs_class_freq"] for x in folds if "logloss_gain_vs_class_freq" in x]))
                         if any("logloss_gain_vs_class_freq" in x for x in folds) else None}
            fb = __import__("masterquo.ml.scalp_task", fromlist=["inner_blocks"]).inner_blocks(sp["dev"], sp["rows"], sp["embargo_s"])
            if min(len(v) for v in fb.values()) >= 5 and not (folds and folds[0].get("status") == "NOT_AVAILABLE"):
                m = Tabular(fam, Y.shape[1]).fit(Xr, Y, R, fb["FIT"], fb["TUNE"])
                Pc, _ = m.predict(Xr[fb["CALIBRATION"]])
                temps = [_temperature(Pc[:, j], Y[fb["CALIBRATION"], j]) for j in range(Y.shape[1])]
                d = rd / "models" / f"{vname}_{fam}"
                mh = save_candidate(d, fam, m, temps, dict(rep, class_order=list(SN.CLASSES), horizons=list(HORIZONS)), man)
                meta = json.loads((d / "candidate.json").read_text(encoding="utf-8"))
                meta.update(experiment_id=experiment, variant=vname, feature_names=info["names"][vname])
                (d / "experiment.json").write_text(json.dumps(meta, indent=1, default=_jd), encoding="utf-8")
                vres[fam]["candidate"] = {"candidate_id": f"{rid}-{vname}_{fam}", "model_hash": mh, "holdout": "NOT_EVALUATED_ON_HOLDOUT_BY_DESIGN"}
        rep["variants"][vname] = vres
        log(f"{experiment} {vname}: {[(k, v['mean_gain']) for k, v in vres.items()]}")
    rep["status"] = "EVALUATED_DEV" if rep["evidence"]["status"] == "OK" else "INSUFFICIENT_EVIDENCE"
    rep["note"] = ("residual ≠ alpha; porównanie RAW/NEUTRAL/RAW_PLUS_FACTORS na tych samych wierszach" if experiment == "MQ_NEUTRAL_REACTION_V1"
                   else "CORE vs ENRICHED na wspólnym okresie z kontekstem ticków")
    (rd / "report.json").write_text(json.dumps(rep, indent=1, default=_jd), encoding="utf-8")
    reg = _reg(inst)
    reg["runs"][rid] = {"run_dir": str(rd), "task": TASK_MOVE, "experiment": experiment, "status": rep["status"], "role": rep["role"], "created_at": rep["created_at"]}
    _save_reg(inst, reg)
    return rep
