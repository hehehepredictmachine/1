"""'Strefy rynkowe' (zones/market.py + zones/market_service.py): detection and confirmation times on M1 / M5 / M15 / M30, no look-ahead,
independent tests, invalidation and expiry, merging with provenance, confluence, instrument scaling, and the job service (multi-click,
older result never overwrites a newer one, instrument isolation, data loss -> stale -> recovery, live recompute only after the
candle close of that timeframe, one subscription, restore after restart, no trading side effects).
All market data here is SYNTHETIC: the tests exercise the rules, they do not measure any predictive value."""
from __future__ import annotations

import ast
import json
import random
import threading
import time
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData, wait_for

from masterquo.zones import market as MZ
from masterquo.zones.market_service import MarketZonesService
from masterquo.zones.series import Series, iso, ts

T0 = 1_792_800_000.0 - (1_792_800_000.0 % 86400)            # a Monday-ish UTC midnight in 2026 (exact weekday irrelevant here)
TFS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800}


def bar(t, o, h, l, c, closed=True, spread=20):
    return {"open_utc": iso(t), "o": o, "h": h, "l": l, "c": c, "tv": 100.0, "rv": 0.0, "spread": spread, "closed": closed}


def flat(n, t0=T0, tf_s=300, p=100.0, rng=1.0):
    return [bar(t0 + i * tf_s, p, p + rng / 2, p - rng / 2, p) for i in range(n)]


def gen(n, tf_s=60, seed=1, p0=2000.0, t0=T0):
    rnd, out, p = random.Random(seed), [], p0
    for i in range(n):
        o = p
        c = o + rnd.gauss(0, 1.2 * (tf_s / 300) ** 0.5)
        h, l = max(o, c) + abs(rnd.gauss(0, 0.6)), min(o, c) - abs(rnd.gauss(0, 0.6))
        p = c
        out.append(bar(t0 + i * tf_s, o, h, l, c))
    return out


def agg(bars, k, tf_s):
    out = []
    for i in range(0, len(bars) - k + 1, k):
        g = bars[i:i + k]
        out.append(bar(ts(g[0]["open_utc"]), g[0]["o"], max(x["h"] for x in g), min(x["l"] for x in g), g[-1]["c"]))
    return out


def ser(rows, tf="M5", as_of=None):
    return Series.from_bars(rows, tf, as_of if as_of is not None else ts(rows[-1]["open_utc"]) + TFS[tf])


def run_tf(rows, tf="M5", inst="XAUUSD", as_of=None, tick=0.01):
    r = MZ.compute({tf: ser(rows, tf, as_of)}, instrument=inst, symbol="X", tick=tick, as_of=as_of or ts(rows[-1]["open_utc"]) + TFS[tf])
    return r["timeframes"][tf]


def swing_high_rows(right_bars: int):
    """40 flat bars, a spike high at index 40, then `right_bars` lower bars."""
    rows = flat(40)
    rows.append(bar(T0 + 40 * 300, 100.0, 105.0, 99.8, 100.2))
    for k in range(right_bars):
        rows.append(bar(T0 + (41 + k) * 300, 100.0, 100.4, 99.6, 100.0))
    return rows


