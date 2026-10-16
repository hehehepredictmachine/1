"""Signal analysis of the price series: FFT (MQ-FFT-1.0.0), EMD (MQ-EMD-1.0.0), VMD (MQ-VMD-1.0.0).

Implementation choice (documented in docs/ANALITYKA_BB_MA_VMD_FFT_EMD_DOUBLE_BOTTOM_PL.md): numpy + scipy that the bot already
ships (scipy.signal.periodogram, scipy.interpolate.CubicSpline). No sktime / PyEMD / vmdpy dependency is added: sktime is
a large stack for one transformer, and the "EMD" name on PyPI is ambiguous (PyEMD = Empirical Mode Decomposition, package
EMD-signal; "pyemd" = Earth Mover's Distance). VMD follows the published ADMM algorithm of Dragomiretskiy & Zosso (2014)
(same structure as the MIT-licensed vmdpy reference); EMD is standard sifting (Huang 1998) with explicit stop criteria.

Causality: every call receives ONLY closed bars up to t (the caller passes the prefix). Padding uses observed samples only
(VMD: mirror extension of the window itself; EMD: end points used as extrema - method recorded). Results for a decision are
archived by the service; a later, longer decomposition never rewrites them. End-of-window revision is MEASURED (the same
analysis on the window ending `revision_lag` bars earlier) and reported - not hidden.

Input regularity: the window must be a contiguous run of bars of the TF (no gaps, no session breaks inside). If the latest
contiguous segment is shorter than the minimum, the result is `unavailable` with reason GAP_IN_WINDOW - gaps are never
filled with zeros or forward-filled prices.
None of these modules predicts direction; they describe the recent series. Three transforms of the same price are never
three independent confirmations.
"""
from __future__ import annotations

import math
import time

import numpy as np

from . import contract
from .ta import TF_SEC

FFT_VERSION, EMD_VERSION, VMD_VERSION = "MQ-FFT-1.0.0", "MQ-EMD-1.0.0", "MQ-VMD-1.0.0"
DEFAULT = {"window": 256, "min_window": 128, "fft_input": "log_returns", "fft_window": "hann", "vmd_k": 4, "vmd_alpha": 2000.0,
           "vmd_tol": 1e-7, "vmd_max_iter": 500, "emd_max_imfs": 8, "emd_max_sift": 50, "emd_sd_stop": 0.2, "revision_lag": 5}


def _ts(s: str) -> int:
    from datetime import datetime
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def contiguous_tail(bars: list[dict], tf: str, window: int) -> tuple[list[dict], int]:
    """Latest run of consecutive bars (step == TF seconds), at most `window` long. Returns (bars, gaps_seen_in_window)."""
    step = TF_SEC.get(tf, 60)
    out = [bars[-1]] if bars else []
    gaps = 0
    for b in reversed(bars[:-1]):
        if len(out) >= window:
            break
        if _ts(out[0]["open_utc"]) - _ts(b["open_utc"]) != step:
            gaps += 1
            break
        out.insert(0, b)
    return out, gaps


def _prep(bars, tf, cfg, module, version, symbol):
    t0 = time.perf_counter()
    seg, gaps = contiguous_tail(bars, tf, int(cfg["window"]))
    if len(seg) < int(cfg["min_window"]):
        r = contract.result(module, version, cfg, symbol=symbol, tf=tf, bars=seg, status="unavailable" if gaps else "warming_up",
                            reason=("GAP_IN_WINDOW: ciągły odcinek " if gaps else "WARMUP: ") + f"{len(seg)}/{cfg['min_window']} świec",
                            t0=t0, tf_seconds=TF_SEC.get(tf))
        return None, None, r, t0
    c = np.asarray([b["c"] for b in seg], dtype=float)
    if not np.all(np.isfinite(c)) or np.any(c <= 0):
        return None, None, contract.result(module, version, cfg, symbol=symbol, tf=tf, bars=seg, status="error", reason="INVALID_PRICES", t0=t0), t0
    return seg, c, None, t0


