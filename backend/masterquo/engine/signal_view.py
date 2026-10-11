"""Presentation model of the current signal for the monitor (MQ-SIGNAL-VIEW-1.0.0).

One object built from ONE decision record (same snapshot_id / decision_id / signal_id as the Signal contract, the
checklist and the AI block), so the card, the checklist and the reason always describe the same decision.

Display states (the engine keeps LONG/SHORT internally):
  BUY          confirmed, current OPENING signal LONG that passed the strategy and the risk/decision rules
  SELL         same for SHORT (opening a short position - never a sale that closes a LONG)
  OCZEKIWANIE  a setup is being prepared - planned direction ("Plan: BUY/SELL") + what is missing
  BRAK_SYGNALU no qualified setup
  BLOKADA      the setup is confirmed but the entry is blocked - concrete reasons
  NIEAKTUALNY  expired / invalidated - must not be acted on
  BRAK_DANYCH  the situation cannot be assessed from the available data
A trend direction or an AI idea alone never produces BUY/SELL. Prices come from the engine; missing values are None
with a short reason ("—" in the UI).
"""
from __future__ import annotations

from ..strategies import ema_pullback_core as epc
from ..timeutil import TF_REGISTRY, TIMEFRAMES

VIEW_SCHEMA = "MQ-SIGNAL-VIEW-1.0.0"
SIDE = {"LONG": "BUY", "SHORT": "SELL"}
ROLE_PL = {"TRIGGER": "precyzja wejścia", "SETUP": "interwał setupu", "SETUP_CONTEXT": "setup S11 / kontekst", "LOCAL_CONTEXT": "kontekst lokalny",
           "HTF": "wyższy interwał – struktura", "TREND_REGIME_CONTEXT": "trend / reżim", "BACKGROUND": "tło dzienne"}
GATE_DESC = {"DATA": ("Dane z MT5", "świeże notowania i kompletne, zamknięte świece"),
             "MARKET": ("Rynek otwarty", "sesja otwarta, brak blokującego okna makro"),
             "RISK": ("Ryzyko i koszty", "SL, wolumen, spread i koszty mieszczą się w limitach ryzyka"),
             "AI": ("Agent AI", "ocena agenta Claude zgodnie z ustawioną polityką (VETO / WYMAGANA / DORADCZA)"),
             "ML": ("Model ML", "zgodnie z trybem ML (wyłączony / doradczy / wymagany)")}
STAGE_PL = {"WATCH": "obserwacja", "EARLY": "wczesny", "EARLY_SETUP": "wczesny", "QUALIFIED": "kwalifikacja", "ARMED": "uzbrojony",
            "TRIGGERED": "wyzwolony", "CONFIRMED": "potwierdzony"}


def _checklist(cl: dict | None) -> list[dict]:
    """Short list of the conditions the selected strategy really uses (+ the decision gates). The execution-mode gate is
    not a confirmation condition (it decides whether the bot SENDS an order) and is shown separately on the card."""
    cl = cl or {}
    items: list[dict] = []
    if cl.get("status") == "SCENARIO":
        for m in cl.get("met") or []:
            if m["id"] == "STRATEGY_RULE":
                items.append({"id": m["id"], "label": "Warunki konieczne strategii", "desc": m.get("reading") or "struktura wykryta", "status": "MET"})
        for m in cl.get("missing") or []:
            if m["id"].startswith(("GATE_", "FACT_")):
                continue
            items.append({"id": m["id"], "label": m["label"], "desc": m.get("required") or "", "status": m.get("status", "MISSING")})
        trg = cl.get("trigger") or {}
        if trg.get("met"):
            items.append({"id": "TRIGGER", "label": "Wyzwalacz wejścia", "desc": (trg.get("description") or "wyzwalacz strategii") + " – spełniony na zamkniętej świecy",
                          "status": "MET"})
        for m in cl.get("missing") or []:
            if m["id"].startswith("FACT_") and m.get("status") == "NO_DATA":
                items.append({"id": m["id"], "label": m["label"], "desc": "brak danych do odczytu", "status": "NO_DATA"})
    for g in cl.get("gates") or []:
        if g["id"] not in GATE_DESC:
            continue
        label, desc = GATE_DESC[g["id"]]
        st = {"MET": "MET", "PENDING": "PENDING"}.get(g["status"], "MISSING")
        if g["id"] == "DATA" and st != "MET":
            st = "NO_DATA"
        items.append({"id": "GATE_" + g["id"], "label": label, "desc": desc, "status": st, "reasons": (g.get("reasons") or [])[:4]})
    return items


