"""1.12 scalp ML/NN pipeline in the isolated candle environment - SYNTHETIC_TEST data checks the PROGRAM, not the market.
Group 9 of the prompt: plan written before fitting and reused, disjoint UTC periods, purge by label end, feature contract
and prefix invariance, labels never across gaps, the artifact read back through the worker path, checksum / data-kind
guards (a synthetic model never becomes active outside tests), BLOCKED_NO_REAL_DATA without an export."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests" / "scalp"))

import synth  # noqa: E402


def _run(args, env):
    return subprocess.run([sys.executable, "-m", "gold_candles_runtime.scalp_train"] + args, cwd=str(ROOT / "backend"), env=env,
                          capture_output=True, text=True, timeout=1800)


class ScalpTrain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="mq_scalp_tr_"))
        cls.data = cls.tmp / "data"
        cls.prev = os.environ.get("MASTERQUO_DATA_DIR")
        os.environ["MASTERQUO_DATA_DIR"] = str(cls.data)
        cls.env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"), MASTERQUO_DATA_DIR=str(cls.data))
        cls.env.pop("MQ_FORECAST_TEST_ALLOW_SYNTHETIC", None)
        cls.hist = synth.write_export(cls.data / "scalp" / "history" / "20260401T0000Z", synth.m1_bars(12, seed=2))
        cls.p = _run(["--data-kind", "SYNTHETIC_TEST", "--small-test", "--commission-per-lot-side", "3.5"], cls.env)
        runs = sorted((cls.data / "scalp" / "runs").glob("*"), key=lambda p: p.stat().st_mtime)
        cls.rd = runs[-1] if runs else None

    @classmethod
    def tearDownClass(cls):
        if cls.prev is None:
            os.environ.pop("MASTERQUO_DATA_DIR", None)
        else:
            os.environ["MASTERQUO_DATA_DIR"] = cls.prev

    def test_run_completes_with_statuses(self):
        self.assertEqual(self.p.returncode, 0, self.p.stdout[-2000:] + self.p.stderr[-2000:])
        rep = json.loads((self.rd / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rep["task_A"]), {"1", "3", "5"})
        for h in rep["task_A"].values():
            self.assertIn(h["status"], ("INSUFFICIENT_DATA", "REJECTED", "SHADOW_UNVALIDATED", "SHADOW_VALIDATED"))
            if h["status"] != "INSUFFICIENT_DATA":
                self.assertIn("BASELINE_PRIOR", h["holdout"])
                self.assertIn("MLP", h["holdout"])                           # the real MLP was trained (small test minimums)
                self.assertGreater(h["mlp"]["epochs"], 0)
                self.assertIn("coverage_q10_q90", h["quantiles"])
                self.assertLess(h["holdout_days"], 30)                       # short synthetic sample can never be SHADOW_VALIDATED
                self.assertNotEqual(h["status"], "SHADOW_VALIDATED")
        self.assertIn(rep["task_B"]["status"], ("INSUFFICIENT_DATA", "REJECTED", "SHADOW_UNVALIDATED"))
        self.assertTrue(all(v["finite"] and v["sum_to_one"] for v in rep["runtime_check"]["horizons"].values()))

    def test_plan_before_fit_and_disjoint_periods(self):
        steps = [json.loads(x)["step"] for x in (self.rd / "run_log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertLess(steps.index("PLAN"), steps.index("FEATURES"))
        self.assertLess(steps.index("PLAN"), steps.index("A"))
        plan = json.loads((self.rd / "TRAINING_PLAN.json").read_text(encoding="utf-8"))
        b = plan["boundaries_utc"]
        self.assertEqual(b["development"][1], b["calibration"][0])
        self.assertEqual(b["calibration"][1], b["holdout"][0])
        self.assertTrue(b["calibration"][0].endswith("T00:00:00Z"))
        self.assertLess(b["development"][0], b["calibration"][0])
        self.assertLess(b["calibration"][0], b["holdout"][0])
        self.assertEqual(plan["embargo_seconds"], 1800)
        self.assertIn("SMALL TEST", plan["minimums_note"])

    def test_plan_reused_for_same_data(self):
        p2 = _run(["--data-kind", "SYNTHETIC_TEST", "--small-test", "--commission-per-lot-side", "3.5"], self.env)
        self.assertEqual(p2.returncode, 0)
        self.assertIn("istniejący plan", p2.stdout)

    def test_synthetic_never_active_and_guards(self):
        from gold_candles_runtime.scalp_infer import read_registry
        reg = read_registry()
        self.assertIsNone(reg.get("active"))
        e = list(reg["runs"].values())[0]
        self.assertTrue(e["activation"].startswith("NOT_ACTIVATED"))
        bad = _run(["--data-kind", "REAL_USER_DATA", "--small-test", "--commission-per-lot-side", "3.5"], self.env)
        self.assertNotEqual(bad.returncode, 0)
        bad2 = _run(["--data-kind", "REAL_USER_DATA", "--commission-per-lot-side", "3.5"], self.env)   # data says SYNTHETIC_TEST
        self.assertNotEqual(bad2.returncode, 0)

    def test_worker_path_and_checksum(self):
        from gold_candles_runtime import scalp_registry, worker
        from gold_candles_runtime.scalp_infer import read_registry
        rid = sorted(read_registry()["runs"])[0]
        self.assertNotEqual(scalp_registry.main(["activate", rid]), 0)        # synthetic: refused
        os.environ["MQ_FORECAST_TEST_ALLOW_SYNTHETIC"] = "1"
        try:
            self.assertEqual(scalp_registry.main(["activate", rid]), 0)
            bars = synth.m1_bars(1, seed=9)[:300]
            ans = worker.scalp_forecast({"m1": bars})
            self.assertEqual(ans["status"], "SHADOW", ans)
            self.assertFalse(ans["execution_permission"])
            for h in ans["horizons"].values():
                self.assertAlmostEqual(h["p_down"] + h["p_flat"] + h["p_up"], 1.0, places=3)
                q = h["q10_q50_q90_price"]
                self.assertTrue(q[0] <= q[1] <= q[2])
            self.assertEqual(worker.scalp_forecast({"m1": bars[:30]})["status"], "WARMUP")
            entry = read_registry()["runs"][rid]
            f = Path(entry["run_dir"]) / entry["models"]["1"]["quantiles_file"]
            raw = f.read_bytes()
            f.write_bytes(raw + b"x")
            worker._scalp_cache.update(run_id=None, model=None)
            ans2 = worker.scalp_forecast({"m1": bars})
            self.assertEqual(ans2["status"], "UNAVAILABLE")
            self.assertIn("CHECKSUM", ans2["reason"])
            f.write_bytes(raw)
            self.assertEqual(scalp_registry.main(["deactivate"]), 0)
            self.assertEqual(worker.scalp_forecast({"m1": bars})["reason"], "NO_MODEL")
        finally:
            os.environ.pop("MQ_FORECAST_TEST_ALLOW_SYNTHETIC", None)

    def test_features_prefix_invariant_and_labels_skip_gaps(self):
        from gold_candles_runtime import scalp_features as SF
        b = synth.m1_bars(1, seed=4)
        t = [int(datetime.fromisoformat(x["open_utc"].replace("Z", "+00:00")).timestamp()) for x in b]
        cols = lambda k: [x[k] for x in b]  # noqa: E731
        X, a = SF.build(t, cols("o"), cols("h"), cols("l"), cols("c"), cols("tv"), cols("spread_price"))
        X2, _ = SF.build(t[:900], cols("o")[:900], cols("h")[:900], cols("l")[:900], cols("c")[:900], cols("tv")[:900], cols("spread_price")[:900])
        np.testing.assert_array_equal(X[:900], X2)
        t_gap = list(t)
        for k in range(500, len(t_gap)):
            t_gap[k] += 3600                                                 # one-hour gap after bar 499
        Y, Q, END = SF.labels(t_gap, cols("c"), a, cols("spread_price"), 0.035, 0.02)
        self.assertEqual(Y[1][499], -1)
        self.assertEqual(Y[5][497], -1)
        self.assertNotEqual(Y[1][498], -1)
        self.assertEqual(END[1][498], t_gap[499] + 60)

    def test_blocked_without_export(self):
        env = dict(self.env, MASTERQUO_DATA_DIR=str(self.tmp / "empty"))
        p = _run(["--commission-per-lot-side", "3.5"], env)
        self.assertEqual(p.returncode, 3)
        st = json.loads((self.tmp / "empty" / "scalp" / "TRAINING_STATUS.json").read_text(encoding="utf-8"))
        self.assertEqual(st["status"], "BLOCKED_NO_REAL_DATA")


class SetupQualityFilter(unittest.TestCase):
    """Task B as a filter on fabricated cycles (SYNTHETIC: one feature carries signal) - walk-forward choice, calibration,
    threshold chosen on calibration by expectancy, holdout once with vs without the filter, artifact read by the worker path."""

    def cycles(self, n, seed, t0):
        from masterquo.scalp.strategy import SETUP_FEATURES
        rng = np.random.default_rng(seed)
        out = []
        for k in range(n):
            f = {x: float(rng.normal()) for x in SETUP_FEATURES}
            good = rng.random() < 1 / (1 + np.exp(-2.5 * f["sweep_depth_atr5"]))
            day = t0 + (k * 86400 * 60) // n
            tt = datetime.fromtimestamp(day, tz=__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            out.append({"features": f, "tp1_before_sl": bool(good), "net_r": 1.2 if good else -1.0, "fill_time": tt,
                        "exits": [{"time": tt}], "ambiguous": False, "hold_min": 10, "direction": "BUY"})
        return out

    def test_filter_trained_calibrated_and_loadable(self):
        from gold_candles_runtime import scalp_train as T
        from gold_candles_runtime.scalp_infer import SetupModel
        rd = Path(tempfile.mkdtemp(prefix="mq_setupq_"))
        dev, cal, hold = self.cycles(600, 1, 1767225600), self.cycles(200, 2, 1767225600 + 70 * 86400), self.cycles(300, 3, 1767225600 + 140 * 86400)
        logs = []
        B, spec, arts = T.train_setup_model(dev, cal, hold, T.MIN, lambda *a, **k: logs.append(a), rd)
        self.assertIn(B["selected"], ("LR", "HGB"))                                            # MLP needs >= 1000 dev cycles
        self.assertNotIn("MLP", B["walk_forward_log_loss"])
        self.assertIsNotNone(B["threshold"])
        hu, hf = B["holdout_unfiltered"], B["holdout_filtered"]
        self.assertGreater(hf["win_rate"], hu["win_rate"])                                     # the informative feature raises win rate
        self.assertGreater(hf["expectancy_r"], hu["expectancy_r"])
        self.assertLess(hf["cycles"], hu["cycles"])                                            # ... by trading less
        self.assertEqual(B["status"], "FILTER_HELPS_IN_HOLDOUT")
        entry = {"run_dir": str(rd), "artifacts": arts, "setup_model": spec}
        m = SetupModel(entry)
        X = np.asarray([[c["features"][k] for k in spec["features"]] for c in hold[:5]])
        p = m.predict(X)
        self.assertTrue(np.all((p > 0) & (p < 1)))
        hi = dict(hold[0]["features"], sweep_depth_atr5=3.0)
        lo = dict(hold[0]["features"], sweep_depth_atr5=-3.0)
        ph, pl_ = m.predict(np.asarray([[hi[k] for k in spec["features"]], [lo[k] for k in spec["features"]]]))
        self.assertGreater(ph, pl_)

    def test_too_few_cycles_is_insufficient(self):
        from gold_candles_runtime import scalp_train as T
        B, spec, arts = T.train_setup_model(self.cycles(50, 1, 1767225600), self.cycles(20, 2, 1767225600), self.cycles(20, 3, 1767225600),
                                            T.MIN, lambda *a, **k: None, None)
        self.assertEqual(B["status"], "INSUFFICIENT_DATA")
        self.assertIsNone(spec)

    def test_noise_feature_gives_no_filter(self):
        from gold_candles_runtime import scalp_train as T
        cyc = lambda n, seed, t0: [dict(c, tp1_before_sl=bool(i % 2), net_r=1.0 if i % 2 else -1.0) for i, c in enumerate(self.cycles(n, seed, t0))]  # noqa: E731
        B, spec, _ = T.train_setup_model(cyc(600, 4, 1767225600), cyc(200, 5, 1767225600 + 70 * 86400), cyc(300, 6, 1767225600 + 140 * 86400),
                                         T.MIN, lambda *a, **k: None, None)
        self.assertIn(B["status"], ("REJECTED", "NO_USEFUL_THRESHOLD", "FILTER_NOT_HELPING_IN_HOLDOUT"))


if __name__ == "__main__":
    unittest.main()
