"""PMW zone engine (HLZE + DSVIE + UZICE, docs/ZONE_ENGINE_ARCHITECTURE.md): pivots and their confirmation time, zone lifecycle,
no look-ahead, DST-aware session profiles, volume-source honesty, evidence-based demand / supply, unification without double
counting, stable ids across restarts, features, evaluation / ML integration and isolation from the order path.
All market data here is SYNTHETIC and only exercises the rules - nothing in this file measures predictive value."""
import ast
import json
import random
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

from masterquo.config import ZonesConfig
from masterquo.zones import dsvie as DV
from masterquo.zones import engine as ZE
from masterquo.zones import features as ZF
from masterquo.zones import hlze as HZ
from masterquo.zones import uzice as UZ
from masterquo.zones.series import Series, iso, ts

UTC = timezone.utc
T0 = datetime(2026, 10, 19, tzinfo=UTC).timestamp()        # Monday
BASE = (100.0, 100.5, 99.5, 100.0)                            # flat bars: ATR 1.0, no pivots (equal highs / lows fail the strict side)
SPIKE = (100.2, 103.0, 100.0, 100.4)                          # swing high 103 (upper wick)
CFG = ZonesConfig()


def bar(t, o, h, l, c, tv=100.0, rv=0.0):
    return {"open_utc": iso(t), "o": o, "h": h, "l": l, "c": c, "tv": tv, "rv": rv, "closed": True}


def series(rows, tf="M5", t0=T0, tf_s=300):
    return Series.from_bars([bar(t0 + i * tf_s, *r) for i, r in enumerate(rows)], tf)


def gen(start, n, tf_s=300, seed=1, p0=2000.0):
    rnd, out, p = random.Random(seed), [], p0
    for i in range(n):
        o = p
        c = o + rnd.gauss(0, 1.2 * (tf_s / 300) ** 0.5)
        h, l = max(o, c) + abs(rnd.gauss(0, 0.6)), min(o, c) - abs(rnd.gauss(0, 0.6))
        p = c
        out.append(bar(start + i * tf_s, o, h, l, c, tv=float(rnd.randint(50, 400))))
    return out


def agg(bars, k):
    out = []
    for i in range(0, len(bars) - k + 1, k):
        g = bars[i:i + k]
        out.append(bar(ts(g[0]["open_utc"]), g[0]["o"], max(x["h"] for x in g), min(x["l"] for x in g), g[-1]["c"], tv=sum(x["tv"] for x in g)))
    return out


def market(n=2016, start=T0, seed=1):
    m5 = gen(start, n, seed=seed)
    return {"M5": m5, "M15": agg(m5, 3), "H1": agg(m5, 12), "D1": agg(m5, 288)}


def cmap(bars, as_of, cfg=CFG):
    return ZE.compute_map(instrument="XAUUSD", symbol="XAUUSD-", tick=0.01, bars=bars, cfg=cfg, as_of=as_of)


def zone_of(zs, ztype, pivot_index, s):
    return next(z for z in zs if z["zone_type"] == ztype and z.get("pivot_time") == iso(s.t[pivot_index]))


# --------------------------------------------------------------------------------------------- HLZE
class Pivots(unittest.TestCase):
    def test_provisional_until_right_side_complete(self):
        s = series([BASE] * 30 + [SPIKE] + [BASE] * 2)
        hs = [p for p in HZ.swings(s, CFG, 0.01) if p["kind"] == "H"]
        self.assertEqual(len(hs), 1)
        self.assertTrue(hs[0]["provisional"])
        self.assertIsNone(hs[0]["confirmed_at"])                  # not usable as a confirmed level yet
        z = zone_of(HZ.swing_zones(s, CFG, 0.01), "SWING_HIGH", 30, s)
        self.assertEqual(z["status"], "PROVISIONAL")

    def test_confirmation_time_is_never_backdated(self):
        s = series([BASE] * 30 + [SPIKE] + [BASE] * 3)
        p = next(p for p in HZ.swings(s, CFG, 0.01) if p["kind"] == "H")
        self.assertFalse(p["provisional"])
        self.assertEqual(p["created_at"], s.close_time(30))         # close of the pivot candle
        self.assertEqual(p["confirmed_at"], s.close_time(33))       # close of pivot + right (M5 right = 3)
        z = zone_of(HZ.swing_zones(s, CFG, 0.01), "SWING_HIGH", 30, s)
        self.assertEqual((z["created_at"], z["confirmed_at"]), (iso(s.close_time(30)), iso(s.close_time(33))))
        self.assertEqual(z["upper"], 103.0)
        self.assertTrue(100.4 < z["lower"] < 103.0)                 # wick-to-body, capped at k x ATR

    def test_low_prominence_is_not_a_swing(self):
        tight = (100.0, 100.1, 99.95, 100.0)                         # excursion around the pivot 0.25 << 0.6 x ATR (~0.9)
        s = series([BASE] * 30 + [tight] * 3 + [(100.0, 100.2, 99.95, 100.05)] + [tight] * 4)
        self.assertEqual([p for p in HZ.swings(s, CFG, 0.01) if p["kind"] == "H" and p["index"] == 33], [])

    def test_too_wide_zone_rejected_and_wide_flag(self):
        tight = CFG.model_copy(update={"max_zone_width_atr": 0.1, "min_width_ticks": 5})
        s = series([BASE] * 30 + [SPIKE] + [BASE] * 3)
        self.assertEqual([z for z in HZ.swing_zones(s, tight, 0.01) if z["zone_type"] == "SWING_HIGH"], [])   # > 2 x max -> rejected
        mid = CFG.model_copy(update={"max_zone_width_atr": 0.2})
        z = zone_of(HZ.swing_zones(s, mid, 0.01), "SWING_HIGH", 30, s)
        self.assertTrue(z["wide"])                                   # between max and 2 x max -> kept, flagged


