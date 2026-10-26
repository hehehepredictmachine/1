# Audyt wejściowy – paczka MasterQUO ALL-IN-ONE (XAUUSD-, FUTURE_CANDLE_TIME_FIX V3, READONLY)

Data audytu: 2026-10-08. Plik: `MasterQUO_ALL_IN_ONE_XAUUSD_MINUS_FUTURE_CANDLE_TIME_FIX_V3_READONLY.zip` (8,46 MB, 367 plików
po rozpakowaniu + 42 archiwa wewnętrzne). Kopia nienaruszona: `archive/`.

## 1. Co przeczytano

`START_TUTAJ_README_PL.md`, `NAPRAWA_FUTURE_CANDLE_AVAILABILITY_PL.md`, `NAPRAWA_BLEDU_VENVLAUNCHER_PYTHON_V2.md`,
`NAPRAWA_PIP_PYTHON_3_14_PL.md`, `01_PROGRAM_GLOWNY_10_ULEPSZEN/{M00U_RUNTIME.py, M00U_CONFIG.json, M00U10_MT5_READONLY_ADAPTER.py,
RUN_UPGRADES_READONLY.py, INTEGRATION_CONTRACT.md}`, `mq_upgrades/` (U02–U10), `legacy_core/` (M01_AUDIT, M02I_M01_M02_LIVE_BRIDGE,
M03E_M10_PIPELINE, M07_M03E_PROFILE_DETECTOR/RUNTIME, M10_AUTO_TRIGGER_CONFIRM, specyfikacje M07_M03E, M10A, M11, vendor M02/M02I/M03/M09/M14),
`02_ZRODLA_NEWS_M04N/` (M04N_ENGINE, konfiguracja), `03_ANALIZA_HISTORYCZNA/` (M06H, M06R, M06T), `DOKUMENTACJA/KATALOG_ARCHIWOW.json`,
oraz specyfikacje M01–M16 rozpakowane z 42 archiwów (szczególnie M01 v4.2.1, M11, M14).

## 2. Stan zastany (fakty)

| Obszar | Stan | Dowód |
|---|---|---|
| Charakter paczki | Badawcza, READONLY, wiele historycznych wersji; brak wykonywania zleceń | `research_only=true`, `enable_orders=false` w M00U_CONFIG |
| Przepływ wykonania | Kilka konkurencyjnych: M00U supervisor (3 procesy), osobny adapter M00U10, viewery Tk, M06R | INTEGRATION_CONTRACT.md: adapter „nie jest częścią nadzoru restartów M00U” |
| Testy bazowe | M00U_TESTS 76/76 OK; tests/ 94/94 OK; operacyjne profile 85/85; makro 287/287; legacy offline 47/48 (1 błąd: brak `tkinter` w Linux); M10A_M15 – ten sam błąd tkinter | uruchomione w audycie (Python 3.13.16, Linux) |
| Symbol | `XAUUSD-` w M00U_CONFIG i trzech BAT; ale domyślne `--symbol XAUUSD` w 7 skryptach legacy_core, w M02I preview, w eksporterach M06H/M06R i w starych BAT | grep `default='XAUUSD'` |
| Alias analityczny | Silniki M01_AUDIT/M02I/M03/M07 sprawdzają `instrument_id=='XAUUSD'` i `exact_symbol` = symbol brokera | M03 `selected_bars`, M07 `_bars` |
| Historia | Adapter M00U10 domyślnie 90 świec dla wszystkich TF; profil M02I D1 wymaga 230; M01_AUDIT wymaga 230 dla każdego TF | `--bars 90`, `M02I_PROFILE_MT5_TIMEFRAMES_v1.1.json`, `audit(min_bars=230)` |
| Czas | Adapter traktuje surowy epoch MT5 jako UTC; poprawka V3 blokuje przyszłe świece (`BROKER_TICK_AHEAD_OF_UTC`), ale nie ustala przesunięcia serwera | `M00U10_MT5_READONLY_ADAPTER.from_mt5` |
| Diagnostyka kierunku | `side='LONG'`, `technical_decision='WAIT'` są stałymi w adapterze, nie wynikiem analizy | `from_mt5` zwraca je zawsze |
| Wynik U10 | `explain()` zwraca wyłącznie `WAIT`/`NO_TRADE`, `execution_permission=BLOCKED` | `mq_upgrades/u10_explain.py` |
| Luki sesji | M01_AUDIT oznacza każdą lukę wśród ostatnich 14 świec jako PENDING (bez kalendarza sesji) → przy dziennej przerwie złota H1/H4 są blokowane przez wiele godzin, weekend blokuje M15+ | `M01_AUDIT.audit` |
| Koszty | U03 wymaga ręcznego pliku ekonomii; brak odczytu prowizji z historii; brak sizingu | `u03_execution.estimate`, M07 `NO_PORTFOLIO_POSITION_SIZING` |
| Spread 40% | Ustawienie bez mianownika – M01 v4.2.1 §12 jawnie odmawia implementacji | M01_DATA_INTELLIGENCE_v4.2.1 §12 |
| Pełny prompt MasterQUO 4.1.0 | **Nie odnaleziony** (tylko odwołania w nagłówkach modułów) | wyszukiwanie w 42 archiwach |
| TP / zarządzanie pozycją | Brak definicji TP w M07; M10 `ENTERED` poza zakresem; brak gatewaya | M07_M03E spec, M10A spec |
| Makro | M04N działa (stdlib, sieć); kalendarz częściowy; statusy uczciwe | M04N_ENGINE.collect |
| Instalator | Rozwiązuje venvlauncher/pip 3.14; instaluje bez przypięcia wersji i bez hashy | `01_INSTALUJ_ZALEZNOSCI.bat` |

