"""PMW-SH-1 stage 4: shared risk engine (sizing, limits, account mode), conflict coordinator, persistent store (idempotent
actions, single owner, state-machine serialization for restart), executor in PAPER and against the SIMULATED terminal
(hedging and netting accounts). No real account is touched."""
import unittest

import _env  # noqa: F401
from _env import TempData

NOW = 1_760_000_000.0


def _spec(vmin=0.01, step=0.01):
    from masterquo.sh.units import SymbolSpec
    return SymbolSpec("XAUUSD-", 0.01, 1.0, 100, vmin, step, 100, 2, "USD", source="TEST")


def _setup(strategy="SCALPING", side="BUY", **kw):
    s = {"signal_id": f"SIG-{strategy}-{side}", "strategy": strategy, "instrument": "XAUUSD", "symbol": "XAUUSD-", "side": side,
         "status": "READY", "valid_until": NOW + 600, "entry_ref": 2000.2, "sl": 1998.2 if side == "BUY" else 2002.2,
         "costs": {"round_trip_price": 0.3}, "model_mode": "OGRANICZONA", "created_at": NOW}
    s.update(kw)
    return s


ACC = {"equity": 10000.0, "margin": 0.0, "margin_free": 10000.0, "margin_mode": "HEDGING", "margin_per_lot": 2000.0}
Q = {"age_s": 0.5, "spread": 0.2, "bid": 2000.0, "ask": 2000.2}


class Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.sh import config as C
        self.cfg = C.load()
        self.C = C

    def tearDown(self):
        self.td.close()

    def risk(self, setup=None, prof=None, acc=None, state=None, mode="PAPER", spec=None, quote=Q, cfg=None):
        from masterquo.sh import risk as R
        s = setup or _setup()
        return R.evaluate(setup=s, spec=spec or _spec(), prof=prof or self.C.profile(self.cfg, "XAUUSD", s["strategy"]), cfg=cfg or self.cfg,
                          inst="XAUUSD", account=acc or ACC, state=state or {}, exec_mode=mode, now=NOW, quote=quote)


class Risk(Base):
    def test_sizing_from_sl_distance(self):
        r = self.risk()
        self.assertEqual(r["status"], "PASS", r.get("reasons"))
        # 0.5 % of 10 000 = 50 USD; loss/lot = (2.0 + 0.3) * 100 = 230 -> 0.21 lot (floor), legs 50/30/20 %
        self.assertAlmostEqual(r["volume"], 0.21)
        self.assertAlmostEqual(sum(r["legs"]), 0.21)
        self.assertEqual(r["legs"], [0.1, 0.06, 0.05])
        self.assertLessEqual(r["risk_money"], 50.0)

    def test_fallback_two_legs_and_infeasible(self):
        acc = dict(ACC, equity=1000.0)            # 5 USD budget -> 0.02 lot: three legs impossible at min 0.01
        r = self.risk(acc=acc)
        self.assertEqual(r["status"], "PASS", r.get("reasons"))
        self.assertEqual(r["legs"], [0.01, 0.01])
        self.assertIn("FALLBACK", r["shares_used"]["variant"])
        r2 = self.risk(acc=dict(ACC, equity=300.0))
        self.assertEqual(r2["status"], "BLOCK")
        self.assertTrue(any("min_volume" in x for x in r2["reasons"]))

    def test_hedging_blocked_on_netting_account(self):
        r = self.risk(setup=_setup("HEDGING", sl=1996.2), acc=dict(ACC, margin_mode="NETTING"))
        self.assertEqual(r["status"], "BLOCK")
        self.assertTrue(any("account_hedging" in x for x in r["reasons"]))
        self.assertEqual(self.risk(setup=_setup("SCALPING"), acc=dict(ACC, margin_mode="NETTING"))["status"], "PASS")

    def test_hedging_exposure_counts_max_hedge(self):
        r = self.risk(setup=_setup("HEDGING", sl=1996.2))
        self.assertEqual(r["status"], "PASS", r.get("reasons"))
        self.assertAlmostEqual(r["gross_exposure_after"], r["volume"] * 1.5)
        self.assertLessEqual(r["basket_loss_limit_money"], 100.0)

    def test_limits(self):
        st = {"daily_realized_money": -250.0}
        self.assertTrue(any("daily_loss" in x for x in self.risk(state=st)["reasons"]))
        st = {"last_close_at": {"SCALPING": NOW - 120}}
        self.assertTrue(any("cooldown" in x for x in self.risk(state=st)["reasons"]))
        st = {"recent_signals": [{"signal_id": "X", "strategy": "SCALPING", "side": "BUY", "created_at": NOW - 60}]}
        self.assertTrue(any("duplicate" in x for x in self.risk(state=st)["reasons"]))
        self.assertTrue(any("foreign_owner" in x for x in self.risk(state={"foreign_positions": 1})["reasons"]))
        self.assertTrue(any("quote_fresh" in x for x in self.risk(quote=dict(Q, age_s=30))["reasons"]))
        self.assertTrue(any("spread" in x for x in self.risk(quote=dict(Q, spread=0.9))["reasons"]))
        self.assertTrue(any("not_expired" in x for x in self.risk(setup=_setup(valid_until=NOW - 1))["reasons"]))

    def test_real_modes(self):
        r = self.risk(mode="AUTO_DEMO")
        self.assertTrue(any("model_mode" in x for x in r["reasons"]))                   # LIMITED mode: no AUTO
        self.assertTrue(any("commission_known" in x for x in r["reasons"]))
        self.assertTrue(any("exec_mode" in x for x in self.risk(mode="AUTO_LIVE", setup=_setup(model_mode="PEŁNA"))["reasons"]))