class Lifecycle(unittest.TestCase):
    RETEST = (100.2, 102.8, 100.0, 100.4)

    def z(self, rows, cfg=CFG):
        s = series(rows)
        return zone_of(HZ.swing_zones(s, cfg, 0.01), "SWING_HIGH", 30, s), s

    def test_active_then_tested_then_weakened(self):
        head = [BASE] * 30 + [SPIKE] + [BASE] * 3
        z, _ = self.z(head + [BASE] * 3)
        self.assertEqual((z["status"], z["retests"]), ("ACTIVE", 0))
        z, _ = self.z(head + [self.RETEST] + [BASE] * 3)
        self.assertEqual((z["status"], z["retests"]), ("TESTED", 1))
        z, _ = self.z(head + ([self.RETEST] + [BASE] * 3) * 3)
        self.assertEqual((z["status"], z["retests"]), ("WEAKENED", 3))   # more tests = weaker, never "stronger"

    def test_touch_without_leaving_is_one_retest(self):
        z, _ = self.z([BASE] * 30 + [SPIKE] + [BASE] * 3 + [self.RETEST] * 3 + [BASE] * 3)
        self.assertEqual(z["retests"], 1)

    def test_sweep_needs_close_back(self):
        z, s = self.z([BASE] * 30 + [SPIKE] + [BASE] * 3 + [(100.2, 103.6, 100.0, 101.0)] + [BASE] * 2)
        self.assertEqual(z["status"], "SWEPT")
        self.assertEqual([e["kind"] for e in z["events"]], ["SWEEP_RECLAIMED", "RETEST"])   # the sweep bar is also a test
        self.assertIsNone(z["broken_at"])

    def test_wick_beyond_then_reclaim_is_sweep_not_break(self):
        # close just above the boundary but less than break_close_atr x ATR beyond it -> not broken; the next close back reclaims
        z, s = self.z([BASE] * 30 + [SPIKE] + [BASE] * 3 + [(100.2, 103.6, 100.0, 103.05)] + [BASE] * 2)
        self.assertEqual(z["status"], "SWEPT")
        ev = next(e for e in z["events"] if e["kind"] == "SWEEP_RECLAIMED")
        self.assertEqual((ev["wick_at"], ev["at"]), (iso(s.close_time(34)), iso(s.close_time(35))))

    def test_break_only_by_close_and_role_flip(self):
        rows = [BASE] * 30 + [SPIKE] + [BASE] * 3 + [(100.4, 104.0, 100.3, 103.8)] + [(103.8, 104.2, 103.4, 104.0)] * 3
        s = series(rows)
        zs = HZ.swing_zones(s, CFG, 0.01)
        z = zone_of(zs, "SWING_HIGH", 30, s)
        self.assertEqual((z["status"], z["broken_at"]), ("BROKEN", iso(s.close_time(34))))
        flip = next(x for x in zs if x["zone_type"] == "BREAKOUT_LEVEL" and x.get("flipped_from") == z["zone_id"])
        self.assertEqual(flip["confirmed_at"], iso(s.close_time(34)))   # known from the breaking close, not earlier
        self.assertEqual(UZ.polarity(flip["zone_type"]), "LOW")        # old resistance -> support candidate

    def test_expired_by_age(self):
        z, _ = self.z([BASE] * 30 + [SPIKE] + [BASE] * 25, cfg=CFG.model_copy(update={"max_age_bars": {"M5": 20, "M15": 20}}))
        self.assertEqual(z["status"], "EXPIRED")

    def test_equal_highs_known_at_second_confirmation(self):
        s = series([BASE] * 30 + [SPIKE] + [BASE] * 6 + [(100.2, 103.02, 100.0, 100.4)] + [BASE] * 5)
        a = HZ.atr_series(s)
        eq = HZ.equal_zones(s, HZ.swings(s, CFG, 0.01, a), CFG, 0.01, a)
        self.assertEqual(len(eq), 1)
        z = eq[0]
        self.assertEqual((z["zone_type"], z["members"]), ("EQUAL_HIGHS", 2))
        self.assertEqual(z["confirmed_at"], iso(s.close_time(40)))    # second pivot (37) + right 3
        self.assertEqual(z["liquidity"]["inference"], "INFERRED")     # never a measured quantity of orders
        self.assertEqual((z["lower"], z["upper"]), (102.97, 103.02))  # min width in ticks, anchored at the highest member


