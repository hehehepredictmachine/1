# Raport testów – MasterQUO AI 1.12.0

## 1.12.0 – scalp M5 Range → M1 Sweep/Reclaim → Retest, hedge, ML/NN – SHADOW (2026-10-15)
Pełny przebieg `python tools/run_tests.py` (Linux, symulator terminala, Chromium, `MQ_CANDLES_PYTHON` = izolowane `.venv_candles`):
**350 testów bota OK + 43 testy środowiska prognoz/scalp OK** (29 referencyjnych `gold_candles`, 7 runtime, 7 nowych `test_scalp_train`),
raport lokalny `data/logs/testy_offline_20261015T145315Z.json`. Pierwszy przebieg pełny – bez błędów.
Nowe: `tests/test_scalp_core.py` (40: przyczynowość i niezmienność prefiksu, sesje/DST, zamrożenie zakresu i `known_at`, TTL retestu,
lustro BUY/SELL, geometria świec i jeden dowód na rodzinę, BB/SAR, kontrakty adapterów i PAL02M bez wartości, rozliczenie Bid/Ask, lot min/krok,
partial TP, SL+TP w jednej świecy, luka przez SL, NETTING/HEDGING, brak drugiego hedge, osierocona noga, timeout bez ponownego wysłania,
limity dzienne po restarcie, idempotentny zapis, brak executora, izolacja awarii, eksport M1–H1 na symulatorze + replay CLI),
`tests/gold_candles/test_scalp_train.py` (7: plan przed treningiem i ponownie użyty, rozłączne okresy, purge, cechy bez look-ahead, etykiety
bez przejścia przez lukę, odczyt przez ścieżkę workera, checksum, syntetyczny model nigdy aktywny, BLOCKED_NO_REAL_DATA),
`tests/test_ui_scalp.py` (3: sześć widoków, EXECUTION_AUTHORIZED=false, brak POST, 390 px bez przewijania poziomego; zrzuty `data/logs/ui_scalp/`).
**Trening i replay na danych rynkowych: NIE wykonane – BLOCKED_NO_REAL_DATA.** Dane syntetyczne służą wyłącznie testom programu.
Nie sprawdzono: Windows, Twój MT5, rzeczywista historia XAUUSD-, ticki, wykonanie brokera.

## 1.11.0 – gold_candles: świece i prognozy SHADOW, eksport historii, trening z planem, Double Retest v2 (2026-10-14)
Pełny przebieg `python tools/run_tests.py` (Linux, symulator terminala, Chromium, `MQ_CANDLES_PYTHON` = izolowane `.venv_candles`):
**307 testów bota OK + 36 testów modułu prognoz OK** (29 testów referencyjnych `gold_candles` + 7 testów runtime), raport lokalny
`data/logs/testy_offline_20261014T174634Z.json`. Wcześniejszy przebieg pominął zestaw prognoz (test integracji usuwał zmienną środowiska
interpretera) – poprawione w teście; jeden test runtime wybierał katalog runu po nazwie – poprawione (wybór po czasie). Bez zmian zachowania programu.
Nowe: `tests/test_forecast_integration.py` (10), `tests/gold_candles/test_runtime.py` (7), `tests/gold_candles/test_candles.py` (29, referencyjne, bez zmian).
Bez `.venv_candles` runner raportuje `SKIPPED_NO_CANDLE_ENV` (nigdy „passed”).
**Trening na danych rynkowych: NIE wykonany – BLOCKED_NO_REAL_DATA** (brak dostępu do MT5 użytkownika w środowisku budowy). Treningi na danych
syntetycznych służyły wyłącznie testom programu. Nie sprawdzono: Windows, Twój MT5, rzeczywista historia XAUUSD-.

