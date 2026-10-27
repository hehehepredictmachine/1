"""PMW-SH-1 acceptance (service level): SCALPING and HEDGING plans driven by the SAME service code in PAPER (simulated fills)
and AUTO_DEMO against the SIMULATED terminal. Covers: targets from the actual fill, partial split, BE only after the confirmed
TP2, SL-modify rejection fallback, gap through the stop, repeated quotes (idempotency), restart / reconciliation with open
positions, hedge rejection, hedge on a netting account, basket accounting. No real account, no external publication."""
import unittest

import _env  # noqa: F401
from _env import TempData

NOW = 1_760_000_000.0


class Bridge:
    """Minimal bridge stand-in: quotes and account controlled by the test."""

    def __init__(self, fake=None, margin_mode="HEDGING"):
        self.fake = fake
        self.account_key = "Synthetic-Demo:5550001"
        self.session_epoch = 1
        self.q = {"bid": 2000.0, "ask": 2000.2}
        self.acc = {"equity": 10000.0, "margin": 0.0, "free_margin": 10000.0, "margin_mode": margin_mode, "trade_mode": "DEMO", "currency": "USD"}
        self.symbol_info = (fake.symbol_info("XAUUSD-")._asdict() if fake else
                            {"name": "XAUUSD-", "trade_tick_size": 0.01, "trade_tick_value": 1.0, "trade_contract_size": 100, "volume_min": 0.01,
                             "volume_step": 0.01, "volume_max": 100, "digits": 2, "currency_profit": "USD", "point": 0.01, "filling_mode": 1})

    def quote_status(self):
        return {"bid": self.q["bid"], "ask": self.q["ask"], "age_seconds": 0.3}

    def account_status(self):
        return dict(self.acc)

    def calc_margin(self, side, vol, price):
        return 2000.0 * vol

    def bars(self, tf, n, include_forming=False):
        return []


class Modes:
    def __init__(self, mode):
        self.mode = mode

    def gate(self, key, **kw):
        return {"mode": self.mode, "allowed": True, "reason_codes": []}


class Log:
    def __getattr__(self, name):
        return lambda *a, **k: None


def mk_setup(spec, strategy="SCALPING", side="BUY", ref=2000.2, sl_dist=2.0, now=NOW):
    from masterquo.sh import config as C
    prof = C.profile(C.load(), "XAUUSD", strategy)
    tps = []
    for name, d, sh in zip(("TP1", "TP2", "TP3"), prof["tp_usd"], prof["shares"]):
        t = spec.target(ref, side, d)
        tps.append({"name": name, "distance_requested": d, "price": t["price"], "distance_actual": t["actual_distance"], "rounding_diff": t["rounding_diff"],
                    "share": sh})
    return {"signal_id": f"SH-{strategy[:4]}{side}{int(ref * 100)}", "strategy": strategy, "instrument": "XAUUSD", "symbol": spec.symbol, "side": side,
            "status": "READY", "entry_ref": ref, "sl": spec.stop(ref, side, sl_dist), "tps": tps, "shares": prof["shares"],
            "be": {"after": "TP2", "rule": "ENTRY_PLUS_COSTS", "offset_price": 0.3}, "invalidation": spec.stop(ref, side, sl_dist * 0.9),
            "entry_zone": [ref - 1, ref], "mode": "CONTINUATION", "costs": {"round_trip_price": 0.3}, "net_rr": 1.2, "horizon_minutes": 30,
            "position_max_minutes": prof["position_max_minutes"], "valid_until": now + 600, "model_mode": "OGRANICZONA",
            "probability": {"status": "BRAK_MODELU_ZDARZENIA"}, "score": {"value": 90}, "created_at": now}


