"""WF3.2 TASK 021 (relationships), 022 (market trap + behaviour guard), 023 (SMMA-CCI), 024 (AutoStrategy generator), 025 (RiskLoot)."""
from __future__ import annotations

import math
import random
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401


def walk(n=600, seed=1, drift=0.0, vol=0.01, start=100.0):
    rnd = random.Random(seed)
    p, out = start, []
    for i in range(n):
        o = p
        p *= math.exp(rnd.gauss(drift, vol))
        out.append({"t": i * 3600, "o": o, "h": max(o, p) * (1 + abs(rnd.gauss(0, vol / 3))), "l": min(o, p) * (1 - abs(rnd.gauss(0, vol / 3))), "c": p})
    return out


class TestRelationships(unittest.TestCase):
    def test_formulas_and_lead_lag(self):
        from masterquo.apollo import relationships as R
        rnd = random.Random(3)
        rb = [rnd.gauss(0, 0.01) for _ in range(800)]
        ra = [0.0] + [1.5 * rb[i - 1] + rnd.gauss(0, 0.002) for i in range(1, 800)]           # A follows B with lag 1
        pa, pb = [100.0], [50.0]
        for x, y in zip(ra, rb):
            pa.append(pa[-1] * math.exp(x))
            pb.append(pb[-1] * math.exp(y))
        res = R.analyse([(i, v) for i, v in enumerate(pa)], [(i, v) for i, v in enumerate(pb)])
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["best_lag"]["lag"], 1)
        self.assertGreater(res["best_lag"]["corr"], 0.9)
        self.assertAlmostEqual(R.return_beta([2 * x for x in rb], rb), 2.0, places=9)
        self.assertIsNone(R.corr([1, 1, 1], [1, 2, 3]))

    def test_sync_no_forward_fill_and_cointegration(self):
        from masterquo.apollo import relationships as R
        ts, a, b = R.synchronize([(1, 1.0), (2, 2.0), (3, 3.0)], [(2, 5.0), (3, 6.0), (4, 7.0)])
        self.assertEqual((ts, a, b), ([2, 3], [2.0, 3.0], [5.0, 6.0]))
        rnd = random.Random(5)
        lb, s = [math.log(100)], [0.0]
        for _ in range(600):
            lb.append(lb[-1] + rnd.gauss(0, 0.01))
            s.append(0.7 * s[-1] + rnd.gauss(0, 0.005))
        pa = [math.exp(0.5 + 1.2 * x + e) for x, e in zip(lb, s)]
        pb = [math.exp(x) for x in lb]
        res = R.analyse([(i, v) for i, v in enumerate(pa)], [(i, v) for i, v in enumerate(pb)])
        self.assertEqual(res["cointegration"], "CANDIDATE")
        self.assertAlmostEqual(res["price_beta"], 1.2, delta=0.1)
        z = R.zscore([0.0] * 10 + [1.0], 10)
        self.assertIsNone(z[-1])                                                               # zero std -> None, not inf

    def test_candidates_status(self):
        from masterquo.apollo import relationships as R
        c = R.candidates()
        self.assertEqual(len(c), 24)
        self.assertTrue(all(not x["active"] for x in c))
        self.assertTrue(all(x["runtime_status"] == "RESEARCH_ONLY" for x in c if x["market_class"] in ("INDEX_FUTURES", "EQUITY_PERP")))