def present(d: dict, sig: dict | None, *, symbol: str, digits: int, execution_mode: str | None = None) -> dict:
    cl = d.get("checklist") or {}
    nodes = {n["node"]: n for n in d.get("decision_tree") or []}
    data_fail = nodes.get("DATA", {}).get("status") == "FAIL"
    items = _checklist(cl)
    missing = [i["label"] for i in items if i["status"] in ("MISSING", "NO_DATA", "PENDING")]
    base = {"view_schema": VIEW_SCHEMA, "symbol": symbol, "digits": digits, "snapshot_id": d.get("snapshot_id"), "decision_id": d.get("decision_id"),
            "generated_at": d.get("as_of_utc"), "data_quality": d.get("data_quality"), "market_state": d.get("market_state"),
            "synthetic": bool(d.get("synthetic")), "checklist": items,
            "missing_summary": ("Do potwierdzenia brakuje: " + ", ".join(missing)) if missing else "Do potwierdzenia brakuje: nic – wszystkie warunki spełnione.",
            "execution_mode": execution_mode, "intent": "OTWARCIE"}
    if sig is None or sig.get("error"):
        state = "BRAK_DANYCH" if (data_fail or (sig or {}).get("error")) else "BRAK_SYGNALU"
        why = list(cl.get("why") or [])[:5]
        reason = ("Nie można ocenić sytuacji: " + ", ".join((nodes.get("DATA") or {}).get("reason_codes") or ["brak aktualnych danych"])) if state == "BRAK_DANYCH" \
            else "Żadna strategia nie ma teraz zakwalifikowanego setupu."
        return {**base, "state": state, "plan_side": None, "signal_id": None, "reason": reason, "why": why, "levels": None,
                "source": "STRATEGIA", "ai": None}
    side = SIDE.get(sig.get("side"))
    status = sig["status"]
    state = {"POTWIERDZONY": side or "BRAK_DANYCH", "OCZEKIWANIE": "OCZEKIWANIE", "ZABLOKOWANY": "BLOKADA", "UNIEWAŻNIONY": "NIEAKTUALNY",
             "WYGASŁY": "NIEAKTUALNY", "BRAK_DANYCH": "BRAK_DANYCH"}.get(status, "BRAK_DANYCH")
    confirmed = state in ("BUY", "SELL", "BLOKADA") and status in ("POTWIERDZONY", "ZABLOKOWANY")
    strat = f"{sig.get('strategy_id') or ''} {sig.get('strategy_name') or ''}".strip()
    tf = sig.get("entry_tf")
    q = sig.get("quote") or {}
    tps = [t["price"] for t in sig.get("targets") or [] if t.get("price") is not None]
    # ---- levels: reference price, planned entry and actual fill are separate values
    if confirmed and sig.get("entry_price") is not None:
        entry = {"value": sig["entry_price"], "kind": "PLANOWANE", "note": f"cena rynkowa ({'Ask' if side == 'BUY' else 'Bid'}) przy potwierdzeniu"}
    elif sig.get("trigger_level") is not None:
        entry = {"value": sig["trigger_level"], "kind": "POZIOM_WYZWALACZA", "note": "wejście dopiero po potwierdzeniu na zamkniętej świecy"}
    else:
        entry = {"value": None, "kind": None, "note": "brak poziomu – setup nie ma jeszcze wyzwalacza"}
    levels = {
        "entry": entry, "reference_price": sig.get("reference_price"),
        "fill": {"value": sig.get("fill_price"), "executed": sig.get("execution_state") == "WYKONANO",
                 "note": "wykonano" if sig.get("execution_state") == "WYKONANO" else {"BRAK": "nie wysłano zlecenia", "WYSŁANO": "zlecenie wysłane – czekam na potwierdzenie",
                                                                                    "ODRZUCONO": "zlecenie odrzucone"}.get(sig.get("execution_state"), "—")},
        "sl": {"value": sig.get("stop_loss"), "note": None if sig.get("stop_loss") is not None else "SL pojawi się po kwalifikacji setupu"},
        "tp": {"value": tps[0] if len(tps) == 1 else None, "values": tps, "note": None if tps else "brak celu",
               "rule": "TP liczony od ceny wejścia" if sig.get("tp_rule") == "RR_FROM_FILL" else None},
        "rr": {"net": sig.get("rr_net"), "gross": sig.get("rr_gross"), "note": None if sig.get("rr_net") is not None else
               ("RR po kosztach – po wyliczeniu ryzyka" if sig.get("rr_gross") is not None else "brak SL/TP")},
    }
    risk = {"money": sig.get("risk_money"), "pct": sig.get("risk_pct"), "volume": sig.get("volume"), "currency": sig.get("currency"),
            "note": None if sig.get("volume") is not None else "wolumen wyliczany dopiero dla potwierdzonego setupu"}
    blocks = [b for b in sig.get("block_reasons") or [] if b != "EXECUTION_NOT_PERMITTED_BY_MODE"]
    stage = STAGE_PL.get((d.get("setup") or {}).get("state"), (d.get("setup") or {}).get("state"))
    if state in ("BUY", "SELL"):
        reason = f"{strat} potwierdziła setup na zamkniętej świecy {tf}" + (f": {sig.get('trigger')}" if sig.get("trigger") else "") + "."
    elif state == "OCZEKIWANIE":
        n = len(missing)
        reason = f"Setup {strat} w przygotowaniu (etap: {stage}); " + (f"do potwierdzenia brakuje {n} warunk{'u' if n == 1 else 'ów'}." if n else "czekam na zamknięcie świecy.")
    elif state == "BLOKADA":
        reason = f"Setup {strat} jest potwierdzony, ale wejście jest zablokowane."
    elif state == "NIEAKTUALNY":
        reason = "Sygnał " + ("wygasł" if status == "WYGASŁY" else "został unieważniony") + " – nie jest podstawą do wejścia."
    else:
        reason = "Nie można ocenić sytuacji na podstawie dostępnych danych."
    ai = sig.get("ai") or {}
    inv = sig.get("invalidation") or {}
    return {**base, "state": state, "plan_side": side, "signal_id": sig.get("signal_id"), "setup_id": sig.get("setup_id"),
            "strategy": strat, "entry_tf": tf, "context_tfs": sig.get("context_tfs"), "source": sig.get("decision_source"),
            "data_source": sig.get("data_source"), "valid_until": sig.get("valid_until"), "signal_status": status,
            "execution_state": sig.get("execution_state"), "levels": levels, "risk": risk, "reason": reason,
            "trigger": sig.get("trigger") or (cl.get("trigger") or {}).get("description"), "invalidation": {"level": inv.get("level"), "rule": inv.get("rule") or "zamknięcie świecy za poziomem unieważnienia"},
            "block_reasons": blocks, "quote": {"bid": q.get("bid"), "ask": q.get("ask"), "age_seconds": q.get("age_seconds")},
            "quality": sig.get("quality"), "probability_win": sig.get("probability_win"),
            "ai": {"status": ai.get("status"), "verdict": ai.get("verdict"), "explanation": ai.get("explanation")},
            "execution_note": None if (d.get("execution_permission") == "ALLOWED" or state not in ("BUY", "SELL")) else
            f"Tryb wykonania {execution_mode or '—'}: bot nie składa zlecenia automatycznie – to sygnał do decyzji."}