class TestDetection(unittest.TestCase):
    def test_swing_known_only_after_confirmation_candles_close(self):
        right = MZ.TF_PARAMS["M5"]["right"]
        early = run_tf(swing_high_rows(right - 1))                     # one confirming candle still missing
        self.assertFalse([x for x in run_tf(swing_high_rows(0))["zones"] if x["type"] == "SR_RESISTANCE"])   # no candidate without any close after it
        z = [x for x in early["zones"] if x["type"] == "SR_RESISTANCE"]
        self.assertTrue(z and all(x["preliminary"] and x["state"] == "PRELIMINARY" for x in z))
        done = run_tf(swing_high_rows(right))
        z2 = next(x for x in done["zones"] if x["type"] == "SR_RESISTANCE")
        self.assertFalse(z2["preliminary"])
        self.assertEqual(z2["detectable_from"], iso(T0 + (40 + right + 1) * 300))   # close of the last confirming candle
        self.assertEqual(z2["id"], z[0]["id"])                                     # persistent id: provisional -> confirmed
        self.assertEqual(z2["upper"], 105.0)

    def test_fvg_detected_at_close_of_third_candle(self):
        rows = flat(40)
        rows += [bar(T0 + 40 * 300, 100.0, 100.5, 99.5, 100.4), bar(T0 + 41 * 300, 100.5, 103.0, 100.4, 102.9),
                 bar(T0 + 42 * 300, 103.0, 103.6, 101.8, 103.5)]
        r = run_tf(rows[:-1])
        self.assertFalse([z for z in r["zones"] if z["type"] == "FVG_BULL"])
        r = run_tf(rows)
        f = next(z for z in r["zones"] if z["type"] == "FVG_BULL")
        self.assertEqual((f["lower"], f["upper"]), (100.5, 101.8))
        self.assertEqual(f["detectable_from"], iso(T0 + 43 * 300))

    def test_order_block_needs_bos_over_a_confirmed_swing(self):
        rows = flat(30)
        rows.append(bar(T0 + 30 * 300, 100.0, 103.0, 99.9, 100.1))            # swing high 103
        rows += [bar(T0 + (31 + k) * 300, 100.0, 100.4, 99.4, 99.8) for k in range(4)]
        rows.append(bar(T0 + 35 * 300, 99.8, 99.9, 98.6, 98.8))              # last bearish candle
        rows.append(bar(T0 + 36 * 300, 98.8, 101.5, 98.7, 101.4))
        before = list(rows)
        r = run_tf(before)
        self.assertFalse([z for z in r["zones"] if z["type"] == "OB_BULL"])   # no BOS yet -> no order block
        rows.append(bar(T0 + 37 * 300, 101.4, 104.2, 101.3, 104.0))          # close above 103 = BOS
        r = run_tf(rows)
        ob = next(z for z in r["zones"] if z["type"] == "OB_BULL")
        self.assertEqual(ob["detectable_from"], iso(T0 + 38 * 300))
        self.assertEqual(ob["origin_time"], iso(T0 + 35 * 300))
        self.assertEqual(ob["bos_time"], iso(T0 + 38 * 300))

    def test_equal_highs_are_inferred_liquidity_and_a_wick_invalidates(self):
        rows = flat(30)
        for i, hi in ((30, 103.0), (38, 103.05)):
            while len(rows) < i:
                rows.append(bar(T0 + len(rows) * 300, 100.0, 100.5, 99.5, 100.0))
            rows.append(bar(T0 + i * 300, 100.2, hi, 99.9, 100.3))
        rows += [bar(T0 + (39 + k) * 300, 100.0, 100.5, 99.5, 100.0) for k in range(5)]
        r = run_tf(rows)
        eq = next(z for z in r["zones"] if z["type"] == "EQH")
        self.assertIn("wnioskowana z OHLC", eq["type_pl"])
        self.assertIn("nie zlecenia", eq["reason"])
        self.assertEqual(eq["direction"], "NEUTRAL")
        rows.append(bar(T0 + 44 * 300, 100.0, 103.4, 99.9, 100.1))           # wick through the level, close back below
        r = run_tf(rows)
        eq2 = next(z for z in r["zones"] if z["id"] == eq["id"])
        self.assertEqual(eq2["state"], "INVALIDATED")

    def test_independent_tests_invalidation_by_close_and_expiry(self):
        rows = swing_high_rows(3)
        n0 = len(rows)

        def add(h, l, c):
            rows.append(bar(T0 + len(rows) * 300, c, h, l, c))
        for _ in range(4):
            add(100.4, 99.6, 100.0)
        add(104.9, 100.0, 100.2)                                              # test 1 (wick into the zone)
        add(104.8, 100.0, 100.2)                                              # still at the zone: same test
        for _ in range(4):
            add(100.4, 99.6, 100.0)
        add(104.9, 100.0, 100.3)                                              # test 2 after leaving the zone
        z = next(x for x in run_tf(rows)["zones"] if x["type"] == "SR_RESISTANCE")
        self.assertEqual((z["state"], z["tests"]), ("TESTED", 2))
        add(105.6, 100.0, 105.05)                                             # wick far beyond, close only 0.05 above: not enough
        z = next(x for x in run_tf(rows)["zones"] if x["id"] == z["id"])
        self.assertEqual(z["state"], "TESTED")
        add(106.0, 104.0, 105.9)                                              # close beyond by > break_atr x ATR
        z = next(x for x in run_tf(rows)["zones"] if x["id"] == z["id"])
        self.assertEqual(z["state"], "INVALIDATED")
        self.assertIsNotNone(z["invalidated_at"])
        # expiry
        rows2 = swing_high_rows(3) + [bar(T0 + (n0 + k) * 300, 100.0, 100.4, 99.6, 100.0) for k in range(MZ.TF_PARAMS["M5"]["max_age"] + 2)]
        z = next(x for x in run_tf(rows2)["zones"] if x["type"] == "SR_RESISTANCE" and x["origin_time"] == iso(T0 + 40 * 300))
        self.assertEqual(z["state"], "EXPIRED")

    def test_zone_schema_score_and_probability_are_separate(self):
        z = next(x for x in run_tf(swing_high_rows(3))["zones"] if x["type"] == "SR_RESISTANCE")
        for k in ("id", "instrument", "timeframe", "type", "lower", "upper", "origin_time", "detectable_from", "direction", "state", "state_pl",
                  "tests", "reason", "invalidation_rule", "quality", "confluence", "algo_version", "events"):
            self.assertIn(k, z)
        self.assertTrue(0 <= z["quality"]["score"] <= 100)
        self.assertEqual(set(z["quality"]["components"]), {"struktura", "reakcja", "świeżość", "testy", "konfluencja", "szerokość"})
        self.assertIsNone(z["probability"])
        self.assertIn("nie jest prawdopodobieństwem", z["quality"]["note"])
        self.assertEqual(z["algo_version"], MZ.VERSION)


