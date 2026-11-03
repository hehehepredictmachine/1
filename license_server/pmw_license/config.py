"""License API configuration - environment variables only (never source control).

PMW_LIC_DATABASE          path of the SQLite file (default ./data/licenses.db; keep it outside any web root, chmod 600)
PMW_LIC_SIGNING_KEY       path of the Ed25519 PRIVATE key (PEM, PKCS8) - server only (default ./secrets/signing_key.pem)
PMW_LIC_KEY_PEPPER        server-side secret mixed into the license-key hash (HMAC-SHA256); required in production
PMW_LIC_ADMIN_USER        administrator user name (only for the optional recovery password login)
PMW_LIC_ADMIN_PASSWORD_HASH  OPTIONAL scrypt hash from `python -m pmw_license hash-password` - empty = password login disabled
                          (normal administration: OWNER device keys, `python -m pmw_license admin-keys add`)
PMW_LIC_ENV               production | development (production refuses to start with missing secrets)
PMW_LIC_HOST / PMW_LIC_PORT  bind address (default 127.0.0.1:8740 - expose only through the HTTPS reverse proxy)
PMW_LIC_TRUST_PROXY       1 = take the client IP from X-Forwarded-For (only behind your own proxy)
PMW_LIC_RATE_PUBLIC_PER_MIN   activation / validation requests per IP and minute (default 30)
PMW_LIC_RATE_LOGIN_PER_MIN    admin login attempts per IP and minute (default 5)
PMW_LIC_ADMIN_SESSION_HOURS   admin session lifetime (default 8)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    database: Path = field(default_factory=lambda: Path(os.environ.get("PMW_LIC_DATABASE", "./data/licenses.db")))
    signing_key: Path = field(default_factory=lambda: Path(os.environ.get("PMW_LIC_SIGNING_KEY", "./secrets/signing_key.pem")))
    key_pepper: str = field(default_factory=lambda: os.environ.get("PMW_LIC_KEY_PEPPER", ""))
    admin_user: str = field(default_factory=lambda: os.environ.get("PMW_LIC_ADMIN_USER", ""))
    admin_password_hash: str = field(default_factory=lambda: os.environ.get("PMW_LIC_ADMIN_PASSWORD_HASH", ""))
    env: str = field(default_factory=lambda: os.environ.get("PMW_LIC_ENV", "production"))
    host: str = field(default_factory=lambda: os.environ.get("PMW_LIC_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("PMW_LIC_PORT", "8740")))
    trust_proxy: bool = field(default_factory=lambda: os.environ.get("PMW_LIC_TRUST_PROXY", "0") == "1")
    rate_public_per_min: int = field(default_factory=lambda: int(os.environ.get("PMW_LIC_RATE_PUBLIC_PER_MIN", "30")))
    rate_login_per_min: int = field(default_factory=lambda: int(os.environ.get("PMW_LIC_RATE_LOGIN_PER_MIN", "5")))
    admin_session_hours: float = field(default_factory=lambda: float(os.environ.get("PMW_LIC_ADMIN_SESSION_HOURS", "8")))

    def problems(self) -> list[str]:
        """Missing / unsafe settings. In production any problem stops the server."""
        out = []
        if self.admin_password_hash and (not self.admin_user or not self.admin_password_hash.startswith("scrypt$")):
            out.append("PMW_LIC_ADMIN_PASSWORD_HASH ustawiony niepoprawnie (pusty = logowanie hasłem wyłączone; inaczej hash scrypt i PMW_LIC_ADMIN_USER)")
        if len(self.key_pepper) < 32:
            out.append("PMW_LIC_KEY_PEPPER musi mieć co najmniej 32 znaki (np. python -m pmw_license new-pepper)")
        if not self.signing_key.exists():
            out.append(f"brak klucza podpisu {self.signing_key} (python -m pmw_license init-keys)")
        return out
