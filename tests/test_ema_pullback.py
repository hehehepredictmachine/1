"""EMA20 Pullback 2.5R: Pine-style indicators, ORIGINAL replica defects, FIXED state machine boundaries, S11 in the
bot pipeline, backtester execution model (fills, gaps, same-bar SL/TP, sizing, min lot) - scenarios 1-3 and 6."""
import math
import unittest

import _env  # noqa: F401

from masterquo.strategies import ema_pullback_backtest as bt
from masterquo.strategies import ema_pullback_core as core


def run(kind, bars, ind, p=None, **kw):
    p = p or core.Params(use_adx=False, max_pullback_bars=3)
    o, h, lo, c = ([b[k] for b in bars] for k in range(4))
    if kind == "FIXED":
        return core.run_fixed(o, h, lo, c, p, ind, start=0, **kw)
    return core.run_original(o, h, lo, c, p, ind)


def fixture(n, ema20=100.0, ema50=90.0, atr=1.0):
    """n bars clearly above EMA20 in an uptrend (EMA20 > EMA50) - tests then overwrite single bars."""
    bars = [[101.5, 102.0, 101.0, 101.5] for _ in range(n)]
    ind = {"ema20": [ema20] * n, "ema50": [ema50] * n, "atr": [atr] * n, "adx": [30.0] * n}
    return bars, ind


def kinds(res, d="LONG"):
    return [(e.i, e.kind) for e in res.events if e.direction == d]


