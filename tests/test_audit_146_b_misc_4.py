"""1.46 audit, group B_misc_4 - regression tests (SYNTHETIC_TEST data only, no network, no demo server).

chunk_24#4   Monte Carlo: the calibrator is applied only to levels that match its validation events (side, TP / SL distance, horizon)
chunk_24#5   Monte Carlo: no spread data -> SELL probabilities NOT_VERIFIED (None), never 0 from NaN comparisons
chunk_24#7   Monte Carlo service: a non-finite / non-positive entry -> BAD_PLAN (was NaN in the JSON -> HTTP 500)
chunk_24#6   Monte Carlo: validation events / scenario levels per instrument (BTC: NOT_CONFIGURED instead of an always-empty run)
chunk_24#3   news: the FRED key is handed to M04N without writing os.environ (focus_X7#6 is the same defect)
chunk_24#17  Telegram account_event: real delivery result, nothing marked sent before Telegram accepted it, rate limit + back-off
chunk_28#18  governor: admit_training check + reservation under the lock (two heavy trainings never admitted together)
chunk_00#5   stats.account_roi: snapshot window clipped to the deal-history coverage (deposits outside it were counted as profit)
chunk_00#6   stats: unknown SH commission -> aggregate commission None (was summed as 0.0)
chunk_00#7   stats.account_stats: commission deals (MT5 deal types 7..11) are part of the trading result
chunk_24#8   Monte Carlo: the newest closed bar can be drawn by BLOCK / REGIME blocks
chunk_24#9   Monte Carlo service: variant_basis does not claim "chosen by validation" for a manually chosen variant
chunk_24#10  Monte Carlo validation: missing spreads filled from the past only; no spreads at all -> INSUFFICIENT_DATA (not 0)
chunk_24#11  Monte Carlo rollback without a registry -> NO_REGISTRY (was FileNotFoundError)
chunk_28#24  governor: a release() that left the process running is not counted / logged as RELEASED
chunk_28#25  governor: user-visible texts say Apollo23, not PMW
chunk_00#10  Runtime.stop(): bootstrap stopped, one failing part does not skip the rest
chunk_00#15  Runtime: AppLog START / STOP texts use the display name
focus_X7#11  SecretStore.source(): UNREADABLE for a stored value that cannot be decrypted
focus_X7#12  SecretStore: the plain-text secrets file is created 0600 (not umask default, then chmod)
"""
from __future__ import annotations

import inspect
import itertools
import json
import os
import tempfile
import threading
import time
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData

T0 = datetime(2026, 9, 1, tzinfo=UTC).timestamp()          # a Tuesday


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def mk_bars(n=1500, seed=3, spread=12, drift=0.0, last_up=None):
    """SYNTHETIC M1 bars (Bid OHLC); spread in points (point 0.01) or no spread key at all (spread=None)."""
    r = np.random.default_rng(seed)
    out, c = [], 2400.0
    for i in range(n):
        o = c
        c = o + drift + r.normal(0, 0.3)
        h = max(o, c) + abs(r.normal(0, 0.4))
        lo = min(o, c) - abs(r.normal(0, 0.4))
        if last_up is not None and i == n - 1:
            h = max(o, c) + last_up
        b = {"open_utc": _iso(T0 + i * 60), "o": o, "h": h, "l": lo, "c": c}
        if spread is not None:
            b["spread"] = spread
        out.append(b)
    return out


