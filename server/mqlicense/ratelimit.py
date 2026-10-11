"""In-process sliding-window rate limiter (one server process). Put additional limits in the reverse proxy
(documented in README_SERWER_PL.md)."""
from __future__ import annotations

import collections
import threading
import time


class RateLimiter:
    def __init__(self, mono=time.monotonic):
        self._hits: dict[str, collections.deque] = {}
        self._lock = threading.Lock()
        self.mono = mono

    def hit(self, key: str, limit: int, window_s: float) -> bool:
        """Records an attempt; False when the limit is exceeded."""
        now = self.mono()
        with self._lock:
            dq = self._hits.setdefault(key, collections.deque())
            while dq and dq[0] <= now - window_s:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            if len(self._hits) > 50000:
                self._hits = {k: v for k, v in self._hits.items() if v}
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


LIMITS = {
    "client_session_ip": (20, 600),      # session openings per IP / 10 min
    "client_session_key": (10, 600),     # per license key (hash prefix) / 10 min
    "client_heartbeat": (30, 60),        # per session / minute (normal: 4-6)
    "admin_login_ip": (20, 600), "admin_login_email": (6, 900), "admin_write": (120, 60),
}
