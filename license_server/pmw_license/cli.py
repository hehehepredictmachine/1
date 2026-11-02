"""Server administration from the server's shell (python -m pmw_license <command>):

  init-keys        create the Ed25519 signing key (refuses to overwrite) and print the PUBLIC key for client builds
  public-key       print the public key / key id of the existing signing key
  hash-password    ask for the admin password twice and print PMW_LIC_ADMIN_PASSWORD_HASH (the password is never stored)
  new-pepper       print a random PMW_LIC_KEY_PEPPER
  serve            run the API (behind the HTTPS reverse proxy)
  create-license   emergency key generation on the server itself (--duration 24h|72h|7d|31d); the key is shown once
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
