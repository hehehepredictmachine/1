"""PMW-UPD-06 Session Sweep Boxes + Liquidation Heatmap. SYNTHETIC_TEST fixtures only (logic, not provider compatibility or edge).
Case ids follow the specification list (11.1-11.12)."""
from __future__ import annotations

import io
import json
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData

UTC = timezone.utc


def m5(start: datetime, n: int, hi=101.0, lo=99.0, c=100.0, step=5):
    return [{"open_utc": (start + timedelta(minutes=step * k)).isoformat(), "o": c, "h": hi, "l": lo, "c": c} for k in range(n)]


class TestSessionEngine(unittest.TestCase):
    def setUp(self):
        from masterquo.analytics import session_engine as se
        self.se = se

    def box(self, boxes, session):
        return [b for b in boxes if b["session"] == session][-1]

    def test_single_bar_is_not_final_regression(self):                 # 11.2 confirmed bug 1
        bars = m5(datetime(2026, 1, 15, 9, 0, tzinfo=UTC), 1)
        b = self.box(self.se.build(bars, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 12, 5, tzinfo=UTC), days=0), "LONDON")
        self.assertEqual((b["state"], b["observed_slots"], b["expected_slots"]), ("INCOMPLETE", 1, 48))
        self.assertIsNone(b["final_high"])
        from masterquo.scalp import sessions
        legacy = {x["session"]: x for x in sessions.boxes_as_of(bars, 5, "2026-01-15T12:05:00Z")}
        self.assertEqual(legacy["LONDON"]["status"], "INCOMPLETE")                                  # not "OK" any more

    def test_both_edges_one_bar_is_ambiguous_regression(self):          # 11.3 confirmed bug 2
        bars = m5(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), 48) + [{"open_utc": "2026-01-15T12:00:00+00:00", "o": 100, "h": 102.0, "l": 98.0, "c": 100.0}]
        b = self.box(self.se.build(bars, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 12, 10, tzinfo=UTC), days=0), "LONDON")
        self.assertEqual(b["state"], "FINAL")
        self.assertEqual([e["kind"] for e in b["events"]], ["SWEEP_BOTH_AMBIGUOUS"])
        self.assertEqual(b["events"][0]["intrabar_order"], "UNKNOWN")
        self.assertEqual((b["edges"]["HIGH"]["state"], b["edges"]["LOW"]["state"]), ("SWEPT", "SWEPT"))
        from masterquo.scalp import sessions
        self.assertEqual({x["session"]: x for x in sessions.boxes_as_of(bars, 5, "2026-01-15T12:10:00Z")}["LONDON"]["state"], "SWEEP_BOTH_AMBIGUOUS")

    def test_edge_events_breakout_return_equal_and_ttl(self):            # 11.3
        base = m5(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), 48)
        t = lambda m: (datetime(2026, 1, 15, 12, 0, tzinfo=UTC) + timedelta(minutes=m)).isoformat()   # noqa: E731
        ev = lambda bars: self.box(self.se.build(base + bars, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 13, tzinfo=UTC), days=0), "LONDON")  # noqa: E731
        self.assertEqual([e["kind"] for e in ev([{"open_utc": t(0), "o": 100, "h": 101.0, "l": 99.5, "c": 100}])["events"]], [])       # high == H: no sweep
        self.assertEqual([e["kind"] for e in ev([{"open_utc": t(0), "o": 100, "h": 100.5, "l": 98.5, "c": 99.5}])["events"]], ["SWEEP_LOW"])
        b = ev([{"open_utc": t(0), "o": 100, "h": 101.8, "l": 100, "c": 101.5}, {"open_utc": t(5), "o": 101, "h": 101.6, "l": 100.2, "c": 100.5},
                {"open_utc": t(10), "o": 100, "h": 101.9, "l": 100, "c": 100.4}])
        self.assertEqual([e["kind"] for e in b["events"]], ["BREAKOUT_UP", "RETURN_INSIDE_AFTER_BREAK"])       # never re-labelled as a sweep
        self.assertEqual(b["edges"]["HIGH"]["state"], "BROKEN")
        later = self.box(self.se.build(base, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 17, 0, tzinfo=UTC), days=2), "LONDON")
        b16 = [x for x in self.se.build(base, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 17, 0, tzinfo=UTC), days=2) if x["box_id"].endswith("LONDON:2026-01-15")][0]
        self.assertEqual(b16["edges"]["HIGH"]["state"], "EXPIRED")                                                 # TTL = next London start
        self.assertTrue(later)

    def test_developing_known_at_profiles_and_boundaries(self):        # 11.1 / 11.2
        bars = m5(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), 20)
        dev = self.box(self.se.build(bars, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 9, 40, tzinfo=UTC), days=0), "LONDON")
        self.assertEqual(dev["state"], "DEVELOPING")
        self.assertIsNone(dev["final_high"])
        self.assertIsNone(dev["known_at"])
        late = [dict(b, available_at="2026-01-15T12:30:00+00:00") if b["open_utc"].startswith("2026-01-15T11:55") else b for b in m5(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), 48)]
        k = self.box(self.se.build(late, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 12, 40, tzinfo=UTC), days=0), "LONDON")
        self.assertEqual(k["known_at"], "2026-01-15T12:30:00+00:00")                                             # delayed data -> later known_at
        self.assertEqual(self.box(self.se.build(late, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 12, 10, tzinfo=UTC), days=0), "LONDON")["state"],
                         "INCOMPLETE")
        ny = self.se.windows("LAB_XAU_REFERENCE_V1", datetime(2026, 1, 15, 12, tzinfo=UTC), 0, 0)
        w = [x for x in ny if x["session"] == "NEW_YORK"][0]
        self.assertEqual((w["start"].hour, w["start"].minute), (13, 20))                                          # 08:20 New York (EST)
        bars_ny = m5(datetime(2026, 1, 15, 13, 15, tzinfo=UTC), 3)
        b = self.box(self.se.build(bars_ny, 300, "LAB_XAU_REFERENCE_V1", "XAUUSD", datetime(2026, 1, 15, 13, 40, tzinfo=UTC), days=0), "NEW_YORK")
        self.assertEqual(b["observed_slots"], 2)                                                                  # 13:15 bar crosses 13:20 -> excluded
        a1 = self.se.build(bars, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 9, 40, tzinfo=UTC), days=0)
        a2 = self.se.build(bars, 300, "LAB_XAU_REFERENCE_V1", "XAUUSD", datetime(2026, 1, 15, 9, 40, tzinfo=UTC), days=0)
        self.assertNotEqual({x["box_id"] for x in a1}, {x["box_id"] for x in a2})
        self.assertEqual(a1, self.se.build(bars, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 9, 40, tzinfo=UTC), days=0))
        p = dict(self.se.PROFILES["SCALP_OPENING_V1"])
        self.se.PROFILES["TEST_MIDNIGHT"] = dict(p, sessions=[("NIGHT", "UTC", "22:00", "02:00")])
        try:
            w = self.se.windows("TEST_MIDNIGHT", datetime(2026, 1, 15, 23, tzinfo=UTC), 0, 0)[0]
            self.assertEqual((w["start"].isoformat(), w["end"].isoformat()), ("2026-01-15T22:00:00+00:00", "2026-01-16T02:00:00+00:00"))
        finally:
            self.se.PROFILES.pop("TEST_MIDNIGHT")

    def test_dst_weeks(self):                                            # 11.4
        w = lambda d, s: [x for x in self.se.windows("SCALP_OPENING_V1", d, 0, 0) if x["session"] == s][0]["start"].hour   # noqa: E731
        self.assertEqual((w(datetime(2026, 1, 15, 12, tzinfo=UTC), "LONDON"), w(datetime(2026, 7, 15, 12, tzinfo=UTC), "LONDON")), (8, 7))
        self.assertEqual((w(datetime(2026, 3, 4, 15, tzinfo=UTC), "NEW_YORK"), w(datetime(2026, 3, 11, 15, tzinfo=UTC), "NEW_YORK")), (13, 12))   # US DST 8 Mar
        self.assertEqual(w(datetime(2026, 3, 11, 12, tzinfo=UTC), "LONDON"), 8)                                    # EU still winter (29 Mar)

    def test_prefix_invariance(self):                                   # 11.5
        import numpy as np
        rng = np.random.default_rng(3)
        bars, c = [], 100.0
        t0 = datetime(2026, 1, 12, 0, tzinfo=UTC)
        for k in range(4 * 288):
            o = c
            c += rng.normal(0, 0.3)
            bars.append({"open_utc": (t0 + timedelta(minutes=5 * k)).isoformat(), "o": o, "h": max(o, c) + 0.2, "l": min(o, c) - 0.2, "c": c})
        full = self.se.build(bars, 300, "SCALP_OPENING_V1", "XAUUSD", t0 + timedelta(days=4), days=4)
        for cut_h in (30, 55, 80):
            T = t0 + timedelta(hours=cut_h)
            pre = self.se.build([b for b in bars if datetime.fromisoformat(b["open_utc"]) < T], 300, "SCALP_OPENING_V1", "XAUUSD", T, days=4)
            for b in pre:
                if b["state"] != "FINAL":
                    continue
                f = next(x for x in full if x["box_id"] == b["box_id"])
                self.assertEqual((f["final_high"], f["final_low"], f["revision"]), (b["final_high"], b["final_low"], b["revision"]))
                known = [e for e in f["events"] if datetime.fromisoformat(e["available_at"]) <= T]
                self.assertEqual([e["event_id"] for e in known], [e["event_id"] for e in b["events"]])


