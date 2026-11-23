"""Market Trap Detector + Trading Behaviour Risk Guard (Apollo23 TASK 022) - OFF / SHADOW, read-only, warns only.

It never states that institutions manipulate a market and never identifies participants. It detects OBSERVABLE risk patterns and lists
alternative explanations. MARKET_TRAP_SCORE (0-100, not a probability), CONFIDENCE, SEVERITY (1-5) and BEHAVIOURAL_RISK_SCORE are four
separate outputs; behavioural risk never raises the market score. Missing data stays UNAVAILABLE (never 0, never rebuilt from OHLCV):
spoofing / layering-like patterns need MBO/L3, executed-flow divergence needs verified aggressor semantics, news bursts need a verified feed.
"""
from __future__ import annotations

import bisect

VERSION = "PMW-MTD-1"
WEIGHTS = {"STRUCTURE_LIQUIDITY": 25, "EXECUTED_FLOW": 20, "CROSS_MARKET": 15, "PRICE_RESPONSE": 20, "REGIME_NEWS": 10, "EXECUTION_STRESS": 10}
ALTERNATIVES = {"FALSE_BREAKOUT_ACCEPTANCE_FAIL": ["zwykła zmienność", "brak płynności po wybiciu", "news / dane makro"],
                "SWEEP_RECLAIM_PROXY": ["realizacja zysków", "naturalny powrót do zakresu", "zmiana sesji"],
                "EXECUTION_STRESS": ["niska płynność sesji", "rollover / przerwa brokera"]}


def _atr(bars, n=14):
    tr = [b["h"] - b["l"] if i == 0 else max(b["h"] - b["l"], abs(b["h"] - bars[i - 1]["c"]), abs(b["l"] - bars[i - 1]["c"])) for i, b in enumerate(bars)]
    return sum(tr[-n:]) / min(n, len(tr)) if tr else None


def price_response(bars: list[dict], lookback: int = 20) -> dict:
    """On CLOSED bars up to as-of: breakout of the prior range that closes back inside (acceptance fail) and sweep + reclaim proxies."""
    if len(bars) < lookback + 2:
        return {"status": "UNAVAILABLE", "reason": "INSUFFICIENT_BARS", "score": None, "reasons": []}
    prior = bars[-lookback - 1:-1]
    hi, lo = max(b["h"] for b in prior), min(b["l"] for b in prior)
    last = bars[-1]
    atr = _atr(bars) or 1e-12
    reasons, score = [], 0.0
    if last["h"] > hi and last["c"] < hi:
        reasons.append("FALSE_BREAKOUT_ACCEPTANCE_FAIL")
        score += min(1.0, (last["h"] - hi) / atr)
    if last["l"] < lo and last["c"] > lo:
        reasons.append("SWEEP_RECLAIM_PROXY")
        score += min(1.0, (lo - last["l"]) / atr)
    return {"status": "OK", "score": min(1.0, score), "reasons": reasons, "range": [lo, hi], "atr": atr}


def execution_stress(spread_points: float | None, spread_baseline: float | None, planned_size: float | None) -> dict:
    if spread_points is None or not spread_baseline:
        return {"status": "UNAVAILABLE", "score": None, "reasons": ["NO_QUOTE_OR_BASELINE"]}
    r = spread_points / spread_baseline
    return {"status": "OK", "score": max(0.0, min(1.0, (r - 1) / 2)), "reasons": ["EXECUTION_STRESS"] if r > 2 else [], "spread_ratio": r,
            "size_known": planned_size is not None}


