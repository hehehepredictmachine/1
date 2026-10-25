"""Multi-Indicator Strategy Pro (PMW-MM-MULTIIND-1). RULE_STRATEGY - analytical events only, execution_allowed = False.

Indicators (closed bars, chronological arrays; index i = the last COMPLETED bar, a forming bar is never passed in):
  RSI(14) Wilder (reused: strategies.indicators.rsi) | Parabolic SAR 0.02/0.20 (reused: scalp.indicators.sar_points, verified profile)
  Heiken-Ashi: HA_C=(O+H+L+C)/4, HA_O=(HA_O[-1]+HA_C[-1])/2 seeded with (O0+C0)/2, HA_H=max(H,HA_O,HA_C), HA_L=min(L,HA_O,HA_C)
  Stochastic 5/3/3 (MT5 convention: main = 100*sum_s(C-LL_k)/sum_s(HH_k-LL_k), signal = SMA_d(main))
  CCI(20) typical price, SMA, mean absolute deviation, 0.015 | Williams %R(14) = -100*(HH-C)/(HH-LL) in [-100, 0]
  Bulls Power(13) = High - EMA13(close), Bears Power(13) = Low - EMA13(close) (MT5 convention) | ATR(14) = SMA of true range (MT5 iATR)
Rules (deterministic, versioned, every outcome carries its decision trace):
  1 trend gate LONG: HA bullish (HA_C>HA_O) AND SAR below close; SHORT mirrored. Missing -> no candidate.
  2 momentum votes: RSI (mode CROSS: crossed the 50 midline between the two last closed bars; LEVEL_RISING: above 50 and rising) and
    Stochastic (%K crossed %D: prev <= / now > ; optional strict mode requires prev %K or %D below oversold). votes >= min_momentum_votes.
  3 exhaustion: LONG suppressed when CCI >= +cci_ext AND %R >= wpr_overbought (both extreme); SHORT mirrored. recovery_mode requires CCI or
    %R to have left an extreme on the last bar.
  4 power (require_power): LONG needs Bulls>0 or rising AND Bears rising (less negative); SHORT mirrored.
  5 conflicts: explicit contrary votes (momentum against, power against) - missing data is not a vote; > max_conflicts -> reject.
  6 risk: ATR valid and > 0; stop = entry -/+ stop_atr*ATR, R = |entry-stop|, target = entry +/- target_r*R (hypothetical).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass

import numpy as np

VERSION = "PMW-MM-MULTIIND-1"


@dataclass
class MIConfig:
    rsi_period: int = 14
    rsi_mode: str = "CROSS"              # CROSS | LEVEL_RISING
    rsi_mid: float = 50.0
    sar_step: float = 0.02
    sar_max: float = 0.20
    stoch_k: int = 5
    stoch_d: int = 3
    stoch_slow: int = 3
    stoch_strict: bool = False
    stoch_os: float = 20.0
    stoch_ob: float = 80.0
    cci_period: int = 20
    cci_ext: float = 100.0
    wpr_period: int = 14
    wpr_os: float = -80.0
    wpr_ob: float = -20.0
    recovery_mode: bool = False
    power_period: int = 13
    require_power: bool = True
    min_momentum_votes: int = 1
    max_conflicts: int = 1
    atr_period: int = 14
    stop_atr: float = 1.5
    target_r: float = 2.0

    def validate(self):
        if self.rsi_mode not in ("CROSS", "LEVEL_RISING") or not (0 < self.rsi_mid < 100):
            raise ValueError("MI_RSI_INVALID")
        if min(self.rsi_period, self.stoch_k, self.stoch_d, self.stoch_slow, self.cci_period, self.wpr_period, self.power_period, self.atr_period) < 1:
            raise ValueError("MI_PERIOD_INVALID")
        if not (0 < self.sar_step <= self.sar_max) or not (-100 <= self.wpr_os < self.wpr_ob <= 0) or not (0 <= self.stoch_os < self.stoch_ob <= 100):
            raise ValueError("MI_LEVEL_INVALID")
        if not (0 <= self.min_momentum_votes <= 2) or self.max_conflicts < 0 or self.stop_atr <= 0 or self.target_r <= 0:
            raise ValueError("MI_RULE_INVALID")

    def hash(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:12]


# ------------------------------------------------------------------------------------------------ indicators
def _sma(x, n):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.r_[0.0, np.cumsum(x)]
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def _ema(x, n):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    a = 2.0 / (n + 1)
    if len(x):
        out[0] = x[0]
        for i in range(1, len(x)):
            out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def heikin_ashi(o, h, l, c):  # noqa: E741
    o, h, l, c = (np.asarray(v, float) for v in (o, h, l, c))  # noqa: E741
    hc = (o + h + l + c) / 4.0
    ho = np.empty_like(hc)
    ho[0] = (o[0] + c[0]) / 2.0
    for i in range(1, len(hc)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2.0
    return ho, np.maximum.reduce([h, ho, hc]), np.minimum.reduce([l, ho, hc]), hc


def _roll(x, n, fn):
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = fn(x[i + 1 - n:i + 1])
    return out


def stochastic(h, l, c, k, d, s):  # noqa: E741
    hh, ll = _roll(h, k, np.max), _roll(l, k, np.min)
    num, den = np.asarray(c, float) - ll, hh - ll
    sn, sd = _roll(num, s, np.sum), _roll(den, s, np.sum)
    with np.errstate(invalid="ignore", divide="ignore"):
        main = np.where(sd > 0, 100.0 * sn / sd, np.where(np.isfinite(sd), 100.0, np.nan))
    sig = np.full(len(main), np.nan)
    for i in range(len(main)):
        w = main[max(0, i + 1 - d):i + 1]
        if len(w) == d and np.isfinite(w).all():
            sig[i] = w.mean()
    return main, sig


def cci(h, l, c, n):  # noqa: E741
    tp = (np.asarray(h, float) + np.asarray(l, float) + np.asarray(c, float)) / 3.0
    out = np.full(len(tp), np.nan)
    for i in range(n - 1, len(tp)):
        w = tp[i + 1 - n:i + 1]
        m = w.mean()
        md = np.abs(w - m).mean()
        out[i] = (tp[i] - m) / (0.015 * md) if md > 0 else 0.0
    return out


def williams_r(h, l, c, n):  # noqa: E741
    hh, ll = _roll(h, n, np.max), _roll(l, n, np.min)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(hh > ll, -100.0 * (hh - np.asarray(c, float)) / (hh - ll), np.where(np.isfinite(hh), -50.0, np.nan))


def atr_sma(h, l, c, n):  # noqa: E741
    h, l, c = (np.asarray(v, float) for v in (h, l, c))  # noqa: E741
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    tr[0] = h[0] - l[0]
    return _sma(tr, n)


def compute(o, h, l, c, cfg: MIConfig) -> dict:  # noqa: E741
    from ..scalp.indicators import sar_points
    from ..strategies.indicators import rsi
    cfg.validate()
    r = np.array([np.nan if v is None else v for v in rsi(list(map(float, c)), cfg.rsi_period)])
    sp = sar_points(list(map(float, h)), list(map(float, l)), cfg.sar_step, cfg.sar_max)
    sar = np.array([np.nan if p is None else p["sar"] for p in sp])
    ho, hh, hl, hc = heikin_ashi(o, h, l, c)
    k, d = stochastic(h, l, c, cfg.stoch_k, cfg.stoch_d, cfg.stoch_slow)
    ema = _ema(c, cfg.power_period)
    ema[: cfg.power_period - 1] = np.nan                                 # EMA warm-up is not "ready"
    return {"rsi": r, "sar": sar, "ha_o": ho, "ha_c": hc, "stoch_k": k, "stoch_d": d, "cci": cci(h, l, c, cfg.cci_period),
            "wpr": williams_r(h, l, c, cfg.wpr_period), "bulls": np.asarray(h, float) - ema, "bears": np.asarray(l, float) - ema,
            "atr": atr_sma(h, l, c, cfg.atr_period), "close": np.asarray(c, float)}


# ------------------------------------------------------------------------------------------------ rules
def _f(x):
    return None if x is None or not np.isfinite(x) else float(x)


def evaluate_bar(ind: dict, i: int, cfg: MIConfig) -> dict:
    """Decision for the bar i (the last completed bar). Returns accepted/rejected + full trace for both directions."""
    need = ("rsi", "sar", "ha_o", "ha_c", "stoch_k", "stoch_d", "cci", "wpr", "bulls", "bears", "atr")
    if i < 1 or any(not np.isfinite(ind[k][i]) or not np.isfinite(ind[k][i - 1]) for k in need):
        return {"status": "NOT_READY", "reason": "INSUFFICIENT_INDICATOR_HISTORY", "missing": [k for k in need if i < 1 or not np.isfinite(ind[k][i])]}
    c = ind["close"][i]
    out = {}
    for side, s in (("LONG", 1), ("SHORT", -1)):
        tr = {}
        ha_ok = (ind["ha_c"][i] > ind["ha_o"][i]) if s > 0 else (ind["ha_c"][i] < ind["ha_o"][i])
        sar_ok = (ind["sar"][i] < c) if s > 0 else (ind["sar"][i] > c)
        tr["trend_gate"] = {"ha": bool(ha_ok), "sar": bool(sar_ok)}
        r0, r1 = ind["rsi"][i - 1], ind["rsi"][i]
        if cfg.rsi_mode == "CROSS":
            rv = (r0 <= cfg.rsi_mid < r1) if s > 0 else (r0 >= cfg.rsi_mid > r1)
            ra = (r0 >= cfg.rsi_mid > r1) if s > 0 else (r0 <= cfg.rsi_mid < r1)
        else:
            rv = (r1 > cfg.rsi_mid and r1 > r0) if s > 0 else (r1 < cfg.rsi_mid and r1 < r0)
            ra = (r1 < cfg.rsi_mid and r1 < r0) if s > 0 else (r1 > cfg.rsi_mid and r1 > r0)
        k0, k1, d0, d1 = ind["stoch_k"][i - 1], ind["stoch_k"][i], ind["stoch_d"][i - 1], ind["stoch_d"][i]
        up, dn = (k0 <= d0 and k1 > d1), (k0 >= d0 and k1 < d1)
        if cfg.stoch_strict:
            up = up and (k0 < cfg.stoch_os or d0 < cfg.stoch_os)
            dn = dn and (k0 > cfg.stoch_ob or d0 > cfg.stoch_ob)
        sv, sa = (up, dn) if s > 0 else (dn, up)
        votes = int(rv) + int(sv)
        against = int(ra) + int(sa)
        tr["momentum"] = {"rsi_for": bool(rv), "rsi_against": bool(ra), "stoch_for": bool(sv), "stoch_against": bool(sa), "votes": votes}
        ci, wi = ind["cci"][i], ind["wpr"][i]
        ext_same = (ci >= cfg.cci_ext and wi >= cfg.wpr_ob) if s > 0 else (ci <= -cfg.cci_ext and wi <= cfg.wpr_os)
        rec = ((ind["cci"][i - 1] <= -cfg.cci_ext < ci) or (ind["wpr"][i - 1] <= cfg.wpr_os < wi)) if s > 0 else \
              ((ind["cci"][i - 1] >= cfg.cci_ext > ci) or (ind["wpr"][i - 1] >= cfg.wpr_ob > wi))
        exh_ok = (not ext_same) and (rec if cfg.recovery_mode else True)
        tr["exhaustion"] = {"both_extreme_same_side": bool(ext_same), "recovery": bool(rec), "recovery_mode": cfg.recovery_mode, "pass": bool(exh_ok)}
        b0, b1, e0, e1 = ind["bulls"][i - 1], ind["bulls"][i], ind["bears"][i - 1], ind["bears"][i]
        p_for = ((b1 > 0 or b1 > b0) and e1 > e0) if s > 0 else ((e1 < 0 or e1 < e0) and b1 < b0)
        p_against = ((b1 < b0) and (e1 < e0)) if s > 0 else ((b1 > b0) and (e1 > e0))
        tr["power"] = {"for": bool(p_for), "against": bool(p_against), "required": cfg.require_power}
        conflicts = against + int(p_against)
        tr["conflicts"] = conflicts
        reasons = []
        if not (ha_ok and sar_ok):
            reasons.append("TREND_GATE")
        if votes < cfg.min_momentum_votes:
            reasons.append("MOMENTUM_QUORUM")
        if not exh_ok:
            reasons.append("EXHAUSTION")
        if cfg.require_power and not p_for:
            reasons.append("POWER")
        if conflicts > cfg.max_conflicts:
            reasons.append("CONFLICTS")
        atr = ind["atr"][i]
        risk = None
        if not (atr > 0):
            reasons.append("ATR_INVALID")
        else:
            stop = c - s * cfg.stop_atr * atr
            R = abs(c - stop)
            risk = {"entry_ref": float(c), "stop": float(stop), "R": float(R), "target": float(c + s * cfg.target_r * R), "atr": float(atr),
                    "note": "poziomy hipotetyczne; ATR nie gwarantuje maksymalnej straty (luki, spread, poślizg)"}
        out[side] = {"accepted": not reasons, "reasons": reasons, "trace": tr, "risk": risk}
    acc = [k for k, v in out.items() if v["accepted"]]
    snap = {k: _f(ind[k][i]) for k in ("rsi", "sar", "ha_o", "ha_c", "stoch_k", "stoch_d", "cci", "wpr", "bulls", "bears", "atr", "close")}
    return {"status": "OK", "decision": acc[0] if len(acc) == 1 else ("NONE" if not acc else "CONFLICT_BOTH"), "sides": out, "inputs": snap}


class Profiler:
    def __init__(self):
        self.samples: dict[str, list[float]] = {}

    def add(self, stage: str, us: float):
        self.samples.setdefault(stage, []).append(us)

    def summary(self) -> dict:
        out = {}
        for k, v in self.samples.items():
            a = np.asarray(v)
            out[k] = {"n": int(len(a)), "median_us": float(np.median(a)), "p95_us": float(np.percentile(a, 95)), "p99_us": float(np.percentile(a, 99))}
        return out


def journal(bars, cfg: MIConfig, symbol: str, tf: str, tf_s: int, horizon: int = 12) -> dict:
    """Replay over closed bars: one journal row per evaluated bar (accepted AND rejected), outcome labels attached only from bars after
    the decision (separate pass, so labels cannot leak into the decision)."""
    prof = Profiler()
    t0 = time.perf_counter_ns()
    ind = compute(bars.o, bars.h, bars.l, bars.c, cfg)
    prof.add("indicators_total", (time.perf_counter_ns() - t0) / 1000)
    rows, seen = [], set()
    for i in range(1, len(bars.c)):
        t1 = time.perf_counter_ns()
        d = evaluate_bar(ind, i, cfg)
        prof.add("strategy_eval", (time.perf_counter_ns() - t1) / 1000)
        if d["status"] != "OK":
            continue
        eid = f"MI-{symbol}-{tf}-{int(bars.t[i])}-{cfg.hash()}"
        if eid in seen:
            continue
        seen.add(eid)
        rows.append({"event_id": eid, "i": i, "bar_ts": float(bars.t[i]), "available_at": float(bars.t[i] + tf_s), "decision": d["decision"],
                     "long_reasons": d["sides"]["LONG"]["reasons"], "short_reasons": d["sides"]["SHORT"]["reasons"], "sides": d["sides"],
                     "inputs": d["inputs"], "config_hash": cfg.hash(), "version": VERSION, "execution_allowed": False})
    # outcome labelling (separate pass): first touch of stop/target within horizon (bar OHLC; same-bar touch of both = STOP, conservative)
    for r in rows:
        if r["decision"] not in ("LONG", "SHORT"):
            continue
        rk = r["sides"][r["decision"]]["risk"]
        s = 1 if r["decision"] == "LONG" else -1
        res = "TIMEOUT"
        for k in range(r["i"] + 1, min(len(bars.c), r["i"] + 1 + horizon)):
            hit_stop = bars.l[k] <= rk["stop"] if s > 0 else bars.h[k] >= rk["stop"]
            hit_tgt = bars.h[k] >= rk["target"] if s > 0 else bars.l[k] <= rk["target"]
            if hit_stop:
                res = "STOP"
                break
            if hit_tgt:
                res = "TARGET"
                break
        r["outcome"] = res if r["i"] + horizon < len(bars.c) or res != "TIMEOUT" else "NOT_MATURED"
    acc = [r for r in rows if r["decision"] in ("LONG", "SHORT")]
    rej = {}
    for r in rows:
        if r["decision"] == "NONE":
            for k in set(r["long_reasons"]) | set(r["short_reasons"]):
                rej[k] = rej.get(k, 0) + 1
    return {"rows": rows, "evaluated": len(rows), "accepted": len(acc), "long": sum(r["decision"] == "LONG" for r in acc),
            "short": sum(r["decision"] == "SHORT" for r in acc), "rejected_reason_counts": rej,
            "outcomes": {o: sum(r.get("outcome") == o for r in acc) for o in ("TARGET", "STOP", "TIMEOUT", "NOT_MATURED")},
            "profile": prof.summary(), "config": asdict(cfg), "config_hash": cfg.hash(), "horizon_bars": horizon}


def ablations(bars, base: MIConfig, symbol: str, tf: str, tf_s: int, horizon: int = 12) -> dict:
    """Full rule set vs simpler variants on identical data: HA+SAR only, +momentum, full, full minus one filter."""
    var = {"HA_SAR_ONLY": dict(min_momentum_votes=0, require_power=False, max_conflicts=99, cci_ext=1e9, wpr_ob=0.0, wpr_os=-100.0),
           "HA_SAR_MOMENTUM": dict(require_power=False, max_conflicts=99, cci_ext=1e9, wpr_ob=0.0, wpr_os=-100.0),
           "FULL": {}, "FULL_NO_POWER": dict(require_power=False), "FULL_NO_EXHAUSTION": dict(cci_ext=1e9, wpr_ob=0.0, wpr_os=-100.0),
           "FULL_NO_CONFLICT_LIMIT": dict(max_conflicts=99)}
    out = {}
    for name, ch in var.items():
        cfg = MIConfig(**{**asdict(base), **ch})
        j = journal(bars, cfg, symbol, tf, tf_s, horizon)
        o = j["outcomes"]
        done = o["TARGET"] + o["STOP"]
        out[name] = {"accepted": j["accepted"], "outcomes": o, "target_share_of_resolved": (o["TARGET"] / done) if done else None}
    return out
