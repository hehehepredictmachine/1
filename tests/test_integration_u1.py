"""1.33 U1 - base repairs: prediction contract PMW-PRED-2 (AUD 3.1 reproductions), M3 timeframe end to end, real DXY availability in the
legacy ML features (MQ-FEAT-1.2.0) with the compatibility adapter for older models."""
from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone

import _env  # noqa: F401
from masterquo.modelhub import contract as C

BASE = dict(instrument="XAUUSD", symbol="XAUUSD-", timeframe="M5", model_name="t", model_version="1", task="T", unit="probability",
            state="READY", data_time="2026-01-01T00:00:00Z")


def mk(**kw):
    return C.make(**{**BASE, **kw})


class TestContractV2(unittest.TestCase):
    def test_aud_3_1_reproductions(self):
        """AUD 3.1: NaN, True, negative horizon and NaN in a regression were accepted by PMW-PRED-1; all are refused now."""
        bad = [dict(task_type="EVENT_PROBABILITY", horizon_bars=1, result=float("nan")),
               dict(task_type="EVENT_PROBABILITY", horizon_bars=1, result=True),
               dict(task_type="EVENT_PROBABILITY", horizon_bars=-1, result=0.5),
               dict(task_type="REGRESSION", horizon_bars=1, result={"pred_close": float("nan")}, unit="price"),
               dict(task_type="EVENT_PROBABILITY", horizon_bars=1, result=float("inf"))]
        for c in bad:
            with self.assertRaises(C.ContractError, msg=str(c)):
                mk(**c)
        self.assertEqual(mk(task_type="EVENT_PROBABILITY", horizon_bars=1, result=0.5)["result"], 0.5)
        self.assertEqual(mk(task_type="EVENT_PROBABILITY", horizon_bars=1, result=0)["result"], 0)        # 0 is a value, not a missing one

    def test_types_shapes_horizons(self):
        for c in (dict(task_type="CLASS_PROBABILITIES", horizon_bars=1, result={}),
                  dict(task_type="CLASS_PROBABILITIES", horizon_bars=1, result={"UP": True, "DOWN": False}),
                  dict(task_type="CLASS_PROBABILITIES", horizon_bars=1, result={"UP": 0.7, "DOWN": 0.2}),
                  dict(task_type="CLASS_PROBABILITIES", horizon_bars=True, result={"UP": 0.5, "DOWN": 0.5}),
                  dict(task_type="CLASS_PROBABILITIES", horizon_bars=1.5, result={"UP": 0.5, "DOWN": 0.5}),
                  dict(task_type="REGRESSION", horizon_bars=None, result={"x": 1.0}, unit="price"),
                  dict(task_type="REGRESSION", horizon_bars=1, result={"lo": 2.0, "hi": 1.0, "mean": 1.5}, unit="price"),
                  dict(task_type="REGRESSION", horizon_bars=1, result={"direction": "UP"}, unit="price"),
                  dict(task_type="VOLATILITY", horizon_bars=1, result={"sigma": 0.01}, unit="sigma_return"),
                  dict(task_type="VOLATILITY", horizon_bars=1, result={"sigma": -0.01, "scale": "decimal"}, unit="sigma_return"),
                  dict(task_type="SCORE", horizon_bars=None, result=55, unit="probability"),
                  dict(task_type="NLP_SENTIMENT", horizon_bars=None, result={"sentiment": {"pos": 0.9}}, unit="sentiment"),
                  dict(task_type="RL_ACTION", horizon_bars=None, result={"action": 1}, unit="action")):
            with self.assertRaises(C.ContractError, msg=str(c)):
                mk(**c)
        # legal: Kronos-like regression with text metadata, horizon in seconds, a state measurement without horizon
        mk(task_type="REGRESSION", horizon_bars=12, unit="price", result={"pred_close": 2650.1, "direction": "UP", "forecast_id": "f1"})
        mk(task_type="EVENT_PROBABILITY", horizon_bars=None, horizon_seconds=30, result=0.4)
        mk(task_type="MICROSTRUCTURE", horizon_bars=None, unit="ratio", result={"imbalance": 0.2, "ofi": None})
        mk(task_type="VOLATILITY", horizon_bars=5, unit="sigma_return", result={"sigma": 0.002, "variance": 4e-6, "scale": "decimal"})
        mk(task_type="NLP_SENTIMENT", horizon_bars=None, unit="sentiment", result={"sentiment": {"neg": 0.1, "neu": 0.2, "pos": 0.7}})
        mk(task_type="RL_ACTION", horizon_bars=None, unit="action", result={"action": "FLAT", "action_probabilities": {"SHORT": 0.2, "FLAT": 0.5, "LONG": 0.3}})

    def test_not_ready_has_no_value_and_a_reason(self):
        p = mk(task_type="EVENT_PROBABILITY", horizon_bars=1, state="BLOCKED_DATA", result=0.4, unavailable_reason="brak danych L2")
        self.assertIsNone(p["result"])
        with self.assertRaises(C.ContractError):
            mk(task_type="EVENT_PROBABILITY", horizon_bars=1, state="ERROR", unavailable_reason=None)
        with self.assertRaises(C.ContractError):
            mk(task_type="EVENT_PROBABILITY", horizon_bars=1, result=0.4, data_kind="DEMO")
        with self.assertRaises(C.ContractError):
            mk(task_type="EVENT_PROBABILITY", horizon_bars=1, result=0.4, freshness_s=float("nan"))


