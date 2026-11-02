"""Training pipeline 1.28 (marketdata + trainhub + modelhub) on the terminal SIMULATOR - SYNTHETIC data, mechanics only:
incremental / resumable export without duplicates, gap classes, checksums and import, no future data in features (higher-TF join by
availability) and in the splits (purge / embargo / untouched holdout), the full pipeline for one model + an adapter test for every
other model, save -> load -> identical predictions, incompatible packages blocked (checksum, schema, library), activation never
automatic, rollback, the job queue running training out of process (cancel), the unified prediction contract and the aggregation
rules (one vote per correlation group, weights from development data only). Nothing here measures predictive value."""
from __future__ import annotations

import ast
import json
import os
import shutil
import time
import unittest
from pathlib import Path

import numpy as np

import _env
from _env import TempData, wait_for

from masterquo.marketdata import export as EX
from masterquo.marketdata import quality as Q
from masterquo.marketdata.sources import DirectSource
from masterquo.marketdata.store import Store, sha256_file
from masterquo.modelhub import aggregate as AG
from masterquo.modelhub import contract as C
from masterquo.mt5.fake import FakeMT5
from masterquo.trainhub import dataset as DS
from masterquo.trainhub import features as F
from masterquo.trainhub import learn as L
from masterquo.trainhub import pipeline as P
from masterquo.trainhub import registry as R

DAY = 86400


class FlakySource(DirectSource):
    """Fails the copy_rates_range calls whose ordinal number is in `fail` (simulates a lost terminal connection mid-export)."""

    def __init__(self, mt5, fail: set, **kw):
        super().__init__(mt5, **kw)
        self.calls, self.fail = 0, set(fail)

    def call(self, fn):
        code = getattr(fn, "__code__", None)
        if code is not None and "copy_rates_range" in code.co_names:
            self.calls += 1
            if self.calls in self.fail:
                raise ConnectionError("No IPC connection")
        return super().call(fn)


def fake(days=70):
    f = FakeMT5(history_days=days)
    f.initialize()
    return f


class Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.store = Store()
        self.src = DirectSource(fake(), offset=3 * 3600, offset_basis="TEST")

    def tearDown(self):
        self.td.close()


