"""1.46 audit, group B_core_exec_2: position manager, Manual Pad, PAPER ledger, MT5 bridge / clock / synthetic terminal.

Unit level (stub bridge + real Database / ConfigStore in an isolated data dir) wherever possible; the Manual Pad flows use the
synthetic terminal (FakeMT5) like test_structure_intelligence. No demo HTTP server, no order_send to a real terminal.
"""
from __future__ import annotations

import json
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import _env  # noqa: F401
from _env import UTC, TempData, core, wait_for


class StubBridge:
    """Enough of MarketBridge for the manager / PAPER ledger: quote, profit calculator, lists under _lock, clock offset."""

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
        self.raw_result = None
        self.raw_calls = 0

    def quote_status(self):
        return dict(self.q) if self.q else None

    def calc_profit(self, side, vol, o, c):
        return round((c - o) * 100.0 * vol * (1 if side == "BUY" else -1), 2)

    def account_status(self):
        return dict(self.account)

    def raw_call(self, fn, prio=0, timeout=None):
        self.raw_calls += 1
        return self.raw_result


class Modes:
    def __init__(self, mode="AUTO_DEMO"):
        self.mode = mode

    def gate(self, account_key, **kw):
        return {"mode": self.mode, "allowed": True, "reason_codes": []}


class _Base(unittest.TestCase):
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

    def open_paper(self, lots=0.05, side="BUY"):
        """PAPER position through PaperBroker.open (order_attempts row first, like the gateway / Manual Pad)."""
        att = "MQO-" + uuid.uuid4().hex[:16]
        now = "2026-11-23T10:00:00Z"
        self.db.execute("""INSERT INTO order_attempts(attempt_id, entry_key, decision_id, setup_id, created_at, updated_at, mode, account_key, symbol,
                           side, volume, price_requested, sl, tp, client_tag, state, initiated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (att, "K:" + att, "D-" + att, "S-" + att, now, now, "PAPER", "srv:1", "XAUUSD-", side, lots, 2000.2, 1990.0, 2020.0, "MQ:T",
                         "PREPARED", "USER"))
        d = {"decision_id": "D-" + att, "symbol": "XAUUSD-", "levels": {}, "risk": {"modeled_loss": 51.0},
             "setup": {"setup_id": "S-" + att, "strategy_id": "XAU-S01", "setup_tf": None}}
        r = self.paper.open(attempt_id=att, decision=d, side=side, lots=lots, sl=1990.0 if side == "BUY" else 2010.0,
                            targets=[{"price": 2020.0 if side == "BUY" else 1980.0, "weight": 1.0}])
        self.assertEqual(r["status"], "FILLED", r)
        return self.db.one("SELECT * FROM managed_positions WHERE attempt_id=?", (att,))

    def mt5_row(self, ticket=1001, key=None, opened_min_ago=20, **extra):
        opened = (datetime.now(UTC) - timedelta(minutes=opened_min_ago)).isoformat().replace("+00:00", "Z")
        row = {"position_key": key or f"AUTO_DEMO:srv:1:{ticket}", "mode": "AUTO_DEMO", "account_key": "srv:1", "position_ticket": ticket,
               "attempt_id": "A1", "decision_id": "D1", "setup_id": "S1", "strategy_id": "XAU-S01", "symbol": "XAUUSD-", "side": "BUY",
               "volume_initial": 0.05, "volume_open": 0.05, "entry_price": 2000.0, "sl": 1990.0, "tp2": 2010.0, "state": "OPEN",
               "opened_at": opened, "planned_risk_money": 50.0}
        row.update(extra)
        cols = ",".join(row)
        self.db.execute(f"INSERT INTO managed_positions({cols}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
        return self.db.one("SELECT * FROM managed_positions WHERE position_key=?", (row["position_key"],))


# ------------------------------------------------------------------------------------------------ chunk_10#8 / #22
class TestPaperDoubleClose(_Base):
    def test_stale_position_is_not_closed_and_booked_twice(self):
        mp = self.open_paper(0.05)
        stale = dict(mp)                                                  # the manager read the row before the API closed it
        bal0 = self.db.one("SELECT balance FROM paper_account WHERE id=1")["balance"]
        net1 = self.paper.close_part(dict(mp), 0.05, 1995.0, "MANUAL_CLOSE")
        net2 = self.paper.close_part(stale, 0.05, 1990.0, "SL")
        self.assertIsNone(net2)
        tr = self.db.one("SELECT * FROM trades WHERE trade_id=?", (f"PAPER-{mp['position_ticket']}",))
        self.assertAlmostEqual(tr["volume"], 0.05)                        # was 0.1 (both closes booked)
        self.assertEqual(tr["status"], "CLOSED")
        bal1 = self.db.one("SELECT balance FROM paper_account WHERE id=1")["balance"]
        self.assertAlmostEqual(bal1 - bal0, net1, places=6)

    def test_close_positions_waits_for_the_manager_tick(self):
        mp = self.open_paper(0.05)
        res = {}
        self.mgr._lock.acquire()                                          # a tick in progress
        try:
            t = threading.Thread(target=lambda: res.update(self.mgr.close_positions("ALL")))
            t.start()
            time.sleep(0.4)
            self.assertTrue(t.is_alive())                                 # was: closed concurrently with the tick
            self.assertEqual(self.db.one("SELECT state FROM managed_positions WHERE position_key=?", (mp["position_key"],))["state"], "OPEN")
        finally:
            self.mgr._lock.release()
        t.join(10)
        self.assertEqual(res.get("closed"), [mp["position_ticket"]])

    def test_manual_pad_paper_close_waits_for_the_manager_tick(self):
        from masterquo.execution.manual import ManualPad
        mp = self.open_paper(0.05)
        iid = mp["decision_id"]
        self.db.execute("INSERT INTO manual_intents(intent_id, version, created_at, updated_at, mode, account, instrument, side, state, plan) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)", (iid, 1, "x", "x", "PAPER", "srv:1", "XAUUSD-", "BUY", "OPEN", "{}"))
        pad = ManualPad(self.cfg, self.b, self.db, self.bus, self.log, self.modes, self.paper, SimpleNamespace(manager=self.mgr, engine=None))
        res = {}
        self.mgr._lock.acquire()
        try:
            t = threading.Thread(target=lambda: res.update(pad.manage(iid, "CLOSE", 1)))
            t.start()
            time.sleep(0.4)
            self.assertTrue(t.is_alive())
        finally:
            self.mgr._lock.release()
        t.join(10)
        self.assertEqual(res.get("status"), "DONE", res)

    def test_close_positions_reports_missing_or_stale_quote(self):
        mp = self.open_paper(0.05)
        self.b.q = None
        r = self.mgr.close_positions("ALL")
        self.assertEqual(r["closed"], [])
        self.assertEqual(r["errors"], [{"ticket": mp["position_ticket"], "error": "NO_QUOTE"}])   # was: 0 done, 0 errors
        self.b.q = {"bid": 2000.0, "ask": 2000.2, "age_seconds": 999.0}
        r = self.mgr.close_positions("ALL")
        self.assertEqual(r["errors"], [{"ticket": mp["position_ticket"], "error": "QUOTE_STALE"}])
        self.assertEqual(self.db.one("SELECT state FROM managed_positions WHERE position_key=?", (mp["position_key"],))["state"], "OPEN")


# ------------------------------------------------------------------------------------------------ chunk_10#9
class TestAdoptManagedPosition(_Base):
    def test_manual_position_adoption_stays_idempotent(self):
        self.b.positions = [{"ticket": 2002, "magic": 0, "symbol": "XAUUSD-", "side": "SELL", "volume": 0.02, "price_open": 2000.0,
                             "sl": None, "tp": None}]
        self.assertTrue(self.mgr.adopt(2002)["ok"])
        self.assertTrue(self.mgr.adopt(2002)["ok"])                       # double click: same ADOPTED row
        self.assertEqual(len(self.db.query("SELECT * FROM managed_positions WHERE position_ticket=2002")), 1)


# ------------------------------------------------------------------------------------------------ chunk_10#12 / chunk_24#1 (manager side)
class TestSettlement(_Base):
    def deals(self, raw_close):
        return [{"position_id": 1001, "entry": 0, "volume": 0.05, "price": 2000.0, "time": raw_close - 600, "profit": 0.0, "commission": -0.15},
                {"position_id": 1001, "entry": 1, "volume": 0.05, "price": 2005.0, "time": raw_close, "profit": 25.0, "commission": -0.15}]

    def test_unknown_server_offset_is_not_taken_as_zero(self):
        mp = self.mt5_row(1001)
        raw_close = 1_795_000_000
        self.b.clock.offset = None
        self.mgr._settle_mt5(mp, self.deals(raw_close))
        self.assertIsNone(self.db.one("SELECT * FROM trades WHERE position_ticket=1001"))      # was: closed_at = server time as UTC
        self.assertEqual(self.db.one("SELECT state FROM managed_positions WHERE position_ticket=1001")["state"], "OPEN")
        self.b.clock.offset = 10800
        self.mgr._settle_mt5(mp, self.deals(raw_close))
        tr = self.db.one("SELECT * FROM trades WHERE position_ticket=1001")
        from masterquo.timeutil import from_epoch, iso
        self.assertEqual(tr["closed_at"], iso(from_epoch(raw_close - 10800)))

    def test_no_settlement_before_deal_history_is_loaded(self):
        self.mt5_row(1001, opened_min_ago=30)
        self.b.positions, self.b.deals, self.b.deals_loaded_at = [], [], None    # account switch / start: lists not loaded yet
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.db.one("SELECT state FROM managed_positions WHERE position_ticket=1001")["state"], "OPEN")   # was CLOSED_UNSETTLED
        self.b.deals_loaded_at = datetime.now(UTC)                                        # history loaded, position really gone
        self.mgr._manage_mt5_positions()
        self.assertEqual(self.db.one("SELECT state FROM managed_positions WHERE position_ticket=1001")["state"], "CLOSED_UNSETTLED")


# ------------------------------------------------------------------------------------------------ chunk_10#11 (stored TP only)
class TestTpSyncStoredValue(_Base):
    def test_tp2_is_not_overwritten_after_a_rejected_sync(self):
        pol = {"tp_rule": "RR_FROM_FILL", "targets": [{"price": 2012.5, "weight": 1.0}]}
        mp = self.mt5_row(1001, tp2=2010.0, exit_policy_json=json.dumps(pol))
        self.b.raw_result = SimpleNamespace(retcode=10016)                                # INVALID_STOPS
        self.mgr._sync_broker_tp(mp, {"tp": 2010.0, "sl": 1990.0}, pol)
        row = self.db.one("SELECT tp2, exit_note FROM managed_positions WHERE position_ticket=1001")
        self.assertEqual(json.loads(row["exit_note"])["tp_sync"], "REJECTED_10016")
        self.assertEqual(row["tp2"], 2010.0)                                               # was 2012.5 (a TP the broker does not have)
        mp2 = self.mt5_row(1002, tp2=2010.0, exit_policy_json=json.dumps(pol))
        self.b.raw_result = SimpleNamespace(retcode=10009)
        self.mgr._sync_broker_tp(mp2, {"tp": 2010.0, "sl": 1990.0}, pol)
        self.assertEqual(self.db.one("SELECT tp2 FROM managed_positions WHERE position_ticket=1002")["tp2"], 2012.5)


# ------------------------------------------------------------------------------------------------ chunk_10#13
class TestPaperValuation(_Base):
    def test_no_quote_is_not_floating_zero(self):
        self.open_paper(0.05)
        self.assertEqual(self.paper.account()["floating_unknown_positions"], 0)
        self.b.q = None
        a = self.paper.account()
        self.assertEqual(a["floating_unknown_positions"], 1)                    # was 0
        self.assertIsNone(a["equity"])                                         # was equity = balance
        self.assertIsNone(a["floating"])
        self.assertEqual(a["valuation"], "NO_QUOTE")
        self.mgr._equity_snapshot()
        self.assertIsNone(self.db.one("SELECT * FROM equity_snapshots WHERE mode='PAPER'"))   # incomplete valuation is not stored
        self.b.q = {"bid": 2001.0, "ask": 2001.2, "age_seconds": 0.1}
        self.mgr._equity_snapshot()
        row = self.db.one("SELECT * FROM equity_snapshots WHERE mode='PAPER'")
        self.assertIsNotNone(row["equity"])


# ------------------------------------------------------------------------------------------------ chunk_10#21
class TestPaperEntryCommission(_Base):
    def test_entry_commission_is_the_one_booked_at_open(self):
        mp = self.open_paper(0.05)                                             # 3.0 / lot / side -> 0.15 charged at open
        bal0 = self.db.one("SELECT starting_balance FROM paper_account WHERE id=1")["starting_balance"]
        self.cfg.update({"costs": {"commission_per_lot_per_side": 10.0}})      # commission source changed meanwhile
        self.paper.close_part(dict(mp), 0.05, 2005.0, "TP")
        tr = self.db.one("SELECT * FROM trades WHERE trade_id=?", (f"PAPER-{mp['position_ticket']}",))
        self.assertEqual(json.loads(tr["deals_json"])[0]["entry_commission"], 0.15)   # was 0.5 (recomputed)
        bal1 = self.db.one("SELECT balance FROM paper_account WHERE id=1")["balance"]
        self.assertAlmostEqual(bal1 - bal0, tr["net_pnl"], places=6)            # ledger and trade agree


# ------------------------------------------------------------------------------------------------ Manual Pad on the synthetic terminal
class TestManualPad146(unittest.TestCase):
    def setUp(self):
        import test_risk_execution as TR
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
        self.gw.manager = PositionManager(cfg, b, db, bus, log, self.modes, self.paper)
        self.gw.manager.reconciled_epoch = b.session_epoch
        self.pad = ManualPad(cfg, b, db, bus, log, self.modes, self.paper, self.gw, ttl_s=30)
        self.sent = []
        orig = self.fake.order_send
        self.fake.order_send = lambda r: self.sent.append(r) or orig(r)
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

    # chunk_10#6
    def test_invalid_numbers_and_ttl_are_plan_errors(self):
        from masterquo.execution.manual import PlanError
        for kw, code in ((dict(sl="abc"), "INVALID_SL"), (dict(sl="nan"), "INVALID_SL"), (dict(sl=None, sl_points="inf"), "INVALID_SL_POINTS"),
                         (dict(lots=True), "INVALID_LOTS"), (dict(ttl_s=1e12), "INVALID_TTL_S"),
                         (dict(tp=None, rr=1e308), "PLAN_INPUT_INVALID")):
            with self.subTest(kw=kw):
                with self.assertRaises(PlanError) as cm:                    # was ValueError / OverflowError -> HTTP 500
                    self.pad.plan(self.body(**kw))
                self.assertIn(code, str(cm.exception))
        p = self.pad.plan(self.body(ttl_s=20))
        self.assertTrue(p["execution_eligible"], p["reason_codes"])

    # chunk_10#18 (memory only; consuming a plan per intent = chunk_10#7, owner decision)
    def test_expired_plans_are_dropped(self):
        from masterquo.execution.manual import PlanError
        p1 = self.pad.plan(self.body())
        self.pad._plans[p1["plan_id"]]["expires_at"] = "2000-01-01T00:00:00Z"
        p2 = self.pad.plan(self.body())
        self.assertNotIn(p1["plan_id"], self.pad._plans)                     # was kept forever
        with self.assertRaises(PlanError):
            self.pad.create_intent(p1["plan_id"])
        self.pad.create_intent(p2["plan_id"])
        self.pad.create_intent(p2["plan_id"])                                # unchanged: one plan may still back several intents

    # chunk_10#4
    def test_account_order_without_tp_is_refused_with_the_real_reason(self):
        p = self.pad.plan(self.body(tp=None))
        self.assertTrue(p["execution_eligible"])                                          # PAPER: no TP is fine
        it = self.pad.create_intent(p["plan_id"])
        self.auto_demo()
        r = self.pad.execute(it["intent_id"])
        self.assertEqual(r["status"], "BLOCKED", r)                                       # was REJECTED PRECHECK_FAILED:TypeError
        self.assertIn("TP_REQUIRED_FOR_REAL", r["reason"])
        self.assertIsNone(self.db.one("SELECT * FROM order_attempts WHERE retcode_text LIKE 'PRECHECK_FAILED%'"))
        self.assertEqual(self.sent, [])
        p2 = self.pad.plan(self.body(tp=None))
        self.assertIn("TP_REQUIRED_FOR_REAL", p2["reason_codes"])
        self.assertFalse(p2["execution_eligible"])

    # chunk_10#5
    def test_paper_partial_close_above_open_volume_is_refused(self):
        it = self.pad.create_intent(self.pad.plan(self.body())["plan_id"])
        self.assertEqual(self.pad.execute(it["intent_id"])["status"], "FILLED")
        r = self.pad.manage(it["intent_id"], "PARTIAL_CLOSE", 1, volume=1.0)
        self.assertEqual(r["items"][0]["status"], "REJECTED")                             # was DONE, closed 1.0 of 0.05
        self.assertEqual(r["items"][0]["reason"], "VOLUME_ABOVE_OPEN")
        mp = self.db.one("SELECT * FROM managed_positions WHERE decision_id=?", (it["intent_id"],))
        self.assertEqual(mp["state"], "OPEN")
        self.assertAlmostEqual(mp["volume_open"], 0.05)
        self.assertIsNone(self.db.one("SELECT * FROM trades WHERE trade_id=?", (f"PAPER-{mp['position_ticket']}",)))


# ------------------------------------------------------------------------------------------------ bridge
def _bridge_offline(cfg_store=None):
    from masterquo.config import ConfigStore
    from masterquo.db.database import Database
    from masterquo.events import AppLog, EventBus
    from masterquo.mt5.bridge import MarketBridge
    db = Database()
    bus = EventBus()
    return MarketBridge(cfg_store or ConfigStore(), None, db, bus, AppLog(db, bus))


class TestBridgeResampledMerge(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_resampled_bucket_takes_parts_and_complete(self):
        from masterquo.mt5.bridge import Bar, TFState
        b = _bridge_offline()
        base = 1_791_000_000 - 1_791_000_000 % 180
        rb = lambda k, parts, **kw: Bar(base + k * 180, 1, 2, 0.5, 1.5, parts, 0, 0, source="resampled", parts=parts, complete=parts == 3, **kw)
        st = TFState()
        st.bars = [rb(0, 3, closed=True), rb(1, 3, closed=True), rb(2, 1)]                # bucket 2 first seen with 1 of 3 minutes
        b._merge_tail(st, "M3", [rb(1, 3), rb(2, 2)], "XAUUSD-")
        self.assertEqual((st.bars[2].parts, st.bars[2].complete), (2, False))
        closed = b._merge_tail(st, "M3", [rb(2, 3), rb(3, 1)], "XAUUSD-")
        self.assertEqual([x.t_raw for x in closed], [base + 2 * 180])
        self.assertTrue(st.bars[2].closed)
        self.assertEqual((st.bars[2].parts, st.bars[2].complete), (3, True))            # was parts=1, complete=False after closing
        self.assertTrue(b._bar_json(st.bars[2], "M3")["complete"])
        st.bars[1].parts, st.bars[1].complete = 2, False                                   # closed bucket revised with the late minute
        b._merge_tail(st, "M3", [rb(1, 3), rb(2, 3), rb(3, 1)], "XAUUSD-")
        self.assertEqual((st.bars[1].parts, st.bars[1].complete, st.bars[1].revision), (3, True, 1))


class TestBridgeTicksTruncation(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_truncation_reported_from_the_raw_answer(self):
        b = _bridge_offline()
        b.clock.load_stored(10800, datetime.now(UTC))
        t0 = 1_795_000_000.0
        raw = [{"time_msc": int((t0 + 10800 + i) * 1000), "bid": 2000.0 + i, "ask": 2000.2 + i, "flags": 6} for i in range(4)]
        raw.insert(2, dict(raw[1]))                                                        # duplicate after re-read -> dropped
        b._call = lambda fn, prio=None: list(raw)
        r = b.ticks_range("XAUUSD-", t0, t0 + 3600, max_count=5)
        self.assertEqual((r["count"], r["raw_count"]), (4, 5))
        self.assertTrue(r["truncated"])                                                   # the answer ended before to_utc
        r = b.ticks_range("XAUUSD-", t0, t0 + 1.5, max_count=5)
        self.assertFalse(r["truncated"])                                                  # the range end was reached
        r = b.ticks_range("XAUUSD-", t0, t0 + 3600, max_count=10)
        self.assertFalse(r["truncated"])


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
            b.deals.append({"ticket": -1, "position_id": -1})                         # sentinel: a deal of the previous account
            b.symbol_info["sentinel"] = True                                           # sentinel: metadata of the previous broker
        epoch = b.session_epoch
        self.fake.switch_account(7770001)
        b._poll_account()
        self.assertTrue(b.account_key.endswith(":7770001"))
        self.assertGreater(b.session_epoch, epoch)
        self.assertNotIn("sentinel", b.symbol_info)                                    # was: kept until a reconnect
        self.assertFalse(any(d.get("ticket") == -1 for d in b.deals))                  # was: kept up to history_poll_seconds
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
        b.connect()                                                                   # reconnect lands on another account
        self.assertTrue(b.account_key.endswith(":7770003"))
        self.assertEqual((b.deals, b.positions, b.deals_loaded_at), ([], [], None))   # was: previous account's deals + loaded_at
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


class TestBridgeSymbolCandidates(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_candidates_follow_the_active_asset(self):
        from masterquo.mt5.bridge import BridgeError
        cfg = SimpleNamespace(get=lambda: SimpleNamespace(mt5=SimpleNamespace(symbol="BTCUSD.x", call_timeout_seconds=5, dxy_symbol=None), assets=SimpleNamespace(active="BTC")))
        b = _bridge_offline(cfg)
        b.assets = SimpleNamespace(NAME_HINTS={"XAUUSD": ("XAUUSD", "GOLD", "XAU"), "BTC": ("BTCUSD", "BITCOIN", "BTC")},
                                   check_symbol=lambda s, p: None, autodetect=lambda a: None)
        groups = []
        names = ["XAUUSD", "GOLD", "BTCUSD", "BTCUSD.m"]

        class M:
            def symbol_info(self, s):
                return None

            def symbols_get(self, group=None):
                import fnmatch
                groups.append(group)
                pats = group.split(",")
                return [SimpleNamespace(_asdict=lambda n=n: {"name": n}) for n in names if any(fnmatch.fnmatch(n, p) for p in pats)]
        b._call = lambda fn, prio=None: fn(M())
        with self.assertRaises(BridgeError):
            b._check_symbol()
        self.assertNotIn("XAU", groups[-1])                                            # was "*XAU*,*GOLD*" for BTC too
        self.assertEqual(b.symbol_candidates, ["BTCUSD", "BTCUSD.m"])


# ------------------------------------------------------------------------------------------------ chunk_24#19
class TestSyntheticTerminalLabels(unittest.TestCase):
    def test_demo_terminal_shows_the_product_name(self):
        from masterquo.mt5.fake import FakeMT5, is_fake
        f = FakeMT5(history_days=3)
        f.initialize()
        self.assertIn("Apollo23", f.terminal_info().company)
        self.assertIn("Apollo23", f.account_info().company)
        self.assertNotIn("MasterQUO", f.terminal_info().company + f.account_info().company)
        self.assertTrue(is_fake(f))                                                    # recognition does not depend on the label


if __name__ == "__main__":
    unittest.main()
