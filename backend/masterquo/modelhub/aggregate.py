"""Routing and aggregation of predictions (PMW-AGG-1).

* Only READY predictions take part; anything else is listed with its reason and contributes nothing.
* Predictions are grouped by correlation group (ROUTES): inside one group only ONE model speaks (the one with the best development
  walk-forward skill) - four models predicting the M5 move are one piece of evidence, not four (no double counting). Results with
  different meanings, units or horizons are never averaged: the silenced members are only listed with their task and horizon.
  The baseline (TH_BASELINE) and a model measured as no better than it (dev skill <= 0) never speak; when no member may speak the
  group is listed with speaker None and the reason (arch146 D12).
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
BASELINE = "TH_BASELINE"


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


def _is_baseline(p: dict) -> bool:
    """The Training Center reference model (class frequencies of the training rows) - every dev skill is measured against it."""
    return str(p.get("model_key") or "").startswith(BASELINE + "_") or p.get("model_name") == BASELINE


def _may_speak(p: dict, skill: float | None) -> bool:
    """arch146 D12: the baseline never speaks for a group, nor a model measured as no better than it (walk-forward dev skill <= 0)."""
    return not _is_baseline(p) and (skill is None or skill > 0)


def evidence(preds: list[dict], strategy: str, inst: str) -> dict:
    groups: dict[tuple, list] = {}
    excluded = []
    for p in preds:
        if p["state"] != "READY":
            excluded.append({"model": p.get("model_key") or p["model_name"], "state": p["state"], "reason": p.get("unavailable_reason")})
            continue
        route = ROUTES.get((_task_family(p), p["timeframe"]))
        if route is None:
            why = ("prognoza ceny (regresja, jednostka: cena) – osobny kontekst Kronos w strategii; nie łączona z prawdopodobieństwami"
                   if p.get("unit") == "price" else "brak jawnego mapowania zadania na rolę strategii")
            # 1.46: families / research modules have no model_key - the entry read {"model": None} (same fallback as the non-READY branch)
            excluded.append({"model": p.get("model_key") or p["model_name"], "state": "READY", "reason": why})
            continue
        groups.setdefault(route["group"], []).append((p, route))
    out = []
    for grp, items in groups.items():
        # one correlation group = ONE speaker (best development skill); the others are listed, never averaged in (their task /
        # horizon / unit may differ - such results are not combined)
        scored = [(dev_skill(inst, p.get("model_key"), p["model_version"]), p, r) for p, r in items]
        # 1.46: a dev skill of exactly 0.0 is a value - `x[0] or -1` ranked it below a negative skill (the worse model spoke)
        # arch146 D12: the speaker must be able to beat the baseline - TH_BASELINE (class frequencies, skill ~0 by construction) and a model
        # measured as no better than it (dev skill <= 0) never speak (c8277f4: the baseline spoke whenever the others were worse / unmeasured).
        # An UNMEASURED skill (None: gold_candles, Studio import) is not evidence of being worse - it keeps its place after measured ones.
        scored.sort(key=lambda x: (_may_speak(x[1], x[0]), x[0] is not None, x[0] if x[0] is not None else float("-inf")), reverse=True)
        silenced = [{"model": x[1].get("model_key") or x[1]["model_name"], "task": x[1]["task"], "horizon_bars": x[1]["horizon"]["bars"]}
                    for x in scored]
        sk, p, r = scored[0]
        if not _may_speak(p, sk):
            out.append({"group": grp, "task": None, "horizon_bars": None, "unit": None, "role": r.get(strategy), "use": DEFAULT_USE,
                        "speaker": None, "version": None, "dev_skill": None, "weight": 0.0, "direction_edge": None,
                        "silenced_same_group": silenced, "data_time": None,
                        "reason": "żaden model grupy nie bije modelu bazowego w walidacji walk-forward (model bazowy TH_BASELINE i modele "
                                  "z umiejętnością <= 0 nie są głosem grupy)"})
            continue
        res = p["result"]
        out.append({"group": grp, "task": p["task"], "horizon_bars": p["horizon"]["bars"], "unit": p["unit"], "role": r.get(strategy),
                    "use": DEFAULT_USE, "speaker": p.get("model_key") or p["model_name"], "version": p["model_version"], "dev_skill": sk,
                    "weight": max(0.0, sk or 0.0),
                    "direction_edge": round(res["UP"] - res["DOWN"], 4) if isinstance(res, dict) and "UP" in res else None,
                    "silenced_same_group": silenced[1:], "data_time": p["data_time"]})
    return {"instrument": inst, "strategy": strategy, "groups": out, "excluded": excluded,
            "rules": "jedna grupa korelacji = jeden głos; wagi z walidacji walk-forward (bez zbioru końcowego); różne zadania/horyzonty/jednostki "
                     "nie są łączone; modele Centrum treningu = OBSERVATION do czasu walidacji SHADOW na danych rzeczywistych"}
