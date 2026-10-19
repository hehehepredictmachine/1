"""Structure Intelligence knowledge for the agent (PMW-UPD-07 R15) - versioned rules ACTUALLY loaded into the prompt + a deterministic
explanation builder (bounded facts with evidence ids). The explanation never computes a new percentage: probabilities are shown only
when the snapshot contains a model output (forecast_status OK); otherwise the text says the model is missing. Adding these rules to
the prompt is NOT fine-tuning of the language model."""
from __future__ import annotations

KNOWLEDGE_VERSION = "PMW-SI-KNOWLEDGE-1.1.0"
RULES = {
    "K01": "Najpierw TF, kontekst i czas dostępności; brak świeżych danych oznacza ograniczoną odpowiedź.",
    "K02": "Świeca jest dowodem warunkowym w strukturze, nie obietnicą kierunku.",
    "K03": "Pivot jest znany po prawych świecach; marker na wcześniejszej świecy nie oznacza wcześniejszej wiedzy.",
    "K04": "BOS wymaga zamknięcia i wcześniej znanej granicy; sweep knota ma inne znaczenie.",
    "K05": "Geometric score, historyczny status DB i trade probability to różne wielkości.",
    "K06": "CONFIRMED DB nie oznacza zyskownej transakcji, a FAILED pattern nie oznacza błędu serwisu.",
    "K07": "Formacja może stracić aktualność; użyj konkretnego warunku unieważnienia/expiry.",
    "K08": "MITP jest opóźnionym potwierdzeniem; utrzymany kolor nie dowodzi aktualnej jednomyślności.",
    "K09": "32 pochodne ceny nie stanowią 32 niezależnych dowodów.",
    "K10": "HV_PROXY, IV_MANUAL i OPTION_CHAIN są odrębnymi źródłami; Daily Open nie jest forward.",
    "K11": "Black Q-quantiles nie są rzeczywistą prognozą CFD ani p_zysk; delta nie jest p_touch.",
    "K12": "Tick volume i kształt świecy nie dowodzą delty/absorpcji instytucji.",
    "K13": "Źródła GLD/GC/BTCUSDT nie są automatycznie zgodne z kontraktem MT5.",
    "K14": "Koszt i przestrzeń do celu mogą unieważnić plan mimo poprawnej formacji.",
    "K15": "Brak zgodnego modelu, słaba kalibracja lub drift wymagają WAIT z nazwanym powodem.",
    "K16": "Ceny kwantyli opisują koniec horyzontu, nie gwarantowaną trajektorię ani high/low.",
    "K17": "Wyjaśnienie pozytywnego scenariusza zawiera również jego poziom unieważnienia i konflikt MTF.",
    "K18": "Agent wyjaśnia odczyty; Manual Pad i gateway przyjmują wyłącznie jawne akcje użytkownika.",
    "K19": "Residual usuwa wybraną liniową ekspozycję w dopasowaniu; nie jest automatycznie alpha ani dowodem zerowej korelacji przyszłych sygnałów.",
    "K20": "Raw/exposure/residual mają odrębne znaczenie; usunięcie trendu może osłabić strategię kontynuacji.",
    "K21": "ADD, AND i IAND mają różne identity conditions; operatorem nie przełącza się gotowych wag bez nowego modelu.",
    "K22": "Newtonian opisuje Bid/Ask osobno; niepewność parametrów, przyszłej ceny i prawdopodobieństwo zysku nie są tym samym.",
    "K23": "Turning time i etykieta fazy są hipotezą lokalnego modelu; nie gwarantują odwrócenia rynku.",
    "K24": "Prognoza tickowa bez terminowego quote do oceny ma UNSCORED_GAP, a nie trafny sygnał.",
    "K36": "Kod/integracja/trening/parytet/native/edge mają oddzielne statusy; brak danych albo testu nie może zostać przemilczany.",
}


def prompt_section() -> str:
    return ("## Wiedza: struktura, świece, MITP, Black-76, prognoza ruchu (" + KNOWLEDGE_VERSION + ")\n" + "\n".join(f"- {k}: {v}" for k, v in RULES.items())
            + "\nFormat odpowiedzi: kontekst → przesłanka → horyzont/niepewność → unieważnienie → brakujące dane; podawaj evidence IDs z narzędzia "
              "get_structure_intelligence i nie dopowiadaj procentów, których nie ma w faktach.")


