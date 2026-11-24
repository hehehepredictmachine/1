"""Fala 2 (grupa sh_exec): wykonanie i zarządzanie planami SCALPING / HEDGING - state machines (lifecycle, hedge_fsm), executor,
reconcile / recover. Each test fails on the code before the fix and documents one item:

I0714 reconcile: None from MT5 / another account is not 'position closed'; the plan is frozen (no hedge, no action) and recovery retried;
      a terminal not answering at all (timeout / busy) is signalled (RECONCILE_WAIT, alert after the wait) and never settled on.
I0740 a rejected close of the hedge in EXIT_PENDING is retried (spaced, bounded, then ERROR); an exit decision is final (no new hedge);
      a retried hedge close (rejected / partial) uses up the activations (no second leg); the working rest of a RETURN partial is not resent.
I0741 a stored remaining 0.0 of a closed position stays 0.0 after a reload (no phantom primary).
I0742 partial closes are capped to the volume the position still holds (after REDUCE / external partial close) - also through
      SHService.manage; a volume drop is first settled on the partial closes in flight (unknown outcome), so TP2 / BE still follow.
I0812 an OK DEAL answer without volume is UNKNOWN (never DONE); process survives a DONE row without volume.
I0813 closing deals include INOUT / OUT_BY; a vanished position without its deal is settled only after the wait (verified=False).
I0814 a rejected CAP reduction releases its own id; the variant policy keeps running; no HEDGE intent next to an open leg.
I0815 the rest of a partially filled TP leg is requested again (new attempt id); the runner counts only unfilled requests.
I0816 the position state never goes back from TP2_DONE to TP1_DONE.
"""
import json
import types
import unittest

import _env  # noqa: F401
import test_sh_service as TS
from masterquo.sh.executor import SHExecutor, TerminalDataUnavailable
from masterquo.sh.hedge_fsm import (
    EXIT_RETRY_SECONDS,
    HEDGE_CLOSE_MAX_TRIES,
    Basket,
    HedgeConfig,
    Leg2,
)
from masterquo.sh.lifecycle import Leg, Position
from masterquo.sh.store import basket_dump, basket_load, pos_dump, pos_load


def pos3(pid="P", vol=1.0, legs=((101.0, 0.4), (102.0, 0.4), (103.0, 0.2))):
    return Position(pid, "BUY", 100.0, vol, 99.0, [Leg(n, px, v) for n, (px, v) in zip(("TP1", "TP2", "TP3"), legs)])


def hedged_basket(pid="B", primary_state_closed=False):
    p = Position(pid, "BUY", 100.0, 1.0, 99.0, [Leg("TP1", 101.0, 0.5), Leg("TP2", 102.0, 0.5)])
    b = Basket(pid, p, HedgeConfig(trigger_adverse_usd=0.5), 100.0, opened_at=0.0)
    b.hedge, b.state, b.activations = Leg2("SELL", 0.5, 99.5, 1.0), "HEDGED", 1
    if primary_state_closed:
        p.on_closed("pc", 1.0, 99.0, "SL")
    return b


# ====================================================================================================================== I0741
class TestPosLoadRemainingZero(unittest.TestCase):
    def test_closed_position_reloads_with_zero_remaining(self):
        p = Position("PL1", "BUY", 100.0, 1.0, 99.0, [Leg("TP1", 101, 0.5), Leg("TP2", 102, 0.5)])
        p.on_closed("e1", 1.0, 99.0, "SL")
        q = pos_load(pos_dump(p))
        self.assertEqual(q.remaining, 0.0)                     # before: 1.0 (phantom full volume at every read of the plan)
        self.assertEqual(q.state, "CLOSED")
        self.assertEqual(Position("N", "BUY", 1.0, 0.3, 0.5, []).remaining, 0.3)   # a new position still starts with its volume

    def test_basket_with_closed_primary_has_no_phantom_exposure(self):
        b = hedged_basket(primary_state_closed=True)
        b2 = basket_load(basket_dump(b))
        self.assertEqual(b2.primary.remaining, 0.0)
        self.assertEqual(b2.primary_unrealized(95.0, 95.1), 0.0)          # before: -500 -> basket loss limit -> CLOSE_PRIMARY on nothing
        self.assertEqual(b2.report(95.0, 95.1)["basket"]["gross_exposure_lots"], 0.5)


# ====================================================================================================================== I0816
class TestNoStateRegression(unittest.TestCase):
    def test_late_tp1_after_tp2_keeps_tp2_done(self):
        p = pos3()
        acts = p.on_quote(102.1, 102.2)
        self.assertEqual([a["action_id"].split(":")[-1] for a in acts], ["TP1", "TP2"])
        p.on_fill("f2", "TP2", 0.4, 102.0)
        self.assertEqual(p.state, "TP2_DONE")
        p.on_fill("f1", "TP1", 0.4, 101.0)
        self.assertEqual(p.state, "TP2_DONE")                  # before: TP1_DONE (hedge_step allowed again after TP2)
        self.assertEqual(p.be_status, "REQUESTED")

    def test_basket_after_tp2_offers_no_hedge_step(self):
        b = Basket("B", pos3("B"), HedgeConfig(trigger_adverse_usd=0.5, max_activations=2), 100.0, opened_at=0.0)
        b.on_quote(1.0, 102.1, 102.2)
        b.on_primary_fill("f2", 2.0, "TP2", 0.4, 102.0)
        b.on_primary_fill("f1", 3.0, "TP1", 0.4, 101.0)
        # SHService.manage runs hedge_step / pack_hedge_step only for a primary in OPEN / TP1_DONE (before: TP1_DONE again)
        self.assertEqual(b.primary.state, "TP2_DONE")
        self.assertNotIn(b.primary.state, ("OPEN", "TP1_DONE"))


