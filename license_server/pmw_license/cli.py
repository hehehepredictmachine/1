"""Server administration from the server's shell (python -m pmw_license <command>):

  init-keys        create the Ed25519 signing key (refuses to overwrite) and print the PUBLIC key for client builds
  public-key       print the public key / key id of the existing signing key
  hash-password    ask for the admin password twice and print PMW_LIC_ADMIN_PASSWORD_HASH (the password is never stored)
  new-pepper       print a random PMW_LIC_KEY_PEPPER
  serve            run the API (behind the HTTPS reverse proxy)
  create-license   emergency key generation on the server itself (--duration 24h|72h|7d|31d); the key is shown once
  admin-keys add --public-key B64 --label NAME    trust an OWNER device key (out-of-band pairing - the only way to add one)
  admin-keys list                                 trusted / revoked OWNER device keys
  admin-keys revoke KID [--reason TEXT]           revoke a device key (lost / replaced computer)
  backup-db --out FILE                            consistent snapshot of the database while the API runs (keep it offline)
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from . import VERSION
from .config import Settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pmw_license", description=f"PepeMarketWizard License API {VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-keys")
    sub.add_parser("public-key")
    sub.add_parser("hash-password")
    sub.add_parser("new-pepper")
    sub.add_parser("serve")
    cl = sub.add_parser("create-license")
    cl.add_argument("--duration", required=True, choices=["24h", "72h", "7d", "31d"])
    cl.add_argument("--note", default=None)
    ak = sub.add_parser("admin-keys")
    aks = ak.add_subparsers(dest="sub", required=True)
    a_add = aks.add_parser("add")
    a_add.add_argument("--public-key", required=True)
    a_add.add_argument("--label", default="OWNER")
    aks.add_parser("list")
    a_rev = aks.add_parser("revoke")
    a_rev.add_argument("kid")
    a_rev.add_argument("--reason", default=None)
    bk = sub.add_parser("backup-db")
    bk.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    s = Settings()
    if a.cmd == "init-keys":
        from .signing import Signer
        sg = Signer.generate()
        sg.write_private(s.signing_key)
        print(f"Zapisano klucz prywatny: {s.signing_key} (tylko na serwerze, chmod 600, kopia zapasowa offline)")
        print(f"KLUCZ PUBLICZNY (do paczki CLIENT): {sg.public_b64}")
        print(f"ID klucza (kid): {sg.kid}")
        return 0
    if a.cmd == "public-key":
        from .signing import Signer
        sg = Signer.load(s.signing_key)
        print(f"KLUCZ PUBLICZNY: {sg.public_b64}\nkid: {sg.kid}")
        return 0
    if a.cmd == "hash-password":
        from .security import hash_password
        p1 = getpass.getpass("Nowe hasło administratora (min. 12 znaków): ")
        p2 = getpass.getpass("Powtórz hasło: ")
        if p1 != p2:
            print("Hasła się różnią.", file=sys.stderr)
            return 2
        print("PMW_LIC_ADMIN_PASSWORD_HASH=" + hash_password(p1))
        return 0
    if a.cmd == "new-pepper":
        print("PMW_LIC_KEY_PEPPER=" + secrets.token_urlsafe(48))
        return 0
    if a.cmd == "serve":
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(s), host=s.host, port=s.port, server_header=False, log_level="info")
        return 0
    if a.cmd == "admin-keys":
        import time
        from . import admin_auth as AA
        from .store import Store
        st = Store(s.database)
        if a.sub == "add":
            try:
                out = AA.add_key(st, a.public_key, a.label, actor="server-shell", now=time.time())
            except ValueError as exc:
                print(f"[BŁĄD] {exc}", file=sys.stderr)
                return 2
            print(f"{out['status']}: {out['kid']} ({a.label}) – aplikacja OWNER z tym kluczem może teraz zarządzać licencjami bez logowania")
            return 0
        if a.sub == "list":
            from .protocol import utc_iso
            for k in AA.list_keys(st):
                state = f"ODWOŁANY {utc_iso(k['revoked_at'])}" if k["revoked_at"] else "ZAUFANY"
                used = utc_iso(k["last_used_at"]) if k["last_used_at"] else "—"
                print(f"{k['kid']}  {state:<32} {k['label'] or '':<24} dodany {utc_iso(k['created_at'])}  ostatnio {used}")
            return 0
        if a.sub == "revoke":
            from .service import LicenseError
            try:
                AA.revoke_key(st, a.kid, "server-shell", time.time(), a.reason)
            except LicenseError as exc:
                print(f"[BŁĄD] {exc.message}", file=sys.stderr)
                return 2
            print(f"Odwołano {a.kid}")
            return 0
    if a.cmd == "backup-db":
        from .store import Store
        out = Store(s.database).backup(a.out)
        print(f"Kopia bazy: {out} (chmod 600). Klucz podpisu {s.signing_key} i plik konfiguracji kopiuj osobno, offline.")
        return 0
    if a.cmd == "create-license":
        from .service import LicenseService
        from .signing import Signer
        from .store import Store
        probs = s.problems()
        if [p for p in probs if "PEPPER" in p or "podpisu" in p]:
            print("Brak konfiguracji: " + "; ".join(probs), file=sys.stderr)
            return 2
        out = LicenseService(Store(s.database), Signer.load(s.signing_key), s.key_pepper).create(a.duration, actor="cli", note=a.note)
        print(f"{out['license_id']} {out['duration']}: {out['license_key']}   (klucz widoczny tylko teraz)")
        return 0
    return 1