class Coordinator(Base):
    def arb(self, ready, open_plans=(), foreign=0, **cfg):
        from masterquo.sh.coordinator import arbitrate
        return {d["strategy"]: d for d in arbitrate(ready, open_plans=list(open_plans), foreign_positions=foreign,
                                                     cfg={**self.cfg, **cfg}, symbol="XAUUSD-")}

    def test_matrix(self):
        sc, hb = _setup("SCALPING", "BUY"), _setup("HEDGING", "BUY")
        d = self.arb([sc, hb])
        self.assertEqual((d["HEDGING"]["decision"], d["SCALPING"]["decision"]), ("PROCEED", "WAIT"))     # priority
        d = self.arb([sc, _setup("HEDGING", "SELL")])
        self.assertEqual({x["decision"] for x in d.values()}, {"WAIT"})                                  # opposite READY
        d = self.arb([sc], open_plans=[{"strategy": "HEDGING", "symbol": "XAUUSD-", "side": "BUY", "state": "HEDGED"}],
                     allow_parallel_same_symbol=True)
        self.assertEqual(d["SCALPING"]["decision"], "WAIT")                                               # basket owns symbol
        d = self.arb([sc], open_plans=[{"strategy": "SCALPING", "symbol": "XAUUSD-", "side": "BUY", "state": "OPEN"}])
        self.assertEqual(d["SCALPING"]["decision"], "WAIT")
        self.assertEqual(self.arb([sc], foreign=1)["SCALPING"]["decision"], "WAIT")
        self.assertEqual(self.arb([sc])["SCALPING"]["decision"], "PROCEED")


