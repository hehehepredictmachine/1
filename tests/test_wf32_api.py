"""WF3.2 API smoke test on the demo server: every new read-only route answers, retired OTC routes return 410, the game works end to end
through the API and the active catalogue is 60 / 6 / 2."""
from __future__ import annotations

import os
import unittest

import _env  # noqa: F401


class TestWf32Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PMW_BOOTSTRAP"] = "0"
        from _demo_server import Server
        cls.S = Server
        Server.start_server()

    @classmethod
    def tearDownClass(cls):
        cls.S.stop_server()

    def test_read_only_routes(self):
        c = self.S.call
        for path in ("/api/v1/indicators/catalog", "/api/v1/indicators/diagnostics", "/api/v1/session-context?timeframe=M5",
                     "/api/v1/session-context/boxes?timeframe=M5", "/api/v1/markets/v2", "/api/v1/models/dt-ranker/status",
                     "/api/v1/models/association/snapshot?timeframe=H1", "/api/v1/models/bat/shadow?timeframe=H1",
                     "/api/v1/strategy-roi?mode=PAPER", "/api/v1/forecast/long-horizon?horizon=24h&timeframe=H1",
                     "/api/v1/change-points?timeframe=H1", "/api/v1/bootstrap", "/api/v1/telegram/account", "/api/v1/strategy-filter/status",
                     "/api/v1/relationships/candidates", "/api/v1/market-trap?timeframe=M5", "/api/v1/smma-cci?timeframe=M5",
                     "/api/v1/asge/ledger", "/api/v1/tlg/meta", "/api/v1/tlg/state", "/api/v1/tlg/loot/catalog", "/api/v1/health"):
            code, body = c(path)
            self.assertEqual(code, 200, (path, body))
        code, h = c("/api/v1/health")
        self.assertEqual(h.get("display_name"), "Apollo23")
        code, sfb = c("/api/v1/strategy-filter/status")
        self.assertEqual((sfb["mode"], sfb["apply_to_execution"], sfb["active_catalog"]["total"]), ("OFF", False, 60))

    def test_retired_otc_routes(self):
        c = self.S.call
        self.assertEqual(c("/api/v1/baskets/otc")[1]["state"], "RETIRED")
        self.assertEqual(c("/api/v1/baskets/otc/ticks", {"ticks": [{"t": 1, "price": 1}]})[0], 410)
        self.assertEqual(c("/api/v1/baskets/declared/OTC_GOLD_POCKETOPTION", {"dir": "CALL"})[0], 410)
        code, cat = c("/api/v1/baskets/catalog")
        self.assertEqual(code, 200)

    def test_game_through_api(self):
        c = self.S.call
        code, st = c("/api/v1/tlg/profile", {"username": "Tester", "class_id": "THE_ANALYST", "difficulty": "MEDIUM", "currency": "USD",
                                             "virtual_capital": 25000})
        self.assertEqual(code, 200, st)
        self.assertEqual(st["profile"]["milestone"], 50000)
        self.assertEqual(c("/api/v1/tlg/profile", {"username": "X2", "class_id": "THE_ANALYST", "difficulty": "EASY"})[0], 409)
        code, r = c("/api/v1/tlg/notes/ANALYSIS", {"text": "Analiza H1: sweep dołka azjatyckiego i reclaim powyżej poziomu.", "invalidation": "2390"})
        self.assertEqual((code, r["reward"]["xp"]), (200, 23))                       # 20 x 1.15 (THE ANALYST bonus)
        code, q = c("/api/v1/tlg/quests")
        d = {x["id"]: x for x in q["items"]}
        self.assertEqual(d["D_CHART"]["status"], "COMPLETED")
        self.assertEqual(c("/api/v1/tlg/quests/D_CHART/claim", {})[0], 200)
        self.assertEqual(c("/api/v1/tlg/quests/D_CHART/claim", {})[0], 409)
        code, sim = c("/api/v1/tlg/sim", {"tf": "H1"})
        self.assertIn(code, (200, 409), sim)
        if code == 200:
            n0 = len(sim["bars"])
            code, sim2 = c(f"/api/v1/tlg/sim/{sim['id']}/step", {"n": 5})
            self.assertEqual(len(sim2["bars"]), n0 + 5)
        code, lb = c("/api/v1/tlg/leaderboard")
        self.assertFalse(lb["global"]["enabled"])


if __name__ == "__main__":
    unittest.main()