def tf_overview(bars_by_tf: dict, dq_tf: dict | None, *, entry_tf: str | None, plan_side: str | None, h8_filter: bool) -> list[dict]:
    """Compact context of every timeframe: direction (EMA20 vs EMA50 on CLOSED bars), role, last closed bar, forming bar,
    data availability and a conflict with the planned direction (with its real impact on qualification)."""
    out = []
    for tf in TIMEFRAMES:
        bars = bars_by_tf.get(tf) or []
        closed = [b for b in bars if b.get("closed") and b.get("open_utc")]
        forming = bars[-1] if bars and not bars[-1].get("closed") else None
        q = ((dq_tf or {}).get(tf) or {}).get("status")
        direction = None
        if len(closed) >= 60:
            c = [b["c"] for b in closed[-400:]]
            e20, e50 = epc.pine_ema(c, 20), epc.pine_ema(c, 50)
            direction = "UP" if e20[-1] > e50[-1] else ("DOWN" if e20[-1] < e50[-1] else "FLAT")
        want = {"BUY": "UP", "SELL": "DOWN"}.get(plan_side or "")
        conflict = bool(want and direction in ("UP", "DOWN") and direction != want and tf in ("H1", "H4", "H8", "D1"))
        affects = conflict and tf == "H8" and h8_filter
        out.append({"tf": tf, "role": "interwał wejścia" if tf == entry_tf else ROLE_PL.get(TF_REGISTRY[tf]["role"], TF_REGISTRY[tf]["role"]),
                    "direction": direction, "data": "OK" if q in (None, "OK") and closed else ("BRAK_DANYCH" if not closed else q),
                    "last_closed_utc": closed[-1]["open_utc"] if closed else None, "forming": bool(forming),
                    "source": (closed[-1].get("source") if closed else None) or "native",
                    "conflict": conflict, "conflict_impact": ("blokuje potwierdzenie (filtr H8 S11)" if affects else "informacyjnie – nie zmienia kwalifikacji")
                    if conflict else None})
    return out
