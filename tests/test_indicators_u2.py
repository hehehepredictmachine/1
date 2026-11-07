"""1.33 U2 - PMW-IND-1 indicators: contract, AVWAP, spread percentile, semivariance, XAUUSD-DXY relation, OFI / book, RVOL in DSVIE,
IndicatorService on the FakeMT5 bridge (feed -> computation -> API) and the read-only guarantee (no order_send)."""
import json
import math
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _env  # noqa: F401
from _env import TempData, core, wait_for

T0 = datetime(2026, 3, 2, 0, 0, tzinfo=timezone.utc).timestamp()      # Monday 00:00 UTC


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def bars(n, tf_s=60, t0=T0, close=None, tv=None, rv=None, start=100.0, skip=()):
    out = []
    for i in range(n):
        if i in skip:
            continue
        c = close(i) if close else start + i * 0.1
        o = c - 0.05
        out.append({"open_utc": iso(t0 + i * tf_s), "o": o, "h": max(o, c) + 0.1, "l": min(o, c) - 0.1, "c": c,
                    "tv": tv(i) if tv else 10, "rv": rv(i) if rv else 0, "closed": True, "available_at": iso(t0 + (i + 1) * tf_s)})
    return out


class TestContract(unittest.TestCase):
    def test_required_fields_and_none_not_zero(self):
        from masterquo.indicators import contract as C
        r = C.result("X", "V1", instrument="XAUUSD", broker_symbol="XAUUSD-", source="T", timeframe="M1", values={"a": float("nan"), "b": 0.0,
                     "c": True}, status="READY")
        self.assertEqual(C.validate(r), [])
        self.assertIsNone(r["values"]["a"])                      # NaN never leaks as a number
        self.assertEqual(r["values"]["b"], 0.0)                  # a real 0 stays a value
        self.assertIs(r["values"]["c"], True)
        w = C.result("X", "V1", instrument="XAUUSD", broker_symbol=None, source="T", timeframe=None, status="WARMUP")
        self.assertEqual(w["reason"], "WARMUP")
        self.assertIsNone(C.value(w, "a"))
        with self.assertRaises(ValueError):
            C.result("X", "V1", instrument="XAUUSD", broker_symbol=None, source="T", timeframe=None, status="MAYBE")

    def test_config_hash_changes_with_instrument_meta(self):
        from masterquo.indicators import contract as C
        self.assertNotEqual(C.config_hash({"a": 1}, {"tick": 0.01}), C.config_hash({"a": 1}, {"tick": 0.001}))


