"""1.46 arch, fala 2 – grupa gold_deep_mm: prognozy złota / scalp (gold_candles_runtime), rodzina RL_PPO (deep_runtime), PMW-MM (Event GRU,
ledger GPR), czytniki ledgera ewaluacji. Każdy test nie przechodzi na kodzie sprzed poprawki (klucze pozycji w nazwach klas).

* I0489: `mm export-fixtures --parity` – kod wyjścia 3 dla NATIVE_NOT_EXECUTED (dziś 0, jak sukces).
* I0632: worker prognoz mapuje MODEL_FROM_FUTURE_RELATIVE_TO_SNAPSHOT -> MODEL_FROM_FUTURE (stan INCOMPATIBLE, nie ERROR).
* I0754: scalp_forecast z as_of bota – zamrożony feed M1 = STALE_DATA (tylko zaostrzenie: rekord SHADOW nie jest READY).
* I0619: pickle HGB / kwantyli z inną wersją scikit-learn – czytelny SKLEARN_VERSION_MISMATCH i ostrzeżenie środowiska.
* I0623: --small-test: podział 60/20/20 bez pustego okresu kalibracji (dane rzeczywiste: plan bez zmian).
* I0066: jedna reguła auto-aktywacji (common.auto_admissible) w plan_train i scalp_train (ręczna aktywacja – D20, fala 1).
* I0466: RL_PPO zapisuje deterministyczną próbkę inferencji, aktywacja ją sprawdza (stare artefakty bez próbki – jak dziś).
* I0023: Event GRU w Quant ładuje artefakt z kontrolą feature_schema (jedna stała EV.FEATURE_SCHEMA).
* I0034: wiersze walk-forward GPR w ledgerze MM mają run_mode WALK_FORWARD[_SYNTHETIC]; summary rozdziela je od LIVE.
* I0039: status ewaluacji liczy PENDING w SQL (bez SELECT * całej historii), raport nie dekoduje całych payloadów (wynik identyczny).
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import pickle
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

import _env
import numpy as np
from _env import TempData

sys.path.insert(0, str(_env.ROOT / "tests" / "scalp"))
INST = "XAUUSD"


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Data(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        self.prev_inst = os.environ.get("MQ_INSTRUMENT")
        os.environ.pop("MQ_INSTRUMENT", None)

        def _restore():
            if self.prev_inst is None:
                os.environ.pop("MQ_INSTRUMENT", None)
            else:
                os.environ["MQ_INSTRUMENT"] = self.prev_inst
        self.addCleanup(_restore)


# ================================================================================================ I0489
class TestMMExportFixturesRcI0489(unittest.TestCase):
    def test_not_executed_is_not_success(self):
        from masterquo.mm import cli
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli.main(["export-fixtures", "--out", td, "--parity", str(Path(td) / "missing.txt")])
        self.assertEqual(json.loads(out.getvalue())["status"], "NATIVE_NOT_EXECUTED")
        self.assertEqual(rc, 3)                                  # was 0 - a script read "native parity not run" as success

    def test_codes_are_distinct(self):
        from masterquo.mm import cli
        for status, rc in (("NATIVE_PARITY_PASS", 0), ("NATIVE_NOT_EXECUTED", 3), ("NATIVE_PARITY_FAIL", 1), ("NATIVE_OUTPUT_INVALID", 1)):
            with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()), \
                    mock.patch("masterquo.mm.fixtures.parity", return_value={"status": status}):
                (Path(td) / "mm_ref_kalman.csv").write_text("x", encoding="utf-8")
                self.assertEqual(cli.main(["export-fixtures", "--out", td, "--parity", str(Path(td) / "n.txt")]), rc, status)


# ================================================================================================ I0632
class TestWorkerStatusMappingI0632(unittest.TestCase):
    def _analyze(self, fc_status: str, mstatus: str = "OK") -> dict:
        from gold_candles import analysis
        from gold_candles_runtime import worker as W
        with mock.patch.object(W, "make_config", return_value=object()), mock.patch.object(W, "bars_frame", return_value=None), \
                mock.patch.object(W, "_active_model", return_value=(object(), {"run_id": "R"}, mstatus, None if mstatus == "OK" else "x")), \
                mock.patch.object(analysis, "analyze", return_value={"forecast": {"status": fc_status}}):
            return W.analyze_request({"tick_size": 0.01, "as_of": "2026-03-02T10:00:00Z", "m5": []})

    def test_model_from_future_relative_to_snapshot(self):
        from masterquo.forecast.service import STATUS_PL
        from masterquo.modelhub.adapters import FORECAST_STATE
        out = self._analyze("MODEL_FROM_FUTURE_RELATIVE_TO_SNAPSHOT")
        self.assertEqual(out["status"], "MODEL_FROM_FUTURE")           # was the raw status -> FORECAST_STATE default ERROR
        self.assertEqual(FORECAST_STATE[out["status"]], "INCOMPATIBLE")
        self.assertIn(out["status"], STATUS_PL)

    def test_no_trained_model_and_existing_mappings(self):
        from gold_candles_runtime import worker as W
        self.assertEqual(W._map_status("NO_TRAINED_MODEL", "OK"), "NO_MODEL")
        self.assertEqual(W._map_status("FEATURE_WARMUP_OR_STALE_M30", "OK"), "WARMUP")
        self.assertEqual(W._map_status("STALE_M5_DATA", "OK"), "STALE_DATA")
        self.assertEqual(W._map_status("SHADOW_RESEARCH_FORECAST", "OK"), "SHADOW")
        self.assertEqual(W._map_status("SHADOW_RESEARCH_FORECAST", "CONTRACT_MISMATCH"), "CONTRACT_MISMATCH")   # model status first
        self.assertEqual(W._map_status("SOMETHING_NEW", "OK"), "SOMETHING_NEW")                               # unknown: unchanged


# ================================================================================================ I0754
def _m1(n: int, last_open: float) -> list[dict]:
    out = []
    for i in range(n):
        c = 2000.0 + math.sin(i / 5.0) + 0.01 * i
        out.append({"open_utc": iso(last_open - 60 * (n - 1 - i)), "o": c - 0.1, "h": c + 0.6, "l": c - 0.6, "c": c, "tv": 100 + i % 7,
                    "spread_price": 0.12})
    return out


class _StubScalp:
    def __init__(self, entry):
        self.entry = entry

    def predict(self, X):
        return {"1": {"P": np.array([[0.2, 0.3, 0.5]]), "Q": None}}


class TestScalpForecastStaleI0754(unittest.TestCase):
    ENTRY: ClassVar[dict] = {"symbol": "XAUUSD-", "tick_size": 0.01, "horizon_status": {"1": "SHADOW_VALIDATED"}, "models": {"1": {"selected": "LR"}}}

    def _ask(self, req: dict) -> dict:
        from gold_candles_runtime import scalp_infer as SI
        from gold_candles_runtime import worker as W
        W._scalp_cache.update(run_id=None, model=None)
        self.addCleanup(W._scalp_cache.update, run_id=None, model=None)
        with mock.patch.object(SI, "read_registry", return_value={"active": "R1", "runs": {"R1": self.ENTRY}}), \
                mock.patch.object(SI, "activatable", return_value=(True, None)), mock.patch.object(SI, "ScalpModel", _StubScalp):
            return W.scalp_forecast(req)

    def test_frozen_feed_is_stale(self):
        now = time.time()
        ans = self._ask({"m1": _m1(150, now - 600), "as_of": iso(now)})
        self.assertEqual(ans["status"], "STALE_DATA")                  # was SHADOW (a 10-minute-old M1 published as the current forecast)
        self.assertFalse(ans["execution_permission"])

    def test_fresh_feed_and_bar_close(self):
        now = time.time()
        last_open = (now // 60) * 60 - 60                                # newest CLOSED M1
        ans = self._ask({"m1": _m1(150, last_open), "as_of": now})
        self.assertEqual(ans["status"], "SHADOW", ans)
        self.assertEqual(ans["feature_time_utc"], iso(last_open))       # BAR_OPEN semantics unchanged
        self.assertEqual(ans["bar_close_utc"], iso(last_open + 60))

    def test_request_without_as_of_unchanged(self):
        ans = self._ask({"m1": _m1(150, time.time() - 6000)})
        self.assertEqual(ans["status"], "SHADOW")                       # old caller: no freshness claim, as before

    def test_service_sends_as_of(self):
        from masterquo.scalp.service import ScalpService
        seen = {}

        def ask(req, timeout):
            seen.update(req)
            return {"status": "SHADOW"}
        fake = SimpleNamespace(registry=lambda: {"active": "R1"}, _worker_down=lambda: None, forecast=SimpleNamespace(proc=object(), _ask=ask),
                               bridge=SimpleNamespace(bars=lambda tf, n, include_forming=False: _m1(3, time.time() - 120), symbol_info={"point": 0.01}))
        ScalpService.forecasts(fake)
        self.assertIn("as_of", seen)
        self.assertLess(abs(datetime.fromisoformat(seen["as_of"]).timestamp() - time.time()), 5)

    def test_quant_record_available_at_bar_close(self):
        from masterquo.quant import adapters as QA
        t_open = 1_794_000_000
        ans = {"status": "SHADOW", "run_id": "R1", "feature_time_utc": iso(t_open), "bar_close_utc": iso(t_open + 60),
               "horizons": {"1": {"p_down": 0.2, "p_flat": 0.3, "p_up": 0.5}}}
        rt = SimpleNamespace(scalp=SimpleNamespace(registry=lambda: {"active": "R1", "runs": {"R1": {}}}, forecasts=lambda: ans))
        rec = QA.scalp_a(rt, INST)[0]
        self.assertEqual(rec["state"], "READY")
        self.assertEqual(rec["data_time"], iso(t_open))
        self.assertEqual(rec["available_at"], iso(t_open + 60))        # was None: "available" at the bar open (before the bar closed)


# ================================================================================================ I0619
class _Bomb:
    """Unpickling raises AttributeError - what an incompatible scikit-learn pickle does after a reinstall."""

    def __reduce__(self):
        return getattr, (0, "attribute_removed_in_new_sklearn")


class TestScalpSklearnVersionGuardI0619(_Data):
    def _entry(self, sk_version: str, payload) -> dict:
        from gold_candles_runtime.common import sha256_file
        rd = Path(self.td.dir) / "scalp" / "runs" / "R1"
        rd.mkdir(parents=True)
        (rd / "q.pkl").write_bytes(pickle.dumps(payload))
        return {"run_dir": str(rd), "artifacts": {"q.pkl": sha256_file(rd / "q.pkl")}, "versions": {"scikit_learn": sk_version},
                "models": {"1": {"selected": "PRIOR", "prior": [0.3, 0.4, 0.3], "quantiles_file": "q.pkl"}}}

    def test_mismatch_gives_readable_reason(self):
        from gold_candles_runtime.scalp_infer import ScalpModel
        with self.assertRaises(RuntimeError) as cm:                      # was a raw AttributeError (FORECAST_UNAVAILABLE without a cause)
            ScalpModel(self._entry("0.0", _Bomb()))
        self.assertIn("SKLEARN_VERSION_MISMATCH", str(cm.exception))
        self.assertIn("0.0", str(cm.exception))

    def test_same_version_error_unchanged(self):
        import sklearn
        from gold_candles_runtime.scalp_infer import ScalpModel
        with self.assertRaises(AttributeError):
            ScalpModel(self._entry(sklearn.__version__, _Bomb()))

    def test_mismatch_that_loads_is_reported(self):
        from gold_candles_runtime.scalp_infer import ScalpModel, sklearn_mismatch
        m = ScalpModel(self._entry("0.0", {"q10": None}))
        self.assertEqual(m.version_warning, sklearn_mismatch({"versions": {"scikit_learn": "0.0"}}))
        self.assertIn("0.0", m.version_warning)
        import sklearn
        self.assertIsNone(sklearn_mismatch({"versions": {"scikit_learn": sklearn.__version__}}))
        self.assertIsNone(sklearn_mismatch({}))                         # entry without versions: nothing claimed

    def test_worker_answer_carries_env_warning(self):
        from gold_candles_runtime import scalp_infer as SI
        from gold_candles_runtime import worker as W

        class Stub(_StubScalp):
            version_warning = "SKLEARN_VERSION_MISMATCH: trenowano 0.0"
        W._scalp_cache.update(run_id=None, model=None)
        self.addCleanup(W._scalp_cache.update, run_id=None, model=None)
        entry = dict(TestScalpForecastStaleI0754.ENTRY)
        with mock.patch.object(SI, "read_registry", return_value={"active": "R1", "runs": {"R1": entry}}), \
                mock.patch.object(SI, "activatable", return_value=(True, None)), mock.patch.object(SI, "ScalpModel", Stub):
            ans = W.scalp_forecast({"m1": _m1(150, time.time() - 120)})
        self.assertEqual(ans["status"], "SHADOW")
        self.assertEqual(ans["env_warning"], Stub.version_warning)


# ================================================================================================ I0623
class TestScalpSmallSplitI0623(unittest.TestCase):
    def _plan(self, bars, small):
        from gold_candles_runtime import scalp_train as T
        t = [int(datetime.fromisoformat(b["open_utc"]).timestamp()) for b in bars]
        d = {"dataset_sha": "0" * 64, "meta": {"data_kind": "SYNTHETIC_TEST", "symbol": "XAUUSD-", "tick_size": 0.01}}
        return t, T.make_plan(t, d, {}, small)

    @staticmethod
    def _counts(t, plan):
        from gold_candles_runtime import scalp_train as T
        b = plan["boundaries_utc"]
        cal0, hold0 = T._ts(b["calibration"][0]), T._ts(b["holdout"][0])
        t = np.asarray(t)
        return int((t < cal0).sum()), int(((t >= cal0) & (t < hold0)).sum()), int((t >= hold0).sum())

    def test_small_test_has_bars_in_every_period(self):
        import synth
        t, plan = self._plan(synth.m1_bars(8), True)
        dev, cal, hold = self._counts(t, plan)
        self.assertGreater(cal, 0, plan["boundaries_utc"])               # was 0: the calibration period fell on the weekend
        self.assertGreater(dev, 0)
        self.assertGreater(hold, 0)

    def test_real_plan_and_working_small_plan_unchanged(self):
        import synth
        from gold_candles_runtime import scalp_train as T
        for days, small in ((8, False), (12, True), (12, False)):
            bars = synth.m1_bars(days, seed=2)
            t, plan = self._plan(bars, small)
            t0, t1 = min(t), max(t)
            span, day = t1 - t0, 86400
            cal, hold = (t0 + int(0.6 * span)) // day * day, (t0 + int(0.8 * span)) // day * day      # the 1.45 formula
            self.assertEqual(plan["boundaries_utc"]["calibration"], [T._iso(cal), T._iso(hold)], (days, small))
            self.assertEqual(plan["boundaries_utc"]["holdout"][0], T._iso(hold))


# ================================================================================================ I0066
class TestAutoActivationRuleI0066(unittest.TestCase):
    def test_one_rule(self):
        import inspect

        from gold_candles_runtime import common, plan_train, scalp_train
        self.assertEqual(common.AUTO_ACTIVATION_VERDICTS, ("TRAINED_SHADOW", "PARTIAL_VALIDATION"))
        self.assertEqual(common.auto_admissible("TRAINED_SHADOW"), (True, None))
        self.assertEqual(common.auto_admissible("PARTIAL_VALIDATION"), (True, None))
        for st in ("SHADOW_UNVALIDATED", "REJECTED", "INSUFFICIENT_DATA", None):
            self.assertEqual(common.auto_admissible(st), (False, f"QUALITY_{st}"))
        for mod in (plan_train, scalp_train):                             # the trainers call it instead of their own copy of the list
            src = inspect.getsource(mod)
            self.assertIn("auto_admissible(", src)
            self.assertNotIn('("TRAINED_SHADOW", "PARTIAL_VALIDATION")', src)


# ================================================================================================ I0466
class TestRlPpoSampleCheckI0466(_Data):
    def _svc_and_dir(self, sample: dict):
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families import base as B
        from masterquo.modelhub.families.service import FamilyService
        store = B.Store(Path(self.td.dir) / "fam")
        d = Path(tempfile.mkdtemp(prefix="run_", dir=self.td.dir))
        (d / "manifest.json").write_text(json.dumps({"sample": sample}), encoding="utf-8")
        return FamilyService(ConfigStore(), None, store=store), d

    SAMPLE: ClassVar[dict] = {"bars_tail": [{"o": 1.0, "h": 1.1, "l": 0.9, "c": 1.0}] * 50, "position": 0.0, "expected": [0.2, 0.5, 0.3], "tolerance": 1e-6}

    def test_mismatch_is_refused(self):
        from masterquo.modelhub.families import deep
        s, d = self._svc_and_dir(self.SAMPLE)
        seen = {}

        def call(op, payload, timeout=0):
            seen.update(op=op, **payload)
            return {"ok": True, "action": 0, "probs": [0.6, 0.2, 0.2]}
        with mock.patch.object(deep, "call", side_effect=call):
            chk = s._sample_check("RL_PPO", {"dir": str(d)}, d)
        self.assertFalse(chk["ok"])                                      # was ok + checked False (any policy / VecNormalize passed)
        self.assertTrue(chk["checked"])
        self.assertEqual(seen["op"], "predict_ppo")
        self.assertEqual(seen["position"], 0.0)
        self.assertEqual(len(seen["bars"]), 50)

    def test_match_passes_and_old_artifact_unchanged(self):
        from masterquo.modelhub.families import deep
        s, d = self._svc_and_dir(self.SAMPLE)
        with mock.patch.object(deep, "call", return_value={"ok": True, "action": 1, "probs": [0.2, 0.5, 0.3]}):
            chk = s._sample_check("RL_PPO", {"dir": str(d)}, d)
        self.assertTrue(chk["ok"] and chk["checked"])
        s2, d2 = self._svc_and_dir({"expected": None, "tolerance": 0.0})
        with mock.patch.object(deep, "call", side_effect=AssertionError("no inference for an artifact without a sample")):
            chk = s2._sample_check("RL_PPO", {"dir": str(d2)}, d2)
        self.assertEqual((chk["ok"], chk["checked"]), (True, False))

    def test_fit_writes_the_sample(self):
        from masterquo.modelhub.families import deep
        from masterquo.modelhub.families.rl import PPO
        bars = [{"t": i, "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.0 + 0.001 * (i % 5), "spread": 20} for i in range(300)]
        res = {"ok": True, "val_ppo_minus_flat": 1.0, "val_ppo_minus_momentum": 1.0, "sample_bars": bars[:40], "sample_probs": [0.1, 0.2, 0.7]}
        with mock.patch.object(deep, "call", return_value=dict(res)):
            parts = PPO().fit({"bars": bars, "point": 0.01}, {}, Path(self.td.dir), {"profile": "smoke"})
        self.assertEqual(parts["sample"]["expected"], [0.1, 0.2, 0.7])
        self.assertEqual(parts["sample"]["bars_tail"], bars[:40])
        self.assertEqual(parts["sample"]["position"], 0.0)
        self.assertNotIn("sample_bars", parts["metrics"])                # the bars are stored once (sample), not in the metrics too


DEEP_PY = os.environ.get("MQ_DEEP_PYTHON") or ""


@unittest.skipUnless(DEEP_PY and Path(DEEP_PY).is_file(), "brak MQ_DEEP_PYTHON (.venv_deep: torch/gymnasium/SB3) – test BLOCKED")
class TestRlPpoSampleDeepI0466(_Data):
    def test_trained_policy_has_a_checked_sample(self):
        import test_families_u4 as U
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families import base as B
        from masterquo.modelhub.families import deep
        from masterquo.modelhub.families import run as RUN
        from masterquo.modelhub.families.service import FamilyService
        deep._HEALTH.clear()
        store = B.Store(Path(self.td.dir) / "fam")
        r = RUN.train("RL_PPO", INST, "smoke", {}, data=U.data_for(U.synth(3200, seed=12)), store=store)
        self.assertEqual(r["state"], "DONE", r)
        man = store.runs("RL_PPO", INST)[-1]
        self.assertEqual(len(man["sample"]["expected"]), 3)
        s = FamilyService(ConfigStore(), None, store=store)
        a = s.activate("RL_PPO", INST, r["run_id"])
        self.assertTrue(a["ok"], a)
        self.assertTrue(a["sample_check"]["checked"])
        self.assertLessEqual(a["sample_check"]["max_abs_diff"], 1e-6)


# ================================================================================================ I0023
class TestEventGruFeatureSchemaI0023(_Data):
    def _promote(self, schema: str) -> str:
        from masterquo.mm import artifacts as MA
        from masterquo.mm import event_engine as EE
        from masterquo.mm import events as EV
        st = {**EE.EventModel(F=len(EV.FEATURES)).state(), "scaler_med": np.zeros(len(EV.FEATURES)), "scaler_iqr": np.ones(len(EV.FEATURES)),
              "band": np.array([1e-4])}
        # merge with group mm (I0545): promote_shadow needs every validation gate True on REAL_USER_DATA (as mm/jobs.py writes)
        aid = MA.save(INST, "event_engine_dir3", st, {"status": "VALIDATED_SHADOW", "model_type": "EVENT_GRU_STACK", "feature_schema": schema,
                                                      "event_source": "BAR_CLOSE_EVENTS", "gates": {"walk_forward": True},
                                                      "data_kind": "REAL_USER_DATA"})
        MA.promote_shadow(INST, "event_engine_dir3", aid, "test")
        return aid

    def _predict(self):
        from masterquo.quant import adapters as QA
        rt = SimpleNamespace(bridge=SimpleNamespace(bars=lambda tf, include_forming=False: [], symbol_info={"point": 0.01}))
        return QA.EventGRU().predict(rt, INST)

    def test_other_feature_order_is_incompatible(self):
        from masterquo.mm import events as EV
        self._promote("PMW-MM-EVENT-1:" + ",".join(reversed(EV.FEATURES)))
        p = self._predict()
        self.assertEqual(p["state"], "INCOMPATIBLE", p)                 # was loaded (BLOCKED_DATA here only for lack of bars)
        self.assertIn("FEATURE_SCHEMA_MISMATCH", p["unavailable_reason"])

    def test_schema_written_by_training_still_loads(self):
        from masterquo.mm import events as EV
        self.assertEqual(EV.FEATURE_SCHEMA, "PMW-MM-EVENT-1:dt_log,dmid,abs_dmid,sgn,spread,dspread,act_log,spread_ok")   # = jobs.py since 1.42
        self._promote(EV.FEATURE_SCHEMA)
        p = self._predict()
        self.assertEqual(p["state"], "BLOCKED_DATA", p)                  # loaded; no closed M1 in this test

    def test_one_label(self):
        import inspect

        from masterquo.mm import events as EV
        from masterquo.mm import jobs
        from masterquo.modelhub.families.seq import EventGRU
        self.assertIn("EV.FEATURE_SCHEMA", inspect.getsource(jobs.job_event_engine))
        self.assertEqual(EventGRU.DATA["feature_schema"], EV.FEATURE_SCHEMA)


# ================================================================================================ I0034
class TestGprWalkForwardRunModeI0034(_Data):
    @staticmethod
    def _series(n=330, seed=3):
        rng = np.random.default_rng(seed)
        c = 2000.0 * np.exp(np.cumsum(rng.normal(0, 4e-4, n)))
        return np.arange(n, dtype=float) * 300 + 1_794_000_000, c

    def _ctx(self, synthetic: bool):
        t, c = self._series()
        snap = SimpleNamespace(snapshot_id="SNAP1", data_kind="SYNTHETIC_TEST" if synthetic else "REAL_USER_DATA")
        return SimpleNamespace(bars=lambda tf: SimpleNamespace(t=t, c=c), prof={"gpr_step": 25}, snap=snap, inst=INST, cancel=None,
                               synthetic=synthetic, seed=1, profile="quick")

    def _rows(self):
        from masterquo.mm import artifacts as MA
        con = sqlite3.connect(str(MA.root(INST) / "ledger.sqlite"))
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute("SELECT * FROM predictions")]
        con.close()
        return rows

    def test_job_rows_are_walk_forward(self):
        from masterquo.mm import jobs
        for synthetic, mode, quality in ((True, "WALK_FORWARD_SYNTHETIC", "SYNTHETIC_TEST"), (False, "WALK_FORWARD", "OK")):
            with self.subTest(synthetic=synthetic):
                jobs.job_gpr(self._ctx(synthetic))
                rows = [r for r in self._rows() if r["model_id"] == "gpr_logret:SNAP1"]
                self.assertTrue(rows)
                self.assertEqual({r["run_mode"] for r in rows}, {mode})      # was SHADOW like the live forecasts
                self.assertEqual({r["quality"] for r in rows}, {quality})    # was the GP health (OK / DEGRADED) - data quality now
                pl = json.loads(rows[0]["payload"])
                self.assertIn(pl["health"], ("OK", "DEGRADED"))
                self.assertEqual(pl["data_kind"], self._ctx(synthetic).snap.data_kind)
                from masterquo.mm import artifacts as MA
                (MA.root(INST) / "ledger.sqlite").unlink()

    def test_summary_separates_live_from_walk_forward(self):
        from masterquo.mm.ledger import Ledger
        led = Ledger(Path(self.td.dir) / "l.sqlite")
        kw = {"artifact_id": None, "feature_schema": "GPR_LAG1_LOGRET", "symbol": INST, "timeframe": "M5", "available_at": 1.0, "matures_at": 2.0,
              "horizon": "3bars", "kind": "GAUSSIAN_PREDICTIVE", "payload": {"pred": 0.0, "sd": 1.0}, "quality": "OK"}
        led.log(pred_id="a", model_id="gpr_logret:LIVE", source_ts=1.0, **kw)
        led.log(pred_id="b", model_id="gpr_logret:OLD", source_ts=1.0, **kw)                   # pre-1.46 walk-forward row (run_mode SHADOW)
        led.log(pred_id="c", model_id="gpr_logret:NEW", source_ts=1.0, run_mode="WALK_FORWARD_SYNTHETIC", **kw)
        led.log(pred_id="d", model_id="PMW-EVAL-1/ACTIVE", source_ts=1.0, **kw)                # evaluation ledger rows keep their run_mode
        led.log(pred_id="e", model_id="gpr_logret:OLD", source_ts=5.0, run_mode="WALK_FORWARD", **kw)       # legacy + new rows: one group
        summ = led.summary()
        modes = {r["model_id"]: r["run_mode"] for r in summ}
        self.assertEqual(modes, {"gpr_logret:LIVE": "SHADOW", "gpr_logret:OLD": "WALK_FORWARD", "gpr_logret:NEW": "WALK_FORWARD_SYNTHETIC",
                                 "PMW-EVAL-1/ACTIVE": "SHADOW"})
        old = next(r for r in summ if r["model_id"] == "gpr_logret:OLD")
        self.assertEqual((old["n"], old["scored"], old["first_ts"], old["last_ts"]), (2, 0, 1.0, 5.0))
        self.assertEqual(len(summ), 4)


# ================================================================================================ I0039
class TestEvalReadersI0039(_Data):
    def _svc(self):
        from masterquo.evaluation.service import EvaluationService
        return EvaluationService(None, None, None, data_dir=Path(self.td.dir) / "evaluation")

    def _fill(self, svc):
        led = svc.ledger
        rng = np.random.default_rng(5)
        n = 0
        for eng in ("ACTIVE_S01_S12", "SH_PACK"):
            for i in range(25):
                n += 1
                prob = None if i % 4 == 0 else float(rng.uniform(0, 1))
                a = {"engine": eng, "decision": "ENTER" if i % 3 else "SKIP", "probability": prob}
                cand = {"market_regime": {"both": {"ACTIVE": f"R{i % 2}", "SH": f"S{i % 3}"}} if i % 5 else None,
                        "features": {f"f{k}": float(rng.normal()) for k in range(40)}}
                out = None
                if i % 6:
                    out = {"status": "MATURED" if i % 7 else "NO_BARS", "plan_r_net": None if i % 8 == 0 else float(rng.normal()) / 3,
                           "first_event": "SL" if i % 2 else "TP1", "targets_hit": [bool(i % 3 == 1), False], "hold_s": float(i * 60) + 0.1,
                           "event_hit": None if i % 9 == 0 else bool(i % 2), "ambiguous_bars": i % 4 == 1}
                led.log(pred_id=f"p{n}", model_id=f"PMW-EVAL-1/{eng}", artifact_id=None, feature_schema="x", symbol=INST, timeframe="M5",
                        source_ts=float(n), available_at=float(n), matures_at=float(n) + 60, horizon="60s", kind="SETUP_ASSESSMENT",
                        payload={"candidate": cand, "assessment": a}, quality="OK")
                if out is not None:
                    led.c.execute("UPDATE predictions SET outcome=? WHERE pred_id=?", (json.dumps(out), f"p{n}"))
        # one row with a NaN probability (json.dumps writes NaN) - decoded by Python exactly as before
        led.log(pred_id="nan", model_id="PMW-EVAL-1/SH_PACK", artifact_id=None, feature_schema="x", symbol=INST, timeframe="M5", source_ts=999.0,
                available_at=999.0, matures_at=1059.0, horizon="60s", kind="SETUP_ASSESSMENT",
                payload={"candidate": {"market_regime": None, "features": {"f0": 1.0}},
                         "assessment": {"engine": "SH_PACK", "decision": "ENTER", "probability": float("nan")}},
                quality="OK")
        led.c.execute("UPDATE predictions SET outcome=? WHERE pred_id='nan'", (json.dumps({"status": "MATURED", "plan_r_net": 0.5, "event_hit": True}),))

    def test_status_counts_pending_in_sql(self):
        svc = self._svc()
        self._fill(svc)
        n_open = svc.ledger.c.execute("SELECT COUNT(*) FROM predictions WHERE outcome IS NULL").fetchone()[0]
        with mock.patch.object(svc.ledger, "pending", side_effect=AssertionError("SELECT * of the whole history")):
            st = svc.status()                                            # was len(self.ledger.pending())
        self.assertEqual(st["pending"], n_open)
        self.assertEqual(svc.ledger.count_pending(), n_open)
        self.assertEqual(svc.ledger.count_pending("PMW-EVAL-1/SH_PACK"),
                         svc.ledger.c.execute("SELECT COUNT(*) FROM predictions WHERE outcome IS NULL AND model_id='PMW-EVAL-1/SH_PACK'").fetchone()[0])

    def test_report_identical_without_decoding_candidates(self):
        from masterquo.evaluation import service as ES
        svc = self._svc()
        self._fill(svc)
        with mock.patch.object(ES, "_REPORT_SQL", None):
            ref = svc.report()                                           # the 1.46 path: every payload decoded in Python
        real_loads = json.loads
        decoded = []

        def loads(s, *a, **kw):
            decoded.append(s)
            return real_loads(s, *a, **kw)
        with mock.patch.object(ES.json, "loads", side_effect=loads):
            got = svc.report()
        self.assertEqual(json.dumps(got, sort_keys=True), json.dumps(ref, sort_keys=True))
        big = [s for s in decoded if isinstance(s, str) and '"features"' in s]
        self.assertEqual(len(big), 1)                                    # only the NaN row; was every row (candidate with its features)
        with mock.patch.object(ES, "_REPORT_SQL", None):
            full = svc._report_rows()
        self.assertEqual(json.dumps(svc._report_rows()), json.dumps(full))   # the decoded values themselves, bit for bit (not only rounded)


if __name__ == "__main__":
    unittest.main()
