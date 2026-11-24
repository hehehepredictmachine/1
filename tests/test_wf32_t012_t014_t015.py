"""WF3.2 TASK 012 (long-horizon distribution), TASK 014 (ROI Strategy Tracker), TASK 015 (floored Gaussian PELT)."""
from __future__ import annotations

import math
import random
import unittest

import _env  # noqa: F401


def brute(r, m, beta=None):
    """Independent exact DP over every legal predecessor (reference)."""
    n = len(r)
    mu = sum(r) / n
    va = sum((x - mu) ** 2 for x in r) / n
    eps = 1e-8 * va
    beta = 2 * math.log(n) if not beta else beta

    def C(s, e):
        seg = r[s:e]
        mm = sum(seg) / len(seg)
        v = sum((x - mm) ** 2 for x in seg) / len(seg)
        return (e - s) * math.log(max(v, eps))
    F = [math.inf] * (n + 1)
    P = [-1] * (n + 1)
    F[0] = -beta
    for t in range(m, n + 1):
        for tau in [0] + list(range(m, t - m + 1)):
            if F[tau] < math.inf:
                v = F[tau] + C(tau, t) + beta
                if v < F[t] - 1e-12:
                    F[t], P[t] = v, tau
    cps, t = [], n
    while t > 0:
        if P[t] > 0:
            cps.append(P[t])
        t = P[t]
    return sorted(cps), F[n]


class TestPELT(unittest.TestCase):
    def series(self, seed, regimes=((0, 0.01, 120), (0.002, 0.03, 100), (-0.001, 0.005, 140))):
        rnd = random.Random(seed)
        return [rnd.gauss(m, s) for m, s, n in regimes for _ in range(n)]

    def test_guarded_pelt_equals_bruteforce(self):
        from masterquo.lab.change_points import pelt as P
        for seed in range(6):
            r = self.series(seed)
            for m in (5, 10):
                res = P.solve(r, m)
                ref_cps, ref_obj = brute(r, m)
                self.assertEqual(res["change_points"], ref_cps, (seed, m))
                self.assertAlmostEqual(res["objective"], ref_obj, places=6)
                self.assertTrue(res["pruning_guard_passed"] and res["pruning_used"] and res["exact_solver"])

    def test_recovers_variance_change(self):
        from masterquo.lab.change_points import pelt as P
        res = P.solve(self.series(42), 10)
        self.assertTrue(any(abs(c - 120) <= 5 for c in res["change_points"]))
        self.assertTrue(any(abs(c - 220) <= 5 for c in res["change_points"]))

    def test_floor_binding_disables_pruning_and_stays_exact(self):
        from masterquo.lab.change_points import pelt as P
        rnd = random.Random(1)
        r = [0.0] * 30 + [rnd.gauss(0, 0.01) for _ in range(60)] + [0.0] * 30          # flat runs bind the epsilon floor
        res = P.solve(r, 10)
        self.assertFalse(res["pruning_guard_passed"])
        self.assertFalse(res["pruning_used"])
        self.assertEqual(res["pruning_disabled_reason"], "GUARD_FAILED")
        self.assertEqual(res["change_points"], brute(r, 10)[0])

    def test_deferred_vs_immediate_pruning(self):
        from masterquo.lab.change_points import pelt as P
        mism = 0
        for seed in range(40):
            r = self.series(seed, ((0, 0.01, 25), (0, 0.04, 12), (0, 0.01, 25)))
            ref = brute(r, 10)[0]
            self.assertEqual(P.solve(r, 10, use_pruning=True, deferred=True)["change_points"], ref, seed)
            mism += P.solve(r, 10, use_pruning=True, deferred=False)["change_points"] != ref
        self.assertGreaterEqual(mism, 0)                     # immediate pruning is not relied on (kept only as a diagnostic path)

    def test_edge_statuses_and_sensitivity(self):
        from masterquo.lab.change_points import pelt as P
        self.assertEqual(P.solve([0.1] * 50, 10)["status"], "ZERO_GLOBAL_VARIANCE")
        self.assertEqual(P.solve([0.1, 0.2] * 5, 10)["status"], "INSUFFICIENT_DATA")
        self.assertEqual(P.solve([0.1, 0.2] * 50, 1)["status"], "INVALID_MIN_SEGMENT")
        rnd = random.Random(9)
        closes = [100.0]
        for s in [0.002] * 300 + [0.01] * 300:
            closes.append(closes[-1] * math.exp(rnd.gauss(0, s)))
        d = P.detect(closes, lookback_returns=500, m=10, sensitivity=True)
        self.assertEqual(d["status"], "OK")
        for s in d["sensitivity"]:
            self.assertIn(s["robustness_label"], ("STABLE", "MIXED", "FRAGILE"))
            self.assertLessEqual(s["support_count"], s["eligible_runs"])
        self.assertIn("nie prawdopodobieństwo", d["sensitivity_note"])


