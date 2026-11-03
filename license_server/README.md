# PepeMarketWizard License API v1

The central license service of PepeMarketWizard:
- activation and validation for CLIENT EDITION installations;
- key generation and administration for OWNER EDITION.

Not part of the client package – it runs on your server (VPS) behind HTTPS.

## What it does
- **Keys** `PMW-XXXXX-XXXXX-XXXXX-XXXXX` (100 random bits).
  - Durations: **24h, 72h, 7d, 31d**.
  - The plaintext key is shown **only once**, in the response that creates it.
  - The database stores only HMAC-SHA256(pepper, key) and the last 4 characters (hint).
- **Expiry** counts from the first activation (UTC, server time).
- **Device:**
  - The first activation binds the license to the device fingerprint hash (HWID hash).
  - Another device gets `DEVICE_MISMATCH`.
  - Only the administrator can reset the binding (`reset-device`). The next activation then binds the new device; the expiry does not change.
- **Validation** at client startup, every 5 minutes and before every new entry.
  - Each response carries an **Ed25519 signature** and the client's nonce, so an old response cannot be replayed.
  - The private key never leaves the server.
- **Administrator (1.1, no login screen):**
  - the OWNER app has its own Ed25519 **device key** (private part only on the OWNER computer, DPAPI on Windows);
  - the server trusts a device key only after you add it **from the server's shell** (one-time pairing, outside the public API);
  - every admin request is signed: method, path + query, SHA-256 of the exact body, UTC time (±120 s) and a random nonce;
  - a reused nonce is rejected (stored in the database - also after a restart); the device key never signs licenses and the
    license-signing key never authenticates an administrator;
  - optional password login (scrypt, bearer session) exists only for OWNER apps older than 1.29 and is **disabled** when
    `PMW_LIC_ADMIN_PASSWORD_HASH` is empty.
- **Rate limits:**
  - activation / validation – per IP address;
  - administrator login – per IP address.
- **Audit log** (`audit_log`) records:
  - key creation, activations, rejections, revocations, device resets;
  - administrator logins (including failed ones).

  It never contains full keys, tokens or whole HWID hashes.

## Installation (Debian/Ubuntu)
```bash
sudo useradd --system --home /opt/pmw-license pmwlicense
sudo mkdir -p /opt/pmw-license /var/lib/pmw-license /etc/pmw-license
sudo cp -r pmw_license requirements.txt /opt/pmw-license/
cd /opt/pmw-license && sudo python3 -m venv venv && sudo venv/bin/pip install -r requirements.txt

# secrets (once)
sudo -u pmwlicense env PMW_LIC_SIGNING_KEY=/etc/pmw-license/signing_key.pem venv/bin/python -m pmw_license init-keys
venv/bin/python -m pmw_license new-pepper        # -> PMW_LIC_KEY_PEPPER
# administrator: NO password needed - after the service runs, pair the OWNER app (see "Pairing the OWNER app" below)
sudo cp .env.example /etc/pmw-license.env && sudo chmod 600 /etc/pmw-license.env   # fill in the values

sudo cp pmw-license.service /etc/systemd/system/ && sudo systemctl enable --now pmw-license
# HTTPS: Caddy (Caddyfile.example) or Nginx -> 127.0.0.1:8740
```

`init-keys` prints the **PUBLIC KEY**. You need it to prepare the CLIENT package
(`PRZYGOTUJ_PACZKE_KLIENTA.bat` in the OWNER package, or `tools/stamp_client_edition.py`).

**Back up the private key and the database offline.**
- Losing the private key requires new client packages.
- Losing the database invalidates all licenses.

## Endpoints
Contract: `docs/LICENCJE_SYSTEM_1_27_PL.md` in the bot repository.