class Base(unittest.TestCase):
    mode = "PAPER"
    fake_kw = None
    margin_mode = "HEDGING"

    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        from masterquo.sh.service import SHService
        self.cfg_store = ConfigStore()
        self.db = Database()
        self.fake = None
        term = None
        if self.mode == "AUTO_DEMO":
            from masterquo.mt5.fake import FakeMT5
            self.fake = FakeMT5(**(self.fake_kw or {}))
            self.fake.initialize()
            term = lambda fn: fn(self.fake)  # noqa: E731
        self.bridge = Bridge(self.fake, self.margin_mode)
        self.t = NOW
        self.svc = SHService(self.cfg_store, self.bridge, self.db, None, Log(), Modes(self.mode), clock=lambda: self.t, terminal=term)
        from masterquo.sh import config as C
        self.shc = C.load()
        self.spec = self.svc.spec(self.svc.account())
        self.ex = self.svc.executor(self.spec)

    def tearDown(self):
        self.td.close()

    def open(self, strategy="SCALPING", side="BUY", volume=0.3, ref=None):
        if self.fake:
            t = self.fake.symbol_info_tick("XAUUSD-")
            self.bridge.q = {"bid": t.bid, "ask": t.ask}
        ref = ref or (self.bridge.q["ask"] if side == "BUY" else self.bridge.q["bid"])
        su = mk_setup(self.spec, strategy, side, ref=ref, now=self.t)
        risk = {"volume": volume, "legs": self.spec.split(volume, su["shares"])["legs"], "shares_used": {"variant": "PRIMARY", "shares": su["shares"]},
                "risk_money": 2.3 * volume * 100, "basket_loss_limit_money": 2.3 * volume * 100}
        q = self.q()
        r = self.svc.open_plan(self.ex, su, risk, self.spec, q, self.mode, self.t, self.shc, "XAUUSD", {"vol": {"atr_m5": 1.5}})
        return r, su

    def q(self, bid=None, spread=0.2):
        if bid is not None:
            self.bridge.q = {"bid": bid, "ask": round(bid + spread, 2)}
        b = self.bridge.q
        return {"bid": b["bid"], "ask": b["ask"], "spread": round(b["ask"] - b["bid"], 4), "age_s": 0.3, "time": self.t}

    def step(self, bid, spread=0.2, dt=60):
        self.t += dt
        self.svc.manage(self.ex, self.spec, self.q(bid, spread), self.t, self.shc)
        return self.row()

    def row(self):
        rows = self.db.query("SELECT plan_id FROM sh_plans ORDER BY created_at DESC LIMIT 1")
        return self.svc.store.plan(rows[0]["plan_id"]) if rows else None


class PaperScalping(Base):
    def test_full_cycle_be_after_confirmed_tp2(self):
        r, su = self.open()
        self.assertEqual(r["status"], "OPEN", r)
        row = self.row()
        pos = row["fsm_obj"]
        fill = pos.entry
        self.assertAlmostEqual(fill, 2000.2 + 0.05)                                     # PAPER: ask + configured slippage
        self.assertEqual([lg.price for lg in pos.legs], [round(fill + 2.5, 2), round(fill + 3.0, 2), round(fill + 5.0, 2)])   # from the FILL
        self.assertEqual([lg.volume for lg in pos.legs], [0.15, 0.09, 0.06])
        self.step(2002.0)
        self.assertEqual(self.row()["fsm_obj"].state, "OPEN")
        row = self.step(fill + 2.55)                                                    # TP1 on the bid
        self.assertEqual(row["fsm_obj"].legs[0].status, "DONE")
        self.assertEqual(row["fsm_obj"].be_status, "NOT_REQUESTED")                     # no BE after TP1
        row = self.step(fill + 2.55)                                                    # same quote again: nothing new
        self.assertAlmostEqual(row["fsm_obj"].remaining, 0.15)
        row = self.step(fill + 3.1)
        p = row["fsm_obj"]
        self.assertEqual((p.legs[1].status, p.be_status), ("DONE", "SET"))              # BE after the CONFIRMED TP2 fill
        self.assertAlmostEqual(p.sl, round(fill + 0.3, 10))
        row = self.step(fill + 0.1)                                                     # back to BE -> runner stopped
        self.assertEqual(row["state"], "CLOSED")
        res = row["result"]
        self.assertEqual(len(res["realized"]), 3)
        self.assertGreater(res["net_money"], 0)
        self.assertFalse(res["commission_known"])
        acts = self.db.query("SELECT kind, status FROM sh_actions WHERE plan_id=?", (row["plan_id"],))
        self.assertEqual(sum(1 for a in acts if a["kind"] == "CLOSE_PARTIAL"), 2)        # each partial exactly once

    def test_gap_through_stop_fills_worse(self):
        self.open()
        row = self.step(1995.0)                                                          # gap far below SL 1998.2
        self.assertEqual(row["state"], "CLOSED")
        self.assertAlmostEqual(row["result"]["realized"][0]["price"], 1995.0)
        self.assertLess(row["result"]["r_multiple"], -1.0)                               # a stop does not cap the loss in a gap

    def test_sell_targets_and_time_limit(self):
        r, _ = self.open(side="SELL")
        p = self.row()["fsm_obj"]
        self.assertEqual([lg.price for lg in p.legs], [round(p.entry - 2.5, 2), round(p.entry - 3.0, 2), round(p.entry - 5.0, 2)])
        self.step(p.entry - 0.5, dt=60 * 91)
        self.assertEqual(self.row()["state"], "CLOSED")
        self.assertIn("TIME_LIMIT", [x["leg"] for x in self.row()["result"]["realized"]])

    def test_infeasible_partial_fill_closes(self):
        r, _ = self.open(volume=0.02)                                                   # three legs impossible, fallback 0.6/0.4 -> 0.01/0.01
        p = self.row()["fsm_obj"]
        self.assertEqual([lg.name for lg in p.legs], ["TP1", "TP2"])


