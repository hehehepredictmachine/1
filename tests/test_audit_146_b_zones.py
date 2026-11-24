"""1.46 audit, group B_zones - regression tests for zones/ (MarketZonesService of the "Strefy rynkowe" panel, the zone-map compiler
and the closed-bar Series). Synthetic data only, no MT5, no HTTP server, no trading path."""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData, wait_for
from masterquo.config import ZonesConfig
from masterquo.events import AppLog
from masterquo.zones import market as MZ
from masterquo.zones.market_service import Job, MarketZonesService
from masterquo.zones.series import Series, iso, ts

T0 = 1_792_800_000.0 - (1_792_800_000.0 % 86400)


def _bars(n=400, tf_s=300, p0=2600.0, seed=7):
    import random
    rnd, out, p = random.Random(seed), [], p0
    for i in range(n):
        o = p
        c = o + rnd.gauss(0, 1.2)
        h, lo = max(o, c) + abs(rnd.gauss(0, 0.6)), min(o, c) - abs(rnd.gauss(0, 0.6))
        p = c
        out.append({"open_utc": iso(T0 + i * tf_s), "o": o, "h": h, "l": lo, "c": c, "tv": 100.0, "rv": 0.0, "spread": 20, "closed": True})
    return out


class _Cfg:
    class _A:
        def __init__(self, s):
            self.broker_symbol = s

    def __init__(self):
        mp = {"XAUUSD": _Cfg._A("XAUUSD-"), "BTC": _Cfg._A("BTCUSDT-")}
        self.c = type("C", (), {"assets": type("A", (), {"mappings": mp})()})()

    def get(self):
        return self.c


class _Bridge:
    """Bars are never needed by these tests except where stated; the quote is controllable."""

    def __init__(self):
        self.quote = {"bid": 2600.0, "ask": 2600.2, "spread": 0.2}

    def symbol_bars(self, sym, tf, n):
        return []

    def symbol_meta(self, sym):
        return {"point": 0.01}

    def symbol_quote(self, sym):
        return self.quote


class _LogDB:
    def __init__(self):
        self.rows = []

    def execute(self, sql, params=()):
        self.rows.append(params)


class _Bus:
    def publish(self, *_a, **_k):
        pass


class _Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.now = T0 + 400 * 300 + 5
        self.br = _Bridge()
        self.logdb = _LogDB()
        self.log = AppLog(self.logdb, _Bus())                      # the REAL production log class (runtime passes AppLog)
        self.svc = MarketZonesService(_Cfg(), self.br, log=self.log, data_dir=Path(self.td.dir), clock=lambda: self.now, poll_s=3600)

    def tearDown(self):
        self.svc.stop_service()
        self.svc.db.close()
        self.td.close()

    def warnings(self, code):
        return [r for r in self.logdb.rows if len(r) > 3 and r[1] == "WARNING" and r[2] == "MARKET_ZONES" and r[3] == code]

    def computed(self, tf="M5"):
        """Put one computed timeframe into the service, as a finished job does."""
        s = Series.from_bars(_bars(), tf, self.now)
        raw = MZ.compute_tf(s, "XAUUSD", 0.01, None)
        raw.update(computed_as_of=iso(self.now), data_status="CONNECTED")
        self.svc.tf[("XAUUSD", tf)] = {"raw": raw, "data_at": self.now, "seq": 1, "computed_at": self.now, "restored": False}
        self.svc.status[("XAUUSD", tf)] = {"status": "CONNECTED", "reason": None, "checked_at": iso(self.now)}
        return raw


# ------------------------------------------------------------------------------------------ chunk_39#1 / focus_X3#1
class LivePollerSurvivesErrors(_Base):
    def test_poller_keeps_running_after_a_poll_exception_with_the_real_applog(self):
        self.svc.poll_s = 0.01
        calls = []

        def boom(inst, tfs):
            calls.append(inst)
            raise RuntimeError("terminal hiccup")
        self.svc.poll_once = boom
        self.svc.request = lambda *a, **k: {}                       # no job / bar reads - only the poller is under test
        self.svc.set_live("XAUUSD", True, ["M5"])
        # 1.45: the handler called AppLog.warning (does not exist) -> AttributeError -> the 'mzones-live' thread died after 1 call
        self.assertTrue(wait_for(lambda: len(calls) >= 3, 5, 0.01), f"poll calls: {len(calls)}")
        self.assertTrue(self.svc._poller.is_alive())
        self.assertTrue(self.warnings("LIVE_POLL_FAILED"))


# ------------------------------------------------------------------------------------------ chunk_39#2
class _FailingDB:
    """sqlite3.Connection.execute cannot be patched: wrap it, fail the snapshot INSERT of one timeframe ('disk full')."""

    def __init__(self, real, fail_tf):
        self.real, self.fail_tf = real, fail_tf

    def execute(self, sql, params=()):
        if sql.startswith("INSERT INTO mz_snapshots") and params[1] == self.fail_tf:
            raise sqlite3.OperationalError("database or disk is full")
        return self.real.execute(sql, params)

    def close(self):
        self.real.close()


