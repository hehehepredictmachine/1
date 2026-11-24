"""1.40.1: the engine never dies on start because of one part.
- a subsystem whose start() raises (here: Chronos-2/Granite TTM service, Memory Governor wiring) is logged and listed in
  /api/v1/health start_failures - the engine still answers and the rest runs;
- an error before the server exists (Runtime construction) ends with exit code 5, the traceback on stderr (the desktop launcher shows
  its last lines) and logs/engine_crash.txt;
- the Windows memory probe uses explicit ctypes prototypes (64-bit HANDLE) and returns (None, None) when unknown, never a guess."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path

import _env
from _env import TempData, wait_for

PORT = 8797


def health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/v1/health", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return None


class TestStartResilience(unittest.TestCase):
    def _run(self, code: str, td: TempData, wait_health: bool):
        with open(os.path.join(td.dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump({"server": {"port": PORT, "open_browser": False}, "news": {"enabled": False}, "clock": {"reference_url": None}}, f)
        env = dict(os.environ, MASTERQUO_DATA_DIR=td.dir, PYTHONPATH=str(_env.ROOT / "backend"))
        return subprocess.Popen([sys.executable, "-c", code], env=env, cwd=str(_env.ROOT / "backend"),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def test_failing_subsystem_does_not_stop_the_engine(self):
        self.assertIsNone(health(), f"port {PORT} busy")
        td = TempData()
        code = ("import sys\n"
                "import masterquo.tsfm.service as S\n"
                "def boom(self): raise RuntimeError('tsfm start boom')\n"
                "S.TsfmService.start = boom\n"
                "import masterquo.runtime as R\n"
                "def gov_boom(self): raise OSError('governor wiring boom')\n"
                "R.Runtime._wire_governor = gov_boom\n"
                "from masterquo.__main__ import main\n"
                "sys.exit(main(['serve', '--demo', '--no-browser']))\n")
        p = self._run(code, td, True)
        try:
            ok = wait_for(lambda: health() is not None, 90, 0.5)
            if not ok:
                p.kill()
                self.fail("engine did not answer: " + (p.stdout.read() if p.stdout else ""))
            h = health()
            self.assertTrue(h["ok"])
            self.assertEqual(h["start_failures"], ["tsfm"])
        finally:
            subprocess.run([sys.executable, "-m", "masterquo", "stop"], env=dict(os.environ, MASTERQUO_DATA_DIR=td.dir,
                           PYTHONPATH=str(_env.ROOT / "backend")), cwd=str(_env.ROOT / "backend"), timeout=60, capture_output=True)
            try:
                out, _ = p.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                p.kill()
                out, _ = p.communicate()
            td.close()
        self.assertIn("tsfm start boom", out)
        self.assertIn("governor wiring boom", out)

    def test_construction_error_exit_5_with_traceback(self):
        self.assertIsNone(health(), f"port {PORT} busy")
        td = TempData()
        code = ("import sys\n"
                "import masterquo.runtime as R\n"
                "def init_boom(self, **kw): raise ImportError('DLL load failed while importing _demo')\n"
                "R.Runtime.__init__ = init_boom\n"
                "from masterquo.__main__ import main\n"
                "sys.exit(main(['serve', '--demo', '--no-browser']))\n")
        p = self._run(code, td, False)
        try:
            out, _ = p.communicate(timeout=90)
            crash = Path(td.dir, "logs", "engine_crash.txt").read_text(encoding="utf-8")
        finally:
            td.close()
        self.assertEqual(p.returncode, 5, out)
        self.assertIn("BŁĄD STARTU SILNIKA", out)
        self.assertIn("ImportError: DLL load failed", out)
        self.assertIn("ImportError: DLL load failed", crash)

    def test_proc_mem_never_guesses(self):
        from masterquo.resources import governor as G
        rss, peak = G._proc_mem(os.getpid())
        if sys.platform.startswith("linux"):
            self.assertGreater(rss, 1.0)
            self.assertGreaterEqual(peak, rss)
        self.assertEqual(G._proc_mem(2**31 - 7), (None, None))      # no such process
        src = Path(G.__file__).read_text(encoding="utf-8")
        for proto in ("OpenProcess.restype = W.HANDLE", "OpenProcess.argtypes", "GetProcessMemoryInfo.argtypes", "CloseHandle.argtypes"):
            self.assertIn(proto, src)
        self.assertNotIn("ctypes.windll.kernel32.OpenProcess", src)
        self.assertNotIn("k32 = ctypes.windll", src)


if __name__ == "__main__":
    unittest.main()
