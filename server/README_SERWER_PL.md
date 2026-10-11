# MasterQUO License Server (`mqlicense`) – serwer licencji 72 h i panel administratora

Ta część **nie trafia do klientów**. Działa na Twoim serwerze (VPS lub komputer administratora) i jest dostępna przez
HTTPS. Bot MasterQUO łączy się z nim przy każdym starcie (`masterquo_start.bat`), żeby sprawdzić wklejony klucz.

**Stan:** kod, migracje, panel i testy są gotowe. Serwer **nie został wdrożony publicznie** w ramach tej pracy. Domenę,
certyfikat i usługę konfigurujesz Ty, według kroków poniżej. Lokalny serwer deweloperski (`start_dev_server.*`) służy
wyłącznie do testów. Produkcyjny klient powinien wskazywać Twój serwer HTTPS.

## Zasady licencji

- **Klucz:** `MQL72-…`, 256 bitów z generatora kryptograficznego. Klucz jest pokazywany **raz**, przy wygenerowaniu.
  W bazie jest tylko HMAC-SHA256 (z sekretem `MQL_KEY_PEPPER`) i 4 ostatnie znaki jako podpowiedź.
- **Ważność:** dokładnie **259200 s (72 h) od wygenerowania**, według zegara serwera (UTC). Wartość nie zależy od
  pierwszego użycia i nie da się jej przedłużyć. „Wydaj ponownie” tworzy **nowy** klucz i nowy rekord, cofa stary i nie
  przywraca go.
- **Sesja jednego uruchomienia:**
  - klient podaje `boot_id` i jednorazowy `nonce`;
  - serwer zwraca token sesji (klient trzyma go tylko w pamięci) i dzierżawę: JWT EdDSA podpisany kluczem Ed25519,
    ważny ≤ 30 s i nigdy dłużej niż licencja;
  - klient odnawia dzierżawę co ≤ 10 s.
- **Cofnięcie / zakończenie sesji:** dociera do bota przy najbliższym odnowieniu (≤ 30 s). Bot blokuje wtedy analizę,
  sygnały, agenta AI, ML i **nowe** zlecenia. Otwarte pozycje i ich SL/TP zostają.
- **Limit jednoczesnych sesji:** domyślnie 1, można ustawić 1–10 per licencja. Rejestracja sesji jest atomowa. Po awarii
  klienta slot zwalnia się po wygaśnięciu dzierżawy (≤ 30 s). Czyste zamknięcie (STOP) zwalnia go od razu.
- **Brak** trybu offline, uniwersalnego klucza i okresu karencji.
- **Zegar:** serwer pamięta najwyższy widziany czas i porównuje zegar systemowy z monotonicznym. Cofnięcie zegara lub
  skok > 120 s to **anomalia**: wydawanie licencji i dzierżaw jest wstrzymane, dopóki nie wykonasz
  `python -m mqlicense clock-ack` po naprawie czasu.

## Zawartość

- `mqlicense/`:
  - `config.py`, `db.py` (SQLite WAL, migracje w `migrations/`);
  - `security.py` (Argon2id, TOTP, Fernet, Ed25519/JWT, klucze);
  - `clock.py`, `ratelimit.py`;
  - `service.py` (logika), `api.py` (HTTP), `__main__.py` (CLI);
  - `static/admin/` – panel administratora po polsku, bez zewnętrznych skryptów, CSP `self`.
- `requirements-server.txt` – przypięte zależności z hashami (Linux x86_64 i Windows x64, Python 3.12/3.13).
- `deploy/` – Caddy (HTTPS), systemd, kopia zapasowa.
- `.env.example` – wzór konfiguracji (bez sekretów).

## Wdrożenie (Ubuntu 24.04 + Caddy)

