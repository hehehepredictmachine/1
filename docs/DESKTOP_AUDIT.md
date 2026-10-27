# PepeMarketWizard Desktop – audyt przed przebudową (27.10.2026)

Polecenie: [desktop_handoff/00_PROMPT_WYKONAWCZY.md](desktop_handoff/00_PROMPT_WYKONAWCZY.md), ustalenia:
[desktop_handoff/04_DOKUMENTACJA/01_ZATWIERDZONY_PROJEKT.md](desktop_handoff/04_DOKUMENTACJA/01_ZATWIERDZONY_PROJEKT.md).
Makiety (`desktop_handoff/01_WIDOKI/*.html`) są wzorcem wyglądu – **nie** źródłem danych ani dowodem integracji.

Statusy: `POTWIERDZONA` (kod + test, który go wykonuje), `W_KODZIE_NIEZWERYFIKOWANA` (kod jest, brak testu tej roli),
`BRAKUJE`, `WYMAGA_DANYCH` (wymaga MT5 użytkownika, Windows, historii lub decyzji). Środowisko audytu: kontener Linux, **bez**
Windows i bez terminala MT5 – działanie MT5 sprawdzane na symulatorze (`mt5/fake.py`, `--demo`).

## 1. Repozytorium i punkt powrotu

| Pozycja | Stan |
|---|---|
| Gałąź / commit startowy | `claude/masterquo-ai-bot-mt5-f7uaht` @ `2293958` (wydanie 1.23.0), drzewo czyste |
| Punkt powrotu | tag `pre-desktop-1.23.0` → `2293958`; paczka `release/PepeMarketWizard_KLIENT_1_23_0.zip` (SHA-256 `4047948b…`) |
| Paczka z handoffu | pliki projektu identyczne z repozytorium (manifest SHA-256 zgodny); dodatkowe tylko `CLAUDE_DESKTOP_HANDOFF/` i `00_START_CLAUDE_CODE.md` → skopiowane do `docs/desktop_handoff/` |
| Rollback | `git revert` commitów etapu albo powrót do `pre-desktop-1.23.0`; dane użytkownika (`data/`) nie są w Git i nie są nadpisywane |

## 2. Przepływ MT5 → … → Telegram

| Etap | Moduł (plik / funkcja) | Status | Dowód / uwagi |
|---|---|---|---|
| MT5 – połączenie, rachunek, zegar | `mt5/bridge.py` (`MarketBridge`), `mt5/worker.py` (`MT5Worker` – jedyny wątek wywołań terminala), `mt5/clock.py` | POTWIERDZONA na symulatorze; real MT5: WYMAGA_DANYCH | `test_bridge_engine`, `test_time_and_data` |
| Świece i ticki (M1…D1, W1/MN1) | `bridge.bars`, `quote_status`, `symbol_bars` | POTWIERDZONA (symulator) | `test_bridge_engine`, `test_markets_signals` |
| Analiza | `engine/service.py`, `strategies/*`, `zones/*`, `analytics/*` | POTWIERDZONA | `test_active_pipeline`, `test_zones`, `test_analytics` |
| Setup | ACTIVE: tracker (`engine/active.py`); SH: `sh/setup.py` | POTWIERDZONA | `test_setup_details`, `test_sh_service` |
| Wybór strategii / ścieżki | `StrategyAutoSelector`, ścieżka główna O1 (`execution/modes.py: gate(path=)`) | POTWIERDZONA | `test_arch_fixes`, `test_active_pipeline` |
| Ryzyko | `risk/engine.py` (M11), `risk/portfolio.py` (wspólny strażnik) | POTWIERDZONA | `test_risk_execution`, `test_finish_plan` |
| Tryb | `execution/modes.py` (SIGNALS / PAPER / AUTO_DEMO / AUTO_LIVE, STOP, rachunek potwierdzony) | POTWIERDZONA | `test_risk_execution` |
| Wykonanie ACTIVE | `execution/gateway.py` (`execute`, ponowna walidacja przed wysłaniem, idempotencja UNIQUE) | POTWIERDZONA (mock) | `test_risk_execution` |
| Wykonanie SH | `sh/executor.py` (claim akcji, UNKNOWN bez ponowień) | POTWIERDZONA dla PAPER / AUTO_DEMO (mock); **AUTO_LIVE bezwarunkowo odrzucane** | §4 |
| Ręczny pad | `execution/manual.py` (plan TTL, intencja, klucz idempotencji, reconcile) | POTWIERDZONA (mock) | `TestManualPadRuntime` |
| Prowadzenie pozycji | `execution/manager.py` (TP1→BE, partiale, adopcja), `sh/service.py` | POTWIERDZONA (mock) | `test_risk_execution`, `test_sh_service` |
| Statystyki | `stats.py` (ROI Dietza, definicje, tryby osobno) | POTWIERDZONA | `test_stats_definitions` |
| Panel (stary) | `frontend/src/pages/*`, `components/*`, `nc/*` | POTWIERDZONA | `test_ui_*` |
| Panel (nowy) | `frontend/src/features/*` | szkielet etapu 1 – sekcje **niezintegrowane** | `test_ui_terminal_shell` |
| Telegram | `notify/telegram.py` – **tylko nowe sygnały**, token w `secrets_store` (DPAPI na Windows) | W_KODZIE_NIEZWERYFIKOWANA (wysyłka); powiadomienia o otwarciu / zamknięciu, statystyki, EN + ZH, wiadomość testowa: **BRAKUJE** | §7 |

