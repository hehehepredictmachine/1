"""1.10 strategy family S12 (RANGE_RECLAIM / WALL_REJECTION / BREAKOUT_RETEST + arbiter) on SYNTHETIC minute paths.
Code checks only - no evidence of a positive expectancy. No orders, no terminal."""
from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone

import _env  # noqa: F401

UTC = timezone.utc
T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
C0 = 2001.0          # range centre
HALF = 3.0           # range half-height -> 1998 .. 2004


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def minute_path(tail: list[tuple[float, float]] | None = None, *, warm=300, rng_min=150):
    """List of (price, tick_volume) per minute: gentle up-trend warm-up, a sine range 1998-2004 (period 30 min), then `tail`."""
    pts = []
    for i in range(warm):
        pts.append((1985 + 16 * i / warm + 0.4 * math.sin(i / 3), 100))
    for i in range(rng_min):
        pts.append((C0 + HALF * math.sin(2 * math.pi * i / 30), 100))
    return pts + (tail or [])


def m1_bars(pts, wick=0.08):
    out = []
    prev = pts[0][0]
    for k, (px, tv) in enumerate(pts):
        o, c = prev, px
        out.append({"open_utc": iso(T0 + timedelta(minutes=k)), "o": o, "h": max(o, c) + wick, "l": min(o, c) - wick, "c": c, "tv": tv,
                    "closed": True})
        prev = px
    return out


def ohlc(m1, override=None):
    """Explicit per-minute OHLC overrides {index: (o, h, l, c, tv)}."""
    for k, v in (override or {}).items():
        o, h, lo, c, tv = v
        m1[k].update(o=o, h=h, l=lo, c=c, tv=tv)
    return m1


def agg(m1, n=5):
    out = []
    for s in range(0, len(m1) - len(m1) % n, n):
        g = m1[s:s + n]
        out.append({"open_utc": g[0]["open_utc"], "o": g[0]["o"], "h": max(x["h"] for x in g), "l": min(x["l"] for x in g), "c": g[-1]["c"],
                    "tv": sum(x["tv"] for x in g), "closed": True})
    return out


def walls_snap(levels, *, avail="2026-10-11T22:00:00Z", until="2026-10-13T22:00:00Z", sid="WS-1", ver=1):
    ws = [{"wall_id": f"W-{side}-{k}", "side": side, "k": k, "level": lvl, "low": lvl - 0.3, "high": lvl + 0.3, "snapshot_id": sid}
          for side, k, lvl in levels]
    return {"status": "OK", "version": "MQ-WALLS-1.0.0", "source_type": "HV_PROXY", "walls": ws, "available_at": avail, "valid_until": until,
            "anchor_time": "2026-10-11T22:00:00Z", "anchor_price": 2006.0, "snapshot_id": sid, "snapshot_version": ver}


def make_view(m1, walls=None, spread=0.1):
    from masterquo.strategies import adapter
    m5 = agg(m1)
    last = m1[-1]
    v = adapter.build_view(symbol="XAUUSD-", bars_by_tf={"M1": m1, "M5": m5}, bid=last["c"], ask=last["c"] + spread, point=0.01,
                           as_of=iso(datetime.fromisoformat(last["open_utc"].replace("Z", "+00:00")) + timedelta(minutes=1)), synthetic=True,
                           max_bars=700)
    v.context = {"walls": walls} if walls is not None else {}
    return v


def s12():
    from masterquo.strategies.registry import STRATEGIES, params_for
    return STRATEGIES["S12"], params_for("S12", None)


def reclaim_tail(*, trigger_tv=400, close_above=1998.9, body_ok=True, sweep=True):
    """After the range: drift to the bottom, a sweep below the local zone, then a strong M1 close back above the zone."""
    tail = []
    px = C0 + HALF * math.sin(2 * math.pi * 150 / 30)
    for k in range(10):                                 # down to ~1998.3
        px -= (px - 1998.3) / (10 - k)
        tail.append((px, 100))
    tail.append((1997.6 if sweep else 1998.2, 100))     # sweep / contact
    tail.append((1998.1, 100))
    return tail, close_above, trigger_tv, body_ok