class TestAVWAP(unittest.TestCase):
    def test_hand_computed_example(self):
        from masterquo.indicators import avwap as AV
        b = [{"open_utc": iso(T0 + i * 60), "h": h, "l": l, "c": c, "tv": w, "rv": 0, "closed": True}
             for i, (h, l, c, w) in enumerate([(11, 9, 10, 1), (13, 11, 12, 3)])]
        pts, src, zero = AV.line(b, T0)
        self.assertEqual(src, "TICK_VOLUME")
        self.assertAlmostEqual(pts[-1]["avwap"], (10 * 1 + 12 * 3) / 4)          # typical = 10 and 12
        self.assertAlmostEqual(pts[-1]["sigma"], math.sqrt((1 * (10 - 11.5) ** 2 + 3 * (12 - 11.5) ** 2) / 4))

    def test_incremental_equals_full(self):
        from masterquo.indicators import avwap as AV
        b = bars(80, tv=lambda i: 1 + (i * 7) % 5, close=lambda i: 100 + math.sin(i / 5))
        acc = AV.Accumulator()
        for i, x in enumerate(b):
            acc.add(AV._price(x, "TYPICAL"), AV._weight(x, "TICK_VOLUME"))
            full, _, _ = AV.line(b[: i + 1], T0)
            m, sd = acc.value()
            self.assertAlmostEqual(m, full[-1]["avwap"], places=10)
            self.assertAlmostEqual(sd, full[-1]["sigma"], places=8)

    def test_zero_weights_not_ready(self):
        from masterquo.indicators import avwap as AV
        b = bars(30, tv=lambda i: 0)
        a = AV.manual_anchor(b[0]["open_utc"], iso(T0))
        r = AV.compute(b, "M1", a, as_of=T0 + 31 * 60, instrument="XAUUSD")
        self.assertNotEqual(r["status"], "READY")
        self.assertIsNone(r["values"].get("avwap"))

    def test_exchange_volume_not_mixed_with_tick_volume(self):
        from masterquo.indicators import avwap as AV
        b = bars(10, tv=lambda i: 100, rv=lambda i: 0 if i == 3 else 5)
        pts, src, zero = AV.line(b, T0)
        self.assertEqual(src, "EXCHANGE_VOLUME")
        self.assertEqual(zero, 1)                                          # bar without real volume weighs 0, tick volume is not used

    def test_late_confirmation_anchor_unknown_before(self):
        from masterquo.indicators import avwap as AV
        b = bars(40)
        a = {"mode": "EVENT", "kind": "BOS_UP", "source_time": b[5]["open_utc"], "confirmed_at": iso(T0 + 30 * 60), "anchor_id": "A"}
        early = AV.compute(b, "M1", a, as_of=T0 + 20 * 60, instrument="XAUUSD")
        self.assertEqual(early["status"], "WARMUP")
        self.assertEqual(early["reason"], "ANCHOR_NOT_CONFIRMED_YET")
        late = AV.compute(b, "M1", a, as_of=T0 + 40 * 60, instrument="XAUUSD", with_line=True)
        self.assertEqual(late["status"], "READY")
        self.assertEqual(late["line"][0]["t"], b[5]["open_utc"])         # drawn back from the source point after confirmation

    def test_event_anchor_from_structure_engine_is_causal(self):
        from masterquo.indicators import avwap as AV
        wave = lambda i: 100 + 3 * math.sin(i / 6) + i * 0.02          # noqa: E731
        b = bars(300, close=wave)
        as_of = T0 + 300 * 60
        a = AV.event_anchor(b, 60, as_of)
        self.assertIsNotNone(a)
        self.assertLessEqual(datetime.fromisoformat(a["confirmed_at"].replace("Z", "+00:00")).timestamp(), as_of)
        self.assertLessEqual(a["source_time"], a["confirmed_at"])
        cut = AV.event_anchor(b, 60, as_of - 120 * 60)                # earlier as_of: never an event confirmed later
        if cut is not None:
            self.assertLessEqual(datetime.fromisoformat(cut["confirmed_at"].replace("Z", "+00:00")).timestamp(), as_of - 120 * 60)

    def test_cross_and_retest_events(self):
        from masterquo.indicators import avwap as AV
        pts = [{"t": "1", "avwap": 10, "close": 9.5, "low": 9.4, "high": 9.8}, {"t": "2", "avwap": 10, "close": 10.5, "low": 10.1, "high": 10.6},
               {"t": "3", "avwap": 10, "close": 10.4, "low": 10.02, "high": 10.5}]
        ev = AV.events(pts, 1.0, 0.1)
        self.assertEqual([e["kind"] for e in ev], ["CROSS_UP", "RETEST_UP"])


class TestSpread(unittest.TestCase):
    def setUp(self):
        from masterquo.indicators import spread as SP
        self.SP = SP
        self.pid = "LAB_XAU_REFERENCE_V1"

    def _samples(self, days, spread_of):
        out = []
        for d in range(days):
            t = T0 + d * 86400 + 9 * 3600 + 60                       # inside LONDON (08:00 London = 08:00 UTC in March before DST)
            for k in range(5):
                ss = self.SP.session_slot(self.pid, t + k * 10, 30)
                out.append({"t": t + k * 10, "spread": spread_of(d), **ss})
        return out

    def test_reference_only_from_past_sessions_one_value_each(self):
        smp = self._samples(8, lambda d: 0.10 + 0.01 * d)
        now = T0 + 7 * 86400 + 9 * 3600 + 200                           # day 7 = current instance
        ss = self.SP.session_slot(self.pid, now, 30)
        ref = self.SP.reference(smp, session=ss["session"], slot=ss["slot"], before_instance_start=ss["instance_start"])
        self.assertEqual(len(ref), 7)                                      # day 7 excluded (own instance), one median per day
        self.assertNotIn(0.17, [round(r, 2) for r in ref])

    def test_percentile_min_sessions_and_no_double_cost(self):
        smp = self._samples(8, lambda d: 0.10 + 0.01 * d)
        now = T0 + 7 * 86400 + 9 * 3600 + 200
        q = {"bid": 2000.0, "ask": 2000.2, "time_utc": iso(now - 1), "received_at": iso(now - 0.5)}
        r = self.SP.compute(q, smp, now=now, instrument="XAUUSD", broker_symbol="XAUUSD-", profile_id=self.pid, tick=0.01, min_sessions=5)
        self.assertEqual(r["status"], "READY")
        self.assertEqual(r["values"]["percentile"], 100.0)
        self.assertTrue(r["values"]["spread_in_prices"])
        self.assertAlmostEqual(r["values"]["spread_ticks"], 20.0)
        self.assertAlmostEqual(r["values"]["receive_delay_s"], 0.5)
        r2 = self.SP.compute(q, smp, now=now, instrument="XAUUSD", broker_symbol="XAUUSD-", profile_id=self.pid, tick=0.01, min_sessions=10)
        self.assertEqual(r2["status"], "WARMUP")
        self.assertIsNone(r2["values"]["percentile"])

    def test_stale_quote(self):
        now = T0 + 9 * 3600
        q = {"bid": 1.0, "ask": 1.1, "time_utc": iso(now - 120), "received_at": iso(now - 119)}
        r = self.SP.compute(q, [], now=now, instrument="XAUUSD", broker_symbol="X", profile_id=self.pid, tick=0.01)
        self.assertEqual(r["status"], "STALE")

    def test_percentile_mid_rank(self):
        self.assertEqual(self.SP.percentile(2, [1, 2, 3, 4]), 37.5)
        self.assertIsNone(self.SP.percentile(2, []))


