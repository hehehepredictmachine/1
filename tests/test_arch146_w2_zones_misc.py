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


# ============================================================================================ I0837 POC migration unknown
class TestPocMigrationUnknown(unittest.TestCase):
    def profiles(self, n_in_window, legacy):
        rows = [BASE] * 24 + [(100.0, 100.5 + 0.1 * k, 99.5, 100.2) for k in range(n_in_window)]
        s = series(rows, t0=T0 - 24 * 300)                              # 2 h before the ASIA window + n bars inside it
        as_of = T0 + n_in_window * 300
        return DV.session_profiles(s, "LAB_XAU_REFERENCE_V1", "XAUUSD", CFG, as_of, "TICK_VOLUME", legacy=legacy), s

    def test_short_developing_path_is_unknown_not_zero(self):
        pr, s = self.profiles(3, legacy=False)
        dev = next(p for p in pr if p["state"] == "DEVELOPING")
        self.assertIsNone(dev["poc_migration_bins"])                    # was 0 ("no migration")
        ctx = DV.context(pr, s.c[-1], s)
        zm = {"zones": [], "m5": [{"zone_type": "SWING_HIGH", "status": "ACTIVE", "lower": 200.0, "upper": 201.0}], "context": ctx,
              "atr_m5": 1.0, "data": {"state": "OK"}}
        self.assertTrue(isnan(ZF.compute(zm, direction="LONG", entry=100.0, stop=99.0)["zone_poc_migration"]))
        old, _ = self.profiles(3, legacy=True)
        self.assertEqual(next(p for p in old if p["state"] == "DEVELOPING")["poc_migration_bins"], 0)     # SEM-1 unchanged
        pr4, _ = self.profiles(5, legacy=False)
        self.assertIsInstance(next(p for p in pr4 if p["state"] == "DEVELOPING")["poc_migration_bins"], int)


# ============================================================================================ I0838 / I0839 DSVIE demand / supply
def _demand_series(touch_before_confirm: bool, spike: bool):
    rows = [BASE] * 30 + [(100.0, 100.3, 98.0, 100.1)]                 # pivot low with a long lower wick (rejection), index 30
    rows += [BASE]                                                      # 31: displacement h - pivot low >= 1 ATR
    rows += [(99.0, 99.4, 98.2, 99.0) if touch_before_confirm else BASE]   # 32: touch of the zone BEFORE the pivot is confirmed (33)
    rows += [BASE] * 12
    return series(rows, tv={30: 200.0} if spike else {})


class TestDsvieDemandSupplyNoLookAhead(unittest.TestCase):
    def pivots(self, s):
        piv = [p for p in HZ.swings(s, CFG, 0.01) if p["kind"] == "L" and not p["provisional"]]
        self.assertEqual([p["index"] for p in piv], [30])
        self.assertEqual(piv[0]["confirm_index"], 33)
        return piv

    def test_I0838_day_level_known_only_after_the_pivot_is_not_context(self):
        s = _demand_series(False, spike=False)
        piv = self.pivots(s)
        ref = {"zone_type": "PREVIOUS_DAY_LOW", "zone_id": "HZ-ref", "lower": 98.0, "upper": 98.05, "evidence": [{"root": "D1:x:LOW"}],
               "confirmed_at": iso(piv[0]["confirmed_at"] + 3600)}         # the day closed 1 h AFTER the pivot was confirmed
        self.assertEqual(len(DV.demand_supply(s, piv, [], [ref], CFG, 0.01, "NONE", legacy=True)), 1)     # SEM-1: look-ahead context
        self.assertEqual(DV.demand_supply(s, piv, [], [ref], CFG, 0.01, "NONE"), [])                     # was a DEMAND zone
        known = dict(ref, confirmed_at=iso(piv[0]["confirmed_at"] - 3600))
        z = DV.demand_supply(s, piv, [], [known], CFG, 0.01, "NONE")
        self.assertEqual([x["zone_type"] for x in z], ["DEMAND"])
        self.assertIn("PREVIOUS_DAY_LOW", [e["kind"] for e in z[0]["evidence"]])

    def test_I0839_lifecycle_starts_at_the_pivot_confirmation(self):
        s = _demand_series(True, spike=True)
        piv = self.pivots(s)
        old = DV.demand_supply(s, piv, [], [], CFG, 0.01, "TICK_VOLUME", legacy=True)
        new = DV.demand_supply(s, piv, [], [], CFG, 0.01, "TICK_VOLUME")
        self.assertEqual((len(old), len(new)), (1, 1))
        self.assertEqual(old[0]["retests"], 1)                          # SEM-1: a touch before the zone was known counted
        self.assertEqual(new[0]["retests"], 0)                          # was 1
        self.assertEqual(new[0]["status"], "ACTIVE")


