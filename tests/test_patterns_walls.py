"""1.10 analysis core: candle patterns, chart patterns (confirmed pivots, states), S/R zones with W1/MN1 aggregation, M5 range +
M1 zones, volatility walls (HV_PROXY / IV_MANUAL / IV import, frozen snapshots). Synthetic bars - code checks, not evidence."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import _env  # noqa: F401

UTC = timezone.utc
T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def bars_from_ohlc(rows, tf_min=5, start=T0, tv=None):
    out = []
    for i, (o, h, lo, c) in enumerate(rows):
        out.append({"open_utc": iso(start + timedelta(minutes=tf_min * i)), "o": o, "h": h, "l": lo, "c": c, "closed": True,
                    "tv": (tv[i] if tv else 100)})
    return out


def path_bars(points, steps=4, wick=0.1, tf_min=5, start=T0):
    """Piecewise-linear path through `points`, `steps` bars per segment."""
    rows = []
    for a, b in zip(points, points[1:]):
        for k in range(steps):
            o = a + (b - a) * k / steps
            c = a + (b - a) * (k + 1) / steps
            rows.append((o, max(o, c) + wick, min(o, c) - wick, c))
    return bars_from_ohlc(rows, tf_min, start)


def view(bars, tf="M5"):
    from masterquo.strategies.base import TFView
    return TFView(tf, bars)


def flat(n, px=100.0, tf_min=5, start=T0):
    return bars_from_ohlc([(px, px + 0.5, px - 0.5, px + (0.1 if i % 2 else -0.1)) for i in range(n)], tf_min, start)


class TestCandles(unittest.TestCase):
    def detect(self, rows, atr=1.0, **kw):
        from masterquo.analysis import candles as C
        b = bars_from_ohlc(rows)
        o, h, lo, c, t = [x["o"] for x in b], [x["h"] for x in b], [x["l"] for x in b], [x["c"] for x in b], [x["open_utc"] for x in b]
        return {p["type"]: p for p in C.detect_at(o, h, lo, c, t, len(b) - 1, atr, "M5", "AV", **kw)}

    def test_engulfing_and_negative(self):
        r = self.detect([(100, 100.2, 99, 99.2), (100.4, 100.5, 99.6, 99.8), (99.7, 101, 99.6, 100.9)])
        self.assertIn("ENGULFING_BULL", r)
        self.assertEqual(r["ENGULFING_BULL"]["variant"], "NO_GAP_CFD")
        r2 = self.detect([(100, 100.1, 99.9, 99.95), (99.95, 100.1, 99.9, 100.05)])       # bodies far below 0.3 ATR
        self.assertNotIn("ENGULFING_BULL", r2)

    def test_hammer_needs_downswing_pin_bar_does_not(self):
        r = self.detect([(103, 103.2, 102, 102.2), (102.2, 102.3, 101.2, 101.4), (101.4, 101.5, 100.6, 100.8), (100.8, 101, 99, 100.9)])
        self.assertIn("PIN_BAR_BULL", r)
        self.assertIn("HAMMER", r)
        r2 = self.detect([(99, 99.2, 98.8, 99.1), (99.1, 99.4, 99, 99.3), (99.3, 99.6, 99.2, 99.5), (100.8, 101, 99, 100.9)])
        self.assertIn("PIN_BAR_BULL", r2)
        self.assertNotIn("HAMMER", r2)

    def test_shooting_star_morning_evening(self):
        r = self.detect([(99, 99.6, 98.9, 99.5), (99.5, 100.1, 99.4, 100), (100, 100.6, 99.9, 100.5), (100.5, 102.5, 100.4, 100.6)])
        self.assertIn("SHOOTING_STAR", r)
        r = self.detect([(102, 102.1, 100.9, 101), (101, 101.15, 100.85, 100.95), (100.95, 101.9, 100.9, 101.8)])
        self.assertIn("MORNING_STAR", r)
        r = self.detect([(100, 101.1, 99.9, 101), (101, 101.15, 100.85, 101.05), (101.05, 101.1, 100.1, 100.2)])
        self.assertIn("EVENING_STAR", r)

    def test_inside_bar_is_neutral_and_break_is_separate(self):
        r = self.detect([(100, 101, 99, 100.5), (100.4, 100.8, 99.5, 100.2)])
        self.assertEqual(r["INSIDE_BAR"]["direction"], "NEUTRAL")
        r = self.detect([(100, 101, 99, 100.5), (100.4, 100.8, 99.5, 100.2), (100.2, 101.6, 100.1, 101.4)])
        self.assertIn("INSIDE_BAR_BREAK_UP", r)

    def test_outside_doji_marubozu_tweezer_soldiers(self):
        r = self.detect([(100, 100.5, 99.5, 100.2), (99.6, 101.2, 99.3, 101.1)])
        self.assertEqual(r["OUTSIDE_BAR_EXPANSION"]["direction"], "LONG")
        r = self.detect([(100, 100.5, 99.5, 100.2), (100.1, 101, 99, 100.12)])
        self.assertIn("LONG_LEGGED_DOJI", r)
        self.assertEqual(r["LONG_LEGGED_DOJI"]["direction"], "NEUTRAL")
        r = self.detect([(100, 100.2, 99.8, 100), (100, 101.32, 99.98, 101.3)])
        self.assertEqual(r["MARUBOZU_DISPLACEMENT"]["direction"], "LONG")
        r = self.detect([(100.5, 100.6, 99.0, 99.2), (99.2, 100.4, 99.03, 100.3)])
        self.assertIn("TWEEZER_BOTTOM", r)
        r = self.detect([(100, 100.65, 99.95, 100.6), (100.3, 101.2, 100.25, 101.1), (100.9, 101.8, 100.85, 101.7)])
        self.assertIn("THREE_WHITE_SOLDIERS", r)
        r = self.detect([(101.7, 101.75, 101.0, 101.05), (101.3, 101.35, 100.5, 100.55), (100.8, 100.85, 100.0, 100.05)])
        self.assertIn("THREE_BLACK_CROWS", r)

    def test_zero_range_and_preview(self):
        self.assertEqual(self.detect([(100, 100, 100, 100), (100, 100, 100, 100)]), {})
        r = self.detect([(100, 101, 99, 100.5), (100.4, 100.8, 99.5, 100.2)], preview=True)
        self.assertEqual(r["INSIDE_BAR"]["state"], "PREVIEW")

    def test_several_names_one_evidence_event(self):
        from masterquo.analysis import candles as C
        b = bars_from_ohlc([(103, 103.2, 102, 102.2), (102.2, 102.3, 101.2, 101.4), (101.4, 101.5, 100.6, 100.8), (100.8, 101, 99, 100.9)])
        o, h, lo, c, t = [x["o"] for x in b], [x["h"] for x in b], [x["l"] for x in b], [x["c"] for x in b], [x["open_utc"] for x in b]
        pats = C.detect_at(o, h, lo, c, t, 3, 1.0, "M5", "AV")
        longs = [p for p in pats if p["direction"] == "LONG"]
        self.assertGreaterEqual(len(longs), 2)                 # PIN_BAR_BULL + HAMMER on the same bar
        ev = [e for e in C.evidence_events(pats) if e["direction"] == "LONG"]
        self.assertEqual(len(ev), 1)
        self.assertGreaterEqual(len(ev[0]["members"]), 2)


class TestChartPatterns(unittest.TestCase):
    def scan(self, bars):
        from masterquo.analysis import chart_patterns as CP
        return CP.scan(view(bars), "M5")

    def by(self, res, kind):
        return [p for p in res["patterns"] if p["type"] == kind]

    def test_double_top_forming_then_confirmed(self):
        pts = [100, 100.5, 99.8, 100.3, 99.9, 104, 101.5, 104.05, 101.8, 102.2]
        base = flat(30, 100)
        b = base + path_bars(pts, steps=4, start=T0 + timedelta(minutes=5 * 30))
        res = self.scan(b)
        dt = self.by(res, "DOUBLE_TOP")
        self.assertTrue(dt, res["patterns"])
        self.assertEqual(dt[0]["state"], "FORMING")
        self.assertEqual(dt[0]["direction_if_confirmed"], "SHORT")
        neck = dt[0]["boundary"]["neckline"]
        # detection never before the last pivot became known (pivot + 3 closed bars)
        last_anchor = max(dt[0]["anchors"], key=lambda a: a["index"])
        self.assertGreaterEqual(dt[0]["detected_at"], last_anchor["known_at"])
        more = path_bars([102.2, 100.0, 99.5], steps=4, start=T0 + timedelta(minutes=5 * len(b)))
        res2 = self.scan(b + more)
        dt2 = [p for p in self.by(res2, "DOUBLE_TOP") if p["boundary"]["neckline"] == neck]
        self.assertEqual(dt2[0]["state"], "CONFIRMED")
        self.assertGreater(dt2[0]["available_at"], dt2[0]["detected_at"])

    def test_inverse_head_shoulders(self):
        pts = [104, 101, 103, 99, 103.1, 101.1, 103.2, 104.5, 105]
        b = flat(30, 104) + path_bars(pts, steps=4, start=T0 + timedelta(minutes=150))
        res = self.scan(b)
        ihs = self.by(res, "INVERSE_HEAD_SHOULDERS")
        self.assertTrue(ihs, [p["type"] for p in res["patterns"]])
        self.assertEqual(ihs[0]["direction_if_confirmed"], "LONG")
        self.assertEqual(ihs[0]["state"], "CONFIRMED")

    def test_triangle_name_does_not_set_direction(self):
        pts = [100, 104, 101, 104, 102, 104, 103, 103.9]
        b = flat(30, 100) + path_bars(pts, steps=5, start=T0 + timedelta(minutes=150))
        res = self.scan(b)
        tri = self.by(res, "TRIANGLE_ASCENDING")
        self.assertTrue(tri, [p["type"] for p in res["patterns"]])
        self.assertIsNone(tri[0]["direction_if_confirmed"])           # no breakout yet -> no direction
        self.assertEqual(tri[0]["state"], "FORMING")

    def test_rectangle_breakout_retest_and_failed_breakout(self):
        pts = [100, 103, 100, 103, 100, 103, 100.2, 102.8]
        b = flat(30, 100) + path_bars(pts, steps=5, start=T0 + timedelta(minutes=150))
        res = self.scan(b)
        self.assertTrue(self.by(res, "RECTANGLE"), [p["type"] for p in res["patterns"]])
        up = b + path_bars([102.8, 104.2, 103.1, 104.5], steps=3, start=T0 + timedelta(minutes=5 * len(b)))
        res2 = self.scan(up)
        kinds = {p["type"] for p in res2["patterns"]}
        self.assertIn("BREAKOUT_RETEST", kinds, kinds)
        fail = b + path_bars([102.8, 104.0, 102.0], steps=2, start=T0 + timedelta(minutes=5 * len(b)))
        res3 = self.scan(fail)
        fb = self.by(res3, "FAILED_BREAKOUT_RECLAIM")
        self.assertTrue(fb, {p["type"] for p in res3["patterns"]})
        self.assertEqual(fb[0]["direction_if_confirmed"], "SHORT")

    def test_wedge_and_channel(self):
        pts = [100, 104, 101.5, 105, 103, 105.6, 104.2, 105.9, 105.0]
        res = self.scan(flat(30, 100) + path_bars(pts, steps=5, start=T0 + timedelta(minutes=150)))
        self.assertTrue(self.by(res, "WEDGE_RISING"), [p["type"] for p in res["patterns"]])
        pts = [100, 103, 101, 104, 102, 105, 103, 106, 104.5]
        res = self.scan(flat(30, 100) + path_bars(pts, steps=5, start=T0 + timedelta(minutes=150)))
        self.assertTrue(self.by(res, "CHANNEL_ASCENDING"), [p["type"] for p in res["patterns"]])

    def test_flag_after_pole(self):
        pole = path_bars([100, 108], steps=6, start=T0 + timedelta(minutes=150))
        cons = path_bars([108, 107.2, 107.8, 107.1, 107.6], steps=2, start=T0 + timedelta(minutes=150 + 30))
        res = self.scan(flat(30, 100) + pole + cons)
        self.assertTrue([p for p in res["patterns"] if p["type"].startswith(("FLAG_", "PENNANT_"))], [p["type"] for p in res["patterns"]])

    def test_random_two_points_are_not_a_pattern(self):
        import random
        rnd = random.Random(3)
        px, rows = 100.0, []
        for _ in range(160):
            nx = px + rnd.gauss(0, 0.6)
            rows.append((px, max(px, nx) + 0.2, min(px, nx) - 0.2, nx))
            px = nx
        res = self.scan(bars_from_ohlc(rows))
        for p in res["patterns"]:
            self.assertGreaterEqual(len(p["anchors"]), 2)
            self.assertTrue(p["detected_at"] >= max(a["known_at"] for a in p["anchors"]))


class TestLevelsAggregation(unittest.TestCase):
    def d1(self, start, n):
        out = []
        for i in range(n):
            t = start + timedelta(days=i)
            px = 2000 + 30 * __import__("math").sin(i / 9)
            out.append({"open_utc": iso(t - timedelta(hours=3)), "o": px, "h": px + 8, "l": px - 8, "c": px + 1, "closed": True,
                        "available_at": iso(t + timedelta(hours=21))})
        return out

    def test_month_boundary_is_calendar(self):
        from masterquo.analysis import levels as L
        bars = self.d1(datetime(2026, 1, 20, tzinfo=UTC), 30)            # Jan 20 .. Feb 18
        agg = L.aggregate_d1(bars, "MN1")
        self.assertEqual([b["period_key"] for b in agg["bars"]], ["2026-01"])     # February is still incomplete
        self.assertEqual(agg["bars"][0]["days"], 12)                              # Jan 20..31, not "30 days"
        self.assertEqual(agg["forming_period"], "2026-02")
        self.assertEqual(agg["bars"][0]["available_at"], bars[11]["available_at"])

    def test_w1_mn1_missing_history_is_no_data(self):
        from masterquo.analysis import levels as L
        from masterquo.strategies.base import MarketView, TFView
        v = MarketView(symbol="X", as_of="", tfs={"D1": TFView("D1", self.d1(datetime(2026, 9, 1, tzinfo=UTC), 25))}, bid=None, ask=None, point=0.01)
        r = L.multi_tf(v)
        self.assertEqual(r["by_tf"]["MN1"]["status"], "BRAK_DANYCH")
        self.assertEqual(r["by_tf"]["H4"]["status"], "BRAK_DANYCH")

    def test_zones_from_confirmed_pivots(self):
        from masterquo.analysis import levels as L
        pts = [100, 104, 100.2, 104.1, 100.1, 104.05, 101]
        res = L.zones_for_tf(view(path_bars(pts, steps=5), "H1"), "H1", point=0.01)
        self.assertEqual(res["status"], "OK")
        top = [z for z in res["zones"] if z["low"] > 103]
        self.assertTrue(top and top[0]["reactions"] >= 3)
        self.assertTrue(all(z["available_at"] for z in res["zones"]))


class TestRange(unittest.TestCase):
    def make(self):
        rows = []
        px = 2000.0
        for i in range(60):                                  # trending warm-up
            rows.append((px, px + 1.2, px - 0.4, px + 0.8))
            px += 0.8
        top, bot = px + 3.0, px - 3.0
        seq = [bot + 0.3, top - 0.3, bot + 0.2, top - 0.2, bot + 0.4, top - 0.4, bot + 0.3, top - 0.25, px, bot + 0.5, px, top - 0.5]
        cur = px
        for target in seq:
            for k in range(2):
                nx = cur + (target - cur) / (2 - k)
                rows.append((cur, max(cur, nx) + 0.3, min(cur, nx) - 0.3, nx))
                cur = nx
        return rows, top, bot

    def test_range_frozen_and_breakout(self):
        from masterquo.analysis import range_m5 as RG
        rows, top, bot = self.make()
        v = view(bars_from_ohlc(rows))
        r = RG.detect(v)
        self.assertEqual(r["status"], "OK", r)
        self.assertEqual(r["state"], "INSIDE")
        same = RG.detect(view(bars_from_ohlc(rows + [(rows[-1][3], rows[-1][3] + 0.3, rows[-1][3] - 0.3, rows[-1][3] + 0.1)])))
        self.assertEqual((same["top"], same["bottom"], same["range_id"]), (r["top"], r["bottom"], r["range_id"]))   # frozen
        c = rows[-1][3]
        brk = rows + [(c, r["top"] + 2.0, c - 0.1, r["top"] + 1.8), (r["top"] + 1.8, r["top"] + 2.5, r["top"] + 1.5, r["top"] + 2.2)]
        b2 = RG.detect(view(bars_from_ohlc(brk)))
        self.assertEqual(b2["state"], "BROKEN_UP")

    def test_local_m1_zones_wick_to_body(self):
        from masterquo.analysis import range_m5 as RG
        rows, top, bot = self.make()
        m5 = bars_from_ohlc(rows)
        r = RG.detect(view(m5))
        m1 = []
        for b in m5:                                         # 5 M1 bars per M5 bar: open, low, high, close path
            t0 = datetime.fromisoformat(b["open_utc"].replace("Z", "+00:00"))
            path = [b["o"], b["l"], b["h"], b["c"], b["c"], b["c"]]
            for k in range(5):
                o, c = path[k], path[k + 1]
                m1.append({"open_utc": iso(t0 + timedelta(minutes=k)), "o": o, "h": max(o, c) + 0.05, "l": min(o, c) - 0.05, "c": c, "closed": True})
        z = RG.local_zones(view(m1, "M1"), r)
        self.assertEqual(z["status"], "OK", z)
        lo = z["lower"]
        self.assertLessEqual(lo["high"] - lo["low"], 0.6 * r["atr"] + 1e-9)
        self.assertLess(lo["high"], r["mid"])
        self.assertNotEqual((lo["low"], lo["high"]), (min(b["l"] for b in m1), max(b["h"] for b in m1)))


class TestWalls(unittest.TestCase):
    class Cfg:
        source = "AUTO"
        hv_window = 20
        ks = (1.0, 2.0)
        band_sigma = 0.15

    def d1(self, n=40):
        out = []
        px = 2000.0
        for i in range(n):
            t = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(days=i)
            nx = px * (1.01 if i % 2 else 0.99)
            out.append({"open_utc": iso(t), "o": px, "h": max(px, nx) + 2, "l": min(px, nx) - 2, "c": nx, "closed": i < n - 1,
                        "available_at": iso(t + timedelta(days=1))})
            px = nx
        return out

    def test_hv_proxy_labelled_and_math(self):
        import math
        from masterquo.analysis import walls as W
        d1 = self.d1()
        now = datetime.fromisoformat(d1[-1]["open_utc"].replace("Z", "+00:00")) + timedelta(hours=2)
        s = W.build(symbol="XAUUSD-", d1_bars=d1, cfg=self.Cfg(), iv_obs=None, manual=None, now=now)
        self.assertEqual((s["status"], s["source_type"], s["day_count_basis"]), ("OK", "HV_PROXY", "TRADING_252"))
        self.assertIn("PROXY_NOT_IMPLIED_VOLATILITY", s["flags"])
        up1 = next(w for w in s["walls"] if w["side"] == "UPPER" and w["k"] == 1.0)
        exp = s["anchor_price"] * math.exp(s["sigma_annual"] * math.sqrt(1 / 252))
        self.assertAlmostEqual(up1["level"], exp, places=1)

    def test_manual_iv_stale_and_other_instrument(self):
        from masterquo.analysis import walls as W
        d1 = self.d1()
        now = datetime.fromisoformat(d1[-1]["open_utc"].replace("Z", "+00:00")) + timedelta(hours=2)
        manual = {"sigma_annual": 0.16, "day_count_basis": "ACT_365", "underlier": "GLD", "source": "GVZ", "available_at": iso(now - timedelta(days=5)),
                  "valid_until": iso(now - timedelta(days=1))}
        s = W.build(symbol="XAUUSD-", d1_bars=d1, cfg=self.Cfg(), iv_obs=None, manual=manual, now=now)
        self.assertEqual(s["source_type"], "HV_PROXY")                              # stale manual IV is not used
        self.assertIn("IV_MANUAL_STALE", s["notes"])
        manual["valid_until"] = iso(now + timedelta(days=1))
        s2 = W.build(symbol="XAUUSD-", d1_bars=d1, cfg=self.Cfg(), iv_obs=None, manual=manual, now=now)
        self.assertEqual((s2["source_type"], s2["day_count_basis"]), ("IV_MANUAL", "ACT_365"))
        self.assertIn("IV_FROM_OTHER_INSTRUMENT_PROXY", s2["flags"])
        cfg = self.Cfg()
        cfg.source = "IV_MANUAL"
        manual["valid_until"] = iso(now - timedelta(days=1))
        s3 = W.build(symbol="XAUUSD-", d1_bars=d1, cfg=cfg, iv_obs=None, manual=manual, now=now)
        self.assertIn(s3["status"], ("STALE", "UNAVAILABLE"))
        self.assertEqual(s3["walls"], [])

    def test_iv_import_units_and_duplicates(self):
        from masterquo.analysis import iv_import as I
        text = """# PRZYKŁAD
