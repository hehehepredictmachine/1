"""S01-S10 functional tests on SYNTHETIC deterministic scenarios (tests/_strategy_fixtures.py).

Per strategy: LONG, SHORT (mirrored prices), near-miss, forming (unclosed) trigger bar, warm-up,
missing data, invalidation, expiry, deduplication, state restore after restart, determinism.
Plus causality (no look-ahead) of the shared indicators. Synthetic results prove rule behaviour,
not profitability.
"""
import copy
import json
import unittest
from datetime import timedelta

import _env  # noqa: F401
import _strategy_fixtures as F
from _env import TempData

from masterquo.strategies import adapter, indicators as ind, registry
from masterquo.strategies.base import TFView

ALL = ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10"]
ZERO = {"watch": 0, "early": 0, "confirmed": 0}


def scenario(sid: str) -> list[dict]:
    return F.s05_session_breakout()[0] if sid == "S05" else F.SCENARIOS[sid]()


def view_for(bars: list[dict], drop: tuple[str, ...] = ()):
    tfs = {tf: bars for tf in ("M1", "M5", "M15", "H1") if tf not in drop}
    last = bars[-1]
    return adapter.build_view(symbol="XAUUSD-", bars_by_tf=tfs, bid=last["c"], ask=last["c"] + 0.1, point=0.01,
                              as_of=last.get("close_confirmed_utc") or last["open_utc"], synthetic=True)


def params(sid: str) -> dict:
    return registry.params_for(sid, {"tfs": ["M5"] if sid == "S05" else ["M15"]})


def drafts(sid: str, bars, direction=None, drop=()):
    s = registry.STRATEGIES[sid]
    out = s.detect(view_for(bars, drop), params(sid))
    return [d for d in out if direction is None or d.direction == direction]


def entry_of(d):
    return d.entry_plan["reference_price"]


class TestRulesPerStrategy(unittest.TestCase):
    def test_registry_has_exactly_ten_implemented(self):
        self.assertEqual(sorted(registry.STRATEGIES), ALL)
        names = {d["name"] for d in registry.describe()}
        self.assertEqual(len(names), 10)
        self.assertTrue(all(d["implemented"] and d["validation_status"].startswith("FUNCTIONAL_ONLY") for d in registry.describe()))

    def test_long_and_short_trigger(self):
        for sid in ALL:
            with self.subTest(sid=sid):
                bars = scenario(sid)
                lg = [d for d in drafts(sid, bars, "LONG") if d.phase == "TRIGGER"]
                self.assertTrue(lg, f"{sid} LONG trigger not detected")
                d = lg[0]
                self.assertLess(d.stop_loss, entry_of(d))
                self.assertTrue(all(t["price"] > entry_of(d) for t in d.targets))
                self.assertIsNotNone(d.invalidation_level)
                sh = [d for d in drafts(sid, F.mirror(bars), "SHORT") if d.phase == "TRIGGER"]
                self.assertTrue(sh, f"{sid} SHORT trigger not detected on mirrored prices")
                e = sh[0]
                self.assertGreater(e.stop_loss, entry_of(e))
                self.assertTrue(all(t["price"] < entry_of(e) for t in e.targets))
                # mirror symmetry of the structure: risk distance identical within spread tolerance
                self.assertAlmostEqual(abs(entry_of(d) - d.stop_loss), abs(entry_of(e) - e.stop_loss), delta=0.15)

    def test_near_miss_is_not_a_trigger(self):
        for sid in ALL:
            with self.subTest(sid=sid):
                bars = copy.deepcopy(scenario(sid))
                prev = bars[-2]["c"]
                bars[-1].update(o=prev, c=prev, h=prev + 0.05, l=prev - 0.05)
                self.assertFalse([d for d in drafts(sid, bars, "LONG") if d.phase == "TRIGGER"], f"{sid} triggered on a flat bar")

    def test_unclosed_trigger_bar_never_confirms(self):
        for sid in ALL:
            with self.subTest(sid=sid):
                bars = copy.deepcopy(scenario(sid))
                bars[-1]["closed"] = False                       # the trigger bar is still forming
                for d in drafts(sid, bars, "LONG"):
                    self.assertFalse(d.phase == "TRIGGER" and not d.trigger_on_forming, f"{sid} confirmed on a forming bar")

    def test_warm_up_and_missing_data(self):
        for sid in ALL:
            s = registry.STRATEGIES[sid]
            with self.subTest(sid=sid):
                bars = scenario(sid)[-(s.min_bars - 1):]
                status, why = s.check_data(view_for(bars))
                self.assertEqual(status, "WARMING_UP", why)
                drop = tuple(s.required_tfs)
                status, why = s.check_data(view_for(scenario(sid), drop=drop))
                self.assertEqual(status, "DATA_MISSING")
        # missing M15 disables only the strategies that need it - the scanner keeps running the rest
        res = registry.scan(view_for(scenario("S05"), drop=("M15",)), enabled={}, overrides={"S05": {"tfs": ["M5"]}}, thresholds=ZERO, account_key="a")
        self.assertEqual(res["per_strategy"]["S05"]["status"], "OK")
        self.assertEqual(res["per_strategy"]["S01"]["status"], "DATA_MISSING")

    def test_determinism(self):
        for sid in ALL:
            with self.subTest(sid=sid):
                a = registry.scan(view_for(scenario(sid)), enabled={}, overrides={sid: params(sid)}, thresholds=ZERO, account_key="a")
                b = registry.scan(view_for(scenario(sid)), enabled={}, overrides={sid: params(sid)}, thresholds=ZERO, account_key="a")
                ca = [c for c in a["candidates"] if c["strategy_id"] == sid]
                cb = [c for c in b["candidates"] if c["strategy_id"] == sid]
                self.assertEqual(json.dumps(ca, sort_keys=True, default=str), json.dumps(cb, sort_keys=True, default=str))