# ============================================================================================ I0840 features: unknown = NaN
class TestZoneFeaturesUnknownAsNaN(unittest.TestCase):
    @staticmethod
    def zmap(ctx, rm):
        z = {"zone_id": "UZ-1", "zone_type": "SWING_HIGH", "polarity": "HIGH", "lower_price": 101.0, "upper_price": 102.0, "confluence_score": 40.0,
             "status": "ACTIVE", "flags": [], "width_atr": 1.0}
        if rm is not None:
            z["reaction_metrics"] = rm
        return {"zones": [z], "context": ctx, "atr_m5": 1.0, "data": {"state": "OK"}}

    def test_unknown_age_retests_and_session(self):
        f = ZF.compute(self.zmap({}, None), direction="LONG", entry=100.0, stop=99.0)
        self.assertTrue(isnan(f["zone_opp_age_bars"]))                  # was 0.0 ("fresh")
        self.assertTrue(isnan(f["zone_opp_retests"]))                   # was 0.0 ("untested")
        self.assertTrue(isnan(f["zone_session"]))                       # was -1.0 ("outside every session")
        g = ZF.compute(self.zmap({"current_session": None}, {"retests": 0, "age_bars": None}), direction="LONG", entry=100.0, stop=99.0)
        self.assertEqual(g["zone_opp_retests"], 0.0)                    # a real 0 stays 0
        self.assertTrue(isnan(g["zone_opp_age_bars"]))
        self.assertTrue(isnan(g["zone_session"]))                       # no developing profile, window unknown
        out = ZF.compute(self.zmap({"current_session": None, "session_window": None}, {"retests": 2, "age_bars": 7}), direction="LONG",
                         entry=100.0, stop=99.0)
        self.assertEqual((out["zone_session"], out["zone_opp_age_bars"], out["zone_opp_retests"]), (-1.0, 7.0, 2.0))
        self.assertEqual(ZF.compute(self.zmap({"current_session": "LONDON"}, None), direction="LONG", entry=100.0, stop=99.0)["zone_session"], 1.0)
        leg = ZF.compute(self.zmap({}, None), direction="LONG", entry=100.0, stop=99.0, legacy=True)
        self.assertEqual((leg["zone_opp_age_bars"], leg["zone_opp_retests"], leg["zone_session"]), (0.0, 0.0, -1.0))   # SEM-1 kept

    def test_map_context_says_whether_a_session_window_is_open(self):
        self.assertEqual(DV.session_window("LAB_XAU_REFERENCE_V1", T0 + 60), "ASIA")
        self.assertIsNone(DV.session_window("LAB_XAU_REFERENCE_V1", T0 - 3 * 3600))     # 21:00 UTC: no XAU reference session


