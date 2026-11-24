"""1.46 audit, group B_misc_1 - regression tests (SYNTHETIC_TEST data only, no network, no demo server).

chunk_01#11  agent: an error while broadcasting the status in the worker's finally no longer ends the worker task
chunk_01#12  agent: _strict_gate iterates a snapshot of `pending` (engine thread vs loop / API threads)
chunk_01#10  agent: an unexpected exception during a run still writes the agent_runs row (audit only, est_cost_usd NULL), then re-raises
chunk_01#16  agent: by_setup / _started_seq are bounded
chunk_01#18  agent: the SVP zone prompt uses the display name Apollo23
chunk_05#10  RiskLoot.evaluate validates scores / setup_family itself (no NaN, no 500, no LEGENDARY from 1e6)
chunk_05#12  RiskLoot: an event without position_id and event_id is vetoed (EVENT_UNIDENTIFIED)
chunk_05#13  RiskLoot: PATIENCE loot only for a verified NO_TRADE
chunk_05#14  RiskLoot.grant: an item already owned -> granted False / ALREADY_OWNED, no extra LOOT_GRANT row
chunk_05#18  traps.behaviour: "after a loss" = last trade CLOSED before the open; first trade checked for chasing
chunk_05#19  traps.detect: recommendation_status says INSUFFICIENT_COVERAGE instead of a silent NONE
chunk_05#3   AssetRegistry.autodetect: a broker name outside SYMBOL_RE -> None + rejection note (was pydantic ValidationError -> HTTP 500)
chunk_05#21  AssetRegistry.rejections is filled (by the autodetect rejection above)
chunk_05#20  AssetRegistry.refresh: a read failure gives a new UNVERIFIED entry (was the old OK status next to READ_FAILED)
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from typing import ClassVar
from unittest import mock

import _env  # noqa: F401
from _env import TempData

CTX = {"snapshot_id": "SNP-1", "as_of": "2026-10-08T12:00:00Z", "symbol": "XAUUSD-", "alias": "XAUUSD", "session_epoch": 1, "account_key": "srv:1",
       "account_currency": "USD", "account_trade_mode": "DEMO",
       "dq": {"data_quality": "GOOD", "market_state": "OPEN", "reason_codes": [], "timeframes": {"M15": {"status": "OK", "closed_bars": 300, "required": 70}}},
       "quote": {"bid": 2000.0, "ask": 2000.2}, "legacy": {"m02": {"structural_direction": "BEARISH", "timeframes": {}}, "m03": {"timeframes": {}}, "m07": {}},
       "closed_bars": {"M15": []},
       "setup": {"setup_id": "MQS-1", "state": "CONFIRMED", "state_changed_at": "2026-10-08T11:59:00Z", "direction": "SHORT",
                 "strategy_id": "XAU-S01", "profile": "MVP", "setup_tf": "M15"},
       "levels": None, "risk": None, "macro": {"status": "PARTIAL"}, "headlines": [], "upcoming_events": [], "history": [], "lessons": []}


def _msg(blocks, stop):
    return NS(content=blocks, stop_reason=stop, usage=NS(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0),
              model="claude-opus-5-5", stop_details=None)


class _Scripted:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self
        self.beta = NS(messages=self)

    async def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


class _AgentCase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-not-a-real-key"
        from masterquo.agent.service import ClaudeAgent
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.events import AppLog, EventBus
        from masterquo.secrets_store import SecretStore
        self.cfg = ConfigStore()
        self.cfg.update({"agent": {"model": "claude-opus-5-5"}})
        self.db = Database()
        bus = EventBus()
        self.agent = ClaudeAgent(self.cfg, SecretStore(), self.db, bus, AppLog(self.db, bus), lambda sid: CTX)

    def tearDown(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.td.close()


class TestAgentWorkerAndGate(_AgentCase):
    def test_status_publish_error_does_not_end_the_worker(self):
        """chunk_01#11: status() -> spent_today() -> 'database is locked' in the finally ended the worker; later requests never ran."""
        a = self.agent
        handled = []

        async def fake_handle(req):
            handled.append(req["question"])

        def locked():
            raise sqlite3.OperationalError("database is locked")

        from masterquo.agent import service as S
        a._handle = fake_handle
        a.spent_today = locked
        loop = asyncio.new_event_loop()
        try:
            a.attach(loop)
            for q in ("q1", "q2", "q3"):
                self.assertIsNotNone(a.request("USER_QUESTION", snapshot_id=None, setup_id=None, setup_state=None, question=q))

            async def wait():
                for _ in range(200):
                    if len(handled) == 3:
                        return
                    await asyncio.sleep(0.01)

            with mock.patch.object(S.log, "exception") as logged:
                loop.run_until_complete(wait())
        finally:
            tasks = asyncio.all_tasks(loop)
            for t in tasks:
                t.cancel()
            if tasks:
                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.close()
        self.assertEqual(handled, ["q1", "q2", "q3"])
        self.assertEqual(a.pending, {})
        self.assertTrue(logged.called)                                         # the failed broadcast is logged, not silent

    def test_strict_gate_iterates_a_snapshot_of_pending(self):
        """chunk_01#12: another thread changing `pending` while the gate iterates it raised RuntimeError in the decision path."""
        a = self.agent

        class Entry(dict):
            def get(self, k, d=None):                      # stands for a thread switch: the loop / API thread adds a request meanwhile
                a.pending["late"] = {"request_id": "AGQ-2", "setup_id": "OTHER-2"}
                return dict.get(self, k, d)

        a.pending["k1"] = Entry(request_id="AGQ-1", setup_id="OTHER-1")
        g = a._strict_gate(CTX["setup"], session_epoch=1, account_key="srv:1", now_iso="2026-10-08T12:00:30Z")
        self.assertEqual(g, {"status": "PENDING", "reason_codes": ["AI_ASSESSMENT_MISSING"]})
        a.pending.clear()
        a.pending["k2"] = {"request_id": "AGQ-3", "setup_id": "MQS-1"}
        g = a._strict_gate(CTX["setup"], session_epoch=1, account_key="srv:1", now_iso="2026-10-08T12:00:30Z")
        self.assertEqual(g["reason_codes"], ["AI_ASSESSMENT_RUNNING"])          # unchanged gate semantics

    def test_unexpected_tool_error_still_records_run(self):
        """chunk_01#10: an AttributeError from a tool skipped the agent_runs INSERT (no audit row). The row is audit only: its est_cost_usd
        stays NULL, so spent_today() / the daily budget (an AI gate input) are exactly as in 1.45."""
        a = self.agent

        def broken_mm():
            raise AttributeError("'list' object has no attribute 'get'")

        ctx = {**CTX, "master_models_fn": broken_mm}
        client = _Scripted([_msg([NS(type="tool_use", name="get_master_models", input={}, id="tu_1")], "tool_use")])
        a._client_get = lambda: client
        req = {"trigger": "SETUP_CONFIRMED", "snapshot_id": "SNP-1", "setup_id": "MQS-1", "setup_state": "CONFIRMED", "question": None, "key": "k"}
        self.assertEqual(a.spent_today(), 0.0)
        with self.assertRaises(AttributeError):                              # the worker / gate still see the same error as before
            asyncio.run(a.run_once(req, ctx))
        row = self.db.one("SELECT status, error_code, input_tokens, output_tokens, est_cost_usd FROM agent_runs WHERE setup_id = ?", ("MQS-1",))
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "INTERNAL_ERROR")
        self.assertIn("AttributeError", row["error_code"])
        self.assertEqual((row["input_tokens"], row["output_tokens"]), (1000, 200))
        self.assertIsNone(row["est_cost_usd"])
        self.assertEqual(a.spent_today(), 0.0)                               # the daily budget input is unchanged from 1.45
        self.assertEqual(a.by_setup, {})                                     # no gate result written (unchanged behaviour)

    def test_setup_maps_are_bounded(self):
        """chunk_01#16: by_setup / _started_seq grew by one entry per setup for the life of the process."""
        from masterquo.agent import service as S
        a = self.agent

        async def fake_run(req, ctx):
            return {"status": "TIMEOUT", "error": "t", "run_id": req["setup_id"]}

        a.run_once = fake_run
        with mock.patch.object(S, "MAX_TRACKED_SETUPS", 5, create=True):
            for i in range(12):
                sid = f"MQS-{i}"
                asyncio.run(a._handle({"trigger": "SETUP_CONFIRMED", "snapshot_id": "SNP-1", "setup_id": sid, "setup_state": "CONFIRMED",
                                       "question": None, "key": sid}))
            self.assertLessEqual(len(a.by_setup), 5)
            self.assertLessEqual(len(a._started_seq), 5)
            self.assertEqual(a.by_setup["MQS-11"]["status"], "TIMEOUT")      # the newest stays
            self.assertNotIn("MQS-0", a.by_setup)
            self.cfg.update({"agent": {"enabled": False}})                    # preflight-skipped CONFIRMED runs are bounded too
            for i in range(12, 20):
                sid = f"MQS-{i}"
                asyncio.run(a._handle({"trigger": "SETUP_CONFIRMED", "snapshot_id": "SNP-1", "setup_id": sid, "setup_state": "CONFIRMED",
                                       "question": None, "key": sid}))
            self.assertLessEqual(len(a.by_setup), 5)
            self.assertEqual(a.by_setup["MQS-19"]["status"], "AGENT_DISABLED")

    def test_svp_zone_prompt_uses_display_name(self):
        """chunk_01#18: the SVP zone prompt introduced the agent as 'PepeMarketWizard'."""
        client = _Scripted([NS(content=[NS(text='{"proposals": []}')], usage=NS(input_tokens=1, output_tokens=1))])
        self.agent._client_get = lambda: client
        out = asyncio.run(self.agent.propose_zones({"snapshot_id": "SVP-1"}))
        self.assertTrue(out["ok"], out)
        system = client.calls[0]["system"]
        self.assertNotIn("PepeMarketWizard", system)
        self.assertIn("Apollo23", system)
        self.assertIn('{"proposals": [{"profile_id"', system)                # the JSON contract text is intact


