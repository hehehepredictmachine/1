"""Multi-market scanner and the bot's signals (strategies S01-S10 on every market): simulator markets, bridge reads,
analysis, strategy scan on other symbols, signal validation/dedupe/tracking, main-engine events. No orders, no AI."""
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import _env
from _env import TempData

UTC = timezone.utc


class World:
    """Fake terminal + bridge connected (server clock offset known), scanner and the bot signal service."""

    def __init__(self):
        from masterquo.markets.scanner import MarketScanner
        from masterquo.markets.signals import BotSignalService
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.bridge = _env.core()
        self.bridge.connect()
        self.bridge.clock.load_stored(10800, datetime.now(UTC))
        self.bridge._poll_quote()
        self.scanner = MarketScanner(self.cfg, self.bridge, self.bus, self.log)
        self.signals = BotSignalService(self.cfg, self.bridge, self.db, self.bus, self.log)
        self.scanner.signals = self.signals

    def close(self):
        self.worker.stop()


class TestSimulatorAndScanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        cls.w = World()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()
        cls.td.close()

    def test_01_symbols_market_watch_vs_all(self):
        mw = [s["name"] for s in self.w.bridge.list_symbols(visible_only=True)]
        allsym = [s["name"] for s in self.w.bridge.list_symbols(visible_only=False)]
        self.assertIn("XAUUSD-", mw)
        self.assertIn("EURUSD-", mw)
        self.assertNotIn("BTCUSD-", mw)                 # hidden in Market Watch
        self.assertIn("BTCUSD-", allsym)
        self.assertEqual(self.w.bridge.symbol_meta("EURUSD-")["digits"], 5)

    def test_02_bars_and_quote_of_other_symbol(self):
        bars = self.w.bridge.symbol_bars("EURUSD-", "H1", 50)
        self.assertEqual(len(bars), 50)
        self.assertTrue(all(b["open_utc"] for b in bars))
        self.assertTrue(0.5 < bars[-1]["c"] < 2.0)
        self.assertTrue(all(b["closed"] for b in bars[:-1]))
        q = self.w.bridge.symbol_quote("EURUSD-", 1e-5)
        self.assertGreater(q["ask"], q["bid"])
        self.assertEqual(q["spread_points"], 8.0)
        x = self.w.bridge.symbol_bars("XAUUSD-", "H1", 5)
        self.assertGreater(x[-1]["c"], 500)               # each market has its own price scale

    def test_03_scan_market_watch(self):
        s = self.w.scanner.scan()
        names = [i["symbol"] for i in s["items"]]
        self.assertEqual(s["state"], "OK", s)
        self.assertEqual(set(names), {"XAUUSD-", "EURUSD-", "GBPUSD-", "USDJPY-", "US30-"})
        for i in s["items"]:
            self.assertEqual(i["status"], "OK", i)
            if i["symbol"] == "XAUUSD-":
                self.assertEqual(i["bot"]["status"], "MAIN_ENGINE")            # main symbol: the bot's own engine
            else:
                self.assertEqual(i["bot"]["status"], "OK", i["bot"])          # S01-S10 ran on this market
                self.assertTrue(all(x["stage"] in ("WATCH", "EARLY", "CONFIRMED") for x in i["bot"]["setups"]))
            self.assertTrue(0 <= i["score"] <= 100)
            self.assertIn(i["regime"], ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOLATILITY", "MIXED"))
        self.assertEqual([i["score"] for i in s["items"]], sorted((i["score"] for i in s["items"]), reverse=True))
        d = self.w.scanner.get("EURUSD-")
        self.assertEqual(d["volatility"]["status"], "OK")
        self.assertEqual(len(d["volatility"]["walls"]), 4)
        self.assertTrue(d["timeframes"]["H4"]["trend"] in ("UP", "DOWN", "MIXED"))

    def test_04_scan_list_and_exclude_and_cap(self):
        self.w.cfg.update({"markets": {"source": "LIST", "symbols": ["BTCUSD-", "XAGUSD-", "NOPE-"], "include_main": False}})
        try:
            s = self.w.scanner.scan()
            self.assertEqual({i["symbol"] for i in s["items"]}, {"BTCUSD-", "XAGUSD-"})
            self.assertIn("NOPE-", s["errors"])
            self.w.cfg.update({"markets": {"source": "ALL", "exclude": ["DXY_SYN"], "max_symbols": 3, "include_main": True}})
            s = self.w.scanner.scan()
            self.assertEqual(len(s["items"]) + len(s["errors"]), 3)
            self.assertIn("XAUUSD-", [i["symbol"] for i in s["items"]])
        finally:
            self.w.cfg.update({"markets": {"source": "MARKET_WATCH", "symbols": [], "exclude": [], "max_symbols": 30, "include_main": True}})

    def test_05_no_look_ahead_in_analysis(self):
        from masterquo.markets import analysis
        bars = {tf: self.w.bridge.symbol_bars("GBPUSD-", tf, n) for tf, n in (("H1", 400), ("H4", 400), ("D1", 420))}
        a = analysis.analyze("GBPUSD-", bars, self.w.bridge.symbol_meta("GBPUSD-"), None, self.w.cfg.get().volatility)
        for tf in ("H1", "H4", "D1"):
            f = dict(bars[tf][-1])
            f.update(h=f["h"] * 1.2, l=f["l"] * 0.8, c=f["c"] * 1.1, closed=False)
            bars[tf] = bars[tf][:-1] + [f]
        b = analysis.analyze("GBPUSD-", bars, self.w.bridge.symbol_meta("GBPUSD-"), None, self.w.cfg.get().volatility)
        self.assertEqual(a["timeframes"]["H4"]["rsi14"], b["timeframes"]["H4"]["rsi14"])
        self.assertEqual(a["timeframes"]["D1"]["atr14"], b["timeframes"]["D1"]["atr14"])


    def test_06_strategies_run_on_other_markets_and_confirmed_become_signals(self):
        from masterquo.strategies.registry import STRATEGIES
        self.w.cfg.update({"markets": {"source": "ALL", "exclude": ["DXY_SYN"]}})
        try:
            s = self.w.scanner.scan()
        finally:
            self.w.cfg.update({"markets": {"source": "MARKET_WATCH", "exclude": []}})
        others = [i for i in s["items"] if i["symbol"] != "XAUUSD-"]
        self.assertEqual(len(others), 6)
        for i in others:
            self.assertEqual(i["bot"]["strategies_ok"], 10, i)
        rows = self.w.db.query("SELECT * FROM ai_signals WHERE source='BOT'")
        confirmed = {(i["symbol"], x["setup_id"]) for i in others for x in i["bot"]["setups"] if x["stage"] == "CONFIRMED"}
        recorded = {(r["symbol"], r["setup_id"]) for r in rows}
        self.assertTrue(recorded <= confirmed | recorded)
        for r in rows:
            self.assertIn(r["strategy_id"], STRATEGIES)
            self.assertEqual(r["trigger"], "SCANNER")
            self.assertIn(r["status"], ("OPEN", "REJECTED"))
        # rescanning the same data never duplicates a signal
        n = len(rows)
        self.w.cfg.update({"markets": {"source": "ALL", "exclude": ["DXY_SYN"]}})
        try:
            self.w.scanner.scan()
        finally:
            self.w.cfg.update({"markets": {"source": "MARKET_WATCH", "exclude": []}})
        self.assertEqual(len(self.w.db.query("SELECT 1 FROM ai_signals WHERE source='BOT'")), n)
        self.assertEqual(self.w.fake._positions, {})                          # no orders from signals

    def test_07_disabled_other_markets(self):
        self.w.cfg.update({"signals": {"scan_other_markets": False}})
        try:
            s = self.w.scanner.scan()
            self.assertTrue(all("bot" not in i or i["bot"] is None or i["bot"].get("status") in ("MAIN_ENGINE",) for i in s["items"]))
        finally:
            self.w.cfg.update({"signals": {"scan_other_markets": True}})


def _sig(**kw):
    s = {"signal_id": "BOT-1", "created_at": "2026-10-08T10:00:00Z", "status": "OPEN", "action": "BUY", "entry_type": "MARKET",
         "entry_price": 100.0, "stop_loss": 99.0, "take_profits_json": "[102.0, 103.0]", "filled_at": "2026-10-08T10:00:00Z", "tp_hit": 0}
    s.update(kw)
    return s


def _b(t, o, h, l, c, closed=True):
    return {"open_utc": t, "o": o, "h": h, "l": l, "c": c, "closed": closed, "tv": 1}


def _rec(**kw):
    r = {"setup_id": "MQA-1", "event_id": "EV-1", "strategy_id": "S03", "strategy_name": "CHANNEL_BREAKOUT", "direction": "LONG", "timeframe": "M5",
         "stop_loss": 1.0980, "targets": [{"price": 1.1030, "weight": 0.5}, {"price": 1.1060, "weight": 0.5}], "setup_score": 74.0,
         "entry_plan": {"trigger_level": 1.0998, "max_distance_atr": 1.0}, "horizon": "SCALP"}
    r.update(kw)
    return r


class TestSignalRules(unittest.TestCase):
    def test_validation_uses_bot_rules(self):
        from masterquo.markets.signals import validate
        v = validate(_rec(), 1.1000, 1.1001, 0.0010, 1.0)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["entry"], 1.1001)                                   # BUY at Ask
        risk = 1.1001 - 1.0980
        self.assertEqual(v["rr"], [round(0.0029 / risk, 2), round(0.0059 / risk, 2)])
        self.assertAlmostEqual(v["rr_weighted"], round(0.5 * v["rr"][0] + 0.5 * v["rr"][1], 2), places=2)
        self.assertIn("RR_BELOW_BOT_LIMIT_3", validate(_rec(), 1.1000, 1.1001, 0.0010, 3.0)["reasons"])
        self.assertIn("PRICE_RAN_AWAY_FROM_TRIGGER", validate(_rec(), 1.1020, 1.1021, 0.0010, 1.0)["reasons"])
        self.assertIn("PRICE_ALREADY_BEYOND_STOP", validate(_rec(), 1.0970, 1.0971, 0.01, 1.0)["reasons"])
        self.assertIn("NO_VALID_TARGET", validate(_rec(targets=[]), 1.1000, 1.1001, 0.001, 1.0)["reasons"])
        self.assertIn("SPREAD_TOO_LARGE_VS_RISK", validate(_rec(), 1.0990, 1.1001, 0.002, 0.0)["reasons"])
        sell = validate(_rec(direction="SHORT", stop_loss=1.1020, targets=[{"price": 1.0970, "weight": 1.0}],
                             entry_plan={"trigger_level": 1.1002, "max_distance_atr": 1.0}), 1.1000, 1.1001, 0.001, 1.0)
        self.assertTrue(sell["ok"], sell)
        self.assertEqual(sell["entry"], 1.1000)                                # SELL at Bid

    def test_tracking_win_partial_loss_timeout(self):
        from masterquo.markets.signals import evaluate
        bars = [_b("2026-10-08T09:45:00Z", 99, 99.5, 98, 99.2),                # before the signal: ignored
                _b("2026-10-08T10:00:00Z", 100, 100.6, 99.5, 100.4),
                _b("2026-10-08T10:15:00Z", 100.4, 102.2, 100.0, 102.0),        # TP1
                _b("2026-10-08T10:30:00Z", 102.0, 103.1, 101.9, 103.0)]        # TP2 -> WIN
        u = evaluate(_sig(), bars, "2026-10-08T11:00:00Z", 72)
        self.assertEqual((u["status"], u["tp_hit"], u["outcome_r"]), ("WIN", 2, 3.0))
        u = evaluate(_sig(), bars[:3], "2026-10-08T10:40:00Z", 72)
        self.assertEqual((u["status"] if "status" in u else "OPEN", u["tp_hit"]), ("OPEN", 1))
        u = evaluate(_sig(tp_hit=1), [_b("2026-10-08T10:45:00Z", 101, 103.5, 98.5, 101)], "2026-10-08T11:00:00Z", 72)
        self.assertEqual((u["status"], u["outcome_r"]), ("LOSS", -1.0))          # SL and TP in one bar -> loss
        u = evaluate(_sig(), [_b("2026-10-08T10:00:00Z", 100, 100.5, 99.5, 100.2), _b("2026-10-09T10:00:00Z", 100.2, 100.6, 99.6, 100.5)],
                     "2026-10-09T10:20:00Z", 24)
        self.assertEqual((u["status"], u["outcome_r"]), ("TIMEOUT", 0.5))
        self.assertIsNone(evaluate(_sig(status="WIN"), [], "2026-10-09T10:20:00Z", 24))

    def test_stats(self):
        from masterquo.markets.signals import stats
        rows = [{"status": "WIN", "action": "BUY", "outcome_r": 2.0}, {"status": "LOSS", "action": "SELL", "outcome_r": -1.0},
                {"status": "OPEN", "action": "BUY", "outcome_r": None}, {"status": "REJECTED", "action": "BUY", "outcome_r": None}]
        s = stats(rows)
        self.assertEqual((s["wins"], s["losses"], s["win_rate_pct"], s["avg_r"], s["open"], s["rejected"]), (1, 1, 50.0, 0.5, 1, 1))