class ManualClose(Base):
    def test_close_plan_all_legs_idempotent(self):
        self.open("HEDGING", volume=0.4)
        b = self.row()["fsm_obj"]
        self.step(b.primary.entry - 1.3)
        self.assertEqual(self.row()["fsm_obj"].state, "HEDGED")
        r = self.svc.close_plan(self.row()["plan_id"])
        self.assertEqual(r, {"ok": True, "state": "CLOSED"})
        self.assertEqual(self.svc.close_plan(self.row()["plan_id"])["error"], "PLAN_NOT_OPEN")
        res = self.row()["result"]
        self.assertEqual(res["hedge_activations"], 1)
        self.assertNotEqual(res["hedge_money"], 0)


class PaperHedging(Base):
    def test_hedge_unwind_and_basket_accounting(self):
        r, su = self.open("HEDGING", volume=0.4)
        b = self.row()["fsm_obj"]
        e = b.primary.entry
        self.assertEqual([round(lg.price - e, 2) for lg in b.primary.legs], [3.5, 5.0, 9.0])
        row = self.step(e - 1.3)                                                        # adverse >= 0.5 * SL (2.0+) -> hedge
        b = row["fsm_obj"]
        self.assertEqual(b.state, "HEDGED", b.transitions)
        self.assertAlmostEqual(b.hedge.volume, 0.2)                                     # ratio 0.5 of the current primary
        row = self.step(e - 1.3 + 1.6)                                                  # recovery >= 1.0 * ATR5 (1.5) -> unwind
        b = row["fsm_obj"]
        self.assertEqual(b.state, "PRIMARY_OPEN")
        self.assertEqual(b.hedge.status, "CLOSED")
        self.assertLess(b.hedge_realized_money, 0)
        self.step(e - 1.3)                                                              # activation budget used: no second hedge
        self.assertEqual(self.row()["fsm_obj"].activations, 1)
        for px in (e + 3.6, e + 5.1, e + 9.1):
            row = self.step(px)
        self.assertEqual(row["state"], "CLOSED")
        res = row["result"]
        self.assertAlmostEqual(res["gross_money"], res["primary_money"] + res["hedge_money"], places=2)
        self.assertEqual(res["hedge_activations"], 1)

    def test_basket_exit_on_invalidation(self):
        self.open("HEDGING", volume=0.4)
        b = self.row()["fsm_obj"]
        row = self.step(b.primary.sl - 0.5)
        self.assertEqual(row["state"], "CLOSED")


class PaperHedgingNetting(Base):
    margin_mode = "NETTING"

    def test_netting_never_hedges_silently(self):
        self.open("HEDGING", volume=0.4)
        b = self.row()["fsm_obj"]
        self.step(b.primary.entry - 1.3)
        b = self.row()["fsm_obj"]
        self.assertIsNone(b.hedge)                                                       # netting: REDUCE instead, visible reason
        ev = [e for e in self.svc.store.events(self.row()["plan_id"]) if e["kind"] == "HEDGE_DECISION"]
        self.assertTrue(ev and ev[0]["payload"]["decision"] == "REDUCE" and "NETTING" in ev[0]["payload"]["reason"])
        self.assertLess(b.primary.remaining, 0.4)


