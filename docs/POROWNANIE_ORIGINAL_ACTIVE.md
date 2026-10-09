# Porównanie ORIGINAL vs ACTIVE – dane SYNTHETIC

**Źródło danych: SYNTHETIC.** To dane symulatora terminala – wynik pokazuje działanie i częstotliwość reguł, **nie dowodzi skuteczności** ani nie przenosi się na XAUUSD- Twojego brokera.

Okres obserwacji: 575.0 h rynku (2300 kroków M15), metoda: closed-bar replay, next-M5-open entry, SL-first on ambiguous bars, costs in R; DEV/VAL/OOS 60/20/20.

## Częstotliwość wykrywania (unikalne setupy; aktualizacje tego samego setupu nie są liczone)

| Profil | Unikalne setupy | Na godzinę obserwowanego rynku |
|---|---|---|
| ORIGINAL M07 (struktura STRICT_H4_H1) | 12 planów | 0.021 (kroki H1: 575, godziny z kierunkiem: 34) |
| ORIGINAL M07 (struktura H1_LEAD) | 59 planów | 0.103 (kroki H1: 575, godziny z kierunkiem: 171) |
| ACTIVE S01–S10 (wszystkie etapy) | 5748 | 9.997 |
| ACTIVE – osiągnięte CONFIRMED | 1102 | 1.917 |

## Per strategia

| Strategia | Unikalne | /h | EARLY→CONFIRMED | Mediana EARLY→CONF [min] | CONFIRMED | Unieważnione/wygasłe/anulowane | Transakcje (sym.) | Expectancy R | OOS: trans. / exp. R |
|---|---|---|---|---|---|---|---|---|---|
| S01 | 410 | 0.713 | 12 | 30.0 | 36 | CANCELLED 200, INVALIDATED 149, EXPIRED 29, MISSED_ENTRY 34 | 36 | 0.681 | 9 / 0.652 |
| S02 | 130 | 0.226 | 0 | None | 95 | MISSED_ENTRY 83, INVALIDATED 20, CANCELLED 28 | 95 | 0.223 | 23 / -0.031 |
| S03 | 1369 | 2.381 | 0 | None | 428 | EXPIRED 450, MISSED_ENTRY 412, CANCELLED 384, INVALIDATED 135 | 428 | 0.267 | 96 / 0.297 |
| S04 | 140 | 0.243 | 7 | 15.0 | 41 | INVALIDATED 63, CANCELLED 32, MISSED_ENTRY 29, EXPIRED 16 | 41 | 0.188 | 11 / 0.246 |
| S05 | 76 | 0.132 | 1 | 30.0 | 8 | INVALIDATED 40, CANCELLED 27, MISSED_ENTRY 6, EXPIRED 2 | 8 | 0.219 | 1 / 1.634 |
| S06 | 578 | 1.005 | 67 | 15.0 | 133 | INVALIDATED 203, MISSED_ENTRY 120, EXPIRED 237, CANCELLED 22 | 132 | 0.229 | 32 / 0.474 |
| S07 | 1044 | 1.816 | 7 | 15.0 | 176 | INVALIDATED 532, EXPIRED 253, CANCELLED 125, MISSED_ENTRY 133 | 176 | 0.048 | 37 / -0.303 |
| S08 | 418 | 0.727 | 10 | 15.0 | 80 | EXPIRED 135, INVALIDATED 152, CANCELLED 66, MISSED_ENTRY 71 | 80 | 0.059 | 12 / -0.275 |
| S09 | 275 | 0.478 | 5 | 15.0 | 66 | CANCELLED 46, EXPIRED 136, MISSED_ENTRY 64, INVALIDATED 30 | 59 | -0.28 | 16 / -0.465 |
| S10 | 1308 | 2.275 | 11 | 15.0 | 39 | INVALIDATED 835, MISSED_ENTRY 37, CANCELLED 212, EXPIRED 223 | 26 | -0.243 | 5 / -1.025 |

Portfel (tylko setup wybrany przez AUTO, jedna pozycja naraz, wspólne limity): `{"trades": 168, "expectancy_r": 0.276, "total_r": 46.34, "profit_factor": 1.6, "win_rate": "92/168 (55%)", "max_drawdown_r": 7.76, "avg_mae_r": 0.81, "avg_mfe_r": 1.36, "avg_hold_m5_bars": 34.1}`

Duplikaty: 710 zdarzeń opisanych jednocześnie przez kilka strategii (maks. 4) – grupowane przez event_id, jedno wejście.
Zmiany wyboru AUTO: 1172; przyczyny: `{"FIRST_SELECTION": 1, "PREVIOUS_SETUP_NO_LONGER_VALID": 1024, "NEW_CANDIDATE": 115, "CHALLENGER_LEADS": 32}`.
Wydajność replay: 93.9 ms/krok (skan 10 strategii + tracker + selektor).

## Interpretacja i ograniczenia
* Wyniki R pochodzą z konserwatywnej symulacji (wejście na otwarciu następnej świecy M5, SL przed TP w niejednoznacznej świecy, koszty i poślizg); przy danych syntetycznych mają charakter testu poprawności, nie oceny strategii.
* Dziesięć strategii i ich parametry to problem wielokrotnego testowania – segment OOS (ostatnie 20%) nie może służyć do strojenia.
* Kryteria oceny badań (ustalone przed oceną): strategia może przejść do FORWARD_DEMO tylko przy OOS ≥ 30 transakcji, expectancy netto > 0 R i profit factor ≥ 1,2 na danych brokera; inaczej pozostaje eksperymentalna.
* ORIGINAL i ACTIVE różnią się celem: ACTIVE pokazuje wcześniejsze etapy (WATCH/EARLY), więc większa liczba setupów nie oznacza większej liczby transakcji.

Uruchomienie na Twoich danych: `python -m masterquo export --from-utc … --to-utc …` (w folderze backend), potem `python tools/replay_strategies.py --csv-dir data/export_mt5_six_tf --compare-original` i `python tools/make_comparison_doc.py <wynik.json>`.

## Komentarz do tego przebiegu (SYNTHETIC, 20 dni + 45 dni rozgrzewki, seed 3)
* ACTIVE wykrywa ok. **100× więcej unikalnych setupów** niż ORIGINAL ze ścisłą strukturą (9,997/h wobec 0,021/h). To głównie etapy
  WATCH/EARLY; etap CONFIRMED osiąga ok. 1,9 setupu/h, a po grupowaniu i wyborze AUTO zostaje 168 transakcji symulowanych w 575 h.
* Zmiany wyboru AUTO: 1024 z 1172 to natychmiastowe odrzucenie setupu, który przestał być ważny (unieważnienie/wygaśnięcie), 115 to nowy kandydat
  po okresie bez wyboru, a tylko **32 to przełączenia przez histerezę** (przewaga ≥ 8 pkt przez 2 aktualizacje) – wybór nie „migocze”.
* Generator symulatora ma dryf zależny od reżimu, więc wyniki R (portfel AUTO: expectancy +0,28 R, PF 1,6) **nie są dowodem skuteczności** –
  na prawdziwym XAUUSD- mogą być zupełnie inne. Ten przebieg sprawdza wyłącznie, że cały łańcuch działa chronologicznie i bez look-ahead.
* S09 i S10 mają ujemne wyniki również na danych syntetycznych – w kartach nic nie zostało „poprawione pod wynik”.
