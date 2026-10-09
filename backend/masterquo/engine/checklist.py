"""Entry-condition checklist for the monitor (12A) - built from the real strategy output, never from colours or guesses.

Four sections:
  met          what is already satisfied, with the measured readings (strategy facts, score, passed gates)
  missing      what is still required, with the exact event that has to happen ("brak danych" when data is missing)
  trigger      the entry trigger: level / zone, timeframe, closed-candle requirement, max distance, max wait
  invalidation the level / event / time that cancels the scenario
Direction words (BUY/SELL/LONG/SHORT) are deliberately not used: the checklist describes conditions, not signals.
"""
from __future__ import annotations

import re

from ..strategies.base import TF_SECONDS

VERSION = "MQ-CHECKLIST-1.0.0"

FACT_PL = {
    "impulse_high_px": "Ekstremum impulsu", "correction_low_px": "Ekstremum korekty", "depth_atr": "Głębokość korekty [ATR]",
    "er": "Efektywność trendu ER(20)", "ema50_slope_atr": "Nachylenie EMA50 [ATR/świecę]", "zone_touch": "Kontakt ze strefą wartości",
    "kama_px": "KAMA", "band_px": "Granica pasma KAMA", "upper_px": "Górna granica kanału", "lower_px": "Dolna granica kanału",
    "width_atr": "Szerokość kanału [ATR]", "bar_range_atr": "Zakres świecy wybicia [ATR]", "box_top_px": "Góra konsolidacji",
    "box_bottom_px": "Dół konsolidacji", "box_bars": "Długość konsolidacji [świece]", "box_height_atr": "Wysokość konsolidacji [ATR]",
    "range_high_px": "Szczyt zakresu sesji", "range_low_px": "Dołek zakresu sesji", "session": "Sesja", "range_start_utc": "Początek zakresu (UTC)",
    "level_px": "Poziom", "break_bar": "Świeca wybicia", "retest_bar": "Świeca retestu", "excursion_low_px": "Ekstremum wyjścia poza zakres",
    "range_top_px": "Góra zakresu", "range_bottom_px": "Dół zakresu", "range_height_atr": "Wysokość zakresu [ATR]", "excursion_bar": "Świeca wyjścia",
    "z_sgn": "Odchylenie z (w kierunku setupu)", "z_extreme3_sgn": "Ekstremum z (3 świece)", "mean_px": "Średnia", "stdev": "Odchylenie standardowe",
    "extreme_px": "Ekstremum ruchu", "choch_level_px": "Poziom zmiany struktury (CHoCH)", "impulse_atr": "Impuls [ATR]",
}

