"""1.46 audit, group B_mq_baskets - regression tests for backend/masterquo/baskets/{hedge,hyperliquid,sfb}.py
(SYNTHETIC_TEST data only, unit level: no network, no demo server, no BasketService thread).

chunk_06#5   _beta_hedge: factor risk before / after = beta x parent notional (+ leg), quote currencies of both legs shown
chunk_06#7   FX hedge plan: no bid/ask -> spread cost None + NO_QUOTE (was 0.0); money in the account currency (tick value)
chunk_06#18  funding_aware: no funding rates at all -> WAITING_FOR_DATA (Unavailable), not a NO_HEDGE market verdict
chunk_06#17  Hyperliquid CAPABILITIES: trades_aggressor follows TASK 004 (NOT_VERIFIED), never True
chunk_07#1   SFB: the evidence source is reported NOT_CONNECTED (status, snapshot, item reason codes) - focus_X2#15 is the same defect
chunk_07#2   SFB: a scope without a capability list is checked against the profile's declared registry (unknown = NOT_VERIFIED)
chunk_07#3   SFB: one selection for every mode (would_keep / hedging_passthrough / bucket_status), SHADOW predicts ASSIST
chunk_07#13  SFB: a snapshot is complete before it is published in `snapshots`
chunk_07#4   SFB: validate_config types / ranges (already fixed earlier in 1.46 - regression guard)
chunk_07#5   SFB: NaN net_R never evidence (already fixed - regression guard)
chunk_07#7   SFB: rows closed after `now` never evidence (already fixed - regression guard)
chunk_07#8   SFB: excluded_rows counts only the strategy's own rows
chunk_07#9   SFB: block bootstrap with n <= block keeps sampling uncertainty (LCB was the sample mean)
chunk_07#10  SFB: retired profile reported as RETIRED_PROFILE
chunk_07#11  SFB: _block_bootstrap_lcb with block < 1 returns None (no endless loop)
chunk_07#12  SFB: status() names the gate that is configurable but not implemented (min_local_instrument_events)
"""
from __future__ import annotations

import json
import math
import random
import threading
import types
import unittest

import _env  # noqa: F401  (sys.path, MQ_BASKETS_OFFLINE)
import numpy as np

T0 = 1_760_000_000


def _pair_bars(n: int = 200, beta: float = 1.5, seed: int = 3, p0: float = 2000.0, h0: float = 25.0):
    """Parent / partner M15 closes with log-returns r_p = beta * r_h + small noise (correlation ~ 1)."""
    rng = np.random.default_rng(seed)
    rh = rng.normal(0, 0.002, n)
    rp = beta * rh + rng.normal(0, 0.0002, n)
    ph, pp = h0 * np.exp(np.cumsum(rh)), p0 * np.exp(np.cumsum(rp))
    hb = [{"t": T0 + k * 900, "c": float(ph[k])} for k in range(n)]
    pb = [{"t": T0 + k * 900, "c": float(pp[k])} for k in range(n)]
    return pb, hb


def _outcomes(s, n=150, mean=0.3, days=60, seed=1, t0=T0):
    rnd = random.Random(seed)
    return [{"strategy_id": s["strategy_id"], "version": s["version"], "config_hash": s["config_hash"], "net_R": rnd.gauss(mean, 1.0),
             "closed_ts": t0 + i * days * 86400 / n, "event_group_id": f"e{i}", "regime": ("TREND", "RANGE")[i % 2], "cost_complete": True,
             "source": "TASK014"} for i in range(n)]


