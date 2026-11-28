"""1.46 audit, group B_ml_quant_1: legacy ML pipeline (backfill / dataset / models / registry / service / trainer / validation),
scalp ML task (ledger, selected-bundle cache, CLI report) and quant adapters (Event GRU). Synthetic data only - mechanics, not edge."""
from __future__ import annotations

import gzip
import json
import math
import random
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
from _env import TempData

UTC = timezone.utc  # noqa: UP017 - same style as the other ML tests
T0 = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def _rec(sl=1995.0):
    return {"strategy_id": "S01", "strategy_version": "1", "direction": "LONG", "timeframe": "M15", "stop_loss": sl,
            "targets": [{"price": 2004.0, "weight": 0.5}, {"price": 2008.0, "weight": 0.5}], "exit_rules": {"time_exit_bars": 8, "be_after_tp1": True}}


def _bf_data(n_m15=8, spread_points=None):
    """Tiny closed-bar history: M15 steps + M1 bars (spread field configurable)."""
    data = {"M15": [], "M1": []}
    for i in range(n_m15):
        op = T0 + timedelta(minutes=15 * i)
        data["M15"].append({"open_utc": iso(op), "o": 2000.0, "h": 2001.0, "l": 1999.0, "c": 2000.0, "tv": 10,
                            "available_at": iso(op + timedelta(minutes=15)), "spread_points": spread_points, "closed": True})
    for i in range(15 * n_m15 + 60):
        op = T0 + timedelta(minutes=i)
        data["M1"].append({"open_utc": iso(op), "o": 2000.0, "h": 2000.5, "l": 1999.5, "c": 2000.0, "tv": 10,
                           "available_at": iso(op + timedelta(minutes=1)), "spread_points": spread_points, "closed": True})
    return data


class _Tracker:
    """SetupTracker stand-in: one NEW_CONFIRMED setup on the first update."""
    def __init__(self, db):
        self.n = 0

    def update(self, cands, **kw):
        self.n += 1
        return [("NEW_CONFIRMED", {"setup_id": "SX", "version": 1, "record": _rec()})] if self.n == 1 else []


def _run_backfill(db, data, cost, **kw):
    from masterquo.ml import backfill
    scan = kw.pop("scan", None) or mock.Mock(return_value={"candidates": []})
    with mock.patch.object(backfill, "SetupTracker", _Tracker), \
            mock.patch.object(backfill.adapter, "build_view", return_value=SimpleNamespace(context={})), \
            mock.patch.object(backfill.registry, "scan", scan), \
            mock.patch("masterquo.ml.features.compute", return_value={}):
        return backfill.run(db, data, feed="T", synthetic=True, cost=cost, warmup_days=0, **kw), scan


