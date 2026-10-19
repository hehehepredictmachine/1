"""MQ_NEWTONIAN_QUOTES_V2 (PMW-UPD-08 R19) - multi-scale local kinematics of Bid and Ask SEPARATELY + causal forecast scoreboard.

Own implementation inspired by the public description of NewtonianMechanics (Code Base 78046); the original MQ5 sources / error-floor
formula were not read: NO parity is claimed. Legacy mid kinematics (lab/ticks.py, M31) stays as an adapter. p/v/a describe a LOCAL
STATISTICAL model, not a physical law of price; turning time is an extrapolation hypothesis. Nothing here places orders.

Ticks: the same MT5 worker/bridge (raw time_msc kept, t_ms = UTC ms after the measured server offset, source order `ord`). Bid updates
only when Bid changes, Ask only when Ask changes. Per side a pending bucket per timestamp keeps the LAST price in source order and
becomes an observation only when a LATER timestamp of that side arrives (no invented positive gaps, A->B->A in one ms kept in order).
Coarse clock (first 200 ticks all on whole seconds) -> bucket to seconds and flag COARSE_CLOCK.
Scales: Kish effective sample size targets 16 / 64 / 256 UPDATES (not seconds): rho = (N-1)/(N+1), w_j = rho^age_j (age in updates),
history kept until w < 1e-6; reported n_eff = (sum w)^2 / sum w^2 (finite), unique times, span. Warm = n_eff >= 0.95 N and rank/span OK;
earlier -> PRELIMINARY. Minimum for a fit: 8 unique times, n_eff >= 12, rank 3.
Fit per side/scale with origin t0 = last observation, T_s = span: u = (t - t0)/T_s, X = [1, u, u^2/2], weighted LS via sqrt(w) + lstsq
(SVD) -> position, v = theta1/T_s (price/s), a = theta2/T_s^2 (price/s^2), also in points/s.
Uncertainty: classical C_iid = s^2 H H^T and own random-walk + quantisation model C_RW = q H K H^T + nu^2 H H^T with K_ij = min(t_i,t_j)-t_min,
nu^2 = tick^2/12, q from increments of the fit residuals (minus the quantisation part) / sum dt; H K H^T via suffix sums U_j (O(m p^2)).
SE_used = max(SE_classical, SE_RW) per parameter -> z_v, z_a (diagnostics, not win probability). Forecast error variances:
  V_RW(h) = q [h + sum_j dt_j (1 - x_h.U_j)^2] + nu^2 [1 + sum_i (x_h.H_i)^2],  V_iid(h) = x_h C_iid x_h^T + s^2,  se_model = max of both roots.
Empirical band only from earlier matured, non-overlapping errors normalised by se_model at emission (else MODEL_BAND_UNCALIBRATED).
Spread: direct model on simultaneous valid pairs (Ask-Bid): level, slope, efficiency |end-start| / sum |changes| (null if 0).
Turning time -v/a: requires |z_a| >= 2, v*a < 0, 0 < t <= 60 s; SE by delta method with Cov(v,a); else UNSTABLE_TURN_TIME.
Phase (slow scale 256, fast 16; frozen order + hysteresis 3 slow updates and >= 1 s, STRESSED immediate): WARMING, STRESSED,
RETRACEMENT, EXPANSION, CONSOLIDATION, UNDETERMINED.
Forecast emission (primary stream per side/scale, non-overlapping): h = min(0.25 * span, 10 s) > clock resolution; issued at the real
computation time; projection over age + h from t0. Outcome = first valid quote of that side in [target, target + max_lag], max_lag =
min(1 s, max(clock_res, 0.25 h)); none -> UNSCORED_GAP (neither hit nor miss). Each forecast scored once.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np

VERSION = "MQ_NEWTONIAN_QUOTES_V2"
SCALES = (16, 64, 256)
CFG = {"min_unique_times": 8, "min_neff": 12.0, "tail_weight": 1e-6, "max_hist": 4000, "max_side_age_s": 5.0, "gap_reset_s": 30.0, "z_sig": 2.0,
       "z_flat": 1.0, "h_frac": 0.25, "h_max_s": 10.0, "turn_max_s": 60.0, "max_cond": 1e12, "hyst_updates": 3, "hyst_s": 1.0, "max_spread": None,
       "calib_min": 50, "band_q": 0.9}


def kish(w: np.ndarray) -> float:
    return float(w.sum() ** 2 / np.sum(w * w)) if len(w) else 0.0


class Side:
    """Closed observations of ONE side (pending bucket per timestamp)."""

    def __init__(self, name: str):
        self.name = name
        self.t: list[float] = []          # seconds (UTC, relative to the engine origin)
        self.y: list[float] = []
        self.pending: tuple[int, float] | None = None
        self.last_price: float | None = None
        self.updates = 0
        self.flags: set[str] = set()

    def push(self, t_ms: int, price: float, origin_ms: int, cfg: dict) -> None:
        if self.last_price is not None and price == self.last_price:
            return                                                   # same price is not a new observation of this side
        self.last_price = price
        if self.pending is not None:
            if t_ms < self.pending[0]:
                self.flags.add("OUT_OF_ORDER")
                return
            if t_ms == self.pending[0]:
                self.pending = (t_ms, price)                         # last price of the bucket in source order
                return
            self._close(origin_ms, cfg)
        self.pending = (t_ms, price)

    def _close(self, origin_ms: int, cfg: dict) -> None:
        t = (self.pending[0] - origin_ms) / 1000.0
        if self.t and t - self.t[-1] > cfg["gap_reset_s"]:
            self.t, self.y = [], []
            self.flags.add("GAP_RESET")
        self.t.append(t)
        self.y.append(self.pending[1])
        self.updates += 1
        if len(self.t) > cfg["max_hist"]:
            self.t, self.y = self.t[-cfg["max_hist"]:], self.y[-cfg["max_hist"]:]


def fit_side(t: list[float], y: list[float], N: int, tick: float, point: float, cfg: dict = CFG) -> dict:
    """Weighted local quadratic fit with classical and random-walk uncertainty."""
    rho = (N - 1.0) / (N + 1.0)
    m_max = int(math.ceil(math.log(cfg["tail_weight"]) / math.log(rho))) + 1
    tt, yy = np.array(t[-m_max:], float), np.array(y[-m_max:], float)
    m = len(tt)
    out = {"scale": N, "n_obs": m}
    if m < 3:
        return dict(out, status="INSUFFICIENT_HISTORY")
    age = np.arange(m - 1, -1, -1, dtype=float)
    w = rho ** age
    ne = kish(w)
    t0 = tt[-1]
    span = float(t0 - tt[0])
    uniq = int(len(np.unique(tt)))
    out.update(n_eff=ne, unique_times=uniq, span_s=span, warm=bool(ne >= 0.95 * N))
    if uniq < cfg["min_unique_times"] or ne < cfg["min_neff"] or span <= 0:
        return dict(out, status="RANK_OR_SPAN_TOO_SMALL")
    u = (tt - t0) / span
    X = np.stack([np.ones(m), u, 0.5 * u * u], axis=1)
    sw = np.sqrt(w)
    theta, _, rank, sv = np.linalg.lstsq(X * sw[:, None], yy * sw, rcond=1e-12)
    cond = float(sv[0] / sv[-1]) if sv[-1] > 0 else float("inf")
    if rank < 3 or cond > cfg["max_cond"]:
        return dict(out, status="RANK_DEFICIENT", condition=cond)
    e = yy - X @ theta
    A = X.T @ (X * w[:, None])
    H = np.linalg.solve(A, X.T * w[None, :])                      # (3, m) influence matrix, no explicit inverse
    dof = max(1.0, ne - 3.0)
    s2 = float(np.sum(w * e * e) / w.sum() * ne / dof)
    C_iid = s2 * H @ H.T
    nu2 = (tick ** 2) / 12.0 if tick > 0 else None
    dt = np.diff(tt, prepend=tt[0])
    de = np.diff(e)
    pos_dt = float(np.sum(dt[dt > 0]))
    q = None
    if nu2 is not None and pos_dt > 0 and len(de):
        q = max(0.0, (float(np.sum(de * de)) - 2.0 * nu2 * len(de)) / pos_dt * (len(de) / max(1, len(de) - 3)))
    U = np.cumsum(H[:, ::-1], axis=1)[:, ::-1]                     # U_j = sum_{i>=j} H[:, i]
    out_rw = None
    if q is not None:
        HKH = (U * dt[None, :]) @ U.T
        C_rw = q * HKH + nu2 * H @ H.T
        out_rw = C_rw
    J = np.diag([1.0, 1.0 / span, 1.0 / span ** 2])
    Pc = J @ C_iid @ J.T
    Pr = J @ out_rw @ J.T if out_rw is not None else None
    se_c = np.sqrt(np.maximum(np.diag(Pc), 0))
    se_r = np.sqrt(np.maximum(np.diag(Pr), 0)) if Pr is not None else None
    se_u = np.maximum(se_c, se_r) if se_r is not None else se_c
    v, a = float(theta[1] / span), float(theta[2] / span ** 2)

    def z(x, s):
        return None if s <= 0 else x / s
    res = dict(out, status="OK" if out["warm"] else "PRELIMINARY", t0=float(t0), position=float(theta[0]), velocity=v, acceleration=a,
               velocity_points_s=v / point if point else None, acceleration_points_s2=a / point if point else None,
               se_classical=se_c.tolist(), se_rw=None if se_r is None else se_r.tolist(), se_used=se_u.tolist(),
               z_v=z(v, se_u[1]), z_a=z(a, se_u[2]), cov_classical=Pc.tolist(), cov_rw=None if Pr is None else Pr.tolist(),
               q=q, nu2=nu2, s2=s2, condition=cond, rw_status="OK" if q is not None else "NO_TICK_SIZE_OR_INCREMENTS")
    res["_H"], res["_U"], res["_dt"], res["_C_iid"] = H, U, dt, C_iid
    # turning time
    cov = Pr if Pr is not None else Pc
    zz = res["z_a"]
    if zz is not None and abs(zz) >= cfg["z_sig"] and v * a < 0 and 0 < -v / a <= cfg["turn_max_s"]:
        g = np.array([-1.0 / a, v / a ** 2])
        sub = np.array([[cov[1][1], cov[1][2]], [cov[2][1], cov[2][2]]])
        res["turning_time_s"] = -v / a
        res["turning_time_se"] = float(math.sqrt(max(0.0, g @ sub @ g)))
        res["turning_status"] = "OK"
    else:
        res["turning_time_s"], res["turning_time_se"], res["turning_status"] = None, None, "UNSTABLE_TURN_TIME"
    return res


def forecast_variance(fit: dict, h: float) -> dict:
    """h = seconds AFTER the fit origin t0 (age + horizon). Returns RW / iid error variances and se_model."""
    span = fit["span_s"]
    x = np.array([1.0, h / span, 0.5 * (h / span) ** 2])
    H, U, dt = fit["_H"], fit["_U"], fit["_dt"]
    v_iid = float(x @ fit["_C_iid"] @ x + fit["s2"])
    v_rw = None
    if fit.get("q") is not None and fit.get("nu2") is not None:
        v_rw = float(fit["q"] * (h + np.sum(dt * (1.0 - x @ U) ** 2)) + fit["nu2"] * (1.0 + np.sum((x @ H) ** 2)))
    se = max(math.sqrt(max(v_iid, 0)), math.sqrt(max(v_rw, 0)) if v_rw is not None else 0.0)
    return {"v_iid": v_iid, "v_rw": v_rw, "se_model": se, "price": float(fit["position"] + fit["velocity"] * h + 0.5 * fit["acceleration"] * h * h)}


def spread_model(pairs_t: list[float], spreads: list[float], N: int = 64) -> dict:
    if len(spreads) < 8:
        return {"status": "INSUFFICIENT_HISTORY"}
    t = np.array(pairs_t[-4 * N:], float)
    s = np.array(spreads[-4 * N:], float)
    rho = (N - 1.0) / (N + 1.0)
    w = rho ** np.arange(len(s) - 1, -1, -1, dtype=float)
    if t[-1] - t[0] <= 0:
        return {"status": "RANK_OR_SPAN_TOO_SMALL", "level": float(s[-1])}
    X = np.stack([np.ones(len(t)), t - t[-1]], axis=1)
    sw = np.sqrt(w)
    beta, _, rank, _ = np.linalg.lstsq(X * sw[:, None], s * sw, rcond=1e-12)
    e = s - X @ beta
    ne = kish(w)
    s2 = float(np.sum(w * e * e) / w.sum() * ne / max(1.0, ne - 2))
    H = np.linalg.solve(X.T @ (X * w[:, None]), X.T * w[None, :])
    cov = s2 * H @ H.T
    path = float(np.sum(np.abs(np.diff(s))))
    return {"status": "OK", "level": float(beta[0]), "slope_per_s": float(beta[1]), "level_se": float(math.sqrt(max(cov[0, 0], 0))),
            "slope_se": float(math.sqrt(max(cov[1, 1], 0))), "efficiency": None if path == 0 else abs(float(s[-1] - s[0])) / path, "n_eff": ne,
            "note": "model bezpośredni na parach Ask-Bid (nie suma wariancji dwóch fitów); to nie jest imbalance arkusza zleceń"}


def classify_phase(bid: dict, ask: dict, spread: dict, cfg: dict = CFG, stressed_quality: bool = False) -> str:
    sb, sa = bid.get(256) or {}, ask.get(256) or {}
    fb, fa = bid.get(16) or {}, ask.get(16) or {}
    if sb.get("status") != "OK" or sa.get("status") != "OK":
        return "WARMING"
    zs = cfg["z_sig"]

    def sig(z):
        return z is not None and abs(z) >= zs
    if stressed_quality or (cfg.get("max_spread") is not None and (spread.get("level") or 0) > cfg["max_spread"]):
        return "STRESSED"
    if sig(sb["z_v"]) and sig(sa["z_v"]) and (sb["velocity"] > 0) != (sa["velocity"] > 0):
        return "STRESSED"
    slow_dir = None
    if sig(sb["z_v"]) and sig(sa["z_v"]) and (sb["velocity"] > 0) == (sa["velocity"] > 0):
        slow_dir = 1 if sb["velocity"] > 0 else -1
    fast_cons = None
    if fb.get("status") in ("OK", "PRELIMINARY") and fa.get("status") in ("OK", "PRELIMINARY") and sig(fb.get("z_v")) and sig(fa.get("z_v")) \
            and (fb["velocity"] > 0) == (fa["velocity"] > 0):
        fast_cons = 1 if fb["velocity"] > 0 else -1
    if slow_dir is not None and fast_cons is not None and fast_cons == -slow_dir:
        return "RETRACEMENT"
    if slow_dir is not None:
        acc = any(sig(s.get("z_a")) and (s["acceleration"] > 0) == (slow_dir > 0) for s in (sb, sa))
        if acc and fast_cons != -slow_dir:
            return "EXPANSION"
    if sb["z_v"] is not None and sa["z_v"] is not None and abs(sb["z_v"]) < cfg["z_flat"] and abs(sa["z_v"]) < cfg["z_flat"]:
        return "CONSOLIDATION"
    return "UNDETERMINED"


class QuoteEngine:
    """Incremental collector + per-side fits + phase with hysteresis + primary forecast stream + scoreboard."""

    def __init__(self, context: str, tick: float, point: float, cfg: dict | None = None):
        self.cfg = dict(CFG, **(cfg or {}))
        self.context, self.tick, self.point = context, tick, point
        self.origin_ms: int | None = None
        self.sides = {"BID": Side("BID"), "ASK": Side("ASK")}
        self.spread_t, self.spread = [], []
        self._seen_last_ms: set = set()
        self.clock = {"mode": "UNKNOWN", "checked": 0, "whole_seconds": 0}
        self.flags: set[str] = set()
        self.phase, self._cand, self._cand_n, self._cand_t = "WARMING", None, 0, None
        self.open_fc: dict[str, dict] = {}
        self.matured: list[dict] = []
        self.pending_score: list[dict] = []
        self.quotes_seen: list[tuple[float, float, float]] = []
        self.seq = 0
        self.last_tick_ms = None

    def _clock(self, t_ms: int) -> int:
        c = self.clock
        if c["checked"] < 200:
            c["checked"] += 1
            c["whole_seconds"] += int(t_ms % 1000 == 0)
            if c["checked"] == 200:
                c["mode"] = "COARSE_SECONDS" if c["whole_seconds"] == 200 else "MILLISECONDS"
        if c["mode"] == "COARSE_SECONDS":
            self.flags.add("COARSE_CLOCK")
            return (t_ms // 1000) * 1000
        return t_ms

    def ingest(self, ticks: list[dict]) -> int:
        """ticks: [{t_ms, bid, ask}] in source order. A new read may overlap the previous one: ticks older than the last processed ms
        are skipped, and at the last ms quotes already seen in an EARLIER read are skipped (within one read A->B->A is kept)."""
        n = 0
        overlap = self.last_tick_ms is not None
        first_ms = self.last_tick_ms
        for k in ticks:
            t_ms = int(k.get("t_ms") if k.get("t_ms") is not None else round(k["t"] * 1000))
            q = (k["bid"], k["ask"])
            if self.last_tick_ms is not None and t_ms < self.last_tick_ms:
                continue                                             # overlap of a re-read (older than what was processed)
            if t_ms == self.last_tick_ms and overlap and q in self._seen_last_ms:
                continue                                             # same ms already processed in an earlier read
            if t_ms != self.last_tick_ms:
                self._seen_last_ms = set()
            self._seen_last_ms.add(q)
            if self.origin_ms is None:
                self.origin_ms = t_ms
            b, a = float(k["bid"]), float(k["ask"])
            if not (b > 0 and a > 0):
                self.flags.add("INVALID_QUOTE")
                continue
            if a < b:
                self.flags.add("CROSSED_QUOTE")
                continue
            tc = self._clock(t_ms)
            self.sides["BID"].push(tc, b, self.origin_ms, self.cfg)
            self.sides["ASK"].push(tc, a, self.origin_ms, self.cfg)
            ts = (tc - self.origin_ms) / 1000.0
            self.spread_t.append(ts)
            self.spread.append(a - b)
            self.quotes_seen.append((ts, b, a))
            self.last_tick_ms = t_ms
            if t_ms != first_ms:
                overlap = False
            n += 1
        self.spread_t, self.spread = self.spread_t[-2000:], self.spread[-2000:]
        self.quotes_seen = self.quotes_seen[-20000:]
        return n

    def snapshot(self, now_ms: int) -> dict:
        now = (now_ms - (self.origin_ms or now_ms)) / 1000.0
        fits = {}
        for nm, sd in self.sides.items():
            fits[nm] = {}
            age = None if not sd.t else now - sd.t[-1]
            for N in SCALES:
                f = fit_side(sd.t, sd.y, N, self.tick, self.point, self.cfg) if sd.t else {"scale": N, "status": "MISSING_TICKS"}
                if f.get("status") in ("OK", "PRELIMINARY") and age is not None and age > self.cfg["max_side_age_s"]:
                    f = dict(f, status="STALE_SIDE")
                f["side_age_s"] = age
                fits[nm][N] = f
        sp = spread_model(self.spread_t, self.spread)
        ph = classify_phase(fits["BID"], fits["ASK"], sp, self.cfg, stressed_quality=bool({"CROSSED_QUOTE", "OUT_OF_ORDER"} & self.flags))
        self._phase_update(ph, now)
        self.seq += 1
        return {"version": VERSION, "context": self.context, "seq": self.seq, "as_of_s": now, "clock": dict(self.clock), "flags": sorted(self.flags),
                "phase": self.phase, "phase_raw": ph, "spread": sp,
                "sides": {nm: {N: {k: v for k, v in f.items() if not k.startswith("_")} for N, f in fs.items()} for nm, fs in fits.items()},
                "_fits": fits, "note": "lokalny model statystyczny Bid/Ask; nie prawo fizyczne, nie gwarancja odwrócenia"}

    def _phase_update(self, ph: str, now: float) -> None:
        if ph == "STRESSED":
            self.phase, self._cand = ph, None
            return
        if ph == self.phase:
            self._cand = None
            return
        if ph != self._cand:
            self._cand, self._cand_n, self._cand_t = ph, 1, now
            return
        self._cand_n += 1
        if self._cand_n >= self.cfg["hyst_updates"] and now - self._cand_t >= self.cfg["hyst_s"]:
            self.phase, self._cand = ph, None

    # ------------------------------------------------------------ forecasts
    def emit(self, snap: dict, now_ms: int) -> list[dict]:
        now = (now_ms - (self.origin_ms or now_ms)) / 1000.0
        res = 1.0 if self.clock["mode"] == "COARSE_SECONDS" else 0.001
        out = []
        for nm, fs in snap["_fits"].items():
            for N, f in fs.items():
                key = f"{nm}|{N}"
                if f.get("status") != "OK":
                    continue
                prev = self.open_fc.get(key)
                if prev is not None and prev["target_s"] > now:
                    continue                                          # primary stream: no overlap
                h = min(self.cfg["h_frac"] * f["span_s"], self.cfg["h_max_s"])
                if h <= res:
                    continue
                lag = min(1.0, max(res, 0.25 * h))
                age = now - f["t0"]
                fv = forecast_variance(f, age + h)
                fc = {"forecast_id": hashlib.sha256(f"{self.context}|{key}|{now_ms}".encode()).hexdigest()[:16], "context": self.context, "side": nm, "scale": N,
                      "issued_s": now, "t0_s": f["t0"], "target_s": now + h, "h_s": h, "max_lag_s": lag, "price": fv["price"], "se_model": fv["se_model"],
                      "v_rw": fv["v_rw"], "v_iid": fv["v_iid"], "last_quote": self.sides[nm].y[-1], "data_age_s": age, "band": self._band(nm, N, fv["se_model"])}
                self.open_fc[key] = fc
                self.pending_score.append(fc)
                out.append(fc)
        return out

    def _band(self, side: str, N: int, se: float) -> dict:
        errs = [abs(m["error"]) / m["se_model"] for m in self.matured if m["side"] == side and m["scale"] == N and m.get("se_model")]
        if len(errs) < self.cfg["calib_min"]:
            return {"status": "MODEL_BAND_UNCALIBRATED", "n": len(errs)}
        k = float(np.quantile(errs, self.cfg["band_q"]))
        return {"status": "EMPIRICAL", "q": self.cfg["band_q"], "multiplier": k, "half_width": k * se, "n": len(errs),
                "calibration_id": hashlib.sha256(f"{side}{N}{len(errs)}".encode()).hexdigest()[:10]}

    def score(self, now_ms: int) -> list[dict]:
        now = (now_ms - (self.origin_ms or now_ms)) / 1000.0
        done, keep = [], []
        for fc in self.pending_score:
            col = 1 if fc["side"] == "BID" else 2
            hit = next((q for q in self.quotes_seen if fc["target_s"] <= q[0] <= fc["target_s"] + fc["max_lag_s"]), None)
            if hit is not None:
                y = hit[col]
                err = y - fc["price"]
                m = dict(fc, status="SCORED", outcome=y, error=err, persistence_error=y - fc["last_quote"], scored_at_s=hit[0])
            elif now > fc["target_s"] + fc["max_lag_s"]:
                m = dict(fc, status="UNSCORED_GAP")
            else:
                keep.append(fc)
                continue
            done.append(m)
            self.matured.append(m)
        self.pending_score = keep
        self.matured = self.matured[-5000:]
        return done

    def scoreboard(self) -> dict:
        out = {}
        for side in ("BID", "ASK"):
            for N in SCALES:
                ms = [m for m in self.matured if m["side"] == side and m["scale"] == N]
                sc = [m for m in ms if m["status"] == "SCORED"]
                if not sc:
                    out[f"{side}_{N}"] = {"n": 0, "unscored_gap": len(ms)}
                    continue
                e = np.array([m["error"] for m in sc])
                pe = np.array([m["persistence_error"] for m in sc])
                y = np.array([m["outcome"] for m in sc])
                ss_p = float(np.sum(pe ** 2))
                pred_dir = np.sign(np.round((np.array([m["price"] for m in sc]) - np.array([m["last_quote"] for m in sc])) / (self.tick or 1e-9)))
                real_dir = np.sign(np.round((y - np.array([m["last_quote"] for m in sc])) / (self.tick or 1e-9)))
                cov = [abs(m["error"]) <= m["band"]["half_width"] for m in sc if m["band"].get("status") == "EMPIRICAL"]
                out[f"{side}_{N}"] = {"n": len(sc), "unscored_gap": len(ms) - len(sc), "mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e ** 2))),
                                      "bias": float(np.mean(e)), "mae_persistence": float(np.mean(np.abs(pe))),
                                      "r2_vs_persistence": None if ss_p == 0 else 1.0 - float(np.sum(e ** 2)) / ss_p,
                                      "hit_rate_flat_zone_1tick": float(np.mean(pred_dir == real_dir)),
                                      "band_coverage": float(np.mean(cov)) if cov else None, "band_n": len(cov)}
        return out
