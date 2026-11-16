"""1.41: research modules, 9 baskets / 90 strategies, OTC payoff gate, OTC feed, Training Center components. Technical acceptance on small
explicit cases (chronology, money math, states) - not a backtest and not an efficacy evaluation."""
from __future__ import annotations

import io
import json
import math
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

import numpy as np

import _env  # noqa: F401


def walk(n: int, seed: int = 7, start: float = 2000.0, step: float = 300.0) -> list[dict]:
    rng = np.random.default_rng(seed)
    c = start + np.cumsum(rng.normal(0, 1.5, n))
    out = []
    for k in range(n):
        o = c[k - 1] if k else c[0]
        h, l = max(o, c[k]) + abs(rng.normal(0, 0.8)), min(o, c[k]) - abs(rng.normal(0, 0.8))
        out.append({"t": 1.7e9 + k * step, "o": float(o), "h": float(h), "l": float(l), "c": float(c[k]), "tv": 100.0})
    return out


class TestCatalog(unittest.TestCase):
    def test_nine_baskets_ninety_unique_strategies_full_contract(self):
        from masterquo.baskets import catalog as C, hedge as H, rules as R
        v = C.validate()
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["total"], 90)
        self.assertEqual(set(v["per_basket"].values()), {10})
        self.assertEqual(set(v["distinct_families_per_basket"].values()), {10})      # no basket = 10 aliases of one rule
        for s in C.CATALOG:
            self.assertIn(s["family_id"], R.FAMILIES if s["kind"] != "HEDGING" else H.PLANNERS, s["strategy_id"])
            if s["profile_id"] == "OTC_GOLD_POCKETOPTION" and s["kind"] != "HEDGING":
                self.assertEqual(s["plan_type"], "FixedExpiryPlan")
                self.assertNotIn("tp_r", s["parameter_schema"])                          # no fake SL/TP for OTC

    def test_preservation_view_has_no_execution_route_next_to_gold_strategies(self):
        from masterquo.baskets import catalog as C
        from masterquo.upgrade import preservation as P
        view = C.preservation_view()
        self.assertEqual(len(view), 90)
        rep = P.compare([{"strategy_id": "S01", "source": "ACTIVE"}], [{"strategy_id": "S01", "source": "ACTIVE"}], new_catalog=view)
        self.assertEqual(rep["duplicate_execution_routes"], [])
        self.assertEqual(rep["missing_strategy_ids"], [])


class TestPayoff(unittest.TestCase):
    def test_call_put_100_at_80_percent_is_minus_20_ties_zero(self):
        from masterquo.baskets import payoff as PO
        legs = [{"dir": "CALL", "stake": 100, "r": 0.8, "strike": 2000, "expiry": 1}, {"dir": "PUT", "stake": 100, "r": 0.8, "strike": 2000, "expiry": 1}]
        t = PO.table(legs)
        self.assertEqual({r["kind"]: r["pnl"] for r in t["rows"]}, {"below": -20.0, "tie": 0.0, "above": -20.0})

    def test_kc_above_kp_both_lose_between(self):
        from masterquo.baskets import payoff as PO
        t = PO.table([{"dir": "CALL", "stake": 100, "r": 0.8, "strike": 2001, "expiry": 1}, {"dir": "PUT", "stake": 100, "r": 0.8, "strike": 2000, "expiry": 1}])
        self.assertEqual(t["worst"], -200.0)

    def test_different_expiries_refused_and_gate_needs_improvement(self):
        from masterquo.baskets import payoff as PO
        self.assertEqual(PO.table([{"dir": "CALL", "stake": 1, "r": .8, "strike": 1, "expiry": 1}, {"dir": "PUT", "stake": 1, "r": .8, "strike": 1, "expiry": 2}])["code"],
                         "EXPIRY_MISMATCH")
        parent = [{"dir": "CALL", "stake": 100, "r": 0.8, "strike": 2000, "expiry": 9}]
        g = PO.gate(parent, dir_new="PUT", strike_est=2001, strike_band=0.1, r_new=0.85, expiry=9, stake_min=1, stake_step=1, stake_max=200, cash_free=150,
                    min_improvement=10)
        self.assertEqual(g["state"], "HEDGE_PLAN")
        self.assertGreaterEqual(g["improvement"], 10)
        self.assertEqual(g["label"], "ESTIMATED_PAYOFF")
        self.assertEqual(PO.gate(parent, dir_new="PUT", strike_est=2001, strike_band=0, r_new=None, expiry=9, stake_min=1, stake_step=1, stake_max=10,
                                 cash_free=10, min_improvement=1)["state"], "NO_HEDGE")
        self.assertIsNone(PO.ev_money(10, 0.8, 0.6, None))                              # never 1 - p_win silently