# ============================================================================================ I0841 equal highs / lows causal
class TestEqualHighsNoLookAhead(unittest.TestCase):
    def test_bounds_grow_only_when_the_next_member_is_confirmed(self):
        rows = [BASE] * 50
        rows[20] = (100.0, 101.5, 99.8, 100.0)                          # p1
        rows[30] = (100.0, 101.5, 99.8, 100.0)                          # p2, confirmed at 33 -> zone [101.45, 101.5]
        rows[38] = (100.0, 101.65, 99.8, 101.0)                         # wick above the zone KNOWN then, close back = sweep
        rows[40] = (100.0, 101.7, 99.8, 100.0)                          # p3 (higher), confirmed only at 43
        s = series(rows)
        a = HZ.atr_series(s)
        piv = HZ.swings(s, CFG, 0.01, a)
        self.assertEqual([p["index"] for p in piv if p["kind"] == "H" and not p["provisional"]], [20, 30, 40])
        old = next(z for z in HZ.equal_zones(s, piv, CFG, 0.01, a, legacy=True) if z["zone_type"] == "EQUAL_HIGHS")
        new = next(z for z in HZ.equal_zones(s, piv, CFG, 0.01, a) if z["zone_type"] == "EQUAL_HIGHS")
        self.assertEqual((old["lower"], old["upper"]), (new["lower"], new["upper"]))     # same final bounds at as_of
        self.assertNotIn("SWEEP_RECLAIMED", [e["kind"] for e in old["events"]])          # SEM-1: bar 38 judged with p3's bound
        self.assertEqual(new["status"], "SWEPT")                                          # was TESTED
        self.assertEqual(new["swept_at"], iso(s.close_time(38)))
        self.assertEqual([x["upper"] for x in new["segments"]], [101.5, 101.7])

    def test_equality_tolerance_uses_the_atr_known_at_confirmation(self):
        rows = [BASE] * 40 + [(95.0 - k % 3, 97.0 - k % 3, 89.0 - k % 3, 93.0 - k % 3) for k in range(40)]
        rows[20] = (100.0, 101.5, 99.8, 100.0)
        rows[30] = (100.0, 101.9, 99.8, 100.0)                          # 0.4 apart: > 0.25 x ATR(~1) when confirmed
        s = series(rows)
        a = HZ.atr_series(s)
        piv = HZ.swings(s, CFG, 0.01, a)

        def eqh(legacy):
            return [z for z in HZ.equal_zones(s, piv, CFG, 0.01, a, legacy=legacy) if z["zone_type"] == "EQUAL_HIGHS" and z["upper"] >= 101.9]
        self.assertEqual(len(eqh(True)), 1)                             # SEM-1: tolerance from the LAST bar's ATR (~7.7) groups them
        self.assertEqual(eqh(False), [])


# ============================================================================================ I0842 / I0843 / I0865 UZICE score
def _profiles():
    out = []
    for k in range(6):                                                  # VP-0 = the OLDEST, its POC at 100 (near the zone)
        poc = 100.0 if k == 0 else 200.0 + 10 * k
        out.append({"profile_id": f"VP-{k}", "state": "COMPLETED", "poc": poc, "vah": poc + 1.0, "val": poc - 1.0, "hvn": [], "lvn": [], "bin_size": 0.5,
                    "end": iso(T0 + k * 86400), "session": "ASIA", "local_date": f"2026-10-{19 + k}", "volume_source": "TICK_VOLUME"})
    return out


def _zone(**kw):
    z = {"zone_id": "HZ-a", "zone_type": "SWING_LOW", "tf": "M5", "lower": 99.9, "upper": 100.1, "status": "ACTIVE", "evidence": [],
         "created_at": iso(T0), "confirmed_at": iso(T0 + 900), "age_bars": 10, "retests": 0}
    z.update(kw)
    return {k: v for k, v in z.items() if v is not None}


def _unify(zones, profiles=None, legacy=False, as_of=T0 + 6 * 86400):
    out, _ = UZ.unify(zones, [], profiles or [], cfg=CFG, atr=1.0, tick=0.01, price=105.0, htf_sr=[], vol_source="TICK_VOLUME",
                      data_state="OK", as_of=as_of, legacy=legacy)
    return out[0]


