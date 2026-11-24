"""CHARTS 1:1 (pakiet update_charts, K5): port Session Volume Profile używany przez ekran CHARTS (frontend .../charts/svpPort.js) daje
te same profile co silnik bota (svp/engine.py): update_charts/narzedzia/svp_zgodnosc – make_fixture.py + test_svp_port.mjs, 27/27."""
from __future__ import annotations

import shutil
import subprocess
import sys
import unittest

import _env

TOOL = _env.ROOT / "update_charts" / "narzedzia" / "svp_zgodnosc"
PORT = _env.ROOT / "frontend" / "src" / "features" / "forex" / "screens" / "charts" / "svpPort.js"


@unittest.skipUnless(shutil.which("node"), "node not installed")
@unittest.skipUnless(TOOL.exists(), "pakiet update_charts nie jest częścią paczki wydania")
class TestChartsSvpPort(unittest.TestCase):
    def test_port_matches_engine(self):
        r = subprocess.run([sys.executable, str(TOOL / "make_fixture.py")], cwd=str(_env.ROOT), capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        r = subprocess.run(["node", str(TOOL / "test_svp_port.mjs"), str(PORT)], cwd=str(_env.ROOT), capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertIn("różne: 0", r.stdout)
        self.assertRegex(r.stdout, r"zgodne: (2[7-9]|[3-9]\d|\d{3,})")


if __name__ == "__main__":
    unittest.main()
