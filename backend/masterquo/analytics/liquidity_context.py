"""Liquidity context policy + knowledge (PMW-UPD-06 LS-08 / LS-09): a PURE rule function over the frozen session boxes and the
heatmap snapshot available at the decision time. OBSERVE only - it never creates a signal, never changes the scalp trigger, TP1
(M5 range MID), SL, sizing, costs or the execution mode. The same rules feed the panel ("Dlaczego bot tak odczytuje warstwy"), the
frozen engine context and the agent tool; the knowledge text below is loaded into the agent system prompt (versioned).
"""
from __future__ import annotations

from datetime import datetime

POLICY_VERSION = "PMW-LIQ-POLICY-1.0.0"
KNOWLEDGE_VERSION = "PMW-LIQ-KNOWLEDGE-1.0.0"
NEAR_ATR = 0.15

RULES = {
    "LQ-K01": "Szacowane poziomy likwidacji (model dostawcy), zaobserwowane likwidacje i pule płynności z OHLC to różne rodzaje danych.",
    "LQ-K02": "Jasność heatmapy to intensywność w skali źródła (provider_intensity) – nie szansa wygranej ani gwarantowany cel ceny.",
    "LQ-K03": "XAUT, XAUUSD- i różne kontrakty BTC mają odrębne ceny i źródła; przeniesienie poziomu wymaga zweryfikowanego adaptera.",
    "LQ-K04": "Brak lub starość danych heatmapy nie oznacza pustego rynku i nie pozwala dopisywać zer.",
    "LQ-K05": "Rozwijający się boks (DEVELOPING) pokazuje dotychczasowy zakres; końcowe high/low są znane dopiero po końcu okna i otrzymaniu danych.",
    "LQ-K06": "Sweep wymaga przekroczenia ustalonej krawędzi i potwierdzonego zamknięcia z powrotem wewnątrz boksu.",
    "LQ-K07": "Zamknięcie poza zakresem to inne zdarzenie (wybicie); może wspierać kontynuację zamiast odwrócenia.",
    "LQ-K08": "Naruszenie obu krawędzi w jednej świecy OHLC nie ujawnia kolejności i nie daje domyślnego kierunku.",
    "LQ-K09": "Nazwa sweep opisuje geometrię – nie dowodzi faktycznego uruchomienia stopów ani intencji uczestników.",
    "LQ-K10": "Sesja i zakres konsolidacji M5 są odrębne; trigger, poziomy (TP1 = MID zakresu M5) i ważność pochodzą z istniejącego setupu.",
    "LQ-K11": "Kilka narzędzi opisujących ten sam ruch (sweep sesji, sweep M03, strefa M5, heatmapa) nie tworzy kilku niezależnych dowodów.",
    "LQ-K12": "Znane koszty, bramki ryzyka, tryb wykonania i STOP obowiązują niezależnie od atrakcyjnego wyglądu warstw.",
    "LQ-K13": "Historyczny wygląd dzisiejszej mapy nie dowodzi, co było dostępne w chwili dawnego wejścia (liczy się first_received_at).",
    "LQ-K14": "Przydatność narzędzi ocenia się poza próbą strojenia i po kosztach; integracja techniczna sama nie potwierdza przewagi.",
}


def prompt_section() -> str:
    return ("## Wiedza: boksy sesji i heatmapa likwidacji (" + KNOWLEDGE_VERSION + ")\n" + "\n".join(f"- {k}: {v}" for k, v in RULES.items())
            + "\nOdpowiadaj kolejno: co widać → źródło/czas → możliwa interpretacja → setup/trigger/braki → blokady i status walidacji.")


def _dist(price: float, low: float, high: float) -> float:
    return 0.0 if low <= price <= high else min(abs(price - low), abs(price - high))


