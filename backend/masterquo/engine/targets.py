"""Execution levels for a frozen M07 plan - rule MQAI-LEVELS-1.0.0 (PROVISIONAL extension).

The M07 operational spec defines direction, location, liquidity, staged thresholds and the
structural invalidation, but no take-profit. This rule adds targets *only from existing,
confirmed M03 evidence* (never from a fixed RR multiple):

  SL   = plan invalidation level (structural + 0.2/0.25 ATR buffer from M07); for SHORT plus the
         current spread because a short position's stop is triggered on Ask.
  TP1  = nearest confirmed opposite-side liquidity level (M03:LEVEL SSL for SHORT / BSL for LONG)
         on the setup timeframe, beyond entry by at least `min_target_distance_atr` x ATR.
  TP2  = next such level on the setup TF, else the nearest qualifying H1 level; may be absent.
  weights: TP1 `tp1_weight`, TP2 the rest (single target -> weight 1.0).
If no qualifying level exists, targets are UNAVAILABLE and the setup cannot be sized.
This rule is versioned, has not been validated OOS and must be re-tested in M06R/M06T.
"""
from __future__ import annotations

LEVELS_RULE_VERSION = "MQAI-LEVELS-1.0.0"


def _levels(m03: dict, tf: str, side: str) -> list[float]:
    want = "SSL" if side == "SHORT" else "BSL"
    out = []
    for lv in ((m03.get("timeframes") or {}).get(tf) or {}).get("liquidity_levels") or []:
        if lv.get("liquidity_side") == want and isinstance(lv.get("reference_level"), (int, float)):
            out.append(float(lv["reference_level"]))
    return out


def derive_levels(plan: dict, m03: dict, atr: float | None, *, entry: float | None, spread: float | None,
                  tp1_weight: float, min_target_distance_atr: float) -> dict:
    side = plan["intended_direction"]
    tf = plan["setup_tf"]
    inv = float(plan["invalidation"]["condition"]["level"])
    reasons: list[str] = []
    sl = inv + (spread or 0.0) if side == "SHORT" else inv
    if spread is None and side == "SHORT":
        reasons.append("SPREAD_UNKNOWN_SL_WITHOUT_ASK_ADJUSTMENT")
    rules = plan["lifecycle_rules"]
    staged = [float(rules[k]["level"]) for k in ("qualification", "arming", "trigger", "confirmation")]
    zone = {"low": min(staged), "high": max(staged)}
    ref = entry if entry is not None else float(rules["confirmation"]["level"])
    min_dist = (atr or 0.0) * min_target_distance_atr
    if atr is None:
        reasons.append("ATR_UNAVAILABLE_TARGET_DISTANCE_UNFILTERED")

    def beyond(levels: list[float]) -> list[float]:
        if side == "LONG":
            return sorted(x for x in levels if x > ref + min_dist)
        return sorted((x for x in levels if x < ref - min_dist), reverse=True)

    primary = beyond(_levels(m03, tf, side))
    secondary = beyond(_levels(m03, "H1", side)) if tf != "H1" else []
    targets = []
    if primary:
        targets.append({"price": primary[0], "source": f"M03:LEVEL:{tf}"})
        nxt = primary[1] if len(primary) > 1 else next((x for x in secondary if (x > primary[0] if side == "LONG" else x < primary[0])), None)
        if nxt is not None:
            targets.append({"price": nxt, "source": f"M03:LEVEL:{tf if len(primary) > 1 else 'H1'}"})
    elif secondary:
        targets.append({"price": secondary[0], "source": "M03:LEVEL:H1"})
        if len(secondary) > 1:
            targets.append({"price": secondary[1], "source": "M03:LEVEL:H1"})
    if not targets:
        reasons.append("NO_CONFIRMED_OPPOSITE_LIQUIDITY_TARGET")
    if len(targets) == 1:
        targets[0]["weight"] = 1.0
    elif len(targets) == 2:
        targets[0]["weight"] = round(tp1_weight, 4)
        targets[1]["weight"] = round(1 - tp1_weight, 4)
    ok_geometry = all((sl < ref < t["price"]) if side == "LONG" else (t["price"] < ref < sl) for t in targets) if targets else False
    if targets and not ok_geometry:
        reasons.append("LEVEL_GEOMETRY_INVALID")
    return {"rule_version": LEVELS_RULE_VERSION, "side": side, "entry_reference": ref, "entry_zone": zone,
            "stop_loss": round(sl, 6), "invalidation_level": inv, "targets": targets,
            "status": "AVAILABLE" if targets and ok_geometry else "UNAVAILABLE", "reasons": reasons}