class TestSemivariance(unittest.TestCase):
    def test_sum_equals_realised_variance(self):
        from masterquo.indicators import semivar as SV
        b = bars(80, close=lambda i: 100 * math.exp(0.001 * math.sin(i)))
        r = SV.compute(b, "M1", as_of=T0 + 81 * 60, instrument="XAUUSD")
        self.assertEqual(r["status"], "READY")
        rets = SV.returns(b, 60)[-20:]
        self.assertAlmostEqual(r["values"]["rs_up_20"] + r["values"]["rs_down_20"], sum(x["r"] ** 2 for x in rets), delta=1e-16)
        self.assertAlmostEqual(r["values"]["rv_20"], sum(x["r"] ** 2 for x in rets), delta=1e-16)
        self.assertEqual(r["values"]["window_s_60"], 3600)

    def test_zero_movement_and_gaps(self):
        from masterquo.indicators import semivar as SV
        flat = bars(80, close=lambda i: 100.0)
        r = SV.compute(flat, "M1", as_of=T0 + 81 * 60, instrument="XAUUSD")
        self.assertIsNone(r["values"]["downside_share_20"])
        self.assertIn(20, r["zero_movement_windows"])
        gap = bars(80, skip=set(range(30, 40)))
        skip = SV.returns(gap, 60, gap_mode="SKIP")
        flag = SV.returns(gap, 60, gap_mode="FLAG")
        self.assertEqual(len(flag) - len(skip), 1)
        self.assertTrue(any(x["gap"] for x in flag))
        short = SV.compute(bars(30), "M1", as_of=T0 + 31 * 60, instrument="XAUUSD")
        self.assertEqual(short["status"], "WARMUP")
        self.assertIsNone(short["values"]["rs_up_60"])


def h1(n, ret, t0=T0, skip=(), start=100.0):
    out, c = [], start
    for i in range(n):
        c = c * math.exp(ret(i))
        if i in skip:
            continue
        out.append({"open_utc": iso(t0 + i * 3600), "o": c, "h": c, "l": c, "c": c, "closed": True, "available_at": iso(t0 + (i + 1) * 3600)})
    return out


