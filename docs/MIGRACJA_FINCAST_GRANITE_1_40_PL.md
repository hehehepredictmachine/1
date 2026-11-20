# 1.40 – FinCast → IBM Granite TTM, Memory Governor (16 GB), harmonogram AI, trening Granite

## 1. Audyt (stan przed migracją, 1.39)
Ścieżka danych modeli prognoz: **MT5 bridge** (zamknięte świece) → `kronos.quality.check` (kolejność, duplikaty, luki, NaN, geometria OHLC, świeżość) →
**jeden snapshot** na (instrument, TF, ostatnia zamknięta świeca), wspólny dla modeli → proces modelu (`tsfm_runtime.worker`, własne `.venv_*`) →
prognoza zapisana w `tsfm_forecasts` PRZED wynikiem → rozliczenie z rzeczywistymi świecami → **ModelHub** (`modelhub/adapters.py`, kontrakt PMW-PRED-2)
→ **koordynator decyzji** (ścieżka ACTIVE, `decision/coordinator.py` przez `tsfm/predictions.coordinator_rows`) i **odbiorniki SH**
(`sh/service._tsfm`, SCALPING / HEDGING) → ryzyko → wykonanie. Role modeli: OBSERVE (domyślnie) / ASSIST / REQUIRED – tylko po walidacji walk-forward
na danych REAL i z potwierdzeniem; model może jedynie WSTRZYMAĆ wejście.

Odwołania do FinCast poza katalogiem (wszystkie zmienione): `tsfm/settings.py`, `tsfm/service.py`, `tsfm/predictions.py`, `tsfm/validation.py`,
`tsfm_runtime/engines.py|worker.py|install.py|lock.py|vendor/fincast`, `modelhub/catalog.py|adapters.py`, `quant/ids.py|inventory.py`,
`sh/models.py|service.py`, `decision/coordinator.py`, `runtime.py`, `api/app.py`, `FoundationModelsPanel.tsx`, `BotChartsPage.tsx`,
`tools/tsfm_setup.py`, `tools/check_requirements_win.py`, `requirements/requirements-fincast-win.txt`, `38_MODELE_CHRONOS2_FINCAST.bat`, testy.

Punkt przywracania: tag git `pre-1.40-restore-point` (= wydanie 1.39.0). Dane użytkownika nie są usuwane (patrz §8).

## 2. Wybór checkpointu Granite TTM
Źródło: `ibm-granite/granite-timeseries-ttm-r2` (licencja **Apache-2.0**; wariantów research-only z `ibm-research/ttm-research-r2` nie użyto).
Kod: PyPI `granite-tsfm` 0.3.11 (wydanie starsze niż 14 dni). Sprawdzone warianty: R2 `512-96-r2` (gałąź main), `1024-96-r2`,
R2.1 `512-48-ft-r2.1`, `512-96-ft-r2.1` (z prefiksem częstotliwości: token 5min / 15min / h).

**Walk-forward na prawdziwych danych XAUUSD** (HistData M1 2025 – 01.2026, publiczny zbiór `fokan/xauusd-2009-2026` na Hugging Face, agregacja do
M5 / M15 / H1; test 2025-10-01 → 2026-01-09, czyli PO publikacji modeli; punkty startu bez nakładania horyzontów; horyzonty jak w bocie:
M5 12, M15 8, H1 6 świec; pasmo neutralne kierunku 0,25 × ATR14 – reguła bota). To NIE są dane Twojego brokera.