# ====================================================================================================================== I0742
class TestPartialCappedByRemaining(unittest.TestCase):
    LIM = (0.01, 0.01)

    def test_requests_never_exceed_remaining_after_reduce(self):
        p = pos3()
        p.on_closed("r1", 0.5, 99.5, "REDUCE")
        acts = p.on_quote(102.5, 102.6, limits=self.LIM)
        self.assertLessEqual(round(sum(a["volume"] for a in acts), 8), 0.5)          # before: 0.8 of a 0.5 position
        self.assertEqual([(a["leg"], a["volume"]) for a in acts], [("TP1", 0.4)])     # TP2 waits for TP1's result (cap from in flight)
        self.assertEqual(p.legs[1].status, "PENDING")                                 # not SKIPPED
        p.on_fill("f1", "TP1", 0.4, 101.0)
        acts = p.on_quote(102.5, 102.6, limits=self.LIM)
        self.assertEqual([(a["leg"], a["volume"]) for a in acts], [("TP2", 0.1)])     # capped by the confirmed remaining
        p.on_fill("f2", "TP2", 0.1, 102.0)
        self.assertEqual((p.state, p.remaining, p.legs[1].status), ("CLOSED", 0.0, "DONE"))

    def test_rejected_in_flight_request_frees_the_volume(self):
        p = pos3()
        p.on_closed("r1", 0.5, 99.5, "REDUCE")
        a = p.on_quote(101.1, 101.2, limits=self.LIM)[0]
        p.on_partial_rejected("rej", "TP1", "REQUOTE", action_id=a["action_id"])
        again = p.on_quote(101.1, 101.2, limits=self.LIM)
        self.assertEqual([(x["action_id"], x["volume"]) for x in again], [(a["action_id"], 0.4)])

    def test_validation_replay_requests_unchanged(self):
        """sh/replay.py calls on_quote without limits: its reports gate the hedge variant (validated_variant / O3) - unchanged here."""
        p = pos3()
        p.on_closed("r1", 0.5, 99.5, "REDUCE")
        self.assertEqual([(a["action_id"], a["volume"]) for a in p.on_quote(102.5, 102.6)],
                         [("P:CLOSE_PARTIAL:TP1", 0.4), ("P:CLOSE_PARTIAL:TP2", 0.4)])

    def test_capped_tp2_filled_in_full_still_sets_be(self):
        p = pos3()
        p.on_closed("x", 0.555, 99.5, "EXTERNAL")                                    # 0.445 left (not a multiple of the step)
        a1 = p.on_quote(101.1, 101.2, limits=self.LIM)[0]
        p.on_fill(a1["action_id"] + ":r", "TP1", a1["volume"], 101.0, requested=a1["volume"])
        a2 = p.on_quote(102.1, 102.2, limits=self.LIM)[0]
        self.assertEqual((a2["leg"], a2["volume"]), ("TP2", 0.04))
        acts = p.on_fill(a2["action_id"] + ":r", "TP2", 0.04, 102.0, requested=0.04)
        self.assertEqual((p.legs[1].status, p.state), ("DONE", "TP2_DONE"))       # BE after TP2 does not disappear
        self.assertEqual([a["kind"] for a in acts], ["MODIFY_SL"])

    def test_volume_rounded_down_to_step_and_min_lot(self):
        p = Position("P", "BUY", 100.0, 1.0, 99.0, [Leg("TP1", 101.0, 0.5), Leg("TP2", 102.0, 0.5)])
        p.on_closed("x", 0.55, 99.5, "EXTERNAL")                                     # 0.45 left
        acts = p.on_quote(101.1, 101.2, limits=(0.1, 0.1))
        self.assertEqual([a["volume"] for a in acts], [0.4])                         # floor(0.45 / 0.1) * 0.1, never above the rest


class TestManageCapsPartials(TS.Base):
    """SHService.manage passes the symbol's volume limits to the state machines (the cap is not only a property of on_quote)."""

    def test_gap_after_external_close_never_requests_more_than_the_position(self):
        self.open(volume=0.3)                                                    # legs 0.15 / 0.09 / runner 0.06
        row = self.row()
        pos = row["fsm_obj"]
        pos.on_closed("ext", 0.1, pos.entry, "ZEWNĘTRZNE_ZAMKNIĘCIE_CZĘŚCI")     # 0.2 left
        self.svc.store.update_plan(row["plan_id"], fsm=pos, now=self.t)
        tp2 = pos.legs[1].price
        row = self.step(tp2 + 0.1, dt=1)                                         # one gap over TP1 and TP2
        req = [(json.loads(a["request"])["leg"], json.loads(a["request"])["volume"]) for a in self.svc.store.actions(row["plan_id"])
               if a["kind"] == "CLOSE_PARTIAL"]
        self.assertEqual(req, [("TP1", 0.15)])                                   # before (no limits in manage): TP1 0.15 + TP2 0.09 > 0.2
        self.assertEqual(row["fsm_obj"].legs[1].status, "PENDING")               # TP2 waits for TP1's result (not SKIPPED)
        row = self.step(tp2 + 0.1, dt=1)
        p = row["fsm_obj"]
        self.assertEqual((p.legs[1].status, row["state"]), ("DONE", "CLOSED"))   # TP2 capped to the 0.05 left: the position is closed
        self.assertAlmostEqual(p.legs[1].fill_volume, 0.05)
        self.assertAlmostEqual(p.remaining, 0.0)


