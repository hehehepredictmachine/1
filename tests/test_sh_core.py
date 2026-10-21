"""PMW-SH-1 core: units (USD price targets on the tick grid, volume splits), scalping position life cycle and the hedging
basket state machine. Pure logic - no terminal, no orders."""
import unittest

import _env  # noqa: F401

from masterquo.sh.hedge_fsm import Basket, HedgeConfig
from masterquo.sh.lifecycle import Leg, Position
from masterquo.sh.units import SymbolSpec, UnitError

GOLD = SymbolSpec(symbol="XAUUSD-", tick_size=0.01, tick_value=1.0, contract_size=100, volume_min=0.01, volume_step=0.01,
                  volume_max=100, digits=2, currency_profit="USD", source="TEST")


def scalp_pos(side="BUY", entry=2000.0, vol=0.10, shares=(0.4, 0.4, 0.2), sl=1997.0):
    legs = GOLD.split(vol, list(shares))["legs"]
    tps = [GOLD.target(entry, side, d)["price"] for d in (2.5, 3.0, 5.0)]
    return Position(plan_id="P1", side=side, entry=entry, volume=vol, sl=sl,
                    legs=[Leg(n, p, v) for n, p, v in zip(("TP1", "TP2", "TP3"), tps, legs)])


class UnitsTests(unittest.TestCase):
    def test_targets_buy_sell_usd_price_moves(self):
        b = GOLD.target(2000.004, "BUY", 2.5)
        self.assertEqual(b["unit"], "USD_PRICE_MOVE")
        self.assertAlmostEqual(b["price"], 2002.51)                    # never closer than requested (rounded up for BUY)
        self.assertGreaterEqual(b["actual_distance"], 2.5)
        s = GOLD.target(2000.004, "SELL", 3.0)
        self.assertAlmostEqual(s["price"], 1997.00)                    # rounded down for SELL
        self.assertGreaterEqual(s["actual_distance"], 3.0 - 1e-9)
        self.assertAlmostEqual(GOLD.stop(2000.0, "BUY", 2.333), 1997.66)
        self.assertAlmostEqual(GOLD.stop(2000.0, "SELL", 2.333), 2002.34)
        with self.assertRaises(UnitError):
            SymbolSpec(**{**GOLD.__dict__, "currency_profit": "USDT"}).check_usd()
        GOLD.check_usd()

    def test_volume_split_and_min_lot(self):
        r = GOLD.split(0.10, [0.4, 0.4, 0.2])
        self.assertEqual((r["status"], r["legs"]), ("OK", [0.04, 0.04, 0.02]))
        self.assertAlmostEqual(sum(r["legs"]), 0.10)
        r = GOLD.split(0.02, [0.4, 0.4, 0.2])
        self.assertEqual(r["status"], "INFEASIBLE")                    # three legs impossible at 0.02 lots - reported, not rescaled
        self.assertEqual(GOLD.split(0.10, [0.5, 0.4])["status"], "INVALID_SHARES")
        self.assertEqual(GOLD.split(0.105, [0.5, 0.5])["status"], "INVALID_TOTAL")
        r = GOLD.split(0.07, [0.4, 0.4, 0.2])
        self.assertEqual(r["status"], "OK")
        self.assertAlmostEqual(sum(r["legs"]), 0.07)
        self.assertTrue(all(GOLD.volume_ok(v) for v in r["legs"]))


