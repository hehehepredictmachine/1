# AUDIT_REPORT – PepeMarketWizard 1.13.0 (dawniej MasterQUO AI), 2026-10-16

**Środowisko audytu:** Linux, symulator terminala MT5 (dane syntetyczne), Chromium.
Nie było Windows, Twojego MT5 ani rzeczywistego rachunku. Wszystkie wnioski o MT5 dotyczą kodu i testów z atrapą terminala, nie Twojej instalacji.

**Ten raport nie stwierdza „braku błędów”.** Opisuje:
- zakres kontroli;
- znalezione usterki;
- wykonane naprawy;
- to, czego nie dało się sprawdzić.

Poprzednie audyty: `AUDYT_MASTERQUO.md` (1.8) oraz `audit/` (1.9 → 1.10, reprodukcje A–J naprawione). Ten audyt obejmuje stan 1.12 → 1.13.

## 1. Zakres i metoda

**Kod przejrzany:**
- `backend/masterquo` (wszystkie pakiety);
- `backend/gold_candles_runtime`;
- `frontend/src`;
- launchery `.bat`;
- `tools/`;
- `tests/`.

**Pominięte:** wygenerowane pliki (`frontend/dist`, `__pycache__`) i dostarczony kod `vendor/` – jego wersja jest zamrożona i ma własne testy regresji.

**Kontrole bazowe przed zmianami** (stan 1.12, commit przed 1.13):
- pełny `tools/run_tests.py`: 359 + 46 testów OK (`RAPORT_TESTOW.md`);
- `compileall`: OK;
- `pyflakes`: 16 uwag (P3).

**Wyszukiwania:**
- puste bloki `except … pass`;
- TODO/FIXME;
- losowość w kodzie produkcyjnym;
- bind adres i CORS;
- zdublowane implementacje wskaźników;
- liczenie wskaźników po stronie frontendu.

**Po zmianach:** pełny `tools/run_tests.py`, build frontendu (`tsc` w `vite build`) i przeglądarka na 1920, 1366 i 390 px – wyniki w `TEST_REPORT.md`.

## 2. Rejestr usterek

| ID | P | Plik / funkcja | Objaw | Przyczyna | Naprawa | Test | Status |
|---|---|---|---|---|---|---|---|
| A-01 | P2 | `strategies/indicators.py`, `scalp/indicators.py`, `engine/chartdata.py` (M02I) | trzy niezależne implementacje Bollinger Bands; ryzyko rozbieżności wykresu i strategii | rozwój modułów w różnych wydaniach | wspólny silnik `analytics/ta.py`; wykresy (EMA/BB) korzystają z niego; równość z M02I i modułem scalp sprawdzana testem (tolerancja 1e-9) | `test_analytics.TestBBMA.test_single_implementation_matches_legacy_and_scalp` | naprawione; `strategies/indicators.bb_width` pozostaje (używa tej samej definicji, ddof=0) |
| A-02 | P3 | `engine/service.py` `start()` | błąd oznaczania starych sygnałów po restarcie był połykany | `except Exception: pass` | wpis w dzienniku `RESTART_EXPIRE_FAILED`; start trwa dalej | przegląd kodu | naprawione |
| A-03 | P2 | `ml/registry.py` | uszkodzony model challenger ML znikał bez śladu | `except Exception: pass` | błąd zapisywany w `challenger_errors` | przegląd kodu | naprawione |
| A-04 | P3 | 10 plików | nieużywane importy i zmienne, f-string bez pola | pozostałości | usunięte | `pyflakes` bez uwag | naprawione |
| A-05 | P1 (wprowadzone przy zmianie nazwy, wykryte testem) | `__main__.cmd_serve` | druga instancja nie rozpoznałaby działającego serwera, a port byłby zajęty | porównanie z dosłownym „MasterQUO AI” | porównanie ze stałą `APP_NAME` oraz z dawną nazwą | `test_app_process.test_01` | naprawione |
| A-06 | P2 (hipoteza) | `scalp/replay.py`, eksport | spread z pola `spread` świecy MT5 może zaniżać koszt (to nie maksimum w świecy) | ograniczenie danych OHLC | opisane w raportach scalp; pełne rozwiązanie wymaga eksportu ticków | brak – wymaga danych z MT5 | otwarte |
| A-07 | P3 | `ml/service.py` (pętla ticków), `prefs.py` (listener) | wyjątki połykane w pętlach pomocniczych | celowe, żeby pętla nie stawała | pozostawione; uwaga do diagnostyki | – | otwarte (niski wpływ) |
| A-08 | P3 | `analytics/signal.py` (nowy kod) | wartości `numpy.bool_` i `float64` psuły serializację API (500) | typy numpy w wyniku | `contract.clean()` – zamiana na typy JSON, NaN i inf na `null` | `test_analytics.TestSignal.test_json_clean`, `test_ui_analytics` | naprawione przed wydaniem |
| A-09 | P3 (nowy kod) | Pulpit (`AnalyticsPages.tsx`) | wykres o zerowej wysokości w nowym kontenerze | brak wysokości flex | klasa `.dash-chart` | zrzut `data/logs/ui_analytics/pulpit_1920.png` | naprawione |

