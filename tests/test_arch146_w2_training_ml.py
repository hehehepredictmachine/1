"""Fala 2 / grupa training_ml (Apollo23 1.46): I0342 (reguły asocjacyjne walidowane na holdoucie), I0667 (TH_RF bez class_weight),
I0674 (TH_SVM: fallback na Prior widoczny, paczka nie zapisana), I0024 (manifest stref / sesji w bundlu ML), I0731 (epizody zdarzeń
w walidacji ML), I0788 (fold walk-forward z jedną klasą), I0050 (poślizg TH na round trip), I0063 (atomowa blokada treningu, blokada
eksportu), I0070 (limit czasu w Centrum Pepe = anulowanie), I0074 (dostępność .venv_candles jak w runnerze).
Każdy test nie przechodzi na kodzie sprzed poprawki. Dane SYNTETYCZNE - sprawdzają reguły, nie wartość predykcyjną."""
from __future__ import annotations

import random
import unittest

import _env


def _walk(seed: int, n: int = 3000) -> list[dict]:
    rnd = random.Random(seed)
    c, bars = 2000.0, []
    for i in range(n):
        o = c
        c = c + rnd.gauss(0, 1.0)
        bars.append({"o": o, "h": max(o, c) + 0.3, "l": min(o, c) - 0.3, "c": c, "hour": i % 24})
    return bars


# ============================================================================= I0342 association rules
class TestAssociationRulesValidity(unittest.TestCase):
    def test_no_supported_on_random_walk(self):
        """Random walk, labels 24 bars ahead (as the route): no SUPPORTED / CONTRARY_EDGE on the last 200 bars (before: seed 0 -> 72)."""
        from masterquo.ml import association_rules as AR
        for seed in (0, 1, 2):
            bars = _walk(seed)
            masks = AR.event_bits(bars)
            m = AR.train(masks, AR.labels([b["c"] for b in bars], 24, 0.0), horizon=24)
            res = [AR.assess(m, mk, d)["reason"] for mk in masks[-200:] for d in ("LONG", "SHORT") if mk is not None]
            self.assertEqual(res.count("SUPPORTED") + res.count("CONTRARY_EDGE"), 0, f"seed {seed}: {sorted(set(res))}")
            self.assertEqual(m["validation"], AR.VALIDATION)
            self.assertEqual(m["validated_rules"], 0)
            if seed == 0:                                   # the in-sample edge is still visible - as IN_SAMPLE_ONLY, not SUPPORTED
                self.assertIn("IN_SAMPLE_ONLY", res)

    def test_injected_dependence_still_supported(self):
        """Control: MOM_UP -> UP with p = 0.7 (else 0.5), independent labels: the rule is validated and LONG is SUPPORTED."""
        from masterquo.ml import association_rules as AR
        mom = 1 << AR.CATALOG.index("MOM_UP")
        for seed in (0, 1, 2):
            bars = _walk(seed)
            masks = AR.event_bits(bars)
            rnd = random.Random(100 + seed)
            labs = [None if mk is None else ("UP" if rnd.random() < (0.7 if mk & mom else 0.5) else "DOWN") for mk in masks]
            m = AR.train(masks, labs, horizon=1)
            mk = next(x for x in reversed(masks) if x is not None and x & mom)
            a = AR.assess(m, mk, "LONG")
            self.assertEqual((a["reason"], a["candidate_direction_supported"]), ("SUPPORTED", True), seed)
            self.assertGreaterEqual(a["validated_rules_for"], 1)
            self.assertEqual(AR.assess(m, mk, "SHORT")["reason"], "CONTRARY_EDGE")
            r = next(r for r in m["rules"] if r["events"] == ["MOM_UP"])
            for k in ("p_adj", "n_eff_holdout", "holdout_edge_up", "fit_edge_up", "validated_direction"):
                self.assertIn(k, r)

    def test_holdout_is_purged_and_bonferroni_counts_every_rule(self):
        from masterquo.ml import association_rules as AR
        bars = _walk(4)
        masks = AR.event_bits(bars)
        labs = AR.labels([b["c"] for b in bars], 24, 0.0)
        m = AR.train(masks, labs, horizon=24)
        vp = m["validation_params"]
        self.assertEqual(vp["tests_bonferroni"], 2 * len(m["rules"]))
        self.assertEqual(vp["purge_bars"], 24)
        idx = [i for i, (mk, y) in enumerate(zip(masks, labs)) if mk is not None and y in ("UP", "DOWN")]
        n_fit = sum(1 for i in idx if i + 24 <= vp["holdout_start_index"])
        self.assertEqual(vp["n_fit"], n_fit)
        self.assertEqual(vp["n_fit"] + vp["n_holdout"] + sum(1 for i in idx if vp["holdout_start_index"] - 24 < i < vp["holdout_start_index"]),
                         m["n_labeled"])
        self.assertAlmostEqual(vp["n_eff_holdout"], vp["n_holdout"] / 24)