class TestDXY(unittest.TestCase):
    def setUp(self):
        from masterquo.indicators import dxy as DX
        self.DX = DX
        self.as_of = T0 + 300 * 3600

    def _run(self, x, d, **kw):
        return self.DX.compute(x, d, as_of=kw.pop("as_of", self.as_of), instrument="XAUUSD", broker_symbol="XAUUSD-", dxy_symbol="DXY", **kw)

    def test_sign_follows_synthetic_relation(self):
        z = lambda i: 0.001 * math.sin(i * 1.7) + 0.0005 * math.cos(i * 0.3)   # noqa: E731
        d = h1(300, z)
        neg = self._run(h1(300, lambda i: -2 * z(i)), d)
        pos = self._run(h1(300, lambda i: 0.5 * z(i)), d)
        self.assertEqual(neg["status"], "READY")
        self.assertLess(neg["values"]["corr_72"], -0.99)
        self.assertAlmostEqual(neg["values"]["beta_72"], -2.0, places=6)
        self.assertGreater(pos["values"]["corr_72"], 0.99)
        self.assertEqual(neg["values"]["sign"], "NEGATIVE")

    def test_no_forward_fill(self):
        z = lambda i: 0.001 * math.sin(i * 1.3)                       # noqa: E731
        d = h1(300, z, skip=set(range(100, 110)))
        obs = self.DX.joint(h1(300, z), d, self.as_of)
        ts = {o[0] for o in obs}
        for i in range(100, 111):                                     # a missing hour removes its own return and the next one
            self.assertNotIn(T0 + i * 3600, ts)
        self.assertEqual(len(obs), 299 - 11)

    def test_beta_excludes_current_observation(self):
        z = lambda i: 0.001 * math.sin(i * 1.7)                       # noqa: E731
        x = h1(300, lambda i: -z(i) + (0.05 if i == 299 else 0.0))    # shock only in the newest hour
        r = self._run(x, h1(300, z))
        st = r["windows"]["72"]
        self.assertAlmostEqual(st["fit_beta"], -1.0, places=6)        # the fit never saw the shock
        self.assertAlmostEqual(r["values"]["resid_72"], 0.05, places=6)
        self.assertNotEqual(st["fit_to"], iso(T0 + 299 * 3600))

    def test_zero_variance_stale_missing(self):
        flat = h1(300, lambda i: 0.0)
        r = self._run(h1(300, lambda i: 0.001 * math.sin(i)), flat)
        self.assertIsNone(r["values"]["beta_72"])
        self.assertEqual(r["windows"]["72"]["reason"], "DXY_ZERO_VARIANCE")
        old = self._run(h1(300, lambda i: 0.001), h1(200, lambda i: 0.001))   # DXY stops 100 h before as_of
        self.assertEqual(old["status"], "STALE")
        self.assertEqual(self.DX.feature_context(old)["status"], "STALE")
        none = self.DX.compute([], [], as_of=self.as_of, instrument="XAUUSD", broker_symbol=None, dxy_symbol=None)
        self.assertEqual(none["status"], "DISABLED")
        nob = self._run(h1(10, lambda i: 0.0), [])
        self.assertEqual(nob["status"], "NO_DATA")

    def test_feature_context_feeds_dxy_missing(self):
        from masterquo.ml import features as F
        z = lambda i: 0.001 * math.sin(i)                             # noqa: E731
        r = self._run(h1(300, z), h1(300, z))
        ctx = self.DX.feature_context(r)

        class V:
            context = {"dxy": ctx}
        self.assertEqual(F.dxy_missing(V, datetime.fromtimestamp(self.as_of, timezone.utc)), 0.0)
        V.context = {"dxy": self.DX.feature_context(None)}
        self.assertEqual(F.dxy_missing(V, datetime.fromtimestamp(self.as_of, timezone.utc)), 1.0)


