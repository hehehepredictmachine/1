"""Single configuration source for SCALPING / HEDGING (backend AND panel): config/sh_strategies_v1.json (defaults, in the
repository) + data/sh/config_override.json (user changes from the panel, atomic write, every version kept in history).
The effective config has a hash; a trade plan freezes the hash and its parameters at creation - later changes never modify
an open position's plan."""
from __future__ import annotations

import copy
import hashlib
import json
import math
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

# 1.46: typed checks of the panel config (a string / negative / non-finite value used to be saved and then broke every SH cycle with a
# TypeError; the risk section was not validated at all). Ranges are sanity bounds of the units only - the defaults are unchanged.
_PCT_KEYS = ("risk_per_trade_pct", "risk_per_basket_pct", "daily_loss_limit_pct", "max_margin_use_pct")     # percent of equity: (0, 100]
_POS_KEYS = ("max_quote_age_s",)                                                                         # > 0
_NONNEG_KEYS = ("cooldown_minutes", "duplicate_window_minutes")                                          # >= 0
_PROFILE_POS = ("sl_min_usd", "sl_max_usd", "min_net_rr", "horizon_minutes", "setup_ttl_minutes", "position_max_minutes")
_PROFILE_NONNEG = ("sl_atr_m1_buffer", "reach_factor", "zone_atr_m5", "tp_model_min_prob")
_HEDGE_NUM = ("trigger_fraction_of_sl", "ratio", "max_ratio", "max_activations", "max_hedge_minutes", "unwind_recovery_atr_m5",
              "basket_loss_limit_x_risk", "reduce_fraction", "max_hedge_cost_fraction_of_sl")


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _nums(xs) -> bool:
    return isinstance(xs, list) and all(_num(x) for x in xs)


def _validate_risk(r) -> list[str]:
    if not isinstance(r, dict):
        return ["risk: sekcja musi być obiektem"]
    errs = []
    for k in _PCT_KEYS:
        if k in r and not (_num(r[k]) and 0 < r[k] <= 100):
            errs.append(f"risk.{k}: liczba w przedziale (0, 100] %")
    for k in _POS_KEYS:
        if k in r and not (_num(r[k]) and r[k] > 0):
            errs.append(f"risk.{k}: liczba > 0")
    for k in _NONNEG_KEYS:
        if k in r and not (_num(r[k]) and r[k] >= 0):
            errs.append(f"risk.{k}: liczba ≥ 0")
    if "max_open_positions" in r and not (_num(r["max_open_positions"]) and r["max_open_positions"] >= 1 and float(r["max_open_positions"]).is_integer()):
        errs.append("risk.max_open_positions: liczba całkowita ≥ 1")
    # per-instrument limits: null = no limit of that instrument; bar ages per TF are always numbers (compared on every cycle)
    for k, pos, nullable in (("max_exposure_lots", False, True), ("max_slippage_usd", False, True), ("max_bar_age_s", True, False)):
        if k not in r:
            continue
        d = r[k]
        if not isinstance(d, dict) or any(not ((v is None and nullable) or (_num(v) and (v > 0 if pos else v >= 0))) for v in d.values()):
            errs.append(f"risk.{k}: obiekt {{klucz: liczba {'> 0' if pos else '≥ 0'}}}")
    return errs


def validate(cfg: dict) -> list[str]:
    errs = []
    if "risk" in cfg:
        errs += _validate_risk(cfg["risk"])
    if "priority" in cfg and not (isinstance(cfg["priority"], list) and all(x in ("HEDGING", "SCALPING") for x in cfg["priority"])):
        errs.append("priority: lista z HEDGING / SCALPING")
    if "allow_parallel_same_symbol" in cfg and not isinstance(cfg["allow_parallel_same_symbol"], bool):
        errs.append("allow_parallel_same_symbol: true / false")
    insts = cfg.get("instruments") or {}
    if not isinstance(insts, dict):
        return errs + ["instruments: sekcja musi być obiektem {instrument: profil}"]
    for inst, ic in insts.items():
        if not isinstance(ic, dict):
            errs.append(f"{inst}: profil instrumentu musi być obiektem")
            continue
        for k in ("max_spread_usd", "slippage_usd"):
            if ic.get(k) is not None and not (_num(ic[k]) and ic[k] >= 0):
                errs.append(f"{inst}: {k} – liczba ≥ 0 albo brak")
        bad_types = False
        for strat in ("SCALPING", "HEDGING"):
            p = ic.get(strat)
            if p is None:
                continue
            if not isinstance(p, dict):
                errs.append(f"{inst}/{strat}: profil strategii musi być obiektem")
                bad_types = True
                continue
            for k in ("shares", "shares_fallback_two", "tp_usd", "tp3_choices", "scenario_levels_usd"):
                if p.get(k) is not None and not _nums(p[k]):
                    errs.append(f"{inst}/{strat}: {k} – lista liczb")
                    bad_types = True
            for k in _PROFILE_POS:
                if p.get(k) is not None and not (_num(p[k]) and p[k] > 0):
                    errs.append(f"{inst}/{strat}: {k} – liczba > 0")
                    bad_types = True
            for k in _PROFILE_NONNEG:
                if p.get(k) is not None and not (_num(p[k]) and p[k] >= 0):
                    errs.append(f"{inst}/{strat}: {k} – liczba ≥ 0")
                    bad_types = True
            h = p.get("hedge")
            if h is not None and not isinstance(h, dict):
                errs.append(f"{inst}/{strat}: hedge – obiekt")
                bad_types = True
            elif h:
                for k in _HEDGE_NUM:
                    if h.get(k) is not None and not (_num(h[k]) and h[k] >= 0):
                        errs.append(f"{inst}/{strat}: hedge.{k} – liczba ≥ 0")
                        bad_types = True
        if bad_types:
            continue                                        # 1.46: the range checks below assume valid types
        c = ic.get("commission_per_lot_side")
        if c is not None and (isinstance(c, bool) or not isinstance(c, (int, float)) or c < 0):
            errs.append(f"{inst}: prowizja na lot na stronę ≥ 0 albo brak (nieznana – nigdy nie zakładam 0)")
        for strat in ("SCALPING", "HEDGING"):
            p = ic.get(strat) or {}
            sh = p.get("shares") or []
            if sh and (abs(sum(sh) - 1.0) > 1e-6 or any(x <= 0 for x in sh)):
                errs.append(f"{inst}/{strat}: udziały muszą sumować się do 100 %")
            tp = p.get("tp_usd") or []
            if tp and any(b <= a for a, b in zip(tp, tp[1:])):
                errs.append(f"{inst}/{strat}: TP muszą rosnąć (TP1 < TP2 < TP3)")
            if tp and p.get("tp3_choices") and tp[-1] not in p["tp3_choices"]:
                errs.append(f"{inst}/{strat}: TP3 musi być jedną z wartości {p['tp3_choices']}")
            lv = p.get("scenario_levels_usd") or []
            if lv and (any(x <= 0 for x in lv) or any(b <= a for a, b in zip(lv, lv[1:]))):
                errs.append(f"{inst}/{strat}: poziomy scenariusza muszą być dodatnie i rosnące")
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
    try:
        errs = validate(eff)
    except (TypeError, AttributeError, KeyError) as exc:    # 1.46: a malformed panel value is a 400 (ValueError), never a 500
        raise ValueError(f"NIEPOPRAWNA_KONFIGURACJA: {type(exc).__name__}: {exc}"[:300]) from exc
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
