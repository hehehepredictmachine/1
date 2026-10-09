"""Server configuration from environment variables (see server/.env.example). Secrets never come from the repository."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _b(v: str | None, default: bool = False) -> bool:
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    env: str = "production"                       # production / dev (dev = local development only)
    database_url: str = ""
    public_url: str = ""                          # https://licencje.twojadomena.pl  (issuer of leases, links in e-mails)
    allowed_origins: list[str] = field(default_factory=list)
    signing_key_file: str = ""                    # Ed25519 private key (PEM) - server only
    data_key: str = ""                            # Fernet key (urlsafe base64, 32 bytes) for TOTP secrets
    mail_mode: str = "smtp"                       # smtp / dev-outbox (dev only)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    secure_cookies: bool = True
    lease_seconds: int = 60
    op_token_seconds: int = 20
    license_seconds: int = 172800                 # standard license: exactly 48 h from first activation
    session_hours_web: int = 12
    session_hours_client: int = 24
    max_body_bytes: int = 1_000_000
    trusted_proxy: bool = False                   # use X-Forwarded-For from the reverse proxy (Caddy/nginx)
    time_reference_url: str = ""                  # optional HTTPS URL whose Date header is used to monitor the clock
    admin_web_dir: str = ""

    @property
    def dev(self) -> bool:
        return self.env == "dev"

    @property
    def issuer(self) -> str:
        return self.public_url.rstrip("/")


def load() -> Settings:
    e = os.environ
    s = Settings(
        env=e.get("MQC_ENV", "production"),
        database_url=e.get("MQC_DATABASE_URL", ""),
        public_url=e.get("MQC_PUBLIC_URL", ""),
        allowed_origins=[o.strip().rstrip("/") for o in e.get("MQC_ALLOWED_ORIGINS", "").split(",") if o.strip()],
        signing_key_file=e.get("MQC_SIGNING_KEY_FILE", ""),
        data_key=e.get("MQC_DATA_KEY", ""),
        mail_mode=e.get("MQC_MAIL_MODE", "smtp"),
        smtp_host=e.get("MQC_SMTP_HOST", ""),
        smtp_port=int(e.get("MQC_SMTP_PORT", "587")),
        smtp_user=e.get("MQC_SMTP_USER", ""),
        smtp_password=e.get("MQC_SMTP_PASSWORD", ""),
        smtp_from=e.get("MQC_SMTP_FROM", ""),
        smtp_starttls=_b(e.get("MQC_SMTP_STARTTLS"), True),
        secure_cookies=_b(e.get("MQC_SECURE_COOKIES"), True),
        lease_seconds=int(e.get("MQC_LEASE_SECONDS", "60")),
        license_seconds=int(e.get("MQC_LICENSE_SECONDS", "172800")),
        trusted_proxy=_b(e.get("MQC_TRUSTED_PROXY"), False),
        time_reference_url=e.get("MQC_TIME_REFERENCE_URL", ""),
        admin_web_dir=e.get("MQC_ADMIN_WEB_DIR", str(Path(__file__).resolve().parents[1] / "admin-web" / "dist")),
    )
    if not s.public_url and s.allowed_origins:
        s.public_url = s.allowed_origins[0]
    if not s.allowed_origins and s.public_url:
        s.allowed_origins = [s.public_url.rstrip("/")]
    return s


def validate(s: Settings) -> list[str]:
    """Hard errors that stop the server - production never silently skips e-mail verification or HTTPS cookies."""
    errs = []
    if not s.database_url:
        errs.append("MQC_DATABASE_URL nie ustawione")
    if not s.public_url:
        errs.append("MQC_PUBLIC_URL nie ustawione")
    if not s.signing_key_file or not Path(s.signing_key_file).exists():
        errs.append("MQC_SIGNING_KEY_FILE nie istnieje (python -m mqcentral gen-keys)")
    if not s.data_key:
        errs.append("MQC_DATA_KEY nie ustawione (python -m mqcentral gen-keys)")
    if s.license_seconds != 172800 and not s.dev:
        errs.append("MQC_LICENSE_SECONDS musi wynosić 172800 (48 h) poza środowiskiem dev")
    if not s.dev:
        if s.database_url.startswith("sqlite"):
            errs.append("SQLite jest dozwolone tylko w MQC_ENV=dev – użyj PostgreSQL")
        if not s.public_url.startswith("https://"):
            errs.append("MQC_PUBLIC_URL musi być https:// poza środowiskiem dev")
        if not s.secure_cookies:
            errs.append("MQC_SECURE_COOKIES=0 jest dozwolone tylko w MQC_ENV=dev")
        if s.mail_mode != "smtp":
            errs.append("MQC_MAIL_MODE=dev-outbox jest dozwolone tylko w MQC_ENV=dev")
        elif not (s.smtp_host and s.smtp_from):
            errs.append("SMTP nie skonfigurowane (MQC_SMTP_HOST, MQC_SMTP_FROM)")
    return errs