# ============================================================================= I0667 TH_RF probabilities
class TestRFProbabilitiesNotFlattened(unittest.TestCase):
    def test_rf_probabilities_follow_class_frequencies(self):
        """Imbalanced DOWN/FLAT/UP (~0.19/0.62/0.19): before mean P(FLAT) ~0.34 and log loss 1.08 > baseline 0.93 (balanced_subsample)."""
        import numpy as np
        from masterquo.trainhub import learn as L
        rs = np.random.RandomState(1)
        n = 6000
        X = rs.randn(n, 10)
        logit = np.c_[-0.5 + 0.3 * X[:, 0], 0.8 + 0 * X[:, 0], -0.5 - 0.3 * X[:, 0]]
        p = np.exp(logit)
        p /= p.sum(1, keepdims=True)
        y = np.array([rs.choice(3, p=pp) for pp in p])
        tr, te = slice(0, 4000), slice(4000, None)
        params = L.MODELS["TH_RF"]["grid"][0]
        m = L.fit("TH_RF", params, X[tr], y[tr], 7)
        pr = L.proba3(m, X[te])
        freq_flat = float((y[te] == 1).mean())
        self.assertLess(abs(float(pr[:, 1].mean()) - freq_flat), 0.1)
        base = L.Prior().fit(X[tr], y[tr]).predict_proba(X[te])
        self.assertLessEqual(L.logloss(pr, y[te]), L.logloss(base, y[te]) * 1.02)
        self.assertIn("class_weight", params)                                 # part of params / version hash / config.json

    def test_params_without_key_keep_the_old_training(self):
        """Reproducibility: params of a <= 1.46 package (no class_weight key) build the forest exactly as before."""
        from masterquo.trainhub import learn as L
        old = {"n_estimators": 200, "max_depth": 6, "min_samples_leaf": 50}
        self.assertEqual(L.make("TH_RF", old, 7).class_weight, "balanced_subsample")
        self.assertIsNone(L.make("TH_RF", L.MODELS["TH_RF"]["grid"][1], 7).class_weight)


# ============================================================================= I0674 TH_SVM fallback
def _svm_ds(n: int = 1000, flat_tail_from: int = 640, seed: int = 3) -> dict:
    """Synthetic trainhub dataset: classes mixed, but the rows from `flat_tail_from` to the holdout are all FLAT (1) - the calibration
    block of the final SVM fit (last 20 % of the development rows) has one class."""
    import numpy as np
    rs = np.random.RandomState(seed)
    X = rs.randn(n, 6)
    y = rs.choice(3, size=n, p=[0.3, 0.4, 0.3]).astype(np.int64)
    y[flat_tail_from:800] = 1
    t = np.arange(n, dtype=np.int64) * 300 + 1_700_000_000
    return {"t": t, "X": X, "y": y, "label_end": t + 600, "fwd": rs.randn(n), "cost": np.full(n, 0.01), "atr": np.ones(n),
            "names": [f"f{i}" for i in range(6)], "point": 0.01}


