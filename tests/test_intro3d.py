"""Intro 3D (pakiet update_intro3d): oś czasu / ruch deterministyczny, TL 13,8 s, bryła bajt w bajt (Node), w module brak Math.random / Date.now."""
from __future__ import annotations

import shutil
import subprocess
import unittest

import _env


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestIntro3DModule(unittest.TestCase):
    def test_timeline_and_motion(self):
        r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(_env.ROOT / "tests" / "js" / "intro3d.test.mjs")],
                           capture_output=True, text=True, timeout=120, cwd=str(_env.ROOT / "frontend"))
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIn("intro3d OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
