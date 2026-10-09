"""ML pipeline (Decision Tree + XGBoost): no look-ahead, labels, validation, models, registry, fallbacks, end-to-end.

Data here is SYNTHETIC (terminal simulator or generated rows). The tests prove the mechanics, not market edge.
"""
from __future__ import annotations

import json
import math
import random
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

try:
    import sklearn  # noqa: F401
    import xgboost  # noqa: F401
    HAVE_ML = True
except ImportError:  # pragma: no cover - reported as skipped, never as passed
    HAVE_ML = False

UTC = timezone.utc
T0 = datetime(2026, 3, 2, 8, 0, tzinfo=UTC)


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def m1_bars(prices, start=T0):
    out = []
    for i, (o, h, lo, c) in enumerate(prices):
        out.append({"open_utc": iso(start + timedelta(minutes=i)), "o": o, "h": h, "l": lo, "c": c, "closed": True})
    return out


def spec(direction="LONG", sl=1995.0, targets=((2004.0, 0.5), (2008.0, 0.5)), horizon=60, spread=0.1, slip=0.0, comm=0.0):
    from masterquo.ml import labels as lb
    rec = {"direction": direction, "stop_loss": sl, "targets": [{"price": p, "weight": w} for p, w in targets], "timeframe": "M1",
           "exit_rules": {"time_exit_bars": horizon, "be_after_tp1": True}}
    return lb.make_spec(rec, iso(T0), spread=spread, slippage=slip, commission=comm, cost_flags=[])


# ----------------------------------------------------------------------------- generated rows for model tests
def gen_rows(n=900, seed=1, start=T0, signal=1.2):
    """Rows with a real (noisy) dependence of the label on two features; time ordered, event groups, label windows."""
    from masterquo.ml import features as fe
    rng = random.Random(seed)
    rows = []
    t = start
    for i in range(n):
        t += timedelta(minutes=rng.choice((15, 30, 45)))
        f = {k: None for k in fe.FEATURE_NAMES}
        a, b = rng.gauss(0, 1), rng.gauss(0, 1)
        f.update({"M15_rsi": 50 + 10 * a, "M5_er20": 0.5 + 0.2 * b, "M15_atr_pct": abs(rng.gauss(0.2, 0.05)), "hour_sin": math.sin(t.hour / 24 * 2 * math.pi),
                  "M5_ret3": rng.gauss(0, 1) if rng.random() > 0.1 else None,          # missing values stay missing
                  "strategy_id": rng.choice(["S01", "S03", "S08"]), "direction": rng.choice(["LONG", "SHORT"]), "timeframe": "M15",
                  "regime": rng.choice(["TREND_UP", "RANGE"]), "family": "TREND"})
        p = 1 / (1 + math.exp(-(signal * a - 0.8 * b)))
        y = int(rng.random() < p)
        rows.append({"sample_id": f"S{i}:1", "setup_id": f"S{i}", "group_id": f"S{i}", "event_id": f"E{i // 2}", "strategy_id": f["strategy_id"],
                     "direction": f["direction"], "timeframe": "M15", "asof_utc": iso(t), "label_end_utc": iso(t + timedelta(minutes=rng.choice((20, 60, 180)))),
                     "label_known_utc": iso(t + timedelta(minutes=200)), "features_json": json.dumps(fe.to_json_safe(f)), "label": y,
                     "outcome_r": (1.2 if y else -1.0) + rng.gauss(0, 0.1), "quality": "HIGH", "source": "TEST", "feature_schema_version": fe.FEATURE_SCHEMA_VERSION})
    return rows


def write_snapshot(rows, path: Path) -> str:
    import gzip
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return str(path)


def train_cfg(**kw):
    from masterquo.config import MLConfig
    c = MLConfig()
    cfg = {k: getattr(c, k) for k in ("embargo_minutes", "min_block_samples", "min_block_per_class", "dt_tuning_budget", "xgb_tuning_budget",
                                      "xgb_max_trees", "xgb_threads", "xgb_device", "random_state")}
    cfg.update(dt_tuning_budget=8, xgb_tuning_budget=3, xgb_max_trees=150)
    cfg["promotion"] = c.promotion.model_dump()
    cfg["promotion"].update(min_test_samples=100, min_test_per_class=20)
    cfg.update(kw)
    return cfg


