"""Wires all components into one supervised application process."""
from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import timedelta

from . import paths
from .agent.service import ClaudeAgent
from .config import ConfigStore
from .data.pcclock import PCClockCheck
from .db.database import Database
from .engine.legacy import Profiles
from .engine.service import EngineService
from .events import AppLog, EventBus
from .prefs import AccountPrefs
from .execution.gateway import ExecutionGateway
from .execution.manager import PositionManager
from .execution.modes import ModeManager
from .execution.paper import PaperBroker
from .markets.scanner import MarketScanner
from .markets.signals import BotSignalService
from .mt5.bridge import MarketBridge
from .mt5.worker import MT5Worker
from .news.service import NewsService
from .notify.telegram import TelegramNotifier
from .timeutil import iso, utcnow
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
                gold = self.cfg.get().assets.mappings["XAUUSD"].broker_symbol or "XAUUSD-"   # synthetic terminal: gold main + BTCUSD- market
                mt5_factory = lambda: FakeMT5(symbol=gold, seed=3)  # noqa: E731
            else:
                mt5_factory = real_mt5_factory
        self.worker = MT5Worker(mt5_factory)
        required = Profiles().required_closed_bars()
        self.bridge = MarketBridge(self.cfg, self.worker, self.db, self.bus, self.log, required_bars=required)
        self.bridge.secrets = self.secrets
        from .assets.registry import AssetRegistry
        self.assets = AssetRegistry(self.cfg, self.bridge, self.log)      # two-asset allowlist (XAUUSD, BTC)
        self.bridge.assets = self.assets
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
        from .ml.router import MLRouter
        self.ml = MLRouter(self.cfg, self.db, self.bridge, self.bus, self.log)      # legacy ML: own database per instrument
        self.engine.ml = self.ml
        self.engine.active.ml = self.ml
        self.telegram = TelegramNotifier(self.cfg, self.secrets, self.db, stats_fn=self._telegram_day_stats)
        self.scanner = MarketScanner(self.cfg, self.bridge, self.bus, self.log)
        self.signals = BotSignalService(self.cfg, self.bridge, self.db, self.bus, self.log, telegram=self.telegram)
        self.scanner.signals = self.signals
        self.engine.active.listeners.append(self.signals.on_main_events)
        self.prefs = AccountPrefs(self.db, self.bridge, self.cfg)          # per account (server:login): setup view + leverage limit
        self.engine.prefs = self.prefs
        self.engine.active.prefs = self.prefs
        from .engine.walls_service import WallsService
        self.walls = WallsService(self.cfg, self.db, self.bridge)           # frozen session walls snapshot -> strategies (S12)
        from .forecast.service import ForecastService
        self.forecast = ForecastService(self.cfg, self.bridge, self.db, self.bus, self.log)   # SHADOW only, isolated worker process
        from .analytics.service import AnalyticsService
        self.analytics = AnalyticsService(self.cfg, self.bridge, self.db, self.bus, self.log)   # observational: BB/MA, FFT/EMD/VMD, Double Bottom
        from .lab.service import LabService
        self.lab = LabService(self.cfg, self.bridge, self.db, self.bus, self.log, self.assets)      # 1.14 lab: two assets, SHADOW
        from .extind.service import ExtIndService
        self.extind = ExtIndService(self.cfg, self.db, self.bridge, self.bus, self.log)       # PMW-UPD-02: read-only IQ/PAL ingest + archive
        from .scalp.service import ScalpService
        self.scalp = ScalpService(self.cfg, self.bridge, self.db, self.bus, self.log, news=self.news, forecast=self.forecast)   # SHADOW only
        from .lab.nss_service import NeuralScalpService
        self.nss = NeuralScalpService(self.db, self.bus, self.log, instrument=self.cfg.get().assets.active)   # PMW-UPD-04: own M1 clock, OBSERVE
        self.scalp.nss = self.nss
        from .mm.service import MMService
        self.mm = MMService(self)                                                   # PMW-MM: master models, SHADOW / OBSERVE (no order path)
        self.engine.mm_provider = lambda: self.mm.live(self.cfg.get().assets.active)    # read-only view for the agent tool get_master_models
        from .scalp.dashboard import MTFDashboard
        self.mtf = MTFDashboard(self.scalp, self.bridge, self.bus, self.db)      # PMW-UPD-05: MTFContextSnapshot + 1 s freshness heartbeat
        self.scalp.dashboard = self.mtf
        from .lab.si_service import StructureIntelligenceService
        self.si = StructureIntelligenceService(self.cfg, self.bridge, self.db, self.bus, self.log, lab=self.lab)   # PMW-UPD-07 (SHADOW/OBSERVE)
        self.mtf.si = self.si
        self.engine.si = self.si
        from .execution.manual import ManualPad
        self.manual = ManualPad(self.cfg, self.bridge, self.db, self.bus, self.log, self.modes, self.paper, self.gateway)   # PMW-UPD-07 R12
        from .analytics.liquidation.service import LiquidityService
        self.liquidity = LiquidityService(self.cfg, self.db, self.bus, self.log, secrets=self.secrets, bridge=self.bridge)   # PMW-UPD-06 (OBSERVE)
        self.engine.liquidity = self.liquidity
        self.scalp.liquidity = self.liquidity
        from .sh.service import SHService
        self.sh = SHService(self.cfg, self.bridge, self.db, self.bus, self.log, self.modes)     # PMW-SH-1 SCALPING / HEDGING
        from .evaluation.service import EvaluationService
        self.evaluation = EvaluationService(self.cfg, self.bridge, self.db, ml=self.ml)          # SHADOW: P/EV ledger of every setup, both paths
        self.engine.active.listeners.append(self.evaluation.on_active_events)
        self.sh.listeners.append(self.evaluation.on_sh_cycle)
        self.scalp.listeners.append(self.evaluation.on_scalp_setup)                               # O6: third SHADOW source
        from .zones.service import ZoneService
        self.zones = ZoneService(self.cfg, self.bridge, bus=self.bus, log=self.log)                # PMW-ZONES: one zone map (analytical)
        self.evaluation.zone_provider = self.zones
        self.evaluation.regime_sources = {"ACTIVE": lambda: getattr(getattr(self.engine.active, "view", None), "regime", None),
                                          "SH": lambda: (self.sh.snapshot or {}).get("regime")}             # O4: both definitions
        self.scalp.extind = self.extind
        self.scalp.ml = self.ml
        self.engine.extind = self.extind
        self.engine.active.context_fn = self.walls.context
        self.prefs.listeners.append(lambda name, v: (self.engine.mark_dirty(), self._publish_prefs()))
        # another account (server:login) = its own preferences; broker parameters are re-read by the bridge
        self.bridge.add_listener(lambda kind, data: self._publish_prefs() if kind in ("account_changed", "connected") else None)
        self.bus.subscribe(self._on_event)
        self._stop = threading.Event()
        self.security = None
        self.shutdown_hook = None  # set by the server launcher

    def _publish_prefs(self) -> None:
        try:
            self.bus.publish("prefs", {**self.prefs.all(), "exposure": self.prefs.exposure_limit()})
        except Exception:
            log.exception("prefs publish failed")

    def request_shutdown(self) -> None:
        if self.shutdown_hook:
            self.shutdown_hook()

    def _on_event(self, ev: dict) -> None:
        if ev["type"] == "agent_result":
            r = ev.get("data") or {}
            rec = r.get("record") or {}
            if r.get("status") == "OK" and r.get("setup_id") and rec.get("proposed_action"):
                row = self.engine.active.tracker.get(r["setup_id"])          # direction of exactly the assessed setup
                if row:
                    want = "BUY" if row["record"]["direction"] == "LONG" else "SELL"
                    self.signals.set_ai_verdict(r["setup_id"], "ZGODA" if rec["proposed_action"] == want else "BRAK_ZGODY")
        if ev["type"] == "decision":
            d = ev["data"]
            s = d.get("setup") or {}
            if s and d.get("signal_stage") in ("EARLY", "CONFIRMED") and s.get("state") in ("EARLY_SETUP", "CONFIRMED"):
                risk = d.get("risk") or {}
                self.telegram.signal(f"{s['setup_id']}:{s['state']}", {
                    "symbol": d.get("symbol"), "side": s.get("direction"), "strategy": f"{s.get('strategy_id')} {s.get('strategy_name') or ''}".strip(),
                    "timeframe": s.get("setup_tf"), "stage": d.get("signal_stage"), "entry": risk.get("entry"), "sl": risk.get("stop_loss"),
                    "tps": [t.get("price") for t in (risk.get("targets") or [])], "synthetic": d.get("synthetic")})
        try:
            self._telegram_trades(ev)
        except Exception:
            logging.getLogger("masterquo.telegram").exception("trade notification failed")

    def _telegram_trades(self, ev: dict) -> None:
        """Opened / closed positions of the bot -> Telegram (only when send_trades is on; deduplicated per order / position)."""
        t, d = ev["type"], ev.get("data")
        if t == "orders":
            fresh = iso(utcnow() - timedelta(minutes=10))          # enabling notifications later must not replay old fills
            for a in d or []:
                if a.get("state") in ("FILLED", "PARTIAL") and a.get("attempt_id") and str(a.get("updated_at") or a.get("created_at") or "") >= fresh:
                    self.telegram.trade_opened(a["attempt_id"], {"mode": a.get("mode"), "symbol": a.get("symbol"), "side": a.get("side"),
                                                                 "volume": a.get("filled_volume") or a.get("volume"), "price": a.get("fill_price"),
                                                                 "sl": a.get("sl"), "tp": a.get("tp"), "strategy": a.get("initiated_by")})
        elif t == "trade_settled" and d:
            row = self.db.one("SELECT * FROM trades WHERE position_ticket=? AND status IN ('CLOSED','UNSETTLED') ORDER BY closed_at DESC LIMIT 1",
                              (d.get("position"),))
            if row:
                self.telegram.trade_closed(str(row["trade_id"]), {"mode": row["mode"], "symbol": row["symbol"], "side": row["side"],
                                                                  "volume": row["volume"], "net": row["net_pnl"], "currency": row["currency"],
                                                                  "r_multiple": row["r_multiple"], "strategy": row["strategy_id"]})
        elif t == "trade_opened" and d:
            self.telegram.trade_opened(str(d.get("key")), d)
        elif t == "trade_closed" and d:
            self.telegram.trade_closed(str(d.get("key")), d)

    def _telegram_day_stats(self):
        from . import stats as _stats
        mode = self.modes.mode if self.modes.mode in ("AUTO_DEMO", "AUTO_LIVE") else "PAPER"
        st = _stats.bot_stats(self.db, mode, self.bridge.account_key)
        return mode, st.get("day") or {}, (self.bridge.account_status() or {}).get("currency")

    def start(self) -> None:
        self.log.info("APP", "START", f"MasterQUO AI start ({'DANE SYNTETYCZNE' if self.demo else 'MT5'}), tryb wykonania {self.modes.mode}")
        self.worker.start()
        self.bridge.start()
        self.news.start()
        self.engine.start()
        self.manager.start()
        self.telegram.start()
        self.ml.start()
        self.scanner.start()
        self.forecast.start()
        self.scalp.start()
        self.analytics.start()
        self.lab.start()
        self.extind.start()
        self.nss.start()
        self.mtf.start()
        self.si.start()                         # PMW-UPD-08 quote collector (same bridge/worker, own thread)
        self.liquidity.start()
        self.sh.start()
        self.mm.start()                         # AR-08: master models on every closed M5 (SHADOW)
        self.zones.start()                      # PMW-ZONES: zone map on every closed M5
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
        self.telegram.stop()
        self._stop.set()
        self.log.info("APP", "STOP", "Zatrzymywanie MasterQUO AI (pozycje w terminalu pozostają pod ochroną SL/TP po stronie serwera brokera).")
        self.ml.stop()
        self.forecast.stop()
        self.scalp.stop()
        self.sh.stop()
        self.mm.stop()
        self.zones.stop()
        self.analytics.stop()
        self.lab.stop()
        self.extind.stop()
        self.nss.stop()
        self.mtf.stop()
        self.si.stop()
        self.liquidity.stop()
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
