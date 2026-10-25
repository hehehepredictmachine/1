"""PMW-MM master models - unit tests of the mathematics and contracts (independent oracles: hand values, numpy/scipy, brute force)."""
from __future__ import annotations

import math
import unittest

import _env  # noqa: F401
import numpy as np

from masterquo.mm import align_mean as AM
from masterquo.mm import breakout_zones as BZ
from masterquo.mm import buzoa as BU
from masterquo.mm import contracts as CT
from masterquo.mm import events as EV
from masterquo.mm import gpr as G
from masterquo.mm import hdc as H
from masterquo.mm import kalman as K
from masterquo.mm import mathbench as MB
from masterquo.mm import multi_indicator as MI
from masterquo.mm import robust_vol as RV
from masterquo.mm import smc_fvg as SF
from masterquo.mm import splits as SP
from masterquo.mm import stfs as STF
from masterquo.mm import ste_flownet as STE
from masterquo.mm import tsvp as TV
from masterquo.mm.data import Bars
from masterquo.lab import autodiff as A


def bars_from(c, tf=300, spread=10.0, start=1_790_000_000.0):
    c = np.asarray(c, float)
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + 0.05
    lo = np.minimum(o, c) - 0.05
    t = start + tf * np.arange(len(c))
    return Bars("M5", t, o, h, lo, c, np.full(len(c), 100.0), np.full(len(c), spread))


def walk(n=3000, seed=1, base=2300.0, sd=0.6):
    g = np.random.default_rng(seed)
    return base + np.cumsum(g.normal(0, sd, n))


class TestContracts(unittest.TestCase):
    def test_envelope_and_output(self):
        e = CT.Envelope("x", "XAUUSD", "M5", 100.0, 400.0)
        self.assertTrue(e.event_id)
        with self.assertRaises(ValueError):
            CT.Envelope("x", "XAUUSD", "M5", 400.0, 100.0)              # cannot be available before the observation
        with self.assertRaises(ValueError):
            CT.ModelOutput(e, "RULE_SIGNAL", {}, execution_allowed=True)
        self.assertFalse(CT.ModelOutput(e, "RULE_SIGNAL", {}).to_dict()["execution_allowed"])


class TestSplits(unittest.TestCase):
    def test_purge_embargo_and_guard(self):
        t = np.arange(1000.0)
        sp = SP.chrono_split(t, t + 12, (0.6, 0.2, 0.2), embargo_s=5)
        SP.assert_no_overlap(sp, t, t + 12)
        self.assertGreater(sp["purged"], 0)
        g = SP.HoldoutGuard(sp["test"])
        g.open({"m": 1})
        with self.assertRaises(RuntimeError):
            g.open({"m": 2})
        with self.assertRaises(ValueError):
            SP.chrono_split(t, t - 1)


class TestKalman(unittest.TestCase):
    def test_equations_by_hand(self):
        f = K.LocalLevel(1.0, 0.2, 1.0)
        self.assertEqual(f.step(100.0)["status"], "INITIALIZED")            # init: no measurement update on the same observation
        r = f.step(101.0)
        P_pred = 1.0 + 1.0
        Kt = P_pred / (P_pred + 0.2)
        self.assertAlmostEqual(r["P_pred"], P_pred)
        self.assertAlmostEqual(r["K"], Kt)
        self.assertAlmostEqual(r["x"], 100.0 + Kt * 1.0)
        self.assertAlmostEqual(r["P"], (1 - Kt) * P_pred)

    def test_steady_state_gains(self):
        for Q, ref in ((1.0, 0.854), (0.005, 0.146)):
            f = K.LocalLevel(Q, 0.2, 1.0)
            f.step(10.0)
            for _ in range(500):
                f.step(10.0)
            self.assertAlmostEqual(f.K, ref, places=3)
            self.assertAlmostEqual(f.K, K.steady_state_gain(Q, 0.2), places=12)

    def test_invalid_and_independence(self):
        with self.assertRaises(ValueError):
            K.LocalLevel(-1, 0.2)
        f = K.LocalLevel(1, 0.2)
        f.step(5.0)
        x0 = f.x
        self.assertEqual(f.step(float("nan"))["status"], "INVALID_INPUT")
        self.assertEqual(f.x, x0)                                            # invalid input does not poison the state
        kc = K.KalmanCross()
        self.assertIsNot(kc.fast, kc.slow)

    def test_fast_responds_faster_and_once_per_bar(self):
        kc = K.KalmanCross(K.CrossConfig(warmup_bars=1))
        for i in range(30):
            kc.update(i, 100.0)
        kc.update(30, 110.0)
        self.assertGreater(kc.fast.x - 100, kc.slow.x - 100)
        n = kc.fast.n
        self.assertFalse(kc.update(30, 111.0)["processed"])                  # same bar again: ignored
        self.assertEqual(kc.fast.n, n)

    def test_confirmation_and_no_startup_signal(self):
        c = np.r_[np.linspace(100, 110, 60), np.linspace(110, 95, 60), np.linspace(95, 112, 60)]
        k, _ = K.run(np.arange(len(c)), c, K.CrossConfig(confirm_bars=2, warmup_bars=5))
        dirs = [e["direction"] for e in k.events]
        self.assertTrue(dirs)
        self.assertTrue(all(a != b for a, b in zip(dirs, dirs[1:])))          # one event per transition
        self.assertNotEqual(k.events[0]["bar_time"], 5)                      # no event at the warm-up boundary (baseline is silent)
        k2, _ = K.run(np.arange(len(c)), c, K.CrossConfig(confirm_bars=2, warmup_bars=5))
        self.assertEqual(k.events, k2.events)                                # deterministic replay


