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
