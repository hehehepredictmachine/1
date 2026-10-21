"""PMW-SH-1 stage 3: single config source (validate / override / rollback), setup engine statuses on hand-built analysis
snapshots (BUY / SELL / WAIT / NO_TRADE / INVALIDATED), unit guard, model registry LIMITED mode, SH target-event model
gate / promotion / rollback / integrity. Synthetic inputs exist only inside the test and an isolated data dir."""
import json
import unittest

import _env  # noqa: F401
from _env import TempData

NOW = 1_760_000_000.0


def _spec(cur="USD"):
    from masterquo.sh.units import SymbolSpec
    return SymbolSpec("XAUUSD-", 0.01, 1.0, 100, 0.01, 0.01, 100, 2, cur, source="TEST")


def _snap(side="BUY", **over):
    up = side == "BUY"
    s = {"data": {"status": "OK", "issues": [], "quote_age_s": 0.5, "spread": 0.2},
         "vol": {"status": "OK", "atr_m1": 0.5, "atr_m5": 1.5},
         "regime": {"status": "OK", "state": "TREND_UP" if up else "TREND_DOWN"},
         "structure_M5": {"status": "OK", "internal": "UP" if up else "DOWN", "major": "UP" if up else "DOWN", "highs": [], "lows": []},
         "structure_M15": {"status": "OK", "internal": "UP" if up else "DOWN", "highs": [], "lows": []},
         "structure_H1": {"status": "OK", "internal": "UP" if up else "DOWN", "major": "UP" if up else "DOWN", "highs": [], "lows": []},
         "ctx": {"status": "OK", "vamd_m5": 0.4 if up else -0.4, "fd_zone_m5": "TREND",
                 "pb_last_low_m5": 1999.0, "pb_last_high_m5": 2001.0},
         "candle_m1": {"status": "OK", "direction": "NEUTRAL"},
         "price": {"bid": 2000.0, "ask": 2000.2}}
    s.update(over)
    return s


def _m1(side="BUY"):
    if side == "BUY":   # dip into the zone (low 1999.5), then a close above the two previous highs
        return [{"o": 2000.0, "h": 2000.1, "l": 1999.5, "c": 1999.8}, {"o": 1999.8, "h": 1999.95, "l": 1999.6, "c": 1999.9},
                {"o": 1999.9, "h": 2000.2, "l": 1999.85, "c": 2000.15}]
    return [{"o": 2000.0, "h": 2000.5, "l": 1999.9, "c": 2000.3}, {"o": 2000.3, "h": 2000.4, "l": 2000.1, "c": 2000.2},
            {"o": 2000.2, "h": 2000.25, "l": 1999.8, "c": 1999.85}]


