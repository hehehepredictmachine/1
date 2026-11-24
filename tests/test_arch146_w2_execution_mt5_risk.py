"""Arch 1.46, fala 2b, grupa execution_mt5_risk: wykonanie (menedżer pozycji, gateway, panel ręczny), most MT5, ryzyko, SH executor.

Poziom jednostkowy (stub mostu + prawdziwa Database / ConfigStore w izolowanym katalogu danych) albo syntetyczny terminal (FakeMT5).
Żadnego order_send do prawdziwego terminala, bez serwera demo.
"""
from __future__ import annotations

import json
import threading
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

import _env  # noqa: F401
from _env import UTC, TempData, core


class StubBridge:
    """Tyle MarketBridge, ile potrzebuje menedżer: listy pod _lock, zegar mostu (now), offset serwera, raw_call."""

    def __init__(self):
        self._lock = threading.RLock()
        self.deals: list = []
        self.positions: list = []
        self.deals_loaded_at = None
        self.account_key = "srv:1"
        self.session_epoch = 1
        self.state = "CONNECTED"
        self.symbol_info = {"point": 0.01, "trade_tick_size": 0.01, "digits": 2, "volume_min": 0.01, "volume_step": 0.01, "volume_max": 5.0}
        self.q: dict | None = {"bid": 2000.0, "ask": 2000.2, "age_seconds": 0.1, "time_utc": None}
        self.clock = SimpleNamespace(offset=10800)
        self.account = {"currency": "USD", "equity": 10000.0, "balance": 10000.0}
        self.t = datetime.now(UTC)
        self.raw_results: list = []
        self.requests: list = []
        self.reloads = 0

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t = self.t + timedelta(seconds=seconds)

    def load_deals(self, deals=None):
        """Nowe przeładowanie historii (deals_loaded_at = teraz wg zegara mostu)."""
        if deals is not None:
            self.deals = deals
        self.advance(1)
        self.deals_loaded_at = self.t

    def request_deals_reload(self):
        self.reloads += 1

    def quote_status(self):
        return dict(self.q) if self.q else None

    def calc_profit(self, side, vol, o, c):
        return round((c - o) * 100.0 * vol * (1 if side == "BUY" else -1), 2)

    def account_status(self):
        return dict(self.account)

    def raw_call(self, fn, prio=0, timeout=None):
        m = SimpleNamespace(TRADE_ACTION_DEAL=1, TRADE_ACTION_SLTP=6, ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, ORDER_TIME_GTC=0,
                            ORDER_FILLING_FOK=0, ORDER_FILLING_IOC=1, symbol_info_tick=lambda s: SimpleNamespace(bid=self.q["bid"], ask=self.q["ask"]),
                            order_send=lambda r: self.requests.append(r) or (self.raw_results.pop(0) if self.raw_results else None),
                            positions_get=lambda ticket=None: [SimpleNamespace(**p) for p in self.positions if ticket is None or p["ticket"] == ticket])
        r = fn(m)
        if isinstance(r, Exception):
            raise r
        return r


class Modes:
    def __init__(self, mode="AUTO_DEMO"):
        self.mode = mode

    def gate(self, account_key, **kw):
        return {"mode": self.mode, "allowed": True, "reason_codes": []}


