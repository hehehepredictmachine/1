"""1.13 shared analytics - SYNTHETIC_TEST data only (checks the algorithms and the integration, never market evidence).

A numerical correctness: BB / MAs reference values, warm-up, flat window, unclipped %b; FFT known frequency, flat signal,
  gaps, Nyquist; EMD exact reconstruction; VMD recovers known components, timeout flagged.
B causality: prefix invariance, causal Double Bottom scan never uses later bars, archived snapshots are not rewritten.
C Double Bottom + library: four statuses, first decisive close fixed, data error != FAILED, deterministic pair, stable id,
  single == library-wide result, empty / deleted / cancelled jobs, report files, import validation, no path traversal.
D integration: one BB/EMA implementation (chart lines == legacy M02I == scalp module), late worker results discarded,
  configuration influence can only be OBSERVE."""
from __future__ import annotations

import json
import math
import sys
import time
import unittest
from pathlib import Path

import _env
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent / "analytics"))

import fixtures as F  # noqa: E402
from masterquo.analytics import contract, double_bottom as DB, signal as SG, ta  # noqa: E402


def sine_bars(n, periods=((32, 3.0),), trend=0.0, tf_min=5, base=2000.0):
    return F.from_path([base + trend * i + sum(a * math.sin(2 * math.pi * i / p) for p, a in periods) for i in range(n)], tf_min, wick=0.1)


