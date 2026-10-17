"""Scenario engine (MQ-LAB-SCN-1.0.0): data -> quality -> regime -> features/patterns -> models -> scenarios -> cost/risk ->
checklist. Asset-agnostic (XAUUSD and BTC use the same code with their own contract data). All scenarios are SHADOW: they never
reach the execution gateway.

Every scenario: stable setup_id, asset, side, TF, created_at, expires_at, version; conditions met / missing / conflicting, trigger,
invalidation, levels/zones; three SEPARATE numbers: checklist completeness (rules met / rules), model score (raw output) and the
calibrated probability of the defined event (TP before SL within H) - the latter only when a model artifact for this
asset/horizon exists. 8/10 rules met is never shown as 80 % confidence.
"""
from __future__ import annotations

import hashlib

from ..analytics.ta import TF_SEC
from .common import iso, ts

VERSION = "MQ-LAB-SCN-1.0.0"
TTL_BARS = 24


def sid(*parts) -> str:
    return "LSC-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:14]


def _cond(name: str, state: str, detail: str = "") -> dict:
    assert state in ("MET", "MISSING", "CONFLICT", "INFO")
    return {"name": name, "state": state, "detail": detail}


def _common(ctx: dict, side: str, conds: list[dict]) -> list[dict]:
    reg = (ctx.get("regime") or {}).get("state")
    if reg in ("TREND_UP", "TREND_DOWN"):
        against = (reg == "TREND_DOWN" and side == "LONG") or (reg == "TREND_UP" and side == "SHORT")
        conds.append(_cond("Reżim (M10) nie przeciwny", "CONFLICT" if against else "MET", reg))
    else:
        conds.append(_cond("Reżim (M10) nie przeciwny", "MET" if reg else "MISSING", reg or "rozgrzewka"))
    cost = ctx.get("cost") or {}
    if cost.get("spread_atr") is None:
        conds.append(_cond("Koszt: spread / ATR ≤ 0,15", "MISSING", "brak notowania lub ATR"))
    else:
        conds.append(_cond("Koszt: spread / ATR ≤ 0,15", "MET" if cost["spread_atr"] <= 0.15 else "CONFLICT", f"{cost['spread_atr']:.3f}"))
    fresh = ctx.get("fresh")
    conds.append(_cond("Dane świeże (wiek notowania)", "MET" if fresh else "CONFLICT", ctx.get("fresh_detail") or ""))
    return conds


def _finish(ctx: dict, kind: str, tf: str, side: str, anchor_t: str, conds: list[dict], trigger: str, invalidation: float | None,
            levels: list[dict], model: dict | None) -> dict:
    created = anchor_t
    invalidation = None if invalidation is None else round(float(invalidation), 5)
    expires = iso(ts(anchor_t) + TTL_BARS * TF_SEC[tf])
    rules = [c for c in conds if c["state"] != "INFO"]
    met = sum(1 for c in rules if c["state"] == "MET")
    conflict = [c["name"] for c in rules if c["state"] == "CONFLICT"]
    missing = [c["name"] for c in rules if c["state"] == "MISSING"]
    last_close = ctx["last_close"]
    invalid = invalidation is not None and ((side == "LONG" and last_close < invalidation) or (side == "SHORT" and last_close > invalidation))
    expired = ts(ctx["as_of"]) > ts(expires)
    status = "INVALIDATED" if invalid else "EXPIRED" if expired else ("ALL_CONDITIONS_MET_SHADOW" if not missing and not conflict else "WATCH")
    if status == "INVALIDATED":
        wait = f"unieważniony: zamknięcie za poziomem {invalidation}"
    elif status == "EXPIRED":
        wait = "wygasł (TTL)"
    elif conflict:
        wait = "konflikt: " + conflict[0]
    elif missing:
        wait = "czekam na: " + missing[0]
    elif status == "ALL_CONDITIONS_MET_SHADOW":
        wait = "warunki spełnione – tryb obserwacyjny (bez zlecenia)"
    else:
        wait = status
    m = None
    if model and model.get("status") == "ready" and model.get("side") == side:
        m = {k: model.get(k) for k in ("model_id", "family", "role", "horizon", "raw_score", "probability", "calibration_ece", "inference_id",
                                         "event", "data_source")}
    elif model:
        m = {"status": model.get("status"), "reason": model.get("reason") or ("model dotyczy strony " + str(model.get("side")))}
    return {"setup_id": sid(ctx["asset"], tf, kind, side, anchor_t), "version": VERSION, "asset": ctx["asset"], "broker_symbol": ctx.get("symbol"),
            "kind": kind, "side": side, "tf": tf, "created_at": created, "expires_at": expires, "status": status,
            "checklist": conds, "checklist_completeness": {"met": met, "total": len(rules), "score": round(met / len(rules), 3) if rules else None,
                                                            "note": "kompletność reguł – NIE prawdopodobieństwo"},
            "missing": missing, "conflicts": conflict, "waiting_for": wait, "trigger": trigger, "invalidation": invalidation,
            "levels": levels, "model": m, "decision_role": "shadow", "trace_id": ctx.get("trace_id")}