class ScalpLifecycleTests(unittest.TestCase):
    def test_buy_partials_on_bid_and_be_only_after_confirmed_tp2(self):
        p = scalp_pos("BUY")
        self.assertEqual(p.on_quote(2002.49, 2002.60), [])              # ask above TP1 but BID below: no fill for a BUY close
        a = p.on_quote(2002.50, 2002.62)
        self.assertEqual([x["kind"] for x in a], ["CLOSE_PARTIAL"])
        self.assertEqual(p.on_quote(2002.55, 2002.70), [])              # repeated quote: no second request
        self.assertEqual(p.on_fill("d1", "TP1", 0.04, 2002.50), [])
        self.assertEqual(p.state, "TP1_DONE")
        a = p.on_quote(2003.00, 2003.10)
        self.assertEqual(a[0]["action_id"], "P1:CLOSE_PARTIAL:TP2")
        self.assertEqual(p.be_status, "NOT_REQUESTED")                  # touch is not a fill
        a = p.on_fill("d2", "TP2", 0.04, 2003.00)
        self.assertEqual(a[0]["kind"], "MODIFY_SL")
        self.assertAlmostEqual(a[0]["sl"], 2000.0)
        self.assertEqual(p.on_fill("d2", "TP2", 0.04, 2003.00), [])    # duplicate event: ignored
        self.assertAlmostEqual(p.remaining, 0.02)
        p.on_sl_result("s1", True, 2003.0, 2003.1)
        self.assertEqual(p.be_status, "SET")
        p.on_closed("c1", 0.02, 2000.0, "SL")                            # runner stopped at BE: still a winning cycle
        self.assertEqual(p.state, "CLOSED")
        r = p.result(money_per_price_per_lot=100.0)
        self.assertGreater(r["net_money"], 0)
        self.assertEqual(len([x for x in p.realized]), 3)

    def test_sell_uses_ask_and_gap_over_two_targets(self):
        p = scalp_pos("SELL", sl=2003.0)
        a = p.on_quote(1996.80, 1996.90)                                  # gap through TP1 (1997.50) and TP2 (1997.00)
        self.assertEqual([x["action_id"] for x in a], ["P1:CLOSE_PARTIAL:TP1", "P1:CLOSE_PARTIAL:TP2"])

    def test_be_rejected_then_retry_then_close_remainder(self):
        p = scalp_pos("BUY")
        p.on_quote(2003.0, 2003.1)
        p.on_fill("d1", "TP1", 0.04, 2002.5)
        p.on_fill("d2", "TP2", 0.04, 2003.0)
        a = p.on_sl_result("s1", False, 2003.0, 2003.1, "INVALID_STOPS")
        self.assertEqual(a[0]["kind"], "MODIFY_SL")                     # retry, SL never widened
        a = p.on_sl_result("s2", False, 1999.9, 2000.0, "INVALID_STOPS")
        self.assertEqual(a[0]["kind"], "CLOSE_RUNNER")                  # price already beyond BE -> close remainder
        self.assertEqual(p.on_sl_result("s2", False, 1999.9, 2000.0), [])

    def test_partial_rejected_is_retried_once_per_attempt(self):
        p = scalp_pos("BUY")
        p.on_quote(2002.6, 2002.7)
        p.on_partial_rejected("r1", "TP1", "REQUOTE")
        self.assertEqual(p.legs[0].status, "PENDING")
        self.assertEqual(len(p.on_quote(2002.6, 2002.7)), 1)