# ------------------------------------------------------------------ FFT
def periodogram(x: np.ndarray, detrend: str, window: str = "hann"):
    from scipy.signal import periodogram as _pg
    f, p = _pg(x, fs=1.0, window=window, detrend=detrend, scaling="spectrum", return_onesided=True)
    return f, p


def fft_analysis(bars: list[dict], tf: str, cfg: dict | None = None, symbol: str | None = None) -> dict:
    cfg = {**DEFAULT, **(cfg or {})}
    seg, c, err, t0 = _prep(bars, tf, cfg, "fft", FFT_VERSION, symbol)
    if err:
        return err
    if cfg["fft_input"] == "log_returns":
        x, det, inp = np.diff(np.log(c)), "constant", "log stopy zwrotu (diff log close), detrend: średnia"
    else:
        x, det, inp = np.log(c), "linear", "log close, detrend: liniowy"

    def spectrum(xx):
        f, p = periodogram(xx, det, cfg["fft_window"])
        m = f > 0
        return f[m], p[m]
    f, p = spectrum(x)
    if not np.any(p > 0):
        return contract.result("fft", FFT_VERSION, cfg, symbol=symbol, tf=tf, bars=seg, status="ready", t0=t0, tf_seconds=TF_SEC.get(tf),
                               values={"flat": True, "dominant": [], "input": inp}, reason="FLAT_SIGNAL", quality=["FLAT_SIGNAL"])
    share = p / p.sum()
    order = np.argsort(p)[::-1]
    peaks = []
    for j in order:
        if 0 < j < len(p) - 1 and p[j] >= p[j - 1] and p[j] >= p[j + 1]:
            peaks.append(int(j))
        if len(peaks) == 3:
            break
    tfm = TF_SEC.get(tf, 60) / 60.0
    dom = [{"frequency_cycles_per_bar": round(float(f[j]), 6), "period_bars": round(float(1 / f[j]), 2), "period_minutes": round(float(1 / f[j]) * tfm, 1),
            "power_share": round(float(share[j]), 4), "peak_to_median": round(float(p[j] / np.median(p)), 2)} for j in peaks]
    # stability: the same analysis on the window ending revision_lag bars earlier (past data only)
    lag = int(cfg["revision_lag"])
    stable = None
    if dom and len(x) > lag + 32:
        f2, p2 = spectrum(x[:-lag])
        j2 = int(np.argmax(p2))
        stable = abs(1 / f2[j2] - dom[0]["period_bars"]) / dom[0]["period_bars"] < 0.2
    q = []
    if not dom or dom[0]["peak_to_median"] < 5:
        q.append("NO_DOMINANT_PEAK")
    if stable is False:
        q.append("UNSTABLE_DOMINANT_PERIOD")
    if dom and dom[0]["period_bars"] < 2.5:
        q.append("DOMINANT_NEAR_NYQUIST")              # 2-bar "cycle" = bar-to-bar noise, not a market cycle
    if dom and dom[0]["period_bars"] > len(x) / 3:
        q.append("PERIOD_TOO_LONG_FOR_WINDOW")
    keep = (1 / f >= 2) & (1 / f <= len(x) / 2)
    sel = np.argsort(f[keep])
    spec = [{"period_bars": round(float(1 / fv), 2), "frequency": round(float(fv), 6), "power_share": round(float(sv), 5)}
            for fv, sv in zip(f[keep][sel], share[keep][sel])]
    vals = {"input": inp, "window_bars": len(seg), "sampling": f"1 próbka = 1 świeca {tf} ({tfm:g} min)", "window_function": cfg["fft_window"],
            "normalization": "periodogram scaling=spectrum, udział mocy = P / ΣP (bez składowej 0)", "zero_padding": "brak",
            "dominant": dom, "dominant_stable": stable, "spectrum": spec[-128:], "quality_ok": not q,
            "note": "widmo opisuje ostatnie okno – nie wyznacza kierunku ceny"}
    return contract.result("fft", FFT_VERSION, cfg, symbol=symbol, tf=tf, bars=seg, status="ready", values=vals, quality=q, t0=t0, tf_seconds=TF_SEC.get(tf))