class _MgrBase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.events import AppLog, EventBus
        from masterquo.execution.manager import PositionManager
        from masterquo.execution.paper import PaperBroker
        self.cfg = ConfigStore()
        self.cfg.update({"costs": {"commission_mode": "CONFIGURED", "commission_per_lot_per_side": 3.0}})
        self.db = Database()
        self.bus = EventBus()
        self.log = AppLog(self.db, self.bus)
        self.b = StubBridge()
        self.modes = Modes()
        self.paper = PaperBroker(self.cfg, self.b, self.db, self.bus, self.log)
        self.mgr = PositionManager(self.cfg, self.b, self.db, self.bus, self.log, self.modes, self.paper)

    def tearDown(self):
        self.td.close()

    def mt5_row(self, ticket=1001, opened_min_ago=20, **extra):
        opened = (datetime.now(UTC) - timedelta(minutes=opened_min_ago)).isoformat().replace("+00:00", "Z")
        row = {"position_key": f"AUTO_DEMO:srv:1:{ticket}", "mode": "AUTO_DEMO", "account_key": "srv:1", "position_ticket": ticket,
               "attempt_id": "A1", "decision_id": "D1", "setup_id": "S1", "strategy_id": "XAU-S01", "symbol": "XAUUSD-", "side": "BUY",
               "volume_initial": 0.1, "volume_open": 0.1, "entry_price": 2000.0, "sl": 1990.0, "tp2": 2010.0, "state": "OPEN",
               "opened_at": opened, "planned_risk_money": 100.0}
        row.update(extra)
        cols = ",".join(row)
        self.db.execute(f"INSERT INTO managed_positions({cols}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
        return self.db.one("SELECT * FROM managed_positions WHERE position_key=?", (row["position_key"],))

    def row(self, ticket=1001):
        return self.db.one("SELECT * FROM managed_positions WHERE position_ticket=?", (ticket,))

    def trade(self, ticket=1001):
        return self.db.one("SELECT * FROM trades WHERE position_ticket=?", (ticket,))


RAW0 = 1_795_000_000


def d_in(vol=0.1, t=RAW0 - 3600, ticket=1001):
    return {"position_id": ticket, "entry": 0, "volume": vol, "price": 2000.0, "time": t, "profit": 0.0, "commission": -0.3}


def d_out(vol, price, profit, t, ticket=1001):
    return {"position_id": ticket, "entry": 1, "volume": vol, "price": price, "time": t, "profit": profit, "commission": -0.15}


# ------------------------------------------------------------------------------------------------ I0807 (dzienna strata, Close By)
class TestDailyLossCloseBy(unittest.TestCase):
    def test_daily_loss_counts_close_by_losses(self):
        from masterquo.risk.engine import daily_loss_used
        d = daily_loss_used([{"type": 1, "entry": 3, "time": 100, "profit": -500.0}], 0, floating=0.0)
        self.assertEqual(d["used"], 500.0)                                     # przed: 0.0 (OUT_BY pomijany)
        self.assertEqual(d["realized_today"], -500.0)

    def test_close_by_profit_never_reduces_used(self):
        from masterquo.risk.engine import daily_loss_used
        deals = [{"type": 1, "entry": 1, "time": 100, "profit": -200.0},
                 {"type": 0, "entry": 3, "time": 110, "profit": 300.0}, {"type": 1, "entry": 3, "time": 110, "profit": -50.0}]
        d = daily_loss_used(deals, 0, floating=0.0)
        self.assertEqual(d["used"], 200.0)                                     # zysk netto z Close By nie zmniejsza zużycia
        old_day = daily_loss_used([{"type": 1, "entry": 3, "time": 10, "profit": -500.0}], 50, floating=0.0)
        self.assertEqual(old_day["used"], 0.0)                                 # deal sprzed początku dnia - bez zmian

    def test_close_by_loss_tightens_the_risk_gate(self):
        import test_risk_execution as TR
        t = TR.TestRisk("test_spread_not_double_counted_and_rr_net")
        t.setUp()
        try:
            base = t.ev(deals=[])
            hit = t.ev(deals=[{"type": 1, "entry": 3, "time": 10, "profit": -600.0}])
        finally:
            t.tearDown()
        self.assertNotIn("DAILY_STOP", base["reason_codes"])
        self.assertIn("DAILY_STOP", hit["reason_codes"])                       # przed: strata Close By niewidoczna dla DAILY_STOP


# ------------------------------------------------------------------------------------------------ I0735 (prowizja z historii)
def _deal(entry, comm, vol=1.0, fee=0.0, sym="XAUUSD-"):
    return {"symbol": sym, "type": 0, "entry": entry, "volume": vol, "commission": comm, "fee": fee}


class TestCommissionFromHistoryPartial(unittest.TestCase):
    def test_close_only_tariff_with_few_closings_is_not_zero(self):
        from masterquo.risk.costs import commission_from_history
        r = commission_from_history([_deal(0, 0.0)] * 4 + [_deal(1, -7.0)] * 2, "XAUUSD-")
        self.assertEqual(r["per_lot_per_side"], 7.0)                           # przed: 0.0 (mediana wszystkich deali)
        self.assertEqual(r["source"], "DEAL_HISTORY_PARTIAL_CONSERVATIVE")
        self.assertEqual(r["tariff"], "UNRESOLVED")

    def test_only_free_openings_is_unresolved_not_zero(self):
        from masterquo.risk.costs import commission_from_history
        r = commission_from_history([_deal(0, 0.0)] * 3, "XAUUSD-")
        self.assertIsNone(r["per_lot_per_side"])                               # przed: 0.0 jako znana prowizja
        self.assertEqual(r["source"], "DEAL_HISTORY_UNRESOLVED_ZERO")

    def test_fee_is_part_of_the_cost(self):
        from masterquo.risk.costs import commission_from_history
        r = commission_from_history([_deal(0, -3.0, fee=-1.0)] * 3 + [_deal(1, -3.0, fee=-1.0)] * 3, "XAUUSD-")
        self.assertEqual(r["per_lot_per_side"], 4.0)                           # przed: 3.0 (fee pominięte)
        r = commission_from_history([_deal(0, -3.0, fee=-1.0)] * 3, "XAUUSD-")
        self.assertEqual(r["per_lot_per_side"], 4.0)

    def test_never_below_the_former_median_and_resolved_branch_unchanged(self):
        from masterquo.risk.costs import commission_from_history
        r = commission_from_history([_deal(0, -3.5)] * 3 + [_deal(1, -3.5)] * 3, "XAUUSD-")
        self.assertEqual((r["per_lot_per_side"], r["source"], r["tariff"]), (3.5, "DEAL_HISTORY_IN_OUT_MEDIAN", "PER_SIDE"))
        r = commission_from_history([_deal(0, -2.0)] * 2 + [_deal(1, -5.0)] * 3, "XAUUSD-")
        self.assertGreaterEqual(r["per_lot_per_side"], 5.0)                    # mediana wszystkich = 5.0
        self.assertIsNone(commission_from_history([_deal(0, -3.0)] * 2, "XAUUSD-")["per_lot_per_side"])   # < min_samples - bez zmian

    def test_unresolved_zero_falls_back_without_loosening_the_manual_pad(self):
        from masterquo.execution.manual import COMMISSION_SOURCE
        from masterquo.risk.costs import resolve_commission
        cfg = SimpleNamespace(commission_mode="FROM_DEAL_HISTORY", commission_per_lot_per_side=3.0)
        r = resolve_commission(cfg, [_deal(0, 0.0)] * 3, "XAUUSD-")
        self.assertEqual(r["per_lot_per_side"], 3.0)                           # przed: 0.0 (DEAL_HISTORY_MEDIAN)
        self.assertNotIn(r["source"], COMMISSION_SOURCE)                       # panel ręczny: UNKNOWN jak przy DEAL_HISTORY_MEDIAN
        self.assertNotIn("DEAL_HISTORY_MEDIAN", COMMISSION_SOURCE)
        cfg0 = SimpleNamespace(commission_mode="FROM_DEAL_HISTORY", commission_per_lot_per_side=None)
        self.assertIsNone(resolve_commission(cfg0, [_deal(0, 0.0)] * 3, "XAUUSD-")["per_lot_per_side"])   # blokada w silniku
        r = resolve_commission(cfg, [_deal(0, -3.0)] * 2, "XAUUSD-")
        self.assertEqual(r["source"], "CONFIGURED_FALLBACK")                   # zwykła za krótka historia - bez zmian


# ------------------------------------------------------------------------------------------------ I0711 / I0712 / I0726 / I0793 (rozliczenie MT5)
class TestSettlementWaitsForFreshDeals(_MgrBase):
    def test_partial_tp_then_sl_is_not_settled_from_stale_deals(self):
        self.mt5_row(1001)
        self.b.load_deals([d_in(), d_out(0.05, 2005.0, 25.0, RAW0)])                 # lista sprzed zniknięcia: tylko TP1
        self.mgr._manage_mt5_positions()                                              # pozycja zniknęła z terminala
        self.assertEqual(self.row()["state"], "OPEN")                                 # przed: CLOSED, volume 0.05 (strata SL pominięta)
        self.assertIsNone(self.trade())
        self.assertEqual(self.b.reloads, 1)                                           # wymuszone przeładowanie historii
        self.b.load_deals()                                                           # nowa lista, nadal bez zamknięcia reszty
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.row()["state"], "OPEN")
        self.b.load_deals([d_in(), d_out(0.05, 2005.0, 25.0, RAW0), d_out(0.05, 1990.0, -50.0, RAW0 + 60)])
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.row()["state"], "CLOSED")
        tr = self.trade()
        self.assertAlmostEqual(tr["volume"], 0.1)
        self.assertAlmostEqual(tr["net_pnl"], round(25.0 - 50.0 - 0.3 - 0.3, 2))
        self.assertEqual(self.b.requests, [])                                         # nic nie wysłano do MT5

    def test_incomplete_history_is_settled_after_the_limit(self):
        self.mt5_row(1001)
        self.b.load_deals([d_in(), d_out(0.05, 2005.0, 25.0, RAW0)])
        self.mgr._manage_mt5_positions()
        for _ in range(2):
            self.b.load_deals()
            self.mgr._manage_mt5_positions()
        self.assertEqual(self.row()["state"], "OPEN")
        self.b.advance(601)
        self.b.load_deals()
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.row()["state"], "CLOSED")                               # strata spoza okna historii nie znika z trades
        self.assertAlmostEqual(self.trade()["volume"], 0.05)
        self.assertIn("HISTORY_INCOMPLETE", json.loads(self.row()["exit_note"])["missing"]["settle_flags"])

    def test_position_back_in_terminal_resets_the_wait(self):
        self.mt5_row(1001)
        self.b.load_deals([d_in()])
        self.mgr._manage_mt5_positions()
        self.assertIn("missing", json.loads(self.row()["exit_note"]))
        self.b.q = None                                                               # bez kwotacji: tylko rekoncyliacja, bez zarządzania
        self.b.positions = [{"ticket": 1001, "volume": 0.1, "sl": 1990.0, "tp": 2010.0, "magic": 0}]
        self.mgr._manage_mt5_positions()
        self.assertNotIn("missing", json.loads(self.row()["exit_note"]))

    def test_old_position_not_unsettled_before_deals_reload(self):
        self.mt5_row(1001, opened_min_ago=11)
        self.b.load_deals([d_in()])
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.row()["state"], "OPEN")                                 # przed: CLOSED_UNSETTLED od razu (10 min od opened_at)
        self.b.load_deals()
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.row()["state"], "OPEN")                                 # < 10 min od zniknięcia
        self.b.advance(601)
        self.b.load_deals()
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.row()["state"], "CLOSED_UNSETTLED")

    def test_closed_unsettled_is_settled_when_deals_appear(self):
        self.mt5_row(1001, state="CLOSED_UNSETTLED", closed_at=(datetime.now(UTC) - timedelta(minutes=30)).isoformat().replace("+00:00", "Z"))
        self.b.load_deals([d_in()])
        self.mgr.tick()
        self.assertEqual(self.row()["state"], "CLOSED_UNSETTLED")
        self.b.load_deals([d_in(), d_out(0.1, 1990.0, -100.0, RAW0)])
        self.mgr.tick()
        self.assertEqual(self.row()["state"], "CLOSED")                               # przed: CLOSED_UNSETTLED na zawsze, brak trades
        tr = self.trade()
        from masterquo.timeutil import from_epoch, iso
        self.assertEqual(tr["closed_at"], iso(from_epoch(RAW0 - 10800)))
        self.assertAlmostEqual(tr["net_pnl"], round(-100.0 - 0.3 - 0.15, 2))
        self.assertEqual(self.b.requests, [])

    def test_closed_unsettled_never_overwrites_trades_nor_comes_back(self):
        self.mt5_row(1001, state="CLOSED_UNSETTLED", closed_at="2026-11-20T10:00:00Z")
        self.db.execute("INSERT INTO trades(trade_id, mode, source, account_key, position_ticket, symbol, side, volume, closed_at, gross_pnl, "
                        "commission, swap, fee, net_pnl, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("AUTO_DEMO-srv:1-1001", "AUTO_DEMO", "BOT", "srv:1", 1001, "XAUUSD-", "BUY", 0.1, "2026-11-20T10:00:00Z", 12.0, 0.0, 0.0, 0.0,
                         12.0, "CLOSED"))
        self.b.load_deals([d_in(), d_out(0.1, 1990.0, -100.0, RAW0)])
        self.mgr.tick()
        self.assertEqual(self.trade()["net_pnl"], 12.0)                               # istniejący wiersz nie jest nadpisany
        self.mt5_row(1002, state="CLOSED_UNSETTLED", closed_at="2026-11-20T10:00:00Z")
        self.b.positions = [{"ticket": 1002, "volume": 0.1, "sl": 1990.0, "tp": 2010.0, "magic": 0}]
        self.b.load_deals()
        self.mgr.tick()
        self.assertEqual(self.row(1002)["state"], "CLOSED_UNSETTLED")                 # nigdy z powrotem do OPEN, bez zarządzania
        self.assertEqual(self.b.requests, [])

    def test_unknown_server_offset_is_not_taken_as_zero(self):
        self.mt5_row(1001)
        self.b.clock.offset = None
        self.b.load_deals([d_in(), d_out(0.1, 2005.0, 50.0, RAW0)])
        self.mgr._manage_mt5_positions()
        self.b.load_deals()
        self.mgr._manage_mt5_positions()
        self.assertIsNone(self.trade())                                               # przed: closed_at = czas serwera jako UTC
        self.assertEqual(self.row()["state"], "OPEN")
        self.b.clock.offset = 10800
        self.mgr._manage_mt5_positions()
        from masterquo.timeutil import from_epoch, iso
        self.assertEqual(self.trade()["closed_at"], iso(from_epoch(RAW0 - 10800)))

    def test_unknown_offset_wait_is_bounded(self):
        self.mt5_row(1001)
        self.b.clock.offset = None
        self.b.load_deals([d_in(), d_out(0.1, 1990.0, -100.0, RAW0)])
        self.mgr._manage_mt5_positions()
        first = json.loads(self.row()["exit_note"])["missing"]["first_missing_at"]
        self.b.advance(301)
        self.b.load_deals()
        self.mgr._manage_mt5_positions()
        tr = self.trade()
        self.assertIsNotNone(tr)                                                      # strata nie zostaje poza trades
        self.assertEqual(tr["closed_at"], first)
        self.assertIn("CLOSED_AT_OBSERVED", json.loads(self.row()["exit_note"])["missing"]["settle_flags"])

    def test_no_settlement_before_deal_history_is_loaded(self):
        self.mt5_row(1001, opened_min_ago=30)
        self.b.positions, self.b.deals, self.b.deals_loaded_at = [], [], None        # zmiana konta / start: listy niewczytane
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.row()["state"], "OPEN")                                 # przed: CLOSED_UNSETTLED
        self.assertIsNone(self.row()["exit_note"])


