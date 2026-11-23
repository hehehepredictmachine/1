"""WF3.2 TASK 007 - Modular Indicator & Smoothing Engine: golden values from the spec, PMW_LEGACY_V1 == analytics.ta, MQL5 EMA source seed,
full == incremental, LWMA two-running-sums order, minimal-history lifecycle, alias, cache separation, applied price, no NaN."""
from __future__ import annotations

import math
import random
import time
import unittest

import _env  # noqa: F401


def bars_of(xs):
    return [{"t": i, "o": x, "h": x + 1, "l": x - 1, "c": x} for i, x in enumerate(xs)]


def approx(a, b, tol=1e-9):
    return len(a) == len(b) and all((x is None and y is None) or (x is not None and y is not None and abs(x - y) <= tol) for x, y in zip(a, b))


class TestGolden(unittest.TestCase):
    X = [1, 2, 3, 4, 5, 6]

    def calc(self, m, pol="PMW_LEGACY_V1", p=3):
        from masterquo.indicators import smoothing as SM
        return SM.full(SM.IndicatorSpec.make(m, p, policy=pol), self.X)

    def test_spec_golden_values(self):
        self.assertTrue(approx(self.calc("SMA"), [None, None, 2, 3, 4, 5]))
        self.assertTrue(approx(self.calc("EMA", "MQL5_STANDARD_V1"), [1, 1.5, 2.25, 3.125, 4.0625, 5.03125]))
        self.assertTrue(approx(self.calc("EMA"), [None, None, 2, 3, 4, 5]))
        self.assertTrue(approx(self.calc("SMMA"), [None, None, 2, 8 / 3, 31 / 9, 116 / 27]))
        self.assertTrue(approx(self.calc("LWMA"), [None, None, 7 / 3, 10 / 3, 13 / 3, 16 / 3]))

    def test_legacy_profile_equals_existing_analytics(self):
        from masterquo.analytics import ta
        from masterquo.indicators import smoothing as SM
        rnd = random.Random(7)
        xs = [2000 + rnd.gauss(0, 3) for _ in range(400)]
        for m, fn in (("SMA", ta.sma), ("EMA", ta.ema), ("WMA", ta.wma)):
            for p in (1, 5, 21, 200):
                self.assertTrue(approx(SM.full(SM.IndicatorSpec.make(m, p), xs), fn(xs, p), 1e-9), (m, p))

    def test_ema_seed_policies_differ_and_never_share_hash(self):
        from masterquo.indicators import smoothing as SM
        a = SM.IndicatorSpec.make("EMA", 10, policy="PMW_LEGACY_V1")
        b = SM.IndicatorSpec.make("EMA", 10, policy="MQL5_STANDARD_V1")
        self.assertNotEqual(a.config_hash, b.config_hash)
        self.assertNotEqual(a.algorithm_version, b.algorithm_version)
        self.assertEqual((a.seed_policy, b.seed_policy), ("PMW_EMA_SMA_SEED_V1", "MQL5_EMA_SOURCE_SEED_V1"))
        self.assertEqual((a.bars_required(), b.bars_required()), (10, 1))

    def test_alias_and_period_clamp(self):
        from masterquo.indicators import smoothing as SM
        w = SM.IndicatorSpec.make("WMA", 7)
        l7 = SM.IndicatorSpec.make("LWMA", 7)
        self.assertEqual((w.method, w.raw_method, w.config_hash), ("LWMA", "WMA", l7.config_hash))
        s = SM.IndicatorSpec.make("SMA", 1, policy="MQL5_STANDARD_V1")
        self.assertEqual(s.period, 2)
        self.assertTrue(s.warnings)
        self.assertEqual(SM.IndicatorSpec.make("SMA", 1).period, 1)                # legacy consumers keep period 1
        for bad in (("HMA", 5), ("SMA", 0), ("SMA", "x")):
            with self.assertRaises(SM.SpecError):
                SM.IndicatorSpec.make(*bad)


