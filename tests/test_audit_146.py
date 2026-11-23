"""1.46 audit fixes - regression tests. Each test fails on 1.45.0 (evidence in docs/AUDYT_1_45.md) and passes after the fix."""
from __future__ import annotations

import os
import unittest

import _env  # noqa: F401


class TestBodyNum(unittest.TestCase):
    def test_wrong_types_are_400_not_500(self):
        from fastapi import HTTPException

        from masterquo.api.app import body_num
        self.assertEqual(body_num({"n": "7"}, "n", 1, int), 7)
        self.assertEqual(body_num({}, "n", 1, int), 1)
        self.assertIsNone(body_num({"v": None}, "v", None, float))
        for bad in ("abc", [1], {"a": 1}, True, "nan", "inf"):
            with self.assertRaises(HTTPException) as cm:
                body_num({"n": bad}, "n", 1, float if bad in ("nan", "inf") else int, 0, 10)
            self.assertEqual(cm.exception.status_code, 400, bad)
        with self.assertRaises(HTTPException):
            body_num({"n": 11}, "n", 1, int, 0, 10)


class TestMarketZonesEmptySeries(unittest.TestCase):
    def test_as_of_before_data_is_no_data_not_index_error(self):
        from masterquo.zones import market as MZ
        from masterquo.zones.series import Series
        s = Series.from_bars([], "M5", 1_700_000_000.0)
        r = MZ.compute_tf(s, "XAUUSD", 0.01, None)                     # 1.45: IndexError in strategies.indicators.true_range
        self.assertEqual((r["state"], r["bars"], r["atr"]), ("NO_DATA", 0, None))
        out = MZ.compute({"M5": s}, instrument="XAUUSD", symbol="XAUUSD-", tick=0.01, as_of=1_700_000_000.0)
        self.assertIn("M5", str(out))


class TestBootstrapProbe(unittest.TestCase):
    """1.45.0: Bootstrap.verify_all raised KeyError 'tabicl' (tsfm_runtime.lock has no such model) -> the bootstrap thread died on every start,
    the components after it were never verified and no heavy runtime was ever queued."""

    def test_verify_all_survives_and_tabicl_uses_its_own_env(self):
        import pathlib
        import tempfile
        import types

        from masterquo.bootstrap import COMPONENTS, Bootstrap
        from masterquo.tsfm.service import TsfmService
        from masterquo.tsfm.settings import SettingsStore
        td = pathlib.Path(tempfile.mkdtemp())
        st = SettingsStore(td / "s.json")

        class Svc:
            settings = st
            jobs: dict = {}

            def env_status(self, mid):
                return TsfmService.env_status(self, mid)

            def weights_root(self):
                return td / "w"
        b = Bootstrap(types.SimpleNamespace(tsfm=Svc(), kronos=None, demo=False), state_file=td / "b.json")
        out = b.verify_all()
        states = {c["id"]: c["state"] for c in out["components"]}
        self.assertEqual(len(states), len(COMPONENTS))
        self.assertEqual(states["tsfm_tabicl"], "NOT_INSTALLED")          # not a crash, not FAILED: the env / weights are simply absent
        self.assertEqual(states["kronos_model"], "NOT_INSTALLED")        # the component AFTER tabicl is verified too
        self.assertTrue(all(v != "PENDING" for v in states.values()))

    def test_a_raising_probe_is_recorded_not_fatal(self):
        import pathlib
        import tempfile

        from masterquo.bootstrap import Bootstrap

        def boom():
            raise KeyError("x")
        td = pathlib.Path(tempfile.mkdtemp())
        b = Bootstrap(state_file=td / "b.json", probes={"tsfm_chronos2": boom})
        states = {c["id"]: c for c in b.verify_all()["components"]}
        self.assertEqual(states["tsfm_chronos2"]["state"], "FAILED")
        self.assertIn("PROBE_ERROR", states["tsfm_chronos2"]["detail"])


class TestWallsStoreRestart(unittest.TestCase):
    """1.45.0: the fingerprint held a tuple; after the JSON round trip (first freeze after a restart) it was a list -> never equal -> every restart
    created version N+1 with a new snapshot_id for the same input (and S12 got a new setup identity for the same market event)."""

    def test_same_input_after_restart_keeps_snapshot_id(self):
        from _env import TempData

        from masterquo.analysis.walls import WallsStore
        from masterquo.db.database import Database
        td = TempData()
        try:
            db = Database()
            snap = {"status": "OK", "symbol": "XAUUSD-", "anchor_time": "2026-11-20T00:00:00Z", "source_type": "HV_PROXY", "sigma_annual": 0.18,
                    "obs_id": None, "band_sigma": 0.15, "available_at": "2026-11-20T00:05:00Z",
                    "walls": [{"k": 1.0, "side": "UPPER", "level": 2410.0}, {"k": 2.0, "side": "UPPER", "level": 2430.0},
                              {"k": 1.0, "side": "LOWER", "level": 2390.0}]}
            a = WallsStore(db).freeze(dict(snap, walls=[dict(w) for w in snap["walls"]]))
            b = WallsStore(db).freeze(dict(snap, walls=[dict(w) for w in snap["walls"]]))     # new store = application restart
            self.assertEqual((b["snapshot_id"], b["snapshot_version"]), (a["snapshot_id"], 1))
            self.assertEqual(db.one("SELECT COUNT(*) n FROM walls_snapshots")["n"], 1)
            c = WallsStore(db).freeze(dict(snap, sigma_annual=0.25, walls=[dict(w) for w in snap["walls"]]))   # a real change -> next version
            self.assertEqual(c["snapshot_version"], 2)
        finally:
            td.close()