# ============================================================================= backfill
class TestBackfill(unittest.TestCase):
    def setUp(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        self.td = TempData()
        self.cfg = ConfigStore()
        self.db = Database()

    def tearDown(self):
        self.db.close()
        self.td.close()

    def test_missing_bar_spread_is_unknown_not_zero(self):
        """chunk_19#6: no bar spread + offline cost model (spread 0.0) -> SPREAD_UNKNOWN, quality COST_UNKNOWN (never trained on)."""
        cost = {"spread": 0.0, "slippage": 0.0, "commission": 0.001, "point": 0.01, "flags": ["SPREAD_FROM_BAR_SPREAD_FIELD"]}
        res, _ = _run_backfill(self.db, _bf_data(spread_points=None), cost)
        self.assertEqual(res["created"], 1, res)
        s = self.db.one("SELECT quality, entry_json FROM ml_samples")
        self.assertEqual(s["quality"], "COST_UNKNOWN")
        flags = json.loads(s["entry_json"])["spec"]["cost_flags"]
        self.assertIn("SPREAD_UNKNOWN", flags)
        self.assertNotIn("SPREAD_FROM_BAR_SPREAD_FIELD", flags)          # the spread did NOT come from the bar
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM ml_samples WHERE quality='COST_UNKNOWN'")["n"], 1)

    def test_bar_spread_known_keeps_approx(self):
        cost = {"spread": 0.0, "slippage": 0.0, "commission": 0.001, "point": 0.01, "flags": ["SPREAD_FROM_BAR_SPREAD_FIELD"]}
        _run_backfill(self.db, _bf_data(spread_points=12), cost)
        s = self.db.one("SELECT quality, entry_json FROM ml_samples")
        self.assertEqual(s["quality"], "APPROX")
        spec = json.loads(s["entry_json"])["spec"]
        self.assertAlmostEqual(spec["spread"], 0.12)
        self.assertIn("SPREAD_FROM_BAR_SPREAD_FIELD", spec["cost_flags"])

    def test_uses_user_config_not_package_defaults(self):
        """chunk_19#10: the replay uses the user's ACTIVE thresholds (as live), not AppConfig() defaults."""
        self.cfg.update({"active": {"thresholds": {"watch": 33.0, "early": 44.0, "confirmed": 66.0}}})
        cost = {"spread": 0.1, "slippage": 0.0, "commission": 0.001, "point": 0.01, "flags": []}
        res, scan = _run_backfill(self.db, _bf_data(spread_points=10), cost)
        self.assertTrue(scan.called)
        self.assertEqual(scan.call_args.kwargs["thresholds"], {"watch": 33.0, "early": 44.0, "confirmed": 66.0})
        self.assertTrue(res.get("config_hash"))

    def test_temp_replay_folder_removed(self):
        """chunk_19#11: the private replay database folder is removed - also when the replay fails."""
        cost = {"spread": 0.1, "slippage": 0.0, "commission": 0.001, "point": 0.01, "flags": []}
        made = []
        import tempfile as _tf
        real = _tf.mkdtemp

        def mk(*a, **k):
            d = real(dir=self.td.dir, prefix="bf_")
            made.append(Path(d))
            return d
        with mock.patch("tempfile.mkdtemp", side_effect=mk):
            _run_backfill(self.db, _bf_data(spread_points=10), cost)
            with self.assertRaises(RuntimeError):
                _run_backfill(self.db, _bf_data(spread_points=10), cost, scan=mock.Mock(side_effect=RuntimeError("boom")))
        self.assertEqual(len(made), 2)
        for d in made:
            self.assertFalse(d.exists(), d)


# ============================================================================= dataset
class TestDataset(unittest.TestCase):
    def setUp(self):
        from masterquo.db.database import Database
        self.td = TempData()
        self.db = Database()

    def tearDown(self):
        self.db.close()
        self.td.close()

    def test_no_stop_loss_is_stored_as_no_entry(self):
        """chunk_19#7: a setup without SL used to raise TypeError in make_spec (NO_ENTRY / NO_VALID_LEVELS never written)."""
        from masterquo.ml.dataset import SampleStore
        st = SampleStore(self.db)
        cost = {"spread": 0.1, "slippage": 0.0, "commission": 0.0, "flags": []}
        ok = st.create(rec=_rec(sl=None), setup_id="NOSL", version=1, view=None, asof=T0, source="LIVE", quality="HIGH", feed_id="T", cost=cost,
                       synthetic=False)
        self.assertTrue(ok)
        r = self.db.one("SELECT status, exit_reason, entry_json FROM ml_samples WHERE sample_id='NOSL:1'")
        self.assertEqual((r["status"], r["exit_reason"]), ("NO_ENTRY", "NO_VALID_LEVELS"))
        self.assertIsNone(json.loads(r["entry_json"])["spec"])
        self.assertEqual(st.pending(), [])                                # never handed to the labeller

    def test_excluded_counts_per_world(self):
        """chunk_19#19: approx_excluded / cost_unknown_excluded count only the selected (synthetic or real) world."""
        from masterquo.ml.dataset import SampleStore
        for i, (syn, q) in enumerate(((0, "COST_UNKNOWN"), (1, "COST_UNKNOWN"), (1, "COST_UNKNOWN"), (0, "APPROX"), (1, "APPROX"), (1, "APPROX"))):
            self.db.execute("""INSERT INTO ml_samples(sample_id, setup_id, setup_version, group_id, symbol, feed_id, strategy_id, strategy_version, direction,
                               timeframe, asof_utc, feature_schema_version, features_json, entry_json, cost_model_version, label_policy_version, source,
                               quality, status, label, synthetic, created_at, updated_at) VALUES (?,?,1,?,'XAUUSD-','T','S01','1','LONG','M15',?,'v','{}','{}','c','l',
                               'LIVE',?,'LABELED',1,?,?,?)""", (f"X{i}:1", f"X{i}", f"X{i}", iso(T0), q, syn, iso(T0), iso(T0)))
        real = SampleStore(self.db).counts(False, False)
        syn = SampleStore(self.db).counts(False, True)
        self.assertEqual((real["cost_unknown_excluded"], real["approx_excluded"]), (1, 1))
        self.assertEqual((syn["cost_unknown_excluded"], syn["approx_excluded"]), (2, 2))


# ============================================================================= models / validation / trainer
def _feat(rng, a=None):
    from masterquo.ml import features as fe
    f = {k: None for k in fe.FEATURE_NAMES}
    a = rng.gauss(0, 1) if a is None else a
    f.update({"M15_rsi": 50 + 10 * a, "M5_er20": 0.5 + 0.2 * rng.gauss(0, 1), "strategy_id": "S01", "direction": "LONG", "timeframe": "M15",
              "regime": "RANGE", "family": "TREND"})
    return f


def gen_rows(n=700, seed=1, legacy_every=0):
    """Rows with a planted dependence; every `legacy_every`-th row is schema MQ-FEAT-1.1.0 with the constant dxy_missing=1.0."""
    from masterquo.ml import features as fe
    rng = random.Random(seed)
    rows, t = [], T0
    for i in range(n):
        t += timedelta(minutes=rng.choice((15, 30, 45)))
        a = rng.gauss(0, 1)
        f = _feat(rng, a)
        legacy = bool(legacy_every) and i % legacy_every == 0
        f["dxy_missing"] = 1.0 if legacy else float(i % 2)
        y = int(rng.random() < 1 / (1 + math.exp(-1.5 * a)))
        rows.append({"sample_id": f"S{i}:1", "setup_id": f"S{i}", "group_id": f"S{i}", "event_id": f"E{i}", "strategy_id": "S01", "direction": "LONG",
                     "timeframe": "M15", "asof_utc": iso(t), "label_end_utc": iso(t + timedelta(minutes=10)), "label_known_utc": iso(t + timedelta(minutes=20)),
                     "features_json": json.dumps(fe.to_json_safe(f)), "label": y, "outcome_r": 1.0 if y else -1.0, "quality": "HIGH", "source": "TEST",
                     "feature_schema_version": "MQ-FEAT-1.1.0" if legacy else fe.FEATURE_SCHEMA_VERSION})
    return rows


def write_snapshot(rows, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return str(path)


class TestModelsValidation(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_policy_exposure_never_above_one(self):
        """chunk_20#4: an earlier row with a longer label window must not push exposure above 1."""
        import numpy as np
        from masterquo.ml import validation as val
        rows = [{"asof_utc": "2026-03-02T10:00:00Z", "label_end_utc": "2026-03-02T20:00:00Z", "outcome_r": 1.0},
                {"asof_utc": "2026-03-02T10:30:00Z", "label_end_utc": "2026-03-02T10:45:00Z", "outcome_r": -1.0}]
        pe = val.policy_eval(rows, np.array([True, False]))
        self.assertLessEqual(pe["exposure"], 1.0)
        self.assertAlmostEqual(pe["exposure"], 1.0)

    def test_trainer_legacy_dxy_missing_is_unknown(self):
        """chunk_20#1: rows of MQ-FEAT-1.0.0/1.1.0 (dxy_missing = constant 1.0) enter a 1.2.0 training with dxy_missing unknown (NaN)."""
        from masterquo.ml import features as fe
        from masterquo.ml import prep, trainer
        seen = {}

        class _Stop(Exception):
            pass

        def fit(self, rows):
            seen["rows"] = rows
            raise _Stop()
        snap = write_snapshot(gen_rows(700, legacy_every=3), Path(self.td.dir) / "s.jsonl.gz")
        cfg = {"embargo_minutes": 0, "min_block_samples": 10, "min_block_per_class": 2, "dt_tuning_budget": 2, "xgb_tuning_budget": 1,
               "xgb_max_trees": 20, "xgb_threads": 1, "xgb_device": "cpu", "random_state": 1, "promotion": {}}
        with mock.patch.object(prep.Preprocessor, "fit", fit), self.assertRaises(_Stop):
            trainer.run(snap, cfg, str(Path(self.td.dir) / "models"), None)
        rows = seen["rows"]
        self.assertTrue(rows)
        legacy = [r for r in rows if r["M15_rsi"] is not None and r.get("dxy_missing") is not None and isinstance(r["dxy_missing"], float)
                  and math.isnan(r["dxy_missing"])]
        known = [r for r in rows if isinstance(r.get("dxy_missing"), float) and not math.isnan(r["dxy_missing"])]
        self.assertTrue(legacy, "legacy rows must carry dxy_missing = NaN")
        self.assertTrue(known)
        self.assertEqual(fe.FEATURE_SCHEMA_VERSION, "MQ-FEAT-1.3.0")      # 1.46: zone semantics SEM-2; dxy as in 1.2.0
        # every 1.2.0 row keeps its real 0/1 flag
        self.assertTrue(all(r["dxy_missing"] in (0.0, 1.0) for r in known))
        self.assertTrue(any(r["dxy_missing"] == 0.0 for r in known))


# ============================================================================= registry
def _fake_result(td: Path, ids=None, snapshot=None):
    """Result dict shaped like trainer.run(); both models pass the default promotion rules."""
    from masterquo.config import MLConfig
    test = {"n": 400, "pos": 200, "neg": 200, "brier": 0.20, "brier_gain": 0.05, "brier_gain_se": 0.005, "ece": 0.02, "log_loss": 0.6, "pr_auc": 0.6}
    models = {}
    for fam, b in (("DECISION_TREE", 0.21), ("XGBOOST", 0.20)):
        mid = f"{fam[:2]}-T-{b}"
        models[fam] = {"model_id": mid, "path": str(td / "models" / mid), "train": {}, "threshold": 0.5, "calibration": "ISOTONIC",
                       "test": dict(test, brier=b), "raw_test_brier": b, "policy": {"avg_r": 0.3, "max_dd_r": 1.0, "trades": 50},
                       "policy_bootstrap": {}, "by_strategy": {}, "by_direction": {}, "by_session": {}, "by_regime": {}}
    res = {"status": "DONE", "snapshot": snapshot or str(td / "none.jsonl.gz"),
           "validation": {"windows": {"test": ["2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z"]}, "test_sample_ids": ids},
           "baselines": {"base_rate": {"brier": 0.25}, "no_ml_policy": {"avg_r": 0.1, "max_dd_r": 1.0}}, "models": models,
           "feature_schema_version": "MQ-FEAT-1.2.0"}
    return res, MLConfig().promotion.model_dump()


class TestRegistry(unittest.TestCase):
    def setUp(self):
        from masterquo.db.database import Database
        self.td = TempData()
        self.root = Path(self.td.dir)
        self.db = Database(self.root / "reg.sqlite")

    def tearDown(self):
        self.db.close()
        self.td.close()

    def test_unavailable_champion_comparison_is_reported_and_blocks_promotion(self):
        """chunk_19#3 / arch146 w2 I0789 (owner's decision: fix everything): an impossible comparison (here: result without test ids) no
        longer promotes the passing challenger (was the 1.45.0 rule) - the champion stays, the cause is reported (reason, event,
        compare_error)."""
        from masterquo.ml.registry import Registry
        reg = Registry(self.db, self.root / "models")
        reg.champion = object()                                           # a loaded champion exists
        snap = write_snapshot([], self.root / "snap.jsonl.gz")
        res, prom = _fake_result(self.root, ids=None, snapshot=snap)
        with mock.patch.object(Registry, "promote") as promote:
            dec = reg.register(res, "SNAP", prom)
        best = min((m["test"]["brier"], m["model_id"]) for m in res["models"].values())[1]
        promote.assert_not_called()
        self.assertFalse(dec[best]["passed"], dec)
        self.assertIn("CHAMPION_COMPARISON_UNAVAILABLE:NO_TEST_SAMPLE_IDS", dec[best]["reasons"])
        ev = [e for e in reg.events() if e["kind"] == "CHAMPION_COMPARISON_UNAVAILABLE"]
        self.assertEqual([(e["model_id"], json.loads(e["detail_json"])["error"]) for e in ev], [(best, "NO_TEST_SAMPLE_IDS")])

    def test_approx_models_are_all_research_approx(self):
        """chunk_19#14: allow_promotion=False -> EVERY passing model is RESEARCH_APPROX (none becomes a shadow-scored CHALLENGER)."""
        from masterquo.ml.registry import Registry
        reg = Registry(self.db, self.root / "models")
        res, prom = _fake_result(self.root, ids=[])
        with mock.patch.object(Registry, "promote") as promote:
            dec = reg.register(res, "SNAP", prom, allow_promotion=False)
        promote.assert_not_called()
        self.assertTrue(all(d["passed"] for d in dec.values()), dec)
        st = {r["model_id"]: r["status"] for r in self.db.query("SELECT model_id, status FROM ml_models")}
        self.assertEqual(set(st.values()), {"RESEARCH_APPROX"}, st)
        self.assertEqual(reg.challengers, {})

    def test_challenger_errors_reset_and_reported(self):
        """chunk_19#18: load errors of challengers are reset on reload and shown in MLService.status()."""
        from masterquo.ml.registry import Registry
        self.db.execute("""INSERT INTO ml_models(model_id, family, version, status, created_at, snapshot_id, feature_schema_version, path, metrics_json,
                           promotion_json) VALUES ('XG-BROKEN','XGBOOST',1,'CHALLENGER',?,'S','v',?,'{}','{}')""", (iso(T0), str(self.root / "missing")))
        reg = Registry(self.db, self.root / "models")
        self.assertIn("XG-BROKEN", reg.challenger_errors)
        self.db.execute("UPDATE ml_models SET status='RETIRED' WHERE model_id='XG-BROKEN'")
        reg.reload()
        self.assertEqual(reg.challenger_errors, {})


# ============================================================================= service
class _Bridge:
    synthetic = True
    account_key = "SYN:1"

    def __init__(self, quote=None, offset=0):
        self.symbol_info = {"point": 0.01, "trade_contract_size": 100.0, "spread": 12}
        self.clock = SimpleNamespace(offset=offset)
        self._quote = quote or {"bid": 2000.0, "ask": 2000.1, "spread": 0.1, "age_seconds": 1.0}
        self._lock = threading.RLock()
        self.deals = []

    def account_status(self):
        return {"server": "Synthetic", "login": 1, "trade_mode": "DEMO"}

    def quote_status(self):
        return self._quote

    def bars(self, tf, include_forming=True):
        return []

    def calc_profit(self, *a):
        return 100.0


class TestService(unittest.TestCase):
    def setUp(self):
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.events import AppLog, EventBus
        self.td = TempData()
        self.cfg = ConfigStore()
        self.db = Database()
        self.bus = EventBus()
        self.log = AppLog(self.db, self.bus)

    def tearDown(self):
        self.db.close()
        self.td.close()

    def svc(self, bridge=None, spawn=None):
        from masterquo.ml.service import MLService
        return MLService(self.cfg, self.db, bridge or _Bridge(), self.bus, self.log, root=Path(self.td.dir) / "ml", spawn=spawn)

    def test_cost_without_any_spread_is_unknown(self):
        """chunk_19#6 (live): no spread in the quote nor in symbol_info -> SPREAD_UNKNOWN (sample COST_UNKNOWN), never spread 0 / HIGH."""
        b = _Bridge(quote={"bid": 2000.0, "ask": 2000.1})
        b.symbol_info = {"point": 0.01, "trade_contract_size": 100.0}
        c = self.svc(bridge=b)._cost()
        self.assertIn("SPREAD_UNKNOWN", c["flags"])
        self.assertNotIn("SPREAD_FROM_SYMBOL_INFO", c["flags"])
        b2 = _Bridge(quote={"bid": 2000.0, "ask": 2000.1})
        c2 = self.svc(bridge=b2)._cost()
        self.assertIn("SPREAD_FROM_SYMBOL_INFO", c2["flags"])
        self.assertAlmostEqual(c2["spread"], 0.12)

    def _tick_once(self, ml):
        orig = ml.bridge.quote_status

        def q():
            ml._stop.set()                                                # one iteration of the loop
            return orig()
        ml.bridge.quote_status = q
        ml._tick_loop()

    def test_ticks_skipped_while_server_offset_unknown(self):
        """chunk_19#1: a quote with server time and no verified offset is not recorded as UTC."""
        msc = 1_772_445_600_000
        ml = self.svc(bridge=_Bridge(quote={"bid": 2000.0, "ask": 2000.1, "time_msc": msc}, offset=None))
        self._tick_once(ml)
        self.assertEqual(len(ml.ticks), 0)
        ml2 = self.svc(bridge=_Bridge(quote={"bid": 2000.0, "ask": 2000.1, "time_msc": msc}, offset=7200))
        self._tick_once(ml2)
        self.assertEqual(list(ml2.ticks), [(msc / 1000 - 7200, 2000.0, 2000.1)])

    def test_status_reads_job_once(self):
        """chunk_19#8: a job finishing between the check and the read of self._job raised TypeError in status()."""
        ml = self.svc()

        class Racy(dict):
            def __bool__(self):
                ml._job = None                                            # _finish_job in another thread
                return True
        ml._job = Racy(job_id="J1", snapshot_id="S1", file=str(Path(self.td.dir) / "j.json"))
        with mock.patch.object(type(ml), "phase", return_value=None):
            st = ml.status(compact=True)
        self.assertEqual(st["job"], {"job_id": "J1", "snapshot_id": "S1"})
        self.assertIn("challenger_errors", st)

    def _interrupted_job(self, ml, prior=None):
        job_id = "JOB-OLD"
        f = ml.root / "jobs" / f"{job_id}.json"
        f.write_text(json.dumps({"job_id": job_id, "snapshot": "x", "snapshot_id": "S", "cfg": {}, "out_dir": "o", "prior_test_end": prior}), encoding="utf-8")
        self.db.execute("INSERT INTO ml_jobs(job_id, kind, status, created_at, started_at, snapshot_id, detail_json) VALUES (?,?,?,?,?,?,?)",
                        (job_id, "TRAIN", "INTERRUPTED", iso(T0), iso(T0), "S", "{}"))
        return f

    def test_resume_respects_job_lock(self):
        """chunk_19#9: a resume while start_training holds the job lock must not spawn a second trainer."""
        spawned = []
        ml = self.svc(spawn=lambda f: spawned.append(f) or SimpleNamespace(poll=lambda: None, kill=lambda: None))
        self._interrupted_job(ml)
        self.assertTrue(ml._job_lock.acquire(blocking=False))            # start_training in progress (snapshot being written)
        try:
            r = ml.resume_interrupted()
        finally:
            ml._job_lock.release()
        self.assertFalse(r["started"])
        self.assertEqual(r["reason"], "JOB_LOCKED")
        self.assertEqual(spawned, [])
        r2 = ml.resume_interrupted()                                      # lock free -> resumes
        self.assertTrue(r2["started"] and r2["resumed"], r2)
        self.assertEqual(len(spawned), 1)

    def test_resume_uses_current_prior_test_end(self):
        """chunk_20#3: the resumed job's TEST must start after every test window used since the original start."""
        spawned = []
        ml = self.svc(spawn=lambda f: spawned.append(f) or SimpleNamespace(poll=lambda: None, kill=lambda: None))
        f = self._interrupted_job(ml, prior="2026-01-01T00:00:00Z")
        self.db.execute("""INSERT INTO ml_models(model_id, family, version, status, created_at, snapshot_id, feature_schema_version, path, metrics_json,
                           promotion_json) VALUES ('DT-NEW','DECISION_TREE',1,'CHAMPION',?,'S2','v','p',?,'{}')""",
                        (iso(T0), json.dumps({"test_window": ["2026-02-01T00:00:00Z", "2026-02-20T00:00:00Z"]})))
        r = ml.resume_interrupted()
        self.assertTrue(r["started"], r)
        self.assertEqual(json.loads(Path(spawned[-1]).read_text(encoding="utf-8"))["prior_test_end"], "2026-02-20T00:00:00Z")
        self.assertEqual(Path(spawned[-1]), f)


# ============================================================================= offline trainer
class TestOffline(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _dataset(self) -> Path:
        ds = Path(self.td.dir) / "ds"
        ds.mkdir()
        meta = {"instrument": "XAUUSD", "symbol": "XAUUSD-", "file_prefix": "XAUUSD", "data_kind": "SYNTHETIC_TEST", "tick_size": 0.01,
                "spec": {"point": 0.01, "trade_contract_size": 100.0}, "dataset_id": "T"}
        (ds / "source_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        for tf in ("M1", "M5", "M15", "H1", "H4", "D1"):
            (ds / f"XAUUSD_{tf}.csv").write_text("time_open_utc,open,high,low,close,tick_volume,spread_points\n"
                                                 "2026-03-02T08:00:00Z,1,2,0.5,1.5,10,12\n", encoding="utf-8")
        return ds

    def test_trainer_exception_marks_job_failed(self):
        """chunk_19#21: an exception of the trainer left the ml_jobs row RUNNING."""
        from masterquo.ml import backfill, offline, trainer
        from masterquo.ml.dataset import SampleStore
        from masterquo.ml.router import ml_store
        with mock.patch.object(backfill, "run", return_value={"created": 0}), \
                mock.patch.object(SampleStore, "counts", return_value={"labeled": 10_000, "by_status": {}}), \
                mock.patch.object(trainer, "run", side_effect=MemoryError("xgb")), self.assertRaises(MemoryError):
            offline.train("XAUUSD", self._dataset(), commission=0.5, log=lambda m: None)
        db, _ = ml_store("XAUUSD")
        try:
            rows = db.query("SELECT status, detail_json FROM ml_jobs WHERE job_id LIKE 'OFF-%'")
        finally:
            db.close()
        self.assertEqual([r["status"] for r in rows], ["FAILED"])
        self.assertIn("MemoryError", json.loads(rows[0]["detail_json"])["reason"])


# ============================================================================= scalp ML task
def _scalp_rows(n=300, seed=5):
    import numpy as np
    from masterquo.scalp.strategy import NET_FEATURES
    rng = np.random.default_rng(seed)
    out = []
    t0 = datetime(2026, 1, 5, tzinfo=UTC)
    for k in range(n):
        for side in ("BUY", "SELL"):
            t = t0 + timedelta(minutes=90 * k + (0 if side == "BUY" else 5))
            y = int(rng.random() < 0.5)
            nr = (1.0 if y else -1.0) * float(rng.uniform(0.3, 1.5))
            out.append({"setup_id": f"{side}{k}", "range_id": f"R{side}{k}", "side": side, "signal_time": t.isoformat(), "fill_time": t.isoformat(),
                        "label_end": (t + timedelta(minutes=30)).isoformat(), "x": {f: float(rng.normal()) for f in NET_FEATURES}, "net_r": nr, "y": y,
                        "spread": 0.1, "risk": 1.0, "net_price": nr, "ambiguous": False})
    return out


class _Clf:
    def predict(self, X, output_margin=False):
        import numpy as np
        return np.zeros(len(X))


class _Bundle:
    def predict_matrix(self, X):
        import numpy as np
        return {"p": np.full(len(X), 0.5), "ev": np.zeros(len(X)), "margin": np.zeros(len(X))}


class TestScalpTask(unittest.TestCase):
    def setUp(self):
        from masterquo.ml import scalp_task as stk
        self.td = TempData()
        stk._cache.clear()

    def tearDown(self):
        from masterquo.ml import scalp_task as stk
        stk._cache.clear()
        self.td.close()

    def _train(self, db):
        from masterquo.ml import scalp_task as stk
        data = {"instrument": "XAUUSD", "symbol": "XAUUSD-", "dataset_id": "T", "data_kind": "SYNTHETIC_TEST", "rows": _scalp_rows(), "blocked": 0,
                "profile_id": "p", "profile_hash": "h", "tick": 0.01, "costs": {}, "precision": "OHLC_APPROX",
                "prof": {"exits": {"max_hold_minutes": {"value": 30}}}}
        fp = {"clf": _Clf(), "reg": _Clf(), "calibrator": {"a": 1.0, "b": 0.0, "status": "TEST"}, "policy": None, "cfg": {}, "sizes": {},
              "trials": [], "policy_trials": [], "n_trees_clf": 1, "n_trees_reg": 1}
        with mock.patch.object(stk, "build_dataset", return_value=data), mock.patch.object(stk, "fit_pair", return_value=fp), \
                mock.patch.object(stk, "save_bundle", side_effect=lambda d, fp, rep, side, data: f"hash-{side}"), \
                mock.patch.object(stk, "load_bundle", return_value=_Bundle()):
            return stk.train("XAUUSD", Path(self.td.dir), db=db, log=lambda m: None)

    def test_holdout_ledger_same_run_both_sides_fresh(self):
        """chunk_19#4: SELL of the SAME run was always REUSED_PERIOD_EXPLORATORY (BUY's reservation of the same period)."""
        from masterquo.db.database import Database
        db = Database()
        try:
            rep = self._train(db)
            st = {s: (v.get("holdout") or {}).get("ledger", {}).get("status") for s, v in rep["sides"].items()}
            self.assertEqual(st, {"BUY": "FRESH", "SELL": "FRESH"}, rep["sides"])
            self.assertEqual(db.one("SELECT COUNT(*) n FROM eval_ledger")["n"], 2)
            rep2 = self._train(db)                                         # a later run on the same period IS a re-use
            st2 = {s: (v.get("holdout") or {}).get("ledger", {}).get("status") for s, v in rep2["sides"].items()}
            self.assertEqual(st2, {"BUY": "REUSED_PERIOD_EXPLORATORY", "SELL": "REUSED_PERIOD_EXPLORATORY"})
        finally:
            db.close()

    def _registry(self):
        from masterquo.ml import scalp_task as stk
        reg = {"schema": "pmw-ml-scalp-registry-1", "history": [],
               "selected": {"BUY": {"run_id": "R1", "role": "OBSERVE", "model_hash": "hb"}, "SELL": {"run_id": "R1", "role": "OBSERVE", "model_hash": "hs"}},
               "runs": {"R1": {"run_dir": str(Path(self.td.dir) / "R1"), "status": "EVALUATED", "role": "RESEARCH", "sides": {}}}}
        (stk.root("XAUUSD") / "registry.json").write_text(json.dumps(reg), encoding="utf-8")

    def test_selected_bundle_cache_per_side(self):
        """chunk_19#5: alternating BUY / SELL candidates reloaded both bundles every time (one-entry cache cleared on a side change)."""
        from masterquo.ml import scalp_task as stk
        self._registry()
        loads = []
        with mock.patch.object(stk, "load_bundle", side_effect=lambda d: loads.append(d.name) or object()):
            got = [stk.selected_bundle("XAUUSD", s)[0] for s in ("BUY", "SELL", "BUY", "SELL", "BUY")]
        self.assertEqual(sorted(loads), ["bundle_BUY", "bundle_SELL"])
        self.assertIs(got[0], got[2])
        self.assertIs(got[1], got[3])

    def test_selected_bundle_threads(self):
        from masterquo.ml import scalp_task as stk
        self._registry()
        errors = []

        def work(side):
            try:
                for _ in range(200):
                    stk.selected_bundle("XAUUSD", side)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        with mock.patch.object(stk, "load_bundle", side_effect=lambda d: object()):
            ts = [threading.Thread(target=work, args=(s,)) for s in ("BUY", "SELL", "BUY", "SELL")]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(errors, [])

    def test_cli_report_unknown_run_is_blad_not_traceback(self):
        """chunk_19#22: an unknown --run / missing report.json -> [BLAD] + exit 2 (was KeyError / FileNotFoundError)."""
        import contextlib
        import io

        from masterquo.ml import scalp_cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(scalp_cli.main(["report", "--asset", "XAUUSD", "--run", "NOPE"]), 2)
        self.assertIn("[BLAD]", buf.getvalue())
        self._registry()                                                  # run R1 exists, its report.json does not
        with contextlib.redirect_stdout(buf):
            self.assertEqual(scalp_cli.main(["report", "--asset", "XAUUSD", "--run", "R1"]), 2)


# ============================================================================= association rules (already fixed in 1.46)
class TestAssociationRules(unittest.TestCase):
    def test_contrary_edge_is_not_supported(self):
        """chunk_19#12: CONTRARY_EDGE / HOLD and candidate_direction_supported=True were reported together."""
        from masterquo.ml import association_rules as AR
        m = {"status": "READY", "rules": [{"mask": 1, "edge_up": 0.10, "edge_down": -0.10}, {"mask": 2, "edge_up": -0.20, "edge_down": 0.20}]}
        a = AR.assess(m, 3, "LONG", mode="ASSIST")
        self.assertEqual((a["action"], a["reason"], a["candidate_direction_supported"]), ("HOLD", "CONTRARY_EDGE", False))


if __name__ == "__main__":
    unittest.main()
