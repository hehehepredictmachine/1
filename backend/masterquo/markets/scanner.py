"""MarketScanner - periodic analysis of the symbols available in the connected MT5 terminal.

Read-only: it reads symbol lists, quotes and bars through the bridge at the lowest worker priority (the main
symbol's six-timeframe loop keeps precedence) and never sends orders. Source of symbols:
  MARKET_WATCH (default) - the symbols visible in the terminal's Market Watch, no side effects;
  LIST - exact broker names from the configuration (selected into Market Watch if hidden);
  ALL - every symbol of the terminal, capped by max_symbols (hidden ones are added to Market Watch).
"""
from __future__ import annotations

import logging
import threading
import time

from ..timeutil import iso, utcnow
from . import analysis

log = logging.getLogger("masterquo.markets")
COUNTS = {"H1": 400, "H4": 400, "D1": 420}


class MarketScanner:
    def __init__(self, cfg_store, bridge, bus, applog):
        self.cfg_store = cfg_store
        self.bridge = bridge
        self.bus = bus
        self.log = applog
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.results: dict[str, dict] = {}
        self.errors: dict[str, str] = {}
        self.state = "IDLE"
        self.last_scan_at: str | None = None
        self.last_duration_ms: float | None = None
        self.symbols_total: int | None = None
        self.listeners = []          # fn(results) after each scan (AI auto signals)

    @property
    def cfg(self):
        return self.cfg_store.get().markets

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="market-scanner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def scan_now(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        last = 0.0
        while not self._stop.is_set():
            due = time.monotonic() - last >= self.cfg.scan_interval_seconds
            if self._wake.is_set() or due:
                self._wake.clear()
                if self.cfg.enabled and self.bridge.state == "CONNECTED" and self.bridge.clock.offset is None:
                    self.state = "WAITING_FOR_SERVER_CLOCK"      # bar times (UTC) need the server offset; retried every 2 s
                elif self.cfg.enabled and self.bridge.state == "CONNECTED":
                    try:
                        self.scan()
                    except Exception as exc:  # never kill the thread
                        log.exception("market scan failed")
                        self.state = "ERROR:" + type(exc).__name__
                    last = time.monotonic()
                elif not self.cfg.enabled:
                    self.state = "DISABLED"
                else:
                    self.state = "WAITING_FOR_MT5"
            self._wake.wait(2.0)

    # ------------------------------------------------------------ scan
    def universe(self) -> list[str]:
        c = self.cfg
        main = self.cfg_store.get().mt5.symbol
        if c.source == "LIST":
            names = list(c.symbols)
        else:
            syms = self.bridge.list_symbols(visible_only=(c.source == "MARKET_WATCH"))
            self.symbols_total = len(syms)
            names = [s["name"] for s in syms if s.get("trade_mode") != 0]   # skip symbols with trading disabled
        names = [n for n in names if n not in c.exclude and n != main]
        names = names[: max(0, c.max_symbols - (1 if c.include_main else 0))]
        return ([main] if c.include_main else []) + names

    def analyze_symbol(self, name: str) -> dict:
        select = self.cfg.source != "MARKET_WATCH"
        meta = self.bridge.symbol_meta(name, select=select)
        if meta is None:
            raise ValueError("SYMBOL_NOT_AVAILABLE")
        quote = self.bridge.symbol_quote(name, meta.get("point"))
        bars = {tf: self.bridge.symbol_bars(name, tf, n) for tf, n in COUNTS.items()}
        res = analysis.analyze(name, bars, meta, quote, self.cfg_store.get().volatility)
        res["scanned_at"] = iso(utcnow())
        res["synthetic"] = self.bridge.synthetic
        return res

    def scan(self) -> dict:
        t0 = time.monotonic()
        self.state = "SCANNING"
        self.bus.publish("markets", self.summary())
        names = self.universe()
        results, errors = {}, {}
        for n in names:
            if self._stop.is_set():
                break
            try:
                results[n] = self.analyze_symbol(n)
            except Exception as exc:
                errors[n] = f"{type(exc).__name__}: {exc}"[:160]
        with self._lock:
            self.results, self.errors = results, errors
            self.last_scan_at = iso(utcnow())
            self.last_duration_ms = round((time.monotonic() - t0) * 1000, 1)
            self.state = "OK" if results else ("NO_SYMBOLS" if not names else "ERROR")
        self.log.info("MARKETS", "SCAN", f"Skaner rynków: {len(results)} symboli przeanalizowanych, {len(errors)} błędów "
                      f"({self.last_duration_ms:.0f} ms, źródło {self.cfg.source}).")
        self.bus.publish("markets", self.summary())
        for fn in list(self.listeners):
            try:
                fn(results)
            except Exception:
                log.exception("scanner listener failed")
        return self.summary()

    # ------------------------------------------------------------ read API
    def get(self, symbol: str) -> dict | None:
        with self._lock:
            return self.results.get(symbol)

    def summary(self) -> dict:
        with self._lock:
            items = [{k: r.get(k) for k in ("symbol", "description", "status", "price", "change_d1_pct", "change_5d_pct", "regime", "bias",
                                            "score", "observations", "atr_d1_pct", "spread_atr_h1_pct", "sigma_position", "digits", "synthetic",
                                            "scanned_at")}
                     | {"trend": {tf: (r.get("timeframes") or {}).get(tf, {}).get("trend") for tf in analysis.TFS},
                        "rsi_h1": ((r.get("timeframes") or {}).get("H1") or {}).get("rsi14"),
                        "adx_h4": ((r.get("timeframes") or {}).get("H4") or {}).get("adx14"),
                        "hv": (r.get("volatility") or {}).get("hv_annual_pct"),
                        "hv_pct": (r.get("volatility") or {}).get("hv_percentile_1y")}
                     for r in self.results.values()]
            return {"state": self.state, "source": self.cfg.source, "enabled": self.cfg.enabled, "last_scan_at": self.last_scan_at,
                    "duration_ms": self.last_duration_ms, "symbols_total": self.symbols_total, "count": len(items),
                    "items": sorted(items, key=lambda x: -(x.get("score") or -1)), "errors": dict(self.errors),
                    "model": analysis.MODEL_VERSION, "interval_seconds": self.cfg.scan_interval_seconds}