# ======================================================================================================== hedge.py
class TestBetaHedgeRisk(unittest.TestCase):
    def _ctx(self, ccy_p="USD", ccy_h="USD"):
        pb, hb = _pair_bars()
        spec = {"XAUUSD": {"trade_contract_size": 100, "volume_step": 0.01, "volume_min": 0.01, "currency_profit": ccy_p},
                "XAGUSD": {"trade_contract_size": 5000, "volume_step": 0.01, "volume_min": 0.01, "currency_profit": ccy_h}}
        return {"strategy": {"exit_policy_or_expiry_policy": "x"}, "p": {"partner": "XAGUSD", "ratio": 0.5}, "symbol": "XAUUSD",
                "exposure": [{"leg": "PRIMARY", "symbol": "XAUUSD", "side": "LONG", "volume": 1.0, "id": "P1"}],
                "bars": {"XAUUSD": {"M15": pb}, "XAGUSD": {"M15": hb}}, "spec": spec}, pb

    def test_factor_notional_is_beta_times_parent_notional(self):                   # chunk_06#5
        from masterquo.baskets import hedge as HG
        ctx, pb = self._ctx()
        r = HG.beta_pair(ctx)
        self.assertEqual(r["state"], "HEDGE_PLAN", r)
        plan = r["plan"]
        b = plan["beta"]["w120"]["beta"]
        self.assertGreater(b, 1.2)
        pn = 1.0 * 100 * pb[-1]["c"]
        leg = plan["legs"][0]
        self.assertEqual(leg["side"], "SHORT")
        self.assertAlmostEqual(plan["risk_before"]["factor_notional"], b * pn, delta=1e-6 * pn)
        self.assertAlmostEqual(plan["risk_after"]["factor_notional"], b * pn - leg["notional"], delta=1e-6 * pn)
        # coverage 50 % -> about half of the factor exposure stays, same sign (the old formula showed a sign flip at beta > 1)
        self.assertAlmostEqual(plan["risk_after"]["factor_notional"] / plan["risk_before"]["factor_notional"], 0.5, delta=0.02)
        self.assertEqual(plan["quote_currency"]["status"], "SAME")

    def test_different_quote_currencies_are_flagged(self):                         # chunk_06#5 (second part: shown, volume = DECISION)
        from masterquo.baskets import hedge as HG
        ctx, _ = self._ctx("USD", "JPY")
        plan = HG.beta_pair(ctx)["plan"]
        self.assertEqual(plan["quote_currency"], {"parent": "USD", "partner": "JPY", "status": "DIFFERENT_NOT_CONVERTED"})
        ctx, _ = self._ctx(None, "USD")
        self.assertEqual(HG.beta_pair(ctx)["plan"]["quote_currency"]["status"], "NOT_VERIFIED")


class TestFxSpreadCost(unittest.TestCase):
    def _run(self, **spec):
        from masterquo.baskets import hedge as HG
        F = types.SimpleNamespace(c=[1.0, 2000.0], i=1)
        ctx = {"account": {"margin_mode": "HEDGING", "currency": "EUR"}, "p": {"ratio": 0.5}, "F": F, "strategy": {"exit_policy_or_expiry_policy": "x"},
               "spec": {"XAUUSD": {"trade_contract_size": 100, "volume_step": 0.01, "volume_min": 0.01, **spec}}}
        par = {"id": "P1", "symbol": "XAUUSD", "side": "LONG", "volume": 1.0}
        r = HG._fx_same_symbol(ctx, par, "test")
        self.assertEqual(r["state"], "HEDGE_PLAN", r)
        return r["plan"]["protection_cost"]

    def test_no_quote_is_unknown_cost_not_zero(self):                              # chunk_06#7
        cost = self._run(spread_price=None, trade_tick_value=0.9, trade_tick_size=0.01)
        self.assertIsNone(cost["spread_money"])
        self.assertIn("NO_QUOTE", cost["reason"])

    def test_cost_in_account_currency_from_tick_value(self):                       # chunk_06#7
        cost = self._run(spread_price=0.2, trade_tick_value=0.9, trade_tick_size=0.01, currency_profit="USD")
        self.assertAlmostEqual(cost["spread_money"], 0.2 / 0.01 * 0.9 * 0.5)          # 20 ticks x 0.90 EUR x 0.5 lot
        self.assertEqual(cost["currency"], "EUR")
        cost = self._run(spread_price=0.2, currency_profit="USD")                     # no tick value: quote-currency amount, labelled as such
        self.assertIsNone(cost["spread_money"])
        self.assertAlmostEqual(cost["spread_quote_ccy"], 0.2 * 0.5 * 100)
        self.assertEqual(cost["quote_currency"], "USD")
        cost = self._run(spread_price=0.0, trade_tick_value=0.9, trade_tick_size=0.01)  # a real zero spread stays 0.0
        self.assertEqual(cost["spread_money"], 0.0)


