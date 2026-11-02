"""Routing and aggregation of predictions (PMW-AGG-1).

* Only READY predictions take part; anything else is listed with its reason and contributes nothing.
* Predictions are grouped by (task, horizon, unit) AND by correlation group: different meanings, units or horizons are never
  averaged together; inside one group only ONE model speaks (the one with the best development walk-forward skill) - four models
  predicting the same M5 move are one piece of evidence, not four (no double counting).
* Weights come from the development (walk-forward) skill recorded in the package - never from the final test set.
* Explicit mapping to strategy roles (ROUTES): which task may inform which role of SCALPING / HEDGING. Training Center models are
  OBSERVATION until validated in SHADOW on real data - they never vote by default (the risk system and gates are unchanged).
"""
from __future__ import annotations

ROUTES = {
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
        k = (route["group"], p["task"], p["horizon"]["bars"], p["unit"])
        groups.setdefault(k, []).append((p, route))
    out = []
    for (grp, task, h, unit), items in groups.items():
        scored = [(dev_skill(inst, p.get("model_key"), p["model_version"]), p, r) for p, r in items]
        scored.sort(key=lambda x: (x[0] is not None, x[0] or -1), reverse=True)
        sk, p, r = scored[0]
        res = p["result"]
        out.append({"group": grp, "task": task, "horizon_bars": h, "unit": unit, "role": r.get(strategy), "use": DEFAULT_USE,
                    "speaker": p.get("model_key"), "version": p["model_version"], "dev_skill": sk, "weight": max(0.0, sk or 0.0),
                    "direction_edge": round(res["UP"] - res["DOWN"], 4) if isinstance(res, dict) and "UP" in res else None,
                    "silenced_same_group": [x[1].get("model_key") for x in scored[1:]], "data_time": p["data_time"]})
    return {"instrument": inst, "strategy": strategy, "groups": out, "excluded": excluded,
            "rules": "jedna grupa korelacji = jeden głos; wagi z walidacji walk-forward (bez zbioru końcowego); różne zadania/horyzonty/jednostki "
                     "nie są łączone; modele Centrum treningu = OBSERVATION do czasu walidacji SHADOW na danych rzeczywistych"}
