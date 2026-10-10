"""Multi-market scanner and AI signals: simulator markets, bridge reads, analysis, validation, tracking, full AI run
with a scripted stand-in for the Anthropic client (no network, no key, no orders)."""
import asyncio
import json
import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import _env
from _env import TempData

UTC = timezone.utc


def iso(d):
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z")


class World:
    """Fake terminal + bridge connected, server clock offset known, scanner and AI signal service."""

    def __init__(self):
        from masterquo.agent.service import ClaudeAgent
        from masterquo.agent.signals import AISignalService
        from masterquo.markets.scanner import MarketScanner
        from masterquo.secrets_store import SecretStore
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.bridge = _env.core()
        self.bridge.connect()
        self.bridge.clock.load_stored(10800, datetime.now(UTC))
        self.bridge._poll_quote()
        self.scanner = MarketScanner(self.cfg, self.bridge, self.bus, self.log)
        self.cfg.update({"agent": {"model": "claude-opus-5-5"}})
        self.agent = ClaudeAgent(self.cfg, SecretStore(), self.db, self.bus, self.log, lambda sid: None)
        self.signals = AISignalService(self.cfg, self.agent, self.scanner, self.bridge, self.db, self.bus, self.log)

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


def _sig(**kw):
    s = {"signal_id": "AIS-1", "created_at": "2026-10-08T10:00:00Z", "status": "PENDING_ENTRY", "action": "BUY", "entry_type": "LIMIT",
         "entry_price": 100.0, "stop_loss": 99.0, "take_profits_json": "[102.0, 103.0]", "valid_until": "2026-10-08T14:00:00Z",
         "filled_at": None, "fill_price": None, "tp_hit": 0}
    s.update(kw)
    return s


def _b(t, o, h, l, c, closed=True):
    return {"open_utc": t, "o": o, "h": h, "l": l, "c": c, "closed": closed, "tv": 1}