# ------------------------------------------------------------------------------------------------ I0793 (most: zmiana konta)
class TestBridgeAccountSwitch(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.b = core()

    def tearDown(self):
        self.worker.stop()
        self.td.close()

    def test_switch_refreshes_symbol_and_deals(self):
        b = self.b
        events = []
        b.add_listener(lambda k, d: events.append(k))
        b.connect()
        b._poll_account()
        b._poll_deals()
        with b._lock:
            b.deals.append({"ticket": -1, "position_id": -1})                         # wartownik: deal poprzedniego konta
            b.symbol_info["sentinel"] = True                                          # wartownik: metadane poprzedniego brokera
        epoch = b.session_epoch
        self.fake.switch_account(7770001)
        b._poll_account()
        self.assertTrue(b.account_key.endswith(":7770001"))
        self.assertGreater(b.session_epoch, epoch)
        self.assertNotIn("sentinel", b.symbol_info)                                   # przed: do ponownego połączenia
        self.assertFalse(any(d.get("ticket") == -1 for d in b.deals))                 # przed: do history_poll_seconds
        self.assertIsNotNone(b.deals_loaded_at)
        self.assertIn("account_changed", events)

    def test_reconnect_to_another_account_drops_the_old_lists(self):
        b = self.b
        b.connect()
        b._poll_account()
        b._poll_deals()
        with b._lock:
            b.deals.append({"ticket": -1, "position_id": -1})
        self.fake.switch_account(7770003)
        b.connect()
        self.assertTrue(b.account_key.endswith(":7770003"))
        self.assertEqual((b.deals, b.positions, b.deals_loaded_at), ([], [], None))  # przed: deale poprzedniego konta + loaded_at
        b._poll_account()
        b._poll_deals()
        self.assertIsNotNone(b.deals_loaded_at)

    def test_failed_reload_after_switch_forces_a_reconnect(self):
        from masterquo.mt5.bridge import BridgeError
        b = self.b
        events = []
        b.add_listener(lambda k, d: events.append(k))
        b.connect()
        b._poll_account()

        def boom():
            raise BridgeError("SYMBOL_NOT_FOUND:X")
        b._check_symbol = boom
        self.fake.switch_account(7770002)
        with self.assertRaises(BridgeError):
            b._poll_account()
        self.assertEqual(b.state, "RECONNECTING")
        self.assertIn("account_changed", events)
        self.assertEqual((b.deals, b.positions, b.deals_loaded_at), ([], [], None))


# ------------------------------------------------------------------------------------------------ I0734 (most: ponowne połączenie w trakcie connect)
class TestBridgeReconnectDuringConnect(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.b = core()

    def tearDown(self):
        self.worker.stop()
        self.td.close()

    def test_request_inside_connect_is_not_lost(self):
        b = self.b
        events = []
        b.add_listener(lambda k, d: events.append(k))
        orig = b._load_all_history

        def load(*a, **k):
            b.request_reconnect("ACTIVE_ASSET_CHANGED")                               # API w trakcie ładowania historii
            return orig(*a, **k)
        b._load_all_history = load
        b.connect()
        self.assertEqual(b.state, "RECONNECTING")                                     # przed: CONNECTED (żądanie przepadło)
        self.assertNotIn("connected", events)
        b._load_all_history = orig
        b.connect()
        self.assertEqual(b.state, "CONNECTED")

    def test_history_of_one_symbol(self):
        b = self.b
        b.connect()
        first = b.cfg.symbol
        asked = []
        orig = b._fetch

        def fetch(sym, tf, n):
            asked.append(sym)
            if len(asked) == 1:                                                       # użytkownik zmienia aktywo w trakcie
                self.cfg.update({"mt5": {"symbol": "XAUUSD.x"}, "assets": {"mappings": {"XAUUSD": {"broker_symbol": "XAUUSD.x", "status": "USER_SPECIFIED"}}}})
            return orig(first, tf, n)
        b._fetch = fetch
        b._load_dxy = lambda: None
        b.connect()
        self.assertEqual(set(asked), {first})                                         # przed: TF ładowane z dwóch symboli
        self.assertEqual(b.buffer_symbol, first)
        self.assertEqual(b.state, "RECONNECTING")                                     # dane starego symbolu nie są CONNECTED


# ------------------------------------------------------------------------------------------------ I0725 (tryb wykonania czytany po walidacji)
class _ExecBase(unittest.TestCase):
    """Bramka wykonania na syntetycznym terminalu (setUp/tearDown jak test_risk_execution.TestExecution)."""

    def setUp(self):
        import test_risk_execution as TR
        self.TR = TR
        TR.TestExecution.setUp(self)
        self.sent = []
        self._orig_send = self.fake.order_send
        self.fake.order_send = lambda r: self.sent.append(r) or self._orig_send(r)

    def tearDown(self):
        self.TR.TestExecution.tearDown(self)

    def decision(self, **kw):
        return self.TR.TestExecution.decision(self, **kw)

    def auto_demo(self):
        acct = self.b.account_status()
        self.modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)

    def switch_after_validation(self, fn):
        orig = self.gw._validate

        def wrapped(did):
            out = orig(did)
            fn()
            return out
        self.gw._validate = wrapped


class TestModeRaceInExecute(_ExecBase):
    def test_switch_to_signals_after_validation_sends_nothing(self):
        self.auto_demo()
        self.engine.decision = self.decision()
        self.switch_after_validation(lambda: self.modes.set_mode("SIGNALS", account=None, account_key=None, synthetic=True))
        r = self.gw.execute("MQD-1")
        self.assertEqual(r, {"status": "BLOCKED", "reason": "MODE_CHANGED_DURING_EXECUTION"})   # przed: order_send w trybie SIGNALS
        self.assertEqual(self.sent, [])
        self.assertIsNone(self.db.one("SELECT * FROM order_attempts"))

    def test_switch_from_paper_to_demo_after_validation_sends_nothing(self):
        self.modes.set_mode("PAPER", confirm="PAPER", account=self.b.account_status(), account_key=self.b.account_key, synthetic=True)
        self.engine.decision = self.decision()
        self.switch_after_validation(self.auto_demo)
        r = self.gw.execute("MQD-1")
        self.assertEqual(r["status"], "BLOCKED")                                       # przed: order_send bez walidacji ścieżki MT5
        self.assertEqual(self.sent, [])
        self.assertIsNone(self.db.one("SELECT * FROM managed_positions"))

    def test_reservation_released_when_blocked(self):
        calls = []
        self.gw.arc = SimpleNamespace(intents=SimpleNamespace(
            open=lambda **kw: {"status": "RESERVED", "intent": {"intent_id": "INT-1"}},
            outcome=lambda iid, res: calls.append((iid, res["status"])), sent=lambda *a: None))
        self.auto_demo()
        self.engine.decision = self.decision()
        self.switch_after_validation(lambda: self.modes.set_kill(True, "TEST"))
        self.assertEqual(self.gw.execute("MQD-1")["status"], "BLOCKED")
        self.assertEqual(calls, [("INT-1", "BLOCKED")])
        self.assertEqual(self.sent, [])

    def test_real_position_keeps_the_mode_it_was_sent_under(self):
        self.auto_demo()
        self.engine.decision = self.decision()
        acct = self.b.account_status()

        def send_then_switch(r):
            res = self._orig_send(r)
            self.modes.set_mode("PAPER", confirm="PAPER", account=acct, account_key=self.b.account_key, synthetic=True)
            return res
        self.fake.order_send = send_then_switch
        self.assertEqual(self.gw.execute("MQD-1")["status"], "FILLED")
        mp = self.db.one("SELECT mode, position_key FROM managed_positions")
        self.assertEqual(mp["mode"], "AUTO_DEMO")                                       # przed: 'PAPER' dla realnej pozycji
        self.assertTrue(mp["position_key"].startswith("AUTO_DEMO:"))

    def test_unchanged_mode_still_executes(self):
        self.auto_demo()
        self.engine.decision = self.decision()
        self.assertEqual(self.gw.execute("MQD-1")["status"], "FILLED")
        self.assertEqual(len(self.sent), 1)


# ------------------------------------------------------------------------------------------------ I0727 / I0782 / I0783 (panel ręczny)
class _PadBase(unittest.TestCase):
    """Panel ręczny na syntetycznym terminalu (jak test_audit_146_b_core_exec_2.TestManualPad146)."""

    def setUp(self):
        import test_risk_execution as TR
        from _env import wait_for
        self.wait_for = wait_for
        self.td = TempData()
        cfg, db, bus, log, fake, worker, b = core()
        self.cfg, self.db, self.fake, self.worker, self.b = cfg, db, fake, worker, b
        cfg.update({"risk": TR.LIMITS, "costs": {"commission_mode": "CONFIGURED", "commission_per_lot_per_side": 3.0}})
        b.start()
        self.assertTrue(wait_for(lambda: b.state == "CONNECTED" and b.quote_status() and b.symbol_info, 40))
        from masterquo.engine.lifecycle import LifecycleStore
        from masterquo.execution.gateway import ExecutionGateway
        from masterquo.execution.manager import PositionManager
        from masterquo.execution.manual import ManualPad
        from masterquo.execution.modes import ModeManager
        from masterquo.execution.paper import PaperBroker
        self.modes = ModeManager(cfg, db, bus, log, account_provider=lambda: (b.account_status(), b.account_key, b.synthetic))
        self.paper = PaperBroker(cfg, b, db, bus, log)
        self.gw = ExecutionGateway(cfg, b, db, bus, log, self.modes, TR.StubEngine(LifecycleStore(db)), self.paper)
        self.mgr = self.gw.manager = PositionManager(cfg, b, db, bus, log, self.modes, self.paper)
        self.mgr.reconciled_epoch = b.session_epoch
        self.pad = ManualPad(cfg, b, db, bus, log, self.modes, self.paper, self.gw, ttl_s=60)
        self.sent = []
        self._orig_send = self.fake.order_send
        self.fake.order_send = lambda r: self.sent.append(r) or self._orig_send(r)
        self.modes.set_mode("PAPER", account=None, account_key=None, synthetic=True)

    def tearDown(self):
        self.b.stop()
        self.worker.stop()
        self.td.close()

    def body(self, **kw):
        q = self.b.quote_status()
        return dict({"side": "BUY", "sl": q["ask"] - 5, "tp": q["ask"] + 10, "sizing_mode": "FIXED", "lots": 0.05}, **kw)

    def auto_demo(self):
        acct = self.b.account_status()
        self.modes.set_mode("AUTO_DEMO", confirm=str(acct["login"]), account=acct, account_key=self.b.account_key, synthetic=True)


class TestManualUnknownReconcile(_PadBase):
    def test_unknown_manual_entry_is_found_by_tag(self):
        self.auto_demo()
        it = self.pad.create_intent(self.pad.plan(self.body())["plan_id"])

        def executes_but_no_answer(r):
            self.sent.append(r)
            self._orig_send(r)                                                        # broker wykonał, odpowiedź (None) nie dotarła
        self.fake.order_send = executes_but_no_answer
        r = self.pad.execute(it["intent_id"])
        self.assertEqual(r["status"], "UNKNOWN", r)
        att = self.db.one("SELECT * FROM order_attempts WHERE attempt_id=?", (r["attempt_id"],))
        self.assertEqual(att["client_tag"], self.sent[0]["comment"])                  # przed: 'MQM:...' != komentarz 'MQ:MTI-...'
        self.b._t_account = 0
        self.assertTrue(self.wait_for(lambda: bool(self.b.positions), 15))
        self.assertEqual(self.pad.reconcile()["reconciled"], [r["idempotency_key"]])   # przed: []
        self.mgr._resolve_unknown()
        self.assertEqual(self.db.one("SELECT state FROM order_attempts WHERE attempt_id=?", (r["attempt_id"],))["state"], "FILLED")
        rows = self.db.query("SELECT * FROM managed_positions WHERE decision_id=?", (it["intent_id"],))
        self.assertEqual(len(rows), 1)
        n = len(self.sent)
        for _ in range(3):                                                            # menedżer nic nie wysyła (bez częściowych, BE, czasu)
            self.mgr.tick()
        self.assertEqual(len(self.sent), n)
        self.mgr._resolve_unknown()
        self.assertEqual(len(self.db.query("SELECT * FROM managed_positions WHERE decision_id=?", (it["intent_id"],))), 1)


PAD_META = {"trade_tick_size": 0.01, "point": 0.01, "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01, "digits": 2}


class TestManualPadRiskPolicy(unittest.TestCase):

    def plan(self, **kw):
        from masterquo.execution.manual import plan_math
        args = {"side": "BUY", "quote": {"bid": 2000.0, "ask": 2000.2}, "meta": dict(PAD_META), "sl": 1990.0, "tp": 2030.0, "sizing_mode": "FIXED",
                "lots": 5.0, "basis_value": 1000.0, "max_risk_pct": 1.0, "calc_profit": lambda s, v, o, c: round((c - o) * 100.0 * v, 2),
                "commission": {"per_lot_per_side": 3.0, "source": "CONFIGURED"}}
        args.update(kw)
        return plan_math(**args)

    def test_fixed_lots_above_risk_policy_not_eligible(self):
        p = self.plan()
        self.assertIn("RISK_ABOVE_POLICY", p["reason_codes"])                         # przed: wykonywalny mimo ryzyka >> 1%
        self.assertFalse(p["execution_eligible"])

    def test_fixed_lots_within_policy_unchanged(self):
        p = self.plan(lots=0.01, basis_value=100000.0)
        self.assertTrue(p["execution_eligible"], p["reason_codes"])

    def test_unknown_basis_blocks(self):
        p = self.plan(lots=0.01, basis_value=None)
        self.assertIn("RISK_BASIS_UNKNOWN", p["reason_codes"])
        self.assertFalse(p["execution_eligible"])


class TestManualPortfolioGuard(_PadBase):
    def test_manual_entry_respects_portfolio_max_open_positions(self):
        self.cfg.update({"risk": {"max_open_positions": 1}})
        it1 = self.pad.create_intent(self.pad.plan(self.body())["plan_id"])
        self.assertEqual(self.pad.execute(it1["intent_id"])["status"], "FILLED")     # jedna pozycja PAPER
        it2 = self.pad.create_intent(self.pad.plan(self.body())["plan_id"])
        r = self.pad.execute(it2["intent_id"])
        self.assertEqual(r["status"], "BLOCKED", r)                                   # przed: FILLED (strażnik portfela pominięty)
        self.assertIn("PORTFOLIO_MAX_OPEN_POSITIONS", r["reason"])
        self.assertNotIn("NOT_PRIMARY_PATH", r["reason"])                              # O1: reguła ścieżki głównej nie dotyczy ręcznych
        self.assertEqual(len(self.db.query("SELECT * FROM managed_positions WHERE state='OPEN'")), 1)

    def test_portfolio_guard_error_blocks(self):
        from unittest import mock
        it = self.pad.create_intent(self.pad.plan(self.body())["plan_id"])
        with mock.patch("masterquo.risk.portfolio.state", side_effect=RuntimeError("db")):
            r = self.pad.execute(it["intent_id"])
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("PORTFOLIO_GUARD_ERROR", r["reason"])


class TestManualIntentSingleEntry(_PadBase):
    def test_second_revision_does_not_open_another_position(self):
        it = self.pad.create_intent(self.pad.plan(self.body())["plan_id"])
        self.assertEqual(self.pad.execute(it["intent_id"], 1)["status"], "FILLED")
        r = self.pad.execute(it["intent_id"], 2)
        self.assertEqual((r["status"], r["reason"]), ("DUPLICATE", "INTENT_ALREADY_EXECUTED"))   # przed: drugi FILLED
        self.assertEqual(len(self.db.query("SELECT * FROM managed_positions WHERE decision_id=?", (it["intent_id"],))), 1)
        again = self.pad.execute(it["intent_id"], 1)                                   # podwójne kliknięcie tej samej rewizji - jak dotąd
        self.assertEqual((again["status"], again["reason"]), ("DUPLICATE", "ACTION_ALREADY_ATTEMPTED"))

    def test_blocked_intent_may_be_retried(self):
        it = self.pad.create_intent(self.pad.plan(self.body())["plan_id"])
        self.modes.set_kill(True, "TEST")
        self.assertEqual(self.pad.execute(it["intent_id"], 1)["status"], "BLOCKED")
        self.assertEqual(self.pad.intent(it["intent_id"])["state"], "BLOCKED")
        self.modes.set_kill(False, "TEST")
        self.assertEqual(self.pad.execute(it["intent_id"], 2)["status"], "FILLED")
        self.assertEqual(self.pad.execute(it["intent_id"], 3)["status"], "DUPLICATE")

    def test_concurrent_claim_lets_one_revision_through(self):
        it = self.pad.create_intent(self.pad.plan(self.body())["plan_id"])
        self.db.execute("UPDATE manual_intents SET state='EXECUTING' WHERE intent_id=?", (it["intent_id"],))
        r = self.pad.execute(it["intent_id"], 1)
        self.assertEqual((r["status"], r["reason"]), ("DUPLICATE", "INTENT_ALREADY_EXECUTED"))
        self.assertIsNone(self.db.one("SELECT * FROM managed_positions WHERE decision_id=?", (it["intent_id"],)))


# ------------------------------------------------------------------------------------------------ I0778 (synchronizacja TP RR_FROM_FILL)
RR_POL = {"tp_rule": "RR_FROM_FILL", "targets": [{"price": 2016.8295, "weight": 1.0}]}      # fill 2001.237, SL 1995.0, rr 2.5


class TestTpSyncTickAligned(_MgrBase):

    def setUp(self):
        super().setUp()
        self.mp = self.mt5_row(1001, entry_price=2001.237, sl=1995.0, tp2=2010.0, exit_policy_json=json.dumps(RR_POL))

    def test_rr_from_fill_tp_is_on_tick_grid(self):
        self.b.positions = [{"ticket": 1001, "volume": 0.1, "sl": 1995.0, "tp": 2010.0}]
        self.b.raw_results = [SimpleNamespace(retcode=10009)]
        self.mgr._sync_broker_tp(self.mp, dict(self.b.positions[0]), dict(RR_POL))
        self.assertEqual(len(self.b.requests), 1)
        self.assertEqual(self.b.requests[0]["tp"], 2016.83)                           # przed: 2016.8295 (poza siatką, INVALID_STOPS)
        self.assertEqual(self.row()["tp2"], 2016.83)

    def test_current_terminal_sl_is_kept(self):
        listed = {"ticket": 1001, "volume": 0.1, "sl": 1995.0, "tp": 2010.0}           # lista mostu sprzed 2 s
        self.b.positions = [dict(listed, sl=1999.5)]                                   # SL przesunięty w terminalu w międzyczasie
        self.b.raw_results = [SimpleNamespace(retcode=10009)]
        self.mgr._sync_broker_tp(self.mp, listed, dict(RR_POL))
        self.assertEqual(self.b.requests[0]["sl"], 1999.5)                            # przed: 1995.0 (nadpisanie świeżego SL)

    def test_missing_terminal_sl_is_never_sent_as_zero(self):
        self.b.positions = [{"ticket": 1001, "volume": 0.1, "sl": None, "tp": 2010.0}]
        self.mgr._sync_broker_tp(self.mp, dict(self.b.positions[0]), dict(RR_POL))
        self.assertEqual(self.b.requests, [])                                         # przed: SLTP z sl=0 (usunięcie stopu)
        self.assertEqual(json.loads(self.row()["exit_note"])["tp_sync"], "NOT_SENT_SL_MISSING_IN_TERMINAL")
        self.assertEqual(self.row()["tp2"], 2010.0)


# ------------------------------------------------------------------------------------------------ I0779 (wyjście czasowe po odrzuceniu)
class TestTimeExitRetry(_MgrBase):
    def setUp(self):
        super().setUp()
        pol = {"targets": [{"price": 2010.0, "weight": 1.0}], "time_exit_minutes": 1, "be_after_tp1": False, "tp_rule": "STRUCTURAL"}
        self.mt5_row(1001, opened_min_ago=2, exit_policy_json=json.dumps(pol))
        self.b.positions = [{"ticket": 1001, "volume": 0.1, "sl": 1990.0, "tp": 2010.0}]
        self.b.load_deals([d_in()])

    def note(self):
        return json.loads(self.row()["exit_note"])["time_exit"]

    def test_rejected_time_exit_is_retried_with_backoff(self):
        self.b.raw_results = [SimpleNamespace(retcode=10018)]                          # MARKET_CLOSED
        self.mgr._manage_mt5_positions()
        self.assertEqual(len(self.b.requests), 1)
        self.mgr._manage_mt5_positions()
        self.assertEqual(len(self.b.requests), 1)                                     # przed upływem 300 s nic
        self.b.advance(301)
        self.b.raw_results = [SimpleNamespace(retcode=10009)]
        self.mgr._manage_mt5_positions()
        self.assertEqual(len(self.b.requests), 2)                                     # przed: nigdy więcej (pozycja bez wyjścia czasowego)
        r = self.b.requests[1]
        self.assertEqual((r["position"], r["volume"], r["type"]), (1001, 0.1, 1))     # tylko zamknięcie tego ticketu, bieżący wolumen
        self.assertEqual(self.note()["state"], "DONE")
        self.b.advance(400)
        self.mgr._manage_mt5_positions()
        self.assertEqual(len(self.b.requests), 2)

    def test_rejections_are_bounded(self):
        for _ in range(10):
            self.b.raw_results = [SimpleNamespace(retcode=10004)]                      # REQUOTE
            self.mgr._manage_mt5_positions()
            self.b.advance(301)
        self.assertEqual(len(self.b.requests), 6)
        self.assertEqual(self.note()["state"], "GAVE_UP")

    def test_unknown_is_not_retried_before_deals_reload(self):
        self.b.raw_results = [None]                                                    # brak odpowiedzi
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.note()["state"], "UNKNOWN")
        self.b.load_deals()
        self.mgr._manage_mt5_positions()
        self.assertEqual(len(self.b.requests), 1)                                     # historia < 90 s po żądaniu
        self.b.advance(100)
        self.b.positions = [{"ticket": 1001, "volume": 0.05, "sl": 1990.0, "tp": 2010.0}]
        self.b.load_deals()
        self.mgr._manage_mt5_positions()
        self.assertEqual(len(self.b.requests), 1)                                     # wolumen się zmienił - coś wykonano, bez ponowienia
        self.b.positions = [{"ticket": 1001, "volume": 0.1, "sl": 1990.0, "tp": 2010.0}]
        self.b.raw_results = [None]
        self.mgr._manage_mt5_positions()
        self.assertEqual(len(self.b.requests), 2)                                     # jedna dodatkowa próba
        self.b.advance(100)
        self.b.load_deals()
        self.mgr._manage_mt5_positions()
        self.assertEqual(len(self.b.requests), 2)
        self.assertEqual(self.note()["state"], "GAVE_UP")

    def test_pre_w2_unknown_note_is_never_repeated(self):
        self.db.execute("UPDATE managed_positions SET exit_note=? WHERE position_ticket=1001", (json.dumps({"time_exit": "UNKNOWN"}),))
        self.b.advance(1000)
        self.b.load_deals()
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.b.requests, [])