def model1(n_t=4, prices=(100.0, 101.0, 102.0, 103.0), cells=None, ms=False):
    times = [1_760_000_000 + 300 * i for i in range(n_t)]
    return {"y_axis": list(prices), "liquidation_leverage_data": cells if cells is not None else [[i, j, float(1 + i + 10 * j)] for i in range(n_t) for j in range(len(prices))],
            "price_candlesticks": [[t * 1000 if ms else t, 1, 1, 1, 1, 1] for t in times]}


class TestHeatmapContract(unittest.TestCase):
    def test_parser_validation(self):                                    # 11.6
        from masterquo.analytics.liquidation import contract as c
        g = c.parse_model1(model1())
        self.assertEqual((g["data_kind"], g["time_axis_status"], g["intensity_unit"]), ("ESTIMATED_LIQUIDATION_LEVELS", "OK", "provider_intensity"))
        self.assertEqual(c.parse_model1(model1(ms=True))["times"], g["times"])                                   # ms == s
        self.assertEqual(g["price_edges"], [99.5, 100.5, 101.5, 102.5, 103.5])
        bad = [(dict(model1(), y_axis=[100, 99, 101, 102]), "UNSUPPORTED_SCHEMA"), (model1(cells=[[0, 0, 1.0], [0, 0, 2.0]]), "DUPLICATE_CELL"),
               (model1(cells=[[0, 0, -1.0]]), "INVALID_INTENSITY"), (model1(cells=[[0, 0, float("nan")]]), "INVALID_INTENSITY"),
               (model1(cells=[[0, 9, 1.0]]), "INDEX_OUT_OF_RANGE"), (model1(cells=[[7, 0, 1.0]]), "INDEX_OUT_OF_RANGE"),
               (dict(model1(), y_axis=[]), "EMPTY"), (dict(model1(), price_candlesticks=[[5, 1], [4, 1], [6, 1], [7, 1]]), "TIME_AXIS_UNVERIFIED")]
        for body, code in bad:
            with self.assertRaises(c.HeatmapError) as cm:
                c.parse_model1(body)
            self.assertEqual(cm.exception.code, code)
        with self.assertRaises(c.HeatmapError):
            c.parse_model1(model1(), max_cells=3)
        no_t = c.parse_model1({k: v for k, v in model1().items() if k != "price_candlesticks"})
        self.assertEqual(no_t["time_axis_status"], "TIME_AXIS_UNVERIFIED")
        self.assertEqual(c.zones(no_t)["status"], "TIME_AXIS_UNVERIFIED")

    def test_zones(self):                                                # 11.9
        from masterquo.analytics.liquidation import contract as c
        z = c.zones(c.parse_model1(model1()))
        self.assertEqual(z["status"], "OK")
        self.assertEqual((z["zones"][0]["low"], z["zones"][0]["high"], z["zones"][0]["rank"]), (102.5, 103.5, 1))
        flat = c.parse_model1(model1(cells=[[3, j, 5.0] for j in range(4)]))
        self.assertEqual(c.zones(flat)["status"], "NO_DISCRIMINATING_RANK")                                     # no artificial strong zone


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestProvider(unittest.TestCase):                                   # 11.7
    def test_requests_and_errors(self):
        from masterquo.analytics.liquidation import provider as pv
        seen = {}

        def ok(req, timeout):
            seen["url"], seen["hdr"] = req.full_url, dict(req.header_items())
            return FakeResp(json.dumps({"code": "0", "msg": "success", "data": model1()}).encode())
        r = pv.fetch("AGGREGATED", "BTC", "24h", None, "SECRET-123", opener=ok)
        self.assertIn("/aggregated-heatmap/model1?symbol=BTC&range=24h", seen["url"])
        self.assertNotIn("SECRET", seen["url"])
        self.assertNotIn("SECRET", json.dumps(r["request"]))
        pv.fetch("PAIR", "BTCUSDT", "3d", "Binance", "k", opener=ok)
        self.assertIn("/liquidation/heatmap/model1?symbol=BTCUSDT&range=3d&exchange=Binance", seen["url"])
        cases = [(lambda q, timeout: FakeResp(json.dumps({"code": "40001", "msg": "Upgrade plan required"}).encode()), "ENTITLEMENT_REQUIRED"),
                 (lambda q, timeout: FakeResp(json.dumps({"code": "0", "data": None}).encode()), "UNSUPPORTED_INSTRUMENT")]
        for code, exp in ((401, "UNAUTHORIZED"), (403, "ENTITLEMENT_REQUIRED"), (429, "RATE_LIMITED")):
            def err(q, timeout, code=code):
                raise urllib.error.HTTPError(q.full_url, code, "x", {"Retry-After": "7"}, None)
            cases.append((err, exp))

        def to(q, timeout):
            raise TimeoutError()
        cases.append((to, "TIMEOUT"))
        for op, exp in cases:
            with self.assertRaises(pv.ProviderError) as cm:
                pv.fetch("AGGREGATED", "BTC", "24h", None, "k", opener=op)
            self.assertEqual(cm.exception.code, exp)
            if exp == "RATE_LIMITED":
                self.assertEqual(cm.exception.retry_after, 7.0)
        with self.assertRaises(pv.ProviderError) as cm:
            pv.fetch("AGGREGATED", "BTC", "24h", None, None)
        self.assertEqual(cm.exception.code, "MISSING_API_KEY")


