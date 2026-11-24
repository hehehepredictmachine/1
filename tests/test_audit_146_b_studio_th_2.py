"""1.46 audit group B_studio_th_2 - Training Center (trainhub): dataset / features / inference / jobs / pipeline / registry.
Each test fails on the 1.45.0 version of the file it guards and passes after the fix. No HTTP server, no real training run (tiny fake
packages; the slow checks of activation are patched where only the registry bookkeeping is tested)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

import _env
import numpy as np
from _env import TempData, wait_for
from masterquo.marketdata import export as EX
from masterquo.marketdata.sources import DirectSource
from masterquo.marketdata.store import Store, iso
from masterquo.mt5.fake import FakeMT5
from masterquo.trainhub import dataset as DS
from masterquo.trainhub import features as F
from masterquo.trainhub import pipeline as P
from masterquo.trainhub import registry as R

DAY = 86400
COLS = ("time", "open", "high", "low", "close", "tick_volume", "spread")


# ------------------------------------------------------------------ helpers
def candles(times: list[int], seed: int = 1, start: float = 2000.0) -> dict:
    """Candles at the given open times (random walk)."""
    rng = np.random.default_rng(seed)
    c = start + np.cumsum(rng.normal(0, 0.5, len(times)))
    o = np.concatenate([[start], c[:-1]])
    return {"time": [int(t) for t in times], "open": o.tolist(), "high": (np.maximum(o, c) + 0.2).tolist(), "low": (np.minimum(o, c) - 0.2).tolist(),
            "close": c.tolist(), "tick_volume": [100.0] * len(times), "spread": [20.0] * len(times)}


def aggregate(base: dict, htf_s: int, upto: float | None = None) -> dict:
    """Higher-TF candles built from the base candles (only periods closed by `upto`)."""
    groups: dict[int, list[int]] = {}
    for i, t in enumerate(base["time"]):
        groups.setdefault(t // htf_s * htf_s, []).append(i)
    out = {k: [] for k in COLS}
    for b, ix in sorted(groups.items()):
        if upto is not None and b + htf_s > upto:
            continue
        out["time"].append(b)
        out["open"].append(base["open"][ix[0]])
        out["high"].append(max(base["high"][i] for i in ix))
        out["low"].append(min(base["low"][i] for i in ix))
        out["close"].append(base["close"][ix[-1]])
        out["tick_volume"].append(sum(base["tick_volume"][i] for i in ix))
        out["spread"].append(20.0)
    return out


def m5_set(times: list[int], htf_upto: float | None = None) -> dict:
    base = candles(times)
    last_close = times[-1] + 300
    lim = last_close if htf_upto is None else min(htf_upto, last_close)
    return {"M5": base, "M15": aggregate(base, 900, lim), "M30": aggregate(base, 1800, lim)}


class FakeStore:
    """Store.read semantics (start inclusive, end exclusive) over in-memory columns."""

    def __init__(self, cols: dict, man: dict | None = None):
        self.cols, self.man = cols, man if man is not None else {"costs": {"spread": {"point": 0.01}}, "files": {}}

    def read(self, inst, tf, start=None, end=None):
        c = self.cols.get(tf) or {k: [] for k in COLS}
        keep = [i for i, t in enumerate(c["time"]) if (start is None or t >= start) and (end is None or t < end)]
        return {k: [v[i] for i in keep] for k, v in c.items()}

    def manifest(self, inst):
        return self.man


CFG = {"base_tf": "M5", "horizon": 6, "k_atr": 0.25, "commission_price": 0.0, "slippage_price": 0.0}


def real_store(days: int = 8) -> Store:
    f = FakeMT5(history_days=days + 4)
    f.initialize()
    st = Store()
    EX.run(DirectSource(f, offset=3 * 3600, offset_basis="TEST"), st, "XAUUSD", "XAUUSD-", timeframes=("M5", "M15", "M30"),
           lookback_days=days, sleep=lambda s: None)
    return st


def fake_pkg(inst: str = "XAUUSD", seed: int = 0) -> str:
    """A minimal package through the real save_package (registry write path); the model itself is never used here."""
    trained = {"model": None, "result": {"model_id": "TH_BASELINE", "params": {"s": seed}, "temperature": 1.0, "decision_threshold": 0.2,
                                         "holdout": {}, "walk_forward": {}, "trading_eval_holdout": {}, "sample": {"X": [], "p_raw": []}}}
    return R.save_package(inst, {"base_tf": "M5", "horizon": 6, "k_atr": 0.25}, trained, {"hash": "h"}, {})["version"]


KEY = "TH_BASELINE_M5_H6"


class Tmp(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)


# ------------------------------------------------------------------ chunk_36#6 point never guessed
class TestPointNeverGuessed(Tmp):
    def test_dataset_refuses_unknown_point_and_takes_an_explicit_one(self):
        st = real_store(6)
        man = st.manifest("XAUUSD")
        man["costs"]["spread"]["point"] = None                 # export._finish after a failed symbol_info
        man["symbol_spec"] = {}
        st.write_manifest("XAUUSD", {"costs": man["costs"], "symbol_spec": man["symbol_spec"]})
        cfg = P.config({"base_tf": "M5", "horizon": 6}, st.manifest("XAUUSD"))
        self.assertIsNone(cfg["point"])                        # 1.45.0: 0.01 silently
        self.assertEqual(cfg["cost_status"]["spread"], "POINT_UNKNOWN")
        with self.assertRaises(DS.InsufficientData) as cm:
            DS.build(st, "XAUUSD", cfg)
        self.assertIn("point", str(cm.exception))
        cfg2 = P.config({"base_tf": "M5", "horizon": 6, "point": 0.001}, st.manifest("XAUUSD"))
        ds = DS.build(st, "XAUUSD", cfg2)
        self.assertEqual(ds["point"], 0.001)
        with self.assertRaises(ValueError):
            P.config({"point": -1}, st.manifest("XAUUSD"))


# ------------------------------------------------------------------ chunk_36#8 ISO range bounds
class TestIsoRangeBounds(Tmp):
    def test_build_and_stage_dataset_accept_iso(self):
        st = real_store(6)
        t = st.read("XAUUSD", "M5")["time"]
        mid = t[len(t) // 3]
        cfg = P.config({"base_tf": "M5", "horizon": 6, "start": iso(mid)}, st.manifest("XAUUSD"))
        a = DS.build(st, "XAUUSD", cfg, iso(mid), None)                        # 1.45.0: TypeError int >= str
        b = DS.build(st, "XAUUSD", cfg, mid, None)
        np.testing.assert_array_equal(a["t"], b["t"])
        self.assertGreaterEqual(int(a["t"][0]), mid)
        ds, desc = P.stage_dataset(st, "XAUUSD", cfg)
        self.assertEqual(desc["config"]["start"], iso(mid))                      # REPRODUCE / dataset.json keep the ISO text
        self.assertGreaterEqual(int(ds["t"][0]), mid)

    def test_bad_date_is_a_value_error(self):
        st = real_store(3)
        with self.assertRaises(ValueError):
            DS.build(st, "XAUUSD", dict(CFG, point=0.01), "31.01.2026", None)
        with self.assertRaises(ValueError):
            P.config({"start": "jutro"}, st.manifest("XAUUSD"))
        with self.assertRaises(ValueError):
            P.config({"start": "2026-02-01", "end": "2026-01-01"}, st.manifest("XAUUSD"))


# ------------------------------------------------------------------ chunk_36#10 parameter ranges
class TestConfigParameterRanges(unittest.TestCase):
    MAN: ClassVar[dict] = {"costs": {"spread": {"point": 0.01}}}

    def test_out_of_range_params_rejected(self):
        for bad in ({"holdout_frac": 0}, {"holdout_frac": 1.5}, {"holdout_frac": "abc"}, {"grid_limit": -1}, {"grid_limit": 0},
                    {"n_folds": 0}, {"n_folds": 2.5}, {"min_train": 0}, {"min_samples": -5}, {"embargo_bars": -1}, {"time_budget_s": -1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                P.config(bad, self.MAN)
        for prof in (None, *P.PROFILES):
            P.config({"profile": prof} if prof else {}, self.MAN)                 # every built-in profile stays valid
        cfg = P.config({"n_folds": "4", "grid_limit": 3, "holdout_frac": 0.25}, self.MAN)
        self.assertEqual((cfg["n_folds"], cfg["grid_limit"], cfg["holdout_frac"]), (4, 3, 0.25))

    def test_submit_rejects_bad_params_up_front(self):
        from masterquo.trainhub import jobs as J
        td = TempData()
        self.addCleanup(td.close)
        tc = J.TrainingCenter(None, None, poll_s=0.05)
        self.addCleanup(tc.db.c.close)
        tc.start = lambda: None                                                  # no queue thread / worker process here
        for kind, bad in (("TRAIN", {"holdout_frac": 0}), ("FULL", {"grid_limit": -1}), ("DATASET", {"start": "jutro"}),
                          ("TRAIN", {"profile": "turbo"})):
            with self.subTest(kind=kind, bad=bad), self.assertRaises(ValueError):    # 1.45.0: QUEUED, then FAILED / IndexError in the worker
                tc.submit(kind, "XAUUSD", bad)
        self.assertEqual(tc.list(), [])
        ok = tc.submit("FULL", "XAUUSD", {"models": ["TH_BASELINE", "TH_LOGREG", "TH_HGB"], "base_tf": "M5", "horizon": 6, "k_atr": 0.25,
                                          "mode": "incremental", "timeframes": ["M1", "M5", "M15", "M30"], "lookback_days": 90})   # panel defaults
        self.assertEqual(ok["status"], "QUEUED")

    def test_splits_guard_instead_of_index_error(self):
        n = 5000
        ds = {"y": np.zeros(n, dtype=np.int64), "t": np.arange(n, dtype=np.int64) * 300, "label_end": np.arange(n, dtype=np.int64) * 300 + 2100}
        for hf in (0.0, 1.5):
            with self.subTest(holdout_frac=hf), self.assertRaises(ValueError):    # 1.45.0: IndexError / absurd split
                DS.splits(ds, holdout_frac=hf, n_folds=4, embargo_bars=6, step=300, min_samples=2000, min_train=500)


# ------------------------------------------------------------------ chunk_36#7 frozen higher-TF features
class TestStaleHigherTimeframe(unittest.TestCase):
    def test_rows_with_frozen_htf_are_dropped(self):
        t0 = 1_790_000_000 // 1800 * 1800
        times = [t0 + i * 300 for i in range(20 * 288)]                         # M5 for 20 days ...
        cols = m5_set(times, htf_upto=t0 + 3 * DAY)                              # ... M15 / M30 only for the first 3 days
        ds = DS.build(FakeStore(cols), "XAUUSD", CFG)
        last_m30_close = cols["M30"]["time"][-1] + 1800
        self.assertLessEqual(int(ds["t"].max()) + 300, last_m30_close + 1800)    # 1.45.0: rows up to day 20 with day-3 M30 values
        self.assertGreater(ds["dropped"]["stale_htf"], 4000)
        self.assertGreater(ds["rows_usable"], 600)

    def test_weekend_and_session_break_are_not_stale(self):
        t0 = 1_790_000_000 // DAY * DAY
        times = []
        for d in range(12):
            if d in (5, 6):
                continue                                                         # weekend
            times += [t0 + d * DAY + i * 300 for i in range(288) if not 22 * 12 <= i < 23 * 12]   # daily 1 h break
        cols = m5_set(times)
        stale = F.htf_stale(cols, "M5")
        self.assertFalse(stale.any())
        ds = DS.build(FakeStore(cols), "XAUUSD", CFG)
        self.assertEqual(ds["dropped"]["stale_htf"], 0)
        _, X, _ = F.build(cols, "M5", 0.01)                                      # the feature function itself is unchanged
        self.assertEqual(X.shape, (len(times), len(F.names("M5"))))


# ------------------------------------------------------------------ inference fixtures
class _Cfg:
    class A:
        broker_symbol = "XAUUSD-"

    def get(self):
        return type("C", (), {"assets": type("As", (), {"mappings": {"XAUUSD": _Cfg.A(), "BTC": _Cfg.A()}})()})()


class Bridge:
    def __init__(self, cols: dict, point: float | None = 0.01):
        self.cols, self.point = cols, point

    def symbol_bars(self, sym, tf, n):
        c = self.cols[tf]
        return [{"open_utc": iso(c["time"][i]), "o": c["open"][i], "h": c["high"][i], "l": c["low"][i], "c": c["close"][i],
                 "tv": c["tick_volume"][i], "spread": c["spread"][i], "closed": True} for i in range(max(0, len(c["time"]) - n), len(c["time"]))]

    def symbol_meta(self, sym):
        return {"point": self.point} if self.point else {}


class InferenceCase(unittest.TestCase):
    def make(self, point_meta=0.01, conf_point=0.01):
        from masterquo.trainhub.inference import TrainhubInference
        t0 = 1_790_000_000 // 1800 * 1800
        cols = m5_set([t0 + i * 300 for i in range(900)])
        self.close_t = cols["M5"]["time"][-1] + 300
        self.now = [self.close_t + 5.0]
        inf = TrainhubInference(_Cfg(), Bridge(cols, point_meta), clock=lambda: self.now[0])
        conf = {"base_tf": "M5", "horizon": 6, "model_id": "TH_LOGREG"} | ({"point": conf_point} if conf_point else {})
        inf.cache[("XAUUSD", "TH_LOGREG_M5_H6", "v1")] = ({"estimator": None, "temperature": 1.0}, conf, {"names": F.names("M5")})
        p = mock.patch.object(R, "predict_loaded", return_value=np.array([[0.2, 0.3, 0.5]]))
        p.start()
        self.addCleanup(p.stop)
        return inf


# ------------------------------------------------------------------ chunk_36#1 stored READY re-checked for freshness
class TestInferenceFreshness(InferenceCase):
    def test_cached_ready_becomes_stale_without_a_new_candle(self):
        inf = self.make()
        p1 = inf.predict("XAUUSD", "TH_LOGREG_M5_H6", "v1")
        self.assertEqual((p1["state"], p1["data_quality"]), ("READY", "OK"))
        self.now[0] = self.close_t + 3 * DAY                                     # market closed, same candles
        p2 = inf.predict("XAUUSD", "TH_LOGREG_M5_H6", "v1")
        self.assertEqual((p2["state"], p2["data_quality"]), ("ERROR", "STALE"))  # 1.45.0: READY / OK for days
        self.assertIsNone(p2["result"])
        self.assertGreater(p2["freshness_s"], 2 * DAY)
        self.assertEqual(inf.predictions("XAUUSD")[0]["state"], "ERROR")


# ------------------------------------------------------------------ chunk_36#6 (inference side) point unknown / different
class TestInferencePoint(InferenceCase):
    def test_same_point_ready(self):
        self.assertEqual(self.make().predict("XAUUSD", "TH_LOGREG_M5_H6", "v1")["state"], "READY")

    def test_point_unknown_is_not_guessed(self):
        p = self.make(point_meta=None, conf_point=None).predict("XAUUSD", "TH_LOGREG_M5_H6", "v1")
        self.assertEqual(p["state"], "ERROR")                                    # 1.45.0: READY on point 0.01
        self.assertIn("point", p["unavailable_reason"])

    def test_training_point_used_when_broker_meta_has_none(self):
        self.assertEqual(self.make(point_meta=None, conf_point=0.01).predict("XAUUSD", "TH_LOGREG_M5_H6", "v1")["state"], "READY")


# ------------------------------------------------------------------ chunk_36#12 clean stop -> INTERRUPTED
class FakeProc:
    pid = 424242

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class TestJobStop(Tmp):
    def run_child(self, after_start):
        from masterquo.trainhub import jobs as J
        tc = J.TrainingCenter(None, None, poll_s=0.05)
        self.addCleanup(tc.db.c.close)
        jid = "TJ-TEST-1"
        tc.db.execute("INSERT INTO jobs(id, kind, instrument, params, status, created_at, log) VALUES (?,?,?,?,?,?,?)",
                      (jid, "TRAIN", "XAUUSD", "{}", "RUNNING", time.time(), str(Path(self.td.dir) / "j.log")))
        proc = FakeProc()
        with mock.patch.object(J.subprocess, "Popen", return_value=proc):
            th = threading.Thread(target=tc._child, args=(jid,), daemon=True)
            th.start()
            self.assertTrue(wait_for(lambda: (tc.get(jid) or {}).get("pid") == proc.pid, 10, 0.02))
            after_start(tc, jid)
            th.join(10)
        self.assertFalse(th.is_alive())
        return tc.get(jid)

    def test_clean_stop_is_interrupted_not_failed(self):
        r = self.run_child(lambda tc, jid: tc.stop())
        self.assertEqual(r["status"], "INTERRUPTED")                             # 1.45.0: FAILED "kodem -15"
        self.assertIsNotNone(r["finished_at"])

    def test_cancel_still_cancelled(self):
        from masterquo.trainhub import jobs as J
        r = self.run_child(lambda tc, jid: J.update(tc.db, jid, cancel=1))
        self.assertEqual(r["status"], "CANCELLED")


# ------------------------------------------------------------------ chunk_36#9 EVALUATE ids
class TestEvaluateIds(Tmp):
    def test_stage_evaluate_rejects_path_ids(self):
        evil = R.root() / "evil" / "v1"
        evil.mkdir(parents=True)
        for key, ver in (("../../evil", "v1"), ("K", "../../../evil/v1"), ("K/..", "v1"), (None, "v1")):
            with self.subTest(key=key, ver=ver), self.assertRaises(ValueError):   # 1.45.0: path built and loaded (IncompatiblePackage)
                P.stage_evaluate(FakeStore({}), "XAUUSD", key, ver)
        self.assertEqual(list(evil.parent.iterdir()), [evil])                    # nothing written next to it

    def test_submit_checks_ids_and_registry(self):
        from masterquo.trainhub import jobs as J
        tc = J.TrainingCenter(None, None, poll_s=0.05)
        self.addCleanup(tc.db.c.close)
        tc.start = lambda: None                                                  # no queue thread / worker process here
        ver = fake_pkg()
        for params in ({"model_key": "../x", "version": ver}, {"model_key": KEY, "version": "../../v"}, {}, {"model_key": KEY, "version": "nope"}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                tc.submit("EVALUATE", "XAUUSD", params)
        j = tc.submit("EVALUATE", "XAUUSD", {"model_key": KEY, "version": ver})
        self.assertEqual(j["status"], "QUEUED")


class TestEvaluateUsesPackagePoint(Tmp):
    def test_store_without_point_falls_back_to_the_package_point(self):
        st = real_store(4)
        trained = {"model": None, "result": {"model_id": "TH_BASELINE", "params": {}, "temperature": 1.0, "decision_threshold": 0.2,
                                             "holdout": {}, "walk_forward": {}, "trading_eval_holdout": {}, "sample": {"X": [], "p_raw": []}}}
        cfg = {"base_tf": "M5", "horizon": 6, "k_atr": 0.25, "commission_price": 0.0, "slippage_price": 0.0, "point": 0.01}
        ver = R.save_package("XAUUSD", cfg, trained, {"hash": "h", "range_utc": [None, iso(4_000_000_000)]}, {})["version"]
        man = st.manifest("XAUUSD")
        man["costs"]["spread"]["point"] = None
        st.write_manifest("XAUUSD", {"costs": man["costs"], "symbol_spec": {}})
        r = P.stage_evaluate(st, "XAUUSD", KEY, ver)                             # no InsufficientData: config.json knows the point
        self.assertEqual(r["status"], "NO_NEW_DATA")


# ------------------------------------------------------------------ chunk_36#2 registry read-modify-write under a lock
_OK = {"ok": True, "checks": []}


class TestRegistryLock(Tmp):
    def test_activation_keeps_a_version_saved_meanwhile(self):
        v1 = fake_pkg(seed=1)
        added = []

        def slow_prediction_test(*a, **k):                                       # the training process saves a package meanwhile
            added.append(fake_pkg(seed=2))
            return {"ok": True}
        with mock.patch.object(R, "compatibility", return_value=_OK), mock.patch.object(R, "prediction_test", side_effect=slow_prediction_test):
            self.assertTrue(R.activate("XAUUSD", KEY, v1)["ok"])
        reg = R.registry("XAUUSD")
        self.assertEqual({v["version"] for v in reg["versions"][KEY]}, {v1, added[0]})   # 1.45.0: the new version vanished
        self.assertEqual(reg["active"][KEY], v1)

    def test_lock_excludes_another_process(self):
        fake_pkg()
        code = ("import sys, time; sys.path.insert(0, sys.argv[1]); from masterquo.trainhub import registry as R\n"
                "with R.reg_lock('XAUUSD'):\n    print('locked', flush=True); time.sleep(1.5)\n")
        env = dict(os.environ, MASTERQUO_DATA_DIR=self.td.dir, PMW_BOOTSTRAP="0")
        p = subprocess.Popen([sys.executable, "-c", code, str(_env.ROOT / "backend")], stdout=subprocess.PIPE, env=env, text=True)
        self.addCleanup(p.wait, 30)
        self.assertEqual(p.stdout.readline().strip(), "locked")
        t0 = time.monotonic()
        R.deactivate("XAUUSD", KEY)                                              # waits for the other process
        self.assertGreater(time.monotonic() - t0, 0.8)
        p.stdout.close()


# ------------------------------------------------------------------ chunk_36#3 rollback chain
class TestRollbackChain(Tmp):
    def test_second_rollback_restores_the_earlier_version(self):
        v1, v2, v3 = (fake_pkg(seed=s) for s in (1, 2, 3))
        with mock.patch.object(R, "compatibility", return_value=_OK), mock.patch.object(R, "prediction_test", return_value={"ok": True}):
            for v in (v1, v2, v3):
                self.assertTrue(R.activate("XAUUSD", KEY, v)["ok"])
            self.assertEqual(R.rollback("XAUUSD", KEY)["active"], v2)
            r = R.rollback("XAUUSD", KEY)
            self.assertEqual((r["ok"], r["active"]), (True, v1))                 # 1.45.0: active None (model silently disabled)
            self.assertEqual(R.registry("XAUUSD")["active"][KEY], v1)
            r = R.rollback("XAUUSD", KEY)
            self.assertEqual((r["ok"], r["status"]), (False, "NOTHING_TO_ROLLBACK"))
            self.assertEqual(R.registry("XAUUSD")["active"][KEY], v1)            # nothing silently disabled
            R.deactivate("XAUUSD", KEY)
            self.assertEqual(R.rollback("XAUUSD", KEY)["status"], "NOTHING_TO_ROLLBACK")
            self.assertTrue(R.activate("XAUUSD", KEY, v3)["ok"])
            self.assertTrue(R.activate("XAUUSD", KEY, v1)["ok"])
            self.assertEqual(R.rollback("XAUUSD", KEY)["active"], v3)


# ------------------------------------------------------------------ chunk_36#4 / #5 commission in price units
class TestCommissionCosts(unittest.TestCase):
    def man(self, comm=None, spec=None, contract=100.0):
        return {"costs": {"spread": {"point": 0.01, "contract_size": contract},
                          "commission": {"source": "DEALS_HISTORY", "commission_per_lot_side": comm} if comm is not None else {"source": "UNKNOWN"}},
                "symbol_spec": spec or {}}

    def test_known_commission_without_symbol_spec_is_not_zero_measured(self):
        cfg = P.config({}, self.man(3.5, spec={}, contract=None))
        self.assertNotEqual(cfg["cost_status"]["commission"], "MEASURED_FROM_DEALS")   # 1.45.0: 0.0 reported as MEASURED_FROM_DEALS
        self.assertEqual(cfg["cost_status"]["commission"], "CONVERSION_UNKNOWN")
        with self.assertRaises(DS.InsufficientData):
            P.stage_dataset(FakeStore({}), "XAUUSD", cfg)
        user = type("C", (), {"commission_per_lot_per_side": 3.5, "slippage_stress_points": 20.0})()
        cfg = P.config({}, self.man(None, spec={}, contract=None), user)
        self.assertEqual(cfg["cost_status"]["commission"], "CONVERSION_UNKNOWN")       # 1.45.0: USER_ASSUMPTION with 0.0
        cfg = P.config({"commission_price": 0.05}, self.man(3.5, spec={}, contract=None))
        self.assertEqual((cfg["commission_price"], cfg["cost_status"]["commission"], cfg["cost_blockers"]), (0.05, "USER_GIVEN_PRICE_UNITS", []))
        cfg = P.config({}, self.man(None))
        self.assertEqual(cfg["cost_status"]["slippage"], "UNKNOWN_ZERO_USED")           # no stress assumption configured - not 'ASSUMPTION_STRESS'

    def test_account_currency_commission_converted_with_tick_value(self):
        pln = {"trade_tick_size": 0.01, "trade_tick_value": 3.7, "trade_contract_size": 100.0}      # PLN account, XAUUSD quoted in USD
        cfg = P.config({}, self.man(7.0, spec=pln))
        self.assertAlmostEqual(cfg["commission_price"], 2 * 7.0 * 0.01 / 3.7, places=12)          # 1.45.0: 2 * 7 / 100 = 0.14
        usd = {"trade_tick_size": 0.01, "trade_tick_value": 1.0, "trade_contract_size": 100.0}
        self.assertAlmostEqual(P.config({}, self.man(3.5, spec=usd))["commission_price"], 2 * 3.5 / 100, places=12)   # USD: unchanged


if __name__ == "__main__":
    unittest.main()