MISSING_PL = {
    "CORRECTION_TOO_SHALLOW": ("Korekta za płytka", "korekta musi osiągnąć minimalną głębokość w ATR (parametr min_depth_atr)"),
    "VALUE_ZONE_NOT_REACHED": ("Strefa wartości nieosiągnięta", "cena musi wejść w strefę EMA20/EMA50 ± 0,25 ATR"),
    "REACTION_BAR_CLOSE_ABOVE_PRIOR_HIGH": ("Brak świecy reakcji", "zamknięta świeca musi zamknąć się za ekstremum poprzedniej świecy, z korpusem w kierunku setupu"),
    "REACTION_BAR_CLOSE_BELOW_PRIOR_LOW": ("Brak świecy reakcji", "zamknięta świeca musi zamknąć się za ekstremum poprzedniej świecy, z korpusem w kierunku setupu"),
    "TREND_EFFICIENCY_WEAK": ("Słaba efektywność trendu", "ER(20) musi wzrosnąć co najmniej do min_er"),
    "ER_INSUFFICIENT": ("Za niska efektywność ruchu", "ER(20) musi przekroczyć próg strategii"),
    "CLOSE_ABOVE_KAMA_BAND": ("Brak zamknięcia poza pasmem KAMA", "zamknięta świeca musi zamknąć się poza pasmem KAMA"),
    "CLOSE_BELOW_KAMA_BAND": ("Brak zamknięcia poza pasmem KAMA", "zamknięta świeca musi zamknąć się poza pasmem KAMA"),
    "KAMA_NOT_RISING": ("KAMA bez nachylenia w kierunku setupu", "KAMA musi zacząć się nachylać w kierunku setupu"),
    "KAMA_NOT_FALLING": ("KAMA bez nachylenia w kierunku setupu", "KAMA musi zacząć się nachylać w kierunku setupu"),
    "NO_ROOM_TO_MEAN": ("Za mało miejsca do średniej", "odległość do średniej musi dać sensowny cel względem stopu"),
    "TRIGGER_BAR_NOT_CLOSED": ("Świeca wyzwalająca w trakcie", "wyzwalacz liczy się dopiero po ZAMKNIĘCIU świecy"),
    "EXTRA_CONFIRMATION_UNAVAILABLE": ("Dodatkowe potwierdzenie niedostępne", "brak danych do kategorii 'dodatkowe' (0 pkt) – nie blokuje, obniża wynik"),
    "CHANNEL_NOT_BROKEN": ("Kanał nie wybity", "zamknięta świeca musi zamknąć się poza granicą kanału Donchiana"),
    "COMPRESSION_NOT_RELEASED": ("Kompresja nie rozładowana", "zamknięta świeca musi wyjść poza konsolidację"),
    "EDGE_ZONE_NOT_REACHED": ("Krawędź zakresu nieosiągnięta", "cena musi dojść do strefy krawędzi zakresu"),
    "NO_RETEST_YET": ("Brak retestu", "cena musi wrócić do wybitego poziomu i go utrzymać"),
    "RETEST_BAR_NOT_CLOSED": ("Świeca retestu w trakcie", "wymagane zamknięcie świecy retestu po właściwej stronie poziomu"),
    "RANGE_NOT_BROKEN": ("Zakres sesji nie wybity", "zamknięta świeca musi zamknąć się poza zakresem sesji"),
    "RETURN_INSIDE_RANGE": ("Brak powrotu do zakresu", "zamknięta świeca musi wrócić do wnętrza zakresu po fałszywym wybiciu"),
    "STRUCTURE_CHANGE_NOT_CONFIRMED": ("Zmiana struktury niepotwierdzona", "zamknięcie świecy za poziomem CHoCH"),
    "Z_EXTREME_NOT_REACHED": ("Odchylenie z nieosiągnięte", "z-score musi dojść do progu ekstremum"),
    "NO_VALID_TARGET": ("Brak poprawnego celu", "struktura musi dać cel w sensownej odległości od stopu"),
}

GATE_PL = {"DATA": "Dane MT5 aktualne i kompletne", "MARKET": "Rynek otwarty, brak blokady makro", "RISK": "Ryzyko i koszty w limitach",
           "AI": "Agent Claude (wg polityki bramki)", "ML": "Model ML (wg trybu ML)", "PERMISSION": "Tryb wykonania dopuszcza zlecenia"}


def _fmt(v):
    if isinstance(v, bool):
        return "tak" if v else "nie"
    if isinstance(v, float):
        return f"{v:.2f}" if abs(v) < 1000 else f"{v:.2f}"
    return "brak danych" if v is None else str(v)


def _missing_item(code: str, rec: dict) -> dict:
    m = re.match(r"SCORE_BELOW_(CONFIRMED|EARLY)_(\d+(?:\.\d+)?)", code)
    if m:
        need = m.group(2)
        return {"id": code, "label": f"Wynik ACTIVE {rec.get('setup_score')} poniżej progu", "required": f"wynik ≥ {need} przy spełnionym wyzwalaczu",
                "status": "MISSING"}
    lab, req = MISSING_PL.get(code, (code.replace("_", " ").capitalize(), "warunek strategii musi zostać spełniony"))
    return {"id": code, "label": lab, "required": req, "status": "MISSING"}