```bash
sudo apt install caddy python3.12-venv
sudo useradd -r -m -d /opt/mqlicense mqlicense
sudo -u mqlicense mkdir -p /opt/mqlicense/{server,data,backups,secrets}
# skopiuj katalog server/ z paczki MasterQUO_SERWER_LICENCJI do /opt/mqlicense/server
sudo -u mqlicense python3.12 -m venv /opt/mqlicense/venv
sudo -u mqlicense /opt/mqlicense/venv/bin/pip install --require-hashes --only-binary=:all: -r /opt/mqlicense/server/requirements-server.txt
cd /opt/mqlicense/server
sudo -u mqlicense /opt/mqlicense/venv/bin/python -m mqlicense gen-keys --out /opt/mqlicense/secrets
#   -> wypisze KLUCZ PUBLICZNY (dla klientów) i zapisze secrets/secrets.env (sekrety serwera)
sudo -u mqlicense cp .env.example .env && sudo chmod 600 .env
#   -> wpisz do .env: MQL_PUBLIC_URL / MQL_ALLOWED_ORIGINS (Twoja domena) oraz MQL_KEY_PEPPER i MQL_DATA_KEY z secrets.env
sudo -u mqlicense /opt/mqlicense/venv/bin/python -m mqlicense check          # pusta lista "problems" = konfiguracja kompletna
sudo -u mqlicense /opt/mqlicense/venv/bin/python -m mqlicense migrate
sudo -u mqlicense /opt/mqlicense/venv/bin/python -m mqlicense bootstrap-admin --email twoj@email.pl
#   -> hasło w ukrytym polu; zeskanuj URI TOTP w aplikacji (Aegis, Google Authenticator...), kody odzyskiwania zapisz OFFLINE
sudo cp deploy/mqlicense.service /etc/systemd/system/ && sudo systemctl enable --now mqlicense
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile        # zmień domenę
sudo systemctl reload caddy
sudo timedatectl set-ntp true                        # synchronizacja czasu (wymagana)
```

Sprawdzenie:

- `https://twoja-domena/api/v1/health` – `license_seconds: 259200`, `clock_anomaly: null`;
- panel: `https://twoja-domena/admin/`.

W trybie `MQL_ENV=prod` serwer **odmawia startu**, gdy brakuje adresu https, klucza podpisu, pieprzu lub klucza danych,
gdy długość licencji ≠ 259200 s albo gdy dzierżawa > 30 s.

### Konfiguracja klienta (każdy komputer z botem)

W `data\config.json` klienta (sekcja `license`):

```json
"license": {
  "server_url": "https://licencje.twoja-domena.pl",
  "public_key_pem": "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA...\n-----END PUBLIC KEY-----\n",
  "telemetry_opt_in": false
}
```

- Klucz publiczny jest wypisywany przez `gen-keys` i zapisany w `secrets/signing_ed25519.pub.pem`.
- Klucza **prywatnego**, `MQL_KEY_PEPPER` ani `MQL_DATA_KEY` nigdy nie kopiuj na komputer klienta.
- `http://` jest akceptowane wyłącznie dla `127.0.0.1`/`localhost` (testy lokalne).

## Panel administratora

- **Logowanie:** e-mail + hasło (Argon2id) + kod TOTP albo jednorazowy kod odzyskiwania. Po 5 błędach konto jest
  zablokowane na 15 min, obowiązuje też limit prób na IP.
- **Sesja:** ciasteczko HttpOnly + SameSite=Strict (w produkcji `__Host-` + Secure). Wygasa po 60 min. Ochrona CSRF
  (`X-CSRF`) i kontrola Origin.
- **Role:**
  - **ADMIN**: wszystko;
  - **VIEWER**: tylko podgląd.
  Uprawnienia są sprawdzane na **serwerze**, dla każdego endpointu.
- **Zakładki:**
  - Podsumowanie: liczby, zdrowie usługi, migracje, ostatnie zdarzenia;
  - Licencje: generowanie 72 h (klient, notatka, limit sesji), wyszukiwanie, filtr statusu, paginacja, czasy
    utworzenia/wygaśnięcia/pierwszego/ostatniego użycia, pozostały czas, cofnięcie, wydanie ponownie, przypisanie,
    zmiana limitu sesji;
  - Sesje: zakończenie;
  - Klienci;
  - Statystyki (opt-in);
  - Audyt;
  - Konto (zmiana hasła).