class HistoryWriteErrorIsReported(_Base):
    def test_sqlite_error_is_logged_and_other_timeframes_are_still_persisted(self):
        real = self.svc.db
        self.svc.db = _FailingDB(real, "M5")
        job = Job(5, "XAUUSD", ["M5", "M15"], "manual")
        fresh = {tf: {"raw": {"zones": [], "last_closed": None, "computed_as_of": iso(self.now)}, "data_at": self.now,
                      "status": {"status": "CONNECTED"}} for tf in ("M5", "M15")}
        # 1.45: AttributeError ('AppLog' object has no attribute 'warning') escaped _apply -> job FAILED, M15 never written
        applied = self.svc._apply(job, fresh)
        self.assertEqual(applied, ["M5", "M15"])
        self.assertEqual(real.execute("SELECT COUNT(*) FROM mz_snapshots WHERE tf='M15'").fetchone()[0], 1)
        self.assertEqual(real.execute("SELECT COUNT(*) FROM mz_snapshots WHERE tf='M5'").fetchone()[0], 0)
        w = self.warnings("HISTORY_WRITE_FAILED")
        self.assertEqual(len(w), 1)
        self.assertIn("disk is full", w[0][4])
        self.assertFalse(real.in_transaction)                      # no transaction left open by the failure


# ------------------------------------------------------------------------------------------ chunk_39#12
class StopBetweenPopAndRun(_Base):
    def test_cancelled_job_never_goes_back_to_running_and_the_popped_job_is_deduplicated(self):
        orig = self.svc._run
        entered, gate, done = threading.Event(), threading.Event(), threading.Event()

        def slow_run(job):
            entered.set()
            gate.wait(5)
            try:
                orig(job)
            finally:
                done.set()
        self.svc._run = slow_run
        j = self.svc.request("XAUUSD", ["M5"])
        self.assertTrue(entered.wait(5))                           # the worker popped the job; _run has not started yet
        again = self.svc.request("XAUUSD", ["M5"])
        self.assertTrue(again["deduplicated"])                     # 1.45: QUEUED but out of the queue -> a second job was created
        self.assertEqual(again["job_id"], j["job_id"])
        out = self.svc.stop("XAUUSD")
        self.assertEqual(out["cancelled_jobs"], 1)
        gate.set()
        self.assertTrue(done.wait(5))                              # _run returned
        st = self.svc.job(j["job_id"])
        self.assertEqual(st["status"], "CANCELLED")                # 1.45: _run overwrote it with RUNNING (stuck forever)
        self.assertEqual(self.svc.view("XAUUSD")["job"]["status"], "CANCELLED")


# ------------------------------------------------------------------------------------------ chunk_39#13 / chunk_39#18
class QuoteFreshnessAndChecklistPrice(_Base):
    def test_live_off_and_stop_drop_the_quote(self):
        self.computed()
        self.svc._live_quote("XAUUSD")
        v = self.svc.view("XAUUSD")
        self.assertEqual(v["quote"]["bid"], 2600.0)
        self.assertTrue(all("live" in z for z in v["timeframes"]["M5"]["zones"]))
        self.svc.set_live("XAUUSD", False)
        v = self.svc.view("XAUUSD")
        self.assertIsNone(v["quote"])                              # 1.45: the last bid stayed forever after LIVE off
        self.assertFalse(any("live" in z for z in v["timeframes"]["M5"]["zones"]))
        self.svc._live_quote("XAUUSD")
        self.svc.stop("XAUUSD")
        self.assertIsNone(self.svc.view("XAUUSD")["quote"])

    def test_an_old_or_missing_quote_is_not_used(self):
        self.svc.poll_s = 2.0                                      # production poll period (the fixture idles the poller with 3600 s)
        self.computed()
        self.svc._live_quote("XAUUSD")
        self.now += 600                                            # the poller died / the market closed: the quote is 10 min old
        v = self.svc.view("XAUUSD")
        self.assertTrue(v["quote"]["stale"])
        self.assertGreaterEqual(v["quote"]["age_s"], 600)
        self.assertFalse(any("live" in z for z in v["timeframes"]["M5"]["zones"]))
        zid = v["timeframes"]["M5"]["zones"][0]["id"]
        spread = next(i for i in self.svc.zone("XAUUSD", zid)["checklist"]["items"] if i["label"].startswith("Spread"))
        self.assertIsNone(spread["ok"])                            # an old spread is not evaluated as current
        self.br.quote = None                                       # terminal returned no quote
        self.svc._live_quote("XAUUSD")
        v = self.svc.view("XAUUSD")
        self.assertNotIn("bid", v["quote"])
        self.assertFalse(any("live" in z for z in v["timeframes"]["M5"]["zones"]))

    def test_checklist_distance_uses_the_last_close_without_a_live_quote(self):
        raw = self.computed()
        v = self.svc.view("XAUUSD")
        self.assertEqual(v["timeframes"]["M5"]["price"], raw["price"])
        zid = v["timeframes"]["M5"]["zones"][0]["id"]
        item = next(i for i in self.svc.zone("XAUUSD", zid)["checklist"]["items"] if i["label"].startswith("Cena w odległości"))
        self.assertIsNotNone(item["ok"])                           # 1.45: always None (tf_view had no 'price')
        self.assertIsNotNone(item["value"])


