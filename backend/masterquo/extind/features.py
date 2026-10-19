"""build_indicator_context_features(decision_snapshot, feature_spec) - ONE function for dataset, training, replay and live.

Groups (stable registry, SCALP_INDICATOR_CONTEXT_V1):
  BASE           the existing setup features (scalp.strategy.SETUP_FEATURES), unchanged
  SAR            per TF (M5, M15): direction-normalised distance to SAR in ATR, SAR with/against side, bars since flip,
                 flips in the last 50 closed bars, AF, degenerate flag - profile MQ_SAR_WILDER_PROFILE_V1 with the given params
  IQ_GOLD_GANN   distance (ATR) to the nearest approved level above / below the price, number of levels, age of the snapshot
  IQ_STAR_LINES  the same for Star levels + schedule known at the decision: minutes to next window start / end, in-window flag
  PAL02M         registered but BLOCKED until the tool is identified (no default algorithm, no features)
Only data available at the decision time: bars with open + TF <= decision, external snapshots with available_at <= decision
(the caller passes as_of snapshots). A missing value is NaN + missing flag, never 0 (imputation is fitted in the train fold).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from ..scalp import indicators as ind
from ..scalp.strategy import SETUP_FEATURES
from ..timeutil import parse_iso

FEATURE_SCHEMA = "SCALP_INDICATOR_CONTEXT_V1"
TASK_ID = "SCALP_TP1_FIRST_WITHIN_FROZEN_POLICY_V1"
GROUPS = ("BASE", "SAR", "IQ_GOLD_GANN", "IQ_STAR_LINES", "PAL02M")
TF_S = {"M5": 300, "M15": 900}
NAN = float("nan")


def default_spec(groups=("BASE", "SAR"), step: float = 0.02, maximum: float = 0.2) -> dict:
    return {"schema": FEATURE_SCHEMA, "groups": list(groups), "sar": {"step": step, "max": maximum, "tfs": ["M5", "M15"]}}


def feature_names(spec: dict) -> list[str]:
    out = []
    for g in spec["groups"]:
        if g == "BASE":
            out += [f"base_{k}" for k in SETUP_FEATURES]
        elif g == "SAR":
            for tf in spec["sar"]["tfs"]:
                out += [f"sar_{tf}_{k}" for k in ("dist_atr_dir", "with_side", "bars_since_flip", "flips50", "af", "degenerate")]
        elif g == "IQ_GOLD_GANN":
            out += ["gann_up_dist_atr", "gann_dn_dist_atr", "gann_levels", "gann_age_min"]
        elif g == "IQ_STAR_LINES":
            out += ["star_up_dist_atr", "star_dn_dist_atr", "star_levels", "star_age_min", "star_min_to_start", "star_min_to_end", "star_in_window"]
    return out


def _closed(bars: list[dict], tf: str, t: datetime) -> list[dict]:
    lim = t - timedelta(seconds=TF_S[tf])
    return [b for b in bars if b.get("open_utc") and parse_iso(b["open_utc"]) <= lim]


def _levels(snap: dict | None, price: float, atr: float, t: datetime, prefix: str, out: dict, groups: dict, g: str) -> None:
    if not snap:
        groups[g] = "MISSING_NO_APPROVED_SNAPSHOT_AS_OF"
        for k in ("up_dist_atr", "dn_dist_atr", "levels", "age_min"):
            out[f"{prefix}_{k}"] = NAN
        return
    lv = [x["price"] for x in snap.get("levels") or [] if x.get("kind") == "LEVEL" and x.get("price") is not None]
    up = min((p for p in lv if p > price), default=None)
    dn = max((p for p in lv if p <= price), default=None)
    out[f"{prefix}_up_dist_atr"] = (up - price) / atr if up is not None and atr else NAN
    out[f"{prefix}_dn_dist_atr"] = (price - dn) / atr if dn is not None and atr else NAN
    out[f"{prefix}_levels"] = float(len(lv))
    out[f"{prefix}_age_min"] = (t - parse_iso(snap["available_at"])).total_seconds() / 60.0
    groups[g] = "OK"


def build_indicator_context_features(snap: dict, spec: dict) -> dict:
    """snap: {decision_time (datetime), side BUY|SELL, price, atr_m5, base {SETUP_FEATURES}, bars {M5:[...], M15:[...]},
    ext {IQ_GOLD_GANN: snapshot|None, IQ_STAR_LINES: snapshot|None}}  ->  {features, missing, groups, schema}."""
    t, sgn = snap["decision_time"], (1 if snap["side"] == "BUY" else -1)
    price, atr = float(snap["price"]), snap.get("atr_m5")
    out: dict[str, float] = {}
    groups: dict[str, str] = {}
    for g in spec["groups"]:
        if g == "BASE":
            base = snap.get("base") or {}
            for k in SETUP_FEATURES:
                v = base.get(k)
                out[f"base_{k}"] = float(v) if isinstance(v, (int, float)) and math.isfinite(v) else NAN
            groups[g] = "OK" if base else "MISSING"
        elif g == "SAR":
            ok = True
            for tf in spec["sar"]["tfs"]:
                b = _closed((snap.get("bars") or {}).get(tf) or [], tf, t)[-400:]
                keys = ("dist_atr_dir", "with_side", "bars_since_flip", "flips50", "af", "degenerate")
                if len(b) < 5 or not atr:
                    ok = False
                    for k in keys:
                        out[f"sar_{tf}_{k}"] = NAN
                    continue
                pts = ind.sar_points([x["h"] for x in b], [x["l"] for x in b], spec["sar"]["step"], spec["sar"]["max"])
                last = pts[-1]
                out[f"sar_{tf}_dist_atr_dir"] = sgn * (b[-1]["c"] - last["sar"]) / atr
                out[f"sar_{tf}_with_side"] = 1.0 if (last["trend"] == "UP") == (sgn > 0) else 0.0
                out[f"sar_{tf}_bars_since_flip"] = float(min(200, last["bars_since_flip"]))
                out[f"sar_{tf}_flips50"] = float(sum(1 for p in pts[-50:] if p and p["flip"]))
                out[f"sar_{tf}_af"] = float(last["af"])
                out[f"sar_{tf}_degenerate"] = 1.0 if last["degenerate"] else 0.0
            groups[g] = "OK" if ok else "WARMING_UP"
        elif g == "IQ_GOLD_GANN":
            _levels((snap.get("ext") or {}).get("IQ_GOLD_GANN"), price, atr, t, "gann", out, groups, g)
        elif g == "IQ_STAR_LINES":
            s = (snap.get("ext") or {}).get("IQ_STAR_LINES")
            _levels(s, price, atr, t, "star", out, groups, g)
            ts = t.timestamp()
            wins = [w for w in (s or {}).get("windows") or [] if w.get("scheduled_start_utc") is not None and w.get("scheduled_end_utc") is not None]
            nxt = min((w["scheduled_start_utc"] for w in wins if w["scheduled_start_utc"] > ts), default=None)
            cur = [w for w in wins if w["scheduled_start_utc"] <= ts < w["scheduled_end_utc"]]
            out["star_min_to_start"] = min(1440.0, (nxt - ts) / 60.0) if nxt is not None else NAN
            out["star_min_to_end"] = (cur[0]["scheduled_end_utc"] - ts) / 60.0 if cur else NAN
            out["star_in_window"] = (1.0 if cur else 0.0) if s else NAN
        elif g == "PAL02M":
            groups[g] = "BLOCKED_IDENTITY_REQUIRED"
    names = feature_names(spec)
    feats = {k: out.get(k, NAN) for k in names}
    return {"schema": FEATURE_SCHEMA, "features": feats, "missing": {k: not math.isfinite(v) for k, v in feats.items()}, "groups": groups}