def build(ctx: dict, mods: dict, model: dict | None) -> list[dict]:
    out = []
    # 1. ICT sequence (M16 + M14) on M15
    ict = (mods.get("M15") or {}).get("ict") or {}
    if ict.get("stage") in ("SWEEP", "MSS", "FVG", "RETEST") and ict.get("sweep_at"):
        side = "LONG" if ict["side"] == "BUY" else "SHORT"
        st = ict["stage"]
        order = ["SWEEP", "MSS", "FVG", "RETEST"]
        k = order.index(st)
        conds = [_cond("Sweep puli płynności (M14)", "MET", f"{ict['pool']['kind']} {ict['pool']['price']}"),
                 _cond("MSS – zmiana struktury", "MET" if k >= 1 else "MISSING"),
                 _cond("Displacement ≥ 1,2 ATR", "MET" if ict.get("displacement") else ("MISSING" if k < 1 else "CONFLICT"),
                       str(ict.get("displacement_body_atr") or "")),
                 _cond("FVG w odcinku displacementu", "MET" if k >= 2 else "MISSING"),
                 _cond("Retest FVG (trigger)", "MET" if k >= 3 else "MISSING")]
        conds = _common(ctx, side, conds)
        fvg = ict.get("fvg")
        levels = [{"kind": "POOL", "price": ict["pool"]["price"]}] + ([{"kind": "FVG", "id": fvg["id"], "top": fvg["top"], "bottom": fvg["bottom"]}] if fvg else [])
        out.append(_finish(ctx, "ICT_SWEEP_MSS_FVG", "M15", side, ict["sweep_at"], conds, "retest FVG + zamknięcie w kierunku scenariusza",
                           ict["pool"]["price"], levels, model))
    # 2. Z-score hypotheses (M23) on M5
    z = (mods.get("M5") or {}).get("zscore") or {}
    for h, stt in (z.get("hypotheses_state") or {}).items():
        if stt not in ("LONG_CANDIDATE", "SHORT_CANDIDATE"):
            continue
        side = "LONG" if stt.startswith("LONG") else "SHORT"
        conds = [_cond(f"Hipoteza {h} ({z['hypotheses'][h]['name']})", "MET", z['hypotheses'][h]["rule"]),
                 _cond("Z-score policzony (odchylenie > próg)", "MET", f"z={z.get('z')}"),
                 _cond("Hipoteza zwalidowana na danych aktywa", "MISSING", "progi z materiałów = punkty startowe")]
        conds = _common(ctx, side, conds)
        out.append(_finish(ctx, f"ZSCORE_{h}", "M5", side, ctx["last_bar_open"]["M5"], conds, "zamknięcie świecy M5 spełniające regułę", None, [], model))
    # 3. Stochastic daily breakout (M25) on M15
    sd = (mods.get("M15") or {}).get("stoch_breakout") or {}
    if sd.get("state") in ("LONG_CANDIDATE", "SHORT_CANDIDATE"):
        side = "LONG" if sd["state"].startswith("LONG") else "SHORT"
        conds = [_cond("Wybicie poziomu poprzedniego dnia", "MET", f"PDH {sd['pdh']} / PDL {sd['pdl']}"),
                 _cond("Zmiana momentum %K/%D", "MET", f"K {sd['k']} D {sd['d']}"),
                 _cond("Hipoteza zwalidowana dla aktywa", "MISSING", sd.get("hypothesis", ""))]
        conds = _common(ctx, side, conds)
        inv = sd["pdh"] if side == "LONG" else sd["pdl"]
        out.append(_finish(ctx, "STOCH_DAILY_BREAKOUT", "M15", side, ctx["last_bar_open"]["M15"], conds, "zamknięcie M15 za poziomem dnia",
                           inv, [{"kind": "PDH", "price": sd["pdh"]}, {"kind": "PDL", "price": sd["pdl"]}], model))
    return out
