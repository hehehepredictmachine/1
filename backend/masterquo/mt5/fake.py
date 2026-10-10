"""Synthetic stand-in for the MetaTrader5 module.

Used ONLY by automated tests and by the explicitly labelled synthetic demo
(`03_START_MASTERQUO.bat --demo`, banner "DANE SYNTETYCZNE", separate database).
It is never selected automatically when the real terminal is missing.

It implements the subset of the official API the application uses, with the same shapes:
raw times are broker-server wall-clock epochs (UTC + server_offset), bars come from a
deterministic random walk with weekend closure and a daily one-hour break, and trading calls
simulate a hedging (or netting) account with commission.
"""
from __future__ import annotations

import threading
import os
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from typing import Callable

import numpy as np

UTC = timezone.utc

TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15 = 1, 5, 15
TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 16385, 16388, 16408
_TF_SEC = {TIMEFRAME_M1: 60, TIMEFRAME_M5: 300, TIMEFRAME_M15: 900, TIMEFRAME_H1: 3600, TIMEFRAME_H4: 14400, TIMEFRAME_D1: 86400}

ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
ORDER_TIME_GTC = 0
TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL = 10008, 10009, 10010
TRADE_RETCODE_REJECT, TRADE_RETCODE_INVALID_STOPS, TRADE_RETCODE_NO_MONEY = 10006, 10016, 10019
TRADE_RETCODE_MARKET_CLOSED = 10018
DEAL_TYPE_BUY, DEAL_TYPE_SELL, DEAL_TYPE_BALANCE = 0, 1, 2
DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 0, 1, 2
ACCOUNT_MARGIN_MODE_RETAIL_NETTING, ACCOUNT_MARGIN_MODE_EXCHANGE, ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 0, 1, 2
SYMBOL_TRADE_MODE_DISABLED, SYMBOL_TRADE_MODE_CLOSEONLY, SYMBOL_TRADE_MODE_FULL = 0, 3, 4

TerminalInfo = namedtuple("TerminalInfo", "connected trade_allowed tradeapi_disabled name company path build ping_last")
AccountInfo = namedtuple("AccountInfo", "login server company name currency trade_mode margin_mode leverage balance equity margin margin_free margin_level profit trade_allowed trade_expert")
SymbolInfo = namedtuple("SymbolInfo", "name visible select point digits trade_tick_size trade_tick_value trade_contract_size volume_min volume_max volume_step trade_stops_level trade_freeze_level trade_mode filling_mode currency_base currency_profit currency_margin spread spread_float description path bid ask time")
Tick = namedtuple("Tick", "time bid ask last volume time_msc flags volume_real")
Position = namedtuple("Position", "ticket time time_msc type magic identifier volume price_open sl tp price_current swap profit symbol comment")
Deal = namedtuple("Deal", "ticket order time time_msc type entry magic position_id volume price commission swap profit fee symbol comment reason")
OrderResult = namedtuple("OrderResult", "retcode deal order volume price bid ask comment request_id retcode_external request")
OrderCheck = namedtuple("OrderCheck", "retcode balance equity profit margin margin_free margin_level comment request")

