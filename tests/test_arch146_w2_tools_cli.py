"""Fala 2 / grupa tools_cli (Apollo23 1.46): narzędzia i CLI bez wpływu na decyzje handlowe.

I0480 (build terminala w statusie natywnym MiniRocket v2). Każdy test nie przechodzi na kodzie sprzed poprawki.
Bez serwera HTTP, bez MT5, bez zleceń.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import _env

ROOT = _env.ROOT
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


# ============================================================================================== I0480 mr2_native_status: build
class TestNativeStatusBuild(unittest.TestCase):
    """I0480: native_status.json had no terminal_build, so MR.native_status(...)['build'] was always None although the self-test line
    carries `build=N` (PMW_MR2_SelfTest.mq5:82)."""

    def setUp(self):
        import mr2_native_status as ns
        self.ns = ns
        self.tmp = Path(tempfile.mkdtemp(prefix="mq_t_w2tc_native_"))
        self.mql = self.tmp / "MQL5"
        for d in ("Scripts/PMW", "Indicators/PMW", "Include/PMW", "Files/PMW"):
            (self.mql / d).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, text: str, selftest_age: float) -> dict:
        ex5 = self.mql / "Scripts" / "PMW" / "PMW_MR2_SelfTest.ex5"
        ex5.write_bytes(b"ex5")
        (self.mql / "Scripts" / "PMW" / "PMW_MR2_SelfTest.mq5").write_text("src", encoding="utf-8")
        st = self.mql / "Files" / "PMW" / "mr2_selftest.txt"
        st.write_text(text, encoding="utf-8")
        now = time.time()
        os.utime(ex5, (now, now))
        os.utime(st, (now + selftest_age, now + selftest_age))
        with redirect_stdout(io.StringIO()):
            self.ns.main(str(self.tmp), "0", "log")
        return json.loads((self.mql / "Files" / "PMW" / "native_status.json").read_text(encoding="utf-8"))

    def test_fresh_selftest_build_is_written_and_reported(self):
        from masterquo.lab import minirocket_v2 as MR
        out = self._run("2026.11.24 PMW_MR2_SELFTEST RESULT=PASS failures=0 build=4620\n", +60)
        self.assertEqual(out["terminal_build"], 4620)
        ns = MR.native_status(self.mql / "Files" / "PMW" / "native_status.json")
        self.assertEqual(ns["build"], 4620)
        self.assertEqual(ns["NATIVE_EXECUTED"], "PASS")

    def test_stale_selftest_build_is_not_evidence(self):
        out = self._run("PMW_MR2_SELFTEST RESULT=PASS failures=0 build=4620\n", -3600)
        self.assertIsNone(out["terminal_build"])
        self.assertEqual(out["selftest_result"], "NATIVE_NOT_EXECUTED")

    def test_selftest_without_build_gives_none(self):
        out = self._run("RESULT=PASS\n", +60)
        self.assertIsNone(out["terminal_build"])
        self.assertEqual(out["selftest_result"], "PASS")


if __name__ == "__main__":
    unittest.main()
