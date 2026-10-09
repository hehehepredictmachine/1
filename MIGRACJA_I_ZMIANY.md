# Migracja z paczki READONLY i lista zmian

## Instalacja
Nowa aplikacja instaluje się do **nowego folderu** (np. `C:\MasterQUO_AI`). Nie nadpisuje poprzedniej paczki, jej `.venv`, konfiguracji
ani historii. Stara paczka może pozostać na dysku – nie uruchamiaj jej procesów MT5 równolegle (dwa programy odpytujące ten sam terminal
nie są szkodliwe, ale niepotrzebne). Oryginalny ZIP jest dołączony w `archive/` bez zmian.

## Migracja uprawnień (READONLY → tryby wykonawcze)
Nie podmieniono żadnego `BLOCKED` na `ALLOWED` ani `research_only=true` na `false` w kodzie legacy – te moduły nadal zwracają
`execution_permission=BLOCKED`, bo **nie są** źródłem uprawnienia. Uprawnienie powstaje wyłącznie w nowym, osobnym łańcuchu:
`drzewo decyzji (7 węzłów) → ModeManager.gate → ExecutionGateway._validate`. Warunki wejścia w tryb wykonawczy:
1. skonfigurowane limity (ryzyko/trade, suma ryzyka, dzienna strata, drawdown, liczba pozycji) – inaczej odmowa;
2. PAPER – wpisanie `PAPER`; DEMO – rachunek typu DEMO i wpisanie numeru rachunku; LIVE – rachunek REAL, ręczne
   `execution.allow_live_execution: true` w `data\config.json` i wpisanie `LIVE <numer>`;
3. tryb wiąże się z rachunkiem; restart, zmiana rachunku, terminala, symbolu albo limitów → powrót do READ_ONLY i AUTO OFF;
4. AUTO TRADING włącza się osobno i tylko w trybie innym niż READ_ONLY.
Testy: `test_mode_requires_confirmation_and_limits`, `test_read_only_blocks_real_orders`, `test_02_security`.

## Zmiany względem paczki (co, dlaczego)

| Element paczki | Zmiana | Powód |
|---|---|---|
| M00U supervisor + adapter M00U10 + viewery Tk (3–4 procesy) | jeden proces `masterquo serve` | jeden nadzór, brak konkurencyjnych silników |
| Adapter: 90 świec dla wszystkich TF | bufor per TF z profili (D1 230) | profil D1 wymagał 230 |
| Adapter: surowy epoch = UTC, blokada `BROKER_TICK_AHEAD_OF_UTC` | pomiar offsetu serwera z ticków + walidacja siatką 15 min | jawny kontrakt czasu bez arbitralnego przesuwania |
| Adapter: stałe `side='LONG'`, `technical_decision='WAIT'` | usunięte; kierunek z setupu/struktury | to były wartości diagnostyczne |
| U10: wynik tylko WAIT/NO_TRADE | nie zmieniane; nowe pola decyzji obok | separacja analizy i uprawnienia |
| M01_AUDIT (live): każda luka → PENDING | nowy moduł jakości z modelem sesji (weekend/przerwa/niewyjaśniona) | przerwa dzienna złota blokowała H1/H4 |
| M10_AUTO_TRIGGER: ocena tylko ostatniej świecy, luka → blokada | reduktor M10A odtwarza każdą nową zamkniętą świecę | uzupełnianie luk po reconnect |
| M14 (signal tiers) | drzewo decyzji 7 węzłów + AI gate + tryb | wymagane pola i wykonanie |
| brak TP / sizingu / gatewaya | MQAI-LEVELS-1.0.0 (prowizoryczne), port M11, gateway | projekt nie kończy się na atrapach |
| `--symbol XAUUSD` w skryptach legacy | aktywny kod: tylko `mt5.symbol` (domyślnie `XAUUSD-`); skrypty legacy nieużywane | błędne domyślne symbole |
| instalator: `pip install MetaTrader5 numpy tzdata` bez wersji | przypięte wersje + hashe, tylko koła, log, kontrola interpretera | powtarzalność, problem venvlauncher/pip 3.14 |
| eksporter M06R (czas serwera jako UTC) | nowe `python -m masterquo export` (UTC, manifest z offsetem) | spójność z kalendarzem makro |
| M06H/M06R/M06T | bez zmian w `research/` | działające narzędzia badawcze |

## Wersja 1.1 – mniej restrykcyjne domyślne bramki
| Bramka | 1.0 (oryginał MasterQUO) | 1.1 domyślnie | Gdzie przywrócić |
|---|---|---|---|
| Kierunek struktury | H4 i H1 zgodne | `H1_LEAD`: decyduje H1, przeciwny H4 tylko oznaczony | Ustawienia → Strategia → Kierunek struktury = `STRICT_H4_H1` |
| RR netto | < 1,5 blokada, 1,5–2 bez wykonania | < 1,0 blokada, 1,0–1,5 wejście z ryzykiem × 0,5, ≥ 1,5 pełne | Ustawienia → Ryzyko |
| Agent Claude | wymagana zgodna ocena | VETO: blokuje tylko jawna niezgoda; czeka max 60 s | Ustawienia → Agent Claude → Rola AI = `REQUIRED` |
| Kalendarz makro | brak kalendarza = blokada | blokuje tylko okno wydarzenia | „Brak kalendarza makro blokuje wejścia” |
| Poślizg | nieustawiony = blokada | 20 punktów doliczane do kosztu | Ustawienia → Koszty |
| Okno wejścia po potwierdzeniu | 2 świece | 3 świece | Ustawienia → Strategia |

Bez zmian (ochrona kapitału): jakość danych i czas, rynek zamknięty, limity ryzyka, dzienny stop, drawdown, min. lot bez zaokrąglania w górę,
nieznana prowizja, potwierdzenie setupu (CONFIRMED), tryb i rachunek. Plik `data\config.json` z 1.0 jest migrowany automatycznie
(`config_version` 2): zmieniane są tylko wartości równe staremu domyślnemu – Twoje własne ustawienia zostają.

## Kod skopiowany bez zmian
`backend/vendor/legacy_core`, `backend/vendor/mq_upgrades`, `backend/vendor/m04n` (bez plików `.bat`), `research/03_ANALIZA_HISTORYCZNA`.
Kontrola: `backend/vendor/VENDOR_MANIFEST.json` (141 plików, wszystkie identyczne z paczką) + test `TestVendoredEnginesUnchanged`.

## Nie uruchamiać
* `archive/MasterQUO_ALL_IN_ONE_…zip` i 42 archiwa w środku – wersje historyczne;
* skryptów `RUN_MT5_*.py`, `M00U*.py`, viewerów `*_VIEWER.py` z kopii vendor – nie są częścią aplikacji (BAT usunięto, by nie uruchamiać ich przypadkiem).
**Aktywny entrypoint:** `03_START_MASTERQUO.bat` → `backend\python -m masterquo serve`.
