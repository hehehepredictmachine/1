# PepeMarketWizard 1.24.0 – aplikacja Windows, trzy panele, wycofanie Execution Lock: raport końcowy

Punkt powrotu: tag `pre-desktop-1.23.0`. Gałąź: `claude/masterquo-ai-bot-mt5-f7uaht`. Etapy: DK0 audyt (`docs/DESKTOP_AUDIT.md`),
DK1 Execution Lock, DK2 aplikacja Windows, DK3–DK5 panele i Telegram, DK6 bramki strategii, DK7 testy, paczka, raport.

## 1. Co działa i które pliki zmieniono

| Obszar | Stan | Najważniejsze pliki |
|---|---|---|
| Aplikacja Windows (własne okno WebView2, nadzór silnika, ikona przy zegarze, autostart do wyboru) | kod gotowy, testy na Linuksie, EXE skompilowany krzyżowo – **nie uruchomiony na Windows** | `desktop/*.go`, `desktop/splash.html`, `desktop/winres/`, `backend/masterquo/desktop.py`, `tools/build_desktop.py`, `docs/DESKTOP_ARCHITEKTURA.md` |
| Wspólna oprawa: menu, nagłówek (źródło danych, MT5, czas aktualizacji, tryb, wejścia, XAUUSD/BTC), Pepe, ustawienia wyglądu (paleta, tekst 12–18 px, ruch pełny/ograniczony/wyłączony, kontrast WCAG) | działa na danych silnika | `frontend/src/features/shell/*` |
| Trading Intelligence: wykresy świec MT5 1/4/6, interwał każdego wykresu M1–D1, zapis układu, setupy z warunkami, trigger, plan, osobno „dlaczego brak sygnału” i „dlaczego brak zlecenia”, saldo/equity/P-L/ROI/win rate, pozycje | działa na danych silnika | `frontend/src/features/trading-intelligence/*` |
| AI Neural Lab: Neural Universe (MLP / Random Forest / XGBoost / Monte Carlo – osobne kształty, obrót, zoom, przepływ, krok, pauza), Trening, Walidacja, Wdrożenia | rejestr modeli z backendu; animacja oznaczona „PRZYKŁAD · NIE DANE MODELU” (silnik nie udostępnia telemetrii aktywacji) | `frontend/src/features/ai-neural-lab/*` |
| Centrum sterowania: stan silnika/MT5/rachunku/danych, tryby z konsekwencjami i potwierdzeniem, STOP, ścieżka główna, MT5, Telegram, praca aplikacji, limity ryzyka i koszty, diagnostyka | działa przez chronione API silnika | `frontend/src/features/system-control/*` |
| Telegram EN + 中文简体 (sygnały, otwarcie/zamknięcie pozycji, dzienne podsumowanie, test) | kod i testy na atrapie; **połączenie z Telegramem nie było sprawdzane** (brak tokenu w tym środowisku) | `backend/masterquo/notify/telegram.py`, `runtime.py`, `sh/service.py`, `config.py`, `api/app.py` |
| Execution Lock wycofany | działa, testy na atrapie MT5 | `config.py` (migracja v12), `mt5/worker.py`, `execution/*`, `sh/*`, `api/app.py`, panel |
| Bramki strategii: wybór AUTO tylko spośród strategii z prawem handlu, AI bez klucza = „nie wymagane”, SH AUTO DEMO bez pełnego modelu | działa, replay przed/po | `strategies/selector.py`, `engine/active.py`, `agent/service.py`, `sh/risk.py`, `tools/replay_strategies.py`, `docs/STRATEGIE_BRAMKI_DESKTOP.md` |

Pełna lista zmian: `git diff --stat pre-desktop-1.23.0..HEAD` (ok. 130 plików). Wersja: `backend/masterquo/version.py` = 1.24.0.

## 2. Execution Lock, tryby, STOP i filtry

* **Execution Lock wycofany** (decyzja użytkownika). Migracja konfiguracji v11 → v12 usuwa pola `lock`; stary stan `LOCKED` nie
  blokuje `order_send`, modyfikacji ani zamknięć żadną drogą (worker MT5 przekazuje terminal bez opakowania blokującego). Nie ma frazy
  odblokowania ani ukrytej blokady zastępczej; dawny endpoint odpowiada `410 EXECUTION_LOCK_WITHDRAWN`.