## 3. Execution Lock – pełna mapa (do wycofania zgodnie z decyzją użytkownika)

| Miejsce | Co robi dziś | Skutek |
|---|---|---|
| `config.py: ExecutionConfig.lock` (`LOCKED` / `UNLOCKED_BY_USER`), `lock_changed_at` | stan blokady | domyślnie `LOCKED` |
| `config.py: ConfigStore.execution_locked()` | `True` gdy nie `UNLOCKED_BY_USER` | czytane przez worker i ścieżki |
| `config.py: _to_v11` | migracja v10→v11 ustawia `LOCKED` wszystkim | stara konfiguracja zawsze zablokowana |
| `runtime.py:56` | `worker.lock_fn = cfg.execution_locked` | podpięcie do workera |
| `mt5/worker.py: _LockedTerminal`, `lock_fn`, `locked_attempts` | proxy modułu MT5: `order_send` → `ExecutionLocked` dla **każdego** wywołującego | blokuje wejścia, modyfikacje, zamknięcia, partiale |
| `mt5/fake.py:559` | symulator „przegląda” proxy | tylko testy |
| `execution/gateway.py` (`_validate`, `common_checks`, `manual_modify`) | `EXECUTION_LOCKED` dla AUTO / ręcznych / modyfikacji | odmowa |
| `execution/manager.py: close_positions` | zamknięcie ręczne → `EXECUTION_LOCKED` | nie da się zamknąć pozycji z panelu |
| `execution/manual.py` (`plan` – pole, `manage`) | zarządzanie pozycją padu → `EXECUTION_LOCKED` | odmowa |
| `execution/modes.py: gate` | powód `EXECUTION_LOCKED` + pole `execution_lock` | tryby AUTO nieaktywne |
| `sh/executor.py: _gate` | AUTO_DEMO → `EXECUTION_LOCKED` | odmowa SH |
| `api/app.py` (`/state.execution_lock`, `/lab/tradepad/plan`, `GET/POST /api/v1/execution/lock`, fraza `ODBLOKUJ WYKONANIE ZLECEN`) | stan i odblokowanie frazą | UI pokazuje / zmienia |
| `lab/edge.py` | opis „BLOCKED_BY_EXECUTION_LOCK” | tylko tekst |
| frontend (`TerminalHeader` „Lock”, `ExecutionLockPanel`/ustawienia) + testy | wyświetlanie, odblokowanie | do usunięcia / zmiany |

Plan (DK1): pole `lock` przestaje mieć jakikolwiek wpływ (migracja v12 usuwa je z konfiguracji i zapisuje w audycie, że stary
stan nie jest już egzekwowany), worker przekazuje moduł MT5 bez proxy, ścieżki tracą warunek `EXECUTION_LOCKED`, trasa z frazą
odblokowania znika (zwraca 410 z wyjaśnieniem dla starych klientów). **Bez** nowej blokady pod inną nazwą. Pozostają: tryb, rachunek
potwierdzony dla AUTO, typ rachunku (DEMO/REAL), STOP nowych wejść, limity ryzyka użytkownika, świeżość danych, uzgodnienie z terminalem,
idempotencja i serializacja przez worker.

## 4. Odmowa AUTO_LIVE w ścieżce SH (`sh/executor.py: _gate`)

