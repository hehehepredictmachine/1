"""1.46 audit, group B_mq_sh_1: sh/config.py, sh/context.py, sh/executor.py, sh/hedge_fsm.py, sh/lifecycle.py, sh/models.py and the
SH pack (catalog / engine / features / policies / replay).

Pure logic and an isolated MASTERQUO_DATA_DIR - no terminal, no orders, no HTTP server. All market data is SYNTHETIC."""
from __future__ import annotations

import random
import unittest
from datetime import UTC, datetime
from unittest import mock

import _env  # noqa: F401
from _env import TempData

T0 = 1762128000                       # Monday 2025-11-03 00:00 UTC (a multiple of 300 s)


def iso(t):
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def m5_series(n, seed=3, t0=T0, step=300):
    rnd = random.Random(seed)
    p, out, drift = 3000.0, [], 0.0
    for k in range(n):
        if k % 700 == 0:
            drift = rnd.choice([0.3, -0.3, 0.0])
        d = drift + rnd.gauss(0, 1.5)
        o, c = p, p + d
        h, lo = max(o, c) + abs(rnd.gauss(0, 0.8)), min(o, c) - abs(rnd.gauss(0, 0.8))
        out.append({"open_utc": iso(t0 + step * k), "o": round(o, 2), "h": round(h, 2), "l": round(lo, 2), "c": round(c, 2), "tv": 50,
                    "closed": True})
        p = c
    return out