class TestIncremental(unittest.TestCase):
    def test_full_equals_incremental_all_methods_and_policies(self):
        from masterquo.indicators import smoothing as SM
        rnd = random.Random(11)
        xs = [100 + rnd.gauss(0, 1) * 5 for _ in range(300)] + [50.0] * 20 + [i * 0.5 for i in range(40)]
        for m in SM.METHODS:
            for pol in ("PMW_LEGACY_V1", "MQL5_STANDARD_V1"):
                for p in (2, 3, 14, 50):
                    sp = SM.IndicatorSpec.make(m, p, policy=pol)
                    st = SM.SmoothingState(sp)
                    inc = [st.commit(x) for x in xs]
                    self.assertTrue(approx(inc, SM.full(sp, xs), 1e-7), (m, pol, p))

    def test_lwma_update_order_matters(self):
        P, xs = 4, [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
        W = sum((k + 1) * xs[k] for k in range(P))
        S = sum(xs[:P])
        good, bad = [], []
        Wb, Sb = W, S
        for i in range(P, len(xs)):
            W = W - S + P * xs[i]
            S = S - xs[i - P] + xs[i]
            good.append(W / (P * (P + 1) / 2))
            Sb = Sb - xs[i - P] + xs[i]
            Wb = Wb - Sb + P * xs[i]                      # wrong order
            bad.append(Wb / (P * (P + 1) / 2))
        naive = [sum(xs[i - P + 1 + k] * (k + 1) for k in range(P)) / (P * (P + 1) / 2) for i in range(P, len(xs))]
        self.assertTrue(approx(good, naive, 1e-12))
        self.assertFalse(approx(bad, naive, 1e-12))

    def test_preview_does_not_commit(self):
        from masterquo.indicators import smoothing as SM
        st = SM.SmoothingState(SM.IndicatorSpec.make("EMA", 3, policy="MQL5_STANDARD_V1"))
        for x in (1, 2, 3):
            st.commit(x)
        p1, p2 = st.preview(10), st.preview(10)
        self.assertEqual(p1, p2)
        self.assertEqual(len(st.committed), 3)
        self.assertEqual(st.commit(10), p1)


class TestEngineLifecycle(unittest.TestCase):
    def test_minimal_history_second_call_no_error_and_warmup(self):
        from masterquo.indicators import smoothing as SM
        eng = SM.IndicatorEngine()
        sp = SM.IndicatorSpec.make("SMA", 5)
        self.assertEqual(eng.calculate(sp, bars_of([1, 2, 3]))["status"], "WARMUP")
        r1 = eng.calculate(sp, bars_of([1, 2, 3, 4, 5]))
        r2 = eng.calculate(sp, bars_of([1, 2, 3, 4, 5]))            # delta 0 - the CSma regression case
        self.assertEqual(r1["values"], r2["values"])
        self.assertEqual(r2["values"][4], 3.0)
        self.assertEqual(r2["valid_from"], 4)
        self.assertEqual(eng.calculate(sp, [])["status"], "NO_DATA")

    def test_incremental_append_then_revision_and_shrink_replay(self):
        from masterquo.indicators import smoothing as SM
        eng = SM.IndicatorEngine()
        sp = SM.IndicatorSpec.make("SMMA", 3, policy="MQL5_STANDARD_V1")
        xs = [float(i % 7) for i in range(50)]
        eng.calculate(sp, bars_of(xs[:40]), revision=1)
        r = eng.calculate(sp, bars_of(xs), revision=1)
        self.assertEqual(r["calc_mode"], "INCREMENTAL")
        self.assertTrue(approx(r["values"], SM.full(sp, xs)))
        xs2 = list(xs)
        xs2[10] += 5                                                   # history correction -> full replay
        r = eng.calculate(sp, bars_of(xs2), revision=2)
        self.assertEqual(r["calc_mode"], "FULL")
        self.assertTrue(approx(r["values"], SM.full(sp, xs2)))
        r = eng.calculate(sp, bars_of(xs2[:30]), revision=2)            # history shrink -> full replay
        self.assertEqual((r["calc_mode"], len(r["values"])), ("FULL", 30))

    def test_forming_bar_ignored_and_applied_prices(self):
        from masterquo.indicators import smoothing as SM
        b = {"o": 1.0, "h": 4.0, "l": 0.0, "c": 3.0}
        self.assertEqual([SM.applied_price(b, k) for k in SM.APPLIED], [1.0, 4.0, 0.0, 3.0, 2.0, 7 / 3, 2.5])
        eng = SM.IndicatorEngine()
        bs = bars_of([1, 2, 3, 4]) + [{"t": 9, "o": 100, "h": 100, "l": 100, "c": 100, "forming": True}]
        r = eng.calculate(SM.IndicatorSpec.make("SMA", 2), bs)
        self.assertEqual(r["values"], [None, 1.5, 2.5, 3.5])

    def test_cache_keys_separate_and_non_finite_rejected(self):
        from masterquo.indicators import smoothing as SM
        keys = {SM.IndicatorEngine.key(SM.IndicatorSpec.make(m, p, a, pol, inst, tf))
                for m in ("SMA", "EMA") for p in (5, 6) for a in ("CLOSE", "TYPICAL") for pol in ("PMW_LEGACY_V1", "MQL5_STANDARD_V1")
                for inst in ("XAUUSD", "EURUSD") for tf in ("M5", "H1")}
        self.assertEqual(len(keys), 64)
        r = SM.IndicatorEngine().calculate(SM.IndicatorSpec.make("SMA", 2), [{"t": 0, "o": 1, "h": 1, "l": 1, "c": float("nan")}])
        self.assertEqual(r["status"], "ERROR")

    def test_lab_profiles_reuse_rolling_ma(self):
        from masterquo.indicators import smoothing as SM
        from masterquo.lab.flow_context.ma import ma_series
        xs = [float(i) for i in range(30)]
        got = SM.full(SM.IndicatorSpec.make("LWMA", 5, policy="LAB_PARTIAL_PREFIX_V1"), xs)
        self.assertTrue(approx(got, [None if v is None else float(v) for v in ma_series(xs, "LWMA", 5, "PARTIAL_PREFIX_V1")]))

    def test_incremental_is_o1_per_bar(self):
        from masterquo.indicators import smoothing as SM
        xs = [math.sin(i / 10) for i in range(100_000)]
        t0 = time.perf_counter()
        st = SM.SmoothingState(SM.IndicatorSpec.make("LWMA", 1000))
        for x in xs:
            st.commit(x)
        self.assertLess(time.perf_counter() - t0, 6.0)                 # naive O(N*P) would be ~1e8 operations


if __name__ == "__main__":
    unittest.main()
