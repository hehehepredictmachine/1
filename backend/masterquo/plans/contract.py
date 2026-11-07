"""PMW-PLAN-1 - trade plan for the chart layers **Pepe Scalp Plan** (SCALPING) and **Pepe Hedge Plan** (HEDGING).

Sources (never recomputed here, never in the frontend): the SH setup evaluation (sh/setup.py: entry_ref, sl, tps from the active
strategy profile and the symbol spec - tick size / digits), the coordinator / risk result, the frozen plan row (sh_plans) and its
state machine (sh/lifecycle.Position, sh/hedge_fsm.Basket) with REAL fills.

Three things are kept apart: analytical readiness (setup READY), permission to execute (risk PASS + coordinator PROCEED + mode) and
an actual open position (plan bound to a fill). The planned ENTRY is labelled PLAN; after a fill the real fill price and ticket are
shown NEXT to it (the plan history is not replaced by an ideal fill). Targets count as reached only from execution data (leg DONE with
fill price, or PAPER fills) - never from a candle crossing a line.

States: WAIT (no levels yet, reason shown) / NO_TRADE (conditions failed, reason) / READY (levels valid, not executed) / ACTIVE (open
position) / EXPIRED (TTL passed without a position) / INVALIDATED (setup invalidated or levels inconsistent) / CLOSED (position closed).
"""
from __future__ import annotations

import hashlib
import json
import time

VERSION = "PMW-PLAN-1"
LAYERS = {"SCALPING": ("SCALP", "Pepe Scalp Plan"), "HEDGING": ("HEDGE", "Pepe Hedge Plan")}
STATES = ("WAIT", "NO_TRADE", "READY", "ACTIVE", "EXPIRED", "INVALIDATED", "CLOSED")
CLOSED_STATES = ("CLOSED", "ERROR_CLOSED", "REJECTED", "ENTRY_UNKNOWN")


def _lvl(name: str, price, kind: str, **kw) -> dict | None:
    if price is None:
        return None
    return {"name": name, "price": float(price), "kind": kind, **kw}


def levels_consistent(side: str, entry: float, sl: float, tps: list[float]) -> str | None:
    """None when BUY: SL < ENTRY < TP1 < TP2 < ... (SELL mirrored); otherwise the reason."""
    if side == "BUY":
        if not sl < entry:
            return "SL nie jest poniżej ENTRY dla BUY"
        seq = [entry] + tps
        if any(b <= a for a, b in zip(seq, seq[1:])):
            return "cele BUY nie rosną od ENTRY"
    elif side == "SELL":
        if not sl > entry:
            return "SL nie jest powyżej ENTRY dla SELL"
        seq = [entry] + tps
        if any(b >= a for a, b in zip(seq, seq[1:])):
            return "cele SELL nie maleją od ENTRY"
    else:
        return f"nieznany kierunek {side}"
    return None


def _entry_price(su: dict) -> float | None:
    e = su.get("entry_ref")
    if isinstance(e, dict):
        e = e.get("price")
    return float(e) if e is not None else None