def build_reclaim(trigger_tv=400, close_above=1998.9, body_ok=True, sweep=True, extra_tail=None):
    tail, ca, tv, ok = reclaim_tail(trigger_tv=trigger_tv, close_above=close_above, body_ok=body_ok, sweep=sweep)
    pts = minute_path(tail + (extra_tail or []))
    m1 = m1_bars(pts)
    last_c = m1[-1]["c"]
    lo = last_c - 0.05
    if ok:
        m1.append({"open_utc": iso(T0 + timedelta(minutes=len(m1))), "o": last_c, "h": ca + 0.05, "l": lo, "c": ca, "tv": tv, "closed": True})
    else:
        m1.append({"open_utc": iso(T0 + timedelta(minutes=len(m1))), "o": last_c, "h": ca + 1.5, "l": lo - 1.0, "c": ca, "tv": tv, "closed": True})
    return m1


def mirror_m1(m1, c=2001.0):
    k = 2 * c
    return [dict(b, o=k - b["o"], h=k - b["l"], l=k - b["h"], c=k - b["c"]) for b in m1]


class TestRangeReclaim(unittest.TestCase):
    def test_long_reclaim_with_wall_is_trigger(self):
        s, p = s12()
        m1 = build_reclaim()
        v = make_view(m1, walls_snap([("LOWER", 1.0, 1998.0), ("UPPER", 1.0, 2010.0)]))
        out = s.detect(v, p)
        d = next((x for x in out if x.direction == "LONG"), None)
        self.assertIsNotNone(d, s.last_rejections)
        f = d.facts
        self.assertEqual(f["variant"], "RANGE_RECLAIM", f)
        self.assertEqual(d.phase, "TRIGGER", d.missing)
        self.assertEqual(f["range_state"], "INSIDE")                       # local reclaim, NOT a breakout of the whole range
        self.assertLess(d.stop_loss, f["zone_low_px"])
        self.assertAlmostEqual(d.targets[0]["price"], f["range_mid_px"], places=4)
        self.assertTrue(f["sweep"])
        self.assertEqual(f["wall_id"], "W-LOWER-1.0")
        self.assertLessEqual(f["zone_high_px"] - f["zone_low_px"], 0.6 * 3.5)
        self.assertIn("WS-1", d.structure_key)                              # snapshot id is part of the scenario identity
        names = [r["name"] for r in f["checklist"]]
        for must in ("Reżim rynku", "Wall – źródło i aktualność", "Zakres M5 (konsolidacja)", "Aktywność (tick volume brokera)", "RR (brutto, wstępnie)"):
            self.assertIn(must, names)
        self.assertTrue(all(r["status"] in ("SPEŁNIONY", "NIESPEŁNIONY", "OCZEKIWANIE", "BRAK DANYCH", "NIE DOTYCZY", "ODCZYT") for r in f["checklist"]))
        self.assertEqual(d.exit_rules["time_exit_bars"], p["time_exit_m1"])

    def test_short_reclaim_mirrored(self):
        s, p = s12()
        m1 = mirror_m1(build_reclaim())
        v = make_view(m1, walls_snap([("UPPER", 1.0, 2004.0), ("LOWER", 1.0, 1992.0)]))
        out = s.detect(v, p)
        d = next((x for x in out if x.direction == "SHORT"), None)
        self.assertIsNotNone(d, s.last_rejections)
        self.assertEqual((d.facts["variant"], d.phase), ("RANGE_RECLAIM", "TRIGGER"), d.missing)
        self.assertGreater(d.stop_loss, d.facts["zone_high_px"])
        self.assertLess(d.facts["zone_low_px"], d.facts["zone_high_px"])
        self.assertEqual(d.facts["wall_id"], "W-UPPER-1.0")
        self.assertTrue(all(t["price"] < d.stop_loss for t in d.targets))

    def test_touch_without_trigger_close(self):
        s, p = s12()
        tail, *_ = reclaim_tail()
        m1 = m1_bars(minute_path(tail))
        out = s.detect(make_view(m1, walls_snap([("LOWER", 1.0, 1998.0)])), p)
        d = next(x for x in out if x.direction == "LONG")
        self.assertNotEqual(d.phase, "TRIGGER")
        self.assertIn("NO_CLOSED_TRIGGER", d.missing)

    def test_weak_and_missing_volume_and_filter_off(self):
        s, p = s12()
        w = walls_snap([("LOWER", 1.0, 1998.0)])
        d = next(x for x in s.detect(make_view(build_reclaim(trigger_tv=100), w), p) if x.direction == "LONG")
        self.assertIn("VOLUME_NOT_CONFIRMED", d.missing)
        self.assertNotEqual(d.phase, "TRIGGER")
        m1 = build_reclaim()
        for b in m1:
            b["tv"] = 0
        d = next(x for x in s.detect(make_view(m1, w), p) if x.direction == "LONG")
        self.assertIn("ACTIVITY_NO_DATA", d.missing)                          # no data is never "met"
        self.assertEqual(next(r for r in d.facts["checklist"] if r["name"].startswith("Aktywność"))["status"], "BRAK DANYCH")
        p2 = dict(p, activity_filter="OFF")
        d = next(x for x in s.detect(make_view(m1, w), p2) if x.direction == "LONG")
        self.assertEqual(d.phase, "TRIGGER", d.missing)                       # explicit research variant without the filter

    def test_entry_in_middle_and_too_late(self):
        s, p = s12()
        d = next(x for x in s.detect(make_view(build_reclaim(close_above=2001.6), walls_snap([("LOWER", 1.0, 1998.0)])), p) if x.direction == "LONG")
        self.assertTrue({"PRICE_IN_MIDDLE", "ENTRY_TOO_LATE"} & set(d.missing), d.missing)
        self.assertNotEqual(d.phase, "TRIGGER")

    def test_walls_missing_stale_misaligned_and_baseline(self):
        s, p = s12()
        m1 = build_reclaim()
        d = next(x for x in s.detect(make_view(m1, walls_snap([("LOWER", 1.0, 1990.0)])), p) if x.direction == "LONG")
        self.assertIn("NO_WALL_ALIGNMENT", d.missing)
        d = next(x for x in s.detect(make_view(m1, walls_snap([("LOWER", 1.0, 1998.0)], until="2026-10-12T01:00:00Z")), p) if x.direction == "LONG")
        self.assertIn("WALL_STALE", d.missing)
        d = next(x for x in s.detect(make_view(m1, None), p) if x.direction == "LONG")
        self.assertIn("NO_WALL_ALIGNMENT", d.missing)
        d = next(x for x in s.detect(make_view(m1, None), dict(p, use_walls=False)) if x.direction == "LONG")
        self.assertEqual((d.facts["variant"], d.phase), ("RANGE_RECLAIM_BASE", "TRIGGER"), d.missing)     # baseline, honestly named
        self.assertFalse(d.facts["uses_walls"])

    def test_new_walls_snapshot_is_new_scenario(self):
        s, p = s12()
        m1 = build_reclaim()
        a = next(x for x in s.detect(make_view(m1, walls_snap([("LOWER", 1.0, 1998.0)], sid="WS-1")), p) if x.direction == "LONG")
        b = next(x for x in s.detect(make_view(m1, walls_snap([("LOWER", 1.0, 1998.1)], sid="WS-2", ver=2)), p) if x.direction == "LONG")
        self.assertNotEqual(a.structure_key, b.structure_key)
        self.assertEqual(a.stop_loss, b.stop_loss)