class Store(Base):
    def db(self):
        from masterquo.db.database import Database
        from masterquo.sh.store import SHStore
        return SHStore(Database())

    def test_action_idempotency_and_owner(self):
        st = self.db()
        a = {"action_id": "P1:CLOSE_PARTIAL:TP1", "plan_id": "P1", "kind": "CLOSE_PARTIAL"}
        self.assertTrue(st.claim_action(a)["claimed"])
        self.assertFalse(st.claim_action(a)["claimed"])                                 # in flight: never resent
        st.finish_action(a["action_id"], "REJECTED", {"status": "REJECTED"})
        self.assertEqual(st.claim_action(a)["attempt"], 2)                              # explicit retry after a rejection
        st.finish_action(a["action_id"], "DONE", {"status": "FILLED", "price": 1.0})
        r = st.claim_action(a)
        self.assertEqual((r["claimed"], r["status"], r["result"]["price"]), (False, "DONE", 1.0))
        self.assertTrue(st.own("acc", 5, "P1", "P"))
        self.assertTrue(st.own("acc", 5, "P1", "P"))
        self.assertFalse(st.own("acc", 5, "P2", "P"))                                    # one owner per position

    def test_plan_once_per_signal_and_fsm_roundtrip(self):
        from masterquo.sh.hedge_fsm import Basket, HedgeConfig
        from masterquo.sh.lifecycle import Leg, Position
        from masterquo.sh.store import fsm_dump, fsm_load
        st = self.db()
        plan = {"plan_id": "P1", "signal_id": "S1", "strategy": "HEDGING", "instrument": "XAUUSD", "symbol": "XAUUSD-", "side": "BUY",
                "exec_mode": "PAPER", "config_hash": "h"}
        self.assertTrue(st.create_plan(plan))
        self.assertFalse(st.create_plan(dict(plan, plan_id="P2")))                      # same signal -> no second plan
        pos = Position("P1", "BUY", 2000.0, 0.3, 1997.0, [Leg("TP1", 2003.5, 0.1), Leg("TP2", 2005.0, 0.1), Leg("TP3", 2009.0, 0.1)])
        b = Basket("P1", pos, HedgeConfig(trigger_adverse_usd=1.5, ratio=0.5, max_ratio=0.5), 100.0, NOW)
        b.on_quote(NOW, 2003.6, 2003.8)
        b.on_primary_fill("e1", NOW, "TP1", 0.1, 2003.5)
        st.update_plan("P1", state="PRIMARY_OPEN", fsm=b)
        b2 = st.plan("P1")["fsm_obj"]
        self.assertEqual(fsm_dump(b2), fsm_dump(b))
        self.assertEqual(b2.primary.on_fill("e1", "TP1", 0.1, 2003.5), [])               # seen event survives a restart
        self.assertEqual(b2.on_quote(NOW, 2003.6, 2003.8), [])                          # issued action not re-issued
        self.assertEqual(len(st.open_plans("XAUUSD-")), 1)
        self.assertIsInstance(fsm_load(fsm_dump(pos)), Position)