* Zapisany tryb AUTO, który stara blokada wstrzymywała, migracja zmienia na **PAPER** z komunikatem (`mode_note`) – nic nie startuje LIVE
  po cichu. Nowa instalacja: PAPER. Import danych do aplikacji desktop: tryb AUTO → PAPER.
* **Tryby:** SIGNALS (bez zleceń), PAPER (symulacja lokalna), AUTO DEMO (potwierdzenie numerem rachunku DEMO), AUTO LIVE (potwierdzenie
  `LIVE <login>`, tylko rachunek REAL, odmowa na danych syntetycznych). Wybór jest zapamiętany dla rachunku – to nie jest odblokowanie przy
  każdym starcie. Zmiana rachunku w terminalu wstrzymuje wysyłkę do ponownego potwierdzenia. Tryb zmienia tylko `POST /api/v1/mode`
  (Centrum sterowania → Tryb pracy); zwykły zapis ustawień go nie zmienia.
* **STOP** zatrzymuje nowe wejścia; otwarte pozycje są dalej prowadzone (SL/TP, części, BE, zamknięcie), ręczne zamknięcie działa.
* **Filtry:** szczegółowa tabela w `docs/STRATEGIE_BRAMKI_DESKTOP.md`. Zmienione: (1) wybór AUTO bierze tylko strategie z prawem handlu
  – strategie „tylko sygnały” (domyślnie S11, S12) dalej sygnalizują, ale nie zajmują wyboru; (2) brak klucza/agenta AI = węzeł AI
  „nie wymagane” od razu; (3) SCALPING/HEDGING w AUTO DEMO nie wymaga pełnego modelu (AUTO LIVE nadal wymaga). Zostały: dane i świeżość,
  rynek/makro, warunki setupu i trigger, limity ryzyka użytkownika, **nieznana prowizja blokuje zlecenie** (rachunek Zero nie dowodzi
  zerowych kosztów – wpisz prowizję, także 0, jeśli ją znasz), warunki brokera, ścieżka główna, STOP.
* **SH AUTO LIVE:** bezwarunkowa odmowa zastąpiona walidacją ścieżki na danych użytkownika (`30_SH_WALIDACJA.bat`: dane z terminala,
  znana prowizja, n ≥ 30 cykli, dodatni wynik po kosztach). **Nie jest to gotowość do LIVE** – walidacji nie wykonano na Twoich danych.

## 3. MT5, Telegram, EXE, trening

* **MT5:** zainstalowany i zalogowany terminal MT5 na tym samym komputerze, „Algo Trading” włączone. Centrum sterowania → Konfiguracja MT5
  (ścieżka `terminal64.exe` opcjonalnie, login/serwer opcjonalnie; hasło tylko w lokalnym magazynie DPAPI). Złoto: `XAUUSD-`; BTC:
  Ustawienia → Aktywa → BTC → „Szukaj kandydatów” → „Potwierdź” (lista z metadanych symboli brokera). Prowizja: Centrum sterowania →
  Ryzyko i koszty.
* **Telegram:** utwórz bota u @BotFather, zdobądź chat ID; Centrum sterowania → MT5 i połączenia → Telegram: token (pole hasła, zapis
  szyfrowany DPAPI, nigdy w logach), chat ID, język EN + 中文 / EN / 中文, rodzaje wiadomości, godzina podsumowania (UTC), „Wyślij test”.
  Stan „OK” pojawia się dopiero, gdy Telegram przyjmie wiadomość; błąd pokazuje opis Telegrama bez tokenu.
* **EXE:** rozpakuj `PepeMarketWizard_DESKTOP_1_24_0.zip` do nowego folderu → `PepeMarketWizardDesktop.exe`. Pierwszy start: import
  poprzedniej instalacji (kopia, oryginał nietknięty) albo start od zera → instalacja składników z PyPI ze sprawdzeniem SHA-256
  (ok. 110 MB) → panel. Wymaga WebView2 (Windows 11 ma wbudowany). Python jest w paczce; Node.js niepotrzebny. Wynik to katalog z EXE
  (nie pojedynczy plik i nie instalator MSI). Lista kontrolna: `docs/DESKTOP_ARCHITEKTURA.md` §9.