class TestSignalRules(unittest.TestCase):
    def proposal(self, **kw):
        from masterquo.agent.signals import SignalProposal
        p = {"context_id": "AIC-1", "symbol": "EURUSD-", "action": "BUY", "entry_type": "MARKET", "entry_price": None, "stop_loss": 1.0950,
             "take_profits": [1.1060, 1.1100], "confidence": 55, "horizon": "INTRADAY", "valid_minutes": 120, "timeframe_basis": "H1",
             "rationale_pl": "x", "invalidation_pl": "y", "risks_pl": [], "key_levels": [], "evidence": []}
        p.update(kw)
        return SignalProposal.model_validate(p)

    CTX = {"quote": {"bid": 1.1000, "ask": 1.1001, "spread": 0.0001}, "analysis": {"atr_h1": 0.0015, "atr_d1": 0.0070}}

    def test_validation(self):
        from masterquo.config import AISignalsConfig
        from masterquo.agent.signals import validate
        cfg = AISignalsConfig()
        v = validate(self.proposal(), self.CTX, cfg)
        self.assertTrue(v["ok"], v)
        self.assertAlmostEqual(v["entry"], 1.1001)
        self.assertEqual(v["rr"][0], round((1.1060 - 1.1001) / (1.1001 - 1.0950), 2))
        self.assertIn("STOP_LOSS_ON_WRONG_SIDE", validate(self.proposal(stop_loss=1.1050), self.CTX, cfg)["reasons"])
        self.assertIn("TAKE_PROFIT_ON_WRONG_SIDE", validate(self.proposal(take_profits=[1.0990]), self.CTX, cfg)["reasons"])
        self.assertIn("STOP_LOSS_TOO_TIGHT_VS_ATR_H1", validate(self.proposal(stop_loss=1.0999), self.CTX, cfg)["reasons"])
        self.assertIn("STOP_LOSS_TOO_WIDE_VS_ATR_D1", validate(self.proposal(stop_loss=1.07), self.CTX, cfg)["reasons"])
        self.assertIn("LIMIT_ON_WRONG_SIDE_OF_PRICE", validate(self.proposal(entry_type="LIMIT", entry_price=1.1020, stop_loss=1.0990, take_profits=[1.1100]), self.CTX, cfg)["reasons"])
        self.assertIn("ENTRY_TOO_FAR_FROM_PRICE", validate(self.proposal(entry_type="LIMIT", entry_price=1.09, stop_loss=1.085, take_profits=[1.10]), self.CTX, cfg)["reasons"])
        self.assertTrue(any(r.startswith("RR_TP1_BELOW") for r in validate(self.proposal(take_profits=[1.1010]), self.CTX, cfg)["reasons"]))
        self.assertIn("TAKE_PROFITS_NOT_ORDERED", validate(self.proposal(take_profits=[1.1100, 1.1060]), self.CTX, cfg)["reasons"])
        sell = validate(self.proposal(action="SELL", stop_loss=1.1050, take_profits=[1.0940]), self.CTX, cfg)
        self.assertTrue(sell["ok"], sell)
        self.assertAlmostEqual(sell["entry"], 1.1000)                     # SELL at Bid
        self.assertTrue(validate(self.proposal(action="NO_TRADE", entry_type=None, stop_loss=None, take_profits=[]), self.CTX, cfg)["ok"])
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.proposal(confidence=150)

    def test_tracking_limit_fill_then_win(self):
        from masterquo.agent.signals import evaluate
        bars = [_b("2026-10-08T09:45:00Z", 99, 99.5, 98, 99.2),             # before the signal: ignored even though it touches SL
                _b("2026-10-08T10:00:00Z", 100.5, 100.8, 100.2, 100.4),
                _b("2026-10-08T10:15:00Z", 100.4, 100.6, 99.9, 100.1),      # fill (touches 100), SL not hit
                _b("2026-10-08T10:30:00Z", 100.1, 102.2, 100.0, 102.0),     # TP1
                _b("2026-10-08T10:45:00Z", 102.0, 103.1, 101.9, 103.0)]     # TP2 -> WIN
        u = evaluate(_sig(), bars, "2026-10-08T11:00:00Z", 72)
        self.assertEqual(u["status"], "WIN")
        self.assertEqual(u["filled_at"], "2026-10-08T10:15:00Z")
        self.assertEqual(u["tp_hit"], 2)
        self.assertEqual(u["outcome_r"], 3.0)

    def test_tracking_partial_progress_and_same_bar_conservative(self):
        from masterquo.agent.signals import evaluate
        u = evaluate(_sig(), [_b("2026-10-08T10:15:00Z", 100.4, 100.6, 99.9, 100.1), _b("2026-10-08T10:30:00Z", 100.1, 102.2, 100.0, 102.0)],
                     "2026-10-08T10:50:00Z", 72)
        self.assertEqual((u["status"], u["tp_hit"]), ("OPEN", 1))
        open_sig = _sig(status="OPEN", filled_at="2026-10-08T10:15:00Z", fill_price=100.0, tp_hit=1)
        u = evaluate(open_sig, [_b("2026-10-08T10:45:00Z", 101, 103.5, 98.5, 101)], "2026-10-08T11:00:00Z", 72)
        self.assertEqual((u["status"], u["outcome_r"]), ("LOSS", -1.0))       # SL and TP in one bar -> loss
        u = evaluate(_sig(), [_b("2026-10-08T10:15:00Z", 100.4, 100.6, 98.8, 99.0)], "2026-10-08T10:40:00Z", 72)
        self.assertEqual(u["status"], "LOSS")                                 # fill bar also hits SL -> loss

    def test_tracking_expiry_timeout_and_market(self):
        from masterquo.agent.signals import evaluate
        u = evaluate(_sig(), [_b("2026-10-08T10:15:00Z", 101, 101.5, 100.5, 101)], "2026-10-08T15:00:00Z", 72)
        self.assertEqual(u["status"], "EXPIRED")
        m = _sig(status="OPEN", entry_type="MARKET", filled_at="2026-10-08T10:00:00Z", fill_price=100.0)
        u = evaluate(m, [_b("2026-10-08T10:00:00Z", 100, 100.5, 99.5, 100.2), _b("2026-10-09T10:00:00Z", 100.2, 100.6, 99.6, 100.5)],
                     "2026-10-09T10:20:00Z", 24)
        self.assertEqual((u["status"], u["outcome_r"]), ("TIMEOUT", 0.5))
        self.assertIsNone(evaluate(_sig(status="WIN"), [], "2026-10-09T10:20:00Z", 24))

    def test_stats(self):
        from masterquo.agent.signals import stats
        rows = [{"status": "WIN", "action": "BUY", "outcome_r": 2.0}, {"status": "LOSS", "action": "SELL", "outcome_r": -1.0},
                {"status": "NO_TRADE", "action": "NO_TRADE", "outcome_r": None}, {"status": "OPEN", "action": "BUY", "outcome_r": None},
                {"status": "REJECTED", "action": "BUY", "outcome_r": None}]
        s = stats(rows)
        self.assertEqual((s["wins"], s["losses"], s["win_rate_pct"], s["avg_r"], s["no_trade"], s["open"], s["rejected"]), (1, 1, 50.0, 0.5, 1, 1, 1))


# --------------------------------------------------------------------------------------------- scripted Claude
def msg(blocks, stop):
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=1500, output_tokens=300, cache_read_input_tokens=0, cache_creation_input_tokens=0),
              model="claude-opus-5-5", stop_details=None)


