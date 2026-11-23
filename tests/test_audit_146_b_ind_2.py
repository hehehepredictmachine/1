"""1.46 audit, group B_ind_2 - PMW-SVP-1 (svp/engine.py, svp/service.py, svp/zones.py). Analytical only - no order path.

* one SQLite connection read from the svp thread, the engine thread and the API pool without the lock (focus_X3#0);
* naive ISO timestamps interpreted in the machine's local zone (chunk_35#16);
* one failing LIVE profile stopped the recomputation of all others (chunk_35#13);
* profile fields stored without validation -> StopIteration / 500 later (chunk_35#14);
* snapshot / zone ids shared by profiles with the same geometry (chunk_35#15);
* zones(as_of) showed zones deleted / replaced before as_of (chunk_35#18);
* profile_events counted the forming candle (chunk_35#17);
* coverage 0.0 for an undefined ratio (chunk_35#25), synchronous compute inside ai_propose (chunk_35#22),
  an invented tick 0.01 (chunk_35#23), POC_MIGRATION never produced (chunk_35#24).
"""
import asyncio
import collections
import json
import math
import sqlite3
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

T0 = datetime(2026, 3, 2, 0, 0, tzinfo=UTC).timestamp()        # Monday 00:00 UTC


def iso(t):
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def mk_bars(n, t0=T0, tf_s=300, f=lambda i: 2000 + math.sin(i / 6), tv=lambda i: 10 + i % 5):
    return [{"open_utc": iso(t0 + i * tf_s), "o": f(i), "h": f(i) + 0.7, "l": f(i) - 0.7, "c": f(i), "tv": tv(i), "rv": 0, "closed": True}
            for i in range(n)]


class _Bridge:
    def __init__(self, bars, info=None):
        self._bars = bars
        self.symbol_info = {"trade_tick_size": 0.01, "digits": 2} if info is None else info
        self.account_key = "srv:1"
        self.sent = []

    def symbol_bars(self, symbol, tf, n):
        return self._bars[-n:]

    def bars(self, tf, include_forming=False, limit=None):
        return self._bars

    def order_send(self, *a, **k):          # never called by SVP
        self.sent.append(a)


class _Agent:
    def __init__(self):
        self.loop = None

    def status(self):
        return {"state": "IDLE", "model": "m"}

    async def propose_zones(self, payload):
        return {"ok": True, "proposals": [], "cost_usd_estimate": 0.0}


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        self.cfg = ConfigStore()
        self.now = T0 + 100 * 300
        self.bars = mk_bars(100)
        self.bridge = _Bridge(self.bars)

    def tearDown(self):
        self.td.close()

    def svc(self, agent=None, bridge=None, sub="svp"):
        from masterquo.svp.service import SVPService
        s = SVPService(self.cfg, bridge or self.bridge, agent=agent, data_dir=Path(self.td.dir) / sub, clock=lambda: self.now)
        self.addCleanup(s.db.close)
        return s


class TestSVPConcurrentReads(_Base):
    """focus_X3#0: reads of the shared connection ran without the lock - with the same SQL text running in two threads Python's sqlite3
    returned InterfaceError / IndexError / UTF-8 errors or silently shortened lists."""

    def test_parallel_profiles_and_snapshots_are_complete_and_without_errors(self):
        s = self.svc()
        pids = []
        for i in range(30):
            pids.append(s.create_profile({"name": f"P{i}", "mode": "SESSION"})["profile_id"])
            self.now += 1
        with s._lock:
            for i, pid in enumerate(pids):
                s.db.execute("INSERT INTO svp_snapshots(snapshot_id, profile_id, created_at, frozen, payload) VALUES (?,?,?,0,?)",
                             (f"S{i}", pid, float(i), json.dumps({"snapshot_id": f"S{i}", "bins": list(range(200))})))
        errs: collections.Counter = collections.Counter()
        ok: collections.Counter = collections.Counter()
        stop = threading.Event()

        def api_like():                     # GET /api/v1/svp/profiles from the API thread pool
            while not stop.is_set():
                try:
                    n = len(s.profiles())
                    if n != 30:
                        errs[f"profiles returned {n} rows"] += 1
                        stop.set()
                    ok["api"] += 1
                except Exception as exc:  # noqa: BLE001
                    errs[f"profiles {type(exc).__name__}: {str(exc)[:60]}"] += 1
                    stop.set()

        def loop_like():                    # svp thread (live_tick) / engine thread (_svp_view)
            while not stop.is_set():
                try:
                    for p in pids[:5]:
                        sn = s.latest_snapshot(p)
                        if not sn or len(sn["bins"]) != 200:
                            errs["latest_snapshot incomplete"] += 1
                            stop.set()
                    n = len(s.profiles())
                    if n != 30:
                        errs[f"loop profiles returned {n} rows"] += 1
                        stop.set()
                    s.zones()
                    ok["loop"] += 1
                except Exception as exc:  # noqa: BLE001
                    errs[f"loop {type(exc).__name__}: {str(exc)[:60]}"] += 1
                    stop.set()

        ths = [threading.Thread(target=api_like), threading.Thread(target=api_like), threading.Thread(target=loop_like)]
        for t in ths:
            t.start()
        stop.wait(3.0)
        stop.set()
        for t in ths:
            t.join(10)
        self.assertEqual(dict(errs), {})
        self.assertGreater(ok["api"] + ok["loop"], 10)