| TF (H) | Model | n | MAE | RMSE | MAE naiwny | skill vs naiwny | trafność kier. (n) | ms / prognoza |
|---|---|---|---|---|---|---|---|---|
| M5 (12) | granite:main | 1611 | 9.26 | 13.28 | 8.47 | -9.3 % | 48.9 % (1088) | 0.25 |
| M5 (12) | granite:512-48-ft-r2.1 | 1611 | 12.02 | 16.80 | 8.47 | -41.8 % | 49.0 % (1272) | 0.22 |
| M5 (12) | granite:512-96-ft-r2.1 | 1611 | 12.84 | 18.12 | 8.47 | -51.6 % | 49.1 % (1320) | 0.23 |
| M5 (12) | granite:1024-96-r2 | 1611 | 9.73 | 13.77 | 8.47 | -14.8 % | 49.8 % (1211) | 0.49 |
| M5 (12) | naive_last | 1611 | 8.47 | 12.42 | 8.47 | +0.0 % | — (0) | — |
| M5 (12) | drift_20 | 1611 | 11.34 | 16.12 | 8.47 | -33.8 % | 46.3 % (1231) | — |
| M5 (12) | chronos2 | 1611 | 8.71 | 12.63 | 8.47 | -2.8 % | 50.6 % (731) | 37.99 |
| M5 (12) | kronos-base | 60 | 12.69 | 17.95 | 8.00 | -58.5 % | 44.4 % (45) | 4423.0 |
| M5 (12) | naive_last(same origins) | 60 | 8.00 | 11.19 | 8.00 | +0.0 % | — (0) | — |
| M15 (8) | granite:main | 805 | 12.81 | 18.11 | 11.72 | -9.2 % | 45.9 % (481) | 0.15 |
| M15 (8) | granite:512-48-ft-r2.1 | 805 | 15.55 | 20.81 | 11.72 | -32.7 % | 45.9 % (601) | 0.14 |
| M15 (8) | granite:512-96-ft-r2.1 | 805 | 15.42 | 20.77 | 11.72 | -31.6 % | 46.3 % (590) | 0.15 |
| M15 (8) | granite:1024-96-r2 | 805 | 13.37 | 18.61 | 11.72 | -14.1 % | 47.6 % (521) | 0.4 |
| M15 (8) | naive_last | 805 | 11.72 | 16.72 | 11.72 | +0.0 % | — (0) | — |
| M15 (8) | drift_20 | 805 | 14.24 | 19.59 | 11.72 | -21.5 % | 51.0 % (578) | — |
| M15 (8) | chronos2 | 805 | 11.96 | 17.19 | 11.72 | -2.0 % | 52.7 % (317) | 19.88 |
| M15 (8) | kronos-base | 40 | 16.45 | 21.98 | 11.82 | -39.1 % | 48.3 % (29) | 2777.5 |
| M15 (8) | naive_last(same origins) | 40 | 11.82 | 16.02 | 11.82 | +0.0 % | — (0) | — |
| H1 (6) | granite:main | 268 | 23.69 | 32.29 | 21.72 | -9.1 % | 46.1 % (165) | 0.13 |
| H1 (6) | granite:512-48-ft-r2.1 | 268 | 29.11 | 37.38 | 21.72 | -34.0 % | 43.3 % (208) | 0.17 |
| H1 (6) | granite:512-96-ft-r2.1 | 268 | 26.51 | 34.87 | 21.72 | -22.0 % | 45.9 % (194) | 0.17 |
| H1 (6) | granite:1024-96-r2 | 268 | 23.59 | 31.30 | 21.72 | -8.6 % | 48.6 % (183) | 0.31 |
| H1 (6) | naive_last | 268 | 21.72 | 29.38 | 21.72 | +0.0 % | — (0) | — |
| H1 (6) | drift_20 | 268 | 24.98 | 33.50 | 21.72 | -15.0 % | 48.9 % (188) | — |
| H1 (6) | chronos2 | 268 | 22.34 | 31.49 | 21.72 | -2.9 % | 57.3 % (96) | 19.97 |
| H1 (6) | kronos-base | 40 | 31.98 | 40.99 | 24.71 | -29.5 % | 41.4 % (29) | 2177.2 |
| H1 (6) | naive_last(same origins) | 40 | 24.71 | 31.66 | 24.71 | +0.0 % | — (0) | — |

Kronos-base: 1 ścieżka próbkowana na prognozę, mniej punktów (CPU ~2–4 s / prognozę); wiersz „naive_last (same origins)” to model naiwny na tych samych punktach.

**Wnioski (uczciwie):** żaden model – Granite, Chronos-2 ani Kronos – nie pokonał prognozy „ostatnia cena” na tych danych (złoto w krótkim
horyzoncie ≈ błądzenie losowe). Trafność kierunku ok. 41–57 % bez istotności. Spośród wariantów Granite najmniejszy błąd dał **R2 512-96 (main)**:
MAE ok. 9 % gorsze od modelu naiwnego, 0,8 M parametrów, ~0,25 ms / prognozę w paczce. Wybrany: `main` @ `d6a79570…` (512 świec kontekstu,
horyzont do 96, bez prefiksu częstotliwości – działa na każdym TF bez mapowania). Rola domyślna: **OBSERVE** – kalibracja i walidacja od zera.

Skrypty i surowe wyniki: `tools/research/tsfm_eval/` (prep.py, eval_granite.py, eval_chronos.py, eval_kronos.py, res_*).

