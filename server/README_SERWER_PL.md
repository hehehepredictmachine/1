# MasterQUO – serwer kont i licencji + MasterQUO License Manager

Ta część **nie trafia do klientów**. Działa na Twoim serwerze (VPS) dostępnym przez HTTPS. Klienci (bot MasterQUO na Windows)
łączą się z nią po adres `https://…`, który wpisują na ekranie logowania monitora.

Ten serwer **nie jest wdrożony publicznie** – kod, konfiguracja i testy są gotowe, ale samo wdrożenie (domena, certyfikat,
serwer, SMTP) wykonujesz Ty. Do tego czasu klienci z innych komputerów nie mogą się logować.

## Co jest w środku
* `mqcentral/` – API (FastAPI): konta, sesje, MFA administratora, licencje 48 h, urządzenia (Ed25519), lease (EdDSA),
  autoryzacja zleceń, telemetria MT5, rekonstrukcja transakcji i win ratio, audyt, CLI.
* `admin-web/` – aplikacja „MasterQUO License Manager” (`/admin/`) i strony konta (`/account/verify`, `/account/reset`,
  `/account/register`, `/account/forgot`). `admin-web/dist` jest zbudowane; źródła w `admin-web/src`.
* `requirements-server.txt` – przypięte zależności z hashami (Linux x86_64 i Windows x64, Python 3.12/3.13).
* `deploy/` – Caddy (HTTPS), systemd, kopia zapasowa.

## Wdrożenie (Ubuntu 24.04, PostgreSQL 16, Caddy)
```bash
sudo apt install postgresql caddy python3.12-venv
sudo -u postgres createuser -P mqcentral          # podaj hasło bazy
sudo -u postgres createdb -O mqcentral mqcentral
sudo useradd -r -m -d /opt/mqcentral mqcentral
sudo -u mqcentral python3 -m venv /opt/mqcentral/venv
sudo -u mqcentral /opt/mqcentral/venv/bin/pip install --require-hashes --only-binary=:all: -r /opt/mqcentral/server/requirements-server.txt
cd /opt/mqcentral/server && sudo -u mqcentral cp .env.example .env && sudo chmod 600 .env
sudo -u mqcentral /opt/mqcentral/venv/bin/python -m mqcentral gen-keys --out /opt/mqcentral/secrets/lease_signing_ed25519.pem
#   -> wpisz wypisane MQC_SIGNING_KEY_FILE i MQC_DATA_KEY do .env, uzupełnij bazę, domenę, SMTP
sudo -u mqcentral /opt/mqcentral/venv/bin/python -m mqcentral migrate
sudo -u mqcentral /opt/mqcentral/venv/bin/python -m mqcentral bootstrap-admin twoj@email.pl
#   -> hasło podajesz w ukrytym polu; zeskanuj URI TOTP w aplikacji uwierzytelniającej, zapisz kody odzyskiwania offline
sudo cp deploy/mqcentral.service /etc/systemd/system/ && sudo systemctl enable --now mqcentral
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # zmień domenę
sudo systemctl reload caddy
```
Sprawdź: `https://twoja-domena/api/v1/health` (czas serwera, brak anomalii zegara) i `https://twoja-domena/admin/`.

### Wartości do uzupełnienia w `.env`
| Zmienna | Co wpisać |
|---|---|
| `MQC_DATABASE_URL` | `postgresql://mqcentral:HASŁO@127.0.0.1:5432/mqcentral` |
| `MQC_PUBLIC_URL`, `MQC_ALLOWED_ORIGINS` | `https://twoja-domena` (ten sam adres wpisują klienci) |
| `MQC_SIGNING_KEY_FILE`, `MQC_DATA_KEY` | z `gen-keys` |
| `MQC_SMTP_*` | serwer pocztowy (STARTTLS, certyfikat weryfikowany) |
| `MQC_TIME_REFERENCE_URL` | opcjonalnie – zaufany serwer HTTPS do kontroli zegara |

Serwer **odmawia startu**, gdy w produkcji brakuje HTTPS w adresie, SMTP, klucza podpisu, ma SQLite albo zmienioną długość licencji.

### Zegar
Ustaw synchronizację czasu (`timedatectl set-ntp true`). Serwer zapamiętuje najwyższy widziany czas i porównuje zegar systemowy
z monotonicznym. Cofnięcie zegara lub skok > 120 s = **anomalia**: nowe aktywacje, lease i autoryzacje zleceń są wstrzymane
(bez przedłużania czegokolwiek), dopóki nie wykonasz `python -m mqcentral clock-ack` po naprawie czasu.

### Kopie zapasowe i odtworzenie
`deploy/backup.sh` (cron, codziennie): `pg_dump` w formacie custom, 14 dni. Odtworzenie: `pg_restore --clean -d mqcentral PLIK`.
Daty licencji są zapisane w bazie (`activated_at`, `expires_at` w sekundach UTC) – restart, odtworzenie ani migracja ich nie zmieniają.
Kopia zawiera skróty haseł, kluczy licencji i tokenów (nie same sekrety) – przechowuj ją jak dane osobowe.

### Rotacja kluczy
* Klucz podpisu lease: wygeneruj nowy plik, zmień `MQC_SIGNING_KEY_FILE`, restart. Klienci mają przypięty klucz z aktywacji –
  po rotacji muszą aktywować ponownie (ta sama licencja, ten sam termin) albo admin zwalnia stanowisko.
* `MQC_DATA_KEY` szyfruje sekrety TOTP – przy zmianie wykonaj ponownie `bootstrap-admin` na nowym koncie / ustaw nowe MFA.

### Limity
Limity prób (logowanie, rejestracja, reset, aktywacja, telemetria) są w procesie API (`mqcentral/ratelimit.py`). Przy kilku
procesach API dodaj limit w Caddy/nginx (przykład w Caddyfile).

## Uruchomienie lokalne (tylko development)
`./start_dev_server.sh` – SQLite, e-maile do **DEV OUTBOX** (widoczne w panelu → System), http://127.0.0.1:8800.
Klient bota akceptuje `http://127.0.0.1` wyłącznie z flagą `central.allow_insecure_localhost: true` w lokalnym `data\config.json`.

## API (skrót)
Publiczne: `POST /api/v1/auth/register|verify-email|login|mfa|logout|password/forgot|password/reset`, `GET /api/v1/auth/session`,
`GET /api/v1/health`, `GET /api/v1/keys`.
Użytkownik (sesja): `GET /api/v1/me`, `GET /api/v1/me/stats`, `POST /api/v1/auth/password/change`, `POST /api/v1/licenses/activate`.
Urządzenie (podpis Ed25519 nonce): `POST /api/v1/device/challenge|heartbeat`, `POST /api/v1/ops/authorize`,
`POST /api/v1/connector/link|unlink`, `POST /api/v1/telemetry/snapshot|deals`, `GET /api/v1/device/status`.
Administrator (sesja + MFA + CSRF): `GET/POST /api/v1/admin/users`, `GET /api/v1/admin/users/{id}`, `POST …/block|unblock`,
`GET/POST /api/v1/admin/licenses`, `POST /api/v1/admin/licenses/{id}/revoke`, `POST /api/v1/admin/activations/{id}/release`,
`POST /api/v1/admin/devices/{id}/revoke`, `GET /api/v1/admin/accounts/{id}/stats`, `GET /api/v1/admin/audit`, `GET /api/v1/admin/system`.
W `MQC_ENV=dev` dokumentacja OpenAPI: `/api/docs`.