class TestAlignMean(unittest.TestCase):
    def test_sources_and_modes(self):
        h, lo, c = np.array([12.0]), np.array([8.0]), np.array([11.0])
        self.assertEqual(AM.price("TYPICAL", h, lo, c)[0], (12 + 8 + 11) / 3)
        self.assertEqual(AM.price("MEDIAN", h, lo, c)[0], 10.0)
        self.assertEqual(AM.price("WEIGHTED_CLOSE", h, lo, c)[0], (12 + 8 + 22) / 4)
        b = bars_from(walk(600))
        r = AM.compute(b.t, b.o, b.h, b.l, b.c, 300, AM.AlignConfig(mode="ROLLING_MEAN", source="CLOSE", lookback="BARS", bars=10), 0.01)
        self.assertTrue(np.isnan(r["mean"][8]))
        self.assertAlmostEqual(r["mean"][20], b.c[11:21].mean())
        rt = AM.compute(b.t, b.o, b.h, b.l, b.c, 300, AM.AlignConfig(mode="ROLLING_MEAN", source="CLOSE", lookback="ELAPSED_TIME", seconds=3000), 0.01)
        self.assertAlmostEqual(rt["mean"][20], b.c[11:21].mean())            # 3000 s on M5 = 10 bars by timestamps
        with self.assertRaises(ValueError):
            AM.AlignConfig(mode="SESSION_MEAN", lookback="BARS").validate()

    def test_fixed_anchor_frozen_until_session_reset(self):
        b = bars_from(walk(900), start=1_790_000_100.0)
        r = AM.compute(b.t, b.o, b.h, b.l, b.c, 300, AM.AlignConfig(mode="FIXED_ANCHORED_MEAN", lookback="SESSION"), 0.01)
        sid = r["session"]
        for s in np.unique(sid):
            v = r["mean"][sid == s]
            v = v[np.isfinite(v)]
            self.assertTrue(np.all(v == v[0]))

    def test_normalisation_status(self):
        b = bars_from(walk(100))
        r = AM.compute(b.t, b.o, b.h, b.l, b.c, 300, AM.AlignConfig(lookback="BARS", bars=200), 0.01)
        self.assertEqual(AM.latest(r, "X", "M5")["status"], "NOT_READY")


