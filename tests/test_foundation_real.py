"""REAL-WEIGHTS category (1.37): Chronos-2 and FinCast on the official checkpoints, inside their own environments.

Run in the model environment with the installed weights, e.g.
  MQ_TSFM_WEIGHTS_ROOT=<data>/tsfm/models PYTHONPATH=backend .venv_chronos2/bin/python -m unittest tests/test_foundation_real.py
  MQ_TSFM_WEIGHTS_ROOT=<data>/tsfm/models PYTHONPATH=backend .venv_fincast/bin/python  -m unittest tests/test_foundation_real.py
Skipped (never faked) without the environment / weights. Checks: identity of the loaded checkpoint (pinned revision + parameter count),
parity of the bot adapter with a direct call of the official API, determinism, no look-ahead (data after the forecast origin cannot change
it), input / contract errors (NaN, too short, unsupported quantile / profile / timeframe), quantile ordering reported. These tests prove
real inference, NOT forecasting quality (that is the walk-forward report)."""
from __future__ import annotations

import importlib.util
import math
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
ROOT = os.environ.get("MQ_TSFM_WEIGHTS_ROOT")
HAS_TORCH = importlib.util.find_spec("torch") is not None
HAS_CHRONOS = HAS_TORCH and importlib.util.find_spec("chronos") is not None
HAS_FINCAST = HAS_TORCH and importlib.util.find_spec("einx") is not None and importlib.util.find_spec("colt5_attention") is not None


def series(n=900, seed=7):
    import numpy as np
    rng = np.random.default_rng(seed)
    return [float(x) for x in np.round(2650 + np.cumsum(rng.normal(0, 1.5, n)), 2)]


class _Real:
    mid = ""
    eng = None

    @classmethod
    def setUpClass(cls):
        from tsfm_runtime import engines as E
        from tsfm_runtime import manifest as M
        assert not (M.read(ROOT, cls.mid) or {}).get("fixture"), "to są wagi testowe, nie oficjalne"
        cls.E = E
        cls.eng = E.make(cls.mid)
        cls.info = cls.eng.load(ROOT, device="CPU", threads=max(1, (os.cpu_count() or 2) - 1))

    def req(self, close, **kw):
        return {"close": close, "pred_len": 12, "context_len": 512, "profile": "CLOSE_V1", "quantiles": [0.1, 0.5, 0.9], "freq_tf": "M5", **kw}

    def test_identity_and_parity(self):
        from tsfm_runtime import lock as L
        pin = L.model(self.mid)
        self.assertEqual((self.info["repo"], self.info["revision"], self.info["params"]), (pin["repo"], pin["revision"], pin["params_measured"]))
        st = self.eng.selftest()
        print(f"\n[real {self.mid}] load {self.info['load_ms']} ms, rss {self.info.get('rss_mb')} MB, smoke {st['smoke']['ms']} ms, parity {st['parity']}")
        self.assertTrue(st["smoke"]["ok"])
        self.assertEqual(st["parity"]["status"], "PASS")

    def test_deterministic_and_no_lookahead(self):
        s = series()
        a = self.eng.predict(self.req(s[:600]))
        b = self.eng.predict(self.req(s[:600]))
        self.assertEqual(a["point"], b["point"])                              # deterministic (no sampling in these models)
        s2 = list(s)
        for i in range(600, len(s2)):
            s2[i] += 500.0                                                     # the "future" is completely different
        c = self.eng.predict(self.req(s2[:600]))
        self.assertEqual(a["point"], c["point"])                              # only data up to the origin enters the forecast
        self.assertTrue(all(math.isfinite(x) for x in a["point"]) and len(a["point"]) == 12)
        q = a["quantiles"]["values"]
        self.assertEqual(sorted(q), ["0.1", "0.5", "0.9"])
        self.assertIsInstance(a["quantiles"]["crossing_steps"], int)          # reported, never repaired

    def test_input_errors(self):
        s = series()
        bad = list(s[:600])
        bad[100] = float("nan")
        for r, code in ((self.req(bad), "NON_FINITE_INPUT"), (self.req(s[:20], context_len=20), "CONFIG"), (self.req(s[:600], pred_len=0), "CONFIG")):
            with self.assertRaises(self.E.EngineError) as cm:
                self.eng.predict(r)
            self.assertEqual(cm.exception.code, code)


@unittest.skipUnless(HAS_CHRONOS and ROOT, "Chronos-2: uruchom w .venv_chronos2 z MQ_TSFM_WEIGHTS_ROOT")
class TestChronos2Real(_Real, unittest.TestCase):
    mid = "chronos2"

    def test_point_is_median_and_covariate_profile(self):
        s = series()
        r = self.eng.predict(self.req(s[:600]))
        self.assertEqual(r["point_kind"], "median")
        self.assertEqual(r["point"], r["quantiles"]["values"]["0.5"])
        cov = {"open": s[:600], "high": [x + 1 for x in s[:600]], "low": [x - 1 for x in s[:600]], "volume": [100.0] * 600}
        r2 = self.eng.predict(self.req(s[:600], profile="CLOSE_OHLCV_PAST_V1", covariates=cov))
        self.assertEqual(r2["profile"], "CLOSE_OHLCV_PAST_V1")
        with self.assertRaises(self.E.EngineError) as cm:                     # missing covariate: never silently another profile
            self.eng.predict(self.req(s[:600], profile="CLOSE_OHLCV_PAST_V1", covariates={k: v for k, v in cov.items() if k != "volume"}))
        self.assertEqual(cm.exception.code, "COVARIATES_MISSING")


@unittest.skipUnless(HAS_FINCAST and ROOT, "FinCast: uruchom w .venv_fincast z MQ_TSFM_WEIGHTS_ROOT")
class TestFinCastReal(_Real, unittest.TestCase):
    mid = "fincast"

    def test_mean_point_quantiles_and_unsupported(self):
        s = series()
        r = self.eng.predict(self.req(s[:600]))
        self.assertEqual(r["point_kind"], "mean")
        self.assertEqual(len(r["median"]), 12)
        for kw, code in (({"quantiles": [0.05, 0.5]}, "QUANTILE_UNSUPPORTED"), ({"profile": "CLOSE_OHLCV_PAST_V1"}, "PROFILE_UNSUPPORTED"),
                         ({"freq_tf": "W1"}, "FREQ_UNSUPPORTED")):
            with self.assertRaises(self.E.EngineError) as cm:
                self.eng.predict(self.req(s[:600], **kw))
            self.assertEqual(cm.exception.code, code)


if __name__ == "__main__":
    unittest.main()
