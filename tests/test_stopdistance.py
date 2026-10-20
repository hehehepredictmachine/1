"""PMW-UPD-11 FF05 StopDistance (T39-T46)."""
import unittest

import _env  # noqa: F401

from _bars import bar
from masterquo.lab.flow_context import stop_distance as SD


class StopDistanceTests(unittest.TestCase):
    def test_t39_t40_points_and_gap(self):
        sd = SD.StopDistance({"period": 1}, point=0.1)
        sd.update(bar(0, 100.5, 99.5, 100))
        r = sd.update(bar(1, 112, 110, 111))
        self.assertAlmostEqual(r["range_points"], 20)                      # not the 120-point true range across the gap
        for bad in (0, None, float("nan")):
            with self.assertRaises(ValueError):
                SD.StopDistance(None, bad)
        with self.assertRaises(ValueError):
            sd.update(bar(2, 1, 2))

    def test_t41_seed_and_methods(self):
        bs = [bar(i, 100 + (i % 5), 100) for i in range(40)]
        rows = SD.series(bs, {"period": 20, "method": "SMA"}, point=1.0)
        self.assertIsNone(rows[18]["average_points"])
        self.assertEqual(rows[18]["status"], "WARMUP")
        self.assertAlmostEqual(rows[19]["average_points"], sum(i % 5 for i in range(20)) / 20)
        e = SD.series(bs, {"period": 20, "method": "EMA"}, point=1.0)
        self.assertAlmostEqual(e[19]["average_points"], rows[19]["average_points"])     # EMA seed = SMA
        a = 2 / 21
        self.assertAlmostEqual(e[20]["average_points"], e[19]["average_points"] + a * (20 % 5 - e[19]["average_points"]))
        self.assertTrue(all(r["range_points"] is not None for r in rows))

    def test_t42_factor_and_flat(self):
        with self.assertRaises(ValueError):
            SD.StopDistance({"factor": 0}, 0.01)
        rows = SD.series([bar(i, 100, 100) for i in range(25)], None, 0.01)
        self.assertEqual(rows[-1]["status"], "FLAT_WINDOW")
        self.assertEqual(rows[-1]["suggested_points"], 0.0)

    def test_t43_preview(self):
        sd = SD.StopDistance({"period": 3}, 1.0)
        for i in range(3):
            sd.update(bar(i, 102, 100))
        p1 = sd.preview(bar(3, 110, 100))
        p2 = sd.preview(bar(3, 110, 100))
        self.assertEqual(p1["average_points"], p2["average_points"])
        self.assertEqual(sd.update(bar(3, 110, 100))["average_points"], p1["average_points"])
        self.assertIsNone(sd.update(bar(3, 110, 100)))

    def test_t44_sl_price_outward(self):
        self.assertAlmostEqual(SD.sl_price(2000.0, "BUY", 1.234, 0.01), 1998.76)
        self.assertAlmostEqual(SD.sl_price(2000.0, "SELL", 1.234, 0.01), 2001.24)
        self.assertAlmostEqual(SD.sl_price(2000.0, "BUY", 1.0, 0.05), 1999.0)
        self.assertAlmostEqual(SD.sl_price(2000.0, "BUY", 1.01, 0.05), 1998.95)          # point != tick: rounded outward to tick grid

    def test_t45_advisory(self):
        row = {"average_points": 100.0, "suggested_points": 150.0}
        d = SD.risk_diagnostics(row, 80.0, 120.0)
        self.assertTrue(d["advisory"])
        self.assertEqual(set(d["flags"]), {"BELOW_AVERAGE_RANGE", "BELOW_SUGGESTED", "BELOW_BROKER_STOPS_LEVEL"})

    def test_t46_calibration(self):
        import numpy as np
        r = np.random.default_rng(0)
        bs = [bar(i, 100 + abs(r.normal(0, 1)), 100) for i in range(600)]
        c = SD.calibrate_factor(bs[:500], 0.01)
        self.assertEqual(c["status"], "OK")
        self.assertGreater(c["factor"], 0)
        self.assertEqual(SD.calibrate_factor(bs[:50], 0.01)["status"], "INSUFFICIENT_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
