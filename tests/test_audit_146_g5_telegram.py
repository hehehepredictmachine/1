"""1.46 audit, group G5 (Telegram account center - outbound notifications only, no order access).

- focus_X2#2: the baseline (deals that already exist = seen, no history replay) was written from bridge.deals before the first history poll
  (an empty list) or from the previous account's list after an account switch - the whole history was then sent as new events.
- focus_X2#3: a partial close of a position opened before the baseline was announced as CLOSE with a negative remaining volume
  (unknown entry volume taken as 0).
- chunk_24#15: after a reversal (INOUT) the remaining volume was computed from the volume before the reversal (final close = PARTIAL).
- chunk_24#14 (= focus_X2#13, focus_X7#7): PUT /api/v1/telegram/account accepted any type / format (report_time "9" broke every report,
  "false" as text enabled events, a symbol list as text matched substrings) and a refused patch stayed half-applied in memory.
- chunk_24#16: poll() rewrote the whole state file every 10 s even without a new deal.
- chunk_24#18: the old brand / raw scope IDs in the texts shown to the user.
All deals here are SYNTHETIC test fixtures."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData


def deal(ticket, pid, typ, entry, volume, t, price=2000.0, profit=0.0, commission=0.0, magic=0, symbol="XAUUSD"):
    return {"ticket": ticket, "position_id": pid, "type": typ, "entry": entry, "volume": volume, "time": t, "price": price, "profit": profit,
            "commission": commission, "swap": 0.0, "fee": 0.0, "magic": magic, "symbol": symbol}


ALL_ON = {"account_event_enabled": True, "notify_position_open": True, "notify_partial_close": True, "notify_position_close": True,
          "notify_position_reversal": True}


class FakeBridge:
    """The parts of mt5.bridge.MarketBridge the account center reads: deals are published by _poll_deals (then a "deals" notify), an
    account switch only changes account / account_key (the deal list is NOT cleared - that is the real bridge's behaviour)."""

    def __init__(self, server, login):
        self._lock = threading.RLock()
        self.deals: list[dict] = []
        self.deals_loaded_at = None
        self.listeners = []
        self.clock = types.SimpleNamespace(offset=None)
        self.switch(server, login, notify=False)

    def add_listener(self, fn):
        self.listeners.append(fn)

    def _notify(self, kind, data):
        for fn in list(self.listeners):
            fn(kind, data)

    def account_status(self):
        return dict(self.account)

    def switch(self, server, login, notify=True):
        prev = getattr(self, "account_key", None)
        self.account, self.account_key = {"server": server, "login": login, "currency": "USD"}, f"{server}:{login}"
        if notify:
            self._notify("account_changed", {"previous": prev, "current": self.account_key})

    def poll_deals(self, deals):
        with self._lock:
            self.deals = [dict(d) for d in deals]
            self.deals_loaded_at = time.time()
        self._notify("deals", {"count": len(deals)})


class RouteDealsSource(unittest.TestCase):
    """focus_X2#2 through the real wiring (api.wf32_routes -> AccountCenter.deals_fn)."""

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def center(self, bridge):
        from fastapi import FastAPI
        from masterquo.api import wf32_routes
        rt = types.SimpleNamespace(bridge=bridge, baskets=None, cfg=None, db=None, telegram=None, _acct_thread=True)  # no 10 s loop thread
        app = FastAPI()
        wf32_routes.register(app, rt)
        return app.state.wf32["acct"]()

    def test_baseline_never_from_a_not_yet_loaded_deal_list(self):
        from masterquo.notify.account_center import CenterError
        b = FakeBridge("Broker-Demo", 123)
        c = self.center(b)
        history = [deal(1, 500, 0, 0, 0.1, 1000), deal(2, 500, 1, 1, 0.1, 2000, profit=5), deal(3, 501, 1, 0, 0.2, 3000),
                   deal(4, 501, 0, 1, 0.2, 4000, profit=-1), deal(5, 502, 0, 0, 0.3, 5000), deal(6, 502, 1, 1, 0.3, 6000, profit=2)]
        with self.assertRaises(CenterError) as cm:
            c.bind("Broker-Demo:123")                                  # first history poll has not run yet (bridge.deals == [])
        self.assertIn("DEALS_NOT_LOADED", str(cm.exception))
        self.assertIsNone(c.cfg["bound_account_key"])                    # refused -> nothing pinned
        b.poll_deals(history)                                           # 30 days of history arrive
        c.bind("Broker-Demo:123")
        c.update(ALL_ON)
        self.assertEqual(c.poll(), [])                                  # no history replay
        self.assertEqual(c.state["outbox"], [])
        b.poll_deals(history + [deal(7, 503, 0, 0, 0.5, 7000)])
        self.assertEqual([(e["kind"], e["ticket"]) for e in c.poll()], [("open", "7")])

    def test_previous_account_deal_list_is_not_reported_as_the_bound_account(self):
        b = FakeBridge("Broker-Demo", 222)
        c = self.center(b)
        b.poll_deals([deal(10, 900, 0, 0, 1.0, 1000)])
        c.bind("Broker-Demo:222")
        c.update(ALL_ON)
        self.assertEqual(c.poll(), [])
        b.switch("Broker-Live", 111)                                     # other account in the terminal
        b.poll_deals([deal(20, 800, 0, 0, 0.1, 1500), deal(21, 800, 1, 1, 0.1, 1600, profit=4), deal(22, 801, 0, 0, 0.4, 1700)])
        self.assertEqual(c.poll(), [])                                  # ACCOUNT_MISMATCH pause
        b.switch("Broker-Demo", 222)                                     # back on the pinned account, deal list still the other account's
        self.assertEqual(c.poll(), [])
        self.assertEqual(c.state["outbox"], [])
        self.assertEqual(c.status()["paused"], "DEALS_NOT_LOADED")
        b.poll_deals([deal(10, 900, 0, 0, 1.0, 1000), deal(11, 900, 1, 1, 1.0, 1800, profit=9)])
        ev = c.poll()
        self.assertEqual([(e["kind"], e["ticket"]) for e in ev], [("close", "11")])
        self.assertIsNone(c.status()["paused"])


    def test_enabling_events_waits_for_the_deals_of_this_account(self):
        from masterquo.notify.account_center import CenterError
        b = FakeBridge("Broker-Demo", 333)
        c = self.center(b)
        b.poll_deals([deal(1, 1, 0, 0, 1.0, 100)])
        c.bind("Broker-Demo:333")
        b.switch("Broker-Live", 444)
        b.poll_deals([deal(50, 5, 0, 0, 1.0, 100), deal(51, 6, 0, 0, 1.0, 110)])
        b.switch("Broker-Demo", 333)                                      # list not refreshed yet
        with self.assertRaises(CenterError) as cm:
            c.update(ALL_ON)
        self.assertIn("DEALS_NOT_LOADED", str(cm.exception))
        self.assertEqual((c.cfg["account_event_enabled"], c.cfg["notify_position_open"]), (False, False))   # nothing half-applied


class Center(unittest.TestCase):
    def setUp(self):
        from masterquo.notify.account_center import AccountCenter
        self.tmp = tempfile.TemporaryDirectory()
        self.deals: list[dict] = []
        self.account = {"server": "Broker-Demo", "login": 123}
        self.mk = lambda: AccountCenter(Path(self.tmp.name), deals_fn=lambda: [dict(d) for d in self.deals], account_fn=lambda: self.account,
                                        pmw_magics=[41082026], clock=lambda: 1_795_000_000.0)
        self.c = self.mk()

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, c=None):
        c = c or self.c
        c.bind("Broker-Demo:123")
        c.update(ALL_ON)
        return c


