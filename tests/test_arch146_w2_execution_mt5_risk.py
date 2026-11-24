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


if __name__ == "__main__":
    unittest.main()
