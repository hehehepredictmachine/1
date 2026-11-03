# Raport końcowy – PepeMarketWizard 1.30.0 (bez licencji)

Wypełniony według `06_RAPORT_KONCOWY/SZABLON_ODBIORU.md` z pakietu aktualizacji. Wersja 1.30 = 1.29 (wykresy, strefy, interfejs w stylu
wież, narzędzia wydania) **minus system licencji**, usunięty na Twoje polecenie „Usuń mi te licencje”. Liczby pochodzą z rzeczywiście
uruchomionych komend; czego nie uruchomiono – oznaczone jako BLOCKED / „nie sprawdzono” / „w toku”.

**Wersja źródła i SHA-256:** gałąź `claude/masterquo-ai-bot-mt5-f7uaht`; paczki zbudowane z commitu
`a2b0d438325d6934272a9e5f0b0361f430296b12` (usunięcie licencji: `5505eb1`; poprzednie wydanie 1.29.0: `5298ec2`).
`MANIFEST_SHA256.txt` (lista i sumy 1163 plików programu): SHA-256 `69a6d39c0ac0f38f704e05a43d77f35905c34fa5c84b834a01bf6ceab372563a`.
**Wersja wydania:** 1.30.0 – jedna wersja programu (bez OWNER / CLIENT, bez serwera licencji).
**Data i środowisko:** 2026-11-03; kontener Linux 6.18 (x86_64), Python 3.13.16, Node 22.22, Go 1.24.7, Chromium (Playwright).
Bez Windows, bez terminala MT5 (symulator = dane SYNTETYCZNE). Żadnych zleceń LIVE.

## Co usunięto w 1.30
* Backend: strażnik licencji przed każdym nowym wejściem (`execution/gateway.py` – S01–S12, `execution/manual.py` – ręczne,
  `sh/executor.py` + `sh/service.py` – SCALPING/HEDGING), blokada Telegrama dla nowych sygnałów (`notify/telegram.py`), API
  `/api/v1/license*` i `/api/v1/owner/*`, sekcja `license` w stanie, cały moduł `backend/masterquo/license/`. Bramki wróciły do stanu
  sprzed 1.27 (tryb, STOP, ścieżka główna, ryzyko, rachunek – bez zmian).
* Panel: okno KEY FOR MAGIC, License Manager, obszar „Licencje”, chipy OWNER/CLIENT (pasek zwykły, wieże, terminal), edycja w tytule.
  Dawny link `#/licencje` otwiera Ustawienia.
* Aplikacja Windows: tytuł okna „PepeMarketWizard 1.30.0” (bez edycji).
* Repozytorium: `license_server/`, `edition.json`, `tools/stamp_client_edition.py`, `PRZYGOTUJ_PACZKE_KLIENTA.bat`,
  `docs/LICENCJE_SYSTEM_1_27_PL.md`, testy licencji (6 modułów); zależności Windows dodane tylko dla licencji: `cryptography`, `cffi`,
  `pycparser`. Historia 1.27–1.29 zostaje w git.
* Dane użytkownika: pliki po licencjach (`license_owner.json`, `license_owner_key.*`, token licencji) nie są używane ani usuwane
  automatycznie – można je skasować ręcznie z folderu `data`.

## Tabela odbioru

| Wymaganie | Status | Dowód / wynik / plik |
|---|---|---|
| Inwentaryzacja przepływu danych i modeli | PASS | `docs/AKTUALIZACJA_1_29_PL.md` §1 (bez zmian w 1.30 poza usunięciem bramki licencji przed wykonaniem) |
| Logika, ryzyko i nowe zlecenia | PASS | strategie, progi, ryzyko, koszty bez zmian; nowe wejścia: tryb, STOP, ścieżka główna, ryzyko, rachunek – bez licencji; `test_sh_*`, `test_app_process`, `test_execution_lock_withdrawn`, `test_telegram` OK |
| Zarządzanie otwartymi pozycjami | PASS (symulator) | bez zmian – brak licencji nie ma już wpływu na nic; moduły zarządzania pozycjami w regresji |
| Jednolity UI i dawne linki | PASS (Chromium) | `test_ui_interface_129` 4/4: obszary wież (bez Licencji), pasek stanu w 3 ramach, 30 dawnych linków + `#/warunki/S01`, `#/licencje` → Ustawienia, 1280×720 / 1920×1080 / 2×, fokus klawiatury, `prefers-reduced-motion`; **brak śladów licencji** (API 404, brak okien i chipów, pozostawiony `edition.json` bez wpływu) |
| Personalizacja wykresów, trwały zoom | PASS (Chromium, 1.29) | `test_ui_chart_prefs` 6/6 (kod wykresów nie zmieniał się w 1.30) |
| Strefy M1/M5/M15 + LIVE + brak look-ahead | PASS (symulator) | `test_ui_chart_prefs`, `test_market_zones` 19/19 |
| Serwer licencji + TLS | **N/D – usunięty** | system licencji usunięty na Twoje polecenie |
| OWNER bez ekranu logowania, autoryzacja admina | **N/D – usunięty** | j.w. |
| CLIENT: 72h/7d/31d i brak funkcji admin | **N/D – usunięty** | jedna wersja dla wszystkich, bez klucza |
| Brak sekretów w każdej paczce | PASS | `python tools/verify_release.py --all` → OK ×2 (ZIP-slip, sumy manifestów, pliki zabronione, skan kluczy/tokenów, `.sha256`, brak elementów usuniętego systemu licencji) |
| Testy backend / frontend / end-to-end | PASS (wybrane) / pełna regresja **w toku** | sekcja „Testy” |
| Windows + WebView2 + czysta instalacja | **BLOCKED** | brak Windows w tym środowisku; EXE zbudowany, `GOOS=windows go vet` OK |
| MT5 DEMO: eksport → trening → walidacja | **BLOCKED** | brak terminala MT5; pipeline sprawdzony na symulatorze |
| Migracja danych, backup i rollback | PASS (kopie danych) | `python tools/migration_check.py` → **11/11 PASS** (1.29.0 worktree `5298ec2` ↔ 1.30.0; pozostałe pliki licencji nietknięte; powrót z kopii) |
| Instrukcje PDF zgodne ze stanem aplikacji | PASS | administrator 8 str., użytkownik 5 str. (`tools/make_manuals.py`); tylko osadzone DejaVu Sans; render obejrzany; bez rozdziałów o licencjach |