class TestHDC(unittest.TestCase):
    def setUp(self):
        self.sp = H.Space(1000, seed=3)                                     # 1000 is not a multiple of 64: padding bits exercised

    def test_bind_properties(self):
        a, b, c = (self.sp.random(s) for s in (1, 2, 3))
        z = self.sp.bind(a, a)
        self.assertEqual(self.sp.hamming(z, np.zeros_like(z)), 0)
        self.assertEqual(self.sp.hamming(self.sp.bind(self.sp.bind(a, b), b), a), 0)
        self.assertEqual(self.sp.hamming(self.sp.bind(a, c), self.sp.bind(b, c)), self.sp.hamming(a, b))
        self.assertEqual(int(a[-1] & ~self.sp.mask[-1]), 0)

    def test_permute(self):
        a = self.sp.random(5)
        bits = self.sp.to_bits(a)
        for k in (0, 1, 63, 64, 65, 999, 1000, -7, 2500):
            p = self.sp.permute(a, k)
            self.assertTrue(np.array_equal(self.sp.to_bits(p), np.roll(bits, k % 1000)))   # whole D-bit rotation, word boundaries crossed
            self.assertEqual(self.sp.hamming(self.sp.permute(p, -k), a), 0)
            self.assertEqual(int(p[-1] & ~self.sp.mask[-1]), 0)

    def test_bundle_ties_and_errors(self):
        a, b = self.sp.random(10), self.sp.random(11)
        with self.assertRaises(ValueError):
            self.sp.bundle([])
        self.assertEqual(self.sp.hamming(self.sp.bundle([a]), a), 0)
        two = self.sp.bundle([a, b])
        tie = self.sp.to_bits(self.sp.tie)
        ba, bb, bt = self.sp.to_bits(a), self.sp.to_bits(b), self.sp.to_bits(two)
        agree = ba == bb
        self.assertTrue(np.array_equal(bt[agree], ba[agree]))
        self.assertTrue(np.array_equal(bt[~agree], tie[~agree]))              # ties -> the seeded tie vector
        self.assertTrue(np.array_equal(self.sp.bundle([a, b]), two))          # deterministic
        three = self.sp.bundle([a, a, b])
        self.assertEqual(self.sp.hamming(three, a), 0)

    def test_hamming_known_and_noise_floor(self):
        a = self.sp.random(1)
        bits = self.sp.to_bits(a).copy()
        bits[[0, 5, 999]] ^= 1
        self.assertEqual(self.sp.hamming(a, self.sp.from_bits(bits)), 3)
        self.assertAlmostEqual(self.sp.similarity(a, self.sp.from_bits(1 - self.sp.to_bits(a))), -1.0)
        sims = [H.Space(4096, 9).similarity(H.Space(4096, 9).random(i), H.Space(4096, 9).random(i + 777)) for i in range(150)]
        self.assertLess(abs(np.mean(sims)), 4 / math.sqrt(4096) / math.sqrt(150) * 3)
        self.assertAlmostEqual(np.std(sims), 1 / math.sqrt(4096), delta=0.006)
        self.assertAlmostEqual(self.sp.null()["similarity_sd"], 1 / math.sqrt(1000))

    def test_online_equals_rebuild_and_watermark(self):
        X = np.random.default_rng(0).normal(size=(200, 4))
        y = (X[:, 0] > 0).astype(int)
        enc = H.Encoder(self.sp, ["a", "b", "c", "d"], 8).fit(X[:150])
        V = [enc.record(x) for x in X]
        on, rb = H.Classifier(self.sp, 2), H.Classifier(self.sp, 2)
        for v, yy in zip(V, y):
            on.update(v, int(yy))
        rb.acc = np.sum([(self.sp.to_bits(v).astype(np.int32) * 2 - 1)[None] * np.eye(2, dtype=np.int32)[yy][:, None] for v, yy in zip(V, y)], axis=0)
        self.assertTrue(np.array_equal(on.acc, rb.acc))
        self.assertTrue(np.array_equal(on.finalize(), rb.finalize()))
        self.assertFalse(on.update(V[0], 1, label_available_at=200.0, watermark=100.0))     # immature label refused
        c2 = H.Classifier(self.sp, 2)
        c2.acc = on.acc.copy()
        n = c2.correct(V, y, 1)
        self.assertEqual(c2.corrections, n)                                   # corrections are a separate, counted stage
        with self.assertRaises(RuntimeError):
            H.Encoder(self.sp, ["a"], 4).quantize(np.array([1.0]))           # quantiser must be fitted (on train only)


class TestSMC(unittest.TestCase):
    def test_mirror_and_contracts(self):
        c = walk(2500, seed=5)
        b = bars_from(c)
        e1 = SF.run(b, SF.SMCFVGConfig(), 300)
        mb = Bars("M5", b.t, 2 * 2300 - b.o, 2 * 2300 - b.l, 2 * 2300 - b.h, 2 * 2300 - b.c, b.tv, b.spread)
        e2 = SF.run(mb, SF.SMCFVGConfig(), 300)
        L1 = sorted(s["entry"]["bar"] for s in e1.setups.values() if s["state"] == "ENTRY_TOUCH_CONFIRMED" and s["direction"] == "LONG")
        S2 = sorted(s["entry"]["bar"] for s in e2.setups.values() if s["state"] == "ENTRY_TOUCH_CONFIRMED" and s["direction"] == "SHORT")
        self.assertEqual(L1, S2)                                              # exact directional mirror
        for s in e1.setups.values():
            if s["state"] == "ENTRY_TOUCH_CONFIRMED":
                en = s["entry"]
                sg = 1 if s["direction"] == "LONG" else -1
                self.assertGreaterEqual(en["depth"], 0.73 - 1e-12)
                self.assertAlmostEqual(en["target"], en["entry"] + sg * 2 * en["R"])
                self.assertGreater(en["R"], 0)
                self.assertGreater(en["bar"], s["B"]["confirm_bar"])           # touch only after B is known (no look-ahead)
                self.assertTrue(all(g["bar"] <= s["bos"]["bar"] for g in s["gaps"]))   # gaps frozen at the BoS bar
                self.assertFalse(s["execution_allowed"])
        with self.assertRaises(ValueError):
            SF.SMCFVGConfig(depth_min=0.5).validate()                          # 50% only through the explicit profile
        SF.SMCFVGConfig(depth_min=0.5, profile="DIAGRAM_50_UNRESOLVED").validate()

    def test_no_lookahead_prefix(self):
        b = bars_from(walk(1500, seed=8))
        full = SF.run(b, SF.SMCFVGConfig(), 300)
        part = SF.run(b.slice(0, 1000), SF.SMCFVGConfig(), 300)
        ev_full = [e["event_id"] for e in full.events if e["bar"] < 1000]
        self.assertEqual(ev_full, [e["event_id"] for e in part.events])      # events up to bar t do not depend on later bars