class TestUnknownPartialSettledByReconcile(TS.Base):
    """A partial close executed by the terminal whose answer was lost (UNKNOWN): reconciliation books the volume drop on that leg first."""
    mode = "AUTO_DEMO"

    def _lose_next_answer(self):
        orig, st = self.fake.order_send, {"n": 0}

        def send(req):
            r = orig(req)
            if req.get("action") == self.fake.TRADE_ACTION_DEAL and st["n"] == 0:
                st["n"] += 1
                raise TimeoutError("executed, answer lost")
            return r
        self.fake.order_send = send

    def test_tp2_and_be_follow_an_unknown_tp1(self):
        self.open(volume=0.3)
        pos = self.row()["fsm_obj"]
        tp1, tp2 = pos.legs[0].price, pos.legs[1].price
        self._lose_next_answer()
        row = self.step(tp1 + 0.1, dt=1)                                         # TP1 executed, UNKNOWN for the bot
        self.assertEqual(row["fsm_obj"].legs[0].status, "REQUESTED")
        row = self.step(tp1 + 0.1, dt=1)                                         # reconcile: the drop is TP1's
        p = row["fsm_obj"]
        self.assertEqual((p.legs[0].status, p.state), ("DONE", "TP1_DONE"))
        self.assertAlmostEqual(p.remaining, 0.15)
        ev = next(x for x in self.svc.store.events(row["plan_id"]) if x["kind"] == "RECONCILED_PRIMARY")["payload"]
        self.assertEqual(([x["leg"] for x in ev["legs_in_flight"]], ev["closed"], ev["closed_external"]), (["TP1"], 0.15, 0.0))
        tp1_row = next(a for a in self.svc.store.actions(row["plan_id"]) if a["action_id"].endswith(":CLOSE_PARTIAL:TP1"))
        self.assertEqual(tp1_row["status"], "DONE")                              # outcome no longer unknown
        for _ in range(3):
            row = self.step(tp2 + 0.1, dt=1)
        acts = {a["action_id"].split(":", 1)[1]: a["status"] for a in self.svc.store.actions(row["plan_id"])}
        self.assertEqual(acts.get("CLOSE_PARTIAL:TP2"), "DONE")                  # before: TP2 never requested (TP1 counted twice)
        self.assertEqual(acts.get("MODIFY_SL:BE1"), "DONE")
        self.assertEqual((row["fsm_obj"].state, row["fsm_obj"].be_status), ("TP2_DONE", "SET"))

    def test_drop_beyond_the_partial_in_flight_is_booked_as_external(self):
        self.open(volume=0.3)
        row = self.row()
        tp1 = row["fsm_obj"].legs[0].price
        self._lose_next_answer()
        self.step(tp1 + 0.1, dt=1)
        tk = int(row["primary_ticket"])
        self.fake.order_send({"action": self.fake.TRADE_ACTION_DEAL, "symbol": "XAUUSD-", "volume": 0.05, "position": tk,
                              "type": self.fake.ORDER_TYPE_SELL, "price": self.fake.symbol_info_tick("XAUUSD-").bid, "comment": "manual"})
        row = self.step(tp1 + 0.1, dt=1)
        p = row["fsm_obj"]
        self.assertEqual(p.legs[0].status, "DONE")
        self.assertAlmostEqual(p.legs[0].fill_volume, 0.15)
        self.assertAlmostEqual(p.remaining, 0.1)
        self.assertEqual([r["leg"] for r in p.realized], ["TP1", "ZEWNĘTRZNE_ZAMKNIĘCIE_CZĘŚCI"])


# ====================================================================================================================== I0815
class TestPartialFillRetry(unittest.TestCase):
    def test_rest_of_partially_filled_leg_requested_again(self):
        p = pos3(legs=((101.0, 0.5), (102.0, 0.3), (103.0, 0.2)))
        a1 = p.on_quote(101.1, 101.2, limits=(0.01, 0.01))[0]
        p.on_fill(a1["action_id"] + ":r", "TP1", 0.2, 101.0, retry_rest=True)
        self.assertEqual((p.legs[0].status, p.remaining), ("PENDING", 0.8))
        a2 = p.on_quote(101.1, 101.2, limits=(0.01, 0.01))
        self.assertEqual([(x["action_id"], x["leg"], x["volume"]) for x in a2], [("P:CLOSE_PARTIAL:TP1#2", "TP1", 0.3)])   # before: []
        p.on_fill(a2[0]["action_id"] + ":r", "TP1", 0.3, 101.0, retry_rest=True)
        self.assertEqual((p.legs[0].status, p.state, p.remaining), ("DONE", "TP1_DONE", 0.5))

    def test_runner_counts_only_unfilled_requests(self):
        p = pos3(legs=((101.0, 0.5), (102.0, 0.3), (103.0, 0.2)))
        p.on_quote(101.1, 101.2)
        p.on_fill("f1", "TP1", 0.2, 101.0)                     # rest may still be working (no retry): leg stays REQUESTED
        self.assertEqual(p.legs[0].status, "REQUESTED")
        acts = p.on_quote(103.1, 103.2)
        runner = next(a for a in acts if a["kind"] == "CLOSE_RUNNER")
        self.assertAlmostEqual(runner["volume"], 0.2)          # 0.8 - 0.3 (TP1 rest) - 0.3 (TP2); before: 0.0


# ====================================================================================================================== I0812
class TestOkWithoutVolume(unittest.TestCase):
    def test_deal_ok_without_volume_is_unknown(self):
        ex = SHExecutor(store=None)
        r = types.SimpleNamespace(retcode=10009, volume=0, price=0, deal=0, order=1, comment="")
        self.assertEqual(ex._result(r, 0.5)["status"], "UNKNOWN")             # before: DONE
        self.assertEqual(ex._result(r, 0.5)["reason"], "OK_BEZ_WOLUMENU")
        self.assertEqual(ex._result(r, 0.0, deal=False)["status"], "DONE")   # SL/TP modification

    def test_modify_sl_still_done_on_terminal(self):
        from masterquo.mt5.fake import FakeMT5
        fake = FakeMT5()
        fake.initialize()

        class St:
            def owner(self, acc, tk):
                return {"plan_id": "PL"}

        ex = SHExecutor(St(), terminal=lambda fn: fn(fake), account_key="A")
        t = fake.symbol_info_tick("XAUUSD-")
        r = fake.order_send({"action": fake.TRADE_ACTION_DEAL, "symbol": "XAUUSD-", "volume": 0.1, "type": fake.ORDER_TYPE_BUY, "price": t.ask,
                             "magic": 1, "comment": "x"})
        res = ex._mt5_action({"symbol": "XAUUSD-", "plan_id": "PL"}, {"kind": "MODIFY_SL", "sl": t.bid - 5, "action_id": "PL:MODIFY_SL:BE1"},
                             r.order, "BUY")
        self.assertEqual(res["status"], "DONE")


