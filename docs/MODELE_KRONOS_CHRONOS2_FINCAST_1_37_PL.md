# Trzy przetrenowane modele prognoz w PepeMarketWizard 1.37 – Kronos-base, Chronos-2, FinCast

Bot liczy lokalnie, na **zamkniętych** świecach z MT5, prognozy trzech przetrenowanych modeli. Każdy działa w osobnym procesie i we
własnym środowisku Pythona. Domyślna rola każdego modelu to **OBSERVE** (tylko pokazywanie i zapis do historii). Żaden model nie otwiera
pozycji, nie zmienia trybu rachunku (w tym nie włącza AUTO_LIVE) i nie omija Execution Lock, limitów ryzyka, kontroli spreadu,
deduplikacji zleceń ani STOP.

## 1. Który model i dlaczego

| Model | Checkpoint (przypięta rewizja) | Parametry | Licencja | Co prognozuje |
|---|---|---|---|---|
| **Kronos-base** | `NeoQuasar/Kronos-base` @ `2b554741eca47781b64468546e77fef3e85130e6` + `NeoQuasar/Kronos-Tokenizer-base` @ `0e0117387f39004a9016484a186a908917e22426` | 102,3M (zmierzone 102 310 592) | MIT (kod), wagi wg karty | ścieżkę świec OHLC (próbkowanie, T=1, top_p 0,9) |
| **Chronos-2** | `amazon/chronos-2` @ `29ec3766d36d6f73f0696f85560a422f50e8498c` | 120M | Apache-2.0 | zamknięcie: kwantyle 0,1/0,5/0,9; punkt = **mediana** |
| **FinCast** | `Vincent05R/FinCast` @ `2d7d90b159db8961d27c2cf165d51195902ef92b` | ok. 1B (zmierzone 991 436 960) | Apache-2.0 | zamknięcie: **średnia** + kwantyle 0,1…0,9 |

**Dlaczego Kronos-base, a nie Kronos-large.** Masterprompt wymagał największego dostępnego Kronosa. Autorzy opisują Kronos-large
(499,2M), ale nie jest on publicznie udostępniony: nie ma go na karcie modelu ani na liście repozytoriów organizacji NeoQuasar na
Hugging Face (sprawdzone podczas wdrożenia). Największy publiczny wariant to Kronos-base. Bot **nie** przechodzi po cichu na Small/Mini:
gdy brakuje pamięci albo wag, stan to RESOURCE_LIMIT / NO_WEIGHTS z przyczyną.

**Migracja z Kronos-small (1.36).** Ten sam serwis i ten sam proces – nie ma drugiej instancji Kronosa. Po aktualizacji Kronos pokazuje
„brak zweryfikowanych wag”, dopóki nie uruchomisz `33_KRONOS_INSTALUJ.bat` (albo przycisku „Zainstaluj model Kronos”). Historyczne rekordy
„Kronos-small” w bazie zachowują nazwę i rewizję (`history` zwraca `model_name` z rewizji zapisanej przy prognozie).
Pliki regresji autorów dotyczą Kronos-small, więc ich test ma status **NOT_APPLICABLE**; zamiast niego „Sprawdź instalację” wykonuje test
zgodności (parity): wynik adaptera bota = bezpośrednie wywołanie `KronosPredictor.predict` z tymi samymi danymi i ziarnem.

## 2. Instalacja

Kronos-base: `33_KRONOS_INSTALUJ.bat` (CPU) albo `33_KRONOS_INSTALUJ.bat cu126` / `cu128` (GPU NVIDIA).

Chronos-2 i FinCast:

```bat
38_MODELE_CHRONOS2_FINCAST.bat
38_MODELE_CHRONOS2_FINCAST.bat chronos2
38_MODELE_CHRONOS2_FINCAST.bat fincast
38_MODELE_CHRONOS2_FINCAST.bat all cu126
38_MODELE_CHRONOS2_FINCAST.bat all "" D:\wagi
```