## 3. Integracja Granite TTM
* `tsfm_runtime/lock.py` – przypięta rewizja, rozmiar + SHA-256 / git-blob każdego pliku, `params_measured` 805 280; FinCast: `retired: True`.
* `tsfm_runtime/engines.py: GraniteTTMEngine` – oficjalna klasa `TinyTimeMixerForPrediction` (ładowana bez `tsfm_public/__init__.py`, który
  importuje pandas / sklearn / datasets / pyarrow: **462 → 349 MB RSS**, ten sam kod i wynik), kontrola tożsamości checkpointu (kontekst 512, horyzont 96,
  bez prefiksu), wejście = dokładnie 512 ZAMKNIĘTYCH świec (mniej → WARMUP, bez dopełniania), **normalizacja z-score wyłącznie z okna kontekstu**,
  odwrócenie do jednostek ceny, prognoza **punktowa** (bez kwantyli i świec OHLC – pola nie są wymyślane, `median` nie występuje w kontrakcie),
  selftest z parytetem względem oficjalnego wywołania (|Δ| ≤ 1e-4 × cena; zmierzone 0,00016 przy ~4000).
* Serwis `tsfm/service.py`: ten sam snapshot co Chronos-2, kolejka z deduplikacją po zamkniętej świecy, ledger, rozliczenie (pinball / pokrycie
  tylko dla modeli z kwantylami), porównanie modeli (tylko ta sama świeca / TF / horyzont), stan `RESOURCE_PAUSED` od Memory Governora.
* Kontrakt PMW-PRED-2 (`tsfm/predictions.py`): `model_id tsfm:granite_ttm`, `checkpoint_revision`, `snapshot_id`, `latency_ms`, `freshness`,
  `validation_status`, `data_profile`, horyzont, jednostka `price`, `UNCALIBRATED`, stan + powód (STALE / niedostępny – nigdy głos neutralny).
* Odbiorcy: koordynator ACTIVE, SH SCALPING / HEDGING (`sh/service._tsfm`), katalog modeli SH (`sh/models.py`, grupa korelacji `TSFM_PRICE` –
  Kronos / Chronos-2 / Granite liczone jak jedna grupa, nie trzy niezależne głosy), inwentarz quant, ModelHub, panel „Modele prognoz”, WTC$PEPE.
* FinCast: nie jest instalowany, ładowany ani planowany (silnik, kod `vendor/fincast`, wymagania – usunięte). Jego prognozy w `tsfm_forecasts`
  zostają z `model_id = fincast` (API historii je zwraca), nie są przypisywane Granite; ustawienia z 1.37–1.39 → `settings.v139.bak.json` +
  wpis w `settings_history.jsonl`; role FinCast NIE przechodzą na Granite.

## 4. Memory Governor + harmonogram AI (`backend/masterquo/resources/governor.py`)
Pomiar (bez psutil – WinAPI / /proc): RAM komputera, RSS i szczyt procesu bota oraz każdego procesu modelu. Poziomy profilu LOW_MEMORY_16GB:
**OK < WARN 75 % < LIMIT_HEAVY 80 % < PAUSE_OPTIONAL 85 %**, budżet procesów PMW 6 GB (preferowany) / 8 GB (maks.), rezerwa dla Windows 4 GB.
* PAUSE_OPTIONAL – brak nowych opcjonalnych prognoz (stan STALE z powodem). LIMIT_HEAVY – ciężki model, który nie jest załadowany, nie startuje.
  Granite (lekki) działa do 85 %.
* **Jeden wspólny slot ciężkiej inferencji / ładowania** dla Kronos i Chronos-2 (równoległość 1) – oba serwisy go używają.
* Zwalnianie bezczynnych ciężkich procesów tylko pod presją pamięci (≥ WARN) albo w ECO po 600 s; nigdy Granite, nigdy model w trakcie pracy.
* Wątki CPU procesów modeli z profilu (ciężkie: min(4, rdzenie/2), lekkie: 1–2).
* Trening: brak dwóch ciężkich treningów naraz, brak treningu w tle podczas AUTO_DEMO / AUTO_LIVE bez świadomego potwierdzenia, brak przy presji RAM.
* Dane rynkowe, pozycje, ryzyko i wykonanie **nie pytają** Governora – nigdy nie czekają na model.
* Profile: LOW_MEMORY_16GB (domyślny), ECO, BALANCED, MANUAL (`config.json → resources`, konfiguracja v15; zmiana bez przebudowy,
  `PUT /api/v1/resources/profile`, wpis w logu). Widok: `GET /api/v1/resources`, panel „Modele prognoz → Zasoby” i WTC$PEPE → ACTIVE MODEL MATRIX.
* Profil: lazy loading ON, deduplikacja ON, cache prognoz (ostatnia zamknięta świeca) ON, trening w tle OFF, pobieranie przy starcie OFF,
  CPU fallback ON (CUDA tylko gdy działa; sterowniki nigdy nie są instalowane).