class TestBreakoutAndRejection(unittest.TestCase):
    def breakout_m1(self, retest=True, fail=False):
        tail = []
        px = C0 + HALF * math.sin(2 * math.pi * 150 / 30)
        for k in range(6):                                   # up to the top
            px += (2004.2 - px) / (6 - k)
            tail.append((px, 100))
        for k in range(10):                                  # accepted breakout: closes well above 2004
            tail.append((2005.0 + 0.25 * k, 300))
        if retest:
            for k in range(8):
                tail.append((2007.2 - (2007.2 - 2004.3) * (k + 1) / 8, 120))
            for k in range(3):
                tail.append((2004.5 + 0.05 * k, 120))
        if fail:
            for k in range(8):
                tail.append((2003.0 - 0.1 * k, 150))
        m1 = m1_bars(minute_path(tail))
        if retest and not fail:
            c = m1[-1]["c"]
            m1.append({"open_utc": iso(T0 + timedelta(minutes=len(m1))), "o": c, "h": 2005.65, "l": c - 0.05, "c": 2005.6, "tv": 500, "closed": True})
        return m1

    def test_breakout_retest_trigger(self):
        s, p = s12()
        v = make_view(self.breakout_m1(), walls_snap([("UPPER", 1.0, 2004.4), ("LOWER", 1.0, 1990.0)]))
        out = s.detect(v, p)
        d = next((x for x in out if x.direction == "LONG"), None)
        self.assertIsNotNone(d, s.last_rejections)
        self.assertEqual(d.facts["variant"], "BREAKOUT_RETEST", (d.facts, d.missing))
        self.assertIn(d.phase, ("TRIGGER", "EARLY"))
        self.assertGreater(d.targets[0]["price"], d.facts["range_top_px"])
        self.assertEqual(d.facts["range_state"], "BROKEN_UP")

    def test_failed_breakout_rejected(self):
        s, p = s12()
        v = make_view(self.breakout_m1(retest=False, fail=True), None)
        s.detect(v, dict(p, use_walls=False))
        self.assertIn("FAILED_BREAKOUT", s.last_rejections["LONG"].get("BREAKOUT_RETEST", []))

    def test_wall_rejection_m5(self):
        s, p = s12()
        tail = []
        px = C0 + HALF * math.sin(2 * math.pi * 150 / 30)
        for k in range(15):
            px -= 0.55
            tail.append((px, 100))
        for k in range(5):                                   # pierce the wall level 1993.0 and come back
            tail.append((1992.6 + 0.05 * k, 100))
        m1 = m1_bars(minute_path(tail))
        m1 = m1[:len(m1) - len(m1) % 5]
        # final M5 bar: strong close back above the wall zone (1993.3)
        c0 = m1[-1]["c"]
        for k, (o, c) in enumerate([(c0, 1993.0), (1993.0, 1993.4), (1993.4, 1993.8), (1993.8, 1994.2), (1994.2, 1994.6)]):
            m1.append({"open_utc": iso(T0 + timedelta(minutes=len(m1))), "o": o, "h": c + 0.05, "l": o - 0.05, "c": c, "tv": 600, "closed": True})
        v = make_view(m1, walls_snap([("LOWER", 1.0, 1993.0), ("UPPER", 1.0, 2010.0)]))
        out = s.detect(v, dict(p, variants=["WALL_REJECTION"]))
        d = next((x for x in out if x.direction == "LONG"), None)
        self.assertIsNotNone(d, s.last_rejections)
        self.assertEqual(d.facts["variant"], "WALL_REJECTION")
        self.assertEqual(d.timeframe, "M5")
        self.assertLess(d.stop_loss, 1993.0)
        self.assertNotIn("NO_CLOSED_TRIGGER", d.missing)

    def test_conflict_reduces_both_to_watch(self):
        from masterquo.strategies.base import Draft
        s, _ = s12()
        mk = lambda side: {"variant": "X", "draft": Draft(strategy_id="S12", direction=side, timeframe="M1", phase="TRIGGER", structure_key="k", event_key="e",  # noqa: E731
                                                            anchor_time=None, entry_plan=None, invalidation_level=None, facts={"variant": "X"})}

        class V:
            regime = {"state": "RANGE"}
        s_out = s._arbiter(V(), [dict(mk("LONG"), variant="RANGE_RECLAIM")], [dict(mk("SHORT"), variant="BREAKOUT_RETEST")])
        self.assertEqual({d.phase for d in s_out}, {"WATCH"})
        self.assertTrue(all("CONFLICT_REJECTION_VS_BREAKOUT" in d.missing for d in s_out))


