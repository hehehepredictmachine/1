"""1.8: scenario list + "Szczegóły setupu" on the real engine with the synthetic terminal (FakeMT5); setup view modes;
leverage limit effect on the scenario sizing; MT5 loss. No real orders - mode SIGNALS, order_attempts must stay empty."""
from __future__ import annotations

import unittest

import _env  # noqa: F401
from _env import wait_for
import test_active_pipeline

STATUSES = {"SPEŁNIONY", "NIESPEŁNIONY", "BRAK DANYCH", "ODCZYT", "—"}


class TestSetupDetails(unittest.TestCase):
    setUp = test_active_pipeline.TestActivePipeline.setUp
    tearDown = test_active_pipeline.TestActivePipeline.tearDown

    def attach_prefs(self):
        from masterquo.prefs import AccountPrefs
        self.prefs = AccountPrefs(self.db, self.b, self.cfg)
        self.engine.prefs = self.prefs
        self.engine.active.prefs = self.prefs

    def scenarios(self, n=6):
        from masterquo.engine import setup_details
        for _ in range(n):
            self.engine.full_cycle()
            items = setup_details.scenarios(self.engine)["items"]
            if items:
                return items
        return []

    def test_scenarios_and_full_details_buy_sell(self):
        from masterquo.engine import setup_details
        self.attach_prefs()
        items = self.scenarios()
        self.assertTrue(items, "the synthetic terminal produced no scenario")
        for it in items:
            for k in ("setup_id", "strategy_id", "symbol", "direction", "timeframe", "created_at", "scenario_status"):
                self.assertIsNotNone(it[k], k)
            self.assertEqual(it["symbol"], "XAUUSD-")                     # exact broker name with suffix
            self.assertIn(it["direction"], ("BUY", "SELL"))
        sides = set()
        for it in items[:8]:
            d = setup_details.details(self.engine, it["setup_id"])
            sides.add(d["direction"])
            self.assertIn(d["scenario_status"], ("OCZEKIWANIE", "WARUNKI_SPELNIONE", "UNIEWAZNIONY", "BRAK_DANYCH"))
            self.assertIn(d["entry"]["status"], ("DOSTĘPNE", "ZABLOKOWANE"))
            if d["entry"]["status"] == "ZABLOKOWANE":
                self.assertTrue(d["entry"]["reasons"])                       # always with a reason
            self.assertIn("nie jest zgodą", d["direction_note"])
            self.assertTrue(all(r["status"] in STATUSES and r["name"] for r in d["checklist"]))
            closed = next(r for r in d["checklist"] if r["name"].startswith("Wyzwalacz na ZAMKNIĘTEJ"))
            if d["stage"] != "CONFIRMED":
                self.assertNotEqual(closed["status"], "SPEŁNIONY")             # candle conditions only after the close
            self.assertIn("NIE jest prawdopodobieństwem", d["score"]["meaning"])
            self.assertEqual(d["history"]["trades"], 0)                       # no fictitious statistics
            self.assertIsNone(d["history"]["stats"])
            self.assertTrue(d["timeframes"])
            self.assertIn(d["times"]["data_source"], ("SYNTHETIC",) + tuple(f"MT5:{x}" for x in ("Synthetic",)))
            if d["scenario_status"] != "UNIEWAZNIONY":
                lv = d["leverage"]
                for k in ("account_leverage", "user_limit", "effective_exposure_position"):
                    self.assertIn(k, lv)
                self.assertEqual(lv["account_leverage"], 100)
        self.assertTrue(sides <= {"BUY", "SELL"})
        self.assertEqual(self.db.query("SELECT * FROM order_attempts"), [])

    def test_lower_leverage_limit_reduces_scenario_volume(self):
        from masterquo.engine import setup_details
        self.attach_prefs()
        items = [i for i in self.scenarios() if i["status"] == "ACTIVE"]
        self.assertTrue(items)
        sid = items[0]["setup_id"]
        a = setup_details.details(self.engine, sid)["sizing"]
        self.prefs.set("leverage", {"mode": "MANUAL", "limit": 1})
        d = setup_details.details(self.engine, sid)
        b = d["sizing"]
        if a["lots"]:
            self.assertLessEqual(b["lots"] or 0, a["lots"])
        self.assertEqual(d["leverage"]["user_limit"], 1)
        self.assertEqual(a["budget"], b["budget"])                             # the risk budget does not depend on leverage
        self.assertNotEqual(a["settings_version"], b["settings_version"])
        if b["lots"]:
            self.assertLessEqual(d["leverage"]["effective_exposure_position"], 1.0 + 1e-9)

    def test_selected_strategy_never_forces_a_signal_and_survives_restart(self):
        from masterquo.prefs import AccountPrefs
        self.attach_prefs()
        self.prefs.set("setup_view", {"mode": "SELECTED", "strategy_id": "S03"})
        for _ in range(3):
            self.engine.full_cycle()
        st = self.engine.active.status()
        self.assertIn(st["selected_strategy_id"], (None, "S03"))
        self.assertEqual(st["strategy_mode"], "MANUAL")
        d = self.engine.current_decision()
        if st["selected_strategy_id"] is None:
            self.assertIsNone(d.get("setup"))                                  # nothing invented for the chosen strategy
        self.assertEqual(self.modes.status()["mode"], "SIGNALS")
        self.assertEqual(self.db.query("SELECT * FROM order_attempts"), [])
        again = AccountPrefs(self.db, self.b, self.cfg).get("setup_view")      # = restart of the program
        self.assertEqual((again["mode"], again["strategy_id"]), ("SELECTED", "S03"))
        self.prefs.set("setup_view", {"mode": "ALL"})
        self.engine.full_cycle()
        self.assertEqual(self.engine.active.status()["strategy_mode"], "AUTO")

    def test_mt5_loss_marks_no_data_and_blocks_entry(self):
        from masterquo.engine import setup_details
        self.attach_prefs()
        items = [i for i in self.scenarios() if i["status"] == "ACTIVE"]
        self.assertTrue(items)
        self.fake.terminal_connected = False
        self.assertTrue(wait_for(lambda: self.b.state != "CONNECTED", 30))
        self.engine.full_cycle()
        d = setup_details.details(self.engine, items[0]["setup_id"])
        self.assertIn(d["scenario_status"], ("BRAK_DANYCH", "UNIEWAZNIONY"))
        self.assertEqual(d["entry"]["status"], "ZABLOKOWANE")
        self.fake.terminal_connected = True


if __name__ == "__main__":
    unittest.main()
