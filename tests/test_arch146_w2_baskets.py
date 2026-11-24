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


# ======================================================================================================================== I0762
def _fx_ctx(F, H, exposure, symbol="XAUUSD", **kw):
    spec = {sym: {"trade_contract_size": 100, "volume_step": 0.01, "volume_min": 0.01, "spread_price": 0.2, "spread_median_price": 0.05}
            for sym in ("XAUUSD", "EURUSD")}
    return {"strategy": {"exit_policy_or_expiry_policy": "x"}, "p": {"ratio": 0.5, "timeout_bars": 6, "max_layers": 1, "pct": 0.95, "lookback": 200,
                                                                        "partner": "XAGUSD"},
            "F": F, "htf": H, "symbol": symbol, "exposure": exposure, "account": {"margin_mode": "HEDGING", "currency": "USD"}, "spec": spec,
            "events": [{"t": time.time() + 60, "currency": "EUR", "title": "CPI"}, {"t": time.time() + 60, "currency": "XAU", "title": "x"}],
            "now": time.time(), "bars": {}, **kw}


def _shock_bars(n=260, end_t=1.79e9, extra=0):
    bars = [{"t": end_t - (n - 1 - k) * 60, "o": 100.0, "h": 100.5, "l": 99.5, "c": 100.0, "tv": 1.0} for k in range(n)]
    for j in range(extra + 1):                                                          # last bar(s): huge bearish range (shock against LONG)
        bars[-1 - j] = {**bars[-1 - j], "o": 100.0, "h": 101.0, "l": 89.0, "c": 90.0 - (extra - j)}
    return bars


class TestFxParentOwnSymbolOnly(unittest.TestCase):
    def _state(self, fn, ctx):
        from masterquo.baskets.rules import Unavailable
        try:
            return fn(ctx)["state"]
        except Unavailable as exc:
            return f"UNAVAILABLE: {exc}"

    def test_position_on_another_symbol_is_no_exposure(self):
        from masterquo.baskets import detectors as D
        from masterquo.baskets import hedge as HG
        F = D.build(_shock_bars(), 0.01)
        H = D.build(_walk(300, end_t=1.79e9, step=3600), 0.01)
        other = [{"leg": "PRIMARY", "symbol": "EURUSD", "side": "LONG", "volume": 1.0, "id": "P2", "entry": 1.0}]
        ctx = _fx_ctx(F, H, other)
        self.assertIsNone(HG._fx_parent(ctx))
        for fn in (HG.structural_choch, HG.range_profit, HG.vol_shock, HG.session_transition, HG.mtf_countermove, HG.event_shield, HG.beta_pair,
                   HG.pair_relative):
            self.assertEqual(self._state(fn, ctx), "NO_EXPOSURE", fn.__name__)

    def test_own_symbol_position_is_still_the_parent(self):
        from masterquo.baskets import detectors as D
        from masterquo.baskets import hedge as HG
        F = D.build(_shock_bars(), 0.01)
        exp = [{"leg": "PRIMARY", "symbol": "EURUSD", "side": "LONG", "volume": 1.0, "id": "P2"},
               {"leg": "PRIMARY", "symbol": "XAUUSD", "side": "LONG", "volume": 1.0, "id": "P1"}]
        ctx = _fx_ctx(F, None, exp)
        self.assertEqual(HG._fx_parent(ctx)["id"], "P1")
        self.assertEqual(HG.vol_shock(ctx)["state"], "HEDGE_PLAN")                     # trigger fires on the bot's own symbol as before


