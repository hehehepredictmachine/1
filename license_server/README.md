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
- **Administrator:**
  - login → bearer session (8 h), stored as a hash on the server;
  - password stored as scrypt;
  - every privileged operation is checked server-side.
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
venv/bin/python -m pmw_license hash-password     # -> PMW_LIC_ADMIN_PASSWORD_HASH (the password is never stored)
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
| `POST /api/v1/admin/login` / `logout` | administrator session |
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