def explain(snap: dict | None) -> dict:
    """Bounded facts + evidence ids + short PL text from ONE Structure Intelligence snapshot (no LLM, no new numbers)."""
    if not snap:
        return {"status": "NO_SNAPSHOT", "rules": ["K01"], "text": "Brak snapshotu struktury – odpowiedź ograniczona (K01).", "evidence_ids": []}
    facts, ev, rules, missing = [], [], {"K01", "K36"}, []
    for tf, c in (snap.get("cells") or {}).items():
        if c.get("status") != "OK":
            missing.append(f"{tf}: {c.get('status')}")
            continue
        s = c.get("structure") or {}
        e = s.get("last_event")
        line = f"{tf}: struktura {s.get('trend_internal')} (wewn.) / {s.get('trend_major')} (nadrz.)"
        if e:
            line += f"; ostatnie zdarzenie {e['kind']} poziom {e['level']} na świecy {e['bar_t']}"
            ev.append(e["event_id"])
            rules.update({"K03", "K04"})
        p = c.get("pattern")
        if p:
            line += f"; formacja {p['type']} stan {p['state']} ({p.get('geometry_quality')}), unieważnienie {p.get('invalidation')}"
            ev.append(p["pattern_id"])
            rules.update({"K05", "K07", "K17"})
        cr = c.get("candle_role") or {}
        if cr.get("role"):
            line += f"; rola świecy {cr['role']}"
            ev += [cr.get("reading_id")] + list(cr.get("evidence") or [])
            rules.update({"K02", "K12"})
        m = c.get("mitp") or {}
        if m.get("held_state") is not None or m.get("current_vote") is not None:
            line += f"; MITP stan utrzymany {m.get('held_state')}, bieżący głos {m.get('current_vote')}"
            rules.update({"K08", "K09"})
        facts.append(line)
    fc = snap.get("forecast") or {}
    if fc.get("forecast_status") == "OK":
        rules.update({"K16", "K11"})
        for hd in fc["heads"]:
            facts.append(f"prognoza h={hd['h_bars']} M1 (model {fc.get('family')}, {fc.get('artifact_id')}): DOWN {hd['p_down']:.2f} / FLAT {hd['p_flat']:.2f} / UP {hd['p_up']:.2f}, "
                         f"q10–q90 ceny {hd['price_q10']:.2f}–{hd['price_q90']:.2f} (koniec horyzontu, nie high/low)")
    else:
        rules.add("K15")
        missing.append(f"prognoza: {fc.get('reason') or fc.get('forecast_status') or 'brak'}")
    nz = snap.get("neutralization") or {}
    if nz.get("raw") is not None:
        rules.update({"K19", "K20"})
        facts.append(f"neutralizacja ROC20: raw {nz['raw']:.5f}, ekspozycja {nz.get('exposure')}, reszta {nz.get('residual')}, status {nz.get('status')}"
                     + (f", fit {nz.get('fit_id')}" if nz.get("fit_id") else ""))
        if nz.get("fit_id"):
            ev.append(nz["fit_id"])
    q = snap.get("quotes") or {}
    if q.get("phase"):
        rules.update({"K22", "K23", "K24"})
        facts.append(f"kinematyka Bid/Ask: faza {q['phase']} (hipoteza lokalnego modelu), zegar {q.get('clock')}")
    if snap.get("divergences"):
        rules.add("K17")
        facts += [f"rozbieżność MTF: {d}" for d in snap["divergences"]]
    text = ("Kontekst: " + (" | ".join(facts[:6]) if facts else "brak gotowych TF") + ". "
            + ("Brakujące dane: " + "; ".join(missing[:6]) + ". " if missing else "")
            + "To odczyt warunkowy – nie zlecenie; akcje wykonuje wyłącznie użytkownik (K18).")
    return {"status": "OK", "snapshot_id": snap.get("snapshot_id"), "as_of": snap.get("as_of"), "facts": facts, "missing": missing,
            "evidence_ids": [x for x in ev if x], "rules": sorted(rules | {"K18"}), "text": text, "knowledge_version": KNOWLEDGE_VERSION}