# ------------------------------------------------------------------ EMD
def _extrema(x: np.ndarray):
    d = np.diff(x)
    mx = np.where((np.hstack([d, 0]) < 0) & (np.hstack([0, d]) > 0))[0]
    mn = np.where((np.hstack([d, 0]) > 0) & (np.hstack([0, d]) < 0))[0]
    return mx, mn


def emd(x: np.ndarray, max_imfs: int = 8, max_sift: int = 50, sd_stop: float = 0.2) -> tuple[list[np.ndarray], np.ndarray, dict]:
    from scipy.interpolate import CubicSpline
    n = len(x)
    t = np.arange(n)
    r = x.copy()
    imfs = []
    sifts = []
    for _ in range(max_imfs):
        mx, mn = _extrema(r)
        if len(mx) + len(mn) < 3:
            break
        h = r.copy()
        it = 0
        for it in range(1, max_sift + 1):
            mx, mn = _extrema(h)
            if len(mx) < 2 or len(mn) < 2:
                break
            ix = np.unique(np.r_[0, mx, n - 1])            # end points as envelope knots (observed samples only)
            iy = np.unique(np.r_[0, mn, n - 1])
            up = CubicSpline(ix, h[ix])(t)
            lo = CubicSpline(iy, h[iy])(t)
            m = (up + lo) / 2
            h_new = h - m
            sd = float(np.sum((h - h_new) ** 2) / max(np.sum(h ** 2), 1e-300))
            h = h_new
            if sd < sd_stop:
                break
        imfs.append(h)
        sifts.append(it)
        r = r - h
    return imfs, r, {"sifts": sifts, "envelope_ends": "punkty końcowe okna jako węzły obwiedni (tylko obserwowane próbki)"}


def _zero_cross_period(v: np.ndarray) -> float | None:
    zc = int(np.sum(np.diff(np.sign(v - v.mean())) != 0))
    return None if zc < 2 else round(2 * len(v) / zc, 2)


def emd_analysis(bars: list[dict], tf: str, cfg: dict | None = None, symbol: str | None = None) -> dict:
    cfg = {**DEFAULT, **(cfg or {})}
    seg, c, err, t0 = _prep(bars, tf, cfg, "emd", EMD_VERSION, symbol)
    if err:
        return err
    x = np.log(c)
    x = x - x[0]
    imfs, res, meta = emd(x, int(cfg["emd_max_imfs"]), int(cfg["emd_max_sift"]), float(cfg["emd_sd_stop"]))
    if not all(np.all(np.isfinite(v)) for v in imfs + [res]):
        return contract.result("emd", EMD_VERSION, cfg, symbol=symbol, tf=tf, bars=seg, status="error", reason="NON_FINITE_RESULT", t0=t0)
    rec = (np.sum(imfs, axis=0) if imfs else 0) + res
    err_rec = float(np.max(np.abs(rec - x)))
    tot = float(sum(np.sum(v ** 2) for v in imfs)) or 1e-300
    comps = [{"imf": k + 1, "energy_share": round(float(np.sum(v ** 2)) / tot, 4), "mean_period_bars": _zero_cross_period(v), "sifts": meta["sifts"][k],
              "last_value": round(float(v[-1]), 7)} for k, v in enumerate(imfs)]
    lag = int(cfg["revision_lag"])
    rev = None
    if len(x) > lag + 64 and imfs:
        im2, r2, _ = emd(x[:-lag], int(cfg["emd_max_imfs"]), int(cfg["emd_max_sift"]), float(cfg["emd_sd_stop"]))
        slow1 = res[-lag - 1]
        slow2 = r2[-1]
        rev = round(float(abs(slow1 - slow2) / (np.std(x) or 1e-12)), 4)
    q = []
    if len(imfs) < 2:
        q.append("FEW_IMFS")
    if rev is not None and rev > 0.5:
        q.append("END_OF_WINDOW_REVISION_HIGH")
    if any(s >= int(cfg["emd_max_sift"]) for s in meta["sifts"]):
        q.append("SIFT_LIMIT_REACHED")
    trend = float(res[-1] - res[-6]) if len(res) > 6 else None
    vals = {"input": "log close (od pierwszej świecy okna)", "window_bars": len(seg), "imfs": comps, "n_imfs": len(imfs),
            "residual_last": round(float(res[-1]), 7), "residual_slope_5_bars": None if trend is None else round(trend, 7),
            "reconstruction_max_abs_error": err_rec, "end_revision_vs_lag": rev, "revision_lag_bars": lag, "method": meta["envelope_ends"],
            "series": {"imf_last_64": [[round(float(v), 7) for v in imf[-64:]] for imf in imfs[:4]], "residual_last_64": [round(float(v), 7) for v in res[-64:]]},
            "quality_ok": not q, "note": "rozkład opisuje okno; składowe przy końcu okna mogą się zmienić po nowych świecach (mierzone)"}
    return contract.result("emd", EMD_VERSION, cfg, symbol=symbol, tf=tf, bars=seg, status="ready", values=vals, quality=q, t0=t0, tf_seconds=TF_SEC.get(tf))


