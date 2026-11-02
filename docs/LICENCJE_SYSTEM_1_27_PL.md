# PepeMarketWizard 1.27 – system licencji v1 (OWNER / CLIENT) i sygnały BUY/SELL wszystkich strategii

Realizuje zadanie z paczki `PepeMarketWizard_License_System_v1.0_ClaudeCode.zip` (CLAUDE.md, implementation_spec, api_contract,
security_notes, acceptance_test_plan) oraz polecenie „niech wszystkie strategie mogą nadawać sygnały buy/sell”.

> **Historia:** licencje były już w projekcie dwa razy (1.4 i 1.7) i za każdym razem zostały usunięte na Twoją prośbę – 1.9.0 była
> „wersją bez licencji”. 1.27 wprowadza nowy system **na Twoje wyraźne polecenie**, w formie z paczki.
>
> Twoja własna instalacja to **OWNER EDITION**: działa bez klucza i dodaje License Manager. Bramka licencji dotyczy wyłącznie paczek
> CLIENT dla Twoich klientów.

## 0. Audyt repozytorium (faza 0)

| Obszar | Stan w repozytorium | Wpływ na licencje |
|---|---|---|
| Punkty wejścia | `python -m masterquo serve` (`backend/masterquo/__main__.py` → `api/app.py` + `runtime.py`); aplikacja Windows `PepeMarketWizardDesktop.exe` (Go + WebView2) uruchamia ten sam serwer; launchery `.bat`; launcher treningu `PepeMarketWizard.exe` | strażnik startuje razem z `Runtime.start()` – jedna ścieżka dla wszystkich sposobów uruchomienia |
| GUI | panel React (Vite) serwowany lokalnie, w oknie WebView2 albo w przeglądarce; brak PySide | KEY FOR MAGIC i License Manager jako widoki panelu (bez nowego frameworka) |
| MT5 | `mt5/bridge.py` + `mt5/worker.py` (jeden wątek terminala, priorytety); `mt5/fake.py` = symulator | bez zmian |
| **Ścieżki NOWEGO zlecenia** | `execution/gateway.py` `ExecutionGateway.execute` (S01–S12, PAPER i MT5; AUTO i ręcznie z panelu) · `execution/manual.py` `ManualPad.execute` (ręczne, przez `gateway._send`) · `sh/executor.py` `SHExecutor.open(role P)` (SCALPING / HEDGING) | **3 punkty integracji `LicenseGuard`** – tylko otwarcie nowej pozycji |
| Zarządzanie otwartymi pozycjami | `execution/manager.py` (częściowe zamknięcia, BE, SL/TP, zamykanie), `gateway.manual_modify`, `SHExecutor.perform` i noga hedge (`role H`) planu | **nieobjęte bramką** – licencja nigdy nie zamyka ani nie blokuje zarządzania pozycją |
| Wątki tła | silnik, skaner, SH, scalp, prognozy (proces roboczy), analityka, lab, Telegram, śledzenie sygnałów | dochodzi wątek `license-guard` (walidacja co 5 min) |
| Konfiguracja i dane | `data/` (config.json, baza SQLite, `secrets.dpapi.json`) – nigdy w paczce; sekrety: DPAPI (Windows) | token aktywacji w `data/license.dpapi` (DPAPI), w OWNER adres serwera w `data/license_owner.json` |
| Budowanie | `tools/build_release.py` (pliki z gita + skan sekretów + manifest), `tools/build_desktop.py` (EXE + Python z NuGet), zależności Windows z hashami (`requirements/requirements-win.txt`) | edycje OWNER / CLIENT, osobna paczka serwera, dodane `cryptography` (+`cffi`, `pycparser`) z hashami |
| Ryzyka | kod klienta to źródła Pythona na komputerze klienta – zdeterminowana osoba może je zmienić | opisane w „Ograniczeniach”; licencja podnosi koszt obejścia, nie jest odporna na modyfikacje |

## 1. Pliki

**Utworzone:**
- `license_server/` – serwer licencji. Moduły `pmw_license/`:
  - `app.py`, `service.py`, `store.py`, `security.py`;
  - `signing.py`, `protocol.py`, `config.py`, `cli.py`.

  Oprócz tego: `README.md`, `requirements.txt`, `.env.example`, `Caddyfile.example`, `pmw-license.service`.
- `backend/masterquo/license/` – strona bota:
  - `protocol.py` – identyczna kopia, sprawdzana testem;
  - `edition.py`, `hwid.py`, `client.py`, `tokenstore.py`, `guard.py`;
  - `owner.py` – nie trafia do paczek CLIENT.
