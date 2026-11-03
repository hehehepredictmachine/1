# Raport końcowy – PepeMarketWizard 1.29.0

Wypełniony według `06_RAPORT_KONCOWY/SZABLON_ODBIORU.md` z pakietu aktualizacji. Wszystkie liczby poniżej pochodzą z rzeczywiście
uruchomionych komend w tym środowisku; czego nie uruchomiono – jest oznaczone jako BLOCKED / „nie sprawdzono”.

**Wersja źródła i SHA-256:** gałąź `claude/masterquo-ai-bot-mt5-f7uaht`; paczki zbudowane z commitu
`207aa0f361c6e28a4f24ce057bceed97be9c3abc` (punkt wyjścia: 1.28.0 = `165bd5d`). `MANIFEST_SHA256.txt` (lista i sumy 1187 plików
programu): SHA-256 `6d617a7204de81a51fdf3fa6047ed4783f057055d07448aaf844c321f93299ed`.
**Wersja wydania:** aplikacja 1.29.0 (OWNER), serwer licencji 1.1.0.
**Data i środowisko:** 2026-11-03; kontener Linux 6.18 (x86_64), Python 3.13.16, Node 22.22, Go 1.24.7, Chromium (Playwright).
Bez Windows, bez terminala MT5 (symulator terminala = dane SYNTETYCZNE), bez publicznego serwera licencji. Żadnych zleceń LIVE.
**Zakres zmian i ścieżki plików:** 61 plików źródłowych (+3745 / −216 wierszy względem 1.28.0, bez `frontend/dist`):
* licencje – `backend/masterquo/license/{url,client,edition,protocol,owner,owner_key}.py`, `license_server/pmw_license/{admin_auth,app,cli,config,store,protocol,__init__}.py`, `license_server/README.md`, `.env.example`, `tools/stamp_client_edition.py`, `frontend/src/features/license/*`;
* wykresy – `frontend/src/chartprefs.ts`, `components/ChartSettings.tsx`, `components/ChartPanel.tsx`, `components/ChartToolbar.tsx`, `features/market-zones/{ZonesControl.tsx,mzStore.ts,ZoneChart.tsx,market-zones.css}`, `pages/{BotChartsPage,AiAnalysisPage}.tsx`;
* interfejs – `frontend/src/{router.ts,theme.tsx,App.tsx,styles.css}`, `components/layout/AppShell.tsx`, `features/wizard/WizardShell.tsx`, `features/shell/{TerminalHeader,TerminalSidebar}.tsx`, `pages/LabPages.tsx`, `desktop/{layout.go,app_windows.go,winres/winres.json,rsrc_windows_amd64.syso}`;
* wydania – `tools/{build_release,verify_release,migration_check,make_manuals}.py`, `backend/masterquo/version.py`;
* testy – `tests/test_license_{acceptance,client,server,url_security}.py`, `tests/test_release_tools.py`, `tests/test_ui_{chart_prefs,interface_129,license}.py` + dostosowane `test_ui_{analytics,lab,pages,terminal_shell}.py`;
* dokumenty – `docs/AKTUALIZACJA_1_29_PL.md`, `CHANGELOG.md`, `START_TUTAJ_PL.md`, PDF w `release/`.

## Tabela odbioru