class _StubEx:
    """Executor stand-in for SHService.process: answers from a queue, records the actions."""

    def __init__(self, answers, rest_cancelled=True):
        self.answers, self.sent, self.rc = list(answers), [], rest_cancelled
        self.account_key = "PAPER"

    def perform(self, plan, action, **kw):
        self.sent.append(action)
        return self.answers.pop(0) if self.answers else {"status": "UNKNOWN"}

    def open(self, plan, **kw):
        self.sent.append({"kind": "OPEN_" + kw.get("role", "?"), **kw})
        return {"status": "REJECTED", "reason": "stub"}

    def rest_cancelled(self):
        return self.rc


class TestProcessResults(TS.Base):
    def test_done_without_volume_is_not_a_crash(self):
        self.open(volume=0.3)
        row = self.row()
        pos = row["fsm_obj"]
        acts = pos.on_quote(pos.legs[0].price + 0.1, pos.legs[0].price + 0.3)
        ex = _StubEx([{"status": "DONE"}])                       # stored DONE row of an OK answer without volume (replayed)
        self.svc.process(ex, row, pos, acts, self.spec, self.q(), self.t)      # before: KeyError 'volume' every tick
        self.assertEqual(self.row()["fsm_obj"].legs[0].status, "REQUESTED")  # unknown outcome: reconciliation decides
        self.assertAlmostEqual(self.row()["fsm_obj"].remaining, 0.3)

    def test_partial_fill_rest_requested_with_new_id(self):
        self.open(volume=0.3)
        row = self.row()
        pos = row["fsm_obj"]
        px = pos.legs[0].price + 0.1
        acts = pos.on_quote(px, px + 0.2)
        ex = _StubEx([{"status": "PARTIAL", "volume": 0.05, "price": px}])
        self.svc.process(ex, row, pos, acts, self.spec, self.q(), self.t)
        row = self.row()
        pos = row["fsm_obj"]
        self.assertEqual(pos.legs[0].status, "PENDING")
        acts = pos.on_quote(px, px + 0.2, limits=(self.spec.volume_step, self.spec.volume_min))
        self.assertEqual([(a["action_id"].split(":")[-1], a["leg"], a["volume"]) for a in acts], [("TP1#2", "TP1", 0.1)])
        ex = _StubEx([{"status": "FILLED", "volume": 0.1, "price": px}])
        self.svc.process(ex, row, pos, acts, self.spec, self.q(), self.t)
        pos = self.row()["fsm_obj"]
        self.assertEqual((pos.legs[0].status, pos.state), ("DONE", "TP1_DONE"))
        self.assertAlmostEqual(pos.remaining, 0.15)

    def test_partial_fill_with_return_filling_is_not_resent(self):
        self.open(volume=0.3)
        row = self.row()
        pos = row["fsm_obj"]
        px = pos.legs[0].price + 0.1
        acts = pos.on_quote(px, px + 0.2)
        self.svc.process(_StubEx([{"status": "PARTIAL", "volume": 0.05, "price": px}], rest_cancelled=False), row, pos, acts, self.spec,
                         self.q(), self.t)
        self.assertEqual(self.row()["fsm_obj"].legs[0].status, "REQUESTED")   # the rest may still be working: never a second order


class TestEntryOkWithoutVolume(TS.Base):
    mode = "AUTO_DEMO"

    def test_entry_ok_without_volume_blocks_as_entry_unknown(self):
        orig = self.fake.order_send
        self.fake.order_send = lambda req: types.SimpleNamespace(retcode=10009, deal=0, order=77, volume=0.0, price=0.0, comment="ok")
        try:
            r, _ = self.open(volume=0.1)
        finally:
            self.fake.order_send = orig
        self.assertEqual(r["status"], "UNKNOWN")
        self.assertEqual(self.row()["state"], "ENTRY_UNKNOWN")             # before: REJECTED (symbol unblocked, position may exist)


# ====================================================================================================================== I0813
class TestClosingDealsOutBy(unittest.TestCase):
    def test_out_by_and_inout_are_closing_deals(self):
        D = types.SimpleNamespace
        deals = (D(ticket=1, entry=0, volume=0.1, price=2000.0, time=1.0, comment=""),
                 D(ticket=2, entry=3, volume=0.1, price=2010.5, time=2.0, comment="close by"),
                 D(ticket=3, entry=2, volume=0.1, price=2011.0, time=3.0, comment="inout"))
        fake = types.SimpleNamespace(history_deals_get=lambda position: deals, last_error=lambda: (1, "Success"))
        ex = SHExecutor(None, terminal=lambda fn: fn(fake))
        self.assertEqual([d["price"] for d in ex.closing_deals(5)], [2010.5, 2011.0])           # before: []