class TestSVMFallbackVisible(unittest.TestCase):
    def test_fallback_is_marked(self):
        import numpy as np
        from masterquo.trainhub import learn as L
        rs = np.random.RandomState(0)
        X = rs.randn(500, 4)
        y = rs.choice(3, size=500).astype(np.int64)
        y[400:] = 1                                                     # last 20 % = calibration block with one class
        m = L.SVMProb("linear", 1.0).fit(X, y)
        self.assertIsNone(m.svm)
        self.assertEqual(m.used_kernel, "PRIOR_FALLBACK")                 # before: 'linear'
        self.assertIn("kalibracyjny", m.fallback_reason)
        y2 = rs.choice(3, size=500).astype(np.int64)
        ok = L.SVMProb("linear", 1.0).fit(X, y2)
        self.assertEqual((ok.used_kernel, ok.fallback_reason), ("linear", None))

    def test_stage_train_does_not_save_a_baseline_as_svm(self):
        from _env import TempData
        from masterquo.trainhub import pipeline as P
        td = TempData()
        try:
            class St:
                def manifest(self, inst):
                    return {}

                def inst_dir(self, inst):                # scalenie z training_studio (I0064): DatasetRef paczki czyta raport jakości Store
                    from pathlib import Path
                    return Path(td.dir) / "marketdata" / inst
            cfg = {"base_tf": "M5", "horizon": 1, "k_atr": 0.25, "holdout_frac": 0.2, "n_folds": 2, "embargo_bars": 0, "min_samples": 500,
                   "min_train": 100, "seed": 7, "models": ["TH_BASELINE", "TH_SVM"], "grid_limit": 1, "profile": None, "time_budget_s": None,
                   "commission_price": 0.0, "slippage_price": 0.0, "point": 0.01}
            out = P.stage_train(St(), "XAUUSD", cfg, ds=_svm_ds(), desc={"hash": "x"})
            self.assertEqual([p["model_key"].split("_M5")[0] for p in out["packages"]], ["TH_BASELINE"])
            sk = {s["model"]: s for s in out["skipped"]}
            self.assertIn("TH_SVM", sk)                                         # before: saved as a TH_SVM package
            self.assertIn("baseline", sk["TH_SVM"]["reason"])
        finally:
            td.close()