class PositionsBeforeBaseline(Center):
    """focus_X2#3"""

    def test_partial_close_of_a_position_opened_before_the_baseline(self):
        self.deals = [deal(1, 500, 0, 0, 1.0, 100, commission=-2)]                # open BEFORE the pin, inside the history window
        self.start()
        self.deals.append(deal(2, 500, 1, 1, 0.3, 200, profit=3))
        ev = self.c.poll()
        self.assertEqual([(e["kind"], e["remaining"]) for e in ev], [("partial", 0.7)])
        self.deals.append(deal(3, 500, 1, 1, 0.7, 300, profit=7, commission=-1))
        ev = self.c.poll()
        self.assertEqual([(e["kind"], e["remaining"], e["net_pnl"], e["side"]) for e in ev], [("close", 0.0, 7.0, "BUY")])

    def test_exit_of_a_position_with_unknown_entry_volume_is_not_a_close(self):
        self.deals = [deal(1, 600, 1, 1, 0.2, 100, profit=1)]                    # entry older than the history window: volume unknown
        self.start()
        self.deals.append(deal(2, 600, 1, 1, 0.3, 200, profit=3))
        self.deals.append(deal(3, 601, 0, 1, 0.5, 210, profit=-2))               # never seen at all
        ev = self.c.poll()
        self.assertEqual([(e["kind"], e["remaining"], e["net_pnl"]) for e in ev], [("exit", None, None), ("exit", None, None)])
        self.assertEqual([e["side"] for e in ev], ["BUY", "SELL"])                # an OUT deal is opposite to its position (MT5)
        self.assertTrue(all("CLOSE" not in m["text"] and "-0." not in m["text"] for m in self.c.state["outbox"]))
        stored = json.loads(Path(self.tmp.name, "telegram_account_state.json").read_text(encoding="utf-8"))["positions"]["600"]
        self.assertEqual((stored["vin_known"], type(stored["vin"]), type(stored["net"])), (False, float, float))   # additive key, 1.45 still loads

    def test_state_written_by_1_45_with_unknown_entry_volume(self):
        Path(self.tmp.name, "telegram_account_state.json").write_text(json.dumps(
            {"cursor": ["1"], "positions": {"700": {"vin": 0.0, "vout": 0.3, "net": 3.0, "side": None}}, "outbox": [], "sent_keys": [],
             "baseline_at": 1.0, "paused": None}), encoding="utf-8")
        Path(self.tmp.name, "telegram_account.json").write_text(json.dumps({"bound_account_key": "Broker-Demo:123", **ALL_ON}), encoding="utf-8")
        self.deals = [deal(1, 700, 1, 1, 0.3, 100, profit=3), deal(2, 700, 1, 1, 0.2, 200, profit=2)]
        c = self.mk()
        self.assertEqual([(e["kind"], e["remaining"]) for e in c.poll()], [("exit", None)])