class TestReconcileDeferred(TS.Base):
    mode = "AUTO_DEMO"

    def _gone_without_deal(self):
        self.open(volume=0.3)
        row = self.row()
        del self.fake._positions[int(row["primary_ticket"])]                    # vanished, the closing deal not (yet) in the history
        return row

    def test_vanished_position_without_deal_waits_then_settles_unverified(self):
        row = self._gone_without_deal()
        e = row["fsm_obj"].entry
        row = self.step(e + 2.6, dt=1)                                          # TP1 crossed while frozen: no action at all
        self.assertNotEqual(row["state"], "CLOSED")                             # before: CLOSED at the SL price at once
        self.assertFalse(any(a["kind"] == "CLOSE_PARTIAL" for a in self.svc.store.actions(row["plan_id"])))
        for _ in range(3):
            row = self.step(e + 0.5, dt=25)
        self.assertEqual(row["state"], "CLOSED")
        self.assertFalse(row["result"]["price_verified"])
        kinds = [x["kind"] for x in self.svc.store.events(row["plan_id"])]
        self.assertIn("RECONCILED_UNVERIFIED", kinds)
        self.assertIn("RECONCILE_WAIT", kinds)

    def test_out_by_deal_gives_the_real_close_price(self):
        from masterquo.mt5.fake import Deal
        self.open(volume=0.3)
        row = self.row()
        tk = int(row["primary_ticket"])
        p = self.fake._positions.pop(tk)
        self.fake._deals.append(Deal(999, 0, 1, 1000, 1, 3, p["magic"], tk, 0.3, 2010.5, 0.0, 0.0, 0.0, 0.0, "XAUUSD-", "close by", 3))
        row = self.step(row["fsm_obj"].entry, dt=1)
        self.assertEqual(row["state"], "CLOSED")
        self.assertEqual(row["result"]["realized"][-1]["price"], 2010.5)        # before: SL / entry substitute
        self.assertTrue(row["result"]["price_verified"])

    def test_basket_with_open_hedge_is_settled_at_once(self):
        self.open("HEDGING", volume=0.4)
        b = self.row()["fsm_obj"]
        row = self.step(b.primary.entry - 1.5, dt=1)
        self.assertEqual(row["fsm_obj"].state, "HEDGED")
        del self.fake._positions[int(row["primary_ticket"])]
        row = self.step(b.primary.entry - 1.5, dt=1)
        b = row["fsm_obj"]
        self.assertEqual(b.primary.state, "CLOSED")                             # the lone hedge is unwound immediately, as before
        self.assertEqual(b.hedge.status, "CLOSED")
        self.assertIn("RECONCILED_UNVERIFIED", [x["kind"] for x in self.svc.store.events(row["plan_id"])])


# ====================================================================================================================== I0714
class TestReconcileTerminalNone(TS.Base):
    mode = "AUTO_DEMO"

    def _none(self):
        orig = self.fake.positions_get

        def pg(symbol=None, ticket=None, group=None):
            if symbol is not None:
                self.fake._last_error = (-10004, "No IPC connection")
                return None
            return orig(symbol=symbol, ticket=ticket, group=group)
        self.fake.positions_get = pg
        return orig

    def test_none_is_not_a_closed_position(self):
        self.open(volume=0.3)
        row = self.row()
        e = row["fsm_obj"].entry
        self._none()
        row = self.step(e + 2.6, dt=1)
        self.assertIn(row["state"], ("OPEN",))                                  # before: CLOSED with a fictitious SL result
        kinds = [x["kind"] for x in self.svc.store.events(row["plan_id"])]
        self.assertNotIn("RECONCILED_PRIMARY", kinds)
        self.assertFalse(any(a["kind"] == "CLOSE_PARTIAL" for a in self.svc.store.actions(row["plan_id"])))   # frozen tick

    def test_none_with_success_code_is_an_empty_list(self):
        fake = types.SimpleNamespace(positions_get=lambda symbol: None, last_error=lambda: (1, "Success"))
        self.assertEqual(SHExecutor(None, terminal=lambda fn: fn(fake)).terminal_positions("X"), [])
        fake2 = types.SimpleNamespace(positions_get=lambda symbol: None, last_error=lambda: (-10004, "No IPC"), positions_total=lambda: 2)
        with self.assertRaises(TerminalDataUnavailable):
            SHExecutor(None, terminal=lambda fn: fn(fake2)).terminal_positions("X")

    def test_no_hedge_in_a_tick_without_terminal_data(self):
        self.open("HEDGING", volume=0.4)
        b = self.row()["fsm_obj"]
        self._none()
        row = self.step(b.primary.entry - 1.5, dt=1)                            # price beyond the hedge trigger
        self.assertFalse(any(a["kind"] == "OPEN_H" for a in self.svc.store.actions(row["plan_id"])))
        self.assertEqual(row["fsm_obj"].state, "PRIMARY_OPEN")
        self.assertNotEqual(row["state"], "CLOSED")

    def test_plan_of_another_account_is_not_touched(self):
        self.open(volume=0.3)
        row = self.row()
        orig = self.fake.positions_get
        self.fake.positions_get = lambda symbol=None, ticket=None, group=None: () if symbol else orig(ticket=ticket)
        self.bridge.account_key = "Synthetic-Demo:5550002"
        ex2 = self.svc.executor(self.spec)
        self.t += 1
        self.svc.manage(ex2, self.spec, self.q(row["fsm_obj"].entry + 2.6), self.t, self.shc)
        row = self.row()
        self.assertNotEqual(row["state"], "CLOSED")                             # before: CLOSED (ticket 'missing' on the other account)
        self.assertEqual(self.svc.plan_view(row, None).get("flags"), ["INNY_RACHUNEK"])
        self.assertEqual(self.svc.store.actions(row["plan_id"])[-1]["kind"], "MODIFY_TP")   # nothing new sent

    def test_terminal_error_is_signalled_and_never_settled(self):
        self.open(volume=0.3)
        row = self.row()
        logged = []
        self.svc.log = types.SimpleNamespace(warn=lambda *a, **k: logged.append(("warn", a[1])), error=lambda *a, **k: logged.append(("error", a[1])),
                                             info=lambda *a, **k: None)

        def busy(symbol=None, ticket=None, group=None):
            raise RuntimeError("MT5Busy: worker not answering")
        self.fake.positions_get = busy
        e = row["fsm_obj"].entry
        for _ in range(4):
            row = self.step(e + 2.6, dt=25)
        self.assertEqual(row["state"], "OPEN")                                  # nothing assumed, nothing settled
        self.assertFalse(any(a["kind"] == "CLOSE_PARTIAL" for a in self.svc.store.actions(row["plan_id"])))
        waits = [x["payload"] for x in self.svc.store.events(row["plan_id"]) if x["kind"] == "RECONCILE_WAIT"]
        self.assertEqual([w["kind"] for w in waits], ["TERMINAL_ERROR", "TERMINAL_ERROR"])   # before: silent SKIP (no event, no alert)
        self.assertEqual(logged, [("warn", "RECONCILE_WAIT"), ("error", "RECONCILE_TERMINAL_ERROR")])   # once per episode

    def test_recover_without_data_rejects_nothing_and_repeats(self):
        self.fake.hang_order_send = True
        self.open(volume=0.1)
        self.fake.hang_order_send = False
        row = self.row()
        self.assertEqual(row["state"], "ENTRY_UNKNOWN")
        orig = self._none()
        out = self.svc.recover(self.ex, self.spec, self.t)
        self.assertEqual(out["rejected"], [])                                    # before: REJECTED 'brak pozycji w terminalu'
        self.assertTrue(out.get("incomplete"))
        self.assertEqual(self.row()["state"], "ENTRY_UNKNOWN")
        self.svc._tick()
        self.assertIsNone(self.svc.recovered_epoch)                              # repeated on the next tick
        self.fake.positions_get = orig
        self.fake._last_error = (1, "Success")
        self.svc._tick()
        self.assertEqual(self.svc.recovered_epoch, self.bridge.session_epoch)