## 1.10.1 – połączenie z MT5 po „-6 Authorization failed” (2026-10-13)
Pełny przebieg `python tools/run_tests.py` (Linux, symulator terminala, Chromium): **297 testów, OK** (`data/logs/testy_offline_20261013T131303Z.json`, lokalny).
Nowe: `test_mt5_login.py` (7) – sesja terminala bez danych logowania; logowanie z hasłem tylko z lokalnego magazynu; odrzucone logowanie bez pętli
i z powrotem do sesji terminala; wykrycie uruchomionego terminala przy kilku instalacjach i zapamiętanie go; ustawiona ścieżka nigdy nie jest
zastępowana; polska podpowiedź dla -6; hasło niewidoczne w masce, konfiguracji, statusie i logu.
Nie sprawdzono: prawdziwy pakiet MetaTrader5 i Twój terminal (zachowanie `initialize(login, password, server)` symulowane).

## 1.10.0 – audyt i naprawy P0, walls/formacje/S12, panel na trzy strony (2026-10-13)
Pełny przebieg `python tools/run_tests.py` (Linux, symulator terminala – DANE SYNTETYCZNE, Chromium, bez klucza Claude): **290 testów, OK, 0 pominiętych**
(raport lokalny `data/logs/testy_offline_20261013T122040Z.json`). Pierwszy przebieg: 290 testów, 2 FAIL + 1 ERROR – nieaktualne oczekiwania
(`test_app_process.test_06`: 11 → 12 strategii po dodaniu S12; `test_setup_details`: nowe statusy wierszy OCZEKIWANIE / NIE DOTYCZY) oraz wyścig
w predykacie testu UI (`window.__mqCharts` jeszcze nie istniał) – poprawione w testach, bez zmiany zachowania programu.
Reprodukcje audytu (`audit/repro/repro_audit.py`): 1.9.0 – 8/8 ODTWORZONE, 1.10.0 – 0/8.
Nowe testy: `test_audit_fixes.py` (16), `test_patterns_walls.py` (25), `test_s12_family.py`, `test_setup_groups.py` (2),
`test_ui_pages.py` (8 – nawigacja, Wstecz/Dalej, link, odświeżenie, jeden WebSocket, brak automatycznego zapytania AI i zmiany strategii,
stany karty AI, 5 wykresów z wykresem głównym bez szóstej instancji, rejestr TF na stronie 2, motyw, uszkodzony localStorage, panel boczny,
rozdzielczości 1920×1080 / 1366×768 / 1024 / 390 px bez przewijania poziomego). Dostosowane: `test_ui_monitor` (11), `test_ui_setup_panel` (5,
przeglądanie setupów bez `POST /api/v1/prefs/setup-view`), `test_ui_signal_card` (9). Zrzuty: `data/logs/ui_pages/`.
`npm run typecheck` i `npm run build` – OK.
Nie sprawdzono: Windows (`.bat` tylko statycznie), Twój terminal MT5, prawdziwe API Claude, skuteczność strategii (brak danych OOS – NIE_OCENIONO_SKUTECZNOŚCI).

## 1.9.0 – bez licencji (2026-10-11)
Pełny przebieg `python tools/run_tests.py` (Linux, symulator terminala, Chromium): **224 testy, OK**. Usunięte testy licencji
(`test_license`, `test_license_admin_ui`, `test_app_process.test_90/test_98`); testy procesu i UI startują serwer bez klucza.
Nowy test: `test_relaxed_gates.test_v8_license_section_dropped_on_upgrade` (config v8 z sekcją `license` → v9 bez niej, ustawienia zachowane).
Nie sprawdzono tutaj: Windows (`.bat` tylko statycznie), Twój terminal MT5, prawdziwe API Claude.

