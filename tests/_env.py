"""Test environment: isolated data dir per test case, backend on sys.path, synthetic MT5."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

UTC = timezone.utc


class TempData:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="mq_test_")
        self.prev = os.environ.get("MASTERQUO_DATA_DIR")
        os.environ["MASTERQUO_DATA_DIR"] = self.dir

    def close(self):
        if self.prev is None:
            os.environ.pop("MASTERQUO_DATA_DIR", None)
        else:
            os.environ["MASTERQUO_DATA_DIR"] = self.prev
        shutil.rmtree(self.dir, ignore_errors=True)


class Clock:
    """Mutable clock for deterministic time tests."""

    def __init__(self, start: datetime | None = None):
        self.t = start or datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


def wait_for(pred, timeout: float = 30.0, step: float = 0.1) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def core(fake_kwargs: dict | None = None, symbol: str = "XAUUSD-"):
    """Build config/db/bus/log/worker/bridge on a FakeMT5 (not started)."""
    from masterquo.config import ConfigStore
    from masterquo.db.database import Database
    from masterquo.events import AppLog, EventBus
    from masterquo.mt5.bridge import MarketBridge
    from masterquo.mt5.fake import FakeMT5
    from masterquo.mt5.worker import MT5Worker
    cfg = ConfigStore()
    if symbol != cfg.get().mt5.symbol:
        cfg.update({"mt5": {"symbol": symbol}})
    db = Database()
    bus = EventBus()
    log = AppLog(db, bus)
    fake = FakeMT5(**(fake_kwargs or {}))
    worker = MT5Worker(lambda: fake)
    worker.start()
    bridge = MarketBridge(cfg, worker, db, bus, log)
    return cfg, db, bus, log, fake, worker, bridge


def bar(t_open: datetime, o, h, l, c, closed=True, available=None, tv=100):
    iso = lambda d: d.astimezone(UTC).isoformat().replace("+00:00", "Z")  # noqa: E731
    conf = t_open + timedelta(minutes=15)
    return {"t_raw": int(t_open.timestamp()), "open_utc": iso(t_open), "o": o, "h": h, "l": l, "c": c, "tv": tv, "rv": 0,
            "spread": 10, "closed": closed, "close_confirmed_utc": iso(conf) if closed else None,
            "available_at": iso(available or conf) if closed else None, "basis": "OBSERVED", "revision": 0}


# ----------------------------------------------------------------------------- licensing test doubles (tests only)
def granted_guard(seconds: float = 3600.0, scopes=None):
    """A REAL LicenseGuard holding a test lease (as if a heartbeat succeeded). Never shipped as a bypass."""
    import time as _t
    from masterquo.licensing.guard import SCOPES, LicenseGuard
    g = LicenseGuard()
    g.install({"scope": list(scopes or SCOPES), "sub": "TEST", "jti": "TEST"}, _t.monotonic() + seconds)
    return g


class FakeLicense:
    """Gateway-facing double: real guard + locally issued single-use operation grants (central server not involved)."""

    def __init__(self, guard=None):
        self.guard = guard or granted_guard()
        self.authorized: list[str] = []
        self._used: set = set()

    def authorize_open(self, intent_id, detail):
        import time as _t
        import uuid as _u
        from masterquo.licensing.service import OpGrant
        self.guard.require("trade_open")
        self.authorized.append(intent_id)
        return OpGrant({"jti": _u.uuid4().hex, "intent": intent_id, "op": "OPEN"}, _t.monotonic() + 20)

    def consume(self, grant):
        import time as _t
        from masterquo.licensing.guard import LicenseRequired
        if grant.used or grant.claims["jti"] in self._used:
            raise LicenseRequired("OP_TOKEN_REUSED")
        if _t.monotonic() >= grant.deadline:
            raise LicenseRequired("OP_TOKEN_EXPIRED")
        self.guard.require("trade_open")
        grant.used = True
        self._used.add(grant.claims["jti"])
