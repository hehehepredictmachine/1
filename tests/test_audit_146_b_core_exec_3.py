"""1.46 audit (group B_core_exec_3) - regression tests for mt5/login.py, plans/contract.py and plans/service.py.

Unit level only: isolated data dir (TempData), a simulated terminal (FakeMT5) for the login path, the SH store on a temp database for
the chart-plan views. Nothing here sends, modifies or cancels an order. risk/engine.py findings are owner DECISIONS (no code change)."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace

import _env
from _env import TempData

NOW = time.time()
SYM = "XAUUSD-"


# ================================================================================================================ mt5/login.py
class StubLogin:
    """initialize() of a terminal that is logged in itself and accepts only the password `good` for the configured login."""

    def __init__(self, good: str):
        self.good = good
        self.calls: list[dict] = []
        self.err = (1, "Success")

    def initialize(self, **kw):
        self.calls.append(dict(kw))
        ok = "login" not in kw or kw.get("password") == self.good
        self.err = (1, "Success") if ok else (-6, "Terminal: Authorization failed")
        return ok

    def last_error(self):
        return self.err


class TestCredentialsKey(unittest.TestCase):
    """chunk_24#2 - the key distinguished passwords only by their length."""

    def test_same_length_password_gives_another_key(self):
        from masterquo.mt5 import login as lg
        cfg = SimpleNamespace(login=123, server="Broker-Live")
        a, b = lg.credentials_key(cfg, "Haslo123"), lg.credentials_key(cfg, "Haslo124")
        self.assertNotEqual(a, b)                                            # was '123@Broker-Live#8' for both
        self.assertEqual(a, lg.credentials_key(cfg, "Haslo123"))             # stable within the process
        self.assertNotIn("Haslo", a)                                         # no secret in clear
        self.assertNotEqual(lg.credentials_key(cfg, None), a)
        self.assertEqual(lg.credentials_key(cfg, None), lg.credentials_key(cfg, ""))

    def test_corrected_password_of_same_length_is_tried_once(self):
        td = TempData()
        try:
            cfg, db, _bus, _log, fake, worker, bridge = _env.core()
            try:
                from masterquo.secrets_store import SecretStore
                secrets = SecretStore()
                bridge.secrets = secrets
                bridge._running_terminals = list
                cfg.update({"mt5": {"login": 5012345, "server": "Broker-Demo"}})
                secrets.set("MT5_PASSWORD", "Haslo123")                     # typo
                st = StubLogin("Haslo124")
                fake.initialize, fake.last_error = st.initialize, st.last_error
                bridge._initialize()
                self.assertTrue(bridge.login_info["credentials_rejected"])
                secrets.set("MT5_PASSWORD", "Haslo124")                     # corrected - same length
                st.calls.clear()
                bridge._initialize()
                self.assertIn({"login": 5012345, "server": "Broker-Demo", "password": "Haslo124"}, st.calls)
                self.assertEqual(bridge.login_info["mode"], "CONFIG_LOGIN")
                logs = json.dumps(db.query("SELECT message, data_json FROM app_events"), ensure_ascii=False)
                self.assertNotIn("Haslo12", logs)
            finally:
                worker.stop()
        finally:
            td.close()


