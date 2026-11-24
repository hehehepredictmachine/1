"""1.46 audit, group B_mm_1 - regression tests of the PMW-MM master-model package (SHADOW / research only; SYNTHETIC_TEST data and
test doubles, no network, no demo server).

chunk_21#6   align_mean: a bar CLOSING exactly at the session start belongs to the session that is ending (was: the new one)
chunk_21#10  breakout_zones.evaluate: false_rate is null when no breakout was resolved (was 0.0)
chunk_21#4   buzoa: random_search / pso / DE with only invalid evaluations -> NO_VALID_EVALUATION (random_search raised AttributeError)
chunk_21#3   event_engine.StateStack.reset after a failed OpenCL init (no GPU) stays on the CPU reference (was AttributeError d_buf)
chunk_21#11  event_engine.Runtime: dspread is 0 when the PREVIOUS event had no spread - identical to events.featurize
chunk_21#7   features.target_dir3: label time from the timeframe, not from the gap between the first two bars
chunk_21#2   jobs._events: the REAL_TICKS archive (t_ms) is really used (was KeyError swallowed -> silent BAR_CLOSE_EVENTS)
chunk_21#5   jobs.job_kalman_calibration: VAL / TEST score only the events of their own block (200 earlier bars only warm the filter)
chunk_21#9   jobs.job_kalman_calibration: missing spread -> cost_log null + UNAVAILABLE (was a silent cost 0.0)
chunk_21#8   evidence board: Kalman direction = last ACCEPTED crossover, never the unconfirmed *_CANDIDATE
chunk_22#3   Ledger.rows(newest=True): the newest window in time order
chunk_22#4   service._gpr: drift is measured on the newest scored forecasts (cumulative coverage kept as information)
chunk_22#0   smc_fvg.evaluate: a stop touched on the entry bar is a STOP; unresolved entries without the full horizon are NOT_MATURED
chunk_22#1   smc_fvg: an invalid bar no longer shifts the structure indices (A / B / FVG scan / timestamps)
chunk_22#2   smc_fvg: a bar that opens below p* fills at the open (a gap below the stop -> INVALID_RISK_GEOMETRY)
chunk_22#7   smc_fvg: stop buffer in points (point of the symbol), not in ticks
chunk_22#5   stfs.triplet_batch_hard: the L2 norm is inside the autodiff graph (gradient = finite differences)
chunk_22#6   tsvp: reconciliation of the trailing millisecond keeps the chronological order (incremental == rebuild in BID_CHANGE)
chunk_21#12  artifacts: the SHADOW pointer is written through a unique temporary file
"""
from __future__ import annotations

import math
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData
from masterquo.lab import autodiff as A
from masterquo.mm import align_mean as AM
from masterquo.mm import breakout_zones as BZ
from masterquo.mm import buzoa as BU
from masterquo.mm import event_engine as EE
from masterquo.mm import events as EV
from masterquo.mm import features as FE
from masterquo.mm import jobs as J
from masterquo.mm import kalman as K
from masterquo.mm import smc_fvg as SF
from masterquo.mm import stfs as STF
from masterquo.mm import tsvp as TV
from masterquo.mm.data import Bars
from masterquo.mm.ledger import Ledger

DAY = 86400.0


