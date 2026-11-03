# Raport końcowy – PepeMarketWizard 1.30.1 (bez licencji)

Wypełniony według `06_RAPORT_KONCOWY/SZABLON_ODBIORU.md` z pakietu aktualizacji. Wersja 1.30 = 1.29 (wykresy, strefy, interfejs w stylu
wież, narzędzia wydania) **minus system licencji**, usunięty na Twoje polecenie „Usuń mi te licencje”. **1.30.1** = 1.30.0 + dwie
poprawki znalezione w pełnej regresji 1.30 (niżej). Liczby pochodzą z rzeczywiście uruchomionych komend; czego nie uruchomiono –
oznaczone jako BLOCKED / „nie sprawdzono”.

**Wersja źródła i SHA-256:** gałąź `claude/masterquo-ai-bot-mt5-f7uaht`; paczki 1.30.1 zbudowane z commitu
`82633b581c896d439bdc15de8f735f74accdc74c` (usunięcie licencji: `5505eb1`; wydanie 1.30.0: `dba6216`; 1.29.0: `5298ec2`).
`MANIFEST_SHA256.txt` (lista i sumy 1163 plików programu): SHA-256 `5d5ece4d1d2860ab33a30f006d4be86bb1c8a1f84a4279b415e484aaf740675f`.
**Wersja wydania:** 1.30.1 – jedna wersja programu (bez OWNER / CLIENT, bez serwera licencji). Paczki 1.30.0 zostają w `release/`
(już je masz); **używaj 1.30.1**.
**Data i środowisko:** 2026-11-03; kontener Linux 6.18 (x86_64, 4 rdzenie), Python 3.13.16, Node 22.22, Go 1.24.7, Chromium
(Playwright, rysowanie programowe bez GPU). Bez Windows, bez terminala MT5 (symulator = dane SYNTETYCZNE). Żadnych zleceń LIVE.

## Co usunięto w 1.30
* Backend: strażnik licencji przed każdym nowym wejściem (`execution/gateway.py` – S01–S12, `execution/manual.py` – ręczne,
  `sh/executor.py` + `sh/service.py` – SCALPING/HEDGING), blokada Telegrama dla nowych sygnałów (`notify/telegram.py`), API
  `/api/v1/license*` i `/api/v1/owner/*`, sekcja `license` w stanie, cały moduł `backend/masterquo/license/`. Bramki wróciły do stanu
  sprzed 1.27 (tryb, STOP, ścieżka główna, ryzyko, rachunek – bez zmian).
* Panel: okno KEY FOR MAGIC, License Manager, obszar „Licencje”, chipy OWNER/CLIENT (pasek zwykły, wieże, terminal), edycja w tytule.
  Dawny link `#/licencje` otwiera Ustawienia.
* Aplikacja Windows: tytuł okna „PepeMarketWizard 1.30.1” (bez edycji).
* Repozytorium: `license_server/`, `edition.json`, `tools/stamp_client_edition.py`, `PRZYGOTUJ_PACZKE_KLIENTA.bat`,
  `docs/LICENCJE_SYSTEM_1_27_PL.md`, testy licencji (6 modułów); zależności Windows dodane tylko dla licencji: `cryptography`, `cffi`,
  `pycparser`. Historia 1.27–1.29 zostaje w git.
* Dane użytkownika: pliki po licencjach (`license_owner.json`, `license_owner_key.*`, token licencji) nie są używane ani usuwane
  automatycznie – można je skasować ręcznie z folderu `data`.

## Poprawki 1.30.1 (z pełnej regresji 1.30)
1. **Panel Neural Cyberpunk zawieszał okno bez akceleracji GPU** (`test_nc_panel`). Animowany „mózg” przerysowywał statyczną warstwę
   (ok. 700 linii, każda z osobnym rozmyciem w trybie `lighter`) przy każdym odświeżeniu rejestru modeli – co kilka sekund. Przy
   rysowaniu programowym (np. Windows VPS / maszyna wirtualna) każde przerysowanie blokowało okno na ok. 10 s. Ten sam wynik na 1.29.0
   (usterka od 1.17, nie skutek usunięcia licencji). Teraz warstwa rysuje się tylko przy zmianie rozmiaru, poświata w jednym
   przejściu rozmycia. Pomiar 1440×900 bez GPU: otwarcie panelu **ok. 1 s (było 20–40 s)**, **ok. 58 klatek/s (było ok. 2)**,
   wygląd bez zmian (zrzuty porównane).
