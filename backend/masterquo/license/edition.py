"""Edition of this installation - fixed at build time in <root>/edition.json:

  {"edition": "OWNER"}                                       the owner's bot: no license gate, License Manager available
  {"edition": "CLIENT", "license_api": "https://...",        a customer's bot: KEY FOR MAGIC + LicenseGuard before every
   "public_key": "<base64 Ed25519>", "kid": "..."}           new trading action; the public key is the only key it holds

Fail-closed: a missing / unreadable / unknown file means CLIENT (never OWNER). The environment variable
MASTERQUO_EDITION=CLIENT can force the stricter edition (tests); it can never switch a CLIENT build to OWNER.
A desktop program runs on the customer's machine: editing this file is possible for a determined user - the licensing
raises the effort, it is not tamper-proof (see docs/LICENCJE_SYSTEM_1_27_PL.md).
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from .. import paths
from . import protocol as P
from .url import valid_license_url

EDITION_FILE = paths.ROOT_DIR / "edition.json"


@dataclass(frozen=True)
class Edition:
    edition: str                     # OWNER / CLIENT
    license_api: str | None = None   # https://... (CLIENT)
    public_key_b64: str | None = None
    kid: str | None = None
    problem: str | None = None       # why a CLIENT build cannot work yet (not stamped, bad key...)

    @property
    def is_owner(self) -> bool:
        return self.edition == "OWNER"

    @property
    def public_key_raw(self) -> bytes | None:
        try:
            raw = base64.b64decode(self.public_key_b64 or "", validate=True)
        except (ValueError, TypeError):
            return None
        return raw if len(raw) == 32 else None

    def public(self) -> dict:
        return {"edition": self.edition, "license_api": self.license_api, "kid": self.kid, "configured": self.problem is None,
                "problem": self.problem}


def load(path=None) -> Edition:
    """MASTERQUO_EDITION_FILE may point to another CLIENT file (tests, a second license server); a file named that way is
    never accepted as OWNER - the owner edition comes only from the installation's own edition.json."""
    env_file = os.environ.get("MASTERQUO_EDITION_FILE")
    path = path or env_file or EDITION_FILE
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    ed = str(d.get("edition") or "").upper()
    if ed == "OWNER" and os.environ.get("MASTERQUO_EDITION", "").upper() != "CLIENT" and not (env_file and path == env_file):
        return Edition("OWNER")
    api = (d.get("license_api") or "").strip().rstrip("/") or None
    pub = (d.get("public_key") or "").strip() or None
    e = Edition("CLIENT", api, pub, d.get("kid"))
    problem = None
    if ed not in ("OWNER", "CLIENT"):
        problem = "brak pliku edition.json – instalacja traktowana jako CLIENT"
    if not api or not pub:
        problem = "paczka CLIENT nie jest przygotowana (brak adresu serwera licencji lub klucza publicznego) – poproś dostawcę o paczkę"
    elif not valid_license_url(api):
        problem = "adres serwera licencji musi używać HTTPS"
    elif e.public_key_raw is None:
        problem = "nieprawidłowy klucz publiczny serwera licencji w edition.json"
    elif e.kid and e.kid != P.key_id(e.public_key_raw):
        problem = "identyfikator klucza (kid) nie pasuje do klucza publicznego"
    return Edition("CLIENT", api, pub, e.kid or (P.key_id(e.public_key_raw) if e.public_key_raw else None), problem)
