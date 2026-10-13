# Postęp audytu (Claude Code)

**Zakres:** audyt MasterQUO 1.9.0, reprodukcje, plan ulepszeń i protokół walidacji. Bez zmian kodu produkcyjnego w ramach audytu. Poprawki zostały wdrożone osobno, w wersji 1.10.0.

| Etap | Stan | Wynik / plik |
|---|---|---|
| 1. Inwentaryzacja repozytorium, wersja, środowisko, skuteczna konfiguracja | ZROBIONE | `AUDYT_MASTERQUO_1_9_0_PL.md` §1 |
| 2. Mapa łańcucha decyzji i ścieżek zleceń | ZROBIONE | §2 |
| 3. Kontrola A–J | ZROBIONE | §3; `repro/repro_audit.py` |
| 4. Reprodukcje (FakeMT5/atrapy, izolowane dane) | ZROBIONE – 8/8 REPRODUCED na 1.9.0 | `repro/wyniki_1_9_0_przed_naprawami.json` |
| 5. Pełny runner testów na 1.9.0 | ZROBIONE – 224 OK, exit 0 | `WYNIKI_TESTOW.json` |
| 6. Dane / wskaźniki / setupy S01–S11, koszty, metryki, ML, agent | ZROBIONE (statycznie + testy) | §4–§7 |
| 7. Plan ulepszeń P0/P1/P2 z kryteriami odrzucenia | ZROBIONE | `PLAN_ULEPSZEN_WINRATE_ROI_PL.md` |
| 8. Protokół walidacji (przed wynikami) | ZROBIONE | `PROTOKOL_WALIDACJI.json` |
| 9. Porównanie wariantów na danych brokera | NIE WYKONANO – brak danych | – |
| 10. Naprawy P0 (osobne zadanie) i reprodukcje po naprawach | 1.10.0 | `repro/wyniki_1_10_0_po_naprawach.json` |

## Brakujące dane

Lista szczegółowa jest w `PROTOKOL_WALIDACJI.json`, w sekcji `data.required_exports`.

1. Eksport OHLC/tick volume/spread z Twojego terminala, co najmniej 18 miesięcy, M1…MN1.
2. Ticki Bid/Ask dla okresów walidacji i OOS.
3. `symbol_info` i historia deals rachunku.
4. Diagnostyka czasu MT5 z kilku sesji, w tym po zmianie czasu (DST).
5. Opcjonalnie historyczna IV z polem `available_at`.

## Jak kontynuować

1. `python audit/repro/repro_audit.py --out audit/repro/wyniki_<etykieta>.json`
2. `python tools/run_tests.py`
3. Po dostarczeniu eksportu: baseline 1.10.0 według protokołu, następnie ablation kolejno według `PROTOKOL_WALIDACJI.json` → `ablations`.