class Executor(Base):
    def make(self, hedging=True, mode_fake=True):
        from masterquo.db.database import Database
        from masterquo.mt5.fake import FakeMT5
        from masterquo.sh.executor import SHExecutor
        from masterquo.sh.store import SHStore
        self.fake = FakeMT5(hedging=hedging)
        self.fake.initialize()
        self.store = SHStore(Database())
        info = self.fake.symbol_info("XAUUSD-")._asdict()
        return SHExecutor(self.store, terminal=lambda fn: fn(self.fake), account_key="acc", symbol_info=info)

    def plan(self, pid="PLN-000001"):
        return {"plan_id": pid, "symbol": "XAUUSD-"}

    def quote(self):
        t = self.fake.symbol_info_tick("XAUUSD-")
        return {"bid": t.bid, "ask": t.ask}

    def test_signals_and_live_blocked(self):
        ex = self.make()
        q = self.quote()
        for mode in ("SIGNALS", "AUTO_LIVE"):
            r = ex.open(self.plan(), role="P", side="BUY", volume=0.1, sl=q["bid"] - 3, tp=0, mode=mode, quote=q, tag="P")
            self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(self.fake.positions_get(), ())

    def test_lock_blocks_terminal(self):
        ex = self.make()
        ex.locked = lambda: True
        q = self.quote()
        self.assertEqual(ex.open(self.plan(), role="P", side="BUY", volume=0.1, sl=q["bid"] - 3, tp=0, mode="AUTO_DEMO", quote=q, tag="P")["reason"],
                         "EXECUTION_LOCKED")

    def test_demo_open_partial_modify_idempotent(self):
        ex = self.make()
        q = self.quote()
        r = ex.open(self.plan(), role="P", side="BUY", volume=0.3, sl=round(q["bid"] - 3, 2), tp=0, mode="AUTO_DEMO", quote=q, tag="P")
        self.assertEqual(r["status"], "FILLED", r)
        tk = r["ticket"]
        p = self.fake.positions_get(ticket=tk)[0]
        self.assertEqual((p.magic, p.comment), (41082100, "SH:N-000001:P"))
        again = ex.open(self.plan(), role="P", side="BUY", volume=0.3, sl=round(q["bid"] - 3, 2), tp=0, mode="AUTO_DEMO", quote=q, tag="P")
        self.assertTrue(again.get("replayed"))
        self.assertEqual(len(self.fake.positions_get()), 1)                              # retry did not open a second position
        act = {"action_id": "PLN-000001:CLOSE_PARTIAL:TP1", "plan_id": "PLN-000001", "kind": "CLOSE_PARTIAL", "volume": 0.1}
        r1 = ex.perform(self.plan(), act, mode="AUTO_DEMO", quote=q, ticket=tk, side_of_position="BUY")
        r2 = ex.perform(self.plan(), act, mode="AUTO_DEMO", quote=q, ticket=tk, side_of_position="BUY")
        self.assertEqual(r1["status"], "FILLED")
        self.assertTrue(r2.get("replayed"))
        self.assertAlmostEqual(self.fake.positions_get(ticket=tk)[0].volume, 0.2)       # closed once only
        be = {"action_id": "PLN-000001:MODIFY_SL:BE1", "plan_id": "PLN-000001", "kind": "MODIFY_SL", "sl": round(r["price"], 2)}
        self.assertEqual(ex.perform(self.plan(), be, mode="AUTO_DEMO", quote=q, ticket=tk, side_of_position="BUY")["status"], "DONE")
        self.assertAlmostEqual(self.fake.positions_get(ticket=tk)[0].sl, round(r["price"], 2))
        other = {"action_id": "OTHER:CLOSE_RUNNER:TP3", "plan_id": "OTHER", "kind": "CLOSE_RUNNER", "volume": 0.2}
        self.assertEqual(ex.perform({"plan_id": "OTHER", "symbol": "XAUUSD-"}, other, mode="AUTO_DEMO", quote=q, ticket=tk,
                                    side_of_position="BUY")["reason"], "POZYCJA_NIE_NALEŻY_DO_PLANU")

    def test_rejection_and_unknown_not_resent(self):
        ex = self.make()
        q = self.quote()
        self.fake.fail_next_order = 10006
        r = ex.open(self.plan(), role="H", side="SELL", volume=0.1, sl=0, tp=0, mode="AUTO_DEMO", quote=q, tag="H1")
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(self.fake.positions_get(), ())
        self.fake.hang_order_send = True
        u = ex.open(self.plan("PLN-000002"), role="P", side="BUY", volume=0.1, sl=round(q["bid"] - 3, 2), tp=0, mode="AUTO_DEMO", quote=q, tag="P")
        self.assertEqual(u["status"], "UNKNOWN")
        self.fake.hang_order_send = False
        u2 = ex.open(self.plan("PLN-000002"), role="P", side="BUY", volume=0.1, sl=round(q["bid"] - 3, 2), tp=0, mode="AUTO_DEMO", quote=q, tag="P")
        self.assertEqual(u2["status"], "UNKNOWN")                                        # never resent blindly
        self.assertEqual(self.fake.positions_get(), ())

    def test_paper_modify_rejected_beyond_price(self):
        ex = self.make()
        q = {"bid": 2000.0, "ask": 2000.2}
        act = {"action_id": "P:MODIFY_SL:BE1", "plan_id": "P", "kind": "MODIFY_SL", "sl": 2000.5}
        self.assertEqual(ex.perform({"plan_id": "P", "symbol": "XAUUSD-"}, act, mode="PAPER", quote=q, ticket=None, side_of_position="BUY")["status"],
                         "REJECTED")


if __name__ == "__main__":
    unittest.main()
