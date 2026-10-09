"""Server clock with anomaly detection. All license decisions use THIS clock (UTC epoch seconds).

* `now()` is injectable for tests (ControlledClock) - no waiting two days.
* Anomaly = wall clock went backwards vs. the highest time ever seen (persisted), or wall and monotonic clocks
  diverged by more than `max_jump` within the process. While an anomaly is active the server issues NO new
  rights (activations, leases, operation tokens) until an administrator resolves it (`python -m mqcentral clock-ack`).
"""
from __future__ import annotations

import threading
import time


class SystemClock:
    def __init__(self, db=None, max_jump: float = 120.0):
        self.db = db
        self.max_jump = max_jump
        self._lock = threading.Lock()
        self._base = (time.time(), time.monotonic())
        self._max_seen = 0.0
        self._last_persist = 0.0
        self.anomaly: str | None = None
        if db is not None:
            r = db.one("SELECT value FROM server_meta WHERE key='clock_max_seen'")
            self._max_seen = float(r["value"]) if r else 0.0
            a = db.one("SELECT value FROM server_meta WHERE key='clock_anomaly'")
            self.anomaly = a["value"] if a and a["value"] else None

    def wall(self) -> float:
        return time.time()

    def now(self) -> int:
        t = self.wall()
        with self._lock:
            w0, m0 = self._base
            drift = (t - w0) - (time.monotonic() - m0)
            if abs(drift) > self.max_jump:
                self._flag(f"WALL_MONOTONIC_DRIFT_{int(drift)}S")
                self._base = (t, time.monotonic())
            if t < self._max_seen - self.max_jump:
                self._flag(f"CLOCK_WENT_BACK_{int(self._max_seen - t)}S")
            if t > self._max_seen:
                self._max_seen = t
                if self.db is not None and t - self._last_persist > 30:
                    self._last_persist = t
                    self._meta("clock_max_seen", str(t))
        return int(t)

    def _flag(self, why: str) -> None:
        if not self.anomaly:
            self.anomaly = why
            if self.db is not None:
                self._meta("clock_anomaly", why)

    def _meta(self, k: str, v: str) -> None:
        if self.db.one("SELECT 1 AS x FROM server_meta WHERE key=?", (k,)):
            self.db.x("UPDATE server_meta SET value=? WHERE key=?", (v, k))
        else:
            self.db.x("INSERT INTO server_meta(key, value) VALUES (?, ?)", (k, v))

    def acknowledge(self) -> None:
        self.anomaly = None
        self._max_seen = self.wall()
        self._base = (time.time(), time.monotonic())
        if self.db is not None:
            self._meta("clock_anomaly", "")
            self._meta("clock_max_seen", str(self._max_seen))

    def check_reference(self, url: str) -> float | None:
        """Optional: compare with the Date header of a trusted HTTPS server (certificate validation ON)."""
        import email.utils
        import urllib.request
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=10) as r:
                ref = email.utils.parsedate_to_datetime(r.headers["Date"]).timestamp()
            skew = self.wall() - ref
            if abs(skew) > self.max_jump:
                self._flag(f"REFERENCE_SKEW_{int(skew)}S")
            return skew
        except Exception:
            return None


class ControlledClock(SystemClock):
    """Test clock: time only moves when the test says so."""

    def __init__(self, start: float, db=None):
        super().__init__(db=None)
        self.t = float(start)

    def wall(self) -> float:
        return self.t

    def now(self) -> int:
        return int(self.t)

    def advance(self, s: float) -> None:
        self.t += s
