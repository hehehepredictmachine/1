"""1.46 audit, group D_mq_lab_3: lab/si_service.py, spike_brain.py, structure_cli.py, structure_task.py, tick_store.py, ticks.py,
traceability.py.

Module-level tests only (no demo server, no socket). All market data is SYNTHETIC; a passing test proves a code path, not an edge."""
from __future__ import annotations

import ast
import io
import json
import re
import threading
import time
import tracemalloc
import types
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import ROOT, TempData

INST = "XAUUSD"


# ----------------------------------------------------------------------------------------------- helpers
def m1_bars(n=400, seed=3):
    rng = np.random.default_rng(seed)
    t0 = datetime(2026, 3, 2, tzinfo=UTC)
    out, c = [], 2000.0
    for i in range(n):
        o = c
        c = o + rng.normal(0, 0.4)
        out.append({"open_utc": (t0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": max(o, c) + abs(rng.normal(0, 0.2)),
                    "l": min(o, c) - abs(rng.normal(0, 0.2)), "c": c, "tv": 50.0, "spread": 12.0})
    return out


def write_export(d: Path, m1: list[dict], kind="SYNTHETIC_TEST") -> Path:
    import csv
    d.mkdir(parents=True)

    def agg(mins):
        res = []
        for i in range(0, len(m1) - mins + 1, mins):
            g = m1[i:i + mins]
            res.append({"open_utc": g[0]["open_utc"], "o": g[0]["o"], "h": max(b["h"] for b in g), "l": min(b["l"] for b in g), "c": g[-1]["c"],
                        "tv": 1.0, "spread": 12.0})
        return res
    for tf, bs in (("M1", m1), ("M5", agg(5)), ("M15", agg(15)), ("H1", agg(60))):
        with open(d / f"XAUUSD_{tf}.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time_open_utc", "open", "high", "low", "close", "tick_volume", "spread_points"])
            for b in bs:
                w.writerow([b["open_utc"], b["o"], b["h"], b["l"], b["c"], b["tv"], b["spread"]])
    (d / "source_metadata.json").write_text(json.dumps({"instrument": "XAUUSD", "file_prefix": "XAUUSD", "tick_size": 0.01, "spec": {"point": 0.01},
                                                        "data_kind": kind, "dataset_id": "fx", "symbol": "XAUUSD-"}))
    return d


def logreg_candidate(d: Path, n_feat: int | None = None, role="RESEARCH", prof_hash: str | None = None) -> str:
    """A real (small) LOGREG candidate of STRUCTURE_MOVE_M1_V1 saved with save_candidate."""
    from masterquo.lab import structure_task as T
    n_feat = n_feat or len(T.TAB)
    rng = np.random.default_rng(0)
    X, Y, R = rng.normal(size=(120, n_feat)), rng.integers(0, 3, size=(120, 3)), rng.normal(size=(120, 3))
    m = T.Tabular("LOGREG", 3).fit(X, Y, R, np.arange(120))
    temps = [{"T": 1.0, "status": "CALIBRATION_UNVERIFIED", "n": 0}] * 3
    rep = {"task_id": T.TASK_MOVE, "class_order": ["DOWN", "FLAT", "UP"], "horizons": [3, 5, 15], "role": role}
    man = {"instrument": INST, "symbol": "XAUUSD-", "indicator_profile": {"hash": prof_hash or T.indicator_profile(INST)["hash"]}, "dataset_id": "SID-x"}
    return T.save_candidate(d, "LOGREG", m, temps, rep, man)


def register_run(rid: str, rd: Path, **extra) -> None:
    from masterquo.lab import structure_task as T
    reg = T._reg(INST)
    reg["runs"][rid] = dict({"run_dir": str(rd), "task": T.TASK_MOVE, "status": "EVALUATED_DEV", "role": "RESEARCH", "created_at": "2026-01-01T00:00:00Z"},
                            **extra)
    T._save_reg(INST, reg)


def set_shadow(d: Path, cid: str = "R-LOGREG") -> None:
    from masterquo.lab import structure_task as T
    reg = T._reg(INST)
    reg["shadow"][T.TASK_MOVE] = {"candidate_id": cid, "dir": str(d), "model_hash": "x", "at": "2026-01-01T00:00:00Z"}
    T._save_reg(INST, reg)


class _DB:
    def __init__(self):
        self.rows = []

    def execute(self, sql, params=()):
        self.rows.append((sql, params))

    def query(self, sql, params=()):
        return []

    def one(self, sql, params=()):
        return None


class _Bus:
    def publish(self, *a, **k):
        pass


class _Cfg:
    def __init__(self, active="XAUUSD", symbol="XAUUSD-"):
        self.v = types.SimpleNamespace(mt5=types.SimpleNamespace(symbol=symbol), assets=types.SimpleNamespace(active=active, symbols={}))

    def get(self):
        return self.v