class TestFundingAware(unittest.TestCase):
    def test_no_funding_rates_is_waiting_for_data(self):                           # chunk_06#18
        from masterquo.baskets import hedge as HG
        from masterquo.baskets.rules import Unavailable
        ctx = {"exposure": [{"instrument": "SOL", "side": "LONG", "size": 10.0, "kind": "PERP"}], "funding": {"BTC": None, "ETH": None},
               "fees": {"taker": 0.00045}, "p": {}, "strategy": {"exit_policy_or_expiry_policy": "x"}}
        with self.assertRaises(Unavailable):
            HG.funding_aware(ctx)


# ======================================================================================================== hyperliquid.py
class TestHyperliquidCapabilities(unittest.TestCase):
    def test_trades_aggressor_not_claimed(self):                                    # chunk_06#17
        from masterquo.baskets import hyperliquid as HL
        from masterquo.orderflow.trades import SIDE_SEMANTICS
        self.assertEqual(SIDE_SEMANTICS["HYPERLIQUID"]["status"], "NOT_VERIFIED")
        self.assertIsNot(HL.CAPABILITIES["trades_aggressor"], True)
        self.assertEqual(HL.CAPABILITIES["trades_aggressor"], "NOT_VERIFIED")


# ======================================================================================================== sfb.py
class _SfbBase(unittest.TestCase):
    def setUp(self):
        from masterquo.baskets import catalog as C
        from masterquo.baskets import sfb as F
        self.C, self.F = C, F
        self.fx_scope = {"profile": "FOREX_MT5", "venue": "MT5", "environment": "LIVE_DATA", "product": "CFD", "instrument": "XAUUSD"}
        self.cp_scope = {"profile": "CRYPTO_FOMO_PERPS", "venue": "HL", "environment": "LIVE_DATA", "product": "PERPETUAL", "instrument": "BTC"}
        self.fx = [s for s in C.CATALOG if s["profile_id"] == "FOREX_MT5"]


class TestSfbCapabilities(_SfbBase):
    def test_scope_without_capabilities_uses_declared_registry(self):               # chunk_07#2
        F, C = self.F, self.C
        st, rc = F.compatibility(C.BY_ID["CP_SCALP_09"], self.cp_scope)              # needs trades_aggressor (TASK 004: NOT_VERIFIED)
        self.assertEqual(st, "DATA_UNAVAILABLE")
        self.assertIn("CAPABILITY_NOT_VERIFIED:trades_aggressor", rc)
        st, rc = F.compatibility(C.BY_ID["FX_HEDGE_01"], self.fx_scope)              # needs the account's hedging mode - unknown to the SFB
        self.assertEqual((st, rc), ("DATA_UNAVAILABLE", ["CAPABILITY_NOT_VERIFIED:account_hedging_mode"]))
        self.assertEqual(F.compatibility(C.BY_ID["FX_SMC_01"], self.fx_scope), ("COMPATIBLE", []))      # closed bars: the data path itself
        # an explicit capability list keeps its meaning
        self.assertEqual(F.compatibility(C.BY_ID["FX_HEDGE_01"], {**self.fx_scope, "capabilities": ["closed_bars", "account_hedging_mode"]}),
                         ("COMPATIBLE", []))
        self.assertEqual(F.compatibility(C.BY_ID["FX_SMC_01"], {**self.fx_scope, "capabilities": []}),
                         ("DATA_UNAVAILABLE", ["MISSING_CAPABILITY:closed_bars"]))

    def test_retired_profile_reason(self):                                          # chunk_07#10
        F, C = self.F, self.C
        self.assertEqual(F.compatibility(C.BY_ID["FX_SMC_01"], {**self.fx_scope, "profile": "OTC_GOLD_POCKETOPTION"}),
                         ("RETIRED_SCOPE", ["RETIRED_PROFILE"]))
        self.assertEqual(F.compatibility(C.HISTORICAL_STRATEGIES["OTC_SMC_01"], self.fx_scope), ("RETIRED_SCOPE", ["RETIRED_STRATEGY_ID"]))


