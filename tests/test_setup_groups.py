"""1.10 "Warunki setupu": presentation grouping of the engine's checklist (engine/setup_details.annotate). The counter
"X z Y wymaganych" counts only requirements; informational readings and not-applicable rows never enter the denominator."""
from __future__ import annotations

import unittest

import _env  # noqa: F401
from masterquo.engine import setup_details as sd


class TestChecklistGroups(unittest.TestCase):
    def rows(self):
        return [
            {"name": "Dane MT5 (jakość)", "status": "SPEŁNIONY"},
            {"name": "Reżim rynku", "status": "ODCZYT"},
            {"name": "Wall", "status": "NIE DOTYCZY", "tf": "—"},
            {"name": "Zakres M5 (konsolidacja)", "status": "SPEŁNIONY", "tf": "M5"},
            {"name": "Wyzwalacz na ZAMKNIĘTEJ świecy M5", "status": "OCZEKIWANIE", "group": 4, "threshold": "zamknięcie powyżej"},
            {"name": "RR po kosztach", "status": "NIESPEŁNIONY", "reason": "RR poniżej progu"},
            {"name": "Spread", "status": "BRAK DANYCH"},
            {"name": "Wolumen (wszystkie limity)", "status": "SPEŁNIONY"},
            {"name": "Zezwolenie na wejście (silnik, tryb, TTL)", "status": "NIESPEŁNIONY", "group": 9},
            {"name": "Unieważnienie scenariusza", "status": "SPEŁNIONY", "group": 10},
        ]

    def test_counter_excludes_na_and_readings(self):
        rows = self.rows()
        sm = sd.annotate(rows, entry_tf="M5", checked_at="2026-10-13T10:00:00Z")
        self.assertEqual(sm["required_total"], 8)                 # 10 rows - reading - not applicable
        self.assertEqual(sm["required_met"], 4)
        self.assertEqual((sm["missing"], sm["pending"], sm["no_data"]), (2, 1, 1))
        self.assertFalse(next(r for r in rows if r["name"] == "Wall")["required"])
        self.assertFalse(next(r for r in rows if r["name"] == "Reżim rynku")["required"])
        self.assertIn("NIE prawdopodobieństwo", sm["meaning"])

    def test_groups_states_tf_and_time(self):
        rows = self.rows()
        sm = sd.annotate(rows, entry_tf="M5", checked_at="2026-10-13T10:00:00Z")
        g = {r["name"]: r["group"] for r in rows}
        self.assertEqual(g["Dane MT5 (jakość)"], 1)
        self.assertEqual(g["Reżim rynku"], 2)
        self.assertEqual(g["Zakres M5 (konsolidacja)"], 3)
        self.assertEqual(g["Wyzwalacz na ZAMKNIĘTEJ świecy M5"], 4)
        self.assertEqual(g["RR po kosztach"], 6)
        self.assertEqual(g["Spread"], 6)
        self.assertEqual(g["Wolumen (wszystkie limity)"], 7)
        self.assertEqual(g["Zezwolenie na wejście (silnik, tryb, TTL)"], 9)
        self.assertEqual(g["Unieważnienie scenariusza"], 10)
        st = {r["name"]: r["state"] for r in rows}
        self.assertEqual((st["Wyzwalacz na ZAMKNIĘTEJ świecy M5"], st["Spread"], st["Wall"]), ("PENDING", "NO_DATA", "NA"))
        self.assertTrue(all(r["at"] == "2026-10-13T10:00:00Z" and r["tf"] for r in rows))
        self.assertEqual(next(r for r in rows if r["name"] == "Zakres M5 (konsolidacja)")["tf"], "M5")
        self.assertEqual(sm["first_blocker"]["name"], "RR po kosztach")                       # first unmet requirement
        self.assertEqual(sm["next_confirmation"]["name"], "Wyzwalacz na ZAMKNIĘTEJ świecy M5")
        self.assertEqual(set(sm["groups"]), set(range(1, 11)))


if __name__ == "__main__":
    unittest.main()