class TestBreakoutAndVol(unittest.TestCase):
    def test_wick_only_and_min_touches(self):
        cfg = BZ.BreakoutConfig(left=2, right=2, min_sep=1, prominence_atr=0.0, min_touches=2, confirmation="NONE", atr_period=3, tol_atr=0.5, pad_atr=0.0)
        e = BZ.Engine(cfg, 0.01, 300)
        path = [100, 101, 103, 101, 100, 99, 100, 101, 103.02, 101, 100, 99, 100, 101, 102, 102.5]
        t = 0
        for p in path:
            e.update(t, p, p + 0.1 if p != 103 and p != 103.02 else p, p - 0.1, p, 10)
            t += 300
        z = [x for x in e.zones if x["kind"] == "RES"]
        self.assertTrue(any(x["state"] == "QUALIFIED_RESISTANCE" for x in z))
        n_before = len(e.events)
        e.update(t, 102.9, 104.0, 102.8, 102.95, 10)                           # wick above, close inside: no breakout
        self.assertEqual(len(e.events), n_before)
        e.update(t + 300, 103.0, 104.5, 103.0, 104.4, 10)                       # close above the upper bound
        self.assertEqual(len(e.events), n_before + 1)
        self.assertEqual(e.panel()["direction"], "BULLISH")
        e.update(t + 600, 104.4, 105, 104.3, 104.9, 10)
        self.assertEqual(len(e.events), n_before + 1)                          # zone consumed: no repeated signal
        e.update(t + 600, 104.4, 105, 104.3, 104.9, 10)                        # replayed bar: ignored

    def test_filter_not_ready_rejects(self):
        b = bars_from(walk(400, seed=3))
        ev = BZ.evaluate(b, BZ.BreakoutConfig(confirmation="SMA", sma_period=10_000), 0.01, 300)
        self.assertEqual(ev["accepted"], 0)
        self.assertEqual(ev["rejected"], ev["rejected_by_reason"]["FILTER_NOT_READY"])

    def test_robust_vol_counterexample_and_outlier(self):
        cfg = RV.RobustVolConfig(clip=False, min_samples=5)
        up = np.linspace(100, 110, 30)
        a, b = RV.window_stat(up, cfg), RV.window_stat(up[::-1], cfg)
        self.assertAlmostEqual(a["sorted_dispersion"], b["sorted_dispersion"])   # sorting is direction-blind ...
        self.assertGreater(a["path"], 0)
        self.assertLess(b["path"], 0)                                          # ... the separate path statistic keeps the sign
        self.assertNotAlmostEqual(a["time_aware_dispersion"], RV.window_stat(np.r_[up[::2], up[1::2]], cfg)["time_aware_dispersion"])
        self.assertEqual(RV.window_stat(np.array([1.0, 2.0]), cfg)["status"], "INSUFFICIENT_SAMPLES")
        self.assertEqual(RV.window_stat(np.r_[up[:-1], -1.0], cfg)["status"], "INVALID_INPUT")
        flat = RV.window_stat(np.full(30, 100.0), cfg)
        self.assertEqual(flat["sorted_dispersion"], 0.0)
        self.assertIn("FLAT_WINDOW", flat["flags"])
        x = walk(48, seed=2)
        y = x.copy()
        y[20] *= 1.2
        c1 = RV.RobustVolConfig(clip=True)
        self.assertLess(abs(RV.window_stat(y, c1)["sorted_dispersion"] - RV.window_stat(x, c1)["sorted_dispersion"]),
                        abs(np.std(np.diff(np.log(y))) - np.std(np.diff(np.log(x)))))


