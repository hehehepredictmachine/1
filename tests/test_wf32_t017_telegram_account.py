"""WF3.2 TASK 017 - Telegram account center: OFF by default, explicit exact-account pin, baseline without history replay, deal-based lifecycle
events (open / partial / close / reversal), scope + symbol filters, outbox dedup, account mismatch pause, DST-safe report keys, safe templates."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import _env  # noqa: F401


class Env:
    def __init__(self):
        self.deals = [{"ticket": 1, "time": 100, "type": 0, "entry": 0, "position_id": 10, "volume": 1, "price": 2000, "magic": 0, "symbol": "XAUUSD",
                       "profit": 0, "commission": -2}]
        self.account = {"server": "Broker-Demo", "login": 123}
        self.sent = []

    def deliver(self, key, text):
        self.sent.append((key, text))
        return True


class TestAccountCenter(unittest.TestCase):
    def setUp(self):
        from masterquo.notify.account_center import AccountCenter
        self.tmp = tempfile.TemporaryDirectory()
        self.e = Env()
        self.mk = lambda: AccountCenter(Path(self.tmp.name), deliver=self.e.deliver, deals_fn=lambda: [dict(d) for d in self.e.deals],
                                        account_fn=lambda: self.e.account, pmw_magics=[41082026], clock=lambda: 1_763_700_000)
        self.c = self.mk()

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_off_and_bind_requires_current_account(self):
        from masterquo.notify.account_center import CenterError
        st = self.c.status()
        self.assertFalse(st["config"]["account_event_enabled"])
        self.assertIsNone(st["config"]["bound_account_key"])
        self.assertEqual(self.c.poll(), [])
        with self.assertRaises(CenterError):
            self.c.update({"account_event_enabled": True})                       # not bound
        with self.assertRaises(CenterError):
            self.c.bind("Other:999")
        self.c.bind("Broker-Demo:123")
        self.assertEqual(self.c.state["cursor"], ["1"])                          # baseline: existing deal is seen, never replayed

    def test_lifecycle_events_outbox_dedup_and_filters(self):
        self.c.bind("Broker-Demo:123")
        self.c.update({"account_event_enabled": True, "notify_position_open": True, "notify_partial_close": True, "notify_position_close": True,
                       "notify_position_reversal": True})
        self.e.deals += [
            {"ticket": 2, "time": 200, "type": 0, "entry": 0, "position_id": 20, "volume": 2, "price": 2010, "magic": 41082026, "symbol": "XAUUSD",
             "profit": 0, "commission": -2},
            {"ticket": 3, "time": 300, "type": 1, "entry": 1, "position_id": 20, "volume": 1, "price": 2020, "magic": 41082026, "symbol": "XAUUSD",
             "profit": 10, "commission": -1},
            {"ticket": 4, "time": 400, "type": 1, "entry": 1, "position_id": 20, "volume": 1, "price": 2030, "magic": 41082026, "symbol": "XAUUSD",
             "profit": 20, "commission": -1, "swap": -0.5},
            {"ticket": 5, "time": 500, "type": 2, "entry": 0, "position_id": 0, "volume": 0, "price": 0, "magic": 0, "symbol": "", "profit": 1000},
        ]
        ev = self.c.poll()
        self.assertEqual([e["kind"] for e in ev], ["open", "partial", "close"])
        self.assertEqual(ev[-1]["net_pnl"], 25.5)                                 # -2 + (10 - 1) + (20 - 1 - 0.5)
        self.assertEqual(ev[0]["source"], "PMW_ENGINES")
        self.assertEqual(self.c.flush(), 3)
        self.assertEqual(self.c.poll(), [])                                       # cursor: nothing twice
        self.assertEqual(self.c.flush(), 0)
        self.assertEqual(len(self.e.sent), 3)
        self.assertIn("XAUUSD", self.e.sent[0][1])
        c2 = self.mk()                                                             # restart: persisted cursor + sent keys
        self.assertEqual(c2.poll(), [])
        c2.update({"account_event_scope": "EXTERNAL_MAGIC"})
        self.e.deals.append({"ticket": 6, "time": 600, "type": 0, "entry": 0, "position_id": 30, "volume": 1, "price": 1, "magic": 0, "symbol": "EURUSD"})
        self.assertEqual(c2.poll(), [])                                            # magic 0 is MAGIC_ZERO_UNCLASSIFIED, filtered out
        c2.update({"account_event_scope": "ALL_ACCOUNT", "symbol_exclude": ["GBPUSD"]})
        self.e.deals.append({"ticket": 7, "time": 700, "type": 0, "entry": 0, "position_id": 40, "volume": 1, "price": 1, "magic": 0, "symbol": "GBPUSD"})
        self.assertEqual(c2.poll(), [])

    def test_account_switch_pauses(self):
        self.c.bind("Broker-Demo:123")
        self.c.update({"account_event_enabled": True, "notify_position_open": True})
        self.e.account = {"server": "Broker-Live", "login": 555}
        self.e.deals.append({"ticket": 9, "time": 900, "type": 0, "entry": 0, "position_id": 90, "volume": 1, "price": 1, "magic": 0, "symbol": "X"})
        self.assertEqual(self.c.poll(), [])
        self.assertEqual(self.c.status()["paused"], "ACCOUNT_MISMATCH")

    def test_reports_dst_safe_once_per_day(self):
        self.c.bind("Broker-Demo:123")
        self.c.update({"send_account_daily_report": True, "report_timezone": "Europe/Warsaw", "report_time": "21:00"})
        tz = ZoneInfo("Europe/Warsaw")
        before = datetime(2025, 3, 30, 20, 59, tzinfo=tz).timestamp()             # DST change day
        after = datetime(2025, 3, 30, 21, 5, tzinfo=tz).timestamp()
        self.assertEqual(self.c.report_due(before), [])
        self.assertEqual(self.c.report_due(after), ["report:daily:Broker-Demo:123:2025-03-30"])
        self.c.roi_fn = lambda days: {"roi_pct": None, "status": "NO_DATA"}
        self.assertEqual(self.c.queue_reports(after), 1)
        self.c.flush()
        self.assertEqual(self.c.report_due(after), [])
        self.assertIn("NO_DATA", self.e.sent[-1][1])

    def test_templates_safe(self):
        from masterquo.notify.account_center import CenterError, validate_template
        self.assertEqual(validate_template("open", "${symbol} ${side}"), "${symbol} ${side}")
        for bad in ("${token}", "${__class__}", "$ {symbol} $", ""):
            with self.assertRaises(CenterError):
                validate_template("open", bad)
        self.c.set_template("open", "OPEN ${symbol}")
        self.assertEqual(self.mk().templates["open"], "OPEN ${symbol}")

    def test_no_order_surface(self):
        import inspect
        from masterquo.notify import account_center as A
        src = inspect.getsource(A).split('"""', 2)[2]                       # code only (the docstring names what is NOT used)
        for w in ("order_send", "getUpdates", "setWebhook", "positions_modify"):
            self.assertNotIn(w, src)


if __name__ == "__main__":
    unittest.main()
