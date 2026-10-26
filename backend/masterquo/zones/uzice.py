"""Unified Zone Intelligence & Confluence Engine - UZICE (PMW-ZONES-UZICE-1). ONE authoritative zone map per instrument and
analysis time: normalises HLZE and DSVIE outputs, merges genuinely overlapping zones of the same polarity, keeps the origin of every
member, detects confluence and contradictions, scores, and publishes the map to the evaluation layer, the ML feature pipeline and the chart.

Merging: zones of one polarity (HIGH = resistance-type, LOW = support-type) whose intervals overlap or are closer than
merge_tol = max(merge_tol_atr x ATR, min_width_ticks x tick) - and only while the merged zone stays within max_zone_width_atr x ATR.
Opposite polarities are never merged; overlapping strong opposite zones are reported as a CONFLICT. Deterministic: candidates sorted
by (lower, upper, zone_id). Stable id: the id of the earliest-confirmed member (anchor), so a zone keeps its id when members join.
Profile levels (POC / VAH / VAL / HVN / LVN of COMPLETED profiles, and of the developing one flagged as such) do not form zones of
their own here; they attach to the structural zones they overlap as volume evidence and are published separately in `profiles`.

Score (0-100, design defaults in config.zones.score_weights, NOT empirically validated; it is not a probability):
  structure    - independent structural roots (M15 swing 10, M5 swing 6, equal highs/lows +6, previous day / session extreme 8,
                 consolidation edge 5, breakout/breakdown level 5), capped
  volume       - completed profile level overlap (once per profile: POC 10 / VAH-VAL 8 / HVN 6 / LVN edge 5), tick-activity spike 4,
                 0 when the volume source is NONE
  reaction     - rejection strength, displacement, sweep-and-reclaim, held retest
  mtf          - M5 and M15 members together 10, overlap with an H1+ S/R zone (analysis.levels) 5
  freshness    - linear in age; minus 2 per retest above weaken_after_retests
  data_quality - 5 complete / 2 developing or degraded / 0 stale
Correlated evidence counts once: every evidence item has a `root` (pivot id, profile id, box id ...) and each root is scored once per group.
Penalties: WIDE -10, CONFLICT -10, provisional -10, INSUFFICIENT_HISTORY -5. confidence_status stays UNVALIDATED (no calibrated
model of zone outcomes exists yet).
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from .hlze import HIGH_TYPES, LOW_TYPES
from .series import iso

VERSION = "PMW-ZONES-UZICE-1"
SCHEMA = "PMW-ZONE-1.0"
LIVE = ("ACTIVE", "TESTED", "WEAKENED", "SWEPT", "PROVISIONAL")
PRIORITY = ["DEMAND", "SUPPLY", "LIQUIDITY_CLUSTER", "EQUAL_HIGHS", "EQUAL_LOWS", "PREVIOUS_DAY_HIGH", "PREVIOUS_DAY_LOW",
            "PREVIOUS_SESSION_HIGH", "PREVIOUS_SESSION_LOW", "SWING_HIGH", "SWING_LOW", "CONSOLIDATION_HIGH", "CONSOLIDATION_LOW",
            "BREAKOUT_LEVEL", "BREAKDOWN_LEVEL", "INTRADAY_HIGH", "INTRADAY_LOW"]
STRUCT_PTS = {"SWING": {"M15": 10, "M5": 6}, "EQUAL": 6, "PREVIOUS_DAY": 8, "PREVIOUS_SESSION": 8, "CONSOLIDATION": 5, "BREAKOUT": 5,
              "BREAKDOWN": 5, "INTRADAY": 3}
VOL_PTS = {"POC": 10, "VAH": 8, "VAL": 8, "HVN": 6, "LVN": 5, "TICK_ACTIVITY_SPIKE": 4}


def _t(x) -> float | None:
    if x is None:
        return None
    return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def polarity(ztype: str) -> str:
    return "HIGH" if ztype in HIGH_TYPES else "LOW" if ztype in LOW_TYPES else "NEUTRAL"


def _profile_levels(profiles: list[dict]) -> list[dict]:
    out = []
    for p in profiles:
        if "poc" not in p or p["state"] not in ("COMPLETED", "DEVELOPING"):
            continue
        half = p["bin_size"] / 2
        lv = [("POC", p["poc"]), ("VAH", p["vah"]), ("VAL", p["val"])] + [("HVN", x) for x in p.get("hvn", [])] + [("LVN", x) for x in p.get("lvn", [])]
        end_ts = datetime.fromisoformat(p["end"].replace("Z", "+00:00")).timestamp()
        for name, price in lv:
            out.append({"kind": name, "price": price, "lower": price - half, "upper": price + half, "profile_id": p["profile_id"],
                        "session": p["session"], "local_date": p["local_date"], "state": p["state"], "volume_source": p["volume_source"],
                        "end_ts": end_ts})
    return out


def _struct_category(kind: str, tf: str | None) -> str:
    if "SWING" in kind:
        return f"SWING_{tf}"
    for key in ("EQUAL", "PREVIOUS_DAY", "PREVIOUS_SESSION", "CONSOLIDATION", "BREAKOUT", "BREAKDOWN", "INTRADAY"):
        if key in kind:
            return key
    return "OTHER"


def _score(members: list[dict], plevels: list[dict], *, cfg, atr: float, htf_sr: list[dict], vol_source: str, data_state: str,
           max_age: int) -> tuple[dict, list[str], list[dict]]:
    """Each evidence ROOT counts once (correlated labels of one pivot are one confirmation); structure counts each CATEGORY once
    (ten M5 swings in one place are not ten independent confirmations); reaction takes the strongest member, not a sum."""
    w = cfg.score_weights
    flags: list[str] = []
    roots: set = set()
    cats: set = set()
    pts = {"structure": 0.0, "volume": 0.0, "reaction": 0.0, "mtf": 0.0, "freshness": 0.0, "data_quality": 0.0}
    evidence = []
    reaction_kinds: set = set()
    for m in members:
        for e in m.get("evidence") or []:
            g, root = e.get("group"), (e.get("group"), e.get("root"))
            if root in roots:
                continue                                                 # same root = correlated evidence, counted once
            roots.add(root)
            evidence.append(dict(e, member=m["zone_id"]))
            k = e.get("kind", "")
            if g == "structure":
                cat = _struct_category(k, m.get("tf"))
                if cat not in cats:
                    cats.add(cat)
                    pts["structure"] += STRUCT_PTS["SWING"].get(m.get("tf"), 6) if cat.startswith("SWING") else STRUCT_PTS.get(cat, 3)
            elif g == "volume" and vol_source != "NONE" and k == "TICK_ACTIVITY_SPIKE" and "TICK" not in reaction_kinds:
                reaction_kinds.add("TICK")
                pts["volume"] += VOL_PTS["TICK_ACTIVITY_SPIKE"]
            elif g == "reaction" and k not in reaction_kinds:
                reaction_kinds.add(k)
                pts["reaction"] += 6 if k == "DISPLACEMENT" else 4
        if m.get("status") == "SWEPT" and "SWEPT" not in reaction_kinds:
            reaction_kinds.add("SWEPT")
            pts["reaction"] += 6
    pts["reaction"] += min(6.0, 3.0 * max((float(m.get("rejection_max_atr") or 0.0) for m in members), default=0.0))
    if vol_source != "NONE":
        recent = sorted({pl["profile_id"]: pl.get("end_ts", 0) for pl in plevels}.items(), key=lambda x: x[1])[-4:]
        keep = {pid for pid, _ in recent}                                # the 3 latest completed + developing profiles only
        best: dict = {}
        for pl in plevels:
            if pl["profile_id"] not in keep:
                continue
            val = VOL_PTS.get(pl["kind"], 3) * (0.5 if pl["state"] == "DEVELOPING" else 1.0)
            if val > best.get(pl["profile_id"], (0, None))[0]:
                best[pl["profile_id"]] = (val, pl)
        for pid, (val, pl) in sorted(best.items()):
            pts["volume"] += val
            evidence.append({"group": "volume", "kind": f"PROFILE_{pl['kind']}", "root": f"{pid}:{pl['kind']}",
                             "detail": f"{pl['kind']} {pl['session']} {pl['local_date']} ({pl['state']}, {pl['volume_source']})",
                             "evidence_type": "VOLUME_OBSERVATION"})
    tfs = {m.get("tf") for m in members}
    if {"M5", "M15"} <= tfs:
        pts["mtf"] += 10
    lo, up = min(m["lower"] for m in members), max(m["upper"] for m in members)
    if any(z["low"] <= up and z["high"] >= lo for z in htf_sr):
        pts["mtf"] += 5
        evidence.append({"group": "mtf", "kind": "HTF_SR_OVERLAP", "root": "HTF", "detail": "nakłada się na strefę S/R H1+ (analysis.levels)"})
    ages = [m.get("age_bars") for m in members if m.get("age_bars") is not None]
    age = min(ages) if ages else 0
    pts["freshness"] = max(0.0, 10.0 * (1 - age / max_age)) if max_age else 0.0
    extra_tests = max(0, max((m.get("retests") or 0) for m in members) - cfg.weaken_after_retests)
    pts["freshness"] = max(0.0, pts["freshness"] - 2 * extra_tests)
    pts["data_quality"] = {"OK": 5.0, "DEGRADED": 2.0}.get(data_state, 0.0)
    caps = {"structure": w.get("structure", 25), "volume": w.get("volume", 25), "reaction": w.get("reaction", 20), "mtf": w.get("mtf", 15),
            "freshness": w.get("freshness", 10), "data_quality": w.get("data_quality", 5)}
    scale = {"mtf": caps["mtf"] / 15.0, "freshness": caps["freshness"] / 10.0, "data_quality": caps["data_quality"] / 5.0}
    comp = {k: round(min(caps[k], v * scale.get(k, 1.0)), 2) for k, v in pts.items()}
    if (up - lo) > cfg.max_zone_width_atr * atr:
        flags.append("WIDE")
    if all(m.get("provisional") for m in members):
        flags.append("PROVISIONAL")
    return comp, flags, evidence


def unify(hlz: list[dict], ds: list[dict], profiles: list[dict], *, cfg, atr: float, tick: float, price: float, htf_sr: list[dict],
          vol_source: str, data_state: str, as_of: float) -> tuple[list[dict], list[dict]]:
    cands = [z for z in hlz + ds if z.get("status") in LIVE]
    expired = [z for z in hlz + ds if z.get("status") not in LIVE]
    tol = max(cfg.merge_tol_atr * atr, cfg.min_width_ticks * tick)
    maxw = cfg.max_zone_width_atr * atr
    plevels = _profile_levels(profiles)
    clusters: dict[str, list[list[dict]]] = {"HIGH": [], "LOW": []}
    for z in sorted(cands, key=lambda z: (z["lower"], z["upper"], z["zone_id"])):
        pol = polarity(z["zone_type"])
        if pol == "NEUTRAL":
            continue
        cl = clusters[pol]
        if cl:
            last = cl[-1]
            lo, up = min(m["lower"] for m in last), max(m["upper"] for m in last)
            if z["lower"] <= up + tol and max(up, z["upper"]) - min(lo, z["lower"]) <= maxw:
                last.append(z)
                continue
        cl.append([z])
    max_age = max(cfg.max_age_bars.values()) if cfg.max_age_bars else 500
    out = []
    for pol, cls in clusters.items():
        for members in cls:
            lo, up = min(m["lower"] for m in members), max(m["upper"] for m in members)
            pl = [p for p in plevels if p["upper"] >= lo - tol and p["lower"] <= up + tol]
            comp, flags, evidence = _score(members, pl, cfg=cfg, atr=atr, htf_sr=htf_sr, vol_source=vol_source, data_state=data_state,
                                           max_age=max_age)
            types = {m["zone_type"] for m in members}
            if types & {"DEMAND", "SUPPLY"}:
                ztype = "DEMAND" if pol == "LOW" else "SUPPLY"
            elif types & {"EQUAL_HIGHS", "EQUAL_LOWS"} and types & {"PREVIOUS_DAY_HIGH", "PREVIOUS_DAY_LOW", "PREVIOUS_SESSION_HIGH",
                                                                       "PREVIOUS_SESSION_LOW", "INTRADAY_HIGH", "INTRADAY_LOW"}:
                ztype = "LIQUIDITY_CLUSTER"
            else:
                ztype = min(types, key=lambda t: PRIORITY.index(t) if t in PRIORITY else 99)
            anchor = min(members, key=lambda m: (_t(m.get("confirmed_at")) or 9e18, m["zone_id"]))
            statuses = [m["status"] for m in members]
            status = ("PROVISIONAL" if all(s == "PROVISIONAL" for s in statuses) else "SWEPT" if "SWEPT" in statuses else
                      "WEAKENED" if "WEAKENED" in statuses else "TESTED" if "TESTED" in statuses else "ACTIVE")
            conf = [_t(m.get("confirmed_at")) for m in members if m.get("confirmed_at")]
            role = "RESISTANCE" if lo > price else "SUPPORT" if up < price else "AT_PRICE"
            out.append({"zone_id": "UZ-" + hashlib.sha256(anchor["zone_id"].encode()).hexdigest()[:12], "schema_version": SCHEMA,
                        "zone_type": ztype, "polarity": pol, "role": role, "origin_module": VERSION, "timeframes": sorted({m.get("tf") for m in members}),
                        "lower_price": lo, "upper_price": up, "mid_price": round((lo + up) / 2, 10), "width_atr": round((up - lo) / atr, 3) if atr else None,
                        "created_at": min((m.get("created_at") for m in members if m.get("created_at")), default=None),
                        "confirmed_at": iso(min(conf)) if conf else None, "last_updated_at": iso(as_of), "status": status,
                        "provisional": "PROVISIONAL" in flags,
                        "structure_evidence": [e for e in evidence if e["group"] in ("structure", "mtf")],
                        "volume_evidence": [e for e in evidence if e["group"] == "volume"],
                        "reaction_metrics": {"retests": max((m.get("retests") or 0) for m in members),
                                             "rejection_max_atr": max((m.get("rejection_max_atr") or 0) for m in members),
                                             "penetration_max": max((m.get("penetration_max") or 0) for m in members),
                                             "swept": any(m.get("status") == "SWEPT" for m in members),
                                             "age_bars": min((m.get("age_bars") for m in members if m.get("age_bars") is not None), default=None)},
                        "score_components": comp, "flags": flags, "confidence_status": "UNVALIDATED",
                        "invalidation_rules": {"broken_by": f"zamknięcie {'powyżej' if pol == 'HIGH' else 'poniżej'} {up if pol == 'HIGH' else lo} "
                                                            f"o ≥ {cfg.break_close_atr} ATR", "wick_only": "knot bez zamknięcia = test/sweep, nie przełamanie"},
                        "source_zone_ids": [m["zone_id"] for m in members], "member_types": sorted(types),
                        "liquidity": next((m.get("liquidity") for m in members if m.get("liquidity")), None),
                        "distance_atr": round(0.0 if role == "AT_PRICE" else min(abs(price - lo), abs(price - up)) / atr, 3) if atr else None})
    # contradictions: strong opposite-polarity zones overlapping each other
    for z in out:
        opp = [o for o in out if o["polarity"] != z["polarity"] and o["lower_price"] <= z["upper_price"] + tol and o["upper_price"] >= z["lower_price"] - tol]
        if opp:
            z["flags"].append("CONFLICT")
            z["conflicting_zone_ids"] = [o["zone_id"] for o in opp]
    for z in out:
        pen = 10 * ("WIDE" in z["flags"]) + 10 * ("CONFLICT" in z["flags"]) + 10 * ("PROVISIONAL" in z["flags"]) + \
              5 * ("INSUFFICIENT_HISTORY" in z["flags"])
        z["penalty"] = pen
        z["confluence_score"] = round(max(0.0, min(100.0, sum(z["score_components"].values()) - pen)), 1)
    out.sort(key=lambda z: (z["distance_atr"] if z["distance_atr"] is not None else 9e9, -z["confluence_score"]))
    return out, expired


def nearest(zmap: dict, side: str, price: float, *, min_score: float = 0.0) -> dict | None:
    """side ABOVE = the nearest live zone that can act as RESISTANCE for price (HIGH polarity at or above price, or a LOW-polarity
    zone wholly above price - a support that price fell below); BELOW = the mirror for SUPPORT."""
    zs = [z for z in zmap.get("zones") or [] if z["confluence_score"] >= min_score and z["status"] in LIVE]
    if side == "ABOVE":
        zs = [z for z in zs if (z["polarity"] == "HIGH" and z["upper_price"] >= price) or (z["polarity"] == "LOW" and z["lower_price"] > price)]
        return min(zs, key=lambda z: (max(0.0, z["lower_price"] - price), -z["confluence_score"]), default=None)
    zs = [z for z in zs if (z["polarity"] == "LOW" and z["lower_price"] <= price) or (z["polarity"] == "HIGH" and z["upper_price"] < price)]
    return min(zs, key=lambda z: (max(0.0, price - z["upper_price"]), -z["confluence_score"]), default=None)
