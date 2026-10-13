"""Scenario list and "Szczegóły setupu" (MQ-SETUP-DETAILS-1.0.0) - computed on request from the engine's live state.

Terms:
  strategy type   an entry of the strategy registry (S01..S12) - a method
  scenario        a concrete detection by that strategy (tracker row): stable setup_id, symbol, direction, timeframe,
                  first_seen_at - it lives through WATCH/EARLY/CONFIRMED and ends INVALIDATED/EXPIRED/MISSED_ENTRY

The direction of a scenario (BUY/SELL = what is being CONSIDERED) is separate from the entry availability (DOSTĘPNE /
ZABLOKOWANE): only the engine's selected, confirmed scenario that passes every gate is available. Sizing uses the same
risk engine (and the same per-account leverage/exposure limit) as the engine's decision. Nothing here can create a
signal or send an order.
"""
from __future__ import annotations

from datetime import datetime

from .. import stats as stats_mod
from ..strategies import registry
from ..timeutil import parse_iso, utcnow
from . import checklist as checklist_mod
from . import signal_view
from .active import levels_for

SCHEMA = "MQ-SETUP-DETAILS-1.0.0"
SIDE = {"LONG": "BUY", "SHORT": "SELL"}
SCEN_PL = {"OCZEKIWANIE": "OCZEKIWANIE", "WARUNKI_SPELNIONE": "WARUNKI SPEŁNIONE", "UNIEWAZNIONY": "UNIEWAŻNIONY", "BRAK_DANYCH": "BRAK DANYCH"}
TERMINAL_PL = {"INVALIDATED": "unieważniony (poziom unieważnienia)", "EXPIRED": "wygasł (brak wyzwalacza w czasie)", "MISSED_ENTRY": "wejście pominięte",
               "CANCELLED": "anulowany", "ENTERED": "wykorzystany (wejście)"}
# fact -> (min param, max param) of the strategy that bounds it (threshold shown next to the measured value)
FACT_LIMITS = {"er": ("min_er", "max_er"), "depth_atr": ("min_depth_atr", "max_depth_atr"), "width_atr": ("min_width_atr", None),
               "box_height_atr": (None, "max_box_atr"), "range_height_atr": ("min_h_atr", "max_h_atr"), "bar_range_atr": (None, "max_bar_atr"),
               "z_sgn": (None, "entry_z"), "adx": ("adx_threshold", None), "ema50_slope_atr": ("min_slope", None)}
RISK_PL = {"SPREAD_LIMIT": "spread powyżej limitu", "STOPS_LEVEL_VIOLATION": "SL/TP bliżej niż stops level brokera",
           "MIN_LOT_EXCEEDS_RISK_BUDGET": "minimalny lot przekracza budżet ryzyka", "MIN_LOT_EXCEEDS_FREE_MARGIN": "brak wolnego marginu na minimalny lot",
           "MIN_LOT_EXCEEDS_EXPOSURE_LIMIT": "minimalny lot przekracza limit ekspozycji (dźwigni)", "EXPOSURE_LIMIT_ALREADY_USED": "limit ekspozycji wykorzystany",
           "EXPOSURE_NOT_COMPUTABLE": "nie można policzyć ekspozycji (kalkulator brokera)", "EQUITY_NOT_POSITIVE": "equity ≤ 0",
           "SIZE_BELOW_BROKER_MIN_LOT": "wolumen poniżej minimalnego lota", "NO_RISK_BUDGET_AVAILABLE": "brak budżetu ryzyka",
           "RISK_LIMITS_NOT_CONFIGURED": "limity ryzyka nie są ustawione", "DAILY_STOP": "dzienny limit straty", "MAX_OPEN_POSITIONS": "limit otwartych pozycji",
           "QUOTE_OR_SYMBOL_OR_ACCOUNT_UNAVAILABLE": "brak notowań / danych symbolu / rachunku (MT5)", "LEVELS_UNAVAILABLE": "brak poziomów SL/TP",
           "COST_MODEL_UNKNOWN_COMMISSION": "nieznana prowizja (ustaw w Koszty)", "SLIPPAGE_STRESS_NOT_CONFIGURED": "nieustawiony stres poślizgu",
           "LIVE_PRICE_OUTSIDE_PLAN_GEOMETRY": "cena poza geometrią planu", "BROKER_MARGIN_CALC_UNAVAILABLE": "brak kalkulacji marginu brokera",
           "OPEN_POSITION_WITHOUT_SL_RISK_UNBOUNDED": "otwarta pozycja bez SL", "PENDING_ORDER_WITHOUT_SL_RISK_UNBOUNDED": "zlecenie oczekujące bez SL",
           "NETTING_ACCOUNT_EXISTING_POSITION_ON_SYMBOL": "rachunek netting z pozycją na symbolu", "DRAWDOWN_BREACH": "przekroczone obsunięcie",
           "COOLDOWN_AFTER_LOSS": "przerwa po stracie", "SYMBOL_TRADE_MODE_NOT_FULL": "symbol nie pozwala na pełny handel"}