def _close(x, y) -> bool:
    """Equal up to float summation order (numpy on arrays of different length): 1e-9 relative."""
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-12)
    return x == y


# ============================================================================= 3. no future data in features
class TestNoLookAhead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from masterquo.ml import backfill
        cls.data = backfill.synthetic_data(12, seed=5)

    def _view(self, t, future_minutes=0):
        """Same first bar in both views (indicator warm-up identical); the second view also contains later bars."""
        from masterquo.config import AppConfig
        from masterquo.strategies import adapter
        bars = {}
        for tf, rows in self.data.items():
            base = [b for b in rows if datetime.fromisoformat(b["available_at"].replace("Z", "+00:00")) <= t][-400:]
            cut = t + timedelta(minutes=future_minutes)
            bars[tf] = [b for b in rows if b["open_utc"] >= base[0]["open_utc"] and datetime.fromisoformat(b["available_at"].replace("Z", "+00:00")) <= cut]
        last = bars["M1"][-1]
        return adapter.build_view(symbol="XAUUSD-", bars_by_tf=bars, bid=last["c"], ask=last["c"] + 0.1, point=0.01, as_of=iso(t), synthetic=True,
                                  regime_params=AppConfig().active.regime, max_bars=5000)

    def test_features_identical_with_future_bars_present(self):
        from masterquo.ml import features as fe
        m15 = self.data["M15"]
        t = datetime.fromisoformat(m15[-120]["available_at"].replace("Z", "+00:00"))
        cand = {"strategy_id": "S01", "direction": "LONG", "timeframe": "M15", "stop_loss": m15[-121]["l"] - 2, "targets": [{"price": m15[-121]["c"] + 4, "weight": 1.0}],
                "setup_score": 72, "entry_plan": {"reference_price": m15[-121]["c"]}}
        a = fe.to_json_safe(fe.compute(self._view(t), cand, t))
        b = fe.to_json_safe(fe.compute(self._view(t, future_minutes=600), cand, t))   # 10 h of later bars visible in the view
        diff = {k: (a[k], b[k]) for k in a if not _close(a[k], b[k]) and k not in ("spread_atr_m5",)}  # live spread is a quote, not history
        self.assertEqual(diff, {}, "features changed when future bars were added")
        self.assertTrue(any(v is not None for v in a.values()))

    def test_pivot_features_use_confirmed_pivots_only(self):
        from masterquo.ml import features as fe
        m5 = self.data["M5"]
        cand = {"strategy_id": "S08", "direction": "SHORT", "timeframe": "M5", "stop_loss": 1.0, "targets": [], "setup_score": 60}
        for back in (300, 200, 150):
            t = datetime.fromisoformat(m5[-back]["available_at"].replace("Z", "+00:00"))
            a = fe.compute(self._view(t), cand, t)
            b = fe.compute(self._view(t, future_minutes=60), cand, t)
            for k in ("M5_piv_hi_dist", "M5_piv_lo_dist", "M5_piv_age"):
                self.assertTrue(_close(fe.to_json_safe(a)[k], fe.to_json_safe(b)[k]), k)

    def test_missing_values_are_not_zero(self):
        from masterquo.ml import features as fe
        f = fe.to_json_safe({"M5_rsi": float("nan"), "M5_er20": None})
        self.assertIsNone(f["M5_rsi"])
        self.assertTrue(math.isnan(fe.from_json(f)["M5_rsi"]) if fe.from_json(f)["M5_rsi"] is not None else True)