## 1.8.0 – wybór setupu, szczegóły, dźwignia (2026-10-11)
Pełny przebieg `python tools/run_tests.py`: **250 testów, 249 OK, 1 FAIL** – `test_ui_signal_card.test_09` (błędy 404 w konsoli: panel szczegółów
pobierał setup z podstawionej w teście decyzji). Poprawka: panel używa wyłącznie identyfikatora scenariusza z trackera silnika; ponowny przebieg
testów UI (`test_ui_signal_card`, `test_ui_setup_panel`, `test_ui_monitor`): 24/24 OK.
Nowe testy:
* `test_leverage_sizing.py` (11): niższy limit dźwigni → mniejszy wolumen; wyższy limit nie zwiększa budżetu ryzyka ani nie przesuwa SL/TP;
  margin i bufor; brak marginu; zaokrąglenia i minimalny lot za duży (ryzyko / margin / ekspozycja); ponowna weryfikacja po zaokrągleniu
  (nieliniowy margin); otwarte pozycje i zlecenia oczekujące (ekspozycja, ryzyko, margin, liczba, brak SL); zerowe equity; brak danych;
  utrata połączenia (kalkulator brokera = None); preferencje per rachunek (serwer:login), walidacja limitu ≤ dźwignia rachunku, trwałość po
  restarcie; tryb SELECTED nie tworzy setupu; bramka wykonania: zmiana ustawień / mniejszy wolumen / nieudane przeliczenie blokują wysyłkę,
  poprawna ścieżka order_check + order_send działa (symulator, tryb AUTO_DEMO na rachunku syntetycznym).
* `test_setup_details.py` (4, silnik + symulator MT5): lista scenariuszy (id, symbol `XAUUSD-`, kierunek, TF, czas), szczegóły BUY/SELL,
  statusy, warunek świecy dopiero po zamknięciu, brak fikcyjnej historii, trzy wartości dźwigni, wpływ limitu 1:1 na wolumen, wybrana strategia
  bez wymuszania i bez zleceń, trwałość po restarcie, utrata MT5 → BRAK DANYCH + ZABLOKOWANE.
* `test_ui_setup_panel.py` (4, prawdziwy monitor w Chromium): AUTO → WSZYSTKIE → „Szczegóły”, odświeżenie zachowuje wybór, WYBRANY SETUP S03
  bez zleceń, ustawienie dźwigni 1:10 (trzy wartości, opcje powyżej dźwigni rachunku niedostępne), **restart programu zachowuje wybory**.
* `test_stats_definitions.test_account_roi…`: ROI rachunku metodą Dietza (wpłata nie jest zyskiem; brak offsetu → brak danych).
NOT_RUN: Twój terminal MT5 / rachunek demo u brokera (`order_calc_margin`, dźwignia i margin `XAUUSD-`, zlecenia oczekujące) – środowisko
budowy ma tylko symulator.


## 1.7.1 – karta sygnału (2026-10-11)
Pełny przebieg `python tools/run_tests.py`: 230 testów; 5 testów wykresów (`test_ui_monitor` 01/02/04/05/06) nie przeszło, bo karta
sygnału przesunęła wykresy poniżej widocznego obszaru (ruch myszy poza oknem) – poprawka w teście (przewinięcie do wykresu),
po niej `test_ui_monitor`: 11/11 OK. Nowe: `test_signal_view.py` (6) i `test_ui_signal_card.py` (9, prawdziwy monitor w Chromium:
BUY, SELL, oczekiwanie z kierunkiem, brak sygnału, blokada, brak danych, AI niedostępne, spóźniona odpowiedź AI, wygaśnięcie,
reconnect, kopiowanie planu = wartości karty, karta = decyzja silnika, 1920/1366/900 px, konsola bez błędów) – PASS.
Zrzuty: `data/logs/ui_signal_card/`. NOT_RUN: Windows i Twój terminal MT5 (środowisko budowy: Linux + symulator).


## 1.7 – przebieg z 2026-10-11

**Środowisko:** Linux, Python 3.13, kontener budowy z symulatorem terminala, Chromium (Playwright). To nie jest
Windows ani Twój terminal MT5.

**Komenda:** `python tools/run_tests.py` (Windows: `05_TESTY_OFFLINE.bat`).

