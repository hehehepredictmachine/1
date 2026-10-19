"""PMW-UPD-08 R19 MQ_NEWTONIAN_QUOTES_V2 - T80-T96 on generated quote streams (code behaviour; not a market calibration)."""
import math
import unittest

import numpy as np

import _env  # noqa: F401
from _env import TempData

from masterquo.lab import quotes as Q

T0 = 1_700_000_000_000


def stream(n=3000, seed=1, step=(50, 400), sd=0.02, spread=0.2):
    rng = np.random.default_rng(seed)
    out, tm, b = [], 0, 2000.0
    for i in range(n):
        tm += int(rng.integers(*step))
        b = round(b + rng.normal(0, sd), 2)
        out.append({"t_ms": T0 + tm, "bid": b, "ask": round(b + spread, 2)})
    return out


class TestKinematics(unittest.TestCase):
    def test_t80_quadratic_three_scales(self):
        rng = np.random.default_rng(1)
        t = np.cumsum(rng.uniform(0.05, 0.4, 2500))
        for N in Q.SCALES:
            y = 2000 + 0.03 * (t - t[-1]) - 0.0002 * (t - t[-1]) ** 2
            f = Q.fit_side(list(t), list(y), N, 0.01, 0.01)
            self.assertAlmostEqual(f["velocity"], 0.03, places=6)
            self.assertAlmostEqual(f["acceleration"], -0.0004, places=7)
            self.assertAlmostEqual(f["velocity_points_s"], 3.0, places=4)
            self.assertAlmostEqual(f["n_eff"], N, delta=0.05 * N)

    def test_t81_side_separation(self):
        eng = Q.QuoteEngine("X", 0.01, 0.01)
        eng.ingest([{"t_ms": T0 + 10 * i, "bid": 2000.0, "ask": 2000.2 + 0.01 * i} for i in range(50)])
        self.assertEqual(eng.sides["BID"].updates, 0)
        self.assertGreater(eng.sides["ASK"].updates, 40)

    def test_t82_t83_equal_times_and_order(self):
        f = Q.fit_side([1.0] * 50, list(np.linspace(1, 2, 50)), 16, 0.01, 0.01)
        self.assertNotEqual(f["status"], "OK")
        s = Q.Side("BID")
        for t, p in ((1000, 1.0), (1000, 2.0), (1000, 1.0), (2000, 3.0), (3000, 4.0)):
            s.push(t, p, 0, Q.CFG)
        self.assertEqual(s.y, [1.0, 3.0])                         # last price of the 1000-ms bucket in source order (A->B->A)
        self.assertEqual(s.t, [1.0, 2.0])                         # no invented ms
        eng = Q.QuoteEngine("X", 0.01, 0.01)
        eng.ingest([{"t_ms": T0 + 1000 * i, "bid": 2000 + 0.01 * (i % 7), "ask": 2000.3 + 0.01 * (i % 7)} for i in range(250)])
        self.assertEqual(eng.clock["mode"], "COARSE_SECONDS")

    def test_t84_kish_from_weights(self):
        rho = 63 / 65
        w = rho ** np.arange(100, dtype=float)[::-1]
        self.assertAlmostEqual(Q.kish(w), w.sum() ** 2 / (w * w).sum())
        t1 = np.cumsum(np.full(1000, 0.1))
        t2 = np.cumsum(np.full(1000, 1.0))
        y = list(2000 + 0.001 * np.arange(1000))
        a, b = Q.fit_side(list(t1), y, 64, 0.01, 0.01), Q.fit_side(list(t2), y, 64, 0.01, 0.01)
        self.assertAlmostEqual(a["n_eff"], b["n_eff"])
        self.assertAlmostEqual(b["span_s"] / a["span_s"], 10.0, places=3)

    def test_t85_quality_flags(self):
        eng = Q.QuoteEngine("X", 0.01, 0.01)
        eng.ingest([{"t_ms": T0, "bid": 2000.5, "ask": 2000.0}])
        self.assertIn("CROSSED_QUOTE", eng.flags)
        s = stream(400)
        eng.ingest(s)
        snap = eng.snapshot(s[-1]["t_ms"] + 60_000)                # 60 s without updates -> stale sides
        self.assertTrue(all(f["status"] in ("STALE_SIDE", "RANK_OR_SPAN_TOO_SMALL") for f in snap["sides"]["BID"].values()))

    def test_t86_rw_suffix_sums(self):
        rng = np.random.default_rng(2)
        t = np.cumsum(rng.uniform(0.1, 0.5, 300))
        y = 2000 + np.cumsum(rng.normal(0, 0.02, 300))
        f = Q.fit_side(list(t), list(np.round(y, 2)), 64, 0.01, 0.01)
        H, U, dt = f["_H"], f["_U"], f["_dt"]
        tt = t[-H.shape[1]:]
        K = np.minimum.outer(tt, tt) - tt[0]
        np.testing.assert_allclose(H @ K @ H.T, (U * dt[None, :]) @ U.T, atol=1e-9)
        fv = Q.forecast_variance(f, 3.0)
        x = np.array([1, 3.0 / f["span_s"], 0.5 * (3.0 / f["span_s"]) ** 2])
        naive = f["q"] * 3.0 + x @ (f["q"] * H @ K @ H.T + f["nu2"] * H @ H.T) @ x
        self.assertGreater(fv["v_rw"], 0)
        self.assertNotAlmostEqual(fv["v_rw"], naive, places=12)   # history-target covariance is included (not the naive form)

    def test_t87_simulated_rw_band(self):
        rng = np.random.default_rng(5)
        errs = []
        for k in range(60):
            t = np.cumsum(rng.uniform(0.2, 0.6, 400))
            x = 2000 + np.cumsum(rng.normal(0, 0.01, 400 + 20))
            y = np.round(x, 2)
            f = Q.fit_side(list(t), list(y[:400]), 64, 0.01, 0.01)
            if f["status"] != "OK":
                continue
            h = 4.0
            j = 400 + int(round(h / 0.4)) - 1
            fv = Q.forecast_variance(f, h)
            errs.append((y[j] - fv["price"]) / fv["se_model"])
        self.assertTrue(errs)
        self.assertLess(np.mean(np.abs(errs)), 5.0)               # code check only - not an empirical market calibration

    def test_t88_turning_time_unstable(self):
        t = np.cumsum(np.full(300, 0.2))
        y = 2000 + 0.01 * (t - t[-1])                               # a = 0
        f = Q.fit_side(list(t), list(y), 64, 0.01, 0.01)
        self.assertEqual(f["turning_status"], "UNSTABLE_TURN_TIME")
        self.assertIsNone(f["turning_time_s"])

    def test_t89_spread_direct(self):
        t = list(np.arange(200) * 0.5)
        sp = Q.spread_model(t, [0.2] * 200)
        self.assertAlmostEqual(sp["level"], 0.2)
        self.assertIsNone(sp["efficiency"])                         # 0 / 0 -> null

    def test_t90_phase_priority(self):
        def side(zv, v, za=0.0, a=0.0, st="OK"):
            return {"status": st, "z_v": zv, "velocity": v, "z_a": za, "acceleration": a}
        bid = {256: side(3, 1, 3, 1), 16: side(-3, -1)}
        ask = {256: side(3, 1, 3, 1), 16: side(-3, -1)}
        self.assertEqual(Q.classify_phase(bid, ask, {}), "RETRACEMENT")          # not hidden by EXPANSION
        bid[16], ask[16] = side(0.5, 0.1), side(0.5, 0.1)
        self.assertEqual(Q.classify_phase(bid, ask, {}), "EXPANSION")
        self.assertEqual(Q.classify_phase({256: side(0.2, 0), 16: side(0, 0)}, {256: side(-0.3, 0), 16: side(0, 0)}, {}), "CONSOLIDATION")
        self.assertEqual(Q.classify_phase({256: side(3, 1)}, {256: side(-3, -1)}, {}), "STRESSED")
        self.assertEqual(Q.classify_phase({256: side(3, 1, st="PRELIMINARY")}, {256: side(3, 1)}, {}), "WARMING")
        eng = Q.QuoteEngine("X", 0.01, 0.01)
        eng._phase_update("EXPANSION", 0.0)
        self.assertEqual(eng.phase, "WARMING")                     # hysteresis: 3 updates and >= 1 s
        eng._phase_update("EXPANSION", 0.5)
        eng._phase_update("EXPANSION", 1.2)
        self.assertEqual(eng.phase, "EXPANSION")

    def test_t91_t92_t93_scoring(self):
        eng = Q.QuoteEngine("X", 0.01, 0.01)
        s = stream(2500)
        eng.ingest(s[:2000])
        now = s[1999]["t_ms"]
        fcs = eng.emit(eng.snapshot(now), now)
        self.assertTrue(fcs)
        self.assertEqual(eng.emit(eng.snapshot(now + 10), now + 10), [])        # primary stream: no overlap
        far = now + 8_990_000                                                   # nearest quote 8990 s later
        eng.ingest([{"t_ms": far, "bid": 2001.0, "ask": 2001.2}])
        done = eng.score(far)
        self.assertTrue(all(d["status"] == "UNSCORED_GAP" for d in done))
        self.assertEqual(eng.score(far), [])                                     # scored once
        e2 = Q.QuoteEngine("X", 0.01, 0.01)
        flat = [{"t_ms": T0 + 100 * i, "bid": 2000.0 + 0.01 * (i % 2), "ask": 2000.2 + 0.01 * (i % 2)} for i in range(3000)]
        e2.matured = [{"side": "BID", "scale": 16, "status": "SCORED", "error": 0.01, "persistence_error": 0.0, "outcome": 2000.0, "last_quote": 2000.0,
                       "price": 1999.99, "band": {"status": "MODEL_BAND_UNCALIBRATED"}}] * 5
        self.assertIsNone(e2.scoreboard()["BID_16"]["r2_vs_persistence"])       # constant target -> null, not 100 %
        self.assertTrue(flat)

    def test_t94_band_uncalibrated(self):
        eng = Q.QuoteEngine("X", 0.01, 0.01)
        s = stream(2200)
        eng.ingest(s)
        fcs = eng.emit(eng.snapshot(s[-1]["t_ms"]), s[-1]["t_ms"])
        self.assertTrue(all(f["band"]["status"] == "MODEL_BAND_UNCALIBRATED" for f in fcs))

    def test_t96_archive_replay_features(self):
        td = TempData()
        try:
            from masterquo.lab import tick_store as TS
            s = stream(6000, step=(200, 900))
            TS.save_chunk("XAUUSD", s[:3000], "SYNTHETIC_TEST", "AS_PROVIDED", False)
            TS.save_chunk("XAUUSD", s[3000:], "SYNTHETIC_TEST", "AS_PROVIDED", False)
            r = TS.replay("XAUUSD", 0.01, 0.01)
            self.assertEqual(r["status"], "OK")
            self.assertEqual(r["ticks"], 6000)
            self.assertGreater(r["rows"], 10)
            self.assertIn("scoreboard_dev", r)
            self.assertEqual(TS.latest_replay("XAUUSD").name, r["replay_id"])
            f = TS.root("XAUUSD") / TS._index("XAUUSD")[0]["file"]
            f.write_bytes(f.read_bytes() + b"x")
            with self.assertRaises(ValueError):
                TS.load("XAUUSD")
        finally:
            td.close()


if __name__ == "__main__":
    unittest.main()
