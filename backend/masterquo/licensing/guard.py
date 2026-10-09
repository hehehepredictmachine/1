"""LicenseGuard - the single local permission check used by the engine, setups, ML, agent, execution, API, WebSocket and CLI.

* Rights exist ONLY while a lease signed by the central server is held in memory. No file, no cache, no default
  grants anything: a missing or invalid lease = no product functions (deny by default).
* The lease deadline is a MONOTONIC deadline computed conservatively from the moment the heartbeat request was SENT:
  deadline = t_send + (exp - iat), never extended by network delay or by the local wall clock.
* A process restart starts without a lease. A jump between wall and monotonic clocks (sleep/hibernation on systems where
  the monotonic clock stops, manual clock change) drops the lease -> online revalidation before any protected action.
This protects against editing files or the system clock; it does NOT make a modified local program impossible -
see LICENCJE_OGRANICZENIA in the documentation.
"""
from __future__ import annotations

import threading
import time

SCOPES = ("analysis", "setups", "ml_train", "agent", "trade_open", "telemetry")


class LicenseRequired(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class LicenseGuard:
    def __init__(self, mono=time.monotonic, wall=time.time, max_discontinuity_s: float = 5.0):
        self.mono, self.wall = mono, wall
        self.max_disc = max_discontinuity_s
        self._lock = threading.RLock()
        self._claims: dict | None = None
        self._deadline = 0.0
        self._ref = (wall(), mono())
        self.reason = "NO_LEASE_YET"
        self.listeners: list = []           # fn(valid: bool, reason: str)
        self._was_valid = False

    # ------------------------------------------------------------ internals
    def _discontinuity(self) -> bool:
        w, m = self.wall(), self.mono()
        w0, m0 = self._ref
        self._ref = (w, m)
        return abs((w - w0) - (m - m0)) > self.max_disc

    def _valid_locked(self) -> bool:
        if self._claims is None:
            return False
        if self._discontinuity():
            self._drop_locked("CLOCK_DISCONTINUITY_REVALIDATE_ONLINE")
            return False
        if self.mono() >= self._deadline:
            self._drop_locked("LEASE_EXPIRED_NO_FRESH_SERVER_CONFIRMATION")
            return False
        return True

    def _drop_locked(self, reason: str) -> None:
        self._claims = None
        self._deadline = 0.0
        self.reason = reason

    def _notify(self) -> None:
        with self._lock:
            now = self._claims is not None and self.mono() < self._deadline
            changed = now != self._was_valid
            self._was_valid = now
            reason = self.reason
        if changed:
            for fn in list(self.listeners):
                try:
                    fn(now, reason)
                except Exception:
                    pass

    # ------------------------------------------------------------ api
    def install(self, claims: dict, deadline_mono: float) -> None:
        with self._lock:
            self._claims = dict(claims)
            self._deadline = float(deadline_mono)
            self._ref = (self.wall(), self.mono())
            self.reason = "OK"
        self._notify()

    def clear(self, reason: str) -> None:
        with self._lock:
            self._drop_locked(reason)
        self._notify()

    def allows(self, scope: str) -> bool:
        with self._lock:
            ok = self._valid_locked() and scope in (self._claims or {}).get("scope", ())
        if not ok:
            self._notify()
        return ok

    def require(self, scope: str) -> dict:
        if not self.allows(scope):
            raise LicenseRequired(self.reason if self.reason != "OK" else f"SCOPE_{scope}_NOT_GRANTED")
        return dict(self._claims or {})

    def claims(self) -> dict | None:
        with self._lock:
            return dict(self._claims) if self._valid_locked() else None

    def lease_remaining(self) -> float:
        with self._lock:
            return max(0.0, self._deadline - self.mono()) if self._claims else 0.0

    def poll(self) -> None:
        """Called periodically: fires listeners when the lease ran out without a heartbeat."""
        with self._lock:
            self._valid_locked()
        self._notify()
