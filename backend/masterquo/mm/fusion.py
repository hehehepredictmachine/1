"""Evidence board - explicit, non-trainable integration layer for the master-model outputs (PMW-MM-FUSION-1).

It does NOT fuse scores. For one symbol it validates every output (symbol, timeframe, available_at <= now, staleness against its own
timeframe, version, data quality) and lays them side by side with their OWN semantics (a GP predictive distribution, a classifier
probability, an HDC margin, an indicator state and a structure event are never converted into one number). Directional readings are
listed with their horizon; disagreement and missing inputs are kept visible. All these modules read the SAME broker price feed, so
their agreement is not independent confirmation (`independence = SAME_PRICE_FEED`). No output of this board is an order instruction.
"""
from __future__ import annotations

import time

VERSION = "PMW-MM-FUSION-1"
TF_S = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "EVENTS": 600}


def _direction(o: dict) -> str | None:
    p, k = o.get("payload") or {}, o.get("kind")
    if k == "GAUSSIAN_PREDICTIVE" and p.get("mean_logret") is not None:
        return "UP" if p["mean_logret"] > 0 else "DOWN" if p["mean_logret"] < 0 else "FLAT"
    if k == "CLASS_PROBABILITIES" and p.get("probs"):
        return ("DOWN", "FLAT", "UP")[max(range(3), key=lambda i: p["probs"][i])]
    if k == "HDC_SIMILARITY" and p.get("class") is not None:
        return ("DOWN", "FLAT", "UP")[int(p["class"])]
    if k == "INDICATOR_STATE" and p.get("direction"):
        return {"BULLISH": "UP", "BEARISH": "DOWN"}.get(p["direction"], p["direction"])
    if k in ("RULE_SIGNAL", "STRUCTURE_EVENT") and p.get("direction"):
        return {"LONG": "UP", "SHORT": "DOWN"}.get(p["direction"], p["direction"])
    return None


def board(outputs: list[dict], symbol: str, now: float | None = None) -> dict:
    now = now or time.time()
    rows, rejected = [], []
    for o in outputs:
        env = o.get("envelope") or {}
        why = []
        if env.get("symbol") != symbol:
            why.append("SYMBOL_MISMATCH")
        if env.get("available_at") is None or env["available_at"] > now + 1e-6:
            why.append("NOT_YET_AVAILABLE")
        tf = env.get("timeframe")
        if tf in TF_S and env.get("available_at") is not None and now - env["available_at"] > 3 * TF_S[tf]:
            why.append("STALE")
        if env.get("data_quality") not in ("OK", "SYNTHETIC_TEST", "DEGRADED"):
            why.append(f"QUALITY_{env.get('data_quality')}")
        if not env.get("model_version") and o.get("kind") not in ("INDICATOR_STATE", "RULE_SIGNAL", "STRUCTURE_EVENT"):
            why.append("NO_MODEL_VERSION")
        if o.get("execution_allowed"):
            why.append("EXECUTION_FLAG_SET")                               # never accepted on the board
        r = {"source": env.get("source_id"), "kind": o.get("kind"), "timeframe": tf, "available_at": env.get("available_at"),
             "version": env.get("model_version"), "quality": env.get("data_quality"), "direction": _direction(o), "horizon": (o.get("payload") or {}).get("horizon"),
             "payload": o.get("payload"), "status": o.get("status")}
        (rejected if why else rows).append({**r, "rejected": why} if why else r)
    dirs = [r["direction"] for r in rows if r["direction"] in ("UP", "DOWN")]
    return {"version": VERSION, "symbol": symbol, "at": now, "readings": rows, "rejected": rejected,
            "directional": {"UP": dirs.count("UP"), "DOWN": dirs.count("DOWN"), "disagreement": bool(dirs) and len(set(dirs)) > 1},
            "independence": "SAME_PRICE_FEED - zgodność modułów nie jest niezależnym potwierdzeniem",
            "rule": "brak głosowania i brak łączenia wyników; każdy odczyt ma własną semantykę i horyzont", "execution_allowed": False}