| Wymaganie | Status | Dowód / wynik / plik |
|---|---|---|
| Inwentaryzacja przepływu danych i modeli | PASS | `docs/AKTUALIZACJA_1_29_PL.md` §1 (źródło → jakość → cechy/strefy → modele → agregacja → strategia → ryzyko → decyzja → wykonanie → monitor/Telegram); koszty: spread zmierzony, prowizja z historii, poślizg = założenie |
| Logika, ryzyko i nowe zlecenia | PASS (bez zmian logiki) | strategie, progi, ryzyko i koszty nietknięte; ścieżki nowych zleceń: `execution/gateway.py` (S01–S12, ręczne – LicenseGuard przed wysyłką), `sh/executor.py` (SCALPING/HEDGING – wejście główne za bramką), zarządzanie `execution/manager.py`; pełna regresja – sekcja „Testy” |
| Zarządzanie otwartymi pozycjami po awarii licencji | PASS (symulator) | `test_license_client`: `test_entry_blocked_position_not_closed_and_still_managed`, `test_sh_primary_entry_gated_management_and_hedge_not`; `test_license_acceptance.test_02` (brak sieci, podmieniony klucz serwera → nowe wejścia zablokowane, pozycje prowadzone) |
| Jednolity UI i dawne linki | PASS (Chromium) | `test_ui_interface_129` 4/4: obszary wież, pasek stanu w 3 ramach, edycja w tytule, 31 dawnych linków + `#/warunki/S01`, mapa ekranów, CLIENT bez Licencji, 1280×720 / 1920×1080 / 2×, fokus klawiatury, `prefers-reduced-motion`; motyw: kontrast WCAG policzony (tekst 16:1, przyciski 14,9:1, osie 10,4:1) |
| Personalizacja wykresów, trwały zoom | PASS (Chromium) | `test_ui_chart_prefs` 6/6: ustawienia po przeładowaniu, izolacja wykresów, reset, szablony, uszkodzony zapis, warstwy, geometria po zoom/pan/resize; zoom/pan/skala – istniejący `chartview` (testy `test_ui_pages`) |
| Strefy M1/M5/M15 + LIVE + brak look-ahead | PASS (symulator) | przycisk w głównym obszarze: `test_ui_chart_prefs.test_01` (zakres M1+M5+M15, 3 kliknięcia = 1 zadanie, M30 nietknięty, LIVE on/off, tylko POST `/market-zones/*`, konfiguracja i tryb bez zmian); NO_DATA / nieaktualne / ponowne połączenie / obcy symbol: `test_05`; look-ahead, nowa świeca, starszy wynik, utrata danych: `test_market_zones` (19 testów) |
| Serwer licencji + TLS | **BLOCKED** (TLS / domena) | kod serwera 1.1.0 PASS lokalnie (`test_license_server`, `test_license_acceptance` przez prawdziwe HTTP na 127.0.0.1); wdrożenie z HTTPS w Internecie – brak serwera i domeny: kroki w `license_server/README.md`, `docs/AKTUALIZACJA_1_29_PL.md` §2, §5 |
| OWNER bez ekranu logowania, autoryzacja admina | PASS (lokalnie) | klucz urządzenia Ed25519 + podpis PMW-ADMIN-v1; `test_license_acceptance.test_03` (bez podpisu / niezaufany / sfałszowany / powtórzenie / podmiana treści / zegar / powtórzenie po restarcie / audyt bez sekretów), `test_05` rotacja, `test_06` CLI + backup/restore; `test_ui_license.test_02` (brak pól hasła, parowanie). DPAPI na Windows – nie sprawdzono |
| CLIENT: 72h/7d/31d i brak funkcji admin | PASS (kod) / **BLOCKED** (paczka) | `test_license_acceptance.test_01` (okresy, aktywacja, restarty, drugie urządzenie, reset, wygaśnięcie, cofnięcie), `test_04` (równoległa aktywacja – 1 urządzenie); stamping usuwa `owner.py`/`owner_key.py` (`test_license_build`); paczka CLIENT nie wydana – brak adresu HTTPS i klucza publicznego |
| Brak sekretów w każdej paczce | PASS | `python tools/verify_release.py --all` → OK ×3 (ZIP-slip, sumy manifestów, pliki zabronione, skan kluczy/tokenów, `.sha256`); skan w `build_release` |
| Testy backend / frontend / end-to-end | W TOKU | sekcja „Testy” niżej |
| Windows + WebView2 + czysta instalacja | **BLOCKED** | brak Windows w tym środowisku; EXE zbudowany (Go, `GOOS=windows go vet` OK), test na czystym Windows 10/11 – do wykonania |
| MT5 DEMO: eksport → trening → walidacja | **BLOCKED** | brak terminala MT5; pipeline przetestowany na symulatorze w 1.28 (`test_trainhub`, `test_marketdata`) – wyniki syntetyczne nic nie mówią o rynku |
| Migracja danych, backup i rollback | PASS (kopie danych) | `python tools/migration_check.py` → 15/15 PASS (1.28 worktree `165bd5d` ↔ 1.29; bot i serwer licencji v1→v2; powrót z kopii) |
| Instrukcje PDF zgodne ze stanem aplikacji | PASS | `release/Instrukcja_Administrator_PepeMarketWizard.pdf` (10 str.), `release/Instrukcja_Klient_PepeMarketWizard.pdf` (5 str.) – generator `tools/make_manuals.py`; tylko osadzone DejaVu Sans (pdffonts), render `pdftoppm` obejrzany; zrzuty z symulatora oznaczone |

## Testy – komendy i liczby

**W TOKU** – pełna regresja (moduły nie-UI i UI) jest uruchomiona; wyniki zostaną wpisane tutaj po jej zakończeniu. Do tej pory uruchomione i zaliczone: `test_license_url_security`, `test_license_client`, `test_license_build`, `test_license_server`, `test_license_acceptance`, `test_release_tools` – 44 testy OK; `go test ./...` (desktop) OK; UI (Chromium): `test_ui_chart_prefs` 6 OK, `test_ui_interface_129` 4 OK, `test_ui_analytics` 4 OK, `test_ui_lab` 14 OK, `test_ui_pages` 8 OK, `test_ui_terminal_shell` 13 OK, `test_ui_market_zones` 1 OK, `test_ui_monitor` 11 OK, `test_ui_license` 2 OK; `tools/migration_check.py` 15/15 PASS.

## Paczki, SHA-256, podpis