# --------------------------------------------------------------------------------------------- no look-ahead
class NoLookAhead(unittest.TestCase):
    def test_map_at_t_equals_map_from_data_cut_at_t(self):
        full = market()
        as_of = T0 + 1500 * 300 + 120                                # inside a forming M5 bar
        cut = {tf: [b for b in rows if ts(b["open_utc"]) + {"M5": 300, "M15": 900, "H1": 3600, "D1": 86400}[tf] <= as_of]
               for tf, rows in full.items()}
        a, b = cmap(full, as_of), cmap(cut, as_of)
        self.assertEqual(a["map_id"], b["map_id"])
        self.assertEqual(json.dumps(a["zones"], sort_keys=True, default=str), json.dumps(b["zones"], sort_keys=True, default=str))
        self.assertEqual(json.dumps(a["profiles"], sort_keys=True, default=str), json.dumps(b["profiles"], sort_keys=True, default=str))
        for z in a["zones"] + a["m5"] + a["m15"]:
            for k in ("confirmed_at", "created_at"):
                if z.get(k):
                    self.assertLessEqual(ts(z[k]), as_of, f"{z['zone_type']} {k}")

    def test_forming_bar_ignored(self):
        bars = market(400)
        as_of = T0 + 399 * 300 + 100                                  # the last bar is still forming
        a = cmap(bars, as_of)
        self.assertEqual(a["data"]["bars"]["M5"], 399)
        bars["M5"][-1]["closed"] = False
        self.assertEqual(cmap(bars, T0 + 400 * 300)["data"]["bars"]["M5"], 399)

    def test_insufficient_and_stale_data(self):
        bars = market(50)
        zm = cmap(bars, T0 + 50 * 300)
        self.assertEqual((zm["data"]["state"], zm["zones"]), ("INSUFFICIENT_HISTORY", []))
        bars = market(400)
        zm = cmap(bars, T0 + 400 * 300 + 3600)
        self.assertEqual(zm["data"]["state"], "STALE")
        self.assertTrue(all(z["score_components"]["data_quality"] == 0 for z in zm["zones"]))