* **Trening:** AI Neural Lab → Trening (gotowość danych, profil, „Rozpocznij trening” z potwierdzeniem; osobny proces, bez zleceń) albo
  `22_TRENUJ_WSZYSTKIE_MODELE.bat` / `PepeMarketWizard.exe` (starszy launcher). Trening nie podmienia modelu LIVE – aktywacja tylko
  modeli zaliczonych walidacją, wybór w Wdrożeniach.

## 4. Testy faktycznie wykonane, porównanie strategii, ograniczenia

Wszystko uruchomione w tym środowisku (Linux, Python 3.13, Chromium/Playwright, Go 1.24) – **bez Windows, bez terminala MT5, bez
prawdziwego rachunku i bez połączenia z Telegramem** (atrapy MT5 i HTTP).

| Zestaw | Wynik |
|---|---|
| Pełny zestaw offline `tools/run_tests.py` (944 testy, w tym testy UI w Chromium) | 1. przebieg: 926 OK, 9 FAIL + 5 ERROR w 10 modułach, 4 pominięte. Przyczyny (obie w kodzie 1.24): **(a)** regresja DK1 – `is_fake()` przestał rozpoznawać symulator za proxy tylko-do-odczytu treningu, więc eksport `--demo` był oznaczany `REAL_USER_DATA` (9 testów); **(b)** skrypt reprodukcji audytu ustawiał usunięte pole `execution.lock` (5 błędów). Obie naprawione, dodany test regresji |
| Ponownie 10 modułów z błędami (po poprawkach) | 153 testy OK, 4 pominięte. Pozostałe moduły przeszły w 1. przebiegu; całego zestawu po poprawce nie powtarzano (poprawki dotyczą tylko `is_fake`, skryptu audytu i tekstów) |
| Pominięte (4) | brak `onnx`/`onnxruntime`, brak `pyopencl`, 2× brak `.venv_candles` (trening prognoz – środowisko tworzy `10_PROGNOZY_INSTALUJ.bat`); zestaw `gold_candles`: pominięty z tego samego powodu |
| Aplikacja desktop (Go) | `go test` (układ folderów, argumenty pip, import/kopia/neutralizacja AUTO, decyzje startu, **test integracyjny z prawdziwym silnikiem**: start, podłączenie do działającego, restart po awarii, restart na żądanie, zatrzymanie) – OK; `go vet` dla Windows – OK; kompilacja Windows x64 GUI + odczyt zasobów PE – OK |
| Panel | `tsc --noEmit` OK, `vite build` OK; po przebudowie paczki panelu ponownie `test_ui_control_center` – 5 OK |

Pokrycie scenariuszy obowiązkowych (atrapy): stara konfiguracja `LOCKED`, nowa instalacja w PAPER, AUTO DEMO/LIVE z potwierdzeniem
rachunku, STOP tylko nowych wejść + prowadzenie i zamknięcie otwartej pozycji – `test_execution_lock_withdrawn`; PAPER/SIGNALS bez
`order_send` i idempotencja – `test_risk_execution`; nieznany wynik wysyłki bez ponownego wysłania i uzgodnienie – `test_risk_execution`
(`test_timeout_unknown_no_resend_then_reconciled`), `test_sh_risk_state` (`test_rejection_and_unknown_not_resent`, właściciel pozycji);
netting/hedging – `test_risk_execution`, `test_sh_risk_state`; rozłączenie i ponowne połączenie – `test_bridge_engine`, `test_app_process`;
brak klucza AI / modelu – `test_agent`, `test_gates_dk6`, `test_relaxed_gates`; XAUUSD / BTC – `test_lab`; nieznane koszty blokują –
`test_risk_execution`; tryby i STOP z panelu, limity, Telegram, Neural Lab – `test_ui_control_center`; puste/nieaktualne dane, utrata
połączenia, klawiatura, brak przewijania poziomego przy 4 szerokościach, wygląd – `test_ui_terminal_shell`; Telegram (formaty EN/ZH,
uczciwy stan, brak tokenu w błędach, deduplikacja) – `test_telegram`; endpointy desktop – `test_desktop_app`.
Nie sprawdzono: skalowania Windows 100–200 %, pracy na wolniejszym komputerze, okna/zasobnika/rejestru Windows, prawdziwego MT5 i Telegrama.