RATE_DTYPE = np.dtype([("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
                       ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])

# Synthetic extra markets (independent random walks, rescaled). Names, prices and paths are illustrative only.
SYN_MARKETS = {
    "EURUSD-": dict(base=1.0850, scale=0.00006, digits=5, seed=11, spread=8, visible=True, desc="Euro vs US Dollar (synthetic)",
                    path="Synthetic\\Forex\\EURUSD-", base_ccy="EUR", profit_ccy="USD", contract=100000.0),
    "GBPUSD-": dict(base=1.2700, scale=0.00008, digits=5, seed=12, spread=10, visible=True, desc="British Pound vs US Dollar (synthetic)",
                    path="Synthetic\\Forex\\GBPUSD-", base_ccy="GBP", profit_ccy="USD", contract=100000.0),
    "USDJPY-": dict(base=149.50, scale=0.012, digits=3, seed=13, spread=9, visible=True, desc="US Dollar vs Japanese Yen (synthetic)",
                    path="Synthetic\\Forex\\USDJPY-", base_ccy="USD", profit_ccy="JPY", contract=100000.0),
    "US30-": dict(base=42100.0, scale=3.2, digits=1, seed=15, spread=20, visible=True, desc="Dow Jones 30 CFD (synthetic)",
                  path="Synthetic\\Indices\\US30-", base_ccy="USD", profit_ccy="USD", contract=1.0),
    "XAGUSD-": dict(base=31.20, scale=0.0035, digits=3, seed=14, spread=25, visible=False, desc="Silver vs US Dollar (synthetic)",
                    path="Synthetic\\Metals\\XAGUSD-", base_ccy="XAG", profit_ccy="USD", contract=5000.0),
    "BTCUSD-": dict(base=64000.0, scale=28.0, digits=2, seed=16, spread=3000, visible=False, desc="Bitcoin vs US Dollar (synthetic)",
                    path="Synthetic\\Crypto\\BTCUSD-", base_ccy="BTC", profit_ccy="USD", contract=1.0),
}


class FakeMT5:
    def __init__(self, *, symbol: str = "XAUUSD-", server_offset_hours: float = 3.0, seed: int = 7,
                 clock: Callable[[], datetime] | None = None, history_days: int = 430, hedging: bool = True,
                 login: int = 5550001, server: str = "Synthetic-Demo", trade_mode: int = ACCOUNT_TRADE_MODE_DEMO,
                 commission_per_lot_side: float = 3.5, start_price: float = 2650.0, extra_symbols=("DXY_SYN",),
                 markets: dict | None = None):
        self.symbol = symbol
        self.offset = int(server_offset_hours * 3600)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.seed = seed
        self.hedging = hedging
        self.commission = commission_per_lot_side
        self.connected = False
        self.terminal_connected = True
        self.fail_next_order: int | None = None
        self.hang_order_send = False
        self._lock = threading.RLock()
        self._last_error = (1, "Success")
        self._accounts = {login: dict(login=login, server=server, trade_mode=trade_mode, balance=10000.0)}
        self._login = login
        self._positions: dict[int, dict] = {}
        self._deals: list[Deal] = []
        self._ticket = 1000
        self._extra = set(extra_symbols)
        self._markets = dict(SYN_MARKETS if markets is None else markets)
        self._series: dict[str, tuple] = {}
        self._visible = {symbol} | {n for n, m in self._markets.items() if m["visible"]}
        self._start_price = start_price
        self._history_days = history_days
        self._build_history()

    # ------------------------------------------------------------------ data
    def _raw_now(self) -> float:
        return self.clock().timestamp() + self.offset

    @staticmethod
    def _is_open(raw_minute: int) -> bool:
        if os.environ.get("MQ_FAKE_MARKET_ALWAYS_OPEN") == "1":
            return True  # offline tests only: results must not depend on the weekday the tests are run
        d = datetime.fromtimestamp(raw_minute, UTC)  # server wall clock
        if d.weekday() == 5 or (d.weekday() == 6) or (d.weekday() == 4 and d.hour >= 23):
            return False  # Fri 23:00 .. Mon 00:00 server time closed (weekend)
        return d.hour != 23  # daily break 23:00-24:00 server time

    def _build_history(self) -> None:
        self._mins, self._m1 = self._build_series(self.seed, self._history_days)

    def _build_series(self, seed: int, history_days: int):
        now_raw = int(self._raw_now()) // 3600 * 3600
        start = now_raw - history_days * 86400
        mins = np.arange(start, now_raw + 86400 * 30, 60, dtype=np.int64)  # 30 days ahead pre-generated
        rng = np.random.default_rng(seed)
        n = len(mins)
        # regime-switching drift + volatility clustering, in price units
        regime = np.repeat(rng.normal(0, 0.035, n // 240 + 1), 240)[:n]
        vol = np.repeat(np.abs(rng.normal(0.45, 0.15, n // 60 + 1)) + 0.12, 60)[:n]
        steps = rng.normal(0, 1, n) * vol + regime
        price = self._start_price + np.cumsum(steps)
        price = np.maximum(price, 100.0)
        wick = np.abs(rng.normal(0, 0.18, (n, 2))) * vol[:, None]
        open_mask = np.array([self._is_open(int(m)) for m in mins[::60]]).repeat(60)[:n]
        kept = mins[open_mask]
        close = price[open_mask]
        opn = np.concatenate([[close[0]], close[:-1]])
        m1 = {"time": kept, "open": opn, "close": close,
              "high": np.maximum(opn, close) + wick[open_mask, 0], "low": np.minimum(opn, close) - wick[open_mask, 1],
              "tick_volume": (rng.integers(20, 400, len(close))).astype(np.uint64)}
        return kept, m1

    def _market_series(self, name: str):
        """Independent random walk per synthetic market (built lazily, shorter history), in the main price units."""
        if name not in self._series:
            m = self._markets[name]
            self._series[name] = self._build_series(m["seed"], min(self._history_days, 160))
        return self._series[name]

    def _to_market(self, name: str, x):
        m = self._markets[name]
        return m["base"] + (x - self._start_price) * m["scale"]

    def _known(self, name: str) -> bool:
        return name == self.symbol or name in self._extra or name in self._markets

    def _m1_upto(self, raw_now: float, mins=None):
        idx = int(np.searchsorted(self._mins if mins is None else mins, raw_now, side="right"))
        return idx

    def _price_at(self, raw_now: float, series=None) -> float | None:
        mins, m1 = series or (self._mins, self._m1)
        idx = self._m1_upto(raw_now, mins)
        if idx == 0:
            return None
        i = idx - 1
        if raw_now - mins[i] >= 60:
            return None  # market closed: no live price
        frac = (raw_now - mins[i]) / 60.0
        o, c = m1["open"][i], m1["close"][i]
        return float(o + (c - o) * frac)

    def _rates(self, tf: int, raw_now: float, series=None) -> np.ndarray:
        mins, m1 = series or (self._mins, self._m1)
        sec = _TF_SEC[tf]
        idx = self._m1_upto(raw_now, mins)
        t = mins[:idx]
        if idx == 0:
            return np.zeros(0, dtype=RATE_DTYPE)
        o, h, lo, c, v = (m1[k][:idx] for k in ("open", "high", "low", "close", "tick_volume"))
        h = h.copy(); lo = lo.copy(); c = c.copy(); v = v.copy()
        # the forming M1 bar is only partially known
        last_frac = min(1.0, max(0.0, (raw_now - t[-1]) / 60.0))
        if last_frac < 1.0:
            c[-1] = o[-1] + (c[-1] - o[-1]) * last_frac
            h[-1] = max(o[-1], c[-1]) + (h[-1] - max(o[-1], m1["close"][idx - 1])) * last_frac
            lo[-1] = min(o[-1], c[-1]) - (min(o[-1], m1["close"][idx - 1]) - lo[-1]) * last_frac
            v[-1] = max(1, int(v[-1] * last_frac))
        bucket = (t // sec) * sec
        uniq, first = np.unique(bucket, return_index=True)
        last = np.concatenate([first[1:] - 1, [len(t) - 1]])
        out = np.zeros(len(uniq), dtype=RATE_DTYPE)
        out["time"] = uniq
        out["open"] = o[first]
        out["close"] = c[last]
        out["high"] = np.maximum.reduceat(h, first)
        out["low"] = np.minimum.reduceat(lo, first)
        out["tick_volume"] = np.add.reduceat(v, first)
        out["spread"] = 12
        return out

    # ---------------------------------------------------------- connection
    def initialize(self, path=None, **kw):
        with self._lock:
            if not self.terminal_connected:
                self._last_error = (-10003, "IPC initialize failed, MetaTrader 5 x64 not found")
                return False
            self.connected = True
            self._last_error = (1, "Success")
            return True

    def shutdown(self):
        self.connected = False
        return True

    def last_error(self):
        return self._last_error

    def _guard(self):
        if not self.connected or not self.terminal_connected:
            self._last_error = (-10004, "No IPC connection")
            return False
        return True

    def terminal_info(self):
        if not self._guard():
            return None
        return TerminalInfo(True, True, False, "Synthetic MT5", "MasterQUO synthetic", "SYNTHETIC", 9999, 25000)

    def version(self):
        return (500, 9999, "synthetic")

    def switch_account(self, login: int, server: str = "Synthetic-Demo", trade_mode: int = ACCOUNT_TRADE_MODE_DEMO):
        with self._lock:
            self._accounts.setdefault(login, dict(login=login, server=server, trade_mode=trade_mode, balance=5000.0))
            self._login = login

    def _acct(self):
        return self._accounts[self._login]

    def account_info(self):
        if not self._guard():
            return None
        with self._lock:
            a = self._acct()
            profit = sum(self._pos_profit(p) for p in self._positions.values())
            margin = sum(self._margin(p["volume"], p["price_open"]) for p in self._positions.values())
            eq = a["balance"] + profit
            return AccountInfo(a["login"], a["server"], "MasterQUO Synthetic Ltd", "Synthetic", "USD", a["trade_mode"],
                               ACCOUNT_MARGIN_MODE_RETAIL_HEDGING if self.hedging else ACCOUNT_MARGIN_MODE_RETAIL_NETTING,
                               100, round(a["balance"], 2), round(eq, 2), round(margin, 2), round(eq - margin, 2),
                               round(eq / margin * 100, 2) if margin else 0.0, round(profit, 2), True, True)

    # ------------------------------------------------------------- symbols
    def symbol_select(self, name, enable=True):
        if not self._guard():
            return False
        if self._known(name):
            (self._visible.add if enable else self._visible.discard)(name)
            return True
        self._last_error = (-1, "Terminal: Call failed")
        return False

    def symbols_total(self):
        return len(self.symbols_get() or ())

    def symbols_get(self, group=None):
        if not self._guard():
            return None
        names = [self.symbol, *sorted(self._extra), *sorted(self._markets)]
        if group:
            import fnmatch
            pats = [g for g in group.split(",") if g and not g.startswith("!")]
            names = [n for n in names if any(fnmatch.fnmatch(n, p) for p in pats)]
        return tuple(self.symbol_info(n) for n in names)

    def symbol_info(self, name):
        if not self._guard() or not self._known(name):
            return None
        t = self.symbol_info_tick(name)
        bid = t.bid if t else 0.0
        ask = t.ask if t else 0.0
        if name in self._markets:
            m = self._markets[name]
            d = m["digits"]
            pt = 10.0 ** -d
            return SymbolInfo(name, name in self._visible, name in self._visible, pt, d, pt, 1.0, m.get("contract", 100000.0), 0.01, 100.0, 0.01,
                              10, 5, SYMBOL_TRADE_MODE_FULL, 3, m.get("base_ccy", "EUR"), m.get("profit_ccy", "USD"), m.get("base_ccy", "EUR"),
                              m["spread"], True, m["desc"], m["path"], bid, ask, int(t.time) if t else 0)
        return SymbolInfo(name, name in self._visible, name in self._visible, 0.01, 2, 0.01, 1.0, 100.0, 0.01, 100.0, 0.01,
                          10, 5, SYMBOL_TRADE_MODE_FULL, 3, "XAU", "USD", "USD", 12, True, "Gold vs USD (synthetic)",
                          "Synthetic\\Metals", bid, ask, int(t.time) if t else 0)

    def symbol_info_tick(self, name):
        if not self._guard() or not self._known(name):
            return None
        raw = self._raw_now()
        if name in self._markets:
            m = self._markets[name]
            series = self._market_series(name)
            px = self._price_at(raw, series)
            d, pt = m["digits"], 10.0 ** -m["digits"]
            if px is None:
                mins, m1 = series
                idx = self._m1_upto(raw, mins)
                if idx == 0:
                    return None
                last_t = int(mins[idx - 1]) + 59
                c = round(float(self._to_market(name, m1["close"][idx - 1])), d)
                return Tick(last_t, c, round(c + m["spread"] * pt, d), 0.0, 0, last_t * 1000, 6, 0.0)
            bid = round(float(self._to_market(name, px)), d)
            return Tick(int(raw), bid, round(bid + m["spread"] * pt, d), 0.0, 0, int(raw * 1000), 6, 0.0)
        px = self._price_at(raw)
        if px is None:
            # market closed: last known tick stays (stale)
            idx = self._m1_upto(raw)
            if idx == 0:
                return None
            last_t = int(self._mins[idx - 1]) + 59
            c = float(self._m1["close"][idx - 1])
            return Tick(last_t, round(c, 2), round(c + 0.12, 2), 0.0, 0, last_t * 1000, 6, 0.0)
        if name != self.symbol:
            px = 100.0 + (px - self._start_price) * 0.002
        bid = round(px, 2)
        ask = round(px + 0.12, 2)
        self._check_stops(bid, ask)
        return Tick(int(raw), bid, ask, 0.0, 0, int(raw * 1000), 6, 0.0)

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        if not self._guard() or not self._known(symbol):
            return None
        if symbol in self._markets:
            r = self._rates(timeframe, self._raw_now(), self._market_series(symbol))
        else:
            r = self._rates(timeframe, self._raw_now())
        end = len(r) - start_pos
        if end <= 0:
            return np.zeros(0, dtype=RATE_DTYPE)
        out = r[max(0, end - count):end].copy()
        if symbol in self._markets:
            d = self._markets[symbol]["digits"]
            for k in ("open", "high", "low", "close"):
                out[k] = np.round(self._to_market(symbol, out[k]), d)
            out["spread"] = self._markets[symbol]["spread"]
        elif symbol != self.symbol:
            for k in ("open", "high", "low", "close"):
                out[k] = 100.0 + (out[k] - self._start_price) * 0.002
        return out

    def copy_rates_range(self, symbol, timeframe, date_from, date_to):
        if not self._guard():
            return None
        r = self._rates(timeframe, self._raw_now())
        f = date_from.timestamp() if isinstance(date_from, datetime) else float(date_from)
        t = date_to.timestamp() if isinstance(date_to, datetime) else float(date_to)
        return r[(r["time"] >= f) & (r["time"] <= t)].copy()

    # ------------------------------------------------------------- trading
    def _margin(self, volume, price):
        return volume * 100.0 * price / 100.0

    def _pos_profit(self, p):
        t = self._last_quote()
        if t is None:
            return 0.0
        bid, ask = t
        close = bid if p["type"] == POSITION_TYPE_BUY else ask
        sign = 1 if p["type"] == POSITION_TYPE_BUY else -1
        return sign * (close - p["price_open"]) * 100.0 * p["volume"]

    def _last_quote(self):
        px = self._price_at(self._raw_now())
        if px is None:
            return None
        return round(px, 2), round(px + 0.12, 2)

    def positions_get(self, symbol=None, ticket=None, group=None):
        if not self._guard():
            return None
        with self._lock:
            out = []
            for p in self._positions.values():
                if symbol and p["symbol"] != symbol:
                    continue
                if ticket and p["ticket"] != ticket:
                    continue
                q = self._last_quote()
                cur = (q[0] if p["type"] == POSITION_TYPE_BUY else q[1]) if q else p["price_open"]
                out.append(Position(p["ticket"], p["time"], p["time"] * 1000, p["type"], p["magic"], p["ticket"], p["volume"],
                                    p["price_open"], p["sl"], p["tp"], cur, 0.0, round(self._pos_profit(p), 2), p["symbol"], p["comment"]))
            return tuple(out)

    def orders_get(self, symbol=None, ticket=None, group=None):
        return () if self._guard() else None

    def history_deals_get(self, date_from=None, date_to=None, position=None, ticket=None, group=None):
        if not self._guard():
            return None
        with self._lock:
            ds = list(self._deals)
        if position is not None:
            return tuple(d for d in ds if d.position_id == position)
        if ticket is not None:
            return tuple(d for d in ds if d.ticket == ticket)
        f = date_from.timestamp() if isinstance(date_from, datetime) else (date_from or 0)
        t = date_to.timestamp() if isinstance(date_to, datetime) else (date_to or 4e9)
        return tuple(d for d in ds if f <= d.time <= t)

    def history_orders_get(self, date_from=None, date_to=None, ticket=None, position=None, group=None):
        return () if self._guard() else None

    def order_calc_profit(self, action, symbol, volume, price_open, price_close):
        if not self._guard():
            return None
        sign = 1 if action == ORDER_TYPE_BUY else -1
        return round(sign * (price_close - price_open) * 100.0 * volume, 2)

    def order_calc_margin(self, action, symbol, volume, price):
        if not self._guard():
            return None
        return round(self._margin(volume, price), 2)

    def order_check(self, request):
        if not self._guard():
            return None
        a = self.account_info()
        m = self._margin(request["volume"], request.get("price") or 0)
        rc = 0 if m < a.margin_free else TRADE_RETCODE_NO_MONEY
        return OrderCheck(rc, a.balance, a.equity, a.profit, m, a.margin_free - m, 0.0, "Done" if rc == 0 else "No money", request)

    def _deal(self, order, typ, entry, pos_id, volume, price, profit, comment, magic):
        self._ticket += 1
        raw = int(self._raw_now())
        d = Deal(self._ticket, order, raw, raw * 1000, typ, entry, magic, pos_id, volume, price,
                 -round(self.commission * volume, 2), 0.0, round(profit, 2), 0.0, self.symbol, comment, 3)
        self._deals.append(d)
        self._acct()["balance"] += d.profit + d.commission
        return d

    def order_send(self, request):
        if not self._guard():
            return None
        if self.hang_order_send:
            raise TimeoutError("SIMULATED_TERMINAL_HANG")
        with self._lock:
            if self.fail_next_order is not None:
                rc, self.fail_next_order = self.fail_next_order, None
                return OrderResult(rc, 0, 0, 0.0, 0.0, 0.0, 0.0, "Rejected (simulated)", 1, 0, request)
            q = self._last_quote()
            if q is None:
                return OrderResult(TRADE_RETCODE_MARKET_CLOSED, 0, 0, 0.0, 0.0, 0.0, 0.0, "Market closed", 1, 0, request)
            bid, ask = q
            if request["action"] == TRADE_ACTION_SLTP:
                p = self._positions.get(request["position"])
                if p is None:
                    return OrderResult(TRADE_RETCODE_REJECT, 0, 0, 0, 0, bid, ask, "Position not found", 1, 0, request)
                p["sl"], p["tp"] = request.get("sl", p["sl"]), request.get("tp", p["tp"])
                return OrderResult(TRADE_RETCODE_DONE, 0, 0, 0, 0, bid, ask, "Request executed", 1, 0, request)
            self._ticket += 1
            order = self._ticket
            typ = request["type"]
            price = ask if typ == ORDER_TYPE_BUY else bid
            vol = float(request["volume"])
            magic = int(request.get("magic", 0))
            comment = str(request.get("comment", ""))[:31]
            pos_ticket = request.get("position")
            if pos_ticket:  # closing (partial) an existing position
                p = self._positions.get(pos_ticket)
                if p is None:
                    return OrderResult(TRADE_RETCODE_REJECT, 0, order, 0, 0, bid, ask, "Position not found", 1, 0, request)
                vol = min(vol, p["volume"])
                sign = 1 if p["type"] == POSITION_TYPE_BUY else -1
                profit = sign * (price - p["price_open"]) * 100.0 * vol
                d = self._deal(order, typ, DEAL_ENTRY_OUT, pos_ticket, vol, price, profit, comment, p["magic"])
                p["volume"] = round(p["volume"] - vol, 2)
                if p["volume"] <= 1e-9:
                    del self._positions[pos_ticket]
                return OrderResult(TRADE_RETCODE_DONE, d.ticket, order, vol, price, bid, ask, "Request executed", 1, 0, request)
            sl, tp = float(request.get("sl") or 0), float(request.get("tp") or 0)
            if (typ == ORDER_TYPE_BUY and ((sl and sl >= bid - 0.10) or (tp and tp <= ask + 0.10))) or \
               (typ == ORDER_TYPE_SELL and ((sl and sl <= ask + 0.10) or (tp and tp >= bid - 0.10))):
                return OrderResult(TRADE_RETCODE_INVALID_STOPS, 0, order, 0, 0, bid, ask, "Invalid stops", 1, 0, request)
            raw = int(self._raw_now())
            ticket = order
            self._positions[ticket] = dict(ticket=ticket, time=raw, type=POSITION_TYPE_BUY if typ == ORDER_TYPE_BUY else POSITION_TYPE_SELL,
                                           magic=magic, volume=vol, price_open=price, sl=sl, tp=tp, symbol=self.symbol, comment=comment)
            d = self._deal(order, typ, DEAL_ENTRY_IN, ticket, vol, price, 0.0, comment, magic)
            return OrderResult(TRADE_RETCODE_DONE, d.ticket, order, vol, price, bid, ask, "Request executed", 1, 0, request)

    def _check_stops(self, bid, ask):
        with self._lock:
            for t, p in list(self._positions.items()):
                hit = None
                if p["type"] == POSITION_TYPE_BUY:
                    if p["sl"] and bid <= p["sl"]:
                        hit = p["sl"]
                    elif p["tp"] and bid >= p["tp"]:
                        hit = p["tp"]
                else:
                    if p["sl"] and ask >= p["sl"]:
                        hit = p["sl"]
                    elif p["tp"] and ask <= p["tp"]:
                        hit = p["tp"]
                if hit is not None:
                    sign = 1 if p["type"] == POSITION_TYPE_BUY else -1
                    profit = sign * (hit - p["price_open"]) * 100.0 * p["volume"]
                    self._deal(0, DEAL_TYPE_SELL if sign > 0 else DEAL_TYPE_BUY, DEAL_ENTRY_OUT, t, p["volume"], hit, profit, "[sl/tp]", p["magic"])
                    del self._positions[t]


def make_fake_module(**kw) -> FakeMT5:
    return FakeMT5(**kw)


def is_fake(module) -> bool:
    return isinstance(module, FakeMT5)


# Expose module-level constants as attributes, like the real MetaTrader5 module.
for _name, _val in list(globals().items()):
    if _name.isupper() and isinstance(_val, int):
        setattr(FakeMT5, _name, _val)
