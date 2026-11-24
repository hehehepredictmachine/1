"""Fala 2 / grupa zones_misc (Apollo23 1.46): I0758 (Double Bottom: podcięcie między dołkami), I0759 (RiskLoot domyślnie OFF),
I0837-I0843 + I0865 (strefy: semantyka PMW-ZONES-SEM-2 bez podglądu przyszłości, nieznane = NaN, świeżość per TF) oraz wersjonowanie
semantyki wejść legacy ML (MQ-FEAT-1.3.0; modele <= 1.2.0 dostają dokładnie dotychczasowy blok stref SEM-1).
Każdy test nie przechodzi na kodzie sprzed poprawki. Dane SYNTETYCZNE - sprawdzają reguły, nie wartość predykcyjną."""
from __future__ import annotations

import math
import unittest
from datetime import UTC, datetime
from typing import ClassVar

import _env  # noqa: F401
from _env import TempData
from masterquo.config import ZonesConfig
from masterquo.zones import dsvie as DV
from masterquo.zones import engine as ZE
from masterquo.zones import features as ZF
from masterquo.zones import hlze as HZ
from masterquo.zones import uzice as UZ
from masterquo.zones.series import Series, iso

T0 = datetime(2026, 10, 19, tzinfo=UTC).timestamp()            # Monday 00:00 UTC = start of the ASIA window (09:00 Asia/Tokyo)
BASE = (100.0, 100.5, 99.5, 100.0)
CFG = ZonesConfig()
NAN = float("nan")


def bar(t, o, h, l, c, tv=100.0, rv=0.0):
    return {"open_utc": iso(t), "o": o, "h": h, "l": l, "c": c, "tv": tv, "rv": rv, "closed": True}


def series(rows, tf="M5", t0=T0 - 86400, tf_s=300, tv=None):
    tv = tv or {}
    return Series.from_bars([bar(t0 + i * tf_s, *r, tv=tv.get(i, 100.0)) for i, r in enumerate(rows)], tf)


def isnan(x) -> bool:
    return isinstance(x, float) and math.isnan(x)


# ============================================================================================ I0758 Double Bottom
class TestDoubleBottomUndercut(unittest.TestCase):
    """I0758: 'drugi dołek nie może być podcięty między dołkami' była tylko komentarzem - para z niższym dołkiem POMIĘDZY była formacją."""

    @staticmethod
    def bars():
        from analytics import fixtures as F
        # decline -> b1 1990 -> neck 2000 -> UNDERCUT 1985 -> 1999 -> b2 1990.2 -> 1997 (no decisive close)
        path = [2010.0] + F.lin(2010, 1990, 12) + F.lin(1990, 2000, 6) + F.lin(2000, 1985, 4) + F.lin(1985, 1999, 4) + \
            F.lin(1999, 1990.2, 5) + F.lin(1990.2, 1997, 5)
        return F.from_path(path)

    def test_lower_low_between_bottoms_is_not_a_double_bottom(self):
        from masterquo.analytics import double_bottom as DB
        for mode in ("SOURCE_COMPAT", "EXTENDED", "BUFFERED"):
            v = DB.validate(self.bars(), {"mode": mode, "min_depth_atr": 0.1}, tf="M5")["values"]
            self.assertEqual(v["status"], "INVALID", (mode, v.get("status"), v.get("coordinates")))       # was CANDIDATE
            self.assertIn("UNDERCUT_BETWEEN_BOTTOMS", v["rejections"], mode)

    def test_clean_double_bottom_unchanged_and_rules_version_bumped(self):
        from analytics import fixtures as F
        from masterquo.analytics import double_bottom as DB
        self.assertEqual(DB.validate(F.double_bottom("up"), tf="M5")["values"]["status"], "CONFIRMED")
        self.assertEqual((DB.VERSION, DB.VERSION_EXT, DB.VERSION_BUF), ("DB-1.0.1", "DB-1.1.1-EXT", "DB-1.2.1-BUF"))

    def test_job_of_an_older_rules_version_is_not_resumed_with_new_rules(self):
        import json
        import time

        from analytics import fixtures as F
        from masterquo.analytics import double_bottom as DB
        from masterquo.analytics.library import PatternLibrary
        from masterquo.db.database import Database
        td = TempData()
        try:
            lib = PatternLibrary(Database(), lambda: dict(DB.DEFAULT))
            a = lib.add_sample("XAUUSD-", "M5", F.double_bottom("up"), "TEST")
            jid = lib.start_job([a["id"]])["job_id"]
            for _ in range(200):
                if lib.job(jid)["status"] != "RUNNING":
                    break
                time.sleep(0.05)
            row = lib.db.one("SELECT manifest FROM pattern_jobs WHERE job_id=?", (jid,))
            man = dict(json.loads(row["manifest"]), rules_version="DB-1.0.0")
            lib.db.execute("UPDATE pattern_jobs SET status='INTERRUPTED', manifest=? WHERE job_id=?", (json.dumps(man), jid))
            r = lib.resume(jid)
            self.assertFalse(r["ok"])
            self.assertTrue(r["error"].startswith("RULES_VERSION_CHANGED"), r)
        finally:
            td.close()


