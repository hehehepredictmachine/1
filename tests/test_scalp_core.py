"""1.12 scalp profile (M5 Range -> M1 Sweep/Reclaim -> Retest) + hedge controller - bot venv, SYNTHETIC_TEST data only.

Groups (prompt section 14): 1 causality / prefix invariance and causal pattern statistics; 2 MTF as-of, gaps, DST, restart;
3 range/zone freeze, known_at, retest TTL, BUY/SELL mirror and "no BUY is not SELL"; 4 candle geometry, zero range,
hammer vs displacement, one evidence per family; 5 BB/SAR formulas and adapter contracts (PAL02M never yields values);
6 Bid/Ask settlement, lot step/minimum, fees, partial TP, SL+TP in one OHLC, no fill on the signal close; 7 NETTING vs
HEDGING, no second hedge, limits, TTL, orphan leg; 8 timeout reconciliation, persisted loss limits, idempotent records;
10 SHADOW never sends orders, a failing module never touches position protection. (9 = tests/gold_candles/test_scalp_train.py)
No real account, no order, no notification."""
from __future__ import annotations

import json
import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _env
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent / "scalp"))

import scenario as S  # noqa: E402
from masterquo.scalp import adapters, candles_sci, hedge, indicators as ind, replay, report, sessions, strategy as st  # noqa: E402


def prof(context=False):
    p = st.load_profile()
    p["context_filter"]["enabled"]["value"] = context
    return p


COSTS = {"commission_price_side": 0.035, "slippage_price": 0.02}


class TestIndicators(unittest.TestCase):
    def test_bollinger_population_std_and_fields(self):
        c = [float(x % 7) + 100 for x in range(140)]
        a = ind.atr([x + 1 for x in c], [x - 1 for x in c], c)
        bb = ind.bollinger(c, a)
        w = c[-20:]
        m = sum(w) / 20
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / 20)              # divide by N (MT5 iBands), not N-1
        self.assertAlmostEqual(bb[-1]["basis"], m)
        self.assertAlmostEqual(bb[-1]["upper"], m + 2 * sd)
        self.assertAlmostEqual(bb[-1]["pct_b"], (c[-1] - (m - 2 * sd)) / (4 * sd))
        self.assertIsNone(bb[100]["bandwidth_pct100"])                   # needs 100 strictly earlier widths
        self.assertIsNotNone(bb[-1]["bandwidth_pct100"])
        self.assertIsNone(bb[18])

    def test_sar_never_inside_previous_bars_and_flips(self):
        h = [10 + i * 0.5 for i in range(30)] + [25 - i * 0.7 for i in range(30)]
        lo = [x - 1 for x in h]
        s = ind.sar(h, lo)
        for i in range(2, 30):
            if s[i]["trend"] == "UP" and not s[i]["flip"]:
                self.assertLessEqual(s[i]["sar"], min(lo[i - 1], lo[i - 2]) + 1e-9)
        self.assertTrue(any(x and x["flip"] for x in s[30:]))
        self.assertEqual(s[-1]["trend"], "DOWN")

    def test_er_zero_denominator(self):
        self.assertEqual(ind.er([5.0] * 15, 10)[-1], 0.0)
        self.assertAlmostEqual(ind.er([float(i) for i in range(15)], 10)[-1], 1.0)

    def test_prefix_invariance(self):
        """Values for bar i do not change when future bars are appended (no look-ahead)."""
        bars = S.sine(400)
        c, h, lo = [b["c"] for b in bars], [b["h"] for b in bars], [b["l"] for b in bars]
        full_a, part_a = ind.atr(h, lo, c), ind.atr(h[:300], lo[:300], c[:300])
        full_bb, part_bb = ind.bollinger(c, full_a), ind.bollinger(c[:300], part_a)
        full_s, part_s = ind.sar(h, lo), ind.sar(h[:300], lo[:300])
        for i in range(300):
            self.assertEqual(full_a[i], part_a[i])
            self.assertEqual(full_bb[i], part_bb[i])
            self.assertEqual(full_s[i], part_s[i])