def walk_bars(n=3000, seed=5, start=1_790_000_000.0, tf=300, spread=10.0):
    g = np.random.default_rng(seed)
    c = 2300 + np.cumsum(g.normal(0, 0.6, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + np.abs(g.normal(0, 0.3, n))
    lo = np.minimum(o, c) - np.abs(g.normal(0, 0.3, n))
    t = start + tf * np.arange(n)
    return Bars("M5", t.astype(float), o, h, lo, c, np.full(n, 100.0), np.full(n, spread, dtype=float))


# ---------------------------------------------------------------------------------------------------------------- align mean / breakout
class TestAlignMeanSessionBoundary(unittest.TestCase):
    def test_bar_closing_at_session_start_belongs_to_the_old_session(self):
        d0 = 20000 * DAY                                                     # 00:00 UTC (session start 0, offset 0)
        t_open = np.array([d0 - 600, d0 - 300, d0, d0 + 300])              # 23:50, 23:55, 00:00, 00:05
        c = np.array([100.0, 200.0, 300.0, 400.0])
        cfg = AM.AlignConfig(mode="SESSION_MEAN", source="CLOSE", lookback="SESSION")
        r = AM.compute(t_open, c, c, c, c, 300, cfg, 0.01)
        self.assertEqual(r["session"].tolist(), [19999, 19999, 20000, 20000])   # the 23:55-00:00 bar lies in the old session
        self.assertEqual(r["mean"][2], 300.0)                                # new session starts with the 00:00 bar only
        self.assertEqual(r["window_bars"][2], 1)
        self.assertEqual(r["mean"][1], 150.0)                                # the old session keeps its last bar
        fx = AM.compute(t_open, c, c, c, c, 300, AM.AlignConfig(mode="FIXED_ANCHORED_MEAN", source="CLOSE", lookback="SESSION"), 0.01)
        self.assertEqual(fx["mean"][2], 300.0)                               # anchor of the new session = its own first bar
        # a non-aligned session start (22:00) still counts a bar closing at 22:00 to the previous session
        cfg22 = AM.AlignConfig(mode="SESSION_MEAN", source="CLOSE", lookback="SESSION", session_start_min=22 * 60)
        s = AM.session_id(np.array([d0 - 2 * 3600.0, d0 - 2 * 3600.0 + 300]), cfg22)
        self.assertEqual(s[1] - s[0], 1)

    def test_mql5_indicator_uses_the_same_session_boundary(self):
        # parity: the MT5 indicator PMW_AlignMean.mq5 must assign sessions exactly like mm/align_mean.session_id
        src = (Path(__file__).resolve().parents[1] / "mql5" / "MasterModels" / "Indicators" / "PMW_AlignMean.mq5").read_text("utf-8")
        line = next(x for x in src.splitlines() if x.startswith("long Sid("))
        self.assertIn("MathCeil(", line)
        self.assertTrue(line.rstrip().endswith("- 1; }"), line)
        self.assertNotIn("MathFloor", line)


class TestBreakoutFalseRate(unittest.TestCase):
    def test_false_rate_is_null_without_resolved_breakouts(self):
        n = 300
        c = np.full(n, 100.0)
        b = Bars("M5", 1_790_000_000.0 + 300 * np.arange(n), c, c + 0.05, c - 0.05, c, np.full(n, 100.0), np.full(n, 10.0))
        ev = BZ.evaluate(b, BZ.BreakoutConfig(confirmation="NONE"), 0.01, 300)
        self.assertEqual(ev["follow_through"] + ev["false_breakout"], 0)
        self.assertIsNone(ev["false_rate"])                                  # unknown, not "0% false breakouts"


# ---------------------------------------------------------------------------------------------------------------- buzoa
class TestOptimisersWithoutValidEvaluation(unittest.TestCase):
    def test_random_search_pso_de_report_no_valid_evaluation(self):
        nan = lambda x: float("nan")
        lb, ub = np.array([0.0, 0.0]), np.array([1.0, 1.0])
        r = BU.random_search(nan, lb, ub, max_evals=30, seed=3, direction="max")   # 1.45.0: AttributeError 'NoneType'.tolist
        self.assertEqual(r["status"], "NO_VALID_EVALUATION")
        self.assertIsNone(r["best_x"])
        self.assertIsNone(r["best_f"])
        for fn in (BU.pso, BU.differential_evolution):
            r = fn(nan, lb, ub, pop=6, max_evals=30, seed=3)
            self.assertEqual(r["status"], "NO_VALID_EVALUATION", fn.__name__)
            self.assertIsNone(r["best_x"])
            self.assertIsNone(r["best_f"])                                    # was +inf presented as a best value
        ok = BU.random_search(BU.sphere, lb - 1, ub, max_evals=50, seed=3)
        self.assertEqual(ok["status"], "OK")
        self.assertTrue(math.isfinite(ok["best_f"]))


# ---------------------------------------------------------------------------------------------------------------- event engine
class TestStateStackWithoutGpu(unittest.TestCase):
    def test_reset_after_failed_opencl_init_uses_cpu(self):
        fake = types.ModuleType("pyopencl")
        fake.get_platforms = list                                      # pyopencl present, no GPU device
        fake.device_type = NS(GPU=4)
        with mock.patch.dict(sys.modules, {"pyopencl": fake}):
            st = EE.StateStack(4, 3, "auto")
        self.assertEqual(st.backend_used, "CPU")
        self.assertIn("NO_OPENCL_GPU_DEVICE", st.cl_error)
        st.push(np.ones(3))
        st.reset()                                                           # 1.45.0: AttributeError 'd_buf'
        b, v = st.snapshot()
        self.assertEqual(int(v.sum()), 0)
        self.assertFalse(b.any())


class TestRuntimeSpreadFeatureParity(unittest.TestCase):
    def test_dspread_zero_after_an_event_without_spread(self):
        m = EE.EventModel(8, H=4, S=2, seed=1)
        sc = EV.Scaler()
        sc.med, sc.iqr = np.zeros(8), np.ones(8)
        rt = EE.Runtime(m, sc, 16, "XAUUSD", "test", 900.0, backend="cpu")
        evs = [(1000.0, 100.0, 100.2, True), (1001.0, 100.1, 100.1, False), (1002.0, 100.0, 100.3, True), (1003.0, 100.05, 100.25, True)]
        for t, bid, ask, ok in evs:
            rt.push({"t": t, "bid": bid, "ask": ask, "activity": 1.0, "spread_ok": ok})
        online = np.asarray(rt.buf)
        acc = {"t": np.array([e[0] for e in evs]), "mid": np.array([(e[1] + e[2]) / 2 for e in evs]),
               "spread": np.array([(e[2] - e[1]) if e[3] else np.nan for e in evs]), "activity": np.ones(len(evs)), "segment": np.zeros(len(evs), int)}
        off = EV.featurize(acc)["F"][1:]
        self.assertEqual(online[1, 5], 0.0)                                  # previous event had no spread -> dspread 0 (was 0.3)
        np.testing.assert_allclose(online, off, atol=1e-12)                  # online == offline features


# ---------------------------------------------------------------------------------------------------------------- features
class TestTargetLabelTime(unittest.TestCase):
    def test_t_end_uses_the_timeframe_not_the_first_gap(self):
        n = 80
        g = np.random.default_rng(2)
        c = 2300 + np.cumsum(g.normal(0, 0.6, n))
        t0 = 1_790_000_100.0
        t = np.r_[t0, t0 + 2 * DAY + 300 * np.arange(1, n)]                 # two-day gap after the first bar
        b = Bars("M5", t, c, c + 0.3, c - 0.3, c, np.full(n, 100.0), np.full(n, 10.0))
        y, t_end = FE.target_dir3(b, 12)
        i = 30
        self.assertGreaterEqual(y[i], 0)
        self.assertEqual(t_end[i], t[i + 12] + 300)                          # 1.45.0: t[i+12] + 172800
        ds = FE.dataset(b, ["ret_1"], 300, 12)
        np.testing.assert_array_equal(ds["t_end"], np.asarray(b.t)[ds["idx"] + 12] + 300)


# ---------------------------------------------------------------------------------------------------------------- jobs
def _fake_ctx(b5: Bars, **kw):
    return NS(inst="XAUUSD", bars=lambda tf: b5 if tf in ("M5", "M1") else None, snap=NS(point=0.01, tick_size=0.01, snapshot_id="SNAP-TEST", data_kind="SYNTHETIC_TEST"),
              prof={"buzoa_evals": 20}, seed=7, cancel=None, synthetic=True, profile="quick", results={}, **kw)


class TestJobsEventsRealTicks(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_tick_archive_is_used_with_times_in_seconds(self):
        from masterquo.lab import tick_store
        g = np.random.default_rng(4)
        mid = 2300 + np.cumsum(g.normal(0, 0.02, 20_500))
        t0 = 1_790_000_000_000
        ticks = [{"t_ms": t0 + 250 * k, "time_msc": t0 + 250 * k, "bid": round(float(mid[k]) - 0.1, 2), "ask": round(float(mid[k]) + 0.1, 2),
                  "flags": 6} for k in range(len(mid))]
        tick_store.save_chunk("XAUUSD", ticks, "TEST", "t_ms = time_msc", False)
        old = [{**x, "t_ms": x["t_ms"] - 10 * 86_400_000, "time_msc": x["time_msc"] - 10 * 86_400_000} for x in ticks[:500]]
        tick_store.save_chunk("XAUUSD", old, "TEST", "t_ms = time_msc", False)                 # before the snapshot: not used
        res = J._events(_fake_ctx(walk_bars(300)))
        acc, src = res[0], res[2]
        self.assertEqual(src, "REAL_TICKS")                                  # 1.45.0: KeyError 't' swallowed -> BAR_CLOSE_EVENTS
        self.assertAlmostEqual(float(acc["t"][0]), t0 / 1000.0)              # seconds (gap_reset_s / dt_log are in seconds)
        self.assertEqual(int(acc["segment"].max()), 0)                       # 0.25 s spacing: no false 900 s gap resets
        self.assertEqual(len(acc["t"]), len(ticks))
        self.assertIsNone(res[3])
        ctx = _fake_ctx(walk_bars(300))
        ctx.prof = {"m1_bars": 20_100}                                        # the profile's event budget: newest ticks only
        acc = J._events(ctx)[0]
        self.assertEqual(len(acc["t"]), 20_100)
        self.assertAlmostEqual(float(acc["t"][-1]), ticks[-1]["t_ms"] / 1000.0)

    def test_fallback_reason_is_reported(self):
        res = J._events(_fake_ctx(walk_bars(300)))                           # empty archive
        self.assertEqual(res[2], "BAR_CLOSE_EVENTS")
        self.assertTrue(res[3])


def _fwd_from(t, c, x, start, cost, horizon=12):
    cfg = K.CrossConfig(Q_fast=10 ** x[0], Q_slow=10 ** x[1], confirm_bars=int(round(x[2])))
    k, rows = K.run(t, c, cfg)
    idx = {r["bar_time"]: i for i, r in enumerate(rows) if r.get("processed")}
    out = []
    for e in k.events:
        i = idx[e["bar_time"]]
        if i >= start and i + horizon < len(c):
            out.append((1 if e["direction"] == "BULLISH" else -1) * math.log(c[i + horizon] / c[i]) - cost)
    return out


class TestKalmanCalibrationJob(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_val_and_test_score_only_their_own_block(self):
        b = walk_bars(4000, seed=11)
        r = J.job_kalman_calibration(_fake_ctx(b))
        n = len(b.t)
        i1, i2 = int(n * 0.6), int(n * 0.8)
        cost = float(np.nanmedian(b.spread) * 0.01 / np.median(b.c))
        x = [0.0, math.log10(0.005), 2.0]
        own = _fwd_from(b.t[i1 - 200:i2], b.c[i1 - 200:i2], x, 200, cost)
        with_warmup = _fwd_from(b.t[i1 - 200:i2], b.c[i1 - 200:i2], x, 0, cost)
        self.assertGreater(len(with_warmup), len(own))                       # events in the 200 TRAIN bars exist ...
        self.assertAlmostEqual(r["val_scores"]["default"], float(np.mean(own)), places=12)   # ... and are not scored on VAL
        xt = r["picked_x"]
        own_t = _fwd_from(b.t[i2 - 200:], b.c[i2 - 200:], xt, 200, cost)
        if len(own_t) >= 30:
            self.assertAlmostEqual(r["test_once"], float(np.mean(own_t)), places=12)
        else:
            self.assertTrue(math.isnan(r["test_once"]))
        self.assertEqual(r["cost_status"], "OK")
        self.assertAlmostEqual(r["cost_log"], cost)

    def test_missing_spread_is_unavailable_not_zero(self):
        b = walk_bars(1500, seed=12, spread=np.nan)
        r = J.job_kalman_calibration(_fake_ctx(b))
        self.assertIsNone(r["cost_log"])                                     # 1.45.0: 0.0
        self.assertEqual(r["cost_status"], "UNAVAILABLE")
        self.assertEqual(r["net_of_cost"], "NOT_VERIFIED")


class TestKalmanDirectionOnBoard(unittest.TestCase):
    def _board_dir(self, kl: dict):
        ctx = _fake_ctx(walk_bars(300))
        ctx.results = {"kalman": {"per_tf": {"M5": kl}}}
        rows = J.job_fusion_board(ctx)["board"]["readings"]
        row = next(r for r in rows if r["source"] == "kalman")
        return row["payload"]["direction"], row

    def test_candidate_is_not_a_direction(self):
        d, row = self._board_dir({"last_state": "BEARISH_CANDIDATE", "last_accepted": 1})
        self.assertEqual(d, "BULLISH")                                        # last accepted crossover (was BEARISH from the candidate)
        self.assertEqual(row["payload"]["state"], "BEARISH_CANDIDATE")        # the candidate stays visible separately
        self.assertEqual(self._board_dir({"last_state": "BULLISH_CANDIDATE", "last_accepted": 0})[0], None)
        self.assertEqual(self._board_dir({"last_state": "BULLISH_CANDIDATE"})[0], None)        # result of an older run (no last_accepted)
        self.assertEqual(self._board_dir({"last_state": "BEARISH_CONFIRMED"})[0], "BEARISH")

    def test_service_helper_and_job_kalman_report_accepted(self):
        from masterquo.mm import service as S
        self.assertEqual(S._kalman_direction("BEARISH_CANDIDATE", 1), "BULLISH")
        self.assertEqual(S._kalman_direction("BULLISH_CANDIDATE", -1), "BEARISH")
        self.assertIsNone(S._kalman_direction("BULLISH_CANDIDATE", 0))
        self.assertEqual(S._kalman_direction("BULLISH_CONFIRMED", 1), "BULLISH")
        b = walk_bars(600, seed=3)
        out = J.job_kalman(_fake_ctx(b))["per_tf"]["M5"]
        full, _ = K.run(b.t, b.c, K.CrossConfig())
        self.assertEqual(out["last_accepted"], full.accepted)


# ---------------------------------------------------------------------------------------------------------------- ledger / service
class TestLedgerNewestAndLiveDrift(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.led = Ledger(Path(self.td.dir) / "ledger.sqlite")

    def tearDown(self):
        self.led.c.close()
        self.td.close()

    def _fill(self, mid, n, t0, scored=None):
        for k in range(n):
            ts = t0 + 300.0 * k
            self.led.log(pred_id=f"{mid}:{k}:{t0}", model_id=mid, artifact_id=None, feature_schema="X", symbol="XAUUSD", timeframe="M5", source_ts=ts,
                         available_at=ts + 300, matures_at=ts + 1200, horizon="3bars", kind="GAUSSIAN_PREDICTIVE", payload={"pred": 0.0, "sd": 1.0},
                         quality="OK")
        if scored is not None:
            self.led.mature(t0 + 300.0 * n + 1200, lambda row: {"in_1sd": scored, "in_2sd": True, "z": 0.0}, mid)

    def test_rows_newest(self):
        self._fill("m", 2500, 1_790_000_000.0)
        new = self.led.rows("m", limit=200, newest=True)
        self.assertEqual(len(new), 200)
        self.assertEqual(new[-1]["source_ts"], 1_790_000_000.0 + 300.0 * 2499)
        self.assertEqual([r["source_ts"] for r in new], sorted(r["source_ts"] for r in new))   # time order kept
        self.assertEqual(self.led.rows("m", limit=5)[0]["source_ts"], 1_790_000_000.0)       # default unchanged (oldest first)

    def test_live_drift_on_recent_window(self):
        from masterquo.mm import service as S
        mid = "gpr_logret:LIVE"
        self._fill(mid, 1000, 1_700_000_000.0, scored=True)                 # long, well calibrated history
        self._fill(mid, 300, 1_710_000_000.0, scored=False)                 # fresh degradation
        b5 = walk_bars(300, seed=9)
        svc = S.MMService(NS())
        svc._ledgers["XAUUSD"] = self.led
        g = svc._gpr("XAUUSD", b5, "SYNTHETIC_TEST")
        cal = g["live_calibration"]
        self.assertEqual(cal["n_scored"], 1300)                              # cumulative kept as information
        self.assertAlmostEqual(cal["coverage_1sd"], 1000 / 1300)
        self.assertEqual(cal["recent"]["n"], 500)
        self.assertAlmostEqual(cal["recent"]["coverage_1sd"], 200 / 500)
        self.assertTrue(any(r.startswith("CALIBRATION_DEGRADED") for r in cal["drift"]["reasons"]), cal["drift"])   # 1.45.0: diluted


# ---------------------------------------------------------------------------------------------------------------- SMC / FVG
class _Bars(NS):
    pass


class TestSmcEvaluate(unittest.TestCase):
    def _eval_with(self, entries, n, h, lo, horizon=5):
        eng = NS(setups={f"S{k}": {"setup_id": f"S{k}", "state": "ENTRY_TOUCH_CONFIRMED", "direction": "LONG", "s": 1, "entry": en, "history": []}
                         for k, en in enumerate(entries)})
        bars = _Bars(t=np.arange(n) * 300.0, h=np.asarray(h, float), l=np.asarray(lo, float))
        with mock.patch.object(SF, "run", lambda *a, **k: eng):
            return SF.evaluate(bars, SF.SMCFVGConfig(), 300, horizon=horizon)

    def test_stop_on_entry_bar_and_not_matured(self):
        en = {"bar": 2, "entry": 102.0, "stop": 100.0, "R": 2.0, "target": 106.0}
        h = [103, 103, 103, 107, 107, 107, 107, 107, 107, 107]
        lo = [101, 101, 99.5, 102, 102, 102, 102, 102, 102, 102]             # low of the ENTRY bar is below the stop
        r = self._eval_with([en], 10, h, lo)
        self.assertEqual((r["stop"], r["target"]), (1, 0))                    # 1.45.0: TARGET (+2R)
        self.assertEqual(r["mean_r_resolved"], -1.0)
        late = {"bar": 7, "entry": 102.0, "stop": 100.0, "R": 2.0, "target": 106.0}
        r = self._eval_with([late], 10, [103] * 10, [101] * 10)
        self.assertEqual(r["not_matured"], 1)                                 # 2 of 5 horizon bars exist: not a TIMEOUT
        self.assertEqual(r["timeout"], 0)
        r = self._eval_with([{**late, "bar": 2}], 10, [103] * 10, [101] * 10)
        self.assertEqual((r["timeout"], r["not_matured"]), (1, 0))


class TestSmcEngine(unittest.TestCase):
    def test_invalid_bar_does_not_shift_structure_indices(self):
        b = walk_bars(3000, seed=5)
        h = b.h.copy()
        h[50] = np.nan
        e = SF.run(Bars("M5", b.t, b.o, h, b.l, b.c, b.tv, b.spread), SF.SMCFVGConfig(), 300)
        with_a = [st for st in e.setups.values() if "A" in st]
        self.assertGreater(len(with_a), 20)
        for st in with_a:
            A_ = st["A"]
            key = "l" if st["s"] > 0 else "h"
            self.assertEqual(e.bars[A_["bar"]][key], A_["price"], st["setup_id"])     # 1.45.0: 72 of 74 shifted by one bar
            self.assertEqual(e.bars[A_["bar"]]["t"], A_["ts"])
            if "B" in st:
                self.assertEqual(e.bars[st["B"]["bar"]]["h" if st["s"] > 0 else "l"], st["B"]["price"])
            for g in st.get("gaps", []):
                self.assertGreaterEqual(g["bar"], A_["bar"] + 2)
        clean = SF.run(b, SF.SMCFVGConfig(), 300)                             # no invalid bar: unchanged behaviour
        self.assertTrue(all(clean.bars[st["A"]["bar"]]["l" if st["s"] > 0 else "h"] == st["A"]["price"]
                            for st in clean.setups.values() if "A" in st))

    def _waiting(self, cfg=None):
        e = SF.ContinuationEngine(cfg or SF.SMCFVGConfig())
        e.bars = [{"t": 1000.0 + 300 * k, "o": 105.0, "h": 106.0, "l": 104.0, "c": 105.0} for k in range(5)]
        st = {"setup_id": "S", "direction": "LONG", "s": 1, "state": "WAITING_FOR_VALID_RETRACEMENT", "history": [],
              "A": {"price": 100.0}, "B": {"price": 110.0, "confirm_bar": 3}, "bos": {"bar": 1},
              "gaps": [{"gap_id": "FVG-2", "low": 102.0, "high": 104.0, "t_low": 102.0, "t_high": 104.0}]}
        e.setups["S"] = st
        return e, st

    def test_gap_open_below_stop_is_not_filled_at_p_star(self):
        e, st = self._waiting()
        e.bars.append({"t": 2500.0, "o": 99.0, "h": 99.5, "l": 98.0, "c": 99.2})
        e._retrace(st, 5)
        self.assertEqual(st["state"], "SETUP_INVALIDATED")                    # 1.45.0: ENTRY_TOUCH_CONFIRMED at 102.7
        self.assertEqual(st["history"][-1]["why"], "INVALID_RISK_GEOMETRY")
        e, st = self._waiting()
        e.bars.append({"t": 2500.0, "o": 101.0, "h": 101.5, "l": 100.5, "c": 101.2})   # opens below the gap, above the stop
        e._retrace(st, 5)
        self.assertEqual(st["state"], "ENTRY_TOUCH_CONFIRMED")
        self.assertEqual(st["entry"]["entry"], 101.0)                         # limit fills at the open
        e, st = self._waiting()
        e.bars.append({"t": 2500.0, "o": 105.0, "h": 105.5, "l": 102.5, "c": 103.0})   # normal touch from above: p*
        e._retrace(st, 5)
        self.assertAlmostEqual(st["entry"]["entry"], 110 - 0.73 * 10)

    def test_stop_buffer_in_points(self):
        cfg = SF.SMCFVGConfig(stop_buffer_points=5, tick=0.05, point=0.01)
        e, st = self._waiting(cfg)
        e.bars.append({"t": 2500.0, "o": 105.0, "h": 105.5, "l": 102.5, "c": 103.0})
        e._retrace(st, 5)
        self.assertAlmostEqual(st["entry"]["stop"], 100.0 - 5 * 0.01)        # 1.45.0: 5 x tick = 0.25
        legacy = SF.SMCFVGConfig(stop_buffer_points=5, tick=0.05)            # no point known: the old tick convention
        e, st = self._waiting(legacy)
        e.bars.append({"t": 2500.0, "o": 105.0, "h": 105.5, "l": 102.5, "c": 103.0})
        e._retrace(st, 5)
        self.assertAlmostEqual(st["entry"]["stop"], 100.0 - 5 * 0.05)
        with self.assertRaises(ValueError):
            SF.SMCFVGConfig(point=0.0).validate()


# ---------------------------------------------------------------------------------------------------------------- STFS
class TestTripletGradient(unittest.TestCase):
    def test_autodiff_matches_finite_differences(self):
        g = np.random.default_rng(1)
        E0 = g.normal(0, 1, (6, 4))
        y = np.array([0, 0, 1, 1, 2, 2])
        E = A.T(E0)
        loss, n = STF.triplet_batch_hard(E, y, 0.5)
        self.assertGreater(n, 0)
        loss.backward()
        num = np.zeros_like(E0)
        eps = 1e-6
        for i in range(E0.shape[0]):
            for j in range(E0.shape[1]):
                p, m = E0.copy(), E0.copy()
                p[i, j] += eps
                m[i, j] -= eps
                num[i, j] = (float(STF.triplet_batch_hard(A.T(p), y, 0.5)[0].data) - float(STF.triplet_batch_hard(A.T(m), y, 0.5)[0].data)) / (2 * eps)
        np.testing.assert_allclose(E.grad, num, atol=1e-5)                    # 1.45.0: max |diff| ~0.26
        radial = (E.grad * E0).sum(axis=1)
        np.testing.assert_allclose(radial, 0.0, atol=1e-8)                   # scale-invariant loss: no radial component
        self.assertAlmostEqual(float(STF.triplet_batch_hard(A.T(10 * E0), y, 0.5)[0].data), float(loss.data), places=9)


# ---------------------------------------------------------------------------------------------------------------- TSVP
class TestTsvpTailOrder(unittest.TestCase):
    def test_incremental_equals_rebuild_in_bid_change_mode(self):
        A_ = {"time_msc": 1000, "bid": 2000.00, "ask": 2000.20, "flags": TV.TICK_FLAG_ASK}
        B_ = {"time_msc": 1000, "bid": 2000.10, "ask": 2000.30, "flags": TV.TICK_FLAG_BID | TV.TICK_FLAG_ASK}
        A2 = dict(A_)
        cfg = TV.TSVPConfig(tick=0.01, bucket_ticks=1)
        inc = TV.Profile(cfg, 0, 10_000)
        inc.ingest([A_])
        inc.ingest([A_, B_, A2])
        full = TV.rebuild(cfg, 0, 10_000, [A_, B_, A2])
        self.assertEqual(inc.counted, full.counted)                           # 1.45.0: 2 vs 3
        self.assertEqual(inc.map.items(), full.map.items())
        self.assertEqual(inc.ignored["duplicate"], 1)


# ---------------------------------------------------------------------------------------------------------------- artifacts
class TestShadowPointerWrite(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_pointer_written_through_unique_tmp(self):
        from masterquo.mm import artifacts as MA
        seen = []
        real = Path.write_text

        def spy(self, *a, **k):
            seen.append(self.name)
            return real(self, *a, **k)
        with mock.patch.object(Path, "write_text", spy):
            MA._write_ptr("XAUUSD", {"active": {}, "history": [], "events": []})
            MA._write_ptr("XAUUSD", {"active": {"m": "a"}, "history": [], "events": []})
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1])                                 # 1.45.0: both SHADOW_ACTIVE.tmp
        self.assertTrue(all(s.startswith("SHADOW_ACTIVE.") and s.endswith(".tmp") for s in seen))
        self.assertEqual(MA.read_pointer("XAUUSD")["active"], {"m": "a"})
        self.assertEqual(sorted(p.name for p in MA.root("XAUUSD").glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