def evaluate(*, boxes: list[dict], heatmap: dict | None, price: float | None, atr_m5: float | None, setup: dict | None = None,
             as_of: str | None = None) -> dict:
    """boxes: shared-engine boxes known at as_of; heatmap: heatmap_public(...) as of the same moment (or None);
    setup: {side BUY|SELL, setup_id, episode_price?} of an EXISTING scalp candidate, or None."""
    codes, support, conflict, missing, applied, facts = [], [], [], [], set(), []
    fams = {}

    def code(c, rules, **kw):
        codes.append(dict(code=c, **kw))
        applied.update(rules)
    side = (setup or {}).get("side")
    for b in boxes or []:
        name = f"{b['session']} ({b['profile_id']})"
        if b["state"] == "DEVELOPING":
            code("SESSION_DEVELOPING", ["LQ-K05"], box_id=b["box_id"], detail=f"{name}: zakres w trakcie {b['developing_low']}–{b['developing_high']} – brak końcowych krawędzi")
            continue
        if b["state"] == "INCOMPLETE":
            code("SESSION_BOX_INCOMPLETE", ["LQ-K05"], box_id=b["box_id"], detail=b.get("reason"))
            missing.append(f"{name}: niepełne dane okna – boks nie jest FINAL")
            continue
        if b["state"] != "FINAL":
            continue
        H, L = b["final_high"], b["final_low"]
        if price is not None and atr_m5:
            for edge, lvl in (("HIGH", H), ("LOW", L)):
                if abs(price - lvl) <= NEAR_ATR * atr_m5:
                    code("SESSION_EDGE_NEAR", ["LQ-K06"], box_id=b["box_id"], edge=edge, detail=f"cena {price} blisko {edge} {lvl} ({name}) – obszar obserwacji, nie trigger")
        evs = [e for e in b.get("events") or [] if as_of is None or _ts(e["available_at"]) <= _ts(as_of)]
        if not evs:
            continue
        e = evs[-1]
        fam = f"SWEEP_EPISODE:{e['bar_open_utc']}"
        fams[fam] = fams.get(fam, 0) + 1
        k = e["kind"]
        if k == "SWEEP_LOW":
            code("SESSION_LOW_REJECTION", ["LQ-K06", "LQ-K09", "LQ-K10"], box_id=b["box_id"], event_id=e["event_id"], evidence_family=fam,
                 detail=f"{name}: SWEEP_LOW potwierdzony {e['confirmed_at']} (dostępny {e['available_at']}) – kontekst dla istniejącego BUY")
            (support if side == "BUY" else conflict if side == "SELL" else facts).append(fam)
        elif k == "SWEEP_HIGH":
            code("SESSION_HIGH_REJECTION", ["LQ-K06", "LQ-K09", "LQ-K10"], box_id=b["box_id"], event_id=e["event_id"], evidence_family=fam,
                 detail=f"{name}: SWEEP_HIGH potwierdzony {e['confirmed_at']} – kontekst dla istniejącego SELL (brak BUY ≠ SELL)")
            (support if side == "SELL" else conflict if side == "BUY" else facts).append(fam)
        elif k in ("BREAKOUT_UP", "BREAKOUT_DOWN"):
            code("SESSION_BREAKOUT_CONTEXT", ["LQ-K07"] + (["LQ-K08"] if e.get("both_sides_breached") else []), box_id=b["box_id"], event_id=e["event_id"],
                 detail=f"{name}: {k} (zamknięcie poza boksem) – kontekst kontynuacji; nie tworzy fade" + (" ; świeca naruszyła obie krawędzie" if e.get("both_sides_breached") else ""))
            against = (k == "BREAKOUT_UP" and side == "SELL") or (k == "BREAKOUT_DOWN" and side == "BUY")
            if against:
                conflict.append(fam)
        elif k == "RETURN_INSIDE_AFTER_BREAK":
            code("SESSION_RETURN_AFTER_BREAK", ["LQ-K07"], box_id=b["box_id"], event_id=e["event_id"], detail=f"{name}: powrót do boksu po wybiciu (osobny epizod)")
        elif k == "SWEEP_BOTH_AMBIGUOUS":
            code("SESSION_BOTH_SIDES_AMBIGUOUS", ["LQ-K08"], box_id=b["box_id"], event_id=e["event_id"],
                 detail=f"{name}: obie krawędzie w jednej świecy – kolejność nieznana, brak kierunku")
            missing.append("jednoznaczny późniejszy trigger (po obustronnym naruszeniu)")
    # heatmap
    hm = heatmap or {}
    st = hm.get("status")
    if st not in ("OK", "STALE"):
        code("LIQ_CONTEXT_UNKNOWN", ["LQ-K04"], cause=st or "NO_SOURCE", detail=hm.get("reason") or "brak mapy")
    else:
        if st == "STALE":
            code("LIQ_CONTEXT_UNKNOWN", ["LQ-K04", "LQ-K13"], cause="STALE", detail=f"mapa sprzed {hm.get('age_s')} s – nie jest świeżym dowodem")
        zs = ((hm.get("zones") or {}).get("zones") or [])[:20]
        mapped = hm.get("mapping_status") == "VALIDATED_BASIS"
        for z in zs[:5]:
            code("LIQ_ESTIMATED_ZONE", ["LQ-K01", "LQ-K02"] + ([] if mapped else ["LQ-K03"]), rank=z["rank"], low=z["low"], high=z["high"],
                 axis="BROKER_PRICE" if mapped else "SOURCE_PRICE", detail=f"strefa {z['low']:.2f}–{z['high']:.2f} (rank {z['rank']}, względna {z['relative']:.2f}) – oszacowanie dostawcy"
                 + ("" if mapped else f" na osi {hm.get('source_instrument', {}).get('symbol')}, nie {hm.get('target_instrument')}"))
        if mapped and price is not None and st == "OK":
            for z in zs:
                if z["low"] <= price <= z["high"]:
                    code("LIQ_ZONE_CONTACT", ["LQ-K02"], rank=z["rank"], detail=f"cena w strefie {z['low']:.2f}–{z['high']:.2f}; reakcja dopiero rozstrzygnie")
                if atr_m5 and any(c["code"] in ("SESSION_LOW_REJECTION", "SESSION_HIGH_REJECTION") for c in codes) and _dist(price, z["low"], z["high"]) <= NEAR_ATR * atr_m5:
                    code("LIQ_SESSION_CONFLUENCE_RESEARCH", ["LQ-K11", "LQ-K14"], rank=z["rank"], detail="sweep sesji blisko strefy heatmapy – hipoteza badawcza, jeden epizod")
        elif not mapped:
            missing.append("zweryfikowane mapowanie ceny źródła na instrument brokera (heatmapa w osobnym panelu)")
    if setup:
        missing.append("trigger, poziomy i ważność wyłącznie z silnika scalp (sweep/reclaim/retest M1, TP1 = MID zakresu M5)")
    applied.update(["LQ-K11", "LQ-K12", "LQ-K14"])
    expl = _explain(codes, side, missing)
    return {"mode": "OBSERVE", "policy_version": POLICY_VERSION, "knowledge_version": KNOWLEDGE_VERSION, "as_of": as_of, "setup": setup,
            "reason_codes": codes, "supporting_evidence_families": sorted(set(support)), "conflicting_evidence_families": sorted(set(conflict)),
            "evidence_family_counts": fams, "missing_conditions": missing, "validation_status": "NO_VALIDATED_EDGE",
            "applied_rules": sorted(applied), "explanation_pl": expl,
            "note": "warstwy nie tworzą sygnału ani filtra wykonania; % / rank to nie prawdopodobieństwo zysku"}


