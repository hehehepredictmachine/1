"""Meta-model features (PMW-QUANT-FEAT-1): named, side-aligned, each with its own missing mask.

Outputs with different meanings are separate NAMED features - nothing is averaged:
  fc:<canonical>:<task>:<tf>:edge        P(side) - P(opposite)  of a READY direction distribution (CLASS_PROBABILITIES with UP/DOWN)
  fc:<canonical>:<task>:<tf>:z           side-aligned mean / sd of a READY return forecast (REGRESSION log_return with mean + sd)
  fc:<canonical>:<task>:<tf>:score       raw score of a READY SCORE record (+ :score_x_side - the LONG score times the side sign)
  st:<canonical>:aligned                 +1 / -1 / 0: a filter state that names a direction agreeing / disagreeing with the side
  ctx:*                                   plan / context numbers available at the decision (R in ATR, costs in R, spread in R, hour, regime,
                                          engine one-hot, engine heuristic score / 100, DXY relation)
  plan:*                                  plan shape (gain in R, TP1 in R, number of targets, horizon minutes, side)
Every feature f has mask m:f = 1 when the input was missing / not READY / excluded - the value is then 0 AND the mask says so; the
meta-model is trained with exactly this policy (a missing model is never turned into a neutral probability). At inference only the
artifact's feature list is used: unknown features are ignored, trained features that are missing get mask 1.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

VERSION = "PMW-QUANT-FEAT-1"
REGIMES = ("TREND", "RANGE", "TRANSITION", "HIGH_VOL")
ENGINES = ("SH_SCALPING", "SH_HEDGING", "SCALP_SHADOW", "ACTIVE_S01_S12")
BULL = ("BULL", "UP", "LONG", "SUPPORT")
BEAR = ("BEAR", "DOWN", "SHORT", "RESIST")


def _f(x) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return float(x)


def _dir_of(text) -> int:
    t = str(text or "").upper()
    if any(b in t for b in BULL):
        return 1
    if any(b in t for b in BEAR):
        return -1
    return 0


def plan_features(c: dict) -> dict:
    side = 1 if c.get("direction") == "LONG" else -1
    e, sl = _f(c.get("entry_price")), _f(c.get("stop_loss"))
    out = {"plan:side_long": 1.0 if side > 0 else 0.0}
    if e is None or sl is None or abs(e - sl) <= 0:
        return out
    R = abs(e - sl)
    tg = c.get("targets") or []
    if tg:
        out["plan:gain_r"] = sum(float(t["weight"]) * abs(float(t["price"]) - e) for t in tg) / R
        out["plan:tp1_r"] = abs(float(tg[0]["price"]) - e) / R
        out["plan:n_targets"] = float(len(tg))
    out["plan:horizon_min"] = float(c.get("horizon_s") or 0) / 60.0
    ec = c.get("execution_context") or {}
    if _f(ec.get("cost_price")) is not None and ec.get("commission_known") is not False:
        out["ctx:cost_r"] = float(ec["cost_price"]) / R
    if _f(ec.get("spread")) is not None:
        out["ctx:spread_r"] = float(ec["spread"]) / R
    atr = _f(((c.get("features") or {}).get("atr_m5"))) or _f((c.get("features") or {}).get("atr"))
    if atr:
        out["ctx:risk_atr"] = R / atr
    return out


def context_features(c: dict) -> dict:
    out = {}
    ts = _f(c.get("decision_ts"))
    if ts is not None:
        h = datetime.fromtimestamp(ts, timezone.utc)
        ang = 2 * math.pi * (h.hour + h.minute / 60) / 24
        out["ctx:hour_sin"], out["ctx:hour_cos"] = math.sin(ang), math.cos(ang)
    reg = str((c.get("market_regime") or {}).get("state") or "").upper()
    for r in REGIMES:
        if reg:
            out[f"ctx:regime={r}"] = 1.0 if reg == r else 0.0
    eng = c.get("engine")
    for e in ENGINES:
        out[f"ctx:engine={e}"] = 1.0 if eng == e else 0.0
    if _f(c.get("score")) is not None:
        out["ctx:heuristic_score"] = float(c["score"]) / 100.0
    return out


def prediction_features(preds: list[dict], side: str) -> dict:
    """From ELIGIBLE (checked, deduplicated) PMW-PRED records only."""
    sgn = 1 if side == "LONG" else -1
    out = {}
    for p in preds or []:
        if p.get("state") != "READY" or not (p.get("eligibility") or {}).get("eligible", True):
            continue
        cid = p.get("canonical_id") or p.get("model_key") or p.get("model_name")
        base = f"fc:{cid}:{p.get('task')}:{p.get('timeframe')}"
        r = p.get("result")
        tt = p.get("task_type")
        if tt == "CLASS_PROBABILITIES" and isinstance(r, dict) and "UP" in r and "DOWN" in r:
            out[base + ":edge"] = sgn * (float(r["UP"]) - float(r["DOWN"]))
        elif tt == "REGRESSION" and isinstance(r, dict) and p.get("unit") in ("log_return", "return") and _f(r.get("mean")) is not None \
                and (_f(r.get("sd")) or 0) > 0:
            out[base + ":z"] = sgn * float(r["mean"]) / float(r["sd"])
        elif tt == "SCORE" and isinstance(r, dict) and _f(r.get("raw_score")) is not None:
            out[base + ":score"] = float(r["raw_score"])
            out[base + ":score_x_side"] = sgn * float(r["raw_score"])
        elif tt == "FILTER_STATE" and isinstance(r, dict) and isinstance(r.get("state"), str):
            d = _dir_of(r["state"])
            out[f"st:{cid}:aligned"] = float(sgn * d)
        elif tt == "STATE" and cid == "analysis:dxy_correlation" and isinstance(r, dict):
            for k in ("corr_72", "resid_z_72", "beta_72"):
                if _f(r.get(k)) is not None:
                    out[f"ctx:dxy_{k}"] = float(r[k])
    return out


def build(c: dict, preds: list[dict]) -> dict:
    f = {**plan_features(c), **context_features(c), **prediction_features(preds, c.get("direction"))}
    return {k: v for k, v in f.items() if _f(v) is not None}


def vectorise(feats: dict, names: list[str]):
    """-> (values, masks) for the trained feature list; a missing feature = (0.0, 1.0)."""
    vals, masks = [], []
    for n in names:
        v = _f(feats.get(n))
        vals.append(0.0 if v is None else v)
        masks.append(1.0 if v is None else 0.0)
    return vals, masks


def schema(names: list[str]) -> str:
    return VERSION + ":" + hashlib.sha256("|".join(names).encode()).hexdigest()[:12]
