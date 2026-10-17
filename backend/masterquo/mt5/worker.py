"""The only thread that touches the MetaTrader5 module.

The official MetaTrader5 Python package keeps one global IPC connection and is not designed for
concurrent calls from several threads. Every terminal call in the application is therefore a job
in a priority queue executed by this single worker thread:

    priority 0 - trading (order_send/order_check, position modifications)
    priority 1 - quotes, account, positions
    priority 2 - bars and history

A job that does not return in time raises MT5CallTimeout for the caller. A wedged terminal
call cannot be interrupted, so the worker is flagged `wedged` and further calls fail fast
until it recovers; the bridge reports TERMINAL_UNRESPONSIVE.
"""
from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable

log = logging.getLogger("masterquo.mt5.worker")

PRIO_TRADE, PRIO_QUOTE, PRIO_HISTORY = 0, 1, 2


class MT5CallTimeout(TimeoutError):
    pass


class MT5WorkerUnavailable(RuntimeError):
    pass


class ExecutionLocked(PermissionError):
    """Execution Lock (1.14): order_send is refused below every application path."""


class _LockedTerminal:
    """Proxy of the MetaTrader5 module handed to jobs while the Execution Lock is LOCKED: reading (quotes, bars,
    order_check, positions) passes through, `order_send` raises. Applies to every caller of the worker."""
    __slots__ = ("_m", "_worker")

    def __init__(self, module, worker):
        object.__setattr__(self, "_m", module)
        object.__setattr__(self, "_worker", worker)

    def order_send(self, *a, **kw):
        self._worker.locked_attempts += 1
        raise ExecutionLocked("EXECUTION_LOCKED")

    def __getattr__(self, name):
        return getattr(self._m, name)


class MT5Worker:
    def __init__(self, module_factory: Callable[[], Any], name: str = "mt5-worker"):
        self._factory = module_factory
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._counter = itertools.count()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._stop = threading.Event()
        self.module: Any = None
        self.module_error: str | None = None
        self._busy_since: float | None = None
        self._lock = threading.Lock()
        self.calls = 0
        self.failures = 0
        self.lock_fn: Callable[[], bool] = lambda: True     # Execution Lock state (runtime binds the config); default LOCKED
        self.locked_attempts = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put((99, next(self._counter), None, None))

    @property
    def wedged_seconds(self) -> float:
        with self._lock:
            return 0.0 if self._busy_since is None else time.monotonic() - self._busy_since

    def _run(self) -> None:
        try:
            self.module = self._factory()
        except Exception as exc:  # ImportError on non-Windows, broken install, ...
            self.module_error = f"{type(exc).__name__}: {exc}"
            log.error("MetaTrader5 module unavailable: %s", self.module_error)
        while not self._stop.is_set():
            _, _, fn, fut = self._q.get()
            if fn is None:
                break
            if fut.set_running_or_notify_cancel() is False:
                continue
            with self._lock:
                self._busy_since = time.monotonic()
            try:
                if self.module is None:
                    raise MT5WorkerUnavailable(self.module_error or "MT5_MODULE_UNAVAILABLE")
                locked = True
                try:
                    locked = bool(self.lock_fn())
                except Exception:          # unreadable lock state = locked
                    locked = True
                fut.set_result(fn(_LockedTerminal(self.module, self) if locked else self.module))
            except BaseException as exc:
                self.failures += 1
                fut.set_exception(exc)
            finally:
                self.calls += 1
                with self._lock:
                    self._busy_since = None

    def submit(self, fn: Callable[[Any], Any], priority: int = PRIO_QUOTE) -> Future:
        fut: Future = Future()
        self._q.put((priority, next(self._counter), fn, fut))
        return fut

    def call(self, fn: Callable[[Any], Any], priority: int = PRIO_QUOTE, timeout: float = 15.0) -> Any:
        if self.wedged_seconds > timeout:
            raise MT5CallTimeout("TERMINAL_UNRESPONSIVE")
        fut = self.submit(fn, priority)
        try:
            return fut.result(timeout=timeout)
        except TimeoutError as exc:
            fut.cancel()
            raise MT5CallTimeout("MT5_CALL_TIMEOUT") from exc