**Wynik:** `Ran 212 tests … OK` – 0 błędów, 0 pominiętych. Raport maszynowy: `data/logs/testy_offline_20261011T133310Z.json`.

Testy procesu aplikacji startują `python -m masterquo serve` dokładnie jak `masterquo_start.bat`.
**1.9.0:** licencjonowanie usunięte – scenariusze 7–11 (licencje) i testy `test_license*` nie istnieją; patrz sekcja 1.9.0 na górze.

### Obowiązkowe scenariusze 1–12

| # | Scenariusz | Testy | Status |
|---|---|---|---|
| 1 | Dotknięcie i potwierdzenie na jednej świecy nie dają wejścia; późniejsze potwierdzenie działa | `test_ema_pullback` (granice FIXED, ta sama świeca, potwierdzenie N+1) | PASS |
| 2 | Zmiana trendu, limit, ponowne dotknięcia, dokładne granice czasu | `test_ema_pullback` (unieważnienie, wygaśnięcie przed potwierdzeniem, `max_pullback_bars` i 0, pierwsze dotknięcie) | PASS |
| 3 | Brak danych, warm-up, ATR 0/NaN, zły SL, minimalny lot ponad budżet, margin | `test_ema_pullback.test_3` (brak ATR, ADX, brak H8 → `BRAK_DANYCH_H8`), `test_6_min_lot_and_gap_rejections`, `test_risk_execution` (min lot nigdy w górę, brak limitów, nieznana prowizja; margin liczony kalkulatorem w ocenie ryzyka), `test_time_and_data` (za krótka historia) | PASS (margin bez osobnego testu odmowy) |
| 4 | M30/H8 w całym potoku: granice świec, świeca otwarta, resampling, DST, as-of | `test_bridge_engine` (natywne H8 wyrównane do 28800, resampling z H1), `test_ema_pullback` (as-of H8, brak lookahead), `test_research_export` (8 TF, DST `NY_CLOSE`), `test_ui_monitor.test_11` (karta M30/H8, 8 wykresów) | PASS |
| 5 | Reconnect/replay bez duplikatów; spóźniona odpowiedź AI nie nadpisuje nowszej; timeout/zły JSON bez fikcyjnego sygnału | `test_agent` (spóźniona odpowiedź, naprawa JSON, timeout), `test_signal_contract` (AI NIEAKTUALNA, AI_BLAD), `test_markets_signals` (deduplikacja), `test_bridge_engine` (gap-fill, reconnect) | PASS |
| 6 | Sizing XAUUSD- od straty do SL i kosztów; statystyki z prowizją, swapem, częściowymi zamknięciami, wpłatami | `test_risk_execution` (order_calc_profit, brak podwójnego spreadu, TP1 częściowe, operacje salda), `test_stats_definitions` (winrate netto, BE osobno, PF, ROI Dietza) | PASS |
| 7 | Każdy start żąda klucza; zły, cofnięty, wygasły lub brak klucza blokuje; dwa starty z tą samą licencją: ponowny prompt, niezmienione `expires_at` | `test_license.test_16`, `test_19`, `test_app_process` (start z kluczem) | PASS |
| 8 | Zegar kontrolowany: tuż przed 72 h / dokładnie 72 h / po; restart, powtórzona odpowiedź i zapisany token nie przedłużają | `test_license.test_01`, `test_18` (powtórzona lub starsza dzierżawa odrzucona), `test_17` (restart serwera), `test_16` (klucz w zmiennych środowiska ignorowany) | PASS |
| 9 | Wygaśnięcie lub cofnięcie w trakcie pracy blokuje operacje; utrata sieci nie daje nieograniczonego dostępu; pozycje chronione | `test_license.test_14` (cofnięcie ≤ 1 dzierżawa, brak sieci → LEASE_LAPSED), `test_app_process.test_98` (API → LICENSE_REQUIRED, STOP i health działają) | PASS |
| 10 | Silnik z pominięciem launchera, API/WS bez sesji, starty ponad limit, panel bez roli | `test_license.test_20` (Runtime bez licencji: brak decyzji, zleceń, agenta), `test_04` (limit sesji), `test_app_process.test_02/05` (sesja, CSRF, WS), `test_license_admin_ui.test_02` (VIEWER → 403) | PASS |
| 11 | Administrator tworzy, kopiuje, przypisuje, wyszukuje, cofa, kończy sesję; użytkownik nie może; rekordy po restarcie | `test_license_admin_ui.test_01` (przeglądarka), `test_license.test_05/06/09/10/12/17` | PASS |
| 12 | Klucze i hasła poza logami, argv, eksportami, paczką i repozytorium; ścieżki Windows ze spacjami; komunikat przy braku serwera | `test_license.test_02` (tylko HMAC w bazie), `test_16/19` (klucz nie pojawia się w wyjściu), `test_app_process.test_90` (brak w logach, configu i API), `test_launchers` (cudzysłowy, CRLF, brak klucza w argumentach), skan sekretów w `tools/build_release.py` | PASS (statycznie dla `.bat`) |

