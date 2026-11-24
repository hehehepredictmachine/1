"""1.46 arch (models check --smoke, research:sdformerflow): no trained SDformerFlow could ever be activated on 1.46.0.

1.46 made every checkpoint read `torch.load(..., weights_only=True)` (no pickle code from an imported ZIP), but sdformer_runtime/train.py
kept writing deps.torch = torch.__version__ - a torch.torch_version.TorchVersion object -> "Unsupported global" on EVERY load: activation
after training failed, fine_tune / resume failed, the module stayed in ERROR and never published a forecast. The tests need a Python
with torch 2.14.1 (MQ_SDF_PYTHON / MQ_DEEP_PYTHON / <program>/.venv_deep) and are skipped without one.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import _env
from _env import TempData


def _torch_python() -> str | None:
    for c in (os.environ.get("MQ_SDF_PYTHON"), os.environ.get("MQ_DEEP_PYTHON"), _env.ROOT / ".venv_deep" / "Scripts" / "python.exe",
              _env.ROOT / ".venv_deep" / "bin" / "python"):
        if c and Path(c).is_file():
            r = subprocess.run([str(c), "-c", "import torch"], capture_output=True, check=False)
            if r.returncode == 0:
                return str(c)
    return None


PY = _torch_python()
BACKEND = _env.ROOT / "backend"


def _run(*args, timeout=600):
    env = dict(os.environ, PYTHONPATH=str(BACKEND), PYTHONNOUSERSITE="1", OMP_NUM_THREADS="1")
    return subprocess.run([PY, *args], cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=timeout, check=False)


@unittest.skipUnless(PY, "brak Pythona z torch (MQ_SDF_PYTHON / MQ_DEEP_PYTHON / .venv_deep) – test pominięty")
class TestSdformerCheckpoint(unittest.TestCase):
    def test_checkpoint_written_by_1_46_0_loads_with_weights_only(self):
        d = Path(tempfile.mkdtemp(prefix="sdf146_"))
        code = ("import torch, sys; from pathlib import Path; from sdformer_runtime.ckpt import load_checkpoint; p = Path(sys.argv[1]) / 'last.pt';"
                "torch.save({'deps': {'torch': torch.__version__}, 'w': torch.zeros(2)}, p);"      # exactly what 1.46.0 wrote
                "ck = load_checkpoint(p); print('OK', type(ck['deps']['torch']).__name__)")
        r = _run("-c", code, str(d))
        self.assertEqual(r.returncode, 0, r.stderr[-600:])                      # 1.46.0: ImportError (no load_checkpoint) / UnpicklingError
        self.assertIn("OK", r.stdout)

    def test_train_then_infer_end_to_end(self):
        from masterquo.modelhub import smoke as S
        td = TempData()
        try:
            bars = S.Ctx("XAUUSD").bars("H1", 700, history_days=60)
            d = Path(td.dir)
            (d / "h1.json").write_text(json.dumps(bars), encoding="utf-8")
            r = _run("-m", "sdformer_runtime.train", "--data", str(d / "h1.json"), "--out", str(d / "sdf"), "--op", "from_scratch",
                     "--epochs", "1", "--minutes", "3", "--batch", "16", "--threads", "1", "--run-id", "SDF-T1")
            self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-800:])
            ck = d / "sdf" / "SDF-T1"
            self.assertTrue((ck / "last.pt").is_file(), list((d / "sdf").iterdir()))
            r = _run("-m", "sdformer_runtime.infer", "--checkpoint", str(ck), "--bars", str(d / "h1.json"), "--threads", "1")
            line = (r.stdout.strip().splitlines() or [""])[-1]
            self.assertTrue(line.startswith("RESULT "), (r.stdout + r.stderr)[-800:])
            res = json.loads(line[7:])
            self.assertTrue(res.get("ok"), res)                                 # 1.46.0: UnpicklingError TorchVersion -> no activation
            r = _run("-m", "sdformer_runtime.train", "--data", str(d / "h1.json"), "--out", str(d / "sdf"), "--op", "fine_tune",
                     "--checkpoint", str(ck), "--epochs", "1", "--minutes", "3", "--batch", "16", "--threads", "1", "--run-id", "SDF-T2")
            self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-800:])
        finally:
            td.close()


if __name__ == "__main__":
    unittest.main()
