"""Builds docs/POROWNANIE_ORIGINAL_ACTIVE.md and docs/TABELA_FILTROW.md from a replay JSON (tools/replay_strategies.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILTERS = [
    ("Zgodność H4 i H1 (M02 SCALP) jako warunek każdego setupu", "kierunek strukturalny", "cały skaner (ORIGINAL)",
     "ZASTĄPIĆ PUNKTACJĄ: w ACTIVE kontekst HTF = 10 pkt; konflikt raportowany z horyzontem (COUNTERTREND); ORIGINAL bez zmian"),
    ("Pięć warunków CORE M03E (przewaga, FVG/OB, płynność, ścieżka, unieważnienie) dla każdej okazji", "jakość lokalizacji", "M07 (ORIGINAL)",
     "OGRANICZYĆ DO STRATEGII: każda S01–S10 ma własne warunki konieczne; nie wymagamy jednocześnie retestu, OB, FVG i sweepu"),
    ("Oczekiwanie na zamknięcie wszystkich TF / pełny cykl tylko po zamknięciu świecy", "brak look-ahead", "cały skaner",
     "OGRANICZYĆ: skan co ≥ 2 s przy nowych danych; świeca tworząca się tylko dla WATCH/EARLY, CONFIRMED wyłącznie na zamkniętej"),
    ("RSI + MACD + nachylenie EMA jako osobne potwierdzenia", "momentum", "punktacja", "USUNĄĆ DUPLIKAT: jedna kategoria momentum (mediana 3 głosów), 20 pkt"),
    ("Brak opcjonalnego DXY", "kontekst USD", "strategie z wymogiem DXY", "PUNKTACJA: 5 pkt „dodatkowe” (0 przy braku), nigdy weto"),
    ("Brak kalendarza / newsów", "ryzyko makro", "wykonanie", "ZACHOWAĆ TYLKO DLA WYKONANIA: okno wydarzenia blokuje zlecenie; brak kalendarza = UNKNOWN, nie blokuje prezentacji"),
    ("Oczekiwanie na odpowiedź Claude", "druga opinia", "wykonanie", "ZACHOWAĆ TYLKO DLA WYKONANIA (VETO, maks. 60 s); lokalny WATCH/EARLY pokazywany od razu (AI_PENDING)"),
    ("Blokada wykonania (READ_ONLY, ryzyko, limity) przeniesiona na prezentację", "bezpieczeństwo", "monitor",
     "USUNIĘTE z prezentacji: setup widoczny z przyczyną zablokowanego wykonania; blokady wykonania bez zmian"),
    ("Stałe WAIT/NO_TRADE i diagnostyczne side='LONG' (M00U10/U10)", "diagnostyka READONLY", "paczka wejściowa",
     "NIE UŻYWANE do analizy (od 1.0); BLOCKED legacy rozdzielone od execution_permission"),
    ("Globalne wymaganie historii", "warm-up wskaźników", "cały skaner", "OGRANICZYĆ DO STRATEGII: min_bars per strategia, brak TF blokuje tylko strategie, które go wymagają"),
    ("Cooldown", "przeciw powtórzeniom", "detekcja/zlecenia/powiadomienia",
     "ROZDZIELONE: detekcja bez cooldownu (struktura publikowana raz), zlecenia – UNIQUE entry_key, powiadomienia – tylko EARLY/CONFIRMED/unieważnienie"),
    ("Jakość danych, STALE, offset czasu, FUTURE_CANDLE", "poprawność danych", "cały system", "ZACHOWAĆ (twarde): STALE nie tworzy nowych setupów"),
    ("Limity ryzyka, RR netto, koszty, min. lot, uprawnienia", "ochrona kapitału", "wykonanie", "ZACHOWAĆ bez zmian (nie obniżane dla liczby sygnałów)"),
    ("Progi punktacji ACTIVE 40 / 55 / 70", "selekcja prezentacji", "ACTIVE", "NOWE (robocze): CONFIRMED wymaga dodatkowo prawdziwego triggera strategii"),
]


def main() -> int:
    if len(sys.argv) < 2:
        print("użycie: make_comparison_doc.py replay.json")
        return 2
    r = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    src = r["source"]
    hours = r["observed_hours"]
    ps = r["per_strategy"]
    tot_setups = sum(s["unique_setups"] for s in ps.values())
    tot_conf = sum(s["confirmed"] for s in ps.values())
    L = [f"# Porównanie ORIGINAL vs ACTIVE – dane {src}", "",
         f"**Źródło danych: {src}.** " + ("To dane symulatora terminala – wynik pokazuje działanie i częstotliwość reguł, **nie dowodzi skuteczności** "
                                          "ani nie przenosi się na XAUUSD- Twojego brokera." if src == "SYNTHETIC" else "Dane z eksportu Twojego MT5."), "",
         f"Okres obserwacji: {hours} h rynku ({r['steps']} kroków {r['step_tf']}), metoda: {r['method']}.", "",
         "## Częstotliwość wykrywania (unikalne setupy; aktualizacje tego samego setupu nie są liczone)", "",
         "| Profil | Unikalne setupy | Na godzinę obserwowanego rynku |", "|---|---|---|"]
    orig = r.get("original_m07") or {}
    for pol, o in orig.items():
        L.append(f"| ORIGINAL M07 (struktura {pol}) | {o['unique_plans']} planów | {o['per_observed_hour']} (kroki H1: {o['steps']}, godziny z kierunkiem: {o['hours_with_direction']}) |")
    L.append(f"| ACTIVE S01–S10 (wszystkie etapy) | {tot_setups} | {round(tot_setups / hours, 3) if hours else '—'} |")
    L.append(f"| ACTIVE – osiągnięte CONFIRMED | {tot_conf} | {round(tot_conf / hours, 3) if hours else '—'} |")
    L += ["", "## Per strategia", "", "| Strategia | Unikalne | /h | EARLY→CONFIRMED | Mediana EARLY→CONF [min] | CONFIRMED | Unieważnione/wygasłe/anulowane | Transakcje (sym.) | Expectancy R | OOS: trans. / exp. R |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for sid, s in ps.items():
        a, o = s["all"], s["segments"]["OOS"]
        term = ", ".join(f"{k} {v}" for k, v in s["terminal"].items()) or "—"
        L.append(f"| {sid} | {s['unique_setups']} | {s['per_observed_hour']} | {s['early_to_confirmed']} | {s['median_lead_early_to_confirmed_min']} | {s['confirmed']} | {term} | "
                 f"{a.get('trades')} | {a.get('expectancy_r', '—')} | {o.get('trades')} / {o.get('expectancy_r', '—')} |")
    L += ["", f"Portfel (tylko setup wybrany przez AUTO, jedna pozycja naraz, wspólne limity): `{json.dumps(r['portfolio_auto_selected'], ensure_ascii=False)}`", "",
          f"Duplikaty: {r['events_shared_by_several_strategies']} zdarzeń opisanych jednocześnie przez kilka strategii (maks. {r['max_strategies_per_event']}) – "
          "grupowane przez event_id, jedno wejście.", f"Zmiany wyboru AUTO: {r['selection_changes']}; przyczyny: `{json.dumps(r.get('selection_change_reasons', {}))}`.",
          f"Wydajność replay: {r['ms_per_step']} ms/krok (skan 10 strategii + tracker + selektor).", "",
          "## Interpretacja i ograniczenia",
          "* Wyniki R pochodzą z konserwatywnej symulacji (wejście na otwarciu następnej świecy M5, SL przed TP w niejednoznacznej świecy, koszty i poślizg); "
          "przy danych syntetycznych mają charakter testu poprawności, nie oceny strategii.",
          "* Dziesięć strategii i ich parametry to problem wielokrotnego testowania – segment OOS (ostatnie 20%) nie może służyć do strojenia.",
          "* Kryteria oceny badań (ustalone przed oceną): strategia może przejść do FORWARD_DEMO tylko przy OOS ≥ 30 transakcji, expectancy netto > 0 R "
          "i profit factor ≥ 1,2 na danych brokera; inaczej pozostaje eksperymentalna.",
          "* ORIGINAL i ACTIVE różnią się celem: ACTIVE pokazuje wcześniejsze etapy (WATCH/EARLY), więc większa liczba setupów nie oznacza większej liczby transakcji.",
          "", "Uruchomienie na Twoich danych: `python -m masterquo export --from-utc … --to-utc …` (w folderze backend), potem "
          "`python tools/replay_strategies.py --csv-dir data/export_mt5_six_tf --compare-original` i `python tools/make_comparison_doc.py <wynik.json>`."]
    (ROOT / "docs" / "POROWNANIE_ORIGINAL_ACTIVE.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    F = ["# Zestawienie zmienionych filtrów (profil ACTIVE)", "",
         "Przepływ: dane → wskaźniki → strategia → kandydat → filtr → trigger → AI → wyświetlenie → wykonanie. Liczby odrzuceń z replay "
         f"({src}, {hours} h): `drafts` = rozpoznane struktury (warunki konieczne spełnione), `below_watch` = odrzucone przez próg WATCH, "
         "`published_*` = opublikowane odczyty w danym etapie (sumowane po krokach).", "",
         "| Filtr | Cel | Zakres | Decyzja |", "|---|---|---|---|"]
    F += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in FILTERS]
    F += ["", "## Lejek kandydatów (przed i po filtrach) – replay", "", "| Strategia | Struktury (drafts) | Odrzucone progiem WATCH | WATCH | EARLY | CONFIRMED | Unikalne setupy |",
          "|---|---|---|---|---|---|---|"]
    for sid, s in ps.items():
        f = s["funnel"]
        F.append(f"| {sid} | {f.get('drafts', 0)} | {f.get('below_watch', 0)} | {f.get('published_WATCH', 0)} | {f.get('published_EARLY', 0)} | "
                 f"{f.get('published_CONFIRMED', 0)} | {s['unique_setups']} |")
    F += ["", "Dalsze filtry wykonania (ryzyko, tryb, AI, makro) nie są symulowane w replay – działają w aplikacji i ich przyczyny są widoczne w drzewie decyzji.",
          "Progi nie zostały obniżone „bo dawno nie było sygnału”; zmiana progów prezentacji nie zmienia progów wykonania ani limitów ryzyka."]
    (ROOT / "docs" / "TABELA_FILTROW.md").write_text("\n".join(F) + "\n", encoding="utf-8")
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
