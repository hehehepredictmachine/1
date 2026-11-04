# Kronos AI Forecast w PepeMarketWizard – instrukcja

Kronos-small to **przetrenowany** model prognozy świec OHLC (autorzy: NeoQuasar / ShiYu, https://github.com/shiyu-coder/Kronos).
Bot go **nie trenuje** – używa oficjalnych wag z Hugging Face i liczy prognozy **lokalnie** na Twoim komputerze. Nie korzysta z płatnego
API i nie wysyła danych rachunku ani historii transakcji na zewnątrz.

**Co robi:** po każdej nowej **zamkniętej** świecy (XAUUSD i BTC; domyślnie M5 i M15) prognozuje ścieżkę kolejnych świec OHLC.
Pokazuje kierunek, zmianę ceny, wykres i pochodzenie danych, zapisuje prognozę i później porównuje ją z faktycznym ruchem.

**Czego nie robi:**
- nie składa zleceń;
- nie zmienia trybu wykonania, przycisku STOP, limitów ryzyka, TP/SL ani ustawień innych modułów.

Domyślnie działa w trybie **SHADOW (obserwacja)**. Gotowość do prognozowania **nie jest** potwierdzoną przewagą handlową.

---

## 1. Wymagania

* Windows 10/11 64-bit. Wystarczy procesor (CPU); karta NVIDIA nie jest wymagana.
* Internet tylko przy pierwszej instalacji. Pobierane są:
  * z PyPI: PyTorch (CPU) i inne pakiety, ok. 250 MB;
  * z Hugging Face: wagi modelu i tokenizera, ok. 120 MB.
* Ok. 1,2 GB wolnego miejsca. Środowisko `.venv_kronos` powstaje obok programu, a wagi trafiają do folderu danych.
* Działający bot PepeMarketWizard 1.31 z podłączonym MT5 (tak jak dotąd).

## 2. Instalacja na Windows

Wybierz jedną z dwóch dróg. Obie robią to samo.

**A) Z panelu:** Wykresy bota → sekcja **Kronos AI Forecast** → **Zainstaluj model Kronos**. Postęp i log są widoczne pod przyciskiem.

**B) Plikiem:** zamknij bota i uruchom `33_KRONOS_INSTALUJ.bat` z folderu programu. Log trafia do `data\logs\instalacja_kronos_*.log`.

Instalator wykonuje 5 kroków:

1. **Python 3.13/3.12 x64** – najpierw `runtime\python` z paczki aplikacji Windows, potem `py -3.13` / `py -3.12`.
2. **`.venv_kronos`** – osobne środowisko. Główne środowisko bota nie jest zmieniane.
3. **Pakiety** z `requirements\requirements-kronos-win.txt`:
   * tylko pakiety binarne z **sumami SHA-256**: `--require-hashes --only-binary=:all:`;
   * `torch==2.14.1` z PyPI, czyli wersja **CPU**.
4. **Wagi** (`python -m kronos_runtime.install download`) w przypiętych rewizjach:
   * `NeoQuasar/Kronos-small` @ `901c26c1332695a2a8f243eb2f37243a37bea320`;
   * `NeoQuasar/Kronos-Tokenizer-base` @ `0e0117387f39004a9016484a186a908917e22426`.

   Instalator sprawdza, że rewizja istnieje w źródle. Każdy plik porównuje z metadanymi źródła: `model.safetensors` – SHA-256 z LFS,
   `config.json` – suma git blob. Sprawdza też rozmiar. Pliki trafiają na miejsce dopiero, gdy **oba** komponenty są zgodne. Wtedy
   powstaje `kronos_manifest.json` z sumami SHA-256.
   Ze względów bezpieczeństwa ładowany jest tylko format **safetensors**, nigdy pliki pickle (`.bin`).
5. **Sprawdzenie** (`verify --reference`), offline:
   * sumy plików;
   * jednorazowe załadowanie modelu i tokenizera (tryb eval, bez gradientów);
   * zgodność pary model/tokenizer (s1/s2 bits, 6 kanałów wejścia, kontekst ≤ 512);
   * prognoza testowa na danych autorów i porównanie z ich wynikiem referencyjnym.