observed_at,available_at,underlier,source,sigma_annual,unit,day_count_basis,tenor_days,quality
2026-10-12T20:00:00Z,2026-10-12T20:15:00Z,GLD,GVZ close,16.4,percent,ACT_365,30,OK
2026-10-12T20:00:00Z,2026-10-12T20:15:00Z,GLD,GVZ close,16.4,percent,ACT_365,30,OK
2026-10-12T20:00:00Z,2026-10-12T20:15:00Z,GLD,X,16.4,fraction,ACT_365,30,OK
2026-10-12T20:00:00Z,2026-10-12T19:00:00Z,GLD,Y,0.16,fraction,ACT_365,30,OK
2026-10-12T20:00:00Z,2026-10-12T20:15:00Z,GLD,Z,0.16,fraction,CAL,30,OK
"""
        ok, bad = I.validate(I.parse_text(text))
        self.assertEqual(len(ok), 1)
        self.assertAlmostEqual(ok[0]["sigma_annual"], 0.164)
        reasons = sorted(b["reason"].split(":")[0] for b in bad)
        self.assertTrue(any(r.startswith("SIGMA_FRACTION_OUT_OF_RANGE") for r in reasons))
        self.assertIn("DUPLICATE", reasons)
        self.assertIn("AVAILABLE_BEFORE_OBSERVED", reasons)
        self.assertTrue(any(r.startswith("UNKNOWN_DAY_COUNT") for r in reasons))

    def test_iv_import_store_and_as_of(self):
        from masterquo.analysis import iv_import as I
        from masterquo.db.database import Database
        td = _env.TempData()
        try:
            db = Database()
            rows = [{"observed_at": "2026-10-12T20:00:00Z", "available_at": "2026-10-12T20:15:00Z", "underlier": "GLD", "source": "GVZ",
                     "sigma_annual": "16.4", "unit": "percent", "day_count_basis": "ACT_365", "tenor_days": "30", "quality": "OK"}]
            rep = I.store(db, rows)
            self.assertEqual(rep["accepted"], 1)
            self.assertEqual(I.store(db, rows)["already_stored"], 1)
            self.assertIsNone(I.latest_usable(db, "2026-10-12T20:10:00Z"))              # not yet published
            self.assertAlmostEqual(I.latest_usable(db, "2026-10-12T21:00:00Z")["sigma_annual"], 0.164)
            db.close()
        finally:
            td.close()

    def test_snapshot_frozen_new_iv_is_new_version(self):
        from masterquo.analysis import walls as W
        d1 = self.d1()
        now = datetime.fromisoformat(d1[-1]["open_utc"].replace("Z", "+00:00")) + timedelta(hours=2)
        st = W.WallsStore()
        s1 = st.freeze(W.build(symbol="XAUUSD-", d1_bars=d1, cfg=self.Cfg(), iv_obs=None, manual=None, now=now))
        again = st.freeze(W.build(symbol="XAUUSD-", d1_bars=d1, cfg=self.Cfg(), iv_obs=None, manual=None, now=now + timedelta(hours=1)))
        self.assertEqual((again["snapshot_id"], again["snapshot_version"]), (s1["snapshot_id"], 1))
        manual = {"sigma_annual": 0.30, "day_count_basis": "ACT_365", "underlier": "XAUUSD-", "available_at": iso(now), "valid_until": iso(now + timedelta(days=1))}
        s2 = st.freeze(W.build(symbol="XAUUSD-", d1_bars=d1, cfg=self.Cfg(), iv_obs=None, manual=manual, now=now + timedelta(hours=2)))
        self.assertEqual(s2["snapshot_version"], 2)
        self.assertNotEqual(s2["snapshot_id"], s1["snapshot_id"])
        self.assertEqual(s1["walls"][0]["level"], again["walls"][0]["level"])          # the old snapshot is unchanged
        m = W.mirror(s1, 4000.0)
        self.assertEqual({w["side"] for w in m["walls"]}, {"UPPER", "LOWER"})


if __name__ == "__main__":
    unittest.main()


class TestExampleIvFile(unittest.TestCase):
    def test_example_file_is_valid_and_marked(self):
        from masterquo.analysis import iv_import as I
        text = (_env.ROOT / "docs" / "przyklad_iv_import.csv").read_text(encoding="utf-8")
        self.assertIn("PRZYKŁAD", text)
        ok, bad = I.validate(I.parse_text(text))
        self.assertEqual((len(ok), bad), (2, []))