# ======================================================================================================================== I0763
class TestFxHedgeLayers(_Svc):
    PRIMARY = {"leg": "PRIMARY", "symbol": "XAUUSD", "side": "LONG", "volume": 1.0, "id": "P1", "entry": 100.0}
    HEDGE = {"leg": "HEDGE", "symbol": "XAUUSD", "side": "SHORT", "volume": 0.5, "id": "P1", "entry": 100.0}

    def test_open_hedge_leg_of_the_parent_uses_the_single_layer(self):
        from masterquo.baskets import detectors as D
        from masterquo.baskets import hedge as HG
        F = D.build(_shock_bars(), 0.01)
        ctx = _fx_ctx(F, None, [dict(self.PRIMARY), dict(self.HEDGE)])
        r = HG.vol_shock(ctx)
        self.assertEqual(r["state"], "NO_HEDGE", r)
        r = HG._fx_same_symbol(ctx, dict(self.PRIMARY), "test")                         # common point of the same-symbol FX planners
        self.assertEqual(r["state"], "NO_HEDGE", r)
        self.assertIn("max_layers", r["reason"])
        ctx["p"]["max_layers"] = 2                                                       # the parameter is respected (2nd layer allowed) ...
        self.assertEqual(HG._fx_same_symbol(ctx, dict(self.PRIMARY), "test")["state"], "HEDGE_PLAN")
        self.assertEqual(HG.vol_shock(ctx)["state"], "NO_HEDGE")                        # ... the volatility shield stays one-time (catalog)
        ctx = _fx_ctx(F, None, [dict(self.PRIMARY), {**self.HEDGE, "id": "OTHER"}])     # a hedge leg of ANOTHER parent does not count
        self.assertEqual(HG.vol_shock(ctx)["state"], "HEDGE_PLAN")

    def test_beta_pair_respects_the_layer_limit(self):
        from masterquo.baskets import hedge as HG
        rng = np.random.default_rng(7)
        n, t0 = 200, 1.79e9
        rh = rng.normal(0, 0.004, n)
        rp = 1.5 * rh + rng.normal(0, 0.0002, n)
        ph, pp = 25.0 * np.exp(np.cumsum(rh)), 2000.0 * np.exp(np.cumsum(rp))
        bars = {"XAUUSD": {"M15": [{"t": t0 + k * 900, "c": float(pp[k])} for k in range(n)]},
                "XAGUSD": {"M15": [{"t": t0 + k * 900, "c": float(ph[k])} for k in range(n)]}}
        spec = {"XAUUSD": {"trade_contract_size": 100, "volume_step": 0.01, "volume_min": 0.01},
                "XAGUSD": {"trade_contract_size": 5000, "volume_step": 0.01, "volume_min": 0.01}}
        ctx = {"strategy": {"exit_policy_or_expiry_policy": "x"}, "p": {"partner": "XAGUSD", "ratio": 0.5, "max_layers": 1}, "symbol": "XAUUSD",
               "exposure": [dict(self.PRIMARY)], "bars": bars, "spec": spec}
        self.assertEqual(HG.beta_pair(ctx)["state"], "HEDGE_PLAN")
        ctx["exposure"].append(dict(self.HEDGE))
        r = HG.beta_pair(ctx)
        self.assertEqual(r["state"], "NO_HEDGE", r)
        self.assertIn("max_layers", r["reason"])

    def test_layers_used_as_dict_per_parent_no_type_error(self):
        from masterquo.baskets import detectors as D
        from masterquo.baskets import hedge as HG
        F = D.build(_shock_bars(), 0.01)
        ctx = _fx_ctx(F, None, [dict(self.PRIMARY)], layers_used={"P1": 1})
        self.assertEqual(HG.vol_shock(ctx)["state"], "NO_HEDGE")
        ctx = _fx_ctx(F, None, [dict(self.PRIMARY)], layers_used={"OTHER": 3})
        self.assertEqual(HG.vol_shock(ctx)["state"], "HEDGE_PLAN")

    def test_recent_proposal_for_the_parent_blocks_the_next_one(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import detectors as D
        s = self.svc()
        st = s.settings()
        strat = CAT.BY_ID["FX_HEDGE_03"]                                                # vol_shock, M1
        c = s._context("FOREX_MT5", "XAUUSD", "MT5", "SYNTHETIC", "1", "CFD")
        extra = {"account": {"margin_mode": "HEDGING", "currency": "USD"}, "spec": _fx_ctx(None, None, [])["spec"],
                 "exposure": [dict(self.PRIMARY)], "fx_pairs": [], "pair_map": {}, "symbol": "XAUUSD", "events": None}
        c.feats["M1"] = D.build(_shock_bars(end_t=time.time()), 0.01)
        s._hedge(c, strat, st, extra)
        self.assertEqual(s.hedge_state["FX_HEDGE_03"]["state"], "HEDGE_PLAN")
        c.feats["M1"] = D.build(_shock_bars(end_t=time.time() + 60, extra=1), 0.01)  # next bar: the shock goes on
        s._hedge(c, strat, st, extra)
        self.assertEqual(s.hedge_state["FX_HEDGE_03"]["state"], "NO_HEDGE", s.hedge_state["FX_HEDGE_03"])
        with sqlite3.connect(s.ledger.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM hedge_plans").fetchone()[0], 1)
            # outside the plan window (timeout_bars x TF) the old proposal no longer counts as a used layer
            db.execute("UPDATE hedge_plans SET created_at = created_at - 3600")
        db.close()
        c.feats["M1"] = D.build(_shock_bars(end_t=time.time() + 120, extra=2), 0.01)
        s._hedge(c, strat, st, extra)
        self.assertEqual(s.hedge_state["FX_HEDGE_03"]["state"], "HEDGE_PLAN")


# ======================================================================================================================== I0764
class TestCryptoHedgeQuantityBelowPrecision(unittest.TestCase):
    """A quantity rounded to zero (szDecimals) -> NO_HEDGE with the reason, never a HEDGE_PLAN with size None."""

    def _base(self, exposure, bars, **p):
        return {"strategy": {"exit_policy_or_expiry_policy": "x"}, "p": {"ratio": 0.5, "timeout_bars": 6, **p}, "exposure": exposure,
                "spec": {k: {"szDecimals": 0} for k in ("BTC", "ETH", "SOL", "BTC2")}, "bars": bars, "fees": {"taker": None}, "funding": {}}

    def _check(self, r):
        self.assertEqual(r["state"], "NO_HEDGE", r)
        self.assertIn("precyzji", r["reason"])

    def test_spot_inventory(self):
        from masterquo.baskets import hedge as HG
        self._check(HG.spot_inventory(self._base([{"kind": "SPOT", "instrument": "BTC", "size": 0.001}], {"BTC": {"M15": [{"t": 0, "c": 100.0}]}})))

    def test_cross_market(self):
        from masterquo.baskets import hedge as HG
        ctx = self._base([{"kind": "PERP", "instrument": "BTC", "side": "LONG", "size": 0.001}],
                         {"BTC": {"M15": [{"t": 0, "c": 100.0}]}, "BTC2": {"M15": [{"t": 0, "c": 100.0}]}})
        ctx["same_underlying"] = {"BTC": "BTC2"}
        self._check(HG.cross_market(ctx))

    def test_stress_loss(self):
        from masterquo.baskets import hedge as HG
        self._check(HG.stress_loss(self._base([{"kind": "PERP", "instrument": "BTC", "side": "LONG", "size": 0.001}],
                                              {"BTC": {"M15": [{"t": 0, "c": 100.0}]}}, loss_limit=0.0)))

    def test_basket_beta(self):
        from masterquo.baskets import hedge as HG
        end = 1.79e9
        bars = {k: {"M15": _walk(200, end_t=end, step=900, seed=sd, start=100.0, sd=0.3)} for k, sd in (("BTC", 1), ("ETH", 2), ("SOL", 3))}
        exp = [{"kind": "PERP", "instrument": "ETH", "side": "LONG", "size": 0.001}, {"kind": "PERP", "instrument": "SOL", "side": "LONG", "size": 0.001}]
        self._check(HG.basket_beta(self._base(exp, bars, limit_usd=0.0)))

    def test_residual_pair(self):
        from masterquo.baskets import hedge as HG
        rng = np.random.default_rng(4)
        end, n = 1.79e9, 200
        le = np.log(100.0) + np.cumsum(rng.normal(0, 0.01, n))
        ls = 0.3 + 0.8 * le + rng.normal(0, 0.001, n)
        ls[-1] += 0.05                                                                  # SOL far above its relation: residual z >> 2
        mk = lambda lg: [{"t": end - (n - 1 - k) * 900, "c": float(np.exp(lg[k]))} for k in range(n)]   # noqa: E731
        ctx = self._base([{"kind": "PERP", "instrument": "SOL", "side": "LONG", "size": 0.001}], {"SOL": {"M15": mk(ls)}, "ETH": {"M15": mk(le)}},
                         pairs={"SOL": "ETH"})
        self._check(HG.residual_pair(ctx))

    def test_a_real_quantity_is_unchanged(self):
        from masterquo.baskets import hedge as HG
        ctx = self._base([{"kind": "SPOT", "instrument": "BTC", "size": 10.0}], {"BTC": {"M15": [{"t": 0, "c": 100.0}]}})
        r = HG.spot_inventory(ctx)
        self.assertEqual(r["state"], "HEDGE_PLAN")
        self.assertEqual(r["plan"]["legs"][0]["size"], 5.0)


# ======================================================================================================================== I0765
class _MitF:
    """Feat double that reaches the OI branch of second_mitigation: BOS + displacement at 16, OB 99-100 (k=15), one retest at 17,
    fresh BOS at 18, confirmed retest at the signal bar 20."""

    def __init__(self, t_open_last, step):
        self.n, self.i = 21, 20
        self.t = np.array([t_open_last - (20 - k) * step for k in range(21)], dtype=float)
        self.c = np.full(21, 100.5)
        self.h, self.l, self.o = self.c + 0.5, self.c - 0.5, self.c - 0.2

    def b(self, i=None):
        return 0.1

    def structure_break(self, k, s):
        return k in (16, 18)

    def displacement(self, k, s, *a):
        return k in (16, 18)

    def order_block(self, k, s):
        return {"k": 15, "lo": 99.0, "hi": 100.0, "mid": 99.5, "side": s}

    def touched(self, k, lo, hi):
        return k == 17

    def confirmed_retest(self, k, lo, hi, s, inval):
        return True


class _ExpF:
    """Feat double for oi_expansion: close 101 above HH20 = 100 + b, RVOL 2."""

    def __init__(self, t_open_last, step):
        self.n, self.i = 30, 29
        self.t = np.array([t_open_last - (29 - k) * step for k in range(30)], dtype=float)
        self.c = np.full(30, 101.0)
        self.h, self.l = self.c + 0.5, np.full(30, 100.0)

    def b(self, i=None):
        return 0.1

    def HH(self, n, i=None):
        return 100.0

    def LL(self, n, i=None):
        return 90.0

    def rvol(self, i):
        return 2.0


class _Up:
    def trend(self, i=None):
        return 1, "test"


class TestOiDeltaAtSignalClose(_Svc):
    T = 1.79e9

    def test_second_mitigation_uses_the_close_of_the_m15_candle(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import rules as R
        T = self.T
        p = CAT.BY_ID["CP_SMC_06"]["parameter_schema"]
        oi = [(T - 600, 100.0), (T - 300, 100.0), (T, 100.0), (T + 600, 105.0), (T + 900, 110.0)]   # OI rises inside the signal candle
        r = R.second_mitigation(_MitF(T, 900), 1, p, {"oi": oi, "now": T + 905, "tf_s": 900})
        self.assertIsNotNone(r)                                                            # ΔOI(close) = 110 - 105 > 0 (was ΔOI(open) = 0)
        self.assertEqual(r["event"]["type"], "MITIGATION_2")
        # no look-ahead: an OI sample later than "now" is never used
        oi2 = [(T - 300, 100.0), (T, 100.0), (T + 600, 100.0), (T + 900, 120.0)]
        self.assertIsNone(R.second_mitigation(_MitF(T, 900), 1, p, {"oi": oi2, "now": T + 700, "tf_s": 900}))
        # without the candle length (direct caller) the 1.46.0 reference time is kept (open of the candle)
        self.assertIsNone(R.second_mitigation(_MitF(T, 900), 1, p, {"oi": oi, "now": T + 905}))

    def test_oi_expansion_uses_the_close_of_the_m5_candle(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import rules as R
        T = self.T
        p = CAT.BY_ID["CP_SCALP_10"]["parameter_schema"]
        oi = [(T - 300, 100.0), (T, 100.0), (T + 60, 100.0), (T + 240, 104.0), (T + 300, 108.0)]
        r = R.oi_expansion(_ExpF(T, 300), 1, p, {"htf": _Up(), "oi": oi, "now": T + 305, "tf_s": 300})
        self.assertIsNotNone(r)
        self.assertEqual(r["conditions"]["d_oi_5m_contracts"], 8.0)                      # 108 (close) - 100 (close - 5 min)
        self.assertIsNone(R.oi_expansion(_ExpF(T, 300), 1, p, {"htf": _Up(), "oi": oi, "now": T + 305}))   # legacy +60 s without tf_s

    def test_fx_smc_06_path_is_unchanged(self):
        """FX_SMC_06 shares second_mitigation but has no oi_delta: the OI branch is never entered, with or without tf_s."""
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import detectors as D
        from masterquo.baskets import rules as R
        p = CAT.BY_ID["FX_SMC_06"]["parameter_schema"]
        self.assertFalse(p.get("oi_delta"))

        def boom(*a, **k):
            raise AssertionError("oi_delta called on the FX path")
        with mock.patch.object(R, "oi_delta", boom):
            for seed in range(25):
                F = D.build(_walk(400, end_t=self.T, step=900, seed=seed), 0.01)
                for side in (1, -1):
                    a = R.second_mitigation(F, side, p, {"oi": [], "now": self.T + 900})
                    b = R.second_mitigation(F, side, p, {"oi": [], "now": self.T + 900, "tf_s": 900})
                    self.assertEqual(a, b)
            self.assertEqual(R.second_mitigation(_MitF(self.T, 900), 1, p, {"tf_s": 900})["event"]["type"], "MITIGATION_2")

    def test_service_passes_the_signal_candle_length(self):
        from masterquo.baskets import rules as R
        self.write("settings.json", {"profiles": {"CRYPTO_FOMO_PERPS": {"instruments": ["BTC"], "selection": "MANUAL_SELECT"}},
                                     "manual_select": {"CRYPTO_FOMO_PERPS": ["CP_SMC_06", "CP_SCALP_10"]}})
        s = self.svc()
        seen = {}

        def spy(name):
            def fam(F, side, p, x):
                seen[name] = x.get("tf_s")
            return fam
        with mock.patch.dict(R.FAMILIES, {"second_mitigation": spy("second_mitigation"), "oi_expansion": spy("oi_expansion")}), \
                mock.patch.dict(os.environ):
            os.environ.pop("MQ_BASKETS_OFFLINE", None)
            s._crypto(s.settings())
        self.assertEqual(seen, {"second_mitigation": 900, "oi_expansion": 300})


# ======================================================================================================================== I0769
class TestBasketPendingLimitSameCycle(_Svc):
    def test_two_events_in_one_cycle_respect_max_pending_intents(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import detectors as D
        self.write("settings.json", {"baskets": {"FX_SMC": {"max_pending_intents": 1}}})
        s = self.svc()
        st = s.settings()
        c = s._context("FOREX_MT5", "XAUUSD", "MT5", "SYNTHETIC", "1", "CFD")
        c.regime = {"regime": "TREND"}
        F = D.build(_walk(300, end_t=1.79e9, step=300), 0.01)
        found = []
        for sid, back in (("FX_SMC_01", 3), ("FX_SMC_02", 5)):                          # two different events -> two groups
            ev = {"type": "BOS", "level": float(F.c[F.i - back]), "t": float(F.t[F.i - back])}
            found.append((CAT.BY_ID[sid], F, 1, {"entry": float(F.c[F.i]), "sl": float(F.c[F.i]) - 5.0, "event": ev}, s.params(CAT.BY_ID[sid], st)))
        n = s._resolve(c, found, st, {})
        self.assertEqual(n, 1)
        self.assertEqual(len(s.ledger.open_signals("FOREX_MT5")), 1)
        states = sorted(c.state[x[0]["strategy_id"]]["state"] for x in found)
        self.assertEqual(states, ["LIMIT", "SIGNAL"])

    def test_below_the_limit_both_are_published(self):
        from masterquo.baskets import catalog as CAT
        from masterquo.baskets import detectors as D
        s = self.svc()
        st = s.settings()
        c = s._context("FOREX_MT5", "XAUUSD", "MT5", "SYNTHETIC", "1", "CFD")
        c.regime = {"regime": "TREND"}
        F = D.build(_walk(300, end_t=1.79e9, step=300), 0.01)
        found = []
        for sid, back in (("FX_SMC_01", 3), ("FX_SMC_02", 5)):
            ev = {"type": "BOS", "level": float(F.c[F.i - back]), "t": float(F.t[F.i - back])}
            found.append((CAT.BY_ID[sid], F, 1, {"entry": float(F.c[F.i]), "sl": float(F.c[F.i]) - 5.0, "event": ev}, s.params(CAT.BY_ID[sid], st)))
        self.assertEqual(s._resolve(c, found, st, {}), 2)
        self.assertEqual(s._resolve(c, found, st, {}), 0)                               # same events again: idempotent, nothing new


if __name__ == "__main__":
    unittest.main()