# ====================================================================================================================== I0740
class TestHedgeCloseRetry(unittest.TestCase):
    def _reject(self, b, a, t):
        b.hedge.status = "OPEN"
        b.on_hedge_closed(a["action_id"] + f":rej{t}", t, 0, 0, ok=False, reason="REQUOTE", action_id=a["action_id"])

    def test_rejected_exit_close_is_retried_then_error(self):
        b = hedged_basket()
        acts = b._exit_all(2.0, "x")
        h = next(a for a in acts if a["kind"] == "CLOSE_HEDGE")
        self._reject(b, h, 3.0)
        self.assertEqual(b.state, "EXIT_PENDING")                                # before: ERROR (dead state, on_quote [])
        self.assertEqual(b.on_quote(3.0 + EXIT_RETRY_SECONDS / 2, 99.0, 99.1), [])   # spaced
        t = 3.0
        for n in range(2, HEDGE_CLOSE_MAX_TRIES + 1):
            t += EXIT_RETRY_SECONDS
            r = b.on_quote(t, 99.0, 99.1)
            self.assertEqual([a["kind"] for a in r], ["CLOSE_HEDGE"])
            self.assertNotEqual(r[0]["action_id"], h["action_id"])
            self.assertEqual(b.hedge.status, "CLOSING")
            self.assertEqual(b.on_quote(t + 60, 99.0, 99.1), [])                 # outcome unknown (CLOSING): never resent
            self._reject(b, r[0], t)
        self.assertEqual(b.state, "ERROR")
        self.assertIn("HEDGE_CLOSE_FAILED", b.transitions[-1]["why"])

    def test_exit_never_returns_to_primary_open(self):
        b = hedged_basket()
        b.hedge = None
        b.state, b.activations = "PRIMARY_OPEN", 0
        acts = b._exit_all(2.0, "x")
        b.on_primary_close_rejected(2.0, acts[0]["action_id"], "REQUOTE")
        self.assertEqual(b.state, "EXIT_PENDING")
        self.assertEqual(b.request_hedge(3.0, 0.5, "x"), [])
        self.assertEqual(b.on_quote(10.0, 99.0, 99.1, primary_close_ok=False), [])      # close of the primary in flight: no resend
        r = b.on_quote(10.0, 99.0, 99.1, primary_close_ok=True)
        self.assertEqual([(a["kind"], a["volume"]) for a in r], [("CLOSE_PRIMARY", 1.0)])

    def test_unwind_rejection_reevaluated_or_retried_when_lone(self):
        b = hedged_basket()
        a = b._unwind(2.0, "odbicie")[0]
        self._reject(b, a, 3.0)
        self.assertEqual(b.state, "HEDGED")                                      # before: UNWINDING with an OPEN leg, never retried
        lone = hedged_basket(primary_state_closed=True)
        lone.state = "HEDGED"
        a = lone._close_hedge_if_any(2.0, "pozycja główna zamknięta")[0]
        self._reject(lone, a, 3.0)
        self.assertEqual(lone.state, "UNWINDING")
        r = lone.on_quote(3.0 + EXIT_RETRY_SECONDS, 99.0, 99.1)
        self.assertEqual([x["kind"] for x in r], ["CLOSE_HEDGE"])

    def test_partial_close_rest_retried_in_exit(self):
        b = hedged_basket()
        h = next(a for a in b._exit_all(2.0, "x") if a["kind"] == "CLOSE_HEDGE")
        b.hedge.status = "OPEN"
        b.on_hedge_closed(h["action_id"] + ":r", 3.0, 0.2, 99.6)
        r = b.on_quote(3.0 + EXIT_RETRY_SECONDS, 99.0, 99.1)
        self.assertEqual([(x["kind"], x["volume"]) for x in r], [("CLOSE_HEDGE", 0.3)])

    def test_new_fields_roundtrip_and_old_records(self):
        b = hedged_basket()
        b.exit_retries, b.exit_round, b.last_exit_try = 2, 3, 12.5
        b2 = basket_load(basket_dump(b))
        self.assertEqual((b2.exit_retries, b2.exit_round, b2.last_exit_try), (2, 3, 12.5))
        d = basket_dump(b)
        for k in ("exit_retries", "exit_round", "last_exit_try"):
            d.pop(k)
        self.assertEqual(basket_load(d).exit_retries, 0)                         # a record of the previous version


