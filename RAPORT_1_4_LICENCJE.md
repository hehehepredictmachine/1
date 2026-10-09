# Raport 1.4.0 – konta, panel administratora, licencje 48 h

## 1. Co zostało zrobione
Trzy współpracujące części:
1. **Klient** (bot + monitor, `backend/`, `frontend/`): logowanie, rejestracja, reset hasła, aktywacja, ekran blokady z ochroną
   pozycji, pasek licencji, konektor MT5, `LicenseGuard` we wszystkich ścieżkach produktu.
2. **Serwer centralny** (`server/mqcentral`): konta, sesje, MFA, licencje, urządzenia, lease, autoryzacja zleceń, telemetria,
   win ratio, audyt, CLI, migracje (PostgreSQL; SQLite jawnie tylko do developmentu).
3. **MasterQUO License Manager** (`server/admin-web`, `/admin/`) + strony konta (`/account/...`).

Ścieżki uruchamiające funkcje bota i ich kontrola:

| Ścieżka | Kontrola |
|---|---|
| Silnik (pełny i lekki cykl, decyzja, checklista) | `EngineService.licensed()` – bez lease brak cyklu, decyzja czyszczona |
| Skan setupów S01–S10 | `ActiveEngine.maybe_scan` – scope `setups` |
| ML: etykiety, trening, backfill, wyniki | `MLService._licensed` – start, przerwanie w punkcie kontrolnym, wyniki nieopublikowane |
| Agent Claude | `ClaudeAgent.request/_preflight` – scope `agent` |
| Nowe zlecenia otwierające | `ExecutionGateway.execute` (lease) + autoryzacja online intencji + `consume` tuż przed `order_send` |
| API monitora | middleware: bez logowania 401, bez licencji 403 (poza logowaniem, statusem, STOP i ochroną pozycji) |
| WebSocket | strumień i odtwarzanie zdarzeń filtrowane; `session_reset` zamyka subskrypcję |
| CLI `export` | wymaga świeżego lease online (kod wyjścia 3) |
| Konektor MT5 | scope `telemetry`; zgoda na jeden rachunek |
| Obsługa istniejących pozycji (PositionManager) | **celowo bez blokady** – tylko ochrona/redukcja, nigdy zwiększenie ekspozycji |

## 2. Wyniki testów (wykonane w tym środowisku)
`python -m unittest` w `tests/`: **182 testy, 0 błędów, 0 pominiętych** (Linux, Python 3.13, PostgreSQL 16.15 lokalnie,
Chromium/Playwright). Testy serwera uruchamiają się dwa razy: na SQLite i na prawdziwym PostgreSQL.
Test 15 (pełny przepływ) działa na prawdziwych procesach (serwer `python -m mqcentral serve`, bot `--demo`) i w przeglądarce
z dwoma oddzielnymi profilami (klient i administrator). Licencja ma tam 45 s (`MQC_ENV=dev`), żeby wygaśnięcie nastąpiło w trakcie
testu. Granica 172 800 s jest sprawdzana kontrolowanym zegarem. Dane w testach to syntetyczne fixture'y – nie klienci ani wyniki tradingowe.

**Błędy znalezione i naprawione dzięki testom:**
- termin lease był liczony zegarem z modułu HTTP zamiast zegarem usługi;
- przy ponownym połączeniu WebSocket (`last_seq`) odtwarzane były zdarzenia bez filtra licencji;
- STOP nie kończył aplikacji przy otwartej karcie monitora;
- wygaśnięcie licencji było opisywane jako „brak sieci”;
- przy kilku licencjach na jednym urządzeniu wybierana była zła aktywacja;
- czas pomiaru salda był w zegarze komputera zamiast serwera.

