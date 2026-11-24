"""1.46 audit, group B_mq_sh_2: sh/replay.py, sh/risk.py, sh/service.py, sh/tpmodel.py, sh/train_cli.py, sh/units.py.

Pure logic, stand-in bridge / modes and an isolated MASTERQUO_DATA_DIR - no terminal, no orders, no HTTP server. All market data is SYNTHETIC."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest import mock

import _env  # noqa: F401
from _env import TempData

T0 = 1_700_000_000


def m1(k, o, h, lo, c, sp=0.2):
    return {"open_utc": datetime.fromtimestamp(T0 + 60 * k, UTC).isoformat().replace("+00:00", "Z"), "o": o, "h": h, "l": lo, "c": c,
            "spread_price": sp}


def test_spec():
    from masterquo.sh.units import SymbolSpec
    return SymbolSpec("XAUUSD-", 0.01, 1.0, 100, 0.01, 0.01, 100, 2, "USD", source="TEST")


# ============================================================================================ sh/replay.py (chunk_30#12)
class TestReplayHedgeClosedAtStopMoment(unittest.TestCase):
    """Live: the hedge leg has its broker TP at the primary SL and the bot closes it as soon as the primary stop is seen. The replay closed
    it at the CLOSE of the stop bar (a later price): a bar closing far beyond the SL overstated the hedge profit of the HEDGE variant."""

    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)
        from masterquo.sh import config as C
        self.prof = C.profile(C.load(), "XAUUSD", "HEDGING")

    def sim(self, bars, side, sl):
        from masterquo.sh import replay as RP
        mk = RP.Market({"M1": bars, "M5": [], "M15": [], "H1": []}, 0.2)
        su = {"side": side, "entry_ref": 2000.2 if side == "BUY" else 2000.0, "sl": sl, "shares": [0.4, 0.3, 0.3], "mode": "T",
              "tps": [{"name": n, "distance_requested": d} for n, d in zip(("TP1", "TP2", "TP3"), (3.5, 5.0, 9.0))], "be": {"offset_price": 0.0},
              "invalidation": None}
        return RP.simulate_hedge(mk, 0, su, test_spec(), self.prof, slip=0.05, commission_side=None, variant="HEDGE", atr_m5=5.0)

    def test_buy_primary_sell_hedge(self):
        # entry ask 2000.25, SL 1996.0 (risk 4.25, trigger 2.125); bar 1 hedges SELL 0.5 at 1997.9 - 0.05 = 1997.85
        base = [m1(0, 2000, 2000.1, 1999.9, 2000), m1(1, 2000.0, 2000.0, 1997.9, 1998.0)]
        tr = self.sim(base + [m1(2, 1997.5, 1997.6, 1990.0, 1990.5)], "BUY", 1996.0)          # stop bar closes 5.5 below the SL
        self.assertEqual(tr["hedge_activations"], 1)
        self.assertAlmostEqual(tr["primary_price"], 1995.95 - 2000.25, places=6)              # stop at the SL - slippage
        # hedge bought back at the ask of the stop moment (1996.0 + spread + slippage), not at close + spread (3.55 in 1.45.0)
        self.assertAlmostEqual(tr["hedge_price"], 0.5 * (1997.85 - 1996.25), places=6)
        tr = self.sim(base + [m1(2, 1994.0, 1994.1, 1990.0, 1990.5)], "BUY", 1996.0)          # gap through the stop: the open
        self.assertAlmostEqual(tr["primary_price"], 1993.95 - 2000.25, places=6)
        self.assertAlmostEqual(tr["hedge_price"], 0.5 * (1997.85 - 1994.25), places=6)

    def test_sell_primary_buy_hedge(self):
        # entry bid 1999.95, SL 2004.0 (risk 4.05); bar 1 hedges BUY 0.5 at ask 2002.2 + 0.05 = 2002.25
        base = [m1(0, 2000, 2000.1, 1999.9, 2000), m1(1, 2000.0, 2002.0, 2000.0, 2001.8)]
        tr = self.sim(base + [m1(2, 2002.5, 2010.0, 2002.4, 2009.5)], "SELL", 2004.0)
        self.assertEqual(tr["hedge_activations"], 1)
        self.assertAlmostEqual(tr["primary_price"], 1999.95 - 2004.05, places=6)
        self.assertAlmostEqual(tr["hedge_price"], 0.5 * (2003.75 - 2002.25), places=6)        # bid of the stop moment - slippage (3.6 before)


# ============================================================================================ sh/replay.py (chunk_30#13)
class TestReplayReportWithoutTrades(unittest.TestCase):
    def test_rates_are_none_not_zero(self):
        from masterquo.sh import replay as RP
        res = {"counts": {}, "reasons": {}, "trades": [], "variants": {"NO_HEDGE": [], "REDUCE": [], "HEDGE": []}, "samples": [], "baseline": []}
        rep = RP.report(res, "SCALPING")
        self.assertEqual(rep["hit_rates"], {"TP1": None, "TP2": None, "TP3": None, "event_TP2_before_SL_in_horizon": None})
        self.assertIsNone(RP.report(res, "HEDGING")["hedge_activation_share"])
        tr = {"status": "DONE", "net_r": 1.0, "t": 0, "legs_done": ["TP1", "TP2"], "label_tp2_before_sl": 1}   # with trades: unchanged
        rep = RP.report(dict(res, trades=[tr, dict(tr, legs_done=["TP1"], label_tp2_before_sl=0)]), "SCALPING")
        self.assertEqual(rep["hit_rates"], {"TP1": 1.0, "TP2": 0.5, "TP3": 0.0, "event_TP2_before_SL_in_horizon": 0.5})
        h = {"status": "DONE", "net_r": 0.5, "t": 0, "hedge_activations": 1}
        self.assertEqual(RP.report(dict(res, variants={"NO_HEDGE": [], "REDUCE": [], "HEDGE": [h, dict(h, hedge_activations=0)]}),
                                   "HEDGING")["hedge_activation_share"], 0.5)


# ============================================================================================ sh/service.py (chunk_31#14, chunk_31#16)
class Arc:
    def __init__(self):
        self.calls = []

    def record_sh(self, su, risk, mode, account_key, coord=None):          # returns no record (as with the coordinator disabled)
        self.calls.append((su["signal_id"], coord))


class ServiceCycle(unittest.TestCase):
    def setUp(self):
        from test_sh_service import NOW, Bridge, Log, Modes
        self.td = TempData()
        self.addCleanup(self.td.close)
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.sh import config as C
        from masterquo.sh.service import SHService
        self.now = NOW
        self.bridge = Bridge(None, "HEDGING")
        self.svc = SHService(ConfigStore(), self.bridge, Database(), None, Log(), Modes("SIGNALS"), clock=lambda: NOW)
        self.svc.arc = Arc()
        self.shc = C.load()
        self.spec = self.svc.spec(self.svc.account())
        self.ex = self.svc.executor(self.spec)

    def cycle(self, setups, snapshot=None, risk=None):
        from masterquo.sh import service as S
        q = {"bid": 2000.0, "ask": 2000.2, "spread": 0.2, "age_s": 0.3, "time": self.now}
        bars = {tf: [] for tf in ("M1", "M5", "M15", "H1")}
        with mock.patch.object(S.CX, "snapshot", side_effect=snapshot or (lambda *a, **k: {"vol": {"atr_m5": 1.5}})), \
             mock.patch.object(S.SU, "evaluate", side_effect=lambda strat, *a, **k: dict(setups[strat])), \
             mock.patch.object(S.RK, "evaluate", return_value=risk):
            return self.svc.cycle("XAUUSD", bars, q, self.spec, self.svc.account(), "SIGNALS", self.now, self.shc, self.ex)

    def setups(self, side_s="BUY", side_h="SELL", st_h="READY"):
        from test_sh_service import mk_setup
        s = mk_setup(self.spec, "SCALPING", side_s, ref=2000.2, now=self.now)
        h = mk_setup(self.spec, "HEDGING", side_h, ref=2000.0, now=self.now)
        h["status"] = st_h
        return {"SCALPING": s, "HEDGING": h}

    def test_decision_record_gets_the_coordinator_result(self):
        """coord is keyed by signal_id; coord.get(strat) was always None, so a coordinator WAIT was recorded as an allowed entry."""
        su = self.setups()                                                           # opposite READY directions -> both WAIT
        self.cycle(su)
        got = dict(self.svc.arc.calls)
        for strat in ("SCALPING", "HEDGING"):
            c = got[su[strat]["signal_id"]]
            self.assertIsNotNone(c, strat)
            self.assertEqual((c["decision"], c["allowed"]), ("WAIT", False))
            self.assertIn("przeciwne kierunki", c["reason"])
        self.svc.arc.calls.clear()
        self.svc.last_saved.clear()
        su = self.setups(st_h="NO_TRADE")                                           # one READY -> PROCEED (recorded as allowed)
        block = {"status": "BLOCK", "checks": [], "warnings": [], "reasons": ["test"], "volume": 0.0, "legs": []}
        evals = self.cycle(su, risk=block)
        c = dict(self.svc.arc.calls)[su["SCALPING"]["signal_id"]]
        self.assertEqual((c["decision"], c["allowed"]), ("PROCEED", True))
        self.assertEqual(evals["SCALPING"]["risk"]["status"], "BLOCK")              # entries still follow the coordinator + risk
        self.assertEqual(self.svc.store.db.query("SELECT plan_id FROM sh_plans"), [])

    def test_snapshot_cache_keeps_only_the_current_session_epoch(self):
        seen = []

        def snap(*a, cache=None, **k):
            cache["used"] = True
            seen.append(cache)
            return {"vol": {"atr_m5": 1.5}}
        su = self.setups(st_h="NO_TRADE")
        su["SCALPING"]["status"] = "NO_TRADE"
        for ep in (1, 2, 3, 3):                                                      # reconnects: the epoch only grows
            self.bridge.session_epoch = ep
            self.cycle(su, snapshot=snap)
        self.assertEqual(list(self.svc.snap_cache), [("XAUUSD", 3)])                 # 1.45.0: one heavy cache per reconnect, never freed
        self.assertIs(seen[2], seen[3])                                              # the current epoch's cache is reused unchanged
        self.assertIsNot(seen[1], seen[2])


# ============================================================================================ sh/tpmodel.py (chunk_31#12)
class TestPromoteRequiresKnownRealData(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.addCleanup(self.td.close)

    @staticmethod
    def samples(n, seed):
        import numpy as np
        from masterquo.sh.tpmodel import FEATURES
        rng = np.random.default_rng(seed)
        X = rng.normal(size=(n, len(FEATURES)))
        y = (rng.random(n) < 1 / (1 + np.exp(-2.5 * X[:, 0]))).astype(int)
        return [{"t": 1_760_000_000 + 600 * i, "x": X[i].tolist(), "y": int(y[i])} for i in range(n)]

    def train(self, strat, provenance, seed=3):
        from masterquo.sh import tpmodel as TM
        rec = TM.train("XAUUSD", strat, self.samples(1500, seed), embargo_s=1800, log=lambda *_: None, allow_promotion=False,
                       provenance=provenance)
        self.assertEqual(rec["verdict"], "HOLDOUT_PASSED")
        return rec

    def test_unknown_data_kind_is_not_promoted(self):
        from masterquo.sh import tpmodel as TM
        # train_cli on a dataset without data_kind: treated as non-real there (--allow-synthetic, no promotion) -> NOT_VERIFIED here too
        rec = self.train("SCALPING", {"dataset_id": "D1", "data_kind": None, "config_hash": "h", "symbol": "XAUUSD-"})
        with self.assertRaises(ValueError):
            TM.promote("XAUUSD", "SCALPING", rec["run_id"])
        self.assertIsNone(TM.status("XAUUSD", "SCALPING").get("version"))
        # an imported run without provenance (unknown origin) is never promoted either
        run = {k: v for k, v in rec.items() if k != "provenance"}
        npz = (TM.root("XAUUSD", "SCALPING") / f"{rec['run_id']}.npz").read_bytes()
        self.assertTrue(TM.import_run("XAUUSD", "HEDGING", run, npz)["imported"])
        with self.assertRaises(ValueError):
            TM.promote("XAUUSD", "HEDGING", rec["run_id"])
        self.assertIsNone(TM.status("XAUUSD", "HEDGING").get("version"))

    def test_real_data_and_legacy_local_runs_still_promote(self):
        from masterquo.sh import tpmodel as TM
        real = self.train("SCALPING", {"dataset_id": "D2", "data_kind": "REAL_USER_DATA"})
        self.assertEqual(TM.promote("XAUUSD", "SCALPING", real["run_id"]), {"active": real["run_id"], "changed": True})
        legacy = self.train("HEDGING", None, seed=4)                                 # no provenance record at all (older versions)
        self.assertTrue(TM.promote("XAUUSD", "HEDGING", legacy["run_id"])["changed"])
        with self.assertRaises(ValueError):                                          # declared test data: refused as before
            TM.promote("XAUUSD", "SCALPING", self.train("SCALPING", {"data_kind": "SYNTHETIC_TEST"}, seed=5)["run_id"])


if __name__ == "__main__":
    unittest.main()