### NOT_RUN – czego nie dało się sprawdzić tutaj

| Element | Powód |
|---|---|
| Uruchomienie `.bat` na Windows | brak Windows w środowisku budowy (sprawdzone statycznie) |
| Twój terminal MT5, `XAUUSD-`, `order_calc_profit` brokera | brak terminala – połączenie **nie jest potwierdzone** |
| Kompilacja Pine (oryginał/FIXED) w TradingView | brak dostępu do TradingView (proxy) – zgodność Pine ↔ Python **niezweryfikowana** |
| Backtest na historii XAUUSD- | brak eksportu z Twojego terminala – RAPORT_WYNIKOW na danych syntetycznych |
| Prawdziwe API Claude | brak klucza – testy z atrapą klienta |

---


Środowisko wykonania testów: **Linux, Python 3.13.16**, kontener budowy (nie Windows, nie Twój terminal).
Data przebiegu: 2026-10-09 (wersja 1.1 – łagodniejsze bramki). Komenda: `python tools/run_tests.py --legacy` (na Windows: `05_TESTY_OFFLINE.bat --legacy`).
Raport maszynowy zapisuje się w `data/logs/testy_offline_*.json`.

Statusy: **PASS** – uruchomione i przeszło; **FAIL** – uruchomione i nie przeszło; **NOT_RUN** – nie uruchomione (z powodem).

## 1. Nowa aplikacja (symulator terminala `mt5/fake.py` + atrapa klienta Claude)

