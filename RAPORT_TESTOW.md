# Raport testów – MasterQUO AI 1.2.0

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