class TestMultiIndicator(unittest.TestCase):
    def test_indicator_references(self):
        g = np.random.default_rng(3)
        c = 100 + np.cumsum(g.normal(0, 1, 200))
        o = np.r_[c[0], c[:-1]]
        h, lo = np.maximum(o, c) + 0.3, np.minimum(o, c) - 0.3
        ho, hh, hl, hc = MI.heikin_ashi(o, h, lo, c)
        self.assertAlmostEqual(hc[10], (o[10] + h[10] + lo[10] + c[10]) / 4)
        self.assertAlmostEqual(ho[10], (ho[9] + hc[9]) / 2)
        w = MI.williams_r(h, lo, c, 14)
        i = 50
        self.assertAlmostEqual(w[i], -100 * (h[i - 13:i + 1].max() - c[i]) / (h[i - 13:i + 1].max() - lo[i - 13:i + 1].min()))
        self.assertTrue(np.nanmin(w) >= -100 and np.nanmax(w) <= 0)
        cc = MI.cci(h, lo, c, 20)
        tp = (h + lo + c) / 3
        win = tp[i - 19:i + 1]
        self.assertAlmostEqual(cc[i], (tp[i] - win.mean()) / (0.015 * np.abs(win - win.mean()).mean()))
        k, d = MI.stochastic(h, lo, c, 5, 3, 3)
        num = sum(c[j] - lo[j - 4:j + 1].min() for j in range(i - 2, i + 1))
        den = sum(h[j - 4:j + 1].max() - lo[j - 4:j + 1].min() for j in range(i - 2, i + 1))
        self.assertAlmostEqual(k[i], 100 * num / den)
        self.assertAlmostEqual(d[i], k[i - 2:i + 1].mean())

    def test_decision_trace_and_mirror(self):
        b = bars_from(walk(800, seed=11))
        ind = MI.compute(b.o, b.h, b.l, b.c, MI.MIConfig())
        self.assertEqual(MI.evaluate_bar(ind, 3, MI.MIConfig())["status"], "NOT_READY")
        j = MI.journal(b, MI.MIConfig(), "X", "M5", 300)
        for r in j["rows"]:
            for side in ("LONG", "SHORT"):
                s = r["sides"][side]
                self.assertEqual(s["accepted"], not s["reasons"])
                if s["risk"]:
                    sg = 1 if side == "LONG" else -1
                    self.assertAlmostEqual(s["risk"]["target"], s["risk"]["entry_ref"] + sg * 2 * s["risk"]["R"])
            self.assertFalse(r["execution_allowed"])
        self.assertEqual(len({r["event_id"] for r in j["rows"]}), len(j["rows"]))   # deduplicated
        mb = Bars("M5", b.t, 2000 - b.o, 2000 - b.l, 2000 - b.h, 2000 - b.c, b.tv, b.spread)
        j2 = MI.journal(mb, MI.MIConfig(), "X", "M5", 300)
        self.assertGreater(j["accepted"] + j2["accepted"], 0)


class TestTSVP(unittest.TestCase):
    def ticks(self, n=3000, seed=4):
        g = np.random.default_rng(seed)
        bid = 2300 + np.cumsum(g.normal(0, 0.05, n)).round(2)
        ms = 1_790_000_000_000 + np.sort(g.integers(0, 3_600_000, n))
        ms[100:105] = ms[100]                                                  # several legitimate ticks in one ms
        return [{"time_msc": int(m), "bid": float(b), "ask": float(b + 0.12), "last": 0.0, "volume": 0, "volume_real": 0.0, "flags": 2} for m, b in zip(ms, bid)]

    def test_bucketing_and_hash(self):
        p = TV.Profile(TV.TSVPConfig(bucket_ticks=10, tick=0.01), 0, 10)
        self.assertEqual(p.key(100.0), 1000)
        self.assertEqual(p.key(100.0999), 1000)
        self.assertEqual(p.key(100.1), 1001)                                   # exact boundary belongs to the upper bucket
        m = TV.BucketMap(8)
        for k in range(-500, 500):
            m.add(k * 7919, 1.0)
        self.assertEqual(len(m.items()), 1000)
        self.assertGreater(m.rehashes, 0)
        self.assertTrue(all(v == 1.0 for _, v, _ in m.items()))

    def test_incremental_equals_rebuild_with_overlap(self):
        tk = self.ticks()
        cfg = TV.TSVPConfig(tick=0.01)
        s, e = tk[0]["time_msc"], tk[-1]["time_msc"]
        full = TV.rebuild(cfg, s, e, tk)
        inc = TV.Profile(cfg, s, e)
        k = 0
        while k < len(tk):
            inc.ingest(tk[max(0, k - 17):k + 97], read_until_ms=tk[min(len(tk) - 1, k + 97)]["time_msc"])
            k += 97
        self.assertEqual(full.map.items(), inc.map.items())
        self.assertEqual(full.poc, inc.poc)
        self.assertEqual(full.counted, len(tk))

    def test_modes_states_poc(self):
        tk = self.ticks(500)
        a = TV.Profile(TV.TSVPConfig(source="ACTUAL_TRADE_VOLUME", tick=0.01), tk[0]["time_msc"], tk[-1]["time_msc"])
        a.ingest(tk)
        self.assertEqual(a.summary()["status"], "ACTUAL_VOLUME_UNAVAILABLE")    # quote-only ticks never become traded volume
        p = TV.Profile(TV.TSVPConfig(tick=0.01), 0, 10 ** 15)
        p.request("FULL_REBUILD_REQUIRED")
        p.ingest([{"time_msc": 5, "bid": 100.0, "ask": 100.1, "flags": 2}])
        self.assertEqual(p.state, "FULL_REBUILD_REQUIRED")                      # a live tick never downgrades a pending rebuild
        p.render_pass()
        p.ingest([{"time_msc": 6, "bid": 100.0, "ask": 100.1, "flags": 2}])
        self.assertEqual(p.state, "FULL_REDRAW_REQUIRED")                       # new maximum -> full redraw
        p.render_pass()
        p.ingest([{"time_msc": 7, "bid": 101.0, "ask": 101.1, "flags": 2}])
        self.assertEqual(p.state, "PARTIAL_UPDATE_PENDING")
        self.assertEqual(p.render_pass()["draw"], [p.key(101.0)])
        r = TV.Profile(TV.TSVPConfig(tick=0.01, bucket_ticks=1), 0, 10 ** 15)
        r.ingest([{"time_msc": i + 1, "bid": 100.0 + 0.01 * i, "ask": 100.1 + 0.01 * i, "flags": 2} for i in range(25)])
        passes = [r.render_pass(rows_budget=10) for _ in range(3)]               # full redraw split over budgeted passes, no repeats
        self.assertEqual([len(x["draw"]) for x in passes], [10, 10, 5])
        self.assertEqual(len({k for x in passes for k in x["draw"]}), 25)
        self.assertEqual(r.state, "CLEAN")
        q = TV.Profile(TV.TSVPConfig(tick=0.01), 0, 10 ** 15)
        q.ingest([{"time_msc": 1, "bid": 101.0, "ask": 101.1, "flags": 2}, {"time_msc": 2, "bid": 100.0, "ask": 100.1, "flags": 2}])
        self.assertEqual(q.poc, q.key(100.0))                                   # tie -> lower price bucket


