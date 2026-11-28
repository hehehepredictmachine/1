"""1.46 audit, group D_runtimes_1: deep_runtime (rl, nlp), gold_candles (cli, mt5_reader), gold_candles_runtime (common, plan_train,
registry_cli, scalp_features, scalp_train, validate, worker), kronos_runtime (engine, install), sdformer_runtime/train.py.

chunk_39#15  PPO predict observes the LAST closed bar (was len-2: the newest closed candle was ignored).
chunk_40#5   reference MT5 reader: broker SERVER time is never taken for UTC - the newest tick must put the server on UTC (15-minute
             zone grid, like the bot's ServerClock); any other / unverifiable offset is BLOCKED (bars were 'from the future' or
             silently shifted).
chunk_40#1   an unreadable forecast / scalp registry is never written back as an empty one (runs + active model were lost).
chunk_40#4   plan_train: after a refused activation the log no longer claims the run is the active SHADOW model.
chunk_40#3   registry_cli list / rollback check the contract like the worker; activate() computes it like the worker (profile grid_step).
chunk_40#7   scalp labels skip rows with ATR == 0 (ZeroDivisionError ended the whole training).
chunk_40#6   scalp training: the commission (account currency) is converted to quote-currency price units with MT5's tick value when
             the account currency differs; no tick value -> COMMISSION_CURRENCY_UNKNOWN.
chunk_40#9   session_check: the gold weekend break is not assumed for BTC (NOT_VERIFIED_BROKER_SESSIONS).
chunk_41#2   Kronos selftest(reference=True) restores the device (RoPE caches reset on that report-only path); install.verify reports the
             LOAD state. (The live predict() GPU -> CPU fallback, chunk_41#1, was kept as in 1.45 here - rule 1; fixed in arch 1.46
             I0193 / I0755 with its decision limits: tests/test_arch146_w2_kronos.py.)
chunk_41#3   SDformerFlow resume writes a NEW version folder (never into the active version); nothing to do -> NOTHING_TO_DO.
chunk_41#5   SDformerFlow: a cancel inside an epoch keeps the last COMPLETE checkpoint.
chunk_41#9   SDformerFlow: trained_until = last TARGET bar of the training samples; the validation tail starts after an embargo.
chunk_39#22  nlp predict: a missing checkpoint is CHECKPOINT_NOT_FOUND (Path('') is the working directory).
chunk_40#14  reference CLI shows Apollo23.
chunk_40#10  plan_train labels use the instrument config (neutral_atr of the profile).
chunk_40#11  validate.py: relocated paths, make_config contract, --instrument, unknown run id.
chunk_41#8   Kronos download retries: no 'ponowienie 5/4' and no sleep after the last attempt.
(chunk_40#2 broker gold symbols and chunk_40#8 scalp staleness are DECISIONS of the lead - not changed, no test here.)
All market data below is SYNTHETIC (random walk); nothing here is a forecast or a backtest."""
from __future__ import annotations

import contextlib
import io
import json
import os
import pickle
import signal
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import _env

UTC = timezone.utc


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _EnvGuard:
    """Restores os.environ keys the runtime sets (use_instrument writes MQ_INSTRUMENT) and the registered broker symbols."""

    KEYS = ("MQ_INSTRUMENT", "MQ_FORECAST_TEST_ALLOW_SYNTHETIC", "MASTERQUO_DATA_DIR")

    def __enter__(self):
        from gold_candles import data as gd
        self.prev = {k: os.environ.get(k) for k in self.KEYS}
        self.syms = set(gd.REGISTERED_SYMBOLS)
        return self

    def __exit__(self, *exc):
        from gold_candles import data as gd
        for k, v in self.prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        gd.REGISTERED_SYMBOLS.clear()
        gd.REGISTERED_SYMBOLS.update(self.syms)


# ===================================================================================================== chunk_39#15 PPO predict
class TestPpoPredictLastClosedBar(unittest.TestCase):
    def _fakes(self, seen):
        gym = types.ModuleType("gymnasium")

        class Env:
            def __init__(self):
                pass

            def reset(self, *, seed=None, options=None):
                return None
        gym.Env = Env
        spaces = types.ModuleType("gymnasium.spaces")
        spaces.Box = lambda *a, **k: ("Box", a, k)
        spaces.Discrete = lambda n: ("Discrete", n)
        gym.spaces = spaces
        sb3 = types.ModuleType("stable_baselines3")

        class Probs:
            def __init__(self, a):
                self.a = a

            def cpu(self):
                return self

            def numpy(self):
                return self.a

        class Policy:
            def obs_to_tensor(self, oo):
                return oo, None

            def get_distribution(self, x):
                return types.SimpleNamespace(distribution=types.SimpleNamespace(probs=Probs(np.array([[0.2, 0.5, 0.3]]))))

        class Model:
            policy = Policy()

            def predict(self, oo, deterministic=True):
                seen.append(np.array(oo))
                return np.array([1]), None

        sb3.PPO = types.SimpleNamespace(load=lambda path, device="cpu": Model())
        common = types.ModuleType("stable_baselines3.common")
        vec = types.ModuleType("stable_baselines3.common.vec_env")
        vec.DummyVecEnv = lambda fns: [f() for f in fns]

        class VN:
            training = True

            def normalize_obs(self, o):
                return o
        vec.VecNormalize = types.SimpleNamespace(load=lambda path, venv: VN())
        torch = types.ModuleType("torch")
        torch.no_grad = contextlib.nullcontext
        return {"gymnasium": gym, "gymnasium.spaces": spaces, "stable_baselines3": sb3, "stable_baselines3.common": common,
                "stable_baselines3.common.vec_env": vec, "torch": torch}

    def test_observation_is_built_on_the_newest_closed_bar(self):
        from deep_runtime import rl
        from masterquo.modelhub.families.rl_core import ReplayCore
        rng = np.random.default_rng(5)
        c = 2000 + np.cumsum(rng.normal(0, 1, 60))
        bars = [{"o": float(x - 0.1), "h": float(x + 0.5), "l": float(x - 0.5), "c": float(x)} for x in c]
        bars[-1] = {"o": bars[-2]["c"], "h": bars[-2]["c"] + 9.0, "l": bars[-2]["c"] - 1.0, "c": bars[-2]["c"] + 8.0}   # distinctive last bar
        env = {"k": 8, "spread": 0.2, "slippage": 0.05, "commission": 0.0, "unit": 1.0, "max_units": 1, "reward_scale": 1.0, "max_steps": 50}
        with tempfile.TemporaryDirectory() as d:
            Path(d, "rl_config.json").write_text(json.dumps({"env": env}), encoding="utf-8")
            seen: list = []
            with mock.patch.dict(sys.modules, self._fakes(seen)):
                out = rl.predict({"dir": d, "bars": bars, "position": 0.0})
        self.assertTrue(out["ok"])
        core = ReplayCore(bars, **env)
        core.reset(len(bars) - 1)
        expected = core.obs()
        np.testing.assert_allclose(seen[0][0], expected, rtol=1e-6)
        self.assertAlmostEqual(float(seen[0][0][env["k"] - 1]), float(np.log(bars[-1]["c"] / bars[-2]["c"]) * 100), places=4)


