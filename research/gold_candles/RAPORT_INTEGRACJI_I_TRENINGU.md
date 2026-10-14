# Raport: integracja gold_candles z MasterQUO i trening prognoz XAUUSD- (2026-10-14)

## 0. Status w jednym zdaniu
- **Integracja: wykonana i przetestowana.**
- **Trening na rynku: BLOCKED_NO_REAL_DATA.** To środowisko (kontener Linux w chmurze) nie ma dostępu do Twojego MT5, a w repozytorium są tylko dane syntetyczne.
- Nie wytrenowano i nie zapisano żadnego modelu rynkowego. Monitor pokazuje `NO_MODEL`.

Cztery oddzielne statusy:

| Status | Wynik |
|---|---|
| poprawność programu | testy PASS (sekcja 6) |
| jakość modelu ceny | nieoceniona – brak danych |
| rentowność strategii | `STRATEGY_BACKTEST_NOT_AVAILABLE` |
| zgoda na zlecenie | zawsze `BLOCKED` |

## 1. Co zmieniono i jak płyną dane
- `backend/gold_candles/` – moduł referencyjny **bez zmian**. Hashe 9 plików i testu są zgodne z `MANIFEST.json`. Pakiet i dokumenty: `research/gold_candles/reference/`.
- `backend/gold_candles_runtime/` – działa w izolowanym `.venv_candles`:
  - `worker.py` – proces analityki, JSON lines; model wczytywany raz;
  - `plan_train.py` – trening z zamrożonym planem;
  - `registry_cli.py`, `validate.py`, `common.py`.
- `backend/masterquo/forecast/`:
  - `service.py` – ForecastService SHADOW: zamknięte M5/M30 z sesji bota, statusy, log prognoz przed wynikiem i ich późniejsza ocena;
  - `export.py` – `python -m masterquo export-candles`;
  - `double_retest.py` – maszyna stanów strategii v2.
- Pozostałe zmiany:
  - konfiguracja: sekcja `forecast` (tylko SHADOW, przełączniki wykonania wyłącznie `false`);
  - baza: migracja `0011_forecast_shadow`;
  - API: `GET /api/v1/forecast`, `GET /api/v1/forecast/shadow`, `POST /api/v1/forecast/reload`;
  - monitor: Wykresy bota → „Świece i prognozy”.
- Szczegóły przepływu, polecenia i rollback: `docs/PROGNOZY_SWIECE_GOLD_CANDLES_PL.md`.
- **Moduł nie zamyka i nie reinicjalizuje sesji MT5 bota.** Referencyjne `read_mt5()` nie jest używane.

## 2. Dane
- **Rzeczywiste:** brak (BLOCKED_NO_REAL_DATA).
- **Eksport:** gotowy i sprawdzony na symulatorze terminala. Zapis jest oznaczony `SYNTHETIC_TEST`, bo symulator nigdy nie daje `REAL_USER_DATA`.
  - Na symulatorze: 18 144 zamkniętych M5 i 3 024 M30 z 79 dni. M30 zgodne z 6×M5. 0 rewizji. Weekendy rozpoznane jako przerwy.
  - Test z wstrzykniętą świecą o błędnej geometrii: świeca odrzucona i wykazana w raporcie.
- **Czas:** eksport i inference używają konwencji bota – czas serwera przeliczony na UTC zmierzonym offsetem albo per świeca modelem NY_CLOSE, gdy zgadza się z pomiarem.
  - Moduł referencyjny zakłada epoch UTC; w tej integracji jest to rozstrzygnięte jedną ścieżką danych.
  - Pierwszy rzeczywisty eksport pokaże `dst_model` i `offset_basis` w `source_metadata.json`.

## 3. Treningi
| Run | Dane | Polecenie | Exit | Próbki | Charakter |
|---|---|---|---|---|---|
| rzeczywisty 5/15/30 | — | — | — | — | **NIE URUCHOMIONY – BLOCKED_NO_REAL_DATA** |
| test programu A | syntetyczny generator, 24 445 M5 | `plan_train --data-kind SYNTHETIC_TEST` | 0 | fit ≈ 14 200 / kal. ≈ 4 850 / holdout ≈ 5 120 na horyzont | test kodu, 72 s, nieaktywowalny |
| test programu B | eksport z symulatora terminala | `plan_train --latest --data-kind SYNTHETIC_TEST` | 0 | holdout 16 dni | test kodu, 59 s; runtime check 39/40 + 1 warmup |

Wyniki testów programu nie mają znaczenia rynkowego, dlatego nie ma tu tabeli jakości. Na danych syntetycznych modele wychodzą `REJECTED` lub `SHADOW_UNVALIDATED`, zgodnie z oczekiwaniem.

