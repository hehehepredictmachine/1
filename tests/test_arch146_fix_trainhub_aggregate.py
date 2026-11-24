"""arch146 fix group trainhub_aggregate - D10 (trainhub inference: frozen higher-TF features) and D12 (TH_BASELINE as the speaker of a
correlation group in modelhub.aggregate.evidence). Each test fails on c8277f4 and passes after the fix. Synthetic candles only, no MT5, no
registry on disk (dev_skill patched), no HTTP server."""
from __future__ import annotations

import unittest
from unittest import mock

import _env  # noqa: F401
import numpy as np
from masterquo.marketdata.store import iso
from masterquo.trainhub import features as F
from masterquo.trainhub import registry as R

DAY = 86400
COLS = ("time", "open", "high", "low", "close", "tick_volume", "spread")
KEY = "TH_LOGREG_M5_H6"


# ------------------------------------------------------------------ candles
def candles(times: list[int], seed: int = 1, start: float = 2000.0) -> dict:
    rng = np.random.default_rng(seed)
    c = start + np.cumsum(rng.normal(0, 0.5, len(times)))
    o = np.concatenate([[start], c[:-1]])
    return {"time": [int(t) for t in times], "open": o.tolist(), "high": (np.maximum(o, c) + 0.2).tolist(),
            "low": (np.minimum(o, c) - 0.2).tolist(), "close": c.tolist(), "tick_volume": [100.0] * len(times), "spread": [20.0] * len(times)}