* `AUTO_LIVE` → `AUTO_LIVE_ZABLOKOWANE_DLA_SH` **bezwarunkowo** – także dla akcji zarządzania (zamknięcie, partial, modyfikacja SL/TP),
  bo `_gate` jest wywoływane w `_run` dla każdej akcji. Skutek: przy AUTO_LIVE SH nie otworzy pozycji, ale też **nie poprowadzi** pozycji
  otwartej wcześniej.
* `SIGNALS` → `TRYB_SIGNALS_BEZ_WYKONANIA` także dla akcji zarządzania – przełączenie na SIGNALS przy otwartej pozycji SH zatrzymuje jej
  prowadzenie przez bota.
* Plan (DK1): rozdzielić bramkę **otwarcia** (tryb, rachunek, walidacja ścieżki) od bramki **zarządzania** (pozycja należy do SH i do tego
  rachunku – zarządzanie zawsze dozwolone, poza PAPER, który zarządza symulacją). AUTO_LIVE dla otwarć SH: dozwolone tylko przy rachunku REAL
  i **zaliczonej walidacji ścieżki SH** dla instrumentu (`sh/validation` – dziś `NOT_RUN`); inaczej jawny powód
  `SH_LIVE_WYMAGA_WALIDACJI` widoczny w panelu. LIVE SH **nie jest gotowy** bez tej walidacji na danych użytkownika.

### Wykonano w DK1 (1.24.0)

* `execution.lock` / `lock_changed_at` usunięte z modelu konfiguracji; migracja v12 zdejmuje je z pliku (kopia `config.v11.bak.json`).
  Zapisany tryb AUTO, który stara blokada wstrzymywała (`lock` ≠ `UNLOCKED_BY_USER`), wraca do PAPER z widoczną notatką `mode_note` –
  usunięcie blokady nie uruchamia po cichu wykonania. Tryb AUTO wybrany świadomie (rachunek odblokowany) pozostaje.
* Worker przekazuje moduł MT5 bez proxy; z bramek gateway/manager/manual/modes/SH zniknął warunek `EXECUTION_LOCKED`.
* `GET /api/v1/execution/lock` → `{"lock":"WITHDRAWN"}`, `POST` → 410 `EXECUTION_LOCK_WITHDRAWN` (fraza nie istnieje).
* `PUT /api/v1/config` odrzuca `execution.mode/bound_account/mode_note` (400 `USE_MODE_ENDPOINT`) – wcześniej dało się tak ustawić AUTO_LIVE
  bez potwierdzenia rachunku (neutralizowała to blokada); jedyną drogą zmiany trybu jest `POST /api/v1/mode` z potwierdzeniem.
* SH: bramka wejścia (tryb, typ rachunku, przy AUTO_LIVE raport walidacji `data/sh/validation/<instr>_<strategia>.json` z danymi
  `REAL_USER_DATA`, znaną prowizją, n ≥ 30 i dodatnią wartością oczekiwaną) oddzielona od zarządzania (tylko terminal i rachunek planu).
  Zarządzanie korzysta z trybu zamrożonego w planie, więc późniejsze przełączenie na SIGNALS/STOP nie odcina prowadzenia pozycji.
* Pozostałe pola `execution_lock` w `gold_candles/analysis.py`, `gold_candles/cli.py` i `forecast/double_retest.py` są **opisowe**
  (raport prognozy SHADOW: „ta prognoza nie składa zleceń”) – nic ich nie czyta jako warunku wykonania; zostawione bez zmian.
* Testy: `tests/test_execution_lock_withdrawn.py` + zaktualizowane testy jednostkowe i UI (56 testów UI/API OK).

## 5. Aplikacja Windows – stan i wybór technologii

| Pozycja | Stan |
|---|---|
| `PepeMarketWizard.exe` | **launcher** konsolowy (Go, `tools/launcher`) – menu instalacji / treningu / startu `.bat`; **nie** jest aplikacją z oknem |
| Monitor | serwowany przez backend (FastAPI) pod `http://127.0.0.1:<port>/`, otwierany w zwykłej przeglądarce |
| Python | instalator `01_INSTALUJ.bat` wymaga **ręcznej** instalacji Python 3.13 x64 przez użytkownika, potem `.venv` + `pip --require-hashes` |
| Serwer | blokada jednej instancji, `/api/v1/health`, zamknięcie tokenem (`data/runtime/shutdown.token`), `server.pid` – POTWIERDZONA (`test_app_process`) |
| Dane | `data/` w folderze programu; `MASTERQUO_DATA_DIR` pozwala przenieść dane poza folder programu – POTWIERDZONA (testy używają) |
| Lokalne API | tylko `127.0.0.1`, kontrola Host i Origin, sesja HttpOnly + CSRF, WS z CSRF – POTWIERDZONA (`test_app_process`, `test_sh_api`) |
| Sekrety | DPAPI (bieżący użytkownik) w `data/secrets.dpapi.json` – W_KODZIE_NIEZWERYFIKOWANA na Windows (ścieżka nie-Windows testowana) |

