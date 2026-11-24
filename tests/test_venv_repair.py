"""1.42.2: model environments (.venv_*) after the program folder was moved to another place / user - pyvenv.cfg points to a base
Python that no longer exists ("did not find executable at ..."). Same Python version -> re-pointed (packages kept); otherwise set aside
(renamed, never deleted) for a fresh venv; the running bot only re-points."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _env

sys.path.insert(0, str(_env.ROOT / "backend"))
import mq_venv  # noqa: E402

BASE = getattr(sys, "_base_executable", None) or sys.executable


def make(d: Path) -> Path:
    v = d / ".venv_granite"
    subprocess.run([BASE, "-m", "venv", "--without-pip", str(v)], check=True)
    return v


def move(v: Path, version: str | None = None) -> None:
    p = v / "pyvenv.cfg"
    lines = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.startswith("home"):
            ln = "home = " + str(Path("/nonexistent/Users/kubal/Desktop/Pepe/runtime/python"))
        if version and ln.startswith("version"):
            ln = "version = " + version
        lines.append(ln)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestVenvRepair(unittest.TestCase):
    def test_ok_moved_mismatch_and_runtime_mode(self):
        with tempfile.TemporaryDirectory() as d:
            v = make(Path(d))
            self.assertEqual(mq_venv.repair(v, BASE)["state"], "OK")
            move(v)
            self.assertEqual(mq_venv.check(v)[0], "MOVED")
            r = mq_venv.repair(v, BASE)
            self.assertEqual(r["state"], "REPAIRED", r)
            self.assertTrue(mq_venv.runs(v))
            self.assertTrue((v / "pyvenv.cfg.moved_bak").is_file())                     # the original is kept
            move(v, version="3.9.1")                                                      # other Python version: never re-pointed
            r = mq_venv.repair(v, BASE, allow_set_aside=False)                            # running bot: no rename
            self.assertEqual(r["state"], "FAILED")
            self.assertTrue(v.exists())
            r = mq_venv.repair(v, BASE)                                                   # installer: set aside, caller recreates
            self.assertEqual(r["state"], "SET_ASIDE")
            self.assertFalse(v.exists())
            self.assertEqual(len([x for x in os.listdir(d) if x.startswith(".venv_granite_old_")]), 1)
            self.assertEqual(mq_venv.repair(v, BASE)["state"], "MISSING")

    def test_repair_all_only_known_venvs(self):
        with tempfile.TemporaryDirectory() as d:
            v = make(Path(d))
            move(v)
            out = mq_venv.repair_all(Path(d), BASE)
            self.assertEqual(out[".venv_granite"]["state"], "REPAIRED")
            self.assertEqual(set(out), {".venv_granite"})


if __name__ == "__main__":
    unittest.main()