# ------------------------------------------------------------------------------------------------ I0781 (adopcja pozycji bota)
class TestAdoptManagedPosition(_MgrBase):
    def test_bot_position_is_not_adopted(self):
        self.mt5_row(1001)
        self.b.positions = [{"ticket": 1001, "magic": 0, "symbol": "XAUUSD-", "side": "BUY", "volume": 0.1, "price_open": 2000.0, "sl": 1990.0, "tp": 2010.0}]
        r = self.mgr.adopt(1001)
        self.assertEqual(r, {"ok": False, "error": "POSITION_ALREADY_MANAGED"})       # przed: ok=True i drugi wiersz OPEN
        self.assertEqual(len(self.db.query("SELECT * FROM managed_positions WHERE position_ticket=1001")), 1)

    def test_manual_position_adoption_stays_idempotent(self):
        self.b.positions = [{"ticket": 2002, "magic": 0, "symbol": "XAUUSD-", "side": "SELL", "volume": 0.02, "price_open": 2000.0, "sl": None, "tp": None}]
        self.assertTrue(self.mgr.adopt(2002)["ok"])
        self.assertTrue(self.mgr.adopt(2002)["ok"])
        self.assertEqual(len(self.db.query("SELECT * FROM managed_positions WHERE position_ticket=2002")), 1)

    def test_bot_order_pending_reconciliation_is_not_adopted(self):
        magic = self.cfg.get().mt5.magic_number
        self.db.execute("""INSERT INTO order_attempts(attempt_id, entry_key, decision_id, setup_id, created_at, updated_at, mode, account_key, symbol,
                           side, volume, price_requested, sl, tp, client_tag, state, initiated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        ("MQO-1", "K1", "D1", "MQS-X1", "x", "x", "AUTO_DEMO", "srv:1", "XAUUSD-", "BUY", 0.1, 2000.0, 1990.0, 2010.0, "MQ:X1",
                         "UNKNOWN", "BOT"))
        self.b.positions = [{"ticket": 3003, "magic": magic, "comment": "MQ:X1", "symbol": "XAUUSD-", "side": "BUY", "volume": 0.1,
                             "price_open": 2000.0, "sl": 1990.0, "tp": 2010.0}]
        self.assertEqual(self.mgr.adopt(3003)["error"], "POSITION_PENDING_RECONCILIATION")
        self.assertIsNone(self.db.one("SELECT * FROM managed_positions WHERE position_ticket=3003"))


# ------------------------------------------------------------------------------------------------ I0721 (noga hedge we wspólnym limicie)
class TestHedgeLegCountsInSharedCap(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        self.cfg = ConfigStore()
        self.cfg.update({"risk": {"max_open_positions": 2}})
        self.db = Database()

    def tearDown(self):
        self.td.close()

    def plan(self, pid, hedge_status=None, state="HEDGED", mode="AUTO_DEMO"):
        fsm = {"type": "BASKET", "data": {"basket_id": pid, "state": state,
                                          "hedge": ({"side": "SELL", "volume": 0.1, "entry": 2000.0, "opened_at": 1.0, "status": hedge_status}
                                                    if hedge_status else None)}}
        self.db.execute("""INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, account_key, state, config_hash, plan,
                           fsm, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (pid, "SIG-" + pid, "HEDGING", "XAUUSD", "XAUUSD-", "BUY", mode, "srv:1", state, "h", "{}", json.dumps(fsm), 1.0, 1.0))

    def reserve(self):
        from masterquo.decision.ledger import RiskBook
        return RiskBook(self.db, self.cfg, sh_limits=dict).reserve(path="ACTIVE", subject="MQO-new", mode="AUTO_DEMO",
                                                                         account_key="srv:1", risk_money=10.0, equity=10000.0)

    def test_open_hedge_leg_takes_a_slot(self):
        self.plan("P1", hedge_status="OPEN")
        r = self.reserve()
        self.assertFalse(r["ok"])                                                     # przed: ok=True (plan liczony jako 1 pozycja)
        self.assertIn("PORTFOLIO_MAX_OPEN_POSITIONS_RESERVED", r["reasons"])
        from masterquo.risk import portfolio as PF
        st = PF.state(self.db, "AUTO_DEMO", "srv:1", 0.0)
        self.assertEqual((st["open_positions"], st["open_hedge_legs"]), (2, 1))
        self.assertIn("PORTFOLIO_MAX_OPEN_POSITIONS", PF.check(st, equity=10000.0, legacy_limits=self.cfg.get().risk, sh_limits={}))

    def test_closed_or_absent_hedge_and_closed_plan_do_not_count(self):
        self.plan("P1", hedge_status="CLOSED", state="PRIMARY_OPEN")
        self.plan("P2", hedge_status="OPEN", state="CLOSED")
        self.plan("P3", hedge_status="OPEN", mode="PAPER")
        self.assertTrue(self.reserve()["ok"])                                         # 1 otwarty plan (P1) + nowe wejście = 2


