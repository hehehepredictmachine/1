# Audyt kodu – PepeMarketWizard 1.42.4

Środowisko: kontener Linux (Python 3.13, Go, Node, Chromium), demo na terminalu SYNTETYCZNYM. Windows / MT5 niedostępne – punkty
wymagające Windows opisane jako DO WERYFIKACJI.

## 1. Pamięć modeli – profile 8 GB / 12 GB
Zmierzone szczyty RSS procesów modeli (weryfikacja + prognoza testowa, CPU, float32):

| Model | Szczyt RAM |
|---|---|
| Kronos-base | 1,07 GB |
| TiRex-2 | 0,94 GB |
| Chronos-2 | 0,84 GB |
| TabICLv2 | 0,67 GB |
| Granite TTM | 0,37 GB |

| Profil | Ciężkie modele w RAM naraz | Budżet PMW (preferowany / maks.) | Zwalnianie | Wątki ciężkie / lekkie |
|---|---|---|---|---|
| LOW_MEMORY_8GB | 1 (wszystkie dozwolone, rotacja) | 2,5 / 3,3 GB | 90 s | 2 / 1 |
| LOW_MEMORY_12GB | 2 | 3,5 / 5 GB | 5 min | 3 / 1 |
| LOW_MEMORY_16GB | bez limitu liczby | 6 / 8 GB | pod presją | 4 / 2 |

AUTO / LOW_MEMORY_16GB / BALANCED są automatycznie obniżane do 12 GB (RAM ≤ 14 GB) lub 8 GB (RAM ≤ 10 GB). Testy: `test_resources_governor`
(9 testów, w tym rotacja przy 8 GB, dwa modele przy 12 GB, dobór AUTO dla 8/12/16/32 GB).

## 2. Analiza statyczna
* `compileall` backend / runtime’y / tools / tests – 0 błędów.
* pyflakes – 0 niezdefiniowanych nazw; 127 nieużywanych importów (bez wpływu na działanie), gwiazdki tylko w kodzie dostawcy Kronos
  i skryptach badawczych; poprawione: martwe zmienne (`lab/structure_task.py`, `zones/hlze.py`), f-string bez zmiennych (`execution/modes.py`).
* TypeScript `tsc -b` – 0 błędów; `npm run build` OK.
* Go: `GOOS=windows go vet` + `go test` – OK.

## 3. Działanie (demo)
* 240 endpointów GET API wywołanych na działającym serwerze: 183 × 200, pozostałe 404/422/400 – celowe odrzucenie testowej wartości
  parametru; **0 × 5xx, 0 wyjątków w logu**, żaden > 5 s.
* Każdy adres `/api/v1/…` używany przez interfejs (frontend + Studio) istnieje w backendzie – 0 braków.
* Interfejs 1.42 w przeglądarce (`test_ui_142`): menu, 4 ekrany FOREX, panele systemowe, przekierowania – bez błędów konsoli i bez POST przy otwieraniu.

## 4. Testy
106 plików, **1249 testów** – wszystkie OK po poprawkach (uruchamiane plik po pliku).

## 5. Znalezione i naprawione
| # | Problem | Skutek | Naprawa |
|---|---|---|---|
| 1 | Walidacja biblioteki formacji ustawiała `COMPLETED` przed zapisem raportu | panel/API mógł zobaczyć zakończone zadanie bez `report_id` (niestabilny test) | status końcowy publikowany dopiero po zapisie raportu; 10/10 przebiegów OK |
| 2 | `23`–`31`, `39`, `tools/trening.cmd`, `tools/ic.cmd` szukały tylko `.venv` | w aplikacji Windows (bez `.venv`) kończyły się „Brak .venv” | wspólny `tools/pmwpy.cmd`: `.venv` albo `runtime\python` + biblioteki aplikacji (`<home>\pyenv\cp313-*`) |
| 3 | Profil 8 GB dopuszczał tylko TiRex-2 / TabICLv2 | Kronos i Chronos-2 nie liczyły na 8 GB | rotacja: wszystkie modele, jeden naraz |
| 4 | Brak profilu 12 GB i doboru do RAM | komputer 8/12 GB z domyślnym profilem 16 GB przekraczał pamięć | `LOW_MEMORY_12GB`, `AUTO`, automatyczne obniżanie |

Wcześniejsze poprawki tej serii (1.42.1–1.42.3): TiRex-2 bez kompilatora C++, przeniesiony folder programu (`pyvenv.cfg`), numpy 2.5.4 przy Smart App Control.

## 6. DO WERYFIKACJI (Windows)
* `tools/pmwpy.cmd` – składnia cmd sprawdzona przeglądem, nie uruchomiona na Windows.
* Czasy przełączania modeli przy 8 GB (ładowanie ciężkiego modelu ok. 3–6 s na CPU) – zależne od dysku i procesora.
* Test modułu świec `gold_candles` wymaga `.venv_candles` (w kontenerze brak – pominięty, jak w poprzednich wydaniach).