def from_setup(su: dict, *, now: float | None = None, timeframe: str = "M1", account_margin_mode: str | None = None,
               plan_row: dict | None = None, position: dict | None = None, basket: dict | None = None, digits: int | None = None) -> dict:
    """One plan view. su = SH setup (last_eval or the frozen plan['setup'] merged with signal metadata)."""
    now = now if now is not None else time.time()
    strat = su.get("strategy")
    kind, layer = LAYERS.get(strat, ("SCALP", "Pepe Scalp Plan"))
    side = su.get("side")
    entry, sl = _entry_price(su), su.get("sl")
    tps = [t for t in (su.get("tps") or []) if t.get("price") is not None]
    out = {"contract": VERSION, "layer": layer, "plan_kind": kind, "instrument": su.get("instrument"), "symbol": su.get("symbol"),
           "strategy": strat, "strategy_version": su.get("setup_version"), "config_hash": su.get("config_hash"),
           "signal_id": su.get("signal_id"), "setup_id": su.get("signal_id"), "plan_id": (plan_row or {}).get("plan_id"),
           "ticket": (plan_row or {}).get("primary_ticket"), "side": side, "direction_label": side, "timeframe": timeframe,
           "signal_time": su.get("created_at"), "valid_until": su.get("valid_until"), "price_source": "MT5 Bid/Ask (BUY otwiera po Ask, zamyka po Bid)",
           "digits": digits, "levels": [], "execution": None, "hedge": None, "basket": None, "account_margin_mode": account_margin_mode}
    status = su.get("status")
    reason = su.get("status_reason")
    if entry is not None and sl is not None and side:
        out["levels"] = [x for x in [_lvl("ENTRY", entry, "PLAN", label=f"ENTRY (plan) {side}"), _lvl("SL", sl, "PLAN", label="STOP LOSS")] +
                         [_lvl(t["name"], t["price"], "PLAN", label=t["name"], share=t.get("share"), optional=t["name"] not in ("TP1", "TP2"))
                          for t in tps] if x]
        bad = levels_consistent(side, entry, float(sl), [float(t["price"]) for t in tps])
    else:
        bad = None
    # ---- state
    pr = plan_row or {}
    if pr and pr.get("state") not in (None,) and pr.get("primary_ticket") is not None or position:
        state = "CLOSED" if pr.get("state") in CLOSED_STATES or (position or {}).get("state") == "CLOSED" else "ACTIVE"
    elif pr and pr.get("state") in ("REJECTED", "ENTRY_UNKNOWN"):
        state, reason = "INVALIDATED", f"wejście {pr['state']}: {(pr.get('result') or {}).get('reason')}"
    elif bad:
        state, reason = "INVALIDATED", f"niespójne poziomy: {bad}"
    elif status == "READY":
        state = "EXPIRED" if (su.get("valid_until") and now > float(su["valid_until"])) else "READY"
        if state == "EXPIRED":
            reason = "minął czas ważności setupu (TTL) bez otwarcia pozycji"
    elif status in ("NO_TRADE", "BLOCKED", "DISABLED"):
        state = "NO_TRADE"
    elif status == "INVALIDATED":
        state = "INVALIDATED"
    else:
        state = "WAIT"
    if state in ("WAIT", "NO_TRADE") and not out["levels"]:
        reason = reason or "brak poziomów – warunki setupu niespełnione"
    out["state"], out["state_reason"] = state, reason
    out["readiness"] = {"analytical": status, "execution_permission": ((su.get("risk") or {}).get("status")),
                        "coordination": ((su.get("coordination") or {}).get("decision")), "position_open": state == "ACTIVE",
                        "entry_block": su.get("entry_block")}
    # ---- execution (real fills only)
    if position:
        legs = position.get("legs") or []
        out["execution"] = {"entry_fill": position.get("entry"), "ticket": pr.get("primary_ticket"), "volume": position.get("volume"),
                            "remaining": position.get("remaining"), "sl_current": position.get("sl"), "sl_plan": sl,
                            "sl_version": 1 + (1 if (position.get("sl") is not None and sl is not None and abs(float(position["sl"]) - float(sl)) > 1e-9) else 0),
                            "sl_change_reason": ("BE po " + str((su.get("be") or {}).get("after", "TP2")) if position.get("be_status") == "SET" else None),
                            "be_status": position.get("be_status"), "be_price": position.get("be_price"), "exec_mode": pr.get("exec_mode"),
                            "targets": [{"name": lg.get("name"), "price": lg.get("price"), "status": lg.get("status"), "fill_price": lg.get("fill_price"),
                                         "fill_volume": lg.get("fill_volume"), "reached": lg.get("status") == "DONE"} for lg in legs],
                            "source": "PAPER (jawny tryb symulacji)" if pr.get("exec_mode") == "PAPER" else "dane wykonania MT5"}
        if position.get("entry") is not None:
            out["levels"].append(_lvl("ENTRY_FILL", position["entry"], "FILL", label=f"FILL #{pr.get('primary_ticket')}"))
        if out["execution"]["sl_version"] > 1:
            out["levels"].append(_lvl("SL_CURRENT", position["sl"], "MANAGED", label=f"SL v{out['execution']['sl_version']}"))
    # ---- hedge (HEDGING only)
    if kind == "HEDGE":
        out["hedge"] = hedge_view(su, pr, basket, account_margin_mode, position)
        if out["hedge"].get("activation_level") is not None:
            out["levels"].append(_lvl("HEDGE_ACTIVATION", out["hedge"]["activation_level"], "HEDGE", label="HEDGE aktywacja"))
        leg = out["hedge"].get("leg") or {}
        if leg.get("entry") is not None:
            out["levels"].append(_lvl("HEDGE_ENTRY", leg["entry"], "HEDGE_FILL", label=f"HEDGE {leg.get('side')} {leg.get('volume')}"))
        out["basket"] = (basket or {}).get("basket")
    out["plan_key"] = "PV-" + hashlib.sha256(json.dumps([out["signal_id"], out["plan_id"], out["state"], out["levels"]], default=str)
                                             .encode()).hexdigest()[:12]
    return out