**GPU (opcjonalnie):** `33_KRONOS_INSTALUJ.bat cu126` albo `cu128` instaluje PyTorch z oficjalnego indeksu PyTorch dla CUDA 12.6 / 12.8.
Torch z tego indeksu nie ma sumy w naszym pliku (zaznaczone w logu); pozostałe pakiety nadal są sprawdzane sumami. Bot używa GPU
tylko wtedy, gdy CUDA jest dostępne **i** operacja testowa na GPU się powiedzie. W przeciwnym razie liczy na CPU i pokazuje przyczynę.

## 3. Gdzie są pliki

| Co | Gdzie |
|---|---|
| Środowisko Pythona z PyTorch | `<folder programu>\.venv_kronos` |
| Wagi + `kronos_manifest.json` | `<folder danych>\kronos\models` (aplikacja Windows: `%LOCALAPPDATA%\PepeMarketWizard\data\kronos\models`) |
| Ustawienia Kronosa | `<folder danych>\kronos\settings.json` |
| Raporty walidacji | `<folder danych>\kronos\validation\` |
| Prognozy i rozliczenia | baza bota, tabela `kronos_forecasts` |
| Logi | `<folder danych>\logs\kronos_worker.log`, `kronos_install_*.log`, `kronos_verify_*.log` |
| Kod modelu (MIT) | `backend\kronos_runtime\vendor\kronos` (licencja: `LICENSE`, pochodzenie: `UPSTREAM.md`) |

Folder wag można zmienić ustawieniem `weights_dir`. Instalator `33_KRONOS_INSTALUJ.bat` używa tej samej ścieżki.

## 4. Uruchomienie i tryb offline

Uruchamiasz bota jak zwykle. Proces modelu (`.venv_kronos\Scripts\python -m kronos_runtime.worker`) startuje sam przy pierwszej prognozie,
ładuje model **raz** i działa obok bota.

Po instalacji internet nie jest potrzebny. Proces modelu działa z `HF_HUB_OFFLINE=1` i czyta tylko lokalne, sprawdzone pliki. Każde
ładowanie ponownie porównuje sumy SHA-256 z manifestem.

Przeniesienie na komputer bez internetu:
1. Zainstaluj na innym komputerze.
2. Skopiuj `.venv_kronos` i folder `kronos\models` (z `kronos_manifest.json`).
3. Kliknij **Sprawdź instalację**.

## 5. Symbole (XAUUSD i BTC)

Kronos korzysta z istniejącego mapowania: **Ustawienia → Mapowanie instrumentów**. Na przykład XAUUSD może być u Twojego brokera
symbolem `XAUUSD-`.

Nazwa BTC i sufiks różnią się między brokerami (BTCUSD, BTCUSDT, BTCUSD., …), więc bot ich nie zgaduje:
- Dopóki symbol ma status „zaproponowany” albo nie ma go wcale, Kronos pokazuje **„brak potwierdzonego symbolu brokera”** i listę kandydatów
  z terminala.
- Wybierz i potwierdź symbol w Ustawieniach.
- Kronos nie czyta świec niepotwierdzonego symbolu.

## 6. Panel „Kronos AI Forecast” (Wykresy bota)

* **Status:** instalacja, działanie, urządzenie (CPU/GPU) i czas ładowania. Tryb **SHADOW – zgoda na zlecenia: NIE**. Rola w strategiach:
  obserwacja albo warunek wymagany.
* **Przyciski:**
  * **Zainstaluj model Kronos**;
  * **Sprawdź instalację** – naprawdę ładuje model i robi prognozę testową, pokazuje porównanie z wynikiem autorów;
  * **Włącz/Wyłącz**;
  * **Odśwież prognozę** – na żądanie, dla bieżącej zamkniętej świecy.
* **Wybór:** instrument, interwał (M1, M5, M15, M30, H1 – domyślnie liczone M5 i M15, pozostałe przyciskiem „Licz …”) i horyzont w świecach.
* **Wykres:** ostatnie 120 zamkniętych świec z MT5 i **osobno** fioletowe świece prognozy („PROGNOZA Kronos (nie notowania)”, znacznik
  „start prognozy”). Przy włączonych ścieżkach niepewności dochodzą linie q10/q90 (nieskalibrowane).
* **Dane prognozy:**
  * kierunek (wzrost / spadek / bocznie) według jawnej reguły: bocznie, gdy |zmiana| ≤ max(0,25 × ATR14, minimalna liczba punktów) – obie
    wartości można zmienić;
  * zmiana ceny w jednostkach instrumentu i w %;
  * czas ostatniej świecy i czas powstania prognozy;
  * źródło danych (MT5 DEMO/REAL albo **SYNTETYCZNE**);
  * źródło wolumenu: tick_volume to liczba zmian ceny, **nie** obrót; amount to syntetyczne przybliżenie;
  * wersje modelu i tokenizera, urządzenie i czas obliczeń.
* **Prognoza nieaktualna:** gdy MT5 jest rozłączony, dane są stare albo trwa liczenie nowej świecy, panel pisze, że prognoza **nie** jest
  aktualna. Starej prognozy nie pokazuje jako nowej.
* **Porównanie z faktycznym ruchem:** tylko prognozy rozliczone prawdziwymi zamkniętymi świecami docelowych czasów. MAE Kronosa jest
  pokazane obok MAE prognozy „ostatnia cena”, plus trafność kierunku z liczbą obserwacji. Dane rzeczywiste i syntetyczne są w osobnych
  wierszach.
* **Walidacja walk-forward** i **Użycie w strategiach** – rozdziały 8 i 9.

Odległość ceny (np. +2,5 USD na XAUUSD) **nie jest** wynikiem transakcji. Wynik pieniężny zależy od wolumenu, specyfikacji kontraktu,
waluty rachunku, spreadu, prowizji i poślizgu.

## 7. Znaczenie statusów

**Model (status ogólny):**

| Status | Znaczenie |
|---|---|
| NOT_INSTALLED | brak `.venv_kronos` – zainstaluj |
| NO_WEIGHTS | środowisko jest, brak kompletnych, zweryfikowanych wag (instalacja przerwana albo pliki usunięte) |
| INSTALLING | trwa instalacja |
| STARTING / LOADING | uruchamianie procesu modelu / ładowanie wag |
| READY | model załadowany – prognozy po każdej nowej zamkniętej świecy |
| ERROR | błąd z kodem: CHECKSUM (pliki zmienione), INCOMPATIBLE (para niezgodna), MISSING_DEPENDENCY, WORKER_TIMEOUT, LOAD_ERROR… Ponowna próba następuje z rosnącym odstępem. |
| DISABLED | wyłączony przyciskiem |

**Instrument × interwał:**

| Status | Znaczenie |
|---|---|
| READY | prognoza aktualna (dla ostatniej zamkniętej świecy) |
| QUEUED / RUNNING | w kolejce / liczenie |
| NO_SYMBOL | brak potwierdzonego symbolu brokera |
| MT5_DISCONNECTED | MT5 rozłączony – nowe prognozy wstrzymane |
| STALE | brak nowych zamkniętych świec (rynek zamknięty, brak notowań) |
| WARMUP | za mało zamkniętych świec (minimum 128) |
| BLOCK | dane odrzucone: niepoprawne OHLC, brakujące wartości, sprzeczne duplikaty, > 10 % luk w sesji, brak czasu UTC (nieznany offset serwera) |
| CALENDAR_UNCERTAIN / CALENDAR_INSUFFICIENT / CALENDAR_NO_SESSION | nie da się wiarygodnie ustalić czasów przyszłych świec – prognoza wstrzymana |
| MODEL_UNAVAILABLE / ERROR | model niedostępny / błąd (z przyczyną) |

W rejestrze modeli i kontrakcie PMW-PRED-1 Kronos ma typ **REGRESSION** i jednostkę **cena**. Kalibracja: „nie dotyczy”, bo pojedyncza
próbka nie jest prawdopodobieństwem. Stan READY oznacza wyłącznie: model załadowany i prognoza dla bieżącej zamkniętej świecy.

## 8. Dane z MT5, kalendarz sesji i jakość

* Świece pochodzą z **istniejącego** mostu MT5 i jego kolejki wywołań. Kronos nie otwiera drugiego połączenia z terminalem.
  * Aktywny symbol jest czytany z bufora mostu.
  * Drugi instrument jest czytany zwykłym `symbol_bars` co najwyżej raz na świecę, kilka sekund po jej spodziewanym zamknięciu.
  * M30 jest czytane natywnie (`TIMEFRAME_M30`).
* Do prognozy idą wyłącznie świece potwierdzone jako **zamknięte**. Przed użyciem sprawdzane są: kolejność, duplikaty, geometria OHLC,
  brakujące wartości, luki, świeżość i źródło wolumenu.
* **Czasy przyszłych świec** wynikają z kalendarza sesji zmierzonego na świecach brokera (ostatnie 4 tygodnie, czas serwera). Przerwa
  dzienna i weekend są pomijane. Jeśli slot w horyzoncie jest niepewny (świece były w nim tylko w części dni) albo historia jest krótsza
  niż 7 dni, prognoza jest **wstrzymana** z przyczyną.
* **Czas:** model dostaje znaczniki w czasie serwera brokera (ustawienie `timestamp_basis`: SERVER albo UTC). Panel pokazuje czasy w UTC
  przeliczone przez zmierzony offset serwera.
* **Wolumen:**
  * AUTO: rzeczywisty wolumen (real_volume), jeśli broker go podaje, w przeciwnym razie tick_volume (to **nie** obrót);
  * NONE: wejście bez wolumenu (oryginalna obsługa Kronosa: volume = amount = 0);
  * `amount` = wolumen × średnia OHLC – **syntetyczne przybliżenie**, oznaczone w panelu.

## 9. Walidacja i użycie w strategiach

**Walidacja walk-forward** (przycisk w panelu, osobny proces modelu, prognozy na żywo działają dalej):

* ostatnie świece z MT5 (do 8000), punkty startu co H świec, więc horyzonty się nie nakładają;
* pierwsze 60 % punktów to DEV – tylko tu wybierany jest mnożnik pasma „bocznie”; ostatnie 40 % to TEST – liczony raz;
* metryki:
  * MAE ceny po H świecach dla Kronosa i dla prognozy „ostatnia cena”;
  * trafność kierunku w porównaniu z bazowym momentum na tych samych przypadkach;
  * test dwumianowy wobec 50 %;
  * liczba obserwacji.
* **Pozytywny** wynik wymaga wszystkich warunków:
  * dane nie są syntetyczne;
  * ≥ 100 obserwacji kierunku;
  * MAE niższe niż dla „ostatniej ceny”;
  * trafność wyższa niż momentum;
  * p < 0,05.
* Zastrzeżenie: okres i skład danych pretreningu Kronosa nie są znane szczegółowo – test może się z nim nakładać. Wynik dotyczy jakości
  prognozy ceny, **nie zysku** (bez kosztów i wolumenu).

**Użycie w strategiach SCALPING / HEDGING:**

* **OBSERVE (domyślnie):**
  * każda ocena setupu dostaje opisany kontekst Kronosa: kierunek, relację do strony setupu, zgodność/konflikt z innymi modelami
    i ze strukturą rynku;
  * w checkliście pojawia się pozycja „Kronos … (obserwacja SHADOW – bez wpływu)”;
  * **nic** w decyzji się nie zmienia.
* **REQUIRED (warunek wymagany):**
  * włączysz go dopiero po **pozytywnej** walidacji na danych rzeczywistych i świadomym potwierdzeniu (przycisk „Ustaw jako warunek…”);
  * warunek może **tylko wstrzymać** gotowy setup: brak modelu, prognoza nieaktualna, kierunek bocznie albo przeciwny = brak wejścia;
  * nigdy nie otwiera pozycji, nie zmienia strony, wolumenu, TP/SL, ryzyka, limitów, STOP ani trybu wykonania;
  * awaria modelu nigdy nie jest BUY, SELL ani zgodą na zlecenie.
* Inne modele liczące na tych samych świecach nie są liczone jako niezależne potwierdzenie. Wyniki o innych jednostkach i horyzontach są
  tylko zestawiane, nie uśredniane.
* Execution Lock został wycofany w 1.24 na Twoją decyzję – Kronos go nie przywraca i nie obchodzi. Obowiązują świadomy wybór trybu
  (SIGNALS/PAPER/AUTO DEMO/AUTO LIVE), STOP nowych wejść, kontrola rachunku, limity i wymagania brokera.

## 10. Ustawienia (`kronos\settings.json`, większość z panelu)

| Ustawienie | Domyślnie | Uwagi |
|---|---|---|
| `enabled` | true | bez instalacji nic się nie liczy |
| `instruments` | XAUUSD, BTC | BTC liczony dopiero po potwierdzeniu symbolu |
| `timeframes` | M5, M15 | dostępne M1, M5, M15, M30, H1 |
| `horizon_bars` | M1 15, M5 12, M15 8, M30 8, H1 6 | 1–64 świece |
| `lookback` / `max_context` | 400 / 512 | Kronos-small ma kontekst 512 – więcej nie jest używane |
| `temperature`, `top_k`, `top_p` | 1.0, 0, 0.9 | jak w `predict()` autorów |
| `paths` | 0 | ≥ 2 = tyle niezależnych ścieżek na pasmo q10–q90 (nieskalibrowane; koszt × N) |
| `direction_band_atr`, `direction_band_min_points` | 0.25, 0 | reguła „bocznie” |
| `volume_source` | AUTO | AUTO / TICK_VOLUME / NONE |
| `timestamp_basis` | SERVER | SERVER / UTC |
| `device` | AUTO | AUTO / CPU / CUDA |
| `cpu_threads` | połowa rdzeni (max 4) | ogranicza obciążenie CPU |
| `request_timeout_s`, `queue_max` | 120 s, 8 | limit czasu prognozy, rozmiar kolejki |
| `weights_dir`, `python_path` | puste | własne ścieżki wag / interpretera |

Ustawienia są w osobnym pliku, więc `config.json` bota się nie zmienia. Zła wartość jest odrzucana; uszkodzony plik oznacza powrót do
wartości domyślnych (obserwacja).

## 11. Rozwiązywanie problemów

| Objaw | Co zrobić |
|---|---|
| Instalacja: błąd NETWORK / brak połączenia | zapora lub proxy blokuje `pypi.org`, `files.pythonhosted.org` albo `huggingface.co` – odblokuj je i powtórz |
| Instalacja: błąd PIP / „hash mismatch” | uszkodzone pobranie albo podmieniony pakiet – usuń `.venv_kronos` i powtórz; nie wyłączaj sprawdzania sum |
| CHECKSUM_MISMATCH / REVISION_MISMATCH / FILE_MISSING | plik w źródle niezgodny z przypiętą rewizją – nic nie zostało zainstalowane; zgłoś |
| Status ERROR: CHECKSUM | pliki wag zmienione na dysku (antywirus, ręczna edycja) – zainstaluj ponownie |
| Status ERROR: INCOMPATIBLE | model i tokenizer nie pasują – ponowna instalacja przypiętej pary |
| „brak GPU z CUDA – CPU” | to normalne bez karty NVIDIA; dla GPU użyj `33_KRONOS_INSTALUJ.bat cu126` |
| WORKER_TIMEOUT | wolny komputer – zmniejsz `lookback`, horyzont, liczbę interwałów, wyłącz `paths`; albo zwiększ `request_timeout_s` |
| NO_SYMBOL | potwierdź symbol w Ustawienia → Mapowanie instrumentów |
| CALENDAR_UNCERTAIN | przy niepewnej godzinie sesji (np. skrócona sesja) prognoza poczeka; wróci, gdy horyzont jej nie obejmuje |
| BLOCK „brak czasu UTC” | most MT5 jeszcze nie zmierzył offsetu serwera (pierwsze ~30 s) albo brak notowań |
| Sprawdź instalację: porównanie „DIFF” | sumy plików są poprawne; różnica obliczeń na innym CPU lub w innej wersji bibliotek może zmienić wybór tokenu – podana jest wielkość różnicy; prognoza testowa działa |

## 12. Testy u siebie (Windows, folder `tests`)

```
..\.venv\Scripts\python -m unittest test_kronos_bot test_ui_kronos        (strona bota; test_ui_kronos wymaga Playwright)
..\.venv_kronos\Scripts\python -m unittest test_kronos_runtime          (PyTorch: silnik, proces, instalator)
set MQ_KRONOS_WEIGHTS_DIR=%LOCALAPPDATA%\PepeMarketWizard\data\kronos\models
..\.venv_kronos\Scripts\python -m unittest test_kronos_runtime.TestOfficialWeights   (oficjalne wagi: zgodność z wynikiem autorów)
```

Część testów strony bota korzysta z zastępczego procesu w skrypcie powłoki – na Windows jest pomijana. Testy uruchomione przy
wdrożeniu i ich wyniki: `docs/KRONOS_RAPORT_WDROZENIA.md`.

## 13. Licencje

* Kod Kronos: MIT, Copyright (c) 2025 ShiYu. Pełny tekst: `backend\kronos_runtime\vendor\kronos\LICENSE`. Zmiana tylko w imporcie –
  `UPSTREAM.md`.
* Wagi: licencja według kart modeli NeoQuasar na Hugging Face. Instalator zapisuje pole `license` z karty w manifeście (jeśli karta je
  podaje).
* Dane testowe autorów (regression_input / regression_output) są dołączone bez zmian do przycisku „Sprawdź instalację”.