class TestS12Integration(unittest.TestCase):
    def test_registry_scan_and_config(self):
        from masterquo.config import AppConfig
        from masterquo.strategies import registry
        cfg = AppConfig()
        self.assertFalse(cfg.active.strategies["S12"].trade)              # scan only until the user enables trading
        self.assertIn("S12", registry.DEFAULT_NO_TRADE)
        cfg2 = AppConfig.model_validate({"active": {"manual_strategy_id": "S12"}})
        self.assertEqual(cfg2.active.manual_strategy_id, "S12")
        with self.assertRaises(Exception):
            AppConfig.model_validate({"active": {"manual_strategy_id": "S99"}})
        v = make_view(build_reclaim(), walls_snap([("LOWER", 1.0, 1998.0)]))
        res = registry.scan(v, enabled={sid: sid == "S12" for sid in registry.STRATEGIES}, overrides={}, thresholds=cfg.active.thresholds.model_dump(),
                            account_key="T")
        self.assertEqual(res["per_strategy"]["S12"]["status"], "OK")
        c = [x for x in res["candidates"] if x["strategy_id"] == "S12"]
        self.assertTrue(c or res["per_strategy"]["S12"].get("below_watch"))

    def test_policy_and_labels_agree_for_s12_plan(self):
        from masterquo.execution import policy as P
        from masterquo.ml import labels as lb
        s, p = s12()
        d = next(x for x in s.detect(make_view(build_reclaim(), walls_snap([("LOWER", 1.0, 1998.0)])), p) if x.direction == "LONG")
        pol = P.from_plan(side="LONG", stop_loss=d.stop_loss, targets=d.targets, exit_rules=d.exit_rules, timeframe=d.timeframe)
        spec = lb.make_spec({"direction": "LONG", "stop_loss": d.stop_loss, "targets": d.targets, "timeframe": d.timeframe, "exit_rules": d.exit_rules},
                            "2026-10-12T08:00:00Z", spread=0.1, slippage=0.0, commission=0.0, cost_flags=[])
        self.assertEqual(spec["horizon_minutes"], pol["time_exit_minutes"])
        self.assertEqual([t["price"] for t in spec["targets"]], [t["price"] for t in pol["targets"]])
        self.assertEqual(spec["be_after_tp1"], pol["be_after_tp1"])