class TestNoNewHedgeAfterRetriedClose(unittest.TestCase):
    def _b(self):
        b = hedged_basket()
        b.cfg.max_activations = 2
        return b

    def test_rejected_unwind_uses_up_the_activations(self):
        b = self._b()
        a = b._unwind(2.0, "odbicie", gated=True)[0]
        b.hedge.status = "OPEN"
        b.on_hedge_closed(a["action_id"] + ":rej", 3.0, 0, 0, ok=False, reason="REQUOTE", action_id=a["action_id"])
        self.assertEqual(b.activations, 2)                                       # before: 1 - a retried unwind led to OPEN_HEDGE H2
        r = b._unwind(3.0 + EXIT_RETRY_SECONDS, "odbicie", gated=True)
        b.hedge.status = "OPEN"
        b.on_hedge_closed(r[0]["action_id"] + ":r", 9.0, 0.5, 99.6, action_id=r[0]["action_id"])
        self.assertEqual(b.state, "PRIMARY_OPEN")
        self.assertEqual(b.hedge_decision(98.0, 98.1, structure_valid=True, risk_ok=True, risk_reason="", hedge_cost_price=0.1,
                                          reduce_cost_price=1.0)["decision"], "HOLD")

    def test_partial_unwind_uses_up_the_activations_cap_does_not(self):
        b = self._b()
        a = b._unwind(2.0, "odbicie")[0]
        b.hedge.status = "OPEN"
        b.on_hedge_closed(a["action_id"] + ":r", 3.0, 0.2, 99.6, action_id=a["action_id"])
        self.assertEqual(b.activations, 2)
        c = self._b()
        c.on_hedge_closed("B:CLOSE_HEDGE:CAP1:r", 3.0, 0.2, 99.6, action_id="B:CLOSE_HEDGE:CAP1")   # ratio-cap reduction (by design)
        self.assertEqual(c.activations, 1)
        d = self._b()
        a = d._unwind(2.0, "odbicie")[0]
        d.hedge.status = "OPEN"
        d.on_hedge_closed(a["action_id"] + ":r", 3.0, 0.5, 99.6, action_id=a["action_id"])   # closed in one go: as before
        self.assertEqual((d.activations, d.state), (1, "PRIMARY_OPEN"))


class TestNoRehedgeOnService(TS.Base):
    mode = "AUTO_DEMO"

    def test_second_hedge_not_opened_after_rejected_unwind(self):
        self.open("HEDGING", volume=0.4)
        row = self.row()
        b = row["fsm_obj"]
        b.cfg.max_activations = 2
        self.svc.store.update_plan(row["plan_id"], fsm=b, now=self.t)
        e = b.primary.entry
        row = self.step(e - 1.5, dt=1)
        h = row["fsm_obj"].hedge
        self.assertEqual((row["fsm_obj"].state, h.status), ("HEDGED", "OPEN"))
        up = round(h.entry + b.cfg.unwind_recovery_usd + 0.1, 2)
        self.fake.fail_next_order = 10004                                        # the unwind close is rejected once
        row = self.step(up, dt=1)
        self.assertEqual(row["fsm_obj"].state, "HEDGED")
        row = self.step(up, dt=EXIT_RETRY_SECONDS + 1)                           # retried unwind succeeds
        self.assertEqual((row["fsm_obj"].state, row["fsm_obj"].hedge.status), ("PRIMARY_OPEN", "CLOSED"))
        for _ in range(2):
            row = self.step(e - 1.5, dt=1)                                       # beyond the hedge trigger again
        n_open_h = sum(1 for a in self.svc.store.actions(row["plan_id"]) if a["kind"] == "OPEN_H")
        self.assertEqual(n_open_h, 1)                                            # before: 2 (OPEN:H2 the base code never sent)


class TestReturnPartialRestNotResent(TS.Base):
    def _basket(self):
        self.open("HEDGING", volume=0.4)
        row = self.row()
        b = row["fsm_obj"]
        b.hedge, b.state, b.activations = Leg2("SELL" if b.primary.side == "BUY" else "BUY", 0.2, b.primary.entry - 1.0, self.t), "HEDGED", 1
        return row, b

    def test_partial_hedge_close_at_return_stays_closing(self):
        row, b = self._basket()
        acts = b._exit_all(self.t, "x")
        ans = [{"status": "FILLED", "volume": b.primary.remaining, "price": b.primary.entry} if a["kind"] == "CLOSE_PRIMARY" else
               {"status": "PARTIAL", "volume": 0.1, "price": b.hedge.entry} for a in acts]
        self.svc.process(_StubEx(ans, rest_cancelled=False), row, b, acts, self.spec, self.q(), self.t)
        self.assertEqual((b.hedge.status, b.hedge.volume), ("CLOSING", 0.1))    # before: OPEN -> rest re-requested 5 s later
        self.assertEqual(b.on_quote(self.t + 60, 1.0, 1.1, primary_close_ok=True), [])
        row2, b2 = self._basket()
        acts = [a for a in b2._exit_all(self.t, "x") if a["kind"] == "CLOSE_HEDGE"]
        self.svc.process(_StubEx([{"status": "PARTIAL", "volume": 0.1, "price": b2.hedge.entry}], rest_cancelled=True), row2, b2, acts,
                         self.spec, self.q(), self.t)
        self.assertEqual(b2.hedge.status, "OPEN")                                # FOK / IOC: the rest is cancelled - retried
        self.assertEqual([a["kind"] for a in b2.on_quote(self.t + 60, 1.0, 1.1)], ["CLOSE_HEDGE"])

    def test_partial_primary_exit_at_return_is_a_close_in_flight(self):
        row, b = self._basket()
        b.state = "EXIT_PENDING"
        aid = f"{row['plan_id']}:CLOSE_PRIMARY:EXIT"
        self.svc.store.claim_action({"action_id": aid, "plan_id": row["plan_id"], "kind": "CLOSE_PRIMARY", "volume": 0.4}, self.t)
        self.svc.store.finish_action(aid, "DONE", {"status": "PARTIAL", "volume": 0.2, "price": 1.0}, self.t)
        self.assertFalse(self.svc._primary_close_free(row, b, _StubEx([], rest_cancelled=False)))   # before: True (EXIT_R sent)
        self.assertTrue(self.svc._primary_close_free(row, b, _StubEx([], rest_cancelled=True)))


