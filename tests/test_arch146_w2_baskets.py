"""Fala 2b, grupa „baskets” (backend/masterquo/baskets: service.py, hedge.py, rules.py; usunięte otc.py / payoff.py).

I0539 pole quant_event_id (alias p_event), I0112 usunięty nieosiągalny kod OTC, I0718 setup_score – tylko wariant informacyjny,
I0762 _fx_parent bez pozycji z innego symbolu, I0763 limit warstw ochrony FX (max_layers), I0764 CRYPTO HEDGE_PLAN bez pustej ilości,
I0765 ΔOI na zamknięciu świecy sygnałowej, I0767 cache świec Hyperliquid z liczbą świec, I0768 seria CRYPTO 600 świec,
I0769 max_pending_intents w jednym cyklu, I0850 CP_SCALP_03 – przecięcia VWAP w 10 świecach.

Testy jednostkowe: bez sieci (FakeHL), bez MT5, osobny folder danych na test."""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import tempfile
import time
import types
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import _env  # noqa: F401  (sys.path, MQ_BASKETS_OFFLINE)
import numpy as np

TF_S = {"M1": 60, "M3": 180, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}


def _rt(**kw):
    return types.SimpleNamespace(**{"demo": True, "bridge": None, "db": None, "bus": None, "quant": None, "news": None, **kw})


def _walk(n: int, *, end_t: float, step: float, seed: int = 5, start: float = 2000.0, sd: float = 1.5) -> list[dict]:
    rng = np.random.default_rng(seed)
    c = start + np.cumsum(rng.normal(0, sd, n))
    out = []
    for k in range(n):
        o = c[k - 1] if k else c[0]
        out.append({"t": end_t - (n - 1 - k) * step, "o": float(o), "h": float(max(o, c[k]) + 0.5), "l": float(min(o, c[k]) - 0.5),
                    "c": float(c[k]), "tv": 1.0})
    return out