| Plik | Testy | Zakres | Status |
|---|---|---|---|
| `tests/test_time_and_data.py` | 16 | offset serwera (pomiar, niewyrównana delta → INCONSISTENT, powtórzony tick nie liczony, zmiana DST, sekundy vs ms), świeca z przyszłości przy złym offsecie blokuje, duplikaty/błędne OHLC, luka niewyjaśniona vs weekend, za krótka historia, nieświeży quote, dokładny symbol `XAUUSD-`, bezpieczne domyślne, wymagania historii z profili, brak błędnego symbolu w aktywnym kodzie | PASS |
| `tests/test_bridge_engine.py` | 14 | okno wejścia konfigurowalne (1.1), 6 TF z dokładnym symbolem, brak podmiany symbolu, rozłączenie/reconnect/zmiana rachunku, gap-fill po pominiętych odczytach, lifecycle M10A (postęp o 1 etap/świecę, unieważnienie, TTL/MISSED_ENTRY, sprzeczne reguły), pivot dostępny dopiero po prawych świecach, snapshot bez świecy formującej, hash silników vendor, MACD signal = SMA | PASS |
| `tests/test_risk_execution.py` | 21 | brak podwójnego spreadu + RR netto, min lot nigdy w górę, brak limitów blokuje (RR widoczne), nieznana prowizja/poślizg blokuje, netting, dzienna strata bez operacji salda, progi RR (1.1: RR warunkowy = połowa ryzyka; oryginał M11 nadal dostępny), EARLY ≠ wykonanie, READ_ONLY, bramki AI/ryzyka, tryby i potwierdzenia, PAPER bez `order_send` i idempotentny, DEMO jedno zlecenie z SL/TP i po restarcie, timeout → UNKNOWN bez ponowienia + rekonsyliacja, TP1 częściowe + SL→BE (DEMO symulator i PAPER), odrzucenie brokera, decyzja przeterminowana/zastąpiona, brak liczb demo w statystykach, migracje + kopia | PASS |
| `tests/test_agent.py` | 11 | polityka VETO/REQUIRED/ADVISORY (1.1), pętla narzędzi + odpowiedź strukturalna, zły JSON → jedna naprawa, niezgodny snapshot, walidacja argumentów narzędzi, timeout/429/401/model, brak klucza → bramka UNAVAILABLE, reguły bramki, spóźniona odpowiedź nie nadpisuje nowszej, budżet, model z konfiguracji (nie wymyślony) | PASS |
| `tests/test_app_process.py` | 6 | prawdziwy proces serwera: health + pojedyncza instancja, bezpieczeństwo (Host/Origin/CSRF/cookie), stan i wykresy, sekret nigdy nie zwracany, WebSocket auth + resync, STOP zatrzymuje tylko ten serwer | PASS |
| `tests/test_relaxed_gates.py` | 8 | (1.1) polityki struktury H1_LEAD / H1_H4_NOT_OPPOSING / STRICT, wynik M02 niezmieniony, migracja configu v1→v2 (własne wartości zostają), brak kalendarza nie blokuje / okno makro blokuje, przeciwny H4 raportowany | PASS |
| `tests/test_research_export.py` | 1 | eksport historii w UTC wczytywany przez M06R | PASS |
| `tests/test_pipeline.py` | 2 | pełny łańcuch snapshot → decyzja → PAPER; brak AI blokuje wejście, ale kierunek analizy widoczny | PASS |
| **Razem** | **79** | `Ran 79 tests … OK` | **PASS** |

## 2. Testy oryginalnej paczki (kopie vendor uruchamiane na kopii tymczasowej)

| Zestaw | Wynik | Status |
|---|---|---|
| `legacy_core/RUN_ALL_OPERATIONAL_PROFILE_TESTS.py` | 85/85 | PASS |
| `legacy_core/RUN_MACRO_GUARD_ALL_TESTS.py` | 287/287 (49 + 153 + 85) | PASS |
| `legacy_core/RUN_ALL_OFFLINE_TESTS.py` | 47/48 – błąd `test_40_viewer_has_six_correct_roles`: brak modułu `tkinter` w Linuksie budowy (viewer Tk, nieużywany przez nową aplikację) | FAIL (środowiskowy) |
| `m04n/M04N_TESTS.py` | 96/96 | PASS |
| Pełna regresja 794 testów legacy (`--with-regression`/`--full`) | długi przebieg; nie uruchomiono ani w audycie, ani tutaj (w audycie: M00U 76/76, tests 94/94 – patrz `AUDYT_WEJSCIOWY.md`) | NOT_RUN |

## 3. Frontend
| Sprawdzenie | Status |
|---|---|
| `tsc --noEmit` | PASS |
| `vite build` – wynik identyczny z zatwierdzonym `frontend/dist` | PASS |
| Playwright (Chromium): zrzuty 1920×1080, 1366×768, 800×1000; kreator pierwszego uruchomienia, szuflada agenta, odmowa trybu bez limitów (`RISK_LIMITS_NOT_CONFIGURED`), układ 6 wykresów, pełny ekran; konsola – tylko oczekiwany 400 z odmowy trybu | PASS (na danych syntetycznych, przebieg z etapu E) |