# ============================================================================================ sh/config.py (chunk_30#9)
class TestConfigValidation(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    def test_typed_values_and_risk_section_are_validated(self):
        from masterquo.sh import config as C
        self.assertEqual(C.validate(C.load()), [])                                    # the shipped defaults stay valid
        bad = [{"instruments": {"XAUUSD": {"SCALPING": {"shares": ["0.5", "0.3", "0.2"]}}}},   # was TypeError -> HTTP 500
               {"instruments": {"XAUUSD": "x"}},                                       # was AttributeError -> HTTP 500
               {"instruments": "x"},
               {"risk": {"max_quote_age_s": "10"}},                                    # was SAVED, then every SH cycle raised TypeError
               {"risk": {"risk_per_trade_pct": 250}},                                  # was accepted
               {"risk": {"max_open_positions": -1}},                                   # was accepted
               {"risk": {"max_bar_age_s": {"M1": None}}},
               {"risk": {"daily_loss_limit_pct": float("nan")}}]
        for patch in bad:
            with self.assertRaises(ValueError, msg=str(patch)):
                C.save_override(patch)
        self.assertEqual(C.load()["_override_version"], 0)                            # nothing invalid was stored
        cfg = C.save_override({"risk": {"risk_per_trade_pct": 0.4}})                  # a valid change still saves
        self.assertEqual((cfg["_override_version"], cfg["risk"]["risk_per_trade_pct"]), (1, 0.4))


# ============================================================================================ sh/context.py (chunk_13#7, chunk_30#15)
# ============================================================================================ sh/executor.py (chunk_30#7, chunk_30#11)
# ============================================================================================ sh/hedge_fsm.py (chunk_30#8)
# ============================================================================================ sh/lifecycle.py (chunk_30#4)
# ============================================================================================ sh/models.py (chunk_30#10)
class TestModeNote(unittest.TestCase):
    def test_limited_mode_note_matches_the_1_39_gate_decision(self):
        td = TempData()
        self.addCleanup(td.close)
        from masterquo.sh import models as M
        mx = M.matrix(None, "XAUUSD")
        self.assertEqual(mx["mode"], "OGRANICZONA")
        note = mx["mode_note"]
        self.assertNotIn("sygnały wyłącznie SIGNALS/PAPER", note)                      # AUTO orders ARE placed since 1.39
        self.assertIn("AUTO_LIVE", note)
        self.assertIn("ostrzeżenie", note)


# ============================================================================================ sh/pack/catalog.py (chunk_32#6, chunk_32#8)
# ============================================================================================ sh/pack/engine.py (chunk_32#9, #10, #11)
def _spec():
    from masterquo.sh.units import SymbolSpec
    return SymbolSpec("XAUUSD-", 0.01, 1.0, 100, 0.01, 0.01, 50, 2, "USD", point=0.01)


# ============================================================================================ sh/pack/policies.py (chunk_32#7)
# ============================================================================================ sh/pack/replay.py (chunk_32#2,3,4,5,12,13)
def _m1(rows):
    return [{"open_utc": iso(T0 + 60 * k), "o": o, "h": h, "l": lo, "c": c, "spread_price": 0.0} for k, (o, h, lo, c) in enumerate(rows)]


def _su(econ=None, sid="PMW_SC01"):
    return {"side": "BUY", "sl": 98.0, "entry_ref": 100.0, "tps": [{"price": 102.0}, {"price": 104.0}], "strategy_id": sid,
            "pack": {"economics": econ or {}}}


class TestReplay(unittest.TestCase):
    def test_entry_slippage_is_counted_once(self):
        from masterquo.sh.pack import replay as PR
        m1 = _m1([(100.0, 100.1, 99.9, 100.0), (100.0, 104.5, 99.95, 104.2)])
        r = PR.simulate(m1, 0, _su(), spread_fb=0.0, slip=0.05, c_rt=0.2, max_minutes=60)
        # fill 100.05 (slip in the price); TP1/TP2 -> 0.5*1.95 + 0.5*3.95 = 2.95; costs once: exit slip 0.05 + commission 0.10
        self.assertAlmostEqual(r["net_r"] * r["R_price"], 2.80, places=9)               # was 2.75 (entry slip twice)

    def test_no_hedge_mode_uses_the_plan_r(self):
        from masterquo.sh.pack import replay as PR
        m1 = _m1([(100.0, 100.1, 99.9, 100.0), (100.0, 104.5, 99.95, 104.2)])
        r = PR.simulate(m1, 0, _su({"hedge_loss_bound_price": 0.3}, "PMW_HG03"), spread_fb=0.0, slip=0.0, c_rt=0.2, max_minutes=60,
                        hedge_ctx=None, mode="NO_HEDGE")
        self.assertAlmostEqual(r["R_price"], 2.0 + 0.2 + 0.3, places=9)                 # was r + C only (other R unit than HEDGE)

    def _hctx(self):
        return {"m5": [], "m5_idx": lambda t: int(t // 300), "h1": lambda t: [], "hcfg": {}, "tick": 0.01, "common": {}}

    def _decisions(self):
        it = iter([{"decision": "HEDGE", "ratio": 0.5, "reason": "t"}])
        return lambda *a, **k: next(it, {"decision": "HOLD", "reason": "t"})

    def test_open_hedge_is_settled_at_data_end(self):
        from masterquo.sh.pack import replay as PR
        m1 = _m1([(100.0, 100.05, 99.95, 100.0), (100.0, 100.05, 99.5, 99.6), (99.6, 99.7, 98.9, 99.0)])
        su = _su({"hedge_loss_bound_price": 0.3}, "PMW_HG03")
        su["tps"] = [{"price": 103.0}, {"price": 106.0}]
        su["sl"] = 95.0
        with mock.patch.object(PR.POL, "decision", self._decisions()):
            r = PR.simulate(m1, 0, su, spread_fb=0.0, slip=0.0, c_rt=0.2, max_minutes=600, hedge_ctx=self._hctx(), mode="HEDGE")
        self.assertEqual(r["end"], "DATA_END")
        self.assertAlmostEqual(r["hedge_price"], 0.5 * (100.0 - 99.0), places=9)        # was 0.0 (hedge left open, its cost charged)

    def test_hedge_closes_at_the_gap_price_with_the_base(self):
        from masterquo.sh.pack import replay as PR
        m1 = _m1([(100.0, 100.05, 99.95, 100.0), (100.0, 100.05, 99.95, 100.0), (90.0, 90.2, 89.9, 90.1)])
        su = _su({"hedge_loss_bound_price": 0.3}, "PMW_HG03")
        su["sl"] = 95.0
        with mock.patch.object(PR.POL, "decision", self._decisions()):
            r = PR.simulate(m1, 0, su, spread_fb=0.0, slip=0.0, c_rt=0.2, max_minutes=600, hedge_ctx=self._hctx(), mode="HEDGE")
        self.assertEqual(r["end"], "SL")
        self.assertAlmostEqual(r["gross_price"], 90.0 - 100.0, places=9)                # the base leaves at the gap open
        self.assertAlmostEqual(r["hedge_price"], 0.5 * (100.0 - 90.0), places=9)       # was 0.5 * (100 - 95): hedge at the SL level

    def test_expectancy_without_unambiguous_trades_is_none(self):
        from masterquo.sh.pack import replay as PR
        t = {"net_r": -1.0, "ambiguous": True, "day": "2025-11-03", "minutes": 3.0, "mae_r": 1.0, "mfe_r": 0.0, "end": "SL"}
        self.assertIsNone(PR.stats([t, dict(t)])["expectancy_ex_ambiguous"])         # was 0.0 R (invented)
        self.assertEqual(PR.stats([t, dict(t, ambiguous=False)])["expectancy_ex_ambiguous"], -1.0)

    def _bars(self, n):
        from masterquo.sh.pack import features as F
        from masterquo.sh.pack import replay as PR
        m1 = m5_series(n, step=60)
        return {"M1": m1, "M3": PR.aggregate(m1, 180), "M5": PR.aggregate(m1, 300), "M15": PR.aggregate(m1, 900), "H1": PR.aggregate(m1, 3600)}, \
            {"instrument": "XAUUSD", "data_kind": "SYNTHETIC_TEST", "spec": {"point": 0.01, "trade_tick_size": 0.01}, "tf_sources": {}}, F

    def test_zero_drawdown_of_hedge_is_not_missing_data(self):
        td = TempData()
        self.addCleanup(td.close)
        from masterquo.sh.pack import replay as PR
        bars, meta, _F = self._bars(60)
        fake = {"HEDGE": {"n": 10, "expectancy_r": 0.10, "max_drawdown_r": 0.0}, "NO_HEDGE": {"n": 10, "expectancy_r": 0.20, "max_drawdown_r": -5.0},
                "REDUCE": {"n": 10, "expectancy_r": 0.05, "max_drawdown_r": -1.0}}
        order = iter(["HEDGE", "NO_HEDGE", "REDUCE"])
        with mock.patch.object(PR, "stats", lambda trades, **kw: dict(fake[next(order)])):
            rep = PR.run(bars, meta, variants=["PMW_HG03"], warm_m1=10 ** 6)
        # NO_HEDGE has a higher expectancy but a deeper drawdown than HEDGE (0.0): it does NOT dominate (was: 0.0 read as -1e9)
        self.assertIsNone(rep["variants"]["PMW_HG03|M15"]["hedge_comparison"]["dominated_by"])
        self.assertEqual(rep["variants"]["PMW_HG03|M15"]["config_hash"], PR.CAT.load()["variants"]["PMW_HG03"]["config_hash"])

    def test_plans_are_solved_with_the_known_commission(self):
        td = TempData()
        self.addCleanup(td.close)
        from masterquo.sh.pack import replay as PR
        from masterquo.sh.pack import solver as SV
        bars, meta, _F = self._bars(400)
        seen = []

        def one(self, X, v, tf, inst, spec, ic, q, t, pipdef, cfg, mpp, ccy):
            seen.append(SV.costs(ic, mpp, cfg["common"]))
            return {"status": "WAIT", "pack": {"reason_code": "TEST"}}
        with mock.patch.object(PR.PackEngine, "_one", one):
            PR.run(bars, meta, variants=["PMW_SC04"], warm_m1=300, commission_price_rt=0.3)
        self.assertTrue(seen)
        self.assertTrue(all(c["cost_status"] == "KNOWN" and abs(c["commission_price_rt"] - 0.3) < 1e-9 for c in seen))   # was the 0.10 scenario
        self.assertTrue(all(abs(c["c_round_trip"] - (2 * 0.05 + 0.3)) < 1e-9 for c in seen))                            # = c_rt of the simulation


if __name__ == "__main__":
    unittest.main()
