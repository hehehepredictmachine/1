"""1.46 arch: `python -m masterquo models check` - one health check of every model producer (modelhub/check.py, modelhub/smoke/).

* the registry layer lists every producer of the canonical registry (no second list of models) and exits 0 on a fresh install;
* `--smoke` runs an area in its own process on a TEMPORARY data folder (the caller's MASTERQUO_DATA_DIR is never written);
* the verdict never says DZIAŁA for a step that could not run here (NIEZWERYFIKOWANY) and never hides a failed step;
* the hidden `_area` worker refuses to run without a temporary data folder.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import _env
from _env import TempData

BACKEND = _env.ROOT / "backend"


def _cli(*args, env_extra=None, timeout=600):
    env = dict(os.environ, PYTHONPATH=str(BACKEND), PMW_BOOTSTRAP="0", **(env_extra or {}))
    return subprocess.run([sys.executable, "-m", "masterquo", *args], cwd=str(BACKEND), env=env, capture_output=True, text=True,
                          timeout=timeout, check=False)


class TestModelsCheckCli(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_registry_layer_lists_every_producer(self):
        from masterquo.modelhub import check as MC
        out = Path(self.td.dir) / "mc.json"
        r = _cli("models", "check", "--json", str(out), env_extra={"MASTERQUO_DATA_DIR": self.td.dir})
        self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-1500:])
        rows = json.loads(out.read_text(encoding="utf-8"))["rows"]
        self.assertEqual(sorted(p.name for p in Path(self.td.dir).iterdir()), ["mc.json"])   # the user data folder stays untouched
        other = TempData()                                                     # the registry probes create folders - never in the user's
        try:
            want = sorted(p["id"] for p in MC.producers())
        finally:
            other.close()
        self.assertEqual(sorted(x["id"] for x in rows), want)
        st = {x["id"]: x["status"] for x in rows}
        self.assertEqual(st["ext:catboost"], "NOT_IMPLEMENTED")
        for ns in ("mm:sdom", "mm:quant_momentum", "mm:renko", "mm:head_shoulders", "mm:data_grabber", "mm:chart_sync", "extind:PAL02M"):
            self.assertEqual(st[ns], "NO_SPEC", ns)                           # 1.46 arch I0548 / I0549 / I0550: every NO_SPEC row
        self.assertNotIn("DZIAŁA", st.values())                              # no smoke requested -> nothing claimed to work

    def test_smoke_area_end_to_end_on_a_temporary_folder(self):
        out = Path(self.td.dir) / "mc.json"
        r = _cli("models", "check", "--smoke", "--area", "trainhub", "--only", "trainhub:TH_LOGREG", "--json", str(out),
                 env_extra={"MASTERQUO_DATA_DIR": self.td.dir})
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-1500:])
        row = json.loads(out.read_text(encoding="utf-8"))["rows"][0]
        self.assertEqual(row["id"], "trainhub:TH_LOGREG")
        self.assertEqual(row["status"], "DZIAŁA", row)
        self.assertEqual({k: v["status"] for k, v in row["steps"].items() if k in ("train", "artifact", "predict", "contract")},
                         {"train": "OK", "artifact": "OK", "predict": "OK", "contract": "OK"})
        self.assertEqual(sorted(p.name for p in Path(self.td.dir).iterdir()), ["mc.json"])

    def test_area_worker_refuses_without_a_temporary_folder(self):
        env = {k: v for k, v in os.environ.items() if k != "MASTERQUO_DATA_DIR"}
        r = subprocess.run([sys.executable, "-m", "masterquo", "models", "_area", "rules"], cwd=str(BACKEND),
                           env=dict(env, PYTHONPATH=str(BACKEND), PMW_BOOTSTRAP="0"), capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(r.returncode, 2, r.stderr)


class TestEnvDiscovery(unittest.TestCase):
    def test_model_environments_are_found_through_the_bots_variables(self):
        import stat

        from masterquo.modelhub import smoke as S
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.dict(os.environ, {"MASTERQUO_DATA_DIR": d}):
            fake = Path(d) / "python"
            fake.write_text("#!/bin/sh\n", encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            ctx = S.Ctx("XAUUSD")
            for venv, var in ((".venv_chronos2", "MQ_CHRONOS2_PYTHON"), (".venv_granite", "MQ_GRANITE_TTM_PYTHON"), (".venv_tirex2", "MQ_TIREX2_PYTHON"),
                              (".venv_deep", "MQ_DEEP_PYTHON"), (".venv_kronos", "MQ_KRONOS_PYTHON"), (".venv_tabicl", "MQ_TABICL_PYTHON")):
                with unittest.mock.patch.dict(os.environ, {var: str(fake)}):
                    self.assertEqual(ctx.env_python(venv), str(fake), var)      # 1.46 arch: chronos2/granite/tirex2 were not mapped


class TestVerdict(unittest.TestCase):
    def _p(self, **kw):
        return {"id": "x:y", "code_state": "IMPLEMENTED", "registry_state": "NOT_TRAINED", "registry_reason": None, **kw}

    def test_verdict_rules(self):
        from masterquo.modelhub import check as MC
        from masterquo.modelhub import smoke as S
        v = lambda steps, nc=None, p=None: MC.verdict(p or self._p(), steps, None, None, nc)[0]
        self.assertEqual(v({"train": S.ok(), "artifact": S.ok(), "predict": S.ok(), "contract": S.ok()}), "DZIAŁA")
        self.assertEqual(v({"train": S.ok(), "artifact": S.ok(), "predict": S.skip("brak ścieżki")}), "DZIAŁA")
        self.assertEqual(v({"env": S.unverified("brak .venv"), "train": S.ok(), "predict": S.ok()}), "NIEZWERYFIKOWANY")
        self.assertEqual(v({"env": S.unverified("brak .venv"), "train": S.fail("x")}), "BŁĄD")
        self.assertEqual(v({}, nc="terminal MT5"), "NIEZWERYFIKOWANY")
        self.assertEqual(v({}), "NOT_TRAINED")
        self.assertEqual(v({}, p=self._p(code_state="NO_SPEC")), "NO_SPEC")

    def test_smoke_exception_is_a_failed_step(self):
        from masterquo.modelhub import smoke as S
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.dict(os.environ, {"MASTERQUO_DATA_DIR": d}), \
                unittest.mock.patch.object(S, "load_area", return_value=({"x:y": lambda ctx: (setattr(ctx, "step", "train"), 1 / 0)}, {})):
            rows = S.run_area("rules")
        self.assertEqual(rows[0]["steps"]["train"]["status"], "FAIL")
        self.assertIn("ZeroDivisionError", rows[0]["steps"]["train"]["detail"])


class TestSmokeZeroIsAValue(unittest.TestCase):
    """A smoke comparison `x or -1` turns a legitimate 0.0 (a TREE raw_score of exactly 0 on SYNTHETIC_TEST data, a confidence score of 0)
    into 'missing' and reports BŁĄD for a model that works (Etap 5: lab:TREE failed one models check run of two). The smoke modules
    compare numbers with an explicit `is not None`."""

    def test_no_falsy_default_in_numeric_comparisons(self):
        import re
        smoke = _env.ROOT / "backend" / "masterquo" / "modelhub" / "smoke"
        bad = []
        for f in sorted(smoke.glob("*.py")):
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bor -1\b", line):
                    bad.append(f"{f.name}:{n}: {line.strip()[:120]}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