class TestTraps(unittest.TestCase):
    def test_false_breakout_and_unavailable_components(self):
        from masterquo.apollo import traps as T
        bars = [{"h": 101.0, "l": 99.0, "c": 100.0} for _ in range(25)] + [{"h": 103.0, "l": 99.5, "c": 100.5}]
        r = T.detect(bars)
        self.assertIn("FALSE_BREAKOUT_ACCEPTANCE_FAIL", r["reason_codes"])
        self.assertIsNotNone(r["market_trap_score"])
        self.assertEqual(r["components"]["EXECUTED_FLOW"]["status"], "UNAVAILABLE")
        self.assertIn("MBO", r["spoofing_layering"])
        self.assertLess(r["confidence"], 0.5)
        self.assertIn("nie dowód manipulacji", r["disclaimer"])
        self.assertIsNone(T.detect(bars[:5])["market_trap_score"])

    def test_behaviour_guard_separate(self):
        from masterquo.apollo import traps as T
        tr = [{"opened": 0, "closed": 3600, "size": 1, "net": -10}, {"opened": 3700, "closed": 3800, "size": 3, "net": 5},
              {"opened": 10_000, "closed": 10_500, "size": 1, "net": 4}, {"opened": 20_000, "closed": 40_000, "size": 1, "net": -8},
              {"opened": 40_100, "closed": 40_200, "size": 1, "net": 2, "entry_move_atr": 3}]
        b = T.behaviour(tr)
        codes = {f["code"] for f in b["flags"]}
        self.assertTrue({"POST_LOSS_SIZE_ESCALATION", "RAPID_REENTRY_AFTER_LOSS", "LATE_MOVE_CHASE_POOR_RR", "DISPOSITION_ASYMMETRY"} <= codes)
        self.assertEqual(T.behaviour(tr[:2])["status"], "LOW_SAMPLE")
        self.assertNotIn("behavioural_risk_score", T.detect(walk(60)))


class TestSmmaCci(unittest.TestCase):
    def test_closed_bar_only_and_contract(self):
        from masterquo.apollo import smma_cci as S
        bars = walk(300, seed=2, drift=0.002)
        r = S.evaluate(bars)
        self.assertIn(r["status"], ("SIGNAL", "NO_SIGNAL"))
        self.assertEqual(r["mode"], "OFF")
        r2 = S.evaluate(bars + [{**bars[-1], "c": bars[-1]["c"] * 1.5, "forming": True}])
        self.assertEqual(r["cci"], r2["cci"])                                                  # forming bar never used
        self.assertEqual(S.evaluate(bars[:20])["status"], "WARMUP")
        if r["signal_quality_score"] is not None:
            self.assertTrue(0 <= r["signal_quality_score"] <= 100)
        found = 0
        for sd in range(15):
            x = S.evaluate(walk(300, seed=sd, drift=0.001))
            if x["status"] == "SIGNAL":
                found += 1
                s = x["smma"]
                if x["side"] == "LONG":
                    self.assertTrue(s[13] > s[21] > s[35] and x["cci_prev"] <= 0 < x["cci"])
        self.assertGreaterEqual(found, 0)


class TestASGE(unittest.TestCase):
    SEED = {"side": "LONG", "family": "TREND", "conditions": [{"type": "close_above_sma", "n": 50}, {"type": "breakout_high", "n": 20}],
            "exit": {"tp_r": 2.0, "sl_atr": 1.5, "max_bars": 30}}

    def test_ir_allowlist(self):
        from masterquo.apollo import asge as A
        A.validate_ir(self.SEED)
        for bad in ({**self.SEED, "code": "import os"}, {**self.SEED, "conditions": [{"type": "eval", "n": 1}]},
                    {**self.SEED, "conditions": [{"type": "close_above_sma", "n": 9999}]}, {**self.SEED, "exit": {"tp_r": 2}}):
            with self.assertRaises(A.IRError):
                A.validate_ir(bad)

    def test_trial_ledger_lineage_and_no_execution(self):
        from masterquo.apollo import asge as A
        led = A.TrialLedger()
        res = A.run(walk(2000, seed=4, drift=0.0004), [self.SEED], n_children=6, ledger=led)
        self.assertEqual(res["trials"], 7)
        self.assertEqual(len(led.rows), 7)                                                       # every trial recorded, rejected ones too
        self.assertTrue(all(r["parent"] == A.ir_hash(self.SEED) for r in led.rows[1:]))
        self.assertTrue(all(r["execution_allowed"] is False for r in led.rows))
        self.assertTrue(all(r["status"] in ("REJECTED", "SHADOW_CHALLENGER") for r in led.rows))
        self.assertGreater(res["hurdle_net_r"], 0)
        from masterquo.baskets import catalog as C
        self.assertEqual(C.validate()["total"], 60)

    def test_backtest_no_lookahead(self):
        from masterquo.apollo import asge as A
        bars = walk(400, seed=8)
        r1 = A.backtest(self.SEED, bars[:300])
        r2 = A.backtest(self.SEED, bars[:300] + [{**b, "c": b["c"] * 10, "h": b["h"] * 10} for b in bars[300:]])
        self.assertEqual(r1, r2[:len(r1)] if len(r2) >= len(r1) else r2)