## 4. NOT_RUN – czego nie dało się sprawdzić tutaj
| Element | Powód |
|---|---|
| Pliki `01–07*.bat` na Windows | brak Windows w środowisku budowy (sprawdzone statycznie: ASCII, CRLF, ścieżki względne) |
| Pakiet `MetaTrader5` i Twój terminal / rachunek | pakiet działa tylko na Windows; brak terminala – **połączenie z Twoim MT5 nie jest potwierdzone** |
| `02_DIAGNOSTYKA.bat`, `06_DIAGNOZA_CZASU_MT5.bat` na Twoim terminalu | jw. – uruchom je jako pierwsze |
| Prawdziwe API Claude (Anthropic) | brak klucza w środowisku budowy; testy używają atrapy klienta |
| Windows DPAPI | tylko Windows; na Linuksie test obejmuje ścieżkę bez DPAPI |
| Pobranie newsów M04N z sieci | sieć do źródeł zablokowana w środowisku budowy (UI pokazuje UNAVAILABLE) |
| Realne zlecenia DEMO/LIVE | zgodnie z wymaganiem nie składano żadnych realnych zleceń |
| Instalacja zależności z hashami | zweryfikowano pobranie kół `win_amd64` dla cp313 i cp312 (`pip download --require-hashes`), bez instalacji na Windows |

## 5. Kontrola paczki ZIP
| Sprawdzenie | Status |
|---|---|
| `tools/build_release.py`: paczka tylko z plików śledzonych w git; blokada `data/`, `.venv`, `node_modules`, `__pycache__`, `.env`, `*.sqlite`, `*.log`, `secrets.*` | PASS |
| Rozpakowanie do pustego katalogu + `sha256sum -c MANIFEST_SHA256.txt` | PASS |
| Skan rozpakowanej paczki na klucze (`sk-ant-…`, `ANTHROPIC_API_KEY=…`) – jedyne trafienie to atrapa w teście wycieku `tests/test_app_process.py` | PASS |
| `tools/run_tests.py --legacy` uruchomione **z rozpakowanej paczki** – wyniki identyczne jak w sekcjach 1–2 (69 OK; legacy jak wyżej) | PASS |

Znaleziony i naprawiony przy tej kontroli błąd: wzorzec `data/` w `.gitignore` wykluczał też pakiet źródłowy `backend/masterquo/data/`
(moduł jakości danych) – pierwsza próba testów z rozpakowanej paczki dała 10 błędów importu. Wzorzec zakotwiczono jako `/data/`.


## 6. Wersja 1.2 – ACTIVE, 10 strategii, AUTO, animowany monitor (2026-10-09)
Komenda: `python tools/run_tests.py` → **Ran 101 tests … OK** (Linux, Python 3.13.16, symulator terminala, atrapa Claude).