def scenario_status(row: dict, data_ok: bool) -> str:
    if row["status"] != "ACTIVE":
        return "UNIEWAZNIONY"
    if row.get("stale") or not data_ok:
        return "BRAK_DANYCH"
    return "WARUNKI_SPELNIONE" if row["stage"] == "CONFIRMED" else "OCZEKIWANIE"


def _data_ok(eng) -> bool:
    d = eng.current_decision() or {}
    nodes = {n["node"]: n for n in d.get("decision_tree") or []}
    return bool(d) and nodes.get("DATA", {}).get("status") != "FAIL"


def scenarios(eng, *, include_terminal: bool = True, limit: int = 60) -> dict:
    act = eng.active
    sel = (act.selector.selected or {}).get("setup_id")
    data_ok = _data_ok(eng)
    rows = act.tracker.recent(limit, include_terminal=include_terminal)
    out = []
    for r in rows:
        if not r or (r.get("account_key") or None) != (eng.bridge.account_key or None):
            continue
        rec = r["record"]
        out.append({"setup_id": r["setup_id"], "strategy_id": rec["strategy_id"], "strategy_name": rec.get("strategy_name"), "symbol": r.get("symbol"),
                    "direction": SIDE.get(rec["direction"]), "timeframe": rec["timeframe"], "created_at": r["first_seen_at"], "updated_at": r["updated_at"],
                    "stage": r["stage"], "status": r["status"], "scenario_status": scenario_status(r, data_ok), "setup_score": rec.get("setup_score"),
                    "engine_selected": r["setup_id"] == sel, "terminal_reason": r.get("terminal_reason")})
    return {"schema": SCHEMA, "items": out, "strategies": [{"strategy_id": d["strategy_id"], "name": d["name"]} for d in registry.describe()],
            "engine_selected": sel, "setup_view": eng.prefs.get("setup_view") if eng.prefs is not None else None}


def _params(eng, sid: str) -> dict:
    base = dict(registry.STRATEGIES[sid].params) if sid in registry.STRATEGIES else {}
    base.update((eng.cfg_store.get().active.params or {}).get(sid) or {})
    return base


def _threshold(fact: str, params: dict) -> str | None:
    lo_k, hi_k = FACT_LIMITS.get(fact, (None, None))
    lo, hi = params.get(lo_k) if lo_k else None, params.get(hi_k) if hi_k else None
    if lo is not None and hi is not None:
        return f"{lo} – {hi}"
    if lo is not None:
        return f"≥ {lo}"
    if hi is not None:
        return f"≤ {hi}"
    return None


def _age(iso_s: str | None, now: datetime) -> int | None:
    t = parse_iso(iso_s) if iso_s else None
    return None if t is None else int((now - t).total_seconds())