Ostatni wariant to instalacja **offline** z katalogu z wcześniej pobranymi plikami: skopiuj do niego foldery `właściciel__repo@rewizja`
(np. `amazon__chronos-2@29ec3766…`) z `data\tsfm\models\chronos2` i `data\tsfm\models\fincast` innego komputera (dla jednego modelu mogą to być same pliki);
każdy plik i tak musi zgadzać się co do rozmiaru i SHA-256 z `lock.py`. To samo robią przyciski „Zainstaluj” / „Sprawdź” w panelu.

Kroki instalatora (`tools/tsfm_setup.py`, log w `data\logs\instalacja_chronos2_fincast_*.log`):
1. Python 3.13/3.12 x64, sprzęt (RAM, wolne miejsce, GPU przez `nvidia-smi`). FinCast przy < 12 GB RAM dostaje ostrzeżenie.
2. Osobne środowisko `.venv_chronos2` / `.venv_fincast` (główne `.venv` i `.venv_kronos` nie są zmieniane). Brak `pip` w środowisku → `ensurepip`.
3. Pakiety z `requirements\requirements-chronos2-win.txt` / `requirements-fincast-win.txt` – na Windows wyłącznie z sumami SHA-256
   (`--require-hashes --only-binary=:all:`), PyTorch CPU z PyPI; z `cu126`/`cu128` torch z indeksu PyTorch (bez sumy – zaznaczone w logu).
4. Wagi z Hugging Face w przypiętej rewizji, z wznowieniem przerwanego pobierania (`.part`), sprawdzenie rozmiaru i SHA-256 każdego
   pliku, atomowy zapis `tsfm_manifest.json`. Wagi trafiają do `data\tsfm\models` (nie do paczki programu).
5. Weryfikacja offline: sumy, jednorazowe ładowanie, tożsamość (repo, rewizja, liczba parametrów), prognoza testowa, parity z oficjalnym API.

Bezpieczeństwo ładowania: Chronos-2 – safetensors; FinCast – oficjalny `.pth` ładowany przez `torch.load(weights_only=True)` i
`load_state_dict(strict=True)`. Nie ma wykonywania dowolnych obiektów pickle ani `strict=False`.

## 3. Zasoby i czasy (zmierzone w środowisku wdrożenia: Linux, CPU, 16,9 GB RAM, bez GPU)

| Model | Dysk (środowisko + wagi) | RAM po załadowaniu | Ładowanie | Prognoza (12 świec, kontekst 512) |
|---|---|---|---|---|
| Kronos-base | ok. 1,3 GB + 0,4 GB | ok. 1,1 GB | 1,4–3 s | 3,9 s osobno; 6,9–9,3 s w działającym bocie (próbkowanie autoregresyjne, wspólny CPU) |
| Chronos-2 | ok. 1,3 GB + 0,46 GB | 0,4–0,9 GB | 0,5–42 s (pierwsze uruchomienie dłużej) | 50–72 ms osobno; p50 0,9–1,2 s w bocie (wspólny CPU z dwoma pozostałymi modelami) |
| FinCast | ok. 1,5 GB + 3,7 GB | **ok. 8,0 GB** (szczyt) | 14–150 s | 0,34–0,56 s osobno; p50 0,7–2,7 s w bocie |

FinCast potrzebuje ok. 8 GB wolnej pamięci przy ładowaniu (float32 na CPU). Przy braku pamięci stan RESOURCE_LIMIT – bot działa dalej bez niego.
Instalacja z czystego folderu (Linux, tryb deweloperski): Chronos-2 3 min 51 s, FinCast ok. 20 min (w tym pobranie ok. 4 GB wag i ok. 1 GB pakietów przy wolnym łączu).

## 4. Jak modele są połączone z botem

* **Dane**: jedna migawka zamkniętych świec na (instrument, interwał, świeca) wspólna dla Chronos-2 i FinCast; Kronos liczy w swoim serwisie
  na tych samych świecach. Bez normalizacji po stronie bota i bez uzupełniania luk; czasy docelowe z kalendarza sesji.
* **Historia i rozliczanie**: tabela `tsfm_forecasts` (migracja 0026) – prognoza zapisywana **przed** wynikiem; po zamknięciu świecy docelowej
  liczone są błąd, błąd „ostatniej ceny”, pinball i pokrycie pasma 80%.