class SHCase(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def prof(self, inst="XAUUSD", strat="SCALPING"):
        from masterquo.sh import config as C
        return C.profile(C.load(), inst, strat)


class Config(SHCase):
    def test_defaults_valid_and_hash(self):
        from masterquo.sh import config as C
        cfg = C.load()
        self.assertEqual(C.validate(cfg), [])
        self.assertEqual(cfg["_override_version"], 0)
        p = C.profile(cfg, "XAUUSD", "SCALPING")
        self.assertEqual(p["tp_usd"], [2.5, 3.0, 5.0])
        self.assertEqual(C.profile(cfg, "XAUUSD", "HEDGING")["tp_usd"], [3.5, 5.0, 9.0])
        self.assertFalse(p["_instrument"].get("enabled") is False)
        self.assertIs(C.profile(cfg, "BTC", "SCALPING")["_instrument"]["enabled"], False)

    def test_override_validation_history_rollback(self):
        from masterquo.sh import config as C
        h0 = C.load()["_hash"]
        with self.assertRaises(ValueError):
            C.save_override({"magic_number": 1})                                         # not editable from the panel
        with self.assertRaises(ValueError):
            C.save_override({"instruments": {"XAUUSD": {"SCALPING": {"shares": [0.5, 0.3, 0.3]}}}})      # 110 %
        with self.assertRaises(ValueError):
            C.save_override({"instruments": {"XAUUSD": {"HEDGING": {"tp_usd": [3.5, 5.0, 11.0]}}}})     # TP3 not in {9,10}
        with self.assertRaises(ValueError):
            C.save_override({"instruments": {"XAUUSD": {"HEDGING": {"hedge": {"ratio": 1.5}}}}})        # martingale-like
        cfg = C.save_override({"instruments": {"XAUUSD": {"HEDGING": {"tp_usd": [3.5, 5.0, 10.0]}}}})
        self.assertEqual(cfg["instruments"]["XAUUSD"]["HEDGING"]["tp_usd"], [3.5, 5.0, 10.0])
        self.assertNotEqual(cfg["_hash"], h0)
        self.assertEqual(cfg["_override_version"], 1)
        back = C.rollback_override()
        self.assertEqual(back["instruments"]["XAUUSD"]["HEDGING"]["tp_usd"], [3.5, 5.0, 9.0])
        self.assertEqual(back["_hash"], h0)


class Setup(SHCase):
    def ev(self, side="BUY", snap=None, prof=None, m1=None, spec=None, **kw):
        from masterquo.sh import setup as SU
        return SU.evaluate("SCALPING", "XAUUSD", snap or _snap(side), spec or _spec(), prof or self.prof(), now=NOW,
                           m1=m1 if m1 is not None else _m1(side), **kw)

    def test_buy_ready_targets_from_ask(self):
        r = self.ev("BUY")
        self.assertEqual(r["status"], "READY", r["status_reason"])
        self.assertEqual(r["side"], "BUY")
        self.assertEqual(r["mode"], "CONTINUATION")
        self.assertAlmostEqual(r["entry_ref"], 2000.2)
        self.assertEqual([t["price"] for t in r["tps"]], [2002.7, 2003.2, 2005.2])
        self.assertTrue(all(abs(t["rounding_diff"]) < 1e-9 for t in r["tps"]))
        self.assertLess(r["sl"], r["entry_ref"])
        self.assertEqual(r["probability"]["status"], "BRAK_MODELU_ZDARZENIA")
        self.assertEqual(r["model_mode"], "OGRANICZONA")
        self.assertIn("NIE jest prawdopodobieństwem", r["score"]["definition"])
        self.assertEqual(r["be"]["after"], "TP2")
        self.assertGreater(r["be"]["offset_price"], 0)                                    # BE after costs, explicitly defined
        self.assertEqual(r["valid_until"], NOW + 600)

    def test_sell_ready_targets_from_bid(self):
        r = self.ev("SELL")
        self.assertEqual(r["status"], "READY", r["status_reason"])
        self.assertEqual(r["side"], "SELL")
        self.assertEqual([t["price"] for t in r["tps"]], [1997.5, 1997.0, 1995.0])
        self.assertGreater(r["sl"], r["entry_ref"])

    def test_htf_conflict_waits(self):
        s = _snap("BUY")
        s["structure_H1"] = {"status": "OK", "internal": "DOWN", "major": "DOWN"}
        r = self.ev("BUY", snap=s)
        self.assertEqual(r["status"], "WAIT")
        self.assertIn("sprzeczne", r["status_reason"])
        self.assertNotIn("tps", r)                                                        # a waiting setup has no active plan

    def test_no_trigger_waits(self):
        m1 = _m1("BUY")
        m1[-1] = dict(m1[-1], c=1999.7)
        self.assertEqual(self.ev("BUY", m1=m1)["status"], "WAIT")

    def test_stale_data_blocks(self):
        s = _snap("BUY", data={"status": "BLOCK", "issues": ["M1: dane nieaktualne (400 s od zamknięcia)"]})
        r = self.ev("BUY", snap=s)
        self.assertEqual(r["status"], "NO_TRADE")
        self.assertIn("nieaktualne", r["status_reason"])

    def test_invalidated(self):
        s = _snap("BUY", price={"bid": 1998.5, "ask": 1998.7})
        self.assertEqual(self.ev("BUY", snap=s)["status"], "INVALIDATED")

    def test_sl_too_wide_no_trade(self):
        s = _snap("BUY")
        s["ctx"] = dict(s["ctx"], pb_last_low_m5=1995.5)
        m1 = [dict(b, l=min(b["l"], 1995.9)) for b in _m1("BUY")]
        p = dict(self.prof(), zone_atr_m5=3.0)                                            # zone reaches the price
        r = self.ev("BUY", snap=s, m1=m1, prof=p)
        self.assertEqual(r["status"], "NO_TRADE")
        self.assertIn("ryzyko", r["status_reason"])

    def test_obstacle_before_tp1_no_trade(self):
        s = _snap("BUY")
        s["structure_M15"] = dict(s["structure_M15"], highs=[2001.0])
        r = self.ev("BUY", snap=s)
        self.assertEqual(r["status"], "NO_TRADE")
        self.assertIn("przeszkoda", r["status_reason"])

    def test_low_calibrated_probability_blocks(self):
        r = self.ev("BUY", tp_prob={"status": "READY", "p": 0.40, "version": "x"})
        self.assertEqual(r["status"], "NO_TRADE")
        self.assertEqual(r["probability"]["status"], "SKALIBROWANE")
        r2 = self.ev("BUY", tp_prob={"status": "SHADOW_ONLY", "p": 0.90})                 # unvalidated model is never a probability
        self.assertEqual(r2["probability"]["status"], "BRAK_MODELU_ZDARZENIA")

    def test_unit_and_instrument_guards(self):
        r = self.ev("BUY", spec=_spec("EUR"))
        self.assertEqual(r["status"], "NO_TRADE")
        self.assertIn("QUOTE_CURRENCY_EUR", r["status_reason"])
        from masterquo.sh import setup as SU
        r2 = SU.evaluate("SCALPING", "BTC", _snap("BUY"), _spec(), self.prof("BTC"), now=NOW, m1=_m1("BUY"))
        self.assertEqual(r2["status"], "NO_TRADE")

    def test_range_middle_waits_edge_reverses(self):
        s = _snap("BUY", regime={"status": "OK", "state": "RANGE"})
        s["structure_M5"] = dict(s["structure_M5"], internal="RANGE", last_low=1990.0, last_high=2010.0)
        s["structure_H1"] = {"status": "OK", "internal": "RANGE", "major": "RANGE"}
        s["structure_M15"] = {"status": "OK", "internal": "RANGE"}
        self.assertEqual(self.ev("BUY", snap=s)["status_reason"], "cena w środku zakresu – brak przewagi lokalizacji")
        s["structure_M5"] = dict(s["structure_M5"], last_low=1999.0, last_high=2030.0)
        r = self.ev("BUY", snap=s)
        self.assertEqual(r.get("mode"), "REVERSAL")
        self.assertEqual(r["status"], "WAIT")                                              # no CHoCH / reversal candle yet
        s["candle_m1"] = {"status": "OK", "direction": "LONG"}
        self.assertEqual(self.ev("BUY", snap=s)["status"], "READY")

    def test_hedging_profile_requires_trend(self):
        from masterquo.sh import setup as SU
        s = _snap("BUY", regime={"status": "OK", "state": "RANGE"})
        r = SU.evaluate("HEDGING", "XAUUSD", s, _spec(), self.prof(strat="HEDGING"), now=NOW, m1=_m1("BUY"))
        self.assertEqual(r["status"], "NO_TRADE")


class Registry(SHCase):
    def test_limited_mode_without_event_model(self):
        from masterquo.sh import models as M
        mx = M.matrix(None, "XAUUSD")
        self.assertEqual(mx["mode"], "OGRANICZONA")
        self.assertIn("AUTO zablokowane", mx["mode_note"])
        ids = {r["id"]: r for r in mx["rows"]}
        self.assertEqual(ids["sh_tp_model"]["SCALPING"]["use"], "NONE")
        for r in mx["rows"]:                                                              # nothing untrained is a decision source
            if r["status"] not in ("READY", "DETERMINISTIC_OK"):
                self.assertIn(r["SCALPING"]["use"], ("INFO", "NONE", "GATE_UNAVAILABLE"), r["id"])


class TpModel(SHCase):
    def samples(self, n, informative, seed=0):
        import numpy as np
        rng = np.random.default_rng(seed)
        from masterquo.sh.tpmodel import FEATURES
        X = rng.normal(size=(n, len(FEATURES)))
        p = 1 / (1 + np.exp(-2.5 * X[:, 0])) if informative else np.full(n, 0.5)
        y = (rng.random(n) < p).astype(int)
        return [{"t": NOW + 600 * i, "x": X[i].tolist(), "y": int(y[i])} for i in range(n)]

    def test_gate_promotion_predict_rollback_integrity(self):
        from masterquo.sh import tpmodel as T
        self.assertEqual(T.status("XAUUSD", "SCALPING")["status"], "NOT_TRAINED")
        self.assertEqual(T.train("XAUUSD", "SCALPING", self.samples(50, True), embargo_s=3600)["verdict"], "INSUFFICIENT_DATA")
        bad = T.train("XAUUSD", "SCALPING", self.samples(1500, False, 1), embargo_s=3600, log=lambda *_: None)
        self.assertEqual(bad["verdict"], "HOLDOUT_FAILED")
        self.assertEqual(T.status("XAUUSD", "SCALPING")["status"], "SHADOW_ONLY")
        self.assertEqual(T.predict("XAUUSD", "SCALPING", [0.0] * len(T.FEATURES))["status"], "NOT_TRAINED")
        good = T.train("XAUUSD", "SCALPING", self.samples(1500, True, 2), embargo_s=3600, log=lambda *_: None)
        self.assertEqual(good["verdict"], "HOLDOUT_PASSED")
        self.assertGreater(good["split"]["holdout"], 0)
        self.assertEqual(T.status("XAUUSD", "SCALPING")["status"], "READY")
        hi = T.predict("XAUUSD", "SCALPING", [2.0] + [0.0] * (len(T.FEATURES) - 1))
        lo = T.predict("XAUUSD", "SCALPING", [-2.0] + [0.0] * (len(T.FEATURES) - 1))
        self.assertEqual(hi["status"], "READY")
        self.assertGreater(hi["p"], lo["p"])
        f = T.root("XAUUSD", "SCALPING") / f"{good['run_id']}.npz"
        raw = f.read_bytes()
        f.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        self.assertEqual(T.predict("XAUUSD", "SCALPING", [0.0] * len(T.FEATURES))["status"], "INCOMPATIBLE")
        f.write_bytes(raw)
        self.assertEqual(T.rollback("XAUUSD", "SCALPING")["active"], None)
        self.assertEqual(T.status("XAUUSD", "SCALPING")["status"], "SHADOW_ONLY")
        reg = json.loads((T.root("XAUUSD", "SCALPING") / "registry.json").read_text())
        self.assertEqual(len(reg["runs"]), 3)                                              # every run kept, none overwritten


if __name__ == "__main__":
    unittest.main()
