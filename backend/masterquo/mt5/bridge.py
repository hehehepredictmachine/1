"""Local MT5 bridge: connection supervision, exact-symbol checks, quotes, six-timeframe bars,
account/positions/history and heartbeat. All terminal calls go through MT5Worker.

Bars are always collected for M1, M5, M15, H1, H4 and D1 regardless of what the user views.
Closed-bar confirmation rule (unchanged intent of the FUTURE_CANDLE_AVAILABILITY fix): a bar is
CLOSED only when the *next* bar of the same timeframe has actually been observed in the
terminal. `available_at` is the moment we observed that next bar (basis OBSERVED); for bars that
were already closed in the initial history load it is the next bar's open time
(basis HISTORICAL_ESTIMATE - the earliest moment the close could have been known).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from ..config import ConfigStore
from ..timeutil import TF_SECONDS, TIMEFRAMES, UTC, from_epoch, iso, utcnow
from .clock import ServerClock
from .worker import PRIO_HISTORY, PRIO_QUOTE, MT5CallTimeout, MT5Worker, MT5WorkerUnavailable

log = logging.getLogger("masterquo.mt5.bridge")

TF_CONST = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
            "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}
# Poll cadence per timeframe (seconds). Higher TFs change rarely.
TF_POLL = {"M1": 1.0, "M5": 2.0, "M15": 3.0, "H1": 5.0, "H4": 10.0, "D1": 15.0}
TRADE_MODE = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
MARGIN_MODE = {0: "NETTING", 1: "EXCHANGE", 2: "HEDGING"}


def _row(r) -> dict:
    if hasattr(r, "_asdict"):
        return r._asdict()
    if hasattr(r, "dtype") and getattr(r.dtype, "names", None):
        return {k: (r[k].item() if hasattr(r[k], "item") else r[k]) for k in r.dtype.names}
    return dict(r)


@dataclass
class Bar:
    t_raw: int
    o: float
    h: float
    l: float
    c: float
    tv: int
    rv: int
    spread: int
    closed: bool = False
    available_raw_next_open: int | None = None  # raw open of the observed next bar
    observed_close_utc: datetime | None = None   # when we observed the next bar (live)
    basis: str = "FORMING"                       # FORMING | OBSERVED | HISTORICAL_ESTIMATE
    revision: int = 0

    def same_values(self, other: "Bar") -> bool:
        return (self.o, self.h, self.l, self.c, self.tv) == (other.o, other.h, other.l, other.c, other.tv)


@dataclass
class TFState:
    bars: list[Bar] = field(default_factory=list)
    last_poll: float = 0.0
    revisions: int = 0
    gap_fills: int = 0
    last_error: str | None = None
    loaded: bool = False


class BridgeError(RuntimeError):
    pass


class MarketBridge:
    def __init__(self, config: ConfigStore, worker: MT5Worker, db, bus, applog,
                 clock_fn: Callable[[], datetime] = utcnow, required_bars: dict[str, int] | None = None):
        self.cfg_store = config
        self.worker = worker
        self.db = db
        self.bus = bus
        self.log = applog
        self.now = clock_fn
        self.required_bars = required_bars or {tf: 260 for tf in TIMEFRAMES}
        self.clock = ServerClock()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state = "DISCONNECTED"
        self.state_reason: str | None = "NOT_STARTED"
        self.session_epoch = 0
        self.terminal: dict | None = None
        self.account: dict | None = None
        self.account_key: str | None = None
        self.symbol_info: dict | None = None
        self.symbol_status = "UNKNOWN"
        self.symbol_candidates: list[str] = []
        self.quote: dict | None = None
        self.tfs: dict[str, TFState] = {tf: TFState() for tf in TIMEFRAMES}
        self.dxy: TFState = TFState()
        self.dxy_status = "NOT_CONFIGURED"
        self.positions: list[dict] = []
        self.orders: list[dict] = []
        self.deals: list[dict] = []
        self.deals_loaded_at: datetime | None = None
        self.last_heartbeat: datetime | None = None
        self.connected_since: datetime | None = None
        self.attempts = 0
        self.next_retry = 0.0
        self.consecutive_errors = 0
        self.errors: list[dict] = []
        self.listeners: list[Callable[[str, dict], None]] = []
        self._last_quote_pub = 0.0
        self._last_bar_pub: dict[str, float] = {}
        self._t_account = self._t_quote = self._t_hist = self._t_hb = 0.0
        self._synthetic = False

    # ---------------------------------------------------------------- helpers
    @property
    def cfg(self):
        return self.cfg_store.get().mt5

    def _call(self, fn, prio=PRIO_QUOTE):
        return self.worker.call(fn, priority=prio, timeout=self.cfg.call_timeout_seconds)

    def add_listener(self, fn: Callable[[str, dict], None]) -> None:
        self.listeners.append(fn)

    def _notify(self, kind: str, data: dict) -> None:
        for fn in list(self.listeners):
            try:
                fn(kind, data)
            except Exception:
                log.exception("bridge listener failed")

    def _error(self, code: str, detail: str | None = None) -> None:
        with self._lock:
            self.errors.append({"ts": iso(self.now()), "code": code, "detail": detail})
            self.errors = self.errors[-50:]

    def _set_state(self, state: str, reason: str | None) -> None:
        changed = (state, reason) != (self.state, self.state_reason)
        self.state, self.state_reason = state, reason
        if changed:
            self.bus.publish("connection", self.connection_status())
            level = "INFO" if state == "CONNECTED" else "WARNING"
            self.log.write(level, "MT5", state, f"MT5: {state}" + (f" ({reason})" if reason else ""))

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="mt5-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        try:
            self._call(lambda m: m.shutdown())
        except Exception:
            pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            mono = time.monotonic()
            try:
                if self.state != "CONNECTED":
                    if mono >= self.next_retry:
                        self.connect()
                else:
                    self.poll(mono)
                    self.consecutive_errors = 0
            except (MT5CallTimeout,) as exc:
                self._handle_failure("TERMINAL_UNRESPONSIVE", str(exc))
            except (BridgeError, MT5WorkerUnavailable) as exc:
                self._handle_failure(type(exc).__name__, str(exc))
            except Exception as exc:  # never let the supervision thread die
                log.exception("bridge loop error")
                self._handle_failure(type(exc).__name__, str(exc))
            self._stop.wait(0.2)

    def _handle_failure(self, code: str, detail: str) -> None:
        self.consecutive_errors += 1
        self._error(code, detail)
        if self.state == "CONNECTED" and self.consecutive_errors < 3:
            return
        self.attempts += 1
        delay = min(self.cfg.reconnect_max_backoff_seconds, 2.0 ** min(self.attempts, 6))
        self.next_retry = time.monotonic() + delay
        if self.worker.module is None:
            self._set_state("MODULE_MISSING", self.worker.module_error or "MetaTrader5 package not importable")
        else:
            self._set_state("RECONNECTING" if self.connected_since else "DISCONNECTED", f"{code}: {detail}"[:240])
        self.quote = None

    # ---------------------------------------------------------------- connect
    def connect(self) -> None:
        self._set_state("CONNECTING", None)
        path = self.cfg.terminal_path
        ok = self._call(lambda m: m.initialize(path=path) if path else m.initialize())
        if not ok:
            err = self._call(lambda m: m.last_error())
            raise BridgeError(f"MT5_INITIALIZE_FAILED:{err}")
        from .fake import is_fake
        self._synthetic = bool(self._call(lambda m: is_fake(m)))
        term = self._call(lambda m: m.terminal_info())
        acct = self._call(lambda m: m.account_info())
        if term is None:
            raise BridgeError("TERMINAL_INFO_UNAVAILABLE")
        if acct is None:
            raise BridgeError("ACCOUNT_NOT_LOGGED_IN")
        terminal = _row(term)
        account = self._account_dict(_row(acct))
        new_key = f"{account['server']}:{account['login']}"
        prev_key, prev_path = self.account_key, (self.terminal or {}).get("path")
        with self._lock:
            self.terminal = {k: terminal.get(k) for k in ("name", "company", "path", "build", "connected", "trade_allowed", "tradeapi_disabled", "ping_last")}
            self.account = account
            self.account_key = new_key
            self.session_epoch += 1
        self._record_account(account)
        if prev_key is not None and (prev_key != new_key or prev_path != terminal.get("path")):
            self.log.warn("MT5", "ACCOUNT_OR_TERMINAL_CHANGED", f"Zmiana rachunku/terminala: {prev_key} -> {new_key}")
            self._notify("account_changed", {"previous": prev_key, "current": new_key})
        self.clock.reset()
        self._load_stored_offset(account["server"])
        self._check_symbol()
        self._load_all_history()
        self._load_dxy()
        self.connected_since = self.now()
        self.attempts = 0
        self._set_state("CONNECTED", None)
        self._notify("connected", {"account_key": new_key, "session_epoch": self.session_epoch})
        self.bus.publish("account", self.account_status())

    def _account_dict(self, a: dict) -> dict:
        return {"login": a.get("login"), "server": a.get("server"), "company": a.get("company"), "name": a.get("name"),
                "currency": a.get("currency"), "trade_mode": TRADE_MODE.get(a.get("trade_mode"), str(a.get("trade_mode"))),
                "margin_mode": MARGIN_MODE.get(a.get("margin_mode"), str(a.get("margin_mode"))),
                "leverage": a.get("leverage"), "balance": a.get("balance"), "equity": a.get("equity"),
                "margin": a.get("margin"), "free_margin": a.get("margin_free"), "margin_level": a.get("margin_level"),
                "profit": a.get("profit"), "trade_allowed": a.get("trade_allowed"), "trade_expert": a.get("trade_expert")}

    def _record_account(self, a: dict) -> None:
        now = iso(self.now())
        key = f"{a['server']}:{a['login']}"
        self.db.execute("""INSERT INTO accounts_seen(account_key, login, server, company, currency, trade_mode, margin_mode, first_seen, last_seen)
                           VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(account_key) DO UPDATE SET last_seen=excluded.last_seen,
                           currency=excluded.currency, trade_mode=excluded.trade_mode, margin_mode=excluded.margin_mode""",
                        (key, a["login"], a["server"], a.get("company"), a.get("currency"), a["trade_mode"], a.get("margin_mode"), now, now))

    def _load_stored_offset(self, server: str) -> None:
        row = self.db.one("SELECT offset_seconds, measured_at FROM clock_offsets WHERE server=?", (server,))
        if row:
            from ..timeutil import parse_iso
            self.clock.load_stored(row["offset_seconds"], parse_iso(row["measured_at"]))

    def _check_symbol(self) -> None:
        sym = self.cfg.symbol
        info = self._call(lambda m: m.symbol_info(sym))
        if info is None:
            cands = self._call(lambda m: m.symbols_get(group="*XAU*,*GOLD*")) or ()
            self.symbol_candidates = sorted({_row(c)["name"] for c in cands})[:30]
            self.symbol_status = "NOT_FOUND"
            self.symbol_info = None
            self.bus.publish("symbol", self.symbol_status_dict())
            raise BridgeError(f"SYMBOL_NOT_FOUND:{sym}:candidates={','.join(self.symbol_candidates) or 'none'}")
        info = _row(info)
        if not info.get("visible"):
            if not self._call(lambda m: m.symbol_select(sym, True)):
                self.symbol_status = "NOT_VISIBLE_SELECT_FAILED"
                raise BridgeError(f"SYMBOL_SELECT_FAILED:{sym}")
            info = _row(self._call(lambda m: m.symbol_info(sym)))
        if info.get("name") != sym:
            raise BridgeError(f"SYMBOL_NAME_MISMATCH:{info.get('name')}!={sym}")
        keep = ("name", "description", "path", "point", "digits", "trade_tick_size", "trade_tick_value", "trade_contract_size",
                "volume_min", "volume_max", "volume_step", "trade_stops_level", "trade_freeze_level", "trade_mode",
                "filling_mode", "currency_base", "currency_profit", "currency_margin", "spread", "spread_float")
        with self._lock:
            self.symbol_info = {k: info.get(k) for k in keep}
            tm = info.get("trade_mode")
            self.symbol_status = "OK" if tm == 4 else {0: "TRADE_DISABLED", 1: "LONG_ONLY", 2: "SHORT_ONLY", 3: "CLOSE_ONLY"}.get(tm, f"TRADE_MODE_{tm}")
        self.bus.publish("symbol", self.symbol_status_dict())

    # ---------------------------------------------------------------- history
    def _fetch(self, symbol: str, tf: str, count: int) -> list[Bar]:
        name = TF_CONST[tf]
        raw = self._call(lambda m: m.copy_rates_from_pos(symbol, getattr(m, name), 0, count), PRIO_HISTORY)
        if raw is None:
            err = self._call(lambda m: m.last_error())
            raise BridgeError(f"COPY_RATES_FAILED:{tf}:{err}")
        out = []
        for r in raw:
            d = _row(r)
            out.append(Bar(int(d["time"]), float(d["open"]), float(d["high"]), float(d["low"]), float(d["close"]),
                           int(d.get("tick_volume") or 0), int(d.get("real_volume") or 0), int(d.get("spread") or 0)))
        out.sort(key=lambda b: b.t_raw)
        return out

    def buffer_size(self, tf: str) -> int:
        return min(2000, max(self.cfg.chart_bars, self.required_bars.get(tf, 260) + 60))

    def _load_all_history(self) -> None:
        for tf in TIMEFRAMES:
            bars = self._fetch(self.cfg.symbol, tf, self.buffer_size(tf) + 1)
            for i in range(len(bars) - 1):
                bars[i].closed = True
                bars[i].available_raw_next_open = bars[i + 1].t_raw
                bars[i].basis = "HISTORICAL_ESTIMATE"
            with self._lock:
                st = self.tfs[tf]
                st.bars, st.loaded, st.last_poll, st.last_error = bars, True, time.monotonic(), None
            self.bus.publish("bars_reloaded", {"tf": tf, "count": len(bars)})

    def _load_dxy(self) -> None:
        sym = self.cfg.dxy_symbol
        if not sym:
            self.dxy_status = "NOT_CONFIGURED"
            return
        try:
            if self._call(lambda m: m.symbol_info(sym)) is None or not self._call(lambda m: m.symbol_select(sym, True)):
                self.dxy_status = "SYMBOL_NOT_FOUND"
                return
            bars = self._fetch(sym, "H1", 300)
            for i in range(len(bars) - 1):
                bars[i].closed, bars[i].available_raw_next_open, bars[i].basis = True, bars[i + 1].t_raw, "HISTORICAL_ESTIMATE"
            with self._lock:
                self.dxy.bars, self.dxy.loaded = bars, True
            self.dxy_status = "OK"
        except (BridgeError, MT5CallTimeout) as exc:
            self.dxy_status = "ERROR:" + str(exc)[:80]

    def _merge_tail(self, st: TFState, tf: str, tail: list[Bar], symbol: str) -> list[Bar]:
        """Merge the newest bars. Returns newly *closed* bars. Fills gaps by refetching."""
        if not tail:
            return []
        newly_closed: list[Bar] = []
        with self._lock:
            bars = st.bars
            last_known = bars[-1].t_raw if bars else None
        if last_known is not None and tail[0].t_raw > last_known:
            # More than len(tail) bars appeared since the previous poll -> gap fill from the terminal.
            need = min(2000, int((tail[-1].t_raw - last_known) / TF_SECONDS[tf]) + 5)
            tail = self._fetch(symbol, tf, need)
            st.gap_fills += 1
        observed = self.now()
        with self._lock:
            bars = st.bars
            index = {b.t_raw: i for i, b in enumerate(bars[-len(tail) - 5:], start=max(0, len(bars) - len(tail) - 5))}
            for nb in tail:
                i = index.get(nb.t_raw)
                if i is not None:
                    old = bars[i]
                    if old.closed:
                        if not old.same_values(nb):
                            old.o, old.h, old.l, old.c, old.tv = nb.o, nb.h, nb.l, nb.c, nb.tv
                            old.revision += 1
                            st.revisions += 1
                    else:
                        old.o, old.h, old.l, old.c, old.tv, old.rv, old.spread = nb.o, nb.h, nb.l, nb.c, nb.tv, nb.rv, nb.spread
                elif not bars or nb.t_raw > bars[-1].t_raw:
                    if bars and not bars[-1].closed:
                        prev = bars[-1]
                        prev.closed = True
                        prev.available_raw_next_open = nb.t_raw
                        prev.observed_close_utc = observed
                        prev.basis = "OBSERVED"
                        newly_closed.append(prev)
                    bars.append(nb)
            keep = self.buffer_size(tf) + 1
            if len(bars) > keep:
                del bars[: len(bars) - keep]
        return newly_closed

    # ---------------------------------------------------------------- polling
    def poll(self, mono: float) -> None:
        c = self.cfg
        if mono - self._t_hb >= c.heartbeat_seconds:
            self._t_hb = mono
            term = self._call(lambda m: m.terminal_info())
            if term is None:
                raise BridgeError("TERMINAL_INFO_NONE")
            t = _row(term)
            if t.get("path") != (self.terminal or {}).get("path"):
                raise BridgeError("TERMINAL_PATH_CHANGED")
            with self._lock:
                self.terminal.update({"connected": t.get("connected"), "trade_allowed": t.get("trade_allowed"),
                                      "tradeapi_disabled": t.get("tradeapi_disabled"), "ping_last": t.get("ping_last")})
            self.last_heartbeat = self.now()
            if not t.get("connected"):
                self._error("TERMINAL_NOT_CONNECTED_TO_TRADE_SERVER")
        if mono - self._t_quote >= c.quote_poll_seconds:
            self._t_quote = mono
            self._poll_quote()
        for tf in TIMEFRAMES:
            st = self.tfs[tf]
            if mono - st.last_poll >= max(TF_POLL[tf], c.bars_poll_seconds if tf != "M1" else TF_POLL[tf]):
                st.last_poll = mono
                tail = self._fetch(c.symbol, tf, 3)
                closed = self._merge_tail(st, tf, tail, c.symbol)
                with self._lock:
                    current = self._bar_json(st.bars[-1], tf) if st.bars else None
                if closed:
                    for b in closed:
                        self.bus.publish("bar_closed", {"tf": tf, "bar": self._bar_json(b, tf)})
                    self._notify("bars_closed", {"tf": tf, "count": len(closed)})
                if current and (mono - self._last_bar_pub.get(tf, 0) >= 1.0 or closed):
                    self._last_bar_pub[tf] = mono
                    self.bus.publish("bar", {"tf": tf, "bar": current})
        if c.dxy_symbol and self.dxy.loaded and mono - self.dxy.last_poll >= 15:
            self.dxy.last_poll = mono
            closed = self._merge_tail(self.dxy, "H1", self._fetch(c.dxy_symbol, "H1", 3), c.dxy_symbol)
            if closed:
                self._notify("bars_closed", {"tf": "DXY_H1", "count": len(closed)})
        if mono - self._t_account >= c.account_poll_seconds:
            self._t_account = mono
            self._poll_account()
        if mono - self._t_hist >= c.history_poll_seconds:
            self._t_hist = mono
            self._poll_deals()

    def _poll_quote(self) -> None:
        sym = self.cfg.symbol
        tick = self._call(lambda m: m.symbol_info_tick(sym))
        received = self.now()
        if tick is None:
            raise BridgeError("TICK_UNAVAILABLE")
        t = _row(tick)
        msc = int(t.get("time_msc") or int(t["time"]) * 1000)
        prev_status = self.clock.evidence.status
        prev_offset = self.clock.evidence.offset_seconds
        is_new = self.quote is None or msc != self.quote.get("time_msc")
        ev = self.clock.observe_tick(msc, received) if is_new else self.clock.evidence
        if ev.status == "VERIFIED" and (prev_status != "VERIFIED" or prev_offset != ev.offset_seconds) and self.account:
            self.db.execute("""INSERT INTO clock_offsets(server, offset_seconds, measured_at, samples, residual_seconds) VALUES (?,?,?,?,?)
                               ON CONFLICT(server) DO UPDATE SET offset_seconds=excluded.offset_seconds, measured_at=excluded.measured_at,
                               samples=excluded.samples, residual_seconds=excluded.residual_seconds""",
                            (self.account["server"], ev.offset_seconds, iso(received), ev.samples, ev.residual_seconds or 0.0))
            self.bus.publish("clock", ev.as_dict())
        bid, ask = float(t["bid"]), float(t["ask"])
        point = (self.symbol_info or {}).get("point") or None
        last_new = received if is_new else (self.quote or {}).get("_last_new_received", received)
        q = {"symbol": sym, "bid": bid, "ask": ask, "spread": round(ask - bid, 10),
             "spread_points": round((ask - bid) / point, 1) if point else None,
             "time_raw": int(t["time"]), "time_msc": msc,
             "time_utc": iso(self.clock.raw_to_utc(msc / 1000.0)) if self.clock.offset is not None else None,
             "received_at": iso(received), "_last_new_received": last_new, "source": "MT5"}
        with self._lock:
            self.quote = q
        mono = time.monotonic()
        if mono - self._last_quote_pub >= 0.25:
            self._last_quote_pub = mono
            self.bus.publish("quote", self.quote_status())

    def _poll_account(self) -> None:
        acct = self._call(lambda m: m.account_info())
        if acct is None:
            raise BridgeError("ACCOUNT_INFO_NONE")
        a = self._account_dict(_row(acct))
        key = f"{a['server']}:{a['login']}"
        if key != self.account_key:
            prev = self.account_key
            with self._lock:
                self.account, self.account_key = a, key
                self.session_epoch += 1
            self._record_account(a)
            self.log.warn("MT5", "ACCOUNT_CHANGED", f"Zmieniono rachunek w terminalu: {prev} -> {key}. Decyzje wygaszone; wysyłka zleceń zablokowana do zgodności rachunku z trybem.")
            self.clock.reset()
            self._load_stored_offset(a["server"])
            self._load_all_history()
            self._notify("account_changed", {"previous": prev, "current": key})
        sym = self.cfg.symbol
        pos = self._call(lambda m: m.positions_get()) or ()
        ords = self._call(lambda m: m.orders_get()) or ()
        with self._lock:
            self.account = a
            self.positions = [self._pos_dict(_row(p)) for p in pos]
            self.orders = [{k: v for k, v in _row(o).items() if k in ("ticket", "time_setup", "type", "symbol", "volume_current", "price_open", "sl", "tp", "magic", "comment")} for o in ords]
        self.bus.publish("account", self.account_status())
        self.bus.publish("positions", {"positions": self.positions, "orders": self.orders, "symbol": sym})

    def _pos_dict(self, p: dict) -> dict:
        return {"ticket": p.get("ticket"), "symbol": p.get("symbol"), "side": "BUY" if p.get("type") == 0 else "SELL",
                "volume": p.get("volume"), "price_open": p.get("price_open"), "sl": p.get("sl") or None, "tp": p.get("tp") or None,
                "price_current": p.get("price_current"), "profit": p.get("profit"), "swap": p.get("swap"),
                "magic": p.get("magic"), "comment": p.get("comment"), "time_raw": p.get("time"), "identifier": p.get("identifier")}

    def _poll_deals(self) -> None:
        days = self.cfg.deals_history_days
        now_raw = self.now().timestamp() + (self.clock.offset or 0)
        frm = datetime.fromtimestamp(now_raw - days * 86400, UTC)
        to = datetime.fromtimestamp(now_raw + 86400, UTC)
        deals = self._call(lambda m: m.history_deals_get(frm, to), PRIO_HISTORY)
        if deals is None:
            self._error("HISTORY_DEALS_UNAVAILABLE")
            return
        out = []
        for d in deals:
            r = _row(d)
            out.append({k: r.get(k) for k in ("ticket", "order", "time", "type", "entry", "magic", "position_id", "volume",
                                              "price", "commission", "swap", "profit", "fee", "symbol", "comment", "reason")})
        with self._lock:
            self.deals = out
            self.deals_loaded_at = self.now()
        self._notify("deals", {"count": len(out)})

    # ---------------------------------------------------------------- read API
    def _bar_json(self, b: Bar, tf: str) -> dict:
        off = self.clock.offset
        open_utc = from_epoch(b.t_raw - off) if off is not None else None
        if b.closed:
            if b.basis == "OBSERVED" and b.observed_close_utc is not None:
                avail = b.observed_close_utc
            elif off is not None and b.available_raw_next_open is not None:
                avail = from_epoch(b.available_raw_next_open - off)
            else:
                avail = None
        else:
            avail = None
        return {"t_raw": b.t_raw, "open_utc": iso(open_utc), "o": b.o, "h": b.h, "l": b.l, "c": b.c, "tv": b.tv, "rv": b.rv,
                "spread": b.spread, "closed": b.closed,
                "close_confirmed_utc": iso(from_epoch(b.available_raw_next_open - off)) if (b.closed and off is not None and b.available_raw_next_open) else None,
                "available_at": iso(avail), "basis": b.basis, "revision": b.revision}

    def bars(self, tf: str, limit: int | None = None, include_forming: bool = True) -> list[dict]:
        with self._lock:
            src = self.dxy.bars if tf == "DXY_H1" else self.tfs[tf].bars
            seq = src if include_forming else [b for b in src if b.closed]
            if limit:
                seq = seq[-limit:]
            return [self._bar_json(b, "H1" if tf == "DXY_H1" else tf) for b in seq]

    def tf_meta(self) -> dict:
        with self._lock:
            return {tf: {"loaded": st.loaded, "bars": len(st.bars), "closed": sum(1 for b in st.bars if b.closed),
                         "revisions": st.revisions, "gap_fills": st.gap_fills, "buffer": self.buffer_size(tf),
                         "required": self.required_bars.get(tf)} for tf, st in self.tfs.items()}

    def quote_status(self) -> dict | None:
        with self._lock:
            if not self.quote:
                return None
            q = {k: v for k, v in self.quote.items() if not k.startswith("_")}
            last_new = self.quote.get("_last_new_received")
        now = self.now()
        q["age_seconds"] = round((now - last_new).total_seconds(), 3) if isinstance(last_new, datetime) else None
        if q.get("time_utc"):
            from ..timeutil import parse_iso
            q["source_age_seconds"] = round((now - parse_iso(q["time_utc"])).total_seconds(), 3)
        else:
            q["source_age_seconds"] = None
        return q

    def connection_status(self) -> dict:
        return {"state": self.state, "reason": self.state_reason, "session_epoch": self.session_epoch,
                "connected_since": iso(self.connected_since), "last_heartbeat": iso(self.last_heartbeat),
                "terminal": self.terminal, "account_key": self.account_key, "synthetic": self._synthetic,
                "attempts": self.attempts, "module_error": self.worker.module_error,
                "worker_wedged_seconds": round(self.worker.wedged_seconds, 1), "errors": self.errors[-8:],
                "clock": self.clock.evidence.as_dict()}

    def account_status(self) -> dict | None:
        with self._lock:
            return dict(self.account) if self.account else None

    def symbol_status_dict(self) -> dict:
        return {"symbol": self.cfg.symbol, "status": self.symbol_status, "info": self.symbol_info,
                "candidates": self.symbol_candidates, "dxy_symbol": self.cfg.dxy_symbol, "dxy_status": self.dxy_status}

    @property
    def synthetic(self) -> bool:
        return self._synthetic

    # ---------------------------------------------------------------- broker calculators
    def calc_profit(self, side: str, volume: float, price_open: float, price_close: float) -> float | None:
        sym = self.cfg.symbol
        return self._call(lambda m: m.order_calc_profit(m.ORDER_TYPE_BUY if side == "BUY" else m.ORDER_TYPE_SELL,
                                                         sym, volume, price_open, price_close))

    def calc_margin(self, side: str, volume: float, price: float) -> float | None:
        sym = self.cfg.symbol
        return self._call(lambda m: m.order_calc_margin(m.ORDER_TYPE_BUY if side == "BUY" else m.ORDER_TYPE_SELL, sym, volume, price))

    def raw_call(self, fn, prio=PRIO_QUOTE, timeout: float | None = None) -> Any:
        return self.worker.call(fn, priority=prio, timeout=timeout or self.cfg.call_timeout_seconds)

    def server_now_raw(self) -> float | None:
        off = self.clock.offset
        return None if off is None else self.now().timestamp() + off

    def server_day_start_utc(self) -> datetime | None:
        """Start of the current broker-server day, in UTC (daily-loss boundary)."""
        off = self.clock.offset
        if off is None:
            return None
        server_now = self.now() + timedelta(seconds=off)
        midnight = server_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight - timedelta(seconds=off)
