"""1.11 - gold_candles_runtime in the isolated candle environment (.venv_candles: pinned numpy/pandas/scikit-learn).
Run with that interpreter (tools/run_tests.py does it): worker protocol, planned training with a frozen plan, statuses,
registry (no synthetic model can become active outside tests, checksum / contract checks, rollback), session break.
Data here is SYNTHETIC_TEST: it checks the program, not the market."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def make_data(d: Path, days: int = 40, seed: int = 3, tick: float = 0.01):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-03-02T00:00:00Z", periods=days * 288 * 7 // 5 + 400, freq="5min")
    idx = idx[idx.weekday < 5][: days * 288]
    n = len(idx)
    ch = rng.normal(0, .55, n)
    close = 3000 + np.cumsum(ch)
    op = np.r_[3000, close[:-1]]
    hi = np.maximum(op, close) + rng.uniform(.05, .8, n)
    lo = np.minimum(op, close) - rng.uniform(.05, .8, n)
    m5 = pd.DataFrame(dict(time_open_utc=idx.strftime("%Y-%m-%dT%H:%M:%SZ"), open=op, high=hi, low=lo, close=close, tick_volume=rng.integers(20, 200, n),
                           symbol="XAUUSD-"))
    d.mkdir(parents=True, exist_ok=True)
    m5.to_csv(d / "XAUUSD_M5.csv", index=False)
    g = pd.DataFrame(dict(o=op, h=hi, l=lo, c=close, v=m5.tick_volume.to_numpy()), index=idx)
    r = g.resample("30min").agg(dict(o="first", h="max", l="min", c="last", v="sum")).dropna()
    pd.DataFrame(dict(time_open_utc=r.index.strftime("%Y-%m-%dT%H:%M:%SZ"), open=r.o, high=r.h, low=r.l, close=r.c, tick_volume=r.v, symbol="XAUUSD-")
                 ).to_csv(d / "XAUUSD_M30.csv", index=False)
    (d / "source_metadata.json").write_text(json.dumps({"data_kind": "SYNTHETIC_TEST", "symbol": "XAUUSD-", "tick_size": tick,
                                                        "cutoff_utc": (idx[-1] + pd.Timedelta(minutes=5)).isoformat()}), encoding="utf-8")
    return m5


class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="mq_gc_rt_"))
        os.environ["MASTERQUO_DATA_DIR"] = str(cls.tmp / "data")
        cls.hist = cls.tmp / "hist"
        cls.m5 = make_data(cls.hist)
        from gold_candles_runtime import plan_train
        cls.rc = plan_train.main(["--data-dir", str(cls.hist), "--data-kind", "SYNTHETIC_TEST", "--trees", "10"])
        from gold_candles_runtime.common import read_registry
        cls.reg = read_registry()
        cls.rid = sorted(cls.reg["runs"])[-1]

    def worker(self, reqs, env_extra=None):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"), **(env_extra or {}))
        p = subprocess.run([sys.executable, "-m", "gold_candles_runtime.worker"], input="\n".join(json.dumps(r) for r in reqs) + "\n",
                           capture_output=True, text=True, env=env, cwd=str(ROOT / "backend"), timeout=300)
        return [json.loads(x) for x in p.stdout.splitlines() if x.strip()]

    def bars(self, n=500, end=None):
        sub = self.m5.iloc[-n:] if end is None else self.m5.iloc[end - n: end]
        rows = [{"open_utc": r.time_open_utc, "o": r.open, "h": r.high, "l": r.low, "c": r.close, "tv": int(r.tick_volume)} for r in sub.itertuples()]
        t = pd.Timestamp(rows[0]["open_utc"])
        f = pd.DataFrame(rows)
        f["t"] = pd.to_datetime(f.open_utc)
        g = f.set_index("t").resample("30min").agg(dict(o="first", h="max", l="min", c="last", tv="sum", open_utc="first")).dropna()
        m30 = [{"open_utc": i.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": r.o, "h": r.h, "l": r.l, "c": r.c, "tv": int(r.tv)} for i, r in g.iterrows()]
        last = pd.Timestamp(rows[-1]["open_utc"]) + pd.Timedelta(minutes=5)
        m30 = [x for x in m30 if pd.Timestamp(x["open_utc"]) + pd.Timedelta(minutes=30) <= last]
        return rows, m30, last.strftime("%Y-%m-%dT%H:%M:%SZ"), t

    def test_01_training_artifacts_plan_and_statuses(self):
        self.assertEqual(self.rc, 0)
        e = self.reg["runs"][self.rid]
        out = Path(e["validation_path"]).parent
        for f in ("forecast_model.json", "forecast_validation.json", "TRAINING_PLAN.json", "run_log.jsonl"):
            self.assertTrue((out / f).exists(), f)
        val = json.loads((out / "forecast_validation.json").read_text(encoding="utf-8"))
        plan = json.loads((self.hist / "TRAINING_PLAN.json").read_text(encoding="utf-8"))
        for h, r in val["horizons"].items():
            self.assertEqual(r["split"], plan["boundaries_utc"])               # ONE set of UTC boundaries for 5/15/30
            self.assertLess(pd.Timestamp(r["fit_labels_end_utc"]), pd.Timestamp(plan["boundaries_utc"]["calibration_start"]) - pd.Timedelta(minutes=30))
            self.assertLess(pd.Timestamp(r["calibration_labels_end_utc"]), pd.Timestamp(plan["boundaries_utc"]["holdout_start"]) - pd.Timedelta(minutes=30))
            self.assertIn(r["status"], ("REJECTED", "SHADOW_UNVALIDATED"))     # synthetic data can never be SHADOW_VALIDATED
            for k in ("baseline", "no_pattern_model", "reliability", "uncertainty_day_block_bootstrap", "quantiles", "sessions"):
                self.assertIn(k, r)
        self.assertEqual(val["strategy_validation"], "STRATEGY_BACKTEST_NOT_AVAILABLE")
        self.assertEqual(val["runtime_check"]["status"], "OK")
        self.assertIsNone(self.reg.get("active"))                               # synthetic model never auto-activated

    def test_02_plan_is_frozen_per_dataset(self):
        from gold_candles_runtime import plan_train
        p0 = json.loads((self.hist / "TRAINING_PLAN.json").read_text(encoding="utf-8"))
        changed = self.tmp / "hist_changed"
        make_data(changed, seed=4)
        (changed / "TRAINING_PLAN.json").write_text(json.dumps(p0), encoding="utf-8")
        with self.assertRaises(SystemExit):                                     # a plan of another dataset is refused
            plan_train.main(["--data-dir", str(changed), "--data-kind", "SYNTHETIC_TEST", "--trees", "10", "--no-activate"])

    def test_03_insufficient_data_is_reported_with_amounts(self):
        from gold_candles_runtime import plan_train
        short = self.tmp / "hist_short"
        make_data(short, days=4)
        rc = plan_train.main(["--data-dir", str(short), "--data-kind", "SYNTHETIC_TEST", "--trees", "10", "--no-activate"])
        self.assertIn(rc, (0, 4))
        runs = sorted((self.tmp / "data" / "forecast" / "runs").glob("*"))
        val = json.loads((runs[-1] / "forecast_validation.json").read_text(encoding="utf-8"))
        self.assertEqual(val["overall_status"], "INSUFFICIENT_DATA")
        self.assertTrue(any("brakuje" in x for x in json.dumps(val, ensure_ascii=False).split('"')))

    def test_04_registry_refuses_synthetic_and_worker_reports_no_model(self):
        from gold_candles_runtime.common import activate
        with self.assertRaises(SystemExit):
            activate(self.rid, reason="test")
        m5, m30, as_of, _ = self.bars()
        ans = self.worker([{"cmd": "hello"}, {"cmd": "analyze", "m5": m5, "m30": m30, "symbol": "XAUUSD-", "tick_size": 0.01, "as_of": as_of, "flags_tail": 5}])
        self.assertTrue(ans[0]["ok"])
        self.assertEqual(ans[1]["status"], "NO_MODEL")
        self.assertIsNone(ans[1]["report"]["forecast"]["probabilities"])
        self.assertFalse(ans[1]["execution_permission"])
        self.assertEqual(ans[1]["report"]["execution_lock"]["state"], "BLOCKED")
        self.assertEqual(len(ans[1]["flags_tail"]), 5)

    def test_05_shadow_forecast_contract_and_mismatches(self):
        env = {"MQ_FORECAST_TEST_ALLOW_SYNTHETIC": "1"}
        os.environ.update(env)
        try:
            from gold_candles_runtime.common import activate, read_registry, write_registry
            activate(self.rid, reason="test only")
            m5, m30, as_of, _ = self.bars()
            ok = self.worker([{"cmd": "analyze", "m5": m5, "m30": m30, "symbol": "XAUUSD-", "tick_size": 0.01, "as_of": as_of}], env)[0]
            self.assertEqual(ok["status"], "SHADOW", ok.get("reason"))
            for h in ok["report"]["forecast"]["probabilities"].values():
                self.assertAlmostEqual(sum(h["probabilities"].values()), 1.0, places=9)
                q = h["close_price_quantiles"]
                self.assertTrue(q["q10"] <= q["q50"] <= q["q90"])
                self.assertTrue(all(np.isfinite(v) for v in list(q.values()) + list(h["probabilities"].values())))
            self.assertFalse(ok["execution_permission"])
            bad_tick = self.worker([{"cmd": "analyze", "m5": m5, "m30": m30, "symbol": "XAUUSD-", "tick_size": 0.05, "as_of": as_of}], env)[0]
            self.assertEqual(bad_tick["status"], "CONTRACT_MISMATCH")
            bad_sym = self.worker([{"cmd": "analyze", "m5": m5, "m30": m30, "symbol": "XAUT", "tick_size": 0.01, "as_of": as_of}], env)[0]
            self.assertEqual(bad_sym["status"], "FORECAST_UNAVAILABLE")              # ONLY_XAUUSD_SUPPORTED - never substituted
            old5, old30, old_as_of, _ = self.bars(end=600)                            # a snapshot before the model's knowledge
            fut = self.worker([{"cmd": "analyze", "m5": old5, "m30": old30, "symbol": "XAUUSD-", "tick_size": 0.01, "as_of": old_as_of}], env)[0]
            self.assertIn(fut["status"], ("MODEL_FROM_FUTURE_RELATIVE_TO_SNAPSHOT", "MODEL_FROM_FUTURE"))
            e = read_registry()["runs"][self.rid]
            Path(e["model_path"]).write_text(Path(e["model_path"]).read_text(encoding="utf-8") + " ", encoding="utf-8")   # tampered artifact
            tam = self.worker([{"cmd": "analyze", "m5": m5, "m30": m30, "symbol": "XAUUSD-", "tick_size": 0.01, "as_of": as_of}], env)[0]
            self.assertEqual(tam["status"], "NO_MODEL")
            self.assertIn("CHECKSUM", tam["reason"])
            reg = read_registry()
            reg["active"] = None
            write_registry(reg)
        finally:
            os.environ.pop("MQ_FORECAST_TEST_ALLOW_SYNTHETIC", None)

    def test_06_session_break_and_warmup(self):
        from gold_candles_runtime.worker import session_check
        self.assertEqual(session_check("2026-10-16T20:45:00Z", 30), "BLOCKED_SESSION_BREAK")     # Friday evening -> weekend
        self.assertEqual(session_check("2026-10-14T10:00:00Z", 30), "NOT_VERIFIED_BROKER_SESSIONS")
        m5, m30, as_of, _ = self.bars(n=30)
        ans = self.worker([{"cmd": "analyze", "m5": m5, "m30": m30[-2:], "symbol": "XAUUSD-", "tick_size": 0.01, "as_of": as_of}])[0]
        self.assertIn(ans["status"], ("NO_MODEL", "WARMUP", "FORECAST_UNAVAILABLE"))
        self.assertFalse(ans["execution_permission"])

    def test_07_bad_request_does_not_kill_the_worker(self):
        ans = self.worker([{"cmd": "analyze"}, {"cmd": "hello"}])
        self.assertFalse(ans[0].get("ok", True))
        self.assertTrue(ans[1]["ok"])


if __name__ == "__main__":
    unittest.main()