class TestDiscoverTerminalsEncoding(unittest.TestCase):
    """chunk_24#20 (guard) - the audit claimed a UTF-8 origin.txt with an even byte count is decoded as UTF-16 (garbage path). Refuted:
    a text-mode 'utf-16' read without a BOM raises UnicodeDecodeError ('Stream does not start with BOM'), so the utf-8 fallback runs.
    Kept as a guard of both encodings."""

    def test_utf8_origin_with_even_byte_count(self):
        from masterquo.mt5 import login as lg
        with tempfile.TemporaryDirectory() as d:
            inst = os.path.join(d, "Broker", "MT5x")
            os.makedirs(inst)
            open(os.path.join(inst, "terminal64.exe"), "w").close()
            term = os.path.join(d, "AppData", "MetaQuotes", "Terminal", "ABC")
            os.makedirs(term)
            txt = inst + (" " if len(inst.encode()) % 2 else "")             # even number of bytes
            self.assertEqual(len(txt.encode()) % 2, 0)
            with open(os.path.join(term, "origin.txt"), "w", encoding="utf-8") as f:
                f.write(txt)
            term2 = os.path.join(d, "AppData", "MetaQuotes", "Terminal", "DEF")  # the MetaQuotes default stays readable (UTF-16 + BOM)
            os.makedirs(term2)
            inst2 = os.path.join(d, "Other")
            os.makedirs(inst2)
            open(os.path.join(inst2, "terminal64.exe"), "w").close()
            with open(os.path.join(term2, "origin.txt"), "w", encoding="utf-16") as f:
                f.write(inst2)
            found = {os.path.normcase(p) for p in lg.discover_terminals(env={"APPDATA": os.path.join(d, "AppData")}, running=[])}
        self.assertIn(os.path.normcase(os.path.join(inst, "terminal64.exe")), found)
        self.assertIn(os.path.normcase(os.path.join(inst2, "terminal64.exe")), found)


# ================================================================================================================ plans/contract.py
def su_setup(strategy="HEDGING", side="BUY", status="READY", valid=None):
    return {"strategy": strategy, "symbol": SYM, "instrument": "XAUUSD", "setup_version": "SH-1", "config_hash": "h", "status": status,
            "status_reason": "ok", "side": side, "signal_id": "SG-1", "created_at": NOW - 60,
            "valid_until": valid if valid is not None else NOW + 600, "entry_ref": 2000.0, "sl": 1996.0,
            "tps": [{"name": "TP1", "price": 2002.0, "share": 0.5}, {"name": "TP2", "price": 2004.0, "share": 0.5}]}


def su_pack(status="READY", family="HEDGING", act=1998.0):
    s = su_setup(strategy=family, status=status)
    s["tps"] = [{"name": "TP1", "price": 2002.0, "share": 0.5, "distance_pips": 20.0}, {"name": "TP2", "price": 2004.0, "share": 0.5, "distance_pips": 40.0}]
    s["strategy_id"] = "PMW_HG01" if family == "HEDGING" else "PMW_SC01"
    s["pack"] = {"family": family, "signal_tf": "M5", "analytical_state": status, "reason_code": "OK",
                 "hedge": {"policy_id": "P1", "activation_level_if_scalar": act, "status": "NOT_ACTIVE", "activations_used": 0}
                 if family == "HEDGING" else None}
    if status == "EXPIRED":
        s["status_reason"] = "TTL minął przed wykonaniem"
    return s


def basket_rep(state="HEDGED", hstatus="OPEN", activations=1, net=-3.2):
    return {"state": state, "hedge": {"side": "SELL", "volume": 0.1 if hstatus == "OPEN" else 0.0, "entry": 1998.0, "status": hstatus,
                                      "activations": activations}, "basket": {"net_after_costs": net}}


ROW = {"plan_id": "PL-2", "primary_ticket": 5, "state": "HEDGED", "exec_mode": "DEMO",
       "plan": {"profile": {"hedge": {"trigger_fraction_of_sl": 0.5}, "position_max_minutes": 240}, "risk": {"basket_loss_limit_money": 50.0}}}
POS_OPEN = {"entry": 2000.0, "sl": 1996.0, "volume": 0.2, "remaining": 0.2, "legs": [], "state": "OPEN"}
POS_CLOSED = dict(POS_OPEN, remaining=0.0, state="CLOSED")