class TestArchiveService(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        self.cs = ConfigStore()
        self.cs.update({"liquidity": {"sources": {"BTC": {"enabled": True, "source_symbol": "BTC", "variant": "AGGREGATED", "range": "24h"}}}})
        self.db = Database()

    def tearDown(self):
        self.td.close()

    def svc(self, fetcher=None):
        from masterquo.analytics.liquidation.service import LiquidityService
        return LiquidityService(self.cs, self.db, None, None, secrets=type("S", (), {"get": lambda s, n: "k", "source": lambda s, n: "LOCAL_STORE"})(), fetcher=fetcher)

    def test_point_in_time_and_no_double_counting(self):                # 11.8 / 11.9
        s = self.svc()
        src = self.cs.get().liquidity.sources["BTC"]
        A = model1()
        B = model1(cells=[[i, j, 99.0 if i == 0 else float(1 + i + 10 * j)] for i in range(4) for j in range(4)])   # rewrites an OLD column
        a = s.ingest("BTC", src, A, origin="API", received_at="2026-10-19T10:00:00+00:00")
        self.assertEqual(s.ingest("BTC", src, A, origin="API", received_at="2026-10-19T10:00:30+00:00")["status"], "UNCHANGED")   # same estimate again
        b = s.ingest("BTC", src, B, origin="API", received_at="2026-10-19T11:00:00+00:00")
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM liq_heatmap_snapshots")["n"], 2)
        self.assertEqual(s.as_of("BTC", "2026-10-19T10:30:00+00:00")["snapshot_id"], a["snapshot_id"])
        self.assertEqual(s.as_of("BTC", "2026-10-19T11:30:00+00:00")["snapshot_id"], b["snapshot_id"])
        self.assertIsNone(s.as_of("BTC", "2026-10-19T09:00:00+00:00"))
        row = self.db.one("SELECT first_received_at, last_seen_at FROM liq_heatmap_snapshots WHERE snapshot_id=?", (a["snapshot_id"],))
        self.assertEqual((row["first_received_at"], row["last_seen_at"]), ("2026-10-19T10:00:00+00:00", "2026-10-19T10:00:30+00:00"))
        z = s.as_of("BTC")["zones"]
        self.assertEqual(z["zones"][0]["max_intensity"], 34.0)                                                   # not summed across polls
        hp = s.heatmap_public("BTC", None, 3)
        self.assertEqual(hp["zones"], s.heatmap_public("BTC", None, 20000)["zones"])                             # LOD never changes zones
        self.assertEqual((hp["axis"].split(" ")[0], hp["mapping_status"], hp["source_instrument"]["symbol"], hp["target_instrument"]),
                         ("SOURCE_PRICE", "MAPPING_UNVALIDATED", "BTC", "BTC"))
        x = s.heatmap_public("XAUUSD")
        self.assertEqual(x["status"], "NO_SOURCE_FOR_INSTRUMENT")                                               # no gold map invented

    def test_file_import_trust_and_poll_errors(self):
        from masterquo.analytics.liquidation import provider as pv
        s = self.svc()
        (s.inbox() / "x.json").write_text(json.dumps({"schema": "pmw-liq-export-1", "target_asset": "BTC", "variant": "AGGREGATED", "source_symbol": "BTC",
                                                        "range": "24h", "declared_received_at": "2025-01-01T00:00:00Z", "data": model1(n_t=3)}))
        (s.inbox() / "bad.json").write_text("{not json")
        res = s.scan_inbox()
        self.assertEqual(sorted(r["status"] for r in res), ["OK", "REJECTED"])
        row = self.db.one("SELECT * FROM liq_heatmap_snapshots WHERE origin='FILE'")
        self.assertEqual(row["availability_trust"], "DECLARED_UNVERIFIED")
        self.assertGreater(row["first_received_at"], "2026")                                                    # import time, not the declared old date
        calls = []

        def boom(*a):
            calls.append(1)
            raise pv.ProviderError("ENTITLEMENT_REQUIRED", "plan")
        s2 = self.svc(fetcher=boom)
        self.assertEqual(len(s2.poll_once(0.0)), 1)
        self.assertEqual(s2.poll_once(1.0), [])                                                                  # backoff, no request storm
        st = self.db.one("SELECT * FROM liq_source_status")
        self.assertEqual(st["status"], "ENTITLEMENT_REQUIRED")
        self.assertEqual(len(calls), 1)


class TestPolicyAndKnowledge(unittest.TestCase):                         # 11.10
    def final_box(self, kind=None, **ev):
        from masterquo.analytics import session_engine as se
        bars = m5(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), 48)
        if kind:
            bars += [dict({"open_utc": "2026-01-15T12:00:00+00:00", "o": 100}, **ev)]
        return [b for b in se.build(bars, 300, "SCALP_OPENING_V1", "XAUUSD", datetime(2026, 1, 15, 12, 10, tzinfo=UTC), days=0) if b["session"] == "LONDON"]

    def test_scenarios(self):
        from masterquo.analytics import liquidity_context as lc
        codes = lambda r: [c["code"] for c in r["reason_codes"]]  # noqa: E731
        r = lc.evaluate(boxes=self.final_box("x", h=100.5, l=98.5, c=99.8), heatmap=None, price=99.9, atr_m5=1.0, setup={"side": "BUY", "setup_id": "S"},
                        as_of="2026-01-15T12:10:00+00:00")
        self.assertIn("SESSION_LOW_REJECTION", codes(r))
        self.assertTrue(r["supporting_evidence_families"])
        self.assertTrue(any("silnika scalp" in m for m in r["missing_conditions"]))
        self.assertEqual((r["mode"], r["validation_status"]), ("OBSERVE", "NO_VALIDATED_EDGE"))
        self.assertIn("LIQ_CONTEXT_UNKNOWN", codes(r))                                                         # no map -> unknown, not empty market
        r = lc.evaluate(boxes=self.final_box("x", h=101.8, l=100, c=101.6), heatmap=None, price=101.6, atr_m5=1.0, setup={"side": "SELL"}, as_of="2026-01-15T12:10:00+00:00")
        self.assertIn("SESSION_BREAKOUT_CONTEXT", codes(r))
        self.assertTrue(r["conflicting_evidence_families"])                                                     # breakout up never a SELL fade
        r = lc.evaluate(boxes=self.final_box("x", h=102, l=98, c=100), heatmap=None, price=100, atr_m5=1.0, as_of="2026-01-15T12:10:00+00:00")
        self.assertIn("SESSION_BOTH_SIDES_AMBIGUOUS", codes(r))
        early = lc.evaluate(boxes=self.final_box("x", h=100.5, l=98.5, c=99.8), heatmap=None, price=99.9, atr_m5=1.0, as_of="2026-01-15T12:04:00+00:00")
        self.assertNotIn("SESSION_LOW_REJECTION", codes(early))                                                 # not available before confirmation
        hm = {"status": "OK", "zones": {"zones": [{"low": 99.5, "high": 100.5, "rank": 1, "relative": 1.0, "max_intensity": 5}]}, "mapping_status": "MAPPING_UNVALIDATED",
              "source_instrument": {"symbol": "XAUT"}, "target_instrument": "XAUUSD"}
        r = lc.evaluate(boxes=[], heatmap=hm, price=100.0, atr_m5=1.0)
        self.assertIn("LIQ_ESTIMATED_ZONE", codes(r))
        self.assertNotIn("LIQ_ZONE_CONTACT", codes(r))                                                          # unmapped XAUT never on the broker axis
        self.assertEqual(r["reason_codes"][0]["axis"], "SOURCE_PRICE")

    def test_knowledge_loaded_and_frozen_tool(self):
        from masterquo.agent.service import load_prompt
        from masterquo.agent.tools import Toolbox
        from masterquo.analytics import liquidity_context as lc
        body, ver = load_prompt()
        self.assertIn("LQ-K13", body)
        self.assertIn("+" + lc.KNOWLEDGE_VERSION, ver)
        fz = lc.frozen(self.final_box("x", h=100.5, l=98.5, c=99.8), None, 99.9, 1.0, "2026-01-15T12:10:00+00:00", max_events=1)
        tb = Toolbox.__new__(Toolbox)
        tb.ctx = {"liquidity_context": fz}
        out = tb.t_get_liquidity_context("M5")
        self.assertEqual(out["boxes"][0]["box_id"], fz["boxes"][0]["box_id"])
        self.assertLessEqual(len(out["events"]), 1)
        self.assertEqual(out["events_total"], 1)