class TestM3(unittest.TestCase):
    def test_registry_and_fake_terminal(self):
        from masterquo.mt5 import fake
        from masterquo.timeutil import TF_REGISTRY, TIMEFRAMES
        self.assertEqual(TF_REGISTRY["M3"]["seconds"], 180)
        self.assertEqual(TIMEFRAMES[:3], ("M1", "M3", "M5"))
        m = fake.FakeMT5(symbol="XAUUSD-", seed=1)
        m.initialize()
        r = m.copy_rates_from_pos("XAUUSD-", fake.TIMEFRAME_M3, 0, 50)
        self.assertEqual(len(r), 50)
        self.assertTrue(all(int(t) % 180 == 0 for t in r["time"]))

    def test_resample_marks_incomplete_triples(self):
        from masterquo.mt5.bridge import RESAMPLE_FROM, Bar, MarketBridge
        self.assertEqual(RESAMPLE_FROM["M3"], ("M1", 3))
        m1 = [Bar(t, 1, 2, 0.5, 1.5, 1, 0, 1) for t in (0, 60, 120, 180, 300)]   # 240 missing -> second bucket has 2 parts
        br = MarketBridge.__new__(MarketBridge)
        br._fetch = lambda sym, tf, n: m1
        out = MarketBridge._resample(br, "X", "M3", 10)
        self.assertEqual([(b.t_raw, b.parts, b.complete) for b in out], [(0, 3, True), (180, 2, False)])

    def test_trainhub_and_kronos_accept_m3(self):
        from masterquo.kronos.settings import TF_ALL
        from masterquo.marketdata.export import EXPORT_TFS
        from masterquo.trainhub.features import HTF_OF, TF_S
        self.assertIn("M3", TF_ALL)
        self.assertIn("M3", EXPORT_TFS)
        self.assertEqual(TF_S["M3"], 180)
        self.assertEqual(HTF_OF["M3"], ("M15", "M30"))


class TestDXYFeature(unittest.TestCase):
    def view(self, ctx):
        from masterquo.strategies.base import MarketView
        return MarketView(symbol="XAUUSD-", as_of="2026-01-01T12:00:00Z", tfs={}, bid=None, ask=None, point=0.01, context=ctx)

    def test_real_availability(self):
        from masterquo.ml import features as fe
        asof = datetime(2026, 1, 6, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(fe.FEATURE_SCHEMA_VERSION, "MQ-FEAT-1.2.0")
        self.assertEqual(fe.dxy_missing(self.view({}), asof), 1.0)
        self.assertEqual(fe.dxy_missing(self.view({"dxy": {"status": "OK", "last_available_at": "2026-01-06T11:00:05Z"}}), asof), 0.0)
        old = (asof - timedelta(hours=5)).isoformat()
        self.assertEqual(fe.dxy_missing(self.view({"dxy": {"status": "OK", "last_available_at": old}}), asof), 1.0)      # stale
        fut = (asof + timedelta(minutes=1)).isoformat()
        self.assertEqual(fe.dxy_missing(self.view({"dxy": {"status": "OK", "last_available_at": fut}}), asof), 1.0)      # not known yet
        self.assertEqual(fe.dxy_missing(self.view({"dxy": {"status": "SYMBOL_NOT_FOUND"}}), asof), 1.0)

    def test_legacy_models_keep_training_semantics(self):
        import numpy as np
        from masterquo.ml.models import Bundle
        seen = []

        class Prep:
            def transform(self, rows):
                seen.append([r["dxy_missing"] for r in rows])
                return np.zeros((len(rows), 1))

        class M:
            def predict_proba(self, X):
                return np.tile([0.4, 0.6], (len(X), 1))
        for sv, want in (("MQ-FEAT-1.1.0", 1.0), ("MQ-FEAT-1.2.0", 0.0)):
            Bundle("DT", M(), Prep(), None, {"feature_schema_version": sv}).raw([{"dxy_missing": 0.0}])
            self.assertEqual(seen[-1], [want])
        self.assertTrue(math.isclose(0.6, 0.6))


if __name__ == "__main__":
    unittest.main()
