"""Daily volatility levels: HV estimators, Black-76 pricing, IV walls, no look-ahead, config migration."""
import json
import math
import tempfile
import unittest
from pathlib import Path

import _env  # noqa: F401

from masterquo.config import AppConfig, ConfigStore, VolatilityConfig
from masterquo.engine import volzones


def d1(n: int, start: float = 2000.0, step_pct: float = 0.01, forming: bool = True) -> list[dict]:
    """Alternating +/- step closes -> known close-to-close volatility."""
    bars, c = [], start
    for i in range(n):
        o = c
        c = o * math.exp(step_pct if i % 2 == 0 else -step_pct)
        bars.append({"open_utc": f"2026-01-{1 + i % 28:02d}T00:00:00Z", "o": o, "h": max(o, c) * 1.002, "l": min(o, c) * 0.998, "c": c, "closed": True})
    if forming:
        bars.append({"open_utc": "2026-02-01T00:00:00Z", "o": c, "h": c * 1.004, "l": c * 0.997, "c": c * 1.001, "closed": False})
    return bars


class TestVolZones(unittest.TestCase):
    def test_hv_close_to_close_known_value(self):
        closes = [100 * math.exp(0.01 * (1 if i % 2 else 0)) for i in range(21)]   # returns alternate +0.01 / -0.01
        s = volzones.hv_close_to_close(closes)
        rets = [0.01 if i % 2 == 0 else -0.01 for i in range(20)]
        mu = sum(rets) / 20
        self.assertAlmostEqual(s, math.sqrt(sum((r - mu) ** 2 for r in rets) / 19), places=12)

    def test_black76_parity_and_atm(self):
        f, k, sig, t = 2000.0, 2030.0, 0.18, 1 / 252
        o = volzones.black76(f, k, sig, t)
        self.assertAlmostEqual(o["call"] - o["put"], f - k, places=9)          # put-call parity (r=0)
        atm = volzones.black76(f, f, sig, t)
        v = sig * math.sqrt(t)
        self.assertAlmostEqual(atm["call"], f * (2 * volzones._ncdf(v / 2) - 1), places=9)
        self.assertAlmostEqual(atm["call"] + atm["put"], 0.7979 * f * v, delta=f * v * 0.002)   # straddle ~ 0.8 * F * sigma * sqrt(T)

    def test_levels_walls_and_lines(self):
        cfg = VolatilityConfig()
        v = volzones.compute(d1(60), cfg, digits=2)
        self.assertEqual(v["status"], "OK")
        a = v["day"]["open"]
        move = v["iv_annual_pct"] / 100 * math.sqrt(1 / 252)
        self.assertAlmostEqual(v["expected_high"], a * math.exp(move), delta=0.02)
        self.assertAlmostEqual(v["expected_low"], a * math.exp(-move), delta=0.02)
        self.assertEqual(v["iv_source"], "HV")
        self.assertEqual(v["iv_annual_pct"], v["hv_annual_pct"])
        self.assertEqual([(w["sigma"], w["side"]) for w in v["walls"]], [(1.0, "UP"), (1.0, "DOWN"), (2.0, "UP"), (2.0, "DOWN")])
        up1 = v["walls"][0]
        self.assertLess(up1["zone_low"], up1["level"])
        self.assertGreater(up1["zone_high"], up1["level"])
        self.assertAlmostEqual(up1["p_close_beyond"], 1 - volzones._ncdf(1 + move / 2), places=3)  # N(d2) at +1 sigma
        self.assertAlmostEqual(up1["delta"], 0.16, delta=0.02)
        c = v["contract"]
        self.assertLess(c["breakeven_up"], v["expected_high"])              # straddle (~0.8 sigma) inside the 1 sigma level
        self.assertGreater(c["breakeven_down"], v["expected_low"])
        kinds = {ln["kind"] for ln in v["lines"]}
        self.assertTrue({"DAILY_OPEN", "EXPECTED_HIGH", "EXPECTED_LOW", "PDH", "PDL", "DAY_HIGH", "DAY_LOW", "STRADDLE_BE"} <= kinds)
        self.assertEqual({z["from_utc"] for z in v["zones"]}, {"2026-02-01T00:00:00Z"})
        self.assertIsNotNone(v["day"]["range_used_pct"])

    def test_no_look_ahead_forming_day(self):
        cfg = VolatilityConfig()
        bars = d1(60)
        a = volzones.compute(bars, cfg)
        bars[-1] = {**bars[-1], "h": bars[-1]["h"] * 1.05, "l": bars[-1]["l"] * 0.95, "c": bars[-1]["c"] * 1.03}
        b = volzones.compute(bars, cfg)
        self.assertEqual(a["hv_annual_pct"], b["hv_annual_pct"])          # forming day never enters HV
        self.assertEqual(a["walls"][0]["level"], b["walls"][0]["level"])
        self.assertNotEqual(a["day"]["high"], b["day"]["high"])
        self.assertTrue(b["walls"][0]["reached"])

    def test_manual_iv_parkinson_and_closed_market(self):
        v = volzones.compute(d1(60), VolatilityConfig(iv_source="MANUAL", manual_iv_pct=25.0))
        self.assertEqual(v["iv_annual_pct"], 25.0)
        self.assertNotEqual(v["iv_annual_pct"], v["hv_annual_pct"])
        p = volzones.compute(d1(60), VolatilityConfig(estimator="parkinson"))
        self.assertEqual(p["status"], "OK")
        self.assertGreater(p["hv_annual_pct"], 0)
        closed = volzones.compute(d1(60, forming=False), VolatilityConfig())
        self.assertEqual(closed["day"]["state"], "NEXT_SESSION_PROJECTION")
        self.assertEqual({z["from_utc"] for z in closed["zones"]}, {None})
        self.assertNotIn("DAY_HIGH", {ln["kind"] for ln in closed["lines"]})

    def test_insufficient_and_disabled(self):
        self.assertEqual(volzones.compute(d1(10), VolatilityConfig())["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(volzones.compute(d1(60), VolatilityConfig(enabled=False))["status"], "DISABLED")
        self.assertEqual(volzones.compute([], VolatilityConfig())["status"], "INSUFFICIENT_HISTORY")

    def test_config_validation_and_v4_licensing_config_loads(self):
        with self.assertRaises(Exception):
            VolatilityConfig(walls_sigma=[])
        with self.assertRaises(Exception):
            VolatilityConfig(walls_sigma=[5.0])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            raw = AppConfig().model_dump(mode="json")
            raw.pop("volatility")
            raw.update({"config_version": 4, "central": {"url": "https://x"}, "connector": {"enabled": False}})
            p.write_text(json.dumps(raw), encoding="utf-8")
            c = ConfigStore(p).get()
            self.assertEqual(c.config_version, 5)
            self.assertEqual(c.volatility.walls_sigma, [1.0, 2.0])
            stored = json.loads(p.read_text(encoding="utf-8"))
            self.assertNotIn("central", stored)


if __name__ == "__main__":
    unittest.main()