class TestRiskLoot(unittest.TestCase):
    EV: ClassVar[dict] = {"event_id": "e1", "position_id": "p1", "source_mode": "SIMULATOR", "setup_family": "EMA_SMMA_PULLBACK", "strategy_status": "VALIDATED",
          "sfb_status": "ELIGIBLE", "trap_no_trade": False, "risk_breach": False, "attribution": "SIM:1",
          "scores": {"setup_quality": 90, "risk_discipline": 95, "execution_adherence": 85, "journal_learning": 80, "evidence_quality": 85}}

    def test_invalid_scores_and_family_are_vetoed(self):
        """chunk_05#10: list scores / 'abc' were exceptions, NaN came back as score NaN, 1e6 / True were accepted."""
        from masterquo.apollo import risk_loot as R
        s = self.EV["scores"]
        cases = (({"scores": [1]}, "INVALID_SCORE"), ({"scores": {**s, "setup_quality": float("nan")}}, "INVALID_SCORE"),
                 ({"scores": {**s, "setup_quality": float("inf")}}, "INVALID_SCORE"), ({"scores": {**s, "setup_quality": "abc"}}, "INVALID_SCORE"),
                 ({"scores": {**s, "setup_quality": 1e6}}, "INVALID_SCORE"), ({"scores": {**s, "setup_quality": -5}}, "INVALID_SCORE"),
                 ({"scores": {**s, "setup_quality": True}}, "INVALID_SCORE"), ({"scores": {**s, "evidence_quality": "85"}}, "INVALID_SCORE"),
                 ({"setup_family": ["X"]}, "INVALID_SETUP_FAMILY"))
        for patch, code in cases:
            out = R.evaluate({**self.EV, **patch})
            self.assertFalse(out["eligible"], patch)
            self.assertIn(code, out["vetoes"], patch)
            self.assertIsNone(out["score"], patch)
            json.dumps(out, allow_nan=False)                                  # always serialisable
        self.assertTrue(R.evaluate(self.EV)["eligible"])                       # valid input unchanged
        self.assertTrue(R.evaluate({**self.EV, "scores": {**s, "setup_quality": 90.5}})["eligible"])

    def test_event_without_any_id_is_vetoed(self):
        """chunk_05#12: no position_id and no event_id -> one shared idempotency key for all such events."""
        from masterquo.apollo import risk_loot as R
        out = R.evaluate({**self.EV, "event_id": None, "position_id": None})
        self.assertFalse(out["eligible"])
        self.assertIn("EVENT_UNIDENTIFIED", out["vetoes"])
        self.assertTrue(R.evaluate({**self.EV, "position_id": None})["eligible"])   # event_id alone is enough

    def test_patience_needs_verified_no_trade(self):
        """chunk_05#13: VERIFIED_NO_TRADE_VETO with trap_no_trade False was granted PATIENCE loot."""
        from masterquo.apollo import risk_loot as R
        out = R.evaluate({**self.EV, "setup_family": "VERIFIED_NO_TRADE_VETO", "trap_no_trade": False, "no_trade_respected": True})
        self.assertFalse(out["eligible"])
        self.assertIn("NO_TRADE_NOT_VERIFIED", out["vetoes"])
        ok = R.evaluate({**self.EV, "setup_family": "VERIFIED_NO_TRADE_VETO", "trap_no_trade": True, "no_trade_respected": True})
        self.assertTrue(ok["eligible"])

    def test_grant_of_an_owned_item_is_not_reported_as_granted(self):
        """chunk_05#14: a second earned award for another position -> new LOOT_GRANT row + granted=True, inventory unchanged."""
        from masterquo.apollo import risk_loot as R
        from masterquo.trader_life_game import GameService
        with tempfile.TemporaryDirectory() as d:
            g = GameService(Path(d))
            g.create_profile({"username": "Kuba", "class_id": "THE_ROOKIE", "difficulty": "EASY"})
            a = R.grant(g, self.EV)
            self.assertTrue(a["granted"])
            b = R.grant(g, {**self.EV, "event_id": "e2", "position_id": "p2"})
            self.assertFalse(b["granted"])
            self.assertTrue(b.get("already_owned"))
            self.assertEqual(b.get("reason"), "ALREADY_OWNED")
            self.assertFalse(b["duplicate"])
            n = g._one("SELECT COUNT(*) AS n FROM gold_ledger WHERE reason = 'LOOT_GRANT'")["n"]
            self.assertEqual(n, 1)
            c = R.grant(g, {**self.EV, "event_id": "e1-partial-2"})          # same position -> still a duplicate
            self.assertFalse(c["granted"])
            self.assertTrue(c["duplicate"])
            g.close()