def hedge_view(su: dict, pr: dict, basket: dict | None, margin_mode: str | None, position: dict | None) -> dict:
    mm = (margin_mode or "").upper()
    if mm and "HEDG" not in mm:
        return {"available": False, "reason": f"konto {margin_mode}: brak hedgingu (NETTING) – noga przeciwna niedostępna, strategia nie jest "
                                               "cicho zamieniana w inną", "activation_level": None, "leg": None}
    prof = (pr.get("plan") or {}).get("profile") or {}
    h = prof.get("hedge") or {}
    entry = (position or {}).get("entry") or _entry_price(su)
    sl = (position or {}).get("sl_plan") or su.get("sl")
    act = None
    if entry is not None and sl is not None and h.get("trigger_fraction_of_sl") is not None:
        d = abs(float(entry) - float(sl)) * float(h["trigger_fraction_of_sl"])
        act = float(entry) - d if su.get("side") == "BUY" else float(entry) + d
    hb = (basket or {}).get("hedge") or {}
    leg = {"side": hb.get("side"), "volume": hb.get("volume"), "entry": hb.get("entry"), "status": hb.get("status"),
           "activations": hb.get("activations")} if hb.get("entry") is not None else None
    cond = None
    if prof:
        lim = ((pr.get("plan") or {}).get("risk") or {}).get("basket_loss_limit_money")
        cond = (f"wyjście koszykowe: strata netto koszyka ≥ {lim} (waluta rachunku) lub czas koszyka > {prof.get('position_max_minutes')} min; "
                "warunek w pieniądzu – nie jest rysowany jako jedna linia ceny") if lim else "wyjście koszykowe: limit czasu / SL pozycji głównej"
    return {"available": True, "activation_level": act if act is not None else None,
            "activation_rule": (f"niekorzystny ruch ≥ {h.get('trigger_fraction_of_sl')} × odległość SL" if h else None), "leg": leg,
            "leg_levels": [], "leg_levels_note": "strategia HEDGING nie definiuje osobnych TP/SL nogi zabezpieczającej – nie są dorysowywane",
            "basket_condition": cond, "note": "stop, cel i wyjście koszykowe nie gwarantują wykonania po wskazanej cenie"}


def chart_payload(plans: list[dict], *, symbol: str, account_key: str | None, primary: str | None = None) -> dict:
    """Only plans of one symbol + account; primary = newest ACTIVE, else newest READY, else newest."""
    plans = [p for p in plans if p.get("symbol") == symbol]
    order = sorted(plans, key=lambda p: (p.get("signal_time") or 0), reverse=True)
    pick = primary or next((p["plan_key"] for p in order if p["state"] == "ACTIVE"), None) or \
        next((p["plan_key"] for p in order if p["state"] == "READY"), None) or (order[0]["plan_key"] if order else None)
    return {"contract": VERSION, "symbol": symbol, "account_key": account_key, "primary": pick, "plans": order,
            "legend": {"SCALP": "Pepe Scalp Plan", "HEDGE": "Pepe Hedge Plan"},
            "note": "poziomy z planu strategii i danych wykonania; przełączanie warstw nie zmienia zleceń"}
