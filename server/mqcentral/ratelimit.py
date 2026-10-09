"""In-process sliding-window rate limiter (one server process). For several API processes put the limits in the
reverse proxy as well (documented in README_SERWER_PL.md)."""
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
    "login_ip": (30, 600), "login_email": (8, 900), "register_ip": (10, 3600), "forgot_email": (3, 3600), "forgot_ip": (20, 3600),
    "activate_user": (10, 3600), "mfa_session": (6, 600), "challenge_device": (120, 60), "heartbeat_device": (12, 60),
    "snapshot_device": (12, 60), "deals_device": (30, 60), "authorize_device": (30, 60), "admin_write": (120, 60),
}
