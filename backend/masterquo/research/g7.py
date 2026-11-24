"""G7 SMC Radar - port of G7_Indicato7.mq5 (Sophea Khin, https://www.mql5.com/en/code/79287, sha256 58875e80...). Implementation id
PMW_G7_SRC_PORT_V2 (the source WAS read). Rule context, NOT a probability (score type RULE_CONFLUENCE_NOT_PROBABILITY):

  CheckFVG(tf)  bars 1..3 of the series (1 = newest CLOSED): +1 when low[1] > high[3], -1 when high[1] < low[3], else 0
  CheckOB(tf)   source loop i = 2..14 over CopyRates(..., 0, ...) - index 0 is the FORMING bar, so the pairs are (newest closed - 1,
                newest closed) .. 13 pairs back: a bearish bar followed by a bullish bar whose body > impulse x the bearish body -> +1
                (bullish OB); symmetric -> -1; the first match (newest) wins; lookback 50 bars of history required
  corr          Pearson correlation x 100 of the H1 CLOSE LEVELS (not returns) of the instrument and DXY over 24 bars
  score         netFVG = fvg(M5) + fvg(M15): +30 / -30; obH1: +40 / -40; corr < -30: +30 (the SOURCE adds +30 regardless of the side -
                kept as published and flagged `asymmetric_dxy_term`); netFVG and obH1 of opposite signs -> score x 0.5 (CONFLICT)
Without DXY data the corr term is ABSENT (coverage < 1, reason given) - it is never filled with 0 that could look like data; the
source's own behaviour (0 when DXY is missing) yields the same score, the coverage makes the difference visible. DXY is never replaced
by US30 / a random USD symbol. The zone LIFECYCLE (created / available / touched / mitigated / invalidated) is PMW's addition: the
source deletes mitigated boxes from the chart, PMW keeps them as history (a mitigated zone stays in the snapshot of earlier decisions).

V2 (1.46 audit, I0803 / I0804) - `radar`, `check_fvg`, `check_ob`:
  * CheckOB checks the pairs (s[i], s[i-1]) for i = 1..13 (s[0] = newest closed = the source's rates[1]); V1 started at i = 2, i.e. one
    bar too far back - the newest closed pair was never an order block;
  * too few candles of a timeframe (FVG < 4, OB < lookback) is an ABSENT component (None + reason), never 0 ("no FVG / OB"); netFVG
    from the present FVG components; coverage = present components / 4; without M5 or H1 the score is None (state BLOCKED_DATA).
V1 (PMW_G7_SRC_PORT_V1, `radar_v1`, `check_fvg_v1`, `check_ob_v1`) is kept BIT FOR BIT: the published research columns rm:g7_* and
the record research:g7_smc_radar are inputs of trained Quant meta-models (ASSIST can HOLD) - an old artifact never gets the new meaning;
the V2 values are published next to them under their own names (research/service.py).
"""
from __future__ import annotations

import hashlib
import math

VERSION = "PMW_G7_SRC_PORT_V2"
LEGACY_VERSION = "PMW_G7_SRC_PORT_V1"
DEFAULT = {"ob_lookback": 50, "impulse_factor": 1.5, "corr_periods": 24}
TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
WEIGHTS = {"net_fvg": 30, "ob_h1": 40, "dxy_corr_lt_-30": 30}


def _fvg(bars: list[dict]) -> int:
    r1, r3 = bars[-1], bars[-3]
    if float(r1["l"]) > float(r3["h"]):
        return 1
    if float(r1["h"]) < float(r3["l"]):
        return -1
    return 0


def check_fvg(bars: list[dict]) -> int | None:
    """bars oldest-first, CLOSED only. Source: r[1] = newest closed, r[3] = three bars back. V2: None when fewer than 4 bars (absent)."""
    if len(bars) < 4:
        return None
    return _fvg(bars)


def check_fvg_v1(bars: list[dict]) -> int:
    """V1 (legacy inputs): 0 when fewer than 4 bars."""
    if len(bars) < 4:
        return 0
    return _fvg(bars)


def _ob(s: list[dict], first: int, stop: int, impulse: float) -> int:
    for i in range(first, stop):
        ri, rp = s[i], s[i - 1]
        oi, ci, op, cp = float(ri["o"]), float(ri["c"]), float(rp["o"]), float(rp["c"])
        if ci < oi and cp > op and (cp - op) > (oi - ci) * impulse:
            return 1
        if ci > oi and cp < op and (op - cp) > (ci - oi) * impulse:
            return -1
    return 0