def details(eng, setup_id: str) -> dict | None:
    act = eng.active
    row = act.tracker.get(setup_id)
    if not row:
        return None
    rec = row["record"]
    sid = rec["strategy_id"]
    strat = registry.STRATEGIES.get(sid)
    cfg = eng.cfg_store.get()
    now = utcnow()
    d = eng.current_decision() or {}
    nodes = {n["node"]: n for n in d.get("decision_tree") or []}
    data_ok = _data_ok(eng)
    scen = scenario_status(row, data_ok)
    side = SIDE.get(rec["direction"])
    params = _params(eng, sid)
    ep = rec.get("entry_plan") or {}
    levels = levels_for(rec)
    quote = eng.bridge.quote_status()
    live = row["stage"] == "CONFIRMED" and row["status"] == "ACTIVE"
    hypo = ep.get("trigger_level") or ep.get("reference_price")
    risk = eng._risk(rec["direction"], levels, quote, live, hypo) if row["status"] == "ACTIVE" else {"risk_gate": "NOT_EVALUATED",
                                                                                                    "reason_codes": ["SCENARIO_ENDED"]}
    selected = (act.selector.selected or {}).get("setup_id") == setup_id
    # ---- checklist: name, required threshold, current value, status, reason
    pseudo = {"decision_tree": [n for k, n in nodes.items() if k in ("DATA", "MARKET")] +
              [{"node": "RISK", "status": "PASS" if risk.get("risk_gate") in ("PASS", "PREVIEW") else ("PENDING" if risk.get("risk_gate") == "NOT_EVALUATED" else "FAIL"),
                "reason_codes": risk.get("reason_codes") or []}]}
    cl = checklist_mod.build(pseudo, row)
    rows: list[dict] = []
    if cl.get("status") == "SCENARIO":
        rows.append({"name": "Warunki konieczne strategii", "threshold": "struktura wymagana przez " + sid, "value": cl["met"][0]["reading"] if cl["met"] else "—",
                     "status": "SPEŁNIONY", "reason": None})
    own = (rec.get("facts") or {}).get("checklist")
    if isinstance(own, list) and own:               # families with their own exact checklist (S12): requirement, reading, TF, time, reason
        rows += [{"name": r["name"], "threshold": r.get("threshold") or "—", "value": r.get("value") or "—", "status": r["status"],
                  "reason": r.get("reason"), "tf": r.get("tf"), "at": r.get("at")} for r in own]
    for k, v in (rec.get("facts") or {}).items():
        if own or k in ("core", "touch_bar", "confirm_bar", "rr"):
            continue
        rows.append({"name": checklist_mod.FACT_PL.get(k, k), "threshold": _threshold(k, params) or "—", "value": "BRAK DANYCH" if v is None else checklist_mod._fmt(v),
                     "status": "BRAK DANYCH" if v is None else "ODCZYT", "reason": None if v is not None else "brak danych do odczytu"})
    for m in cl.get("missing") or []:
        if m["id"].startswith(("FACT_", "GATE_", "SCORE_BELOW")) or m["id"] == "TRIGGER":
            continue                                   # score and the closed-candle trigger have their own rows below
        rows.append({"name": m["label"], "threshold": m.get("required") or "—", "value": "nie spełniono", "status": "NIESPEŁNIONY",
                     "reason": m.get("required")})
    th = cfg.active.thresholds
    sc = rec.get("setup_score")
    rows.append({"name": "Wynik ACTIVE (heurystyka 0–100, nie prawdopodobieństwo)", "threshold": f"≥ {th.confirmed:g} dla potwierdzenia (≥ {th.early:g} wczesny)",
                 "value": "BRAK DANYCH" if sc is None else f"{sc}", "status": "BRAK DANYCH" if sc is None else ("SPEŁNIONY" if sc >= th.confirmed else "NIESPEŁNIONY"),
                 "reason": None if sc is None or sc >= th.confirmed else "wynik poniżej progu potwierdzenia"})
    tf = rec["timeframe"]
    rows.append({"name": f"Wyzwalacz na ZAMKNIĘTEJ świecy {tf}", "threshold": ep.get("trigger") or "wyzwalacz strategii",
                 "value": "spełniony" if live else ("świeca w trakcie / brak wyzwalacza" if row["status"] == "ACTIVE" else "—"),
                 "status": "SPEŁNIONY" if live else ("NIESPEŁNIONY" if row["status"] == "ACTIVE" else "—"),
                 "reason": None if live else "warunek potwierdzany dopiero po zamknięciu świecy"})
    dn = nodes.get("DATA") or {}
    rows.append({"name": "Dane MT5 (jakość)", "threshold": "GOOD lub DEGRADED, bez błędów TF", "value": d.get("data_quality") or "BRAK DANYCH",
                 "status": "SPEŁNIONY" if data_ok else "BRAK DANYCH", "reason": None if data_ok else ", ".join((dn.get("reason_codes") or [])[:4]) or "brak decyzji silnika"})
    rows.append({"name": "Rynek", "threshold": "otwarty, brak blokady makro", "value": d.get("market_state") or "BRAK DANYCH",
                 "status": "SPEŁNIONY" if (nodes.get("MARKET") or {}).get("status") == "PASS" else ("BRAK DANYCH" if not d else "NIESPEŁNIONY"),
                 "reason": None if (nodes.get("MARKET") or {}).get("status") == "PASS" else ", ".join(((nodes.get("MARKET") or {}).get("reason_codes") or [])[:3]) or None})
    if risk.get("rr_net") is not None:
        rows.append({"name": "RR po kosztach", "threshold": f"≥ {cfg.risk.rr_block_below:g} (pełne ryzyko od {cfg.risk.rr_pass_from:g})", "value": f"{risk['rr_net']}",
                     "status": "SPEŁNIONY" if risk["rr_net"] >= cfg.risk.rr_block_below else "NIESPEŁNIONY",
                     "reason": None if risk["rr_net"] >= cfg.risk.rr_block_below else "RR po kosztach poniżej progu"})
    if risk.get("spread_points") is not None or cfg.risk.max_spread_points:
        sp = risk.get("spread_points")
        ok = sp is not None and (cfg.risk.max_spread_points is None or sp <= cfg.risk.max_spread_points)
        rows.append({"name": "Spread", "threshold": f"≤ {cfg.risk.max_spread_points:g} pkt" if cfg.risk.max_spread_points else "brak limitu",
                     "value": "BRAK DANYCH" if sp is None else f"{sp} pkt", "status": "SPEŁNIONY" if ok else ("BRAK DANYCH" if sp is None else "NIESPEŁNIONY"),
                     "reason": None if ok else "spread powyżej limitu"})
    lots = risk.get("lots")
    rows.append({"name": "Wolumen (wszystkie limity)", "threshold": f"≥ {risk.get('volume_min', '—')} lot (krok {risk.get('volume_step', '—')})",
                 "value": "BRAK DANYCH" if lots is None else f"{lots} lot", "status": "SPEŁNIONY" if lots else ("BRAK DANYCH" if lots is None else "NIESPEŁNIONY"),
                 "reason": None if lots else ", ".join(RISK_PL.get(c, c) for c in (risk.get("reason_codes") or [])[:3]) or None})
    # ---- entry availability (separate from the scenario direction)
    why: list[str] = []
    if scen != "WARUNKI_SPELNIONE":
        why.append({"OCZEKIWANIE": "warunki scenariusza jeszcze niespełnione", "UNIEWAZNIONY": "scenariusz zakończony", "BRAK_DANYCH": "brak aktualnych danych"}[scen])
    if not selected:
        why.append("to nie jest setup wybrany przez silnik (" + ("tryb AUTO wybrał inny" if (act.prefs and act.prefs.get("setup_view")["mode"] != "SELECTED") else "wybrano inną strategię") + ")")
    if risk.get("risk_gate") not in ("PASS", "PREVIEW"):
        why += [RISK_PL.get(c, c) for c in (risk.get("reason_codes") or [])[:6]] or ["ryzyko: " + str(risk.get("risk_gate"))]
    elif risk.get("risk_gate") == "PREVIEW":
        why += [RISK_PL.get(c, c) for c in (risk.get("reason_codes") or [])[:4]]   # hypothetical sizing: only real problems
    toggle = cfg.active.strategies.get(sid)
    trade_ok = (toggle.trade if toggle else sid not in registry.DEFAULT_NO_TRADE)
    if not trade_ok:
        why.append(f"{sid} ma wyłączone „Dopuść do handlu” (tylko skanowanie)")
    if selected and d.get("decision") not in ("BUY", "SELL") and scen == "WARUNKI_SPELNIONE":
        why += [c for c in (d.get("reason_codes") or [])[:4]]
    entry = {"status": "DOSTĘPNE" if not why else "ZABLOKOWANE", "reasons": sorted(set(why), key=why.index),
             "execution_mode": eng.modes.mode, "note": "DOSTĘPNE oznacza zgodę reguł bota; wysłanie zlecenia zależy jeszcze od trybu wykonania."}
    # ---- timeframes used by this strategy: agreement / conflict
    tfs = list(dict.fromkeys([tf] + list(getattr(strat, "setup_tfs", ()) or []) + list(getattr(strat, "required_tfs", ()) or [])
                             + ([strat.context_tf] if getattr(strat, "context_tf", None) else []) + ["H1", "H4"]))
    try:
        ov = signal_view.tf_overview(eng._bars(), (eng.dq or {}).get("timeframes"), entry_tf=tf, plan_side=side,
                                     h8_filter=bool(params.get("h8_trend_filter")) if sid == "S11" else False)
    except Exception:
        ov = []
    want = {"BUY": "UP", "SELL": "DOWN"}.get(side or "")
    tf_rows = []
    for o in ov:
        if o["tf"] not in tfs:
            continue
        st = "BRAK DANYCH" if o["direction"] is None else ("ZGODNY" if o["direction"] == want else ("NEUTRALNY" if o["direction"] == "FLAT" else "KONFLIKT"))
        tf_rows.append({**o, "agreement": st})
    # ---- real historical results of this strategy (closed bot trades only)
    trades = eng.db.query("SELECT * FROM trades WHERE strategy_id=? AND source IN ('BOT','ADOPTED') AND status='CLOSED' ORDER BY closed_at", (sid,))
    hist = {"trades": len(trades), "period_from": trades[0].get("opened_at") or trades[0]["closed_at"] if trades else None,
            "period_to": trades[-1]["closed_at"] if trades else None, "stats": stats_mod._agg(trades) if trades else None,
            "note": "z rozliczonych transakcji bota (po kosztach)" if trades else "brak rozliczonych transakcji tej strategii – brak statystyk"}
    reg = (act.selector.state or {}).get("regime") or {}
    reason_txt = ", ".join(c for c in rec.get("reason_codes") or [] if c != "COUNTERTREND") or "struktura wykryta"
    inv = rec.get("invalidation_level")
    digits = int((eng.bridge.symbol_info or {}).get("digits") or 2)
    inv = None if inv is None else round(float(inv), digits)
    lev = risk.get("leverage") or {}
    if not lev and eng.prefs is not None:          # sizing stopped earlier - the three values are still shown
        e = eng.prefs.exposure_limit()
        lev = {"account_leverage": e.get("account_leverage"), "user_limit": e.get("user_limit"), "limit_mode": e.get("mode"),
               "exposure_limit": e.get("limit"), "note": e.get("note"), "position_notional": None, "effective_exposure_position": None,
               "effective_exposure_total": None, "effective_exposure_existing": None, "instrument_margin_leverage": None,
               "missing_reason": "brak kalkulacji wolumenu: " + (", ".join(RISK_PL.get(c, c) for c in (risk.get("reason_codes") or [])[:3]) or "—")}
    return {
        "schema": SCHEMA, "setup_id": setup_id, "strategy_id": sid, "strategy_name": rec.get("strategy_name"), "strategy_version": rec.get("strategy_version"),
        "symbol": row.get("symbol") or cfg.mt5.symbol, "direction": side, "direction_note": "kierunek rozważanego scenariusza – nie jest zgodą na wejście",
        "timeframe": tf, "timeframes_used": tfs, "stage": row["stage"], "scenario_status": scen, "scenario_status_pl": SCEN_PL[scen],
        "terminal_reason": TERMINAL_PL.get(row.get("terminal_reason"), row.get("terminal_reason")), "engine_selected": selected,
        "entry": entry,
        "context": {"regime": reg.get("state"), "regime_reason": reg.get("reason"), "countertrend": bool(rec.get("countertrend")),
                    "rationale": f"{sid} {rec.get('strategy_name') or ''}: {reason_txt}. Etap: {row['stage']}, wynik ACTIVE {rec.get('setup_score')}."},
        "checklist": rows,
        "levels": {"entry_zone": ep.get("zone"), "trigger": ep.get("trigger"), "trigger_level": ep.get("trigger_level"), "reference_price": ep.get("reference_price"),
                   "planned_entry": risk.get("entry"), "entry_basis": risk.get("entry_basis"), "stop_loss": rec.get("stop_loss"),
                   "targets": [t.get("price") for t in rec.get("targets") or []], "invalidation_level": inv,
                   "invalidation_rule": f"zamknięcie świecy {tf} za poziomem {inv}" if inv is not None else "—",
                   "expires_at": row.get("expires_at")},
        "rr": {"gross": risk.get("rr_gross"), "net": risk.get("rr_net"), "net_complete": risk.get("rr_complete"),
               "note": "netto = po prowizji w obie strony i stresie poślizgu; brutto = bez kosztów" if risk.get("rr_net") is not None else "brak kalkulacji (dane / poziomy)"},
        "sizing": {"risk_gate": risk.get("risk_gate"), "lots": lots, "binding_constraint": risk.get("binding_constraint"), "max_lots_by": risk.get("max_lots_by"),
                   "estimated_loss_at_sl": risk.get("modeled_loss"), "estimated_result_at_tp": risk.get("modeled_reward"), "loss_note": risk.get("loss_note"),
                   "margin_required": risk.get("margin_required"), "free_margin": risk.get("free_margin"), "free_margin_after": risk.get("free_margin_after"),
                   "pending_margin": risk.get("pending_margin"), "budget": risk.get("trade_budget"), "available_budget": risk.get("available_budget"),
                   "open_risk": risk.get("total_open_risk"), "currency": risk.get("currency"), "equity": risk.get("equity"),
                   "reason_codes": risk.get("reason_codes"), "reasons_pl": [RISK_PL.get(c, c) for c in risk.get("reason_codes") or []],
                   "settings_version": risk.get("settings_version"), "entry_basis": risk.get("entry_basis")},
        "leverage": lev,
        "score": {"value": rec.get("setup_score"), "meaning": "wynik ACTIVE 0–100: heurystyka zgodności z regułami strategii i reżimem; NIE jest prawdopodobieństwem wygranej (brak kalibracji)"},
        "history": hist, "timeframes": tf_rows,
        "times": {"created_at": row["first_seen_at"], "updated_at": row["updated_at"], "age_seconds": _age(row["first_seen_at"], now),
                  "since_update_seconds": _age(row["updated_at"], now), "data_source": "SYNTHETIC" if eng.bridge.synthetic else f"MT5:{(eng.bridge.account or {}).get('server')}"},
    }