**Porównanie przed/po (DK6):** wyłącznie dane syntetyczne (symulator), ten sam kod skanera/selektora, koszty w R, podział 60/20/20.
Całość: 820 → 913 transakcji, wartość oczekiwana 0,144 R w obu wariantach; OOS: 0,257 R (143) → 0,223 R (166), maks. obsunięcie OOS
6,3 → 10,5 R. Przypadki, w których wybór trzymała strategia „tylko sygnały”: 358 → 0. **To nie jest dowód skuteczności** – zmiana
usuwa kolizję bramek; liczby na danych syntetycznych nie uzasadniają tezy o poprawie ani pogorszeniu. Polecenie dla Twoich danych:
`docs/STRATEGIE_BRAMKI_DESKTOP.md` §4.

**Ograniczenia:** Neural Lab nie pokazuje rzeczywistych aktywacji (brak telemetrii w silniku – widok ilustracyjny, jawnie oznaczony);
Telegram nie był połączony z prawdziwym botem; nie było terminala MT5 ani danych brokera; EXE niepodpisany (SmartScreen).

## 5. Co wymaga Windows, MT5, danych brokera lub decyzji

* **Windows 10/11 x64:** uruchomienie EXE, okno WebView2, ikona przy zegarze, pytanie przy zamknięciu, pojedyncza kopia, Job Object
  (zamknięcie EXE kończy silnik), autostart w rejestrze, instalacja składników z PyPI, skalowanie 100–200 % – lista w
  `docs/DESKTOP_ARCHITEKTURA.md` §9.
* **Zalogowany MT5:** rzeczywiste świece i notowania, rachunek, typ hedging/netting, dźwignia, prowizja; reconnect po rozłączeniu terminala.
* **Rachunek DEMO (po Twojej zgodzie):** AUTO DEMO na prawdziwym serwerze brokera – zlecenia, modyfikacje, zamknięcia, ścieżka SH.
* **Dane brokera:** replay przed/po na Twojej historii; walidacja SH (`30_SH_WALIDACJA.bat`) przed AUTO LIVE; trening modeli.
* **Decyzje:** przełączniki handlu per strategia (S11/S12 domyślnie tylko sygnały), wartość prowizji, limity ryzyka (bez nich wejścia są
  wstrzymane), wybór ścieżki głównej per instrument, ewentualny podpis kodu EXE, Telegram.

## 6. Paczka i rollback

Zbudowane w tym środowisku (Linux, kompilacja krzyżowa; **nie uruchomione na Windows**):

| Plik | Zawartość | Rozmiar | Suma kontrolna |
|---|---|---|---|
| `release/PepeMarketWizard_DESKTOP_1_24_0.zip` | folder `PepeMarketWizard_Desktop/`: **nowe** `PepeMarketWizardDesktop.exe` (Windows x64 GUI, wersja 1.24.0.0, ikona, manifest DPI), Python 3.13.17 (`runtime/python/`), silnik, panel, launchery, dokumentacja | ok. 36 MB | obok: `.zip.sha256` |
| `release/PepeMarketWizard_KLIENT_1_24_0.zip` | klasyczna paczka klienta (pliki `.bat`, wcześniejszy launcher `PepeMarketWizard.exe`) | ok. 18,5 MB | obok: `.zip.sha256` |

`PepeMarketWizard.exe` (konsolowy launcher z wersji 1.16) **nie jest** nową aplikacją – nowa aplikacja to `PepeMarketWizardDesktop.exe`.
Wariant offline (koła Pythona w paczce, ok. 150 MB): `python tools/build_desktop.py --offline` – nie budowano.

**Rollback:** `ROLLBACK.md` §10 – poprzednia wersja z jej folderu (aplikacja desktop pracuje na kopii danych w
`%LOCALAPPDATA%\PepeMarketWizard`), konfiguracja sprzed migracji `data\config.v11.bak.json`, kopie danych aplikacji w
`%LOCALAPPDATA%\PepeMarketWizard\backups\`, w repozytorium tag `pre-desktop-1.23.0`.