class TestBUZOA(unittest.TestCase):
    def test_bounds_modes_determinism(self):
        lb, ub = np.array([-5.0, 0.0, 10.0]), np.array([5.0, 1.0, 1000.0])
        seen = []

        def f(x):
            self.assertTrue(np.all(x >= lb) and np.all(x <= ub))
            seen.append(x.copy())
            return float(np.sum((x - (lb + ub) / 2) ** 2))
        r1 = BU.buzoa(f, lb, ub, BU.BuzoaConfig(max_evals=300, epochs=10 ** 6))
        r2 = BU.buzoa(f, lb, ub, BU.BuzoaConfig(max_evals=300, epochs=10 ** 6))
        self.assertEqual(r1["best_x"], r2["best_x"])
        self.assertEqual(r1["evaluations"], 300)
        self.assertEqual(r1["stop"], "MAX_EVALS")
        self.assertTrue(all(v > 0 for v in r1["mode_counts"].values()))
        self.assertAlmostEqual(r1["alpha1_final"], 0.9 * 0.99 ** r1["iterations"])
        conv = [v for v in r1["convergence"] if v is not None]
        self.assertTrue(all(b <= a + 1e-12 for a, b in zip(conv, conv[1:])))
        rmax = BU.buzoa(lambda x: -f(x), lb, ub, BU.BuzoaConfig(max_evals=300, direction="max", epochs=10 ** 6))
        self.assertLessEqual(rmax["best_f"], 0)
        with self.assertRaises(ValueError):
            BU.buzoa(f, ub, lb)

    def test_nan_objective_never_best(self):
        r = BU.buzoa(lambda x: float("nan") if x[0] > 0 else float(x[0] ** 2), [-1.0], [1.0], BU.BuzoaConfig(max_evals=200, epochs=10 ** 6))
        self.assertLessEqual(r["best_x"][0], 0)
        self.assertGreater(r["failed_evaluations"], 0)
        r = BU.buzoa(lambda x: float("nan"), [-1.0], [1.0], BU.BuzoaConfig(max_evals=50, epochs=10 ** 6))
        self.assertEqual(r["status"], "NO_VALID_EVALUATION")