**Usterki P0 (niezamierzone zlecenie, naruszenie uprawnień, utrata danych): nie znaleziono w tym audycie.**
- Ścieżki wykonania są bez zmian.
- Nowe moduły nie mają referencji do executora ani modułu ryzyka (sprawdzone grep i testem).
- Nowe endpointy POST/DELETE przechodzą przez istniejącą ochronę: sesja, Origin, CSRF, Host.

## 3. Stan podzespołów

| Podzespół | Stan |
|---|---|
| Analiza M1–D1 (+ H8) | **działa** – bufory per TF, świeca otwarta oddzielona, kontrola jakości M01 |
| Strategie S01–S12 + AUTO (wybór automatyczny) | **działa** – na symulatorze; skuteczność na rynku nie oceniona |
| Strategie nazwane „MVP / SMC / SCALPING” | **nie istnieją pod tymi nazwami** – odpowiedniki: S01–S12 (struktura SMC: BOS/CHoCH/FVG/sweep w M03), profil scalp 1.12 (SHADOW) |
| Panel, checklista, trigger, unieważnienie | **działa** |
| Bollinger Bands, MAs | **działa** (1.13 wspólny silnik) |
| VMD, FFT, EMD | **działa – obserwacyjnie**; wpływ na strategię nie oceniony |
| Double Bottom: walidator, biblioteka, skaner | **działa** – na danych syntetycznych |
| Formacje świecowe i cenowe, FVG, płynność | **działa** (MQ-CANDLE, chart patterns, M03) |
| Prognozowanie (gold_candles, scalp ML/NN) | **działa częściowo** – kod i testy OK; **brak treningu na Twoich danych** (BLOCKED_NO_REAL_DATA) |
| Decision Tree / XGBoost | **działa** (trener w osobnym procesie, rejestr, SHADOW/ASSIST) – modele tylko z danych syntetycznych |
| Telegram | **działa** – kolejka i deduplikacja; testy bez wysyłki do odbiorców |
| Historia transakcji, statystyki | **działa** (win rate, ROI bez wpłat i wypłat – naprawy 1.10) |
| Konta użytkowników i licencje | **usunięte w 1.9 na Twoją prośbę** – nie dotyczy |
| MT5 na Twoim komputerze | **nie da się zweryfikować** w tym środowisku |

## 4. Zabezpieczenia

- **Serwer i dostęp:**
  - serwer wyłącznie na 127.0.0.1 (`Literal["127.0.0.1"]`);
  - kontrola nagłówka Host (DNS rebinding) i Origin;
  - sesja w ciasteczku HttpOnly z SameSite=Strict, CSRF na wszystkich metodach innych niż GET/HEAD/OPTIONS, w tym nowych DELETE.
- **Sekrety:**
  - klucze trzymane w lokalnym magazynie (DPAPI), nie w kodzie, logach ani ZIP;
  - builder paczki skanuje pliki pod kątem kluczy.
- **Nowe ścieżki:**
  - identyfikator raportu formacji jest walidowany – brak path traversal;
  - import biblioteki waliduje schemat i dane;
  - pickle modeli ładowany wyłącznie po zgodności sha256 z własnym rejestrem.
- **Zależności:** w tym środowisku nie wykonano audytu podatności pakietów (pip-audit / npm audit z siecią) – **do wykonania**. Wersje są przypięte z hashami w `requirements/`.

## 5. Gotowość

| Zastosowanie | Ocena |
|---|---|
| Lokalne uruchomienie (demo / symulator) | gotowe – testy, build i przeglądarka OK |
| Monitorowanie danych live z MT5 | wymaga sprawdzenia na Twoim komputerze (`02_DIAGNOSTYKA.bat`, strona Diagnostyka); logika połączenia testowana atrapą |
| Wykonywanie transakcji | **nie jest potwierdzone** – testy z atrapami nie dowodzą wykonania u brokera; moduły 1.12/1.13 są SHADOW/OBSERVE; istniejące tryby AUTO_DEMO/AUTO_LIVE wymagają Twojej weryfikacji na demo |

## 6. Następne kroki (poza zakresem tej wersji)

1. Na Windows z MT5:
   1. `02_DIAGNOSTYKA.bat`;
   2. strona Diagnostyka;
   3. eksport historii (11 i 16);
   4. replay i trening (12, 17, 19).
2. Eksport ticków do replayu (usterka A-06).
3. `pip-audit` i `npm audit` przy dostępie do sieci.
4. Ocena przyrostowej wartości BB/MA, VMD/FFT/EMD i Double Bottom na Twoich danych – opis w `docs/ANALITYKA_…`.