class TestScoringAndStages(unittest.TestCase):
    def test_confirmed_needs_trigger_and_threshold(self):
        from masterquo.strategies.base import Draft, finalize
        d = Draft(strategy_id="X", direction="LONG", timeframe="M15", phase="EARLY", structure_key="k", event_key="e", anchor_time=None,
                  entry_plan=None, invalidation_level=None)
        th = {"watch": 40, "early": 55, "confirmed": 70}
        self.assertEqual(finalize(d, {"total": 99}, th)[0], "EARLY")            # high score without a trigger is never CONFIRMED
        d.phase = "TRIGGER"
        self.assertEqual(finalize(d, {"total": 69}, th)[0], "EARLY")
        self.assertEqual(finalize(d, {"total": 70}, th)[0], "CONFIRMED")
        d.trigger_on_forming = True
        self.assertEqual(finalize(d, {"total": 90}, th), ("EARLY", ["TRIGGER_BAR_NOT_CLOSED"]))
        self.assertEqual(finalize(d, {"total": 39}, th)[0], None)

    def test_score_scale_and_unknown_components(self):
        bars = scenario("S01")
        res = registry.scan(view_for(bars), enabled={k: k == "S01" for k in ALL}, overrides={"S01": params("S01")}, thresholds=ZERO, account_key="a")
        c = res["candidates"][0]
        sc = c["score"]
        self.assertEqual(sum(sc["weights"].values()), 100)
        self.assertLessEqual(sc["total"], 100)
        self.assertEqual(sc["points"]["extra"], 0.0)                              # DXY unknown -> 0 points, not removed
        self.assertLess(sc["completeness"], 1.0)
        self.assertIn("EXTRA_CONFIRMATION_UNAVAILABLE", c["missing_confirmations"])
        self.assertIn("nie prawdopodobieństwo", sc["scale"])


class TestNoLookAhead(unittest.TestCase):
    def test_indicators_are_causal(self):
        bars = F.s04_compression_breakout()
        c = [b["c"] for b in bars]
        h = [b["h"] for b in bars]
        lo = [b["l"] for b in bars]
        fns = {"ema": lambda x: ind.ema(x, 20), "rsi": lambda x: ind.rsi(x, 14), "kama": lambda x: ind.kama(x), "er": lambda x: ind.efficiency_ratio(x, 10),
               "macdh": ind.macd_hist, "z": lambda x: ind.zscore(x, 40), "bbw": lambda x: ind.bb_width(x)}
        for name, fn in fns.items():
            full = fn(c)
            for k in (60, 100, 140):
                self.assertEqual(fn(c[:k + 1])[k], full[k], f"{name} uses future data at {k}")
        a_full = ind.atr(h, lo, c, 14)
        self.assertEqual(ind.atr(h[:101], lo[:101], c[:101], 14)[100], a_full[100])

    def test_donchian_excludes_current_bar_and_pivots_need_right_bars(self):
        h = [1, 2, 3, 10, 3, 2, 1, 1, 1]
        lo = [0] * 9
        up, _ = ind.donchian_prior(h, lo, 3)
        self.assertEqual(up[3], 3)                       # bar 3 (high 10) is not part of its own threshold
        piv = ind.pivots(h, lo, 3, 3)
        p = next(q for q in piv if q["kind"] == "H")
        self.assertEqual((p["index"], p["confirmed_index"]), (3, 6))
        self.assertEqual(ind.known_pivots(piv, 5), [q for q in piv if q["confirmed_index"] <= 5])
        self.assertNotIn(p, ind.known_pivots(piv, 5))