# ============================================================================= I0024 ML bundle records the zone / session context
class TestMLBundleRecordsZoneConfigHash(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_bundle_meta_has_hashes_and_load_compares(self):
        from pathlib import Path

        from test_ml import HAVE_ML, gen_rows, train_cfg, write_snapshot
        if not HAVE_ML:
            self.skipTest("scikit-learn/xgboost not installed")
        from masterquo.ml import features as fe
        from masterquo.ml import trainer
        from masterquo.ml.models import Bundle
        root = Path(self.td.dir)
        res = trainer.run(write_snapshot(gen_rows(900), root / "snaps" / "s.jsonl.gz"), train_cfg(), str(root / "models"), None)
        self.assertEqual(res["status"], "DONE", res)
        b = Bundle.load(Path(res["models"]["DECISION_TREE"]["path"]))
        self.assertIn("zone_config_hash", b.meta)                                          # before: no field
        cur = fe.feature_context()
        self.assertEqual(b.meta.get("zone_config_hash"), cur["zone_config_hash"])
        self.assertEqual(b.meta.get("sessions_profile_hash"), cur["sessions_profile_hash"])
        self.assertEqual(b.meta["feature_context"]["status"], "OK")

    def test_changed_defaults_are_a_warning_not_incompatible(self):
        from masterquo.ml import features as fe
        cur = fe.feature_context()
        chk = fe.feature_context_check({**cur, "zone_config_hash": "0" * 64})
        self.assertEqual((chk["status"], chk["changed"]), ("MISMATCH", ["zone_config_hash"]))
        self.assertTrue(chk["warnings"])
        self.assertEqual(fe.feature_context_check({})["status"], "UNKNOWN")                 # bundle of <= 1.46.0
        from masterquo.config import ZonesConfig
        self.assertNotEqual(fe.feature_context()["zone_config_hash"], fe.feature_context()["sessions_profile_hash"])
        self.assertIn("XAUUSD", ZonesConfig().session_profile)

    def test_session_features_unchanged(self):
        """sess_* values are the same fixed UTC hours as before (values of the schema do not change)."""
        from masterquo.ml import features as fe
        self.assertEqual(fe.SESS_UTC_HOURS, {"sess_asia": (0, 7), "sess_london": (7, 12), "sess_ny": (12, 21)})


# ============================================================================= I0731 validation: event episodes
def _ev_rows(n: int = 400, step_h: float = 3.6, label_h: float = 1.0, event: str = "EV-MEANREV", seed: int = 2) -> list[dict]:
    from datetime import UTC, datetime, timedelta
    rnd = random.Random(seed)
    t0 = datetime(2026, 1, 5, tzinfo=UTC)
    out = []
    for i in range(n):
        t = t0 + timedelta(hours=i * step_h)
        out.append({"sample_id": f"S{i:04d}:1", "group_id": f"S{i:04d}", "event_id": event, "asof_utc": t.isoformat().replace("+00:00", "Z"),
                    "label_end_utc": (t + timedelta(hours=label_h)).isoformat().replace("+00:00", "Z"), "label": int(rnd.random() < 0.5)})
    return out


class TestValidationEventEpisodes(unittest.TestCase):
    def test_one_event_id_over_60_days_is_split_by_time(self):
        """S09-like event_id without a time part: 400 samples over 60 days (label 1 h, embargo 60 min). Before: every sample in FIT
        (NOT_READY - TUNE / CALIB / TEST empty)."""
        from masterquo.ml import validation as val
        info, reasons = val.split(_ev_rows(), embargo_minutes=60, min_block=10, min_class=2)
        self.assertEqual(reasons, [])
        c = info["counts"]
        self.assertGreater(min(c.values()), 0)
        self.assertAlmostEqual(c["fit"] / sum(c.values()), 0.5, delta=0.05)
        self.assertAlmostEqual(c["test"] / sum(c.values()), 0.2, delta=0.05)
        self.assertEqual(info["version"], "MQ-VALIDATION-1.1.0")                # new validation version in the training report

    def test_overlapping_samples_of_one_event_stay_together(self):
        """Samples whose label windows chain (next asof <= label end + embargo) are ONE episode -> one block; versions of one setup too."""
        from masterquo.ml import validation as val
        rows = _ev_rows(400, step_h=0.5, label_h=1.0)                # every 30 min with 1 h labels: one long episode
        ep = val.episodes(rows, 60)
        self.assertEqual(len(set(ep)), 1)
        rows = _ev_rows(40)
        rows[5] = dict(rows[5], group_id=rows[30]["group_id"])          # two versions of one setup far apart in time
        ep = val.episodes(rows, 60)
        self.assertEqual(ep[5], ep[30])
        self.assertNotEqual(ep[5], ep[6])
        info, _ = val.split(rows, embargo_minutes=60, min_block=1, min_class=0)
        where = {r["sample_id"]: b for b, blk in info["blocks"].items() for r in blk}
        if rows[5]["sample_id"] in where and rows[30]["sample_id"] in where:
            self.assertEqual(where[rows[5]["sample_id"]], where[rows[30]["sample_id"]])

    def test_walk_forward_keeps_earlier_episodes_in_training(self):
        """Before: once one sample of the event was in a validation fold, every earlier sample of it left the training part (empty)."""
        from masterquo.ml import validation as val
        folds = val.walk_forward(_ev_rows(300), 3, 60)
        self.assertEqual(len(folds), 3)
        for tr, va in folds:
            self.assertGreater(len(tr), 50)
            self.assertLess(max(r["asof_utc"] for r in tr), min(r["asof_utc"] for r in va))


# ============================================================================= I0788 DT walk-forward fold with one class
class TestTrainDtOneClassValidationFold(unittest.TestCase):
    def _rows(self, n, rnd, label=None):
        return [{"M15_rsi": rnd.gauss(50, 10), "M5_er20": rnd.random(), "M15_atr_pct": abs(rnd.gauss(0.2, 0.05)),
                 "label": label if label is not None else int(rnd.random() < 0.5)} for _ in range(n)]

    def test_one_class_validation_fold_is_skipped(self):
        import math

        import numpy as np
        from masterquo.db.database import dumps
        from masterquo.ml.models import train_dt
        from masterquo.ml.prep import Preprocessor
        rnd = random.Random(4)
        tr, va_one, va_mix = self._rows(120, rnd), self._rows(30, rnd, label=0), self._rows(30, rnd)
        pp = Preprocessor().fit(tr)
        X, y = pp.transform(tr), np.array([r["label"] for r in tr])
        _, info = train_dt([(tr, va_one), (tr, va_mix)], X, y, budget=6, seed=1, prep_fit=lambda rows: Preprocessor().fit(rows))
        self.assertTrue(math.isfinite(info["walk_forward_logloss"]))             # before: inf (mean with the one-class fold)
        dumps({"train": info})                                                    # Registry.register: allow_nan=False (before: ValueError)
        _, info = train_dt([(tr, va_one)], X, y, budget=6, seed=1, prep_fit=lambda rows: Preprocessor().fit(rows))
        self.assertIsNone(info["walk_forward_logloss"])                           # no usable fold: no score, default params
        self.assertEqual(info["trials"], 0)
        dumps({"train": info})


# ============================================================================= I0050 trainhub slippage per round trip
class TestTrainhubSlippageRoundTrip(unittest.TestCase):
    def test_slippage_counted_for_two_fills_like_the_risk_engine(self):
        from masterquo.trainhub import pipeline as P
        user = type("C", (), {"commission_per_lot_per_side": None, "slippage_stress_points": 2.0})()
        cfg = P.config({"point": 0.1}, {}, user)
        self.assertAlmostEqual(cfg["slippage_price"], 0.4)                     # before: 0.2 (one fill)
        self.assertEqual((cfg["cost_status"]["slippage"], cfg["cost_status"]["slippage_fills"]), ("ASSUMPTION_STRESS", 2))
        self.assertEqual(cfg["cost_policy"], P.COST_POLICY)
        # explicit price stays as given (already a round-trip price in price units)
        cfg = P.config({"point": 0.1, "slippage_price": 0.25}, {}, user)
        self.assertEqual((cfg["slippage_price"], cfg["cost_status"]["slippage"], cfg["cost_status"]["slippage_fills"]),
                         (0.25, "USER_GIVEN_PRICE_UNITS", None))

    def test_same_semantics_as_risk_engine(self):
        """risk/engine: slip_1 = 2 x |profit(slippage_stress_points x point)| per lot - the label cost uses the same 2 fills."""
        import inspect

        from masterquo.risk import engine as RE
        self.assertIn("slip_1 = 2 * abs(v)", inspect.getsource(RE))
        from masterquo.trainhub import pipeline as P
        self.assertEqual(P.SLIPPAGE_FILLS, 2)


# ============================================================================= I0063 training lock / export lock
_CHILD = r"""
import json, os, sys, time
sys.path.insert(0, {backend!r})
from masterquo.training import core
orig = core.write_json_atomic
def slow(path, payload):
    time.sleep(0.6)                                   # widen the read -> write window
    return orig(path, payload)
core.write_json_atomic = slow
t0 = float(sys.argv[1])
while time.time() < t0:
    time.sleep(0.005)
r = core.acquire_lock(sys.argv[2])
print(json.dumps({{"run": sys.argv[2], "holder": r}}), flush=True)
time.sleep(2.5)                                       # stay alive: the other process must see a LIVE owner
"""


class TestTrainingLockAtomic(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_two_threads_never_both_acquire(self):
        import threading
        from unittest import mock

        from masterquo.training import core
        orig = core.write_json_atomic

        def slow(path, payload):
            import time
            time.sleep(0.3)
            return orig(path, payload)
        res = {}
        with mock.patch.object(core, "write_json_atomic", slow):
            ts = [threading.Thread(target=lambda r=r: res.__setitem__(r, core.acquire_lock(r))) for r in ("TR-A", "TR-B")]
            for t in ts:
                t.start()
            for t in ts:
                t.join(10)
        self.assertEqual(sum(1 for v in res.values() if v is None), 1, res)            # before: both None (both "own" the lock)
        winner = next(k for k, v in res.items() if v is None)
        self.assertEqual(next(v for v in res.values() if v is not None), winner)

    def test_two_processes_never_both_acquire(self):
        import json
        import os
        import subprocess
        import sys
        import time
        from pathlib import Path
        backend = str(Path(_env.ROOT) / "backend")
        t0 = time.time() + 1.5
        env = dict(os.environ, MASTERQUO_DATA_DIR=self.td.dir, PMW_BOOTSTRAP="0")
        ps = [subprocess.Popen([sys.executable, "-c", _CHILD.format(backend=backend), str(t0), rid], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, env=env) for rid in ("TR-P1", "TR-P2")]
        outs = [p.communicate(timeout=60) for p in ps]
        res = [json.loads(o.strip().splitlines()[-1]) for o, _ in outs]
        self.assertEqual(sum(1 for r in res if r["holder"] is None), 1, [outs])          # before: both None
        win = next(r["run"] for r in res if r["holder"] is None)
        self.assertEqual(next(r["holder"] for r in res if r["holder"] is not None), win)

    def test_unique_tmp_names(self):
        """write_json_atomic no longer uses one fixed '<name>.tmp' shared by every process."""
        from pathlib import Path
        from unittest import mock

        from masterquo.training import core
        seen = []
        real = Path.write_text

        def spy(self, *a, **k):
            seen.append(self.name)
            return real(self, *a, **k)
        p = Path(self.td.dir) / "x" / "state.json"
        with mock.patch.object(Path, "write_text", spy):
            core.write_json_atomic(p, {"a": 1})
            core.write_json_atomic(p, {"a": 2})
        tmps = [n for n in seen if n != "state.json"]
        self.assertEqual(len(tmps), 2)
        self.assertNotEqual(tmps[0], tmps[1])                                            # before: 'state.json.tmp' twice
        import json
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"a": 2})


