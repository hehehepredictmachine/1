"""PMW-UPD-09 R22 MQ_REGIME_MULTI_V2 (T123-T128)."""
import math
import unittest

import numpy as np

import _env  # noqa: F401

from _bars import from_closes, zigzag
from masterquo.lab import market as M1
from masterquo.lab import market_v2 as V


class RegimeTests(unittest.TestCase):
    def test_t123_er_and_scale(self):
        self.assertEqual(V._er(np.arange(30.0), 20), 1.0)
        self.assertAlmostEqual(V._er(np.array([0, 1] * 15, float), 20), 0.0)
        self.assertEqual(V._er(np.ones(30), 20), 0.0)
        self.assertIsNone(V._er(np.ones(10), 20))
        rm = V.RegimeMachine()
        c = 100 + np.cumsum(np.random.default_rng(0).normal(0.1, 1, 80))
        a = rm.components(c, 1.3, "UP")
        b = rm.components(c * 7, 1.3 * 7, "UP")
        np.testing.assert_allclose(a["d_n"], b["d_n"], atol=1e-3)
        self.assertEqual(rm.components(c, 0.0, "UP")["status"], "ATR_BELOW_FLOOR")

    def test_t124_flat_vs_missing_and_strength(self):
        rm = V.RegimeMachine()
        self.assertEqual(rm.components(np.ones(10), 1.0, "UNKNOWN")["status"], "WARMING_UP")
        flat = rm.components(np.ones(60), 1.0, "UNKNOWN")
        self.assertEqual(rm.candidate(flat), ("RANGE", ["FLAT"]))
        c = 100 + np.arange(60) * 0.5
        comp = rm.components(c, 1.0, "UNKNOWN")
        cand, why = rm.candidate(comp)
        self.assertEqual(cand, "TRANSITION")
        self.assertIn("STRUCTURE_NOT_CONFIRMED", why)
        self.assertIsNone(rm.strength("TRANSITION", comp))
        s = rm.strength("TREND_UP", comp)
        self.assertTrue(0 <= s <= 100)
        self.assertFalse(rm.view(comp)["strength_is_probability"])

    def test_t125_hysteresis(self):
        rm = V.RegimeMachine()
        c = 100 + np.arange(80) * 0.5
        st = [rm.step(f"b{i}", c[:i + 1], 1.0, "UP")["state"] for i in range(51, 55)]
        self.assertEqual(st[0], "TRANSITION")
        self.assertEqual(st[1], "TREND_UP")                                    # two consecutive candidates
        before = dict(rm.st)
        rm.step("b54", c[:55], 1.0, "UP")                                      # repeated poll: no recount
        self.assertEqual(rm.st["count_fail"], before["count_fail"])
        v = rm.step("b55", c[:56], 1.0, "DOWN", opposite_break=True)
        self.assertEqual(v["state"], "TRANSITION")                             # immediate on opposite break, never UP->DOWN directly
        d = 100 - np.arange(80) * 0.5
        rm.step("b56", d[:57], 1.0, "DOWN")
        self.assertIn(rm.step("b57", d[:58], 1.0, "DOWN")["state"], ("TREND_DOWN", "TRANSITION"))
        self.assertTrue(all(not (h["from"] == "TREND_UP" and h["to"] == "TREND_DOWN") for h in rm.st["history"]))

    def test_t126_restart_and_prefix(self):
        bars = zigzag([100, 110, 104, 116, 108, 122, 115, 125, 118], 12)
        full = V.regime_series(bars, "M1", 0.01, keep=len(bars))
        part = V.regime_series(bars[:70], "M1", 0.01, keep=70)
        self.assertEqual([x["state"] for x in full["series"][:70]], [x["state"] for x in part["series"]])
        rm = V.RegimeMachine()
        rm.restore(part["checkpoint"])
        with self.assertRaises(ValueError):
            V.RegimeMachine({"confirm": 3}).restore(part["checkpoint"])

    def test_t127_vol_axis_shared(self):
        rel = np.concatenate([np.full(150, 0.001), [0.002]])
        v = V.vol_axis(rel, 150)
        self.assertEqual(v["state"], "HIGH")
        self.assertEqual(V.vol_axis(rel, 50)["state"], "WARMING_UP")
        self.assertEqual(V.vol_axis(np.full(151, 0.001), 150)["percentile"], 0.5)     # ties count half
        from datetime import datetime, timezone
        bars = [dict(b, open_utc=datetime.fromtimestamp(b["open_utc"], timezone.utc).isoformat().replace("+00:00", "Z"))
                for b in from_closes(list(2000 + np.cumsum(np.random.default_rng(3).normal(0, 1, 400))))]
        m11 = M1.vol_regime(bars)
        self.assertEqual(m11["axis_v2"], V.regime_series(bars, "M1", 0.01)["current"]["volatility"])


if __name__ == "__main__":
    unittest.main()
