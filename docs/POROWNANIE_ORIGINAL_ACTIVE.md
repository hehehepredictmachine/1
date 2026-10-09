# Porównanie ORIGINAL vs ACTIVE – dane SYNTHETIC

**Źródło danych: SYNTHETIC.** To dane symulatora terminala – wynik pokazuje działanie i częstotliwość reguł, **nie dowodzi skuteczności** ani nie przenosi się na XAUUSD- Twojego brokera.

Okres obserwacji: 30.0 h rynku (120 kroków M15), metoda: closed-bar replay, next-M5-open entry, SL-first on ambiguous bars, costs in R; DEV/VAL/OOS 60/20/20.

## Częstotliwość wykrywania (unikalne setupy; aktualizacje tego samego setupu nie są liczone)

| Profil | Unikalne setupy | Na godzinę obserwowanego rynku |
|---|---|---|
| ACTIVE S01–S10 (wszystkie etapy) | 285 | 9.5 |
| ACTIVE – osiągnięte CONFIRMED | 57 | 1.9 |

## Per strategia

| Strategia | Unikalne | /h | EARLY→CONFIRMED | Mediana EARLY→CONF [min] | CONFIRMED | Unieważnione/wygasłe/anulowane | Transakcje (sym.) | Expectancy R | OOS: trans. / exp. R |
|---|---|---|---|---|---|---|---|---|---|
| S01 | 19 | 0.633 | 1 | 15.0 | 1 | INVALIDATED 10, CANCELLED 8 | 1 | -1.031 | 0 / — |
| S02 | 11 | 0.367 | 0 | None | 4 | INVALIDATED 4, CANCELLED 6, MISSED_ENTRY 2 | 4 | 1.031 | 2 / 2.198 |
| S03 | 66 | 2.2 | 0 | None | 16 | INVALIDATED 7, CANCELLED 19, MISSED_ENTRY 16, EXPIRED 26 | 16 | -0.187 | 1 / -1.048 |
| S04 | 6 | 0.2 | 0 | None | 1 | CANCELLED 2, INVALIDATED 3, MISSED_ENTRY 1 | 1 | -1.033 | 0 / — |
| S05 | 2 | 0.067 | 0 | None | 0 | CANCELLED 1, INVALIDATED 1 | 0 | — | 0 / — |
| S06 | 27 | 0.9 | 3 | 15.0 | 9 | INVALIDATED 5, EXPIRED 14, MISSED_ENTRY 8 | 9 | 0.09 | 2 / 1.497 |
| S07 | 54 | 1.8 | 1 | 30.0 | 13 | EXPIRED 15, MISSED_ENTRY 10, INVALIDATED 25, CANCELLED 4 | 13 | 0.38 | 4 / -0.676 |
| S08 | 13 | 0.433 | 1 | 15.0 | 4 | CANCELLED 1, MISSED_ENTRY 3, INVALIDATED 5, EXPIRED 3 | 4 | -0.357 | 3 / -0.129 |
| S09 | 18 | 0.6 | 1 | 15.0 | 8 | MISSED_ENTRY 8, EXPIRED 4, CANCELLED 3, INVALIDATED 3 | 7 | -0.247 | 1 / -1.01 |
| S10 | 69 | 2.3 | 1 | 15.0 | 1 | EXPIRED 17, INVALIDATED 36, CANCELLED 14, MISSED_ENTRY 1 | 1 | -1.02 | 0 / — |

Portfel (tylko setup wybrany przez AUTO, jedna pozycja naraz, wspólne limity): `{"trades": 14, "expectancy_r": 0.78, "total_r": 10.92, "profit_factor": 4.43, "win_rate": "10/14 (71%)", "max_drawdown_r": 3.18, "avg_mae_r": 0.55, "avg_mfe_r": 1.58, "avg_hold_m5_bars": 23.6}`

Duplikaty: 27 zdarzeń opisanych jednocześnie przez kilka strategii (maks. 3) – grupowane przez event_id, jedno wejście.
Zmiany wyboru AUTO: 63; przyczyny: `{}`.
Wydajność replay: 84.1 ms/krok (skan 10 strategii + tracker + selektor).

## Interpretacja i ograniczenia
* Wyniki R pochodzą z konserwatywnej symulacji (wejście na otwarciu następnej świecy M5, SL przed TP w niejednoznacznej świecy, koszty i poślizg); przy danych syntetycznych mają charakter testu poprawności, nie oceny strategii.
* Dziesięć strategii i ich parametry to problem wielokrotnego testowania – segment OOS (ostatnie 20%) nie może służyć do strojenia.
* Kryteria oceny badań (ustalone przed oceną): strategia może przejść do FORWARD_DEMO tylko przy OOS ≥ 30 transakcji, expectancy netto > 0 R i profit factor ≥ 1,2 na danych brokera; inaczej pozostaje eksperymentalna.
* ORIGINAL i ACTIVE różnią się celem: ACTIVE pokazuje wcześniejsze etapy (WATCH/EARLY), więc większa liczba setupów nie oznacza większej liczby transakcji.

Uruchomienie na Twoich danych: `python -m masterquo export --from-utc … --to-utc …` (w folderze backend), potem `python tools/replay_strategies.py --csv-dir data/export_mt5_six_tf --compare-original` i `python tools/make_comparison_doc.py <wynik.json>`.
