"""1.46 audit, group D_mq_lab_4: lab/zones.py (MQ-LAB-ZONES-2.0.0) - validation of manual edits, manual zone ids, lifecycle start
of manual zones, HISTORY_GAP without a checkpoint, score refresh, lazy restore before the first snapshot write, snapshot lock,
no-op saves, broken_at on manual state changes, atomic revision checks, bounded event list. Synthetic bars only (TEST_ONLY)."""
from __future__ import annotations

import json
import shutil
import threading
import unittest
from collections import Counter
from datetime import UTC, datetime, timedelta

import _env
from _env import TempData

T0 = datetime(2026, 3, 2, tzinfo=UTC)


def bars(prices, start=T0, minutes=15):
    return [{"open_utc": (start + timedelta(minutes=minutes * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": p, "h": p + 0.5, "l": p - 0.5, "c": p}
            for i, p in enumerate(prices)]


def t(i, minutes=15):
    return (T0 + timedelta(minutes=minutes * i)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.db.database import Database
        from masterquo.lab.zones import ZoneStore
        self.db = Database()
        self.root = _env.Path(self.td.dir) / "z"
        self.st = ZoneStore(self.db, self.root)

    def tearDown(self):
        self.td.close()

    def auto(self, **kw):
        z = {"zone_id": "SDZ-XAUUSD-M15-D-T", "asset": "XAUUSD", "tf": "M15", "kind": "DEMAND", "top": 100.0, "bottom": 99.0,
             "origin_time": t(0), "confirmed_at": t(1), "source": "AUTO", "quality": "AUTO_RULE", "exit_strength_atr": 2.0, "base_len": 1}
        z.update(kw)
        return z

    def row(self, zid):
        return next(z for z in self.st.list_asof("XAUUSD", include_archived=True) if z["zone_id"] == zid)


# ------------------------------------------------------------------------------------------------ chunk_16#0
class PatchCoercesLevels(_Base):
    def test_patch_text_levels_are_numbers_or_refused(self):
        self.st.save("XAUUSD", [self.auto()])
        zid = "SDZ-XAUUSD-M15-D-T"
        r = self.st.patch(zid, 1, top="101")                                # was TypeError ('>' between str and float) -> 500
        self.assertEqual((r["top"], r["revision"]), (101.0, 2))
        self.assertEqual(self.db.one("SELECT typeof(top) AS t FROM lab_zones WHERE zone_id=?", (zid,))["t"], "real")
        with self.assertRaises(ValueError):
            self.st.patch(zid, 2, top="b", bottom="a")                      # was stored as TEXT (lexicographic 'b' > 'a')
        with self.assertRaises(ValueError):
            self.st.patch(zid, 2, top="99.5", bottom="100")                 # was an inverted zone ('99.5' > '100' as text)
        for bad in (float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                self.st.patch(zid, 2, top=bad)
        r = self.st.patch(zid, 2, top="100", bottom="99")                   # a valid pair was refused as ZERO_HEIGHT_ZONE
        self.assertEqual((r["top"], r["bottom"], r["revision"]), (100.0, 99.0, 3))

    def test_process_survives_a_legacy_text_level_row(self):
        self.st.save("XAUUSD", [self.auto(), self.auto(zone_id="SDZ-XAUUSD-M15-D-BAD")])
        self.db.execute("UPDATE lab_zones SET top='b', bottom='a' WHERE zone_id='SDZ-XAUUSD-M15-D-BAD'")   # 1.45 PATCH left TEXT here
        b = bars([105, 104, 99.8, 103])
        self.st.process("XAUUSD", "M15", b)                                 # was TypeError -> whole transaction (and lab tick) lost
        good = self.row("SDZ-XAUUSD-M15-D-T")
        self.assertEqual((good["state"], good["touch_count"]), ("TESTED", 1))
        bad = self.row("SDZ-XAUUSD-M15-D-BAD")
        self.assertIn("INVALID_LEVELS", bad["flags"])
        self.assertEqual(bad["state"], "FRESH")
        self.assertEqual(self.db.one("SELECT last_bar FROM lab_zone_checkpoints WHERE asset='XAUUSD' AND tf='M15'")["last_bar"], b[-1]["open_utc"])
        r = self.st.patch("SDZ-XAUUSD-M15-D-BAD", 1, top=100.0, bottom=99.0, reason="fix")      # repaired by a manual edit
        self.assertEqual(r["revision"], 2)
        self.assertNotIn("INVALID_LEVELS", self.row("SDZ-XAUUSD-M15-D-BAD")["flags"])


# ------------------------------------------------------------------------------------------------ chunk_16#1
class AddManualValidation(_Base):
    def test_non_finite_levels_unknown_tf_and_bad_time_refused(self):
        for top, bottom in ((float("inf"), 99.0), (100.0, float("-inf")), (float("nan"), 99.0), (json.loads("1e999"), 99.0)):
            with self.assertRaises(ValueError):
                self.st.add_manual("XAUUSD", "M15", "DEMAND", top, bottom, t(0))
        with self.assertRaises(ValueError):
            self.st.add_manual("XAUUSD", "M5", "DEMAND", 100.0, 99.0, t(0))           # never processed by LabService -> FRESH forever
        for bad_t in ("garbage", "1960-01-01T00:00:00Z", None):
            with self.assertRaises(ValueError):
                self.st.add_manual("XAUUSD", "M15", "DEMAND", 100.0, 99.0, bad_t)
        self.assertEqual(self.st.list_asof("XAUUSD"), [])
        json.dumps(self.st.list_asof("XAUUSD"), allow_nan=False)

    def test_origin_time_is_normalised(self):
        z = self.st.add_manual("XAUUSD", "M15", "DEMAND", 100.0, 99.0, "2026-03-02 00:15:00")
        self.assertEqual(z["origin_time"], "2026-03-02T00:15:00Z")
        self.assertEqual(self.row(z["zone_id"])["origin_time"], "2026-03-02T00:15:00Z")
        z2 = self.st.add_manual("XAUUSD", "H1", "SUPPLY", 110.0, 109.0, "2026-03-02T02:00:00+00:00")
        self.assertEqual(z2["zone_id"], "SDZ-XAUUSD-H1-M-2026-03-02T02:00:00Z")      # first manual zone keeps the legacy id format


# ------------------------------------------------------------------------------------------------ chunk_16#2
class AddManualNeverFakesSuccess(_Base):
    def test_second_zone_on_the_same_base_and_re_add_after_delete(self):
        a = self.st.add_manual("XAUUSD", "M15", "DEMAND", 100.0, 99.0, t(0))
        b = self.st.add_manual("XAUUSD", "M15", "SUPPLY", 120.0, 119.0, t(0))      # was silently dropped (same id) but returned
        self.assertNotEqual(a["zone_id"], b["zone_id"])
        rb = self.row(b["zone_id"])
        self.assertEqual((rb["kind"], rb["top"], rb["bottom"]), ("SUPPLY", 120.0, 119.0))
        self.assertEqual(len(self.st.list_asof("XAUUSD")), 2)
        self.st.delete(a["zone_id"], 1)
        c = self.st.add_manual("XAUUSD", "M15", "DEMAND", 105.0, 104.0, t(0))      # tombstoned id -> was never created
        rc = self.row(c["zone_id"])
        self.assertEqual((rc["top"], rc["bottom"]), (105.0, 104.0))
        self.assertNotIn(a["zone_id"], [z["zone_id"] for z in self.st.list_asof("XAUUSD")])   # the tombstone stays a tombstone

    def test_exact_duplicate_is_refused_not_reported_as_saved(self):
        self.st.add_manual("XAUUSD", "M15", "DEMAND", 100.0, 99.0, t(0))
        with self.assertRaises(ValueError) as cm:
            self.st.add_manual("XAUUSD", "M15", "DEMAND", 100.0, 99.0, t(0))
        self.assertIn("ZONE_EXISTS", str(cm.exception))
        self.assertEqual(len(self.st.list_asof("XAUUSD")), 1)


# ------------------------------------------------------------------------------------------------ chunk_16#3
class ManualZoneLifecycleStart(_Base):
    def test_departure_from_the_base_is_not_a_test(self):
        # base 99.5 (inside 99..100), departure 99.7 (still inside), exit 102 / 104, real return 99.8, exit 103
        b = bars([99.5, 99.7, 102, 104, 99.8, 103])
        z = self.st.add_manual("XAUUSD", "M15", "DEMAND", 100.0, 99.0, b[0]["open_utc"])
        self.st.process("XAUUSD", "M15", b)
        r = self.row(z["zone_id"])
        self.assertEqual((r["state"], r["touch_count"]), ("TESTED", 1))
        self.assertEqual([h["t"] for h in r["history"] if h["event"] == "TOUCH"], [b[4]["open_utc"]])
        self.assertNotIn("HISTORY_GAP", r["flags"])

    def test_untouched_after_departure_stays_fresh(self):
        b = bars([99.5, 99.7, 102, 104, 105])
        z = self.st.add_manual("XAUUSD", "M15", "DEMAND", 100.0, 99.0, b[0]["open_utc"])
        self.st.process("XAUUSD", "M15", b)
        r = self.row(z["zone_id"])
        self.assertEqual((r["state"], r["touch_count"]), ("FRESH", 0))

    def test_origin_before_the_window_flags_history_gap(self):
        b = bars([105, 104, 99.8, 103], start=T0 + timedelta(days=3))
        z = self.st.add_manual("XAUUSD", "M15", "DEMAND", 100.0, 99.0, t(0))    # base 3 days before the first bar of the window
        self.st.save("XAUUSD", [self.auto(zone_id="SDZ-XAUUSD-M15-D-OLD")])        # AUTO zone without checkpoint, displacement before window
        self.st.process("XAUUSD", "M15", b)
        self.assertIn("HISTORY_GAP", self.row(z["zone_id"])["flags"])
        self.assertIn("HISTORY_GAP", self.row("SDZ-XAUUSD-M15-D-OLD")["flags"])

    def test_auto_zone_in_window_has_no_gap(self):
        self.st.save("XAUUSD", [self.auto()])
        self.st.process("XAUUSD", "M15", bars([105, 104, 99.8, 103]))
        self.assertNotIn("HISTORY_GAP", self.row("SDZ-XAUUSD-M15-D-T")["flags"])


# ------------------------------------------------------------------------------------------------ chunk_16#4
class ScoreFollowsLifecycle(_Base):
    def test_tests_and_age_refreshed_by_process(self):
        self.st.save("XAUUSD", [self.auto()])
        self.assertEqual(self.row("SDZ-XAUUSD-M15-D-T")["score"]["rating"], "B")
        b = bars([105, 104, 99.8, 99.6, 99.9, 103, 104, 99.7, 103])           # two test episodes
        self.st.process("XAUUSD", "M15", b)
        r = self.row("SDZ-XAUUSD-M15-D-T")
        self.assertEqual(r["touch_count"], 2)
        self.assertEqual(r["score"]["components"]["tests"], 2)                  # was 0 forever
        self.assertEqual(r["score"]["components"]["age_bars"], 8)              # closed bars since confirmed_at (00:15 .. 02:00)
        self.assertEqual(r["score"]["rating"], "C")
        self.assertEqual(r["score"]["components"]["exit_strength_atr"], 2.0)    # detector components kept
        self.st.process("XAUUSD", "M15", b + bars([105], start=T0 + timedelta(minutes=15 * 9)))
        self.assertEqual(self.row("SDZ-XAUUSD-M15-D-T")["score"]["components"]["age_bars"], 9)

    def test_manual_zone_stays_baseline(self):
        b = bars([99.5, 102, 99.8, 103])
        z = self.st.add_manual("XAUUSD", "M15", "DEMAND", 100.0, 99.0, b[0]["open_utc"])
        self.st.process("XAUUSD", "M15", b)
        self.assertEqual(self.row(z["zone_id"])["score"]["rating"], "MANUAL_BASELINE")


# ------------------------------------------------------------------------------------------------ chunk_16#5
class RestoreBeforeFirstWrite(_Base):
    def test_write_before_restore_keeps_the_recovery_point(self):
        from masterquo.lab.zones import ZoneStore
        a = self.st.add_manual("XAUUSD", "H1", "DEMAND", 100.0, 99.0, "2026-03-01T00:00:00Z")
        b = self.st.add_manual("XAUUSD", "H1", "SUPPLY", 120.0, 119.0, "2026-03-01T01:00:00Z")
        self.db.execute("DELETE FROM lab_zones")                               # DB loss
        st2 = ZoneStore(self.db, self.root)                                    # new process, the API writes before LabService restores
        st2.add_manual("XAUUSD", "H1", "DEMAND", 90.0, 89.0, "2026-03-05T00:00:00Z")
        st2.add_manual("XAUUSD", "H1", "DEMAND", 80.0, 79.0, "2026-03-05T01:00:00Z")
        st2.restore("XAUUSD")
        ids = {z["zone_id"] for z in st2.list_asof("XAUUSD")}
        self.assertTrue({a["zone_id"], b["zone_id"]} <= ids, ids)
        self.assertEqual(len(ids), 4)


# ------------------------------------------------------------------------------------------------ chunk_16#6
class SnapshotWritesSerialised(_Base):
    def test_parallel_writers_never_degrade(self):
        self.st.save("XAUUSD", [self.auto(zone_id=f"Z{i:03d}") for i in range(150)])
        res = Counter()

        def writer():
            for _ in range(120):
                res[self.st.write_snapshot("XAUUSD")] += 1

        th = [threading.Thread(target=writer) for _ in range(3)]
        for x in th:
            x.start()
        for x in th:
            x.join()
        self.assertEqual(res, Counter({"OK": 360}))
        self.assertTrue(self.st._valid(self.root / "zones_XAUUSD.json"))


# ------------------------------------------------------------------------------------------------ chunk_16#7
class ManualStateKeepsBrokenAt(_Base):
    def test_revive_clears_and_manual_break_sets_the_right_edge(self):
        self.st.save("XAUUSD", [self.auto()])
        self.st.process("XAUUSD", "M15", bars([105, 104, 98.0]))
        r = self.row("SDZ-XAUUSD-M15-D-T")
        self.assertEqual((r["state"], r["right_edge"]), ("BROKEN", t(2)))
        self.st.patch(r["zone_id"], r["revision"], state="FRESH", reason="revive")
        r = self.row("SDZ-XAUUSD-M15-D-T")
        self.assertTrue(r["active"])
        self.assertIsNone(r["right_edge"])                                     # was the old break date on an active zone
        self.st.patch(r["zone_id"], r["revision"], state="BROKEN", reason="manual break")
        r = self.row("SDZ-XAUUSD-M15-D-T")
        self.assertIsNotNone(r["right_edge"])                                  # was None -> drawn to infinity
        self.assertEqual(r["history"][-1]["event"], "BROKEN")
        m = self.st.add_manual("XAUUSD", "M15", "SUPPLY", 120.0, 119.0, t(5))  # never processed: wall-clock right edge
        self.st.patch(m["zone_id"], 1, state="BROKEN")
        self.assertIsNotNone(self.row(m["zone_id"])["right_edge"])


# ------------------------------------------------------------------------------------------------ chunk_16#9
class NoOpSaveDoesNotRewriteSnapshot(_Base):
    def test_unchanged_store_is_not_rewritten(self):
        calls = []
        orig = self.st.write_snapshot
        self.st.write_snapshot = lambda asset: (calls.append(asset), orig(asset))[1]
        z = self.auto()
        self.st.save("XAUUSD", [z])
        self.st.save("XAUUSD", [z])                                             # completes the main/.bak pair
        self.assertTrue((self.root / "zones_XAUUSD.json.bak").exists())
        n = len(calls)
        for _ in range(5):
            r = self.st.save("XAUUSD", [z])
            self.assertEqual((r["saved"], r["stored"], r["snapshot"]), (0, 1, "OK"))
        self.assertEqual(len(calls), n)                                         # was one full rewrite (+fsync) per save
        self.st.process("XAUUSD", "M15", bars([105, 104, 99.8]))                # lifecycle changed -> next save writes it
        self.st.save("XAUUSD", [])
        self.assertEqual(len(calls), n + 1)
        snap = json.loads((self.root / "zones_XAUUSD.json").read_text(encoding="utf-8"))["body"]["zones"]
        self.assertEqual(snap[0]["touch_count"], 1)
        self.st.save("XAUUSD", [])
        self.assertEqual(len(calls), n + 1)
        (self.root / "zones_XAUUSD.json").unlink()                              # a missing main snapshot is rewritten
        self.st.save("XAUUSD", [])
        self.assertEqual(len(calls), n + 2)
        self.assertTrue(self.st._valid(self.root / "zones_XAUUSD.json"))


# ------------------------------------------------------------------------------------------------ chunk_16#8
class _TxHook:
    """Runs `fn` once, right before the first write transaction of the next store call (a concurrent writer in that window)."""

    def __init__(self, db, fn):
        self.db, self.fn, self.fired, self.orig = db, fn, False, db.tx
        db.tx = self.tx

    def tx(self):
        if not self.fired:
            self.fired = True
            self.fn()
        return self.orig()


class RevisionChecksAreAtomic(_Base):
    def test_delete_of_an_unseen_revision_is_a_conflict(self):
        self.st.save("XAUUSD", [self.auto()])
        zid = "SDZ-XAUUSD-M15-D-T"
        _TxHook(self.db, lambda: self.st.patch(zid, 1, top=101.0, reason="other client"))
        with self.assertRaises(ValueError):
            self.st.delete(zid, 1)                                              # was deleted although revision 2 was never seen
        self.assertEqual(self.row(zid)["revision"], 2)

    def test_patch_keeps_history_written_by_process_meanwhile(self):
        self.st.save("XAUUSD", [self.auto()])
        zid = "SDZ-XAUUSD-M15-D-T"
        _TxHook(self.db, lambda: self.st.process("XAUUSD", "M15", bars([105, 104, 99.8])))
        self.st.patch(zid, 1, blacklist=True, reason="edit")
        ev = [h["event"] for h in self.row(zid)["history"]]
        self.assertIn("TOUCH", ev)                                              # was overwritten by the stale history of the patch
        self.assertEqual(ev[-1], "EDIT")


# ------------------------------------------------------------------------------------------------ chunk_16#10
class EventsBounded(_Base):
    def test_permanent_snapshot_failure_does_not_grow_events(self):
        shutil.rmtree(self.root)
        self.root.write_text("not a directory", encoding="utf-8")              # every snapshot write fails
        for _ in range(300):
            self.assertTrue(self.st.write_snapshot("XAUUSD").startswith("DEGRADED_SNAPSHOT"))
        self.assertLessEqual(len(self.st.events), 200)
        self.assertEqual(self.st.events[-1]["event"], "DEGRADED_SNAPSHOT")


if __name__ == "__main__":
    unittest.main()
