"""1.46 arch, fala 2 – scalenie grup execution_mt5_risk (ponowienie NOT_SENT, I0739) i sh_exec (ponawiane zamknięcia hedge, I0740/I0742).

Obie grupy były poprawne osobno, ale razem dawały dwie nowe ścieżki:
1. NOT_SENT_TTL dla CLOSE_HEDGE w UNWINDING cofa koszyk do HEDGED z otwartą nogą hedge. Udane późniejsze odwrócenie prowadzi do PRIMARY_OPEN, a
   przy max_activations >= 2 hedge_step mógłby otworzyć drugą nogę hedge, której kod sprzed fali nie otwierał (S0 b – ta sama ścieżka, którą
   druga recenzja sh_exec zablokowała dla odrzuconego zamknięcia). Po scaleniu: zużycie pozostałych aktywacji (Basket._no_new_hedge).
2. Zamknięcie bazy NOT_SENT (czeka na ponowienie z tym samym id) nie było liczone jako zamknięcie w toku, więc ponawianie wyjścia z sh_exec
   (_primary_close_free) mogło w tym czasie wysłać drugie zamknięcie. Po scaleniu NOT_SENT jest „w toku” do wygaśnięcia TTL.
"""
from __future__ import annotations

import unittest

from _env import TempData


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.sh.lifecycle import Leg, Position
        from masterquo.sh.service import SHService
        from masterquo.sh.store import SHStore
        self.svc = SHService.__new__(SHService)
        self.svc.store = SHStore(Database())
        self.svc.finish = lambda *a, **k: None
        self.pos = Position(plan_id="PLAN-1", side="BUY", entry=2000.0, volume=0.1, sl=1990.0,
                            legs=[Leg("TP1", 2002.0, 0.05), Leg("TP2", 2004.0, 0.03), Leg("TP3", 2006.0, 0.02)])
        self.row = {"plan_id": "PLAN-1", "exec_mode": "AUTO_DEMO", "primary_ticket": 77, "plan": {"instrument_profile": {}}}

    def tearDown(self):
        self.td.close()

    def basket(self, state, hedge_status, max_activations):
        from masterquo.sh.hedge_fsm import Basket, HedgeConfig, Leg2
        return Basket("PLAN-1", self.pos, HedgeConfig(trigger_adverse_usd=1.0, max_activations=max_activations), 100.0, 0.0, state=state,
                      hedge=Leg2(side="SELL", volume=0.05, entry=2000.0, opened_at=0.0, status=hedge_status), activations=1)


class TestNotSentUnwindUsesUpActivations(_Base):
    def test_not_sent_ttl_unwind_back_to_hedged_allows_no_second_leg(self):
        b = self.basket("UNWINDING", "CLOSING", max_activations=2)
        aid = "PLAN-1:CLOSE_HEDGE:1"
        b.issued.add(aid)
        b._sh_retry = [{"action": {"action_id": aid, "basket_id": "PLAN-1", "kind": "CLOSE_HEDGE", "volume": 0.05}, "first_at": 0.0}]
        self.assertEqual(self.svc._retry_acts(self.row, b, 100.0), [])
        self.assertEqual((b.state, b.hedge.status), ("HEDGED", "OPEN"))
        self.assertEqual(b.activations, 2)                    # przed scaleniem: 1 < 2 -> hedge_step mógł otworzyć drugą nogę
        # pełne odwrócenie później -> PRIMARY_OPEN, ale bez budżetu na nową nogę
        b.hedge.status = "CLOSING"
        b.on_hedge_closed("PLAN-1:CLOSE_HEDGE:2:r", 120.0, 0.05, 2001.0, action_id="PLAN-1:CLOSE_HEDGE:2")
        self.assertEqual(b.state, "PRIMARY_OPEN")
        self.assertGreaterEqual(b.activations, b.cfg.max_activations)

    def test_default_single_activation_unchanged(self):
        b = self.basket("UNWINDING", "CLOSING", max_activations=1)
        aid = "PLAN-1:CLOSE_HEDGE:1"
        b.issued.add(aid)
        b._sh_retry = [{"action": {"action_id": aid, "basket_id": "PLAN-1", "kind": "CLOSE_HEDGE", "volume": 0.05}, "first_at": 0.0}]
        self.svc._retry_acts(self.row, b, 100.0)
        self.assertEqual(b.activations, 1)                    # domyślna konfiguracja: bez zmiany licznika


class TestNotSentCloseIsInFlight(_Base):
    def test_not_sent_primary_close_blocks_exit_retry(self):
        b = self.basket("EXIT_PENDING", "CLOSED", max_activations=1)
        a = {"action_id": "PLAN-1:CLOSE_PRIMARY:EXIT", "plan_id": "PLAN-1", "kind": "CLOSE_PRIMARY", "volume": 0.1}
        self.svc.store.claim_action(a, 0.0)
        self.svc.store.finish_action(a["action_id"], "NOT_SENT", {"status": "NOT_SENT"}, 0.0)
        inflight = self.svc._closes_in_flight(self.row)
        self.assertEqual([x["action_id"] for x in inflight], ["PLAN-1:CLOSE_PRIMARY:EXIT"])   # przed scaleniem: []
        self.assertFalse(self.svc._primary_close_free(self.row, b))                            # przed scaleniem: True (drugie zamknięcie)


if __name__ == "__main__":
    unittest.main()