class Reversal(Center):
    """chunk_24#15"""

    def test_volumes_after_a_reversal(self):
        self.start()
        self.deals += [deal(1, 9, 0, 0, 1.0, 100, commission=-1), deal(2, 9, 1, 2, 1.5, 200, profit=5, commission=-1.5),
                       deal(3, 9, 0, 1, 0.2, 300, profit=2), deal(4, 9, 0, 1, 0.3, 400, profit=3)]
        ev = self.c.poll()
        self.assertEqual([(e["kind"], e["side"], e["remaining"]) for e in ev],
                         [("open", "BUY", 1.0), ("reversal", "SELL", 0.5), ("partial", "SELL", 0.3), ("close", "SELL", 0.0)])
        self.assertEqual(ev[-1]["net_pnl"], 7.5)                                  # whole position id: -1 + 5 - 1.5 + 2 + 3


class ConfigValidation(Center):
    """chunk_24#14 (= focus_X2#13, focus_X7#7)"""

    def test_wrong_types_and_formats_are_refused(self):
        from masterquo.notify.account_center import CenterError
        self.c.bind("Broker-Demo:123")
        for patch in ({"report_time": "9"}, {"report_time": 2100}, {"report_time": "25:99"}, {"report_time": "21:00:00"},
                      {"account_event_enabled": "false"}, {"notify_position_open": 1}, {"send_account_daily_report": "true"},
                      {"symbol_allowlist": "XAUUSD"}, {"symbol_exclude": [1]}, {"account_roi_days": True}, {"report_timezone": None}):
            with self.subTest(patch=patch), self.assertRaises(CenterError):
                self.c.update(patch)
        self.assertEqual(self.c.cfg["report_time"], "21:00")
        self.assertIs(self.c.cfg["account_event_enabled"], False)
        self.c.update({"report_time": "07:30", "symbol_allowlist": ["XAUUSD"], "account_roi_days": 7, "send_account_daily_report": True})
        self.assertEqual((self.c.cfg["report_time"], self.c.cfg["symbol_allowlist"]), ("07:30", ["XAUUSD"]))
        self.assertEqual(self.c.report_due(1_795_000_000.0), ["report:daily:Broker-Demo:123:2026-11-18"])       # 12:06 Warsaw

    def test_refused_patch_is_not_half_applied(self):
        from masterquo.notify.account_center import CenterError
        with self.assertRaises(CenterError):
            self.c.update({"report_time": "08:00", "notify_position_open": True, "account_event_enabled": True})   # not bound
        self.assertEqual((self.c.cfg["report_time"], self.c.cfg["notify_position_open"], self.c.cfg["account_event_enabled"]),
                         ("21:00", False, False))
        self.assertEqual(self.mk().cfg["report_time"], "21:00")

    def test_invalid_stored_config_loads_safe_and_is_reported(self):
        Path(self.tmp.name, "telegram_account.json").write_text(json.dumps(
            {"bound_account_key": "Broker-Demo:123", "report_time": "9", "account_event_enabled": "false", "symbol_allowlist": "XAUUSD",
             "notify_position_open": True, "send_account_daily_report": True}), encoding="utf-8")
        c = self.mk()
        self.assertEqual(c.cfg["report_time"], "21:00")
        self.assertIs(c.cfg["account_event_enabled"], False)
        self.assertEqual(c.cfg["symbol_allowlist"], [])
        self.assertIs(c.cfg["notify_position_open"], True)                        # valid stored values are kept
        self.assertEqual(sorted(c.status()["config_invalid"]), ["account_event_enabled", "report_time", "symbol_allowlist"])
        self.assertIsInstance(c.report_due(1_795_000_000.0), list)                  # no ValueError every 10 s