def build(decision: dict | None, row: dict | None, *, no_setup_reasons: list[str] | None = None) -> dict:
    out = {"version": VERSION, "status": "NO_SCENARIO", "met": [], "missing": [], "trigger": None, "invalidation": None, "gates": []}
    nodes = {n["node"]: n for n in (decision or {}).get("decision_tree") or []}
    data_fail = nodes.get("DATA", {}).get("status") == "FAIL"
    for key in ("DATA", "MARKET", "RISK", "AI", "ML", "PERMISSION"):
        n = nodes.get(key)
        if not n:
            continue
        g = {"id": key, "label": GATE_PL[key], "status": "MET" if n["status"] == "PASS" else ("PENDING" if n["status"] in ("PENDING", "SKIPPED") else "MISSING"),
             "reasons": n.get("reason_codes") or n.get("unmet") or []}
        out["gates"].append(g)
    if row is None or row.get("status") != "ACTIVE":
        out["no_scenario_reason"] = "Brak aktualnego scenariusza – żadna strategia nie ma teraz aktywnego setupu."
        out["why"] = (no_setup_reasons or [])[:8]
        return out
    rec = row["record"]
    out["status"] = "SCENARIO"
    out.update(setup_id=row["setup_id"], setup_version=row["version"], strategy_id=rec["strategy_id"], strategy_name=rec.get("strategy_name"),
               timeframe=rec["timeframe"], stage=row["stage"], stale=bool(row.get("stale")))
    # ---- met: necessary rule of the strategy (the draft exists only when it holds) + measured facts + score + passed gates
    out["met"].append({"id": "STRATEGY_RULE", "label": f"Warunki konieczne {rec['strategy_id']} {rec.get('strategy_name') or ''}".strip(),
                       "reading": ", ".join(c for c in rec.get("reason_codes") or [] if c != "COUNTERTREND") or "struktura wykryta"})
    for k, v in (rec.get("facts") or {}).items():
        item = {"id": "FACT_" + k, "label": FACT_PL.get(k, k), "reading": _fmt(v)}
        (out["missing"] if v is None else out["met"]).append(item if v is not None else dict(item, required="brak danych", status="NO_DATA"))
    sc = rec.get("score") or {}
    pts = sc.get("points") or {}
    out["met"].append({"id": "SCORE", "label": "Wynik ACTIVE (heurystyka, nie prawdopodobieństwo)",
                       "reading": f"{rec.get('setup_score')} / 100 (struktura {pts.get('structure')}, formacja {pts.get('formation')}, momentum {pts.get('momentum')}, "
                                  f"wyzwalacz {pts.get('trigger')}, wyższe TF {pts.get('htf')})"})
    for g in out["gates"]:
        if g["status"] == "MET":
            out["met"].append({"id": "GATE_" + g["id"], "label": g["label"], "reading": "spełnione"})
    # ---- missing: strategy confirmations + gates
    for code in rec.get("missing_confirmations") or []:
        out["missing"].append(_missing_item(code, rec))
    ep = rec.get("entry_plan") or {}
    if row["stage"] != "CONFIRMED" and not any(m["id"].startswith(("REACTION", "TRIGGER", "CLOSE_")) for m in out["missing"]):
        out["missing"].append({"id": "TRIGGER", "label": "Wyzwalacz wejścia", "required": ep.get("trigger") or "wyzwalacz strategii na zamkniętej świecy",
                               "status": "MISSING"})
    for g in out["gates"]:
        if g["status"] != "MET":
            out["missing"].append({"id": "GATE_" + g["id"], "label": g["label"], "required": ", ".join(g["reasons"][:4]) or "warunek bramki",
                                   "status": "NO_DATA" if g["id"] == "DATA" and data_fail else ("PENDING" if g["status"] == "PENDING" else "MISSING"),
                                   "reasons": g["reasons"]})
    # ---- trigger
    tf = rec["timeframe"]
    out["trigger"] = {"description": ep.get("trigger"), "level": ep.get("trigger_level"), "zone": ep.get("zone"), "reference_price": ep.get("reference_price"),
                      "timeframe": tf, "closed_bar_required": True, "max_wait_bars": ep.get("max_wait_bars"), "max_distance_atr": ep.get("max_distance_atr"),
                      "send_when": ep.get("send_when"), "met": row["stage"] == "CONFIRMED"}
    # ---- invalidation
    out["invalidation"] = {"level": rec.get("invalidation_level"), "event": f"zamknięcie świecy {tf} za poziomem unieważnienia",
                           "time": row.get("expires_at"), "time_rule": f"wygasa po {rec.get('expires_bars')} świecach {tf} bez wyzwalacza"
                           if rec.get("expires_bars") else None, "stop_loss": rec.get("stop_loss"), "targets": [t.get("price") for t in rec.get("targets") or []],
                           "bar_seconds": TF_SECONDS.get(tf)}
    if data_fail:
        out["data_note"] = "brak danych – część odczytów może być nieaktualna"
    return out