Porównanie opcji (szczegóły i decyzja: [DESKTOP_ARCHITEKTURA.md](DESKTOP_ARCHITEKTURA.md)):

| Opcja | Plusy | Minusy |
|---|---|---|
| **Go + WebView2 (wybrana)** | rozszerza istniejący launcher Go; build krzyżowy z Linuksa bez cgo; mały EXE; osobny proces nadzoru silnika (Job Object – zamknięcie drzewa procesów przy awarii); silnik bez zmian | wymaga środowiska WebView2 (wbudowane w Windows 11, w Windows 10 zwykle obecne – inaczej instalator Evergreen); test okna tylko na Windows |
| Python + pywebview (pythonnet) | jeden język | okno i silnik w jednym procesie (awaria silnika = awaria okna), zależność od .NET/pythonnet, pakowanie PyInstaller tylko na Windows |
| Tauri (Rust) + sidecar Python | dojrzały shell | nowy toolchain (Rust, MSVC – kompilacja krzyżowa z Linuksa trudna), i tak potrzebny Python – bez zysku dla silnika |

Python: wbudowany oficjalny pakiet NuGet `python` (Windows x64, bez instalatora), zależności z `requirements-win.txt` z hashami –
instalowane automatycznie przez aplikację (wariant online) albo dołączone do paczki (wariant offline). Użytkownik nie instaluje Pythona
ani Node.js. MT5 pozostaje osobnym programem. Środowisko treningowe `.venv_candles` pozostaje opcjonalne.

## 6. Nowe panele – stan wyjściowy

Trading Intelligence / AI Neural Lab / System Control Center: szkielet etapu 1 (`frontend/src/features/*`) – nagłówek z backendu
(środowisko, MT5, świeżość, instrument, tryb, Execution Lock), sekcje oznaczone „etap N – nie zintegrowane”. Makiety wymagają
dodatkowo: sidebar RYNEK / SYSTEM z kartą „Silnik bota”, baner z Pepe, przełącznik XAUUSD-/BTC w nagłówku, panel „Wygląd”, układy
wykresów 1/4/6, zakładki Neural Universe / Trening / Walidacja / Wdrożenia, zakładki Przegląd / MT5 / Ryzyko i koszty / Diagnostyka,
preferencje pracy w tle i autostartu.

## 7. Telegram

`notify/telegram.py`: wysyłka tylko przy nowych sygnałach (`runtime.py:166`), deduplikacja w SQLite, błąd nie wpływa na handel. Brakuje:
powiadomień o otwarciu / zamknięciu pozycji z danych MT5, podsumowań statystyk, trybu dwujęzycznego (EN + 中文简体), wiadomości testowej
i konfiguratora w nowym panelu. Osobny bot `frog_wizard_bot/` (statystyki EN/ZH) jest poza paczką klienta. Plan (DK5): rozszerzenie
istniejącego notyfikatora (te same sekrety DPAPI, ta sama deduplikacja), bez udawania połączenia – status z ostatniej rzeczywistej wysyłki.

## 8. Warunki blokujące sygnał i zlecenie

Pełna inwentaryzacja (ACTIVE S01–S12 i SH, rodzaj: `WAIT` / obniżenie oceny / blokada zlecenia, plik, funkcja, przyczyna, test) –
[STRATEGIE_BRAMKI_DESKTOP.md](STRATEGIE_BRAMKI_DESKTOP.md) (etap DK6), na bazie `docs/TABELA_FILTROW.md` i drzewa decyzji
(`engine/decision.py` – 8 bramek). Przed zmianami bramek: porównanie przed/po na tych samych danych (replay).

## 9. Kolejność realizacji

DK1 Execution Lock → DK2 aplikacja Windows → DK3 oprawa + Trading Intelligence → DK4 AI Neural Lab → DK5 System Control Center +
Telegram → DK6 strategie → DK7 testy, pakiet, raport. Execution Lock przed panelami, żeby nowe panele nie budowały UI dla wycofywanej
blokady.