class TestExport(Base):
    def test_incremental_no_duplicates_and_manifest(self):
        r = EX.run(self.src, self.store, "XAUUSD", "XAUUSD-", timeframes=("M1", "M5", "M15", "M30"), lookback_days=12, sleep=lambda s: None)
        self.assertEqual(r["status"], "COMPLETE")
        n = {tf: len(self.store.read("XAUUSD", tf)["time"]) for tf in ("M1", "M5", "M15", "M30")}
        self.assertGreater(n["M1"], 10 * 1440)
        r2 = EX.run(self.src, self.store, "XAUUSD", "XAUUSD-", timeframes=("M1", "M5", "M15", "M30"), lookback_days=12, sleep=lambda s: None)
        self.assertTrue(all(v["added"] <= 2 for v in r2["timeframes"].values()))            # only candles closed meanwhile
        r3 = EX.run(self.src, self.store, "XAUUSD", "XAUUSD-", timeframes=("M5",), mode="historical", start=time.time() - 10 * DAY,
                    end=time.time() - 5 * DAY, sleep=lambda s: None)
        self.assertEqual(r3["timeframes"]["M5"]["added"], 0)
        self.assertGreater(r3["timeframes"]["M5"]["duplicates"], 1000)
        for tf in ("M1", "M5", "M15", "M30"):
            t = self.store.read("XAUUSD", tf)["time"]
            self.assertEqual(len(t), len(set(t)))
            self.assertEqual(t, sorted(t))
            step = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800}[tf]
            self.assertTrue(all(x % step == 0 for x in t))
            self.assertLess(t[-1] + step, time.time() + 1)                                   # no unclosed candle
        man = self.store.manifest("XAUUSD")
        self.assertEqual(man["schema_version"], "PMW-MD-1")
        self.assertEqual(man["data_kind"], "SYNTHETIC_TEST")
        self.assertTrue(self.store.verify("XAUUSD")["ok"])
        self.assertTrue(any(k.endswith(".parquet") for k in man["files"]) and any(k.endswith(".csv") for k in man["files"]))
        self.assertEqual(man["costs"]["commission"]["source"], "UNKNOWN")                   # no deals -> never assumed
        self.assertIn("NOT_AVAILABLE", man["costs"]["bid_ask_history"])
        self.assertEqual(man["time_model"]["model"], "UNIFORM")
        self.assertEqual(len(self.store.read("XAUUSD", "M5")["time"]), man["timeframes"]["M5"]["rows"])

    def test_resume_after_failure(self):
        src = FlakySource(fake(), {3, 4, 5}, offset=3 * 3600, offset_basis="TEST")          # 3 attempts of chunk 3 fail
        r = EX.run(src, self.store, "XAUUSD", "XAUUSD-", timeframes=("M1",), lookback_days=20, sleep=lambda s: None)
        self.assertEqual(r["status"], "FAILED")                                              # 3 retries of the same chunk -> FAILED
        st = json.loads((self.store.inst_dir("XAUUSD") / "export_state.json").read_text())
        done = len(st["done"]["M1"])
        self.assertGreaterEqual(done, 1)
        src.fail = set()
        r = EX.run(src, self.store, "XAUUSD", "XAUUSD-", timeframes=("M1",), lookback_days=20, sleep=lambda s: None)
        self.assertEqual(r["status"], "COMPLETE")
        self.assertTrue(r["resumed"])
        self.assertEqual(r["timeframes"]["M1"]["chunks_skipped_done"], done)
        t = self.store.read("XAUUSD", "M1")["time"]
        self.assertEqual(len(t), len(set(t)))

    def test_retry_recovers_single_failure(self):
        src = FlakySource(fake(), {2}, offset=3 * 3600, offset_basis="TEST")                 # one failure -> retried
        r = EX.run(src, self.store, "XAUUSD", "XAUUSD-", timeframes=("M5",), lookback_days=5, sleep=lambda s: None)
        self.assertEqual(r["status"], "COMPLETE")

    def test_revision_conflict_keeps_stored_row(self):
        row = (1_700_000_100 // 300 * 300, 10.0, 11.0, 9.0, 10.5, 5, 3, 0, 0, 0)
        self.store.merge("XAUUSD", "M5", [row])
        m = self.store.merge("XAUUSD", "M5", [row, (row[0], 10.0, 12.0, 9.0, 10.5, 5, 3, 0, 0, 0)])
        self.assertEqual((m["added"], m["duplicates"], m["conflicts"]), (0, 1, 1))
        self.assertEqual(self.store.read("XAUUSD", "M5")["high"], [11.0])
        ok, bad = Q.check_rows([(row[0], 10.0, 9.5, 9.0, 10.5, 1, 1, 0, 0, 0)])
        self.assertEqual((len(ok), len(bad)), (0, 1))

    def test_gap_classes(self):
        step = 300
        t0 = 1_793_000_000 // 86400 * 86400 - 4 * 86400        # some UTC midnight
        times = []
        for d in range(14):
            day0 = t0 + d * 86400
            for k in range(288):
                tt = day0 + k * step
                if 21 * 3600 <= tt - day0 < 22 * 3600:                                 # daily break 21:00-22:00 UTC
                    continue
                times.append(tt)
        times = [x for x in times if not (t0 + 9 * 86400 + 3600 <= x < t0 + 9 * 86400 + 3 * 3600)]   # 2 h of missing data
        g = Q.classify_gaps(sorted(times), step)
        self.assertGreaterEqual(g["SESSION_BREAK"], 12)
        self.assertEqual(g["MISSING"], 1)
        self.assertEqual(g["missing_bars"], 24)                                              # 01:00-03:00 = 24 candles of M5
        self.assertEqual(g["session_break_times_utc"], ["21:00"])

    def test_import_verifies_checksums(self):
        EX.run(self.src, self.store, "XAUUSD", "XAUUSD-", timeframes=("M5",), lookback_days=5, sleep=lambda s: None)
        other = Store(Path(self.td.dir) / "other")
        res = EX.import_folder(other, "XAUUSD", self.store.inst_dir("XAUUSD"))
        self.assertEqual(res["status"], "OK")
        self.assertEqual(len(other.read("XAUUSD", "M5")["time"]), len(self.store.read("XAUUSD", "M5")["time"]))
        f = next(p for p in (self.store.inst_dir("XAUUSD") / "M5").iterdir() if p.suffix == ".csv")
        f.write_text(f.read_text() + "x\n")                                                  # damaged copy
        with self.assertRaises(ValueError):
            EX.import_folder(Store(Path(self.td.dir) / "third"), "XAUUSD", self.store.inst_dir("XAUUSD"))


class TestNoFutureData(Base):
    def setUp(self):
        super().setUp()
        EX.run(self.src, self.store, "XAUUSD", "XAUUSD-", timeframes=("M5", "M15", "M30"), lookback_days=30, sleep=lambda s: None)
        self.cols = {tf: self.store.read("XAUUSD", tf) for tf in ("M5", "M15", "M30")}

    def test_features_ignore_future_candles_and_htf_before_close(self):
        t, X, names = F.build(self.cols, "M5", 0.01)
        i = len(t) - 500
        cut = int(t[i]) + 300                                                                # close of base candle i
        fut = {tf: {k: [v * (1.5 if k in ("open", "high", "low", "close") and c["time"][j] + F.TF_S[tf] > cut else 1)
                        for j, v in enumerate(vals)] if k != "time" else vals for k, vals in c.items()} for tf, c in self.cols.items()}
        t2, X2, _ = F.build(fut, "M5", 0.01)
        np.testing.assert_allclose(X[: i + 1], X2[: i + 1], equal_nan=True)
        # the M30 block of row i uses the last M30 candle CLOSED at the M5 close
        j = names.index("M30_r1")
        m30 = self.cols["M30"]
        k = max(n for n, tt in enumerate(m30["time"]) if tt + 1800 <= cut)
        exp = np.log(m30["close"][k] / m30["close"][k - 1])
        self.assertAlmostEqual(float(X[i, j]), float(exp), places=12)

    def test_splits_purge_embargo_and_holdout(self):
        cfg = P.config({"base_tf": "M5", "horizon": 6}, self.store.manifest("XAUUSD"))
        ds = DS.build(self.store, "XAUUSD", cfg)
        sp = DS.splits(ds, holdout_frac=0.2, n_folds=4, embargo_bars=6, step=300, min_samples=2000, min_train=500)
        hs = sp["holdout_start"]
        self.assertTrue((ds["label_end"][sp["dev"]] <= hs - 6 * 300).all())               # no dev label reaches into the holdout
        self.assertFalse(set(sp["dev"].tolist()) & set(sp["holdout"].tolist()))
        for f in sp["folds"]:
            ts0 = ds["t"][f["test"][0]]
            self.assertTrue((ds["label_end"][f["train"]] <= ts0 - 6 * 300).all())
            self.assertTrue((ds["t"][f["train"]] < ts0).all())
        self.assertTrue(all(ds["label_end"] > ds["t"]))
        with self.assertRaises(DS.InsufficientData):
            DS.splits(ds, holdout_frac=0.2, n_folds=4, embargo_bars=6, step=300, min_samples=10 ** 7, min_train=500)

    def test_labels_include_costs(self):
        cfg = P.config({"base_tf": "M5", "horizon": 6, "commission_price": 5.0}, self.store.manifest("XAUUSD"))
        ds_hi = DS.build(self.store, "XAUUSD", cfg)
        ds_lo = DS.build(self.store, "XAUUSD", P.config({"base_tf": "M5", "horizon": 6, "commission_price": 0.0}, self.store.manifest("XAUUSD")))
        self.assertGreater((ds_hi["y"] == 1).mean(), (ds_lo["y"] == 1).mean())               # higher costs -> more FLAT
        self.assertEqual(cfg["cost_status"]["commission"], "USER_GIVEN_PRICE_UNITS")


class TestPipelinePackages(Base):
    @classmethod
    def setUpClass(cls):
        cls.td_cls = TempData()
        cls.store_cls = Store()
        src = DirectSource(fake(), offset=3 * 3600, offset_basis="TEST")
        EX.run(src, cls.store_cls, "XAUUSD", "XAUUSD-", timeframes=("M5", "M15", "M30"), lookback_days=40, sleep=lambda s: None)
        cls.cfg = P.config({"models": [m for m, ok in L.available().items() if ok]}, cls.store_cls.manifest("XAUUSD"))
        cls.out = P.stage_train(cls.store_cls, "XAUUSD", cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls.td_cls.close()

    def setUp(self):
        os.environ["MASTERQUO_DATA_DIR"] = self.td_cls.dir

    def tearDown(self):
        pass

    def pkg(self, mid):
        return next(p for p in self.out["packages"] if p["model_key"].startswith(mid + "_"))

    def test_full_pipeline_and_every_adapter(self):
        keys = {p["model_key"].split("_M")[0] for p in self.out["packages"]}
        self.assertTrue({"TH_BASELINE", "TH_LOGREG", "TH_HGB"} <= keys)
        for p in self.out["packages"]:
            d = Path(p["path"])
            for f in ("model.joblib", "feature_order.json", "feature_schema.json", "config.json", "metrics.json", "data_manifest.json", "deps.json",
                      "inference_sample.json", "REPRODUCE.md", "package_manifest.json"):
                self.assertTrue((d / f).exists(), f)
            met = json.loads((d / "metrics.json").read_text())
            self.assertIn("baseline_log_loss", met["holdout"])
            self.assertIn("ece_after", met["calibration"])
            self.assertIn("mean_net_atr", met["trading_eval_holdout"])
            self.assertEqual(json.loads((d / "data_manifest.json").read_text())["data_kind"], "SYNTHETIC_TEST")
            blob = b"".join(x.read_bytes() for x in d.iterdir() if x.suffix in (".json", ".md"))
            for word in (b"password", b"token", b"PRIVATE KEY", b"api_key"):
                self.assertNotIn(word, blob.lower() if word.islower() else blob)
        self.assertEqual(R.registry("XAUUSD")["active"], {})                                  # training never activates
        b = self.pkg("TH_BASELINE")
        self.assertEqual(b["holdout"]["log_loss"], b["holdout"]["baseline_log_loss"])

    def test_save_load_same_predictions(self):
        p = self.pkg("TH_LOGREG")
        key, ver = p["model_key"], p["version"]
        pt = R.prediction_test("XAUUSD", key, ver)
        self.assertTrue(pt["ok"])
        self.assertEqual(pt["max_abs_diff"], 0.0)
        obj, conf, sch = R.load("XAUUSD", key, ver)
        ds = DS.build(self.store_cls, "XAUUSD", self.cfg)
        a = R.predict_loaded(obj, ds["X"][-50:])
        b = R.predict_loaded(R.load("XAUUSD", key, ver)[0], ds["X"][-50:])
        np.testing.assert_array_equal(a, b)
        np.testing.assert_allclose(a.sum(axis=1), 1.0, atol=1e-9)

    def test_incompatible_packages_are_blocked(self):
        p = self.pkg("TH_HGB")
        key, ver = p["model_key"], p["version"]
        d = R.package_dir("XAUUSD", key, ver)
        bak = Path(self.td_cls.dir) / "bak"
        shutil.copytree(d, bak, dirs_exist_ok=True)
        try:
            (d / "feature_schema.json").write_text(json.dumps({**json.loads((d / "feature_schema.json").read_text()), "hash": "deadbeef"}))
            r = R.activate("XAUUSD", key, ver)
            self.assertEqual((r["ok"], r["status"]), (False, "INCOMPATIBLE"))
            with self.assertRaises(R.IncompatiblePackage):
                R.load("XAUUSD", key, ver)
            shutil.copytree(bak, d, dirs_exist_ok=True)
            deps = json.loads((d / "deps.json").read_text())
            deps["sklearn"] = "0.1.0"
            (d / "deps.json").write_text(json.dumps(deps))
            man = json.loads((d / "package_manifest.json").read_text())
            man["files"]["deps.json"] = sha256_file(d / "deps.json")                         # consistent checksum, wrong library
            (d / "package_manifest.json").write_text(json.dumps(man))
            comp = R.compatibility("XAUUSD", key, ver)
            self.assertFalse(comp["ok"])
            self.assertTrue(any(c["check"] == "wersja sklearn" and not c["ok"] for c in comp["checks"]))
            self.assertEqual(R.registry("XAUUSD").get("active", {}).get(key), None)
            from masterquo.trainhub.inference import TrainhubInference
            inf = TrainhubInference(_Cfg(), _NoBridge())
            pr = inf.predict("XAUUSD", key, ver)
            self.assertEqual(pr["state"], "INCOMPATIBLE")
            self.assertIsNone(pr["result"])
        finally:
            shutil.copytree(bak, d, dirs_exist_ok=True)
        self.assertTrue(R.compatibility("XAUUSD", key, ver)["ok"])

    def test_activation_and_rollback(self):
        p1 = self.pkg("TH_LOGREG")
        key = p1["model_key"]
        r = R.activate("XAUUSD", key, p1["version"])
        self.assertTrue(r["ok"])
        cfg2 = dict(self.cfg, models=["TH_LOGREG"], seed=11)
        out2 = P.stage_train(self.store_cls, "XAUUSD", cfg2)
        v2 = out2["packages"][0]["version"]
        self.assertEqual(R.registry("XAUUSD")["active"][key], p1["version"])                  # new training does not replace
        self.assertTrue(R.activate("XAUUSD", key, v2)["ok"])
        rb = R.rollback("XAUUSD", key)
        self.assertEqual((rb["active"], rb["previous"]), (p1["version"], v2))
        self.assertEqual(R.registry("XAUUSD")["active"][key], p1["version"])
        R.deactivate("XAUUSD", key)

    def test_evaluate_needs_newer_data(self):
        p = self.pkg("TH_LOGREG")
        r = P.stage_evaluate(self.store_cls, "XAUUSD", p["model_key"], p["version"])
        self.assertEqual(r["status"], "NO_NEW_DATA")

    def test_btc_trained_separately(self):
        reg_btc = R.registry("BTC")
        self.assertEqual(reg_btc.get("versions", {}), {})
        with self.assertRaises(DS.InsufficientData):
            P.stage_validate(self.store_cls, "BTC")


class _Cfg:
    class A:
        broker_symbol = "XAUUSD-"

    def get(self):
        return type("C", (), {"assets": type("As", (), {"mappings": {"XAUUSD": _Cfg.A(), "BTC": _Cfg.A()}})()})()


class _NoBridge:
    def symbol_bars(self, *a):
        raise ConnectionError("down")

    def symbol_meta(self, *a):
        return {"point": 0.01}


class TestJobsOutOfProcess(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        src = DirectSource(fake(), offset=3 * 3600, offset_basis="TEST")
        EX.run(src, Store(), "XAUUSD", "XAUUSD-", timeframes=("M5", "M15", "M30"), lookback_days=30, sleep=lambda s: None)
        from masterquo.config import ConfigStore
        from masterquo.trainhub.jobs import TrainingCenter
        self.tc = TrainingCenter(ConfigStore(), bridge=None, poll_s=0.2)

    def tearDown(self):
        self.tc.stop()
        self.td.close()

    def test_train_job_in_child_process_cancel_and_dedup(self):
        t0 = time.perf_counter()
        j = self.tc.submit("TRAIN", "XAUUSD", {"models": ["TH_BASELINE", "TH_LOGREG"], "export": False})
        self.assertLess(time.perf_counter() - t0, 1.0)                                       # the caller (panel) is not blocked
        d = self.tc.submit("TRAIN", "XAUUSD", {"models": ["TH_BASELINE", "TH_LOGREG"], "export": False})
        self.assertTrue(d["deduplicated"])
        self.assertEqual(d["id"], j["id"])
        self.assertTrue(wait_for(lambda: (self.tc.get(j["id"]) or {}).get("pid"), 60, 0.1))
        self.assertNotEqual(self.tc.get(j["id"])["pid"], os.getpid())
        self.assertTrue(wait_for(lambda: self.tc.get(j["id"])["status"] not in ("QUEUED", "RUNNING"), 240, 0.2))
        r = self.tc.get(j["id"])
        self.assertEqual(r["status"], "SUCCEEDED", self.tc.log_tail(j["id"]))
        self.assertEqual(len(r["result"]["training"]["packages"]), 2)
        self.assertEqual(R.registry("XAUUSD")["active"], {})
        j2 = self.tc.submit("TRAIN", "XAUUSD", {"models": ["TH_HGB"], "export": False, "seed": 3})
        self.assertTrue(wait_for(lambda: self.tc.get(j2["id"])["status"] == "RUNNING" and self.tc.get(j2["id"]).get("pid"), 60, 0.05))
        self.tc.cancel(j2["id"])
        self.assertTrue(wait_for(lambda: self.tc.get(j2["id"])["status"] == "CANCELLED", 60, 0.2))
        self.tc._stop.set()
        self.tc._wake.set()
        self.tc._thread.join(10)
        q = self.tc.submit("DATASET", "XAUUSD", {"base_tf": "M5"})                         # queue stopped: stays QUEUED
        self.assertEqual(self.tc.cancel(q["id"])["status"], "CANCELLED")

    def test_insufficient_data_message(self):
        j = self.tc.submit("TRAIN", "BTC", {"models": ["TH_LOGREG"], "export": False})
        self.assertTrue(wait_for(lambda: self.tc.get(j["id"])["status"] not in ("QUEUED", "RUNNING"), 120, 0.2))
        r = self.tc.get(j["id"])
        self.assertEqual(r["status"], "FAILED")
        self.assertIn("brak danych BTC", r["error"])


class TestContractAndAggregation(unittest.TestCase):
    def base(self, **kw):
        d = dict(instrument="XAUUSD", symbol="XAUUSD-", timeframe="M5", model_name="TH_LOGREG", model_version="v1", task_type="CLASS_PROBABILITIES",
                 task="DIRECTION_H6_M5", horizon_bars=6, unit="probability", state="READY", result={"DOWN": 0.2, "FLAT": 0.3, "UP": 0.5},
                 data_time="2026-11-02T10:00:00Z", calibration={"method": "t", "status": "CALIBRATED_DEV"})
        d.update(kw)
        return d

    def test_contract_rules(self):
        p = C.make(**self.base())
        self.assertEqual(p["state_pl"], "gotowy")
        e = C.make(**self.base(state="ERROR", unavailable_reason="dane nieaktualne"))
        self.assertIsNone(e["result"])                                                         # a failure never carries a value
        with self.assertRaises(C.ContractError):
            C.make(**self.base(state="ERROR"))                                                 # reason required
        with self.assertRaises(C.ContractError):
            C.make(**self.base(result={"DOWN": 0.2, "FLAT": 0.3, "UP": 0.6}))
        with self.assertRaises(C.ContractError):
            C.make(**self.base(result={"DOWN": -0.1, "FLAT": 0.6, "UP": 0.5}))
        with self.assertRaises(C.ContractError):
            C.make(**self.base(horizon_bars=None))
        with self.assertRaises(C.ContractError):
            C.make(**self.base(unit="percent"))
        bad = dict(p, result={"UP": 1.0}, state="INCOMPATIBLE", unavailable_reason="x")
        with self.assertRaises(C.ContractError):
            C.validate(bad)

    def test_one_vote_per_group_and_no_cross_horizon_merge(self):
        a = C.make(**self.base(model_name="TH_LOGREG", extra={"model_key": "TH_LOGREG_M5_H6"}))
        b = C.make(**self.base(model_name="TH_HGB", extra={"model_key": "TH_HGB_M5_H6"}))
        c = C.make(**self.base(model_name="TH_HGB", task="DIRECTION_H12_M5", horizon_bars=12, extra={"model_key": "TH_HGB_M5_H12"}))
        e = C.make(**self.base(model_name="TH_XGB", state="ERROR", unavailable_reason="brak danych", extra={"model_key": "TH_XGB_M5_H6"}))
        ev = AG.evidence([a, b, c, e], "SCALPING", "XAUUSD")
        g6 = [g for g in ev["groups"] if g["horizon_bars"] == 6]
        g12 = [g for g in ev["groups"] if g["horizon_bars"] == 12]
        self.assertEqual((len(g6), len(g12)), (1, 1))                                          # same group = ONE speaker; H6 and H12 separate
        self.assertEqual(len(g6[0]["silenced_same_group"]), 1)
        self.assertEqual(ev["excluded"][0]["state"], "ERROR")
        self.assertTrue(all(g["use"] == "OBSERVATION" for g in ev["groups"]))
        src = (_env.ROOT / "backend" / "masterquo" / "modelhub" / "aggregate.py").read_text(encoding="utf-8")
        self.assertIn("dev_skill_vs_baseline", src)                                            # weights from development walk-forward
        self.assertNotIn("holdout", src.split("def dev_skill")[1].split("def evidence")[0])


class TestIsolationFromTrading(unittest.TestCase):
    def test_no_order_path_in_new_modules(self):
        base = _env.ROOT / "backend" / "masterquo"
        files = list((base / "marketdata").glob("*.py")) + list((base / "trainhub").glob("*.py")) + list((base / "modelhub").glob("*.py")) + \
            [base / "zones" / "market.py", base / "zones" / "market_service.py"]
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertFalse([m for m in mods if any(x in m for x in ("execution", "risk", "gateway", "manual"))], f.name)
            src = f.read_text(encoding="utf-8")
            for call in ("order_send", "order_check", "positions_get(", "cfg_store.update", ".update({\"execution"):
                self.assertNotIn(call, src, f"{f.name}: {call}")


if __name__ == "__main__":
    unittest.main()
