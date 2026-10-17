"""M29 Fourier extrapolator with a forecast archive (MQ-LAB-FX-1.0.0).

Own implementation (the exact MQL5 'Extrapolator' variant with Npast/Nfut/MinHarmGain from the images could not be
identified): detrended window of the last n_past closes, harmonics chosen by periodogram power on THAT window, each kept only if
it reduces the in-window residual variance by >= min_harm_gain; extrapolated n_fut bars. Every forecast is archived at issue
time; evaluation always uses the archived path, never a curve recomputed later on a longer history.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

VERSION = "MQ-LAB-FX-1.0.0"


def extrapolate(c: np.ndarray, n_past: int = 256, n_fut: int = 20, max_harm: int = 8, min_harm_gain: float = 0.02) -> dict:
    if len(c) < n_past:
        return {"status": "warming_up", "reason": f"POTRZEBA_{n_past}_ZAMKNIETYCH"}
    y = np.asarray(c[-n_past:], float)
    x = np.arange(n_past)
    k, b0 = np.polyfit(x, y, 1)
    r = y - (k * x + b0)
    base_var = float(r.var()) or 1e-12
    spec = np.abs(np.fft.rfft(r)) ** 2
    order = np.argsort(spec[1:])[::-1] + 1
    harms, fit = [], np.zeros(n_past)
    for f in order[: max_harm * 3]:
        if len(harms) >= max_harm:
            break
        w = 2 * np.pi * f / n_past
        X = np.vstack([np.cos(w * x), np.sin(w * x)]).T
        ab, *_ = np.linalg.lstsq(X, r - fit, rcond=None)
        new = fit + X @ ab
        gain = (float((r - fit).var()) - float((r - new).var())) / base_var
        if gain < min_harm_gain:
            continue
        harms.append({"freq_index": int(f), "period_bars": round(n_past / f, 2), "a": float(ab[0]), "b": float(ab[1]), "gain": round(gain, 4)})
        fit = new
    xf = np.arange(n_past, n_past + n_fut)
    path = k * xf + b0
    for hm in harms:
        w = 2 * np.pi * hm["freq_index"] / n_past
        path = path + hm["a"] * np.cos(w * xf) + hm["b"] * np.sin(w * xf)
    explained = 1 - float((r - fit).var()) / base_var
    return {"status": "ready", "path": [float(v) for v in path], "harmonics": harms, "explained_in_window": round(explained, 4),
            "params": {"n_past": n_past, "n_fut": n_fut, "max_harm": max_harm, "min_harm_gain": min_harm_gain},
            "edge_note": "dopasowanie tylko do okna; koniec okna (efekt brzegowy) ma największą niepewność"}


def archive_record(asset: str, tf: str, as_of: str, last_open_utc: str, res: dict) -> dict:
    body = {"asset": asset, "tf": tf, "as_of": as_of, "last_bar": last_open_utc, "path": res["path"], "params": res["params"]}
    return {**body, "forecast_id": "FX-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16], "version": VERSION}


def evaluate(archive: list[dict], closes_by_open: dict[str, float], open_times: list[str]) -> dict:
    """Score archived forecasts against bars that closed AFTER their issue (step h uses the h-th later bar)."""
    errs, dir_hits, n_dir = [], 0, 0
    idx = {t: i for i, t in enumerate(open_times)}
    for f in archive:
        i0 = idx.get(f["last_bar"])
        if i0 is None:
            continue
        base = closes_by_open[f["last_bar"]]
        for h, p in enumerate(f["path"], start=1):
            j = i0 + h
            if j >= len(open_times):
                break
            act = closes_by_open[open_times[j]]
            errs.append(act - p)
            if h == len(f["path"]) or j == len(open_times) - 1:
                n_dir += 1
                dir_hits += int(np.sign(act - base) == np.sign(p - base))
    if not errs:
        return {"evaluated_points": 0}
    e = np.array(errs)
    return {"evaluated_points": len(e), "mae": float(np.abs(e).mean()), "bias": float(e.mean()),
            "direction_hit_rate": dir_hits / n_dir if n_dir else None, "direction_samples": n_dir,
            "note": "ocena z archiwum prognoz z chwili publikacji"}