class TestExitIsFinalOnService(TS.Base):
    mode = "AUTO_DEMO"

    def test_rejected_exit_retry_never_opens_a_hedge(self):
        self.open("HEDGING", volume=0.4)
        row = self.row()
        b = row["fsm_obj"]
        b.cfg.max_activations = 2
        self.svc.store.update_plan(row["plan_id"], fsm=b, now=self.t)
        e = b.primary.entry
        self.fake.fail_next_order = 10004                                        # the exit close of the primary is rejected (requote)
        row = self.step(e - 1.85, dt=1)                                          # beyond the invalidation -> EXIT
        self.assertEqual(row["fsm_obj"].state, "EXIT_PENDING")                   # before: back to PRIMARY_OPEN
        self.fake.fail_next_order = 10004                                        # the first retry is rejected too
        row = self.step(e - 1.5, dt=EXIT_RETRY_SECONDS)                          # structure valid again, beyond the hedge trigger
        self.assertFalse(any(a["kind"] == "OPEN_H" for a in self.svc.store.actions(row["plan_id"])))
        self.assertEqual(row["fsm_obj"].state, "EXIT_PENDING")
        row = self.step(e - 1.5, dt=EXIT_RETRY_SECONDS)
        self.assertEqual(row["state"], "CLOSED")
        self.assertFalse(any(a["kind"] == "OPEN_H" for a in self.svc.store.actions(row["plan_id"])))


# ====================================================================================================================== I0814
class TestCapRejectReleasesId(TS.Base):
    def _pack_row(self, b):
        return {"plan_id": b.basket_id, "exec_mode": "PAPER", "instrument": "XAUUSD",
                "plan": {"pack": {"structure_view": {}}, "strategy_id": "PMW_HG01", "instrument_profile": {}}}

    def _basket(self):
        p = Position("PK", "BUY", 100.0, 1.0, 99.0, [Leg("TP1", 101.0, 0.6), Leg("TP2", 102.0, 0.4)])
        b = Basket("PK", p, HedgeConfig(trigger_adverse_usd=1e12, ratio=0.5, max_ratio=0.5), 100.0, opened_at=0.0)
        b.hedge, b.state, b.activations = Leg2("SELL", 0.5, 99.5, 1.0), "HEDGED", 1
        p.on_fill("f1", "TP1", 0.6, 101.0)                                      # base 0.4 -> cap 0.2, hedge 0.5: excess
        return b

    def test_rejected_cap_releases_its_id_and_policy_runs(self):
        from masterquo.sh.pack import policies as POL
        calls = []
        orig = POL.decision
        POL.decision = lambda vid, **kw: calls.append(kw.get("hedged")) or {"decision": "HOLD", "reason": "stub"}
        self.svc.pack = None
        try:
            b = self._basket()
            row = self._pack_row(b)
            acts = self.svc.pack_hedge_step(row, b, self.spec, self.q(), self.t)
            self.assertEqual([a["action_id"] for a in acts], ["PK:CLOSE_HEDGE:CAP1"])
            self.assertEqual(calls, [])
            self.svc.store.update_plan = lambda *a, **k: None                    # process() only feeds the result back here
            self.svc.process(_StubEx([{"status": "REJECTED", "reason": "REQUOTE"}]), dict(row, plan=dict(row["plan"], instrument_profile={})),
                             b, acts, self.spec, self.q(), self.t)
            self.assertNotIn("PK:CLOSE_HEDGE:CAP1", b.issued)                    # before: still issued (CLOSE_HEDGE:1 released instead)
            self.assertEqual(b.state, "HEDGED")
            self.assertEqual(self.svc.pack_hedge_step(row, b, self.spec, self.q(), self.t + 1), [])    # spaced retry; policy evaluated
            self.assertEqual(calls, [True])                                      # before: 0 calls - policy dead until the basket ends
            acts = self.svc.pack_hedge_step(row, b, self.spec, self.q(), self.t + 10)
            self.assertEqual([a["action_id"] for a in acts], ["PK:CLOSE_HEDGE:CAP1"])
        finally:
            POL.decision = orig

    def test_no_hedge_intent_next_to_an_open_leg(self):
        from masterquo.sh.pack import policies as POL
        orig = POL.decision
        POL.decision = lambda vid, **kw: {"decision": "HEDGE", "reason": "stub", "ratio": 0.5}
        opened = []
        self.svc.arc = types.SimpleNamespace(intents=types.SimpleNamespace(open=lambda **kw: opened.append(kw) or {"status": "BLOCKED"}))
        self.svc.pack = None
        try:
            b = self._basket()
            b.issued.add("PK:CLOSE_HEDGE:CAP1")                                  # CAP in flight: the policy runs, HEDGE is refused
            self.assertEqual(self.svc.pack_hedge_step(self._pack_row(b), b, self.spec, self.q(), self.t), [])
            b2 = self._basket()
            b2.primary = Position("PK", "BUY", 100.0, 1.0, 99.0, [Leg("TP1", 101.0, 0.6), Leg("TP2", 102.0, 0.4)])   # no excess
            self.assertEqual(self.svc.pack_hedge_step(self._pack_row(b2), b2, self.spec, self.q(), self.t), [])
            self.assertEqual(opened, [])                                         # before: arc.intents.open(kind='HEDGE') reached
        finally:
            POL.decision = orig


if __name__ == "__main__":
    unittest.main()