# ------------------------------------------------------------------ VMD
def vmd(f: np.ndarray, alpha: float = 2000.0, tau: float = 0.0, K: int = 4, DC: bool = True, tol: float = 1e-7, max_iter: int = 500,
        deadline: float | None = None):
    """ADMM VMD (Dragomiretskiy & Zosso 2014). Mirror extension of the window (observed samples only). Memory-light: keeps
    only the current and previous iterate. Returns (modes K x N, omega K (cycles/sample), iterations, converged)."""
    if len(f) % 2:
        f = f[1:]
    T0 = len(f)
    half = T0 // 2
    fm = np.concatenate([f[:half][::-1], f, f[-half:][::-1]])
    T = len(fm)
    freqs = np.arange(1, T + 1) / T - 0.5 - 1 / T
    f_hat = np.fft.fftshift(np.fft.fft(fm))
    f_hat_plus = f_hat.copy()
    f_hat_plus[: T // 2] = 0
    u = np.zeros((K, T), dtype=complex)
    omega = np.array([0.5 / K * i for i in range(K)], dtype=float)
    if DC:
        omega[0] = 0.0
    lam = np.zeros(T, dtype=complex)
    n, udiff, conv = 0, tol + 1.0, False
    pos = slice(T // 2, T)
    while n < max_iter:
        u_old = u.copy()
        for k in range(K):
            others = u.sum(axis=0) - u[k]
            u[k] = (f_hat_plus - others - lam / 2) / (1.0 + alpha * (freqs - omega[k]) ** 2)
            if not (DC and k == 0):
                w = np.abs(u[k, pos]) ** 2
                omega[k] = float(np.dot(freqs[pos], w) / w.sum()) if w.sum() > 0 else omega[k]
        lam = lam + tau * (u.sum(axis=0) - f_hat_plus)
        n += 1
        udiff = float(np.sum(np.abs(u - u_old) ** 2) / T)
        if udiff < tol:
            conv = True
            break
        if deadline is not None and time.perf_counter() > deadline:
            break
    u_full = np.zeros((K, T), dtype=complex)
    u_full[:, T // 2:] = u[:, T // 2:]
    idx = np.arange(1, T // 2 + 1)[::-1]
    u_full[:, idx] = np.conj(u[:, T // 2:])
    u_full[:, 0] = np.conj(u_full[:, -1])
    modes = np.real(np.fft.ifft(np.fft.ifftshift(u_full, axes=1), axis=1))[:, T // 4: 3 * T // 4]
    order = np.argsort(omega)
    return modes[order], omega[order], n, conv


def vmd_analysis(bars: list[dict], tf: str, cfg: dict | None = None, symbol: str | None = None, timeout_s: float = 10.0) -> dict:
    cfg = {**DEFAULT, **(cfg or {})}
    seg, c, err, t0 = _prep(bars, tf, cfg, "vmd", VMD_VERSION, symbol)
    if err:
        return err
    K = int(cfg["vmd_k"])
    if not 2 <= K <= 8:
        return contract.result("vmd", VMD_VERSION, cfg, symbol=symbol, tf=tf, bars=seg, status="error", reason="INVALID_CONFIG: vmd_k 2..8", t0=t0)
    x = np.log(c)
    x = x - x.mean()
    scale = float(np.std(x)) or 1.0                    # unit-variance input: the tolerance is scale-free (rescaled back below)
    x = x / scale
    deadline = time.perf_counter() + timeout_s
    modes, omega, iters, conv = vmd(x, float(cfg["vmd_alpha"]), 0.0, K, True, float(cfg["vmd_tol"]), int(cfg["vmd_max_iter"]), deadline)
    if not np.all(np.isfinite(modes)):
        return contract.result("vmd", VMD_VERSION, cfg, symbol=symbol, tf=tf, bars=seg, status="error", reason="NON_FINITE_RESULT", t0=t0)
    xs = x[1:] if len(x) % 2 else x
    rec = modes.sum(axis=0)
    rel_err = float(np.linalg.norm(rec - xs) / (np.linalg.norm(xs) or 1e-300))
    en = np.sum(modes ** 2, axis=1)
    share = en / (en.sum() or 1e-300)
    tfm = TF_SEC.get(tf, 60) / 60.0
    comps = []
    for k in range(K):
        per = None if omega[k] <= 1e-9 else float(1 / omega[k])
        role = ("TREND_HYPOTHESIS" if k == 0 else "NOISE_HYPOTHESIS" if k == K - 1 else "CYCLE_HYPOTHESIS")
        comps.append({"mode": k + 1, "center_frequency_cycles_per_bar": round(float(omega[k]), 6), "period_bars": None if per is None else round(per, 2),
                      "period_minutes": None if per is None else round(per * tfm, 1), "energy_share": round(float(share[k]), 4), "role": role,
                      "last_value": round(float(modes[k, -1] * scale), 7)})
    lag = int(cfg["revision_lag"])
    stab = None
    if len(x) > lag + 64 and time.perf_counter() < deadline:
        _, om2, _, _ = vmd(x[:-lag], float(cfg["vmd_alpha"]), 0.0, K, True, float(cfg["vmd_tol"]), int(cfg["vmd_max_iter"]), deadline)
        stab = round(float(np.max(np.abs(om2[1:] - omega[1:]) / np.maximum(omega[1:], 1e-9))), 4)
    q = []
    if not conv:
        q.append("NOT_CONVERGED" if time.perf_counter() <= deadline else "TIMEOUT")
    if rel_err > 0.2:
        q.append("HIGH_RECONSTRUCTION_ERROR")
    if stab is not None and stab > 0.3:
        q.append("MODES_UNSTABLE_BETWEEN_WINDOWS")
    vals = {"input": "log close minus średnia okna", "window_bars": len(seg), "K": K, "alpha": cfg["vmd_alpha"], "tau": 0.0, "DC": True,
            "tol": cfg["vmd_tol"], "iterations": iters, "converged": conv, "modes": comps, "reconstruction_rel_error": round(rel_err, 5),
            "residual_rel": round(rel_err, 5), "omega_change_vs_lag": stab, "revision_lag_bars": lag,
            "assignment_rule": "mody sortowane wg częstotliwości środkowej: najniższa = hipoteza trendu, najwyższa = hipoteza szumu, pozostałe = cykle; "
                               "numer modu nie jest gwarancją znaczenia – sprawdzana stabilność między oknami",
            "padding": "odbicie lustrzane okna (tylko obserwowane próbki)",
            "series": {"modes_last_64": [[round(float(v * scale), 7) for v in m[-64:]] for m in modes]}, "input_scale": scale, "quality_ok": not q}
    return contract.result("vmd", VMD_VERSION, cfg, symbol=symbol, tf=tf, bars=seg, status="ready", values=vals, quality=q, t0=t0, tf_seconds=TF_SEC.get(tf))


def _round_list(v, n=6):
    return [None if (x is None or (isinstance(x, float) and math.isnan(x))) else round(float(x), n) for x in v]