* **Kontrakt PMW-PRED-2**: `task_type` REGRESSION, jednostka cena, kalibracja UNCALIBRATED (Chronos-2/FinCast) / NOT_APPLICABLE (Kronos).
  Regresja **nie jest** zamieniana na prawdopodobieństwo (bez sigmoidu, softmaxu i przypisywania procentów zgodnym modelom).
* **ModelHub, koordynator (ACTIVE) i SH (SCALPING / HEDGING)** widzą wiersze `tsfm:chronos2`, `tsfm:fincast` i `kronos:Kronos-base@<TF>`.
  Kierunek: UP / DOWN / FLAT z reguły pasma neutralnego `max(0,25 × ATR14, min. punktów)`.
* **Role** (osobno dla ACTIVE, SCALPING, HEDGING):
  * **OBSERVE** (domyślnie) – tylko informacja;
  * **ASSIST** – aktualna prognoza przeciwna do setupu → WAIT; brak / nieaktualna prognoza nic nie zmienia;
  * **REQUIRED** – brak modelu, nieaktualna prognoza, kierunek przeciwny albo FLAT → brak wejścia.
  ASSIST i REQUIRED można ustawić **tylko** przez `/api/v1/models/foundation/use` (lub przyciski w panelu), z potwierdzeniem, i tylko gdy
  istnieje pozytywny raport walidacji walk-forward na **danych rzeczywistych** dla bieżącego powiązania (checkpoint, symbol, interwał, horyzont,
  kontekst, profil, pasmo). Zmiana checkpointu lub parametrów unieważnia dopuszczenie (stan STALE → REQUIRED wstrzymuje wejścia).

## 5. Walidacja walk-forward (PMW-TSFM-WF-1)

Przycisk „Uruchom walidację” w panelu (albo `POST /api/v1/models/foundation/validate`). Punkty startu co H świec, podział DEV 60% / TEST 40%,
te same punkty dla trzech modeli (tabela „wspólne”), porównanie z prognozą „ostatnia cena” i momentum: MAE, RMSE, trafność kierunku z testem
dwumianowym, pinball, pokrycie i szerokość pasma 80%. Raporty: `data\tsfm\reports`. Werdykt pozytywny wymaga m.in. danych rzeczywistych,
≥ 100 obserwacji kierunku, MAE niższego od „ostatniej ceny”, trafności wyższej od momentum i p < 0,05. Modele nie są łączone (brak wag bez
osobnej walidacji). Zastrzeżenie: modele mogły widzieć podobne dane w pretreningu – wynik walidacji to warunek konieczny, nie dowód przewagi.

**Przebieg w środowisku wdrożenia** (symulator terminala, dane SYNTETYCZNE, XAUUSD M5, H = 12, 60 punktów startu: DEV 36 / TEST 24,
wszystkie trzy modele odpowiedziały na 24/24 punkty testowe, 351 s, raport `XAUUSD_M5_20261109T005225956040Z`):

| Model | MAE | MAE „ostatnia cena” | RMSE | Kierunek (momentum, n) | p | Pinball / pokrycie 80% | Werdykt |
|---|---|---|---|---|---|---|---|
| Chronos-2 | 3,53 | 3,67 | 4,31 | 75,0% (75,0%), n = 8 | 0,14 | 1,09 / 79,2% | niepozytywny |
| FinCast | 3,63 | 3,67 | 4,42 | 53,8% (46,2%), n = 13 | 0,50 | 1,15 / 91,7% | niepozytywny |
| Kronos-base | 5,35 | 3,67 | 6,98 | 66,7% (52,4%), n = 21 | 0,09 | — | niepozytywny |

Werdykty są niepozytywne z definicji (dane syntetyczne, za mało obserwacji kierunku). Próba ustawienia Chronos-2 jako ASSIST na tym raporcie
została odrzucona przez serwer (`409 VALIDATION_REQUIRED`). Ten przebieg dowodzi działania procedury, nie jakości prognoz na rynku.

## 6. Panel i API