| Plik | Testy | Zakres | Status |
|---|---|---|---|
| `tests/test_strategies.py` | 16 (pętle po 10 strategiach) | dokładnie 10 strategii w rejestrze; dla KAŻDEJ: LONG i SHORT (ceny odbite) z SL/celami po właściwej stronie i symetrią ryzyka, near-miss (płaska świeca – brak triggera), trigger na świecy niezamkniętej nigdy nie potwierdza, warm-up, brak wymaganych danych (reszta skanera działa), determinizm; punktacja (CONFIRMED wymaga triggera, 0 pkt za nieznane składniki), przyczynowość wskaźników (brak look-ahead), Donchian bez bieżącej świecy, pivot dostępny po prawych świecach; tracker dla KAŻDEJ strategii: deduplikacja, odtworzenie po restarcie, natychmiastowe unieważnienie, wygaśnięcie; STALE nie tworzy setupów; histereza obniżenia etapu; selektor: trend → range → ekspansja, brak przełączania przy identycznych danych i małej różnicy, konflikt LONG/SHORT, grupowanie event_id, MANUAL z niedopasowaniem, STALE; decyzja ACTIVE: obserwacja ≠ uprawnienie, „Dopuść do handlu” | PASS (SYNTETYCZNE scenariusze) |
| `tests/test_active_pipeline.py` | 3 | symulator MT5: AUTO działa bez klucza Claude i bez DXY, zmiana AUTO/MANUAL nie włącza zleceń; utrata MT5 → STALE/brak wyboru, reconnect → OK; wybrany CONFIRMED setup → jedno zlecenie PAPER, setup ENTERED, wyłączenie handlu strategii blokuje, zmiana wyboru nie modyfikuje otwartej pozycji | PASS |
| `tests/test_app_process.py` | +3 (razem 9) | prawdziwy proces: kontrakt AUTO, CSRF/Origin, MANUAL/toggle zapisane w backendzie, tryb READ_ONLY i wykonywanie zleceń bez zmian; backend skanuje bez otwartej przeglądarki; GIF żaby 336×468/22 klatki/przezroczystość, upload GIF (403 bez CSRF, 400 dla nie-GIF, 200 + serwowanie) | PASS |
| pozostałe (1.0/1.1) | 79 | bez zmian merytorycznych; testy ścieżki oryginalnej jawnie w profilu ORIGINAL | PASS |

### Monitor (Playwright, Chromium, DANE SYNTETYCZNE)
| Sprawdzenie | Wynik | Status |
|---|---|---|
| Żaba animowana (FULL): dwa zrzuty elementu w odstępie 430 ms | różne (hash) | PASS |
| OFF: dwa zrzuty w odstępie 430 ms; `src` = `frog-dance-static.png` | identyczne | PASS |
| Tło: warstwa `pointer-events: none`, pod interfejsem | tak | PASS |
| Tło animowane | otrzymany plik jest statyczny (1 klatka) – animacja po wgraniu oryginału; ścieżkę uploadu i serwowania sprawdza test_08 (wgranym GIF-em testowym) | NOT_RUN dla oryginalnego GIF-a tła |
| Nakładanie żaby i BALANCE, poziomy scroll – 1920×1080, 1366×768, 420×900 | brak / brak | PASS |
| Błędy konsoli | brak | PASS |
| Obciążenie UI 10 s @1920×1080: FULL vs OFF | FULL 59 fps, 0 long tasks; OFF 60 fps, 0 long tasks; sterta JS 17–18 MB | PASS |
| Opóźnienie aktualizacji (WebSocket, lokalnie) | quote: mediana 1,6 ms, maks 28,6 ms; auto: mediana 3,6 ms | PASS |
| Czas skanu 10 strategii (backend, symulator) | ~85–120 ms na skan, skan co ≥ 2 s tylko przy nowych danych | PASS |

### Replay (SYNTHETIC)
`python tools/replay_strategies.py --synthetic 20 --compare-original` – 2300 kroków M15 (575 h), 0 błędów, wynik w `docs/replay/` i
`docs/POROWNANIE_ORIGINAL_ACTIVE.md`, lejek filtrów w `docs/TABELA_FILTROW.md`. Status: FUNCTIONAL_REPLAY_SYNTHETIC (nie OOS na danych brokera).

### NOT_RUN (1.2)
* Replay i OOS na danych Twojego brokera – brak eksportu CSV z Twojego MT5 w tym środowisku (narzędzie: `tools/replay_strategies.py --csv-dir data\export_mt5_six_tf`).
* Forward test DEMO – wymaga Twojego terminala i czasu.
* Animacja oryginalnego GIF-a tła – plik nie dotarł w postaci animowanej.
* Weryfikacja źródeł książkowych – serwisy wydawców niedostępne (DNS), patrz `docs/ZRODLA_I_ADAPTACJE.md`.
* Windows/MT5/Claude API – jak w sekcji 4.
