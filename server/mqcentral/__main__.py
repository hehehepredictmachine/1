"""Command line of the central server.

  python -m mqcentral gen-keys                 Ed25519 lease-signing key + MQC_DATA_KEY (prints values to put in .env)
  python -m mqcentral migrate                  apply database migrations
  python -m mqcentral bootstrap-admin EMAIL    first administrator (password typed via getpass, TOTP + recovery codes printed once)
  python -m mqcentral set-role EMAIL ROLE      USER / ADMIN (audited; sessions of that user are revoked)
  python -m mqcentral serve [--host --port]    API + admin app (put HTTPS reverse proxy in front: see deploy/Caddyfile)
  python -m mqcentral sweep                    persist EXPIRED statuses (auxiliary - validity is evaluated on every request)
  python -m mqcentral clock-check              compare server clock with MQC_TIME_REFERENCE_URL
  python -m mqcentral clock-ack                resolve a detected clock anomaly after the time was fixed
  python -m mqcentral backup DIR               SQLite copy / PostgreSQL pg_dump (custom format)
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .clock import SystemClock
from .db import Database


def _env_file() -> None:
    """Load KEY=VALUE pairs from .env next to the server (without overriding real environment variables)."""
    p = Path(os.environ.get("MQC_ENV_FILE", Path(__file__).resolve().parents[1] / ".env"))
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def build(settings=None, clock=None):
    from .service import Central
    s = settings or config.load()
    errs = config.validate(s)
    if errs:
        raise SystemExit("Konfiguracja serwera niepoprawna:\n - " + "\n - ".join(errs))
    db = Database(s.database_url)
    db.migrate()
    return Central(s, db, clock or SystemClock(db))


def main(argv=None) -> int:
    _env_file()
    ap = argparse.ArgumentParser(prog="mqcentral")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen-keys")
    g.add_argument("--out", default=os.environ.get("MQC_SIGNING_KEY_FILE", "secrets/lease_signing_ed25519.pem"))
    sub.add_parser("migrate")
    b = sub.add_parser("bootstrap-admin")
    b.add_argument("email")
    r = sub.add_parser("set-role")
    r.add_argument("email")
    r.add_argument("role", choices=["USER", "ADMIN"])
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default=os.environ.get("MQC_HOST", "127.0.0.1"))
    sv.add_argument("--port", type=int, default=int(os.environ.get("MQC_PORT", "8800")))
    sub.add_parser("sweep")
    sub.add_parser("clock-check")
    sub.add_parser("clock-ack")
    bk = sub.add_parser("backup")
    bk.add_argument("dir")
    a = ap.parse_args(argv)

    if a.cmd == "gen-keys":
        from cryptography.fernet import Fernet
        from .security import gen_signing_key
        out = Path(a.out)
        if out.exists():
            print(f"Klucz już istnieje: {out} (nie nadpisuję – rotacja: zapisz nowy plik i zmień MQC_SIGNING_KEY_FILE)")
        else:
            gen_signing_key(out)
            print(f"Zapisano klucz prywatny podpisu lease: {out} (tylko serwer, chmod 600)")
        print("Dopisz do .env (jeżeli jeszcze nie ma):")
        print(f"MQC_SIGNING_KEY_FILE={out}")
        print(f"MQC_DATA_KEY={Fernet.generate_key().decode()}")
        return 0
    if a.cmd == "migrate":
        s = config.load()
        db = Database(s.database_url)
        print("Zastosowano:", db.migrate() or "nic nowego", "| wersje:", db.versions())
        return 0
    c = build()
    if a.cmd == "bootstrap-admin":
        pw = getpass.getpass("Hasło administratora (min. 12 znaków): ")
        if pw != getpass.getpass("Powtórz hasło: "):
            print("Hasła różnią się.")
            return 2
        out = c.bootstrap_admin(a.email, pw)
        print("Administrator utworzony. Dodaj konto w aplikacji TOTP (Google Authenticator, Aegis, 1Password):")
        print("  URI:", out["totp_uri"])
        print("  Sekret:", out["totp_secret"])
        print("Kody odzyskiwania (każdy jednorazowy, zapisz offline – nie zostaną pokazane ponownie):")
        for code in out["recovery_codes"]:
            print("  ", code)
        return 0
    if a.cmd == "set-role":
        c.set_role(a.email, a.role)
        print("Rola zmieniona, sesje użytkownika unieważnione.")
        return 0
    if a.cmd == "sweep":
        print("Oznaczono jako EXPIRED:", c.sweep_expired())
        return 0
    if a.cmd == "clock-check":
        if not c.s.time_reference_url:
            print("MQC_TIME_REFERENCE_URL nie ustawione")
            return 1
        print(json.dumps({"skew_s": c.clock.check_reference(c.s.time_reference_url), "anomaly": c.clock.anomaly}))
        return 0
    if a.cmd == "clock-ack":
        c.clock.acknowledge()
        print("Anomalia zegara zamknięta.")
        return 0
    if a.cmd == "backup":
        d = Path(a.dir)
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        if c.db.pg:
            f = d / f"mqcentral_{stamp}.dump"
            subprocess.run(["pg_dump", "--format=custom", "--file", str(f), c.s.database_url], check=True)
        else:
            f = d / f"mqcentral_{stamp}.sqlite"
            c.db.conn().execute(f"VACUUM INTO '{f}'")
        print("Kopia:", f)
        return 0
    if a.cmd == "serve":
        import threading
        import uvicorn
        from .api import create_app

        def sweeper():
            while True:
                try:
                    c.sweep_expired()
                    if c.s.time_reference_url:
                        c.clock.check_reference(c.s.time_reference_url)
                except Exception:
                    pass
                time.sleep(60)
        threading.Thread(target=sweeper, daemon=True).start()
        if c.clock.anomaly:
            print("UWAGA: wykryto anomalię zegara serwera:", c.clock.anomaly, "– nowe uprawnienia nie będą wydawane do `clock-ack`.")
        uvicorn.run(create_app(c), host=a.host, port=a.port, proxy_headers=c.s.trusted_proxy, forwarded_allow_ips="127.0.0.1" if c.s.trusted_proxy else None,
                    log_level="info")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
