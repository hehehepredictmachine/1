"""PMW-UPD-08 R17 SIGNAL_NEUTRALIZATION_ROLLING_V1 - T62-T71 on generated data (code behaviour, not market evidence)."""
import math
import unittest

import numpy as np

import _env  # noqa: F401
from _env import TempData

from masterquo.analysis import neutralization as NZ


def series(n=600, seed=1, drift=False):
    rng = np.random.default_rng(seed)
    f1 = rng.normal(0, 1, n)
    f2 = np.cumsum(rng.normal(0, 0.1, n))
    b = np.where(np.arange(n) > n // 2, 3.0, 1.0) if drift else np.ones(n)
    s = 0.5 + b * f1 * 2.0 - 1.5 * f2 + rng.normal(0, 0.3, n)
    return [float(i * 60) for i in range(n)], list(s), {"volatility": list(f1), "trend_slope": list(f2)}


class TestNeutralization(unittest.TestCase):
    def test_t62_fit_orthogonality_only_in_window(self):
        t, s, f = series()
        rows = NZ.run_series(t, s, f)
        ok = [r for r in rows if r["status"] == "OK"]
        self.assertTrue(ok)
        nz = NZ.RollingNeutralizer("ROC20", "M", "C")
        for i in range(len(t)):
            nz.step(t[i], s[i], {k: v[i] for k, v in f.items()})
        self.assertLess(nz.fit["orthogonality_max_abs"], 1e-9)
        self.assertLess(abs(nz.fit["mean_residual_fit"]), 1e-9)

    def test_t63_score_before_update_and_future_mutation(self):
        t, s, f = series()
        a = NZ.run_series(t, s, f)
        s2 = s[:400] + [x * 50 for x in s[400:]]
        b = NZ.run_series(t, s2, f)
        for i in range(400):
            self.assertEqual(a[i].get("residual"), b[i].get("residual"))
            self.assertEqual(a[i].get("fit_id"), b[i].get("fit_id"))
        nz = NZ.RollingNeutralizer("X", "M", "C")
        for i in range(300):
            nz.step(t[i], s[i], {k: v[i] for k, v in f.items()})
        before = nz.fit["fit_id"]
        r = nz.step(t[300], 1e6, {k: v[300] for k, v in f.items()})            # extreme current value does not move its own fit
        self.assertEqual(r["fit_id"], before)
        self.assertAlmostEqual(r["residual"], 1e6 - r["exposure"])

    def test_t65_states(self):
        t = [float(i) for i in range(200)]
        r = NZ.run_series(t, [1.0] * 200, {"volatility": [1.0] * 200, "trend_slope": list(np.linspace(0, 1, 200))})
        self.assertIn("CONSTANT_FACTOR", {x["status"] for x in r})
        self.assertFalse(any(x["eligible"] for x in r))
        r2 = NZ.run_series(t[:30], [1.0] * 30, {"volatility": list(range(30)), "trend_slope": list(range(30))})
        self.assertEqual({x["status"] for x in r2}, {"WARMUP"})
        nz = NZ.RollingNeutralizer("X", "M", "C")
        self.assertEqual(nz.step(0.0, None, {"volatility": 1, "trend_slope": 1})["status"], "NAN_INPUT")
        tt, s, f = series(300)
        f["trend_slope"] = [2 * x for x in f["volatility"]]                      # collinear
        rr = NZ.run_series(tt, s, f)
        self.assertIn("SINGULAR", {x["status"] for x in rr} | {x.get("fit", {}).get("status") if isinstance(x.get("fit"), dict) else None for x in rr})

    def test_t66_units_invariance(self):
        t, s, f = series()
        a = NZ.run_series(t, s, f)
        g = {"volatility": [x * 1000 for x in f["volatility"]], "trend_slope": [x / 50 for x in f["trend_slope"]]}
        b = NZ.run_series(t, s, g)
        for x, y in zip(a, b):
            if x.get("residual") is not None:
                self.assertAlmostEqual(x["residual"], y["residual"], places=6)

    def test_t67_t68_degenerate_and_partial(self):
        t = [float(i) for i in range(300)]
        f1 = list(np.random.default_rng(3).normal(size=300))
        f2 = list(np.random.default_rng(4).normal(size=300))
        s = [0.2 + 1.5 * a - 0.7 * b for a, b in zip(f1, f2)]                  # perfectly explained -> residual ~ 0
        r = NZ.run_series(t, s, {"volatility": f1, "trend_slope": f2})
        last = r[-1]
        self.assertEqual(last["status"], "DEGENERATE_RESIDUAL")
        self.assertIsNone(last["z_residual"])
        tt, ss, ff = series()
        x = [q for q in NZ.run_series(tt, ss, ff) if q.get("partial")][-1]
        self.assertAlmostEqual(x["partial"]["0.0"], x["raw"])
        self.assertAlmostEqual(x["partial"]["1.0"], x["residual"])

    def test_t69_restart_duplicate_version_gap(self):
        t, s, f = series()
        nz = NZ.RollingNeutralizer("ROC20", "M1", "C")
        for i in range(250):
            nz.step(t[i], s[i], {k: v[i] for k, v in f.items()})
        st = nz.state()
        nz2 = NZ.RollingNeutralizer.load(st, "ROC20", "M1", "C")
        a = nz.step(t[250], s[250], {k: v[250] for k, v in f.items()})
        b = nz2.step(t[250], s[250], {k: v[250] for k, v in f.items()})
        self.assertAlmostEqual(a["residual"], b["residual"])
        self.assertEqual(nz2.step(t[250], s[250], {k: v[250] for k, v in f.items()})["status"], "DUPLICATE_OR_OLD")
        nz3 = NZ.RollingNeutralizer.load(st, "ROC20", "M2", "C")                  # new model version -> reset
        self.assertEqual(nz3.last_reset, "VERSION_OR_CONTEXT_CHANGE")
        self.assertEqual(len(nz3.S), 0)
        nz2.step(t[251] + 10 ** 6, s[251], {k: v[251] for k, v in f.items()})   # long gap -> reset
        self.assertEqual(nz2.last_reset, "GAP")

    def test_t70_drift_reported(self):
        t, s, f = series(800, drift=True)
        rows = NZ.run_series(t, s, f)
        d = NZ.diagnostics(rows, ["volatility", "trend_slope"])
        self.assertIsNotNone(d["prequential_corr_residual_volatility"])
        self.assertGreater(max(d["beta_drift_std"]), 0.1)

    def test_t64_t71_experiment_same_rows(self):
        td = TempData()
        try:
            import mq_instruments
            from test_structure_intelligence import m1_bars, write_export
            from masterquo.lab import structure_task as T
            ds = write_export(mq_instruments.data_dir() / "e", m1_bars(2600))
            T.save_dataset("XAUUSD", T.build_move_dataset("XAUUSD", ds, log=lambda *a: None))
            rep = T.train_experiment("XAUUSD", T.latest_dataset("XAUUSD", T.TASK_MOVE), "MQ_NEUTRAL_REACTION_V1", ["LOGREG"], "quick", log=lambda *a: None)
            self.assertEqual(set(rep["variants"]), {"RAW_FILTER", "NEUTRAL_FILTER", "RAW_PLUS_FACTORS"})
            self.assertGreaterEqual(rep["rows_rejected_warmup_or_failure"], 0)         # rejections reported (dataset warm-up 200 >= neutralizer warm-up)
            self.assertEqual(rep["rows"] + rep["rows_rejected_warmup_or_failure"], len(T.load_dataset(T.latest_dataset("XAUUSD", T.TASK_MOVE), T.TASK_MOVE)["rows_idx"]))
            self.assertEqual(rep["role"], "TEST_ONLY")
            q = T.train_experiment("XAUUSD", T.latest_dataset("XAUUSD", T.TASK_MOVE), "MQ_QUOTE_CONTEXT_REACTION_V1", ["LOGREG"], "quick")
            self.assertEqual(q["status"], "BLOCKED_NO_TICK_HISTORY")                 # T95: no ticks -> no fake training
        finally:
            td.close()

    def test_model_score_adapter(self):
        self.assertAlmostEqual(NZ.model_score(0.5, 0.25), math.log((0.5 + 1e-6) / (0.25 + 1e-6)))


if __name__ == "__main__":
    unittest.main()
