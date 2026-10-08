"""Event bus with monotonically increasing sequence numbers.

Producers run in worker threads; consumers are WebSocket sessions on the asyncio loop.
A ring buffer allows incremental resync (`since(seq)`); if the client fell further behind,
it receives `None` and must perform a full resync from the REST snapshot.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import threading
from typing import Any, Callable

from .timeutil import iso, utcnow

log = logging.getLogger("masterquo.events")


class EventBus:
    def __init__(self, capacity: int = 5000):
        self._lock = threading.Lock()
        self._seq = 0
        self._buf: collections.deque[dict] = collections.deque(maxlen=capacity)
        self._subscribers: list[Callable[[dict], None]] = []
        self.boot_id = utcnow().strftime("%Y%m%d%H%M%S%f")

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def publish(self, type_: str, data: Any) -> dict:
        with self._lock:
            self._seq += 1
            ev = {"seq": self._seq, "boot_id": self.boot_id, "type": type_, "ts": iso(utcnow()), "data": data}
            self._buf.append(ev)
            subs = list(self._subscribers)
        for s in subs:
            try:
                s(ev)
            except Exception:  # a broken consumer must not stop producers
                log.exception("event subscriber failed")
        return ev

    def since(self, seq: int) -> list[dict] | None:
        with self._lock:
            if seq == self._seq:
                return []
            if not self._buf or seq < self._buf[0]["seq"] - 1 or seq > self._seq:
                return None
            return [e for e in self._buf if e["seq"] > seq]

    def subscribe(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._subscribers:
                    self._subscribers.remove(fn)
        return unsubscribe

    def subscribe_async(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> Callable[[], None]:
        def push(ev: dict) -> None:
            try:
                loop.call_soon_threadsafe(_put_nowait, queue, ev)
            except RuntimeError:
                pass  # loop closed
        return self.subscribe(push)


def _put_nowait(q: asyncio.Queue, ev: dict) -> None:
    try:
        q.put_nowait(ev)
    except asyncio.QueueFull:
        # Slow client: mark overflow; the WS handler forces a full resync.
        try:
            q.put_nowait({"type": "__overflow__"})
        except asyncio.QueueFull:
            pass


class AppLog:
    """Bot log: persisted to app_events and published as `log` events. Never logs secrets."""

    def __init__(self, db, bus: EventBus):
        self.db = db
        self.bus = bus
        self.py = logging.getLogger("masterquo")

    def write(self, level: str, category: str, code: str, message: str, data: dict | None = None) -> None:
        from .db.database import dumps
        ts = iso(utcnow())
        try:
            self.db.execute("INSERT INTO app_events(ts, level, category, code, message, data_json) VALUES (?,?,?,?,?,?)",
                            (ts, level, category, code, message, dumps(data) if data else None))
        except Exception:
            self.py.exception("cannot persist app event")
        getattr(self.py, level.lower() if level.lower() in ("info", "warning", "error", "debug") else "info")(
            "%s %s %s", category, code, message)
        self.bus.publish("log", {"ts": ts, "level": level, "category": category, "code": code, "message": message})

    def info(self, category: str, code: str, message: str, data: dict | None = None) -> None:
        self.write("INFO", category, code, message, data)

    def warn(self, category: str, code: str, message: str, data: dict | None = None) -> None:
        self.write("WARNING", category, code, message, data)

    def error(self, category: str, code: str, message: str, data: dict | None = None) -> None:
        self.write("ERROR", category, code, message, data)