2. **Fałszywy „TIMEOUT > 10s” w karcie FFT tuż po starcie** (`test_ui_analytics`, odtworzone przy osobnym uruchomieniu). Do limitu
   pierwszego obliczenia wliczał się jednorazowy import `scipy.signal`, który przy starcie wszystkich usług trwał ponad 10 s. Wątek
   analityki ładuje teraz biblioteki raz, przed pierwszym obliczeniem. Nowy test `test_library_load_is_not_counted_in_the_timeout`
   (bez poprawki kończy się „TIMEOUT”); `test_late_result_discarded_and_snapshots_kept` czeka na warunek zamiast stałych 1,5 s
   (pod obciążeniem 4 rdzeni 6/6 OK).

Bez zmian w logice bota, strategiach, progach, ryzyku, kosztach, trybach, danych i API.

## Tabela odbioru

| Wymaganie | Status | Dowód / wynik / plik |
|---|---|---|
| Inwentaryzacja przepływu danych i modeli | PASS | `docs/AKTUALIZACJA_1_29_PL.md` §1 (bez zmian w 1.30 poza usunięciem bramki licencji przed wykonaniem) |
| Logika, ryzyko i nowe zlecenia | PASS | strategie, progi, ryzyko, koszty bez zmian; nowe wejścia: tryb, STOP, ścieżka główna, ryzyko, rachunek – bez licencji; `test_sh_*`, `test_app_process`, `test_execution_lock_withdrawn`, `test_telegram` OK |
| Zarządzanie otwartymi pozycjami | PASS (symulator) | bez zmian; moduły zarządzania pozycjami w pełnej regresji OK |
| Jednolity UI i dawne linki | PASS (Chromium) | `test_ui_interface_129` 4/4: obszary wież (bez Licencji), pasek stanu w 3 ramach, 30 dawnych linków + `#/warunki/S01`, `#/licencje` → Ustawienia, 1280×720 / 1920×1080 / 2×, fokus klawiatury, `prefers-reduced-motion`; **brak śladów licencji** (API 404, brak okien i chipów, pozostawiony `edition.json` bez wpływu) |
| Personalizacja wykresów, trwały zoom | PASS (Chromium) | `test_ui_chart_prefs` 6/6 |
| Strefy M1/M5/M15 + LIVE + brak look-ahead | PASS (symulator) | `test_ui_chart_prefs`, `test_ui_market_zones`, `test_market_zones` OK |
| Panel Neural Cyberpunk bez GPU | PASS (Chromium, 1.30.1) | `test_nc_panel` 1/1 (12 ekranów × 1440 / 390 px); pomiar otwarcia i klatek – sekcja „Poprawki 1.30.1” |
| Serwer licencji + TLS | **N/D – usunięty** | system licencji usunięty na Twoje polecenie |
| OWNER bez ekranu logowania, autoryzacja admina | **N/D – usunięty** | j.w. |
| CLIENT: 72h/7d/31d i brak funkcji admin | **N/D – usunięty** | jedna wersja dla wszystkich, bez klucza |
| Brak sekretów w każdej paczce | PASS | `python tools/verify_release.py --all` → OK ×2 (ZIP-slip, sumy manifestów, pliki zabronione, skan kluczy/tokenów, `.sha256`, brak elementów usuniętego systemu licencji) |
| Testy backend / frontend / end-to-end | PASS | pełna regresja + powtórki po poprawkach – sekcja „Testy” |
| Windows + WebView2 + czysta instalacja | **BLOCKED** | brak Windows w tym środowisku; EXE zbudowany, `GOOS=windows go vet` OK |
| MT5 DEMO: eksport → trening → walidacja | **BLOCKED** | brak terminala MT5; pipeline sprawdzony na symulatorze |
| Migracja danych, backup i rollback | PASS (kopie danych) | `python tools/migration_check.py` → **11/11 PASS** (1.29.0 worktree `5298ec2` ↔ 1.30.1; pozostałe pliki licencji nietknięte; powrót z kopii) |
| Instrukcje PDF zgodne ze stanem aplikacji | PASS | administrator 8 str., użytkownik 5 str. (`tools/make_manuals.py`, wersja 1.30.1); tylko osadzone DejaVu Sans; strony obejrzane; bez rozdziałów o licencjach |

## Testy – komendy i liczby

**Pełna regresja 1.30** (każdy moduł osobno, `tests/test_*.py`):
* bez UI: **82 moduły, 969 testów** – wszystkie OK poza `test_nc_panel` (usterka 1 → poprawiona); pominięte 4 testy wymagające
  opcjonalnych składników (`onnxruntime`, `pyopencl`, `.venv_candles` ×2).