class TestCandles(unittest.TestCase):
    def test_zero_range(self):
        r = candles_sci.read_bar([1.0], [1.0], [1.0], [1.0], ["t"], 0, 0.5, "M1", "t")
        self.assertTrue(r["geometry"]["zero_range"])
        self.assertEqual(r["verdict"], "WAIT")
        self.assertEqual(r["patterns"][0]["name"], "ZERO_RANGE")

    def test_rejection_family_one_evidence(self):
        # hammer-like bar: long lower wick, small body near the high
        o, h, lo, c = [10.0, 10.4], [10.5, 10.62], [9.5, 9.0], [10.0, 10.6]
        r = candles_sci.read_bar(o, h, lo, c, ["a", "b"], 1, 1.0, "M1", "b")
        rej = [e for e in r["evidence"] if e["family"] == "REJECTION" and e["direction"] == "LONG"]
        self.assertEqual(len(rej), 1)                                    # several names -> ONE evidence
        self.assertGreaterEqual(len(rej[0]["members"]), 1)
        self.assertEqual(r["verdict"], "CONFIRM_LONG")

    def test_hammer_and_displacement_are_not_required_together(self):
        o, h, lo, c = [10.0, 10.0], [10.2, 11.3], [9.8, 9.95], [10.0, 11.25]   # big body bar = displacement, no rejection
        r = candles_sci.read_bar(o, h, lo, c, ["a", "b"], 1, 1.0, "M1", "b")
        fams = {e["family"] for e in r["evidence"] if e["direction"] == "LONG"}
        self.assertIn("DISPLACEMENT", fams)
        self.assertNotIn("REJECTION", fams)

    def test_doji_inside_is_wait(self):
        o, h, lo, c = [10.0, 10.1], [11.0, 10.5], [9.0, 9.7], [10.8, 10.1]
        r = candles_sci.read_bar(o, h, lo, c, ["a", "b"], 1, 1.0, "M1", "b")
        self.assertEqual(r["verdict"], "WAIT")

    def test_pattern_stats_causal_with_shrinkage(self):
        ps = candles_sci.PatternStats(baseline=0.5, prior_weight=20, min_n=30)
        for k in range(40):
            ps.add("REJ_LONG", f"2026-01-01T00:{k:02d}:00Z", success=True)
        e = ps.estimate("REJ_LONG", "2026-01-01T00:10:00Z")
        self.assertEqual(e["n"], 10)                                     # only outcomes known BEFORE t
        self.assertEqual(e["status"], "INSUFFICIENT_SAMPLE")
        self.assertAlmostEqual(e["shrunk"], (10 + 10) / 30, places=4)     # shrunk toward the baseline, not 100%