## 5. Trening Granite (Centrum treningu)
Eksport z magazynu świec (ten sam eksport MT5 co inne modele) z walidacją (min. 5000 świec, rosnące czasy, ceny > 0, geometria OHLC, raport luk)
→ osobny proces `.venv_granite` (`tsfm_runtime.granite_finetune`): zamrożony backbone (receptura autorów TTM), podział chronologiczny 70 / 15 / 15 %
z embargo 512 + H świec, wczesne zatrzymanie na walidacji, **wynik na niewidzianych 15 %**, zapis `data/tsfm/finetuned/granite_ttm/GTR-…/`
(config + safetensors + `granite_finetune.json` z SHA-256 i metrykami). Aktywacja tylko ręczna i tylko przy werdykcie IMPROVED_VS_BASE (sumy,
odcisk modelu bazowego i horyzont sprawdzane); powrót: BASE. Przerwanie = nic nie zapisano.

Przykład (HistData XAUUSD M5, 4 epoki, 4 wątki, 223 s): test MAE dotrenowany **8,14** / bazowy 8,44 / naiwny **7,83** → lepszy od bazowego,
NIE lepszy od „ostatniej ceny”. Plik: `tools/research/tsfm_eval/finetune_GTR-TEST-M5.json`.

## 6. Pomiary pamięci i opóźnień (komputer 16 GB)
Komputer pomiarowy: **16 GB RAM**, 4 vCPU Xeon 2,1 GHz, bez GPU (Linux; na Windows wartości RSS są zbliżone, nie zmierzone). Procesy i protokół jak
w bocie (`tools/ram_benchmark.py`, prawdziwe wagi, prawdziwe świece XAUUSD M5 / M15), wątki z profilu LOW_MEMORY_16GB (ciężkie 2, lekkie 1).

| Proces | RSS po starcie | RSS po załadowaniu | szczyt | ładowanie | inferencja M5 p50 / p95 |
|---|---|---|---|---|---|
| Backend bota (FastAPI + silnik + bridge, demo) | – | 431 MB | 455 MB | – | – |
| Granite TTM | 213 MB | 346 MB | 356 MB | 2,7 s | **3,4 / 5,4 ms** |
| Chronos-2 | 215 MB | 600 MB | 835 MB | 3,6 s | 79 / 94 ms |
| Kronos-base | 248 MB | 672 MB | 1062 MB | 3,4 s | 6876 / 7297 ms (CPU, 2 wątki) |

Sekwencyjnie (jak slot Governora), 60 kolejnych zamkniętych świec M5 + co 3. świeca M15, wszystkie trzy modele: 80 prognoz każdego, **0 błędów,
0 OOM**, suma RSS procesów modeli w szczycie **2,02 GB**, RAM systemu w szczycie **11,7 %** (z 16 GB), czas 512 s (dominują próbki Kronos ~7 s).
Razem z backendem: ok. **2,5 GB** procesów PMW – poniżej preferowanego budżetu 6 GB profilu LOW_MEMORY_16GB.
Poprawka w trakcie pomiaru: worker odczytywał wersje pakietów przez ich import (pandas, cały granite-tsfm) – po zmianie na odczyt metadanych
Granite: 469 → 346 MB po załadowaniu. FinCast (1.37–1.39) potrzebował ok. 8 GB w szczycie ładowania – na komputerze 16 GB był głównym ryzykiem OOM.
Surowe wyniki: `tools/research/tsfm_eval/ram_bench_full.json`, `ram_bench2.json`. NOT RUN: GUI aplikacji Windows (WebView2) i prawdziwy MT5 Bridge.

## 7. Testy
`test_tsfm_bot.py` (serwis, kontrakt, rozliczenie, wycofanie FinCast, migracja ustawień), `test_foundation_real.py` (prawdziwe wagi: tożsamość,
parytet, determinizm, brak look-ahead, błędy wejścia, dotrenowanie + ładowanie checkpointu, podmieniony plik odrzucony), `test_resources_governor.py`
(progi, dopuszczanie, wspólny slot, zwalnianie, trening, profile, prognoza wstrzymana = STALE bez wartości), `test_granite_train.py`,
`test_ui_foundation.py`, `test_live_start.py` (konfiguracja v15). Wyniki pełnej regresji: `release/RAPORT_KONCOWY.md`.

NOT RUN (środowisko): Windows i prawdziwy terminal MT5 (bridge testowany na symulatorze), GPU / CUDA (brak karty), porównanie strategii po kosztach
na Twoich danych (brak Twojej historii MT5 – wymagany eksport w Centrum treningu i `39_PAKIET_20_WALIDACJA.bat`).

## 8. Powrót (rollback)
`ROLLBACK.md` 0e: `config.v14.bak.json` → `config.json`, `data/tsfm/settings.v139.bak.json` → `settings.json`, uruchomienie folderu 1.39.0
i ponowna instalacja FinCast (`38_MODELE_CHRONOS2_FINCAST.bat` z folderu 1.39). Baza i historia prognoz są wspólne (1.40 nie dodaje migracji bazy).