- **Statystyki (balance, equity, winrate, PF, E[R], ROI):**
  - pochodzą wyłącznie z telemetrii wysłanej przez bota z ważną sesją licencji;
  - bot musi mieć `license.telemetry_opt_in: true`, a klient w panelu – „zgodę na statystyki”;
  - brak połączenia oznacza „brak danych”, nigdy zero;
  - serwer nie przyjmuje loginów, haseł brokerskich ani zleceń.
- **Administratorzy:** tworzy się ich tylko przez CLI (`bootstrap-admin`, `add-admin`). Nie ma publicznej rejestracji
  ani domyślnego hasła. Reset MFA: `reset-mfa`. Wyłączenie konta: `disable-admin`.

## Kopie zapasowe, migracje, restart

- **Kopia:** `deploy/backup.sh` (cron, codziennie) wykonuje spójną kopię SQLite (`python -m mqlicense backup`) i trzyma
  ją 14 dni.
- **Odtworzenie:** zatrzymaj usługę, podmień plik bazy, uruchom usługę.
- **Daty licencji** (`created_at`, `expires_at`, sekundy UTC) są zapisane w bazie. Restart, odtworzenie ani migracja
  ich nie zmieniają. Test: `test_license.test_17`.
- **Migracje:** `python -m mqlicense migrate`. Usługa systemd uruchamia je przed startem (wersje w `schema_migrations`).
- **Kopia bazy** zawiera skróty kluczy i haseł oraz zaszyfrowane sekrety TOTP. Przechowuj ją jak dane poufne.
- **Rotacja klucza podpisu:**
  1. wygeneruj nowe klucze (`gen-keys --out nowy_katalog`);
  2. zmień `MQL_SIGNING_KEY_FILE`;
  3. zrestartuj serwer;
  4. rozdaj klientom nowy klucz publiczny.
  Stare dzierżawy wygasną w ≤ 30 s.

## Uruchomienie lokalne (tylko rozwój i testy)

- Linux: `PY=/ścieżka/python ./start_dev_server.sh`
- Windows: `start_dev_server.bat` (wymaga `.venv-server`, patrz `INSTRUKCJA_WINDOWS_PL.md`)

Skrypt tworzy klucze deweloperskie w `server/data/dev/` (ignorowane przez git i niepakowane), tryb `MQL_ENV=dev` i
adres `http://127.0.0.1:8790`. Pierwszy administrator:
`python -m mqlicense --env-file data/dev/dev.env bootstrap-admin --email ty@example.com`.

## API (skrót)

- **Publiczne:** `GET /api/v1/health`, `GET /api/v1/keys`.
- **Klient** (klucz/token tylko w treści POST; zapytania z parametrami w URL są odrzucane):
  `POST /api/v1/client/session | renew | end`.
- **Administrator** (ciasteczko + `X-CSRF` dla zmian):
  - `POST /api/v1/admin/login | logout | password`, `GET /api/v1/admin/me | summary`;
  - `GET/POST /api/v1/admin/licenses`, `GET /api/v1/admin/licenses/{id}`;
  - `POST /api/v1/admin/licenses/{id}/revoke | reissue | assign | max-sessions`;
  - `GET /api/v1/admin/sessions`, `POST /api/v1/admin/sessions/{id}/terminate`;
  - `GET/POST /api/v1/admin/customers`, `POST /api/v1/admin/customers/{id}`;
  - `GET /api/v1/admin/audit | telemetry | admins`.

## Ograniczenia (świadomie, bez deklaracji „nie do obejścia”)

- Ochrona działa po stronie klienta na komputerze użytkownika. Osoba z pełną kontrolą nad tym komputerem może
  zmodyfikować kod Pythona albo podmienić klucz publiczny w `data\config.json`. Serwer kontroluje wydawanie licencji,
  czas ważności (72 h), cofanie i liczbę jednoczesnych sesji, ale nie gwarantuje integralności zmodyfikowanego klienta.
- Jeden proces API (SQLite). Przy kilku procesach dodaj limity w reverse proxy i przenieś bazę na serwer SQL (wymaga
  zmiany warstwy `db.py`).