class NoIdleStateWrites(Center):
    """chunk_24#16"""

    def test_poll_without_new_deals_does_not_rewrite_the_state(self):
        self.deals = [deal(1, 1, 0, 0, 1.0, 100)]
        self.start()
        with mock.patch.object(self.c, "_write", wraps=self.c._write) as w:
            for _ in range(3):
                self.assertEqual(self.c.poll(), [])
            self.assertEqual(w.call_count, 0)
            self.deals.append(deal(2, 2, 0, 0, 1.0, 200))
            self.assertEqual(len(self.c.poll()), 1)
            self.assertEqual(w.call_count, 1)                                     # a new deal is persisted
            self.account = {"server": "Other", "login": 9}
            self.c.poll()
            self.c.poll()
            self.assertEqual(w.call_count, 2)                                     # pause recorded once, not every 10 s
            self.assertEqual(self.c.status()["paused"], "ACCOUNT_MISMATCH")


class DisplayTexts(Center):
    """chunk_24#18"""

    def test_user_visible_texts_use_the_new_brand_and_ids_stay(self):
        self.start()
        self.deals.append(deal(1, 1, 0, 0, 1.0, 100, magic=41082026))
        ev = self.c.poll()
        self.assertEqual(ev[0]["source"], "PMW_ENGINES")                          # internal scope ID unchanged
        text = self.c.state["outbox"][0]["text"]
        self.assertNotIn("PMW", text)
        self.assertIn("Apollo23", text)
        self.assertNotIn("PMW", self.c.status()["roi_note"])


if __name__ == "__main__":
    unittest.main()


class AccountLoopStops(unittest.TestCase):
    """focus_X3#6: the telegram-account thread was `while True` - Runtime.stop() never ended it."""

    def test_loop_ends_when_runtime_stops(self):
        # 1.46 arch (I0092): the loop is no longer started by the route registration (it started before rt.start() and regardless of
        # the licence lock) - Runtime.start starts it through Wf32Services.start_account_loop; it still ends with rt._stop
        import threading
        import types
        from unittest import mock

        from masterquo.wf32_services import Wf32Services
        rt = types.SimpleNamespace(_stop=threading.Event(), bridge=types.SimpleNamespace(), cfg=None)
        svc = Wf32Services(rt)
        with mock.patch.object(Wf32Services, "acct", return_value=mock.MagicMock()):
            self.assertTrue(svc.start_account_loop(rt._stop))
            th = getattr(rt, "_acct_thread", None)
            self.assertIsNotNone(th)
            rt._stop.set()
            th.join(15)
        self.assertFalse(th.is_alive())


class ExportUnknownEntryVolume(unittest.TestCase):
    """focus_X2#3 (export): positions_state of the telegram-center export showed 0.0 for an entry volume never seen - it is null."""

    def test_unknown_entry_volume_is_null_in_the_export(self):
        import json
        import tempfile
        from pathlib import Path

        from masterquo.exports import sources as SRC
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "telegram_account"
            d.mkdir()
            (d / "telegram_account_state.json").write_text(json.dumps({"positions": {"7": {"side": "BUY", "vin": 0.0, "vout": 0.3, "net": 1.0, "vin_known": False},
                                                                    "8": {"side": "SELL", "vin": 1.0, "vout": 0.0, "net": 0.0}}}), encoding="utf-8")
            col = SRC.telegram_center(SRC.SourceContext(data_dir=Path(td)))
        pos = {r["position_id"]: r for r in next(x for x in col.datasets if x.name == "positions_state").rows}
        self.assertIsNone(pos["7"]["volume_in"])
        self.assertEqual(pos["8"]["volume_in"], 1.0)