if __name__ == "__main__":
    unittest.main()


class TestS12LivePipeline(unittest.TestCase):
    """Real engine on the SYNTHETIC terminal: walls snapshot (HV proxy) reaches the scan, S12 runs, structure endpoint data."""
    setUp = None

    def setUp(self):  # noqa: F811
        import test_active_pipeline
        test_active_pipeline.TestActivePipeline.setUp(self)
        from masterquo.engine.walls_service import WallsService
        self.walls = WallsService(self.cfg, self.db, self.b)
        self.engine.active.context_fn = self.walls.context

    def tearDown(self):
        import test_active_pipeline
        test_active_pipeline.TestActivePipeline.tearDown(self)

    def test_engine_scan_with_walls_and_structure(self):
        self.engine.full_cycle()
        ps = self.engine.active.scan_result["per_strategy"]["S12"]
        self.assertIn(ps["status"], ("OK", "WARMING_UP", "DATA_MISSING"), ps)
        snap = self.walls.last
        self.assertIn(snap["status"], ("OK", "MARKET_CLOSED", "BRAK_DANYCH"), snap)
        if snap["status"] == "OK":
            self.assertEqual(snap["source_type"], "HV_PROXY")            # no IV source configured -> proxy, labelled as such
            self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM walls_snapshots")["n"], 1)
            self.engine.full_cycle()
            self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM walls_snapshots")["n"], 1)   # frozen: no new version without new input
        st = self.engine.structure("M5")
        self.assertEqual(st["status"], "OK")
        for k in ("sr", "range", "chart", "candles", "pivots", "walls"):
            self.assertIn(k, st)
        self.assertTrue(all(p["known_at"] > p["t"] for p in st["pivots"]))   # a pivot is known only after its right bars
        self.assertIn(st["sr"]["by_tf"]["MN1"]["status"], ("OK", "BRAK_DANYCH"))
        self.assertEqual(self.db.query("SELECT * FROM order_attempts"), [])