## 4. Ścieżki (po uruchomieniu na Windows)
| Co | Gdzie |
|---|---|
| historia | `data\forecast\history\<cutoff>\` – `XAUUSD_M5.csv`, `XAUUSD_M30.csv`, `source_metadata.json`, `DATA_QUALITY_REPORT.json`, `TRAINING_PLAN.json`, `chunks\` |
| modele | `data\forecast\runs\<run_id>\` – `forecast_model.json`, `forecast_validation.json`, `TRAINING_PLAN.json`, `run_log.jsonl`, `checkpoint_h*.json` |
| rejestr | `data\forecast\registry.json` |
| launchery | `10_PROGNOZY_INSTALUJ.bat`, `11_EKSPORT_HISTORII_XAUUSD.bat`, `12_TRENING_MODELI_XAUUSD.bat`, `13_WALIDACJA_MODELI_XAUUSD.bat`, `14_ROLLBACK_MODELU_PROGNOZ.bat`, `15_START_PROGNOZ_SHADOW.bat` |

## 5. Tabela jakości 5/15/30
Brak – wymaga rzeczywistej historii. `12_TRENING_MODELI_XAUUSD.bat` zapisze dla każdego horyzontu:
- daty i końce etykiet, liczebność klas i dni;
- Brier, log loss, balanced accuracy, recall i ECE dla każdej klasy, krzywe niezawodności;
- pokrycie q10–q90, MAE mediany;
- porównanie z baseline i z modelem bez formacji, z przedziałami z bootstrapu bloków dni;
- podział na sesje;
- status, zawsze z powodami.

## 6. Testy wykonane w tym środowisku
| Zestaw | Wynik |
|---|---|
| `tests/gold_candles/test_candles.py` (29 testów modułu referencyjnego, `.venv_candles`) | 29/29 OK |
| `tests/gold_candles/test_runtime.py` (7) | OK |
| `tests/test_forecast_integration.py` (10, środowisko bota) | OK |
| pełny `tools/run_tests.py` (2026-10-14 17:46 UTC) | 307 testów bota OK + 36 testów modułu prognoz OK (`.venv_candles`) |

`test_runtime.py` sprawdza:
- protokół workera;
- wspólne granice UTC i purge;
- zamrożenie planu względem danych;
- INSUFFICIENT_DATA z brakującą ilością;
- rejestr odrzucający model syntetyczny;
- NO_MODEL z `probabilities = null`;
- SHADOW: suma prawdopodobieństw = 1, kwantyle uporządkowane i skończone;
- CONTRACT_MISMATCH (tick size), odrzucenie innego symbolu, model z przyszłości;
- zmodyfikowany artefakt → NO_MODEL;
- przerwę weekendową, warmup i odporność na błędne żądanie.

`test_forecast_integration.py` sprawdza:
- maszynę v2: pełna sekwencja BUY i lustrzany SELL; determinizm, czyli restart nie dubluje setupów, a przyszłe świece nie zmieniają przeszłych; brak świecy potwierdzenia; luka danych; zbyt głęboki probe; rodzina CONTINUATION; doji/inside bar nie są triggerem; nigdy READY;
- konfigurację tylko SHADOW;
- brak środowiska → status zamiast awarii, brak zleceń;
- ocenę SHADOW wyłącznie dokładnym i ciągłym celem;
- eksport na symulatorze: SYNTHETIC_TEST, odrzucona geometria, tylko zamknięte świece.

**Pomiar runtime** (serwer demo na symulatorze, proces roboczy z modelem testowym):
- analiza 256–385 ms;
- pełny cykl 323–406 ms po każdej zamkniętej M5;
- szczyt pamięci procesu roboczego ok. 158 MB.

To pomiar w kontenerze Linux, nie na Twoim komputerze.

## 7. SHADOW, ograniczenia, rollback
**Stan SHADOW:**
- Moduł działa po instalacji `.venv_candles`.
- Bez modelu pokazuje formacje, setup v2 i `NO_MODEL`.
- Z modelem pokazuje prognozy oznaczone SHADOW, zapisuje je przed wynikiem i ocenia po upływie horyzontu.

**Ograniczenia:**
- brak historii tickowej, a więc brak tickowego backtestu;
- kalendarz sesji brokera nieznany (pewna jest tylko przerwa weekendowa);
- brak modelu wyniku transakcji;
- maszyna v2 nie liczy kosztów, wolumenu ani ryzyka;
- Windows, Twój MT5 i rzeczywista historia nie zostały sprawdzone tutaj.

**Rollback:** `14_ROLLBACK_MODELU_PROGNOZ.bat` albo `"forecast": {"enabled": false}`. Szczegóły: `docs/PROGNOZY_SWIECE_GOLD_CANDLES_PL.md`.

## 8. Walidacja modelu ceny ≠ walidacja strategii
- Nawet `SHADOW_VALIDATED` oznacza tylko lepszą od baseline i skalibrowaną prognozę **przyszłego close**.
- Nie jest to P(TP przed SL), win rate ani EV.
- Strategia Double Retest v2 nie ma backtestu P&L z Bid/Ask i kosztami (`STRATEGY_BACKTEST_NOT_AVAILABLE`), więc żaden stan nie daje zgody na zlecenie.