## Testy – komendy i liczby

Uruchomione po usunięciu licencji (wszystkie OK):
* `python -m unittest test_app_process test_desktop_app test_execution_lock_withdrawn test_launchers test_sh_api test_sh_core
  test_sh_fixes test_sh_risk_state test_sh_scenario test_sh_service test_telegram test_release_tools test_relaxed_gates` → 114 testów;
  jedyny błąd dotyczył testu narzędzia wydania (oczekiwał starej nazwy zmiennej) – poprawiony, `test_desktop_app` 12/12 OK.
* `go vet ./...`, `GOOS=windows go vet ./...`, `go test ./...` (desktop) → OK.
* UI (Chromium): `test_ui_interface_129` 4/4, `test_ui_analytics` 4/4, `test_ui_terminal_shell` 13/13.
* `tools/migration_check.py` → 11/11 PASS. `tools/verify_release.py --all` → OK ×2.
* Pełna regresja 1.29 (przed usunięciem licencji): 87 modułów nie-UI, 1006 testów – wszystkie OK poza wyścigiem w
  `test_app_process` (poprawiony test).
* **Pełna regresja 1.30 (`regress.sh` + `regress_ui.sh`) – w toku**; wyniki dopiszę po zakończeniu.

## Paczki, SHA-256, podpis

| Plik | Rozmiar (B) | SHA-256 | Podpis Authenticode |
|---|---|---|---|
| `PepeMarketWizard_DESKTOP_1_30_0.zip` | 39 683 696 | `c9fc6529d23efa77d4d7c72c08a0f343834afaa503b84558653dd2fd7b7327ab` | **niepodpisany cyfrowo** (brak certyfikatu) |
| `PepeMarketWizard_1_30_0.zip` | 22 226 038 | `1d8e061beb3d73d1437699cedf4be988adca9d1aed3f4d260624698310a53d33` | nie dotyczy (bez EXE aplikacji) |
| `Instrukcja_Administrator_PepeMarketWizard.pdf` | 371 881 | `0ed4d1b5699e57a4bc7eaca66f712ae96f4fa62d4c2c5ec91787b45db2aa5a42` | nie dotyczy |
| `Instrukcja_Klient_PepeMarketWizard.pdf` (instrukcja użytkownika) | 1 502 462 | `c33376c474fdca71a2090e55d0bdca35facf235a0824753005bd845d05893004` | nie dotyczy |

Manifest wewnątrz paczki Windows (`MANIFEST_SHA256.txt`) jest identyczny z manifestem paczki folderu (porównanie `cmp`).

## Gotowość

| Produkt | Status | Uzasadnienie |
|---|---|---|
| PepeMarketWizard 1.30.0 (folder + aplikacja Windows) | **READY do testu na Windows / DEMO** | zbudowany i zweryfikowany, testy na symulatorze przechodzą; nie uruchomiony na Windows ani z MT5 – pierwszy start na rachunku DEMO |

## Procedura bezpiecznego rollbacku

1. STOP nowych wejść, zamknij aplikację 1.30.
2. Przywróć `data\` z `%LOCALAPPDATA%\PepeMarketWizard\backups\<data>_…` (kopia robiona automatycznie przed aktualizacją) albo z własnej
   kopii; uruchom program 1.29 z jego folderu (wraca wtedy system licencji 1.29).
3. Sprawdzone (`tools/migration_check.py`): 1.29 startuje na kopii sprzed aktualizacji; informacyjnie także wprost na danych po 1.30.

## Czego nie sprawdzono

* Windows 10/11: start EXE, WebView2, tytuł okna, czysta instalacja, SmartScreen (EXE niepodpisany).
* Prawdziwy MT5 (dane, czas serwera, symbole brokera, koszty), rachunek DEMO, eksport → trening na danych rzeczywistych.
* Skuteczność stref, modeli i strategii – nie oceniano; wyniki na danych syntetycznych nie są dowodem przewagi. Nie obiecuję
  win rate, ROI ani zysku.
* Pełna regresja 1.30 – w toku w chwili wydania paczek.