class TestDetectorsAndRules(unittest.TestCase):
    def test_detectors_do_not_look_ahead(self):
        from masterquo.baskets import detectors as D, rules as R
        bars = walk(600)
        F1, F2 = D.build(bars[:450], 0.01), D.build(bars, 0.01)
        i = 449
        self.assertEqual(F1.trend(i), F2.trend(i))
        self.assertEqual(F1.structure_break(i, 1), F2.structure_break(i, 1))
        self.assertEqual([p.k for p in F1.swings(i, "L", 4)], [p.k for p in F2.swings(i, "L", 4)])
        self.assertTrue(all(p.confirmed_at == p.k + 2 for p in F2.pivots()))
        for name in ("ema_pullback", "bb_reentry", "compression_breakout", "failed_breakdown", "double_bottom", "inside_bar", "rsi2_snapback"):
            fam = R.FAMILIES[name]
            ctx = {"htf": D.build(bars[:450], 0.01)}
            a = fam(F1, 1, {}, ctx)
            b = fam(D.build(bars[:450], 0.01), 1, {}, ctx)
            self.assertEqual(a, b, name)

    def test_missing_real_volume_is_unavailable_not_zero(self):
        from masterquo.baskets import detectors as D, rules as R
        F = D.build(walk(300), 0.01)
        self.assertIsNone(F.rvol(F.i))
        with self.assertRaises(R.Unavailable):
            R.squeeze_volume(D.build(walk(400), 0.01), 1, {}, {}) if False else R.l2_aggressor(F, 1, {}, {"flow": []})

    def test_failed_breakdown_explicit_case(self):
        from masterquo.baskets import detectors as D, rules as R
        bars = [{"t": k * 60.0, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0} for k in range(40)]
        bars.append({"t": 40 * 60.0, "o": 100.0, "h": 100.5, "l": 97.0, "c": 99.6})        # sweep below LL20 - b, close back above
        bars.append({"t": 41 * 60.0, "o": 99.6, "h": 101.2, "l": 99.5, "c": 101.0})        # close above the sweep bar's high
        r = R.failed_breakdown(D.build(bars, 0.01), 1, {}, {})
        self.assertIsNotNone(r)
        self.assertLess(r["sl"], 97.0)
        self.assertEqual(r["event"]["type"], "FAILED_BREAKDOWN")


class TestOtcFeed(unittest.TestCase):
    def test_waiting_without_feed_and_no_fake_short_candles(self):
        from masterquo.baskets import otc as O
        with tempfile.TemporaryDirectory() as d:
            f = O.OTCFeed(Path(d))
            self.assertEqual(f.state()["state"], "WAITING_FOR_OTC_FEED")
            (Path(d) / "import" / "gold_M1.csv").write_text("t,o,h,l,c\n0,1,2,0.5,1.5\n60,1.5,2,1,1.2\n", encoding="utf-8")
            self.assertEqual(f.import_dir()["candles"], 2)
            self.assertEqual(f.bars("S15", now=1e9), [])                                 # M1 is never cut into S15
            self.assertEqual(len(f.bars("M1", now=1e9)), 2)
            self.assertEqual(O.choose_expiry(60, [30, 65, 120]), 65)
            self.assertIsNone(O.choose_expiry(60, [30, 120]))