class TestSVPNaiveTimestamps(_Base):
    """chunk_35#16: a timestamp without a zone was read in the machine's local zone (project rule: NAIVE_TIMESTAMP is rejected)."""

    def test_ts_rejects_naive_and_keeps_aware_and_epoch(self):
        from masterquo.svp import engine as EN
        from masterquo.svp import zones as ZN
        ref = datetime(2026, 11, 23, 8, 0, tzinfo=UTC).timestamp()
        for f in (EN._ts, ZN._ts):
            with self.assertRaises(ValueError):
                f("2026-11-23T08:00:00")
            self.assertEqual(f("2026-11-23T08:00:00Z"), ref)
            self.assertEqual(f("2026-11-23T09:00:00+01:00"), ref)
            self.assertEqual(f(ref), ref)                                       # numbers = epoch seconds UTC

    def test_naive_profile_bounds_and_ai_valid_until_rejected(self):
        s = self.svc()
        with self.assertRaises(ValueError):                                     # API: 400 instead of a silently shifted window
            s.create_profile({"mode": "RANGE", "t0": "2026-03-02T00:00:00", "t1": iso(T0 + 90 * 300)})
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 90 * 300), "bin_ticks": 20})
        with self.assertRaises(ValueError):
            s.update_profile(p["profile_id"], {"t1": "2026-03-02T07:00:00"})
        snap = dict(s.compute(p["profile_id"]), profile_id=p["profile_id"])
        from masterquo.svp import zones as ZN
        prop = {"profile_id": p["profile_id"], "snapshot_id": snap["snapshot_id"], "lower": snap["val"], "upper": snap["poc"], "type": "VALUE_AREA",
                "justification": "VA", "confirmation": "c", "invalidation": "i",
                "valid_until": datetime.fromtimestamp(self.now + 3600, UTC).replace(tzinfo=None).isoformat()}
        ok, why, _ = ZN.validate_ai(prop, snap, symbol="XAUUSD-", now=self.now)
        self.assertFalse(ok)
        self.assertIn("czas", why)


class TestSVPLiveTickIsolation(_Base):
    """chunk_35#13: the first failing LIVE profile (e.g. NO_ACTIVE_SESSION between sessions) aborted the whole tick, every bar."""

    def test_failing_profile_does_not_block_the_others(self):
        self.now = T0 + 19 * 3600                                               # 19:00 UTC Monday: no LAB_XAU_REFERENCE_V1 session active
        self.bars[:] = mk_bars(19 * 12)
        self.bridge = _Bridge(self.bars)
        s = self.svc()
        a = s.create_profile({"mode": "LIVE", "tf": "M5", "name": "A live"})
        self.now += 1
        b = s.create_profile({"mode": "RANGE", "tf": "M5", "t0": iso(T0 + 10 * 3600), "t1": iso(T0 + 18 * 3600), "bin_ticks": 20, "name": "B"})
        s.set_live(b["profile_id"], True)
        self.assertEqual([p["profile_id"] for p in s.profiles()], [a["profile_id"], b["profile_id"]])
        n = s.live_tick()
        self.assertEqual(n, 1)
        self.assertIsNotNone(s.latest_snapshot(b["profile_id"]))
        self.assertIn("NO_ACTIVE_SESSION", s.state["profile_errors"][a["profile_id"]])
        self.assertEqual(s.live_tick(), 0)                                      # same closed bar -> nothing to do