class TestSfbSelection(_SfbBase):
    def test_shadow_predicts_assist(self):                                          # chunk_07#3
        F = self.F
        shadow = F.StrategyFilterBucket({"mode": "SHADOW"})
        kept_s, snap_s = shadow.filter(self.fx, self.fx_scope)
        self.assertIs(kept_s, self.fx)                                                  # SHADOW filters nothing
        assist = F.StrategyFilterBucket({"mode": "ASSIST"})
        kept_a, snap_a = assist.filter(self.fx, self.fx_scope)
        for k in ("would_keep", "hedging_passthrough", "bucket_status"):
            self.assertEqual(snap_s[k], snap_a[k], k)
        self.assertEqual(snap_s["bucket_status"], "NO_TRADE_BUCKET")
        self.assertEqual(snap_s["would_keep"], [])
        hedges = [s["strategy_id"] for s in self.fx if s["kind"] == "HEDGING"]
        self.assertEqual(snap_s["hedging_passthrough"], hedges)
        self.assertEqual([s["strategy_id"] for s in kept_a], snap_a["would_keep"] + snap_a["hedging_passthrough"])   # ASSIST unchanged

    def test_assist_with_evidence_keeps_the_same_list(self):                        # chunk_07#3 (ASSIST list itself unchanged)
        F, C = self.F, self.C
        import time as _t
        fx1 = C.BY_ID["FX_SMC_01"]
        outs = _outcomes(fx1, mean=0.4, t0=_t.time() - 61 * 86400)
        a = F.StrategyFilterBucket({"mode": "ASSIST"}, outcomes_fn=lambda scope: outs)
        kept, snap = a.filter(self.fx, self.fx_scope)
        self.assertEqual(snap["would_keep"], ["FX_SMC_01"])
        self.assertEqual(snap["bucket_status"], "ACTIVE")
        self.assertEqual([s["strategy_id"] for s in kept], [s["strategy_id"] for s in self.fx if s["strategy_id"] == "FX_SMC_01" or s["kind"] == "HEDGING"])
        o = F.StrategyFilterBucket({"mode": "OBSERVE"}, outcomes_fn=lambda scope: outs)
        kept_o, snap_o = o.filter(self.fx, self.fx_scope)
        self.assertEqual(kept_o, self.fx)
        self.assertEqual((snap_o["would_keep"], snap_o["bucket_status"]), (["FX_SMC_01"], "ACTIVE"))

    def test_snapshot_complete_when_published(self):                                # chunk_07#13
        F = self.F
        seen: list[set] = []

        class Spy(F.StrategyFilterBucket):
            @property
            def snapshots(self):
                return self.__dict__.get("_snaps", [])

            @snapshots.setter
            def snapshots(self, v):
                if v:
                    seen.append(set(v[-1]))                                             # keys of the snapshot at the moment it becomes visible
                self.__dict__["_snaps"] = v

        sfb = Spy({"mode": "SHADOW"})
        sfb.filter(self.fx, self.fx_scope)
        self.assertEqual(len(seen), 1)
        self.assertTrue({"would_keep", "bucket_status", "hedging_passthrough"} <= seen[0], seen[0])