def htf(base: dict, htf_s: int, upto: float) -> dict:
    """Higher-TF candles built from the base candles - only periods closed by `upto`."""
    groups: dict[int, list[int]] = {}
    for i, t in enumerate(base["time"]):
        groups.setdefault(t // htf_s * htf_s, []).append(i)
    out = {k: [] for k in COLS}
    for b, ix in sorted(groups.items()):
        if b + htf_s > upto:
            continue
        out["time"].append(b)
        out["open"].append(base["open"][ix[0]])
        out["high"].append(max(base["high"][i] for i in ix))
        out["low"].append(min(base["low"][i] for i in ix))
        out["close"].append(base["close"][ix[-1]])
        out["tick_volume"].append(sum(base["tick_volume"][i] for i in ix))
        out["spread"].append(20.0)
    return out


def m5_set(n_bars: int, htf_upto: float | None = None) -> dict:
    t0 = 1_790_000_000 // 1800 * 1800
    base = candles([t0 + i * 300 for i in range(n_bars)])
    last_close = base["time"][-1] + 300
    lim = last_close if htf_upto is None else min(htf_upto, last_close)
    return {"M5": base, "M15": htf(base, 900, lim), "M30": htf(base, 1800, lim)}


class _Cfg:
    class A:
        broker_symbol = "XAUUSD-"

    def get(self):
        return type("C", (), {"assets": type("As", (), {"mappings": {"XAUUSD": _Cfg.A(), "BTC": _Cfg.A()}})()})()


class Bridge:
    """MarketBridge.symbol_bars / symbol_meta over in-memory columns (closed candles, oldest first, last `n`)."""

    def __init__(self, cols: dict):
        self.cols = cols

    def symbol_bars(self, sym, tf, n):
        c = self.cols[tf]
        return [{"open_utc": iso(c["time"][i]), "o": c["open"][i], "h": c["high"][i], "l": c["low"][i], "c": c["close"][i],
                 "tv": c["tick_volume"][i], "spread": c["spread"][i], "closed": True} for i in range(max(0, len(c["time"]) - n), len(c["time"]))]

    def symbol_meta(self, sym):
        return {"point": 0.01}


class InferenceCase(unittest.TestCase):
    def make(self, cols: dict):
        from masterquo.trainhub.inference import TrainhubInference
        self.bridge = Bridge(cols)
        self.close_t = cols["M5"]["time"][-1] + 300
        self.now = [self.close_t + 5.0]                                          # the base candle is fresh
        inf = TrainhubInference(_Cfg(), self.bridge, clock=lambda: self.now[0])
        conf = {"base_tf": "M5", "horizon": 6, "model_id": "TH_LOGREG", "point": 0.01}
        inf.cache[("XAUUSD", KEY, "v1")] = ({"estimator": None, "temperature": 1.0}, conf, {"names": F.names("M5")})
        p = mock.patch.object(R, "predict_loaded", return_value=np.array([[0.2, 0.3, 0.5]]))
        p.start()
        self.addCleanup(p.stop)
        return inf


# ------------------------------------------------------------------ D10 frozen higher TF -> same rule as training (htf_stale)
class TestTrainhubInferenceHtfStale(InferenceCase):
    def test_frozen_htf_is_not_ready(self):
        cols = m5_set(10 * 288, htf_upto=1_790_000_000 // 1800 * 1800 + 3 * DAY)   # M15/M30 stop a week before the fresh M5 candle
        self.assertTrue(bool(F.htf_stale(cols, "M5")[-1]))                          # training drops exactly this row
        inf = self.make(cols)
        p = inf.predict("XAUUSD", KEY, "v1")
        self.assertNotEqual(p["state"], "READY")                                    # c8277f4: READY on week-old M15/M30 features
        self.assertEqual(p["data_quality"], "DEGRADED")
        self.assertIsNone(p["result"])
        self.assertIn("htf_stale", p["unavailable_reason"])
        self.assertIn("M15", p["unavailable_reason"])
        self.assertNotEqual(inf.predictions("XAUUSD")[0]["state"], "READY")

    def test_fresh_htf_is_ready(self):
        cols = m5_set(10 * 288)
        self.assertFalse(bool(F.htf_stale(cols, "M5")[-1]))
        p = self.make(cols).predict("XAUUSD", KEY, "v1")
        self.assertEqual((p["state"], p["data_quality"]), ("READY", "OK"))
        self.assertEqual(p["result"], {"DOWN": 0.2, "FLAT": 0.3, "UP": 0.5})

    def test_late_htf_candle_is_rechecked_on_the_next_poll(self):
        """The M15/M30 candle closing together with the base candle may come a moment later: the non-READY answer is not cached until
        the next base candle (5 min on M5) - the next poll recomputes and gives READY once the higher TF is complete."""
        full = m5_set(10 * 288)
        late = {k: dict(v) for k, v in full.items()}
        for h in ("M15", "M30"):
            late[h] = {k: v[:-1] for k, v in full[h].items()}                       # the last M15 / M30 candle not delivered yet
        self.assertTrue(bool(F.htf_stale(late, "M5")[-1]))
        inf = self.make(late)
        self.assertNotEqual(inf.predict("XAUUSD", KEY, "v1")["state"], "READY")
        self.bridge.cols = full                                                     # same base candle, higher TF complete now
        self.now[0] += 5.0
        p = inf.predict("XAUUSD", KEY, "v1")
        self.assertEqual((p["state"], p["data_quality"]), ("READY", "OK"))

    def test_session_break_is_not_stale(self):
        """A weekend / session break (no base candle traded in between) is not a frozen higher TF - same as the dataset."""
        t0 = 1_790_000_000 // DAY * DAY
        times = []
        for d in range(4):
            times += [t0 + d * DAY + i * 300 for i in range(288) if not 22 * 12 <= i < 23 * 12]     # daily 1 h break
        base = candles(times)
        last_close = times[-1] + 300
        cols = {"M5": base, "M15": htf(base, 900, last_close), "M30": htf(base, 1800, last_close)}
        self.assertFalse(F.htf_stale(cols, "M5").any())
        p = self.make(cols).predict("XAUUSD", KEY, "v1")
        self.assertEqual(p["state"], "READY")


if __name__ == "__main__":
    unittest.main()