class SignalClient:
    """Calls get_symbol_overview, then answers with levels computed from the tool result (like a model would)."""

    def __init__(self, action="BUY", mutate=None):
        self.action, self.mutate, self.calls = action, mutate, []
        self.messages = self
        self.beta = NS(messages=self)

    async def create(self, **kw):
        self.calls.append(kw)
        msgs = kw["messages"]
        if len(msgs) == 1:
            return msg([NS(type="tool_use", name="get_symbol_overview", input={}, id="tu_1"),
                        NS(type="tool_use", name="get_volatility_levels", input={}, id="tu_2")], "tool_use")
        ov = json.loads(msgs[-1]["content"][0]["content"])
        q, atr = ov["quote"], ov["atr_h1"]
        ctx_id = re.search(r"(AIC-[0-9a-f]+)", msgs[0]["content"]).group(1)
        if self.action == "BUY":
            e = q["ask"]
            ans = {"action": "BUY", "entry_type": "MARKET", "entry_price": None, "stop_loss": round(e - 1.2 * atr, 6),
                   "take_profits": [round(e + 1.8 * atr, 6), round(e + 3 * atr, 6)]}
        else:
            ans = {"action": "NO_TRADE", "entry_type": None, "entry_price": None, "stop_loss": None, "take_profits": []}
        ans.update(context_id=ctx_id, symbol=ov["symbol"], confidence=60, horizon="INTRADAY", valid_minutes=180, timeframe_basis="H1",
                   rationale_pl="Trend H4 w górę, korekta do EMA20.", invalidation_pl="Zamknięcie H1 poniżej SL.", risks_pl=["dane makro"],
                   key_levels=[{"price": q["bid"], "label": "cena"}], evidence=["H4 trend UP"])
        if self.mutate:
            self.mutate(ans)
        return msg([NS(type="text", text=json.dumps(ans))], "end_turn")


class TestAISignalRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-not-a-real-key"
        cls.w = World()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        cls.w.close()
        cls.td.close()

    def run_signal(self, symbol, client):
        self.w.agent._client_get = lambda: client
        ctx = self.w.signals.build_context(symbol)
        return asyncio.run(self.w.signals.run_once({"symbol": symbol, "trigger": "USER", "note": None}, ctx)), ctx

    def test_01_buy_signal_validated_stored_and_tracked(self):
        c = SignalClient("BUY")
        r, ctx = self.run_signal("EURUSD-", c)
        sig = r["signal"]
        self.assertEqual(r["status"], "OPEN", sig)
        self.assertEqual((sig["symbol"], sig["action"], sig["entry_type"]), ("EURUSD-", "BUY", "MARKET"))
        self.assertAlmostEqual(sig["entry_price"], ctx["quote"]["ask"])
        self.assertEqual(sig["rr1"], 1.5)
        self.assertTrue(sig["synthetic"])
        self.assertEqual(c.calls[0]["output_config"]["format"]["type"], "json_schema")
        self.assertEqual({t["name"] for t in c.calls[0]["tools"]} >= {"get_symbol_overview", "get_closed_bars"}, True)
        self.assertNotIn("sk-ant", json.dumps(c.calls[0], default=str))
        run = self.w.db.one("SELECT trigger, status, est_cost_usd FROM agent_runs ORDER BY started_at DESC LIMIT 1")
        self.assertEqual((run["trigger"], run["status"]), ("AI_SIGNAL_USER", "OK"))   # cost counts toward the agent's daily budget
        # tracking: no orders are ever sent, only the record changes
        before = len(self.w.fake._positions)
        self.w.signals.track()
        self.assertEqual(len(self.w.fake._positions), before)
        lst = self.w.signals.list(symbol="EURUSD-")
        self.assertEqual(lst["stats"]["open"], 1)

    def test_02_no_trade_and_rejected(self):
        r, _ = self.run_signal("GBPUSD-", SignalClient("NO_TRADE"))
        self.assertEqual(r["status"], "NO_TRADE")
        r, _ = self.run_signal("USDJPY-", SignalClient("BUY", mutate=lambda a: a.update(stop_loss=a["take_profits"][0])))
        self.assertEqual(r["status"], "REJECTED")
        self.assertIn("STOP_LOSS_ON_WRONG_SIDE", r["signal"]["validation"]["reasons"])

    def test_03_context_mismatch_and_bad_json(self):
        r, _ = self.run_signal("US30-", SignalClient("BUY", mutate=lambda a: a.update(symbol="EURUSD-")))
        self.assertEqual((r["status"], r["error"]), ("FAILED", "CONTEXT_OR_SYMBOL_MISMATCH"))

        class Bad(SignalClient):
            async def create(self, **kw):
                self.calls.append(kw)
                return msg([NS(type="text", text="nie wiem")], "end_turn")
        r, _ = self.run_signal("US30-", Bad())
        self.assertEqual(r["status"], "FAILED")
        self.assertIn("SCHEMA_VALIDATION_FAILED", r["error"])

    def test_04_preflight_without_key(self):
        key = os.environ.pop("ANTHROPIC_API_KEY")
        try:
            loop = asyncio.new_event_loop()
            self.w.signals.loop, self.w.signals.queue = loop, asyncio.Queue()
            self.assertEqual(self.w.signals.request("EURUSD-")["error"], "AI_UNAVAILABLE_NO_KEY")
            loop.close()
        finally:
            os.environ["ANTHROPIC_API_KEY"] = key


if __name__ == "__main__":
    unittest.main()
