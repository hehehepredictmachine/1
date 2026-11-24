"""CHARTS 1:1 (pakiet update_charts, K1): adaptery API → model widoku (D1 §3) – stany puste, brak zgadywania, % tylko skalibrowane. Node."""
from __future__ import annotations

import shutil
import subprocess
import unittest

import _env


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestChartsAdapters(unittest.TestCase):
    def test_adapters(self):
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_env.ROOT / "tests" / "js" / "charts_adapters.test.mjs")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIn("charts adapters OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
