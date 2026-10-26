"""Single configuration source for SCALPING / HEDGING (backend AND panel): config/sh_strategies_v1.json (defaults, in the
repository) + data/sh/config_override.json (user changes from the panel, atomic write, every version kept in history).
The effective config has a hash; a trade plan freezes the hash and its parameters at creation - later changes never modify
an open position's plan."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from pathlib import Path

from .. import paths

DEFAULTS = paths.ROOT_DIR / "config" / "sh_strategies_v1.json"


def _dir() -> Path:
    d = paths.data_dir() / "sh"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def chash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def load() -> dict:
    base = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    ov_p = _dir() / "config_override.json"
    ov = json.loads(ov_p.read_text(encoding="utf-8")) if ov_p.exists() else {}
    cfg = _merge(base, ov.get("override") or {})
    cfg["_hash"] = chash({k: v for k, v in cfg.items() if not k.startswith("_")})
    cfg["_override_version"] = ov.get("version", 0)
    return cfg


ALLOWED_TOP = {"risk", "instruments", "priority", "allow_parallel_same_symbol"}


def validate(cfg: dict) -> list[str]:
    errs = []
    for inst, ic in (cfg.get("instruments") or {}).items():
        for strat in ("SCALPING", "HEDGING"):
            p = ic.get(strat) or {}
            sh = p.get("shares") or []
            if sh and (abs(sum(sh) - 1.0) > 1e-6 or any(x <= 0 for x in sh)):
                errs.append(f"{inst}/{strat}: udziały muszą sumować się do 100 %")
            tp = p.get("tp_usd") or []
            if tp and any(b <= a for a, b in zip(tp, tp[1:])):
                errs.append(f"{inst}/{strat}: TP muszą rosnąć (TP1 < TP2 < TP3)")
            if strat == "HEDGING" and tp and p.get("tp3_choices") and tp[-1] not in p["tp3_choices"]:
                errs.append(f"{inst}/HEDGING: TP3 musi być jedną z wartości {p['tp3_choices']}")
            if p.get("sl_min_usd") and p.get("sl_max_usd") and p["sl_min_usd"] > p["sl_max_usd"]:
                errs.append(f"{inst}/{strat}: sl_min > sl_max")
            h = p.get("hedge") or {}
            if h and (h.get("ratio", 0) <= 0 or h.get("ratio", 0) > h.get("max_ratio", 1.0) or h.get("max_ratio", 1.0) > 1.0):
                errs.append(f"{inst}/HEDGING: 0 < ratio ≤ max_ratio ≤ 1 (brak martingale)")
            if h and h.get("netting_alternative", "BLOCK") not in ("BLOCK", "REDUCE"):
                errs.append(f"{inst}/HEDGING: netting_alternative = BLOCK | REDUCE")
            if h and int(h.get("max_activations", 1)) > 3:
                errs.append(f"{inst}/HEDGING: max_activations ≤ 3")
    return errs


def save_override(patch: dict, who: str = "panel") -> dict:
    bad = [k for k in patch if k not in ALLOWED_TOP]
    if bad:
        raise ValueError("NIEDOZWOLONE_POLA:" + ",".join(bad))
    p = _dir() / "config_override.json"
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"version": 0, "override": {}, "history": []}
    new_ov = _merge(cur.get("override") or {}, patch)
    eff = _merge(json.loads(DEFAULTS.read_text(encoding="utf-8")), new_ov)
    errs = validate(eff)
    if errs:
        raise ValueError("; ".join(errs))
    cur["history"] = (cur.get("history") or [])[-50:] + [{"version": cur.get("version", 0), "override": cur.get("override"), "at": time.time()}]
    cur.update(version=cur.get("version", 0) + 1, override=new_ov, saved_at=time.time(), saved_by=who)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return load()


def rollback_override() -> dict:
    p = _dir() / "config_override.json"
    if not p.exists():
        return load()
    cur = json.loads(p.read_text(encoding="utf-8"))
    hist = cur.get("history") or []
    if not hist:
        raise ValueError("BRAK_HISTORII")
    prev = hist.pop()
    cur.update(version=cur.get("version", 0) + 1, override=prev.get("override") or {}, history=hist, saved_at=time.time(), saved_by="rollback")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return load()


def profile(cfg: dict, inst: str, strategy: str) -> dict:
    ic = (cfg.get("instruments") or {}).get(inst)
    if not ic or strategy not in ic:
        raise KeyError(f"BRAK_PROFILU:{inst}/{strategy}")
    return {**ic[strategy], "_instrument": {k: v for k, v in ic.items() if k not in ("SCALPING", "HEDGING")}}