## 3. Wymaganie → moduł → test → wynik
| # | Wymaganie | Moduł | Test | Wynik |
|---|---|---|---|---|
| 1 | Rejestracja, weryfikacja e-mail, login/logout, reset, blokada, brak enumeracji, limity | `service.py`, `api.py`, `security.py`, `ratelimit.py` | `test_central …test_01*`, `test_14_invite…` | PASS (SQLite + PostgreSQL) |
| 2 | Brak eskalacji USER→ADMIN, izolacja ID/payload/WebSocket | `api.py` (extra=forbid, admin+MFA), `app.py` (WS filtr) | `test_02_no_escalation_and_isolation`, e2e krok 10 | PASS |
| 3 | Generowanie tylko przez admina, klucz 256 bit pokazany raz, skrót w bazie | `security.license_key`, `generate_license` | `test_03_generate_only_admin_key_shown_once`, e2e | PASS |
| 4 | Aktywacja przez właściciela, inne konto odrzucone, jedno stanowisko, kilka kart | `activate`, `ux_activation_seat` | `test_04…`, `test_ui_monitor` (wiele kart/odświeżeń) | PASS |
| 5 | Granica 48 h: ważne przed, wygasłe w `expires_at` i później | `status_of`, `heartbeat` | `test_05_boundary` (zegar kontrolowany) | PASS |
| 6 | Równoczesna aktywacja, retry, reinstalacja, reset stanowiska, restart serwera | transakcja + blokada wiersza / BEGIN IMMEDIATE | `test_06_concurrent_first_activation_and_no_reset` | PASS |
| 7 | Zegar klienta, strefa, restart, uśpienie, brak sieci, koniec lease | `guard.py`, `service.py` | `test_conservative_deadline…`, `test_wall_clock_changes…`, `test_activation_lease_and_restart…` | PASS |
| 8 | Podrobiony/zmieniony lease, inny odbiorca/urządzenie, cofnięcie, ponowne użycie autoryzacji | `_verify`, `consume`, `op_authorizations` | `test_forged_and_foreign_leases_rejected`, `test_operation_token…`, `test_08_signatures…` | PASS |
| 9 | Backend, CLI, workery mimo pominięcia UI | middleware, guard w silniku/ML/agencie, CLI | `test_engine_ml_agent_denied…`, `test_cli_export_requires_license`, `test_no_license_no_agent`, `test_app_process` (401 bez logowania) | PASS |
| 10 | Wygaśnięcie w trakcie pracy: blokada otwarć, ochrona pozycji, anulowanie własnych zleceń, wyścig | `enforce.py`, `gateway.py` | `test_gateway_blocks_after_loss…`, `test_enforcement_cancels_only_bot_opening_orders`, e2e krok 7 | PASS |
| 11 | Balance/equity/waluta osobno, nieaktualne oznaczone, bez zera | `snapshot`, `account_view` | `test_11_13…`, e2e (panel) | PASS |
| 12 | Win ratio: zysk, strata, neutralny, prowizja, wpłaty, częściowe zamknięcie, odwrócenie, niekompletna historia, mianownik 0 | `stats.py` | `TestWinRatio` (7 testów) | PASS |
| 13 | Deduplikacja, stary snapshot, zmiana rachunku, wznowienie importu | `snapshot`, `deals`, `connector.py` | `test_11_13…`, `test_connector_sends_snapshot_and_deals` | PASS |
| 14 | Wylogowanie/zmiana użytkownika bez danych poprzedniego | `session_reset`, `locked_state`, store | e2e krok 9–10 | PASS |
| 15 | Pełny przepływ rejestracja → … → nowa licencja przywraca dostęp | całość | `test_e2e_licensing.test_full_flow` | PASS |
| – | MFA admina, kody odzyskiwania, Origin | `complete_mfa`, `_check_second_factor` | `test_08c_admin_mfa…` | PASS |
| – | Anomalia zegara wstrzymuje nowe uprawnienia | `clock.py` | `test_08b_clock_anomaly…` | PASS |
| – | Lista admina: szukaj, filtruj, sortuj, stronicuj | `admin_users` | `test_10_admin_list…` | PASS |
| – | Zależności z hashami | `server/requirements-server.txt`, `requirements/requirements-win.txt` | czysta instalacja serwera w venv (Linux); domknięcie zależności klienta dla Windows | PASS (instalacja na Windows: NIE SPRAWDZONA) |
| – | Wcześniejsze funkcje (zoom, motywy, checklista, ML, tryby, strategie) | bez zmian logiki | dotychczasowe testy (przez prawdziwą aktywację) | PASS |

## 4. Czego NIE sprawdzono (brak w tym środowisku)
- Twój terminal MT5 i prawdziwe deale brokera (`history_deals_get` / `account_info` testowane na symulatorze).
- Wysyłka SMTP – testy używały DEV OUTBOX; produkcja wymaga SMTP i bez niego serwer nie wystartuje.
- Publiczny HTTPS (Caddy, certyfikat, domena) – konfiguracja przygotowana, ale **system nie jest wdrożony publicznie**.
- DPAPI na Windows – magazyn sekretów działa jak w poprzednich wersjach; na Linuksie użyty plik z `chmod 600`.
- Instalacja `requirements-win.txt` na Windows – sprawdzone pobranie wheeli (cp312/cp313) z hashami i komplet zależności.

## 5. Wartości do uzupełnienia przy uruchomieniu
**Serwer (`server/.env`):**
- `MQC_DATABASE_URL`
- `MQC_PUBLIC_URL` / `MQC_ALLOWED_ORIGINS` – Twoja domena HTTPS
- `MQC_SIGNING_KEY_FILE` i `MQC_DATA_KEY` – z `gen-keys`
- `MQC_SMTP_*`
- opcjonalnie `MQC_TIME_REFERENCE_URL`

Następnie `bootstrap-admin`.

**Klient:** adres `https://…` serwera, wpisywany na ekranie logowania monitora.

## 6. Realne granice ochrony
**Egzekwowane na serwerze** (nie da się ich obejść modyfikacją programu klienta):
- termin 48 h i cofnięcie;
- przypisanie klucza do konta;
- jedno stanowisko;
- jednorazowe autoryzacje zleceń;
- role i uprawnienia administratora;
- dostęp do danych innych kont;
- obliczanie win ratio z deali.

**Egzekwowane lokalnie** (podatne na zmodyfikowany kod klienta):
- blokada silnika, setupów, ML i agenta;
- filtr API i WebSocket monitora;
- lokalne sprawdzenie podpisu lease.

Program działa w całości na komputerze klienta. Ktoś, kto zmieni jego kod Python, może wyłączyć lokalne kontrole i uruchamiać
strategie bez serwera. Nie dostanie jednak nowych lease, autoryzacji zleceń ani statusu w panelu, a jego statystyki nie trafią na serwer.

Zmodyfikowany klient może też wysłać nieprawdziwe saldo lub deale. Konektor potwierdza tylko powiązanie z urządzeniem, nie
autentyczność danych brokera. Dlatego panel opisuje je jako „dane z konektora MT5”, a nie audyt brokera.

Obfuskacja lub EXE mogą to utrudnić, ale nie są fundamentem zabezpieczenia. System **nie** jest „w 100% nie do obejścia”.
Bez sieci klient działa najwyżej do końca ostatniego lease (≤ 60 s). Cofnięcie licencji dociera do niego najpóźniej wtedy.