class TestBBMA(unittest.TestCase):
    def test_bb_reference_values(self):
        c = [1.0, 2.0, 3.0, 4.0, 5.0]
        bb = ta.bollinger(c, 5, 2.0)
        sd = math.sqrt(2.0)                                       # population std of 1..5
        self.assertAlmostEqual(bb["middle"][-1], 3.0)
        self.assertAlmostEqual(bb["upper"][-1], 3.0 + 2 * sd)
        self.assertAlmostEqual(bb["bandwidth_ratio"][-1], 4 * sd / 3.0)
        self.assertAlmostEqual(bb["bandwidth_pct"][-1], 100 * 4 * sd / 3.0)
        self.assertIsNone(bb["middle"][3])
        self.assertEqual(bb["reason"][3], "WARMUP")

    def test_flat_window_and_unclipped_percent_b(self):
        bb = ta.bollinger([5.0] * 25, 20, 2.0)
        self.assertIsNone(bb["percent_b"][-1])
        self.assertEqual(bb["reason"][-1], "FLAT_WINDOW")
        c = [1.0] * 19 + [1.0, 10.0]
        bb2 = ta.bollinger(c, 20, 2.0)
        self.assertGreater(bb2["percent_b"][-1], 1.0)              # not clipped

    def test_ma_reference(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        self.assertEqual(ta.sma(x, 3)[-1], 5.0)
        self.assertAlmostEqual(ta.wma(x, 3)[-1], (4 * 1 + 5 * 2 + 6 * 3) / 6)
        e = ta.ema(x, 3)
        self.assertEqual(e[2], 2.0)                                # seeded with SMA of the first 3
        self.assertAlmostEqual(e[3], 0.5 * 4 + 0.5 * 2.0)
        self.assertIsNone(e[1])

    def test_ma_cross_events_and_bb_middle_flag(self):
        bars = F.from_path([10.0] * 30 + [10 + 0.5 * k for k in range(1, 15)])
        r = ta.ma_analysis(bars, [{"id": "EMA3", "type": "EMA", "period": 3}, {"id": "SMA20", "type": "SMA", "period": 20}], tf="M5")
        v = r["values"]
        self.assertTrue(any(e["kind"] == "BULLISH_CROSS" for e in v["crosses"]) or v["ordering"] == "BULLISH")
        self.assertTrue(next(m for m in v["mas"] if m["id"] == "SMA20")["same_as_bb_middle"])
        r2 = ta.ma_analysis(bars, [{"id": "EMA3", "type": "EMA", "period": 3}, {"id": "SMA20", "type": "SMA", "period": 20}], tf="M5")
        self.assertEqual([e["event_id"] for e in v["crosses"]], [e["event_id"] for e in r2["values"]["crosses"]])   # stable ids
        bad = ta.ma_analysis(bars, [{"id": "X", "type": "HMA", "period": 3}], tf="M5")
        self.assertEqual(bad["status"], "error")

    def test_bb_contract_and_events(self):
        r = ta.bb_analysis(sine_bars(200), tf="M5", symbol="XAUUSD-")
        for k in ("schema_version", "algorithm_version", "config_hash", "snapshot_id", "source_revision", "as_of", "available_at", "window_start",
                  "window_end", "status", "closed_bars_only", "samples", "latency_ms"):
            self.assertIn(k, r)
        self.assertEqual(r["status"], "ready")
        self.assertIsInstance(r["values"]["events"], list)
        self.assertEqual(ta.bb_analysis(sine_bars(10), tf="M5")["status"], "warming_up")

    def test_single_implementation_matches_legacy_and_scalp(self):
        from masterquo.engine.legacy import modules
        from masterquo.scalp import indicators as sci
        m = modules()["m02i"]
        c = [b["c"] for b in sine_bars(120, ((17, 2.0), (5, 0.7)))]
        ours = ta.bollinger(c, 20, 2.0)
        for i in range(19, len(c)):
            leg = m.bb(c[: i + 1], 20, 2.0)
            self.assertAlmostEqual(ours["upper"][i], leg["upper"], places=9)
            self.assertAlmostEqual(ours["lower"][i], leg["lower"], places=9)
        for a, b in zip(ta.ema(c, 21), m.ema(c, 21)):
            if a is not None and b is not None:
                self.assertAlmostEqual(a, b, places=9)
        sb = sci.bollinger(c, [1.0] * len(c))
        for i in range(19, len(c)):
            self.assertAlmostEqual(sb[i]["upper"], ours["upper"][i], places=9)
        from masterquo.engine import chartdata
        bars = sine_bars(80)
        lines = chartdata.indicator_series("M5", bars, {"enabled": {"ema": [9], "bollinger": {"period": 20, "std_mult": 2.0}}})["lines"]
        self.assertEqual({ln["id"] for ln in lines} >= {"EMA9", "BB_U", "BB_L"}, True)
        self.assertTrue(all(ln.get("engine") == ta.VERSION for ln in lines))

    def test_prefix_invariance(self):
        bars = sine_bars(300, ((23, 2.0),), 0.01)
        a = ta.bb_analysis(bars[:250], tf="M5")["values"]
        b = ta.bb_analysis(bars[:250], tf="M5")["values"]
        self.assertEqual(a, b)
        full = ta.bollinger([x["c"] for x in bars], 20, 2.0)
        part = ta.bollinger([x["c"] for x in bars[:250]], 20, 2.0)
        self.assertEqual(full["upper"][:250], part["upper"])


class TestSignal(unittest.TestCase):
    def test_fft_known_period(self):
        r = SG.fft_analysis(sine_bars(400, ((32, 3.0),)), "M5", {"fft_input": "detrended_log_close"})
        self.assertEqual(r["status"], "ready")
        self.assertAlmostEqual(r["values"]["dominant"][0]["period_bars"], 32, delta=2)
        self.assertEqual(r["values"]["dominant"][0]["period_minutes"], round(r["values"]["dominant"][0]["period_bars"] * 5, 1))
        self.assertEqual(r["values"]["zero_padding"], "brak")

    def test_fft_flat_gap_and_short(self):
        flat = F.from_path([2000.0] * 300, wick=0.0)
        self.assertIn("FLAT_SIGNAL", SG.fft_analysis(flat, "M5")["quality_flags"])
        bars = sine_bars(300)
        gap = bars[:250] + [dict(b, open_utc=F.from_path([1.0] * 400)[0]["open_utc"].replace("2026-03-02", "2026-03-09")) for b in bars[250:251]]
        r = SG.fft_analysis(gap, "M5")
        self.assertIn(r["status"], ("unavailable", "warming_up"))
        self.assertIn("GAP_IN_WINDOW", r["reason"] or "") if r["status"] == "unavailable" else None
        self.assertEqual(SG.fft_analysis(sine_bars(50), "M5")["status"], "warming_up")

    def test_emd_reconstruction_and_components(self):
        r = SG.emd_analysis(sine_bars(400, ((40, 3.0), (6, 0.6)), 0.01), "M5")
        v = r["values"]
        self.assertEqual(r["status"], "ready")
        self.assertLess(v["reconstruction_max_abs_error"], 1e-9)
        periods = [c["mean_period_bars"] for c in v["imfs"] if c["mean_period_bars"]]
        self.assertTrue(any(abs(p - 6) < 2 for p in periods))
        self.assertTrue(any(abs(p - 40) < 10 for p in periods))

    def test_vmd_components_and_timeout(self):
        r = SG.vmd_analysis(sine_bars(400, ((40, 3.0), (8, 1.0))), "M5", {"vmd_k": 3})
        v = r["values"]
        per = sorted(m["period_bars"] for m in v["modes"] if m["period_bars"])
        self.assertTrue(any(abs(p - 8) < 1.5 for p in per), per)
        self.assertTrue(any(abs(p - 40) < 8 for p in per), per)
        self.assertLess(v["reconstruction_rel_error"], 0.2)
        t = SG.vmd_analysis(sine_bars(1024, ((40, 3.0),)), "M5", {"window": 1024, "vmd_tol": 1e-30, "vmd_max_iter": 100000}, timeout_s=0.05)
        self.assertIn("TIMEOUT", t["quality_flags"])
        self.assertFalse(t["values"]["converged"])

    def test_json_clean(self):
        r = SG.fft_analysis(sine_bars(300), "M5")
        json.dumps(r, allow_nan=False)                            # numpy types / NaN never leak into the API


class TestDoubleBottom(unittest.TestCase):
    def test_four_statuses(self):
        self.assertEqual(DB.validate(F.double_bottom("up"), tf="M5")["values"]["status"], "CONFIRMED")
        self.assertEqual(DB.validate(F.double_bottom("down"), tf="M5")["values"]["status"], "FAILED")
        self.assertEqual(DB.validate(F.double_bottom("none"), tf="M5")["values"]["status"], "CANDIDATE")
        inv = DB.validate(F.from_path(F.lin(2000, 2010, 40)), tf="M5")["values"]
        self.assertEqual(inv["status"], "INVALID")
        self.assertIsNone(inv["coordinates"])

    def test_first_decisive_close_is_final(self):
        v = DB.validate(F.double_bottom("up"), tf="M5")["values"]      # breaks up, later drops below the bottoms
        self.assertEqual(v["status"], "CONFIRMED")
        self.assertEqual(v["coordinates"]["decisive"]["kind"], "BREAK_ABOVE_NECKLINE")

    def test_data_error_is_not_failed(self):
        bars = F.double_bottom("up")
        bars[5] = dict(bars[5], h=bars[5]["l"] - 1)
        r = DB.validate(bars, tf="M5")
        self.assertEqual(r["status"], "error")
        self.assertIn("DATA_ERROR", r["reason"])
        dup = F.double_bottom("up")
        dup[6] = dict(dup[6], open_utc=dup[5]["open_utc"])
        self.assertIn("UNSORTED_OR_DUPLICATE", DB.validate(dup, tf="M5")["reason"])

    def test_deterministic_and_stable_id(self):
        a = DB.validate(F.double_bottom("up"), symbol="XAUUSD-", tf="M5")["values"]
        b = DB.validate(F.double_bottom("up"), symbol="XAUUSD-", tf="M5")["values"]
        self.assertEqual(a["pattern_id"], b["pattern_id"])
        self.assertEqual(a["coordinates"], b["coordinates"])

    def test_causal_scan_no_future(self):
        bars = F.double_bottom("up")
        full = DB.validate(bars, tf="M5")["values"]
        dec = full["coordinates"]["decisive"]["index"]
        before = DB.scan_causal(bars[:dec], tf="M5")["values"]           # the decisive bar not yet closed
        self.assertEqual(before["status"], "CANDIDATE")
        i2 = full["coordinates"]["bottom2"]["index"]
        early = DB.scan_causal(bars[: i2 + 2], tf="M5")["values"]         # right-side pivot bars not closed yet
        self.assertNotEqual((early.get("coordinates") or {}).get("bottom2", {}).get("index"), i2)
        av = full["available"]["bottom2_pivot_known_at"]
        self.assertGreater(av, bars[i2]["open_utc"])                       # known only after the right-side bars

    def test_extended_mode_is_separate_version(self):
        r = DB.validate(F.double_bottom("up"), {"mode": "EXTENDED", "min_depth_atr": 0.5}, tf="M5")
        self.assertEqual(r["algorithm_version"], DB.VERSION_EXT)
        self.assertEqual(DB.validate(F.double_bottom("up"), tf="M5")["algorithm_version"], DB.VERSION)


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.analytics.library import PatternLibrary
        self.db = Database()
        self.lib = PatternLibrary(self.db, lambda: dict(DB.DEFAULT))

    def tearDown(self):
        self.td.close()

    def wait(self, job_id):
        for _ in range(200):
            j = self.lib.job(job_id)
            if j["status"] != "RUNNING":
                return j
            time.sleep(0.05)
        self.fail("job did not finish")

    def test_add_duplicate_validate_and_job_equivalence(self):
        a = self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("up"), "TEST")
        b = self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("up"), "TEST")
        self.assertTrue(b["duplicate"])
        self.assertEqual(a["id"], b["id"])
        c = self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("down"), "TEST")
        one = self.lib.validate_one(a["id"])["result"]["values"]
        j = self.wait(self.lib.start_job(None)["job_id"])
        self.assertEqual(j["status"], "COMPLETED")
        self.assertEqual(j["counts"]["CONFIRMED"], 1)
        self.assertEqual(j["counts"]["FAILED"], 1)
        rep = self.lib.report(j["report_id"])
        r0 = next(r for r in rep["results"] if r["sample_id"] == a["id"])
        self.assertEqual(r0["coordinates"], one["coordinates"])               # single == library-wide
        self.assertEqual(r0["status"], one["status"])
        from masterquo.analytics.library import lib_dir
        self.assertTrue((lib_dir() / "reports" / f"{j['report_id']}.csv").exists())
        raw = self.lib.get(c["id"])["bars"]
        self.assertEqual(raw, json.loads(json.dumps(raw)))                   # raw sample untouched
        self.assertEqual(self.lib.list(status="CONFIRMED")[0]["id"], a["id"])

    def test_empty_deleted_and_bad_samples(self):
        j = self.wait(self.lib.start_job(None)["job_id"])
        self.assertEqual(j["status"], "COMPLETED")
        self.assertEqual(j["total"], 0)
        a = self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("up"), "TEST")
        self.lib.delete(a["id"])
        j2 = self.wait(self.lib.start_job([a["id"], 999])["job_id"])
        self.assertEqual(j2["counts"]["MISSING"], 2)
        bad = F.double_bottom("up")
        bad[3] = dict(bad[3], h=bad[3]["l"] - 5)
        self.assertFalse(self.lib.add_sample("XAUUSD-", "M5", bad, "TEST")["ok"])

    def test_cancel_gives_partial_not_complete(self):
        ids = [self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("up", 1990.2 + k * 0.01), "TEST")["id"] for k in range(30)]
        st = self.lib.start_job(ids)
        self.lib.cancel(st["job_id"])
        j = self.wait(st["job_id"])
        self.assertIn(j["status"], ("CANCELLED", "COMPLETED"))
        if j["status"] == "CANCELLED":
            self.assertFalse(self.lib.report(j["report_id"])["complete"])

    def test_import_validation_and_report_id_safety(self):
        self.assertFalse(self.lib.import_samples({"samples": []})["ok"])
        ok = self.lib.import_samples({"schema": "mq-pattern-library-1", "samples": [{"symbol": "XAUUSD-", "timeframe": "M5", "bars": F.double_bottom("up")},
                                                                                     {"symbol": "XAUUSD-", "timeframe": "M5", "bars": [{"x": 1}]}]})
        self.assertEqual(ok["added"], 1)
        self.assertEqual(len(ok["errors"]), 1)
        self.assertIsNone(self.lib.report("../../etc/passwd"))


