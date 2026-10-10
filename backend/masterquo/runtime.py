"""Wires all components into one supervised application process."""
from __future__ import annotations

import logging
import os
import sys
import threading

from . import paths
from .agent.service import ClaudeAgent
from .config import ConfigStore
from .data.pcclock import PCClockCheck
from .db.database import Database
from .engine.legacy import Profiles
from .engine.service import EngineService
from .events import AppLog, EventBus
from .execution.gateway import ExecutionGateway
from .execution.manager import PositionManager
from .execution.modes import ModeManager
from .execution.paper import PaperBroker
from .markets.scanner import MarketScanner
from .markets.signals import BotSignalService
from .ml.service import MLService
from .mt5.bridge import MarketBridge
from .mt5.worker import MT5Worker
from .news.service import NewsService
from .notify.telegram import TelegramNotifier
from .secrets_store import SecretStore

log = logging.getLogger("masterquo.runtime")


def real_mt5_factory():
    import MetaTrader5  # noqa: F401  (Windows only; raises ImportError elsewhere)
    return MetaTrader5


class Runtime:
    def __init__(self, *, demo: bool = False, mt5_factory=None):
        self.demo = demo
        self.cfg = ConfigStore()
        if demo:
            self.cfg.set_runtime_flag(synthetic_demo=True)
        self.secrets = SecretStore()
        self.db = Database()
        self.bus = EventBus()
        self.log = AppLog(self.db, self.bus)
        if mt5_factory is None:
            if demo:
                from .mt5.fake import FakeMT5
                symbol = self.cfg.get().mt5.symbol
                mt5_factory = lambda: FakeMT5(symbol=symbol, seed=3)  # noqa: E731
            else:
                mt5_factory = real_mt5_factory
        self.worker = MT5Worker(mt5_factory)
        required = Profiles().required_closed_bars()
        self.bridge = MarketBridge(self.cfg, self.worker, self.db, self.bus, self.log, required_bars=required)
        c = self.cfg.get().clock
        self.pcclock = PCClockCheck(c.reference_url, c.max_pc_clock_skew_seconds)
        self.modes = ModeManager(self.cfg, self.db, self.bus, self.log,
                                 account_provider=lambda: (self.bridge.account_status(), self.bridge.account_key, self.bridge.synthetic))
        self.news = NewsService(self.cfg, self.secrets, self.bus, self.log)
        self.engine = EngineService(self.cfg, self.bridge, self.db, self.bus, self.log, self.modes, self.news, self.pcclock)
        self.paper = PaperBroker(self.cfg, self.bridge, self.db, self.bus, self.log)
        self.gateway = ExecutionGateway(self.cfg, self.bridge, self.db, self.bus, self.log, self.modes, self.engine, self.paper)
        self.manager = PositionManager(self.cfg, self.bridge, self.db, self.bus, self.log, self.modes, self.paper)
        self.gateway.manager = self.manager
        self.engine.gateway = self.gateway
        self.agent = ClaudeAgent(self.cfg, self.secrets, self.db, self.bus, self.log, self.engine.context)
        self.engine.agent = self.agent
        self.ml = MLService(self.cfg, self.db, self.bridge, self.bus, self.log)
        self.engine.ml = self.ml
        self.engine.active.ml = self.ml
        self.telegram = TelegramNotifier(self.cfg, self.secrets, self.db)
        self.scanner = MarketScanner(self.cfg, self.bridge, self.bus, self.log)
        self.signals = BotSignalService(self.cfg, self.bridge, self.db, self.bus, self.log, telegram=self.telegram)
        self.scanner.signals = self.signals
        self.engine.active.listeners.append(self.signals.on_main_events)
        self.bus.subscribe(self._on_event)
        self._stop = threading.Event()
        self.security = None
        self.shutdown_hook = None  # set by the server launcher

    def request_shutdown(self) -> None:
        if self.shutdown_hook:
            self.shutdown_hook()

    def _on_event(self, ev: dict) -> None:
        if ev["type"] == "decision":
            d = ev["data"]
            s = d.get("setup") or {}
            if s and d.get("signal_stage") in ("EARLY", "CONFIRMED") and s.get("state") in ("EARLY_SETUP", "CONFIRMED"):
                self.telegram.notify(f"{s['setup_id']}:{s['state']}",
                                     f"MasterQUO AI {'[DANE SYNTETYCZNE] ' if d.get('synthetic') else ''}{d['symbol']} {s['direction']} "
                                     f"{s['strategy_id']} etap {s['state']} | decyzja {d['decision']} | wykonanie {d['execution_permission']}")

    def start(self) -> None:
        self.log.info("APP", "START", f"MasterQUO AI start ({'DANE SYNTETYCZNE' if self.demo else 'MT5'}), tryb wykonania {self.modes.mode}")
        self.worker.start()
        self.bridge.start()
        self.news.start()
        self.engine.start()
        self.manager.start()
        self.ml.start()
        self.scanner.start()
        threading.Thread(target=self._clock_loop, name="pc-clock", daemon=True).start()
        threading.Thread(target=self._signal_track_loop, name="signal-track", daemon=True).start()

    def _clock_loop(self) -> None:
        while not self._stop.is_set():
            self.pcclock.check()
            self._stop.wait(1800)

    def _signal_track_loop(self) -> None:
        while not self._stop.wait(60):
            try:
                self.signals.track()
            except Exception:
                log.exception("bot signal tracking failed")

    def attach_loop(self, loop) -> None:
        self.agent.attach(loop)

    def stop(self) -> None:
        self._stop.set()
        self.log.info("APP", "STOP", "Zatrzymywanie MasterQUO AI (pozycje w terminalu pozostają pod ochroną SL/TP po stronie serwera brokera).")
        self.ml.stop()
        self.scanner.stop()
        self.engine.stop()
        self.manager.stop()
        self.news.stop()
        self.bridge.stop()
        self.worker.stop()


def platform_info() -> dict:
    import platform
    return {"python": sys.version.split()[0], "implementation": platform.python_implementation(),
            "arch": platform.machine(), "bits": 64 if sys.maxsize > 2**32 else 32, "os": platform.platform(),
            "data_dir": str(paths.data_dir()), "pid": os.getpid()}