class TestIndicators(unittest.TestCase):
    def test_pine_definitions(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(core.pine_ema(x, 3)[0], 1.0)                       # seeded with the first value
        self.assertAlmostEqual(core.pine_ema(x, 3)[1], 0.5 * 2 + 0.5 * 1)
        r = core.pine_rma(x, 3)
        self.assertEqual(r[:2], [None, None])
        self.assertAlmostEqual(r[2], 2.0)                                   # SMA seed
        self.assertAlmostEqual(r[3], (4 + 2 * 2.0) / 3)
        h, lo, c = [10, 11, 12, 11, 13] * 10, [9, 10, 10, 10, 11] * 10, [9.5, 10.5, 11.5, 10.5, 12.5] * 10
        p, m, adx = core.pine_dmi(h, lo, c, 5, 5)
        self.assertIsNone(adx[5])
        self.assertTrue(all(0 <= v <= 100 for v in adx[12:]))
        self.assertTrue(all(v is None or not math.isnan(v) for v in core.pine_atr(h, lo, c, 5)))


class TestFixedStateMachine(unittest.TestCase):
    def test_1_touch_and_confirm_same_bar_never_enters(self):
        bars, ind = fixture(8)
        bars[2] = [100.5, 101.0, 99.8, 100.6]           # touches EMA20 and closes above it on the SAME bar
        res = run("FIXED", bars, ind)
        self.assertEqual(kinds(res)[0], (2, "TOUCH"))
        self.assertEqual(kinds(res)[1], (3, "CONFIRM"))                     # only on the next closed bar
        self.assertNotIn((2, "CONFIRM"), kinds(res))
        self.assertEqual(res.events[1].setup_id, 2)

    def test_2a_trend_change_invalidates(self):
        bars, ind = fixture(8)
        bars[2] = [100.5, 101.0, 99.5, 99.7]           # touch, close below EMA20
        ind["ema50"][3] = 105.0                         # EMA20 < EMA50 on the next bar: trend gone
        res = run("FIXED", bars, ind)
        self.assertIn((3, "INVALIDATED"), kinds(res))
        self.assertNotIn("CONFIRM", [k for _, k in kinds(res)])
        orig = run("ORIGINAL", bars, ind)
        self.assertIn((3, "CONFIRM"), kinds(orig))                          # Pine defect 1: confirms against the trend

    def test_2b_expiry_boundary_and_no_extension(self):
        bars, ind = fixture(12)
        bars[2] = [100.5, 101.0, 99.5, 99.7]           # first touch
        for i in (3, 4, 5, 6):
            bars[i] = [99.8, 100.0, 99.4, 99.7]        # keep touching, closes below EMA20 (no confirmation)
        bars[6] = [99.8, 100.0, 99.6, 99.9]
        bars[7] = [100.2, 101.0, 100.1, 100.8]         # first close above EMA20: bar 7 = touch+5 > 3
        res = run("FIXED", bars, ind)
        ks = kinds(res)
        self.assertIn((6, "EXPIRED"), ks)                                   # touch at 2, allowed 3..5, expired at 6
        self.assertIn((6, "TOUCH"), ks)                                     # the touch at 6 opens a NEW setup (id 6)
        conf = [e for e in res.events if e.kind == "CONFIRM"][0]
        self.assertEqual((conf.i, conf.setup_id), (7, 6))
        orig = run("ORIGINAL", bars, ind)
        oc = [e for e in orig.events if e.kind == "CONFIRM"][0]
        self.assertEqual(oc.setup_id, 6)                                    # Pine: every touch silently restarts the wait

    def test_2c_exact_boundary(self):
        for k, expect in ((3, True), (4, False)):
            bars, ind = fixture(10)
            bars[2] = [100.5, 101.0, 99.5, 99.7]
            for i in range(3, 2 + k):
                bars[i] = [99.9, 100.4, 100.05, 99.95]  # no touch (low above EMA20 x tol), no close above
            bars[2 + k] = [100.2, 101.0, 100.1, 100.8]
            res = run("FIXED", bars, ind)
            self.assertEqual(any(e.kind == "CONFIRM" and e.i == 2 + k for e in res.events), expect, k)
        # ORIGINAL defect 3: the snapshot is taken before the expiry, so touch+max+1 still confirms
        bars, ind = fixture(10)
        bars[2] = [100.5, 101.0, 99.5, 99.7]
        for i in range(3, 6):
            bars[i] = [99.9, 100.4, 100.05, 99.95]
        bars[6] = [100.2, 101.0, 100.1, 100.8]
        self.assertTrue(any(e.kind == "CONFIRM" and e.i == 6 for e in run("ORIGINAL", bars, ind).events))

    def test_2d_zero_means_no_limit(self):
        bars, ind = fixture(40)
        bars[2] = [100.5, 101.0, 99.5, 99.7]
        for i in range(3, 35):
            bars[i] = [99.9, 100.4, 100.05, 99.95]
        bars[35] = [100.2, 101.0, 100.1, 100.8]
        res = run("FIXED", bars, ind, core.Params(use_adx=False, max_pullback_bars=0))
        self.assertTrue(any(e.kind == "CONFIRM" and e.i == 35 for e in res.events))

    def test_3_missing_data_and_filters(self):
        bars, ind = fixture(8)
        bars[2] = [100.5, 101.0, 99.5, 99.7]
        ind["atr"] = [None] * 8                                             # no ATR: nothing qualifies
        self.assertEqual(run("FIXED", bars, ind).events, [])
        bars, ind = fixture(8)
        bars[2] = [100.5, 101.0, 99.5, 99.7]
        ind["adx"][3] = 12.0
        p = core.Params(use_adx=True, adx_threshold=20, max_pullback_bars=3)
        res = run("FIXED", bars, ind, p)
        self.assertNotIn((3, "CONFIRM"), kinds(res))                        # ADX too low: wait continues
        self.assertIn((4, "CONFIRM"), kinds(res))
        p = core.Params(use_adx=False, max_pullback_bars=3, h8_trend_filter=True)
        res = run("FIXED", bars, ind, p, h8_trend=[None] * 8)
        self.assertIn("BRAK_DANYCH_H8", [e.reason for e in res.events if e.kind == "BLOCKED_FILTER"])
        res = run("FIXED", bars, ind, p, h8_trend=[-1] * 8)
        self.assertIn("H8_TREND_AGAINST", [e.reason for e in res.events if e.kind == "BLOCKED_FILTER"])
        self.assertIn((3, "CONFIRM"), kinds(run("FIXED", bars, ind, p, h8_trend=[1] * 8)))

    def test_short_side_symmetry_and_zone_touch(self):
        bars, ind = fixture(8, ema20=100.0, ema50=110.0)
        bars = [[98.5, 99.0, 98.0, 98.5] for _ in range(8)]
        bars[2] = [99.5, 100.2, 99.0, 99.4]
        res = run("FIXED", bars, ind)
        self.assertIn((3, "CONFIRM"), kinds(res, "SHORT"))
        conf = [e for e in res.events if e.kind == "CONFIRM"][0]
        self.assertGreater(conf.stop, conf.ref_price)
        # ZONE_ATR + approach: a bar that gaps far below EMA20 is a breakdown, not a pullback
        bars, ind = fixture(8)
        bars[2] = [97.0, 97.5, 96.0, 96.5]
        p = core.Params(use_adx=False, touch_mode="ZONE_ATR", touch_tol_atr=0.2, require_approach=True, max_depth_atr=1.0)
        self.assertEqual([k for _, k in kinds(run("FIXED", bars, ind, p))], [])

    def test_asof_join_uses_only_closed_h8(self):
        p = core.Params()
        h8 = [{"close_ts": 28800 * (k + 1), "c": 100 + k} for k in range(200)]      # rising -> trend +1 after warm-up
        tr = core.asof_h8_trend([28800 * 160 - 1, 28800 * 160, 28800 * 190 + 5], h8, p)
        self.assertEqual(tr[0], 1)
        # a base bar closing 1 s before the H8 close must not see that H8 bar
        h8b = h8[:159] + [{"close_ts": 28800 * 160, "c": 0.0}] + h8[160:]
        self.assertEqual(core.asof_h8_trend([28800 * 160 - 1], h8b, p), core.asof_h8_trend([28800 * 160 - 1], h8, p))


class TestBacktestModel(unittest.TestCase):
    def bars(self, rows):
        return [{"t": f"2026-01-01T{i // 4:02d}:{(i % 4) * 15:02d}:00Z", "o": r[0], "h": r[1], "l": r[2], "c": r[3], "spread": 10}
                for i, r in enumerate(rows)]

    def machine(self, i, stop, ref=100.0, d="LONG"):
        return core.MachineResult(events=[core.Event(i, "CONFIRM", d, i - 1, ref_price=ref, stop=stop)])

    def test_6_mt5_fill_sizing_target_and_costs(self):
        rows = [[100, 100.5, 99.5, 100]] * 3 + [[100.2, 100.4, 100.1, 100.3], [100.3, 104, 100.2, 103.9], [104, 104, 103, 103.5]]
        m = bt.ExecModel(mode="MT5", slippage_ticks=0, commission_per_lot_side=3.5, spread_price=0.10)
        res = bt.simulate(self.bars(rows), self.machine(2, 99.0), core.Params(), m, "FIXED")
        t = res["trades"][0]
        self.assertEqual(t.fill_i, 3)
        self.assertAlmostEqual(t.fill_price, 100.30)                      # next open + spread (Ask)
        risk = 100.30 - 99.0
        self.assertAlmostEqual(t.target, round(100.30 + 2.5 * risk, 2))   # TP from the real fill
        self.assertAlmostEqual(t.qty, math.floor(100 / (risk * 100) / 0.01) * 0.01)   # 1% of 10k / (risk x 100 oz)
        self.assertEqual(t.exit_reason, "TP")
        self.assertAlmostEqual(t.costs, 3.5 * t.qty * 2)
        self.assertLess(t.r, 2.5)                                          # costs reduce R

    def test_6_min_lot_and_gap_rejections(self):
        rows = [[100, 100.5, 99.5, 100]] * 3 + [[100.2, 100.4, 100.1, 100.3]] * 3
        m = bt.ExecModel(mode="MT5", initial_capital=50, slippage_ticks=0, spread_price=0.0)
        res = bt.simulate(self.bars(rows), self.machine(2, 90.0), core.Params(), m, "FIXED")
        self.assertEqual((res["trades"], res["diag"]["rejected_min_lot"]), ([], 1))  # never raises the risk to the min lot
        rows2 = [[100, 100.5, 99.5, 100]] * 3 + [[98.0, 98.5, 97.5, 98.0]] * 3
        res = bt.simulate(self.bars(rows2), self.machine(2, 99.0), core.Params(), bt.ExecModel(mode="MT5", spread_price=0.0), "FIXED")
        self.assertEqual(res["diag"]["rejected_gap_beyond_sl"], 1)

    def test_same_bar_sl_tp_conservative_and_gap_exit(self):
        rows = [[100, 100.5, 99.5, 100]] * 3 + [[100.0, 100.1, 99.9, 100.0], [100.0, 110.0, 90.0, 100.0]]
        m = bt.ExecModel(mode="MT5", slippage_ticks=0, spread_price=0.0)
        t = bt.simulate(self.bars(rows), self.machine(2, 99.0), core.Params(), m, "FIXED")["trades"][0]
        self.assertEqual((t.exit_reason, t.exit_price), ("SL_SAME_BAR", 99.0))
        rows = [[100, 100.5, 99.5, 100]] * 3 + [[100.0, 100.1, 99.9, 100.0], [97.0, 97.5, 96.5, 97.0]]
        t = bt.simulate(self.bars(rows), self.machine(2, 99.0), core.Params(), m, "FIXED")["trades"][0]
        self.assertEqual((t.exit_reason, t.exit_price), ("GAP_SL", 97.0))      # the gap is a real, bigger loss
        self.assertLess(t.r, -1.0)

    def test_blocked_setup_is_consumed_not_delayed(self):
        rows = [[100, 100.5, 99.5, 100]] * 3 + [[100.0, 100.1, 99.9, 100.0]] * 6
        mach = core.MachineResult(events=[core.Event(2, "CONFIRM", "LONG", 1, ref_price=100, stop=99.0),
                                          core.Event(4, "CONFIRM", "LONG", 3, ref_price=100, stop=99.0)])
        res = bt.simulate(self.bars(rows), mach, core.Params(), bt.ExecModel(mode="MT5", spread_price=0.0, slippage_ticks=0), "FIXED")
        self.assertEqual(res["diag"]["blocked_position"], 1)
        self.assertEqual(len(res["trades"]), 1)                              # the blocked one never fills later

    def test_metrics_definitions(self):
        T = lambda r, net: bt.Trade("LONG", 0, 0, 0, 0, 0, 0, 0, 1, 100, net=net, r=r)  # noqa: E731
        m = bt.metrics([T(2.5, 250), T(-1, -100), T(0.01, 1)], 10000)
        self.assertEqual((m["wins"], m["losses"], m["breakeven"], m["winrate_pct"]), (1, 1, 1, 50.0))
        self.assertEqual(m["profit_factor"], round(251 / 100, 3))
        self.assertIsNone(bt.metrics([T(1, 100)], 10000)["profit_factor"])  # no losses: PF not 'infinite'
        self.assertEqual(bt.metrics([], 10000)["note"], "BRAK_TRANSAKCJI")


class TestS11InBot(unittest.TestCase):
    def test_registered_scan_only_and_runs_on_market_view(self):
        from datetime import datetime, timedelta, timezone
        from masterquo.config import AppConfig
        from masterquo.strategies import adapter, registry
        self.assertIn("S11", registry.STRATEGIES)
        self.assertIn("S11", registry.DEFAULT_NO_TRADE)
        self.assertFalse(AppConfig().active.strategies["S11"].trade)
        t0 = datetime(2026, 1, 5, tzinfo=timezone.utc)

        def series(sec, n, base):
            out, px = [], base
            for k in range(n):
                px += 0.3 if (k // 15) % 3 else -0.25          # uptrend with regular pullbacks
                out.append({"open_utc": (t0 + timedelta(seconds=sec * k)).isoformat().replace("+00:00", "Z"),
                            "o": px - 0.1, "h": px + 0.5, "l": px - 0.6, "c": px, "tv": 10, "closed": True})
            return out
        stages, cands = set(), []
        for n in (380, 383, 386):
            bars = {"M15": series(900, n, 2000), "M30": series(1800, n, 2000)}
            view = adapter.build_view(symbol="XAUUSD-", bars_by_tf=bars, bid=2100.0, ask=2100.2, point=0.01, as_of="2026-01-10T00:00:00Z",
                                      synthetic=True)
            res = registry.scan(view, enabled={sid: sid == "S11" for sid in registry.STRATEGIES}, overrides={},
                                thresholds={"watch": 0, "early": 0, "confirmed": 0}, account_key=None)
            self.assertEqual(res["per_strategy"]["S11"]["status"], "OK", res["per_strategy"]["S11"])
            stages |= {c["stage"] for c in res["candidates"]}
            cands += res["candidates"]
        self.assertTrue({"EARLY", "CONFIRMED"} <= stages, stages)            # waiting after the touch, then confirmed
        for cand in cands:
            self.assertEqual(cand["strategy_id"], "S11")
            self.assertEqual(cand["exit_rules"]["tp_rule"], "RR_FROM_FILL")
            self.assertEqual(len(cand["targets"]), 1)                       # no artificial TP1/TP2
            sl, tp = cand["stop_loss"], cand["targets"][0]["price"]
            ref = cand["entry_plan"]["reference_price"]
            if cand["direction"] == "LONG":
                self.assertTrue(sl < ref < tp)
            else:
                self.assertTrue(tp < ref < sl)


if __name__ == "__main__":
    unittest.main()