class TestSVPProfileValidation(_Base):
    """chunk_35#14: update_profile stored any value (mode='live' -> StopIteration in compute, 500 and a poisoned LIVE loop)."""

    def test_update_normalises_mode_and_validates_fields(self):
        s = self.svc()
        c = s.create_profile({"mode": "RANGE", "tf": "M5", "t0": iso(T0), "t1": iso(T0 + 90 * 300), "bin_ticks": 20})
        pid = c["profile_id"]
        u = s.update_profile(pid, {"mode": "live"})
        self.assertEqual((u["mode"], u["live"]), ("LIVE", 1))
        for patch in ({"tf": "M7"}, {"bin_ticks": 0}, {"bin_ticks": "x"}, {"va_pct": 1.5}, {"mode": "FROZEN"}, {"mode": "SIDEWAYS"},
                      {"session": "MARS"}, {"local_date": "2026-13-40"}, {"tz": "Mars/Base"}, {"start_hm": "25:99"},
                      {"profile_set": "NO_SUCH_SET"}, {"opacity": "abc"}):
            with self.assertRaises(ValueError, msg=str(patch)):
                s.update_profile(pid, patch)
        for spec in ({"tf": "M7"}, {"bin_ticks": -3}, {"session": "MARS", "local_date": "2026-03-02"}, {"mode": "live", "tz": "Nowhere/X"}):
            with self.assertRaises(ValueError, msg=str(spec)):
                s.create_profile(dict({"mode": "SESSION"}, **spec))
        ok = s.update_profile(pid, {"mode": "SESSION", "session": "LONDON", "local_date": "2026-03-02", "tf": "m5"})
        self.assertEqual((ok["mode"], ok["live"], ok["tf"]), ("SESSION", 0, "M5"))

    def test_legacy_bad_rows_fail_with_value_error(self):
        from masterquo.svp import engine as EN
        with self.assertRaises(ValueError):
            EN.session_window("LAB_XAU_REFERENCE_V1", "MARS", "2026-03-02")
        with self.assertRaises(ValueError):
            EN.session_window("NO_SUCH_SET", "ASIA", "2026-03-02")
        with self.assertRaises(ValueError):
            EN.custom_window("Europe/London", "08:00", "12:00", None)
        s = self.svc()
        p = s.create_profile({"mode": "SESSION", "session": "LONDON", "local_date": "2026-03-02"})
        with s._lock:                                                           # a row stored by 1.45 without validation
            s.db.execute("UPDATE svp_profiles SET session='MARS' WHERE profile_id=?", (p["profile_id"],))
        with self.assertRaises(ValueError):
            s.compute(p["profile_id"])


class TestSVPProfileBoundIds(_Base):
    """chunk_35#15: two profiles with the same geometry shared snapshot_id / zone_id - the second profile had no snapshot, its refresh
    moved the ALGORITHM zones of the first one and its frozen view showed the first profile's name and colour."""

    def test_same_geometry_profiles_are_independent(self):
        s = self.svc()
        spec = {"mode": "RANGE", "tf": "M5", "t0": iso(T0), "t1": iso(T0 + 90 * 300), "bin_ticks": 20}
        p1 = s.create_profile(dict(spec, name="Profil 1", color="#ff0000"))
        self.now += 1
        p2 = s.create_profile(dict(spec, name="Profil 2", color="#00ff00"))
        r1 = s.algo_now(p1["profile_id"])
        n1 = len(s.zones(profile_id=p1["profile_id"]))
        self.assertGreater(n1, 0)
        r2 = s.algo_now(p2["profile_id"])
        self.assertEqual(r1["profile"]["geometry_id"], r2["profile"]["geometry_id"])
        self.assertNotEqual(r1["profile"]["snapshot_id"], r2["profile"]["snapshot_id"])
        self.assertEqual(len(s.zones(profile_id=p1["profile_id"])), n1)        # p2 refresh does not take p1's zones
        self.assertEqual(len(s.zones(profile_id=p2["profile_id"])), n1)
        self.assertEqual(s.latest_snapshot(p2["profile_id"])["profile_id"], p2["profile_id"])
        s.freeze(p2["profile_id"])
        v = s.compute(p2["profile_id"])
        self.assertEqual((v.get("label"), v.get("color")), ("Profil 2", "#00ff00"))
        self.assertEqual(s.compute(p1["profile_id"])["snapshot_id"], r1["profile"]["snapshot_id"])   # deterministic per profile


