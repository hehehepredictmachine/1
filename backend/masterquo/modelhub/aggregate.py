"""Routing and aggregation of predictions (PMW-AGG-1).

* Only READY predictions take part; anything else is listed with its reason and contributes nothing.
* Predictions are grouped by correlation group (ROUTES): inside one group only ONE model speaks (the one with the best development
  walk-forward skill) - four models predicting the M5 move are one piece of evidence, not four (no double counting). Results with
  different meanings, units or horizons are never averaged: the silenced members are only listed with their task and horizon.
* Weights come from the development (walk-forward) skill recorded in the package - never from the final test set.
* Explicit mapping to strategy roles (ROUTES): which task may inform which role of SCALPING / HEDGING. Training Center models are
  OBSERVATION until validated in SHADOW on real data - they never vote by default (the risk system and gates are unchanged).
"""
from __future__ import annotations

ROUTES = {
    ("CANDLE_CLOSE_DIRECTION_H", "M5"): {"group": "M5_DIRECTION", "SCALPING": "TIMING", "HEDGING": "DIRECTION_STRUCTURE"},   # gold_candles
    ("DIRECTION_H", "M1"): {"group": "M1_DIRECTION", "SCALPING": "DIRECTION_STRUCTURE", "HEDGING": "TIMING"},
    ("DIRECTION_H", "M5"): {"group": "M5_DIRECTION", "SCALPING": "TIMING", "HEDGING": "DIRECTION_STRUCTURE"},
    ("DIRECTION_H", "M15"): {"group": "HTF_DIRECTION", "SCALPING": "DIRECTION_STRUCTURE", "HEDGING": "DIRECTION_STRUCTURE"},
    ("DIRECTION_H", "M30"): {"group": "HTF_DIRECTION", "SCALPING": "DIRECTION_STRUCTURE", "HEDGING": "DIRECTION_STRUCTURE"},
}
DEFAULT_USE = "OBSERVATION"


def _task_family(p: dict) -> str:
    """'DIRECTION_H6_M5' -> 'DIRECTION_H' (task without its horizon and timeframe)."""
    import re
    m = re.match(r"^(.*_H)\d+(?:_.*)?$", p.get("task") or "")
    return m.group(1) if m else (p.get("task") or "?")


def dev_skill(inst: str, key: str, version: str) -> float | None:
    from ..trainhub import registry as R
    for v in (R.registry(inst).get("versions") or {}).get(key, []):
        if v["version"] == version:
            return (v.get("walk_forward") or {}).get("dev_skill_vs_baseline")
    return None


def evidence(preds: list[dict], strategy: str, inst: str) -> dict:
    groups: dict[tuple, list] = {}
    excluded = []
    for p in preds:
        if p["state"] != "READY":
            excluded.append({"model": p.get("model_key") or p["model_name"], "state": p["state"], "reason": p.get("unavailable_reason")})
            continue
        route = ROUTES.get((_task_family(p), p["timeframe"]))
        if route is None:
            excluded.append({"model": p.get("model_key"), "state": "READY", "reason": "brak jawnego mapowania zadania na rolę strategii"})
            continue
        groups.setdefault(route["group"], []).append((p, route))
    out = []
    for grp, items in groups.items():
        # one correlation group = ONE speaker (best development skill); the others are listed, never averaged in (their task /
        # horizon / unit may differ - such results are not combined)
        scored = [(dev_skill(inst, p.get("model_key"), p["model_version"]), p, r) for p, r in items]
        scored.sort(key=lambda x: (x[0] is not None, x[0] or -1), reverse=True)
        sk, p, r = scored[0]
        res = p["result"]
        out.append({"group": grp, "task": p["task"], "horizon_bars": p["horizon"]["bars"], "unit": p["unit"], "role": r.get(strategy),
                    "use": DEFAULT_USE, "speaker": p.get("model_key") or p["model_name"], "version": p["model_version"], "dev_skill": sk,
                    "weight": max(0.0, sk or 0.0),
                    "direction_edge": round(res["UP"] - res["DOWN"], 4) if isinstance(res, dict) and "UP" in res else None,
                    "silenced_same_group": [{"model": x[1].get("model_key") or x[1]["model_name"], "task": x[1]["task"],
                                             "horizon_bars": x[1]["horizon"]["bars"]} for x in scored[1:]], "data_time": p["data_time"]})
    return {"instrument": inst, "strategy": strategy, "groups": out, "excluded": excluded,
            "rules": "jedna grupa korelacji = jeden głos; wagi z walidacji walk-forward (bez zbioru końcowego); różne zadania/horyzonty/jednostki "
                     "nie są łączone; modele Centrum treningu = OBSERVATION do czasu walidacji SHADOW na danych rzeczywistych"}