class TestGPR(unittest.TestCase):
    def test_kernel_cholesky_lml_vs_scipy(self):
        x = np.array([0.0, 1.0, 2.5])
        K_ = G.matern32(x, x, 2.0, 1.5)
        s = math.sqrt(3) * 1.0 / 2.0
        self.assertAlmostEqual(K_[0, 1], 1.5 * (1 + s) * math.exp(-s))
        self.assertTrue(np.allclose(K_, K_.T))
        A_ = K_ + 0.1 * np.eye(3)
        L = G.cholesky_ref(A_)
        self.assertTrue(np.allclose(L @ L.T, A_))
        self.assertIsNone(G.cholesky_ref(np.array([[1.0, 2.0], [2.0, 1.0]])))
        g = np.random.default_rng(1)
        xx, yy = g.normal(size=40), g.normal(size=40)
        sc = G.score(xx, yy, 1.3, 0.7, 0.2, 1e-12)
        from scipy.stats import multivariate_normal
        xn, yn = (xx - xx.mean()) / xx.std(), (yy - yy.mean()) / yy.std()
        cov = G.matern32(xn, xn, 1.3, 0.7) + 0.2 * np.eye(40)
        self.assertAlmostEqual(sc["lml"], multivariate_normal(np.zeros(40), cov).logpdf(yn), places=8)

    def test_samples_indexing_and_variances(self):
        c = np.exp(np.cumsum(np.random.default_rng(2).normal(0, 0.001, 400))) * 2000
        x, y, k = G.samples(c, 300, 100, 3)
        self.assertEqual(k[-1], 297)                                            # last target ends exactly at the fit bar T
        self.assertAlmostEqual(x[-1], math.log(c[297] / c[296]))
        self.assertAlmostEqual(y[-1], math.log(c[300] / c[297]))
        self.assertIsNone(G.samples(c, 50, 100, 3))
        m = G.GPModel(G.GPRConfig(window=100, horizon=3))
        self.assertTrue(m.refit(c, 300, True)["ok"])
        p = m.predict(math.log(c[300] / c[299]), c[300])
        self.assertAlmostEqual(p["observed_var"] - p["latent_var"], m.fit.noise_var * m.fit.y_std ** 2)
        self.assertAlmostEqual(p["price"]["upper1"], c[300] * math.exp(p["mean_logret"] + p["sd"]))
        self.assertAlmostEqual(p["edge_price"], c[300] * (math.exp(p["mean_logret"]) - 1))

    def test_transactional_commit(self):
        c = np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.001, 400))) * 2000
        m = G.GPModel(G.GPRConfig(window=100))
        m.refit(c, 300, True)
        before = m.fit
        bad = c.copy()
        bad[250] = -1.0
        r = m.refit(bad, 300, True)
        self.assertFalse(r["ok"])
        self.assertIs(m.fit, before)                                            # failure leaves the committed fit untouched

    def test_calibration_counting_on_known_distribution(self):
        g = np.random.default_rng(4)
        rows = [{"pred": 0.0, "sd": 1.0, "real": float(v), "hist_mean": 0.0, "ols": 0.0, "jitter": 0.0, "hp": {"ell": 1}} for v in g.normal(size=4000)]
        cal = G.calibration(rows)
        self.assertAlmostEqual(cal["coverage_1sd"], 0.6827, delta=0.025)
        self.assertAlmostEqual(cal["coverage_2sd"], 0.9545, delta=0.015)