class TestEvaluation(unittest.TestCase):                                 # 11.12
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        import sys
        sys.modules.pop("MetaTrader5", None)
        self.td.close()

    def test_fixture_b0_b3(self):
        import sys
        from masterquo.mt5.fake import FakeMT5
        sys.modules["MetaTrader5"] = FakeMT5()
        from masterquo.forecast.export import export_candles
        ds = Path(self.td.dir) / "ds"
        self.assertEqual(export_candles(1, str(ds), "AUTO", ("M1", "M5", "M15", "M30", "H1"), "training", "XAUUSD", "XAUUSD-"), 0)
        from masterquo.analytics import liquidity_eval as le
        from masterquo.analytics.liquidation.service import LiquidityService
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        db = Database()
        rep = le.evaluate("XAUUSD", ds, commission=0.5, db=db, liquidity=LiquidityService(ConfigStore(), db, None, None), log=lambda m: None)
        v = rep["variants"]
        self.assertEqual(v["B0"]["status"], "FIXTURE_ONLY")
        self.assertEqual((v["B2"]["status"], v["B3"]["status"]), ("BLOCKED", "BLOCKED"))
        self.assertEqual(rep["heatmap_status"], "NO_SOURCE_FOR_INSTRUMENT")
        self.assertLessEqual(v["B1"]["full"]["trades"], v["B0"]["full"]["trades"] + v["B1"]["rejected_by_variant"])
        self.assertEqual(v["B0"]["rejected_by_variant"], 0)


if __name__ == "__main__":
    unittest.main()