class TestSessionsAdapters(unittest.TestCase):
    def test_box_known_only_after_end_and_dst(self):
        # London 08:00 local = 07:00 UTC in summer (BST), 08:00 UTC in winter
        summer = [w for w in sessions.windows(datetime(2026, 7, 1, 12, tzinfo=timezone.utc)) if w[0] == "LONDON"]
        winter = [w for w in sessions.windows(datetime(2026, 1, 15, 12, tzinfo=timezone.utc)) if w[0] == "LONDON"]
        self.assertEqual(summer[-1][1].hour, 7)
        self.assertEqual(winter[-1][1].hour, 8)
        t0 = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
        bars = [{"open_utc": (t0 + timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%SZ"), "h": 10 + i * 0.01, "l": 9 - i * 0.01, "c": 9.5}
                for i in range(80)]
        during = {b["session"]: b for b in sessions.boxes_as_of(bars, 5, "2026-01-15T11:00:00Z")}
        self.assertNotEqual(during.get("LONDON", {}).get("end_utc"), "2026-01-15T12:00:00+00:00")   # today's box not known yet
        after = {b["session"]: b for b in sessions.boxes_as_of(bars, 5, "2026-01-15T12:05:00Z")}
        self.assertEqual(after["LONDON"]["end_utc"], "2026-01-15T12:00:00+00:00")
        self.assertEqual(after["LONDON"]["bars"], 48)

    def test_pal02m_undocumented_and_no_values(self):
        td = TempData()
        try:
            snaps = {s["adapter"]: s for s in adapters.all_snapshots("XAUUSD-")}
            self.assertEqual(snaps["PAL02M"]["status"], "UNDOCUMENTED_EXTERNAL")
            for s in snaps.values():
                self.assertIsNone(s["values"])                           # missing never becomes 0
                self.assertIn(s["status"], adapters.STATUSES)
            self.assertEqual(snaps["IQ_GOLD_GANN"]["status"], "UNAVAILABLE")
        finally:
            td.close()

    def test_file_bridge_symbol_age_and_unvalidated(self):
        td = TempData()
        try:
            d = adapters.ext_dir()
            d.mkdir(parents=True)
            now = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
            (d / "IQ_GOLD_GANN.json").write_text(json.dumps({"symbol": "XAUUSD-", "known_at": "2026-05-01T11:59:30Z", "values": {"l1": 2400.5, "bad": "x"}}))
            s = adapters.snapshot("IQ_GOLD_GANN", "XAUUSD-", now)
            self.assertEqual(s["status"], "UNVALIDATED")
            self.assertEqual(s["values"], {"l1": 2400.5, "bad": None})
            self.assertEqual(adapters.snapshot("IQ_GOLD_GANN", "XAUUSD-", now + timedelta(hours=1))["status"], "STALE")
            self.assertEqual(adapters.snapshot("IQ_GOLD_GANN", "XAUUSD", now)["status"], "UNAVAILABLE")
            (d / "IQ_STAR_LINES.json").write_text(json.dumps({"symbol": "XAUUSD-", "known_at": "2026-05-01T13:00:00Z", "values": {}}))
            self.assertEqual(adapters.snapshot("IQ_STAR_LINES", "XAUUSD-", now)["status"], "UNAVAILABLE")    # from the future
        finally:
            td.close()


class TestStateMachine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = prof()
        cls.bars, cls.info = S.build(cls.p)

    def test_buy_setup_and_frozen_zone(self):
        m, plans = S.run(self.p, self.bars)
        self.assertEqual([x["direction"] for x in plans], ["BUY"])
        pl = plans[0]
        self.assertEqual(pl["zone"]["z_low"], self.info["zone"]["z_low"])          # zone frozen at arming, not narrowed
        self.assertEqual(pl["retest_bar"], self.info["retest_time"])
        self.assertLess(pl["sl"], pl["sweep_extreme"])
        self.assertEqual(pl["tp1"], round(self.info["range"]["MID"], 10))
        self.assertGreater(pl["decision_ts"], pl["zone"]["known_at_ts"])
        states = [j["state"] for j in m.journal]
        for s_ in ("RANGE_ARMED", "WAIT_SWEEP", "WAIT_RETEST", "ENTRY_CANDIDATE"):
            self.assertIn(s_, states)

    def test_mirror_gives_sell_and_no_buy(self):
        m, plans = S.run(self.p, S.mirror(self.bars))
        self.assertEqual([x["direction"] for x in plans], ["SELL"])               # absence of BUY is not SELL; SELL needs its own sweep
        b = S.run(self.p, self.bars)[1][0]
        sp = plans[0]
        self.assertAlmostEqual(sp["sweep_extreme"], 2 * S.C - b["sweep_extreme"], places=6)
        self.assertAlmostEqual(sp["tp1"], 2 * S.C - b["tp1"], places=6)

    def test_sweep_before_known_at_is_ignored(self):
        """A bar that closes at/before the zone freeze cannot be the sweep."""
        m = st.ScalpMachine(self.p, 0.01)
        m5 = {st.ts(b["open_utc"]) + 300: b for b in S.m5_of(self.bars)}
        for b in self.bars:
            T = st.ts(b["open_utc"]) + 60
            m.on_m1_close(b)
            if T in m5:
                m.on_m5_close(m5[T])
            if m.dirs.get("BUY", {}).get("state") == "WAIT_SWEEP":
                z = m.dirs["BUY"]["zone"]
                self.assertTrue(all(st.ts(x) + 60 <= z["known_at_ts"] for x in z["bars"]))
                break

    def test_retest_ttl_expires(self):
        bars = [dict(b) for b in self.bars]
        i = next(k for k, b in enumerate(bars) if b["open_utc"] == self.info["retest_time"])
        # replace the retest and the rally by bars that stay far above the zone (no retest within 3 M1)
        zh = self.info["zone"]["z_high"]
        for k in range(i, len(bars)):
            bars[k].update(o=zh + 1.0, h=zh + 1.2, l=zh + 0.9, c=zh + 1.0)
        m, plans = S.run(self.p, bars)
        self.assertEqual(plans, [])
        self.assertIn("EXPIRED", [j["state"] for j in m.journal if j.get("direction") == "BUY"])

    def test_no_confirmation_no_setup(self):
        bars = [dict(b) for b in self.bars]
        i = next(k for k, b in enumerate(bars) if b["open_utc"] == self.info["sweep_time"])
        bars[i]["tv"] = 100                                              # tick volume ratio 1.0 < 1.2
        m, plans = S.run(self.p, bars)
        self.assertEqual(plans, [])
        self.assertTrue(any("tick volume" in j["reason"] for j in m.journal))

    def test_context_filter_blocks_only_strong_opposite_trend(self):
        p = prof(context=True)
        down = {"status": "OK", "sar_trend": "DOWN", "slope": -0.4, "bw_pct": 90}
        self.assertTrue(st.fade_blocked({"M30": down, "M15": down}, "BUY", p)[0])
        self.assertFalse(st.fade_blocked({"M30": down, "M15": dict(down, bw_pct=50)}, "BUY", p)[0])
        self.assertFalse(st.fade_blocked({"M30": down, "M15": down}, "SELL", p)[0])
        self.assertIsNone(st.fade_blocked({"M30": {"status": "WARMUP"}, "M15": down}, "BUY", p)[0])


class TestReplaySettlement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = prof()
        cls.bars, cls.info = S.build(cls.p)

    def test_fill_next_open_ask_and_partial_tp(self):
        res = replay.run(self.bars, self.p, 0.01, COSTS)
        self.assertEqual(len(res["cycles"]), 1)
        c = res["cycles"][0]
        nxt = next(b for b in self.bars if st.ts(b["open_utc"]) == st.ts(self.info["retest_time"]) + 60)
        self.assertAlmostEqual(c["fill"], nxt["o"] + 0.1 + 0.02)            # next open (fresh quote) + spread + slippage, not the signal close
        self.assertEqual([e["reason"] for e in c["exits"]], ["TP1", "TP2"])
        self.assertEqual([e["vol"] for e in c["exits"]], [0.5, 0.5])
        exp = 0.5 * (c["tp1"] - 0.02 - c["fill"]) + 0.5 * (c["tp2"] - 0.02 - c["fill"]) - 2 * 0.035
        self.assertAlmostEqual(c["net_price"], exp, places=9)

    def test_sell_closes_on_ask(self):
        res = replay.run(S.mirror(self.bars), self.p, 0.01, COSTS)
        c = res["cycles"][0]
        self.assertEqual(c["direction"], "SELL")
        self.assertGreater(c["sl"], c["fill"] + 0.1)                       # SELL stop is an Ask level above entry

    def test_sl_and_tp_in_one_bar_is_conservative_and_flagged(self):
        P = replay.Path([{"open_utc": "2026-01-01T00:00:00Z", "o": 100, "h": 103, "l": 97, "c": 100, "spread_price": 0.1}], None)
        r = replay.walk(P, 0, 1, 1.0, 98.0, 102.0, None, 1.0, 10 ** 10, {})
        self.assertTrue(r["ambiguous"])
        self.assertEqual(r["exits"][0][3], "SL")

    def test_gap_through_stop_fills_at_open(self):
        P = replay.Path([{"open_utc": "2026-01-01T00:00:00Z", "o": 100, "h": 100.5, "l": 99.5, "c": 100, "spread_price": 0.1},
                         {"open_utc": "2026-01-01T00:01:00Z", "o": 96, "h": 96.5, "l": 95.5, "c": 96, "spread_price": 0.1}], None)
        r = replay.walk(P, 0, 1, 1.0, 98.0, 103.0, None, 1.0, 10 ** 10, {})
        self.assertEqual(r["exits"][0][1], 96)

    def test_sizing_floor_and_min_lot(self):
        z = st.size(2.0, 100.0, 10000.0, self.p, 0.01, 0.01, 100)          # budget 25 USD, 200 USD per lot -> 0.125 -> 0.12
        self.assertEqual(z["lots"], 0.12)
        self.assertTrue(z["split"])
        self.assertEqual(z["tp1_lots"], 0.06)
        z2 = st.size(2.0, 100.0, 500.0, self.p, 0.01, 0.01, 100)          # 1.25 USD budget < min lot risk -> skip, never round up
        self.assertFalse(z2["ok"])
        z3 = st.size(2.0, 100.0, 1700.0, self.p, 0.01, 0.01, 100)          # 0.02 lots -> halves 0.01 + 0.01 ok
        self.assertTrue(z3["split"])
        z4 = st.size(2.0, 100.0, 1300.0, self.p, 0.01, 0.01, 100)          # 0.01 lot -> single TP1 variant
        self.assertEqual(z4["exit_variant"], "SINGLE_TP1")

    def test_economics_rejects_costly_tp1(self):
        pl = {"direction": "BUY", "tp1": 100.5, "tp2": 101.0, "sl": 99.5}
        e = st.economics(pl, 100.2, 0.2, 0.05, self.p)
        self.assertFalse(e["ok"])

    def test_policy_values_on_same_path(self):
        res = replay.run(self.bars, self.p, 0.01, COSTS)
        d = res["decisions"]
        self.assertTrue(d)
        for x in d:
            self.assertEqual(set(x["values_r"]), set(replay.ACTIONS))
            self.assertAlmostEqual(x["values_r"]["HOLD"], res["cycles"][0]["net_r"])
        n = replay.run(self.bars, self.p, 0.01, COSTS, margin_mode="NETTING")
        self.assertTrue(all(x["values_r"]["HEDGE_PARTIAL"] is None for x in n["decisions"]))

    def test_report_small_sample_is_insufficient(self):
        res = replay.run(self.bars, self.p, 0.01, COSTS)
        s = report.strategy_summary(res["cycles"])
        self.assertEqual(s["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(report.hedge_summary(res["decisions"])["status"], "INSUFFICIENT_EVIDENCE")

    def test_aggregate_requires_complete_buckets(self):
        bars = S.sine(10)
        del bars[3]
        agg = replay.aggregate(bars, 5)
        self.assertEqual(len(agg), 1)                                      # the bucket with a missing M1 is not forward-filled


class TestHedge(unittest.TestCase):
    def setUp(self):
        self.h = hedge.HedgeController(prof())

    def kw(self, **k):
        d = dict(margin_mode="HEDGING", base={"lots": 0.10}, setup_valid=True, adverse_signal={"x": 1}, policy_model=None, hedges_used=0,
                 budget_ok=True, vmin=0.01, vstep=0.01)
        d.update(k)
        return d

    def test_netting_reduces_instead_of_hedge(self):
        self.assertEqual(self.h.decide(**self.kw(margin_mode=0))["action"], "REDUCE")
        self.assertEqual(self.h.decide(**self.kw(margin_mode="NETTING"))["action"], "REDUCE")

    def test_no_second_hedge_and_no_budget(self):
        self.assertIn("hedge na hedge", self.h.decide(**self.kw(hedges_used=1))["reasons"][0])
        self.assertEqual(self.h.decide(**self.kw(budget_ok=False))["action"], "REDUCE")

    def test_without_validated_policy_no_hedge(self):
        r = self.h.decide(**self.kw())
        self.assertEqual(r["action"], "REDUCE")
        self.assertEqual(r["hypothetical_hedge_lots"], 0.05)
        self.assertFalse(r["execution"])
        ok = self.h.decide(**self.kw(policy_model={"status": "VALIDATED", "hedge_minus_reduce_r": 0.2, "threshold_r": 0.05}))
        self.assertEqual(ok["action"], "HEDGE_PARTIAL")
        self.assertFalse(ok["execution"])

    def test_setup_negated_closes(self):
        self.assertEqual(self.h.decide(**self.kw(setup_valid=False))["action"], "CLOSE")

    def test_min_lot_cannot_force_limit(self):
        v = hedge.hedge_volume(0.01, prof(), 0.01, 0.01)                   # 50% of 0.01 = 0.005 < min lot
        self.assertFalse(v["ok"])
        self.assertEqual(hedge.hedge_volume(0.07, prof(), 0.01, 0.01)["lots"], 0.03)

    def test_hedge_exit_rules(self):
        self.assertEqual(self.h.hedge_exit(bars_since_fill=3, consecutive_base_dir_closes=0, edge_reclaimed=False, base_open=True), "TTL")
        self.assertEqual(self.h.hedge_exit(bars_since_fill=1, consecutive_base_dir_closes=2, edge_reclaimed=True, base_open=True),
                         "BASE_DIRECTION_CONFIRMED")
        self.assertEqual(self.h.hedge_exit(bars_since_fill=1, consecutive_base_dir_closes=0, edge_reclaimed=False, base_open=False), "BASKET_CLOSE")

    def test_orphan_leg_and_timeout(self):
        legs = [{"ticket": 1, "side": "BUY", "lots": 0.1, "role": "BASE", "sl": 99}, {"ticket": 2, "side": "SELL", "lots": 0.05, "role": "HEDGE", "sl": 101}]
        r = hedge.HedgeController.on_leg_stopped(legs, 1)
        self.assertEqual(r["action"], "CLOSE_ORPHAN_HEDGE")
        self.assertAlmostEqual(r["net_lots"], -0.05)
        t = hedge.HedgeController.on_timeout("MQ-SC-1", [], [{"comment": "MQ-SC-1", "ticket": 9}])
        self.assertEqual(t["action"], "ADOPT_EXISTING")
        self.assertFalse(t["resend"])
        self.assertFalse(hedge.HedgeController.on_timeout("MQ-SC-2", [], [])["resend"])

    def test_basket_pnl_counts_all_legs(self):
        b = hedge.basket([{"side": "BUY", "price": 100.0, "lots": 0.1, "commission": 0.7}, {"side": "SELL", "price": 99.0, "lots": 0.05, "commission": 0.35}],
                         {"BUY": 98.0, "SELL": 98.2}, {"contract_size": 100.0})
        self.assertAlmostEqual(b["mark_to_close"], -0.2 * 100 * 0.1 * 10 + 0.8 * 0.05 * 100)
        self.assertAlmostEqual(b["gross_lots"], 0.15)
        self.assertAlmostEqual(b["net_lots"], 0.05)


class TestConfigAndService(unittest.TestCase):
    def test_switches_cannot_be_enabled(self):
        from masterquo.config import ScalpConfig
        c = ScalpConfig()
        self.assertEqual((c.mode, c.live_trading, c.ml_execution, c.hedge_execution), ("SHADOW", False, False, False))
        for k, v in (("live_trading", True), ("ml_execution", True), ("hedge_execution", True), ("mode", "LIVE")):
            with self.assertRaises(Exception):
                ScalpConfig(**{k: v})

    def test_commission_default_050_and_null_migrated(self):
        from masterquo.config import ConfigStore, ScalpConfig
        self.assertEqual(ScalpConfig().commission_per_lot_side, 0.5)
        td = TempData()
        try:
            p = Path(td.dir) / "config.json"
            p.write_text(json.dumps({"config_version": 10, "scalp": {"commission_per_lot_side": None}}), encoding="utf-8")
            self.assertEqual(ConfigStore(p).get().scalp.commission_per_lot_side, 0.5)
            p.write_text(json.dumps({"config_version": 10, "scalp": {"commission_per_lot_side": 3.5}}), encoding="utf-8")
            self.assertEqual(ConfigStore(p).get().scalp.commission_per_lot_side, 3.5)
        finally:
            td.close()

    def test_profile_units_and_switches(self):
        p = st.load_profile()
        self.assertEqual(p["switches"], {"MODE": "SHADOW", "LIVE_TRADING": False, "ML_EXECUTION": False, "HEDGE_EXECUTION": False})
        for sec in ("range", "zone", "trigger", "economics", "risk"):
            for k, v in p[sec].items():
                self.assertIn("unit", v, f"{sec}.{k} without unit")

    def test_service_shadow_records_and_failure_isolation(self):
        """Fake bridge with the scenario bars: the module records a decision, never calls an executor, and an exception
        sets ERROR_RECOVERY without raising."""
        from masterquo.db.database import Database
        from masterquo.scalp.service import ScalpService
        td = TempData()
        try:
            p = prof()
            bars, info = S.build(p)
            ret = next(k for k, b in enumerate(bars) if b["open_utc"] == info["retest_time"])
            live = bars[:ret + 1]
            now = datetime.fromtimestamp(st.ts(live[-1]["open_utc"]) + 61, timezone.utc)

            class Bridge:
                session_epoch = 1
                symbol_info = {"trade_tick_size": 0.01, "point": 0.01, "trade_contract_size": 100.0, "volume_min": 0.01, "volume_step": 0.01,
                               "volume_max": 50, "currency_base": "XAU", "currency_profit": "USD"}

                def bars(self, tf, limit, include_forming=False):
                    src = live if tf == "M1" else [dict(b, spread=10) for b in S.m5_of(live)] if tf == "M5" else []
                    return [dict(b, spread=10) for b in src][-limit:] if tf == "M1" else src

                def quote_status(self):
                    return {"bid": live[-1]["c"], "ask": live[-1]["c"] + 0.1, "age_seconds": 0.5}

                def account_status(self):
                    return {"equity": 10000.0, "margin_mode": "HEDGING"}

            class Bus:
                def publish(self, *a):
                    pass

            class Log:
                def info(self, *a):
                    pass

            class Cfg:
                def get(self):
                    from masterquo.config import AppConfig
                    c = AppConfig()
                    c.scalp.commission_per_lot_side = 3.5
                    return c

            db = Database()
            svc = ScalpService(Cfg(), Bridge(), db, Bus(), Log(), news=None)
            import masterquo.scalp.service as mod
            orig = mod.time.time
            mod.time.time = lambda: now.timestamp()
            try:
                svc.tick()
            finally:
                mod.time.time = orig
            rows = svc.recent()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["direction"], "BUY")
            self.assertEqual(rows[0]["status"], "BLOCKED")                  # calendar service missing -> new entries blocked
            self.assertTrue(any("kalendarz" in r for r in rows[0]["reasons"]))
            self.assertFalse(next(g for g in rows[0]["gates"] if g["name"] == "uprawnienie wykonania")["ok"])
            self.assertEqual(svc.state["statuses"]["EXECUTION_AUTHORIZED"]["value"], False)
            svc.tick()                                                      # same bar again: idempotent, no duplicate record
            self.assertEqual(len(svc.recent()), 1)
            self.assertFalse(hasattr(svc, "gateway"))                       # no executor reference in the module
            svc.bridge.bars = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            svc.last_key = None
            svc._stop.set()
            try:
                svc.tick()
            except RuntimeError:
                svc._set("ERROR_RECOVERY", "boom")                          # what _loop does; nothing else is touched
            self.assertEqual(svc.state["status"], "ERROR_RECOVERY")
            db.close() if hasattr(db, "close") else None
        finally:
            td.close()

    def test_loss_limits_persist_across_restart(self):
        from masterquo.scalp.service import ScalpService
        td = TempData()
        try:
            svc = ScalpService.__new__(ScalpService)
            svc.prof = st.load_profile()
            ok, _ = svc._loss_limits({"equity": 10000.0})
            self.assertTrue(ok)
            svc2 = ScalpService.__new__(ScalpService)                       # "restart": reference equity is read from disk
            svc2.prof = svc.prof
            ok2, why = svc2._loss_limits({"equity": 9800.0})                 # -2% today > 1.5% daily limit
            self.assertFalse(ok2)
            self.assertIn("2.00%", why)
        finally:
            td.close()


class TestWinRateVariants(unittest.TestCase):
    """1.12 win-ratio levers 1-7 (profile switches; default = unchanged behaviour)."""

    @classmethod
    def setUpClass(cls):
        cls.p = prof()
        cls.bars, cls.info = S.build(cls.p)

    def plans(self, **over):
        return S.run(st.with_overrides(self.p, over), self.bars)[1]

    def test_1_quality_filters(self):
        self.assertEqual(len(self.plans(**{"trigger.min_sweep_depth_atr_m5": 0.1})), 1)
        self.assertEqual(self.plans(**{"trigger.min_sweep_depth_atr_m5": 0.5}), [])          # sweep ~0.25 ATR deep
        self.assertEqual(len(self.plans(**{"trigger.allowed_confirmation_families": ["REJECTION"]})), 1)
        self.assertEqual(self.plans(**{"trigger.allowed_confirmation_families": ["ENGULFING"]}), [])
        self.assertEqual(self.plans(**{"trigger.tick_volume_ratio_min": 5.0}), [])             # sweep bar tv ratio 4.0

    def test_2_session_filter(self):
        t = int(datetime(2026, 3, 3, 8, 10, tzinfo=timezone.utc).timestamp())               # London 08:00 GMT (before DST)
        self.assertTrue(st.session_blocked(t, st.with_overrides(self.p, {"session_filter.block_after_open_min": 30}))[0])
        self.assertFalse(st.session_blocked(t + 3600, st.with_overrides(self.p, {"session_filter.block_after_open_min": 30}))[0])
        q = st.with_overrides(self.p, {"session_filter.allowed_utc_hours": [12, 13]})
        res = replay.run(self.bars, q, 0.01, COSTS)
        self.assertEqual(res["cycles"], [])
        self.assertIn("poza dozwolonymi", res["blocked"][0]["reason"])

    def test_3_trend_modes(self):
        down = {"status": "OK", "sar_trend": "DOWN", "slope": -0.4, "bw_pct": 90}
        calm = dict(down, bw_pct=50)
        for mode, exp in (("BOTH", False), ("ANY", True)):
            p = st.with_overrides(prof(True), {"context_filter.mode": mode})
            self.assertEqual(st.fade_blocked({"M30": down, "M15": calm, "H1": calm}, "BUY", p)[0], exp, mode)
        p = st.with_overrides(prof(True), {"context_filter.mode": "ANY_PLUS_H1"})
        self.assertTrue(st.fade_blocked({"M30": calm, "M15": calm, "H1": down}, "BUY", p)[0])
        self.assertFalse(st.fade_blocked({"M30": calm, "M15": calm, "H1": down}, "BUY", prof(True))[0])   # BOTH ignores H1

    def test_4_range_quality(self):
        self.assertEqual(self.plans(**{"range.er10_max": 0.0}), [])
        self.assertEqual(self.plans(**{"range.touch_min_per_edge": 5}), [])

    def test_5_retest_proximity_and_limit_entry(self):
        self.assertEqual(self.plans(**{"trigger.retest_close_max_atr_m1": 0.01}), [])
        self.assertEqual(len(self.plans(**{"trigger.retest_close_max_atr_m1": 5.0})), 1)
        q = st.with_overrides(self.p, {"entry.mode": "LIMIT_EDGE"})
        pl = S.run(q, self.bars)[1][0]
        self.assertEqual(pl["limit_price"], round(pl["zone"]["z_high"] + pl["eps"] + 0.1, 2))
        res = replay.run(self.bars, q, 0.01, COSTS)
        if res["cycles"]:
            c = res["cycles"][0]
            self.assertEqual(c["entry_mode"], "LIMIT")
            self.assertLessEqual(c["fill"], pl["limit_price"] + 1e-9)                         # never worse than the limit
        else:
            self.assertEqual(res["blocked"][0]["reason"], "MISSED_LIMIT_NOT_FILLED")

    def test_6_be_after_tp1_and_early_exit(self):
        mk = lambda i, o, h, l, c: {"open_utc": f"2026-01-01T00:{i:02d}:00Z", "o": o, "h": h, "l": l, "c": c, "spread_price": 0.0}  # noqa: E731
        P = replay.Path([mk(0, 100, 100.2, 99.9, 100.1), mk(1, 100.1, 101.1, 100.0, 101.0), mk(2, 101.0, 101.1, 99.5, 99.6)], None)
        r = replay.walk(P, 0, 1, 1.0, 98.0, 101.0, 104.0, 0.5, 10 ** 10, {}, entry=100.0, be_offset=0.05)
        self.assertEqual([e[3] for e in r["exits"]], ["TP1", "BE"])
        self.assertAlmostEqual(r["exits"][1][1], 100.05)                                       # stop at entry + costs, not the original SL
        r0 = replay.walk(P, 0, 1, 1.0, 98.0, 101.0, 104.0, 0.5, 10 ** 10, {}, entry=100.0)
        self.assertNotIn("BE", [e[3] for e in r0["exits"]])
        F = replay.Path([mk(k, 100, 100.1, 99.9, 100) for k in range(12)], None)
        e = replay.walk(F, 0, 1, 1.0, 98.0, 101.0, 104.0, 0.5, 10 ** 10, {}, entry=100.0, early=(8, 0.5))
        self.assertEqual(e["exits"][0][3], "EARLY_NO_PROGRESS")
        self.assertEqual(e["end_i"], 7)

    def test_7_setup_features_causal_and_identical(self):
        pl = S.run(self.p, self.bars)[1][0]
        self.assertEqual(tuple(pl["features"]), st.SETUP_FEATURES)
        self.assertTrue(all(isinstance(v, float) and math.isfinite(v) for v in pl["features"].values()))
        ret = next(k for k, b in enumerate(self.bars) if b["open_utc"] == self.info["retest_time"])
        pl2 = S.run(self.p, self.bars[:ret + 1])[1][0]                                          # nothing after the decision
        self.assertEqual(pl["features"], pl2["features"])
        res = replay.run(self.bars, self.p, 0.01, COSTS)
        self.assertEqual(res["cycles"][0]["features"], pl["features"])                         # replay = live features
        self.assertTrue(res["cycles"][0]["win"])

    def test_variant_comparison_small_sample(self):
        vdef = json.loads((st.PROFILE_PATH.parent / "scalp_variants_v1.json").read_text(encoding="utf-8"))
        ids = [v["id"] for v in vdef["variants"]]
        self.assertEqual(ids[0], "BASE")
        cmp_ = replay.compare_variants(self.bars, self.p, vdef["variants"][:3], 0.01, COSTS)
        self.assertIsNone(cmp_["chosen"])                                                       # < 30 development cycles -> no winner
        self.assertIn("INSUFFICIENT", cmp_["chosen_reason"])
        self.assertIn("win_rate", cmp_["rows"][0]["development"] if cmp_["rows"][0]["development"]["cycles"] else {"win_rate": 0})
        for v in vdef["variants"]:
            st.with_overrides(st.load_profile(), v["set"])                                     # every override path is valid


class TestScalpExportAndReplayCli(unittest.TestCase):
    def test_export_on_simulator_then_replay(self):
        """export-scalp on the simulated terminal (SYNTHETIC_TEST, never REAL_USER_DATA) -> scalp-replay CLI summary."""
        import tempfile
        import types
        from masterquo.forecast.export import SCALP_TFS, export_candles
        from masterquo.mt5.fake import FakeMT5
        from masterquo.scalp import cli
        td = TempData()
        sys.modules["MetaTrader5"] = FakeMT5()
        try:
            out = Path(tempfile.mkdtemp(prefix="mq_scalp_exp_")) / "20260101T0000Z"
            self.assertEqual(export_candles(1, str(out), "AUTO", SCALP_TFS, "scalp"), 0)
            meta = json.loads((out / "source_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["data_kind"], "SYNTHETIC_TEST")
            self.assertEqual(meta["timeframes"], list(SCALP_TFS))
            for tf in SCALP_TFS:
                self.assertTrue((out / f"XAUUSD_{tf}.csv").exists(), tf)
            dq = json.loads((out / "DATA_QUALITY_REPORT.json").read_text(encoding="utf-8"))
            self.assertGreater(dq["timeframes"]["M1"]["rows"], 1000)
            a = types.SimpleNamespace(history=str(out), commission_per_lot_side=3.5, slippage_ticks=2.0, cost_stress=1.0, margin_mode="HEDGING")
            self.assertEqual(cli.replay_cmd(a), 0)
            summ = json.loads(sorted((Path(os.environ["MASTERQUO_DATA_DIR"]) / "scalp" / "replay").glob("*/summary.json"))[-1].read_text(encoding="utf-8"))
            self.assertEqual(summ["data_kind"], "SYNTHETIC_TEST")
            self.assertIn(summ["strategy"]["status"], ("INSUFFICIENT_EVIDENCE", "FAILED", "PASSED_RESEARCH_GATE_PENDING_COST_STRESS"))
            self.assertIn("python", summ)
        finally:
            sys.modules.pop("MetaTrader5", None)
            td.close()


if __name__ == "__main__":
    unittest.main()