- `edition.json` – OWNER w repozytorium; paczki CLIENT dostają własny plik.
- `tools/stamp_client_edition.py` i `PRZYGOTUJ_PACZKE_KLIENTA.bat` – budowa paczki CLIENT.
- `frontend/src/features/license/`:
  - `KeyForMagic.tsx` – okno KEY FOR MAGIC i chip licencji;
  - `LicenseManager.tsx`;
  - `license.css`.
- Testy:
  - `tests/test_license_server.py`, `test_license_client.py`, `test_license_build.py`;
  - `test_ui_license.py`, `test_strategy_signals.py`.

**Zmienione:**
- `runtime.py` – strażnik, OWNER manager, bramka Telegrama, wpięcie nasłuchu sygnałów.
- `api/app.py` – `/api/v1/license/*`, `/api/v1/owner/*`, stan licencji w `/api/v1/state`.
- `execution/gateway.py`, `execution/manual.py`, `sh/executor.py`, `sh/service.py` – bramka nowych wejść.
- `notify/telegram.py` – bramka powiadomień o nowych sygnałach.
- `markets/signals.py`, `config.py`, `forecast/service.py` – sygnały wszystkich strategii.
- `requirements/requirements-win.txt`, `tools/build_release.py`, `tools/build_desktop.py`.
- Frontend: `store.tsx`, `router.ts`, `App.tsx`, `WizardShell.tsx`.
- Wersja 1.27.0.

## 2. Architektura i przepływ danych

```
OWNER (Twój komputer)                     SERWER LICENCJI (VPS, HTTPS)                     CLIENT (komputer klienta)
License Manager ── login (hasło raz) ──▶  /api/v1/admin/*  (sesja bearer, scrypt, audyt)
  generuj 24h/72h/7d/31d ◀── klucz RAZ ──  licenses: HMAC(klucz), okres, status, HWID-hash
  lista / cofnij / reset HWID              Ed25519 (klucz prywatny tylko tu)
                                           /api/v1/licenses/activate  ◀── klucz + HWID-hash + nonce ── KEY FOR MAGIC
                                           /api/v1/licenses/validate  ◀── id + token + HWID + nonce ── start, co 5 min,
                                                     └── podpisana odpowiedź (nonce, wygaśnięcie) ──▶    przed każdym wejściem
```

**Klucz licencji:**
- format `PMW-XXXXX-XXXXX-XXXXX-XXXXX` – 100 losowych bitów (Crockford base32);
- pokazany tylko raz;
- serwer przechowuje wyłącznie HMAC-SHA256(pepper, klucz) i 4 ostatnie znaki.

**Okres:** 24 h / 72 h / 7 dni / 31 dni, liczony od **pierwszej aktywacji**, według czasu UTC serwera.

**Urządzenie:**
- pierwsza aktywacja wiąże licencję ze skrótem odcisku urządzenia;
- inne urządzenie dostaje `DEVICE_MISMATCH`;
- tylko administrator może zresetować powiązanie. Następna aktywacja wiąże wtedy nowe urządzenie, a termin wygaśnięcia się nie zmienia.

**Odcisk urządzenia (Windows):**
- źródła: MachineGuid, SMBIOS UUID i numer seryjny woluminu systemowego (bez adresów MAC);
- wysyłany jest tylko SHA-256 tych wartości.

**Odpowiedzi serwera:**
- podpisane Ed25519;
- zawierają nonce klienta, więc starej odpowiedzi nie da się odtworzyć;
- obcy serwer nie ma klucza prywatnego, więc jego odpowiedzi nie przejdą weryfikacji.

**LicenseGuard (CLIENT):**
- **Walidacja online:**
  - przy starcie;
  - co 5 min;
  - tuż przed każdym nowym wejściem (S01–S12, ręczne, SCALPING/HEDGING).
- **Brak okresu offline:** błąd lub brak serwera oznacza blokadę nowych wejść.
- **Między walidacjami** wygaśnięcie liczone jest według czasu serwera z ostatniej odpowiedzi.
- Bez ważnej licencji wyłączone są też **powiadomienia Telegram o nowych sygnałach**.
- **Nigdy nie zamyka otwartych pozycji.** SL/TP, częściowe wyjścia, przesunięcie na BE, noga hedge istniejącego planu i ręczne
  zamykanie działają dalej.

**OWNER:**
- brak bramki;
- License Manager woła wyłącznie uwierzytelnione endpointy administratora;
- nie dotyka bazy serwera.