class TestTracker(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import AppConfig
        from masterquo.db.database import Database
        from masterquo.strategies.tracker import SetupTracker
        self.db = Database()
        self.tr = SetupTracker(self.db)
        self.cfg = AppConfig().active

    def tearDown(self):
        self.td.close()

    def _scan(self, bars, sid):
        v = view_for(bars)
        res = registry.scan(v, enabled={k: k == sid for k in ALL}, overrides={sid: params(sid)}, thresholds=ZERO, account_key="acc")
        return v, [c for c in res["candidates"] if c["direction"] == "LONG"]

    def _now(self, bars):
        from masterquo.timeutil import parse_iso
        return parse_iso(bars[-1]["close_confirmed_utc"]) + timedelta(seconds=5)

    def test_dedupe_invalidation_expiry_restore(self):
        from masterquo.strategies.tracker import SetupTracker
        for sid in ALL:
            with self.subTest(sid=sid):
                bars = scenario(sid)
                v, cands = self._scan(bars, sid)
                self.assertTrue(cands)
                now = self._now(bars)
                ev = self.tr.update(cands, view=v, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=True, now=now, cfg=self.cfg, scanned={sid})
                self.assertTrue(any(k.startswith("NEW_") for k, _ in ev))
                # same data again: same setup ids, no new rows, version unchanged
                self.tr.update(cands, view=v, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=False, now=now, cfg=self.cfg, scanned={sid})
                rows = [r for r in self.tr.active("XAUUSD-", "acc") if r["record"]["strategy_id"] == sid]
                self.assertEqual(sorted(r["setup_id"] for r in rows), sorted({c["setup_id"] for c in cands}))
                self.assertTrue(all(r["version"] == 1 for r in rows))
                # restore: a new tracker on the same DB sees the same state
                self.assertEqual(len([r for r in SetupTracker(self.db).active("XAUUSD-", "acc") if r["record"]["strategy_id"] == sid]), len(rows))
                # invalidation: next closed bar beyond the level -> INVALIDATED immediately
                r0 = rows[0]
                lvl = r0["record"]["invalidation_level"]
                nb = F.bars_from_closes([bars[-1]["c"], lvl - 3.0], tf_min=5 if sid == "S05" else 15, wick=0.2,
                                        start=self._now(bars) - timedelta(seconds=5) - timedelta(minutes=5 if sid == "S05" else 15))[1]
                nb["open_utc"] = bars[-1]["close_confirmed_utc"]
                bars2 = bars + [nb]
                v2 = view_for(bars2)
                ev2 = self.tr.update([], view=v2, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=True,
                                     now=now + timedelta(minutes=20), cfg=self.cfg, scanned={sid})
                self.assertIn(("INVALIDATED", r0["setup_id"]), [(k, r["setup_id"]) for k, r in ev2])
                # expiry: anything still active expires once its time window has passed
                self.tr.update([], view=v, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=False, now=now + timedelta(days=3),
                               cfg=self.cfg, scanned={sid})
                self.assertFalse([r for r in self.tr.active("XAUUSD-", "acc") if r["record"]["strategy_id"] == sid])
                st = {self.tr.get(r["setup_id"])["status"] for r in rows}
                self.assertTrue(st <= {"INVALIDATED", "EXPIRED", "MISSED_ENTRY"}, st)

    def test_stale_flags_without_creating_and_downgrade_hysteresis(self):
        bars = scenario("S08")
        v, cands = self._scan(bars, "S08")
        now = self._now(bars)
        self.assertEqual(self.tr.update(cands, view=v, symbol="XAUUSD-", account_key="acc", data_ok=False, new_data=True, now=now, cfg=self.cfg,
                                        scanned={"S08"}), [])
        self.assertFalse(self.tr.active("XAUUSD-", "acc"))                       # stale data never creates setups
        self.tr.update(cands, view=v, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=True, now=now, cfg=self.cfg, scanned={"S08"})
        self.tr.update(cands, view=v, symbol="XAUUSD-", account_key="acc", data_ok=False, new_data=True, now=now, cfg=self.cfg, scanned={"S08"})
        self.assertTrue(all(r["stale"] for r in self.tr.active("XAUUSD-", "acc")))
        # soft downgrade needs 2 updates with NEW data (CONFIRMED is never downgraded)
        c = dict(cands[0], stage="EARLY")
        sid = c["setup_id"]
        self.tr.update([dict(c, stage="EARLY")], view=v, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=True, now=now, cfg=self.cfg, scanned={"S08"})
        before = self.tr.get(sid)["stage"]
        self.tr.update([dict(c, stage="WATCH")], view=v, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=False, now=now, cfg=self.cfg, scanned={"S08"})
        self.assertEqual(self.tr.get(sid)["stage"], before)                    # same data: no change
        if before != "CONFIRMED":
            self.tr.update([dict(c, stage="WATCH")], view=v, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=True, now=now, cfg=self.cfg, scanned={"S08"})
            self.tr.update([dict(c, stage="WATCH")], view=v, symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=True, now=now, cfg=self.cfg, scanned={"S08"})
            self.assertEqual(self.tr.get(sid)["stage"], "WATCH")


class TestSelector(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import AppConfig
        from masterquo.db.database import Database
        from masterquo.strategies.selector import StrategyAutoSelector
        from masterquo.timeutil import parse_iso
        self.db = Database()
        self.sel = StrategyAutoSelector(self.db)
        self.cfg = AppConfig().active
        self.t0 = parse_iso("2026-10-08T10:00:00Z")

    def tearDown(self):
        self.td.close()

    @staticmethod
    def row(sid, stage, score, fit, direction="LONG", horizon="INTRADAY", event=None, setup=None):
        return {"setup_id": setup or f"MQA-{sid}-{direction}", "status": "ACTIVE", "stale": 0, "stage": stage,
                "record": {"strategy_id": sid, "strategy_name": sid, "strategy_version": "1", "direction": direction, "timeframe": "M15",
                           "horizon": horizon, "setup_score": score, "strategy_fit_score": fit, "countertrend": False, "event_id": event or f"EV-{sid}-{direction}",
                           "score": {"points": {}}}}

    def pick(self, rows, sec, new_data=True, regime="TREND_UP"):
        st = self.sel.select(rows, cfg=self.cfg, regime={"state": regime}, data_ok=True, new_data=new_data, now=self.t0 + timedelta(seconds=sec),
                             snapshot_id="S", account_key="a", per_strategy={})
        return (st["selected"] or {}).get("strategy_id"), st

    def test_trend_range_expansion_with_hysteresis(self):
        # TREND: trend pullback fits best
        s, _ = self.pick([self.row("S01", "EARLY", 60, 100), self.row("S08", "EARLY", 70, 10)], 0)
        self.assertEqual(s, "S01")
        # RANGE: S01 setup disappeared (invalidated) -> immediate switch, no hysteresis delay
        s, _ = self.pick([self.row("S08", "EARLY", 70, 100)], 5, regime="RANGE")
        self.assertEqual(s, "S08")
        # EXPANSION: S03 leads by > margin -> needs 2 NEW-data updates and the 60 s hold
        rows = [self.row("S08", "EARLY", 60, 10), self.row("S03", "EARLY", 75, 100)]
        self.assertEqual(self.pick(rows, 10, regime="EXPANSION")[0], "S08")
        self.assertEqual(self.pick(rows, 20, new_data=False, regime="EXPANSION")[0], "S08")   # identical data does not count
        self.assertEqual(self.pick(rows, 30, regime="EXPANSION")[0], "S08")                   # 2 updates but hold < 60 s
        self.assertEqual(self.pick(rows, 70, regime="EXPANSION")[0], "S03")
        log = self.db.query("SELECT previous_strategy, selected_strategy, reason FROM strategy_selection_log ORDER BY id")
        self.assertEqual([(r["previous_strategy"], r["selected_strategy"]) for r in log], [(None, "S01"), ("S01", "S08"), ("S08", "S03")])

    def test_small_difference_never_switches(self):
        rows = [self.row("S01", "EARLY", 60, 100), self.row("S02", "EARLY", 62, 100)]
        first = self.pick(rows, 0)[0]
        for k in range(1, 8):
            self.assertEqual(self.pick(rows, 100 * k)[0], first)

    def test_conflict_grouping_manual_and_stale(self):
        # same horizon LONG vs SHORT with close ranks -> no selection
        s, st = self.pick([self.row("S01", "EARLY", 60, 100, "LONG"), self.row("S07", "EARLY", 62, 90, "SHORT")], 0)
        self.assertIsNone(s)
        self.assertTrue(any(r.startswith("CONFLICT_") for r in st["reason_codes"]))
        # same event -> grouped, ranked once
        _, st = self.pick([self.row("S03", "EARLY", 70, 100, event="EV-X"), self.row("S04", "EARLY", 65, 100, event="EV-X")], 10)
        self.assertEqual(len(st["candidate_ranking"]), 1)
        self.assertTrue(st["candidate_ranking"][0]["grouped_with"])
        # MANUAL only considers the chosen strategy and reports a regime mismatch
        self.cfg.strategy_mode, self.cfg.manual_strategy_id = "MANUAL", "S08"
        s, st = self.pick([self.row("S03", "EARLY", 90, 100), self.row("S08", "WATCH", 45, 10)], 20, regime="TREND_UP")
        self.assertEqual(s, "S08")
        self.assertTrue(st["manual_fit"]["mismatch"])
        # stale data drops the selection immediately
        st = self.sel.select([self.row("S08", "WATCH", 45, 10)], cfg=self.cfg, regime={"state": "STALE"}, data_ok=False, new_data=True,
                             now=self.t0 + timedelta(seconds=30), snapshot_id="S", account_key="a", per_strategy={})
        self.assertEqual(st["system_state"], "STALE")
        self.assertIsNone(st["selected"])


class TestDecisionActive(unittest.TestCase):
    def build(self, setup, trade_allowed=True, mode_allowed=True):
        from masterquo.config import AppConfig
        from masterquo.engine import decision
        cfg = AppConfig()
        dq = {"analysis_allowed": True, "entries_allowed": True, "reason_codes": [], "market_state": "OPEN", "data_quality": "GOOD"}
        return decision.build(snapshot_id="S", as_of="2026-10-08T12:00:00Z", symbol="XAUUSD-", account_key="a", session_epoch=1, dq=dq, legacy={},
                              setup=setup, levels={}, risk={"risk_gate": "PASS", "reason_codes": []}, agent_gate={"status": "NOT_REQUIRED", "reason_codes": []},
                              mode_gate={"mode": "PAPER" if mode_allowed else "READ_ONLY", "allowed": mode_allowed, "reason_codes": []},
                              macro={"status": "UNAVAILABLE"}, strategy_cfg=cfg.strategy, risk_cfg=cfg.risk, dxy_status="NOT_CONFIGURED", synthetic=True,
                              active={"regime": {"state": "TREND_UP", "conflicts": []}, "bias": "LONG", "trade_allowed": trade_allowed, "reason_codes": []})

    def setup(self, state):
        return {"setup_id": "MQA-1", "state": state, "signal_stage": state, "direction": "LONG", "strategy_id": "S01", "profile": "ACTIVE",
                "setup_tf": "M15", "state_changed_at": "2026-10-08T11:59:00Z"}

    def test_observation_separate_from_permission(self):
        d = self.build(self.setup("EARLY"))
        self.assertEqual((d["analysis_direction"], d["signal_stage"], d["decision"], d["execution_permission"]), ("LONG", "EARLY", "WAIT", "BLOCKED"))
        d = self.build(self.setup("CONFIRMED"))
        self.assertEqual((d["decision"], d["execution_permission"], d["profile"]), ("BUY", "ALLOWED", "ACTIVE"))
        d = self.build(self.setup("CONFIRMED"), trade_allowed=False)
        self.assertEqual(d["execution_permission"], "BLOCKED")
        self.assertIn("STRATEGY_TRADE_DISABLED_S01", d["reason_codes"])
        d = self.build(None)
        self.assertEqual((d["analysis_direction"], d["direction_basis"], d["execution_permission"]), ("LONG", "REGIME_OBSERVATION", "BLOCKED"))


if __name__ == "__main__":
    unittest.main()
