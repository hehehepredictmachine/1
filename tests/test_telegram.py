"""Telegram notifications (1.24): bilingual EN + 中文 messages, real connection state (never pretended), errors without the token,
deduplication, opened / closed positions and the daily summary. Nothing is sent to Telegram here - the HTTP call is replaced."""
from __future__ import annotations

import io
import json
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest import mock

import _env  # noqa: F401

from masterquo.config import TelegramConfig
from masterquo.notify import telegram as T

TOKEN = "123456:SECRET-TOKEN-VALUE"


class FakeDB:
    def __init__(self):
        self.keys = set()

    def one(self, sql, args):
        return {"x": 1} if args[0] in self.keys else None

    def execute(self, sql, args):
        self.keys.add(args[0])


def notifier(token=TOKEN, **cfg):
    c = TelegramConfig(**{"enabled": True, "chat_id": "42", **cfg})
    store = NS(get=lambda: NS(telegram=c))
    n = T.TelegramNotifier(store, NS(get=lambda k: token if k == "TELEGRAM_BOT_TOKEN" else None), FakeDB(),
                           stats_fn=lambda: ("PAPER", {"trades": 3, "net": 12.5, "win_rate": 66.7, "profit_factor": 2.1}, "USD"))
    n._send_async = lambda tok, chat, text: n.outbox.append(text)       # synchronous, no network
    n.outbox = []
    return n


class TestFormats(unittest.TestCase):
    def test_bilingual_and_single_language(self):
        d = {"symbol": "XAUUSD-", "side": "SHORT", "strategy": "S12", "timeframe": "M1", "stage": "CONFIRMED", "entry": 3456.6, "sl": 3467.7, "tps": [3451.6]}
        both = T.fmt_signal(d, "EN_ZH")
        self.assertIn("Signal | 信号", both)
        self.assertIn("SELL | 卖出", both)
        self.assertIn("Analysis only", both)
        self.assertIn("仅供分析", both)
        self.assertNotIn("信号", T.fmt_signal(d, "EN"))
        self.assertNotIn("Signal", T.fmt_signal(d, "ZH"))
        closed = T.fmt_closed({"mode": "AUTO_DEMO", "symbol": "XAUUSD-", "side": "BUY", "volume": 0.1, "net": -4.2, "currency": "USD",
                               "r_multiple": -0.5, "commission_known": False}, "EN_ZH")
        self.assertIn("Position closed | 已平仓", closed)
        self.assertIn("-4.20 USD (-0.50R)", closed)
        self.assertIn("commission unknown", closed)
        stats = T.fmt_stats({"trades": 0}, "PAPER", "USD", "2026-10-27", "EN_ZH")
        self.assertIn("No closed trades today.", stats)
        self.assertIn("今日无已平仓交易。", stats)
        self.assertIn("Past results do not guarantee", stats)


class TestNotifier(unittest.TestCase):
    def test_state_is_never_pretended(self):
        self.assertEqual(notifier(token=None).status()["state"], "NOT_CONFIGURED")
        self.assertEqual(notifier(enabled=False).status()["state"], "DISABLED")
        n = notifier()
        self.assertEqual(n.status()["state"], "UNTESTED")                      # configured, but nothing was ever accepted by Telegram
        with mock.patch.object(n, "_post", return_value=(True, None)):
            self.assertTrue(n.send_test()["ok"])
        self.assertEqual(n.status()["state"], "OK")
        with mock.patch.object(n, "_post", return_value=(False, "HTTP 400: chat not found")):
            r = n.send_test()
        self.assertFalse(r["ok"])
        st = n.status()
        self.assertEqual((st["state"], st["last_error"]), ("ERROR", "HTTP 400: chat not found"))
        self.assertNotIn(TOKEN, json.dumps(st))

    def test_http_error_text_has_no_token(self):
        n = notifier()
        err = urllib.error.HTTPError(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 401, "Unauthorized", {},
                                     io.BytesIO(b'{"ok":false,"description":"Unauthorized"}'))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            ok, msg = n._post(TOKEN, "42", "x")
        self.assertFalse(ok)
        self.assertEqual(msg, "HTTP 401: Unauthorized")
        with mock.patch("urllib.request.urlopen", side_effect=OSError(f"failed {TOKEN}")):
            ok, msg = n._post(TOKEN, "42", "x")
        self.assertNotIn(TOKEN, msg)

    def test_flags_and_dedup(self):
        n = notifier(send_trades=False)
        self.assertFalse(n.trade_opened("A1", {"mode": "PAPER"}))             # trades not switched on
        n = notifier(send_trades=True)
        self.assertTrue(n.trade_opened("A1", {"mode": "PAPER", "symbol": "XAUUSD-", "side": "BUY", "volume": 0.1, "price": 1.0}))
        self.assertFalse(n.trade_opened("A1", {"mode": "PAPER"}))             # same order: once
        self.assertTrue(n.trade_closed("A1", {"mode": "PAPER", "net": 1}))    # open and close are separate keys
        self.assertEqual(len(n.outbox), 2)
        self.assertIn("Position opened | 已开仓", n.outbox[0])

    def test_daily_summary_once_after_the_hour(self):
        n = notifier(send_stats=True, stats_hour_utc=21)
        early = datetime(2026, 10, 27, 20, 59, tzinfo=timezone.utc)
        late = early + timedelta(minutes=2)
        self.assertFalse(n.send_daily_stats(early))
        self.assertTrue(n.send_daily_stats(late))
        self.assertFalse(n.send_daily_stats(late + timedelta(hours=1)))        # once per day
        self.assertIn("Daily summary | 每日汇总 2026-10-27 · PAPER", n.outbox[0])
        self.assertIn("66.7 %", n.outbox[0])


class TestRuntimeTradeEvents(unittest.TestCase):
    def test_fresh_fills_only(self):
        from masterquo.runtime import Runtime
        from masterquo.timeutil import iso, utcnow
        calls = []
        rt = NS(telegram=NS(trade_opened=lambda k, d: calls.append((k, d)), trade_closed=lambda k, d: calls.append((k, d))), db=None)
        now = utcnow()
        Runtime._telegram_trades(rt, {"type": "orders", "data": [
            {"attempt_id": "OLD", "state": "FILLED", "updated_at": iso(now - timedelta(hours=2))},
            {"attempt_id": "NEW", "state": "FILLED", "updated_at": iso(now), "mode": "AUTO_DEMO", "symbol": "XAUUSD-", "side": "BUY",
             "filled_volume": 0.1, "fill_price": 3456.6, "sl": 3450.0, "tp": 3470.0},
            {"attempt_id": "REJ", "state": "REJECTED", "updated_at": iso(now)}]})
        self.assertEqual([k for k, _ in calls], ["NEW"])
        Runtime._telegram_trades(rt, {"type": "trade_closed", "data": {"key": "PLAN-1", "mode": "PAPER", "net": 2.0}})
        self.assertEqual(calls[-1][0], "PLAN-1")


if __name__ == "__main__":
    unittest.main()
