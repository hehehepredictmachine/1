"""CLI of the license server. Administrators are created ONLY here (no default password, no web sign-up).

  python -m mqlicense gen-keys --out secrets/        Ed25519 signing key + pepper + data key (prints public key for the client)
  python -m mqlicense check                          configuration problems
  python -m mqlicense migrate
  python -m mqlicense bootstrap-admin --email a@b    first ADMIN (refused when any administrator exists)
  python -m mqlicense add-admin --email x --role VIEWER
  python -m mqlicense reset-mfa --email x            new TOTP + recovery codes, logs the admin out everywhere
  python -m mqlicense disable-admin --email x | enable-admin --email x
  python -m mqlicense clock-ack                      acknowledge a server clock anomaly after checking the time
  python -m mqlicense backup --out backups/x.sqlite3
  python -m mqlicense serve                          (default 127.0.0.1:8790; put HTTPS reverse proxy in front)
Passwords are read with getpass (never from argv).
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

from . import config
from . import security as sec


def _svc(s):
    from .clock import SystemClock
    from .db import DB
    from .service import LicenseService
    db = DB(s.db_path)
    return LicenseService(s, db, SystemClock(db))


def _pw(confirm: bool = True) -> str:
    p = getpass.getpass("Hasło (min. 12 znaków): ")
    if confirm and getpass.getpass("Powtórz hasło: ") != p:
        sys.exit("Hasła różnią się.")
    return p


def _show_mfa(out: dict) -> None:
    print("\nSkonfiguruj aplikację TOTP (Google Authenticator, Aegis, 1Password...):")
    print("  sekret:", out["totp_secret"])
    print("  URI   :", out["otpauth_uri"])
    print("\nKody odzyskiwania (jednorazowe, zapisz offline - nie będą pokazane ponownie):")
    for c in out["recovery_codes"]:
        print("  ", c)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="mqlicense")
    ap.add_argument("--env-file", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen-keys")
    g.add_argument("--out", default="secrets")
    sub.add_parser("check")
    sub.add_parser("migrate")
    for name in ("bootstrap-admin", "add-admin", "reset-mfa", "disable-admin", "enable-admin"):
        p = sub.add_parser(name)
        p.add_argument("--email", required=True)
        if name == "add-admin":
            p.add_argument("--role", choices=["ADMIN", "VIEWER"], default="VIEWER")
    sub.add_parser("clock-ack")
    b = sub.add_parser("backup")
    b.add_argument("--out", required=True)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default=None)
    sv.add_argument("--port", type=int, default=None)
    a = ap.parse_args(argv)

    if a.cmd == "gen-keys":
        out = Path(a.out)
        kp = out / "signing_ed25519.pem"
        if kp.exists():
            sys.exit(f"{kp} już istnieje - nie nadpisuję (rotacja: patrz README_SERWER_PL.md).")
        pub = sec.gen_signing_key(kp)
        (out / "signing_ed25519.pub.pem").write_text(pub, encoding="utf-8")
        from cryptography.fernet import Fernet
        env = out / "secrets.env"
        env.write_text(f"MQL_SIGNING_KEY_FILE={kp.resolve()}\nMQL_KEY_PEPPER={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}\n"
                       f"MQL_DATA_KEY={Fernet.generate_key().decode()}\n", encoding="utf-8")
        try:
            env.chmod(0o600)
        except OSError:
            pass
        print(f"Zapisano: {kp}, {env} (dopisz do .env serwera; NIE commituj, NIE kopiuj do klienta).")
        print("Klucz publiczny (wklej do config klienta: license.public_key_pem):\n" + pub)
        return 0

    s = config.load(a.env_file)
    if a.cmd == "check":
        probs = s.problems()
        print(json.dumps({"env": s.env, "db": s.db_path, "problems": probs}, ensure_ascii=False, indent=2))
        return 1 if probs else 0
    if a.cmd == "migrate":
        from .db import DB
        print("Zastosowano:", DB(s.db_path).versions())
        return 0
    if a.cmd == "backup":
        from .db import DB
        DB(s.db_path).backup(a.out)
        print("Kopia:", a.out)
        return 0
    probs = s.problems()
    if probs and a.cmd != "clock-ack":
        print("Konfiguracja niekompletna:\n - " + "\n - ".join(probs))
        if s.env == "prod" or a.cmd == "serve":
            return 2
    svc = _svc(s)
    from .service import Denied
    try:
        if a.cmd == "bootstrap-admin":
            _show_mfa(svc.add_admin(a.email, _pw(), "ADMIN", bootstrap=True))
        elif a.cmd == "add-admin":
            _show_mfa(svc.add_admin(a.email, _pw(), a.role))
        elif a.cmd == "reset-mfa":
            _show_mfa(svc.reset_mfa(a.email))
        elif a.cmd in ("disable-admin", "enable-admin"):
            svc.set_admin_status(a.email, "DISABLED" if a.cmd == "disable-admin" else "ACTIVE")
            print("OK")
        elif a.cmd == "clock-ack":
            svc.clock.acknowledge()
            svc.audit(None, actor="cli", action="CLOCK_ACK")
            print("Anomalia zegara potwierdzona.")
        elif a.cmd == "serve":
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(svc), host=a.host or s.host, port=a.port or s.port, access_log=False, log_level="warning",
                        proxy_headers=s.trust_proxy, forwarded_allow_ips="127.0.0.1" if s.trust_proxy else None)
    except Denied as e:
        print("Odmowa:", e.code, e.detail or "")
        return 3
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