# ===================================================================================================== chunk_40#5 MT5 reader time
class _FakeMT5:
    TIMEFRAME_M5, TIMEFRAME_M30 = 5, 30

    def __init__(self, offset_s: int, stale_s: float = 0.0):
        self.offset, self.stale, self.n = int(offset_s), float(stale_s), 0

    def initialize(self):
        return True

    def shutdown(self):
        return None

    def last_error(self):
        return (1, "Success")

    def symbol_select(self, s, v):
        return True

    def symbol_info(self, s):
        return types.SimpleNamespace(visible=True, name=s, currency_base="XAU", currency_profit="USD", trade_tick_size=0.01, trade_contract_size=100.0)

    def symbol_info_tick(self, s):
        self.n += 1
        ms = int((time.time() - self.stale + self.offset) * 1000) - 50 + self.n      # broker SERVER wall clock as an epoch
        return types.SimpleNamespace(time_msc=ms, time=ms // 1000, bid=2000.0, ask=2000.2)

    def copy_rates_from_pos(self, s, tf, pos, count):
        step = tf * 60
        server_now = int(time.time() - self.stale) + self.offset
        last_open = server_now // step * step - pos * step
        t = last_open - step * np.arange(count)[::-1]
        c = 2000 + np.cumsum(np.random.default_rng(1).normal(0, 0.3, count))
        o = np.r_[c[0], c[:-1]]
        dt = np.dtype([("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"), ("tick_volume", "<u8"),
                       ("spread", "<i4"), ("real_volume", "<u8")])
        out = np.zeros(count, dtype=dt)
        out["time"], out["open"], out["close"] = t, o, c
        out["high"], out["low"] = np.maximum(o, c) + 0.2, np.minimum(o, c) - 0.2
        out["tick_volume"], out["spread"] = 50, 20
        return out


class TestReferenceMt5ReaderTime(unittest.TestCase):
    def _read(self, offset, stale=0.0):
        from gold_candles import mt5_reader
        with mock.patch.dict(sys.modules, {"MetaTrader5": _FakeMT5(offset, stale)}):
            return mt5_reader.read_mt5("XAUUSD-", 400)

    def test_server_ahead_of_utc_is_blocked_with_the_time_reason(self):
        from gold_candles.data import DataError
        with self.assertRaises(DataError) as cm:
            self._read(7200)
        self.assertIn("MT5_SERVER_TIME", str(cm.exception))

    def test_server_behind_utc_is_not_silently_shifted(self):
        from gold_candles.data import DataError
        with self.assertRaises(DataError) as cm:
            self._read(-3600)
        self.assertIn("MT5_SERVER_TIME", str(cm.exception))

    def test_server_behind_utc_with_stale_tick_is_not_taken_for_utc(self):
        from gold_candles.data import DataError
        with self.assertRaises(DataError) as cm:
            self._read(-7200, stale=600)                                     # quiet / closed market: offset cannot be confirmed
        self.assertIn("MT5_SERVER_TIME_OFFSET_UNVERIFIED", str(cm.exception))

    def test_utc_server_still_reads_closed_bars(self):
        m5, m30, config, quote, now = self._read(0)
        self.assertLessEqual(m5.time_close_utc.iloc[-1], now)
        self.assertGreater(len(m5), 100)
        self.assertEqual(config.symbol, "XAUUSD-")
        self.assertTrue(quote["valid"])


# ===================================================================================================== gold_candles_runtime registry helpers
def _gc_entry(root: Path, rid: str, contract: str, *, symbol="XAUUSD-", tick=0.01, inst=None, grid_step=5.0, base=None) -> dict:
    """Registry entry with a real artifact file (checksum) under <forecast>/runs/<rid>/ (or under `base` = an old project folder)."""
    from gold_candles.model import SCHEMA
    from gold_candles_runtime.common import sha256_file
    d = root / "runs" / rid
    d.mkdir(parents=True, exist_ok=True)
    mp = d / "forecast_model.json"
    mp.write_text(json.dumps({"schema": SCHEMA, "run_id": rid}), encoding="utf-8")
    (d / "forecast_validation.json").write_text(json.dumps({"run_id": rid, "horizons": {}}), encoding="utf-8")
    shown = (base / "runs" / rid) if base is not None else d
    e = {"run_id": rid, "model_path": str(shown / "forecast_model.json"), "artifact_sha256": sha256_file(mp),
         "validation_path": str(shown / "forecast_validation.json"), "data_kind": "SYNTHETIC_TEST", "data_dir": str(root / "no_such_history"),
         "symbol": symbol, "tick_size": tick, "grid_step": grid_step, "contract_hash": contract, "horizons_trained": ["1", "3", "6"],
         "overall_status": "SHADOW_UNVALIDATED", "horizon_status": {"1": "SHADOW_UNVALIDATED"}}
    if inst:
        e["instrument"] = inst
    return e


class _RegistryCase(unittest.TestCase):
    def setUp(self):
        self.guard = _EnvGuard().__enter__()
        self.td = _env.TempData()
        os.environ["MQ_FORECAST_TEST_ALLOW_SYNTHETIC"] = "1"
        os.environ.pop("MQ_INSTRUMENT", None)

    def tearDown(self):
        self.td.close()
        self.guard.__exit__(None, None, None)

    def write_reg(self, reg):
        from gold_candles_runtime.common import registry_path
        p = registry_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(reg), encoding="utf-8")
        return p


