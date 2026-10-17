# AUDIT – PepeMarketWizard 1.14 (dwa aktywa XAUUSD / BTC), 17.10.2026

Środowisko: Linux, symulator terminala MT5 (dane syntetyczne), Chromium. Nie było Windows, Twojego MT5, rachunku ani sieci do mql5.com i arxiv. Poprzednie audyty: `AUDIT_REPORT.md` (1.13), `AUDYT_MASTERQUO.md` (1.8), `audit/` (1.9–1.10).

## 1. Stan zastany (1.13) – inwentaryzacja

**Stack i struktura:**
- FastAPI + SQLite (migracje 0001–0013), React 19 / Vite, jeden WebSocket.
- Bridge MT5 w jednym wątku workera.
- Silnik legacy M01–M07, strategie S01–S12 + AUTO, ML DT/XGBoost (SHADOW/ASSIST), gold_candles (SHADOW), scalp 1.12 (SHADOW), analityka 1.13 (OBSERVE).

**Źródła danych:**
- MT5 – jeden symbol główny plus skaner „wszystkich rynków” (Market Watch / ALL).
- Opcjonalnie DXY, kalendarz FRED, IV z ręcznego importu.

**Drogi składania zleceń (pełna lista):**

| Ścieżka | Moment |
|---|---|
| `execution/gateway.py` (`order_send`) | wejście |
| `execution/manager.py` | TP częściowy, BE, sync TP, wyjście czasowe, zamknięcie na żądanie |
| `execution/paper.py` | symulacja – bez terminala |

Innych wywołań `order_send` w kodzie nie ma (grep).

## 2. Rejestr usterek i zmian

| ID | P | Obszar | Problem | Naprawa 1.14 | Test |
|---|---|---|---|---|---|
| B-01 | P1 | symbole | aplikacja przyjmowała dowolny symbol: skaner wszystkich rynków, `/markets/*` z dowolnym symbolem, `PUT /config` z `mt5.symbol`; wymaganie: wyłącznie XAUUSD i BTC | `assets/registry.py`: allowlista na wejściu danych (bridge), w API, treningu, skanerze, powiadomieniach i bramce wykonania; mapowanie wyłącznie po metadanych i potwierdzeniu; `PUT /config` nie zmienia symbolu ani blokady | `test_lab.TestSymbolLock`, `test_ui_lab.test_02` |
| B-02 | P1 | wykonanie | brak globalnej blokady – tryby AUTO_DEMO/AUTO_LIVE mogły wysłać zlecenie po spełnieniu bramek | **Execution Lock**: proxy modułu MT5 w workerze odrzuca każde `order_send` (dowolna ścieżka); bramka i menedżer pozycji sprawdzają blokadę jawnie (bez modyfikacji pozycji); odblokowanie tylko frazą w Ustawieniach; migracja ustawia LOCKED dla wszystkich | `TestExecutionLock`, `test_ui_lab.test_02` |
| B-03 | P1 (wykryte w 1.14 przy przełączaniu) | analityka 1.13 | cache wyników kluczowany bez symbolu – po zmianie aktywa panel „Co wspiera analizę” pokazywał wartości złota dla BTC | symbol w kluczu; pełne czyszczenie stanu przy zmianie symbolu | zrzut `data/logs/ui_lab/btc_*`, `TestEndToEnd` |
| B-04 | P1 | bridge | po zmianie symbolu bufory TF przez chwilę zawierały świece poprzedniego symbolu | `buffer_symbol`; `bars()` zwraca pustą listę, dopóki bufory nie należą do bieżącego symbolu | `TestEndToEnd.test_xauusd_then_btc` |
| B-05 | P2 | strategie | S01–S12, scalp i gold_candles są skalibrowane dla XAUUSD (M01 odrzuca inne `instrument_id`) | dla BTC: jawne `LEGACY_ENGINE_XAUUSD_ONLY` / `UNSUPPORTED_ASSET`; scenariusze BTC tylko z silnika lab | `TestEndToEnd`, UI |
| B-06 | P2 | ML DT/XGB | trening na setupach S01–S12 – nie dotyczy BTC | trening zablokowany dla BTC z powodem; ścieżka per aktywo w lab | przegląd kodu |
| B-07 | P3 | ACD | pierwsza wersja optymalizatora startowała poza obszarem α+β<1 | parametryzacja wymuszająca ograniczenia | `TestTicks` |
| B-08 | P3 | kontrola negatywna | kontrola „etykiety opóźnione” była źle zaprojektowana (przeszła etykieta jest wyznaczalna z bieżących cech) | zastąpiona kontrolą `FUTURE_SHIFTED_LABELS` z purgingiem | `TestProtocol` |
| A-06 | P2 | replay | spread z pola świecy (z 1.13) | nadal otwarte – wymaga ticków | – |

## 3. Czego nie dało się sprawdzić

- Prawdziwy terminal: metadane `XAUUSD-` u brokera, nazwa i kontrakt BTC (np. `BTCUSD`), sesje, `copy_ticks_from`, `trade_calc_mode`.
- Treść źródeł MQL5 i prac naukowych (sieć) – implementacje są własne i tak opisane.
- Trening i walidacja na danych rynkowych – brak historii; tylko testy techniczne na danych syntetycznych.
- Audyt podatności zależności (`pip-audit`, `npm audit`) – brak sieci.

## 4. Ocena

**Co jest zrobione (technicznie):**
- dwa aktywa egzekwowane w kodzie;
- Execution Lock aktywny i przetestowany;
- spójna ścieżka danych → panel dla obu aktywów na symulatorze;
- rejestr M01–M42 bez maskowania braków.

**Czego nie ma:**
- **Brak zwalidowanego rynkowo modelu ani scenariusza.**
- **Nie jest to deklaracja gotowości do handlu.**
