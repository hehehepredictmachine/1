# Raport wersji 1.3.0 – kolory, niezależny zoom, Decision Tree + XGBoost, tryby ACTIVE

Środowisko testów: Linux, CPython 3.13.16, scikit-learn 1.9.1, xgboost 3.4.1, numpy 2.5.3, Chromium (Playwright), symulator terminala
(`FakeMT5`). **Wszystkie testy działały na danych syntetycznych.** Nie łączyłem się z Twoim terminalem MT5 i nie złożyłem żadnego
zlecenia na Twoim rachunku – połączenie z Twoim MT5 jest **NIE SPRAWDZONE** do czasu uruchomienia `02_DIAGNOSTYKA.bat` u Ciebie.

## 1. Przyczyna wspólnego zoomu (naprawiona)
1. Każda pełna analiza (zamknięcie świecy dowolnego TF, 60 s, resync) zwiększała globalny `analysisSeq` → **wszystkie** wykresy
   pobierały świece od nowa, a krok renderowania usuwał i dodawał serie wskaźników, RSI/MACD i panele (`removePane`). Lightweight Charts
   resetował wtedy skalę czasu na wszystkich wykresach jednocześnie – wyglądało to jak jeden wspólny zoom.
2. Opcja „Synchronizacja” rozsyłała widoczny zakres jednego wykresu do wszystkich pozostałych, a obsługa celownika trzymała nieaktualną
   kopię opcji.

Naprawa (`frontend/src/components/ChartPanel.tsx`, `frontend/src/chartview.ts`): serie tworzone raz i tylko aktualizowane; przed i po
każdym odświeżeniu zapis/odtworzenie widoku (kotwica czasowa – starsze świece doładowane z lewej nie przesuwają widoku); osobny stan
widoku per `chart_id + symbol + TF` (wersjonowany localStorage), zmieniany wyłącznie działaniami użytkownika (kółko, przeciągnięcie,
gest, przyciski); tryb śledzenia najnowszej świecy jako osobny stan; synchronizacja zakresu domyślnie wyłączona i tylko w wybranej
grupie A/B (bez pętli – odebrany zakres nie jest rozsyłany dalej); wspólny celownik osobnym przełącznikiem; sprzątanie subskrypcji.

## 2. Usunięty READONLY
* `execution.mode` = SIGNALS („Analiza warunków”) / PAPER / AUTO_DEMO / AUTO_LIVE, zapisywany w konfiguracji (config v3, migracja
  0003 zmienia stare nazwy w historii). Nie ma już resetu do READ_ONLY po restarcie / zmianie limitów / zmianie rachunku.
* Pierwszy start: PAPER. Wcześniejszy wybór użytkownika jest zachowany. Stara nazwa `READ_ONLY` przychodząca z API = SIGNALS.
* Typ rachunku i login z terminala; niezgodność (inny rachunek, AUTO_DEMO na REAL, AUTO_LIVE na DEMO/danych syntetycznych) blokuje
  zlecenia z dokładnym kodem; tryb zostaje. W AUTO brak potwierdzania pojedynczych transakcji. STOP = tylko nowe wejścia.
* Flagi `research_only` w dołączonym, niezmienianym kodzie oryginalnego MasterQUO (`backend/vendor`) nie są bramką w aktywnej
  konfiguracji – opisują status badawczy strategii M07 (dokumentacja, nie blokada).

## 3. Punkty integracji ML
| Miejsce | Plik | Co robi |
|---|---|---|
| Kolektor | `engine/active.py` → `ml/service.py:on_setup_events` | próbka przy NEW_/STAGE_CONFIRMED każdej wersji setupu |
| Etykiety | `ml/service.py:label_once` (co 30 s) | zamknięte M1 z bridge + bufor kwotowań |
| Harmonogram | `ml/service.py:check_once` (co 60 s) | gotowość, start treningu, poll procesu, monitoring |
| Trener | `ml/trainer.py` (osobny proces) | DT + XGB, kalibracja, test, raport |
| Rejestr | `ml/registry.py` | promocja wg reguł, rollback |
| Drzewo decyzji | `engine/decision.py` węzeł ML, `engine/service.py:_ml_gate` | OFF/SHADOW nie blokują, ASSIST poniżej progu = FAIL |
| Ranking AUTO | `strategies/selector.py` `ml_bonus` | tylko ASSIST, premia rankingowa |
| API | `api/app.py` `/api/v1/ml/*` | status, mode, collect, pause, train, cancel, resume, rollback, models, report, explain, predict, backfill |
| Monitor | `components/MLPanel.tsx`, `Header.tsx` | panel ML, chip „ML tryb · status” |

## 4. Wyniki testów (ten raport)
`python tools/run_tests.py` → **135 testów, 0 błędów** (w tym 24 testy ML, 2 checklisty, 8 testów przeglądarkowych).
Przykładowy przebieg end-to-end na symulatorze: backfill 18 dni → 556 próbek (496 z etykietą, 39 MISSING_DATA, 19 NO_ENTRY,
1 AMBIGUOUS) → trening DT + XGB w 2,3 s → oba modele odrzucone przez reguły promocji (66 próbek testu < 150) – **zgodnie z oczekiwaniem**;
na danych syntetycznych nie ma przewagi do nauczenia i to nie jest wynik handlowy.

## 5. Do sprawdzenia na Twoim komputerze (NIE WYKONANE tutaj)
1. `01_INSTALUJ.bat` – instalacja nowych pakietów (scikit-learn, xgboost, scipy, joblib, threadpoolctl, narwhals, cloudpickle) z hashami
   (zweryfikowane pobranie wheeli win_amd64 dla cp312 i cp313).