def detect(bars: list[dict], *, spread_points=None, spread_baseline=None, planned_size=None, aggressor_verified=False, mbo_available=False,
           news_verified=False, mode: str = "SHADOW") -> dict:
    comps = {"PRICE_RESPONSE": price_response(bars), "EXECUTION_STRESS": execution_stress(spread_points, spread_baseline, planned_size),
             "EXECUTED_FLOW": {"status": "UNAVAILABLE", "score": None, "reasons": ["AGGRESSOR_NOT_VERIFIED"]} if not aggressor_verified else
             {"status": "NOT_IMPLEMENTED_FOR_FEED", "score": None, "reasons": []},
             "STRUCTURE_LIQUIDITY": {"status": "UNAVAILABLE", "score": None, "reasons": ["MBO_UNAVAILABLE" if not mbo_available else "L2_ONLY"]},
             "CROSS_MARKET": {"status": "UNAVAILABLE", "score": None, "reasons": ["SECOND_SOURCE_NOT_CONFIGURED"]},
             "REGIME_NEWS": {"status": "UNAVAILABLE", "score": None, "reasons": ["NEWS_FEED_NOT_VERIFIED"] if not news_verified else []}}
    avail = {k: v for k, v in comps.items() if v.get("score") is not None}
    wsum = sum(WEIGHTS[k] for k in avail)
    score = round(100 * sum(WEIGHTS[k] * v["score"] for k, v in avail.items()) / wsum, 1) if wsum else None
    coverage = wsum / sum(WEIGHTS.values())
    reasons = [r for v in comps.values() for r in v.get("reasons", [])]
    pattern_reasons = [r for r in reasons if r in ALTERNATIVES]
    sev = None if score is None else (1 + min(4, int(score // 20)))
    rec = "WAIT" if (score is not None and score >= 60 and coverage >= 0.3) else "NONE"
    # 1.46: with OHLC only (PRICE_RESPONSE, weight 20) coverage is 0.2 < 0.3, so a high score silently said NONE - the reason is explicit now
    rec_status = "UNAVAILABLE" if score is None else ("INSUFFICIENT_COVERAGE" if score >= 60 and coverage < 0.3 else "OK")
    return {"version": VERSION, "mode": mode, "market_trap_score": score, "confidence": round(coverage, 2), "severity": sev,
            "components": comps, "reason_codes": reasons, "alternative_explanations": {r: ALTERNATIVES[r] for r in pattern_reasons},
            "recommendation": rec, "recommendation_status": rec_status, "recommendation_min_coverage": 0.3,
            "recommendation_scope": "tylko nowe wejście, przez istniejącą bramę Risk/STOP/Execution; brak akcji na zleceniach",
            "disclaimer": "wzorzec ryzyka, nie dowód manipulacji ani identyfikacja uczestników; wynik 0–100 nie jest prawdopodobieństwem",
            "spoofing_layering": "UNAVAILABLE (wymaga MBO/L3)" if not mbo_available else "NOT_IMPLEMENTED"}


def behaviour(trades: list[dict], *, window_s: float = 900, chase_atr: float = 2.0) -> dict:
    """Own-user closed trades (opt-in): {opened, closed, size, net, risk?, entry_move_atr?}. Separate score; no psychological diagnosis."""
    if len(trades) < 5:
        return {"behavioural_risk_score": None, "status": "LOW_SAMPLE", "flags": []}
    t = sorted(trades, key=lambda x: x["opened"])
    flags = []
    sizes = [x["size"] for x in t]
    base = sorted(sizes)[len(sizes) // 2]
    # 1.46: "after a loss" = the trade CLOSED most recently before `cur` opened (was: the previous one by open time - a trade opened while
    # a later loser was still open got both post-loss flags, with a negative gap); the chase check covers the first trade too
    by_close = sorted(t, key=lambda x: x["closed"])
    closes = [x["closed"] for x in by_close]
    for cur in t:
        j = bisect.bisect_right(closes, cur["opened"]) - 1
        while j >= 0 and by_close[j] is cur:
            j -= 1
        prev = by_close[j] if j >= 0 else None
        if prev is not None and prev["net"] < 0 and cur["size"] > 1.5 * base:
            flags.append({"code": "POST_LOSS_SIZE_ESCALATION", "at": cur["opened"]})
        if prev is not None and prev["net"] < 0 and cur["opened"] - prev["closed"] < window_s:
            flags.append({"code": "RAPID_REENTRY_AFTER_LOSS", "at": cur["opened"]})
        if (cur.get("entry_move_atr") or 0) >= chase_atr:
            flags.append({"code": "LATE_MOVE_CHASE_POOR_RR", "at": cur["opened"]})
    days: dict[int, int] = {}
    for x in t:
        days[int(x["opened"] // 86400)] = days.get(int(x["opened"] // 86400), 0) + 1
    med = sorted(days.values())[len(days) // 2]
    flags += [{"code": "TRADE_FREQUENCY_SPIKE", "day": d} for d, n in days.items() if n >= 3 * max(1, med) and n >= 6]
    win_h = [x["closed"] - x["opened"] for x in t if x["net"] > 0]
    loss_h = [x["closed"] - x["opened"] for x in t if x["net"] < 0]
    if win_h and loss_h and sum(loss_h) / len(loss_h) > 2 * sum(win_h) / len(win_h):
        flags.append({"code": "DISPOSITION_ASYMMETRY"})
    score = min(100, 15 * len(flags))
    return {"behavioural_risk_score": score, "status": "OK", "flags": flags, "sample": len(t),
            "note": "proxy zachowań na danych użytkownika – nie diagnoza; nie wpływa na wynik rynkowy"}
