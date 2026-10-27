"""SCALPING scenario of a 2.5-10 USD PRICE MOVE (prompt MC §3/§7) on top of the existing SCALPING setup - not a second trading system.

The orders stay the SCALPING plan (TP1 2.5 / TP2 3 / TP3 5 USD, BE after the CONFIRMED TP2 = entry + costs, partials checked against
the broker's volume grid). Levels above TP3 up to 10 USD are SCENARIOS (analysis, no order) unless the user sets TP3 higher.
For every level the panel gets, separately: price move, volume of the leg, the account result from the terminal's tick value
(order_calc_profit-equivalent; missing tick value = no number), spread, commission (unknown = shown as unknown, never 0), slippage,
the Monte Carlo probability IN THE MODEL (conservative / optimistic for bars touching TP and SL, path error) and the calibrated value
only when the user's validation produced one. Models are listed with their own event and status - no probabilities of different
events are multiplied or averaged. A price move is not account profit."""
from __future__ import annotations

import time

from . import config as C
from . import models as SHM
from . import tpmodel as SHT

DEFAULT_LEVELS = {"XAUUSD": [2.5, 3.0, 5.0, 7.5, 10.0]}       # the user's XAUUSD levels; other instruments use their own tp_usd only


def _levels(inst: str, prof: dict) -> list[float]:
    lv = prof.get("scenario_levels_usd") or DEFAULT_LEVELS.get(inst) or list(prof.get("tp_usd") or [])
    return sorted({float(x) for x in lv} | {float(x) for x in prof.get("tp_usd") or []})


def min_split_volume(spec, shares: list[float], max_steps: int = 400) -> tuple[float | None, dict]:
    v = spec.volume_min
    for _ in range(max_steps):
        r = spec.split(round(v, 8), shares)
        if r.get("status") == "OK":
            return round(v, 8), r
        v += spec.volume_step
    return None, {"status": "INFEASIBLE", "reason": "brak wolumenu, który da każdej części min. wolumen brokera"}


