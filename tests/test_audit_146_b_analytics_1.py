"""1.46 audit, group B_analytics_1 - regression tests (SYNTHETIC_TEST data only: logic checks, never market evidence).

chunk_01#4   chart_patterns: invalidation BEFORE the confirmation is checked first and never revived by a later neckline break
chunk_01#5   H&S / inverse H&S invalidation beyond the right shoulder; after the confirmation the reported level is the state rule
chunk_01#3   structure_v2.upgrade_patterns: real boundary keys (neckline / level / upper / lower), start = bar of detected_at
chunk_01#13  sci2: the bearish family is HEAD_SHOULDERS (NECKLINE_BREAK reachable), structural level = frozen v2 confirm level
chunk_01#8   levels.aggregate_d1: Sunday D1 opens the next week; a forming D1 of the next period completes the previous one
chunk_01#6 / #14 / #17  iv_import: bad rows rejected with a reason (never an exception), BOM, TIME_WITHOUT_UTC_ZONE reachable
chunk_02#10 / #11 / #12  black76: unknown quote age is not fresh, malformed pairs / discount rejected, overflow -> Black76Error
chunk_02#15  contract.clean: numpy NaN / inf scalars -> None
chunk_02#3 / #4 / #13 / #18  pattern library: one bad sample != failed job, restore of a deleted sample, delete result, resume race
chunk_02#5 / #6 / #7  liquidity service: every poll failure backs off, a poisoned inbox file never blocks, as_of point in time
chunk_02#17  liquidity CLI: sessions as_of = close of the last M1 bar, unknown profile rejected by argparse
chunk_02#16  liquidity_eval: heatmap coverage counted per variant
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import _env  # noqa: F401
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent / "analytics"))

import fixtures as F
from test_patterns_walls import T0, bars_from_ohlc, flat, path_bars, view


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _scan(bars):
    from masterquo.analysis import chart_patterns as CP
    return CP.scan(view(bars), "M5")


def _cols(bars):
    return [x["open_utc"] for x in bars], [x["o"] for x in bars], [x["h"] for x in bars], [x["l"] for x in bars], [x["c"] for x in bars]


DT_PTS = [100, 100.5, 99.8, 100.3, 99.9, 104, 101.5, 104.05, 101.8, 102.2]     # double top 104 / 104.05, neckline ~101.4
HS_PTS = [96, 99, 97, 101, 96.9, 98.9, 96.8, 95.5, 95]                          # H&S: LS 99, H 101, RS 98.9, confirmed


def _dt_base():
    return flat(30, 100) + path_bars(DT_PTS, steps=4, start=T0 + timedelta(minutes=150))


# ---------------------------------------------------------------------------------------------------------- chunk_01#4
class TestChartPatternPreConfirmationInvalidation(unittest.TestCase):
    def test_close_beyond_extreme_before_confirmation_is_invalidated_not_confirmed_later(self):
        b = _dt_base()
        dt = [p for p in _scan(b)["patterns"] if p["type"] == "DOUBLE_TOP" and p["state"] == "FORMING"]
        self.assertTrue(dt)
        pid = dt[0]["pattern_id"]
        ext = max(a["price"] for a in dt[0]["anchors"] if a["role"].startswith("PEAK"))
        # price closes ABOVE both peaks (pattern dead), then falls through the neckline: the old code confirmed it (A-07-01)
        more = path_bars([102.2, 105.6, 105.2, 100.0, 99.0], steps=3, start=T0 + timedelta(minutes=5 * len(b)))
        self.assertTrue(any(x["c"] > ext for x in more))
        rec = next(p for p in _scan(b + more)["patterns"] if p["pattern_id"] == pid)
        self.assertEqual(rec["state"], "INVALIDATED")
        self.assertIsNone(rec["confirm_bar"])

    def test_plain_confirmation_unchanged(self):
        b = _dt_base()
        more = path_bars([102.2, 100.0, 99.5], steps=4, start=T0 + timedelta(minutes=5 * len(b)))
        dt = [p for p in _scan(b + more)["patterns"] if p["type"] == "DOUBLE_TOP" and p["boundary"]["neckline"] == 101.4]
        self.assertEqual(dt[0]["state"], "CONFIRMED")


# ---------------------------------------------------------------------------------------------------------- chunk_01#5
class TestHeadShouldersInvalidationLevel(unittest.TestCase):
    def _case(self, inverse):
        pts = [200 - x for x in HS_PTS] if inverse else HS_PTS
        b = flat(30, pts[0]) + path_bars(pts, steps=4, start=T0 + timedelta(minutes=150))
        kind = "INVERSE_HEAD_SHOULDERS" if inverse else "HEAD_SHOULDERS"
        p0 = next(p for p in _scan(b)["patterns"] if p["type"] == kind)
        rs = next(a["price"] for a in p0["anchors"] if a["role"] == "RIGHT_SHOULDER")
        hd = next(a["price"] for a in p0["anchors"] if a["role"] == "HEAD")
        return b, pts, p0, rs, hd

    def test_invalidation_is_beyond_the_right_shoulder(self):
        _, _, p0, rs, _ = self._case(False)
        self.assertEqual(p0["state"], "CONFIRMED")
        self.assertGreater(p0["invalidation"], rs)                       # bearish H&S: above the right shoulder (was rs - 0.1 ATR)
        _, _, p1, rs1, _ = self._case(True)
        self.assertLess(p1["invalidation"], rs1)                         # inverse: below the right shoulder

    def test_state_rule_uses_the_reported_level_after_confirmation(self):
        for inverse in (False, True):
            b, pts, p0, _, hd = self._case(inverse)
            tgt = 100.2 if not inverse else 99.8                         # back beyond the right shoulder, NOT beyond the head
            self.assertTrue((p0["invalidation"] < tgt < hd) if not inverse else (hd < tgt < p0["invalidation"]))
            more = path_bars([pts[-1], tgt, tgt], steps=3, start=T0 + timedelta(minutes=5 * len(b)))
            rec = next(p for p in _scan(b + more)["patterns"] if p["pattern_id"] == p0["pattern_id"])
            self.assertEqual(rec["state"], "INVALIDATED", inverse)


# ---------------------------------------------------------------------------------------------------------- chunk_01#3
class TestUpgradePatternsV2(unittest.TestCase):
    def _up(self, bars):
        from masterquo.analysis import structure_v2 as S
        sc = _scan(bars)
        t, o, h, lo, c = _cols(bars)
        return S.upgrade_patterns(sc, t, o, h, lo, c, S._atr(h, lo, c, len(c) - 1)), t

    def test_confirm_level_from_real_boundary_keys(self):
        from masterquo.analysis import structure_v2 as S
        self.assertEqual(S.confirm_level({"boundary": {"neckline": 101.4, "slope": 0.0}, "direction_if_confirmed": "SHORT"}, 10), 101.4)
        f = S.confirm_level({"boundary": {"neckline": 100.0, "slope": 0.5}, "direction_if_confirmed": "SHORT"}, 10)
        self.assertTrue(callable(f))
        self.assertEqual((f(9), f(7)), (100.0, 99.0))                    # the record's value is at the last bar of the window
        geo = {"upper": 105.0, "lower": 95.0, "upper_slope": 0.0, "lower_slope": 0.0}
        self.assertEqual(S.confirm_level({"boundary": geo, "direction_if_confirmed": "LONG"}, 10), 105.0)
        self.assertEqual(S.confirm_level({"boundary": geo, "direction_if_confirmed": "SHORT"}, 10), 95.0)
        self.assertIsNone(S.confirm_level({"boundary": geo, "direction_if_confirmed": None}, 10))
        self.assertEqual(S.confirm_level({"boundary": {"level": 101.0}, "direction_if_confirmed": "SHORT"}, 10), 101.0)

    def test_scan_to_v2_is_supported_and_starts_after_detection(self):
        b = _dt_base()
        bars = b + path_bars([102.2, 100.0, 99.5], steps=4, start=T0 + timedelta(minutes=5 * len(b)))
        ups, t = self._up(bars)
        directional = [r for r in ups if r.get("direction_if_confirmed") and r.get("invalidation") is not None]
        self.assertTrue(directional)
        self.assertFalse([r for r in directional if r["v2_state"] == "UNSUPPORTED_FOR_V2"], [r["type"] for r in directional])
        dt = next(r for r in ups if r["type"] == "DOUBLE_TOP" and r["state"] == "CONFIRMED")
        self.assertEqual(dt["v2_confirm_level"], dt["boundary"]["neckline"])
        st = dt["v2_start_index"]
        close_st = datetime.fromisoformat(t[st]) + timedelta(minutes=5)
        self.assertEqual(_iso(close_st), dt["detected_at"])              # the bar at whose close the pattern became known
        last_anchor = max(a["index"] for a in dt["anchors"])
        self.assertEqual(st, last_anchor + 3)                            # not the pivot bar itself (no look-ahead)
        first = dt["v2_history"][0]
        self.assertGreater(first["bar_index"], st)
        self.assertEqual((first["to"], t[first["bar_index"]]), ("CONFIRMED", dt["confirm_bar"]))

    def test_invalidated_before_confirmation_stays_invalidated(self):
        b = _dt_base()
        bars = b + path_bars([102.2, 105.6, 105.2, 100.0, 99.0], steps=3, start=T0 + timedelta(minutes=5 * len(b)))
        ups, _ = self._up(bars)
        dt = next(r for r in ups if r["type"] == "DOUBLE_TOP" and r["boundary"]["neckline"] == 101.4)
        self.assertEqual(dt["v2_state"], "INVALIDATED")
        self.assertNotIn("CONFIRMED", [x["to"] for x in dt["v2_history"]])


# ---------------------------------------------------------------------------------------------------------- chunk_01#13
class TestSci2HeadShouldersFamily(unittest.TestCase):
    def test_bearish_hs_neckline_break_and_structural_level(self):
        import random

        from masterquo.analysis import sci2
        rnd = random.Random(5)
        px, rows = 100.0, []
        for _ in range(60):
            nx = px + rnd.gauss(0, 0.5)
            rows.append((px, max(px, nx) + 0.2, min(px, nx) - 0.2, nx))
            px = nx
        t, o, h, lo, c = _cols(bars_from_ohlc(rows))
        i = len(c) - 1
        for typ, d in (("HEAD_SHOULDERS", "SHORT"), ("INVERSE_HEAD_SHOULDERS", "LONG")):
            rec = {"pattern_id": "CH-x", "type": typ, "direction_if_confirmed": d, "boundary": {"neckline": 99.5, "slope": -0.01},
                   "invalidation": 101.0, "v2_confirm_level": 99.4, "v2_history": [{"bar_index": i, "from": "FORMING", "to": "CONFIRMED"}]}
            rd = sci2.read(t, o, h, lo, c, "M5", patterns=[rec])
            self.assertEqual((rd["role"], rd["role_direction"]), ("NECKLINE_BREAK", d), typ)
            self.assertEqual(rd["structural_level"], 99.4)


# ---------------------------------------------------------------------------------------------------------- chunk_01#8
class TestW1MN1Aggregation(unittest.TestCase):
    def _sunday(self):
        d = datetime(2026, 10, 1, tzinfo=UTC)
        return d + timedelta(days=(6 - d.weekday()) % 7)

    def test_sunday_d1_opens_the_next_week(self):
        from masterquo.analysis import levels as L
        sun = self._sunday()
        d1 = []
        for w in range(4):                                               # UTC+0 server: Sun..Fri D1 bars, the Sunday one marked
            for k in range(6):
                t = sun + timedelta(days=7 * w + k)
                hi = 2100.0 + w if k == 0 else 2000.0
                d1.append({"open_utc": _iso(t), "o": 1990.0, "h": hi, "l": 1980.0, "c": 1995.0 + w if k == 5 else 1990.0, "closed": True})
        agg = L.aggregate_d1(d1, "W1")
        self.assertEqual(len(agg["bars"]), 3)                            # the 4th week has no later D1 -> still incomplete
        for k, bar in enumerate(agg["bars"]):
            self.assertEqual(datetime.fromisoformat(bar["open_utc"]).weekday(), 6)
            self.assertEqual((bar["days"], bar["h"], bar["c"]), (6, 2100.0 + k, 1995.0 + k))   # never the next week's Sunday

    def test_forming_bar_of_next_period_completes_the_previous(self):
        from masterquo.analysis import levels as L
        sun = self._sunday()
        week = [{"open_utc": _iso(sun + timedelta(days=k)), "o": 1, "h": 2, "l": 0.5, "c": 1.5, "closed": True} for k in range(6)]
        forming = {"open_utc": _iso(sun + timedelta(days=7)), "o": 9, "h": 99, "l": 0.1, "c": 9, "closed": False}
        agg = L.aggregate_d1(week + [forming], "W1")
        self.assertEqual(len(agg["bars"]), 1)
        self.assertEqual((agg["bars"][0]["days"], agg["bars"][0]["h"]), (6, 2))     # the forming bar's data never enters
        self.assertNotEqual(agg["forming_period"], agg["bars"][0]["period_key"])
        self.assertEqual(L.aggregate_d1(week, "W1")["bars"], [])         # without it the week stays incomplete (as before)
        jan = [{"open_utc": _iso(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=k)), "o": 1, "h": 2, "l": 0.5, "c": 1.5, "closed": True}
               for k in range(31)]
        mn = L.aggregate_d1(jan + [{"open_utc": "2026-02-01T00:00:00Z", "o": 1, "h": 2, "l": 1, "c": 1, "closed": False}], "MN1")
        self.assertEqual([x["period_key"] for x in mn["bars"]], ["2026-01"])
        self.assertEqual(mn["forming_period"], "2026-02")


# ---------------------------------------------------------------------------------------------------------- chunk_01#6 / #14 / #17
GOOD_IV = {"observed_at": "2026-10-12T20:00:00Z", "available_at": "2026-10-12T20:15:00Z", "underlier": "GLD", "source": "GVZ",
           "sigma_annual": "16.4", "unit": "percent", "day_count_basis": "ACT_365", "tenor_days": "30", "quality": "OK"}


class TestIvImportValidation(unittest.TestCase):
    def test_bad_rows_are_rejected_with_a_reason_never_raised(self):
        from masterquo.analysis import iv_import as I
        rows = [dict(GOOD_IV),
                dict(GOOD_IV, source="A", tenor_days="30d"),
                dict(GOOD_IV, source="B", valid_until="2026-10-20"),
                dict(GOOD_IV, source="C", valid_until="not-a-time"),
                dict(GOOD_IV, source="D", valid_until="2026-10-12T20:10:00Z"),
                dict(GOOD_IV, source="E", tenor_days="-5"),
                dict(GOOD_IV, source="F", underlier=123),
                "not an object",
                dict(GOOD_IV, source="G", observed_at="2026-10-12T20:00:00"),
                dict(GOOD_IV, source="H", tenor_days=None, expiry={"x": 1})]
        ok, bad = I.validate(rows)
        self.assertEqual([r["source"] for r in ok], ["GVZ", "F"])
        self.assertEqual(ok[1]["underlier"], "123")
        self.assertEqual({b["row"]: b["reason"] for b in bad},
                         {2: "TENOR_NOT_A_NUMBER", 3: "VALID_UNTIL_WITHOUT_UTC_ZONE", 4: "BAD_VALID_UNTIL", 5: "VALID_UNTIL_BEFORE_AVAILABLE",
                          6: "TENOR_NOT_POSITIVE", 8: "ROW_NOT_OBJECT", 9: "TIME_WITHOUT_UTC_ZONE", 10: "BAD_EXPIRY"})

    def test_store_reports_instead_of_failing(self):
        from masterquo.analysis import iv_import as I
        from masterquo.db.database import Database
        td = TempData()
        try:
            db = Database()
            rows = I.parse_text(json.dumps([GOOD_IV, ["x"], dict(GOOD_IV, source="Z", tenor_days="30d")]), "json")
            rep = I.store(db, rows)
            self.assertEqual((rep["accepted"], len(rep["rejected"])), (1, 2))
            db.close()
        finally:
            td.close()

    def test_obs_id_of_a_valid_row_is_unchanged(self):
        import hashlib

        from masterquo.analysis import iv_import as I
        ok, _ = I.validate([dict(GOOD_IV)])
        key = ("GLD", "GVZ", "2026-10-12T20:00:00Z", "30")
        self.assertEqual(ok[0]["obs_id"], "IV-" + hashlib.sha256("|".join(key).encode()).hexdigest()[:14])

    def test_utf8_bom_csv(self):
        from masterquo.analysis import iv_import as I
        hdr = ",".join(GOOD_IV)
        text = "﻿# PRZYKŁAD z Excela\n" + hdr + "\n" + ",".join(GOOD_IV.values()) + "\n"
        ok, bad = I.validate(I.parse_text(text))
        self.assertEqual((len(ok), bad), (1, []))


# ---------------------------------------------------------------------------------------------------------- chunk_02#10 / #11 / #12
def _pair(k, cb, ca, pb, pa, **kw):
    return dict({"strike": k, "call_bid": cb, "call_ask": ca, "put_bid": pb, "put_ask": pa}, **kw)


class TestBlack76Validation(unittest.TestCase):
    def test_unknown_age_is_not_fresh(self):
        from masterquo.analytics import black76 as B
        pairs = [_pair(k, max(0, 100 - k) + 1.9, max(0, 100 - k) + 2.1, max(0, k - 100) + 1.9, max(0, k - 100) + 2.1) for k in (95, 100, 105)]
        r = B.forward_from_parity(pairs, 1.0)
        self.assertEqual(r["status"], "INSUFFICIENT_PAIRS")
        self.assertEqual({x[1] for x in r["rejected"]}, {"AGE_UNKNOWN"})
        for p in pairs:
            p["age_s"] = 5
        self.assertEqual(B.forward_from_parity(pairs, 1.0)["status"], "OK")

    def test_malformed_pairs_and_discount(self):
        from masterquo.analytics import black76 as B
        r = B.forward_from_parity([1, 2, 3], 1.0)
        self.assertEqual({x[1] for x in r["rejected"]}, {"PAIR_NOT_OBJECT"})
        r = B.forward_from_parity([{"call_bid": 1, "call_ask": 2, "put_bid": 1, "put_ask": 2, "age_s": 1}], 1.0)
        self.assertEqual(r["rejected"], [(None, "STRIKE_INVALID")])
        good = [_pair(100, 1.9, 2.1, 1.9, 2.1, age_s=1)] * 3
        for d in (-1.0, 0.0, float("nan"), float("inf")):
            with self.assertRaises(B.Black76Error):
                B.forward_from_parity(good, d)

    def test_empty_admissible_interval_is_flagged(self):
        from masterquo.analytics import black76 as B
        ok = [_pair(100, 1.9, 2.1, 1.9, 2.1, age_s=1), _pair(95, 6.9, 7.1, 1.9, 2.1, age_s=1), _pair(100, 1.9, 2.1, 1.9, 2.1, age_s=2)]
        self.assertEqual(B.forward_from_parity(ok, 1.0)["admissible_status"], "OK")
        bad = ok[:2] + [_pair(100, 4.9, 5.1, 1.9, 2.1, age_s=1)]          # F in [102.8, 103.2] vs [99.8, 100.2]
        r = B.forward_from_parity(bad, 1.0)
        self.assertGreater(r["admissible"][0], r["admissible"][1])
        self.assertEqual(r["admissible_status"], "EMPTY_INCONSISTENT_QUOTES")

    def test_overflow_is_an_error_not_nan(self):
        from masterquo.analytics import black76 as B
        with self.assertRaises(B.Black76Error):
            B.price(100, 100, 1e308, 4)
        x = B.price(100, 100, 50.0, 4)                                   # large but representable: finite numbers
        self.assertTrue(all(math.isfinite(v) for v in (x["call"], x["put"], x["d1"])))


# ---------------------------------------------------------------------------------------------------------- chunk_02#15
class TestContractCleanNumpy(unittest.TestCase):
    def test_numpy_nan_inf_scalars_become_none(self):
        import numpy as np
        from masterquo.analytics import contract
        out = contract.clean({"a": np.float64("nan"), "b": np.float32("inf"), "c": np.float64(1.5), "d": np.array([np.nan, 1.0]), "e": np.int64(3)})
        self.assertEqual(out, {"a": None, "b": None, "c": 1.5, "d": [None, 1.0], "e": 3})


# ---------------------------------------------------------------------------------------------------------- chunk_02#3 / #4 / #13 / #18
class TestPatternLibrary(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.analytics import double_bottom as DB
        from masterquo.analytics.library import PatternLibrary
        from masterquo.db.database import Database
        self.db = Database()
        self.lib = PatternLibrary(self.db, lambda: dict(DB.DEFAULT))

    def tearDown(self):
        self.db.close()
        self.td.close()

    def wait(self, job_id):
        for _ in range(200):
            j = self.lib.job(job_id)
            if j["status"] != "RUNNING":
                return j
            time.sleep(0.05)
        self.fail("job did not finish")

    def _legacy_bad_sample(self):
        """A sample stored before 1.46 (add_sample did not check open_utc): non-ISO times on a known TF."""
        bars = [dict(b, open_utc=f"x{k:04d}") for k, b in enumerate(F.double_bottom("up"))]
        self.db.execute("INSERT INTO pattern_samples(created_at, symbol, timeframe, start_utc, end_utc, bars, data_sha256, origin, note) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", ("2026-01-01T00:00:00Z", "XAUUSD-", "M5", bars[0]["open_utc"], bars[-1]["open_utc"],
                                                     json.dumps(bars), "legacy-sha", "TEST", ""))
        return self.db.one("SELECT id FROM pattern_samples WHERE data_sha256='legacy-sha'")["id"]

    def test_one_bad_sample_is_an_error_not_a_failed_job(self):
        bad_id = self._legacy_bad_sample()
        good = self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("up"), "TEST")
        j = self.wait(self.lib.start_job(None)["job_id"])
        self.assertEqual(j["status"], "COMPLETED", j.get("error"))
        self.assertEqual((j["processed"], j["counts"]["ERROR"], j["counts"]["CONFIRMED"]), (2, 1, 1))
        st = {r["sample_id"]: r["status"] for r in self.lib.results(j["job_id"])}
        self.assertEqual((st[bad_id], st[good["id"]]), ("ERROR", "CONFIRMED"))
        one = self.lib.validate_one(bad_id)                              # a single validation of it: an error result, no exception
        self.assertEqual(one["result"]["status"], "error")
        self.assertIn("BAD_OPEN_UTC", one["result"]["reason"])
        bars =[dict(b, open_utc=f"y{k:04d}") for k, b in enumerate(F.double_bottom("down"))]
        r = self.lib.add_sample("XAUUSD-", "M5", bars, "TEST")
        self.assertFalse(r["ok"])
        self.assertIn("BAD_OPEN_UTC", r["error"])

    def test_readding_a_deleted_sample_restores_it(self):
        a = self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("up"), "TEST")
        self.assertTrue(self.lib.delete(a["id"]))
        r = self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("up"), "TEST")
        self.assertEqual((r["ok"], r["id"], r.get("restored"), r["duplicate"]), (True, a["id"], True, False))
        self.assertIsNotNone(self.lib.get(a["id"]))
        self.assertEqual([x["id"] for x in self.lib.list()], [a["id"]])
        self.assertTrue(self.lib.delete(a["id"]))
        imp = self.lib.import_samples({"schema": "mq-pattern-library-1", "samples": [{"symbol": "XAUUSD-", "timeframe": "M5", "bars": F.double_bottom("up")}]})
        self.assertEqual((imp["added"], imp["duplicates_kept_existing"]), (1, 0))
        self.assertIsNotNone(self.lib.get(a["id"]))

    def test_delete_reports_the_real_outcome(self):
        a = self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("up"), "TEST")
        self.assertTrue(self.lib.delete(a["id"]))
        self.assertFalse(self.lib.delete(a["id"]))                     # already deleted
        self.assertFalse(self.lib.delete(9999))                          # never existed

    def test_resume_only_once_and_own_cancel_handle(self):
        a = self.lib.add_sample("XAUUSD-", "M5", F.double_bottom("up"), "TEST")
        j = self.wait(self.lib.start_job([a["id"]])["job_id"])
        jid = j["job_id"]
        self.db.execute("UPDATE pattern_jobs SET status='RUNNING' WHERE job_id=?", (jid,))     # another resume already won
        real_one = self.db.one

        def stale(sql, args=()):
            r = real_one(sql, args)
            if sql.startswith("SELECT status, manifest FROM pattern_jobs") and r:
                r = dict(r, status="INTERRUPTED")                        # read before the other resume's UPDATE
            return r
        spawned = []
        with mock.patch.object(self.db, "one", side_effect=stale), mock.patch.object(self.lib, "_spawn", side_effect=spawned.append):
            r = self.lib.resume(jid)
        self.assertFalse(r["ok"])
        self.assertEqual(spawned, [])
        # a finishing (older) run never removes the cancel handle of the run that replaced it
        newer = threading.Event()
        self.lib._jobs[jid] = {"cancel": newer}
        self.lib._run(jid, threading.Event())
        self.assertIs(self.lib._jobs.get(jid, {}).get("cancel"), newer)
        self.assertTrue(self.lib.cancel(jid))


# ---------------------------------------------------------------------------------------------------------- chunk_02#5 / #6 / #7
def _model1(n_t=4, prices=(100.0, 101.0, 102.0, 103.0)):
    times = [1_760_000_000 + 300 * i for i in range(n_t)]
    return {"y_axis": list(prices), "liquidation_leverage_data": [[i, j, float(1 + i + 10 * j)] for i in range(n_t) for j in range(len(prices))],
            "price_candlesticks": [[t, 1, 1, 1, 1, 1] for t in times]}


class TestLiquidityService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        self.cs = ConfigStore()
        self.cs.update({"liquidity": {"sources": {"BTC": {"enabled": True, "source_symbol": "BTC", "variant": "AGGREGATED", "range": "24h"}}}})
        self.db = Database()

    def tearDown(self):
        self.db.close()
        self.td.close()

    def svc(self, fetcher=None):
        from masterquo.analytics.liquidation.service import LiquidityService
        return LiquidityService(self.cs, self.db, None, None, secrets=type("S", (), {"get": lambda s, n: "k", "source": lambda s, n: "LOCAL_STORE"})(),
                                fetcher=fetcher)

    def test_any_poll_failure_backs_off(self):
        for exc, code in ((ConnectionResetError("reset"), "NETWORK_ERROR"), (AttributeError("'list' object has no attribute 'get'"), "UNEXPECTED_ERROR")):
            self.db.execute("DELETE FROM liq_source_status")
            calls = []

            def boom(*a, exc=exc, calls=calls):
                calls.append(1)
                raise exc
            s = self.svc(fetcher=boom)
            self.assertEqual(len(s.poll_once(0.0)), 1)
            self.assertEqual(s.poll_once(1.0), [])                       # backoff: no request every 5 s
            self.assertEqual(len(calls), 1)
            self.assertEqual(self.db.one("SELECT status FROM liq_source_status")["status"], code)

    def test_inbox_runs_even_when_the_poll_raises(self):
        s = self.svc()
        seen = []

        def poll():
            s._stop.set()
            raise RuntimeError("poll broke")
        s.poll_once = poll
        s.scan_inbox = lambda: seen.append(1) or []
        s._loop()
        self.assertEqual(seen, [1])

    def test_poisoned_inbox_file_never_blocks(self):
        s = self.svc()
        good = {"schema": "pmw-liq-export-1", "target_asset": "BTC", "variant": "AGGREGATED", "source_symbol": "BTC", "range": "24h", "data": _model1()}
        (s.inbox() / "a_bad.json").write_text("[]")
        (s.inbox() / "b_bad.json").write_text(json.dumps(dict(good, target_asset={"x": 1})))
        (s.inbox() / "c_good.json").write_text(json.dumps(good))
        res = {r.get("file"): r["status"] for r in s.scan_inbox()}
        self.assertEqual((res["a_bad.json"], res["b_bad.json"]), ("REJECTED", "REJECTED"))
        self.assertIn("OK", res.values())
        left = sorted(p.name for p in s.inbox().iterdir())
        self.assertEqual(left, ["a_bad.rejected", "b_bad.rejected", "c_good.done"])

    def test_as_of_is_a_point_in_time(self):
        s = self.svc()
        src = self.cs.get().liquidity.sources["BTC"]
        a = s.ingest("BTC", src, _model1(), origin="API", received_at="2026-11-23T11:30:00.123456Z")
        b = s.ingest("BTC", src, _model1(n_t=5), origin="API", received_at="2026-11-23T12:00:00.500000Z")
        self.assertIsNone(s.as_of("BTC", "2026-11-23T12:00:00+02:00"))               # = 10:00Z, both received later
        self.assertEqual(s.as_of("BTC", "2026-11-23T13:45:00+02:00")["snapshot_id"], a["snapshot_id"])   # 11:45Z
        self.assertEqual(s.as_of("BTC", "2026-11-23T12:00:00.400000Z")["snapshot_id"], a["snapshot_id"])
        self.assertEqual(s.as_of("BTC", "2026-11-23T12:00:00.600000Z")["snapshot_id"], b["snapshot_id"])
        self.assertEqual(s.as_of("BTC", "2026-11-23T12:00:00.500000Z")["snapshot_id"], b["snapshot_id"])  # <= D
        self.assertEqual(s.heatmap_public("BTC", "2026-11-23")["status"], "INVALID_AS_OF")               # no zone: rejected
        self.assertEqual(s.heatmap_public("BTC", None, 0)["snapshot_id"], b["snapshot_id"])


# ---------------------------------------------------------------------------------------------------------- chunk_02#17
class TestLiquidityCli(unittest.TestCase):
    def test_sessions_as_of_is_the_close_of_the_last_bar(self):
        from masterquo.analytics import liquidity_cli as cli
        m1 = [{"open_utc": "2026-11-23T10:00:00Z"}, {"open_utc": "2026-11-23T10:01:00Z"}]
        self.assertEqual(cli.sessions_as_of(m1), datetime(2026, 11, 23, 10, 2, tzinfo=UTC).timestamp())
        self.assertIsNone(cli.sessions_as_of([]))

    def test_unknown_profile_is_rejected_by_argparse(self):
        from masterquo.analytics import liquidity_cli as cli
        td = TempData()
        try:
            with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                cli.main(["sessions", "--profile", "NO_SUCH_PROFILE"])
        finally:
            td.close()


# ---------------------------------------------------------------------------------------------------------- chunk_02#16
class TestLiquidityEvalCoverage(unittest.TestCase):
    def test_coverage_is_counted_per_variant(self):
        from masterquo.analytics import liquidity_eval as le
        plans = [{"decision_ts": 1_767_607_200.0, "direction": "BUY", "ref_close_bid": 100.0, "range": {"atr_m5": 1.0}}]
        data = {"data_kind": "SYNTHETIC_TEST", "m1": [], "rows": [{"signal_time": "2026-01-05T10:00:00Z", "label_end": "2026-01-05T10:10:00Z"}],
                "dataset_id": "t", "profile_hash": "h", "costs": {}, "prof": {}, "tick": 0.01, "replay_costs": {}}

        def run(m1, prof, tick, costs, accept=None):
            for p in plans:
                if accept is not None:
                    accept(p)
            return {"cycles": [], "blocked": []}

        src = type("Src", (), {"mapping": "VALIDATED_BASIS", "source_symbol": "XAUT"})()

        class Liq:
            cfg = type("Cfg", (), {"sources": {"XAUUSD": src}})()

            @staticmethod
            def as_of(inst, D):
                return {"zones": {"zones": []}}                          # a map existed before the decision
        with mock.patch("masterquo.ml.scalp_task.build_dataset", return_value=data), mock.patch("masterquo.scalp.replay.run", side_effect=run):
            rep = le.evaluate("XAUUSD", Path("."), liquidity=Liq(), log=lambda *a: None)
        v = rep["variants"]
        self.assertEqual(v["B2"]["heatmap_coverage_decisions"], 1)
        # B3 = B1 and B2: B1 never passes here, so no heatmap was consulted in B3 at all
        self.assertEqual(v["B3"]["heatmap_coverage_decisions"], 0)
        self.assertEqual(v["B3"]["status"], "BLOCKED_NO_POINT_IN_TIME_HISTORY")


if __name__ == "__main__":
    unittest.main()