class TestUziceScore(unittest.TestCase):
    def test_I0842_volume_points_only_from_the_latest_profiles_of_the_map(self):
        self.assertEqual(_unify([_zone()], _profiles(), legacy=True)["score_components"]["volume"], 10.0)   # SEM-1: oldest profile scored
        self.assertEqual(_unify([_zone()], _profiles())["score_components"]["volume"], 0.0)                 # was 10
        near_new = _profiles()
        near_new[5]["poc"] = 100.0                                      # the NEWEST profile at the zone still counts
        self.assertEqual(_unify([_zone()], near_new)["score_components"]["volume"], 10.0)

    def test_I0843_unknown_age_is_not_maximal_freshness(self):
        z = _zone(zone_type="PREVIOUS_SESSION_LOW", age_bars=None, created_at=None, confirmed_at=None)
        self.assertEqual(_unify([z], legacy=True)["score_components"]["freshness"], 10.0)     # SEM-1: unknown = age 0
        u = _unify([z])
        self.assertEqual(u["score_components"]["freshness"], 0.0)                              # was 10
        self.assertIn("AGE_UNKNOWN", u["flags"])
        known = _unify([_zone(zone_type="PREVIOUS_SESSION_LOW", age_bars=None, created_at=iso(T0 - 2 * 3600))], as_of=T0)
        self.assertAlmostEqual(known["score_components"]["freshness"], round(10 * (1 - 24 / 576), 2))   # age from its known time
        self.assertNotIn("AGE_UNKNOWN", known["flags"])

    def test_I0865_freshness_against_the_members_own_tf_limit(self):
        z = _zone(tf="M15", age_bars=CFG.max_age_bars["M15"])
        self.assertAlmostEqual(_unify([z], legacy=True)["score_components"]["freshness"], round(10 * (1 - 384 / 576), 2))   # SEM-1
        self.assertEqual(_unify([z])["score_components"]["freshness"], 0.0)                    # was 3.33
        half = _unify([_zone(tf="M15", age_bars=192), _zone(zone_id="HZ-b", tf="M5", age_bars=576)])
        self.assertEqual(half["score_components"]["freshness"], 5.0)                           # the freshest member counts