# ------------------------------------------------------------------------------------------ chunk_39#14
class _HookLock:
    """RLock wrapper: runs `hook` once, in the poller thread, right after it released the lock with no live subscription."""

    def __init__(self, inner, svc, hook):
        self.inner, self.svc, self.hook, self.fired = inner, svc, hook, False

    def __enter__(self):
        self.inner.acquire()
        return self

    def __exit__(self, *a):
        self.inner.release()
        if not self.fired and threading.current_thread().name == "mzones-live" and not self.svc.live:
            self.fired = True
            self.hook()
        return False


class PollerExitRace(_Base):
    def test_subscription_added_while_the_poller_exits_gets_a_poller(self):
        calls = []
        self.svc.poll_s = 0.01
        self.svc.poll_once = lambda inst, tfs: calls.append(inst) or []
        self.svc.request = lambda *a, **k: {}
        self.svc._lock = _HookLock(self.svc._lock, self.svc, lambda: self.svc.set_live("XAUUSD", True, ["M5"]))
        old = threading.Thread(target=self.svc._poll_loop, name="mzones-live", daemon=True)
        self.svc._poller = old
        old.start()                                                # no subscription: this poller decides to exit ...
        self.assertTrue(wait_for(lambda: self.svc._lock.fired, 5, 0.01))
        old.join(5)                                                # ... and set_live() ran in that window
        self.assertFalse(old.is_alive())
        # 1.45: set_live saw the exiting poller as alive and started none - the LIVE subscription stayed without a thread
        self.assertTrue(wait_for(lambda: self.svc._poller is not None and self.svc._poller.is_alive() and calls, 5, 0.01))
        self.assertIn("XAUUSD", self.svc.live)


# ------------------------------------------------------------------------------------------ chunk_39#16
class NaiveIsoIsUtc(unittest.TestCase):
    def test_naive_timestamp_does_not_depend_on_the_machine_time_zone(self):
        prev = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Warsaw"
        time.tzset()
        try:
            self.assertEqual(ts("2026-11-20T12:00:00"), ts("2026-11-20T12:00:00Z"))   # 1.45: 11:00Z (local CET)
            self.assertEqual(ts("2026-07-20T12:00:00"), ts("2026-07-20T12:00:00+00:00"))
            self.assertEqual(ts("2026-11-20T13:00:00+01:00"), ts("2026-11-20T12:00:00Z"))  # explicit offsets unchanged
            self.assertEqual(ts(1_800_000_000), 1_800_000_000.0)
            with self.assertRaises(ValueError):
                ts("not a time")                                   # the API still answers 400 INVALID_AS_OF
        finally:
            if prev is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = prev
            time.tzset()


# ------------------------------------------------------------------------------------------ chunk_39#17
class ProfileTfWithoutBars(unittest.TestCase):
    def test_missing_profile_series_is_reported_not_masked_as_no_volume(self):
        import test_zones as TZ
        bars = TZ.market()
        as_of = TZ.T0 + 2016 * 300
        ok = TZ.cmap(bars, as_of)
        self.assertEqual(ok["data"]["state"], "OK")                # default profile_tf M5: unchanged
        self.assertTrue(ok["profiles"]["completed"])
        zm = TZ.cmap(bars, as_of, cfg=ZonesConfig(profile_tf="M1"))  # allowed by the config; ZoneService reads no M1 bars
        self.assertEqual(zm["data"]["state"], "DEGRADED")          # 1.45: OK + 'brak użytecznego wolumenu' (a market property)
        self.assertTrue(any("M1" in r for r in zm["data"]["reasons"]), zm["data"]["reasons"])
        self.assertEqual(zm["volume_source"].get("missing_series"), "M1")
        m1 = [dict(b, open_utc=iso(ts(b["open_utc"]) + k * 60)) for b in bars["M5"][-600:] for k in range(5)]
        zm1 = TZ.cmap(dict(bars, M1=m1), as_of, cfg=ZonesConfig(profile_tf="M1"))     # M1 bars present: profiles from M1
        self.assertEqual(zm1["data"]["state"], "OK")
        self.assertNotIn("missing_series", zm1["volume_source"])


if __name__ == "__main__":
    unittest.main()