class TestSVPZonesAsOf(_Base):
    """chunk_35#18: zones(as_of) returned zones deleted / replaced before as_of (deactivation had no time)."""

    def test_deleted_zone_not_visible_after_deletion_time(self):
        s = self.svc()
        t_create = self.now
        z = s.create_manual({"lower": 2000, "upper": 2001, "name": "M"})
        self.now += 3600
        t_del = self.now
        self.assertTrue(s.delete_zone(z["zone_id"]))
        self.now += 3600
        self.assertEqual(s.zones(), [])
        self.assertEqual([x["zone_id"] for x in s.zones(as_of=t_create + 1)], [z["zone_id"]])   # before deletion: visible
        self.assertEqual(s.zones(as_of=t_del + 1), [])                                         # after deletion: gone
        self.assertEqual(s.zones(as_of=self.now), [])

    def test_algorithm_refresh_does_not_mix_snapshots(self):
        s = self.svc()
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 200 * 300), "bin_ticks": 20})
        s.algo_now(p["profile_id"])
        first = {z["zone_id"] for z in s.zones(source="ALGORITHM")}
        t1 = self.now
        self.bars.extend(mk_bars(30, t0=T0 + 100 * 300, f=lambda i: 2004 + i * 0.05, tv=lambda i: 40))
        self.now += 30 * 300
        s.algo_now(p["profile_id"])
        second = {z["zone_id"] for z in s.zones(source="ALGORITHM")}
        self.assertTrue(first and second and not (first & second))
        self.assertEqual({z["zone_id"] for z in s.zones(source="ALGORITHM", as_of=t1)}, first)
        self.assertEqual({z["zone_id"] for z in s.zones(source="ALGORITHM", as_of=self.now)}, second)

    def test_old_database_migrates_additively(self):
        d = Path(self.td.dir) / "old"
        d.mkdir(parents=True)
        db = sqlite3.connect(str(d / "svp.sqlite"))
        db.executescript("""
CREATE TABLE svp_zones (zone_id TEXT, version INTEGER, source TEXT, instrument TEXT, symbol TEXT, account_key TEXT, profile_id TEXT,
  snapshot_id TEXT, kind TEXT, lower REAL, upper REAL, name TEXT, color TEXT, description TEXT, pinned INTEGER DEFAULT 0, locked INTEGER DEFAULT 0,
  created_at REAL, available_at TEXT, valid_until TEXT, active INTEGER DEFAULT 1, payload TEXT, PRIMARY KEY(zone_id, version));""")
        db.execute("INSERT INTO svp_zones(zone_id, version, source, symbol, account_key, lower, upper, created_at, active, payload) "
                   "VALUES ('SZ-old', 1, 'MANUAL', 'XAUUSD-', 'srv:1', 1990, 1991, ?, 1, '{}')", (T0,))
        db.commit()
        db.close()
        for _ in range(2):                                                       # idempotent
            s = self.svc(sub="old")
            self.assertEqual([z["zone_id"] for z in s.zones()], ["SZ-old"])
            self.assertEqual([z["zone_id"] for z in s.zones(as_of=self.now)], ["SZ-old"])
            s.db.close()


class TestSVPProfileEventsClosedOnly(unittest.TestCase):
    """chunk_35#17: profile_events counted the forming candle (closed=False) as one of the N closes outside the value area."""

    def test_forming_bar_never_confirms(self):
        from masterquo.svp import zones as ZN
        p = {"vah": 2001.0, "val": 1999.0, "poc": 2000.0, "bin_size": 0.2, "known_at": iso(T0)}
        b = [{"open_utc": iso(T0 + i * 300), "o": 2002, "h": 2002.5, "l": 2001.5, "c": 2002.0, "closed": True} for i in range(2)]
        forming = dict(b[-1], open_utc=iso(T0 + 600), closed=False)
        self.assertEqual([e["kind"] for e in ZN.profile_events(p, b + [forming], tf_s=300)], [])     # 1.45: ['ACCEPTANCE_ABOVE_VA']
        self.assertEqual(ZN.profile_events(p, b + [forming], tf_s=300, as_of=T0 + 700), [])
        third = dict(forming, closed=True)
        self.assertEqual(ZN.profile_events(p, b + [third], tf_s=300, as_of=T0 + 700), [])            # not closed yet at as_of
        ev = ZN.profile_events(p, b + [third], tf_s=300, as_of=T0 + 900)
        self.assertEqual([e["kind"] for e in ev], ["ACCEPTANCE_ABOVE_VA"])