class HedgeFsmTests(unittest.TestCase):
    def basket(self, **kw):
        p = Position(plan_id="H1", side="BUY", entry=2000.0, volume=0.10, sl=1990.0,
                     legs=[Leg("TP1", 2003.5, 0.04), Leg("TP2", 2005.0, 0.04), Leg("TP3", 2009.0, 0.02)])
        return Basket(basket_id="B1", primary=p, cfg=HedgeConfig(trigger_adverse_usd=3.0, ratio=0.5, **kw), money_per_price_per_lot=100.0,
                      opened_at=0.0)

    def test_decision_event_justification_and_no_martingale(self):
        b = self.basket()
        d = b.hedge_decision(1998.5, 1998.6, structure_valid=True, risk_ok=True, risk_reason="", hedge_cost_price=0.3, reduce_cost_price=0.5)
        self.assertEqual(d["decision"], "HOLD")
        d = b.hedge_decision(1996.9, 1997.0, structure_valid=False, risk_ok=True, risk_reason="", hedge_cost_price=0.3, reduce_cost_price=0.5)
        self.assertEqual(d["decision"], "EXIT")
        d = b.hedge_decision(1996.9, 1997.0, structure_valid=True, risk_ok=True, risk_reason="", hedge_cost_price=0.6, reduce_cost_price=0.5)
        self.assertEqual(d["decision"], "REDUCE")
        d = b.hedge_decision(1996.9, 1997.0, structure_valid=True, risk_ok=True, risk_reason="", hedge_cost_price=0.3, reduce_cost_price=0.5)
        self.assertEqual(d["decision"], "HEDGE")
        self.assertAlmostEqual(b.hedge_volume(GOLD.floor_volume), 0.05)   # bounded fraction of the CURRENT primary volume

    def test_rejected_hedge_never_hedged_and_activation_limit(self):
        b = self.basket()
        a = b.request_hedge(10, 0.05, "event")
        self.assertEqual(b.state, "HEDGE_PENDING")
        self.assertEqual(a[0]["side"], "SELL")
        b.on_hedge_result("e1", 11, ok=False, reason="NO_MONEY")
        self.assertEqual(b.state, "PRIMARY_OPEN")
        self.assertIsNone(b.hedge)
        d = b.hedge_decision(1996.9, 1997.0, structure_valid=True, risk_ok=True, risk_reason="", hedge_cost_price=0.3, reduce_cost_price=0.5)
        self.assertEqual(d["decision"], "HOLD")                          # max_activations=1 used up

    def test_partial_fill_unwind_and_tp2_closes_hedge(self):
        b = self.basket(max_activations=2)
        b.request_hedge(10, 0.05, "event")
        b.on_hedge_result("e1", 11, ok=True, volume=0.03, price=1997.0, reason="PARTIAL")
        self.assertEqual((b.state, b.hedge.volume), ("HEDGED", 0.03))
        a = b.on_quote(20, 1998.0, 1998.1)                                # recovery 1.1 >= 1.0 -> unwind
        self.assertEqual(a[0]["kind"], "CLOSE_HEDGE")
        self.assertEqual(b.state, "UNWINDING")
        b.on_hedge_closed("c1", 21, 0.03, 1998.1)
        self.assertEqual(b.state, "PRIMARY_OPEN")
        self.assertAlmostEqual(b.hedge_realized_money, -0.03 * 1.1 * 100)
        # second activation, then the primary reaches TP2: hedge must be closed with the BE request
        b.request_hedge(30, 0.05, "event2")
        b.on_hedge_result("e2", 31, ok=True, volume=0.05, price=1997.0)
        b.primary.on_quote(2005.0, 2005.1)
        b.on_primary_fill("f1", 40, "TP1", 0.04, 2003.5)
        acts = b.on_primary_fill("f2", 41, "TP2", 0.04, 2005.0)
        kinds = sorted(x["kind"] for x in acts)
        self.assertEqual(kinds, ["CLOSE_HEDGE", "MODIFY_SL"])

    def test_basket_loss_limit_exits_all_legs(self):
        b = self.basket(basket_loss_limit_money=50.0)
        b.request_hedge(10, 0.05, "event")
        b.on_hedge_result("e1", 11, ok=True, volume=0.05, price=1997.0)
        acts = b.on_quote(20, 1993.0, 1993.1)                            # primary -0.10*7*100 = -700 ; hedge +0.05*3.9*100
        self.assertEqual(sorted(x["kind"] for x in acts), ["CLOSE_HEDGE", "CLOSE_PRIMARY"])
        self.assertEqual(b.state, "EXIT_PENDING")
        rep = b.report(1993.0, 1993.1)
        self.assertIn("nie oznacza", rep["note"])
        self.assertAlmostEqual(rep["basket"]["gross_exposure_lots"], 0.10)   # hedge in CLOSING is not counted as open
        b.on_hedge_closed("h", 21, 0.05, 1993.1)
        b.on_primary_closed("p", 21, 0.10, 1993.0, "EXIT")
        self.assertEqual(b.state, "CLOSED")



class GapThroughAllTargets(unittest.TestCase):
    def test_runner_volume_excludes_pending_partials(self):
        from masterquo.sh.lifecycle import Leg, Position
        p = Position("R", "BUY", 2000.25, 1.0, 1998.0, [Leg("TP1", 2002.75, 0.5), Leg("TP2", 2003.25, 0.3), Leg("TP3", 2005.25, 0.2)])
        acts = p.on_quote(2006.0, 2006.2)
        self.assertEqual([(a["kind"], a["volume"]) for a in acts], [("CLOSE_PARTIAL", 0.5), ("CLOSE_PARTIAL", 0.3), ("CLOSE_RUNNER", 0.2)])
        self.assertAlmostEqual(sum(a["volume"] for a in acts), 1.0)

if __name__ == "__main__":
    unittest.main()
