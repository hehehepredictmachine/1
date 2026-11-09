"""1.39 WTC PEPE 2.1 Chart Lab: the pure calculations (Heikin Ashi, EMA, RSI, ATR, BB, MACD, daily VWAP, sessions, Session Volume Profile
with POC / Value Area, biggest impulse 3/5/8/12, SMC BOS/CHoCH) checked in Node on deterministic bars (tests/js/chartlab_calc.test.mjs):
causality (a prefix gives the same values), volume conservation of the profile, VA >= 70 %, impulse found where it was put."""
from __future__ import annotations

import shutil
import subprocess
import unittest

import _env


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestChartLabCalc(unittest.TestCase):
    def test_calc(self):
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_env.ROOT / "tests" / "js" / "chartlab_calc.test.mjs")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIn("chartlab calc OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