* UI (Chromium): **15 modułów, 100 testów** – OK poza `test_ui_analytics` (usterka 2 → poprawiona) i `test_ui_lab` (zadanie treningu
  SEW_SNN nie skończyło się w 600 s; w tym czasie uruchamiałem równolegle pomiary przeglądarką i budowanie panelu).

**Powtórki po poprawkach (każda osobno, bez innych obciążeń):**
* `test_nc_panel` **1/1 OK**, `test_ui_analytics` **4/4 OK**, `test_ui_lab` **14/14 OK** (641 s – długi moduł; zadanie SEW_SNN zajmuje
  w tym kontenerze dużą część limitu 600 s).
* `test_analytics` 25/25; `TestServiceIntegration` pod obciążeniem 4 rdzeni 6/6.
* Po zmianie wersji: `test_analytics test_app_process test_desktop_app test_release_tools test_launchers test_execution_lock_withdrawn`
  → 68 testów OK (×2; w pierwszym przebiegu 1 błąd – niestabilny test analityki, przyczyna usunięta wyżej).
* `go vet ./...`, `GOOS=windows go vet ./...`, `go test ./...` (desktop) → OK.
* `tools/migration_check.py` → 11/11 PASS. `tools/verify_release.py --all` → OK ×2.

## Paczki, SHA-256, podpis

| Plik | Rozmiar (B) | SHA-256 | Podpis Authenticode |
|---|---|---|---|
| `PepeMarketWizard_DESKTOP_1_30_1.zip` | 39 685 534 | `1d51b4d5dba07c8e2501519105a6ad5864d7934022f9e2a46cf15396726502e3` | **niepodpisany cyfrowo** (brak certyfikatu) |
| `PepeMarketWizard_1_30_1.zip` | 22 227 879 | `2486829bb806fb976bbd66c7af1d2a1e65ef0176a7fe4f054a9a6c5a9806fc90` | nie dotyczy (bez EXE aplikacji) |
| `Instrukcja_Administrator_PepeMarketWizard.pdf` | 377 322 | `863d15bd71822f8a30694db16f6ae4460c5a8056f1e3df1a9d106661232c7409` | nie dotyczy |
| `Instrukcja_Klient_PepeMarketWizard.pdf` (instrukcja użytkownika) | 1 415 925 | `43a8e8b4b0727d4a1db8bb401dce4b9190c39888e92219db55d30288036b9a77` | nie dotyczy |

Manifest wewnątrz paczki Windows (`MANIFEST_SHA256.txt`) zawiera te same pliki i sumy co manifest paczki folderu (różni się tylko
pierwszy wiersz-opis).

## Gotowość

| Produkt | Status | Uzasadnienie |
|---|---|---|
| PepeMarketWizard 1.30.1 (folder + aplikacja Windows) | **READY do testu na Windows / DEMO** | zbudowany i zweryfikowany, pełna regresja na symulatorze przechodzi (po poprawkach); nie uruchomiony na Windows ani z MT5 – pierwszy start na rachunku DEMO |

## Procedura bezpiecznego rollbacku

1. STOP nowych wejść, zamknij aplikację 1.30.1.
2. Przywróć `data\` z `%LOCALAPPDATA%\PepeMarketWizard\backups\<data>_…` (kopia robiona automatycznie przed aktualizacją) albo z własnej
   kopii; uruchom program 1.29 z jego folderu (wraca wtedy system licencji 1.29).
3. Sprawdzone (`tools/migration_check.py`): 1.29 startuje na kopii sprzed aktualizacji; informacyjnie także wprost na danych po 1.30.1.
   Przejście 1.30.0 → 1.30.1 nie zmienia danych ani bazy (te same migracje).

## Czego nie sprawdzono

* Windows 10/11: start EXE, WebView2, tytuł okna, czysta instalacja, SmartScreen (EXE niepodpisany).
* Prawdziwy MT5 (dane, czas serwera, symbole brokera, koszty), rachunek DEMO, eksport → trening na danych rzeczywistych.
* Płynność panelu Neural Cyberpunk zmierzona w Chromium bez GPU w kontenerze – nie na Windows (WebView2) ani na komputerze z GPU.
* Skuteczność stref, modeli i strategii – nie oceniano; wyniki na danych syntetycznych nie są dowodem przewagi. Nie obiecuję
  win rate, ROI ani zysku.