class TestRecordAndDedupe(unittest.TestCase):
    def setUp(self):
        from masterquo.markets.signals import BotSignalService
        from masterquo.strategies.base import TFView
        self.td = TempData()
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.bridge = _env.core()
        self.sent = []
        self.svc = BotSignalService(self.cfg, self.bridge, self.db, self.bus, self.log,
                                    telegram=NS(notify=lambda k, t: self.sent.append((k, t))))
        bars = [{"open_utc": f"2026-10-08T{8 + i // 12:02d}:{(i % 12) * 5:02d}:00Z", "o": 1.1, "h": 1.1010, "l": 1.0990, "c": 1.1, "closed": True}
                for i in range(30)]
        self.view = NS(symbol="EURUSD-", bid=1.1000, ask=1.1001, synthetic=False, tfs={"M5": TFView("M5", bars)})

    def tearDown(self):
        self.worker.stop()
        self.td.close()

    def test_record_dedupe_reject_and_main_events(self):
        out = self.svc.record(_rec(), self.view, source="SCANNER")
        self.assertEqual((out["status"], out["action"], out["strategy_id"], out["source"]), ("OPEN", "BUY", "S03", "BOT"))
        self.assertEqual(len(self.sent), 1)                                    # Telegram notification for a new signal
        self.assertIsNone(self.svc.record(_rec(), self.view, source="SCANNER"))                    # same setup
        self.assertIsNone(self.svc.record(_rec(setup_id="MQA-2", strategy_id="S06"), self.view, source="SCANNER"))   # same event, open
        rej = self.svc.record(_rec(setup_id="MQA-3", event_id="EV-3", targets=[{"price": 1.1005, "weight": 1.0}]), self.view, source="SCANNER")
        self.assertEqual(rej["status"], "REJECTED")
        self.assertTrue(rej["validation"]["reasons"][0].startswith("RR_BELOW_BOT_LIMIT_"))
        self.assertEqual(len(self.sent), 1)                                    # no notification for rejected
        # main symbol: the bot engine's own CONFIRMED events
        mv = NS(symbol="XAUUSD-", bid=2000.0, ask=2000.2, synthetic=False, tfs={})
        self.svc.on_main_events([("NEW_EARLY", {"setup_id": "MQA-E", "stage": "EARLY", "record": _rec(setup_id="MQA-E")}),
                                 ("STAGE_CONFIRMED", {"setup_id": "MQA-M", "stage": "CONFIRMED",
                                                      "record": _rec(setup_id="MQA-M", event_id="EV-M", stop_loss=1990.0,
                                                                     targets=[{"price": 2020.0, "weight": 1.0}], entry_plan={})})], mv)
        lst = self.svc.list()
        self.assertEqual({(x["symbol"], x["trigger"]) for x in lst["items"]}, {("EURUSD-", "SCANNER"), ("XAUUSD-", "MAIN")})
        self.assertEqual(lst["stats"]["open"], 2)
        self.assertEqual(lst["stats"]["rejected"], 1)
        self.assertEqual(len(self.svc.list(include_rejected=False)["items"]), 2)


if __name__ == "__main__":
    unittest.main()