### Sygnały BUY/SELL wszystkich strategii
- **S01–S11** oceniają obie strony tym samym kodem: SHORT na lustrzanym odbiciu ceny (`Strategy.detect`). **S12** ma arbitra obu
  kierunków. Te sygnały istniały już wcześniej, także na innych rynkach (skaner).
- **Nowe źródła sygnałów** – te same sygnały bota, z kierunkiem BUY/SELL, śledzeniem wyniku (WIN/LOSS/TIMEOUT), WebSocketem i
  Telegramem:
  - **SCALPING i HEDGING** (status READY);
  - **Range→Sweep→Retest** (READY_SHADOW z ceną wykonania);
  - **Double Retest v2** (RESEARCH_SETUP_COMPLETE).
- Strategie SHADOW i badawcze są opisane jako **niezweryfikowane**.
- Próg R:R bota dotyczy planów S01–S12. Strategie z własnymi celami i kosztami walidują go same.
- Każde źródło można wyłączyć w `signals.strategy_sources`.
- Sygnał to informacja – **nie składa zlecenia**. Zlecenia idą swoimi niezmienionymi ścieżkami (tryb, STOP, limity, broker, licencja).

## 3. Uruchomienie API
Szczegóły w `license_server/README.md`. W skrócie (Linux, systemd + Caddy):
1. Skopiuj `license_server` na serwer i utwórz virtualenv: `pip install -r requirements.txt`.
2. Wykonaj polecenia `python -m pmw_license …`:
   - `init-keys` – klucz podpisu; **zanotuj wypisany klucz publiczny i kid**;
   - `new-pepper`;
   - `hash-password`.
3. Wpisz wartości do `/etc/pmw-license.env` (chmod 600).
4. `systemctl enable --now pmw-license`; HTTPS przez Caddy (`Caddyfile.example`).

Lokalnie, do prób: `PMW_LIC_ENV=development python -m pmw_license serve` (z ustawionymi zmiennymi).

## 4. OWNER EDITION
Paczki `PepeMarketWizard_OWNER_1_27_0.zip` (folder z launcherami) i `PepeMarketWizard_DESKTOP_OWNER_1_27_0.zip` (aplikacja Windows).
- Bot działa jak dotąd – bez klucza.
- **License Manager:**
  - wejście: panel → Ustawienia → **Licencje** (albo chip „OWNER” w górnym pasku menu z wieżami);
  - podaj adres serwera, login i hasło administratora;
  - dostępne akcje:
    - generowanie klucza 24h / 72h / 7d / 31d (klucz widoczny raz, przycisk „Kopiuj”);
    - lista i wyszukiwanie;
    - „Cofnij”, „Reset HWID”;
    - dziennik audytu.
- Hasło nie jest zapisywane. Sesja żyje w pamięci programu.

## 5. CLIENT EDITION
1. W folderze programu OWNER uruchom `PRZYGOTUJ_PACZKE_KLIENTA.bat https://licencje.twoja-domena.pl`. Narzędzie:
   - pobiera klucz publiczny z serwera i pokazuje jego **kid** – porównaj go z wypisanym przez `init-keys`;
   - zapisuje `release\PepeMarketWizard_CLIENT_…zip` bez modułu właściciela, serwera i danych.
2. Klient rozpakowuje paczkę i uruchamia program. Widzi okno **KEY FOR MAGIC**:
   - wpisuje klucz i klika **ACTIVATE MAGIC**;
   - stany: łączenie / aktywna / nieprawidłowy klucz / wygasła / cofnięta / inne urządzenie / brak serwera / błąd podpisu.
3. Po aktywacji panel działa. W górnym pasku chip „Licencja do …”. Bez ważnej licencji okno wraca, pokazując liczbę otwartych pozycji
   i informację, że nie są zamykane.

## 6. HTTPS i sekrety
- **Na serwerze, poza repozytorium (zmienne środowiskowe):**
  - klucz prywatny Ed25519 (`/etc/pmw-license/signing_key.pem`, chmod 600);
  - pepper kluczy;
  - hash hasła administratora (scrypt);
  - baza `licenses.db` (poza katalogiem WWW, chmod 600, kopie zapasowe).
- **Paczka CLIENT** zawiera tylko adres serwera i **klucz publiczny**. Narzędzie stemplujące odrzuca paczkę z kluczem prywatnym,
  hashem hasła, pepperem, bazą licencji lub modułem właściciela (test).