## 3. Wybór jednego kanonicznego przepływu

**Wybrano:** jeden proces `python -m masterquo serve` (backend FastAPI) z wątkami pod jednym nadzorem:
MT5 worker (jedyny dotykający terminala) → bridge (6 TF, czas, rachunek) → jakość danych → **niezmienione** silniki M02, M02I, M03,
M07 + `ResearchPlanLock` → nowy reduktor cyklu życia (reguły M10A) → MQAI-LEVELS → port M11 → agent Claude → drzewo decyzji (rola M14)
→ gateway (PAPER/DEMO/LIVE) → menedżer pozycji/rozliczenia. Monitor WWW serwowany z tego samego procesu.

**Zintegrowane przez kontrakty (kod bez zmian, weryfikacja SHA-256 w `backend/vendor/VENDOR_MANIFEST.json`):** M02, M02I, M03,
M07_M03E (+ M03E_M10_PIPELINE.construct_early, M01_AUDIT jako zależność importu), M04N (kolektor in-process).
**Zastąpione nowym kodem (z uzasadnieniem):** M01_AUDIT w trybie live (blokowanie każdej luki), adapter M00U10 (90 świec, stałe LONG/WAIT,
surowy czas jako UTC), M10_AUTO_TRIGGER (ocena tylko ostatniej świecy → luka po reconnect blokowała; teraz odtwarzane są wszystkie
nowe świece), M14 (nowe drzewo z rozdzielonymi polami), M15 viewer Tk (monitor WWW), M00U supervisor (jeden proces).
**Zachowane jako narzędzia:** M06H/M06R/M06T w `research/` (działają; nowy eksport `python -m masterquo export` daje czas UTC).
**Archiwum (nie uruchamiać):** `archive/…zip` z 42 wersjami, U02–U10 (`backend/vendor/mq_upgrades`, niepodłączone – kalkulatory diagnostyczne
bez wpływu na decyzje), viewery Tk, BAT legacy (usunięte z kopii vendor).

## 4. Odpowiedzi na punkty szczególne zlecenia

1. **`side='LONG'` / `technical_decision='WAIT'`** – nie przeniesione. Kierunek = kierunek zamrożonego setupu M07 albo obserwacja
   struktury M02 (`direction_basis`).
2. **Ograniczenie U10 do WAIT/NO_TRADE** – nie „naprawiane” usunięciem blokad; nowe, oddzielne pola `analysis_direction`,
   `signal_stage`, `decision`, `execution_permission`; uprawnienie nadaje wyłącznie drzewo decyzji + tryb + limity.
3. **Nadzór restartów** – jeden proces; bridge z backoffem; pętle wątków odporne na wyjątki; START/STOP pojedynczej instancji.
4. **Propagacja `XAUUSD-`** – jedna wartość `mt5.symbol` w konfiguracji → bridge, zapytania MT5, snapshot (`exact_symbol`), plany, zlecenia,
   API, UI, eksport. Alias `XAUUSD` pozostaje jawnie jako `instrument_id` silników legacy. Test blokuje `default='XAUUSD'` w aktywnym kodzie.
5. **Historia per TF** – wymagania z profili (`D1=230, H1/H4=90, M15/M5=70, M1=50`); bufor = max(wykres 500, wymaganie+60).
6. **Brakujące zależności** – koszty (prowizja z historii transakcji lub konfiguracji; stres poślizgu wymagany), makro (M04N, status
   uczciwy), kalibracja (brak → brak procentów), badania (M06R/M06T jako narzędzia). Każdy brak = kod przyczyny, nie sukces.

## 5. Ryzyka zidentyfikowane w trakcie budowy (i obsługa)

* Surowy czas MT5 = czas serwera → offset mierzony z ticków, weryfikowany siatką 15 min, opcjonalny test zegara PC; brak = blokada wejść.
* Cofnięcie czasu serwera (DST) → wykrywane, pomiar od nowa (błąd znaleziony testem i poprawiony).
* Zawieszony terminal → worker oznacza `TERMINAL_UNRESPONSIVE`; timeout zlecenia = UNKNOWN bez ponawiania.
* Prompt injection w newsach → treści oznaczone `UNTRUSTED_EXTERNAL_DATA`, agent nie ma narzędzi wykonawczych.