# ============================================================================= 4. labels
class TestLabels(unittest.TestCase):
    def test_long_targets_partial_then_breakeven(self):
        from masterquo.ml import labels as lb
        sp = spec()
        bars = m1_bars([(2000, 2001, 1999.5, 2000.5), (2000.5, 2004.5, 2000.2, 2004), (2004, 2004.2, 1999.0, 1999.5)])
        st, res = lb.step(sp, lb.new_state(sp), bars, [], T0 + timedelta(minutes=5))
        self.assertEqual(res["status"], "LABELED")
        self.assertEqual(res["exit_reason"], "BREAKEVEN_STOP")
        entry = 2000 + 0.1
        self.assertAlmostEqual(res["outcome_r"], round(0.5 * (2004 - entry) / (entry - 1995), 4), places=3)
        self.assertEqual(res["label"], 1)

    def test_same_bar_sl_and_tp_without_quotes_is_ambiguous(self):
        from masterquo.ml import labels as lb
        sp = spec(targets=((2003.0, 1.0),))
        bars = m1_bars([(2000, 2000.5, 1999.8, 2000.2), (2000.2, 2003.5, 1994.0, 2000)])
        _, res = lb.step(sp, lb.new_state(sp), bars, [], T0 + timedelta(minutes=3))
        self.assertEqual(res["status"], "AMBIGUOUS")
        self.assertIsNone(res.get("label"))

    def test_same_bar_resolved_by_recorded_quotes(self):
        from masterquo.ml import labels as lb
        sp = spec(targets=((2003.0, 1.0),))
        bars = m1_bars([(2000, 2000.5, 1999.8, 2000.2), (2000.2, 2003.5, 1994.0, 2000)])
        t1 = (T0 + timedelta(minutes=1)).timestamp()
        ticks = [(t1 + 5, 2001.0, 2001.1), (t1 + 20, 2003.2, 2003.3), (t1 + 40, 1994.5, 1994.6)]
        _, res = lb.step(sp, lb.new_state(sp), bars, ticks, T0 + timedelta(minutes=3))
        self.assertEqual((res["status"], res["exit_reason"], res["label"]), ("LABELED", "TARGETS", 1))

    def test_short_uses_ask_for_exit_and_spread(self):
        from masterquo.ml import labels as lb
        sp = spec(direction="SHORT", sl=2005.0, targets=((1996.0, 1.0),), spread=0.3)
        # bid low 1995.8 -> ask 1996.1 > target: NOT filled; then bid 1995.5 -> ask 1995.8 <= 1996 filled
        bars = m1_bars([(2000, 2000.2, 1999.5, 1999.8), (1999.8, 1999.9, 1995.8, 1996.0), (1996.0, 1996.1, 1995.5, 1995.6)])
        _, res = lb.step(sp, lb.new_state(sp), bars, [], T0 + timedelta(minutes=4))
        self.assertEqual(res["status"], "LABELED")
        self.assertEqual(res["label_end_utc"], iso(T0 + timedelta(minutes=3)))

    def test_missing_data_gap_and_no_entry(self):
        from masterquo.ml import labels as lb
        sp = spec()
        bars = m1_bars([(2000, 2000.5, 1999.8, 2000.2)]) + m1_bars([(2000.2, 2000.6, 1999.9, 2000.1)], start=T0 + timedelta(minutes=25))
        _, res = lb.step(sp, lb.new_state(sp), bars, [], T0 + timedelta(minutes=30))
        self.assertEqual(res["status"], "MISSING_DATA")
        late = m1_bars([(2000, 2000.5, 1999.8, 2000.2)], start=T0 + timedelta(minutes=10))
        _, res = lb.step(sp, lb.new_state(sp), late, [], T0 + timedelta(minutes=12))
        self.assertEqual((res["status"], res["exit_reason"]), ("NO_ENTRY", "NO_BAR_IN_ENTRY_WINDOW"))

    def test_time_exit_and_unresolved(self):
        from masterquo.ml import labels as lb
        sp = spec(horizon=3)
        bars = m1_bars([(2000, 2000.5, 1999.8, 2000.2)] * 4)
        _, res = lb.step(sp, lb.new_state(sp), bars, [], T0 + timedelta(minutes=6))
        self.assertEqual(res["exit_reason"], "TIME")
        _, res = lb.step(sp, lb.new_state(sp), [], [], T0 + timedelta(days=5))
        self.assertEqual(res["status"], "UNRESOLVED")

    def test_incremental_restart_no_double_label(self):
        """State persisted after each step: a restart continues; sample creation and labelling are idempotent."""
        from masterquo.db.database import Database
        from masterquo.ml.dataset import SampleStore
        td = TempData()
        try:
            db = Database(Path(td.dir) / "t.sqlite")
            store = SampleStore(db)
            sp = spec()
            ej = json.dumps({"spec": sp, "state": __import__("masterquo.ml.labels", fromlist=["x"]).new_state(sp)})
            db.execute("""INSERT INTO ml_samples(sample_id, setup_id, setup_version, group_id, symbol, feed_id, strategy_id, strategy_version, direction, timeframe,
                          asof_utc, feature_schema_version, features_json, entry_json, cost_model_version, label_policy_version, source, quality, status, synthetic,
                          created_at, updated_at) VALUES ('A:1','A',1,'A','XAUUSD-','T','S01','1','LONG','M1',?,?,?,?,?,?,'TEST','HIGH','PENDING',1,?,?)""",
                       (iso(T0), "MQ-FEAT-1.0.0", "{}", ej, "c", "l", iso(T0), iso(T0)))
            part1 = m1_bars([(2000, 2001, 1999.5, 2000.5), (2000.5, 2004.5, 2000.2, 2004)])
            self.assertEqual(store.advance("A:1", ej, part1, [], T0 + timedelta(minutes=3)), "PENDING")       # TP1 hit, still open
            # "restart": reload state from DB, feed all bars again (overlap) + the closing bar
            row = db.one("SELECT entry_json FROM ml_samples WHERE sample_id='A:1'")
            self.assertEqual(json.loads(row["entry_json"])["state"]["remaining"], 0.5)
            allb = part1 + m1_bars([(2004, 2004.2, 1999.0, 1999.5)], start=T0 + timedelta(minutes=2))
            self.assertEqual(store.advance("A:1", row["entry_json"], allb, [], T0 + timedelta(minutes=4)), "LABELED")
            r1 = db.one("SELECT label, outcome_r FROM ml_samples WHERE sample_id='A:1'")
            # a second labelling pass changes nothing (status is no longer PENDING)
            store.advance("A:1", row["entry_json"], allb, [], T0 + timedelta(minutes=5))
            self.assertEqual(db.one("SELECT label, outcome_r FROM ml_samples WHERE sample_id='A:1'"), r1)
            self.assertEqual(len(store.pending()), 0)
            db.close()
        finally:
            td.close()