class TestEventsSTFS(unittest.TestCase):
    def test_ingestor(self):
        ing = EV.Ingestor("X", gap_reset_s=10)
        self.assertEqual(ing.push({"t": 1.0, "bid": 1.0, "ask": 1.1})["status"], "ACCEPTED")
        self.assertEqual(ing.push({"t": 1.0, "bid": 1.0, "ask": 1.1})["reason"], "DUPLICATE")
        self.assertEqual(ing.push({"t": 1.0, "bid": 1.01, "ask": 1.1})["status"], "ACCEPTED")    # same ms, different quote
        self.assertEqual(ing.push({"t": 0.5, "bid": 1.0, "ask": 1.1})["reason"], "LATE")
        self.assertEqual(ing.push({"t": 2.0, "bid": 1.2, "ask": 1.1})["reason"], "CROSSED")
        self.assertEqual(ing.push({"t": 2.0, "bid": float("nan"), "ask": 1.1})["reason"], "NON_FINITE")
        self.assertEqual(ing.push({"t": 30.0, "bid": 1.0, "ask": 1.1})["segment"], 1)              # gap -> new segment

    def test_stfs_zero_params_and_train_only(self):
        st = STF.STFS(k_time=3, n_subsets=2, seed=1)
        self.assertEqual(st.n_params, 0)
        H_ = A.T(np.random.default_rng(0).normal(size=(4, 6, 5)))
        self.assertIsNone(st.views(H_, np.ones((4, 6), bool), training=False))
        mask = np.ones((4, 6), bool)
        mask[0, 4:] = False
        v = st.views(H_, mask, training=True)
        self.assertFalse(st.last_meta["time_selected"][0, 4:].any())           # never samples invalid positions
        self.assertTrue(np.allclose(v["global"].data[1], H_.data[1].mean(axis=0)))
        self.assertTrue(np.allclose(v["global"].data[0], H_.data[0, :4].mean(axis=0)))
        loss = v["temporal"].sum() + v["feature"].sum()
        loss.backward()
        self.assertIsNotNone(H_.grad)                                           # gradients reach the upstream feature map

    def test_losses(self):
        lg = A.T(np.array([[2.0, 0.5, -1.0], [0.1, 0.2, 0.3]]))
        y = np.array([0, 2])
        ref = -np.mean([np.log(np.exp(r[k]) / np.exp(r).sum()) for r, k in zip(lg.data, y)])
        self.assertAlmostEqual(float(STF.label_smoothed_ce(lg, y, 0.0).data), ref)
        self.assertGreater(float(STF.label_smoothed_ce(lg, y, 0.2).data), ref - 1)
        E = A.T(np.random.default_rng(1).normal(size=(6, 4)))
        _, n = STF.triplet_batch_hard(E, np.array([0, 0, 0, 0, 0, 0]))
        self.assertEqual(n, 0)                                                   # no negatives -> no fabricated triplets
        tl, n = STF.triplet_batch_hard(E, np.array([0, 0, 1, 1, 2, 2]))
        self.assertEqual(n, 6)
        self.assertGreaterEqual(float(tl.data), 0.0)

    def test_state_stack_semantics(self):
        from masterquo.mm.event_engine import EventModel, StateStack
        s = StateStack(3, 2, backend="cpu")
        self.assertEqual(s.snapshot()[1].sum(), 0)
        for k in range(5):
            s.push(np.array([k, k], float))
        b, v = s.snapshot()
        self.assertTrue(np.array_equal(b[:, 0], [4, 3, 2]))                     # newest on top, oldest dropped
        self.assertTrue(np.allclose(s.corr(np.array([1.0, 0.0])), [4, 3, 2]))
        self.assertTrue(np.allclose(s.corr(np.array([1.0, 1.0]), l2=True), [1, 1, 1]))
        with self.assertRaises(ValueError):
            s.push(np.array([1.0]))
        m = EventModel(8, 4, 3, 3, use_stack=True)
        q, _ = m.encode(np.random.default_rng(0).normal(size=(2, 5, 8)))
        stack = np.random.default_rng(1).normal(size=(2, 3, 4))
        out = m.logits(q, stack, np.ones((2, 3)))
        out.sum().backward()
        self.assertIsNotNone(m.p["Wz"].grad)                                    # gradient flows into the current descriptor's encoder

    def test_gaussian_weights(self):
        w, st = STE.gaussian_weights(np.array([1.0, 2.0, 3.0, 4.0]))
        self.assertAlmostEqual(w.sum(), 4.0)
        self.assertGreater(w[1], w[0])
        self.assertEqual(STE.gaussian_weights(np.array([5.0, 5.0, 5.0]))[1], "ZERO_TIME_VARIANCE")
        self.assertEqual(STE.gaussian_weights(np.array([5.0]))[1], "SINGLE")
        r = STE.split_repr(np.array([1.0, 2.0, 3.0]), np.array([0.1, -0.2, 0.3]), np.zeros(3), np.zeros(3), np.zeros(3))
        w, _ = STE.gaussian_weights(np.array([1.0, 2.0, 3.0]))                  # [0.728, 1.543, 0.728] (sum 3)
        self.assertEqual(r[0], math.ceil(w[0] + w[2]))                           # ceil of the weighted up-count (1.457 -> 2)
        self.assertEqual(r[1], math.ceil(w[1]))                                  # the centre event weighs more (1.543 -> 2)

    def test_ste_shared_refinement_and_shapes(self):
        m = STE.STEModel(K=3)
        out = m.forward(np.random.default_rng(0).normal(size=(5, 8, 7)))
        self.assertEqual(len(out["iters"]), 3)
        self.assertEqual(out["final"].data.shape, (5, 1))
        self.assertEqual(STE.STEModel(K=1).n_params(), m.n_params())            # refinement weights are shared across iterations
        h = STE.huber(A.T(np.array([[0.5], [3.0]])), np.array([0.0, 0.0]))
        self.assertAlmostEqual(float(h.data), (0.125 + 2.5) / 2)


class TestMathBench(unittest.TestCase):
    def test_export_roundtrip_and_onnx_bytes(self):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        man = MB.export(d)
        chk = MB.python_checks(d)
        self.assertEqual(chk["reload_max_abs_diff"], 0.0)                       # exact float64 CSV round trip
        self.assertEqual(chk["rows_read"], 200)
        self.assertLess(chk["float32_expected_max_abs_err"], 1e-4)
        P = MB.read_weights(d / "model_weights.csv")
        self.assertEqual({k: v.shape for k, v in P.items()}, {k: v for k, v in MB.SHAPES.items()})
        self.assertEqual(man["onnx"]["dtype"], "float32")
        bad = (d / "model_weights.csv").read_text().replace("#W2,16,8", "#W2,8,16")
        (d / "bad.csv").write_text(bad)
        with self.assertRaises(ValueError):
            MB.read_weights(d / "bad.csv")
        self.assertAlmostEqual(MB.percentile_linear([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(MB.percentile_linear(list(range(101)), 0.95), 95.0)


if __name__ == "__main__":
    unittest.main()
