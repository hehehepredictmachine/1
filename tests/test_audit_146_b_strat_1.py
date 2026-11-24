"""1.46 audit, group B_strat_1: forecast (Double Retest view, candle export checkpoints, long horizon, SHADOW service), scalp
(adapters, MTF archive chart, replay / SHADOW settlement, training status) and strategies (mirror codes / facts, backtest spread).
No orders, no terminal (the export runs on the MT5 simulator), no HTTP server. Strategy decision behaviour is NOT changed here."""
from __future__ import annotations

import json
import math
import random
import shutil
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent / "scalp"))

UTC = timezone.utc


# ============================================================================================== forecast/double_retest (chunk_11#13)
class TestDoubleRetestSellPublicView(unittest.TestCase):
    def _run(self, mirror=None, flag="lower_wick_rejection"):
        from test_forecast_integration import flags_at, m5_bars, m30_bars
        from masterquo.forecast.double_retest import DoubleRetest
        return DoubleRetest().update(m5_bars(mirror=mirror), m30_bars(mirror=mirror), flags_at(20, [flag]), 0.01)

    def test_sell_trace_label_and_trigger_are_in_real_prices(self):
        """chunk_11#13: SELL is computed on negated prices - the public view showed the trace of a real swing HIGH as 'LOW' and the raw
        'observed_retest_low' with a negative price in the trigger (that trigger goes to the signal facts)."""
        s = self._run(mirror=8280.0, flag="upper_wick_rejection")["states"]["SELL"]["recent"][0]
        self.assertEqual(s["state"], "RESEARCH_SETUP_COMPLETE")
        self.assertEqual(s["location"]["trace"], "HIGH")
        self.assertAlmostEqual(s["location"]["trace_price"], 4139.95)             # the real swing high just under L (mirror of BUY 4140.05)
        self.assertNotIn("observed_retest_low", s["trigger"])
        self.assertAlmostEqual(s["trigger"]["observed_retest_extreme"], 4139.9)
        self.assertTrue(all(v > 0 for v in s["trigger"].values() if isinstance(v, (int, float)) and not isinstance(v, bool)), s["trigger"])

    def test_buy_view_unchanged(self):
        s = self._run()["states"]["BUY"]["recent"][0]
        self.assertEqual(s["location"]["trace"], "LOW")
        self.assertAlmostEqual(s["trigger"]["observed_retest_low"], 4140.1)
        self.assertAlmostEqual(s["trigger"]["observed_retest_extreme"], 4140.1)

    def test_session_level_labels_are_swapped_for_sell(self):
        from masterquo.forecast import double_retest as DR
        self.assertEqual([DR._real_kind(k, -1) for k in ("LOW", "HIGH", "ASIA_LOW", "NEW_YORK_HIGH", "LONDON_LOW")],
                         ["HIGH", "LOW", "ASIA_HIGH", "NEW_YORK_LOW", "LONDON_HIGH"])
        self.assertEqual(DR._real_kind("ASIA_LOW", 1), "ASIA_LOW")


# ============================================================================================== forecast/service (chunk_11#12, #18)
class _FBridge:
    def __init__(self, m5, m30, age=0.0):
        self.m5, self.m30, self.symbol_info, self.age = m5, m30, {}, age

    def bars(self, tf, n, include_forming=False):
        return list(self.m5 if tf == "M5" else self.m30)

    def quote_status(self):
        return {"bid": 4140.0, "ask": 4140.2, "time_utc": None, "age_seconds": self.age}