def v_bars(bars, spread_price=0.12):
    """Bars in the validate.load_dataset format."""
    return [{"open_utc": b["open_utc"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "spread_price": spread_price} for b in bars]


CAL = {"status": "ACTIVE", "variant": "BLOCK", "run_id": "MC-TEST", "calibrator": {"kind": "ISOTONIC", "x": [0.0, 1.0], "y": [0.2, 0.2]},
       "events": [{"side": s, "tp": tp, "sl": 3.0} for s in ("BUY", "SELL") for tp in (2.5, 5.0)], "horizon_bars": 60}


class _Bridge:
    def __init__(self, b):
        self.b = b
        self.symbol_info = {"point": 0.01, "trade_tick_size": 0.01}

    def bars(self, tf, limit=None, include_forming=True):
        return self.b

    def quote_status(self):
        return {"bid": self.b[-1]["c"], "ask": self.b[-1]["c"] + 0.12}


def _cfg(inst="XAUUSD"):
    return NS(get=lambda: NS(assets=NS(active=inst)))


# ------------------------------------------------------------------------------------------------------------------- Monte Carlo
class TestMonteCarloEngine(unittest.TestCase):
    def setUp(self):
        from masterquo.montecarlo import engine as E
        self.E = E

    def test_chunk_24_4_calibrator_only_for_its_events(self):
        E = self.E
        b = mk_bars()
        as_of = T0 + len(b) * 60
        e = b[-1]["c"] + 0.12
        match = E.Plan("BUY", e, e - 3.0, [e + 2.5, e + 30.0], 60)              # TP 2.5 / SL 3 / H 60 = a validation event; TP 30 is not
        r = E.run(b, as_of, [match], variant="BLOCK", calibrator=CAL)
        lv = r["plans"][0]["levels"]
        self.assertAlmostEqual(lv[0]["p_calibrated"], 0.2)
        self.assertIsNone(lv[1]["p_calibrated"])
        self.assertEqual(lv[1]["calibration_status"], "CALIBRATOR_EVENT_MISMATCH")
        self.assertTrue(r["calibrated"])
        other = E.Plan("BUY", e, e - 30.0, [e + 1.0], 240)                        # SL 30 / TP 1 / H 240: never validated
        r = E.run(b, as_of, [other], variant="BLOCK", horizon=240, calibrator=CAL)
        self.assertIsNone(r["plans"][0]["levels"][0]["p_calibrated"])
        self.assertFalse(r["calibrated"])
        self.assertNotIn("calibrated_by", r["plans"][0])
        h120 = E.Plan("BUY", e, e - 3.0, [e + 2.5], 120)                         # same distances, other horizon
        r = E.run(b, as_of, [h120], variant="BLOCK", horizon=120, calibrator=CAL)
        self.assertIsNone(r["plans"][0]["levels"][0]["p_calibrated"])
        self.assertFalse(r["calibrated"])

    def test_chunk_24_5_no_spread_data_is_not_zero(self):
        E = self.E
        b = mk_bars(spread=None)                                                  # no spread value in any bar
        as_of = T0 + len(b) * 60
        last = b[-1]["c"]
        sell = E.Plan("SELL", last, last + 3.0, [last - 2.5], 60)
        buy = E.Plan("BUY", last + 0.12, last + 0.12 - 3.0, [last + 0.12 + 2.5], 60)
        r = E.run(b, as_of, [sell, buy])
        self.assertEqual(r["status"], "OK")
        self.assertIn("NO_SPREAD_DATA", r["data"]["flags"])
        self.assertIn("NO_SPREAD_DATA", r["warning"])
        s = r["plans"][0]
        self.assertEqual(s["status"], "NOT_VERIFIED")
        self.assertIsNone(s["sl_within_h"])
        for k in ("p_tp_before_sl_conservative", "p_tp_before_sl_optimistic", "p_ambiguous_same_bar", "p_tp_within_h", "mc_error_95"):
            self.assertIsNone(s["levels"][0][k], k)
        bp = r["plans"][1]                                                        # BUY: Bid only, the entry (Ask) is given by the plan
        self.assertEqual(bp["status"], "OK")
        self.assertIsNotNone(bp["levels"][0]["p_tp_before_sl_conservative"])
        json.dumps(r, allow_nan=False)
        r = E.run(b, as_of, [sell], variant="BLOCK", calibrator=CAL)             # never calibrated from a missing value
        self.assertIsNone(r["plans"][0]["levels"][0]["p_calibrated"])
        self.assertFalse(r["calibrated"])

    def test_chunk_24_8_newest_bar_reachable_by_blocks(self):
        E = self.E
        b = mk_bars(300, last_up=100.0)                                           # only the newest closed bar has a +100 high
        h = E.history(b, T0 + 300 * 60)
        self.assertEqual(h.n, 300)
        for variant in ("BLOCK", "REGIME"):
            p = E.simulate(h, n_paths=4000, horizon=30, variant=variant, seed=7, block=30)
            self.assertGreater(float((p["high"] - p["open"]).max()), 90.0, variant)

    def test_chunk_24_6_scenarios_without_levels_not_configured(self):
        E = self.E
        b = mk_bars()
        r = E.run(b, T0 + len(b) * 60, None, levels=())
        self.assertEqual(r["scenarios"]["status"], "NOT_CONFIGURED")
        self.assertEqual(r["scenarios"]["levels_price"], [])


class TestMonteCarloService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_chunk_24_7_bad_entry_is_refused_not_nan(self):
        from masterquo.montecarlo.service import MonteCarloService
        svc = MonteCarloService(_cfg(), _Bridge(mk_bars()), synthetic=True, n_paths=300)
        try:
            for bad in (float("nan"), float("inf"), -5.0, 0.0):
                plan = svc.plan_for("BUY", 3.0, [2.5], entry=bad)
                res = svc.compute([plan])
                self.assertEqual(res["status"], "BAD_PLAN", bad)
                json.dumps(res, allow_nan=False)                                   # FastAPI JSON never sees NaN
            ok = svc.compute([svc.plan_for("SELL", 3.0, [2.5])])
            self.assertEqual(ok["status"], "OK")
        finally:
            svc.stop()

    def test_chunk_24_9_variant_basis_for_manual_variant(self):
        from masterquo.montecarlo import service as S
        svc = S.MonteCarloService(_cfg(), _Bridge(mk_bars()), synthetic=False, n_paths=300)
        try:
            with mock.patch.object(S.V, "active_calibrator", return_value=dict(CAL)):
                auto = svc.compute(None)
                manual = svc.compute(None, variant="IID")
            self.assertIn("wybrany walidacją na Twoich danych", auto["variant_basis"])
            self.assertNotIn("wybrany walidacją na Twoich danych", manual["variant_basis"])
            self.assertIn("ręcznie", manual["variant_basis"])
        finally:
            svc.stop()

    def test_chunk_24_6_btc_scenarios_have_no_gold_levels(self):
        from masterquo.montecarlo.service import MonteCarloService
        svc = MonteCarloService(_cfg("BTC"), _Bridge(mk_bars()), synthetic=True, n_paths=300)
        gold = MonteCarloService(_cfg("XAUUSD"), _Bridge(mk_bars()), synthetic=True, n_paths=300)
        try:
            r = svc.compute(None)
            self.assertEqual(r["status"], "OK")
            self.assertEqual(r["scenarios"]["levels_price"], [])
            self.assertEqual(r["scenarios"]["status"], "NOT_CONFIGURED")
            self.assertEqual(gold.compute(None)["scenarios"]["levels_price"], [2.5, 3.0, 5.0, 7.5, 10.0])
            r = svc.compute(None, levels=(500.0, 1000.0))                         # levels given explicitly (SH profile) are used
            self.assertEqual(r["scenarios"]["levels_price"], [500.0, 1000.0])
        finally:
            svc.stop()
            gold.stop()


class TestMonteCarloValidate(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _validate(self, bars, meta, **kw):
        from masterquo.montecarlo import validate as V
        with mock.patch.object(V, "load_dataset", return_value=(bars, meta)):
            return V.validate(Path(self.td.dir) / "no_such_dataset", log=lambda m: None, **kw)

    def test_chunk_24_6_btc_without_events_not_configured(self):
        b = v_bars(mk_bars(600))
        r = self._validate(b, {"instrument": "BTC", "data_kind": "SYNTHETIC_TEST", "spec": {"point": 0.01}})
        self.assertEqual(r["status"], "NOT_CONFIGURED")
        r = self._validate(b, {"instrument": "BTC", "data_kind": "SYNTHETIC_TEST", "spec": {"point": 0.01}},
                           events=[{"side": "BUY", "tp": 500.0, "sl": 600.0}])
        self.assertEqual(r["status"], "INSUFFICIENT_DATA")                        # explicit events: a normal run (too few points here)
        r = self._validate(b, {"instrument": "XAUUSD", "data_kind": "SYNTHETIC_TEST", "spec": {"point": 0.01}})
        self.assertEqual(r["status"], "INSUFFICIENT_DATA")

    def test_chunk_24_10_no_spreads_insufficient_and_fill_from_past_only(self):
        from masterquo.montecarlo import validate as V
        b = v_bars(mk_bars(600), spread_price=None)
        r = self._validate(b, {"instrument": "XAUUSD", "data_kind": "SYNTHETIC_TEST", "spec": {"point": 0.01}})
        self.assertEqual(r["status"], "INSUFFICIENT_DATA")
        self.assertIn("NO_SPREAD_DATA", r["reason"])
        b = v_bars(mk_bars(50), spread_price=None)
        b[10]["spread_price"], b[30]["spread_price"] = 0.2, 0.5
        fill = V.past_spread_fill(b)
        self.assertTrue(np.isnan(fill[:10]).all())                               # nothing known yet -> unknown, never 0
        self.assertTrue((fill[10:30] == 0.2).all())
        self.assertTrue((fill[30:] == 0.5).all())
        b2 = [dict(x) for x in b]
        b2[40]["spread_price"] = 9.9                                              # a later spread never changes an earlier fill
        np.testing.assert_array_equal(V.past_spread_fill(b2)[:40], fill[:40])
        y, _ = V.outcomes(b, 5, {"side": "SELL", "tp": 2.5, "sl": 3.0}, None, 60, fill)
        self.assertTrue(np.isnan(y[1:11]).all())                                  # entry spread unknown before bar 10 -> no label

    def test_chunk_24_10_walk_forward_still_completes(self):
        meta = {"instrument": "XAUUSD", "data_kind": "SYNTHETIC_TEST", "spec": {"point": 0.01}}
        kw = {"window": 600, "stride": 10, "horizon": 60, "n_paths": 200, "max_points": 200}
        b = v_bars(mk_bars(1500))
        r = self._validate(b, meta, **kw)
        self.assertEqual(r["status"], "DONE", r.get("reason"))
        self.assertEqual(r["verdict"], "TEST_TECHNICZNY")
        json.dumps(r, allow_nan=False)
        part = [dict(x, spread_price=None) if k < 700 else x for k, x in enumerate(b)]   # spreads only from bar 700 on
        r2 = self._validate(part, meta, **kw)
        self.assertIn(r2["status"], ("DONE", "INSUFFICIENT_DATA"))
        if r2["status"] == "DONE":
            self.assertLess(r2["test"]["n"] + r2["cal"]["n"], r["test"]["n"] + r["cal"]["n"])   # points without a known entry spread skipped

    def test_chunk_24_11_rollback_without_registry(self):
        from masterquo.montecarlo import validate as V
        self.assertEqual(V.rollback("BTC"), {"active": None, "reason": "NO_REGISTRY"})
        (V.root("BTC") / "registry.json").write_text("[1, 2]", encoding="utf-8")   # damaged registry
        self.assertEqual(V.rollback("BTC"), {"active": None, "reason": "NO_REGISTRY"})


# ------------------------------------------------------------------------------------------------------------------- news / FRED
class TestNewsFredKey(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.prev = os.environ.pop("FRED_API_KEY", None)

    def tearDown(self):
        os.environ.pop("FRED_API_KEY", None)
        if self.prev is not None:
            os.environ["FRED_API_KEY"] = self.prev
        self.td.close()

    def _run_once(self, secrets) -> str | None:
        from masterquo.news import service as NSV
        from masterquo.timeutil import iso, utcnow
        seen = {}
        eng = types.ModuleType("M04N_FAKE")
        eng.os = os                                                               # the vendor module reads its global `os`

        class Store:
            def __init__(self, p):
                self.p = p

        def collect(mcfg, store):
            seen["key"] = eng.os.environ.get("FRED_API_KEY")
            svc._stop.set()
            svc._kick.set()
            return {"as_of": iso(utcnow()), "status": "OK"}, None
        eng.Store, eng.collect = Store, collect
        cfg = NS(get=lambda: NS(news=NS(enabled=True, poll_seconds=300)))
        svc = NSV.NewsService(cfg, secrets, NS(publish=lambda *a: None), None)
        with mock.patch.object(NSV, "_engine", return_value=eng):
            svc._loop()
        return seen["key"]

    def test_chunk_24_3_fred_key_not_written_to_environment(self):
        from masterquo.secrets_store import SecretStore
        st = SecretStore(Path(self.td.dir))
        st.set("FRED_API_KEY", "OLDKEY1234567890")
        self.assertEqual(self._run_once(st), "OLDKEY1234567890")                  # M04N still gets the key
        self.assertFalse("FRED_API_KEY" in os.environ, "FRED_API_KEY written to os.environ")   # ... but not through the process environment
        self.assertEqual(st.source("FRED_API_KEY"), "LOCAL_STORE")
        st.set("FRED_API_KEY", "NEWKEY0987654321")
        self.assertEqual(self._run_once(st), "NEWKEY0987654321")                  # a key changed in Settings is used at once
        st.set("FRED_API_KEY", None)
        self.assertIsNone(self._run_once(st))                                     # a removed key is not sent any more
        self.assertEqual(st.source("FRED_API_KEY"), "MISSING")
        os.environ["FRED_API_KEY"] = "ENVKEY_FROM_USER"                           # the user's own environment variable keeps priority
        self.assertEqual(self._run_once(st), "ENVKEY_FROM_USER")


# ------------------------------------------------------------------------------------------------------------------- Telegram
class _DB:
    def __init__(self):
        self.keys = set()

    def one(self, sql, args):
        return {"x": 1} if args[0] in self.keys else None

    def execute(self, sql, args):
        self.keys.add(args[0])


class TestTelegramAccountEvent(unittest.TestCase):
    def setUp(self):
        from masterquo.config import TelegramConfig
        from masterquo.notify import telegram as T
        self.T = T
        self.now = [1_800_000_000.0]
        c = TelegramConfig(enabled=True, chat_id="42")
        self.db = _DB()
        self.n = T.TelegramNotifier(NS(get=lambda: NS(telegram=c)), NS(get=lambda k: "123:TOKEN" if k == "TELEGRAM_BOT_TOKEN" else None), self.db,
                                    clock=lambda: self.now[0])
        self.n._sleep = lambda s: self.now.__setitem__(0, self.now[0] + s)
        self.async_sent = []
        self.n._send_async = lambda tok, chat, text: self.async_sent.append(text)   # never a real thread / network call
        p = mock.patch("urllib.request.urlopen", side_effect=OSError("network disabled in tests"))
        p.start()
        self.addCleanup(p.stop)

    def test_chunk_24_17_failed_send_stays_queued_with_backoff(self):
        n = self.n
        with mock.patch.object(n, "_post", return_value=(False, "brak połączenia z api.telegram.org (URLError)")) as post:
            self.assertFalse(n.account_event("e1", "text"))
            self.assertEqual(post.call_count, 1)
        self.assertNotIn("e1", self.db.keys)                                       # not marked as delivered
        self.assertEqual(self.async_sent, [])
        calls = []
        with mock.patch.object(n, "_post", side_effect=lambda *a: calls.append(a) or (True, None)):
            self.assertFalse(n.account_event("e1", "text"))                       # back-off: no request at all
            self.assertEqual(calls, [])
            self.now[0] += 61
            self.assertTrue(n.account_event("e1", "text"))
            self.assertIn("e1", self.db.keys)
            self.assertTrue(n.account_event("e1", "text"))                        # dedup: already delivered
            self.assertEqual(len(calls), 1)

    def test_chunk_24_17_retry_after_and_rate_limit(self):
        n = self.n
        with mock.patch.object(n, "_post", return_value=(False, "HTTP 429: Too Many Requests: retry after 120")):
            self.assertFalse(n.account_event("e1", "text"))
        calls = []
        with mock.patch.object(n, "_post", side_effect=lambda *a: calls.append(self.now[0]) or (True, None)):
            self.now[0] += 61
            self.assertFalse(n.account_event("e1", "text"))                       # Telegram asked for 120 s
            self.assertEqual(calls, [])
            self.now[0] += 60
            res = [n.account_event(f"b{i}", "text") for i in range(8)]
        sent = sum(res)
        self.assertGreaterEqual(sent, 1)
        self.assertLess(sent, 8)                                                   # a full outbox is not fired at once
        self.assertEqual(res, [True] * sent + [False] * (8 - sent))
        self.assertTrue(all(b - a >= 1.0 - 1e-9 for a, b in itertools.pairwise(calls)))   # about one message per second

    def test_chunk_24_17_account_center_outbox_keeps_undelivered(self):
        from masterquo.notify.account_center import AccountCenter
        with tempfile.TemporaryDirectory() as d:
            c = AccountCenter(Path(d), deliver=self.n.account_event, clock=lambda: self.now[0])
            c.state["outbox"] = [{"key": "acct:e1", "text": "t1"}, {"key": "acct:e2", "text": "t2"}]
            with mock.patch.object(self.n, "_post", return_value=(False, "HTTP 502: Bad Gateway")):
                self.assertEqual(c.flush(), 0)
            self.assertEqual([m["key"] for m in c.state["outbox"]], ["acct:e1", "acct:e2"])
            self.assertEqual(c.state["sent_keys"], [])
            self.now[0] += 61
            with mock.patch.object(self.n, "_post", return_value=(True, None)):
                self.assertEqual(c.flush(), 2)
            self.assertEqual(c.state["outbox"], [])


# ------------------------------------------------------------------------------------------------------------------- governor
def _gov_cfg(profile="LOW_MEMORY_16GB"):
    return NS(get=lambda: NS(resources=NS(profile=profile, manual=None)))


class TestGovernor(unittest.TestCase):
    def test_chunk_28_18_two_heavy_trainings_never_admitted_together(self):
        from masterquo.resources.governor import Governor

        def mem():
            time.sleep(0.15)                                                     # measurement takes time (/proc, WinAPI)
            return {"total_mb": 16384, "used_pct": 40.0}
        g = Governor(_gov_cfg(), memory=mem, proc_mem=lambda pid: (None, None))
        res = []
        ths = [threading.Thread(target=lambda n=n: res.append(g.admit_training(n, "heavy", trading_active=False))) for n in ("granite", "sdformer")]
        for t in ths:
            t.start()
        for t in ths:
            t.join(10)
        self.assertEqual(sorted(ok for ok, _ in res), [False, True])
        self.assertEqual(len(g.training), 1)
        g.training_done(next(iter(g.training)))
        self.assertEqual(g.training, {})

    def test_chunk_28_24_release_counted_only_when_process_gone(self):
        from masterquo.resources.governor import Governor
        g = Governor(_gov_cfg(), memory=lambda: {"total_mb": 16384, "used_pct": 95.0}, proc_mem=lambda pid: (300.0, 300.0))
        g.register("tabicl", "heavy", lambda: 4242, release=lambda: False, idle=lambda: 1000.0)   # busy worker: release refused
        self.assertEqual(g.maintain(), [])
        self.assertEqual(g.counters["released"], 0)
        self.assertFalse([e for e in g.events if e["kind"] == "RELEASED"])
        st = {"pid": 4343}
        g.register("chronos2", "heavy", lambda: st["pid"], release=lambda: st.update(pid=None), idle=lambda: 1000.0)  # returns None, process gone
        self.assertEqual(g.maintain(), ["chronos2"])
        self.assertEqual(g.counters["released"], 1)
        self.assertEqual(g._release_idle_heavy(except_model="x", min_idle_s=0.0, why="t"), [])     # tabicl still refuses
        self.assertEqual(g._make_room("tirex2", 1), [])
        self.assertEqual(g.counters["released"], 1)

    def test_chunk_28_25_texts_use_display_name(self):
        from masterquo.resources.governor import Governor
        mem = {"total_mb": 16384, "used_pct": 40.0}
        g = Governor(_gov_cfg(), memory=lambda: dict(mem), proc_mem=lambda pid: (500.0, 500.0))
        g.register("bot", "bot", lambda: 1)
        g.sample()
        mem["used_pct"] = 82.0                                                    # LIMIT_HEAVY
        g.sample()
        msg = [e["message"] for e in g.events if e["kind"] == "LEVEL"][-1]
        self.assertIn("Apollo23", msg)
        self.assertNotIn("PMW", msg)
        ok, reason = g.admit("chronos2", loaded=False)
        self.assertFalse(ok)
        self.assertIn("Apollo23", reason)
        self.assertNotIn("PMW", reason)
        self.assertIn("pmw_total_mb", g.sample())                                 # the API key stays (identifier)


# ------------------------------------------------------------------------------------------------------------------- stats
class _SnapDB:
    def __init__(self, snaps=(), sh=()):
        self.snaps, self.sh = list(snaps), list(sh)

    def query(self, sql, args):
        if "FROM equity_snapshots" in sql:
            return [r for r in self.snaps if r["ts"] >= args[-1]]
        if "FROM sh_plans" in sql:
            return list(self.sh)
        return []


class TestStats(unittest.TestCase):
    def test_chunk_00_5_roi_window_clipped_to_deal_history(self):
        from masterquo import stats
        from masterquo.timeutil import iso, utcnow
        now = utcnow()
        snaps = [{"ts": iso(now - timedelta(days=25)), "equity": 1000.0}, {"ts": iso(now - timedelta(days=5)), "equity": 2000.0},
                 {"ts": iso(now - timedelta(minutes=1)), "equity": 2000.0}]
        db = _SnapDB(snaps)
        cover = (now - timedelta(days=7)).timestamp()                             # deals_history_days = 7: the deposit 20 days ago is not in `deals`
        r = stats.account_roi(db, "Broker:1", [], 0.0, days=30, deals_from_utc=cover)
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["roi_pct"], 0.0)                                       # was 100 % (the deposit counted as profit)
        self.assertTrue(r["period_clipped_to_deal_history"])
        self.assertEqual(r["deals_coverage"], "VERIFIED")
        dep = [{"type": 2, "profit": 1000.0, "time": (now - timedelta(days=20)).timestamp()}]
        r = stats.account_roi(db, "Broker:1", dep, 0.0, days=30, deals_from_utc=(now - timedelta(days=40)).timestamp())
        self.assertEqual((r["roi_pct"], r["period_clipped_to_deal_history"]), (0.0, False))
        r = stats.account_roi(db, "Broker:1", dep, 0.0, days=30)                  # callers that do not pass the coverage: unchanged + NOT_VERIFIED
        self.assertEqual((r["roi_pct"], r["deals_coverage"]), (0.0, "NOT_VERIFIED"))
        r = stats.account_roi(_SnapDB(snaps[:2]), "Broker:1", [], 0.0, days=30, deals_from_utc=cover)
        self.assertEqual(r["status"], "NO_DATA")                                  # one snapshot inside the covered window: no ROI

    def test_chunk_00_6_unknown_sh_commission_not_summed_as_zero(self):
        from masterquo import stats
        t = datetime(2026, 9, 1, 12, tzinfo=UTC).timestamp()
        sh = [{"strategy": "SCALPING", "symbol": "XAUUSD-", "state": "CLOSED", "closed_at": t,
               "result": json.dumps({"net_money": 10.0, "commission_known": False, "commission_money": None, "r_multiple": 0.5})},
              {"strategy": "SCALPING", "symbol": "XAUUSD-", "state": "CLOSED", "closed_at": t + 60,
               "result": json.dumps({"net_money": 5.0, "commission_known": True, "commission_money": 2.0, "r_multiple": 0.2})},
              {"strategy": "HEDGING", "symbol": "XAUUSD-", "state": "CLOSED", "closed_at": t + 120,
               "result": json.dumps({"net_money": -3.0, "commission_known": True, "commission_money": 1.5, "r_multiple": -0.3})}]
        r = stats.engine_stats(_SnapDB(sh=sh), "PAPER")
        self.assertIsNone(r["per_engine"]["SH_SCALPING"]["commission"])
        self.assertEqual(r["per_engine"]["SH_SCALPING"]["commission_unknown_trades"], 1)
        self.assertIsNone(r["combined"]["commission"])
        self.assertEqual(r["per_engine"]["SH_HEDGING"]["commission"], 1.5)        # all known: the sum stays
        self.assertEqual(r["per_engine"]["SH_HEDGING"]["commission_unknown_trades"], 0)
        self.assertEqual(r["sh_commission_unknown_plans"], 1)

    def test_chunk_00_7_commission_deals_in_trading_result(self):
        from masterquo import stats
        deals = [{"type": 0, "profit": 100.0, "commission": 0.0, "swap": 0.0, "fee": 0.0, "symbol": "XAUUSD-", "time": 1000},
                 {"type": 7, "profit": -5.0, "symbol": "", "time": 1100},                  # DEAL_TYPE_COMMISSION
                 {"type": 9, "profit": -2.0, "symbol": "", "time": 1200},                  # DEAL_TYPE_COMMISSION_MONTHLY
                 {"type": 2, "profit": 1000.0, "symbol": "", "time": 900}]                 # deposit - never trading
        r = stats.account_stats(deals, "XAUUSD-", 1050)
        self.assertEqual(r["trading_net_all_symbols"], 93.0)
        self.assertEqual(r["commission_deals"], -7.0)
        self.assertEqual(r["commission_deals_count"], 2)
        self.assertEqual(r["trading_net_today"], -7.0)
        self.assertEqual(r["trading_net_symbol"], 100.0)                           # account-level charges have no symbol
        self.assertEqual(r["deposits"], 1000.0)
        self.assertEqual(r["deals"], 1)


# ------------------------------------------------------------------------------------------------------------------- runtime
class _Part:
    def __init__(self, name, calls, fail=False):
        self.name, self.calls, self.fail = name, calls, fail

    def stop(self):
        self.calls.append(self.name)
        if self.fail:
            raise RuntimeError("stop failed")

    def stop_service(self):
        self.stop()


PARTS = ("bootstrap", "telegram", "governor", "ml", "forecast", "scalp", "sh", "mm", "zones", "indicators", "svp", "market_zones", "trainhub",
         "trainhub_inference", "kronos", "tsfm", "montecarlo", "quant", "research", "baskets", "analytics", "lab", "extind", "nss", "mtf", "si",
         "liquidity", "scanner", "engine", "manager", "news", "bridge", "worker")


class TestRuntimeStop(unittest.TestCase):
    def _rt(self, fail=()):
        from masterquo.runtime import Runtime
        rt = Runtime.__new__(Runtime)
        calls, logs = [], []
        for n in PARTS:
            setattr(rt, n, _Part(n, calls, n in fail))
        rt._stop = threading.Event()
        rt.log = NS(info=lambda *a: logs.append(a), warn=lambda *a: logs.append(a), error=lambda *a: logs.append(a))
        return rt, calls, logs

    def test_chunk_00_10_bootstrap_stopped_and_failures_isolated(self):
        rt, calls, _ = self._rt(fail=("sh", "tsfm"))
        with self.assertLogs("masterquo.runtime", "ERROR") as cm:
            rt.stop()
        self.assertTrue(rt._stop.is_set())
        self.assertEqual(calls[0], "bootstrap")                                    # first: no new installer after the services stopped
        self.assertEqual(sorted(calls), sorted(PARTS))                             # every part asked to stop, despite two failures
        self.assertEqual(calls[-3:], ["news", "bridge", "worker"])                 # order kept: MT5 bridge / worker last
        self.assertEqual(len([m for m in cm.output if "stop of" in m]), 2)
        rt2, calls2, _ = self._rt()
        rt2.research = rt2.baskets = rt2.bootstrap = None                          # optional parts missing
        rt2.stop()
        self.assertNotIn("research", calls2)

    def test_chunk_00_15_display_name_in_applog(self):
        from masterquo import runtime
        from masterquo.version import DISPLAY_NAME
        rt, _, logs = self._rt()
        rt.stop()
        stop = [a for a in logs if a[:2] == ("APP", "STOP")]
        self.assertTrue(stop and DISPLAY_NAME in stop[0][2] and "MasterQUO" not in stop[0][2])
        self.assertNotIn("MasterQUO AI", inspect.getsource(runtime.Runtime._start_engine_parts))


# ------------------------------------------------------------------------------------------------------------------- secrets
class TestSecretStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)

    def test_focus_x7_11_unreadable_secret_is_not_local_store(self):
        from masterquo import secrets_store as SS
        st = SS.SecretStore(Path(self.tmp.name))
        st.set("TELEGRAM_BOT_TOKEN", "QkxPQg==")                                    # stored (as on Windows: base64 of the DPAPI blob)
        st.windows = True                                                           # read as on another Windows user / computer
        with mock.patch.object(SS, "_dpapi", side_effect=OSError("DPAPI_FAILED")):
            self.assertIsNone(st.get("TELEGRAM_BOT_TOKEN"))
            self.assertEqual(st.source("TELEGRAM_BOT_TOKEN"), "UNREADABLE")
            self.assertIsNone(st.mask("TELEGRAM_BOT_TOKEN"))
        with mock.patch.object(SS, "_dpapi", return_value=b"123:abcdefghijklmnop"):
            self.assertEqual(st.source("TELEGRAM_BOT_TOKEN"), "LOCAL_STORE")
        self.assertEqual(st.source("FRED_API_KEY"), "MISSING")

    @unittest.skipIf(os.name == "nt", "POSIX permissions (Windows: DPAPI file)")
    def test_focus_x7_12_plain_secrets_file_created_private(self):
        from masterquo.secrets_store import SecretStore
        old = os.umask(0o022)
        try:
            st = SecretStore(Path(self.tmp.name))
            with mock.patch("os.chmod", side_effect=OSError("chmod refused")):      # no reliance on a later chmod
                st.set("FRED_API_KEY", "abcdef1234567890")
            self.assertEqual(st.path.stat().st_mode & 0o777, 0o600)
            stale = st.path.with_suffix(".tmp")                                     # a stale world-readable temp file is not reused as is
            stale.write_text("{}", encoding="utf-8")
            os.chmod(stale, 0o644)
            st.set("FRED_API_KEY", "abcdef1234567891")
            self.assertEqual(st.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(st.get("FRED_API_KEY"), "abcdef1234567891")
        finally:
            os.umask(old)


if __name__ == "__main__":
    unittest.main()