class TestPlanContract(unittest.TestCase):
    def setUp(self):
        from masterquo.plans import contract as PC
        self.PC = PC

    def names(self, v):
        return [x["name"] for x in v["levels"]]

    def test_basket_with_open_hedge_leg_is_not_closed(self):
        """chunk_25#1 - primary closed, basket EXIT_PENDING with the hedge leg still closing -> ACTIVE (not CLOSED)."""
        row = dict(ROW, state="EXIT_PENDING")
        v = self.PC.from_setup(su_setup(), account_margin_mode="HEDGING", plan_row=row, position=POS_CLOSED,
                               basket=basket_rep(state="EXIT_PENDING", hstatus="CLOSING"))
        self.assertEqual(v["state"], "ACTIVE")
        self.assertTrue(v["readiness"]["position_open"])
        self.assertIn("HEDGE_ENTRY", self.names(v))
        p = self.PC.from_pack(su_pack(), plan_row=dict(row, state="ERROR"), position=POS_CLOSED, account_margin_mode="HEDGING",
                              basket=basket_rep(state="ERROR", hstatus="OPEN"))
        self.assertEqual(p["state"], "ACTIVE")
        self.assertIn("HEDGE_ENTRY", self.names(p))
        done = self.PC.from_setup(su_setup(), account_margin_mode="HEDGING", plan_row=dict(row, state="CLOSED"), position=POS_CLOSED,
                                  basket=basket_rep(state="CLOSED", hstatus="CLOSED"))
        self.assertEqual(done["state"], "CLOSED")
        plain = self.PC.from_setup(su_setup(strategy="SCALPING"), plan_row=dict(ROW, state="OPEN"), position=POS_CLOSED)
        self.assertEqual(plain["state"], "CLOSED")                          # a plain position still closes on its own state

    def test_entry_unknown_and_pending_entry_are_unknown(self):
        """chunk_25#3 - ENTRY_UNKNOWN / PENDING_ENTRY never claim 'no position' (INVALIDATED / EXPIRED 'bez otwarcia pozycji')."""
        for st in ("ENTRY_UNKNOWN", "PENDING_ENTRY"):
            row = {"plan_id": "PL-3", "primary_ticket": None, "state": st, "exec_mode": "DEMO", "result": {"reason": "timeout"} if st == "ENTRY_UNKNOWN" else None}
            v = self.PC.from_setup(su_setup(strategy="SCALPING", valid=NOW - 5), plan_row=row, now=NOW)
            self.assertEqual(v["state"], "UNKNOWN", st)
            self.assertNotIn("bez otwarcia", v["state_reason"])
            self.assertIn("niezweryfikowany", v["state_reason"])
            self.assertIsNone(v["readiness"]["position_open"])
        rej = self.PC.from_setup(su_setup(strategy="SCALPING"), plan_row={"plan_id": "PL-4", "state": "REJECTED", "result": {"reason": "no money"}})
        self.assertEqual(rej["state"], "INVALIDATED")
        self.assertIn("UNKNOWN", self.PC.STATES)

    def test_expired_pack_candidate_is_expired(self):
        """chunk_25#4 - a pack candidate with status EXPIRED was state WAIT."""
        v = self.PC.from_pack(su_pack(status="EXPIRED", family="SCALPING"), now=NOW)
        self.assertEqual(v["state"], "EXPIRED")
        self.assertEqual(v["analytical_state"], "EXPIRED")
        self.assertIn("TTL", v["state_reason"])

    def test_pack_hedge_keeps_account_check(self):
        """chunk_25#5 - from_pack overwrote hedge_view (NETTING) and drew the activation threshold anyway."""
        net = self.PC.from_pack(su_pack(), now=NOW, account_margin_mode="NETTING")
        self.assertIs(net["hedge"]["available"], False)
        self.assertIn("NETTING", net["hedge"]["reason"])
        self.assertNotIn("HEDGE_ACTIVATION", self.names(net))
        self.assertEqual(net["hedge"]["policy_id"], "P1")                     # pack data kept
        ok = self.PC.from_pack(su_pack(), now=NOW, account_margin_mode="HEDGING")
        self.assertIs(ok["hedge"]["available"], True)
        self.assertIn("HEDGE_ACTIVATION", self.names(ok))

    def test_unknown_margin_mode_is_not_available_true(self):
        """chunk_25#6 - margin mode None / 'None' gave available=True and a line; EXCHANGE was called '(NETTING)'."""
        for mm in (None, "None", ""):
            v = self.PC.from_setup(su_setup(), account_margin_mode=mm, plan_row=ROW, position=POS_OPEN, basket=basket_rep())
            self.assertIsNone(v["hedge"]["available"], mm)
            self.assertEqual(v["hedge"]["availability"], "NOT_VERIFIED")
            self.assertNotIn("HEDGE_ACTIVATION", self.names(v))
            self.assertIsNotNone(v["hedge"]["leg"])                            # the real leg is still reported
        ex = self.PC.from_setup(su_setup(), account_margin_mode="EXCHANGE")
        self.assertIs(ex["hedge"]["available"], False)
        self.assertIn("EXCHANGE", ex["hedge"]["reason"])
        self.assertNotIn("(NETTING)", ex["hedge"]["reason"])
        p = self.PC.from_pack(su_pack(), now=NOW, account_margin_mode=None)
        self.assertIsNone(p["hedge"]["available"])
        self.assertNotIn("HEDGE_ACTIVATION", self.names(p))
        h = self.PC.from_setup(su_setup(), account_margin_mode="HEDGING", plan_row=ROW, position=POS_OPEN, basket=basket_rep())
        self.assertIs(h["hedge"]["available"], True)
        self.assertAlmostEqual(h["hedge"]["activation_level"], 1998.0)

    def test_closed_hedge_leg_is_not_drawn_as_fill(self):
        """chunk_25#7 - a CLOSED hedge leg stayed on the chart as 'HEDGE SELL 0.0'."""
        b = basket_rep(state="PRIMARY_OPEN", hstatus="CLOSED")
        v = self.PC.from_setup(su_setup(), account_margin_mode="HEDGING", plan_row=dict(ROW, state="PRIMARY_OPEN"), position=POS_OPEN, basket=b)
        self.assertNotIn("HEDGE_ENTRY", self.names(v))
        self.assertEqual(v["hedge"]["leg"]["status"], "CLOSED")                # still in the data
        p = self.PC.from_pack(su_pack(), plan_row=dict(ROW, state="PRIMARY_OPEN"), position=POS_OPEN, basket=b, account_margin_mode="HEDGING")
        self.assertNotIn("HEDGE_ENTRY", self.names(p))
        self.assertEqual(p["hedge"]["leg"]["status"], "CLOSED")

    def test_paper_fill_label(self):
        """chunk_25#8 - 'FILL #None' for PAPER plans."""
        v = self.PC.from_setup(su_setup(strategy="SCALPING"), plan_row={"plan_id": "PL-5", "primary_ticket": None, "state": "OPEN", "exec_mode": "PAPER"},
                               position=POS_OPEN)
        lab = next(x["label"] for x in v["levels"] if x["name"] == "ENTRY_FILL")
        self.assertEqual(lab, "FILL (PAPER)")
        r = self.PC.from_setup(su_setup(strategy="SCALPING"), plan_row={"plan_id": "PL-6", "primary_ticket": 77, "state": "OPEN", "exec_mode": "DEMO"},
                               position=POS_OPEN)
        self.assertEqual(next(x["label"] for x in r["levels"] if x["name"] == "ENTRY_FILL"), "FILL #77")

    def test_dead_code_cleanup(self):
        """chunk_25#10 - unused chart_payload(primary=...) parameter removed; hedge_view reads the plan SL (no dead 'sl_plan' lookup)."""
        import inspect
        self.assertNotIn("primary", inspect.signature(self.PC.chart_payload).parameters)
        hv = self.PC.hedge_view(su_setup(), ROW, None, "HEDGING", dict(POS_OPEN, sl_plan=1990.0))
        self.assertAlmostEqual(hv["activation_level"], 1998.0)                  # from su['sl'] (1996), never from a stray key