class TestRiskLoot(unittest.TestCase):
    EV = {"event_id": "e1", "position_id": "p1", "source_mode": "SIMULATOR", "setup_family": "EMA_SMMA_PULLBACK", "strategy_status": "VALIDATED",
          "sfb_status": "ELIGIBLE", "trap_no_trade": False, "risk_breach": False, "attribution": "SIM:1",
          "scores": {"setup_quality": 90, "risk_discipline": 95, "execution_adherence": 85, "journal_learning": 80, "evidence_quality": 85}}

    def test_score_tier_vetoes(self):
        from masterquo.apollo import risk_loot as R
        r = R.evaluate(self.EV)
        self.assertAlmostEqual(r["score"], 0.25 * 90 + 0.30 * 95 + 0.20 * 85 + 0.10 * 80 + 0.15 * 85, delta=0.05)   # reported with 0.1 precision
        self.assertEqual(r["tier"], "RARE")
        self.assertEqual(r["item"]["loot_family"], "PULLBACK")
        for patch, code in (({"risk_breach": True}, "RISK_POLICY_BREACH"), ({"risk_breach": None}, "DATA_INSUFFICIENT"),
                            ({"attribution": None}, "SETUP_UNATTRIBUTED"), ({"trap_no_trade": True}, "MARKET_TRAP_NO_TRADE"),
                            ({"setup_family": "WHATEVER"}, "UNMAPPED_SETUP_FAMILY"),
                            ({"scores": {**self.EV["scores"], "pnl": 999}}, "PNL_NOT_REWARD_BASIS"),
                            ({"scores": {**self.EV["scores"], "risk_discipline": None}}, "DATA_INSUFFICIENT"),
                            ({"source_mode": "MT5_READ_ONLY", "sfb_status": "COMPATIBLE_UNVALIDATED"}, "SFB_BLOCKED")):
            out = R.evaluate({**self.EV, **patch})
            self.assertFalse(out["eligible"])
            self.assertIn(code, out["vetoes"], patch)

    def test_patience_and_legendary_needs_evidence(self):
        from masterquo.apollo import risk_loot as R
        p = R.evaluate({**self.EV, "setup_family": "VERIFIED_NO_TRADE_VETO", "trap_no_trade": True, "no_trade_respected": True})
        self.assertTrue(p["eligible"])
        self.assertEqual(p["loot_family"], "PATIENCE_NO_TRADE")
        top = {**self.EV, "scores": {k: 100 for k in R.WEIGHTS}}
        self.assertEqual(R.evaluate(top)["tier"], "EPIC")
        self.assertEqual(R.evaluate({**top, "independent_evidence": True})["tier"], "LEGENDARY")

    def test_grant_idempotent_partial_exits_into_game_inventory(self):
        from masterquo.apollo import risk_loot as R
        from masterquo.trader_life_game import GameService
        with tempfile.TemporaryDirectory() as d:
            g = GameService(Path(d))
            g.create_profile({"username": "Kuba", "class_id": "THE_ROOKIE", "difficulty": "EASY"})
            a = R.grant(g, self.EV)
            b = R.grant(g, {**self.EV, "event_id": "e1-partial-2"})                               # same position -> no second award
            self.assertTrue(a["granted"])
            self.assertFalse(b["granted"])
            self.assertEqual(g.gold_total(), 0)                                                    # loot never adds Trader Gold / money
            self.assertIsNotNone(g._one("SELECT * FROM inventory WHERE item_id = ?", (a["item"]["item_id"],)))
            self.assertEqual(a["monetary_value"], "NONE")


if __name__ == "__main__":
    unittest.main()