class TestApiInputValidation(unittest.TestCase):
    """Smoke test 1.45.0: these requests answered 500 (Internal Server Error) - now 400 with a reason."""

    @classmethod
    def setUpClass(cls):
        os.environ["PMW_BOOTSTRAP"] = "0"
        from _demo_server import Server
        cls.S = Server
        Server.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()

    def test_bad_values_answer_400(self):
        c = self.S.call
        self.assertEqual(c("/api/v1/lab/memory?tf=M5&t=garbage")[0], 400)
        code, _ = c("/api/v1/tlg/profile", {"username": "Walidacja", "class_id": "THE_ROOKIE", "difficulty": "EASY"})
        self.assertIn(code, (200, 409))
        self.assertEqual(c("/api/v1/tlg/sim", {"symbol": "XAUUSD", "count": "abc"})[0], 400)
        self.assertEqual(c("/api/v1/tlg/sim/1/step", {"n": "x"})[0], 400)
        self.assertEqual(c("/api/v1/asge/run", {"timeframe": "H1", "children": "x"})[0], 400)
        self.assertEqual(c("/api/v1/asge/run", {"timeframe": "H1", "children": 10_000})[0], 400)
        self.assertEqual(c("/api/v1/indicators/calculate", {"method": "SMA", "period": 5, "count": "x"})[0], 400)
        self.assertEqual(c("/api/v1/indicators/calculate", {"method": "SMA", "period": 5, "bars": [1, 2]})[0], 400)
        self.assertEqual(c("/api/v1/kronos/validate", {"max_origins": "x"})[0], 400)
        self.assertEqual(c("/api/v1/models/foundation/validate", {"max_origins": "x"})[0], 400)
        self.assertEqual(c("/api/v1/quant/tabicl/reconstruct", {"days": "x"})[0], 400)
        code, body = c("/api/v1/market-zones/as-of?as_of=2020-01-01T00:00:00Z")
        self.assertEqual(code, 200, body)                              # was 503 "IndexError: list index out of range"


if __name__ == "__main__":
    unittest.main()


class TestAgentGateAndBudget(unittest.TestCase):
    """1.45.0: (a) a USER_QUESTION run with the setup id replaced the AI gate assessment of a CONFIRMED setup (WAIT answer -> DISAGREE veto) and
    marked a running SETUP_CONFIRMED assessment as superseded; (b) a model id without an exact price (e.g. a dated id returned by the API)
    stored est_cost_usd = NULL and the daily budget counted it as 0."""

    def setUp(self):
        import test_agent as TA
        self.TA = TA
        self.t = TA.TestAgent("test_veto_policy")
        self.t.setUp()
        self.agent = self.t.agent

    def tearDown(self):
        self.t.tearDown()

    def _handle(self, trigger, ans, question=None):
        import asyncio
        import json
        TA = self.TA
        client = TA.ScriptedClient([TA.msg([TA.text(json.dumps(ans))], "end_turn")])
        self.agent._client_get = lambda: client
        self.agent.last_auto_run = self.agent.last_user_run = 0
        self.agent.loop = None
        req = {"trigger": trigger, "snapshot_id": "SNP-1", "setup_id": "MQS-1", "setup_state": "CONFIRMED", "question": question, "key": trigger}
        asyncio.run(self.agent._handle(req))

    def test_user_question_does_not_replace_gate_assessment(self):
        TA = self.TA
        self._handle("SETUP_CONFIRMED", TA.answer())                                   # SELL for a SHORT setup -> PASS
        self.assertEqual(self.agent.by_setup["MQS-1"]["record"]["proposed_action"], "SELL")
        self._handle("USER_QUESTION", TA.answer(proposed_action="WAIT", answer_pl="Ryzyka newsów: ..."), question="Jakie są ryzyka?")
        self.assertEqual(self.agent.by_setup["MQS-1"]["record"]["proposed_action"], "SELL")   # the question's WAIT is not a veto
        self.assertEqual(self.agent.last_result["status_note"], "ANSWER_ONLY_NOT_A_GATE_ASSESSMENT")

    def test_unknown_or_dated_model_price_is_not_zero(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 0}
        self.assertEqual(self.agent._cost("claude-opus-5-5-20261101", usage), 4.0)             # dated id -> base model price
        self.assertEqual(self.agent._cost("some-unknown-model", usage, requested="claude-opus-5-5"), 4.0)
        self.assertEqual(self.agent._cost("some-unknown-model", usage), 10.0)                  # no price at all -> upper bound, never 0 / None