class TestStrategyROI(unittest.TestCase):
    def rows(self):
        base = {"strategy_id": "FX_SMC_01", "version": "1", "config_hash": "h", "market": "FOREX", "instrument": "XAUUSD", "venue": "MT5",
                "timeframe": "M5", "environment": "PAPER", "account": "a", "currency": "USD", "source": "BASKET", "status": "CLOSED"}
        out = []
        for i, (pnl, r) in enumerate([(100, 1.0), (-50, -0.5), (2, 0.02), (80, 0.8), (-60, -0.6)]):
            out.append({**base, "net_pnl": pnl, "r_multiple": r, "commission": -1, "swap": 0, "initial_risk": 100, "closed_at": f"2025-01-0{i + 1}"})
        return base, out

    def test_metrics_definitions(self):
        from masterquo.evaluation import strategy_roi as SR
        base, rows = self.rows()
        rep = SR.report(rows)
        it = rep["items"][0]
        self.assertEqual((it["wins"], it["losses"], it["breakeven"]), (2, 2, 1))
        self.assertEqual(it["win_rate"], 50.0)
        self.assertEqual(it["win_rate_all_closed"], 40.0)
        self.assertEqual(it["profit_factor"], round(182 / 110, 2))               # all positive net outcomes (incl. the +2 BE row)
        self.assertAlmostEqual(it["return_on_risk_pct"], 100 * 72 / 500)
        self.assertEqual((it["strategy_roi_pct"], it["strategy_roi_status"]), (None, "NO_CAPITAL_BASE"))
        self.assertEqual(it["sample_status"], "SMALL_SAMPLE")
        lo, hi = it["win_rate_ci95"]
        self.assertTrue(0 < lo < 0.5 < hi < 1)

    def test_capital_base_modified_dietz_and_scope_isolation(self):
        from masterquo.evaluation import strategy_roi as SR
        base, rows = self.rows()
        m = SR.metrics(rows, {"start_equity": 10_000, "flows": [(5_000, 0.5)]})
        self.assertAlmostEqual(m["strategy_roi_pct"], round(100 * 72 / (10_000 + 2_500), 3))
        mixed = rows + [{**r, "environment": "AUTO_LIVE"} for r in rows] + [{**rows[0], "status": "OPEN_PARTIAL"}, {**rows[0], "strategy_id": None},
                                                                             {**rows[0], "strategy_id": "OTC_SMC_01"}, {**rows[0], "environment": "??"}]
        rep = SR.report(mixed)
        self.assertEqual(len(rep["items"]), 2)                                   # PAPER and AUTO_LIVE never merged
        self.assertEqual(rep["excluded"]["OPEN_PARTIAL"], 1)
        self.assertEqual(rep["excluded"]["UNATTRIBUTED"], 1)
        self.assertEqual(rep["excluded"]["UNKNOWN_ENVIRONMENT"], 1)
        self.assertEqual(len(rep["retired_scope"]), 1)                           # retired OTC kept separately
        self.assertNotIn("OTC_SMC_01", [i["scope"]["strategy_id"] for i in rep["items"]])
        self.assertEqual(SR.metrics([])["sample_status"], "NO_DATA")


class TestLongHorizon(unittest.TestCase):
    def path(self, n=24 * 400, seed=2):
        rnd = random.Random(seed)
        ts, px, p = [], [], 100.0
        for i in range(n):
            ts.append(1_700_000_000 + i * 3600)
            p *= math.exp(rnd.gauss(0.0001, 0.004))
            px.append(p)
        return ts, px

    def test_distribution_contract_and_no_future(self):
        from masterquo.forecast import long_horizon as LH
        ts, px = self.path()
        f = LH.forecast(ts, px, "24h")
        self.assertEqual(f["status"], "OK")
        q = [f["log_return_quantiles"][k] for k in ("q05", "q10", "q25", "q50", "q75", "q90", "q95")]
        self.assertEqual(q, sorted(q))
        self.assertAlmostEqual(f["p_down"] + f["p_flat"] + f["p_up"], 1.0)
        self.assertIn(f["calibration"], ("CALIBRATED", "UNCALIBRATED"))
        cut = ts[len(ts) // 2]
        a = LH.forecast(ts, px, "48h", as_of=cut)
        px2 = px[: len(ts) // 2 + 1] + [x * 5 for x in px[len(ts) // 2 + 1:]]
        b = LH.forecast(ts, px2, "48h", as_of=cut)
        self.assertEqual(a["log_return_quantiles"], b["log_return_quantiles"])  # data after as_of is never read

    def test_exact_elapsed_horizon_and_gaps(self):
        from masterquo.forecast import long_horizon as LH
        ts = [0, 3600, 7200, 86400 + 1800, 90000]
        px = [100, 101, 102, 110, 111]
        r = LH.direct_returns(ts, px, 86400, max_fill_s=3600)
        self.assertEqual([round(t) for t, _ in r], [0, 3600])                    # 0 -> first obs >= 86400 is 88200 (within 1 h)
        self.assertAlmostEqual(r[0][1], math.log(110 / 100))
        self.assertEqual([t for t, _ in LH.direct_returns(ts, px, 86400, max_fill_s=600)], [3600])   # t=0: 1800 s late > 600 -> excluded
        self.assertEqual(LH.forecast(ts, px, "24h")["status"], "UNAVAILABLE")
        with self.assertRaises(ValueError):
            LH.forecast(ts, px, "12h")


if __name__ == "__main__":
    unittest.main()