| | |
|---|---|
| `GET /health` | status and server time |
| `GET /api/v1/public-key` | public key (Ed25519) and its `kid` |
| `POST /api/v1/licenses/activate` | `license_key, hwid_hash, nonce, client_version` → status, expiry, device token, signed assertion |
| `POST /api/v1/licenses/validate` | `license_id, hwid_hash, token, nonce` → fresh signed assertion |
| `GET /api/v1/admin/whoami` | signed check: which OWNER device key is calling (pairing test) |
| `GET /api/v1/admin/keys`, `POST /api/v1/admin/keys/{kid}/revoke` | trusted OWNER device keys; revoke another key (never the calling one) |
| `POST /api/v1/admin/login` / `logout` | legacy password session - only when `PMW_LIC_ADMIN_PASSWORD_HASH` is set |
| `POST /api/v1/admin/licenses` | `{"duration": "24h|72h|7d|31d", "note"}` → key **once** |
| `GET /api/v1/admin/licenses` | list (`status`, `duration`, `q`, `limit`, `offset`) – no keys or hashes |
| `POST /api/v1/admin/licenses/{id}/revoke` | revoke |
| `POST /api/v1/admin/licenses/{id}/reset-device` | reset the device binding |
| `GET /api/v1/admin/stats`, `GET /api/v1/admin/audit` | counters, audit log |

Errors use the shape `{"error": {"code", "message"}}`. Codes:
- `INVALID_LICENSE`
- `LICENSE_EXPIRED`
- `LICENSE_REVOKED`
- `DEVICE_MISMATCH`
- `RATE_LIMITED`
- `INVALID_REQUEST`
- `UNAUTHORIZED`
- `NOT_FOUND`

## Limitations
- **Rate limits** are kept in the process memory – run **one** API process. With several workers, use a shared limit (e.g. in the proxy).
- **SQLite** suits a small deployment.
  - Requires: a file outside the web directory, chmod 600, backups.
  - Moving to PostgreSQL means a new `store.py` with the same methods.

## Pairing the OWNER app (once per OWNER computer)
1. OWNER app → **Ustawienia → Licencje**: enter the server address (`https://…`) and click *Zapisz i sprawdź*.
2. The page shows a command with the computer's PUBLIC key. Run it on the server, in the service folder, as the service user:
   ```bash
   sudo -u pmwlicense env $(grep -v '^#' /etc/pmw-license.env | xargs) venv/bin/python -m pmw_license admin-keys add --public-key <KEY> --label "OWNER PC"
   ```
3. Click *Sprawdź parowanie*. From now on the page works without any login, also after restarts.

Key management on the server: `admin-keys list`, `admin-keys revoke <kid> --reason "…"`.
- **New / replaced OWNER computer:** pair the new computer the same way, then revoke the old kid.
- **Rotation from the app:** *Rozpocznij rotację klucza* → pair the shown new key → *Zakończ rotację* (the old key is revoked).
- **Lost computer / leaked key:** `admin-keys revoke <kid>` immediately; pair a new key.
- **Lost access to every OWNER computer:** only the server shell can add a key - that is the recovery path.

## Backup and restore
- Database (online, consistent): `python -m pmw_license backup-db --out /var/backups/pmw-license/licenses-$(date +%F).db`
- Copy **offline** also: the signing key (`PMW_LIC_SIGNING_KEY`) and `/etc/pmw-license.env` (pepper!). Without the same pepper
  existing keys cannot be verified; without the same signing key every CLIENT package must be rebuilt.
- Restore: stop the service, put the database file at `PMW_LIC_DATABASE`, the key at `PMW_LIC_SIGNING_KEY`, the same env file,
  start the service (`systemctl start pmw-license`), check `GET /health` and a signed `whoami` from the OWNER app.
- Database schema: v2 (1.1) adds `admin_keys` and `admin_nonces` in place on first start; a 1.0 server can still read the
  database (the new tables are only additional).

## Update / restart
`systemctl restart pmw-license` (the service starts again after a reboot: `systemctl enable pmw-license`). Before an update
make a database backup. Never expose port 8740 directly - only the HTTPS reverse proxy (Caddyfile.example) with a valid
certificate; do not enable any debug mode.