class TestResearchModules(unittest.TestCase):
    def test_features_as_of_and_composite_optimizer(self):
        from masterquo.research import service as RS
        bars = walk(900, step=300)
        st = {"n": 500}
        with tempfile.TemporaryDirectory() as d:
            rt = types.SimpleNamespace(demo=True, bridge=None, sh=types.SimpleNamespace(instrument=lambda: "XAUUSD"))
            svc = RS.ResearchModulesService(rt, data_dir=Path(d))
            c = RS.Context("K", "XAUUSD", lambda tf, n: bars[:st["n"]][-n:] if tf == "M5" else [])
            svc.contexts["K"] = c
            svc.ensure_main_context = lambda: c
            svc.update_settings({"modules": {"sdformerflow": {"enabled": False}}, "optimizer": {"min_interval_seconds": 0, "coa_evals": 40, "bchimp_evals": 30}})
            for k in range(120):
                st["n"] = 500 + k
                svc.cycle()
            early = c.snaps[20]
            f = svc.features_for("XAUUSD", early["t"])
            self.assertEqual(f["graph_bpc10_raw"], early["modules"]["cellular_feature_graph"]["targets"]["BPC10"]["raw_score"])
            self.assertEqual(svc.features_for("XAUUSD", c.snaps[0]["t"] - 1), {})        # nothing known before the first snapshot
            self.assertIn("optimizer_last", svc.jobs)
            w = svc.settings()["composite"]["weights"]
            self.assertTrue(all(math.isfinite(x) for x in w))
            preds = svc.predictions("XAUUSD")
            self.assertTrue(preds and all(p["unit"] != "probability" for p in preds))
            with self.assertRaises(ValueError):
                svc.update_settings({"account": 1})

    def test_optimizer_refuses_forbidden_parameters(self):
        from masterquo.research import optim as OP
        with self.assertRaises(ValueError):
            OP.ParameterSpace(["position_size"], [0], [1], [0.1], "v")
        with self.assertRaises(ValueError):
            OP.ParameterSpace(["leverage_x"], [0], [1], [0.1], "v")

    def test_etc_component_optimize_export_import_rollback(self):
        import time
        from masterquo.research import service as RS
        bars = walk(1400, step=300)
        with tempfile.TemporaryDirectory() as d:
            rt = types.SimpleNamespace(demo=True, bridge=None, sh=types.SimpleNamespace(instrument=lambda: "XAUUSD"))
            svc = RS.ResearchModulesService(rt, data_dir=Path(d))
            c = RS.Context("K", "XAUUSD", lambda tf, n: bars[-n:] if tf == "M5" else [])
            svc.ensure_main_context = lambda: c
            cp = svc.components
            self.assertTrue(cp.start_job("ETC_LOG_CHANNEL", "OPTIMIZE", {"coa_evals": 20, "bchimp_evals": 10, "deadline_s": 30})["ok"])
            t0 = time.time()
            while cp.jobs["etc_last"]["state"] == "RUNNING" and time.time() - t0 < 120:
                time.sleep(0.5)
            j = cp.jobs["etc_last"]
            self.assertEqual(j["state"], "DONE", j)
            self.assertIn(j["computation"]["decision"], ("APPLY", "KEEP_INCUMBENT"))
            ver = svc.settings()["etc"]["param_version"]
            z = cp.export_zip("ETC_LOG_CHANNEL", ver)
            self.assertTrue(cp.import_zip("ETC_LOG_CHANNEL", z)["ok"])
            bad = io.BytesIO()
            with zipfile.ZipFile(bad, "w") as zz:
                zz.writestr("manifest.json", "{}")
                zz.writestr("run.py", "print(1)")
            with self.assertRaises(ValueError):
                cp.import_zip("ETC_LOG_CHANNEL", bad.getvalue())


class TestBasketService(unittest.TestCase):
    def test_forex_signals_are_deduplicated_and_never_orders(self):
        from datetime import datetime, timezone
        from masterquo.baskets import service as BS
        m5 = walk(3200, seed=3, step=300)
        st = {"n": 3000}

        def agg(bs, sec):
            out = {}
            for b in bs:
                k = b["t"] // sec * sec
                if k not in out:
                    out[k] = dict(b, t=k)
                else:
                    o = out[k]
                    o["h"], o["l"], o["c"] = max(o["h"], b["h"]), min(o["l"], b["l"]), b["c"]
            return list(out.values())

        class Br:
            cfg = types.SimpleNamespace(symbol="XAUUSD-")
            symbol_info = {"point": 0.01, "trade_tick_size": 0.01, "volume_step": 0.01}

            def account_status(self):
                return {"login": 1, "margin_mode": "NETTING"}

            def quote_status(self):
                return {}

            def bars(self, tf, include_forming=True):
                sec = {"M5": 300, "M15": 900, "H1": 3600}.get(tf)
                if not sec:
                    return []
                bs = m5[:st["n"]]
                a = bs if sec == 300 else agg(bs, sec)
                return [{"open_utc": datetime.fromtimestamp(b["t"], timezone.utc).isoformat(), **{k: b[k] for k in "ohlc"}, "tv": 1} for b in a]

            def order_send(self, *a, **k):                                               # must never be called
                raise AssertionError("basket sent an order")

        with tempfile.TemporaryDirectory() as d:
            rt = types.SimpleNamespace(demo=True, bridge=Br(), db=None, bus=None, quant=None, news=None)
            svc = BS.BasketService(rt, data_dir=Path(d))
            svc.update_settings({"profiles": {"CRYPTO_FOMO_PERPS": {"enabled": False}, "OTC_GOLD_POCKETOPTION": {"enabled": False}}})
            for k in range(150):
                st["n"] = 3000 + k
                svc.cycle()
            sig = svc.ledger.recent(limit=500)
            self.assertEqual(len({s["event_id"] for s in sig}), len(sig))               # one primary plan per event
            for s in sig:
                self.assertEqual(s["plan"]["execution_status"], "SIGNAL (bez zlecenia)")
                self.assertIsNone(s["plan"]["quantity"])                                    # no capital configured -> no guessed size
            hedge = {k: v["state"] for k, v in svc.hedge_state.items()}
            self.assertTrue(all(v in ("NO_EXPOSURE", "WAITING_FOR_DATA") for v in hedge.values()), hedge)
            with self.assertRaises(ValueError):
                svc.update_settings({"profiles": {"FOREX_MT5": {"selection": "YOLO"}}})


if __name__ == "__main__":
    unittest.main()