# ============================================================================================ I0759 RiskLoot Default OFF
class TestRiskLootDefaultOff(unittest.TestCase):
    EV: ClassVar[dict] = {"event_id": "e1", "position_id": "p1", "source_mode": "SIMULATOR", "setup_family": "EMA_SMMA_PULLBACK", "strategy_status": "VALIDATED",
          "sfb_status": "ELIGIBLE", "trap_no_trade": False, "risk_breach": False, "attribution": "SIM:1",
          "scores": {"setup_quality": 90, "risk_discipline": 95, "execution_adherence": 85, "journal_learning": 80, "evidence_quality": 85}}

    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_grant_writes_nothing_until_the_player_turns_it_on(self):
        from pathlib import Path

        from masterquo.apollo import risk_loot as R
        from masterquo.trader_life_game import GameService
        g = GameService(Path(self.td.dir) / "tlg")
        try:
            self.assertFalse(R.grant_enabled(g))                           # catalogue: enabled_by_default = NO
            self.assertTrue(R.evaluate(self.EV)["eligible"])                # assessment keeps working
            r = R.grant(g, self.EV)
            self.assertFalse(r["granted"])                                  # was granted=True with the switch absent
            self.assertEqual(r["reason"], "GRANT_DISABLED")
            self.assertIsNone(g._one("SELECT 1 AS x FROM inventory"))
            self.assertIsNone(g._one("SELECT 1 AS x FROM gold_ledger WHERE reason='LOOT_GRANT'"))
            self.assertTrue(R.set_grant_enabled(g, True)["grant_enabled"])
            self.assertTrue(R.grant(g, self.EV)["granted"])
            with self.assertRaises(TypeError):
                R.set_grant_enabled(g, "yes")
        finally:
            g.close()

    def test_api_grant_is_409_by_default_and_settings_route(self):
        import types

        from fastapi import FastAPI, HTTPException
        from masterquo.api import wf32_routes
        app = FastAPI()
        wf32_routes.register(app, types.SimpleNamespace())
        ep = {(r.path, m): r.endpoint for r in app.routes if hasattr(r, "methods") for m in r.methods}
        self.assertFalse(ep[("/api/v1/tlg/loot/settings", "GET")]()["grant_enabled"])
        with self.assertRaises(HTTPException) as cm:
            ep[("/api/v1/tlg/loot/grant", "POST")](body=dict(self.EV))
        self.assertEqual(cm.exception.status_code, 409)
        self.assertTrue(str(cm.exception.detail).startswith("GRANT_DISABLED"))
        with self.assertRaises(HTTPException) as cm:
            ep[("/api/v1/tlg/loot/settings", "PUT")](body={"grant_enabled": "1"})
        self.assertEqual(cm.exception.status_code, 400)
        self.assertTrue(ep[("/api/v1/tlg/loot/settings", "PUT")](body={"grant_enabled": True})["grant_enabled"])
        self.assertTrue(ep[("/api/v1/tlg/loot/grant", "POST")](body=dict(self.EV))["granted"])


if __name__ == "__main__":
    unittest.main()