def check_ob(bars: list[dict], lookback: int = 50, impulse: float = 1.5) -> int | None:
    """V2: the source's 13 pairs from the newest closed one; None when fewer than `lookback` bars (absent)."""
    if len(bars) < lookback:
        return None
    s = list(reversed(bars[-(lookback + 1):]))               # series order like CopyRates(...,0,...) without the forming bar: s[0] = newest closed
    return _ob(s, 1, 14, impulse)


def check_ob_v1(bars: list[dict], lookback: int = 50, impulse: float = 1.5) -> int:
    """V1 (legacy inputs): pairs from (s[2], s[1]) - the newest closed pair skipped; 0 when fewer than `lookback` bars."""
    if len(bars) < lookback:
        return 0
    s = list(reversed(bars[-(lookback + 1):]))
    return _ob(s, 2, 15, impulse)


def pearson_levels(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3 or len(b) != n:
        return None
    sx, sy = sum(a), sum(b)
    sxy = sum(x * y for x, y in zip(a, b))
    sx2, sy2 = sum(x * x for x in a), sum(y * y for y in b)
    den = math.sqrt(max(0.0, (n * sx2 - sx * sx) * (n * sy2 - sy * sy)))
    if den == 0:
        return None
    return (n * sxy - sx * sy) / den * 100.0


def _corr(h1: list[dict], dxy_h1: list[dict] | None, n: int) -> tuple[float | None, str | None]:
    corr, why = None, None
    if dxy_h1 and len(dxy_h1) >= n and len(h1) >= n:
        common = {int(b["t"]): float(b["c"]) for b in dxy_h1}
        pairs = [(float(b["c"]), common[int(b["t"])]) for b in h1 if int(b["t"]) in common][-n:]
        if len(pairs) == n:
            corr = pearson_levels([x for x, _ in pairs], [y for _, y in pairs])
        else:
            why = "DXY: brak wspólnych zamkniętych świec H1 (różne godziny notowań)"
    else:
        why = "DXY niedostępny w terminalu / dostawcy – składowa nieobecna (nie 0)"
    return corr, why


def _score(net: int, ob: int, corr: float | None) -> tuple[int, int, bool]:
    score = 0
    if net > 0:
        score += 30
    elif net < 0:
        score -= 30
    if ob > 0:
        score += 40
    elif ob < 0:
        score -= 40
    dxy_term = 0
    if corr is not None and corr < -30:
        score += 30                                          # source: +30 independent of the side (flagged below)
        dxy_term = 30
    conflict = (net > 0 and ob < 0) or (net < 0 and ob > 0)
    if conflict:
        score = int(score * 0.5)
    return score, dxy_term, conflict


def radar_v1(m5: list[dict], m15: list[dict], h1: list[dict], dxy_h1: list[dict] | None, p: dict | None = None) -> dict:
    """V1 output exactly as 1.46 published it (legacy inputs of trained models): shifted CheckOB, missing candles = 0, coverage 3 + DXY."""
    p = {**DEFAULT, **(p or {})}
    fm5, fm15 = check_fvg_v1(m5), check_fvg_v1(m15)
    ob = check_ob_v1(h1, int(p["ob_lookback"]), float(p["impulse_factor"]))
    corr, why = _corr(h1, dxy_h1, int(p["corr_periods"]))
    net = fm5 + fm15
    comp = {"fvg_m5": fm5, "fvg_m15": fm15, "net_fvg": net, "ob_h1": ob, "dxy_corr_h1_levels": corr}
    score, dxy_term, conflict = _score(net, ob, corr)
    present = 3 + (1 if corr is not None else 0)
    return {"implementation_id": LEGACY_VERSION, "rule_confluence_score": float(score), "score_type": "RULE_CONFLUENCE_NOT_PROBABILITY",
            "scale": "-100..100 (źródło); NIE jest prawdopodobieństwem", "components": comp, "weights": dict(WEIGHTS),
            "conflict": conflict, "dxy_term": dxy_term, "asymmetric_dxy_term": True, "coverage": round(present / 4, 2), "reason": why,
            "params": p, "zone_correlation_group": "STRUCTURE_FVG_OB"}


def radar(m5: list[dict], m15: list[dict], h1: list[dict], dxy_h1: list[dict] | None, p: dict | None = None) -> dict:
    """V2: source-exact CheckOB; a timeframe without enough candles is an absent component; without M5 or H1 no score (None)."""
    p = {**DEFAULT, **(p or {})}
    lb = int(p["ob_lookback"])
    fm5, fm15 = check_fvg(m5), check_fvg(m15)
    ob = check_ob(h1, lb, float(p["impulse_factor"]))
    corr, why = _corr(h1, dxy_h1, int(p["corr_periods"]))
    reasons = []
    for tf, v, n, have in (("M5", fm5, 4, len(m5)), ("M15", fm15, 4, len(m15)), ("H1", ob, lb, len(h1))):
        if v is None:
            reasons.append(f"{tf}: {have} zamkniętych świec (< {n}) – składowa nieobecna (nie 0)")
    if why:
        reasons.append(why)
    fvg = [v for v in (fm5, fm15) if v is not None]
    net = sum(fvg) if fvg else None
    comp = {"fvg_m5": fm5, "fvg_m15": fm15, "net_fvg": net, "ob_h1": ob, "dxy_corr_h1_levels": corr}
    present = sum(v is not None for v in (fm5, fm15, ob, corr))
    if fm5 is None or ob is None:
        score, dxy_term, conflict, state = None, None, None, "BLOCKED_DATA"
    else:
        sc, dxy_term, conflict = _score(net, ob, corr)
        score, state = float(sc), "READY"
    return {"implementation_id": VERSION, "rule_confluence_score": score, "state": state, "score_type": "RULE_CONFLUENCE_NOT_PROBABILITY",
            "scale": "-100..100 (źródło); NIE jest prawdopodobieństwem", "components": comp, "weights": dict(WEIGHTS),
            "conflict": conflict, "dxy_term": dxy_term, "asymmetric_dxy_term": True, "coverage": round(present / 4, 2),
            "reason": "; ".join(reasons) or None, "params": p, "zone_correlation_group": "STRUCTURE_FVG_OB"}


def zone_id(inst: str, tf: str, kind: str, t: float, lo: float, hi: float) -> str:
    return "G7Z-" + hashlib.sha256(f"{inst}|{tf}|{kind}|{int(t)}|{lo:.6f}|{hi:.6f}".encode()).hexdigest()[:12]


class ZoneBook:
    """Lifecycle of the FVG / OB zones the radar's rules find on CLOSED bars (PMW addition; the source only draws / deletes boxes)."""

    def __init__(self, inst: str):
        self.inst = inst
        self.zones: dict[str, dict] = {}

    def observe(self, tf: str, bars: list[dict], p: dict | None = None) -> None:
        if len(bars) < 4:
            return
        # 1.46: bars from the bridge carry no tf_s - available_at / valid_from (and the TOUCHED / MITIGATED events) were the OPEN of the
        # bar, i.e. before the bar that formed / touched the zone had closed; now its close = open + the timeframe's duration
        tf_s = float(bars[-1].get("tf_s") or TF_SECONDS.get(tf, 0))
        t_close = float(bars[-1]["t"]) + tf_s
        f = check_fvg(bars)
        if f:
            r1, r3 = bars[-1], bars[-3]
            lo, hi = (float(r3["h"]), float(r1["l"])) if f > 0 else (float(r1["h"]), float(r3["l"]))
            zid = zone_id(self.inst, tf, "FVG", float(bars[-2]["t"]), lo, hi)
            self.zones.setdefault(zid, {"zone_id": zid, "tf": tf, "kind": "FVG", "direction": "BULL" if f > 0 else "BEAR", "lo": lo, "hi": hi,
                                        "created_at": float(bars[-1]["t"]), "available_at": t_close, "valid_from": t_close, "state": "ACTIVE",
                                        "events": [], "detector": VERSION})
        last = bars[-1]
        for z in self.zones.values():
            if z["tf"] != tf or z["state"] in ("MITIGATED", "INVALIDATED", "EXPIRED") or float(last["t"]) <= z["created_at"]:
                continue
            l_, h_, c = float(last["l"]), float(last["h"]), float(last["c"])
            touched = l_ <= z["hi"] and h_ >= z["lo"]
            if z["direction"] == "BULL" and c < z["lo"] or z["direction"] == "BEAR" and c > z["hi"]:
                z["state"] = "MITIGATED"
                z["events"].append({"t": t_close, "event": "MITIGATED"})
            elif touched and z["state"] == "ACTIVE":
                z["state"] = "TOUCHED"
                z["events"].append({"t": t_close, "event": "TOUCHED"})

    def asof(self, t: float) -> list[dict]:
        """Zones as they were known at time t (state replayed from the events <= t) - mitigation later never erases earlier existence."""
        out = []
        for z in self.zones.values():
            if z["available_at"] > t:
                continue
            st = "ACTIVE"
            for e in z["events"]:
                if e["t"] <= t:
                    st = e["event"]
            out.append({**{k: z[k] for k in ("zone_id", "tf", "kind", "direction", "lo", "hi", "created_at", "available_at")}, "state": st})
        return out