- Adres serwera w paczce CLIENT musi być `https://` (wyjątek: 127.0.0.1 do testów).

## 7. Budowanie
```
python tools/build_release.py           # PepeMarketWizard_OWNER_1_27_0.zip + PepeMarketWizard_LICENSE_SERVER_1_27_0.zip
python tools/build_desktop.py           # PepeMarketWizard_DESKTOP_OWNER_1_27_0.zip (Go >= 1.23)
python tools/stamp_client_edition.py --license-url https://licencje.twoja-domena.pl --source release/PepeMarketWizard_DESKTOP_OWNER_1_27_0.zip
                                        # -> PepeMarketWizard_DESKTOP_CLIENT_1_27_0_<serwer>.zip (folder: --source release/PepeMarketWizard_OWNER_1_27_0.zip)
```
Paczki CLIENT nie są w `release/` repozytorium, bo wymagają adresu i klucza publicznego **Twojego** serwera.

## 8. Wyniki testów (uruchomione w tym środowisku)

| Test | Zakres | Wynik |
|---|---|---|
| `test_license_server` | 4 okresy, jednorazowy klucz + hash, aktywacja / drugie urządzenie / ponowna aktywacja, walidacja z nonce, wygaśnięcie na zegarze testowym, cofnięcie, reset HWID (wygaśnięcie bez zmian), nieautoryzowany admin, sfałszowane / obce asercje, złe zapytania, równoległa aktywacja, limit zapytań, konfiguracja produkcyjna | 10 / 10 OK |
| `test_license_client` | edycja fail-closed, aktywacja, podpis (sfałszowany, obcy serwer), brak serwera przy starcie i w trakcie, walidacja okresowa, wygaśnięcie między walidacjami, cofnięcie, OWNER License Manager, **zlecenie na symulatorze MT5 zablokowane po cofnięciu, otwarta pozycja nie zamknięta i dalej zarządzana**, SCALPING/HEDGING (wejście zablokowane, zarządzanie i hedge działają), bramka Telegrama, identyczny protokół | 12 / 12 OK |
| `test_license_build` | paczka OWNER bez serwera, paczka serwera bez sekretów, stemplowanie folderu i aplikacji Windows, manifesty, odrzucenie klucza prywatnego / bazy, klucz publiczny z serwera | 5 / 5 OK |
| `test_ui_license` (Chromium) | KEY FOR MAGIC: zły klucz, aktywacja, cofnięcie → okno wraca; OWNER: logowanie, klucz raz, lista, cofnięcie | 2 / 2 OK |
| `test_strategy_signals` | S01–S12 oba kierunki, SCALPING/HEDGING/R→S→R/Double Retest BUY i SELL, przełączniki, deduplikacja | 6 / 6 OK |

Testy regresji zmienionych modułów i pełne liczby: CHANGELOG 1.27.0.

## 9. Ograniczenia
- **Program działa na komputerze klienta.** Zdeterminowana osoba może zmienić pliki Pythona (np. `edition.json` albo kod strażnika).
  Licencja podnosi koszt obejścia, nie jest niełamalna.
- **HWID to środek odstraszający.** Reinstalacja Windows, wymiana płyty głównej lub niektóre maszyny wirtualne zmieniają odcisk –
  wtedy administrator robi reset HWID.
- **Tylko online:**
  - brak internetu albo awaria serwera blokuje nowe wejścia u wszystkich klientów;
  - otwarte pozycje są dalej zarządzane.
- **Limity zapytań** są w pamięci jednego procesu API – uruchamiaj jeden proces albo dodaj limit w proxy.
- **PAPER u klienta też wymaga licencji** (nowe wejście papierowe = nowa akcja handlowa).
- **SCALPING/HEDGING:** noga hedge istniejącego planu nie jest blokowana, bo chroni otwartą pozycję.

## 10. Czego NIE zweryfikowano
- Uruchomienia na Windows:
  - odcisk HWID (MachineGuid / SMBIOS / wolumin);
  - DPAPI tokenu;
  - instalacja `cryptography` z hashami w aplikacji Windows.
- Wdrożenia serwera na VPS:
  - HTTPS przez Caddy / Let's Encrypt;
  - systemd;
  - kopie zapasowe.
- Testów bezpieczeństwa / penetracyjnych serwera.
- Działania z prawdziwym MT5 i rachunkiem (testy użyły symulatora MT5).

**System nie jest gotowy do produkcji, dopóki nie przejdzie wdrożenia i testów bezpieczeństwa na Twoim serwerze.**