| Plik | Rozmiar (B) | SHA-256 | Podpis Authenticode |
|---|---|---|---|
| `PepeMarketWizard_DESKTOP_OWNER_1_29_0.zip` | 39 763 443 | `6fe8f9e95c0559301e231a066a8ba08bbef467cac8f05c4a60ad0763a5554b85` | **niepodpisany cyfrowo** (brak certyfikatu) |
| `PepeMarketWizard_OWNER_1_29_0.zip` | 22 303 865 | `413f6aedf7b2f211ca241fedf343f23879cfcd3d71a78d68fa247df9c3c0798f` | nie dotyczy (bez EXE aplikacji Windows) |
| `PepeMarketWizard_LICENSE_SERVER_1_29_0.zip` | 35 767 | `18fef2acd933b9d6b490e1eb4973f64f1c658f3cbeb4617b47dcb822598fc3c7` | nie dotyczy (Python) |
| `PepeMarketWizard_DESKTOP_CLIENT_1_29_0.zip` | – | – | **BLOCKED – nie wydano** |
| `Instrukcja_Administrator_PepeMarketWizard.pdf`, `Instrukcja_Klient_PepeMarketWizard.pdf` | – | (wersja robocza – zostaną odświeżone ze zrzutami w nowym motywie) | nie dotyczy |

Weryfikacja paczek:
* `python tools/verify_release.py --all` → `OK` dla trzech archiwów (rc=0).
* Build bez `.git`: rozpakowany `PepeMarketWizard_OWNER_1_29_0.zip` (brak `.git`) → `python tools/build_release.py` zbudował paczkę
  z listy `MANIFEST_SHA256.txt`: 1187 wpisów, **identyczne nazwy i treść każdego wpisu** jak w oryginale; serwer licencji pominięty
  z komunikatem (folderu nie ma w paczce bota).
* Diagnostyka z pakietu (`04_DIAGNOSTYKA/sprawdz_paczke.py`, uruchomiona `python -I`) na rozpakowanym DESKTOP_OWNER: OK dla runtime,
  API, silnika stref, Centrum treningu, interfejsu (źródło i build), `PepeMarketWizardDesktop.exe`, `edition.json` (Edycja: OWNER),
  obu manifestów; „BRAK serwer licencyjny” – zgodnie z projektem serwer jest osobną paczką (`license_server/pmw_license/protocol.py`
  jest w `PepeMarketWizard_LICENSE_SERVER_1_29_0.zip`).

## Adres wdrożonej usługi i identyfikator klucza publicznego

**Brak – BLOCKED.** Serwer licencji nie został wdrożony w Internecie (nie mam serwera, domeny ani certyfikatu TLS). Nie podaję
adresu ani klucza przykładowego. Po wdrożeniu: `python -m pmw_license public-key` podaje klucz publiczny i `kid`.

## Gotowość

| Produkt | Status | Uzasadnienie |
|---|---|---|
| OWNER (folder + aplikacja Windows) | **READY do testu na Windows / DEMO** | zbudowany, zweryfikowany, testy przeszły na symulatorze; nie uruchomiony na Windows ani z MT5 – pierwszy start zrób na rachunku DEMO |
| Serwer licencji 1.1.0 | **READY do wdrożenia** | kod przetestowany lokalnie (HTTP 127.0.0.1); TLS, domena, proxy – Twoje wdrożenie wg README |
| CLIENT | **BLOCKED** | wymaga działającego serwera `https://…` i jego klucza publicznego → `docs/AKTUALIZACJA_1_29_PL.md` §5 „Jak wydać CLIENT” |

## Procedura bezpiecznego rollbacku

1. STOP nowych wejść, zamknij aplikację 1.29.
2. Aplikacja Windows: przywróć `data\` z `%LOCALAPPDATA%\PepeMarketWizard\backups\<data>_…` (kopia robiona automatycznie przed
   aktualizacją; pliki > 128 MB tylko wymienione w manifeście kopii) albo z własnej kopii; uruchom program 1.28 z jego folderu.
3. Serwer licencji: zatrzymaj, przywróć bazę z kopii `backup-db` sprzed aktualizacji, uruchom kod 1.0.0. Sprawdzono, że 1.0.0
   pracuje także na bazie v2; OWNER 1.29 wymaga serwera 1.1 (podpis kluczem urządzenia).
4. Sprawdzone (`tools/migration_check.py`): 1.28 startuje na kopii sprzed aktualizacji; informacyjnie także wprost na danych po 1.29.

## Czego nie sprawdzono

* Windows 10/11: start EXE, WebView2, DPAPI klucza OWNER, tytuł okna, czysta instalacja, SmartScreen (EXE niepodpisany).
* Prawdziwy MT5 (dane, czas serwera, symbole brokera, koszty), rachunek DEMO, eksport → trening na danych rzeczywistych.
* Serwer licencji w Internecie (HTTPS, reverse proxy, domena, zegar serwera), aktywacja z innego komputera.
* Paczka CLIENT (nie wydana).
* Skuteczność stref, modeli i strategii – nie oceniano; wyniki na danych syntetycznych nie są dowodem przewagi. Nie obiecuję
  win rate, ROI ani zysku.
* Lokalny Python nie jest odporny na modyfikację przez zdeterminowanego użytkownika – licencja chroni dostęp do serwera, nie kod.
* Ustawienia wykresów są w pamięci okna (WebView2 / przeglądarka): wspólne dla profilu okna, nie synchronizowane między komputerami.