class TestNoLookAhead(unittest.TestCase):
    def setUp(self):
        m1 = gen(30 * 600, seed=5)
        self.bars = {"M1": m1[-1500:], "M5": agg(m1, 5, 300)[-1000:], "M15": agg(m1, 15, 900)[-700:], "M30": agg(m1, 30, 1800)[-500:]}
        self.end = ts(m1[-1]["open_utc"]) + 60

    def compute(self, bars, as_of):
        return MZ.compute({tf: Series.from_bars(b, tf, as_of) for tf, b in bars.items()}, instrument="XAUUSD", symbol="X", tick=0.01, as_of=as_of)

    def test_future_bars_change_nothing_and_nothing_is_known_early(self):
        rnd = random.Random(9)
        for back in (47 * 60, 3 * 3600 + 13 * 60, 9 * 3600):
            cut = self.end - back
            a = self.compute(self.bars, cut)
            fut = {tf: [dict(b, h=b["h"] + rnd.uniform(0, 50), l=b["l"] - rnd.uniform(0, 50), c=b["c"] + rnd.uniform(-40, 40))
                        if ts(b["open_utc"]) + TFS[tf] > cut else b for b in rows] for tf, rows in self.bars.items()}
            b = self.compute(fut, cut)
            self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
            for tf, r in a["timeframes"].items():
                for z in r["zones"]:
                    self.assertLessEqual(z["detectable_from"], iso(cut))
                    for e in z["events"]:
                        self.assertLessEqual(e["at"], iso(cut))
            # an M30 candle forming at the cut is not used by any M30 zone or by the confluence of lower TFs
            last30 = a["timeframes"]["M30"]["last_closed"]
            self.assertLessEqual(last30, iso(cut))

    def test_forming_candle_is_not_used(self):
        rows = list(self.bars["M5"])
        rows[-1] = dict(rows[-1], closed=False, h=rows[-1]["h"] + 500)
        r = run_tf(rows, "M5", as_of=ts(rows[-1]["open_utc"]) + 300)
        self.assertLess(r["last_closed"], iso(ts(rows[-1]["open_utc"]) + 300))
        self.assertTrue(all(z["upper"] < rows[-1]["h"] for z in r["zones"]))

    def test_state_as_of_from_events(self):
        a = self.compute(self.bars, self.end)
        z = next(z for r in a["timeframes"].values() for z in r["zones"] if z["state"] == "INVALIDATED")
        self.assertIsNone(MZ.state_as_of(z, iso(ts(z["detectable_from"]) - 1)))
        self.assertIn(MZ.state_as_of(z, z["detectable_from"]), ("ACTIVE", "PRELIMINARY"))
        self.assertEqual(MZ.state_as_of(z, z["invalidated_at"]), "INVALIDATED")

    def test_all_four_timeframes_confluence_and_limits(self):
        a = self.compute(self.bars, self.end)
        self.assertEqual(set(a["timeframes"]), {"M1", "M5", "M15", "M30"})
        conf = 0
        for tf, r in a["timeframes"].items():
            self.assertTrue(r["visible"], tf)
            self.assertLessEqual(len(r["visible"]), MZ.COMMON["visible_per_tf"])
            for z in r["zones"]:
                self.assertEqual(z["timeframe"], tf)
                for oid in z["confluence"]["zone_ids"]:
                    o = next(x for orr in a["timeframes"].values() for x in orr["zones"] if x["id"] == oid)
                    self.assertNotEqual(o["timeframe"], tf)
                    self.assertTrue(o["lower"] <= z["upper"] and o["upper"] >= z["lower"])
                conf += z["confluence"]["count"]
        self.assertGreater(conf, 0)

    def test_merge_keeps_provenance(self):
        a = self.compute(self.bars, self.end)
        merged = [z for r in a["timeframes"].values() for z in r["zones"] if z["members"]]
        self.assertTrue(merged)
        for z in merged:
            self.assertGreaterEqual(len(z["members"]), 2)
            self.assertEqual(z["id"], z["members"][0]["id"])
            self.assertEqual(z["detectable_from"], min(m["detectable_from"] for m in z["members"]))
            self.assertEqual(z["bounds_known_from"], max(m["detectable_from"] for m in z["members"]))
            self.assertEqual([sg["from"] for sg in z["segments"]], sorted(m["detectable_from"] for m in z["members"]))
            self.assertLessEqual(z["lower"], min(m["lower"] for m in z["members"]) + 1e-9)
            for t in z["test_times"]:                                      # every test happened after the zone was known
                self.assertGreater(t, z["detectable_from"])

    def test_instrument_profiles_scale_widths(self):
        self.assertGreater(MZ.min_width("BTC", 0.01, 64000.0, 30.0), MZ.min_width("XAUUSD", 0.01, 2600.0, 0.2))
        self.assertNotEqual(MZ.PROFILES["XAUUSD"], MZ.PROFILES["BTC"])

    def test_engine_has_no_trading_imports(self):
        for f in ("market.py", "market_service.py"):
            tree = ast.parse((_env.ROOT / "backend" / "masterquo" / "zones" / f).read_text(encoding="utf-8"))
            mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
                   {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            self.assertFalse([m for m in mods if any(x in m for x in ("execution", "risk", "order", "gateway", "sh."))], f)


class StubBridge:
    """Serves synthetic bars of two symbols; `now` moves the candle closes; `down` simulates a lost terminal connection."""

    def __init__(self, now: float):
        self.now = now
        self.down = False
        self.calls = 0
        self.lock = threading.Lock()
        t0 = (now // 1800) * 1800 - 20000 * 60                                  # M1 grid aligned with the M30 grid
        self.m1 = {s: gen(20000 + 3000, seed=k + 3, p0=p0, t0=t0) for k, (s, p0) in enumerate((("XAUUSD-", 2600.0), ("BTCUSDT-", 64000.0)))}

    def symbol_bars(self, sym, tf, n):
        with self.lock:
            self.calls += 1
        if self.down:
            raise ConnectionError("No IPC connection")
        step = TFS[tf]
        src = [b for b in self.m1[sym] if ts(b["open_utc"]) < self.now]
        buckets: dict[float, list] = {}
        for b in src:                                                            # broker-style buckets on the TF grid
            buckets.setdefault((ts(b["open_utc"]) // step) * step, []).append(b)
        rows = [bar(t, g[0]["o"], max(x["h"] for x in g), min(x["l"] for x in g), g[-1]["c"]) for t, g in sorted(buckets.items())][-n:]
        out = []
        for b in rows:
            closed = ts(b["open_utc"]) + TFS[tf] <= self.now
            out.append(dict(b, closed=closed))
        return out

    def symbol_meta(self, sym):
        return {"point": 0.01, "digits": 2}

    def symbol_quote(self, sym):
        if self.down:
            raise ConnectionError("down")
        last = [b for b in self.m1[sym] if ts(b["open_utc"]) < self.now][-1]
        return {"bid": last["c"], "ask": last["c"] + 0.2, "spread": 0.2}


class Cfg:
    class _A:
        def __init__(self, s):
            self.broker_symbol = s

    def __init__(self):
        self.calls = 0
        mp = {"XAUUSD": Cfg._A("XAUUSD-"), "BTC": Cfg._A("BTCUSDT-")}
        self.c = type("C", (), {"assets": type("A", (), {"mappings": mp})()})()

    def get(self):
        return self.c

    def update(self, *_a, **_k):                       # must never be called by the zones service
        raise AssertionError("zones service tried to change the configuration")


class TestService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        self.now = (time.time() // 60) * 60 + 5
        self.br = StubBridge(self.now)
        self.clock = lambda: self.br.now
        self.svc = MarketZonesService(Cfg(), self.br, data_dir=Path(self.td.dir), clock=self.clock, poll_s=3600)

    def tearDown(self):
        self.svc.stop_service()
        self.td.close()

    def wait_job(self, j):
        self.assertTrue(wait_for(lambda: self.svc.job(j["job_id"])["status"] not in ("QUEUED", "RUNNING"), 60, 0.05))
        return self.svc.job(j["job_id"])

    def test_button_all_four_tfs_multi_click_and_isolation(self):
        a = self.svc.request("XAUUSD")
        b = self.svc.request("XAUUSD", ["M5", "M15"])
        c = self.svc.request("XAUUSD")
        self.assertEqual((b["job_id"], c["job_id"]), (a["job_id"], a["job_id"]))
        self.assertTrue(b["deduplicated"] and c["deduplicated"])
        self.assertEqual(self.wait_job(a)["status"], "DONE")
        v = self.svc.view("XAUUSD")
        for tf in MZ.TFS:
            self.assertEqual(v["timeframes"][tf]["status"]["status"], "CONNECTED")
            self.assertTrue(v["timeframes"][tf]["zones"])
        self.assertEqual(self.svc.view("BTC")["timeframes"]["M5"]["zones"], [])          # instruments never mix
        jb = self.svc.request("BTC", ["M5"])
        self.wait_job(jb)
        vb = self.svc.view("BTC")
        self.assertTrue(all(z["instrument"] == "BTC" for z in vb["timeframes"]["M5"]["zones"]))
        self.assertEqual(self.svc.view("XAUUSD")["timeframes"]["M5"]["zones"][0]["instrument"], "XAUUSD")
        with self.assertRaises(ValueError):
            self.svc.request("EURUSD")
        with self.assertRaises(ValueError):
            self.svc.request("XAUUSD", ["H1"])

    def test_older_result_never_overwrites_newer(self):
        j = self.wait_job(self.svc.request("XAUUSD", ["M5"]))
        self.assertEqual(j["timeframe_results"]["M5"], "APPLIED")
        cur = self.svc.tf[("XAUUSD", "M5")]
        from masterquo.zones.market_service import Job
        old = Job(0, "XAUUSD", ["M5"], "manual")
        res = self.svc._apply(old, {"M5": {"raw": {"zones": [], "last_closed": None}, "data_at": cur["data_at"] - 600, "status": {"status": "CONNECTED"}}})
        self.assertEqual(res, [])
        self.assertEqual(old.tf_result["M5"], "DISCARDED_OLDER")
        self.assertIs(self.svc.tf[("XAUUSD", "M5")], cur)
        self.assertEqual(self.svc.counters["discarded_older_results"], 1)

    def test_data_loss_keeps_zones_stale_and_recovers(self):
        self.wait_job(self.svc.request("XAUUSD"))
        n = len(self.svc.view("XAUUSD")["timeframes"]["M1"]["zones"])
        self.br.down = True
        j = self.wait_job(self.svc.request("XAUUSD"))
        self.assertEqual(j["status"], "FAILED")
        v = self.svc.view("XAUUSD")
        for tf in MZ.TFS:
            self.assertEqual(v["timeframes"][tf]["status"]["status"], "ERROR")
            self.assertTrue(v["timeframes"][tf]["stale"])
        self.assertEqual(len(v["timeframes"]["M1"]["zones"]), n)                            # last zones kept, marked stale
        self.assertTrue(all(z["stale"] for z in v["timeframes"]["M1"]["zones"]))
        self.br.down = False                                                               # reconnect: the live poll recomputes
        self.svc.live["XAUUSD"] = {"tfs": list(MZ.TFS), "last_closed": {}, "since": None}
        due = self.svc.poll_once("XAUUSD", list(MZ.TFS))
        self.assertEqual(sorted(due), sorted(MZ.TFS))
        self.assertTrue(wait_for(lambda: not self.svc.view("XAUUSD")["timeframes"]["M30"]["stale"], 60, 0.05))

    def test_live_recomputes_only_the_closed_timeframe_and_one_subscription(self):
        # put "now" right after an M30 close so M1, M5, M15, M30 all closed together, then step one minute at a time
        self.br.now = (self.now // 1800) * 1800 + 5
        self.svc.set_live("XAUUSD", True)
        self.svc.set_live("XAUUSD", True)
        self.assertEqual(len(self.svc.live), 1)
        self.assertTrue(wait_for(lambda: all(("XAUUSD", t) in self.svc.tf for t in MZ.TFS), 60, 0.05))
        self.assertTrue(wait_for(lambda: self.svc.current_job["XAUUSD"].status not in ("QUEUED", "RUNNING"), 60, 0.05))
        self.assertEqual(self.svc.poll_once("XAUUSD", list(MZ.TFS)), [])                  # nothing new closed
        self.br.now += 60                                                                 # one more M1 close only
        self.assertEqual(self.svc.poll_once("XAUUSD", list(MZ.TFS)), ["M1"])
        self.br.now += 4 * 60                                                             # M5 closes (and M1)
        self.assertEqual(sorted(self.svc.poll_once("XAUUSD", list(MZ.TFS))), ["M1", "M5"])
        self.br.now += 10 * 60                                                            # :15 -> M15 closes
        self.assertIn("M15", self.svc.poll_once("XAUUSD", list(MZ.TFS)))
        self.assertTrue(wait_for(lambda: self.svc.current_job["XAUUSD"].status not in ("QUEUED", "RUNNING"), 60, 0.05))
        self.assertEqual(self.svc.view("XAUUSD")["timeframes"]["M15"]["last_closed"], iso((self.br.now // 900) * 900))
        self.assertEqual(self.svc.view("XAUUSD")["quote"]["preliminary"], True)
        self.svc.stop("XAUUSD")
        self.assertEqual(self.svc.live, {})

    def test_restore_after_restart_is_stale_and_events_are_idempotent(self):
        self.wait_job(self.svc.request("XAUUSD", ["M5"]))
        self.wait_job(self.svc.request("XAUUSD", ["M5"]))
        ev = self.svc.events("XAUUSD", 5000)
        self.assertEqual(len(ev), len({(e["zone_id"], e["event"], e["at"]) for e in ev}))
        svc2 = MarketZonesService(Cfg(), self.br, data_dir=Path(self.td.dir), clock=self.clock, poll_s=3600)
        v = svc2.view("XAUUSD")
        self.assertTrue(v["timeframes"]["M5"]["restored"] and v["timeframes"]["M5"]["stale"])
        self.assertEqual(v["timeframes"]["M5"]["status"]["status"], "STALE")
        z = v["timeframes"]["M5"]["zones"][0]
        d = svc2.zone("XAUUSD", z["id"])
        self.assertTrue(d["events"])
        self.assertIn("nie jest sygnałem", d["checklist"]["note"])

    def test_stop_cancels_queued_jobs(self):
        self.br.lock.acquire()                                                            # hold the worker on its first read
        try:
            a = self.svc.request("XAUUSD")
            b = self.svc.request("BTC")
            out = self.svc.stop("BTC")
            self.assertEqual(out["cancelled_jobs"], 1)
            self.assertEqual(self.svc.job(b["job_id"])["status"], "CANCELLED")
        finally:
            self.br.lock.release()
        self.wait_job(a)
        self.assertEqual(self.svc.view("BTC")["timeframes"]["M5"]["zones"], [])


if __name__ == "__main__":
    unittest.main()
