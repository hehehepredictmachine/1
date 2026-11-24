"""1.42 E8 §5(h): pure FOREX screen helpers (empty / partial API answers -> empty states; % only from a calibrated probability), in Node."""
from __future__ import annotations

import shutil
import subprocess
import unittest

import _env


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestForexFormat(unittest.TestCase):
    def test_format(self):
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_env.ROOT / "tests" / "js" / "forex_format.test.mjs")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIn("forex format OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