class TestSVPLowFindings(_Base):
    def test_coverage_undefined_is_null(self):
        """chunk_35#25: coverage of a range shorter than one bar is undefined (None), not 0.0; a range with no bars keeps 0.0."""
        from masterquo.svp import engine as EN
        p = EN.compute(self.bars, "M5", T0, T0 + 100, as_of=T0 + 200, tick=0.01, bin_ticks=20, instrument="XAUUSD")
        self.assertEqual(p["status"], "NO_DATA")
        self.assertIsNone(p["coverage"])
        q = EN.compute(self.bars, "M5", T0 + 500 * 300, T0 + 600 * 300, as_of=T0 + 700 * 300, tick=0.01, bin_ticks=20, instrument="XAUUSD")
        self.assertEqual((q["status"], q["coverage"]), ("NO_DATA", 0.0))

    def test_ai_propose_compute_off_loop_and_value_error_mapped(self):
        """chunk_35#22: ai_propose ran compute (MT5 read) on the event loop and raised ValueError (500)."""
        s = self.svc(agent=_Agent())
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 99 * 300), "bin_ticks": 20})
        threads = []
        orig = s.compute

        def rec(*a, **k):
            threads.append(threading.get_ident())
            return orig(*a, **k)
        s.compute = rec
        r = asyncio.run(s.ai_propose(p["profile_id"]))
        self.assertEqual(r["status"], "OK")
        self.assertTrue(threads)
        self.assertNotIn(threading.get_ident(), threads)                         # not on the event-loop thread
        self.now = T0 + 19 * 3600                                                # LIVE outside any session -> NO_ACTIVE_SESSION
        lp = s.create_profile({"mode": "LIVE"})
        r = asyncio.run(s.ai_propose(lp["profile_id"]))
        self.assertEqual(r["status"], "NO_PROFILE")
        self.assertIn("NO_ACTIVE_SESSION", r["reason"])

    def test_unknown_tick_is_not_invented(self):
        """chunk_35#23: no symbol_info -> tick 0.01 was assumed; the profile is NO_DATA (TICK_UNKNOWN) and nothing is stored."""
        s = self.svc(bridge=_Bridge(self.bars, info={}))
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 99 * 300), "bin_ticks": 20})
        r = s.compute(p["profile_id"])
        self.assertEqual(r["status"], "NO_DATA")
        self.assertIn("TICK_UNKNOWN", r["reason"])
        self.assertIsNone(r.get("snapshot_id"))
        self.assertIsNone(s.latest_snapshot(p["profile_id"]))
        a = s.algo_now(p["profile_id"])
        self.assertEqual(a["zones"], [])
        v = s.visible("M5", iso(T0), iso(T0 + 50 * 300))
        self.assertEqual(v["status"], "NO_DATA")
        self.assertIn("TICK_UNKNOWN", v["reason"])

    def test_poc_migration_event(self):
        """chunk_35#24: algo_now never passed prev_poc, so POC_MIGRATION was dead."""
        s = self.svc()
        p = s.create_profile({"mode": "RANGE", "t0": iso(T0), "t1": iso(T0 + 300 * 300), "bin_ticks": 20})
        first = s.algo_now(p["profile_id"])
        self.assertNotIn("POC_MIGRATION", [e["kind"] for e in first["events"]])
        self.bars.extend(mk_bars(60, t0=T0 + 100 * 300, f=lambda i: 2010.0, tv=lambda i: 500))
        self.now += 60 * 300
        second = s.algo_now(p["profile_id"])
        mig = [e for e in second["events"] if e["kind"] == "POC_MIGRATION"]
        self.assertEqual(len(mig), 1)
        self.assertEqual((mig[0]["from"], mig[0]["to"]), (first["profile"]["poc"], second["profile"]["poc"]))
        s.update_profile(p["profile_id"], {"t0": iso(T0 + 50 * 300)})            # new geometry: no migration across geometries
        third = s.algo_now(p["profile_id"])
        self.assertNotIn("POC_MIGRATION", [e["kind"] for e in third["events"]])


if __name__ == "__main__":
    unittest.main()
