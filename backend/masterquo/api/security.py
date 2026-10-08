"""Local request security.

Loopback is not a security boundary by itself (other local programs and web pages in the browser
can reach 127.0.0.1). Therefore:
* Host header must be 127.0.0.1:<port> or localhost:<port>  (DNS-rebinding protection);
* state-changing requests and the WebSocket must carry an allowed Origin;
* a session cookie (HttpOnly, SameSite=Strict) is issued with the page; state-changing requests
  require the CSRF token (X-MQ-CSRF) that only same-origin script can read via /api/v1/session;
* the WebSocket requires the session cookie and the CSRF token in its first message.
"""
from __future__ import annotations

import hmac
import secrets

SESSION_COOKIE = "mq_sid"


class LocalSecurity:
    def __init__(self, port: int):
        self.port = port
        self.sessions: dict[str, str] = {}  # sid -> csrf
        self.shutdown_token = secrets.token_urlsafe(32)

    @property
    def hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    @property
    def origins(self) -> set[str]:
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    def host_ok(self, host: str | None) -> bool:
        return bool(host) and host in self.hosts

    def origin_ok(self, origin: str | None) -> bool:
        return bool(origin) and origin in self.origins

    def new_session(self) -> tuple[str, str]:
        if len(self.sessions) > 200:
            self.sessions.clear()
        sid, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        self.sessions[sid] = csrf
        return sid, csrf

    def csrf_for(self, sid: str | None) -> str | None:
        return self.sessions.get(sid or "")

    def csrf_ok(self, sid: str | None, token: str | None) -> bool:
        exp = self.csrf_for(sid)
        return bool(exp and token and hmac.compare_digest(exp, token))