def _explain(codes: list[dict], side: str | None, missing: list[str]) -> str:
    seen = [c["detail"] for c in codes if c.get("detail")][:6]
    head = "Co widać: " + ("; ".join(seen) if seen else "brak zdarzeń sesji ani stref heatmapy w tym snapshotcie") + "."
    tail = (f" Dla setupu {side}: " if side else " Brak setupu: ") + ("brakuje – " + "; ".join(missing[:3]) if missing else "kontekst opisowy") + "."
    return (head + tail + " Status walidacji: NO_VALIDATED_EDGE (OBSERVE).")[:1200]


def frozen(boxes: list[dict], heatmap: dict | None, price, atr_m5, as_of: str | None, max_events: int = 12, max_zones: int = 20) -> dict:
    """Compact, copy-only payload for the engine context / agent tool (no grid, bounded counts with a truncation flag)."""
    evs = [dict(e, session=b["session"]) for b in boxes or [] for e in (b.get("events") or [])]
    zs = ((heatmap or {}).get("zones") or {}).get("zones") or []
    return {"as_of": as_of, "boxes": [{k: b.get(k) for k in ("box_id", "session", "profile_id", "state", "start_utc", "end_utc", "known_at", "final_high", "final_low",
                                                              "developing_high", "developing_low", "coverage_ratio", "missing_slots", "expires_at")} for b in boxes or []][:9],
            "events": evs[-max_events:], "events_total": len(evs), "zones": zs[:max_zones], "zones_total": len(zs),
            "truncated": len(evs) > max_events or len(zs) > max_zones,
            "heatmap": {k: (heatmap or {}).get(k) for k in ("status", "snapshot_id", "first_received_at", "age_s", "mapping_status", "axis", "source_instrument",
                                                            "target_instrument", "reason", "availability_trust")},
            "policy": evaluate(boxes=boxes, heatmap=heatmap, price=price, atr_m5=atr_m5, as_of=as_of)}


def _ts(s) -> float:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