class TestOFI(unittest.TestCase):
    def book(self, t, pb, qb, pa, qa):
        return {"t": t, "bids": [(pb, qb)], "asks": [(pa, qa)]}

    def test_ofi_cases(self):
        from masterquo.indicators import ofi as OF
        b0 = self.book(0, 10.0, 5, 10.1, 4)
        self.assertEqual(OF.ofi_step(b0, self.book(1, 10.0, 7, 10.1, 4)), 2)          # bid size +2
        self.assertEqual(OF.ofi_step(b0, self.book(1, 10.0, 5, 10.1, 6)), -2)         # ask size +2
        self.assertEqual(OF.ofi_step(b0, self.book(1, 10.05, 3, 10.1, 4)), 3)         # bid price up: whole new bid size
        self.assertEqual(OF.ofi_step(b0, self.book(1, 9.95, 3, 10.1, 4)), -5)         # bid level removed: old size leaves
        self.assertEqual(OF.ofi_step(b0, self.book(1, 10.0, 5, 10.15, 2)), 4)         # ask level removed
        self.assertEqual(OF.ofi_step(b0, self.book(1, 10.0, 5, 10.05, 2)), -2)        # ask price down: whole new ask size

    def test_imbalance_microprice_and_zero_sizes(self):
        from masterquo.indicators import ofi as OF
        b = {"t": 0, "bids": [(10.0, 3), (9.9, 1)], "asks": [(10.2, 1), (10.3, 1)]}
        self.assertAlmostEqual(OF.best_imbalance(b), 0.5)
        self.assertAlmostEqual(OF.depth_imbalance(b, 5), 1 / 3)
        mp, mid = OF.microprice(b)
        self.assertAlmostEqual(mp, (10.2 * 3 + 10.0 * 1) / 4)
        self.assertAlmostEqual(mid, 10.1)
        z = self.book(0, 10, 0, 10.1, 0)
        self.assertIsNone(OF.best_imbalance(z))
        self.assertIsNone(OF.microprice(z)[0])

    def test_gap_and_symbol_change_reset(self):
        from masterquo.indicators import ofi as OF
        acc = OF.OFIAccumulator(max_gap_s=5)
        acc.add(self.book(0, 10, 5, 10.1, 4), key="A")
        acc.add(self.book(1, 10, 7, 10.1, 4), key="A")
        self.assertEqual(acc.view()["ofi"], 2)
        acc.add(self.book(20, 10, 9, 10.1, 4), key="A")                               # gap 19 s -> reset, change NOT summed
        self.assertEqual(acc.view()["ofi"], 0)
        self.assertTrue(acc.last_reset.startswith("GAP"))
        acc.add(self.book(21, 10, 9, 10.1, 4), key="B")
        self.assertEqual(acc.last_reset, "SYMBOL_OR_SESSION_CHANGE")
        self.assertEqual(acc.view()["mode"], "SAMPLED(1s)")
        self.assertTrue(acc.view()["estimate"])

    def test_no_dom_does_not_vote(self):
        from masterquo.indicators import ofi as OF
        r = OF.compute(None, OF.OFIAccumulator(), instrument="XAUUSD", broker_symbol="X", status="NO_DATA", reason=None)
        self.assertEqual(r["status"], "NO_DATA")
        self.assertEqual(r["reason"], "Brak danych arkusza")
        self.assertEqual(r["values"], {})

    def test_normalize_mt5_rows(self):
        from masterquo.indicators import ofi as OF
        from masterquo.mt5.fake import BookInfo
        b = OF.normalize([BookInfo(1, 10.2, 1, 1.0), BookInfo(1, 10.1, 2, 2.0), BookInfo(2, 10.0, 3, 3.0)], 5.0)
        self.assertEqual(b["asks"][0], (10.1, 2.0))
        self.assertEqual(b["bids"][0], (10.0, 3.0))
        self.assertIsNone(OF.normalize([BookInfo(2, 10.0, 3, 3.0)], 5.0))


