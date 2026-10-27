"""Walk-forward validation of the Monte Carlo variants on an exported dataset (closed M1 bars, optional Bid/Ask ticks).

Event (explicit, one per side x TP distance): "the price reaches TP before SL within H bars" for a position opened at the close of the
decision bar (BUY at Ask = Bid close + spread, closes at Bid; SELL at Bid, closes at Ask). The real outcome comes from the bars AFTER
the decision point; a bar touching TP and SL is resolved by the dataset's ticks when they cover it, otherwise it stays AMBIGUOUS and
is labelled by the declared conservative rule (SL first) - reported separately, never guessed.

Protocol: decision points every `stride` bars; each forecast uses only the `window` bars closed before the point (no look-ahead).
Chronological split CAL 50% / TEST 50% of the points after a warm-up, with an embargo of H bars at the border (horizons never overlap
the next block). On CAL: the variant with the best Brier score is chosen and an isotonic calibrator is fitted; TEST is touched once.
Baseline: the event frequency in the forecast's own window (climatology) - a model must beat it to be useful. Metrics: Brier, log
loss, reliability bins, n, positives, ambiguous share, bootstrap 95% interval of the Brier difference. Synthetic data -> technical
test only, never an active calibrator."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import engine as E

DEFAULT_EVENTS = [{"side": s, "tp": tp, "sl": 3.0} for s in ("BUY", "SELL") for tp in (2.5, 5.0)]


# ------------------------------------------------------------------ data
def load_dataset(ds: Path, tf: str = "M1") -> tuple[list[dict], dict]:
    from ..forecast.export import dataset_state
    ds = Path(ds)
    st = dataset_state(ds)
    if not st["usable"]:
        raise ValueError(f"DATASET_NOT_COMPLETE:{st['state']}")
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    point = float((meta.get("spec") or {}).get("point") or meta.get("tick_size") or 0.01)
    rows = []
    with (ds / f"{meta.get('file_prefix') or 'XAUUSD'}_{tf}.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sp = r.get("spread_points")
            rows.append({"open_utc": r["time_open_utc"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                         "spread_price": float(sp) * point if sp not in (None, "") else None})
    return rows, meta


class Ticks:
    """Ticks of the dataset (ticks/*.npz) for resolving the order of TP / SL inside one bar."""

    def __init__(self, ds: Path):
        self.t = self.bid = self.ask = None
        d = Path(ds) / "ticks"
        files = sorted(d.glob("ticks_*.npz")) if d.exists() else []
        if files:
            parts = []
            for f in files:
                with np.load(f) as z:
                    parts.append((z["time_msc_utc"].copy(), z["bid"].copy(), z["ask"].copy()))
            self.t = np.concatenate([p[0] for p in parts])
            self.bid = np.concatenate([p[1] for p in parts])
            self.ask = np.concatenate([p[2] for p in parts])

    def order(self, t0: float, t1: float, side: str, tp: float, sl: float) -> str | None:
        """'TP' / 'SL' first inside [t0, t1) from real quotes; None when ticks do not cover the bar."""
        if self.t is None:
            return None
        a, b = np.searchsorted(self.t, int(t0 * 1000)), np.searchsorted(self.t, int(t1 * 1000))
        if b <= a:
            return None
        px = self.bid[a:b] if side == "BUY" else self.ask[a:b]
        hit_tp = px >= tp if side == "BUY" else px <= tp
        hit_sl = px <= sl if side == "BUY" else px >= sl
        i_tp = int(hit_tp.argmax()) if hit_tp.any() else None
        i_sl = int(hit_sl.argmax()) if hit_sl.any() else None
        if i_tp is None and i_sl is None:
            return None
        if i_sl is None or (i_tp is not None and i_tp < i_sl):
            return "TP"
        return "SL"


def actual(bars: list[dict], i: int, H: int, side: str, tp_d: float, sl_d: float, spread: float, ticks: Ticks | None, step: int) -> tuple[int, bool]:
    """Outcome of the event opened at the close of bar i-1 (decision at its close): (1 = TP first, 0 = SL first / not reached, ambiguous)."""
    c0 = bars[i - 1]["c"]
    entry = c0 + spread if side == "BUY" else c0
    tp = entry + tp_d if side == "BUY" else entry - tp_d
    sl = entry - sl_d if side == "BUY" else entry + sl_d
    for k in range(i, min(i + H, len(bars))):
        b = bars[k]
        sp = b["spread_price"] if b["spread_price"] is not None else spread
        if side == "BUY":
            ht, hs = b["h"] >= tp, b["l"] <= sl
        else:
            ht, hs = b["l"] + sp <= tp, b["h"] + sp >= sl
        if ht and hs:
            t0 = E._ts(b["open_utc"])
            o = ticks.order(t0, t0 + step, side, tp, sl) if ticks is not None else None
            if o is None:
                return 0, True                                                     # declared rule: SL first (conservative)
            return (1 if o == "TP" else 0), False
        if ht:
            return 1, False
        if hs:
            return 0, False
    return 0, False


def outcomes(bars: list[dict], H: int, ev: dict, ticks: Ticks | None, step: int, fallback_spread: float) -> tuple[np.ndarray, np.ndarray]:
    """Outcome of the event opened at the close of every bar (spread of that bar, fallback the median): y[k], ambiguous[k] for k = 1..n-H."""
    n = len(bars)
    y, amb = np.full(n, np.nan), np.zeros(n, bool)
    for k in range(1, n - H):
        sp = bars[k - 1]["spread_price"]
        y[k], amb[k] = actual(bars, k, H, ev["side"], ev["tp"], ev["sl"], fallback_spread if sp is None else sp, ticks, step)
    return y, amb


def climatology(y: np.ndarray, i: int, H: int, window: int) -> float:
    """Baseline: event frequency of the outcomes fully known before decision point i (opened in the window, resolved by i)."""
    a, b = max(1, i - window), i - H + 1
    seg = y[a:b]
    seg = seg[np.isfinite(seg)]
    return float(seg.mean()) if len(seg) else float("nan")


# ------------------------------------------------------------------ metrics
def brier(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def logloss(p, y) -> float:
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability(p, y, bins: int = 10) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    out = []
    for k in range(bins):
        m = (p >= k / bins) & (p < (k + 1) / bins if k < bins - 1 else p <= 1)
        if m.any():
            out.append({"bin": [k / bins, (k + 1) / bins], "n": int(m.sum()), "mean_p": float(p[m].mean()), "freq": float(y[m].mean())})
    return out


def bootstrap_diff(pa, pb, y, n: int = 1000, seed: int = 11) -> list[float]:
    """95% interval of Brier(a) - Brier(b) (negative = a better), resampling decision points."""
    pa, pb, y = (np.asarray(x, float) for x in (pa, pb, y))
    rng = np.random.default_rng(seed)
    m = len(y)
    d = [(np.mean((pa[i] - y[i]) ** 2) - np.mean((pb[i] - y[i]) ** 2)) for i in (rng.integers(0, m, m) for _ in range(n))]
    return [float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975))]


def fit_calibrator(p, y) -> dict:
    from sklearn.isotonic import IsotonicRegression
    ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(np.asarray(p, float), np.asarray(y, float))
    return {"kind": "ISOTONIC", "x": [float(x) for x in ir.X_thresholds_], "y": [float(v) for v in ir.y_thresholds_]}


def apply_calibrator(cal: dict, p: float) -> float:
    c = cal.get("calibrator") or cal
    return float(np.interp(p, c["x"], c["y"])) if c.get("x") else float(p)


# ------------------------------------------------------------------ protocol
def validate(ds: Path, *, events=None, horizon: int = 60, window: int = 3000, stride: int = 30, n_paths: int = 500, max_points: int = 600,
             variants=E.VARIANTS, seed: int = 7, log=print) -> dict:
    t_start = time.time()
    bars, meta = load_dataset(ds)
    synthetic = meta.get("data_kind") != "REAL_USER_DATA"
    point = float((meta.get("spec") or {}).get("point") or meta.get("tick_size") or 0.01)
    events = events or DEFAULT_EVENTS
    step = 60
    ticks = Ticks(ds)
    pts = list(range(window, len(bars) - horizon, stride))
    if len(pts) > max_points:
        pts = [pts[int(k)] for k in np.linspace(0, len(pts) - 1, max_points)]
    rep = {"version": E.VERSION, "dataset": str(Path(ds).resolve()), "dataset_id": meta.get("dataset_id"), "data_kind": meta.get("data_kind"),
           "instrument": meta.get("instrument"), "symbol": meta.get("symbol"), "tf": "M1", "horizon_bars": horizon, "window_bars": window,
           "stride_bars": stride, "n_paths": n_paths, "seed": seed, "events": events, "variants": list(variants),
           "ticks_available": ticks.t is not None, "protocol": "walk-forward: CAL 50% / TEST 50% punktów, embargo H, wybór wariantu i kalibracja tylko na CAL"}
    if len(pts) < 60:
        return dict(rep, status="INSUFFICIENT_DATA", reason=f"{len(pts)} punktów decyzji < 60 (potrzeba ≥ {window + horizon + 60 * stride} świec M1)")
    cut = len(pts) // 2
    cal_pts = [x for x in pts[:cut] if x + horizon < pts[cut]]                     # embargo: CAL horizons end before TEST starts
    test_pts = pts[cut:]
    rows = []
    log(f"[..] Monte Carlo walidacja: {len(pts)} punktów decyzji, warianty {', '.join(variants)}, {n_paths} ścieżek")
    sps = [b["spread_price"] for b in bars if b["spread_price"] is not None]
    med_sp = float(np.median(sps)) if sps else 0.0
    outc = {json.dumps(ev, sort_keys=True): outcomes(bars, horizon, ev, ticks, step, med_sp) for ev in events}
    cal_set, test_set = set(cal_pts), set(test_pts)
    for j, i in enumerate(pts):
        as_of = E._ts(bars[i - 1]["open_utc"]) + step
        hist = E.history(bars[max(0, i - window):i], as_of, "M1", point, window)
        if hist.n < E.MIN_BARS:
            continue
        sims = {v: E.simulate(hist, n_paths, horizon, v, seed + i) for v in variants}
        sp0 = bars[i - 1]["spread_price"] if bars[i - 1]["spread_price"] is not None else med_sp
        for ev in events:
            ys, ambs = outc[json.dumps(ev, sort_keys=True)]
            c0 = bars[i - 1]["c"]
            entry = c0 + sp0 if ev["side"] == "BUY" else c0
            plan = E.Plan(ev["side"], entry, entry - ev["sl"] if ev["side"] == "BUY" else entry + ev["sl"],
                          [entry + ev["tp"] if ev["side"] == "BUY" else entry - ev["tp"]], horizon)
            row = {"i": i, "seg": "CAL" if i in cal_set else ("TEST" if i in test_set else "EMBARGO"), "event": f"{ev['side']}_TP{ev['tp']}_SL{ev['sl']}",
                   "y": int(ys[i]), "ambiguous": bool(ambs[i]), "base": climatology(ys, i, horizon, window)}
            for v, pth in sims.items():
                row[v] = E.evaluate(pth, c0, plan)["levels"][0]["p_tp_before_sl_conservative"]
            rows.append(row)
        if (j + 1) % 50 == 0:
            log(f"[POSTEP] montecarlo {j + 1}/{len(pts)}")
    cal = [r for r in rows if r["seg"] == "CAL" and math.isfinite(r["base"])]
    test = [r for r in rows if r["seg"] == "TEST" and math.isfinite(r["base"])]
    if len(cal) < 50 or len(test) < 50 or len({r["y"] for r in cal}) < 2:
        return dict(rep, status="INSUFFICIENT_DATA", reason=f"za mało zdarzeń (CAL {len(cal)}, TEST {len(test)}) albo jedna klasa")

    def block(rs, keys):
        y = [r["y"] for r in rs]
        out = {"n": len(rs), "positives": int(sum(y)), "ambiguous_share": float(np.mean([r["ambiguous"] for r in rs]))}
        for k in keys:
            p = [r[k] for r in rs]
            out[k] = {"brier": brier(p, y), "logloss": logloss(p, y)}
        return out
    keys = list(variants) + ["base"]
    cal_m = block(cal, keys)
    best = min(variants, key=lambda v: cal_m[v]["brier"])
    calib = fit_calibrator([r[best] for r in cal], [r["y"] for r in cal])
    for r in test:
        r["calibrated"] = apply_calibrator(calib, r[best])
    test_m = block(test, keys + ["calibrated"])
    yt = [r["y"] for r in test]
    ci = bootstrap_diff([r["calibrated"] for r in test], [r["base"] for r in test], yt)
    per_event = {}
    for ev in sorted({r["event"] for r in test}):
        rs = [r for r in test if r["event"] == ev]
        per_event[ev] = {"n": len(rs), "freq": float(np.mean([r["y"] for r in rs])), "brier_calibrated": brier([r["calibrated"] for r in rs], [r["y"] for r in rs]),
                         "brier_base": brier([r["base"] for r in rs], [r["y"] for r in rs])}
    edge = ci[1] < 0
    verdict = "TEST_TECHNICZNY" if synthetic else ("PRZEWAGA_NAD_BAZOWYM" if edge else "BRAK_POTWIERDZONEJ_PRZEWAGI")
    rep.update(status="DONE", chosen_variant=best, cal=cal_m, test=test_m, test_per_event=per_event,
               reliability_test=reliability([r["calibrated"] for r in test], yt), brier_diff_calibrated_minus_base_ci95=ci, verdict=verdict,
               calibrator={"variant": best, "calibrator": calib, "fitted_on": "CAL", "events": events, "horizon_bars": horizon},
               endpoint_reference="MarkovDiff (flow_context) symuluje tylko zamknięcia – nie ocenia TP/SL; porównanie ścieżek dotyczy wariantów IID/BLOCK/REGIME",
               seconds=round(time.time() - t_start, 1))
    return rep


# ------------------------------------------------------------------ registry (atomic, with rollback)
def root(inst: str) -> Path:
    import mq_instruments as mi
    d = mi.data_dir() / "montecarlo" / inst
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
    os.replace(tmp, p)


def save(inst: str, rep: dict) -> dict:
    """Run folder + registry. Only REAL_USER_DATA with an edge over the baseline becomes the ACTIVE calibrator; the previous one stays
    in history (rollback). Synthetic / no edge -> saved for research."""
    rid = "MC-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(json.dumps(rep, default=str).encode()).hexdigest()[:6]
    d = root(inst) / "runs" / rid
    _write(d / "report.json", rep)
    reg_p = root(inst) / "registry.json"
    try:
        reg = json.loads(reg_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reg = {"active": None, "history": [], "runs": {}}
    activate = rep.get("status") == "DONE" and rep.get("data_kind") == "REAL_USER_DATA" and rep.get("verdict") == "PRZEWAGA_NAD_BAZOWYM"
    reg["runs"][rid] = {"created_at": datetime.now(timezone.utc).isoformat(), "status": rep.get("status"), "verdict": rep.get("verdict"),
                        "variant": rep.get("chosen_variant"), "data_kind": rep.get("data_kind"), "dataset_id": rep.get("dataset_id"),
                        "report": str(d / "report.json"), "report_sha256": hashlib.sha256((d / "report.json").read_bytes()).hexdigest()}
    if activate:
        _write(d / "calibrator.json", dict(rep["calibrator"], run_id=rid, status="ACTIVE"))
        if reg.get("active"):
            reg["history"].append(reg["active"])
        reg["active"] = rid
    _write(reg_p, reg)
    return {"run_id": rid, "activated": activate, "dir": str(d)}


def active_calibrator(inst: str) -> dict | None:
    try:
        reg = json.loads((root(inst) / "registry.json").read_text(encoding="utf-8"))
        rid = reg.get("active")
        return json.loads((root(inst) / "runs" / rid / "calibrator.json").read_text(encoding="utf-8")) if rid else None
    except (OSError, ValueError, TypeError):
        return None


def rollback(inst: str) -> dict:
    reg_p = root(inst) / "registry.json"
    reg = json.loads(reg_p.read_text(encoding="utf-8"))
    prev = reg["history"].pop() if reg.get("history") else None
    reg["active"] = prev
    _write(reg_p, reg)
    return {"active": prev}