# ================================================================================================================ plans/service.py
class FakeSH:
    def __init__(self, db, quote=None, mm="HEDGING"):
        from masterquo.sh.store import SHStore
        self.store = SHStore(db)
        self.bridge = SimpleNamespace(quote=quote, account_key="srv:1", symbol_info={"digits": 2})
        self.state = {"symbol": SYM, "account_margin_mode": mm}
        self.pack = None
        self.last_eval = {}


def mk_plan(pid, t, *, strategy="HEDGING", strategy_id="PMW_HG01", tf="M5"):
    return {"plan_id": pid, "signal_id": "SG-" + pid[3:], "strategy": strategy, "strategy_id": strategy_id, "instrument": "XAUUSD",
            "symbol": SYM, "side": "BUY", "exec_mode": "PAPER", "account_key": "srv:1", "config_hash": "h",
            "pack": {"family": strategy, "signal_tf": tf, "analytical_state": "READY",
                     "hedge": {"policy_id": "P1", "activation_level_if_scalar": None, "status": "NOT_ACTIVE", "activations_used": 0}}
            if strategy_id else None,
            "setup": {"entry_ref": 2000.0, "sl": 1996.0, "valid_until": t + 600,
                      "tps": [{"name": "TP1", "price": 2002.0, "share": 0.5, "distance_pips": 20.0},
                              {"name": "TP2", "price": 2004.0, "share": 0.5, "distance_pips": 40.0}]},
            "risk": {}, "profile": {}, "created_at": t}


