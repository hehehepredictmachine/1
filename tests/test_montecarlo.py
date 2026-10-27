"""Monte Carlo of price paths (PMW-MC-1): deterministic seed, shapes and bounds, no look-ahead, TP/SL scenarios on Bid/Ask, ambiguous
bars (never guessed), missing / invalid / stale data, load, walk-forward validation with embargo, calibration registry with rollback,
runtime service and API. All market data here is SYNTHETIC."""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import _env
from _env import TempData

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()


def bars(n=1500, drift=0.0, rng_w=0.4, seed=3, spread=12, step=60, wide=False):
    r = np.random.default_rng(seed)
    out, c = [], 2400.0
    for i in range(n):
        o = c
        c = o + drift + r.normal(0, 0.3)
        h = max(o, c) + abs(r.normal(0, rng_w)) + (20 if wide else 0)
        lo = min(o, c) - abs(r.normal(0, rng_w)) - (20 if wide else 0)
        out.append({"open_utc": datetime.fromtimestamp(T0 + i * step, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": h, "l": lo, "c": c,
                    "spread": spread})
    return out


class TestEngine(unittest.TestCase):
    def setUp(self):
        from masterquo.montecarlo import engine as E
        self.E = E
        self.b = bars()
        self.as_of = T0 + len(self.b) * 60

    def plan(self, side="BUY", tp=2.5, sl=3.0, h=60, entry=None):
        last = self.b[-1]["c"]
        e = entry if entry is not None else (last + 0.12 if side == "BUY" else last)
        s = 1 if side == "BUY" else -1
        return self.E.Plan(side, e, e - s * sl, [e + s * tp, e + s * 5.0], h)

    def test_deterministic_seed_and_bounds(self):
        a = self.E.run(self.b, self.as_of, [self.plan()], seed=11)
        b = self.E.run(self.b, self.as_of, [self.plan()], seed=11)
        c = self.E.run(self.b, self.as_of, [self.plan()], seed=12)
        self.assertEqual(a["plans"], b["plans"])
        self.assertNotEqual(a["plans"][0]["levels"][0]["p_tp_before_sl_conservative"], c["plans"][0]["levels"][0]["p_tp_before_sl_conservative"])
        for lv in a["plans"][0]["levels"]:
            self.assertTrue(0 <= lv["p_tp_before_sl_conservative"] <= lv["p_tp_before_sl_optimistic"] <= 1)
            self.assertLessEqual(lv["p_tp_before_sl_conservative"], lv["p_tp_within_h"])
            self.assertGreater(lv["mc_error_95"], 0)
        q = list(a["plans"][0]["end_move_quantiles"].values())
        self.assertEqual(q, sorted(q))
        self.assertEqual(a["probability_kind"], "MODEL_SIMULATED")
        self.assertFalse(a["calibrated"])
        s = a["scenarios"]
        self.assertEqual(s["levels_price"], [2.5, 3.0, 5.0, 7.5, 10.0])
        self.assertEqual(s["p_up_reach"], sorted(s["p_up_reach"], reverse=True))       # farther = rarer
        for k in ("seed", "n_paths", "horizon_bars", "version"):
            self.assertIn(k, a)
        self.assertIn("hash", a["data"])

    def test_no_look_ahead(self):
        future = bars(1600)[1500:]                                               # bars after as_of
        a = self.E.run(self.b, self.as_of, [self.plan()], seed=5)
        b = self.E.run(self.b + [dict(x, c=x["c"] + 50, h=x["h"] + 50) for x in future], self.as_of, [self.plan()], seed=5)
        self.assertEqual(a["plans"], b["plans"])
        self.assertEqual(a["data"]["bars"], b["data"]["bars"])

    def test_trend_and_sides(self):
        up = bars(1500, drift=0.5)
        as_of = T0 + 1500 * 60
        r = self.E.run(up, as_of, [self.plan("BUY", 2.5, 3.0), self.plan("SELL", 2.5, 3.0)], variant="BLOCK")
        buy, sell = r["plans"][0]["levels"][0], r["plans"][1]["levels"][0]
        self.assertGreater(buy["p_tp_before_sl_conservative"], 0.9)
        self.assertLess(sell["p_tp_before_sl_optimistic"], 0.1)

    def test_spread_makes_sell_tp_harder(self):
        narrow, wide = bars(spread=0), bars(spread=300)                          # 0.00 vs 3.00 USD spread (point 0.01)
        a = self.E.run(narrow, self.as_of, [self.plan("SELL")], seed=4)["plans"][0]["levels"][0]["p_tp_before_sl_conservative"]
        b = self.E.run(wide, self.as_of, [self.plan("SELL")], seed=4)["plans"][0]["levels"][0]["p_tp_before_sl_conservative"]
        self.assertLess(b, a)

    def test_ambiguous_bars_are_not_guessed(self):
        w = bars(wide=True)                                                       # every bar spans more than TP and SL
        lv = self.E.run(w, self.as_of, [self.plan("BUY", 2.5, 3.0)])["plans"][0]["levels"][0]
        self.assertGreater(lv["p_ambiguous_same_bar"], 0.9)
        self.assertLess(lv["p_tp_before_sl_conservative"], 0.1)
        self.assertGreater(lv["p_tp_before_sl_optimistic"], 0.9)

    def test_missing_invalid_stale_and_synthetic(self):
        r = self.E.run(self.b[:100], T0 + 100 * 60, [self.plan()])
        self.assertEqual(r["status"], "INSUFFICIENT_DATA")
        bad = list(self.b)
        bad[700] = dict(bad[700], h=bad[700]["l"] - 1)
        r = self.E.run(bad, self.as_of + 3 * 86400 if datetime.fromtimestamp(self.as_of + 3 * 86400, timezone.utc).weekday() < 5 else self.as_of + 86400,
                       [self.plan()], synthetic=True)
        self.assertEqual(r["data"]["dropped_invalid"], 1)
        self.assertIn("STALE_LAST_BAR", r["data"]["flags"])
        self.assertIn("SYNTETYCZNE", r["warning"])
        self.assertEqual(r["data"]["kind"], "SYNTHETIC_TEST")

    def test_variants_and_load(self):
        for v in self.E.VARIANTS:
            r = self.E.run(self.b, self.as_of, [self.plan()], variant=v)
            self.assertEqual(r["status"], "OK", v)
            self.assertEqual(r["sim"]["variant"], v)
        big = bars(6000)
        t = time.perf_counter()
        r = self.E.run(big, T0 + 6000 * 60, [self.plan(h=240)], n_paths=5000, horizon=240, variant="REGIME")
        self.assertLess(time.perf_counter() - t, 20)
        self.assertEqual(r["plans"][0]["n_paths"], 5000)


class TestValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = TempData()
        from masterquo.mt5.fake import FakeMT5
        sys.modules["MetaTrader5"] = FakeMT5()
        from masterquo.forecast.export import export_candles
        cls.ds = Path(tempfile.mkdtemp(prefix="mq mc "))
        assert export_candles(1, str(cls.ds), "AUTO", ("M1",), "training", "XAUUSD", "XAUUSD-", tick_days=0.5) == 0
        sys.modules.pop("MetaTrader5", None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ds, ignore_errors=True)
        cls.td.close()

    def test_walk_forward_embargo_baseline_and_registry(self):
        from masterquo.montecarlo import validate as V
        rep = V.validate(self.ds, max_points=160, n_paths=200, log=lambda m: None)
        self.assertEqual(rep["status"], "DONE", rep.get("reason"))
        self.assertEqual(rep["verdict"], "TEST_TECHNICZNY")                      # synthetic data: never an edge claim
        self.assertIn(rep["chosen_variant"], ("IID", "BLOCK", "REGIME"))
        self.assertTrue(rep["ticks_available"])
        for k in ("brier", "logloss"):
            self.assertIn(k, rep["test"]["calibrated"])
            self.assertIn(k, rep["test"]["base"])
        lo, hi = rep["brier_diff_calibrated_minus_base_ci95"]
        self.assertLessEqual(lo, hi)
        saved = V.save("XAUUSD", rep)
        self.assertFalse(saved["activated"])                                     # synthetic -> research only
        self.assertIsNone(V.active_calibrator("XAUUSD"))
        # activation and rollback only for the user's data with an out-of-sample edge (report crafted for the registry logic)
        real = dict(rep, data_kind="REAL_USER_DATA", verdict="PRZEWAGA_NAD_BAZOWYM")
        a = V.save("XAUUSD", real)
        b = V.save("XAUUSD", real)
        self.assertTrue(a["activated"] and b["activated"])
        self.assertEqual(V.active_calibrator("XAUUSD")["run_id"], b["run_id"])
        V.rollback("XAUUSD")
        self.assertEqual(V.active_calibrator("XAUUSD")["run_id"], a["run_id"])
        cal = V.active_calibrator("XAUUSD")
        self.assertTrue(0 <= V.apply_calibrator(cal, 0.3) <= 1)

    def test_embargo_and_no_future_in_points(self):
        from masterquo.montecarlo import validate as V
        b, _ = V.load_dataset(self.ds)
        H = 60
        y, amb = V.outcomes(b, H, {"side": "BUY", "tp": 2.5, "sl": 3.0}, None, 60, 0.12)
        i = 4000
        base = V.climatology(y, i, H, 3000)
        y2 = y.copy()
        y2[i - H + 1:] = 1 - np.nan_to_num(y2[i - H + 1:])                       # outcomes not yet known at i must not matter
        self.assertEqual(base, V.climatology(y2, i, H, 3000))

    def test_ticks_resolve_order_inside_a_bar(self):
        from masterquo.montecarlo import validate as V
        tk = V.Ticks(self.ds)
        self.assertIsNotNone(tk.t)
        t0 = tk.t[len(tk.t) // 2] / 1000
        px = tk.bid[(tk.t >= t0 * 1000) & (tk.t < (t0 + 60) * 1000)]
        if len(px) >= 2:
            first = float(px[0])
            self.assertEqual(tk.order(t0, t0 + 60, "BUY", first - 1e-6, first - 100), "TP")   # TP touched by the first quote

    def test_incomplete_dataset_refused(self):
        from masterquo.montecarlo import validate as V
        d = Path(tempfile.mkdtemp())
        (d / "EXPORT_STATUS.json").write_text(json.dumps({"status": "FAILED"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            V.load_dataset(d)


class _Bridge:
    def __init__(self, b):
        self.b = b
        self.symbol_info = {"point": 0.01, "trade_tick_size": 0.01}

    def bars(self, tf, limit=None, include_forming=True):
        return self.b

    def quote_status(self):
        return {"bid": self.b[-1]["c"], "ask": self.b[-1]["c"] + 0.12}


class TestService(unittest.TestCase):
    def test_service_uses_closed_bars_caches_and_states_basis(self):
        td = TempData()
        try:
            from masterquo.config import ConfigStore
            from masterquo.montecarlo.service import MonteCarloService
            svc = MonteCarloService(ConfigStore(), _Bridge(bars()), synthetic=True, n_paths=500)
            plan = svc.plan_for("BUY", 3.0, [2.5, 5.0])
            self.assertAlmostEqual(plan.entry, bars()[-1]["c"] + 0.12)              # BUY at Ask
            r1 = svc.compute([plan])
            r2 = svc.compute([plan])
            self.assertIs(r1, r2)                                                 # cached per last closed bar
            self.assertEqual(r1["status"], "OK")
            self.assertIn("NIE był wybrany walidacją", r1["variant_basis"])
            self.assertEqual(svc.status()["variant"], "BLOCK")
            svc.stop()
        finally:
            td.close()


if __name__ == "__main__":
    unittest.main()


class TestMonteCarloApi(unittest.TestCase):
    """Demo server (simulator): endpoints answer from the bot's own M1 buffer, in the MC thread, with the probability kind stated."""

    @classmethod
    def setUpClass(cls):
        from test_ui_export import Server
        cls.S = type("S", (Server,), {})
        cls.S.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()

    def test_status_scenarios_and_plan(self):
        from _env import wait_for
        st, s = self.S.call("/api/v1/montecarlo/status")
        self.assertEqual(st, 200)
        self.assertEqual(s["variant"], "BLOCK")
        self.assertFalse(s["calibrated"])
        self.assertTrue(wait_for(lambda: self.S.call("/api/v1/montecarlo/scenarios?horizon=60")[1].get("status") == "OK", 90, 1))
        sc = self.S.call("/api/v1/montecarlo/scenarios?horizon=60")[1]
        self.assertEqual(sc["data"]["kind"], "SYNTHETIC_TEST")
        self.assertIn("SYNTETYCZNE", sc["warning"])
        st, r = self.S.call("/api/v1/montecarlo/run", {"side": "SELL", "sl_distance": 3.0, "tp_distances": [2.5, 3.0, 5.0, 10.0], "horizon": 60,
                                                          "n_paths": 1000})
        self.assertEqual(st, 200, r)
        self.assertEqual(r["status"], "OK", r)
        lv = r["plans"][0]["levels"]
        self.assertEqual(len(lv), 4)
        self.assertEqual([x["p_tp_within_h"] for x in lv], sorted([x["p_tp_within_h"] for x in lv], reverse=True))
        self.assertEqual(r["probability_kind"], "MODEL_SIMULATED")
        for bad in ({"side": "UP", "sl_distance": 3, "tp_distances": [2]}, {"side": "BUY", "sl_distance": -1, "tp_distances": [2]},
                    {"side": "BUY", "sl_distance": 3, "tp_distances": []}, {"side": "BUY", "sl_distance": 3, "tp_distances": [2], "n_paths": 10 ** 7}):
            self.assertEqual(self.S.call("/api/v1/montecarlo/run", bad)[0], 400, bad)
        self.assertEqual(self.S.call("/api/v1/montecarlo/run", {"side": "BUY", "sl_distance": 3, "tp_distances": [2]}, csrf=False)[0], 403)