class TestTraps(unittest.TestCase):
    def test_behaviour_uses_last_closed_trade_and_checks_first_trade(self):
        """chunk_05#18: a trade opened before the earlier-opened loser closed got post-loss flags; the first trade was never checked."""
        from masterquo.apollo import traps as T
        tr = [{"opened": 0, "closed": 20_000, "size": 1, "net": -10, "entry_move_atr": 5},
              {"opened": 100, "closed": 200, "size": 3, "net": 5},
              {"opened": 50_000, "closed": 50_100, "size": 1, "net": 4},
              {"opened": 60_000, "closed": 60_100, "size": 1, "net": 3},
              {"opened": 70_000, "closed": 70_100, "size": 1, "net": 2}]
        flags = T.behaviour(tr)["flags"]
        at100 = {f["code"] for f in flags if f.get("at") == 100}
        self.assertNotIn("POST_LOSS_SIZE_ESCALATION", at100)
        self.assertNotIn("RAPID_REENTRY_AFTER_LOSS", at100)
        self.assertIn({"code": "LATE_MOVE_CHASE_POOR_RR", "at": 0}, flags)
        # a real re-entry right after the loser closed is still flagged
        tr2 = [*tr[:1], {"opened": 20_100, "closed": 20_200, "size": 3, "net": 5}, *tr[2:]]
        codes = {f["code"] for f in T.behaviour(tr2)["flags"] if f.get("at") == 20_100}
        self.assertEqual(codes, {"POST_LOSS_SIZE_ESCALATION", "RAPID_REENTRY_AFTER_LOSS"})

    def test_recommendation_status_explains_insufficient_coverage(self):
        """chunk_05#19: with OHLC only coverage is 0.2 < 0.3 - a high score silently gave recommendation NONE."""
        from masterquo.apollo import traps as T
        bars = [{"h": 101.0, "l": 99.0, "c": 100.0} for _ in range(25)] + [{"h": 103.0, "l": 99.5, "c": 100.5}]
        r = T.detect(bars)
        self.assertGreaterEqual(r["market_trap_score"], 60)
        self.assertEqual(r["recommendation"], "NONE")                          # unchanged
        self.assertEqual(r["recommendation_status"], "INSUFFICIENT_COVERAGE")
        r2 = T.detect(bars, spread_points=10.0, spread_baseline=10.0)
        self.assertEqual((r2["recommendation"], r2["recommendation_status"]), ("WAIT", "OK"))
        self.assertEqual(T.detect(bars[:5])["recommendation_status"], "UNAVAILABLE")