class FakeHL:
    errors = 0
    last_error = None

    def __init__(self):
        core = {"native_id": None, "dex": "core", "szDecimals": 3, "maxLeverage": 20, "delisted": False, "namespace": "Hyperliquid core"}
        self.cat = {"BTC": {**core, "native_id": "BTC"}, "ETH": {**core, "native_id": "ETH"}, "SOL": {**core, "native_id": "SOL"}}
        self.calls: list[tuple] = []
        self.fail = False

    def catalog(self):
        return self.cat

    def contexts(self):
        return {}

    def flow(self, coin):
        return {"t": time.time(), "connected": True}

    def candles(self, coin, tf, n=500):
        from masterquo.baskets.hyperliquid import HLError
        self.calls.append((coin, tf, n))
        if self.fail:
            raise HLError("offline")
        sec = TF_S[tf]
        last = (time.time() // sec) * sec - sec
        return [{"t": last - (n - 1 - k) * sec, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "v": 1.0, "trades": 1} for k in range(n)]


class _Svc(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.d = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def svc(self, **rt):
        from masterquo.baskets import service as BS
        return BS.BasketService(_rt(**rt), data_dir=self.d, hl=FakeHL())

    def write(self, name, obj):
        (self.d / name).write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


# ======================================================================================================================== I0539
class TestQuantEventIdField(_Svc):
    """BasketService._quant: 'p_event' held the Quant event id (text), not a probability -> 'quant_event_id' (+ alias for one version)."""

    PLAN = {"plan_type": "PositionPlan", "side": "LONG", "entry_ref": 2000.0, "sl": 1990.0, "targets": [{"price": 2020.0, "weight": 1.0}],
            "timeout_bars": 8, "timeframe": "M5", "risk_per_unit": 10.0}

    def _quant(self):
        return types.SimpleNamespace(instrument=lambda: "XAUUSD",
                                     assess=lambda cd, log_row=False: {"confidence": {"p_event_raw": 0.61, "state": "OK"},
                                                                       "event": {"event_id": "TP1_BEFORE_STOP"}})

    def test_event_id_named_as_such_alias_kept_score_unchanged(self):
        from masterquo.baskets import catalog as CAT
        strat = CAT.BY_ID["FX_SMC_01"]
        s = self.svc(quant=self._quant())
        c = s._context("FOREX_MT5", "XAUUSD", "MT5", "SYNTHETIC", "1", "CFD")
        out = s._scores(c, strat, None, 1, {}, dict(self.PLAN))
        self.assertEqual(out.get("quant_event_id"), "TP1_BEFORE_STOP")
        self.assertEqual(out["p_event"], out["quant_event_id"])                       # alias (rows / readers of 1.46.0), same value
        self.assertEqual(out["p_event_raw"], 0.61)
        self.assertEqual(out["confidence_state"], "OK")
        base = self.svc()._scores(c, strat, None, 1, {}, dict(self.PLAN))              # without Quant: setup_score is the same
        self.assertEqual(out["setup_score"], base["setup_score"])
        self.assertEqual(out["setup_components"], base["setup_components"])


# ======================================================================================================================== I0112
class TestRetiredOtcCodeRemoved(_Svc):
    def test_every_planner_is_reachable_from_the_active_catalog(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import hedge as HG
        active = {s["family_id"] for s in CAT.CATALOG if s["kind"] == "HEDGING"}
        self.assertLessEqual(set(HG.PLANNERS), active, sorted(set(HG.PLANNERS) - active))
        self.assertEqual(set(HG.PLANNERS), active)                                     # every active hedge strategy still has its planner

    def test_otc_feed_and_payoff_modules_are_gone(self):
        self.assertIsNone(importlib.util.find_spec("masterquo.baskets.otc"))
        self.assertIsNone(importlib.util.find_spec("masterquo.baskets.payoff"))

    def test_service_and_cycle_never_touch_the_stored_otc_history(self):
        otc = self.d / "otc"
        otc.mkdir()
        (otc / "ticks.jsonl").write_text("[1700000000.0, 2000.5]\n", encoding="utf-8")
        (otc / "meta.json").write_text('{"payout": {"CALL": 0.8}}', encoding="utf-8")
        before = {p.name: p.read_bytes() for p in otc.iterdir()}
        s = self.svc()
        self.assertFalse(hasattr(s, "otc"))                                            # no OTC feed object at all (was a lazy reader)
        s.update_settings({"profiles": {"CRYPTO_FOMO_PERPS": {"enabled": False}}})
        s.cycle()
        self.assertEqual({p.name: p.read_bytes() for p in otc.iterdir()}, before)      # user data on disk untouched, nothing created
        self.assertEqual(s.status()["otc_feed"], {"state": "RETIRED", "reason": "RETIRED_PROFILE", "history": "READ_ONLY"})

    def test_retired_labels_stay(self):
        from masterquo.baskets import catalog as CAT
        self.assertEqual(len(CAT.HISTORICAL_STRATEGIES), 30)
        self.assertTrue(CAT.retired_reason("OTC_HEDGE_01"))


# ======================================================================================================================== I0718
class TestSetupScoreInformationalOnly(_Svc):
    """Safe variant only: setup_score (ranking, SH score, Quant ctx:heuristic_score) is computed exactly as before; the missing HTF
    context and the constant components are shown next to it."""

    def _plan(self, rr):
        return {"plan_type": "PositionPlan", "side": "LONG", "entry_ref": 100.0, "sl": 99.0, "targets": [{"price": 100.0 + rr, "weight": 1.0}],
                "timeout_bars": 8, "timeframe": "M5", "risk_per_unit": 1.0}

    def test_missing_htf_is_flagged_and_score_is_unchanged(self):
        from masterquo.baskets import catalog as CAT
        s = self.svc()
        c = s._context("FOREX_MT5", "XAUUSD", "MT5", "SYNTHETIC", "1", "CFD")
        strat = CAT.BY_ID["FX_SMC_01"]                                                  # context M15 / H1 declared, none loaded
        out = s._scores(c, strat, None, 1, {}, self._plan(1.0))
        room = min(25.0, 12.5 * 1.0)
        self.assertEqual(out["setup_score"], round(100 * (0 + room + 25 + 25) / 100, 1))  # 1.46.0 formula (missing HTF = 0)
        self.assertEqual(out["setup_components"], {"htf_alignment": 0, "room": room, "confirmation": 25, "data": 25})
        self.assertEqual(out.get("setup_flags"), ["DATA_INCOMPLETE"])
        basis = out["setup_components_basis"]
        self.assertEqual(basis["htf_alignment"], "MISSING_CONTEXT")
        self.assertTrue(basis["confirmation"].startswith("CONSTANT_25"))
        self.assertTrue(basis["data"].startswith("CONSTANT_25"))
        self.assertEqual(out["setup_score_measured"], round(100 * room / 25, 1))      # measured components only (room), informational

    def test_htf_present_no_flag_and_measured_score_includes_it(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import detectors as D
        s = self.svc()
        c = s._context("FOREX_MT5", "XAUUSD", "MT5", "SYNTHETIC", "1", "CFD")
        H = D.build(_walk(300, end_t=1.79e9, step=900), 0.01)
        c.feats["M15"] = H
        strat = CAT.BY_ID["FX_SMC_01"]
        side = H.trend()[0] or 1
        plan = {**self._plan(2.0), "side": "LONG" if side > 0 else "SHORT"}
        out = s._scores(c, strat, None, side, {}, plan)
        htf = 25 if H.trend()[0] == side else 0
        self.assertEqual(out["setup_components"]["htf_alignment"], htf)
        self.assertEqual(out["setup_score"], round(100 * (htf + 25 + 25 + 25) / 100, 1))
        self.assertEqual(out["setup_flags"], [])
        self.assertEqual(out["setup_score_measured"], round(100 * (htf + 25) / 50, 1))

    def test_ranking_of_the_event_group_is_unchanged(self):
        """Two strategies of one event: the one without HTF context keeps losing exactly as in 1.46.0 (score unchanged)."""
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import detectors as D
        s = self.svc()
        st = s.settings()
        c = s._context("FOREX_MT5", "XAUUSD", "MT5", "SYNTHETIC", "1", "CFD")
        c.regime = {"regime": "TREND"}
        F = D.build(_walk(300, end_t=1.79e9, step=300), 0.01)
        H = D.build(_walk(300, end_t=1.79e9, step=900, seed=9), 0.01)
        side = H.trend()[0] or 1
        c.feats["M15"] = H                                                              # FX_SMC_01 / 02: M15 context present
        ev = {"type": "BOS", "level": float(F.c[F.i - 3]), "t": float(F.t[F.i - 3])}
        r = {"entry": float(F.c[F.i]), "sl": float(F.c[F.i]) - side * 5.0, "event": ev}
        no_htf = CAT.BY_ID["FX_SMC_10"]                                                  # M5, context H1 (not loaded)
        self.assertEqual(no_htf["context_timeframes"], ["H1"])
        found = [(no_htf, F, side, dict(r), s.params(no_htf, st)), (CAT.BY_ID["FX_SMC_01"], F, side, dict(r), s.params(CAT.BY_ID["FX_SMC_01"], st))]
        sc = {x[0]["strategy_id"]: s._scores(c, x[0], F, side, x[3], s._plan(c, x[0], F, side, x[3], x[4], st, {})) for x in found}
        room = sc["FX_SMC_10"]["setup_components"]["room"]
        self.assertEqual(sc["FX_SMC_10"]["setup_score"], round(100 * (0 + room + 25 + 25) / 100, 1))     # 1.46.0 formula: missing HTF = 0
        self.assertEqual(sc["FX_SMC_10"]["setup_flags"], ["DATA_INCOMPLETE"])
        s._resolve(c, found, st, {})
        sig = s.ledger.open_signals("FOREX_MT5")
        self.assertEqual(len(sig), 1)
        expected = sorted(sc, key=lambda k: -sc[k]["setup_score"])[0]                  # stable sort in found order, as _resolve ranks
        self.assertEqual(sig[0]["strategy_id"], expected)
        self.assertEqual(sig[0]["scores"]["setup_score"], sc[expected]["setup_score"])


if __name__ == "__main__":
    unittest.main()