# --------------------------------------------------------------------------------------------- DSVIE
class Profiles(unittest.TestCase):
    def test_known_histogram_value_area_nodes(self):
        s = series([(100.0, 102.0, 100.0, 101.0, 100.0), (100.5, 100.5, 100.5, 100.5, 10.0)])
        h = DV.histogram(s, [0, 1], 1.0, "TICK_VOLUME")
        self.assertEqual(h, {100: 60.0, 101: 50.0})                  # 2-wide bar split by overlap; a zero-range bar -> one bin
        self.assertEqual(DV.value_area({0: 10, 1: 20, 2: 50, 3: 15, 4: 5}, 0.70), (2, 1, 2))
        self.assertEqual(DV.value_area({0: 10, 1: 10}, 0.5)[0], 0)  # tie -> lower price
        hist = dict(enumerate([1, 5, 10, 5, 1, 1, 5, 9, 5, 1]))
        self.assertEqual(DV.nodes(hist, 2, CFG.model_copy(update={"node_smoothing_bins": 1})), ([7], [4]))

    def test_volume_source_is_reported_not_assumed(self):
        mk = lambda tv, rv: Series.from_bars([bar(T0 + i * 300, *BASE, tv=tv, rv=rv) for i in range(10)], "M5")
        self.assertEqual(DV.volume_source(mk(100, 0))["source"], "TICK_VOLUME")
        self.assertEqual(DV.volume_source(mk(100, 5))["source"], "EXCHANGE_VOLUME")
        src = DV.volume_source(mk(0, 0))
        self.assertEqual((src["source"], src["order_flow"], src["footprint"], src["order_book"]), ("NONE", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE"))
        self.assertIn("nie jest wolumenem transakcyjnym", DV.volume_source(mk(100, 0))["note"])

    def _profiles(self, rows, as_of):
        s = Series.from_bars(rows, "M5", as_of)
        return DV.session_profiles(s, "LAB_XAU_REFERENCE_V1", "XAUUSD", CFG, as_of, "TICK_VOLUME")

    def test_dst_session_boundaries(self):
        start = datetime(2026, 10, 21, tzinfo=UTC).timestamp()
        rows = gen(start, 7 * 288)
        ps = self._profiles(rows, start + 7 * 86400)
        lon = {p["local_date"]: p for p in ps if p["session"] == "LONDON"}
        ny = {p["local_date"]: p for p in ps if p["session"] == "NEW_YORK"}
        self.assertEqual(lon["2026-10-23"]["start"], "2026-10-23T07:00:00Z")   # BST (UTC+1)
        self.assertEqual(lon["2026-10-26"]["start"], "2026-10-26T08:00:00Z")   # GMT after 25 Oct 2026
        self.assertEqual(ny["2026-10-26"]["start"], "2026-10-26T12:20:00Z")    # New York still on EDT until 1 Nov
        self.assertEqual(lon["2026-10-23"]["expected_bars"], 102)               # 08:00-16:30 = 8.5 h of M5

    def test_completed_profile_is_reproducible_and_developing_uses_only_closed_bars(self):
        start = datetime(2026, 10, 21, tzinfo=UTC).timestamp()
        rows = gen(start, 4 * 288)
        keys = ("profile_id", "state", "poc", "vah", "val", "hvn", "lvn", "total_volume", "known_at", "bars")
        p1 = next(p for p in self._profiles(rows, start + 86400 + 17 * 3600) if p["session"] == "LONDON" and p["local_date"] == "2026-10-22")
        p2 = next(p for p in self._profiles(rows, start + 3 * 86400) if p["session"] == "LONDON" and p["local_date"] == "2026-10-22")
        self.assertEqual(p1["state"], "COMPLETED")
        self.assertEqual({k: p1[k] for k in keys}, {k: p2[k] for k in keys})
        dev_at = datetime(2026, 10, 22, 10, 0, tzinfo=UTC).timestamp()
        d = next(p for p in self._profiles(rows, dev_at) if p["session"] == "LONDON" and p["local_date"] == "2026-10-22")
        self.assertEqual((d["state"], d["bars"], d["known_at"]), ("DEVELOPING", 36, "2026-10-22T10:00:00Z"))
        self.assertTrue(all(ts(x["at"]) <= dev_at for x in d["poc_path"]))

    def test_incomplete_window_is_invalid_and_old_developing_is_stale(self):
        start = datetime(2026, 10, 21, tzinfo=UTC).timestamp()
        rows = gen(start, 3 * 288)
        hole = [b for b in rows if not ("2026-10-22T08:00" <= b["open_utc"] < "2026-10-22T10:00")]
        p = next(p for p in self._profiles(hole, start + 2 * 86400 + 3600) if p["session"] == "LONDON" and p["local_date"] == "2026-10-22")
        self.assertEqual(p["state"], "INVALID")
        self.assertIn("pokrycie", p["reason"])
        early = [b for b in rows if b["open_utc"] < "2026-10-22T09:00"]
        p = next(p for p in self._profiles(early, datetime(2026, 10, 22, 10, 0, tzinfo=UTC).timestamp())
                 if p["session"] == "LONDON" and p["local_date"] == "2026-10-22")
        self.assertEqual(p["state"], "STALE")

    def test_relative_volume_uses_same_session_same_elapsed_time(self):
        start = datetime(2026, 10, 19, tzinfo=UTC).timestamp()
        rows = gen(start, 5 * 288)
        for b in rows:                                               # double activity on 23 Oct only
            if b["open_utc"].startswith("2026-10-23"):
                b["tv"] *= 2
        p = next(p for p in self._profiles(rows, datetime(2026, 10, 23, 10, 0, tzinfo=UTC).timestamp())
                 if p["session"] == "LONDON" and p["local_date"] == "2026-10-23")
        self.assertGreater(p["relative_volume"], 1.5)
        self.assertGreaterEqual(p["relative_volume_baseline_sessions"], 3)


class DemandSupply(unittest.TestCase):
    LOW = (100.0, 100.2, 97.0, 99.9)                                 # lower wick = rejection

    def ds(self, tv_pivot):
        rows = [BASE] * 30 + [self.LOW + (tv_pivot,)] + [BASE] * 6
        s = Series.from_bars([bar(T0 + i * 300, *(r if len(r) == 5 else r + (100.0,))) for i, r in enumerate(rows)], "M5")
        return DV.demand_supply(s, HZ.swings(s, CFG, 0.01), [], [], CFG, 0.01, "TICK_VOLUME")

    def test_price_action_alone_is_not_demand(self):
        self.assertEqual(self.ds(100.0), [])

    def test_demand_needs_context_and_is_never_order_flow(self):
        out = self.ds(400.0)                                          # tick-activity spike = volume observation (proxy)
        self.assertEqual(len(out), 1)
        z = out[0]
        self.assertEqual((z["zone_type"], z["order_flow_verified"]), ("DEMAND", False))
        self.assertEqual({e["evidence_type"] for e in z["evidence"]}, {"PRICE_ACTION_INFERENCE", "VOLUME_OBSERVATION"})
        self.assertIn("TICK_ACTIVITY_SPIKE", {e["kind"] for e in z["evidence"]})


# --------------------------------------------------------------------------------------------- UZICE
def mz(zid, ztype, lo, up, tf="M5", conf="2026-10-20T10:00:00Z", root=None, status="ACTIVE", **kw):
    z = {"zone_id": zid, "zone_type": ztype, "tf": tf, "lower": lo, "upper": up, "status": status, "provisional": status == "PROVISIONAL",
         "created_at": conf, "confirmed_at": None if status == "PROVISIONAL" else conf, "age_bars": 10, "retests": 0, "rejection_max_atr": 0.0,
         "penetration_max": 0.0, "evidence": [{"group": "structure", "kind": f"{tf}_{ztype}", "root": root or zid}]}
    z.update(kw)
    return z


def unify(zs, price=99.0, profiles=(), vol="TICK_VOLUME", state="OK"):
    return UZ.unify(list(zs), [], list(profiles), cfg=CFG, atr=1.0, tick=0.01, price=price, htf_sr=[], vol_source=vol, data_state=state,
                    as_of=ts("2026-10-20T12:00:00Z"))[0]


class Unify(unittest.TestCase):
    def test_merge_keeps_origins_and_anchor_id(self):
        a = mz("HZ-a", "SWING_HIGH", 100.0, 100.3, conf="2026-10-20T10:00:00Z")
        b = mz("HZ-b", "SWING_HIGH", 100.2, 100.5, tf="M15", conf="2026-10-20T09:00:00Z")
        out = unify([a, b])
        self.assertEqual(len(out), 1)
        z = out[0]
        self.assertEqual(sorted(z["source_zone_ids"]), ["HZ-a", "HZ-b"])
        self.assertEqual(z["timeframes"], ["M15", "M5"])
        self.assertEqual(z["score_components"]["mtf"], 10)
        out2 = unify([a, b, mz("HZ-c", "SWING_HIGH", 100.25, 100.45, conf="2026-10-20T11:00:00Z")])
        self.assertEqual(out2[0]["zone_id"], z["zone_id"])           # a later member does not change the id
        self.assertEqual(z["confidence_status"], "UNVALIDATED")

    def test_too_wide_cluster_is_not_merged(self):
        out = unify([mz("HZ-a", "SWING_HIGH", 100.0, 100.8), mz("HZ-b", "SWING_HIGH", 100.9, 101.7)])
        self.assertEqual(len(out), 2)                                  # merged width would exceed max_zone_width_atr

    def test_opposite_polarity_conflict_not_merged(self):
        out = unify([mz("HZ-a", "SWING_HIGH", 100.0, 100.3), mz("HZ-b", "SWING_LOW", 100.1, 100.4)])
        self.assertEqual(len(out), 2)
        for z in out:
            self.assertIn("CONFLICT", z["flags"])
            self.assertGreaterEqual(z["penalty"], 10)

    def test_correlated_evidence_counted_once(self):
        one = unify([mz("HZ-a", "SWING_HIGH", 100.0, 100.3, root="PV-1")])[0]
        two = unify([mz("HZ-a", "SWING_HIGH", 100.0, 100.3, root="PV-1"), mz("HZ-b", "SWING_HIGH", 100.05, 100.3, root="PV-1")])[0]
        many = unify([mz(f"HZ-{i}", "SWING_HIGH", 100.0 + i * 0.01, 100.3, root=f"PV-{i}") for i in range(8)])[0]
        self.assertEqual(one["score_components"]["structure"], two["score_components"]["structure"])
        self.assertEqual(many["score_components"]["structure"], 6)    # eight M5 swings in one place = one category

    def test_deterministic_and_bounded(self):
        zs = [mz(f"HZ-{i}", "SWING_HIGH" if i % 2 else "SWING_LOW", 95 + i * 0.7, 95.3 + i * 0.7) for i in range(12)]
        a = unify(zs)
        b = unify(list(reversed(zs)))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertTrue(all(0 <= z["confluence_score"] <= 100 for z in a))

    def test_volume_points_need_a_volume_source_and_data_quality_follows_state(self):
        prof = {"profile_id": "VP-1", "session": "LONDON", "local_date": "2026-10-19", "state": "COMPLETED", "volume_source": "TICK_VOLUME",
                "bin_size": 0.5, "poc": 100.25, "vah": 101.0, "val": 99.0, "hvn": [], "lvn": [], "end": "2026-10-19T15:30:00Z"}
        z = mz("HZ-a", "SWING_HIGH", 100.0, 100.3)
        self.assertEqual(unify([z], profiles=[prof])[0]["score_components"]["volume"], 10)
        self.assertEqual(unify([z], profiles=[prof], vol="NONE")[0]["score_components"]["volume"], 0)
        self.assertEqual(unify([z], state="STALE")[0]["score_components"]["data_quality"], 0)

    def test_nearest_is_directional(self):
        zm = {"zones": unify([mz("HZ-r", "SWING_HIGH", 101.0, 101.3), mz("HZ-s", "SWING_LOW", 98.0, 98.3)], price=100.0)}
        self.assertEqual(UZ.nearest(zm, "ABOVE", 100.0)["source_zone_ids"], ["HZ-r"])
        self.assertEqual(UZ.nearest(zm, "BELOW", 100.0)["source_zone_ids"], ["HZ-s"])
        self.assertIsNone(UZ.nearest({"zones": [z for z in zm["zones"] if z["polarity"] == "LOW"]}, "ABOVE", 100.0))


# --------------------------------------------------------------------------------------------- map, features, evaluation
class MapAndFeatures(unittest.TestCase):
    def test_map_contract_and_speed(self):
        bars = market()
        t0 = time.perf_counter()
        zm = cmap(bars, T0 + 2016 * 300)
        self.assertLess(time.perf_counter() - t0, 10.0)
        self.assertEqual((zm["schema_version"], zm["mode"], zm["data"]["state"]), ("PMW-ZONE-1.0", "ANALYTICAL_ONLY", "OK"))
        self.assertEqual(zm["volume_source"]["source"], "TICK_VOLUME")
        self.assertTrue(zm["zones"])
        need = {"zone_id", "zone_type", "polarity", "timeframes", "lower_price", "upper_price", "mid_price", "width_atr", "created_at",
                "confirmed_at", "status", "structure_evidence", "volume_evidence", "reaction_metrics", "score_components", "flags",
                "confidence_status", "invalidation_rules", "source_zone_ids", "confluence_score"}
        for z in zm["zones"]:
            self.assertFalse(need - set(z), z["zone_type"])
            self.assertLessEqual(z["lower_price"], z["upper_price"])
        ids = [z["zone_id"] for z in zm["zones"]]
        self.assertEqual(len(ids), len(set(ids)))                   # one authoritative map: no duplicate zone

    def test_features_complete_and_nan_without_map(self):
        zm = cmap(market(), T0 + 2016 * 300)
        f = ZF.compute(zm, direction="LONG", entry=zm["price"], stop=zm["price"] - 3, cost_price=0.3)
        self.assertEqual(set(f), set(ZF.NAMES))
        self.assertEqual(f["zone_volume_source"], 1.0)
        empty = ZF.compute({}, direction="LONG", entry=100.0, stop=99.0)
        self.assertTrue(all(v != v for v in empty.values()))

    def test_room_flag_only_for_strong_close_opposing_zone(self):
        def zmap(score):
            z = dict(unify([mz("HZ-r", "SWING_HIGH", 101.0, 101.3)], price=100.0)[0], confluence_score=score)
            return {"zones": [z], "data": {"state": "OK"}, "atr_m5": 1.0, "map_id": "ZM-x", "as_of": "2026-10-20T12:00:00Z"}
        ctx = ZF.context_for(zmap(70), direction="LONG", entry=100.0, stop=99.0, cost_price=0.2, cfg=CFG)
        self.assertEqual((ctx["room_after_costs_r"], ctx["flags"]), (0.8, ["ZONE_ROOM_INSUFFICIENT"]))
        self.assertEqual(ZF.context_for(zmap(40), direction="LONG", entry=100.0, stop=99.0, cost_price=0.2, cfg=CFG)["flags"], [])
        self.assertEqual(ZF.context_for(zmap(70), direction="LONG", entry=100.0, stop=99.5, cost_price=0.2, cfg=CFG)["flags"], [])


class EvaluationIntegration(unittest.TestCase):
    def test_zone_context_reduces_only_with_ok_data(self):
        from test_evaluation import cand
        from masterquo.evaluation import engine as E
        p = {"value": 0.60, "calibrated": True, "n_calibration": 2000}
        self.assertEqual(E.assess(cand(), prob=p, extra_cost=0.1).decision, "ACCEPT")
        z = {"map_id": "ZM-1", "map_as_of": "x", "data_state": "OK", "flags": ["ZONE_ROOM_INSUFFICIENT"], "room_after_costs_r": 0.5}
        a = E.assess(cand(), prob=p, extra_cost=0.1, zones=z)
        self.assertEqual((a.decision, a.rejection_reasons), ("REDUCE", ["ZONE_ROOM_INSUFFICIENT"]))
        self.assertEqual(a.zone_context["map_id"], "ZM-1")
        b = E.assess(cand(), prob=p, extra_cost=0.1, zones=dict(z, data_state="STALE"))
        self.assertEqual(b.decision, "ACCEPT")                       # a non-OK map is information only
        self.assertTrue(any("mapa stref STALE" in n for n in b.notes))
        self.assertEqual(E.assess(cand(), prob=None, extra_cost=0.1, zones=z).decision, "DEFER")   # zones never create a probability


class EvaluationLookAhead(unittest.TestCase):
    """The ledger stores the zone context of a setup only from a map known at the decision time."""

    def setUp(self):
        import test_evaluation as TE
        self.TE = TE
        TE.ServiceAndExposure.setUp(self)

    def tearDown(self):
        self.TE.ServiceAndExposure.tearDown(self)

    def log_with_map(self, map_as_of):
        class Provider:
            def context_for(self, **kw):
                return {"map_id": "ZM-1", "map_as_of": iso(map_as_of), "data_state": "OK", "flags": [], "features": {"zone_data_ok": 1.0}}
        TE = self.TE
        self.svc.zone_provider = Provider()
        su = TE.mk_setup(self.spec, "SCALPING", "BUY", ref=2000.2)
        self.svc.on_sh_cycle({"SCALPING": su}, inst="XAUUSD", symbol=su["symbol"], snap=None, now=TE.NOW)
        return self.svc.assessments()[0]["zone_context"]

    def test_map_newer_than_decision_is_ignored(self):
        self.assertEqual(self.log_with_map(self.TE.NOW + 60), {})       # no zone context recorded

    def test_map_known_at_decision_is_recorded(self):
        self.assertEqual(self.log_with_map(self.TE.NOW - 60)["map_id"], "ZM-1")


class ServiceRestart(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        self.store = ConfigStore()
        self.bars = market()
        bars = self.bars

        class Bridge:
            symbol_info = {"trade_tick_size": 0.01}

            def symbol_bars(self, symbol, tf, n):
                return bars[tf][-n:]

            def bars(self, tf, include_forming=False, limit=None):
                return bars[tf][-500:]
        self.bridge = Bridge()
        self.as_of = T0 + 2016 * 300

    def tearDown(self):
        self.td.close()

    def svc(self):
        from masterquo.zones.service import ZoneService
        return ZoneService(self.store, self.bridge, data_dir=Path(self.td.dir) / "zones", clock=lambda: self.as_of)

    def test_stable_ids_and_no_duplicate_events_across_restart(self):
        s1 = self.svc()
        m1 = s1.refresh()
        n_ev = len(s1.events(1000))
        self.assertGreater(n_ev, 0)
        self.assertEqual(s1.refresh()["map_id"], m1["map_id"])
        self.assertEqual(len(s1.events(1000)), n_ev)
        s1.db.close()
        s2 = self.svc()                                               # restart: same bars -> same map, same zone ids, no new events
        m2 = s2.refresh()
        self.assertEqual(m2["map_id"], m1["map_id"])
        self.assertEqual([z["zone_id"] for z in m2["zones"]], [z["zone_id"] for z in m1["zones"]])
        self.assertEqual(len(s2.events(1000)), n_ev)
        self.assertEqual(s2.db.execute("SELECT COUNT(*) FROM zone_maps").fetchone()[0], 1)
        self.assertEqual(s2.status()["mode"], "ANALYTICAL_ONLY")
        s2.db.close()

    def test_historical_view_and_chart_payload(self):
        from masterquo.zones.service import ZoneService
        s = self.svc()
        past = self.as_of - 6 * 3600
        h = s.at(past)
        self.assertEqual(h["as_of"], iso(past))
        self.assertTrue(all(ts(z["confirmed_at"]) <= past for z in h["zones"] if z.get("confirmed_at")))
        self.assertEqual(ZoneService.chart_view(None), {"status": "NO_MAP"})
        down = ZoneService(self.store, object(), data_dir=Path(self.td.dir) / "zones2", clock=lambda: self.as_of)
        self.assertIsNone(down.current_or_refresh())                 # no terminal: no map and no exception
        self.assertIn("AttributeError", down.status()["last_error"])
        down.db.close()
        cv = ZoneService.chart_view(s.refresh(), "M5")
        self.assertEqual(cv["status"], "OK")
        self.assertTrue(all("M5" in z["timeframes"] or "D1" in z["timeframes"] for z in cv["zones"]))
        self.assertEqual(cv["profile_last_completed"]["state"], "COMPLETED")
        self.assertEqual(cv["volume_source"]["source"], "TICK_VOLUME")
        ctx = s.context_for(direction="LONG", entry=cv["summary"]["price"], stop=cv["summary"]["price"] - 3)
        self.assertEqual(ctx["map_id"], cv["map_id"])
        s.db.close()


class MLSchema(unittest.TestCase):
    def test_superset_schema(self):
        from masterquo.ml import features as fe
        self.assertEqual(fe.FEATURE_SCHEMA_VERSION, "MQ-FEAT-1.1.0")
        self.assertIn("MQ-FEAT-1.0.0", fe.COMPATIBLE_SCHEMAS)
        self.assertTrue(set(ZF.NAMES) <= set(fe.FEATURE_NAMES))

    def test_feature_engine_fills_the_zone_block(self):
        """The zone block must really be computed in the ML path (its error fallback is NaN, which would otherwise go unnoticed);
        test_ml.TestNoLookAhead already checks that these values do not change when future bars are added."""
        import test_ml as TM
        from masterquo.ml import features as fe
        TM.TestNoLookAhead.setUpClass()
        case = TM.TestNoLookAhead()
        m15 = TM.TestNoLookAhead.data["M15"]
        t = datetime.fromisoformat(m15[-120]["available_at"].replace("Z", "+00:00"))
        cand = {"strategy_id": "S01", "direction": "LONG", "timeframe": "M15", "stop_loss": m15[-121]["l"] - 2,
                "targets": [{"price": m15[-121]["c"] + 4, "weight": 1.0}], "setup_score": 72, "entry_plan": {"reference_price": m15[-121]["c"]}}
        f = fe.compute(case._view(t), cand, t)
        z = {k: f[k] for k in ZF.NAMES}
        self.assertGreaterEqual(sum(1 for v in z.values() if v == v), 20, z)
        self.assertEqual(z["zone_data_ok"], 1.0)
        self.assertLess(z["zone_opp_room_after_costs_r"], z["zone_opp_dist_r"])   # the quoted spread is a real cost

    def test_model_saved_on_1_0_0_still_loads_and_scores_1_1_0_rows(self):
        import tempfile
        from sklearn.tree import DecisionTreeClassifier
        from masterquo.ml.models import Bundle, Calibrator
        from masterquo.ml.prep import NUMERIC, Preprocessor
        old = [n for n in NUMERIC if not n.startswith("zone_")][:3]
        rnd = random.Random(3)
        rows = [{n: rnd.random() for n in old} for _ in range(60)]
        y = [int(r[old[0]] > 0.5) for r in rows]
        prep = Preprocessor().fit(rows)
        model = DecisionTreeClassifier(max_depth=2, random_state=0).fit(prep.transform(rows), y)
        with tempfile.TemporaryDirectory() as d:
            for sv, ok in (("MQ-FEAT-1.0.0", True), ("MQ-FEAT-1.1.0", True), ("MQ-FEAT-0.9.0", False)):
                path = Path(d) / sv
                Bundle("DECISION_TREE", model, prep, Calibrator(), {"family": "DECISION_TREE", "feature_schema_version": sv}).save(path)
                if not ok:
                    with self.assertRaises(ValueError):
                        Bundle.load(path)
                    continue
                b = Bundle.load(path)
                new_row = dict(rows[0], **{n: 1.0 for n in ZF.NAMES})          # a 1.1.0 row: extra zone columns are ignored
                self.assertEqual(list(b.raw([new_row])), list(b.raw([rows[0]])))


class Isolation(unittest.TestCase):
    def test_zone_package_never_reaches_the_order_path(self):
        root = _env.ROOT / "backend" / "masterquo" / "zones"
        banned_mod = ("execution", "mt5.worker", "sh.executor", "engine.decision", "risk.engine")
        banned_name = {"order_send", "ExecutionGateway", "PaperBroker", "PositionManager", "SHExecutor", "open_plan", "close_position"}
        files = sorted(root.glob("*.py"))
        self.assertGreaterEqual(len(files), 7)
        for f in files:
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.ImportFrom):
                    mod = n.module or ""
                    self.assertFalse(any(b in mod for b in banned_mod), f"{f.name}: from {mod}")
                elif isinstance(n, ast.Import):
                    self.assertFalse(any(b in a.name for a in n.names for b in banned_mod), f"{f.name}")
                elif isinstance(n, (ast.Attribute, ast.Name)):
                    self.assertNotIn(getattr(n, "attr", None) or getattr(n, "id", None), banned_name, f"{f.name}")


if __name__ == "__main__":
    unittest.main()