class _Bridge:
    def __init__(self, rows, meta=None):
        self.rows = rows
        self.state = "CONNECTED"
        self.meta = meta
        self.fail = False

    def _call(self, fn):
        return fn(NS(symbols_get=lambda: self.rows))

    def symbol_meta(self, name, guard=False):
        if self.fail:
            raise TimeoutError("terminal timeout")
        return self.meta


class TestAssetRegistry(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        self.cfg = ConfigStore()

    def tearDown(self):
        self.td.close()

    def test_autodetect_invalid_broker_name_is_rejected_not_500(self):
        """chunk_05#3 / #21: 'BTC/USD' (outside SYMBOL_RE) raised pydantic ValidationError out of check_asset / switch."""
        from masterquo.assets.registry import AssetRegistry, SymbolNotAllowed
        rows = [{"name": "BTC/USD", "currency_base": "BTC", "currency_profit": "USD", "visible": True, "trade_mode": 4},
                {"name": "BTCUSD.x", "currency_base": "BTC", "currency_profit": "USD", "visible": False, "trade_mode": 4}]
        reg = AssetRegistry(self.cfg, _Bridge(rows))
        self.assertEqual(reg.find_on_account("BTC"), "BTC/USD")               # selection unchanged (owner decision, see report)
        self.assertIsNone(reg.autodetect("BTC"))
        with self.assertRaises(SymbolNotAllowed):                            # -> 409 in the API, not 500
            reg.check_asset("BTC", "SWITCH")
        with self.assertRaises(SymbolNotAllowed):
            reg.switch("BTC")
        self.assertIsNone(self.cfg.get().assets.mappings["BTC"].broker_symbol)   # nothing saved
        rej = reg.state()["rejections"]
        self.assertTrue(rej)
        self.assertEqual((rej[-1]["asset"], rej[-1]["broker_symbol"], rej[-1]["reason"]), ("BTC", "BTC/USD", "INVALID_BROKER_SYMBOL"))

    def test_refresh_read_failure_is_unverified_not_old_status(self):
        """chunk_05#20: after a read error the entry kept status OK next to READ_FAILED."""
        from masterquo.assets.registry import AssetRegistry
        meta = {"name": "XAUUSD-", "currency_base": "XAU", "currency_profit": "USD", "trade_calc_mode": 2, "trade_contract_size": 100,
                "digits": 2, "point": 0.01}
        b = _Bridge([], meta)
        reg = AssetRegistry(self.cfg, b)
        reg.refresh()
        first = reg.state()["assets"]["XAUUSD"]["metadata_check"]
        self.assertEqual(first["status"], "OK")
        b.fail = True
        reg.refresh()
        reg.refresh()                                                          # repeated failures do not nest
        chk = reg.state()["assets"]["XAUUSD"]["metadata_check"]
        self.assertEqual(chk["status"], "UNVERIFIED")
        self.assertEqual(chk["reasons"], ["READ_FAILED:TimeoutError"])
        self.assertEqual(chk["previous"]["status"], "OK")
        self.assertNotIn("previous", chk["previous"])
        self.assertEqual(first["status"], "OK")                               # the dict returned before is not mutated


if __name__ == "__main__":
    unittest.main()