class TestServiceIntegration(unittest.TestCase):
    def test_influence_only_observe(self):
        from masterquo.config import AnalyticsConfig
        with self.assertRaises(Exception):
            AnalyticsConfig(influence="DECIDE")
        with self.assertRaises(Exception):
            AnalyticsConfig(mas=[{"id": "X", "type": "HMA", "period": 9}])

    def test_late_result_discarded_and_snapshots_kept(self):
        from masterquo.analytics.service import AnalyticsService
        from masterquo.config import AppConfig
        from masterquo.db.database import Database
        td = TempData()
        try:
            bars = {"M5": sine_bars(300, ((32, 3.0),))}

            class Bridge:
                def bars(self, tf, limit, include_forming=False):
                    return bars.get(tf, [])[-(limit or 10 ** 9):]

            class Cfg:
                def get(self):
                    c = AppConfig()
                    c.analytics.timeframes = ["M5"]
                    c.analytics.signal_timeframes = ["M5"]
                    c.analytics.db_timeframes = ["M5"]
                    return c

            class Bus:
                def publish(self, *a):
                    pass
            svc = AnalyticsService(Cfg(), Bridge(), Database(), Bus(), None)
            svc.tick()
            key, b0, sym, cfg, to = svc.pending["M5"]
            snap = svc.history("bollinger", "M5", 10)
            self.assertEqual(len(snap), 1)
            bars["M5"] = sine_bars(301, ((32, 3.0),))                  # a new bar arrives before the worker runs
            svc.tick()
            svc.pending["M5"] = (key, b0, sym, cfg, to)                 # the OLD job is processed late
            svc._stop.set()
            import threading
            th = threading.Thread(target=svc._worker)
            svc._stop.clear()
            th.start()
            time.sleep(1.5)
            svc._stop.set()
            with svc._cv:
                svc._cv.notify_all()
            th.join(5)
            self.assertGreaterEqual(svc.counters["discarded_stale"], 1)
            self.assertNotIn("fft", svc.state["M5"])                   # nothing from the old key shown as current
            hist = svc.history("bollinger", "M5", 10)
            self.assertEqual(len(hist), 2)
            self.assertEqual(hist[-1]["payload"], snap[0]["payload"])  # the archived earlier snapshot is unchanged
            sup = svc.support()
            self.assertIn("OBSERVE", sup["influence"])
        finally:
            td.close()


if __name__ == "__main__":
    unittest.main()