# ------------------------------------------------------------------------------------------------ I0739 (SH: błąd przed wysłaniem = NOT_SENT)
class TestWorkerNotSubmitted(unittest.TestCase):
    def test_refused_before_submit_is_marked(self):
        import time as _t

        from masterquo.mt5.worker import MT5Busy, MT5CallTimeout, MT5Worker
        w = MT5Worker(lambda: SimpleNamespace())
        w._busy_since = _t.monotonic() - 100                                          # zawieszony job: odmowa przed submit
        with self.assertRaises(MT5CallTimeout) as cm:
            w.call(lambda m: 1, timeout=1.0)
        self.assertTrue(getattr(cm.exception, "not_submitted", False))
        self.assertTrue(issubclass(MT5Busy, MT5CallTimeout))                          # hierarchia bez zmian

    def test_unavailable_worker_is_marked_and_a_running_job_is_not(self):
        import time as _t

        from masterquo.mt5.worker import MT5CallTimeout, MT5Worker, MT5WorkerUnavailable
        def boom():
            raise ImportError("no MetaTrader5")
        w = MT5Worker(boom)
        w.start()
        try:
            with self.assertRaises(MT5WorkerUnavailable) as cm:
                w.call(lambda m: 1, timeout=5.0)
            self.assertTrue(getattr(cm.exception, "not_submitted", False))
        finally:
            w.stop()
        w2 = MT5Worker(lambda: SimpleNamespace())
        w2.start()
        try:
            with self.assertRaises(MT5CallTimeout) as cm:
                w2.call(lambda m: _t.sleep(0.5), timeout=0.1)                         # job już wykonywany - mógł dotrzeć do terminala
            self.assertFalse(getattr(cm.exception, "not_submitted", False))
        finally:
            w2.stop()


