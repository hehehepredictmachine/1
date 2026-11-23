"""WF3.2 TASK 018 - Strategy Filter Bucket: strict config (apply_to_execution not configurable), hard compatibility, lineage-only evidence
(SIGNAL_SIMULATION never counts), gates for ELIGIBLE, OFF parity, ASSIST narrows only / NO_TRADE_BUCKET, basket service integration."""
from __future__ import annotations

import random
import tempfile
import types
import unittest
from pathlib import Path

import _env  # noqa: F401


def outcomes(s, n=150, mean=0.3, days=60, src="TASK014", regimes=("TREND", "RANGE"), seed=1, cost=True):
    rnd = random.Random(seed)
    t0 = 1_760_000_000
    return [{"strategy_id": s["strategy_id"], "version": s["version"], "config_hash": s["config_hash"], "net_R": rnd.gauss(mean, 1.0),
             "closed_ts": t0 + i * days * 86400 / n, "event_group_id": f"e{i}", "regime": regimes[i % len(regimes)], "cost_complete": cost, "source": src}
            for i in range(n)]


class TestSFB(unittest.TestCase):
    def setUp(self):
        from masterquo.baskets import catalog as C
        self.C = C
        self.fx = C.BY_ID["FX_SMC_01"]
        self.cp = C.BY_ID["CP_SMC_01"]
        self.scope = {"profile": "FOREX_MT5", "venue": "MT5", "environment": "LIVE_DATA", "product": "CFD", "instrument": "XAUUSD"}

    def test_config_strict(self):
        from masterquo.baskets import sfb as F
        self.assertEqual(F.validate_config({})["mode"], "OFF")
        for bad in ({"apply_to_execution": True}, {"mode": "LIVE"}, {"foo": 1}, {"allow_cross_profile_pooling": True}):
            with self.assertRaises(F.ConfigError):
                F.validate_config(bad)
        self.assertFalse(F.APPLY_TO_EXECUTION)

    def test_compatibility_gates(self):
        from masterquo.baskets import sfb as F
        self.assertEqual(F.compatibility(self.fx, self.scope)[0], "COMPATIBLE")
        self.assertEqual(F.compatibility(self.cp, self.scope), ("INCOMPATIBLE", ["PROFILE_MISMATCH"]))
        self.assertEqual(F.compatibility(self.fx, {**self.scope, "product": "PERPETUAL"})[1], ["PRODUCT_MISMATCH"])
        self.assertEqual(F.compatibility(self.fx, {**self.scope, "profile": "INDICES"})[1], ["UNSUPPORTED_PROFILE"])
        self.assertEqual(F.compatibility(self.C.HISTORICAL_STRATEGIES["OTC_SMC_01"], self.scope)[0], "RETIRED_SCOPE")
        self.assertEqual(F.compatibility(self.fx, {**self.scope, "capabilities": []})[0], "DATA_UNAVAILABLE")

    def test_evidence_gates_and_lineage(self):
        from masterquo.baskets import sfb as F
        cfg = F.validate_config({})
        now = 1_760_000_000 + 61 * 86400
        good = F.evidence(self.fx, outcomes(self.fx, mean=0.4), cfg, now)
        self.assertEqual(good["status"], "ELIGIBLE", good)
        self.assertEqual(F.evidence(self.fx, outcomes(self.fx, mean=0.4, src="SIGNAL_SIMULATION"), cfg, now)["status"], "COMPATIBLE_UNVALIDATED")
        wrong = [{**o, "config_hash": "other"} for o in outcomes(self.fx)]
        self.assertEqual(F.evidence(self.fx, wrong, cfg, now)["reason_codes"], ["NO_LINEAGE_EVIDENCE"])
        self.assertIn("NET_R_LCB_NOT_ABOVE_HURDLE", F.evidence(self.fx, outcomes(self.fx, mean=-0.2), cfg, now)["reason_codes"])
        self.assertIn("REGIMES 1<2", F.evidence(self.fx, outcomes(self.fx, mean=0.4, regimes=("TREND",)), cfg, now)["reason_codes"])
        self.assertTrue(any(r.startswith("COST_COVERAGE") for r in F.evidence(self.fx, outcomes(self.fx, mean=0.4, cost=False), cfg, now)["reason_codes"]))
        small = F.evidence(self.fx, outcomes(self.fx, n=20, mean=0.5), cfg, now)
        self.assertEqual(small["status"], "COMPATIBLE_UNVALIDATED")
        stale = F.evidence(self.fx, outcomes(self.fx, mean=0.4), cfg, now + 30 * 86400)
        self.assertEqual(stale["status"], "STALE_ARTIFACT")

    def test_off_parity_observe_and_assist(self):
        from masterquo.baskets import sfb as F
        strats = [s for s in self.C.CATALOG if s["profile_id"] == "FOREX_MT5"]
        off = F.StrategyFilterBucket({})
        kept, snap = off.filter(strats, self.scope)
        self.assertIs(kept, strats)
        self.assertIsNone(snap)
        obs = F.StrategyFilterBucket({"mode": "OBSERVE"})
        kept, snap = obs.filter(strats, self.scope)
        self.assertEqual(kept, strats)
        self.assertEqual(snap["would_keep"], [])
        now_out = outcomes(self.fx, mean=0.4)
        for o in now_out:
            o["closed_ts"] = __import__("time").time() - 86400 * 60 + (o["closed_ts"] - 1_760_000_000)
        asst = F.StrategyFilterBucket({"mode": "ASSIST"}, outcomes_fn=lambda scope: now_out)
        kept, snap = asst.filter(strats, self.scope)
        ids = [s["strategy_id"] for s in kept if s["kind"] != "HEDGING"]
        self.assertEqual(ids, ["FX_SMC_01"])
        self.assertEqual(snap["bucket_status"], "ACTIVE")
        none = F.StrategyFilterBucket({"mode": "ASSIST"})
        kept, snap = none.filter([s for s in strats if s["kind"] != "HEDGING"], self.scope)
        self.assertEqual((kept, snap["bucket_status"]), ([], "NO_TRADE_BUCKET"))
        self.assertFalse(snap["apply_to_execution"])

    def test_basket_service_default_off_and_config_persist(self):
        from masterquo.baskets import service as BS
        with tempfile.TemporaryDirectory() as d:
            svc = BS.BasketService(types.SimpleNamespace(demo=True, bridge=None, db=None, bus=None, quant=None, news=None), data_dir=Path(d))
            self.assertEqual(svc.sfb.status()["mode"], "OFF")
            svc.set_sfb({"mode": "SHADOW"})
            svc2 = BS.BasketService(types.SimpleNamespace(demo=True, bridge=None, db=None, bus=None, quant=None, news=None), data_dir=Path(d))
            self.assertEqual(svc2.sfb.status()["mode"], "SHADOW")
            from masterquo.baskets.sfb import ConfigError
            with self.assertRaises(ConfigError):
                svc2.set_sfb({"apply_to_execution": True})


if __name__ == "__main__":
    unittest.main()