class TestExportCandlesTakesExportLock(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_busy_export_lock_refuses(self):
        import contextlib
        import io
        from unittest import mock

        from masterquo.forecast import export as FE
        from masterquo.paths import data_dir
        from masterquo.studio.lock import Lock
        held = Lock(data_dir() / "locks" / "pmw_export.lock", app="PepeTrainingStudio")
        ok, _ = held.acquire("studio-export:XAUUSD")
        self.assertTrue(ok)
        buf = io.StringIO()
        try:
            with mock.patch.object(FE, "EXPORT_LOCK_WAIT_S", 0.0, create=True), contextlib.redirect_stdout(buf):
                rc = FE.export_candles(1, str(self.td.dir) + "/out", "AUTO", ("M5",), "training", "XAUUSD", "XAUUSD-")
        finally:
            held.release()
        self.assertEqual(rc, 9, buf.getvalue())                                            # before: the export went on (no lock)
        self.assertIn("BUSY", buf.getvalue())

    def test_free_lock_is_taken_and_released(self):
        import contextlib
        import io

        from masterquo.forecast import export as FE
        from masterquo.paths import data_dir
        seen = {}
        real = FE._export

        def spy(*a, **k):
            seen["owner"] = __import__("json").loads((data_dir() / "locks" / "pmw_export.lock").read_text(encoding="utf-8"))
            return 0
        FE._export = spy
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = FE.export_candles(1, str(self.td.dir) + "/out", "AUTO", ("M5",), "training", "XAUUSD", "XAUUSD-")
        finally:
            FE._export = real
        self.assertEqual(rc, 0)
        self.assertEqual(seen["owner"]["job"], "export_candles:XAUUSD")
        self.assertFalse((data_dir() / "locks" / "pmw_export.lock").exists())             # released after the export


# ============================================================================= I0070 Pepe center: wait limit = cancel
class _Tick:
    """Clock jumping 10**6 s per call: every _wait limit passes at its first check."""

    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        self.t += 1e6
        return self.t


class _RunningTH:
    def __init__(self, cancel_works: bool = True):
        self.jobs, self.cancelled, self.cancel_works = {}, [], cancel_works

    def submit(self, kind, inst, params):
        jid = f"TJ-{len(self.jobs)}"
        self.jobs[jid] = {"id": jid, "kind": kind, "instrument": inst, "status": "RUNNING", "stage": "trening"}
        return self.jobs[jid]

    def get(self, jid):
        return self.jobs.get(jid)

    def list(self, n):
        return list(self.jobs.values())[::-1][:n]

    def cancel(self, jid):
        self.cancelled.append(jid)
        if self.cancel_works:
            self.jobs[jid]["status"] = "CANCELLED"
        return self.jobs[jid]


class _RunningFamilies:
    fams = ("TS_ARIMA", "VOL_GARCH")

    def __init__(self):
        self.state = {f: "RUNNING" for f in self.fams}
        self.cancelled = []

    def train_all(self, inst, profile):
        return {"started": list(self.fams), "queued": [], "blocked": [], "delegated": []}

    def job(self, f, inst):
        return {"state": self.state[f]}

    def cancel(self, f, inst):
        self.cancelled.append(f)
        self.state[f] = "CANCELLED"
        return {"ok": True}

    def catalog(self, inst):
        return [{"id": f, "status": {"implementation": "AVAILABLE", "job": {"state": self.state[f]}}} for f in self.fams]


class TestPepeCenterTimeout(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def center(self, **rt):
        import types

        from masterquo.training import pepe_center as P
        base = {"demo": True, "trainhub": None, "families": None, "research": None, "tsfm": None}
        return P.PepeTrainingCenter(types.SimpleNamespace(**{**base, **rt}), clock=_Tick())

    def test_trainhub_timeout_cancels_the_job(self):
        th = _RunningTH()
        c = self.center(trainhub=th)
        q = c._item("trainhub", ["XAUUSD"], name="Kierunek TH · XAUUSD")
        res = c._run(q)
        self.assertEqual(th.cancelled, [q["job_id"]])                                   # before: no cancel, the job kept training
        self.assertEqual(res["state"], "FAILED")
        self.assertIn("TIMEOUT", res["detail"])

    def test_families_timeout_is_not_done(self):
        fam = _RunningFamilies()
        c = self.center(families=fam)
        res = c._run(c._item("families", ["XAUUSD"], name="Rodziny · XAUUSD"))
        self.assertNotEqual(res["state"], "DONE")                                       # before: 'DONE' with families still RUNNING
        self.assertEqual(sorted(fam.cancelled), sorted(fam.fams))
        self.assertIn("TIMEOUT", res["detail"])

    def test_job_that_does_not_stop_halts_the_queue(self):
        th = _RunningTH(cancel_works=False)
        c = self.center(trainhub=th)
        q1, q2 = c._item("trainhub", ["XAUUSD"], name="TH XAU"), c._item("trainhub", ["BTC"], name="TH BTC")
        c.queue = [q1, q2]
        c._loop()                                                                        # synchronously: the queue thread's body
        self.assertEqual(len(th.jobs), 1)                                                # before: TH BTC started next to TH XAU
        self.assertEqual((q1["state"], q2["state"]), ("FAILED", "SKIPPED"))
        self.assertIn("nadal działa", q2["detail"])


# ============================================================================= I0074 Pepe center: .venv_candles like the runner
class TestPepeCandlesAvailability(unittest.TestCase):
    def setUp(self):
        import tempfile
        import types
        from pathlib import Path

        from _env import TempData
        self.td = TempData()
        self.root = Path(tempfile.mkdtemp(prefix="mq_root_"))                         # app folder WITHOUT .venv_candles
        self.rt = types.SimpleNamespace(demo=True, trainhub=None, families=None, research=None, tsfm=None)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)
        self.td.close()

    def _center(self):
        from masterquo.training import pepe_center as P
        return P.PepeTrainingCenter(self.rt)

    def test_env_variable_interpreter_is_used(self):
        import os
        import sys
        from unittest import mock

        from masterquo.training import core as tc
        from masterquo.training import pepe_center as P
        with mock.patch.dict(os.environ, {"MQ_CANDLES_PYTHON": sys.executable}), mock.patch.object(P.paths, "ROOT_DIR", self.root), \
                mock.patch.object(tc, "candles_healthy", lambda py, max_age_s=None: True):
            c = self._center()
            getattr(c, "_check_candles", lambda py: None)(sys.executable)                # the background check, synchronously
            av = c.availability()
        self.assertNotIn("forecast", av)                                                 # before: 'brak środowiska .venv_candles'
        self.assertNotIn("scalp_A", av)

    def test_missing_env_with_auto_install_is_a_note_not_a_block(self):
        import os
        from unittest import mock

        from masterquo.training import pepe_center as P
        env = {k: v for k, v in os.environ.items() if k != "MQ_CANDLES_PYTHON"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(P.paths, "ROOT_DIR", self.root), \
                mock.patch.object(P, "_candles_autoinstall", lambda: True, create=True):
            c = self._center()
            av = c.availability()
            st = c.status()
        self.assertNotIn("forecast", av)
        row = next(u for u in st["units"] if u["id"] == "forecast")
        self.assertIn("zainstaluje się automatycznie", row["status"]["XAUUSD"]["detail"])

    def test_broken_env_without_auto_install_blocks(self):
        import os
        import sys
        from unittest import mock

        from masterquo.training import core as tc
        from masterquo.training import pepe_center as P
        with mock.patch.dict(os.environ, {"MQ_CANDLES_PYTHON": sys.executable}), mock.patch.object(P.paths, "ROOT_DIR", self.root), \
                mock.patch.object(tc, "candles_healthy", lambda py, max_age_s=None: False), \
                mock.patch.object(P, "_candles_autoinstall", lambda: False, create=True):
            c = self._center()
            self.assertNotIn("forecast", c.availability())                               # health not known yet -> not blocked
            c._check_candles(sys.executable)
            self.assertIn("forecast", c.availability())


if __name__ == "__main__":
    unittest.main()