def build(rt, strategy: str = "SCALPING", volume: float | None = None, now: float | None = None) -> dict:
    now = now or time.time()
    sh = rt.sh
    inst = sh.instrument()
    cfg = C.load()
    ic = (cfg.get("instruments") or {}).get(inst) or {}
    prof = ic.get(strategy) or {}
    out = {"strategy": strategy, "instrument": inst, "generated_at": now, "unit": "USD_PRICE_MOVE – ruch ceny instrumentu, nie zysk rachunku"}
    if not prof:
        return dict(out, status="NO_PROFILE", reason=f"brak profilu {strategy} dla {inst}")
    acc = rt.bridge.account_status() or {}
    try:
        spec = sh.spec(acc)
    except Exception as exc:  # noqa: BLE001 - symbol not known yet (terminal disconnected)
        return dict(out, status="NO_SYMBOL", reason=str(exc)[:200])
    try:
        spec.check_usd()
    except Exception as exc:  # noqa: BLE001 - levels are USD price moves; no silent conversion
        return dict(out, status="UNIT_ERROR", reason=str(exc)[:200])
    q = sh.quote(now)
    su = (sh.last_eval or {}).get(strategy) or {}
    horizon = int(prof.get("horizon_minutes") or 30)
    levels = _levels(inst, prof)
    shares = list(prof.get("shares") or [1.0])
    tp_index = {round(float(d), 6): i for i, d in enumerate(prof.get("tp_usd") or [])}
    out.update(levels_usd=levels, horizon_minutes=horizon, setup_status=su.get("status"), setup_reason=su.get("status_reason"),
               trigger=[x for x in su.get("checklist") or [] if x.get("id") == "trigger"], invalidation=su.get("invalidation"),
               score=(su.get("score") or {}).get("value") if isinstance(su.get("score"), dict) else su.get("score"), quote=q and {k: q[k] for k in ("bid", "ask", "spread")})
    side = su.get("side")
    out["side"] = side
    have_plan = su.get("status") in ("READY", "WAIT") and side in ("BUY", "SELL") and su.get("sl") is not None and su.get("entry_ref") is not None
    # ---------------- Monte Carlo (own thread of the MC service; model probability unless a calibrator is active)
    plans = []
    if have_plan:
        entry = float(su["entry_ref"])
        tps = [spec.target(entry, side, d)["price"] for d in levels]
        from ..montecarlo.engine import Plan
        plans = [Plan(side, entry, float(su["sl"]), tps, horizon)]
    mc = rt.montecarlo.compute(plans or None, horizon=horizon, levels=tuple(levels))
    out["montecarlo"] = {k: mc.get(k) for k in ("status", "reason", "variant", "variant_basis", "n_paths", "seed", "probability_kind", "calibrated",
                                                 "horizon_bars", "data", "warning", "compute_ms", "scenarios")}
    mc_levels = (mc.get("plans") or [{}])[0].get("levels") if plans and mc.get("status") == "OK" else None
    # ---------------- calculator (terminal tick value; costs shown separately; unknown stays unknown)
    comm = ic.get("commission_per_lot_side")
    slip = float(ic.get("slippage_usd") or 0.0)
    spread = q.get("spread") if q else None
    vol_total, split = (float(volume), spec.split(float(volume), shares)) if volume else min_split_volume(spec, shares)
    try:
        mpp_1lot = spec.money_per_price(1.0)
    except Exception:  # noqa: BLE001 - tick value unknown
        mpp_1lot = None
    out["volume"] = {"total": vol_total, "split": split, "volume_min": spec.volume_min, "volume_step": spec.volume_step,
                     "on_broker_grid": spec.volume_ok(vol_total) if vol_total else None,
                     "basis": "podany w panelu" if volume else "najmniejszy wolumen, przy którym każda część ma min. wolumen brokera",
                     "if_split_impossible": "plan przechodzi na 2 części (shares_fallback_two), a gdy i to niemożliwe – jedna pozycja bez częściowych "
                                            "zamknięć; nic nie jest po cichu przeskalowane"}
    legs = split.get("legs") if split.get("status") == "OK" else None
    rows = []
    scen = (mc.get("scenarios") or {}) if mc.get("status") == "OK" else {}
    for k, d in enumerate(levels):
        i = tp_index.get(round(d, 6))
        leg_vol = legs[i] if (legs and i is not None and i < len(legs)) else None
        tgt = spec.target(float(su["entry_ref"]), side, d) if have_plan else None
        dist = tgt["actual_distance"] if tgt else d
        row = {"level_usd": d, "role": f"TP{i + 1} – zlecenie częściowe" if i is not None else "scenariusz – bez zlecenia",
               "price": tgt and tgt["price"], "distance_actual": dist, "leg_volume": leg_vol,
               # BUY enters at Ask and exits at Bid (SELL the reverse): the spread is NOT a second deduction from the result at TP,
               # it is the extra move the exit side needs from the current quote
               "move_needed_from_quote": None if spread is None else round(dist + spread, 5)}
        vol_for_money = leg_vol if leg_vol else vol_total
        if mpp_1lot and vol_for_money:
            gross = dist * mpp_1lot * vol_for_money
            sl_cost = 2 * slip * mpp_1lot * vol_for_money
            cm_cost = 2 * comm * vol_for_money if comm is not None else None
            row.update(gross_account=round(gross, 2), volume_used=vol_for_money, currency=acc.get("currency"),
                       spread_value=None if spread is None else round(spread * mpp_1lot * vol_for_money, 2),
                       slippage_cost=round(sl_cost, 2), commission_cost=None if cm_cost is None else round(cm_cost, 2),
                       net_account=None if cm_cost is None else round(gross - sl_cost - cm_cost, 2),
                       net_note=None if cm_cost is not None else "prowizja nieznana – wyniku netto nie podaję (nie zakładam 0)")
        else:
            row.update(gross_account=None, net_account=None, net_note="brak wartości ticka z terminala – wyniku w walucie rachunku nie liczę")
        if mc_levels:
            m = mc_levels[k]
            row.update(p_tp_before_sl_conservative=m["p_tp_before_sl_conservative"], p_tp_before_sl_optimistic=m["p_tp_before_sl_optimistic"],
                       p_ambiguous=m["p_ambiguous_same_bar"], p_reach_within_h=m["p_tp_within_h"], mc_error_95=m["mc_error_95"],
                       p_calibrated=m.get("p_calibrated"))
        elif scen.get("p_up_reach") and k < len(scen["p_up_reach"]):
            row.update(p_up_reach=scen["p_up_reach"][k], p_down_reach=scen["p_down_reach"][k])
        rows.append(row)
    out["levels"] = rows
    be_off = (su.get("be") or {}).get("offset_price")
    out["break_even"] = {"after": prof.get("be_after", "TP2"), "rule": prof.get("be_rule"), "offset_price": be_off,
                         "price": (round(float(su["entry_ref"]) + (be_off or 0) * (1 if side == "BUY" else -1), 5) if have_plan else None),
                         "note": "BE dopiero po POTWIERDZONYM TP2 (wykonanie częściowego zamknięcia); koszty doliczone, gdy znane"}
    out["costs"] = {"spread_price": spread, "commission_per_lot_side": comm, "commission_known": comm is not None, "slippage_usd_per_side": slip,
                    "spread_rule": "wejście BUY po Ask, wyjście po Bid (SELL odwrotnie) – spread jest w cenach, nie odejmuję go drugi raz od wyniku przy TP",
                    "note": "konto Zero nie dowodzi zerowych kosztów – nieznana prowizja jest pokazywana jako nieznana"}
    # ---------------- models: each with its OWN event, never combined into one number
    board = []
    tp = SHT.status(inst, strategy) or {}
    board.append({"model": "sh_tp_model", "event": f"TP2 przed SL w {horizon} min ({strategy})", "status": tp.get("status"), "reason": tp.get("reason"),
                  "value": (su.get("probability") or {}).get("value"), "kind": (su.get("probability") or {}).get("status"),
                  "use": "bramka tylko gdy READY (skalibrowany na Twoich danych)"})
    board.append({"model": "montecarlo", "event": f"TP przed SL w {horizon} min (każdy poziom)", "status": mc.get("status"),
                  "value": None, "kind": "SKALIBROWANE" if mc.get("calibrated") else "W_MODELU (nieskalibrowane)",
                  "use": "ocena – nie blokuje zleceń"})
    try:
        for r in SHM.matrix(rt, inst)["rows"]:
            if r["id"] == "sh_tp_model":
                continue
            part = r.get(strategy) or {}
            board.append({"model": r["id"], "event": r.get("output"), "role": part.get("role"), "status": r.get("status"), "reason": r.get("reason"),
                          "value": None, "kind": None, "use": part.get("use") or "NONE",
                          "used": part.get("use") not in (None, "NONE", "GATE_UNAVAILABLE")})
    except Exception as exc:  # noqa: BLE001 - one broken probe must not hide the scenario
        board.append({"model": "matrix", "status": "ERROR", "reason": str(exc)[:120], "use": "NONE", "used": False})
    out["models"] = board
    out["combined_probability"] = {"value": None, "status": "N/A",
                                   "reason": "brak zwalidowanego modelu łączącego – procentów różnych zdarzeń nie łączę ani nie uśredniam"}
    # ---------------- order: the scenario never places anything; this is what the SCALPING cycle decided and why
    st = sh.public() if hasattr(sh, "public") else {}
    risk = su.get("risk") or {}
    coord = su.get("coordination") or {}
    why = None
    if not su:
        why = "silnik SCALPING nie ocenił jeszcze zamkniętej świecy M1 (start, brak danych MT5 albo zegar serwera niezmierzony)"
    elif su.get("status") != "READY":
        why = su.get("status_reason") or f"setup {su.get('status')} – nie READY"
    elif coord and coord.get("decision") != "PROCEED":
        why = "koordynator: " + str(coord.get("reason"))
    elif risk.get("status") not in (None, "PASS"):
        why = "ryzyko: " + "; ".join(risk.get("reasons") or [])
    elif su.get("entry_block"):
        why = "nowe wejścia zablokowane: " + ", ".join(su["entry_block"])
    elif st.get("mode") == "SIGNALS":
        why = "tryb SIGNALS – tylko sygnał, bez zlecenia (wybór użytkownika)"
    out["order"] = {"exec_mode": st.get("mode"), "coordination": coord.get("decision"), "risk_status": risk.get("status"),
                    "volume": risk.get("volume"), "legs": risk.get("legs"), "why_no_order": why,
                    "note": "ocena scenariusza nie składa zleceń – zlecenie składa wyłącznie cykl SCALPING (tryb, STOP, limity, broker)"}
    out["status"] = "PLAN" if have_plan else "NO_SETUP"
    if not have_plan:
        out["no_plan_reason"] = su.get("status_reason") or (f"setup {su['status']}" if su.get("status") else "brak oceny setupu")
    return out