# ===================================================================================================== chunk_40#1 unreadable registry
class TestUnreadableRegistryNeverOverwritten(_RegistryCase):
    def _corrupt(self):
        from gold_candles_runtime.common import registry_path
        p = registry_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'{"schema": "masterquo-forecast-registry-1", "active": "RUN_A", "runs": {"RUN_A": {"run_id": "RUN_A"')   # truncated
        return p, p.read_bytes()

    def test_strict_read_refuses(self):
        from gold_candles_runtime import common
        p, raw = self._corrupt()
        self.assertEqual(common.read_registry().get("error"), "REGISTRY_UNREADABLE")     # readers still get the empty view
        with self.assertRaises(SystemExit) as cm:
            common.read_registry(strict=True)
        self.assertIn("REGISTRY_UNREADABLE", str(cm.exception))
        self.assertEqual(p.read_bytes(), raw)

    def test_registry_cli_deactivate_and_rollback_leave_the_file(self):
        from gold_candles_runtime import registry_cli
        p, raw = self._corrupt()
        for cmd in ("deactivate", "rollback"):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = registry_cli.main([cmd])
            self.assertNotEqual(rc, 0, cmd)
            self.assertEqual(p.read_bytes(), raw, cmd)

    def test_validate_reports_unreadable_registry(self):
        from gold_candles_runtime import validate
        p, raw = self._corrupt()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = validate.main([])
        self.assertEqual(rc, 2)
        self.assertIn("REGISTRY_UNREADABLE", out.getvalue())
        self.assertEqual(p.read_bytes(), raw)

    def test_scalp_train_registry_update_refuses_unreadable(self):
        from gold_candles_runtime import scalp_train
        from gold_candles_runtime.scalp_infer import registry_path
        p = registry_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'{"active": "S1", "runs": {"S1": ')
        raw = p.read_bytes()
        with self.assertRaises(SystemExit) as cm:
            scalp_train._registry_for_update()
        self.assertIn("REGISTRY_UNREADABLE", str(cm.exception))
        self.assertEqual(p.read_bytes(), raw)


    def test_scalp_registry_cli_leaves_an_unreadable_registry(self):
        # chunk_40#1 (rest): scalp_registry rollback / deactivate wrote the empty view back, validate returned 0
        from gold_candles_runtime import scalp_registry
        from gold_candles_runtime.scalp_infer import registry_path
        p = registry_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'{"active": "S1", "history": ["S0"], "runs": {"S1": ')
        raw = p.read_bytes()
        for cmd in ("deactivate", "rollback", "validate", "list"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = scalp_registry.main([cmd])
            self.assertEqual(rc, 2, cmd)
            self.assertIn("REGISTRY_UNREADABLE", out.getvalue(), cmd)
            self.assertEqual(p.read_bytes(), raw, cmd)

# ===================================================================================================== chunk_40#3 registry_cli contract
class TestRegistryCliContract(_RegistryCase):
    def test_rollback_skips_contract_mismatch_and_list_shows_it(self):
        from gold_candles_runtime import registry_cli
        from gold_candles_runtime.common import forecast_dir, make_config, read_registry
        cur = make_config("XAUUSD-", 0.01).contract_hash()
        root = forecast_dir()
        reg = {"schema": "masterquo-forecast-registry-1", "active": "RUN_C", "history": ["RUN_GOOD", "RUN_OLD"],
               "runs": {"RUN_GOOD": _gc_entry(root, "RUN_GOOD", cur), "RUN_OLD": _gc_entry(root, "RUN_OLD", "0" * 64),
                        "RUN_C": _gc_entry(root, "RUN_C", cur)}}
        self.write_reg(reg)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            registry_cli.main(["list"])
        line = next(x for x in out.getvalue().splitlines() if "RUN_OLD" in x)
        self.assertIn("CONTRACT_MISMATCH", line)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = registry_cli.main(["rollback"])
        self.assertEqual(rc, 0)
        self.assertEqual(read_registry()["active"], "RUN_GOOD")             # the incompatible run is skipped, never activated

    def test_activate_uses_the_profile_grid_step_like_the_worker(self):
        os.environ["MQ_INSTRUMENT"] = "BTC"
        from gold_candles_runtime import common
        stale = common.make_config("BTCUSD", 0.01, "BTC", 250.0).contract_hash()      # trained with another grid_step than the profile now has
        self.write_reg({"schema": "masterquo-forecast-registry-1", "active": None, "history": [],
                        "runs": {"RUN_B": _gc_entry(common.forecast_dir(), "RUN_B", stale, symbol="BTCUSD", inst="BTC", grid_step=250.0)}})
        with self.assertRaises(SystemExit) as cm:
            common.activate("RUN_B", reason="test")
        self.assertIn("CONTRACT_MISMATCH", str(cm.exception))
        self.assertIsNone(common.read_registry()["active"])


# ===================================================================================================== chunk_40#4 / #1 / #10 plan_train
def _m5_data(d: Path, days: int = 15, seed: int = 3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-03-02T00:00:00Z", periods=days * 288 * 7 // 5 + 400, freq="5min")
    idx = idx[idx.day_of_week < 5][: days * 288]
    n = len(idx)
    close = 3000 + np.cumsum(rng.normal(0, .55, n))
    op = np.r_[3000, close[:-1]]
    hi = np.maximum(op, close) + rng.uniform(.05, .8, n)
    lo = np.minimum(op, close) - rng.uniform(.05, .8, n)
    m5 = pd.DataFrame(dict(time_open_utc=idx.strftime("%Y-%m-%dT%H:%M:%SZ"), open=op, high=hi, low=lo, close=close,
                           tick_volume=rng.integers(20, 200, n), symbol="XAUUSD-"))
    d.mkdir(parents=True, exist_ok=True)
    m5.to_csv(d / "XAUUSD_M5.csv", index=False)
    g = pd.DataFrame(dict(o=op, h=hi, l=lo, c=close, v=m5.tick_volume.to_numpy()), index=idx)
    r = g.resample("30min").agg(dict(o="first", h="max", l="min", c="last", v="sum")).dropna()
    pd.DataFrame(dict(time_open_utc=r.index.strftime("%Y-%m-%dT%H:%M:%SZ"), open=r.o, high=r.h, low=r.l, close=r.c, tick_volume=r.v,
                      symbol="XAUUSD-")).to_csv(d / "XAUUSD_M30.csv", index=False)
    (d / "source_metadata.json").write_text(json.dumps({"data_kind": "SYNTHETIC_TEST", "symbol": "XAUUSD-", "tick_size": 0.01,
                                                        "cutoff_utc": (idx[-1] + pd.Timedelta(minutes=5)).isoformat()}), encoding="utf-8")


class TestPlanTrainRegistryAndLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = _EnvGuard().__enter__()
        cls.td = _env.TempData()
        os.environ.pop("MQ_INSTRUMENT", None)
        os.environ.pop("MQ_FORECAST_TEST_ALLOW_SYNTHETIC", None)
        cls.hist = Path(cls.td.dir) / "hist"
        cls.out = Path(cls.td.dir) / "run_out"
        _m5_data(cls.hist)
        from gold_candles_runtime import plan_train
        with contextlib.redirect_stdout(io.StringIO()):
            cls.rc = plan_train.main(["--data-dir", str(cls.hist), "--data-kind", "SYNTHETIC_TEST", "--trees", "5", "--out", str(cls.out)])

    @classmethod
    def tearDownClass(cls):
        cls.td.close()
        cls.guard.__exit__(None, None, None)

    def test_refused_activation_is_not_logged_as_active(self):
        self.assertEqual(self.rc, 0)
        msgs = [json.loads(x)["msg"] for x in (self.out / "run_log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(m.startswith("NIE aktywowano") for m in msgs), msgs[-5:])
        self.assertFalse(any(m.startswith("aktywny model obserwacyjny SHADOW") for m in msgs), msgs[-5:])

    def test_unreadable_registry_after_training_is_left_untouched(self):
        from gold_candles_runtime import plan_train
        from gold_candles_runtime.common import registry_path
        p = registry_path()
        good = json.loads(p.read_text(encoding="utf-8"))
        self.assertTrue(good["runs"])
        p.write_bytes(p.read_bytes()[:40])                                    # truncated by a crash / locked by another program
        raw = p.read_bytes()
        try:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
                plan_train.main(["--data-dir", str(self.hist), "--data-kind", "SYNTHETIC_TEST", "--trees", "5", "--out", str(self.out)])
            self.assertIn("REGISTRY_UNREADABLE", str(cm.exception))
            self.assertEqual(p.read_bytes(), raw)                             # never replaced by {"runs": {<new run>}}
        finally:
            p.write_text(json.dumps(good), encoding="utf-8")

    def test_labels_use_the_instrument_config(self):
        from gold_candles.data import Config
        from gold_candles_runtime import plan_train
        seen = {}

        class Stop(Exception):
            pass

        def fake_labels(m5, h, config=None):
            seen["config"] = config
            raise Stop()
        cfg = Config(symbol="XAUUSD-", tick_size=0.01, neutral_atr=0.35)
        with mock.patch("gold_candles.features.make_labels", side_effect=fake_labels), self.assertRaises(Stop):
            plan_train.train_horizon(1, None, None, None, {}, 5, lambda *a, **k: None, config=cfg)
        self.assertIs(seen["config"], cfg)


# ===================================================================================================== chunk_40#7 scalp labels ATR 0
class TestScalpLabelsZeroAtr(unittest.TestCase):
    def test_zero_atr_rows_get_no_label(self):
        from gold_candles_runtime import scalp_features as SF
        n = 40
        t = [1_700_000_000 + 60 * i for i in range(n)]
        c = [2000.0] * 20 + [2000.0 + 0.5 * i for i in range(20)]
        a = [None] * 13 + [0.0] * 7 + [0.4] * 20                      # flat first minutes: ATR exactly 0
        sp = [0.2] * n
        Y, Q, END = SF.labels(t, c, a, sp, 0.005, 0.02)
        for hz in SF.HORIZONS:
            self.assertTrue((Y[hz][13:20] == -1).all())
            self.assertTrue(np.isnan(Q[hz][13:20]).all())
            self.assertTrue((Y[hz][20:n - hz] >= 0).all())


# ===================================================================================================== chunk_40#6 scalp commission currency
class TestScalpCommissionCurrency(unittest.TestCase):
    def setUp(self):
        self.guard = _EnvGuard().__enter__()
        self.td = _env.TempData()
        os.environ.pop("MQ_INSTRUMENT", None)
        self.hist = Path(self.td.dir) / "scalp" / "history" / "20260401T0000Z"
        self.hist.mkdir(parents=True)
        t0 = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
        rows = ["time_open_utc,open,high,low,close,tick_volume,symbol,spread_points"]
        for i in range(30):
            rows.append(f"{_iso(t0 + timedelta(minutes=i))},2000,2000.5,1999.5,2000.1,100,XAUUSD-,12")
        (self.hist / "XAUUSD_M1.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    def tearDown(self):
        self.td.close()
        self.guard.__exit__(None, None, None)

    def _costs(self, **meta_extra):
        from gold_candles_runtime import scalp_train
        spec = {"point": 0.01, "trade_tick_size": 0.01, "trade_contract_size": 100.0, "volume_min": 0.01, "volume_step": 0.01}
        spec.update(meta_extra.pop("spec", {}))
        meta = {"symbol": "XAUUSD-", "data_kind": "SYNTHETIC_TEST", "tick_size": 0.01, "spec": spec, **meta_extra}
        (self.hist / "source_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        seen = {}

        class Stop(Exception):
            pass

        def fake_plan(t, d, costs, small):
            seen["costs"] = costs
            raise Stop()
        with mock.patch.object(scalp_train, "make_plan", side_effect=fake_plan), contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(Stop):
            scalp_train.main(["--history", str(self.hist), "--data-kind", "SYNTHETIC_TEST", "--commission-per-lot-side", "3.5", "--no-activate"])
        return seen["costs"]

    def test_non_usd_account_is_converted_with_tick_value(self):
        c = self._costs(account_currency="EUR", quote_currency="USD", spec={"trade_tick_value": 0.92})
        self.assertAlmostEqual(c["commission_price_side"], 3.5 * 0.01 / 0.92, places=12)     # EUR -> USD price units (was 3.5 / 100)
        self.assertIn("tick_value", c["conversion"])

    def test_non_usd_account_without_tick_value_is_refused(self):
        from gold_candles_runtime import scalp_train
        (self.hist / "source_metadata.json").write_text(json.dumps({"symbol": "XAUUSD-", "data_kind": "SYNTHETIC_TEST", "tick_size": 0.01,
                                                                     "account_currency": "PLN", "quote_currency": "USD",
                                                                     "spec": {"point": 0.01, "trade_tick_size": 0.01, "trade_contract_size": 100.0}}),
                                                         encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            scalp_train.main(["--history", str(self.hist), "--data-kind", "SYNTHETIC_TEST", "--commission-per-lot-side", "3.5", "--no-activate"])
        self.assertIn("COMMISSION_CURRENCY_UNKNOWN", str(cm.exception))

    def test_same_currency_and_old_metadata_unchanged(self):
        self.assertEqual(self._costs(account_currency="USD", quote_currency="USD", spec={"trade_tick_value": 1.0})["commission_price_side"], 3.5 / 100.0)
        self.assertEqual(self._costs()["commission_price_side"], 3.5 / 100.0)                 # export without the currencies: as before


# ===================================================================================================== chunk_40#9 session_check BTC
class TestSessionCheckInstrument(unittest.TestCase):
    def test_btc_weekend_is_not_assumed_closed(self):
        from gold_candles_runtime import worker
        fri = "2026-10-16T21:30:00Z"
        with _EnvGuard():
            os.environ.pop("MQ_INSTRUMENT", None)
            self.assertEqual(worker.session_check(fri, 30), "BLOCKED_SESSION_BREAK")          # gold: unchanged
            self.assertEqual(worker.session_check(fri, 30, "BTC"), "NOT_VERIFIED_BROKER_SESSIONS")
            os.environ["MQ_INSTRUMENT"] = "BTC"
            self.assertEqual(worker.session_check(fri, 30), "NOT_VERIFIED_BROKER_SESSIONS")
            self.assertEqual(worker.session_check(fri, 30, "XAUUSD"), "BLOCKED_SESSION_BREAK")


# ===================================================================================================== chunk_41#2 Kronos engine (selftest)
class _Rope:
    def __init__(self):
        self.seq_len_cached = self.cos_cached = self.sin_cached = None


class _KMod:
    def __init__(self, dev):
        self.dev, self.rope = dev, _Rope()

    def to(self, dev):
        self.dev = dev                         # like nn.Module.to(): parameters / buffers move, the RoPE cache attributes do not
        return self

    def modules(self):
        return [self, self.rope]

    def run(self, seq_len):
        r = self.rope
        if r.seq_len_cached is not None and r.seq_len_cached == seq_len and r.cos_cached[1] != self.dev:
            raise RuntimeError(f"Expected all tensors to be on the same device, but found {self.dev} and {r.cos_cached[1]}")
        if seq_len != r.seq_len_cached:
            r.seq_len_cached, r.cos_cached, r.sin_cached = seq_len, ("cos", self.dev), ("sin", self.dev)


class _KPred:
    def __init__(self, dev="cuda:0", fail=()):
        self.device, self.model, self.tokenizer, self.fail = dev, _KMod(dev), _KMod(dev), set(fail)

    def _out(self, n, pred_len):
        for m in (self.tokenizer, self.model):
            m.run(n)
        return pd.DataFrame({k: np.full(pred_len, 100.0) for k in ("open", "high", "low", "close", "volume", "amount")})

    def predict(self, df, x_timestamp, y_timestamp, pred_len, **kw):
        if str(self.device).startswith("cuda") and "predict" in self.fail:
            self.model.run(len(df))
            raise RuntimeError("CUDA error: an illegal memory access was encountered")
        return self._out(len(df), pred_len)

    def predict_batch(self, dfs, xs, ys, pred_len, **kw):
        if str(self.device).startswith("cuda") and "predict_batch" in self.fail:
            self.model.run(len(dfs[0]))
            raise RuntimeError("CUDA out of memory")
        return [self._out(len(d), pred_len) for d in dfs]


def _fake_torch():
    t = types.ModuleType("torch")
    t.manual_seed = lambda s: None
    t.inference_mode = contextlib.nullcontext
    return t


def _kronos_req(n=400, h=12, paths=0):
    t0 = datetime(2026, 1, 5, tzinfo=UTC)
    ts = [str(t0 + timedelta(minutes=5 * i)) for i in range(n + h)]
    c = list(2000 + np.cumsum(np.random.default_rng(2).normal(0, 1, n)))
    return {"candles": {"t": ts[:n], "open": c, "high": [x + 1 for x in c], "low": [x - 1 for x in c], "close": c}, "y_t": ts[n:],
            "pred_len": h, "seed": 7, "paths": paths}


class TestKronosGpuFallback(unittest.TestCase):
    def _engine(self, pred):
        from kronos_runtime import engine as E
        eng = E.Engine()
        eng.predictor = pred
        eng.info = {"device": pred.device, "device_note": None}
        return eng

    def test_reference_selftest_restores_the_device(self):
        pred = _KPred()
        eng = self._engine(pred)
        info0 = dict(eng.info)
        with mock.patch.dict(sys.modules, {"torch": _fake_torch()}):
            st = eng.selftest(reference=True)
            self.assertIn("parity", st)
            self.assertEqual(st["parity"].get("device"), "cpu")
            self.assertEqual(eng.info, info0)
            self.assertEqual(str(pred.device), "cuda:0")
            self.assertEqual((pred.model.dev, pred.tokenizer.dev), ("cuda:0", "cuda:0"))
            self.assertEqual(eng.predict(_kronos_req())["device"], "cuda:0")   # back on the GPU, caches rebuilt there

    def test_install_verify_reports_the_load_state(self):
        from kronos_runtime import engine as E
        from kronos_runtime import install as I

        class FakeEngine:
            def __init__(self):
                self.info = {}

            def load(self, weights_dir, device="AUTO", verify_files=True):
                self.info = {"device": "cuda:0", "device_note": None, "load_ms": 1.0}
                return self.info

            def selftest(self, reference=False):
                self.info["device"], self.info["device_note"] = "cpu", "GPU_ERROR_FALLBACK_CPU: x"    # an engine that mutates its info
                return {"smoke": {"ok": True, "pred_len": 8, "ms": 1.0}}
        out = io.StringIO()
        with mock.patch.object(I.M, "verify", return_value={"files": []}), mock.patch.object(E, "Engine", FakeEngine), \
                contextlib.redirect_stdout(out):
            rc = I.verify("w", None, False, "AUTO")
        self.assertEqual(rc, 0)
        res = json.loads(next(x for x in out.getvalue().splitlines() if x.startswith("RESULT "))[7:])
        self.assertEqual(res["load"]["device"], "cuda:0")


# ===================================================================================================== chunk_41#8 Kronos download retries
class TestKronosFetchRetries(unittest.TestCase):
    def test_no_retry_message_or_sleep_after_the_last_attempt(self):
        from kronos_runtime import install as I
        said = []
        rep = types.SimpleNamespace(say=lambda msg, step=None, state="RUNNING": said.append(msg))
        with tempfile.TemporaryDirectory() as d, mock.patch("urllib.request.urlopen", side_effect=OSError("connection reset")), \
                mock.patch("time.sleep") as sl:
            with self.assertRaises(OSError):
                I._fetch("https://example.invalid/x", Path(d) / "x.part", 10, "x", rep, 1, retries=4)
        self.assertEqual(sl.call_count, 4)
        self.assertEqual(len(said), 4)
        self.assertFalse(any("5/4" in s for s in said), said)


# ===================================================================================================== sdformer_runtime.train (fake torch)
class _FT:
    """numpy stand-in for the few torch.Tensor operations sdformer_runtime.train performs."""

    def __init__(self, a):
        self.a = np.asarray(a)

    def __getitem__(self, i):
        return _FT(self.a[i])

    def __len__(self):
        return len(self.a)

    def detach(self):
        return self

    def clone(self):
        return _FT(self.a.copy())

    @property
    def dtype(self):
        return types.SimpleNamespace(is_floating_point=bool(np.issubdtype(self.a.dtype, np.floating)))

    def item(self):
        return float(self.a)

    def __float__(self):
        return float(self.a)

    def backward(self):
        return None


class _SdfModel:
    arch = {"fake": "SDF"}
    calls: list = []
    hook = None

    def __init__(self):
        self.w, self.training = 1.0, True

    def parameters(self):
        return [self]

    def train(self):
        self.training = True

    def eval(self):
        self.training = False

    def __call__(self, X, TF):
        _SdfModel.calls.append(("train" if self.training else "eval", len(X)))
        if _SdfModel.hook:
            _SdfModel.hook(len(_SdfModel.calls))
        return _FT(X.a[:, -24:, :] * self.w), None

    def state_dict(self):
        return {"w": _FT(np.array([self.w]))}

    def load_state_dict(self, sd, strict=True):
        self.w = float(sd["w"].a[0])


class _Adam:
    def __init__(self, params, lr):
        self.m, self.n = params[0], 0

    def zero_grad(self):
        return None

    def step(self):
        self.m.w -= 0.001
        self.n += 1

    def state_dict(self):
        return {"n": self.n}

    def load_state_dict(self, s):
        self.n = s["n"]


def _sdf_fakes():
    t = types.ModuleType("torch")
    t.__version__ = "0-fake"
    t.set_num_threads = t.manual_seed = t.set_rng_state = lambda *a, **k: None
    t.tensor = lambda x: _FT(x)
    t.isfinite = lambda x: bool(np.isfinite(x.a).all())
    t.equal = lambda a, b: bool(np.array_equal(a.a, b.a))
    t.no_grad = contextlib.nullcontext
    t.get_rng_state = lambda: _FT(np.zeros(4))

    def save(obj, path):
        with open(path, "wb") as f:
            pickle.dump(obj, f)

    def load(path, map_location=None, weights_only=False):
        with open(path, "rb") as f:
            return pickle.load(f)
    t.save, t.load = save, load
    t.optim = types.SimpleNamespace(Adam=_Adam)

    class MSE:
        def __call__(self, p, y):
            return _FT(np.mean((p.a - y.a) ** 2))
    t.nn = types.SimpleNamespace(MSELoss=MSE, utils=types.SimpleNamespace(clip_grad_norm_=lambda *a, **k: None))
    m = types.ModuleType("sdformer_runtime.model")
    m.SDformerFlow, m.n_params = _SdfModel, (lambda model: 1)
    return {"torch": t, "sdformer_runtime.model": m}


class TestSdformerTrain(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mq_sdf_"))
        self.data = self.tmp / "bars.json"
        self.set_bars(320)                     # 137 samples: 4 training batches of 32 per epoch
        self.out = self.tmp / "sdformer"
        self.out.mkdir()
        self.sig = signal.getsignal(signal.SIGTERM)
        _SdfModel.calls, _SdfModel.hook = [], None

    def tearDown(self):
        import shutil
        signal.signal(signal.SIGTERM, self.sig)
        _SdfModel.calls, _SdfModel.hook = [], None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_bars(self, n):
        rng = np.random.default_rng(9)
        c = 2000 + np.cumsum(rng.normal(0, 1, n))
        t0 = 1_767_225_600
        self.bars = [{"t": t0 + 3600 * i, "o": float(c[i] - 0.3), "h": float(c[i] + 1), "l": float(c[i] - 1), "c": float(c[i]), "tv": 100}
                     for i in range(len(c))]
        self.data.write_text(json.dumps(self.bars), encoding="utf-8")

    def train(self, *args):
        from sdformer_runtime import train as T
        T.STOP["flag"] = False
        buf = io.StringIO()
        with mock.patch.dict(sys.modules, _sdf_fakes()), contextlib.redirect_stdout(buf):
            rc = T.main(["--data", str(self.data), "--out", str(self.out), "--batch", "32", "--minutes", "30"] + list(args))
        line = [x for x in buf.getvalue().splitlines() if x.startswith("RESULT ")][-1]
        return rc, json.loads(line[7:])

    @staticmethod
    def ck(p: Path) -> dict:
        with open(p, "rb") as f:
            return pickle.load(f)

    def test_resume_writes_a_new_version_and_never_the_active_one(self):
        rc, r = self.train("--op", "from_scratch", "--epochs", "2", "--run-id", "SDF-A")
        self.assertEqual((rc, r["run_id"]), (0, "SDF-A"))
        active = self.out / "SDF-A"
        before = {p.name: p.read_bytes() for p in active.iterdir()}
        rc, r = self.train("--op", "resume", "--checkpoint", str(active), "--epochs", "3", "--run-id", "SDF-B")
        self.assertEqual((rc, r["run_id"]), (0, "SDF-B"))
        self.assertEqual(Path(r["dir"]), self.out / "SDF-B")
        self.assertEqual({p.name: p.read_bytes() for p in active.iterdir()}, before)        # the active version is untouched
        st = self.ck(self.out / "SDF-B" / "last.pt")
        self.assertEqual((st["epoch"], st["run_id"], st.get("resumed_from")), (3, "SDF-B", "SDF-A"))
        rc, r = self.train("--op", "resume", "--checkpoint", str(active), "--epochs", "2", "--run-id", "SDF-C")
        self.assertEqual((rc, r["code"]), (1, "NOTHING_TO_DO"))
        self.assertFalse((self.out / "SDF-C").exists())                                    # no empty version folder
        rc, r = self.train("--op", "resume", "--checkpoint", str(active), "--epochs", "4", "--run-id", "SDF-A")
        self.assertEqual((rc, r["code"]), (1, "RESUME_TARGET_IS_SOURCE"))                  # never into the source version
        self.assertEqual({p.name: p.read_bytes() for p in active.iterdir()}, before)

    def test_cancel_inside_an_epoch_keeps_the_last_complete_checkpoint(self):
        cancel = self.tmp / "cancel.flag"
        # epoch 1 = 4 training batches + 1 tail evaluation (calls 1-5); epoch 2 is cancelled after its 2nd batch (call 7)
        _SdfModel.hook = lambda n: cancel.write_text("x") if n == 7 else None
        rc, r = self.train("--op", "from_scratch", "--epochs", "3", "--run-id", "SDF-X", "--cancel-file", str(cancel))
        self.assertEqual(r["code"], "CANCELLED")
        st = self.ck(self.out / "SDF-X" / "last.pt")
        self.assertEqual(st["epoch"], 1)
        self.assertEqual([h["epoch"] for h in st["history"]], [1])
        self.assertEqual(r["epochs_done"], 1)

    def test_trained_until_and_validation_embargo(self):
        from sdformer_runtime import data as D
        self.set_bars(600)
        rc, r = self.train("--op", "from_scratch", "--epochs", "1", "--run-id", "SDF-T")
        self.assertEqual(rc, 0)
        X, Y, T, idx = D.samples(self.bars)
        n_tr = int(len(X) * 0.85)
        st = self.ck(self.out / "SDF-T" / "last.pt")
        self.assertEqual(st["trained_until"], float(self.bars[idx[n_tr - 1] + D.FORECAST]["t"]))    # last TARGET bar seen in training
        val = [j for j in range(n_tr, len(X)) if idx[j] - idx[n_tr - 1] > D.FORECAST]
        self.assertGreater(len(val), 0)
        self.assertEqual([n for kind, n in _SdfModel.calls if kind == "eval"], [len(val)])          # tail after the embargo only
        # a tail shorter than the embargo has no validation loss (it was computed on samples sharing the training targets)
        self.set_bars(320)
        _SdfModel.calls = []
        rc, r = self.train("--op", "from_scratch", "--epochs", "1", "--run-id", "SDF-T2")
        self.assertEqual(rc, 0)
        self.assertIsNone(r["history"][0]["val_tail_loss"])
        self.assertEqual([n for kind, n in _SdfModel.calls if kind == "eval"], [])


# ===================================================================================================== small findings
class TestSmallFindings(unittest.TestCase):
    def test_nlp_missing_checkpoint(self):
        from deep_runtime import nlp
        for req in ({"texts": ["x"]}, {"checkpoint": "", "texts": ["x"]}, {"checkpoint": None, "texts": ["x"]}):
            self.assertEqual(nlp.predict(req), {"ok": False, "error": "CHECKPOINT_NOT_FOUND"})

    def test_reference_cli_brand(self):
        from gold_candles import cli
        d = cli.build_parser().description
        self.assertIn("Apollo23", d)
        self.assertNotIn("MasterQUO", d)


class TestValidateCli(_RegistryCase):
    def test_unknown_run_id_is_a_clear_error(self):
        from gold_candles_runtime import validate
        from gold_candles_runtime.common import forecast_dir, make_config
        self.write_reg({"schema": "masterquo-forecast-registry-1", "active": None, "history": [],
                        "runs": {"R1": _gc_entry(forecast_dir(), "R1", make_config("XAUUSD-", 0.01).contract_hash())}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = validate.main(["--run-id", "NOPE"])
        self.assertEqual(rc, 3)
        self.assertIn("NOPE", out.getvalue())

    def test_relocated_project_folder(self):
        from gold_candles_runtime import validate
        from gold_candles_runtime.common import forecast_dir, make_config
        old = Path(self.td.dir) / "moved_from" / "data" / "forecast"
        root = forecast_dir()
        self.write_reg({"schema": "masterquo-forecast-registry-1", "active": "R1", "history": [],
                        "runs": {"R1": _gc_entry(root, "R1", make_config("XAUUSD-", 0.01).contract_hash(), base=old)}})
        with contextlib.redirect_stdout(io.StringIO()):
            rc = validate.main(["--run-id", "R1"])
        self.assertEqual(rc, 0)
        res = json.loads((root / "runs" / "R1" / "revalidation.json").read_text(encoding="utf-8"))
        self.assertTrue(res["checksum_ok"])
        self.assertTrue(res["contract_hash_matches_current_code"])
        self.assertTrue(res["activatable"])

    def test_btc_contract_through_make_config(self):
        from gold_candles_runtime import validate
        from gold_candles_runtime.common import forecast_dir, make_config
        os.environ["MQ_INSTRUMENT"] = "BTC"
        cur = make_config("BTCUSD", 0.01, "BTC").contract_hash()
        from gold_candles import data as gd
        gd.REGISTERED_SYMBOLS.discard("BTCUSD")                                 # a fresh process knows nothing about the symbol
        self.write_reg({"schema": "masterquo-forecast-registry-1", "active": "RB", "history": [],
                        "runs": {"RB": _gc_entry(forecast_dir(), "RB", cur, symbol="BTCUSD", inst="BTC", grid_step=500.0)}})
        with contextlib.redirect_stdout(io.StringIO()):
            rc = validate.main(["--instrument", "BTC", "--run-id", "RB"])
        self.assertEqual(rc, 0)
        res = json.loads((forecast_dir() / "runs" / "RB" / "revalidation.json").read_text(encoding="utf-8"))
        self.assertTrue(res["contract_hash_matches_current_code"])


if __name__ == "__main__":
    unittest.main()