class DemoTerminal(Base):
    mode = "AUTO_DEMO"

    def test_open_partials_be_reject_and_restart(self):
        r, su = self.open(volume=0.3)
        self.assertEqual(r["status"], "OPEN", r)
        row = self.row()
        tk = row["primary_ticket"]
        tp = self.fake.positions_get(ticket=tk)[0]
        self.assertEqual((tp.magic, round(tp.tp, 2)), (41082100, round(row["fsm_obj"].legs[-1].price, 2)))   # broker TP from the fill
        e = row["fsm_obj"].entry
        self.step(e + 2.6)
        self.assertAlmostEqual(self.fake.positions_get(ticket=tk)[0].volume, 0.15)
        self.fake.fail_next_order = 10016                                               # the partial at TP2 succeeds, then BE is rejected
        row = self.step(e + 3.1)
        p = row["fsm_obj"]
        self.assertIn(p.legs[1].status, ("PENDING", "DONE"))
        if p.legs[1].status == "PENDING":                                               # partial was the rejected order: retried
            row = self.step(e + 3.1)
            p = row["fsm_obj"]
        self.assertEqual(p.legs[1].status, "DONE")
        self.assertIn(p.be_status, ("SET", "REJECTED"))
        # --- restart: a new service instance on the same database, position closed by the broker while offline
        vol = self.fake.positions_get(ticket=tk)[0].volume
        t = self.fake.symbol_info_tick("XAUUSD-")
        self.fake.order_send({"action": self.fake.TRADE_ACTION_DEAL, "symbol": "XAUUSD-", "volume": vol, "position": tk,
                              "type": self.fake.ORDER_TYPE_SELL, "price": t.bid, "magic": 41082100, "comment": "[sl]"})
        from masterquo.sh.service import SHService
        svc2 = SHService(self.cfg_store, self.bridge, self.db, None, Log(), Modes("AUTO_DEMO"), clock=lambda: self.t, terminal=self.svc._terminal)
        svc2.recover(self.ex, self.spec, self.t)
        svc2.manage(self.ex, self.spec, self.q(), self.t, self.shc)
        row = self.row()
        self.assertEqual(row["state"], "CLOSED")
        self.assertTrue(any(e["kind"] == "RECONCILED_PRIMARY" for e in svc2.store.events(row["plan_id"])))
        self.assertEqual(self.fake.positions_get(), ())

    def test_unknown_entry_adopted_and_orphan_reported(self):
        self.fake.hang_order_send = True
        r, su = self.open(volume=0.1)
        self.assertEqual(r["status"], "UNKNOWN")
        self.fake.hang_order_send = False
        row = self.row()
        self.assertEqual(row["state"], "ENTRY_UNKNOWN")
        t = self.fake.symbol_info_tick("XAUUSD-")                                       # the order did reach the terminal
        self.fake.order_send({"action": self.fake.TRADE_ACTION_DEAL, "symbol": "XAUUSD-", "volume": 0.1, "type": self.fake.ORDER_TYPE_BUY,
                              "price": t.ask, "sl": su["sl"] - 5, "tp": 0, "magic": 41082100, "comment": self.ex.comment(row["plan_id"], "P")})
        self.fake.order_send({"action": self.fake.TRADE_ACTION_DEAL, "symbol": "XAUUSD-", "volume": 0.1, "type": self.fake.ORDER_TYPE_BUY,
                              "price": t.ask, "sl": 0, "tp": 0, "magic": 41082100, "comment": "SH:unknown"})
        out = self.svc.recover(self.ex, self.spec, self.t)
        self.assertEqual(out["adopted"], [row["plan_id"]])
        self.assertEqual(len(out["orphans"]), 1)
        self.assertIn(self.row()["state"], ("OPEN", "PRIMARY_OPEN"))

    def test_hedge_rejected_stays_unhedged(self):
        r, su = self.open("HEDGING", volume=0.4)
        b = self.row()["fsm_obj"]
        self.fake.fail_next_order = 10019
        row = self.step(b.primary.entry - 1.5)
        b = row["fsm_obj"]
        self.assertEqual(b.state, "PRIMARY_OPEN")                                        # never HEDGED without a fill
        self.assertEqual(b.activations, 1)
        self.assertEqual(len(self.fake.positions_get()), 1)

    def test_management_runs_without_any_lock(self):
        """1.24: the Execution Lock is withdrawn - a reached TP1 of an open terminal plan is executed on the (simulated) terminal."""
        self.open(volume=0.3)
        row = self.row()
        e = row["fsm_obj"].entry
        row = self.step(e + 2.6)
        self.assertLess(self.fake.positions_get(ticket=row["primary_ticket"])[0].volume, 0.3)                   # TP1 part closed
        self.assertEqual(row["fsm_obj"].legs[0].status, "DONE")


if __name__ == "__main__":
    unittest.main()


class LiveBridgeSmoke(unittest.TestCase):
    """The full evaluation cycle (bars -> snapshot -> setups -> coordinator -> risk -> signals) on the real MarketBridge fed by
    the simulated terminal, in SIGNALS mode (nothing executed)."""

    def test_tick_cycle_persists_signals(self):
        td = TempData()
        try:
            from test_lab import connected
            cfg, db, bus, log, fake, worker, b, reg = connected()
            try:
                from masterquo.sh.service import SHService
                svc = SHService(cfg, b, db, bus, log, Modes("SIGNALS"))
                svc.tick()
                self.assertEqual(svc.state["status"], "RUNNING", svc.state.get("reason"))
                self.assertEqual(set(svc.last_eval), {"SCALPING", "HEDGING"})
                for strat, ev in svc.last_eval.items():
                    self.assertIn(ev["status"], ("READY", "WAIT", "NO_TRADE", "INVALIDATED"), ev)
                    self.assertIn("NIE jest prawdopodobieństwem", ev["score"]["definition"])
                rows = db.query("SELECT strategy, status FROM sh_signals")
                self.assertEqual({r["strategy"] for r in rows}, {"SCALPING", "HEDGING"})
                self.assertEqual(db.query("SELECT COUNT(*) AS n FROM sh_plans")[0]["n"], 0)       # SIGNALS: no plan, no order
                self.assertTrue(all(s["data"]["status"] in ("OK", "BLOCK") for s in [svc.snapshot]))
            finally:
                b.stop()
                worker.stop()
        finally:
            td.close()