class TestForecastServiceMissingFlags(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        self.db = Database()
        if hasattr(self.db, "migrate"):
            self.db.migrate()

    def tearDown(self):
        self.db.close()
        self.td.close()

    def _svc(self, bridge):
        from masterquo.forecast.service import ForecastService
        cfg = types.SimpleNamespace(forecast=types.SimpleNamespace(enabled=True, m5_bars=500, m30_bars=200, request_timeout_seconds=5),
                                    assets=types.SimpleNamespace(active="XAUUSD"), mt5=types.SimpleNamespace(symbol="XAUUSD-"))
        bus = types.SimpleNamespace(publish=lambda *a: None)
        log = types.SimpleNamespace(info=lambda *a, **k: None, warn=lambda *a, **k: None, error=lambda *a, **k: None)
        svc = ForecastService(types.SimpleNamespace(get=lambda: cfg), bridge, self.db, bus, log)
        svc.proc = types.SimpleNamespace(poll=lambda: None)                       # a running worker (answers are scripted below)
        return svc

    def test_worker_error_does_not_invalidate_double_retest_setups(self):
        """chunk_11#12: a worker DataError (no flags_tail) replayed the machine with {} flags - the completed setup was rewritten as
        INVALIDATED 'brak świecy potwierdzenia' and listeners were called with it."""
        from test_forecast_integration import SEQ, T0, iso, m5_bars, m30_bars
        m5, m30 = m5_bars(), m30_bars()
        br = _FBridge(m5, m30)
        svc = self._svc(br)
        seen = []
        svc.listeners.append(lambda setup, sym: seen.append(setup))
        flags = [{"time_open_utc": b["open_utc"].replace("Z", "+00:00"), "names": ["lower_wick_rejection"] if k == 20 else []}
                 for k, b in enumerate(m5)]
        svc._ask = lambda req, timeout: {"status": "SHADOW", "flags_tail": flags, "report": None, "model": None}
        svc.tick()
        first = svc.state["setup_v2"]["states"]["BUY"]["recent"][0]
        self.assertEqual(first["state"], "RESEARCH_SETUP_COMPLETE")
        self.assertEqual(len(seen), 1)
        # next closed M5, the worker answers CONTRACT_MISMATCH (no flags)
        br.m5 = m5 + [{"open_utc": iso(T0 + timedelta(minutes=30 * 60 + 5 * len(SEQ))), "o": 4141.5, "h": 4142, "l": 4141, "c": 4141.8, "tv": 50}]
        svc._ask = lambda req, timeout: {"status": "CONTRACT_MISMATCH", "reason": "CONTRACT_MISMATCH tick size", "report": None}
        svc.tick()
        st = svc.state["setup_v2"]
        self.assertEqual(st["FLAGS_STATE"], "UNAVAILABLE")
        self.assertEqual(st["states"]["BUY"]["recent"][0]["state"], "RESEARCH_SETUP_COMPLETE")
        self.assertEqual(len(seen), 1)                                            # no observer gets a result computed on missing flags
        self.assertEqual(svc.state["status"], "CONTRACT_MISMATCH")

    def test_missing_flags_on_first_answer_is_a_marked_empty_result(self):
        from test_forecast_integration import m5_bars, m30_bars
        svc = self._svc(_FBridge(m5_bars(), m30_bars()))
        svc._ask = lambda req, timeout: {"status": "FORECAST_UNAVAILABLE", "reason": "x"}
        svc.tick()
        st = svc.state["setup_v2"]
        self.assertEqual((st["FLAGS_STATE"], st["states"], st["can_submit_order"]), ("UNAVAILABLE", {}, False))

    def test_quote_with_zero_age_is_valid(self):
        """chunk_11#18: '(age or 99) <= 2' turned a fresh quote with age 0.0 into a stale one."""
        from test_forecast_integration import m5_bars, m30_bars
        got = {}
        for age, exp in ((0.0, True), (1.5, True), (None, False), (3.0, False)):
            svc = self._svc(_FBridge(m5_bars(), m30_bars(), age=age))
            svc._ask = lambda req, timeout: got.update(q=req["quote"]) or {"status": "SHADOW", "flags_tail": []}
            svc.tick()
            self.assertIs(got["q"]["valid"], exp, age)


# ============================================================================================== forecast/long_horizon (chunk_11#10, #11)
def _lh_path(n, seed=2, t0=1_700_000_000, step=3600):
    rnd = random.Random(seed)
    ts, px, p = [], [], 100.0
    for i in range(n):
        ts.append(t0 + i * step)
        p *= math.exp(rnd.gauss(0.0001, 0.004))
        px.append(p)
    return ts, px


class TestLongHorizon(unittest.TestCase):
    def test_stale_against_wall_clock_and_close_times(self):
        """chunk_11#10: as_of defaulted to the last bar, so age was always 0 and STALE unreachable; bars are open times (close one TF
        later). `now` / `bar_seconds` measure the real age and shift as_of to the observed close."""
        from masterquo.forecast import long_horizon as LH
        ts, px = _lh_path(24 * 300)
        old = LH.forecast(ts, px, "24h", now=ts[-1] + 3600 + 73 * 3600, bar_seconds=3600)
        self.assertEqual(old["status"], "STALE")
        self.assertEqual(old["as_of"], ts[-1] + 3600)                              # observation = close of the last bar
        fresh = LH.forecast(ts, px, "24h", now=ts[-1] + 3600 + 300, bar_seconds=3600)
        self.assertEqual(fresh["status"], "OK")
        self.assertEqual(fresh["log_return_quantiles"], LH.forecast(ts, px, "24h")["log_return_quantiles"])   # same distribution
        self.assertEqual(LH.forecast(ts, px, "24h")["status"], "OK")              # replay call without a clock: unchanged
        h4 = LH.forecast(ts, px, "24h", now=ts[-1] + 3600 * 4 + 3 * 3600, bar_seconds=4 * 3600)   # H4 bar closed 3 h ago: not stale
        self.assertEqual(h4["status"], "OK")

    def test_effective_samples_gate_the_calibrated_label(self):
        """chunk_11#11: samples every ~H/6 overlap ~6x; 'CALIBRATED' needed 30 raw calibration samples = ~5 independent windows."""
        from masterquo.forecast import long_horizon as LH
        ts, px = _lh_path(8000, seed=3)
        f = LH.forecast(ts, px, "72h")
        self.assertLess(f["samples_effective"], f["samples"])
        self.assertAlmostEqual(f["samples_effective"], int(f["samples"] * f["sample_spacing_seconds"] / 259200), delta=1)
        self.assertGreaterEqual(f["calib_samples"], 30)
        self.assertLess(f["calib_samples_effective"], 30)
        self.assertEqual(f["calibration"], "UNCALIBRATED")
        g = LH.forecast(*_lh_path(9600), "24h")
        self.assertGreaterEqual(g["calib_samples_effective"], 30)
        self.assertIn(g["calibration"], ("CALIBRATED", "UNCALIBRATED"))
        self.assertIsNotNone(g["calib_band_scale"])


# ============================================================================================== forecast/export (chunk_11#9)
class TestExportCheckpointsOfAnotherClockModel(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.root = Path(tempfile.mkdtemp(prefix="mq_exp_b1_"))
        from masterquo.diagnostics import ny_close_offset
        from masterquo.mt5.fake import BTCUSDT_SYN, SYN_MARKETS, FakeMT5
        off_now = ny_close_offset(time.time())                                     # NY_CLOSE must agree with the offset measured today
        self.fake = FakeMT5(markets=dict(SYN_MARKETS, **BTCUSDT_SYN), server_offset_hours=off_now / 3600)
        sys.modules["MetaTrader5"] = self.fake
        # a range in the OTHER US DST season: there NY_CLOSE (NY + 7 h) differs from today's fixed offset by 1 h
        self.rng = ("2026-09-01", "2026-09-04T00:00Z") if off_now == 7200 else ("2026-01-05", "2026-01-08T00:00Z")

    def tearDown(self):
        sys.modules.pop("MetaTrader5", None)
        shutil.rmtree(self.root, ignore_errors=True)
        self.td.close()

    def _export(self, out, model, ticks=0.0):
        from masterquo.forecast.export import export_candles
        return export_candles(1, str(out), model, ("M5",), "training", "XAUUSD", "XAUUSD-", date_from=self.rng[0], date_to=self.rng[1],
                              tick_days=ticks)

    def test_new_model_in_the_same_folder_does_not_reuse_old_utc_times(self):
        """chunk_11#9: a non-resumed export (other --dst-model, or after COMPLETE) reused out/chunks written with the previous model -
        CSV with the old UTC times under metadata of the new model."""
        import numpy as np
        a, b = self.root / "A", self.root / "B"
        self.assertEqual(self._export(a, "NY_CLOSE", ticks=0.05), 0)
        csv_ny = (a / "XAUUSD_M5.csv").read_text(encoding="utf-8")
        self.assertEqual(self._export(a, "UNIFORM", ticks=0.05), 0)               # same folder, another clock model
        self.assertEqual(self._export(b, "UNIFORM", ticks=0.05), 0)               # fresh folder = reference
        meta = json.loads((a / "source_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((a / "EXPORT_STATUS.json").read_text(encoding="utf-8"))["frozen"]["dst_model"], "UNIFORM", meta.keys())
        csv_a, csv_b = (a / "XAUUSD_M5.csv").read_text(encoding="utf-8"), (b / "XAUUSD_M5.csv").read_text(encoding="utf-8")
        self.assertNotEqual(csv_ny, csv_b)                                         # the two models really differ in this season
        self.assertEqual(csv_a, csv_b)
        for f in sorted((b / "ticks").glob("ticks_*.npz")):
            with np.load(a / "ticks" / f.name) as za, np.load(f) as zb:
                self.assertEqual(za["time_msc_utc"].tolist(), zb["time_msc_utc"].tolist(), f.name)
                self.assertEqual(str(za["clock_model"][0]), str(zb["clock_model"][0]))

    def test_checkpoint_checks(self):
        import numpy as np
        from masterquo.diagnostics import server_to_utc
        from masterquo.forecast.export import _chunk_matches, _ticks_match
        raw = 1788231600                                                           # 2026-09-01 server time
        row = (raw - 7200, 1.0, 2.0, 0.5, 1.5, 10, 12, raw, 0, None)
        self.assertTrue(_chunk_matches([row], "UNIFORM", 7200, server_to_utc))
        self.assertFalse(_chunk_matches([row], "UNIFORM", 10800, server_to_utc))
        self.assertFalse(_chunk_matches([row], "NY_CLOSE", 7200, server_to_utc))   # September: NY_CLOSE = +3 h
        self.assertTrue(_chunk_matches([row[:9]], "UNIFORM", 7200, server_to_utc))  # checkpoint from before 1.25 (no real_volume)
        srv = np.array([raw * 1000, raw * 1000 + 500], np.int64)
        arr = {"time_msc_utc": srv - 7200 * 1000, "time_msc_server": srv}
        self.assertTrue(_ticks_match(arr, "UNIFORM", 7200, server_to_utc))          # untagged file (before 1.46): checked by its ticks
        self.assertFalse(_ticks_match(arr, "NY_CLOSE", 7200, server_to_utc))
        self.assertFalse(_ticks_match({"time_msc_utc": srv[:0], "time_msc_server": srv[:0]}, "UNIFORM", 7200, server_to_utc))
        self.assertTrue(_ticks_match(dict(arr, clock_model=np.array(["UNIFORM|7200"])), "UNIFORM", 7200, server_to_utc))
        self.assertFalse(_ticks_match(dict(arr, clock_model=np.array(["NY_CLOSE|7200"])), "UNIFORM", 7200, server_to_utc))


# ============================================================================================== scalp/adapters (chunk_29#3)
class TestScalpAdapterExport(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _write(self, name, doc):
        from masterquo.scalp import adapters
        adapters.ext_dir().mkdir(parents=True, exist_ok=True)
        (adapters.ext_dir() / f"{name}.json").write_text(doc, encoding="utf-8")

    def test_naive_known_at_is_unavailable_not_an_exception(self):
        """chunk_29#3: a known_at without offset was compared with an aware 'now' outside the try -> TypeError in ScalpService.tick."""
        from masterquo.scalp import adapters
        now = datetime(2026, 11, 23, 10, 1, tzinfo=UTC)
        self._write("VOLATILITY_MASTER", json.dumps({"symbol": "XAUUSD-", "known_at": "2026-11-23T10:00:00", "values": {"x": 1.0}}))
        s = adapters.snapshot("VOLATILITY_MASTER", "XAUUSD-", now)
        self.assertEqual(s["status"], "UNAVAILABLE")
        self.assertIn("strefy", s["reason"])
        self.assertIsNone(s["values"])
        rows = adapters.all_snapshots("XAUUSD-", now)
        self.assertEqual(len(rows), len(adapters.ADAPTERS))

    def test_non_finite_values_are_null(self):
        from masterquo.scalp import adapters
        now = datetime(2026, 11, 23, 10, 1, tzinfo=UTC)
        self._write("VOLATILITY_MASTER", '{"symbol": "XAUUSD-", "known_at": "2026-11-23T10:00:00Z", "values": {"a": NaN, "b": Infinity, "c": 2}}')
        s = adapters.snapshot("VOLATILITY_MASTER", "XAUUSD-", now)
        self.assertEqual(s["status"], "UNVALIDATED")
        self.assertEqual(s["values"], {"a": None, "b": None, "c": 2.0})
        json.dumps(s, allow_nan=False)                                             # the API answer stays valid JSON

    def test_one_failing_adapter_does_not_stop_the_others(self):
        from masterquo.scalp import adapters

        class Ext:
            def status(self, *a):
                raise RuntimeError("broken ingest")
        rows = adapters.all_snapshots("XAUUSD-", datetime(2026, 11, 23, tzinfo=UTC), ext=Ext(), instrument="XAUUSD")
        by = {r["adapter"]: r for r in rows}
        self.assertEqual(by["IQ_GOLD_GANN"]["status"], "UNAVAILABLE")
        self.assertIn("RuntimeError", by["IQ_GOLD_GANN"]["reason"])
        self.assertEqual(by["VOLATILITY_MASTER"]["status"], "UNAVAILABLE")


# ============================================================================================== scalp/dashboard (chunk_29#9)
class TestArchivedChartRevisions(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from test_mtf_dashboard import Bridge, Bus, gen, scalp_stub
        from masterquo.db.database import Database
        from masterquo.scalp.dashboard import MTFDashboard
        self.end = datetime.now(UTC).replace(second=0, microsecond=0)
        self.bars = gen(self.end, n_m1=1500)
        self.bridge = Bridge(self.bars)
        self.db = Database()
        self.dash = MTFDashboard(scalp_stub(self.bars), self.bridge, Bus(), self.db)

    def tearDown(self):
        self.db.close()
        self.td.close()

    def test_revised_bars_of_the_series_are_reported(self):
        """chunk_29#9: the archived chart compared only the open time of the last bar - revised OHLC (also of earlier bars) were charted
        as the analysed series with status OK."""
        s = self.dash.build(self.bars, info={"name": "XAUUSD-", "digits": 2, "trade_tick_size": 0.01}, epoch=1, recent=[], nss_last=None)
        self.dash.cache.clear()
        c = self.dash.chart("M5", s["snapshot_id"])
        self.assertEqual((c["status"], c["bars_source"], c["revision_check"], c["revised_bars"]), ("OK", "BRIDGE_BUFFER_CUTOFF", "MATCHES_SNAPSHOT", []))
        b = self.bars["M5"][-4]
        b["c"] += 5.0
        b["revision"] = 1                                                           # the bridge re-read an EARLIER closed bar
        c = self.dash.chart("M5", s["snapshot_id"])
        self.assertEqual(c["revision_check"], "REVISED_SINCE_SNAPSHOT")
        self.assertEqual(c["revised_bars"], [b["open_utc"]])
        # snapshot archived before 1.46 (no per-series revisions): the last bar's revision is still compared
        body = json.loads(self.db.one("SELECT body FROM mtf_snapshots WHERE snapshot_id=?", (s["snapshot_id"],))["body"])
        body.pop("tf_series_revisions", None)
        self.db.execute("UPDATE mtf_snapshots SET body=? WHERE snapshot_id=?", (json.dumps(body), s["snapshot_id"]))
        self.assertEqual(self.dash.chart("M5", s["snapshot_id"])["revision_check"], "MATCHES_SNAPSHOT")
        self.bars["M5"][-1]["revision"] = 2
        c = self.dash.chart("M5", s["snapshot_id"])
        self.assertEqual((c["revision_check"], c["revised_bars"]), ("REVISED_SINCE_SNAPSHOT", [self.bars["M5"][-1]["open_utc"]]))


# ============================================================================================== scalp/replay + service._outcome
def _m1(rows, sp=0.1, t0=datetime(2026, 1, 1, 10, 0, tzinfo=UTC)):
    out = []
    for k, r in enumerate(rows):
        o, h, lo, c = r[:4]
        out.append({"open_utc": (t0 + timedelta(minutes=k)).isoformat().replace("+00:00", "Z"), "o": o, "h": h, "l": lo, "c": c,
                    "spread_price": r[4] if len(r) > 4 else sp})
    return out


class TestReplayLimitFillBar(unittest.TestCase):
    ROWS = [(2010, 2011, 2009.5, 2010.5), (2010, 2016, 2004.8, 2006), (2006, 2006.5, 2003, 2003.5), (2003.5, 2004, 2001, 2001.5),
            (2001.5, 2002, 2000.5, 2001)]

    def test_tp_on_the_intrabar_fill_bar_is_not_taken(self):
        """chunk_29#5: LIMIT_EDGE filled inside bar k; walk() took TP1 from the high of that bar although it may have come BEFORE the fill
        (net +10 while the price then fell to SL), and the cycle was not flagged ambiguous."""
        from masterquo.scalp import replay
        P = replay.Path(_m1(self.ROWS), None)
        plan = {"direction": "BUY", "entry_mode": "LIMIT_EDGE", "limit_price": 2005.0, "limit_wait_m1": 3}
        fl = replay.get_fill(plan, P, P.t[1], 0.0)
        self.assertEqual((fl["ok"], fl["i"], fl["fill"], fl["at_open"]), (True, 1, 2005.0, False))
        r = replay.walk(P, fl["i"], 1, 1.0, 2002.0, 2015.0, None, 1.0, 10 ** 10, {}, entry=fl["fill"], open_in_first_bar=fl["at_open"])
        self.assertEqual([e[3] for e in r["exits"]], ["SL"])
        self.assertTrue(r["ambiguous"])
        self.assertLess(r["mfe"], 2015.0 - 2005.0)                               # the fill bar's high is not counted as reached
        mk = replay.walk(P, 1, 1, 1.0, 2002.0, 2015.0, None, 1.0, 10 ** 10, {}, entry=2005.0)        # MARKET semantics unchanged
        self.assertEqual([e[3] for e in mk["exits"]], ["TP1"])

    def test_tp_with_close_beyond_it_is_taken(self):
        from masterquo.scalp import replay
        rows = list(self.ROWS)
        rows[1] = (2010, 2016, 2004.8, 2015.5)                                      # close beyond TP: reached after the fill
        P = replay.Path(_m1(rows), None)
        r = replay.walk(P, 1, 1, 1.0, 2002.0, 2015.0, None, 1.0, 10 ** 10, {}, entry=2005.0, open_in_first_bar=False)
        self.assertEqual(([e[3] for e in r["exits"]], r["ambiguous"]), (["TP1"], False))

    def test_limit_through_the_open_is_filled_at_the_open(self):
        from masterquo.scalp import replay
        rows = list(self.ROWS)
        rows[1] = (2004.0, 2016, 2003.9, 2006)
        fl = replay.get_fill({"direction": "BUY", "entry_mode": "LIMIT_EDGE", "limit_price": 2005.0, "limit_wait_m1": 3}, replay.Path(_m1(rows), None),
                             replay.Path(_m1(rows), None).t[1], 0.0)
        self.assertEqual((fl["fill"], fl["at_open"]), (2004.1, True))


class TestReplaySpreadUnknown(unittest.TestCase):
    def test_missing_spread_is_never_zero(self):
        """chunk_29#8 (replay part): a bar without spread_price was replayed with spread 0 (SELL exits on Bid, BUY limit at Bid)."""
        from masterquo.scalp import replay
        rows = [(2000, 2000.5, 1999.5, 2000), (2000, 2001, 1999, 2000.5, None), (2000.5, 2001, 1990, 1991)]
        P = replay.Path(_m1(rows), None)
        r = replay.walk(P, 0, -1, 1.0, 2005.0, 1995.0, None, 1.0, 10 ** 10, {}, entry=2000.0)
        self.assertTrue(r["spread_unknown"])
        self.assertEqual((r["exits"], r["open_at_end"]), ([], 1.0))
        ok = replay.walk(P, 0, 1, 1.0, 1995.0, 2000.8, None, 1.0, 10 ** 10, {}, entry=2000.1)   # BUY exits on Bid: spread not needed
        self.assertEqual([e[3] for e in ok["exits"]], ["TP1"])
        fl = replay.get_fill({"direction": "BUY", "entry_mode": "LIMIT_EDGE", "limit_price": 1999.2, "limit_wait_m1": 3}, P, P.t[0], 0.0)
        self.assertEqual(fl, {"ok": False, "reason": "SPREAD_UNKNOWN"})
        plan = {"zone": {"z_high": 2001.0, "z_low": 1999.0}}
        self.assertIsNone(replay.hedge_value(P, 0, 1, plan, 2000.0, 0.0, {"exits": []}, 10 ** 10, 1.0, {}, _prof()))


def _prof():
    from masterquo.scalp import strategy as st
    return st.load_profile()


class _ScalpCfg:
    def get(self):
        from masterquo.config import AppConfig
        c = AppConfig()
        c.scalp.commission_per_lot_side = 3.5
        return c


def _outcome_svc():
    from masterquo.scalp.service import ScalpService
    svc = ScalpService.__new__(ScalpService)
    svc.prof, svc.cfg_store, svc.inst = _prof(), _ScalpCfg(), "XAUUSD"
    svc.bridge = types.SimpleNamespace(symbol_info={"trade_contract_size": 100.0, "trade_tick_size": 0.01})
    return svc


class TestShadowOutcome(unittest.TestCase):
    def _P(self, rows, **kw):
        from masterquo.scalp import replay
        return replay.Path(_m1(rows, **kw), None)

    def test_market_fill_has_slippage_and_costs(self):
        """chunk_29#6: the SHADOW / ML / NSS settlement used the raw quote (no entry slippage), spread 0 when unknown and a cost-free risk."""
        from masterquo.scalp import replay
        svc = _outcome_svc()
        costs = svc._costs({})
        rows = [(2000, 2000.5, 1999.6, 2000.2), (2000.2, 2006, 2000.1, 2005.5)]
        P = self._P(rows)
        T = P.t[0]
        base = {"direction": "BUY", "decision_ts": T, "sl": 1995.0, "tp1": 2005.0, "tp2": 2008.0, "sizing": {"split": False}}
        st_, out = svc._outcome(P, dict(base, fill_shadow=2000.1, economics={"risk_per_unit": 5.2}))
        self.assertEqual(st_, "SETTLED")
        fill = 2000.1 + costs["slippage_price"]
        self.assertAlmostEqual(out["net_r"], replay.pnl(1, fill, 1.0, [(1.0, 2005.0 - costs["slippage_price"], 0, "TP1")], costs) / 5.2)
        st2, out2 = svc._outcome(P, dict(base, fill_shadow=None, economics=None))                 # ML / NSS snapshot without a quote
        fill2 = P.o[0] + P.sp[0] + costs["slippage_price"]
        risk2 = abs(fill2 - 1995.0) + 2 * costs["commission_price_side"] + 2 * costs["slippage_price"]
        self.assertEqual(st2, "SETTLED")
        self.assertAlmostEqual(out2["net_r"], replay.pnl(1, fill2, 1.0, [(1.0, 2005.0 - costs["slippage_price"], 0, "TP1")], costs) / risk2)

    def test_unknown_spread_and_chase_limit(self):
        svc = _outcome_svc()
        P = self._P([(2000, 2000.5, 1999.6, 2000.2, None), (2000.2, 2006, 2000.1, 2005.5)])
        base = {"direction": "BUY", "decision_ts": P.t[0], "sl": 1995.0, "tp1": 2005.0, "tp2": 2008.0, "sizing": {"split": False}}
        self.assertEqual(svc._outcome(P, base), ("NO_DATA", None))                 # was a BUY filled at Bid (spread 0)
        P2 = self._P([(2003, 2003.5, 2002.6, 2003.2), (2003.2, 2006, 2003.1, 2005.5)])
        chase = dict(base, decision_ts=P2.t[0], ref_close_bid=2000.0, spread_at_signal=0.1, chase_limit=0.5)
        self.assertEqual(svc._outcome(P2, chase), ("MISSED_LIMIT", None))
        sell = dict(base, direction="SELL", decision_ts=P2.t[0], sl=2010.0, tp1=2001.0, fill_shadow=2003.0)
        P3 = self._P([(2003, 2003.5, 2002.6, 2003.2), (2003.2, 2004, 2002.1, 2002.5, None), (2002.5, 2003, 2000, 2000.5)])
        self.assertEqual(svc._outcome(P3, dict(sell, decision_ts=P3.t[0])), ("NO_DATA", None))   # SELL exits on Ask: unknown spread

    def test_limit_edge_outcome_uses_the_intrabar_fill_rule(self):
        svc = _outcome_svc()
        P = self._P(TestReplayLimitFillBar.ROWS)
        plan = {"direction": "BUY", "decision_ts": P.t[1], "entry_mode": "LIMIT_EDGE", "limit_price": 2005.0, "limit_wait_m1": 3, "sl": 2002.0,
                "tp1": 2015.0, "tp2": 2020.0, "sizing": {"split": False}}
        st_, out = svc._outcome(P, plan)
        self.assertEqual(st_, "SETTLED")
        self.assertEqual([e["reason"] for e in out["exits"]], ["SL"])
        self.assertTrue(out["ambiguous"])


class TestScalpTrainingStatus(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_damaged_report_files_do_not_raise(self):
        """chunk_29#7: TRAINING_STATUS.json / runs/*/report.json / replay/*/summary.json were parsed without error handling - one
        interrupted write sent ScalpService into ERROR_RECOVERY on every M1."""
        svc = _outcome_svc()
        d = svc._root()
        for rel in ("TRAINING_STATUS.json", "runs/R1/report.json", "replay/X1/summary.json"):
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text('{"summary": {"a": 1', encoding="utf-8")
        tr = svc.training_status()
        self.assertIsNone(tr["status_file"])
        self.assertIsNone(tr["last_run"])
        self.assertIsNone(tr["last_replay"])
        self.assertEqual(sorted(tr["unreadable_files"]), ["R1/report.json", "X1/summary.json", "XAUUSD/TRAINING_STATUS.json"]
                         if d.name == "XAUUSD" else sorted(tr["unreadable_files"]))
        self.assertEqual(len(tr["unreadable_files"]), 3)
        svc.registry = lambda: {"active": None, "runs": {}}
        self.assertEqual(svc.statuses()["HEDGE_VALID"]["basis"], "NOT_EVALUATED")
        (d / "replay" / "X1" / "summary.json").write_text(json.dumps({"strategy": {"status": "S"}}), encoding="utf-8")
        self.assertEqual(svc.training_status()["last_replay"], {"strategy": {"status": "S"}})


class TestScalpRiskReferenceWrite(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_reference_is_written_atomically_and_values_unchanged(self):
        """focus_X3#8 (value-neutral part): risk_reference.json is replaced atomically and only when the day / week changes."""
        from masterquo.scalp import service as mod
        svc = _outcome_svc()
        calls = []
        orig = mod._atomic_write_text
        mod._atomic_write_text = lambda p, t: calls.append(p) or orig(p, t)
        try:
            ok, why = svc._loss_limits({"equity": 10000.0})
            self.assertTrue(ok, why)
            ok2, why2 = svc._loss_limits({"equity": 9900.0})                      # same day: no rewrite, the reference stays 10000
        finally:
            mod._atomic_write_text = orig
        self.assertEqual(len(calls), 1)
        self.assertIn("dzień 1.00%", why2)
        self.assertEqual(json.loads((svc._root() / "risk_reference.json").read_text(encoding="utf-8"))["day_equity"], 10000.0)
        self.assertEqual([p.name for p in svc._root().iterdir() if ".tmp" in p.name], [])


class TestScalpEvaluatePricedSnapshot(unittest.TestCase):
    def test_ml_and_nss_get_fill_and_economics(self):
        """chunk_29#6 (3): ml_scalp() / neural() got the plan BEFORE fill_shadow / economics were added - every ML / NSS sample had both
        None and its label was settled without entry costs."""
        import scenario as S
        from masterquo.db.database import Database
        from masterquo.scalp import strategy as st
        from masterquo.scalp.service import ScalpService
        td = TempData()
        try:
            p = _prof()
            p["context_filter"]["enabled"]["value"] = False
            bars, info = S.build(p)
            ret = next(k for k, b in enumerate(bars) if b["open_utc"] == info["retest_time"])
            live = bars[:ret + 1]
            now = datetime.fromtimestamp(st.ts(live[-1]["open_utc"]) + 61, UTC)

            class Bridge:
                session_epoch = 1
                symbol_info = {"trade_tick_size": 0.01, "point": 0.01, "trade_contract_size": 100.0, "volume_min": 0.01, "volume_step": 0.01,
                               "volume_max": 50, "currency_base": "XAU", "currency_profit": "USD"}

                def bars(self, tf, limit, include_forming=False):
                    src = live if tf == "M1" else [dict(b, spread=10) for b in S.m5_of(live)] if tf == "M5" else []
                    return [dict(b, spread=10) for b in src][-limit:] if tf == "M1" else src

                def quote_status(self):
                    return {"bid": live[-1]["c"], "ask": live[-1]["c"] + 0.1, "age_seconds": 0.5}

                def account_status(self):
                    return {"equity": 10000.0, "margin_mode": "HEDGING"}

            got = {}

            class ML:
                def on_scalp_candidate(self, plan, **kw):
                    got["ml"] = plan
                    return {"status": "NO_MODEL"}

                def scalp_pending(self, inst):
                    return []

            class NSS:
                last = None

                def on_m1(self, *a, **k):
                    pass

                def submit(self, plan, bars, **kw):
                    got["nss"] = plan
                    return {"status": "QUEUED"}

                def pending(self):
                    return []

            db = Database()
            svc = ScalpService(_ScalpCfg(), Bridge(), db, types.SimpleNamespace(publish=lambda *a: None),
                               types.SimpleNamespace(info=lambda *a: None, error=lambda *a: None), news=None)
            svc.prof = p
            svc.ml, svc.nss = ML(), NSS()
            import masterquo.scalp.service as mod
            orig = mod.time.time
            mod.time.time = lambda: now.timestamp()
            try:
                svc.tick()
            finally:
                mod.time.time = orig
            db.close()
            rows = svc.recent()
            self.assertEqual(len(rows), 1)
            for k in ("ml", "nss"):
                self.assertEqual(got[k]["fill_shadow"], rows[0]["plan"]["fill_shadow"], k)
                self.assertIsNotNone(got[k]["fill_shadow"], k)
                self.assertEqual(got[k]["economics"], rows[0]["plan"]["economics"], k)
                self.assertIsNotNone(got[k]["economics"], k)
        finally:
            td.close()


# ============================================================================================== strategies/base (chunk_33#4, #5)
def _tf_bars(n=40, t0=datetime(2026, 1, 5, tzinfo=UTC)):
    out, px = [], 100.0
    for k in range(n):
        px += 0.3 if (k // 7) % 2 else -0.2
        out.append({"open_utc": (t0 + timedelta(minutes=5 * k)).isoformat().replace("+00:00", "Z"), "o": px - 0.1, "h": px + 0.6, "l": px - 0.7,
                    "c": px, "tv": 10, "closed": True})
    return out


class TestMirrorCodesAndFacts(unittest.TestCase):
    def test_non_directional_codes_are_not_mirrored(self):
        """chunk_33#4: 'RR_NET_TOO_LOW' became 'RR_NET_TOO_HIGH' on SHORT (S12 checklist then showed RR as met) and 'ADX_BELOW_20'
        became 'ADX_ABOVE_20' (ADX has no direction)."""
        from masterquo.strategies.base import mirror_code
        for c in ("RR_NET_TOO_LOW", "ADX_BELOW_20", "ADX_BELOW_22.5", "SCORE_BELOW_EARLY_60"):
            self.assertEqual(mirror_code(c), c)
        self.assertEqual(mirror_code("REACTION_BAR_CLOSE_ABOVE_PRIOR_HIGH"), "REACTION_BAR_CLOSE_BELOW_PRIOR_LOW")   # directional: mirrored
        self.assertEqual(mirror_code("KAMA_NOT_RISING"), "KAMA_NOT_FALLING")

    def test_short_facts_keep_their_labels(self):
        """chunk_33#5: after the reflection back, S01-S10 SHORT facts had upper / lower values under swapped keys ('Górna granica
        kanału' = the lower edge); S07 range_top_px held the range bottom."""
        from masterquo.strategies.base import Draft, MarketView, Strategy, TFView

        class Probe(Strategy):
            id = "SX"

            def detect_long(self, view, p):
                v = view.tfs["M5"]
                hi, lo = max(v.h), min(v.l)
                return [Draft(strategy_id="SX", direction="LONG", timeframe="M5", phase="WATCH", structure_key="k", event_key="E:LONG",
                              anchor_time=None, entry_plan=None, invalidation_level=None,
                              facts={"upper_px": hi, "lower_px": lo, "level_px": lo, "range_top_px": hi, "er": 0.3},
                              missing=["RR_NET_TOO_LOW", "ADX_BELOW_20", "CLOSE_ABOVE_LEVEL_PLUS_BUFFER"])]
        bars = _tf_bars()
        view = MarketView(symbol="XAUUSD-", as_of=bars[-1]["open_utc"], tfs={"M5": TFView("M5", bars)}, bid=bars[-1]["c"], ask=bars[-1]["c"] + 0.2,
                          point=0.01)
        out = {d.direction: d for d in Probe().detect(view, {})}
        hi, lo = max(b["h"] for b in bars), min(b["l"] for b in bars)
        lg, sh = out["LONG"].facts, out["SHORT"].facts
        self.assertEqual((lg["upper_px"], lg["lower_px"], lg["range_top_px"]), (hi, lo, hi))
        self.assertAlmostEqual(sh["upper_px"], hi, places=4)
        self.assertAlmostEqual(sh["lower_px"], lo, places=4)
        self.assertAlmostEqual(sh["level_px"], hi, places=4)                       # failed breakout ABOVE resistance (label 'Poziom')
        self.assertNotIn("range_top_px", sh)
        self.assertAlmostEqual(sh["range_bottom_px"], lo, places=4)
        self.assertEqual(sh["er"], 0.3)
        self.assertEqual(out["SHORT"].missing, ["RR_NET_TOO_LOW", "ADX_BELOW_20", "CLOSE_BELOW_LEVEL_PLUS_BUFFER"])

    def test_dead_helpers_removed(self):
        """chunk_33#12: helpers without any caller in backend / tests / tools."""
        from masterquo.strategies import base, common
        for name in ("stop_with_spread", "last_swing", "mirror_ok"):
            self.assertFalse(hasattr(common, name), name)
        self.assertFalse(hasattr(base.Strategy, "tick_round"))
        from masterquo.forecast import export
        self.assertFalse(hasattr(export, "TFS") or hasattr(export, "TRAINING_TFS"))


# ============================================================================================== strategies/ema_pullback_backtest (chunk_33#8)
class TestBacktestSpreadUnknown(unittest.TestCase):
    def _run(self, spread):
        from masterquo.strategies import ema_pullback_backtest as bt, ema_pullback_core as core
        rows = [[100, 100.5, 99.5, 100]] * 3 + [[100.2, 100.4, 100.1, 100.3], [100.3, 104, 100.2, 103.9], [104, 104, 103, 103.5]]
        bars = [dict({"t": f"2026-01-01T{i // 4:02d}:{(i % 4) * 15:02d}:00Z", "o": r[0], "h": r[1], "l": r[2], "c": r[3]},
                     **({} if spread is None else {"spread": spread})) for i, r in enumerate(rows)]
        mach = core.MachineResult(events=[core.Event(2, "CONFIRM", "LONG", 1, ref_price=100.0, stop=99.0)])
        return bt.simulate(bars, mach, core.Params(), bt.ExecModel(mode="MT5", slippage_ticks=0), "FIXED")

    def test_missing_spread_is_counted_and_marked(self):
        """chunk_33#8: the MT5 model used spread 0 for bars without the spread field, with no trace in the result."""
        r = self._run(None)
        self.assertEqual(r["diag"]["spread_missing_bars"], 6)
        self.assertTrue(r["spread_cost_status"].startswith("NOT_VERIFIED"), r["spread_cost_status"])
        ok = self._run(10)
        self.assertEqual((ok["diag"]["spread_missing_bars"], ok["spread_cost_status"]), (0, "COMPLETE"))
        self.assertEqual(r["bt_version"], "MQ-EMA-PULLBACK-BT-1.0.0")
        self.assertEqual([t.fill_price for t in r["trades"]], [t.fill_price for t in self._run(0)["trades"]])   # values unchanged


if __name__ == "__main__":
    unittest.main()
