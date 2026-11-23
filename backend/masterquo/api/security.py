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
import threading
from collections import OrderedDict

SESSION_COOKIE = "mq_sid"
MAX_SESSIONS = 200


class LocalSecurity:
    def __init__(self, port: int):
        self.port = port
        self.sessions: OrderedDict[str, str] = OrderedDict()  # sid -> csrf, least recently USED first
        self._lock = threading.Lock()
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
        # 1.46: evict the least recently USED session, never all of them (1.45.0: >200 GET / from any web page cleared every session and
        # logged the open panel out - its STOP / close buttons stopped working until a reload)
        sid, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with self._lock:
            while len(self.sessions) >= MAX_SESSIONS:
                self.sessions.popitem(last=False)
            self.sessions[sid] = csrf
        return sid, csrf

    def csrf_for(self, sid: str | None) -> str | None:
        with self._lock:
            csrf = self.sessions.get(sid or "")
            if csrf is not None:
                self.sessions.move_to_end(sid)          # an active panel (polling / WebSocket) is never the eviction candidate
            return csrf

    def csrf_ok(self, sid: str | None, token: str | None) -> bool:
        exp = self.csrf_for(sid)
        return bool(exp and token and hmac.compare_digest(exp, token))