2. `02_DIAGNOSTYKA.bat` – nowe pozycje: import sklearn/xgboost i test działania obu modeli; połączenie z Twoim terminalem i typ rachunku.
3. Monitor: zoom na każdym wykresie osobno, przyciski, kolory na Twoim monitorze/skalowaniu Windows.
4. Tryb AUTO_DEMO na rachunku DEMO (numer wpisany raz); sprawdź, że AUTO_DEMO na rachunku REAL jest zablokowany.
5. Po kilku dniach: panel ML – liczności, etykiety, brak AMBIGUOUS w nadmiarze (bufor kwotowań działa od startu aplikacji).

## 6. Wymaganie → pliki → test → wynik
| # | Wymaganie | Pliki | Test | Wynik |
|---|---|---|---|---|
| 1 | Pełna paleta kolorów, picker HSV/HEX/RGB/HSL/alfa, presety, import/eksport z walidacją, kontrast, trwałość | `frontend/src/theme.tsx`, `components/ThemeDialog.tsx`, `styles.css` | `test_ui_monitor` 04, 06, 07 | PASS |
| 1a | Zmiana motywu bez odtwarzania wykresu i utraty zoomu | `ChartPanel.tsx` (applyOptions) | `test_ui_monitor` 04 | PASS |
| 1b | GIF: przyciemnienie/przezroczystość, bez przechwytywania kliknięć | `appearance.tsx`, `styles.css` | `test_ui_monitor` 01 (kliknięcia/kółko przez warstwę) | PASS |
| 2 | Niezależny zoom per wykres | `ChartPanel.tsx`, `chartview.ts` | `test_ui_monitor` 01 | PASS |
| 2a | Brak resetu przy ticku/odświeżeniu/reconnect | `ChartPanel.tsx` (restoreView) | `test_ui_monitor` 02 | PASS |
| 2b | Przyciski +, −, Dopasuj, Najnowsza, auto-skala | `ChartPanel.tsx` | `test_ui_monitor` 03 | PASS |
| 2c | Resize nie zmienia stanu widoku; trwałość po odświeżeniu | `ChartPanel.tsx`, `chartview.ts` | `test_ui_monitor` 05, 06 | PASS |
| 2d | Synchronizacja domyślnie OFF, grupy, celownik osobno | `chartview.ts`, `ChartPanel.tsx` | `test_ui_monitor` 01 (inne wykresy bez zmian) | PASS |
| 3 | Brak przyszłych danych w cechach, potwierdzone pivoty, braki ≠ 0 | `ml/features.py` | `test_ml.TestNoLookAhead` | PASS |
| 3a | Nakładające się okna etykiet: purging/embargo, grupy zdarzeń | `ml/validation.py` | `test_ml.TestValidation` | PASS |
| 4 | Etykiety: SL/TP w jednej świecy, kwotowania, luki, częściowe zamknięcie, restart bez podwójnej etykiety | `ml/labels.py`, `ml/dataset.py` | `test_ml.TestLabels` (7) | PASS |
| 5 | DT i XGB: trening, zapis, odczyt, spójność po restarcie, wyjaśnienia | `ml/models.py`, `ml/trainer.py` | `test_ml.TestModels.test_both_models_*` | PASS |
| 6 | Fallback: brak modelu, uszkodzony model, jedna klasa, NaN, nieznana kategoria | `ml/service.py`, `ml/registry.py`, `ml/models.py` | `TestModels`, `TestService.test_no_model_*` | PASS |
| 7 | Challenger: kryteria, porównanie z championem, rollback z preprocessingiem i kalibratorem | `ml/registry.py` | `test_registry_promotion_rules_and_rollback_restores_bundle` | PASS |
| 7a | Trener: lock, timeout, przerwanie i wznowienie na tym samym snapshocie | `ml/service.py` | `test_job_lock_timeout_and_interrupted_recovery` | PASS |
| 8 | READONLY usunięty; PAPER bez zleceń do brokera; AUTO_DEMO odrzuca rachunek REAL | `execution/modes.py`, `config.py`, migracja 0003 | `test_risk_execution` (mode, paper), `test_app_process` 02 | PASS |
| 9 | Timeout/restart bez podwójnego wykonania, STOP i limity | `execution/gateway.py`, `modes.py` | `test_risk_execution.test_timeout_*`, `test_mode_*` | PASS |
| 10 | Przepływ end-to-end MT5(symulator) → strategie → próbki → etykiety → trening w procesie → rejestr | `ml/backfill.py`, `ml/service.py` | `test_end_to_end_backfill_train_register_predict` | PASS |
| 10a | Węzeł ML w drzewie decyzji, ASSIST blokuje poniżej progu, SHADOW nie | `engine/decision.py`, `ml/service.py` | `test_assist_blocks_below_threshold_with_champion` | PASS |
| 11 | Checklista 12A (spełnione/brakuje/wyzwalacz/unieważnienie, „brak danych”, „brak scenariusza”) | `engine/checklist.py`, `components/Checklist.tsx` | `test_checklist`, `test_ui_monitor` 08 | PASS |
| 12 | Panel ML 12B z przyciskami do backendu, osobne chipy statusu | `components/MLPanel.tsx`, `Header.tsx` | `test_ui_monitor` 08 | PASS |
| 13 | Zależności przypięte z hashami (Windows cp312/cp313), diagnostyka importów i działania | `requirements/requirements-win.txt`, `diagnostics.py` | weryfikacja `pip download --require-hashes` + domknięcie zależności | PASS (pobranie), instalacja na Windows: NIE SPRAWDZONA |
| 14 | Połączenie z Twoim MT5 | – | – | **NIE SPRAWDZONE** (brak dostępu do Twojego terminala) |