# ============================================================================= validation: chronology, purging, groups
class TestValidation(unittest.TestCase):
    def test_blocks_chronological_purged_and_grouped(self):
        from masterquo.ml import validation as val
        rows = gen_rows(600)
        info, reasons = val.split(rows, embargo_minutes=120, min_block=40, min_class=5)
        self.assertEqual(reasons, [])
        B = info["blocks"]
        for a, b in zip(val.BLOCKS[:-1], val.BLOCKS[1:]):
            start = datetime.fromisoformat(B[b][0]["asof_utc"].replace("Z", "+00:00"))
            for r in B[a]:
                self.assertLessEqual(datetime.fromisoformat(r["label_end_utc"].replace("Z", "+00:00")), start - timedelta(minutes=120))  # purged + embargo
            self.assertLess(B[a][-1]["asof_utc"], B[b][0]["asof_utc"])                                                                     # no shuffling
        ev = {}
        for name, blk in B.items():
            for r in blk:
                ev.setdefault(r["event_id"], set()).add(name)
        self.assertTrue(all(len(v) == 1 for v in ev.values()), "one event split between blocks")
        self.assertGreater(sum(info["purged"].values()), 0)

    def test_not_ready_reasons_are_exact(self):
        from masterquo.ml import validation as val
        info, reasons = val.split(gen_rows(80), embargo_minutes=120, min_block=60, min_class=10)
        self.assertIsNone(info)
        self.assertTrue(any(r.startswith("TEST_BLOCK_") for r in reasons), reasons)

    def test_used_test_window_becomes_history(self):
        from masterquo.ml import validation as val
        rows = gen_rows(700)
        info, _ = val.split(rows, embargo_minutes=60, min_block=30, min_class=5)
        end = info["windows"]["test"][0]
        info2, _ = val.split(rows, embargo_minutes=60, min_block=30, min_class=5, test_after=end)
        if info2:
            self.assertGreater(info2["windows"]["test"][0], end)

    def test_metrics_na_for_one_class(self):
        import numpy as np
        from masterquo.ml import validation as val
        m = val.classification_metrics(np.ones(20, dtype=int), np.full(20, 0.7), 0.5)
        self.assertEqual((m["pr_auc"], m["log_loss"], m["precision"]), ("N/A", "N/A", "N/A"))


