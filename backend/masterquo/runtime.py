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
from .version import DISPLAY_NAME

log = logging.getLogger("masterquo.runtime")


def real_mt5_factory():
    import MetaTrader5  # noqa: F401  (Windows only; raises ImportError elsewhere)
    return MetaTrader5


class Runtime:
    def __init__(self, *, demo: bool = False, mt5_factory=None):
        self.demo = demo
        if not demo:
            try:                                            # 1.41: inventory "before" + configuration snapshot, once, before any 1.41 service
                from .upgrade import migrate as _UM
                _UM.before()
            except Exception:  # noqa: BLE001 - never blocks the start; the after-report shows the missing step
                log.exception("upgrade 1.41 before-step failed")
            try:                                            # 1.46 arch (I0120): copy of every settings file once per app version
                from .upgrade import migrate as _UM
                _UM.snapshot_before()
            except Exception:                               # a copy never blocks the start
                log.exception("settings snapshot before the update failed")
        try:                                                # 1.42.2: program folder moved -> model venvs re-pointed to this Python
            import mq_venv
            base = getattr(sys, "_base_executable", None) or sys.executable
            fixed = mq_venv.repair_all(paths.ROOT_DIR, base, lambda m: log.warning("venv: %s", m))
            bad = {k: v for k, v in fixed.items() if v["state"] not in ("OK", "MISSING")}
            if bad:
                log.warning("model environments after repair: %s", bad)
        except Exception:  # noqa: BLE001 - never blocks the start; the installers repair too
            log.exception("venv repair failed")
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
        from .sh.pack.engine import NEEDED_BARS as _PACK_BARS                 # 1.38 pack: H1 EMA200 x5 warm-up, previous-session profile, M3
        for _tf, _n in _PACK_BARS.items():
            required[_tf] = max(int(required.get(_tf) or 0), _n)
        self.bridge = MarketBridge(self.cfg, self.worker, self.db, self.bus, self.log, required_bars=required)
        self.bridge.secrets = self.secrets
        from .assets.registry import AssetRegistry
        self.assets = AssetRegistry(self.cfg, self.bridge, self.log)      # two-asset allowlist (XAUUSD, BTC)
        self.bridge.assets = self.assets
        c = self.cfg.get().clock
        self.pcclock = PCClockCheck(c.reference_url, c.max_pc_clock_skew_seconds)
        self.modes = ModeManager(self.cfg, self.db, self.bus, self.log,
                                 account_provider=lambda: (self.bridge.account_status(), self.bridge.account_key, self.bridge.synthetic))
        if not demo and mt5_factory is None:                                # 1.39: real terminal only - start in execution.start_mode (AUTO_LIVE)
            self.modes.apply_start_mode()
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
        self.telegram = TelegramNotifier(self.cfg, self.secrets, self.db, stats_fn=self._telegram_day_stats,
                                         template_path=paths.data_dir() / "telegram" / "signal_template.json")
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
        from .sh.pack.engine import PackEngine
        self.sh.pack = PackEngine()                                                               # 1.38: 20 variants in the SAME SH cycle
        from .evaluation.service import EvaluationService
        self.evaluation = EvaluationService(self.cfg, self.bridge, self.db, ml=self.ml)          # SHADOW: P/EV ledger of every setup, both paths
        self.engine.active.listeners.append(self.evaluation.on_active_events)
        self.sh.listeners.append(self.evaluation.on_sh_cycle)
        self.scalp.listeners.append(self.evaluation.on_scalp_setup)                               # O6: third SHADOW source
        # 1.27: every strategy publishes its BUY / SELL setups as bot signals (information - orders keep their own paths)
        self.sh.listeners.append(self.signals.on_sh_cycle)
        self.scalp.listeners.append(self.signals.on_scalp_setup)
        self.forecast.listeners.append(lambda setup_v2, symbol: self.signals.on_double_retest(setup_v2, symbol=symbol))
        from .zones.service import ZoneService
        self.zones = ZoneService(self.cfg, self.bridge, bus=self.bus, log=self.log)                # PMW-ZONES: one zone map (analytical)
        from .indicators.service import IndicatorService
        self.indicators = IndicatorService(self.cfg, self.bridge, zones=self.zones, bus=self.bus, log=self.log)   # PMW-IND-1 (1.33)
        self.sh.indicators = self.indicators                                                        # SCALPING / HEDGING: context (OBSERVE)
        self.engine.indicators_provider = self.indicators                                           # agent: frozen PMW-IND-1 snapshot
        from .svp.service import SVPService
        self.svp = SVPService(self.cfg, self.bridge, agent=self.agent, bus=self.bus)               # PMW-SVP-1 profiles + MANUAL/ALGORITHM/AI zones
        self.engine.svp_provider = self.svp                                                         # agent: frozen SVP profiles + zones
        from .modelhub.families.service import FamilyService
        self.families = FamilyService(self.cfg, self.bridge, indicators=self.indicators, news=self.news)   # PMW-FAM-1: 15 model families
        self.sh.families = self.families                                                            # SH receiver: context + ASSIST hold
        from .decision.coordinator import DecisionCoordinator
        self.arc = DecisionCoordinator(self.db, self.cfg, families=self.families, instrument_fn=self.sh.instrument)   # PMW-ARC-1
        self.engine.arc = self.gateway.arc = self.sh.arc = self.manager.arc = self.arc                  # one coordinator + ledger for both paths
        from .zones.market_service import MarketZonesService
        self.market_zones = MarketZonesService(self.cfg, self.bridge, bus=self.bus, log=self.log)  # 1.28: "Strefy rynkowe" M1/M5/M15/M30
        from .kronos.service import KronosService
        self.kronos = KronosService(self.cfg, self.bridge, self.db, self.bus, self.log)   # Kronos-small (1.42.8; Kronos-base 1.37-1.42.7), own .venv_kronos process
        from .trainhub.inference import TrainhubInference
        from .trainhub.jobs import TrainingCenter
        self.trainhub = TrainingCenter(self.cfg, self.bridge, bus=self.bus, log=self.log)         # 1.28: Centrum treningu (kolejka, proces obok)
        self.trainhub_inference = TrainhubInference(self.cfg, self.bridge, bus=self.bus, log=self.log)   # aktywne paczki, zamknięte świece
        from .montecarlo.service import MonteCarloService
        self.montecarlo = MonteCarloService(self.cfg, self.bridge, synthetic=demo)                 # PMW-MC-1: path simulation, own thread
        from .quant.service import QuantService
        self.quant = QuantService(self)                                                             # 1.35 PMW Quant Core: own thread, SHADOW by default
        self.evaluation.listeners.append(self.quant.on_candidate)                                  # decision-time features + SHADOW assessment
        self.families.event_gru_provider = lambda inst: self.quant.event_gru.latest.get(inst)      # Event GRU: live path owned by Quant
        self.families.event_gru_live = lambda: self.quant.mode() != "OFF"                          # 1.46 arch (I0477): status only (read)
        self.arc.quant = self.quant                                                                 # ASSIST only after validation + explicit activation
        self.sh.kronos = self.kronos                                                                # Kronos context in SCALPING / HEDGING
        from .tsfm.service import TsfmService
        self.tsfm = TsfmService(self.cfg, self.bridge, self.db, self.bus, self.log)     # Chronos-2 + Granite TTM (1.40, FinCast retired): own processes, OBSERVE default
        self.tsfm.kronos = self.kronos                                                              # three-model comparison (read only)
        try:                                                                                        # 1.41 six MQL5-derived research modules (autostart)
            from .research.service import ResearchModulesService
            self.research = ResearchModulesService(self)
        except Exception:  # noqa: BLE001 - a broken research state never stops the engine
            log.exception("research modules unavailable")
            self.research = None
        from .training.pepe_center import PepeTrainingCenter                                        # 1.42.10 Centrum Treningowe Pepe (kolejka 1 naraz)
        self.pepe_training = PepeTrainingCenter(self)
        try:                                                                                        # 1.41 three market profiles, 9 baskets / 90 strategies
            from .baskets.service import BasketService
            self.baskets = BasketService(self)
            self.sh.baskets = self.baskets                                                          # 1.42: FX basket plans -> SH execution path
        except Exception:  # noqa: BLE001
            log.exception("baskets unavailable")
            self.baskets = None
        try:
            self._wire_governor()
        except Exception:  # noqa: BLE001 - 1.40.1: no governor = models run unmanaged (as in 1.39), the engine still starts
            log.exception("memory governor unavailable")
            self.governor = None
            self.tsfm.governor = self.kronos.governor = None
        self.sh.tsfm = self.tsfm                                                                    # SH receivers (roles per strategy)
        from .tsfm import predictions as _tsfm_pred
        self.arc.extra_providers = [lambda inst: _tsfm_pred.coordinator_rows(self.tsfm, inst),       # ACTIVE: roles of Chronos-2 / Granite TTM
                                    lambda inst: _tsfm_pred.kronos_rows(self.kronos, inst)]          # Kronos: recorded as OBSERVE only
        from .modelhub import adapters as _model_adapters
        self.sh.predictions_provider = lambda inst: _model_adapters.all_predictions(self, inst)       # other models, for agreement / conflict only
        self.evaluation.zone_provider = self.zones
        self.evaluation.regime_sources = {"ACTIVE": lambda: getattr(getattr(self.engine.active, "view", None), "regime", None),
                                          "SH": lambda: (self.sh.snapshot or {}).get("regime")}             # O4: both definitions
        self.scalp.extind = self.extind
        self.scalp.ml = self.ml
        self.engine.extind = self.extind
        self.engine.active.context_fn = lambda view, bars: {**self.walls.context(view, bars), **self.indicators.context(view, bars)}
        self.prefs.listeners.append(lambda name, v: (self.engine.mark_dirty(), self._publish_prefs()))
        # another account (server:login) = its own preferences; broker parameters are re-read by the bridge
        self.bridge.add_listener(lambda kind, data: self._publish_prefs() if kind in ("account_changed", "connected") else None)
        self.bus.subscribe(self._on_event)
        self._stop = threading.Event()
        # 1.44.0: centralna kontrola licencji (wersja klienta). Wersja właściciela: licencja niepotrzebna (gate.required = False).
        from .licensing.gate import LicenseGate
        self.license = LicenseGate(log=self.log)
        self.modes.license_ok = self.license.ok
        self.start_failures: list[dict] = []
        self._engine_started = False
        self._engine_lock = threading.Lock()
        self.security = None
        self.shutdown_hook = None  # set by the server launcher
        # 1.46 arch (I0088): services of the workflow v3.2 routes (ledgers, journal, game, Hyperliquid / Universe, Telegram account center)
        # are owned here, not by the HTTP layer; rt.wf32 is the dict the routes publish as app.state.wf32 and the exporters read
        from .wf32_services import Wf32Services
        self.wf32_services = Wf32Services(self)
        self.wf32 = self.wf32_services.public
        # 1.46 arch (I0092): ONE Bootstrap, built here (reads its state file only - no thread, no installer); started in start()
        self.bootstrap = None
        try:
            from .bootstrap import Bootstrap
            self.bootstrap = Bootstrap(self)
        except Exception:                                   # never blocks the construction
            log.exception("bootstrap construction failed")

    def _wire_governor(self) -> None:
        """1.40 Memory Governor: one resource manager for every model process (Kronos, Chronos-2, Granite TTM) + training jobs."""
        import os as _os

        from .resources.governor import Governor
        self.governor = Governor(self.cfg, self.log)
        self.tsfm.governor = self.governor
        self.kronos.governor = self.governor
        self.governor.register("bot", "bot", lambda: _os.getpid())
        # 1.46 arch (I0089/I0102): every model service registers its own worker(s) (same pid / release / idle callables and the same
        # 'never release while it computes' guards as the former lambdas here) - this composition root no longer knows their internals
        self.kronos.register_with(self.governor)
        self.quant.tabicl.governor = self.governor                     # 1.41 TabICLv2 worker (heavy slot, idle release)
        self.quant.tabicl.register_with(self.governor)
        if getattr(self, "research", None) is not None:
            self.research.governor = self.governor                     # 1.41 SDformerFlow training / inference (heavy slot)
        self.tsfm.register_with(self.governor)

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
        """1.44.0: wersja klienta bez ważnej licencji – silnik (MT5, strategie, tryby, modele) NIE startuje; działa tylko serwer z ekranem
        aktywacji. Po aktywacji (gate.on_unlock) silnik startuje raz, tak jak przy zwykłym starcie."""
        st = self.license.evaluate(refresh_net=True)
        self.license.start_monitor(self._stop)
        if self.license.locked:
            self.log.warn("LICENSE", "LOCKED_AT_START", f"Brak ważnej licencji ({st.get('code')}) – silnik czeka na aktywację klucza.")
            self.license.on_unlock.append(lambda: threading.Thread(target=self._start_engine, name="engine-start-after-license",
                                                                   daemon=True).start())
            return
        self._start_engine()

    def _start_engine(self) -> None:
        with self._engine_lock:
            if self._engine_started:
                return
            self._engine_started = True
        self._start_engine_parts()

    def _start_engine_parts(self) -> None:
        """1.40.1: every subsystem starts on its own - one failing part (MT5 terminal, a model worker, a broken settings file, a Windows
        API call) never takes the whole engine down; the failure is logged with its traceback and listed in start_failures (API health)."""
        self.log.info("APP", "START", f"{DISPLAY_NAME} start ({'DANE SYNTETYCZNE' if self.demo else 'MT5'}), tryb wykonania {self.modes.mode}")   # 1.46: brand
        self.start_failures: list[dict] = []
        for name in ("worker", "bridge", "news", "engine", "manager", "telegram", "ml", "scanner", "forecast", "scalp", "analytics", "lab",
                     "extind", "nss", "mtf", "si", "liquidity", "sh", "mm", "zones", "indicators", "svp"):
            self._start_part(name)
        try:                                    # Studio packages handed over while the bot was off (candidates, inactive)
            from .studio import importer as _IM
            self.studio_imports = _IM.process_inbox()
        except Exception as exc:  # noqa: BLE001
            self.studio_imports = [{"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}]
        # market_zones/trainhub: job workers; kronos/tsfm: forecasts after new closed bars (nothing until installed);
        # governor: 1.40 Memory Governor (measurement every 15 s); quant: 1.35 Quant Core
        try:                                                # 1.42 (DIRECT_USER_REQUEST): models OBSERVE -> ASSIST, FX baskets -> SH path, once
            from .upgrade import migrate as _UM
            _UM.apply_142(self)
        except Exception:  # noqa: BLE001 - never blocks the start
            log.exception("upgrade 1.42 step failed")
        # families: 1.46 arch (I0790) background inference of the .venv_deep families after a bar close (the SH cycle reads the cache)
        for name in ("market_zones", "trainhub", "trainhub_inference", "kronos", "tsfm", "governor", "quant", "research", "baskets", "families"):
            self._start_part(name)
        threading.Thread(target=self._clock_loop, name="pc-clock", daemon=True).start()
        threading.Thread(target=self._signal_track_loop, name="signal-track", daemon=True).start()
        if not self.demo:
            threading.Thread(target=self._upgrade_after, name="upgrade-1.41", daemon=True).start()
        try:                                                # 1.45 (TASK 013): verify-first bootstrap; heavy runtimes sequential, after start
            if self.bootstrap is None:                     # 1.46 arch (I0092): normally built in __init__
                from .bootstrap import Bootstrap
                self.bootstrap = Bootstrap(self)
            self.bootstrap.start()                         # no-op in demo / PMW_BOOTSTRAP=0
        except Exception:  # noqa: BLE001 - never blocks the start
            log.exception("bootstrap failed to start")
        self._start_account_loop()
        if self.start_failures:
            self.log.error("APP", "START_DEGRADED", "Nie wystartowały: " + ", ".join(f["part"] for f in self.start_failures)
                           + " – reszta aplikacji działa, szczegóły w logs/engine_console.log")

    def _start_account_loop(self) -> None:
        """1.46 arch (I0092): the Telegram account loop (read the account / deals, queue and send reports - never an order) starts here,
        i.e. after the licence unlock, ONCE, only with the real MT5 terminal (never in the synthetic demo / `models check --live`); it ends
        with self._stop (Runtime.stop). Before 1.46 the route registration started it, before start() and regardless of the licence."""
        if self.demo:
            return
        try:
            self.wf32_services.start_account_loop(self._stop)
        except Exception as exc:                            # never blocks the start of the other parts
            log.exception("start of telegram_account failed")
            self.start_failures.append({"part": "telegram_account", "error": f"{type(exc).__name__}: {exc}"[:300]})

    def _upgrade_after(self) -> None:
        """1.41: after-inventory + preservation report (60 s after start, when every registry is loaded) and the background installation
        of TiRex-2 / TabICLv2 when they are missing (DIRECT_USER_REQUEST - the bot keeps working)."""
        self._stop.wait(60)
        if self._stop.is_set():
            return
        try:
            from .upgrade import migrate as _UM
            _UM.after(self)
            _UM.auto_install(self)
        except Exception:  # noqa: BLE001
            log.exception("upgrade 1.41 after-step failed")

    def _start_part(self, name: str) -> None:
        part = getattr(self, name, None)
        if part is None:
            return
        try:
            part.start()
        except Exception as exc:  # noqa: BLE001 - see start()
            log.exception("start of %s failed", name)
            self.start_failures.append({"part": name, "error": f"{type(exc).__name__}: {exc}"[:300]})

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

    # 1.46: stop order (unchanged); every part stops on its own - an exception in one .stop() skipped all later parts (bridge, MT5
    # worker) and the cleanup of shutdown.token / server.pid in __main__
    _STOP_ORDER = ("ml", "forecast", "scalp", "sh", "mm", "zones", "indicators", "svp", "market_zones", "trainhub", "trainhub_inference",
                   "kronos", "tsfm", "montecarlo", "quant", "research", "baskets", "families", "analytics", "lab", "extind", "nss", "mtf", "si",
                   "liquidity", "scanner", "engine", "manager", "news", "bridge", "worker")

    def _stop_part(self, name: str, method: str = "stop") -> None:
        part = getattr(self, name, None)
        if part is None:
            return
        try:
            getattr(part, method)()
        except Exception:                               # logged, the remaining parts still stop
            log.exception("stop of %s failed", name)

    def stop(self) -> None:
        self._stop_part("bootstrap")                    # 1.46: was never stopped - it could start another installer after the services
        self._stop_part("telegram")
        self._stop.set()
        self._stop_part("governor")
        try:
            self.log.info("APP", "STOP", f"Zatrzymywanie {DISPLAY_NAME} (pozycje w terminalu pozostają pod ochroną SL/TP po stronie serwera brokera).")
        except Exception:
            log.exception("stop log failed")
        for name in self._STOP_ORDER:
            self._stop_part(name, "stop_service" if name == "market_zones" else "stop")


def platform_info() -> dict:
    import platform
    return {"python": sys.version.split()[0], "implementation": platform.python_implementation(),
            "arch": platform.machine(), "bits": 64 if sys.maxsize > 2**32 else 32, "os": platform.platform(),
            "data_dir": str(paths.data_dir()), "pid": os.getpid()}