class TestSfbEvidenceSource(_SfbBase):
    def test_not_connected_reported(self):                                          # chunk_07#1 / focus_X2#15
        F = self.F
        sfb = F.StrategyFilterBucket({"mode": "SHADOW"})
        self.assertEqual(sfb.status()["evidence_source"]["state"], "NOT_CONNECTED")
        _, snap = sfb.filter(self.fx, self.fx_scope)
        self.assertEqual(snap["evidence_source"], "NOT_CONNECTED")
        it = snap["items"]["FX_SMC_01"]
        self.assertEqual(it["eligibility_status"], "COMPATIBLE_UNVALIDATED")
        self.assertIn("EVIDENCE_SOURCE_NOT_CONNECTED", it["reason_codes"])
        again = F.StrategyFilterBucket({"mode": "OBSERVE"}, sfb.outcomes_fn)          # BasketService.set_sfb hands the same function over
        self.assertEqual(again.status()["evidence_source"]["state"], "NOT_CONNECTED")
        wired = F.StrategyFilterBucket({"mode": "SHADOW"}, outcomes_fn=lambda scope: [])
        self.assertEqual(wired.status()["evidence_source"]["state"], "CONNECTED")
        _, snap = wired.filter(self.fx, self.fx_scope)
        self.assertNotIn("EVIDENCE_SOURCE_NOT_CONNECTED", snap["items"]["FX_SMC_01"]["reason_codes"])

    def test_status_names_unimplemented_gate(self):                                 # chunk_07#12
        st = self.F.StrategyFilterBucket({}).status()
        self.assertIn("min_local_instrument_events", st["not_implemented"])


class TestSfbEvidence(_SfbBase):
    def setUp(self):
        super().setUp()
        self.s = self.C.BY_ID["FX_SMC_01"]
        self.cfg = self.F.validate_config({})
        self.now = T0 + 61 * 86400

    def test_config_types_and_ranges(self):                                         # chunk_07#4 (already fixed)
        for bad in ({"bootstrap_reps": 0}, {"bootstrap_confidence": 0}, {"bootstrap_confidence": 1.5}, {"bootstrap_block": -1000},
                    {"bootstrap_block": 0}, {"min_independent_events": "100"}, {"min_outer_folds": True}, {"stale_after_hours": 0}):
            with self.assertRaises(self.F.ConfigError, msg=str(bad)):
                self.F.validate_config(bad)

    def test_nan_net_r_is_not_evidence(self):                                       # chunk_07#5 (already fixed)
        rows = _outcomes(self.s, mean=-0.05, seed=9)
        base = self.F.evidence(self.s, rows, self.cfg, self.now)
        nan = self.F.evidence(self.s, rows + [{**rows[0], "net_R": float("nan"), "event_group_id": "nan"}], self.cfg, self.now)
        self.assertEqual((nan["status"], nan["net_r_lcb"], nan["n_events"]), (base["status"], base["net_r_lcb"], base["n_events"]))
        json.dumps(nan, allow_nan=False)

    def test_rows_after_now_ignored(self):                                          # chunk_07#7 (already fixed)
        rows = _outcomes(self.s, mean=0.4)
        mid = T0 + 10 * 86400
        e = self.F.evidence(self.s, rows, self.cfg, mid)
        self.assertEqual(e["n_events"], sum(1 for o in rows if o["closed_ts"] <= mid))
        self.assertNotEqual(e["status"], "ELIGIBLE")

    def test_excluded_rows_only_own_strategy(self):                                 # chunk_07#8
        other = self.C.BY_ID["FX_SCALP_01"]
        rows = _outcomes(other) + [{**o, "source": "SIGNAL_SIMULATION"} for o in _outcomes(self.s, n=7)]
        e = self.F.evidence(self.s, rows, self.cfg, self.now)
        self.assertEqual(e["excluded_rows"], 7)

    def test_short_series_keeps_uncertainty(self):                                  # chunk_07#9
        xs = [1.0, -0.5, 2.0, -1.0, 0.8]
        lcb = self.F._block_bootstrap_lcb(xs, 10, 400, 0.9)
        self.assertIsNotNone(lcb)
        self.assertLess(lcb, sum(xs) / len(xs) - 0.1)                                   # was exactly the sample mean (0.26)

    def test_block_below_one_terminates(self):                                      # chunk_07#11
        out: list = []
        th = threading.Thread(target=lambda: out.append(self.F._block_bootstrap_lcb([0.1, 0.2, -0.3, 0.4], 0, 50, 0.9)), daemon=True)
        th.start()
        th.join(3.0)
        self.assertFalse(th.is_alive(), "endless loop for block = 0")
        self.assertEqual(out, [None])
        self.assertTrue(math.isfinite(self.F._block_bootstrap_lcb([0.1, 0.2, -0.3, 0.4] * 30, 10, 50, 0.9)))


if __name__ == "__main__":
    unittest.main()