class TestRelativeVolume(unittest.TestCase):
    def test_rvol_reports_sessions_rejects_incomplete_and_interval_variant(self):
        from masterquo.config import ZonesConfig
        from masterquo.zones import dsvie as DS
        from masterquo.zones.series import Series
        tf_s = 300
        n = 12 * 24 * 6
        b = [{"open_utc": iso(T0 + i * tf_s), "o": 100, "h": 100.5, "l": 99.5, "c": 100, "tv": (50 if (i // 288) == 5 else 10), "rv": 0,
              "closed": True} for i in range(n) if not (384 <= i < 394)]       # day 1: 08:00-08:50 UTC missing (complete session, short start)
        s = Series.from_bars(b, "M5")
        cfg = ZonesConfig(relvol_min_sessions=2, relvol_min_coverage=0.8)
        as_of = T0 + 5 * 86400 + 12 * 3600
        ps = DS.session_profiles(s, "LAB_XAU_REFERENCE_V1", "XAUUSD", cfg, as_of, "TICK_VOLUME")
        dev = [p for p in ps if p["state"] == "DEVELOPING"]
        self.assertTrue(dev)
        p = dev[-1]
        self.assertGreater(p["relative_volume"], 4.0)
        self.assertGreaterEqual(p["relative_volume_rejected_sessions"], 1)              # incomplete day rejected
        self.assertGreaterEqual(p["relative_volume_baseline_sessions"], 2)
        self.assertIsNotNone(p["interval_relative_volume"])
        strict = DS.session_profiles(s, "LAB_XAU_REFERENCE_V1", "XAUUSD", ZonesConfig(relvol_min_sessions=50), as_of, "TICK_VOLUME")
        sp = [x for x in strict if x["state"] == "DEVELOPING"][-1]
        self.assertIsNone(sp["relative_volume"])
        self.assertTrue(sp["relative_volume_reason"])


class TestServiceOnFakeBridge(unittest.TestCase):
    """Feed (FakeMT5 through the real MT5 worker queue) -> IndicatorService -> context / API; no order is ever sent."""

    def setUp(self):
        self.td = TempData()
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.b = core()
        self.b.start()
        self.assertTrue(wait_for(lambda: self.b.state == "CONNECTED" and self.b.quote_status() and self.b.bars("M1"), 40))
        sent = []
        self.fake.order_send = lambda *a, **k: sent.append(a) or None
        self.sent = sent

    def tearDown(self):
        self.b.stop()
        self.worker.stop()
        self.td.close()

    def svc(self):
        from masterquo.indicators.service import IndicatorService
        return IndicatorService(self.cfg, self.b, data_dir=Path(self.td.dir) / "ind")

    def test_snapshot_book_context_and_read_only(self):
        from masterquo.indicators import contract as C
        s = self.svc()
        now = time.time()
        for k in range(3):
            s.tick(now + k * 11)
        self.assertEqual(s.book.status, "READY")                       # FakeMT5 serves a market depth through the call queue
        self.assertIsNotNone(s.book.last)
        snap = s.refresh(time.time())                                   # book timestamps are wall clock
        for key in ("semivar", "spread", "dxy", "profile", "microstructure"):
            self.assertEqual(C.validate(snap[key]), [], key)
        for tf in ("M1", "M5"):
            for mode in ("SESSION", "EVENT"):
                self.assertEqual(C.validate(snap["avwap"][tf][mode]), [], (tf, mode))
        self.assertEqual(snap["dxy"]["status"], "DISABLED")            # no dxy_symbol configured: explicit degraded mode
        self.assertEqual(snap["microstructure"]["status"], "READY")
        ctx = s.context(None, {})
        self.assertEqual(ctx["dxy"]["status"], "DISABLED")
        self.assertIn("avwap", ctx["indicators"])
        json.dumps(snap, allow_nan=False, default=str)
        self.assertEqual(self.sent, [])
        s.stop()
        self.assertEqual(s.book.status, "NOT_SUBSCRIBED")

    def test_no_dom_symbol(self):
        self.fake.book_available = False
        s = self.svc()
        s.tick(time.time())
        snap = s.refresh()
        self.assertEqual(snap["microstructure"]["status"], "NO_DATA")
        self.assertEqual(snap["microstructure"]["extra"] if "extra" in snap["microstructure"] else snap["microstructure"]["label"],
                         "Brak danych arkusza")

    def test_manual_anchor_versioning_and_persistence(self):
        s = self.svc()
        m1 = self.b.bars("M1", include_forming=False)
        a = s.add_manual_anchor("M1", m1[-30]["open_utc"], "test")
        snap = s.refresh()
        man = snap["avwap"]["M1"]["MANUAL"]
        self.assertEqual(len(man), 1)
        self.assertEqual(man[0]["anchor"]["anchor_id"], a["anchor_id"])
        s2 = self.svc()                                                 # restart: anchors persist
        self.assertEqual([x["anchor_id"] for x in s2.manual_anchors("M1")], [a["anchor_id"]])
        self.assertTrue(s2.remove_manual_anchor(a["anchor_id"]))
        self.assertEqual(s2.manual_anchors("M1"), [])
        self.assertEqual(s._version("k", "A1"), 1)
        self.assertEqual(s._version("k", "A1"), 1)
        self.assertEqual(s._version("k", "A2"), 2)                     # anchor change = new version


class TestAgentTools(unittest.TestCase):
    def test_tools_read_frozen_snapshot_only(self):
        from masterquo.agent import tools as AT
        names = {t["name"] for t in AT.TOOL_DEFS}
        self.assertIn("get_pmw_indicators", names)
        self.assertIn("get_dxy_relation", names)
        out, err = AT.Toolbox({}, 3).run("get_dxy_relation", {})
        self.assertFalse(err)
        self.assertEqual(json.loads(out)["status"], "UNAVAILABLE")
        snap = {"version": "V", "dxy": {"status": "STALE", "reason": "DXY_AGE", "values": {"corr_72": None}}, "avwap": {"M1": {"SESSION": {"status": "READY"},
                "MANUAL": []}}, "semivar": {"status": "READY", "values": {}}}
        r = json.loads(AT.Toolbox({"pmw_indicators": snap}, 3).run("get_dxy_relation", {})[0])
        self.assertEqual(r["status"], "STALE")
        r = json.loads(AT.Toolbox({"pmw_indicators": snap}, 3).run("get_pmw_indicators", {})[0])
        self.assertEqual(r["avwap"]["M1"]["SESSION"]["status"], "READY")


if __name__ == "__main__":
    unittest.main()