class _Bridge:
    state = "CONNECTED"

    def __init__(self, symbol_info=None):
        self.symbol_info = symbol_info
        self.calls = 0

    def ticks_range(self, symbol, t0, t1, max_count):
        self.calls += 1
        return {"status": "ok", "ticks": []}


def si_service(bridge=None, cfg=None):
    from masterquo.lab.si_service import StructureIntelligenceService
    return StructureIntelligenceService(cfg or _Cfg(), bridge or _Bridge(), _DB(), _Bus(), None)


def wait_job(si, jid, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = si.job(jid)
        if j and j["status"] != "RUNNING":
            return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()


# =============================================================================================== si_service.py
class TestForecasterProfileCache(_Base):
    def test_cached_forecaster_follows_indicator_profile(self):
        """chunk_15#2: the cached Forecaster kept forecasting OK after a new indicator profile (features of the NEW profile fed to a model
        trained on the old one) - a fresh load rejects the artefact."""
        from masterquo.lab import structure_task as T
        d = T.root(INST) / "runs" / "R" / "models" / "LOGREG"
        logreg_candidate(d)
        set_shadow(d)
        si = si_service()
        bars = {"M1": m1_bars(400)}
        self.assertEqual(si.forecast(bars, INST, 0.01, None)["forecast_status"], "OK")
        (T.root(INST) / "indicator_profile.json").write_text(json.dumps({"version": "X", "structure": {"internal": [2, 2], "major": [5, 5]},
                                                                         "mitp_profile": "STRICT_ALL", "hash": "different"}))
        out = si.forecast(bars, INST, 0.01, None)
        self.assertEqual(out["forecast_status"], "ABSTAIN")
        self.assertIn("indicator_profile", out["reason"].lower())

    def test_forecaster_refuses_stale_profile(self):
        """chunk_15#2: Forecaster.forecast itself compares the live profile hash with the artefact's."""
        from masterquo.lab import structure_task as T
        d = T.root(INST) / "runs" / "R" / "models" / "LOGREG"
        logreg_candidate(d)
        set_shadow(d)
        f = T.Forecaster(INST)
        self.assertIsNotNone(f.model)
        (T.root(INST) / "indicator_profile.json").write_text(json.dumps({"version": "X", "structure": {"internal": [2, 2], "major": [5, 5]},
                                                                         "mitp_profile": "STRICT_ALL", "hash": "different"}))
        out = f.forecast(m1_bars(400), {}, 0.01)
        self.assertEqual(out["forecast_status"], "ABSTAIN")
        self.assertIn("STALE_INDICATOR_PROFILE", out["reason"])


class TestJobAssetValidation(_Base):
    def test_job_asset_outside_allow_list_refused(self):
        """chunk_15#4: body['asset'] went unchecked into data paths (tick_export wrote index.json / ticks_*.npz outside the data dir)."""
        si = si_service()
        for bad in ("../../X", "/tmp/x", "EURUSD", ["XAUUSD"]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                si.start_job("tick_export", {"asset": bad, "days": 1})
        self.assertEqual(si.jobs, {})

    def test_roots_refuse_path_like_instrument(self):
        """chunk_15#4 (defence in depth): root() never builds a directory from a path-like instrument."""
        from masterquo.lab import structure_task as T
        from masterquo.lab import tick_store as TS
        for bad in ("..", "../x", "a/b", "a\\b", ""):
            with self.assertRaises(ValueError, msg=bad):
                TS.root(bad)
            with self.assertRaises(ValueError, msg=bad):
                T.root(bad)
        self.assertTrue(T.root("XAUUSD").is_dir() and TS.root("BTC").is_dir())


class TestTickJobsActiveSymbol(_Base):
    def test_tick_export_for_inactive_asset_refused(self):
        """chunk_15#5: tick_export always pulls the ACTIVE broker symbol - saving it under another asset mixed archives."""
        import mq_instruments
        si = si_service(cfg=_Cfg(active="XAUUSD"))
        with self.assertRaises(ValueError) as cm:
            si.start_job("tick_export", {"asset": "BTC", "days": 1})
        self.assertIn("ASSET_NOT_ACTIVE", str(cm.exception))
        self.assertFalse((mq_instruments.data_dir() / "ticks" / "BTC" / "index.json").exists())

    def test_tick_replay_without_symbol_info_blocked(self):
        """chunk_15#5: replay used 0.01 / 0.01 when the bridge had no symbol_info (guessed tick size / point)."""
        si = si_service(bridge=_Bridge(symbol_info=None))
        j = wait_job(si, si.start_job("tick_replay", {})["job_id"])
        self.assertEqual(j["status"], "FAILED")
        self.assertIn("SYMBOL_INFO", j["error"])


class TestSnapshotForecastIsolated(_Base):
    def test_snapshot_survives_forecast_exception(self):
        """chunk_15#1: si_service.snapshot called self.forecast without isolation - one exception lost every TF cell."""
        si = si_service()
        with mock.patch.object(si, "forecast", side_effect=ValueError("operands could not be broadcast")):
            snap = si.snapshot({}, INST, 0.01, None)
        self.assertEqual(snap["forecast"]["forecast_status"], "ABSTAIN")
        self.assertIn("ValueError", snap["forecast"]["reason"])
        self.assertEqual(set(snap["cells"]), {"H1", "M30", "M15", "M5", "M1"})


class TestJobCancel(_Base):
    def test_non_cancellable_job_reports_truth(self):
        """chunk_15#7: cancel() of a job that ignores cancel answered ok and the job was marked CANCELLED although it completed (and
        e.g. calibrate wrote a new indicator profile)."""
        from masterquo.lab import structure_task as T
        ev = threading.Event()

        def calib(inst, log=None):
            ev.wait(10)
            return {"version": "CAL-X"}
        si = si_service()
        with mock.patch.object(T, "calibrate_indicators", side_effect=calib):
            jid = si.start_job("calibrate", {})["job_id"]
            self.assertFalse(si.cancel(jid))
            ev.set()
            j = wait_job(si, jid)
        self.assertEqual(j["status"], "COMPLETED")
        self.assertEqual(j["result"], {"version": "CAL-X"})

    def test_train_job_still_cancellable(self):
        """chunk_15#7: the kinds that honour cancel keep accepting it."""
        from masterquo.lab import structure_task as T
        ev = threading.Event()
        seen = {}

        def train(*a, cancel=None, **k):
            ev.wait(10)
            seen["cancelled"] = cancel()
            return {"status": "CANCELLED"}
        si = si_service()
        with mock.patch.object(T, "latest_dataset", return_value=Path("x")), mock.patch.object(T, "train", side_effect=train):
            jid = si.start_job("train", {})["job_id"]
            self.assertTrue(si.cancel(jid))
            ev.set()
            j = wait_job(si, jid)
        self.assertTrue(seen["cancelled"])
        self.assertEqual(j["status"], "CANCELLED")


class TestRuntimePoint(_Base):
    def test_forecast_features_use_point(self):
        """chunk_15#11: runtime features() got no point - spread_atr (MT5 spread in POINTS) was scaled by trade_tick_size, while the dataset
        builder uses spec.point."""
        from masterquo.lab import structure_task as T
        d = T.root(INST) / "runs" / "R" / "models" / "LOGREG"
        logreg_candidate(d)
        set_shadow(d)
        si = si_service(bridge=_Bridge(symbol_info={"point": 0.001, "trade_tick_size": 0.01}))
        with mock.patch.object(T, "features", wraps=T.features) as fe:
            out = si.forecast({"M1": m1_bars(400)}, INST, 0.01, None)
        self.assertEqual(out["forecast_status"], "OK")
        args, kw = fe.call_args
        self.assertEqual(kw.get("point", args[4] if len(args) > 4 else None), 0.001)


# =============================================================================================== structure_task.py
class TestSelectShadowCompat(_Base):
    def test_experiment_candidate_refused(self):
        """chunk_15#1: an experiment candidate (3 / 6 / 59 feature columns) could be selected as SHADOW; Forecaster then raised on every
        snapshot (broadcast error)."""
        from masterquo.lab import structure_task as T
        rid = "20260101T000000Z_aaaa_MQ_NEUTRAL_REACTION_V1"
        rd = T.root(INST) / "runs" / rid
        d = rd / "models" / "RAW_FILTER_LOGREG"
        logreg_candidate(d, n_feat=3)
        (d / "experiment.json").write_text(json.dumps({"experiment_id": "MQ_NEUTRAL_REACTION_V1", "variant": "RAW_FILTER"}))
        register_run(rid, rd, experiment="MQ_NEUTRAL_REACTION_V1")
        with self.assertRaises(ValueError):
            T.select_shadow(INST, f"{rid}-RAW_FILTER_LOGREG")
        self.assertNotIn(T.TASK_MOVE, T._reg(INST)["shadow"])

    def test_forecaster_abstains_on_incompatible_pointer(self):
        """chunk_15#1: a pointer already stored (older version) never makes forecast() raise."""
        from masterquo.lab import structure_task as T
        d = T.root(INST) / "runs" / "R_X" / "models" / "RAW_FILTER_LOGREG"
        logreg_candidate(d, n_feat=3)
        set_shadow(d, "R_X-RAW_FILTER_LOGREG")
        out = T.Forecaster(INST).forecast(m1_bars(400), {}, 0.01)
        self.assertEqual(out["forecast_status"], "ABSTAIN")

    def test_forecaster_abstains_on_quote_event_spike(self):
        """chunk_15#1: MQ_SPIKE_BRAIN with QUOTE_EVENT_V1 needs the tick archive of the CURRENT minutes - live it raised
        BLOCKED_NO_QUOTE_HISTORY out of forecast() (or ran on empty windows)."""
        from masterquo.lab import si_families as SF
        from masterquo.lab import spike_brain as SB
        from masterquo.lab import structure_task as T
        net = SB.SpikeBrain(8, {"encoder": "QUOTE_EVENT_V1", "d_model": 8, "heads": 1, "d_k": 4, "experts": 2, "expert_hidden": 8, "blocks": 1,
                                "window": 4}, seed=1)
        d = T.root(INST) / "runs" / "R_Q" / "models" / SF.SB_FAMILY
        rep = {"task_id": T.TASK_MOVE, "class_order": ["DOWN", "FLAT", "UP"], "horizons": [3, 5, 15], "role": "RESEARCH"}
        man = {"instrument": INST, "symbol": "XAUUSD-", "indicator_profile": {"hash": T.indicator_profile(INST)["hash"]}, "dataset_id": "SID-x"}
        T.save_candidate(d, SF.SB_FAMILY, ("SB", net, {}, "QUOTE_EVENT_V1"), [{"T": 1.0, "status": "X", "n": 0}] * 3, rep, man, {})
        set_shadow(d, f"R_Q-{SF.SB_FAMILY}")
        out = T.Forecaster(INST).forecast(m1_bars(400), {}, 0.01)
        self.assertEqual(out["forecast_status"], "ABSTAIN")
        self.assertIn("QUOTE_EVENT_V1", out["reason"])

    def test_candidate_id_traversal_refused(self):
        """chunk_15#17: candidate_id '<run>-../x' pointed the SHADOW pointer at any directory holding a candidate.json."""
        from masterquo.lab import structure_task as T
        rid = "20260101T000000Z_bbbb"
        rd = T.root(INST) / "runs" / rid
        logreg_candidate(rd / "models" / "LOGREG")
        logreg_candidate(rd / "outside")
        register_run(rid, rd)
        with self.assertRaises(ValueError):
            T.select_shadow(INST, f"{rid}-../outside")
        self.assertNotIn(T.TASK_MOVE, T._reg(INST)["shadow"])
        self.assertTrue(T.select_shadow(INST, f"{rid}-LOGREG")["ok"])


class TestRollbackTwice(_Base):
    def test_two_rollbacks_in_a_row(self):
        """chunk_15#3: the second rollback read a candidate_id string as a pointer dict -> TypeError (HTTP 500)."""
        from masterquo.lab import structure_task as T
        rid = "20260101T000000Z_cccc"
        rd = T.root(INST) / "runs" / rid
        logreg_candidate(rd / "models" / "LOGREG")
        logreg_candidate(rd / "models" / "XGB")
        register_run(rid, rd)
        T.select_shadow(INST, f"{rid}-LOGREG")
        T.select_shadow(INST, f"{rid}-XGB")
        self.assertEqual(T.rollback(INST, T.TASK_MOVE)["shadow"]["candidate_id"], f"{rid}-LOGREG")
        self.assertIsNone(T.rollback(INST, T.TASK_MOVE)["shadow"])
        with self.assertRaises(ValueError):
            T.rollback(INST, T.TASK_MOVE)
        T.select_shadow(INST, f"{rid}-XGB")                                    # history keeps working after the undo chain
        self.assertEqual(T._reg(INST)["shadow"][T.TASK_MOVE]["candidate_id"], f"{rid}-XGB")
        self.assertIsNone(T.rollback(INST, T.TASK_MOVE)["shadow"])

    def test_legacy_history_with_string_from(self):
        """chunk_15#3: registries written by 1.45 (rollback entry with 'from' as a string) still roll back."""
        from masterquo.lab import structure_task as T
        rid = "20260101T000000Z_dddd"
        rd = T.root(INST) / "runs" / rid
        logreg_candidate(rd / "models" / "LOGREG")
        register_run(rid, rd)
        a = {"candidate_id": f"{rid}-LOGREG", "dir": str(rd / "models" / "LOGREG"), "model_hash": "h", "at": "t"}
        reg = T._reg(INST)
        reg["shadow"][T.TASK_MOVE] = a
        reg["history"] = [{"task": T.TASK_MOVE, "from": None, "to": f"{rid}-LOGREG", "at": "t1"},
                          {"task": T.TASK_MOVE, "from": a, "to": f"{rid}-XGB", "at": "t2"},
                          {"task": T.TASK_MOVE, "from": f"{rid}-XGB", "to": f"{rid}-LOGREG", "at": "t3", "rollback": True}]
        T._save_reg(INST, reg)
        self.assertIsNone(T.rollback(INST, T.TASK_MOVE)["shadow"])


class TestTrainedFixture(_Base):
    """Small synthetic dataset (TEST_ONLY) shared by the protocol tests."""

    def setUp(self):
        super().setUp()
        import mq_instruments
        from masterquo.lab import structure_task as T
        ds = write_export(mq_instruments.data_dir() / "exp", self.bars())
        T.save_dataset(INST, T.build_move_dataset(INST, ds, log=lambda *a: None))
        T.PROFILES["fixture46"] = dict(T.PROFILES["quick"], epochs=1, net_cfg={"widths": [4, 8], "blocks_per_stage": 1, "cardinality": 2},
                                       max_fit_rows=300)

    def tearDown(self):
        from masterquo.lab import structure_task as T
        T.PROFILES.pop("fixture46", None)
        super().tearDown()

    @staticmethod
    def bars():
        return m1_bars(3000)

    def _train(self, families=("LOGREG",), cancel=None, db=None):
        from masterquo.lab import structure_task as T
        return T.train(INST, T.latest_dataset(INST, T.TASK_MOVE), T.TASK_MOVE, list(families), "fixture46", db=db, log=lambda *a: None, cancel=cancel)


class TestTrainCancel(TestTrainedFixture):
    def _run(self, after_fits: int):
        from masterquo.lab import structure_task as T
        real = T._fit_family
        calls = []

        def fit_family(*a, **k):
            calls.append(a[0])
            return real(*a, **k)
        with mock.patch.object(T, "_fit_family", side_effect=fit_family):
            rep = self._train(cancel=lambda: len(calls) >= after_fits)
        return rep, calls

    def test_cancel_between_families(self):
        """chunk_15#7: cancel was checked only at the start of a fold - the fold (all families x seeds) and the final candidates ran on."""
        rep, calls = self._run(1)
        self.assertEqual(rep["status"], "CANCELLED")
        self.assertEqual(calls, ["CLASS_FREQ"])
        self.assertEqual(rep["candidates"], {})

    def test_cancel_before_final_candidates(self):
        """chunk_15#7: the final-candidate loop never checked cancel."""
        rep, calls = self._run(3)                                              # CLASS_FREQ, RULE_STRUCTURE, LOGREG of the one fold
        self.assertEqual(rep["status"], "CANCELLED")
        self.assertEqual(len(calls), 3)
        self.assertEqual(rep["candidates"], {})

    def test_structurenet_fit_gets_cancel(self):
        """chunk_15#7: _fit_family passed cancel only to the spike family; SN.fit ran with cancel=None."""
        from masterquo.lab import structure_task as T
        data = T.load_dataset(T.latest_dataset(INST, T.TASK_MOVE), T.TASK_MOVE)
        sp = T.split(data)
        cancel = mock.Mock(return_value=False)
        with mock.patch.object(T.SN, "fit", return_value={"status": "CANCELLED"}) as fit:
            T._fit_family("MQ_SEW_RESNET1D_V2", data, T.TASK_MOVE, sp["folds"][-1]["blocks"], T.PROFILES["fixture46"], 11, None,
                          time.time() + 60, cancel)
        self.assertIs(fit.call_args.kwargs.get("cancel"), cancel)


class TestRegistryLostUpdate(TestTrainedFixture):
    def test_evaluate_holdout_keeps_concurrent_registry_changes(self):
        """chunk_15#14: evaluate_holdout read the registry, predicted for minutes, then wrote the OLD object back - a run registered
        (or a SHADOW pointer moved) meanwhile was lost."""
        from masterquo.db.database import Database
        from masterquo.lab import structure_task as T
        db = Database()
        db.migrate()
        rep = self._train(db=db)
        cid = rep["candidates"]["LOGREG"]["candidate_id"]
        real = T._predict

        def predict(*a, **k):
            reg = T._reg(INST)                                                 # another writer during the long prediction
            reg["runs"]["OTHER_RUN"] = {"run_dir": "x", "task": T.TASK_MOVE, "status": "EVALUATED_DEV", "role": "RESEARCH", "created_at": "t"}
            T._save_reg(INST, reg)
            return real(*a, **k)
        with mock.patch.object(T, "_predict", side_effect=predict):
            out = T.evaluate_holdout(INST, cid, T.PROTOCOL_ID, db)
        self.assertEqual(out["status"], "EVALUATED_ONCE")
        reg = T._reg(INST)
        self.assertIn("OTHER_RUN", reg["runs"])
        self.assertIn(cid, reg["holdout_access"])
        self.assertEqual(T.evaluate_holdout(INST, cid, T.PROTOCOL_ID, db)["status"], "ALREADY_EVALUATED")


class TestLabelsNaNAtr(unittest.TestCase):
    def test_nan_atr_is_missing_label(self):
        """chunk_15#16: `not a or a <= 0` let NaN through - a row without ATR became class FLAT."""
        from masterquo.lab import structure_task as T
        t = [1_772_000_000 + 60 * i for i in range(30)]
        c = [2000.0 + i for i in range(30)]
        Y, R = T.labels(t, c, [float("nan")] * 30)
        self.assertTrue((Y == -1).all())
        self.assertTrue(np.isnan(R).all())
        Y2, _ = T.labels(t, c, [1.0] * 30)
        self.assertTrue((Y2[:-15] >= 0).all())


# =============================================================================================== spike_brain.py
def _sb_setup():
    from masterquo.lab import spike_brain as SB

    def mk(seed, N=8, T=6):
        rng = np.random.default_rng(seed)
        return (rng.integers(0, 3, size=(N, T, 8)).astype(float), np.ones((N, T), bool), np.ones((N, T)), np.ones((N, T)),
                rng.integers(0, 3, size=(N, 3)), rng.normal(size=(N, 3)))
    cfg = {"d_model": 8, "heads": 1, "d_k": 4, "experts": 2, "expert_hidden": 8, "blocks": 1, "window": 4}
    return SB, SB.SpikeBrain(8, cfg, seed=3), mk(0), mk(1)


class TestSpikeBrainBest(unittest.TestCase):
    def test_cancelled_returns_best_weights(self):
        """chunk_15#9: the best (early-stopping) weights were restored only for TRAINED - CANCELLED / BUDGET_EXCEEDED / NAN_LOSS returned
        the last epoch."""
        SB, net, tr, va = _sb_setup()
        n = {"c": 0}

        def cancel():
            n["c"] += 1
            return n["c"] > 4
        info = SB.fit(net, lambda rng: [tr], va, epochs=10, lr=0.3, patience=100, cancel=cancel)
        self.assertEqual(info["status"], "CANCELLED")
        vals = [h["val_loss"] for h in info["history"]]
        self.assertLess(min(vals), vals[-1])                                   # precondition: the last epoch is not the best
        self.assertAlmostEqual(net.loss(*va)[1]["loss"], min(vals), places=6)

    def test_budget_exceeded_returns_best_weights(self):
        """chunk_15#9: BUDGET_EXCEEDED (trial_minutes / deadline) returned the last epoch."""
        SB, net, tr, va = _sb_setup()
        clock = {"t": 0.0}

        def mono():
            clock["t"] += 1.0
            return clock["t"]
        fake = types.SimpleNamespace(monotonic=mono, perf_counter=time.perf_counter)
        with mock.patch.object(SB, "time", fake):
            info = SB.fit(net, lambda rng: [tr], va, epochs=10, lr=0.3, patience=100, budget_s=4.5)
        self.assertEqual(info["status"], "BUDGET_EXCEEDED")
        vals = [h["val_loss"] for h in info["history"]]
        self.assertLess(min(vals), vals[-1])
        self.assertAlmostEqual(net.loss(*va)[1]["loss"], min(vals), places=6)

    def test_resume_keeps_best_weights(self):
        """chunk_15#10: the checkpoint stored `best` but not the best weights - a resumed fit could not restore them."""
        import tempfile
        SB, net1, tr, va = _sb_setup()
        SB.fit(net1, lambda rng: [tr], va, epochs=5, lr=0.3, patience=100)
        _, net2, _, _ = _sb_setup()
        with tempfile.TemporaryDirectory() as tmp:
            n = {"c": 0}

            def cancel():
                n["c"] += 1
                return n["c"] > 2
            self.assertEqual(SB.fit(net2, lambda rng: [tr], va, epochs=5, lr=0.3, patience=100, ckpt_dir=Path(tmp), cancel=cancel)["status"],
                             "CANCELLED")
            _, net3, _, _ = _sb_setup()
            info = SB.fit(net3, lambda rng: [tr], va, epochs=5, lr=0.3, patience=100, ckpt_dir=Path(tmp))
        self.assertEqual(info["status"], "TRAINED")
        for k in net1.p:
            np.testing.assert_allclose(net3.p[k].data, net1.p[k].data, err_msg=k)


# =============================================================================================== tick_store.py
def _ticks(t0_ms, n, step_ms=250, seed=0):
    rng = np.random.default_rng(seed)
    px = 2400 + np.cumsum(rng.normal(0, 0.02, n))
    return [{"t_ms": int(t0_ms + i * step_ms), "bid": round(float(px[i]), 2), "ask": round(float(px[i]) + 0.12, 2), "time_msc": int(t0_ms + i * step_ms),
             "flags": 6} for i in range(n)]


def _reference_load(inst):
    """The 1.45 semantics of tick_store.load (list of dicts sorted by (t_ms, ord), index order kept on ties)."""
    from masterquo.lab import tick_store as TS
    out = []
    for e in json.loads((TS.root(inst) / "index.json").read_text(encoding="utf-8")):
        with np.load(TS.root(inst) / e["file"], allow_pickle=False) as z:
            for i in range(len(z["t_ms"])):
                out.append({"t_ms": int(z["t_ms"][i]), "bid": float(z["bid"][i]), "ask": float(z["ask"][i]), "ord": int(z["ord"][i]),
                            "time_msc": int(z["time_msc"][i]), "flags": int(z["flags"][i])})
    out.sort(key=lambda k: (k["t_ms"], k["ord"]))
    return out


class TestTickExportDays(_Base):
    def test_days_validated(self):
        """chunk_15#6: days=inf looped for ever (t = -inf), NaN / negative gave complete=True with no data."""
        from masterquo.lab import tick_store as TS

        class Bridge(_Bridge):
            def ticks_range(self, *a):
                self.calls += 1
                if self.calls > 5:
                    raise RuntimeError("runaway export loop")
                return {"status": "ok", "ticks": []}
        for bad in (float("inf"), float("nan"), -1.0, 0.0, 10_000.0):
            br = Bridge()
            with self.assertRaises(ValueError, msg=bad):
                TS.export_via_bridge(br, "XAUUSD-", INST, bad)
            self.assertEqual(br.calls, 0)
        si = si_service(bridge=Bridge())                                      # a runaway job must stop on its own (no endless thread)
        for bad in ("inf", "Infinity", "nan", -3, "abc"):
            with self.assertRaises(ValueError, msg=bad):
                si.start_job("tick_export", {"days": bad})
        self.assertEqual(si.jobs, {})

    def test_cancelled_export_not_complete(self):
        """chunk_15#6: an export cancelled before its first chunk reported complete=True."""
        from masterquo.lab import tick_store as TS
        r = TS.export_via_bridge(_Bridge(), "XAUUSD-", INST, 1.0, cancel=lambda: True)
        self.assertFalse(r["complete"])


class TestTickArchiveStreaming(_Base):
    def test_iter_ticks_same_order_as_load(self):
        """chunk_15#15: streamed reading returns exactly the 1.45 order, also for overlapping chunks and equal timestamps."""
        from masterquo.lab import tick_store as TS
        base = 1_772_000_000_000
        TS.save_chunk(INST, _ticks(base, 400, seed=1), "MT5", "", False)
        TS.save_chunk(INST, _ticks(base + 50_000, 300, step_ms=500, seed=2), "MT5", "", False)        # overlaps the first chunk
        TS.save_chunk(INST, _ticks(base + 99_750, 50, seed=3), "MT5", "", False)                      # touches the first chunk's end
        TS.save_chunk(INST, _ticks(base + 10_000_000, 200, seed=4), "MT5", "", False)                 # separate
        ref = _reference_load(INST)
        self.assertEqual(list(TS.iter_ticks(INST)), ref)
        self.assertEqual(TS.load(INST), ref)

    def test_streaming_memory_bounded(self):
        """chunk_15#15: load() materialised the whole archive as dicts (~300 B/tick) in the bot process; the stream keeps one chunk."""
        from masterquo.lab import tick_store as TS
        base = 1_772_000_000_000
        for k in range(4):
            TS.save_chunk(INST, _ticks(base + k * 100_000_000, 30_000, seed=k), "MT5", "", False)
        tracemalloc.start()
        try:
            n = sum(1 for _ in TS.iter_ticks(INST))
            peak_iter = tracemalloc.get_traced_memory()[1]
            tracemalloc.reset_peak()
            full = TS.load(INST)
            peak_load = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(n, len(full))
        self.assertLess(peak_iter, peak_load / 4)

    def test_replay_streams(self):
        """chunk_15#15: replay() no longer builds the full list."""
        from masterquo.lab import tick_store as TS
        TS.save_chunk(INST, _ticks(1_772_000_000_000, 2000, step_ms=200), "MT5", "", False)
        with mock.patch.object(TS, "load", side_effect=AssertionError("full archive materialised")):
            r = TS.replay(INST, 0.01, 0.01)
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["ticks"], 2000)
        self.assertGreater(r["rows"], 0)


class TestTickIndexAtomic(_Base):
    def test_interrupted_index_write_keeps_old_index(self):
        """focus_X3#7: index.json was rewritten in place - an interrupted write left a truncated index and the archive unreadable."""
        from masterquo.lab import tick_store as TS
        TS.save_chunk(INST, _ticks(1_772_000_000_000, 50), "MT5", "", False)
        orig = Path.write_text

        def bad(self, data, *a, **k):
            if self.name.startswith("index.json"):
                orig(self, data[:15], *a, **k)
                raise OSError("disk full")
            return orig(self, data, *a, **k)
        with mock.patch.object(Path, "write_text", bad), self.assertRaises(OSError):
            TS.save_chunk(INST, _ticks(1_772_100_000_000, 50), "MT5", "", False)
        idx = json.loads((TS.root(INST) / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(idx), 1)

    def test_corrupt_index_rebuilt_from_chunks(self):
        """focus_X3#7: a corrupt index.json made every read and every later export raise although the chunks were intact."""
        from masterquo.lab import tick_store as TS
        TS.save_chunk(INST, _ticks(1_772_000_000_000, 50), "MT5", "", False)
        TS.save_chunk(INST, _ticks(1_772_100_000_000, 30), "MT5", "", False)
        p = TS.root(INST) / "index.json"
        p.write_text('[{"file": "ticks_', encoding="utf-8")
        self.assertEqual(len(TS.load(INST)), 80)
        self.assertTrue(list(TS.root(INST).glob("index.json.corrupt-*")))          # the damaged file is kept, never deleted
        TS.save_chunk(INST, _ticks(1_772_200_000_000, 20), "MT5", "", False)
        self.assertEqual(len(TS.load(INST)), 100)


# =============================================================================================== ticks.py
class TestTickKinematics(unittest.TestCase):
    def test_verify_skips_forecasts_before_window(self):
        """chunk_15#12: a forecast whose target precedes the tick window was scored against the window's FIRST tick (hours later)."""
        from masterquo.lab.ticks import verify_forecasts
        ticks = [{"t": 10_800.0 + i, "bid": 149.95, "ask": 150.05} for i in range(100)]
        self.assertEqual(verify_forecasts([{"issued_at_t": 0.0, "horizon_s": 10.0, "mid": 100.0, "se": 1.0}], ticks)["verified"], 0)

    def test_coverage_only_over_forecasts_with_se(self):
        """chunk_15#12: forecasts without se counted as 'outside' in coverage_2se."""
        from masterquo.lab.ticks import verify_forecasts
        ticks = [{"t": 100.0 + i, "bid": 99.95, "ask": 100.05} for i in range(100)]
        v = verify_forecasts([{"issued_at_t": 100.0, "horizon_s": 10.0, "mid": 100.0, "se": 1.0},
                              {"issued_at_t": 100.0, "horizon_s": 10.0, "mid": 100.0, "se": None}], ticks)
        self.assertEqual(v["verified"], 2)
        self.assertEqual(v["coverage_2se"], 1.0)
        v2 = verify_forecasts([{"issued_at_t": 100.0, "horizon_s": 10.0, "mid": 100.0, "se": None}], ticks)
        self.assertIsNone(v2["coverage_2se"])

    def test_rank_deficient_fit_not_ready(self):
        """chunk_15#13: >= 8 ticks on 1-2 distinct timestamps gave status 'ready' with NaN standard errors (JSON 500)."""
        from masterquo.lab.ticks import kinematics
        tk = [{"t": 1000.0 + (0.0 if i < 5 else 1.0), "bid": 2400 + 0.01 * i, "ask": 2400.1 + 0.01 * i} for i in range(10)]
        k = kinematics(tk)
        self.assertEqual(k["status"], "missing_data")
        self.assertEqual(k["reason"], "RANK_DEFICIENT")
        json.dumps(k, allow_nan=False)
        good = [{"t": 1000.0 + i * 0.5, "bid": 2400 + 0.005 * i, "ask": 2400.1 + 0.005 * i} for i in range(60)]
        k2 = kinematics(good)
        self.assertEqual(k2["status"], "ready")
        json.dumps(k2, allow_nan=False)


# =============================================================================================== structure_cli.py
class TestCliImport(_Base):
    def test_import_does_not_claim_registration(self):
        """chunk_15#18: 'export --source import' printed {imported_source ...} although nothing was copied or registered."""
        from masterquo.lab import structure_cli
        d = Path(self.td.dir) / "exp"
        d.mkdir()
        (d / "source_metadata.json").write_text(json.dumps({"instrument": "XAUUSD", "data_kind": "REAL_USER_DATA"}))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = structure_cli.main(["export", "--asset", "XAUUSD", "--source", "import", "--path", str(d)])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertIs(out["registered"], False)
        self.assertIn("--dataset", out["note"])


# =============================================================================================== traceability.py
class TestTraceability(unittest.TestCase):
    @staticmethod
    def _classes(path: Path) -> dict:
        t = ast.parse(path.read_text(encoding="utf-8"))
        return {n.name: {m.name for m in n.body if isinstance(m, ast.FunctionDef)} for n in t.body if isinstance(n, ast.ClassDef)}

    def test_evidence_points_to_existing_tests(self):
        """chunk_16#11: evidence named test classes / methods that do not exist (TestArtifacts, TestMiniRocket, TestExecutionLock, ...)."""
        from masterquo.lab import traceability as TR
        missing = []
        for r in TR.ROWS:
            for part in [p.strip() for p in r["evidence"].split(";")]:
                m = re.match(r"(tests/[\w/]+\.py)(?:::(.+))?$", part)
                if not m:
                    for f in [x.strip() for x in part.split(",")]:
                        if f.startswith("tests/") and not (ROOT / f).exists():
                            missing.append((r["id"], f))
                    continue
                path = ROOT / m.group(1)
                if not path.exists():
                    missing.append((r["id"], m.group(1)))
                    continue
                cl = self._classes(path)
                for item in [x.strip() for x in (m.group(2) or "").split(",") if x.strip()]:
                    c, _, meth = item.partition(".")
                    if c not in cl or (meth and meth not in cl[c]):
                        missing.append((r["id"], item))
        self.assertEqual(missing, [])

    def test_status_values_documented(self):
        """chunk_16#12: M32 had implementation_status 'implemented' outside the documented set."""
        from masterquo.lab import traceability as TR
        self.assertEqual({r["implementation_status"] for r in TR.ROWS} - {"verified", "implemented_unverified", "blocked"}, set())
        self.assertNotIn("implemented", TR.summary()["implementation_status"])


if __name__ == "__main__":
    unittest.main()
