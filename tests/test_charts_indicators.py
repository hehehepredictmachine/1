"""CHARTS 1:1 (pakiet update_charts, K2 §3): wskaźniki rysowane na ekranie CHARTS (kod wzorca) są zgodne z silnikiem bota
(engine.chartdata.indicator_series z profilem M02I dla M5 / M15 / H1: okresy EMA, RSI, MACD z sygnałem SMA(9), ATR14). Node."""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import _env  # noqa: F401  (sys.path → backend)
from masterquo.engine import chartdata
from masterquo.engine.legacy import Profiles


def bars(step_min: int, n: int = 600, seed: int = 7) -> list[dict]:
    rnd, px, t0, out = random.Random(seed), 3400.0, datetime(2026, 11, 2, tzinfo=timezone.utc), []
    for i in range(n):
        o = px
        c = o + rnd.gauss(0, 1.2)
        h, l = max(o, c) + abs(rnd.gauss(0, .5)), min(o, c) - abs(rnd.gauss(0, .5))
        out.append({"open_utc": (t0 + timedelta(minutes=step_min * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": h, "l": l, "c": c,
                    "tv": 100, "closed": True})
        px = c
    return out


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestChartsIndicators(unittest.TestCase):
    def test_pattern_formulas_equal_engine(self):
        tp = Profiles().m02i.get("timeframe_profiles", {})
        data = {}
        for tf, step in (("M5", 5), ("M15", 15), ("H1", 60)):
            b = bars(step, seed=step)
            data[tf] = {"bars": b, "indicators": chartdata.indicator_series(tf, b, tp.get(tf))}
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_env.ROOT / "tests" / "js" / "charts_indicators.test.mjs"), path],
                               capture_output=True, text=True, timeout=120)
        finally:
            os.unlink(path)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:] + r.stdout[-2000:])
        self.assertIn("charts indicators OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
