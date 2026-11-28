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
# the terminal simulator closes the market at the weekend; offline tests must not depend on the day they are run
os.environ.setdefault("MQ_FAKE_MARKET_ALWAYS_OPEN", "1")
os.environ.setdefault("MQ_BASKETS_OFFLINE", "1")          # 1.41: no Hyperliquid calls from the test suite
sys.path.insert(0, str(ROOT / "backend"))

UTC = timezone.utc


def api_sources() -> str:
    """Source text of the bot API routes: api/app.py + api/schemas.py + api/routes/*.py. Etap 4 krok B moved the handlers of
    create_app from api/app.py to api/routes/<domain>.py unchanged - tests that read the handler source read all of it."""
    api = ROOT / "backend" / "masterquo" / "api"
    files = [api / "app.py", api / "schemas.py", *sorted((api / "routes").glob("*.py"))]
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


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
        cfg.update({"mt5": {"symbol": symbol}, "assets": {"mappings": {"XAUUSD": {"broker_symbol": symbol, "status": "USER_SPECIFIED"}}}})
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