def mk_basket(pid, t, *, hedge_open=True, primary_closed=False, state=None):
    from masterquo.sh.hedge_fsm import Basket, HedgeConfig, Leg2
    from masterquo.sh.lifecycle import Leg, Position
    pos = Position(pid, "BUY", 2000.0, 0.2, 1996.0, [Leg("TP1", 2002.0, 0.1), Leg("TP2", 2004.0, 0.1)])
    b = Basket(pid, pos, HedgeConfig(trigger_adverse_usd=1e12, ratio=0.5, max_activations=1), 100.0, opened_at=t)
    if hedge_open:
        b.activations = 1
        b.hedge = Leg2(side="SELL", volume=0.1, entry=1998.0, opened_at=t)
        b.state = "HEDGED"
    if primary_closed:
        pos.state, pos.remaining = "CLOSED", 0.0
        b.hedge.status = "CLOSING"
        b.state = "EXIT_PENDING"
    if state:
        b.state = state
    return b


class TestPlanService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        self.db = Database()

    def tearDown(self):
        self.db.close()
        self.td.close()

    def add(self, sh, pid, t, *, state, fsm=None, ticket=None, **kw):
        sh.store.create_plan(mk_plan(pid, t, **kw), now=t)
        sh.store.update_plan(pid, state=state, fsm=fsm, primary_ticket=ticket, now=t)

    def test_open_plan_older_than_history_is_kept(self):
        """chunk_25#0 - LIMIT history cut an ACTIVE plan out of the chart answer (collect_pack and collect)."""
        from masterquo.plans import service as PS
        from masterquo.sh.lifecycle import Leg, Position
        sh = FakeSH(self.db, quote={"bid": 2000.5, "ask": 2000.7})
        pos = Position("PL-a0", "BUY", 2000.0, 0.2, 1996.0, [Leg("TP1", 2002.0, 0.1), Leg("TP2", 2004.0, 0.1)])
        self.add(sh, "PL-a0", NOW - 3600, state="OPEN", fsm=pos, ticket=None, strategy="SCALPING", strategy_id="PMW_SC01")
        for i in range(1, 4):                                                   # three newer, already closed plans
            self.add(sh, f"PL-a{i}", NOW - 3600 + i * 60, state="CLOSED", strategy="SCALPING", strategy_id="PMW_SC01")
        out = PS.collect_pack(sh, history=2, now=NOW)
        ids = [p["plan_id"] for p in out["plans"]]
        self.assertIn("PL-a0", ids)
        self.assertEqual(next(p for p in out["plans"] if p["plan_id"] == "PL-a0")["state"], "ACTIVE")
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 3)                                           # 2 newest + the open one
        self.assertEqual(out["primary"], next(p["plan_key"] for p in out["plans"] if p["plan_id"] == "PL-a0"))
        legacy_pos = Position("PL-b0", "BUY", 2000.0, 0.2, 1996.0, [Leg("TP1", 2002.0, 0.1)])
        self.add(sh, "PL-b0", NOW - 3600, state="OPEN", fsm=legacy_pos, strategy="SCALPING", strategy_id=None)
        for i in range(1, 4):
            self.add(sh, f"PL-b{i}", NOW - 3600 + i * 60, state="CLOSED", strategy="SCALPING", strategy_id=None)
        leg = PS.collect(sh, "SCALPING", history=1, now=NOW)
        self.assertIn("PL-b0", [p["plan_id"] for p in leg["plans"]])

    def test_basket_without_quote_reports_the_hedge_leg(self):
        """chunk_25#2 - without a quote the open hedge read NOT_ACTIVE / 0 activations / no leg; P&L must be null, not 0."""
        from masterquo.plans import service as PS
        sh = FakeSH(self.db, quote=None)
        self.add(sh, "PL-c0", NOW - 600, state="HEDGED", fsm=mk_basket("PL-c0", NOW - 600), ticket=11)
        out = PS.collect_pack(sh, history=5, now=NOW)
        h = out["plans"][0]["hedge"]
        self.assertEqual(h["status"], "ACTIVE")
        self.assertEqual(h["activations_used"], 1)
        self.assertEqual(h["leg"]["entry"], 1998.0)
        self.assertIsNone(h["basket_net"])                                       # needs a quote -> null
        self.assertIn("HEDGE_ENTRY", [x["name"] for x in out["plans"][0]["levels"]])
        b = out["plans"][0]["basket"]
        self.assertIsNone(b["unrealized"])
        legacy = PS.collect(sh, "HEDGING", history=5, now=NOW)                    # PMW-PLAN-1 view: no variant rows -> empty, no crash
        self.assertEqual(legacy["plans"], [])
        q = FakeSH(self.db, quote={"bid": 1999.0, "ask": 1999.2})                 # with a quote the P&L is a number
        hq = PS.collect_pack(q, history=5, now=NOW)["plans"][0]["hedge"]
        self.assertIsInstance(hq["basket_net"], float)

    def test_basket_primary_closed_hedge_closing_is_active_in_service(self):
        """chunk_25#1 through the service: basket EXIT_PENDING with a closing hedge -> ACTIVE, with or without a quote."""
        from masterquo.plans import service as PS
        for quote in (None, {"bid": 1999.0, "ask": 1999.2}):
            db_sh = FakeSH(self.db, quote=quote)
            pid = "PL-d0" if quote is None else "PL-d1"
            self.add(db_sh, pid, NOW - 600, state="EXIT_PENDING", fsm=mk_basket(pid, NOW - 600, primary_closed=True), ticket=12)
            p = next(x for x in PS.collect_pack(db_sh, plan_id=pid, now=NOW)["plans"] if x["plan_id"] == pid)
            self.assertEqual(p["state"], "ACTIVE", quote)

    def test_legacy_strategy_id_returns_legacy_plans(self):
        """chunk_25#9 - strategy_id LEGACY_* always gave an empty list."""
        from masterquo.plans import service as PS
        from masterquo.sh.lifecycle import Leg, Position
        sh = FakeSH(self.db, quote={"bid": 2000.5, "ask": 2000.7})
        pos = Position("PL-e0", "BUY", 2000.0, 0.2, 1996.0, [Leg("TP1", 2002.0, 0.1)])
        self.add(sh, "PL-e0", NOW - 60, state="OPEN", fsm=pos, ticket=13, strategy="SCALPING", strategy_id=None)
        self.add(sh, "PL-e1", NOW - 30, state="CLOSED", strategy="SCALPING", strategy_id="PMW_SC01")
        out = PS.collect_pack(sh, strategy_id="LEGACY_SCALPING", now=NOW)
        self.assertEqual([p["plan_id"] for p in out["plans"]], ["PL-e0"])
        self.assertNotIn("None pips", json.dumps(out["plans"][0]["levels"]))
        self.assertEqual(PS.collect_pack(sh, strategy_id="LEGACY_HEDGING", now=NOW)["plans"], [])
        self.assertEqual([p["plan_id"] for p in PS.collect_pack(sh, strategy_id="PMW_SC01", now=NOW)["plans"]], ["PL-e1"])


if __name__ == "__main__":
    unittest.main()
