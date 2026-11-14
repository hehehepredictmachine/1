"""1.40.1: model installers (Kronos, Chronos-2 / Granite TTM, deep) started from the desktop app inherit the bot's PYTHONPATH (backend + the
bot's own site-packages). pip inside .venv_* then treated the bot's packages as "already satisfied" and skipped them -> incomplete model
environment, failed check. Children now get a clean environment: no foreign PYTHONPATH / PYTHONHOME / PIP_* overrides, user site off; an
explicit PYTHONPATH (the program's backend folder for the model's own code) is kept; proxy and PATH stay."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import _env

sys.path.insert(0, str(_env.ROOT / "tools"))

PROBE = "import json,os;print(json.dumps({k: os.environ.get(k) for k in ('PYTHONPATH','PYTHONHOME','PIP_TARGET','PYTHONNOUSERSITE','HTTPS_PROXY')}))"


class TestInstallerEnv(unittest.TestCase):
    def test_child_env_drops_the_bot_environment(self):
        import kronos_setup as KS
        polluted = {"PYTHONPATH": "C:\\app\\backend;C:\\Users\\u\\PepeMarketWizard\\pyenv\\cp313-x\\site-packages", "PYTHONHOME": "C:\\py",
                    "PIP_TARGET": "C:\\t", "HTTPS_PROXY": "http://proxy:8080", "PATH": os.environ.get("PATH", "")}
        with mock.patch.dict(os.environ, polluted):
            e = KS.child_env()
            self.assertNotIn("PYTHONPATH", e)
            self.assertNotIn("PYTHONHOME", e)
            self.assertNotIn("PIP_TARGET", e)
            self.assertEqual(e["PYTHONNOUSERSITE"], "1")
            self.assertEqual(e["HTTPS_PROXY"], "http://proxy:8080")       # network settings of the user stay
            explicit = KS.child_env(dict(os.environ, PYTHONPATH="C:\\app\\backend"))
            self.assertEqual(explicit["PYTHONPATH"], "C:\\app\\backend")  # the model's own code path is kept, nothing else
            self.assertNotIn("PYTHONHOME", explicit)

    def test_run_gives_children_the_clean_environment(self):
        import kronos_setup as KS
        lines = []
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/bot/site-packages", "PIP_TARGET": "/t"}), mock.patch.object(KS, "emit", lines.append):
            rc, last = KS.run([sys.executable, "-c", PROBE], KS.Out(None), 1)
        self.assertEqual(rc, 0)
        seen = json.loads(last)
        self.assertIsNone(seen["PYTHONPATH"])
        self.assertIsNone(seen["PIP_TARGET"])
        self.assertEqual(seen["PYTHONNOUSERSITE"], "1")

    def test_app_control_block_is_explained(self):
        import kronos_setup as KS
        KS.CHILD["result"] = {"code": "MISSING_DEPENDENCY", "error": 'OSError: [WinError 4551] Zasady kontroli aplikacji zablokowały ten plik. '
                              'Error loading "C:\\x\\.venv_granite\\Lib\\site-packages\\torch\\lib\\shm.dll"'}
        code, msg = KS.child_error("")
        self.assertEqual(code, "APP_CONTROL_BLOCKED")
        import tsfm_setup as TS                                   # the Chronos-2 / Granite installer uses its own wrapper
        self.assertEqual(TS.child_error("")[0], "APP_CONTROL_BLOCKED")
        self.assertIn("Smart App Control", msg)
        self.assertNotIn("powtórz instalację", msg)
        KS.CHILD["result"] = None

    def test_granite_uses_the_same_torch_as_the_other_models(self):
        req = (_env.ROOT / "requirements")
        pins = {f: next(l.split(" ")[0] for l in (req / f).read_text(encoding="utf-8").splitlines() if l.startswith("torch=="))
                for f in ("requirements-granite-win.txt", "requirements-chronos2-win.txt", "requirements-kronos-win.txt")}
        self.assertEqual(len(set(pins.values())), 1, pins)       # torch 2.11.0 was blocked by Smart App Control (WinError 4551)
        t = (_env.ROOT / "tools" / "tsfm_setup.py").read_text(encoding="utf-8")
        self.assertIn('"granite_ttm": "torch==2.14.1"', t)
        self.assertIn('pip.append("--no-deps")', t)

    def test_every_installer_uses_it(self):
        tools = _env.ROOT / "tools"
        k = (tools / "kronos_setup.py").read_text(encoding="utf-8")
        self.assertIn("env=child_env(env)", k)
        t = (tools / "tsfm_setup.py").read_text(encoding="utf-8")
        self.assertIn("KS.run(", t)
        self.assertNotIn("capture_output=True).returncode", t)           # the pip probe too
        d = (tools / "deep_setup.py").read_text(encoding="utf-8")
        self.assertIn("env=KS.child_env(env)", d)


if __name__ == "__main__":
    unittest.main()
