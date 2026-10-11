"""Settings from environment variables (MQL_*) or a .env file. Nothing secret has a default value."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import LICENSE_SECONDS


def _b(v: str | None, d: bool) -> bool:
    return d if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    env: str = "prod"                              # prod | dev | test
    db_path: str = "data/mqlicense.sqlite3"
    public_url: str = ""                           # https://licencje.twoja-domena.pl
    signing_key_file: str = ""                     # Ed25519 private key (PEM) - signs client leases
    key_pepper: str = ""                           # secret for HMAC of license keys (32+ random bytes, base64)
    data_key: str = ""                             # Fernet key encrypting admin TOTP secrets
    license_seconds: int = LICENSE_SECONDS
    lease_seconds: int = 30                        # client lease; revocation reaches a client within this time
    default_max_sessions: int = 1
    admin_session_minutes: int = 60
    allowed_origins: list[str] = field(default_factory=list)
    host: str = "127.0.0.1"
    port: int = 8790
    trust_proxy: bool = False                      # use X-Forwarded-For (only behind your own reverse proxy)

    @property
    def secure_cookies(self) -> bool:
        return self.env == "prod"

    def problems(self) -> list[str]:
        p = []
        if not self.signing_key_file or not Path(self.signing_key_file).exists():
            p.append("MQL_SIGNING_KEY_FILE: brak pliku klucza podpisu (python -m mqlicense gen-keys)")
        if len(self.key_pepper) < 32:
            p.append("MQL_KEY_PEPPER: brak lub za krótki sekret (min. 32 znaki)")
        if not self.data_key:
            p.append("MQL_DATA_KEY: brak klucza szyfrowania sekretów TOTP")
        if self.env == "prod":
            if self.license_seconds != LICENSE_SECONDS:
                p.append("MQL_LICENSE_SECONDS: w produkcji licencja trwa dokładnie 259200 s (72 h)")
            if not self.public_url.startswith("https://"):
                p.append("MQL_PUBLIC_URL: w produkcji wymagany adres https://")
            if not self.lease_seconds or self.lease_seconds > 30:
                p.append("MQL_LEASE_SECONDS: maks. 30 s (cofnięcie musi dotrzeć do klienta w 30 s)")
        return p


def load(env_file: str | None = None) -> Settings:
    path = Path(env_file or os.environ.get("MQL_ENV_FILE") or ".env")
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    g = os.environ.get
    s = Settings(env=g("MQL_ENV", "prod"), db_path=g("MQL_DB_PATH", "data/mqlicense.sqlite3"), public_url=g("MQL_PUBLIC_URL", ""),
                 signing_key_file=g("MQL_SIGNING_KEY_FILE", ""), key_pepper=g("MQL_KEY_PEPPER", ""), data_key=g("MQL_DATA_KEY", ""),
                 license_seconds=int(g("MQL_LICENSE_SECONDS", str(LICENSE_SECONDS))), lease_seconds=int(g("MQL_LEASE_SECONDS", "30")),
                 default_max_sessions=int(g("MQL_DEFAULT_MAX_SESSIONS", "1")), admin_session_minutes=int(g("MQL_ADMIN_SESSION_MINUTES", "60")),
                 allowed_origins=[x.strip() for x in g("MQL_ALLOWED_ORIGINS", "").split(",") if x.strip()],
                 host=g("MQL_HOST", "127.0.0.1"), port=int(g("MQL_PORT", "8790")), trust_proxy=_b(g("MQL_TRUST_PROXY"), False))
    return s
