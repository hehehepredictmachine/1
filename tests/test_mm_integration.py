"""PMW-MM master models - integration: the full orchestrator graph on a SYNTHETIC export (subprocess, the same command the training
runner task `master_models` uses), immutable artifacts (checksum, promotion only from VALIDATED_SHADOW, rollback), the SHADOW ledger
(dedup, maturation once), runner/registry wiring, native fixture parity contract, drift actions, the API endpoints on a real server
process, and static isolation: no order path in the mm package or in the new MQL5 sources. OpenCL / ONNX checks run only when the
optional packages are installed (skipped otherwise - never reported as passed)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

import _env
from _env import TempData
import test_sh_api as T
from test_sh_api import call

from masterquo.mm import artifacts as AR
from masterquo.mm import drift as DR
from masterquo.mm import fixtures as FX
from masterquo.mm import inventory as INV
from masterquo.mm.ledger import Ledger
from masterquo.mm.orchestrator import GRAPH

BACKEND = _env.ROOT / "backend"
MQL5 = [p for d in ("mql5/MasterModels", "mql5/MathFidelity") for p in (_env.ROOT / d).rglob("*") if p.suffix in (".mq5", ".mqh")]


def _env_for(td: str) -> dict:
    env = dict(os.environ, MASTERQUO_DATA_DIR=td, PYTHONPATH=str(BACKEND), MQ_FAKE_MARKET_ALWAYS_OPEN="1")
    env.pop("ANTHROPIC_API_KEY", None)
    return env


class TestOrchestratorRun(unittest.TestCase):
    """One quick run of every job on a synthetic export; assertions on statuses, labels, artifacts and the SHADOW pointer."""

    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        cls.ds = Path(cls.td.dir) / "ds" / "XAUUSD"
        cls.out = Path(cls.td.dir) / "run"
        env = _env_for(cls.td.dir)
        r = subprocess.run([sys.executable, "-m", "masterquo", "training", "export", "--instrument", "XAUUSD", "--symbol", "XAUUSD-", "--months", "2",
                            "--out", str(cls.ds), "--tfs", "M1,M5,M15,H1", "--synthetic"], cwd=str(BACKEND), env=env, capture_output=True, text=True,
                           timeout=1200)
        if r.returncode != 0:
            raise RuntimeError("export failed: " + r.stdout[-800:] + r.stderr[-800:])
        r = subprocess.run([sys.executable, "-m", "masterquo", "mm", "train", "--dataset", str(cls.ds), "--instrument", "XAUUSD", "--out", str(cls.out),
                            "--profile", "quick"], cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=2400)
        cls.rc, cls.log = r.returncode, r.stdout[-3000:] + r.stderr[-3000:]
        cls.rep = json.loads((cls.out / "REPORT.json").read_text(encoding="utf-8")) if (cls.out / "REPORT.json").exists() else {}

    @classmethod
    def tearDownClass(cls):
        cls.td.close()

    def test_all_jobs_and_labels(self):
        self.assertEqual(self.rc, 0, self.log)
        jobs = self.rep["jobs"]
        self.assertEqual(set(jobs), {g[0] for g in GRAPH})
        bad = {k: (v["status"], v.get("reason")) for k, v in jobs.items() if v["status"] != "SUCCEEDED"}
        self.assertEqual(bad, {})
        self.assertEqual(self.rep["snapshot"]["data_kind"], "SYNTHETIC_TEST")
        self.assertFalse(any(v.get("validation_passed") for v in jobs.values()))         # synthetic data never validates a model
        self.assertEqual(self.rep["safety"]["orders_sent"], 0)
        for j in ("hdc", "gpr", "event_engine", "ste_flownet"):
            self.assertTrue(jobs[j]["training_executed"], j)
            self.assertTrue(jobs[j]["artifact_id"], j)
        for f in ["REPORT.md"] + [f"{g[0]}.json" for g in GRAPH]:
            self.assertTrue((self.out / f).exists(), f)

    def test_artifacts_pointer_and_inventory(self):
        os.environ["MASTERQUO_DATA_DIR"] = self.td.dir
        arts = AR.list_artifacts("XAUUSD")
        self.assertGreaterEqual(len(arts), 4)
        self.assertEqual({a["status"] for a in arts}, {"TECHNICAL_TEST_ONLY"})
        self.assertEqual(AR.read_pointer("XAUUSD")["active"], {})                       # nothing promoted from a synthetic run
        a = next(x for x in arts if x["model_id"].startswith("gpr"))
        state, man = AR.load("XAUUSD", a["model_id"], a["artifact_id"])
        self.assertEqual(man["data_kind"], "SYNTHETIC_TEST")
        with self.assertRaises(AR.ArtifactError):
            AR.promote_shadow("XAUUSD", a["model_id"], a["artifact_id"], "test")
        with self.assertRaises(AR.ArtifactError):
            AR.load("BTC", a["model_id"], a["artifact_id"])
        rep = INV.latest_report("XAUUSD")
        self.assertEqual(rep["run_id"], self.rep["run_id"])
        rows = INV.merge_run(rep)
        self.assertEqual(len(rows), 20)
        self.assertEqual(sum(r["status"] == "BLOCKED" for r in rows), 6)

    def test_cancel_and_bad_snapshot(self):
        env = _env_for(self.td.dir)
        cf = Path(self.td.dir) / "cancel.flag"
        cf.write_text("x")
        out = Path(self.td.dir) / "run_cancel"
        r = subprocess.run([sys.executable, "-m", "masterquo", "mm", "train", "--dataset", str(self.ds), "--instrument", "XAUUSD", "--out", str(out),
                            "--profile", "quick", "--cancel-file", str(cf)], cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=600)
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        self.assertEqual(rep["status"], "CANCELLED", r.stdout[-500:])
        self.assertTrue(all(j["status"] == "CANCELLED" for j in rep["jobs"].values()))
        broken = Path(self.td.dir) / "broken"
        broken.mkdir()
        (broken / "source_metadata.json").write_text("{}")
        out2 = Path(self.td.dir) / "run_broken"
        subprocess.run([sys.executable, "-m", "masterquo", "mm", "train", "--dataset", str(broken), "--instrument", "XAUUSD", "--out", str(out2),
                        "--profile", "quick"], cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=600)
        rep2 = json.loads((out2 / "REPORT.json").read_text(encoding="utf-8"))
        self.assertEqual(rep2["status"], "BLOCKED_DATA_QUALITY")
        self.assertEqual(rep2["jobs"]["snapshot"]["status"], "BLOCKED_DATA_QUALITY")
        self.assertEqual(rep2["jobs"]["gpr"]["status"], "BLOCKED_DEPENDENCY")              # dependants blocked, never "succeeded"
        self.assertEqual(rep2["jobs"]["buzoa"]["status"], "SUCCEEDED")                     # independent jobs still run


class TestArtifactsLedgerDrift(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_artifact_immutability_promotion_rollback(self):
        a1 = AR.save("XAUUSD", "unit_model", {"w": np.arange(4.0)}, {"status": "VALIDATED_SHADOW", "data_kind": "REAL_USER_DATA"})
        a2 = AR.save("XAUUSD", "unit_model", {"w": np.arange(4.0) + 1}, {"status": "VALIDATED_SHADOW", "data_kind": "REAL_USER_DATA"})
        a3 = AR.save("XAUUSD", "unit_model", {"w": np.zeros(2)}, {"status": "CANDIDATE"})
        AR.promote_shadow("XAUUSD", "unit_model", a1, "first")
        AR.promote_shadow("XAUUSD", "unit_model", a2, "second")
        self.assertEqual(AR.read_pointer("XAUUSD")["active"]["unit_model"], a2)
        with self.assertRaises(AR.ArtifactError):
            AR.promote_shadow("XAUUSD", "unit_model", a3, "candidate")                  # only VALIDATED_SHADOW can move the pointer
        self.assertEqual(AR.rollback("XAUUSD", "unit_model")["active"]["unit_model"], a1)
        with self.assertRaises(AR.ArtifactError):
            AR.rollback("XAUUSD", "unit_model")                                         # no older artifact left
        p = AR.path("XAUUSD", "unit_model", a1) / "state.npz"
        p.write_bytes(p.read_bytes()[:-3] + b"xyz")
        with self.assertRaisesRegex(AR.ArtifactError, "CHECKSUM"):
            AR.load("XAUUSD", "unit_model", a1)
        with self.assertRaises(AR.ArtifactError):
            AR.save("XAUUSD", "unit_model", {"o": np.array([{"a": 1}], dtype=object)}, {})
        with self.assertRaises(AR.ArtifactError):
            AR.save("XAUUSD", "unit_model", {"w": np.zeros(1)}, {"status": "LIVE"})    # no LIVE status exists

    def test_ledger_dedup_and_single_maturation(self):
        led = Ledger(Path(self.td.dir) / "ledger.sqlite")
        kw = dict(model_id="m", artifact_id="a", feature_schema="f", symbol="XAUUSD", timeframe="M5", horizon="3xM5", kind="RETURN_DISTRIBUTION",
                  payload={"mean": 0.1}, quality="OK")
        self.assertTrue(led.log(pred_id="p1", source_ts=100, available_at=400, matures_at=1300, **kw))
        self.assertFalse(led.log(pred_id="p1", source_ts=100, available_at=400, matures_at=1300, **kw))   # restart/replay: no duplicate
        self.assertTrue(led.log(pred_id="p2", source_ts=400, available_at=700, matures_at=1600, **kw))
        with self.assertRaises(ValueError):
            led.log(pred_id="p3", source_ts=0, available_at=500, matures_at=100, **kw)
        calls = []
        res = lambda r: (calls.append(r["pred_id"]) or {"y": 1.0})                     # noqa: E731
        self.assertEqual(led.mature(1300, res), 1)                                       # p2 is not observable yet
        self.assertEqual(led.mature(1300, res), 0)                                       # scored once
        self.assertEqual(led.mature(2000, res), 1)
        self.assertEqual(calls, ["p1", "p2"])
        self.assertEqual(led.summary()[0]["scored"], 2)

    def test_drift_schedules_candidate_only(self):
        g = np.random.default_rng(1)
        ref = g.normal(0, 1, 2000)
        fr = {"x": (DR.reference_bins(ref), ref)}
        same = DR.evaluate(feature_ref=fr, feature_cur={"x": g.normal(0, 1, 500)}, ref_abs_err=1.0, cur_abs_err=1.0, ref_coverage=0.68,
                           cur_coverage=0.68, artifact_created_at=None)
        self.assertEqual(same["action"], "NONE")
        moved = DR.evaluate(feature_ref=fr, feature_cur={"x": g.normal(2, 1, 500)}, ref_abs_err=1.0, cur_abs_err=1.0, ref_coverage=0.68,
                            cur_coverage=0.40, artifact_created_at=None)
        self.assertEqual(moved["action"], "SCHEDULE_CANDIDATE")                         # recommend a candidate job, never replace a model
        self.assertTrue(any(x.startswith("INPUT_DRIFT") for x in moved["reasons"]) and any(x.startswith("CALIBRATION") for x in moved["reasons"]))
        self.assertNotIn("PROMOTE", json.dumps(moved))


class TestNativeContracts(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.ref = Path(self.td.dir) / "fx"
        FX.export(self.ref)

    def tearDown(self):
        self.td.close()

    def _perfect_native(self) -> dict:
        ref = self.ref
        k = [ln.split(",") for ln in (ref / "mm_ref_kalman.csv").read_text().splitlines()[1:] if ln]
        g = [ln.split(",") for ln in (ref / "mm_ref_gpr.csv").read_text().splitlines()[1:] if ln]
        b = [ln.split(",") for ln in (ref / "mm_ref_breakout.csv").read_text().splitlines()[1:] if ln]
        f = lambda x: None if x == "nan" else float(x)                                  # noqa: E731
        return {"kalman": [[int(r[0])] + [f(x) for x in r[1:7]] + [r[7]] for r in k], "gpr": [[int(r[0])] + [f(x) for x in r[1:]] for r in g],
                "hdc": {"all_pass": True}, "breakout": [[int(r[0]), r[1], float(r[2]), float(r[3])] for r in b]}

    def test_parity_statuses(self):
        nat = Path(self.td.dir) / "PMW_MM_NATIVE.txt"
        self.assertEqual(FX.parity(nat, self.ref)["status"], "NATIVE_NOT_EXECUTED")
        d = self._perfect_native()
        nat.write_text(json.dumps(d))
        res = FX.parity(nat, self.ref)
        self.assertEqual(res["status"], "NATIVE_PARITY_PASS", res)
        d["kalman"][500][1] += 1e-6
        nat.write_text(json.dumps(d))
        res = FX.parity(nat, self.ref)
        self.assertEqual((res["status"], res["gates"]["kalman"]), ("NATIVE_PARITY_FAIL", False))
        d = self._perfect_native()
        d["breakout"] = d["breakout"][:-1]
        nat.write_text(json.dumps(d))
        self.assertFalse(FX.parity(nat, self.ref)["gates"]["breakout"])
        nat.write_text("{broken")
        self.assertEqual(FX.parity(nat, self.ref)["status"], "NATIVE_OUTPUT_INVALID")

    def test_fixture_files(self):
        rows = (self.ref / "mm_fixture_bars.csv").read_text().splitlines()
        self.assertEqual(rows[0], "t,o,h,l,c,tv")
        self.assertEqual(len(rows), 1501)
        self.assertGreater(len((self.ref / "mm_ref_breakout.csv").read_text().splitlines()), 10)


class TestStaticIsolation(unittest.TestCase):
    """No order path: the mm package never calls an order function and the new MQL5 sources use no trade API."""

    FORBIDDEN_MQL = re.compile(r"\b(OrderSend|OrderSendAsync|OrderModify|OrderDelete|PositionOpen|PositionClose|PositionModify|CTrade|CPositionInfo)\b"
                               r"|Trade\\Trade\.mqh")

    def test_mm_package_has_no_order_calls(self):
        pat = re.compile(r"order_send\s*\(|order_check\s*\(|place_order|close_position|TRADE_ACTION_|from \.\.(execution|risk|sh\.engine)")
        hits = [f"{p.name}:{i}" for p in (BACKEND / "masterquo" / "mm").glob("*.py") for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                if pat.search(ln)]
        self.assertEqual(hits, [])

    def test_mql5_sources_have_no_trade_api_and_balanced_braces(self):
        self.assertGreaterEqual(len(MQL5), 20)
        for p in MQL5:
            src = p.read_text(encoding="utf-8")
            code = re.sub(r"//[^\n]*", "", re.sub(r'"(\\.|[^"\\])*"', '""', src))
            self.assertIsNone(self.FORBIDDEN_MQL.search(code), p.name)
            self.assertEqual(code.count("{"), code.count("}"), p.name)
            self.assertEqual(code.count("("), code.count(")"), p.name)

    def test_inventory_files_exist(self):
        for m in INV.MODULES:
            for f in m.get("files", []):
                path = f.split(" (")[0]
                self.assertTrue((_env.ROOT / path).exists(), f"{m['id']}: {path}")
        self.assertTrue((_env.ROOT / "mql5" / "MasterModels" / "Scripts" / "PMW_MM_SelfTest.mq5").exists())

    def test_opencl_kernel_source_is_shared(self):
        cl = (BACKEND / "masterquo" / "mm" / "kernels" / "state_stack.cl").read_text(encoding="utf-8")
        mq = (_env.ROOT / "mql5" / "MasterModels" / "Include" / "PMW" / "PMW_StateStack.mqh").read_text(encoding="utf-8")
        for k in ("__kernel void stack_push", "__kernel void stack_corr"):
            self.assertIn(k, cl)
            self.assertIn(k, mq)

    def test_runner_and_registry_wiring(self):
        from masterquo.sh import models as SM
        from masterquo.training import runner as R
        self.assertIn("master_models", {t[0] for t in R.TASKS})
        self.assertIn("master_models", R.STEPS)
        mm = [it for it in SM.REGISTRY if it["id"].startswith("mm_")]
        self.assertGreaterEqual(len(mm), 9)
        for it in mm:
            self.assertEqual(set(it["roles"].values()), {"OBSERVATION"}, it["id"])
            for s in ("READY", "DETERMINISTIC_OK", "NOT_TRAINED", "BLOCKED"):
                self.assertIn(SM.participation(it, {"status": s}, "SCALPING")["use"], ("INFO", "NONE"))


class TestAgentTool(unittest.TestCase):
    def test_get_master_models_is_read_only_observation(self):
        from masterquo.agent import service as S
        from masterquo.agent import tools as AT
        self.assertIn("get_master_models", {t["name"] for t in AT.TOOL_DEFS})
        body, ver = S.load_prompt()
        self.assertTrue(ver.endswith("+PMW-MM-KNOWLEDGE-1.0.0"))
        self.assertIn("MM-K05", body)
        out, err = AT.Toolbox({}, 3).run("get_master_models", {})
        self.assertEqual((json.loads(out)["status"], err), ("UNAVAILABLE", False))     # no provider -> no reading, never a neutral signal
        live = {"status": "OK", "last_closed_m5": 1.0, "data_quality": "SYNTHETIC_TEST", "align_mean": {"charts": []}, "kalman": {"state": "NEUTRAL"},
                "breakout": {"panel": {"text": "LATEST ACCEPTED BREAKOUT: NONE"}, "zones": [1, 2]}, "gpr": {"status": "OK", "mean_logret": 1e-4, "sd": 1e-3,
                "search": {"x": 1}}, "board": {"independence": "SAME_PRICE_FEED"}, "multi_indicator": {"decision": "NO_SIGNAL"}, "smc_fvg": {"trend": 0}}
        r = json.loads(AT.Toolbox({"master_models_fn": lambda: live}, 3).run("get_master_models", {})[0])
        self.assertEqual((r["mode"], r["execution_allowed"]), ("SHADOW_OBSERVE", False))
        self.assertNotIn("zones", r["breakout"])
        self.assertNotIn("search", r["gpr"])


class TestOptionalBackends(unittest.TestCase):
    def test_opencl_stack_parity(self):
        try:
            import pyopencl  # noqa: F401
        except ImportError:
            self.skipTest("pyopencl not installed (OpenCL path not tested here)")
        from masterquo.mm import event_engine as EE
        g = np.random.default_rng(3)
        cpu = EE.StateStack(16, 32, backend="cpu")
        try:
            cl = EE.StateStack(16, 32, backend="opencl")
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"no OpenCL device: {exc}")
        if cl.backend_used != "OPENCL":
            self.skipTest("no OpenCL device")
        for _ in range(40):
            v = g.normal(size=32).astype(np.float32)
            cpu.push(v)
            cl.push(v)
        q = g.normal(size=32).astype(np.float32)
        self.assertLess(float(np.max(np.abs(cpu.corr(q) - cl.corr(q)))), 1e-4)

    def test_onnx_graph(self):
        try:
            import onnx
            import onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest("onnx/onnxruntime not installed (Python-side ONNX check not run)")
        from masterquo.mm import mathbench as MB
        td = TempData()
        try:
            MB.export(Path(td.dir) / "mb", n_vectors=50)
            chk = MB.python_checks(Path(td.dir) / "mb")
            self.assertEqual(chk["onnx_checker"], "PASS")
            self.assertLess(chk["onnxruntime_python"]["max_abs_err_vs_float64"], 1e-4)
            onnx.checker.check_model(onnx.load(str(Path(td.dir) / "mb" / "model.onnx")))
        finally:
            td.close()


class TestMMApi(T.TestSHApi):
    test_endpoints = test_config_change_and_rollback = test_panels_in_browser = None    # reuse only the server fixture

    def test_mm_endpoints(self):
        self.assertTrue(_env.wait_for(lambda: bool(call("/api/v1/sh")[1].get("last_eval")), 120, 1.0))
        mode0 = call("/api/v1/sh")[1]["mode"]
        c, st = call("/api/v1/mm/status?instrument=XAUUSD")
        self.assertEqual(c, 200)
        self.assertEqual(len(st["inventory"]), 20)
        self.assertEqual(st["latest_run"], None)
        c, lv = call("/api/v1/mm/live?instrument=XAUUSD")
        self.assertEqual(c, 200)
        self.assertIn(lv["status"], ("OK", "DATA_MISSING", "UNAVAILABLE"))
        self.assertIs(lv.get("execution_allowed", False), False)
        self.assertEqual(call("/api/v1/mm/status?instrument=EURUSD")[0], 400)
        self.assertEqual(call("/api/v1/mm/job?instrument=XAUUSD&job=nope")[0], 400)
        self.assertEqual(call("/api/v1/mm/job?instrument=XAUUSD&job=gpr")[1]["status"], "NOT_RUN")
        c, led = call("/api/v1/mm/ledger?instrument=XAUUSD")
        self.assertEqual(c, 200)
        self.assertIn("summary", led)
        c, rb = call("/api/v1/mm/rollback", {"instrument": "XAUUSD", "model": "gpr_logret"})
        self.assertEqual((c, rb["ok"]), (200, False))
        c, tm = call("/api/v1/training/models?instrument=XAUUSD")
        self.assertEqual(c, 200)
        rows = [r for r in tm["models"] if r["id"].startswith("mm_")]
        self.assertGreaterEqual(len(rows), 9)
        self.assertTrue(all(r["SCALPING"]["role"] == "OBSERVATION" and r["SCALPING"]["use"] in ("INFO", "NONE") for r in rows))
        self.assertEqual(call("/api/v1/sh")[1]["mode"], mode0)                         # read-only endpoints never change the mode


if __name__ == "__main__":
    unittest.main()