# ============================================================================================ map semantics + ML schema versioning
class TestZoneSemanticsAndMLSchema(unittest.TestCase):
    # zone block of MQ-FEAT-1.2.0, computed by the code BEFORE the fix for the deterministic bars of _case (SHORT, as_of = 7 M5 bars
    # before the end of test_zones.market()); SEM-2 differs there (zone_opp_age_bars unknown, zone_opp_score 24.2)
    EXPECTED_1_2_0: ClassVar[dict] = {"zone_data_ok": 1.0, "zone_dist_demand_atr": 3.57770049, "zone_dist_m15_high_atr": 4.286552397, "zone_dist_m15_low_atr": 4.498101278,
                      "zone_dist_m5_high_atr": 0.468795282, "zone_dist_m5_low_atr": 1.170498429, "zone_dist_poc_atr": 11.147860817, "zone_dist_supply_atr": None,
                      "zone_dist_vah_atr": 5.837856271, "zone_dist_val_atr": 15.368633662, "zone_hvn_near": 0.0, "zone_lvn_near": 0.0, "zone_opp_age_bars": 0.0,
                      "zone_opp_dist_r": 0.716406146, "zone_opp_retests": 0.0, "zone_opp_room_after_costs_r": 0.683072813, "zone_opp_score": 25.0,
                      "zone_opp_width_atr": 0.027, "zone_own_dist_r": 0.283593854, "zone_own_score": 28.0, "zone_own_swept": 0.0, "zone_poc_migration": None,
                      "zone_relvol": None, "zone_session": -1.0, "zone_va_position": -1.0, "zone_volume_source": 1.0}

    @staticmethod
    def _case():
        import test_zones as TZ
        from masterquo.config import AppConfig
        from masterquo.strategies import adapter
        m5 = TZ.gen(TZ.T0, 2016, seed=1)
        mk = {"M5": m5, "M15": TZ.agg(m5, 3), "H1": TZ.agg(m5, 12), "H4": TZ.agg(m5, 48), "D1": TZ.agg(m5, 288)}
        as_of = TZ.T0 + (2016 - 7) * 300
        sec = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
        bars = {tf: [b for b in rows if TZ.ts(b["open_utc"]) + sec[tf] <= as_of] for tf, rows in mk.items()}
        last = bars["M5"][-1]
        view = adapter.build_view(symbol="XAUUSD-", bars_by_tf=bars, bid=last["c"], ask=last["c"] + 0.1, point=0.01, as_of=iso(as_of),
                                  synthetic=True, regime_params=AppConfig().active.regime, max_bars=5000)
        ref = last["c"]
        cand = {"strategy_id": "S01", "direction": "SHORT", "timeframe": "M15", "stop_loss": ref + 3, "targets": [{"price": ref - 6, "weight": 1.0}],
                "setup_score": 72, "entry_plan": {"reference_price": ref}}
        return view, cand, datetime.fromtimestamp(as_of, UTC)

    @staticmethod
    def _r(d):
        return {k: (None if isnan(v) else round(v, 9)) for k, v in d.items()}

    def test_schema_bumped_and_old_schemas_still_load(self):
        from masterquo.ml import features as fe
        self.assertEqual(fe.FEATURE_SCHEMA_VERSION, "MQ-FEAT-1.3.0")
        self.assertTrue({"MQ-FEAT-1.0.0", "MQ-FEAT-1.1.0", "MQ-FEAT-1.2.0"} <= set(fe.COMPATIBLE_SCHEMAS))   # never INCOMPATIBLE (fail-open)
        self.assertEqual(set(fe.LEGACY_ZONE_SCHEMAS), {"MQ-FEAT-1.0.0", "MQ-FEAT-1.1.0", "MQ-FEAT-1.2.0"})

    def test_feature_row_carries_the_exact_1_2_0_zone_block_for_old_models(self):
        from masterquo.ml import features as fe
        f = fe.compute(*self._case())
        self.assertEqual(self._r(f[fe.LEGACY_ZONE_KEY]), self.EXPECTED_1_2_0)     # bit-identical inputs of a 1.2.0 model
        self.assertTrue(isnan(f["zone_opp_age_bars"]))                             # SEM-2 block for 1.3.0
        js = fe.from_json(__import__("json").loads(__import__("json").dumps(fe.to_json_safe(f))))
        self.assertEqual(self._r(js[fe.LEGACY_ZONE_KEY]), self.EXPECTED_1_2_0)    # survives storage (NaN -> null -> NaN)

    def test_bundle_adapt_by_model_schema_and_old_rows(self):
        from masterquo.ml import features as fe
        from masterquo.ml.models import Bundle, Calibrator
        from masterquo.ml.prep import Preprocessor
        new = {n: 1.0 for n in ZF.NAMES} | {"M5_rsi": 50.0, fe.LEGACY_ZONE_KEY: {n: 2.0 for n in ZF.NAMES}}

        def bundle(sv):
            return Bundle("DECISION_TREE", None, Preprocessor(), Calibrator(), {"family": "DECISION_TREE", "feature_schema_version": sv})
        for sv in ("MQ-FEAT-1.1.0", "MQ-FEAT-1.2.0", None):
            self.assertEqual(bundle(sv).adapt([new])[0]["zone_opp_score"], 2.0, sv)      # old model: its own (SEM-1) block
        self.assertEqual(bundle("MQ-FEAT-1.3.0").adapt([new])[0]["zone_opp_score"], 1.0)
        old_row = {n: 3.0 for n in ZF.NAMES} | {"M5_rsi": 50.0}                         # stored by 1.2.0: zone_* = SEM-1 values
        r = fe.from_json(fe.to_json_safe(old_row), "MQ-FEAT-1.2.0")
        self.assertTrue(isnan(r["zone_opp_score"]))                                     # unknown for a 1.3.0 model
        self.assertEqual(r["M5_rsi"], 50.0)
        self.assertEqual(bundle("MQ-FEAT-1.2.0").adapt([r])[0]["zone_opp_score"], 3.0)   # the 1.2.0 champion: exactly as before
        self.assertEqual(fe.from_json(fe.to_json_safe(old_row))["zone_opp_score"], 3.0)  # schema unknown: untouched

    def test_compute_map_semantics(self):
        import test_zones as TZ
        mk = TZ.market()
        as_of = T0 + 2016 * 300 - 7 * 300
        old = ZE.compute_map(instrument="XAUUSD", symbol="XAUUSD-", tick=0.01, bars=mk, cfg=CFG, as_of=as_of, semantics=ZE.LEGACY_SEMANTICS)
        new = ZE.compute_map(instrument="XAUUSD", symbol="XAUUSD-", tick=0.01, bars=mk, cfg=CFG, as_of=as_of)
        self.assertNotIn("semantics", old["versions"])                              # SEM-1 map (and map_id) as before
        self.assertEqual(new["versions"]["semantics"], ZE.SEMANTICS)
        self.assertNotEqual(old["map_id"], new["map_id"])
        self.assertIn("session_window", new["context"])
        self.assertNotIn("session_window", old["context"])
        with self.assertRaises(ValueError):
            ZE.compute_map(instrument="XAUUSD", symbol="XAUUSD-", tick=0.01, bars=mk, cfg=CFG, as_of=as_of, semantics="X")


if __name__ == "__main__":
    unittest.main()