def _not_submitted_exc():
    from masterquo.mt5.worker import MT5CallTimeout
    e = MT5CallTimeout("TERMINAL_UNRESPONSIVE")
    e.not_submitted = True
    return e


class _FakeM:
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP, ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TIME_GTC = 1, 6, 0, 1, 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2

    def __init__(self, tick=True):
        self.sent = []
        self.tick = tick

    def symbol_info_tick(self, s):
        return SimpleNamespace(bid=2000.0, ask=2000.2) if self.tick else None

    def order_check(self, r):
        return SimpleNamespace(retcode=0)

    def order_send(self, r):
        self.sent.append(r)
        return SimpleNamespace(retcode=10009, volume=r["volume"], price=r["price"], deal=0, order=555)

    def positions_get(self, ticket=None, symbol=None):
        return [SimpleNamespace(sl=1990.0, tp=2010.0)]


class TestExecutorNotSent(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.sh.store import SHStore
        self.db = Database()
        self.store = SHStore(self.db)
        self.store.own("srv:1", 77, "PLAN-1", "OPEN_P")
        self.plan = {"plan_id": "PLAN-1", "symbol": "XAUUSD-", "account_key": "srv:1"}
        self.m = _FakeM()
        self.refuse = True

    def tearDown(self):
        self.td.close()

    def ex(self):
        from masterquo.sh.executor import SHExecutor

        def terminal(fn):
            if self.refuse:
                raise _not_submitted_exc()
            return fn(self.m)
        return SHExecutor(self.store, terminal=terminal, account_key="srv:1")

    def perform(self, kind="CLOSE_PARTIAL"):
        a = {"action_id": f"PLAN-1:{kind}:TP1", "plan_id": "PLAN-1", "kind": kind, "volume": 0.05, "sl": 1999.0}
        return self.ex().perform(self.plan, a, mode="AUTO_DEMO", quote={"bid": 2000.0, "ask": 2000.2}, ticket=77, side_of_position="BUY", now=1.0)

    def test_close_not_submitted_is_not_sent_then_sent_again(self):
        r = self.perform()
        self.assertEqual(r["status"], "NOT_SENT")                                     # przed: UNKNOWN
        self.refuse = False
        r = self.perform()
        self.assertEqual(r["status"], "FILLED")                                       # przed: UNKNOWN '... bez ponownego wysłania'
        self.assertEqual(len(self.m.sent), 1)

    def test_no_tick_is_not_sent(self):
        self.refuse, self.m.tick = False, False
        self.assertEqual(self.perform()["status"], "NOT_SENT")                        # przed: AttributeError -> UNKNOWN
        self.assertEqual(self.m.sent, [])

    def test_entries_stay_unknown(self):
        for role in ("P", "H"):                                                       # strażnik S0: OPEN_P i OPEN_H nigdy NOT_SENT
            with self.subTest(role=role):
                ex = self.ex()
                kw = {"role": role, "side": "BUY", "volume": 0.1, "sl": 1990.0, "tp": 2010.0, "mode": "AUTO_DEMO",
                      "quote": {"bid": 2000.0, "ask": 2000.2}, "tag": role + "1", "now": 1.0}
                self.assertEqual(ex.open(self.plan, **kw)["status"], "UNKNOWN")
                self.refuse = False
                self.assertEqual(self.ex().open(self.plan, **kw)["status"], "UNKNOWN")   # nigdy ponownie wysłane
                self.assertEqual(self.m.sent, [])
                self.refuse = True

    def test_after_submit_timeout_stays_unknown(self):
        from masterquo.mt5.worker import MT5CallTimeout
        from masterquo.sh.executor import SHExecutor

        def terminal(fn):
            raise MT5CallTimeout("MT5_CALL_TIMEOUT")                                  # po submit: mogło dotrzeć
        a = {"action_id": "PLAN-1:CLOSE_RUNNER:X", "plan_id": "PLAN-1", "kind": "CLOSE_RUNNER", "volume": 0.05}
        r = SHExecutor(self.store, terminal=terminal, account_key="srv:1").perform(self.plan, a, mode="AUTO_DEMO", quote={}, ticket=77,
                                                                                    side_of_position="BUY", now=1.0)
        self.assertEqual(r["status"], "UNKNOWN")


class TestServiceNotSentRetry(unittest.TestCase):
    """Ponowienie akcji NOT_SENT w SHService: ten sam action_id, ograniczone TTL, bez zmiany stanu automatu."""

    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.sh.lifecycle import Leg, Position
        from masterquo.sh.service import SHService
        from masterquo.sh.store import SHStore
        self.db = Database()
        self.svc = SHService.__new__(SHService)
        self.svc.store = SHStore(self.db)
        self.svc.finish = lambda *a, **k: None
        self.pos = Position(plan_id="PLAN-1", side="BUY", entry=2000.0, volume=0.1, sl=1990.0,
                            legs=[Leg("TP1", 2002.0, 0.05), Leg("TP2", 2004.0, 0.03), Leg("TP3", 2006.0, 0.02)])
        self.row = {"plan_id": "PLAN-1", "exec_mode": "AUTO_DEMO", "primary_ticket": 77, "plan": {"instrument_profile": {}}}
        self.results = []
        self.calls = []

    def tearDown(self):
        self.td.close()

    def perform(self, plan, a, **kw):
        self.calls.append(a["action_id"])
        return self.results.pop(0)

    def run_tick(self, acts, now):
        ex = SimpleNamespace(perform=self.perform)
        acts = self.svc._retry_acts(self.row, self.pos, now) + acts
        self.svc.process(ex, self.row, self.pos, acts, None, {"bid": 2003.0, "ask": 2003.2}, now)

    def test_partial_retried_then_back_to_pending_after_ttl(self):
        acts = self.pos.on_quote(2002.5, 2002.7)                                      # TP1 przekroczony -> CLOSE_PARTIAL
        self.results = [{"status": "NOT_SENT", "reason": "x"}]
        self.run_tick(acts, 100.0)
        self.assertEqual(self.pos.legs[0].status, "REQUESTED")                        # bez zmiany stanu automatu
        self.results = [{"status": "NOT_SENT", "reason": "x"}]
        self.run_tick([], 120.0)
        self.assertEqual(self.calls, ["PLAN-1:CLOSE_PARTIAL:TP1"] * 2)                # ten sam action_id
        from masterquo.sh.store import fsm_dump, fsm_load
        d = fsm_dump(self.pos)
        self.assertIn("retry", d)
        self.assertNotIn("_sh_retry", d["data"])                                      # dane automatu bez nowego pola
        self.assertEqual(len(fsm_load(d)._sh_retry), 1)                               # przetrwa restart
        self.run_tick([], 200.0)                                                      # po TTL: brak wysyłki, noga -> PENDING
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.pos.legs[0].status, "PENDING")
        self.assertEqual(self.pos._sh_retry, [])

    def test_retried_failure_changes_nothing(self):
        a = {"action_id": "PLAN-1:MODIFY_SL:BE1", "plan_id": "PLAN-1", "kind": "MODIFY_SL", "sl": 2000.0}
        self.pos.be_status = "REQUESTED"
        self.results = [{"status": "NOT_SENT"}]
        self.run_tick([a], 100.0)
        self.results = [{"status": "REJECTED", "reason": "INVALID_STOPS"}]
        self.run_tick([], 110.0)
        self.assertEqual(self.pos.be_status, "REQUESTED")                             # bez BE_FALLBACK na ścieżce ponowienia
        self.assertEqual(self.pos._sh_retry, [])
        self.assertNotIn("PLAN-1:CLOSE_RUNNER:BE_FALLBACK", self.pos.issued)

    def test_retried_success_feeds_the_state_machine(self):
        acts = self.pos.on_quote(2002.5, 2002.7)
        self.results = [{"status": "NOT_SENT"}, {"status": "FILLED", "volume": 0.05, "price": 2002.4}]
        self.run_tick(acts, 100.0)
        self.run_tick([], 105.0)
        self.assertEqual(self.pos.legs[0].status, "DONE")
        self.assertEqual(self.pos.state, "TP1_DONE")

    def basket(self, state, hedge_status):
        from masterquo.sh.hedge_fsm import Basket, HedgeConfig, Leg2
        b = Basket("PLAN-1", self.pos, HedgeConfig(trigger_adverse_usd=1.0), 100.0, 0.0, state=state,
                   hedge=Leg2(side="SELL", volume=0.05, entry=2000.0, opened_at=0.0, status=hedge_status), activations=1)
        return b

    def test_unwind_back_to_evaluation_and_exit_never_rolled_back(self):
        b = self.basket("UNWINDING", "CLOSING")
        aid = "PLAN-1:CLOSE_HEDGE:1"
        b.issued.add(aid)
        b._sh_retry = [{"action": {"action_id": aid, "basket_id": "PLAN-1", "kind": "CLOSE_HEDGE", "volume": 0.05}, "first_at": 0.0}]
        self.assertEqual(self.svc._retry_acts(self.row, b, 100.0), [])                # po TTL: bez ślepej wysyłki
        self.assertEqual((b.state, b.hedge.status), ("HEDGED", "OPEN"))              # ocena od nowa (noga hedge nadal otwarta)
        self.assertNotIn(aid, b.issued)
        x = self.basket("EXIT_PENDING", "CLOSING")
        x._sh_retry = [{"action": {"action_id": "PLAN-1:CLOSE_PRIMARY:EXIT", "basket_id": "PLAN-1", "kind": "CLOSE_PRIMARY", "volume": 0.1},
                        "first_at": 0.0}]
        self.svc.store.claim_action({"action_id": "PLAN-1:CLOSE_PRIMARY:EXIT", "plan_id": "PLAN-1", "kind": "CLOSE_PRIMARY"}, 0.0)
        self.svc.store.finish_action("PLAN-1:CLOSE_PRIMARY:EXIT", "NOT_SENT", {"status": "NOT_SENT"}, 0.0)
        self.svc._retry_acts(self.row, x, 100.0)
        self.assertEqual(x.state, "EXIT_PENDING")                                     # bez cofnięcia EXIT_PENDING -> HEDGED/PRIMARY_OPEN
        cl = self.svc.store.claim_action({"action_id": "PLAN-1:CLOSE_PRIMARY:EXIT", "plan_id": "PLAN-1", "kind": "CLOSE_PRIMARY"}, 101.0)
        self.assertFalse(cl["claimed"])                                               # po TTL nie jest już wysyłana ponownie


if __name__ == "__main__":
    unittest.main()