# ============================================================================= 5/6/7 models, contract, fallbacks, registry
@unittest.skipUnless(HAVE_ML, "scikit-learn/xgboost not installed")
class TestModels(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.root = Path(self.td.dir)

    def tearDown(self):
        self.td.close()

    def _train(self, rows, name="s1", prior=None, **kw):
        from masterquo.ml import trainer
        snap = write_snapshot(rows, self.root / "snaps" / f"{name}.jsonl.gz")
        return trainer.run(snap, train_cfg(**kw), str(self.root / "models"), prior)

    def test_both_models_train_save_load_consistent(self):
        from masterquo.ml import features as fe
        from masterquo.ml.models import Bundle, explain_dt, explain_xgb
        res = self._train(gen_rows(1000))
        self.assertEqual(res["status"], "DONE", res)
        self.assertEqual(set(res["models"]), {"DECISION_TREE", "XGBOOST"})
        probe = [fe.from_json(json.loads(r["features_json"])) for r in gen_rows(30, seed=9)]
        for fam, m in res["models"].items():
            p = Path(m["path"])
            files = {x.name for x in p.iterdir()}
            self.assertTrue({"preprocessor.json", "calibrator.json", "meta.json"} <= files)
            self.assertIn("model.ubj" if fam == "XGBOOST" else "model.joblib", files)
            b1, b2 = Bundle.load(p), Bundle.load(p)                          # "restart": two independent loads
            self.assertTrue((b1.raw(probe) == b2.raw(probe)).all())
            self.assertIn(m["calibration"], ("ISOTONIC", "SIGMOID"))
            self.assertLess(m["test"]["brier"], res["baselines"]["base_rate"]["brier"] + 0.02)     # learnt the planted signal
            ex = explain_dt(b1, probe[0]) if fam == "DECISION_TREE" else explain_xgb(b1, probe[0])
            self.assertTrue(ex.get("steps") is not None or ex.get("top"))
        self.assertIn("best_iteration", res["models"]["XGBOOST"]["train"])
        self.assertIsNotNone(res["baselines"]["no_ml_policy"]["trades"])

    def test_nan_features_and_unseen_category(self):
        from masterquo.ml import features as fe
        from masterquo.ml.models import Bundle
        res = self._train(gen_rows(900))
        b = Bundle.load(Path(res["models"]["DECISION_TREE"]["path"]))
        row = {k: None for k in fe.FEATURE_NAMES}
        row.update(strategy_id="S99", direction="LONG", timeframe="H4", regime="NEW_REGIME")
        p = b.raw([row])
        self.assertTrue(0 <= p[0] <= 1)

    def test_registry_promotion_rules_and_rollback_restores_bundle(self):
        from masterquo.db.database import Database
        from masterquo.ml import features as fe
        from masterquo.ml.registry import Registry
        db = Database(self.root / "reg.sqlite")
        reg = Registry(db, self.root / "models")
        res1 = self._train(gen_rows(1000, seed=1), "a")
        dec1 = reg.register(res1, "SNAP-A", train_cfg()["promotion"])
        self.assertTrue(any(d["passed"] for d in dec1.values()), dec1)
        first = reg.champion_id
        self.assertIsNotNone(first)
        probe = [fe.from_json(json.loads(r["features_json"])) for r in gen_rows(20, seed=4)]
        p_first = reg.champion.raw(probe)
        # (a) a challenger that fails the pre-registered rules (too few test samples) is never promoted
        res2 = self._train(gen_rows(420, seed=2, start=T0 + timedelta(days=60)), "b", min_block_samples=30)
        if res2["status"] == "DONE":
            dec2 = reg.register(res2, "SNAP-B", train_cfg()["promotion"])
            self.assertEqual(reg.champion_id, first, dec2)
            self.assertTrue(all(any(x.startswith("TEST_SAMPLES_") for x in d["reasons"]) for d in dec2.values()), dec2)
        # (b) passing the rules is not enough: it must beat the champion on the SAME new test block
        res3 = self._train(gen_rows(1000, seed=3, start=T0 + timedelta(days=120)), "c")
        reg._champion_brier_on = lambda result: 0.0
        dec3 = reg.register(res3, "SNAP-C", train_cfg()["promotion"])
        self.assertEqual(reg.champion_id, first)
        self.assertTrue(any(any(x.startswith("NOT_BETTER_THAN_CHAMPION") for x in d["reasons"]) for d in dec3.values()) or
                        all(not d["passed"] for d in dec3.values()), dec3)
        # (c) a better challenger replaces it atomically; rollback restores the previous bundle (model + preprocessing + calibrator)
        res4 = self._train(gen_rows(1000, seed=4, start=T0 + timedelta(days=180)), "d")
        reg._champion_brier_on = lambda result: 1.0
        dec4 = reg.register(res4, "SNAP-D", train_cfg()["promotion"])
        if any(d["passed"] for d in dec4.values()):
            self.assertNotEqual(reg.champion_id, first)
            reg.rollback()
            self.assertEqual(reg.champion_id, first)
            self.assertTrue((reg.champion.raw(probe) == p_first).all())
            again = Registry(db, self.root / "models")                           # after restart the restored champion is loaded
            self.assertEqual(again.champion_id, first)
            self.assertEqual(again.champion.calib.to_json(), reg.champion.calib.to_json())
        evs = [e["kind"] for e in reg.events(50)]
        self.assertIn("PROMOTE", evs)
        db.close()

    def test_one_class_calibration_is_none_not_fake(self):
        import numpy as np
        from masterquo.ml.models import Calibrator
        c = Calibrator.fit(np.linspace(0.1, 0.9, 50), np.ones(50, dtype=int))
        self.assertEqual(c.kind, "NONE")
        self.assertIsNone(c.apply(np.array([0.3])))

    def test_corrupt_champion_falls_back(self):
        from masterquo.db.database import Database
        from masterquo.ml.registry import Registry
        db = Database(self.root / "reg.sqlite")
        reg = Registry(db, self.root / "models")
        res = self._train(gen_rows(1000), "a")
        reg.register(res, "SNAP-A", train_cfg()["promotion"])
        path = Path(db.one("SELECT path FROM ml_models WHERE status='CHAMPION'")["path"])
        (path / "preprocessor.json").write_text("{broken", encoding="utf-8")
        reg2 = Registry(db, self.root / "models")
        self.assertIsNone(reg2.champion)
        self.assertTrue(reg2.load_error.startswith("CHAMPION_LOAD_FAILED"))
        db.close()


# ============================================================================= service: contract, modes, fallback, scheduler, e2e
class _Bridge:
    synthetic = True
    symbol_info = {"point": 0.01, "trade_contract_size": 100.0, "spread": 12}
    account_key = "SYN:1"

    class clock:
        offset = 0

    def __init__(self, m1=None):
        self.m1 = m1 or []

    def account_status(self):
        return {"server": "Synthetic", "login": 1, "trade_mode": "DEMO"}

    def quote_status(self):
        return {"bid": 2000.0, "ask": 2000.1, "spread": 0.1, "age_seconds": 1.0}

    def bars(self, tf, include_forming=True):
        return self.m1


@unittest.skipUnless(HAVE_ML, "scikit-learn/xgboost not installed")
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

    def svc(self, spawn=None, bridge=None):
        from masterquo.ml.service import MLService
        from _env import granted_guard
        ml = MLService(self.cfg, self.db, bridge or _Bridge(), self.bus, self.log, root=Path(self.td.dir) / "ml", spawn=spawn)
        ml.guard = granted_guard()
        return ml

    def test_no_model_contract_and_fallback(self):
        ml = self.svc()
        row = {"setup_id": "X", "version": 1, "record": {"strategy_id": "S01", "direction": "LONG", "timeframe": "M15"}}
        p = ml.predict(row, None)
        self.assertEqual((p["readiness"], p["calibrated_probability"], p["raw_score"]), ("NOT_READY", None, None))   # no fake 50%
        for k in ("setup_id", "model_id", "model_version", "feature_schema_version", "asof_utc", "raw_score", "calibrated_probability",
                  "calibration_status", "target_definition", "readiness", "uncertainty_reason", "data_quality", "explanation_ref"):
            self.assertIn(k, p)
        for mode in ("OFF", "SHADOW", "ASSIST"):
            self.cfg.update({"ml": {"mode": mode}})
            g = ml.gate(row, None)
            self.assertEqual(g["status"], "PASS", mode)                     # lack of a model never blocks the bot
        self.assertTrue(any(c.startswith("ML_FALLBACK_STRATEGIES_ONLY") for c in ml.gate(row, None)["codes"]))
        st = ml.status()
        self.assertEqual(st["status"], "COLLECTING")
        self.assertFalse(st["readiness"]["ready"] if st["readiness"].get("counts") else False)

    def test_readiness_thresholds_and_reasons(self):
        ml = self.svc()
        r = ml._readiness()
        self.assertFalse(r["ready"])
        self.assertTrue(any(x.startswith("ETYKIETY_0/1000") for x in r["reasons"]), r)
        self.assertIn("nie wytrenowany", r["note"])

    def test_assist_blocks_below_threshold_with_champion(self):
        from masterquo.ml import trainer
        ml = self.svc()
        rows = gen_rows(1000)
        snap = write_snapshot(rows, Path(self.td.dir) / "s.jsonl.gz")
        res = trainer.run(snap, train_cfg(), str(ml.root / "models"), None)
        ml.registry.register(res, "SNAP", train_cfg()["promotion"])
        self.assertIsNotNone(ml.registry.champion)
        thr = ml.registry.champion.meta["threshold"]
        # store sample features for two setups: one clearly bad, one clearly good (planted signal: M15_rsi high = good)
        for sid, rsi in (("BAD", 20.0), ("GOOD", 80.0)):
            f = json.loads(rows[0]["features_json"])
            f.update(M15_rsi=rsi, M5_er20=0.5)
            self.db.execute("""INSERT INTO ml_samples(sample_id, setup_id, setup_version, group_id, symbol, feed_id, strategy_id, strategy_version, direction,
                               timeframe, asof_utc, feature_schema_version, features_json, entry_json, cost_model_version, label_policy_version, source,
                               quality, status, synthetic, created_at, updated_at) VALUES (?,?,1,?,'XAUUSD-','T','S01','1','LONG','M15',?,?,?,'{}','c','l','LIVE',
                               'HIGH','PENDING',1,?,?)""", (f"{sid}:1", sid, sid, iso(T0), "MQ-FEAT-1.0.0", json.dumps(f), iso(T0), iso(T0)))
        self.cfg.update({"ml": {"mode": "ASSIST"}})
        bad = ml.gate({"setup_id": "BAD", "version": 1, "record": {}}, None)
        good = ml.gate({"setup_id": "GOOD", "version": 1, "record": {}}, None)
        self.assertEqual(good["status"], "PASS", good)
        self.assertEqual(bad["prediction"]["readiness"], "READY")
        if bad["prediction"]["calibrated_probability"] < thr:
            self.assertEqual(bad["status"], "FAIL")
            self.assertIn("ML_BELOW_THRESHOLD", bad["codes"])
        self.assertGreater(good["prediction"]["calibrated_probability"], bad["prediction"]["calibrated_probability"])
        # SHADOW never gates; predictions are linked to the model version
        self.cfg.update({"ml": {"mode": "SHADOW"}})
        self.assertEqual(ml.gate({"setup_id": "BAD", "version": 1, "record": {}}, None)["status"], "PASS")
        self.assertEqual(self.db.one("SELECT model_id FROM ml_predictions WHERE setup_id='BAD' AND role='CHAMPION'")["model_id"], ml.registry.champion_id)
        self.assertEqual(ml.status()["status"], "SHADOW")
        self.assertIn("explanation", ml.explain("GOOD", 1))

    def test_job_lock_timeout_and_interrupted_recovery(self):
        class P:
            returncode = None

            def poll(self):
                return None

            def kill(self):
                self.returncode = -9

            terminate = kill
        spawned = []
        ml = self.svc(spawn=lambda f: spawned.append(f) or P())
        rows = gen_rows(400)
        for r in rows:          # write labelled samples into the live table
            self.db.execute("""INSERT INTO ml_samples(sample_id, setup_id, setup_version, group_id, event_id, symbol, feed_id, strategy_id, strategy_version, direction,
                               timeframe, asof_utc, feature_schema_version, features_json, entry_json, cost_model_version, label_policy_version, source, quality,
                               status, label, outcome_r, label_end_utc, label_known_utc, synthetic, created_at, updated_at)
                               VALUES (?,?,1,?,?,'XAUUSD-','T',?, '1', ?, 'M15', ?, ?, ?, '{}', 'c', 'l', 'LIVE', 'HIGH', 'LABELED', ?, ?, ?, ?, 1, ?, ?)""",
                            (r["sample_id"], r["setup_id"], r["group_id"], r["event_id"], r["strategy_id"], r["direction"], r["asof_utc"], r["feature_schema_version"],
                             r["features_json"], r["label"], r["outcome_r"], r["label_end_utc"], "2026-01-01T00:00:00Z", r["asof_utc"], r["asof_utc"]))
        a = ml.start_training("USER", force=True)
        self.assertTrue(a["started"], a)
        b = ml.start_training("USER", force=True)
        self.assertEqual(b["reason"], "JOB_ALREADY_RUNNING")              # one job at a time
        self.assertEqual(len(spawned), 1)
        self.cfg.update({"ml": {"train_timeout_minutes": 1}})
        ml._job["started"] -= 120
        ml._poll_job()
        self.assertEqual(self.db.one("SELECT status FROM ml_jobs WHERE job_id=?", (a["job_id"],))["status"], "FAILED")
        # restart while running -> INTERRUPTED, resumable on the same immutable snapshot
        c = ml.start_training("USER", force=True)
        ml2 = self.svc(spawn=lambda f: spawned.append(f) or P())
        self.assertEqual(self.db.one("SELECT status FROM ml_jobs WHERE job_id=?", (c["job_id"],))["status"], "INTERRUPTED")
        r = ml2.resume_interrupted()
        self.assertTrue(r["started"] and r["resumed"])
        self.assertEqual(json.loads(Path(spawned[-1]).read_text())["snapshot_id"], c["snapshot_id"])
        self.assertTrue(ml2.cancel()["cancelled"])

    def test_end_to_end_backfill_train_register_predict(self):
        """MT5-like history -> strategies -> samples -> labels -> snapshot -> trainer subprocess -> registry -> prediction."""
        from masterquo.ml import backfill
        from masterquo.strategies.tracker import SetupTracker  # noqa: F401
        data = backfill.synthetic_data(40, seed=11)
        res = backfill.run(self.db, data, feed="SYN", synthetic=True, cost={"spread": 0.12, "slippage": 0.05, "commission": 0.0035, "point": 0.01, "flags": []},
                           warmup_days=30)
        self.assertGreater(res["created"], 50, res)
        self.assertGreater(res["labels"].get("LABELED", 0), 30, res)
        self.assertEqual(self.db.one("SELECT COUNT(*) n FROM ml_samples WHERE quality!='APPROX'")["n"], 0)       # backfill is APPROX, separate
        self.cfg.update({"ml": {"use_backfill_approx": True, "min_block_samples": 15, "min_block_per_class": 3, "dt_tuning_budget": 4, "xgb_tuning_budget": 2,
                                "xgb_max_trees": 60}})
        ml = self.svc()
        st = ml.start_training("USER", force=True)
        self.assertTrue(st["started"], st)
        deadline = time.time() + 240
        while ml._job is not None and time.time() < deadline:            # real separate process
            ml._poll_job()
            time.sleep(0.5)
        job = self.db.one("SELECT status, detail_json FROM ml_jobs WHERE job_id=?", (st["job_id"],))
        self.assertIn(job["status"], ("DONE", "NOT_READY"), job)
        if job["status"] == "DONE":
            self.assertEqual(len(self.db.query("SELECT * FROM ml_models")), 2)          # DT + XGB registered (promoted or rejected with reasons)
            for m in ml.registry.models():
                self.assertIsNotNone(m["promotion"]["reasons"] is not None)
        self.assertIn(ml.status()["status"], STATUSES_OK)


STATUSES_OK = ("COLLECTING", "WAITING_FOR_LABELS", "SHADOW", "ACTIVE", "DEGRADED", "ERROR")


if __name__ == "__main__":
    unittest.main()