Strona „Wykresy bota” → zwijana sekcja **„Modele prognoz: Kronos-base · Chronos-2 · FinCast”** (wygląd i nawigacja aplikacji bez zmian):
status, checkpoint, urządzenie, czasy ładowania i prognozy, przyciski Zainstaluj / Sprawdź / Odśwież, wykres zamknięć z liniami prognoz
(przełącznik dla każdego modelu; prognoza nieaktualna – linia kropkowana i komunikat), kwantyle 0,1/0,9 przerywaną linią, tabela porównania
(tylko prognozy dla tej samej świecy, interwału i horyzontu), raport walidacji, role w strategiach.

API: `GET /api/v1/models/foundation`, `…/forecast?model=&instrument=&tf=`, `…/compare`, `…/history`, `…/validation`, `…/job/{name}`;
`PUT …/settings` (bez ról); `POST …/install`, `…/verify`, `…/refresh`, `…/validate`, `…/use`.

## 7. Testy

| Kategoria | Plik | Wynik w środowisku wdrożenia |
|---|---|---|
| Serwis, kolejka, kontrakt, rozliczenie, role, koordynator, SH (atrapa procesu) | `tests/test_tsfm_bot.py` | WYNIK_TSFM_BOT |
| UI + API bez wag (stan uczciwy, blokady ról) | `tests/test_ui_foundation.py` | WYNIK_UI_FOUNDATION |
| **Prawdziwe wagi** Chronos-2 (tożsamość, parity, determinizm, brak look-ahead, błędy wejścia, kowariaty) | `tests/test_foundation_real.py` w `.venv_chronos2` | OK (4 testy; ładowanie 4,6 s, 383 MB, prognoza 72 ms, parity PASS – różnica 0,0) |
| **Prawdziwe wagi** FinCast (j.w. + kwantyle, nieobsługiwane profile/interwały) | `tests/test_foundation_real.py` w `.venv_fincast` | OK (4 testy; ładowanie 15,4 s, 8,0 GB, prognoza 0,6 s, parity PASS – różnica 0,0) |
| Kronos-base runtime (w tym oficjalne wagi: 102 310 592 parametrów, parity PASS, referencja NOT_APPLICABLE) | `tests/test_kronos_runtime.py` | OK (8 testów, z oficjalnymi wagami) |
| Pełny zestaw regresji | `tools/run_tests.py` | WYNIK_FULL |

Testy prawdziwych wag uruchamia się w środowisku modelu:

```bat
set MQ_TSFM_WEIGHTS_ROOT=%CD%\data\tsfm\models
set PYTHONPATH=backend
.venv_chronos2\Scripts\python.exe -m unittest tests\test_foundation_real.py
.venv_fincast\Scripts\python.exe -m unittest tests\test_foundation_real.py
```

Bez środowiska lub wag są pomijane (SKIP) – nigdy nie są udawane.

## 8. Ograniczenia (stan rzeczywisty)

* Środowisko wdrożenia nie miało Windows ani GPU: instalatory i inferencję sprawdzono na Linuksie (CPU) z tymi samymi wersjami pakietów;
  pliki z sumami dla Windows sprawdzono narzędziem `tools/check_requirements_win.py` (każdy pakiet ma koło dla win_amd64/cp313 i sumę),
  ale sama instalacja na Windows nie była uruchomiona. Ścieżka GPU (`cu126`/`cu128`) nie była testowana.
* Walidacja w środowisku wdrożenia była możliwa tylko na danych **syntetycznych** (symulator terminala) – jej werdykt jest z definicji
  niepozytywny i nie mówi nic o rynku. Dopuszczenie ASSIST/REQUIRED wymaga walidacji na Twoich danych MT5.
* Kwantyle Chronos-2/FinCast i pasmo Kronosa są nieskalibrowane na danych brokera.
* Modele widzą tylko świece (Chronos-2 opcjonalnie OHLC + tick volume jako przeszłe zmienne) – nie znają newsów, spreadu, prowizji,
  poślizgu ani pozycji. Zgodność trzech modeli na tych samych świecach nie jest niezależnym potwierdzeniem.

## 9. Rollback

Opis w `ROLLBACK.md` (sekcja „Wersja 1.37.0 → 1.36.0”). Wyłączenie bez cofania wersji: rola „obserwacja” albo `"enabled": false` w
`data\tsfm\settings.json`.
