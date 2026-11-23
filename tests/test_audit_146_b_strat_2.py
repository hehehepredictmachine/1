"""1.46 audit, group B_strat_2: selector / tracker / S11 / S12 regression tests (strategy decision behaviour is NOT changed here -
only display, bookkeeping and per-thread state). No orders, no terminal, no HTTP server."""
from __future__ import annotations

import threading
import unittest
from datetime import UTC, datetime, timedelta

import _env  # noqa: F401
from _env import TempData


class _View:
    """Minimal MarketView stand-in for the tracker (no bars -> no hard check on closes)."""

    def __init__(self, tfs=None, bid=4000.0, ask=4000.2):
        self.tfs, self.bid, self.ask = tfs or {}, bid, ask

    @property
    def mid(self):
        return None if self.bid is None or self.ask is None else (self.bid + self.ask) / 2


def _cand(sid="MQA-T1", strat="S02", stage="EARLY", ver="1.0", chash="cfgA", event="EV-1", sl=3985.0):
    return {"setup_id": sid, "strategy_id": strat, "strategy_version": ver, "config_hash": chash, "direction": "LONG", "timeframe": "M15",
            "structure_key": "k", "event_id": event, "stage": stage, "setup_score": 60, "expires_bars": 50, "stop_loss": sl,
            "invalidation_level": sl, "invalidation_rule": "CLOSE_BEYOND", "synthetic": False}


# ============================================================================================== selector (chunk_33#2)
class TestSelectorStaleState(unittest.TestCase):
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
        self.db.close()
        self.td.close()

    def _select(self, rows, sec, data_ok):
        return self.sel.select(rows, cfg=self.cfg, regime={"state": "RANGE"}, data_ok=data_ok, new_data=True, now=self.t0 + timedelta(seconds=sec),
                               snapshot_id="S", account_key="a", per_strategy={})

    def test_stale_state_clears_when_fresh_data_returns(self):
        """chunk_33#2: _publish read the PREVIOUS state - after one stale scan the system stayed STALE on fresh data until a selection."""
        self.assertEqual(self._select([], 0, False)["system_state"], "STALE")
        for k in (1, 2):
            st = self._select([], 10 * k, True)
            self.assertEqual(st["system_state"], "SCANNING", st["reason_codes"])
            self.assertEqual(st["reason_codes"], ["NO_VALID_CANDIDATE"])
        self.assertEqual(self._select([], 40, False)["system_state"], "STALE")     # stale data is still reported as STALE


# ============================================================================================== tracker (chunk_34#8, chunk_34#9)
class TestTrackerBookkeeping(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import AppConfig
        from masterquo.db.database import Database
        from masterquo.strategies.tracker import SetupTracker
        from masterquo.timeutil import parse_iso
        self.db = Database()
        self.tr = SetupTracker(self.db)
        self.cfg = AppConfig().active
        self.t0 = parse_iso("2026-10-08T10:00:00Z")

    def tearDown(self):
        self.db.close()
        self.td.close()

    def _upd(self, cands, minutes, scanned=("S02",)):
        return self.tr.update(cands, view=_View(), symbol="XAUUSD-", account_key="acc", data_ok=True, new_data=True,
                              now=self.t0 + timedelta(minutes=minutes), cfg=self.cfg, scanned=set(scanned))

    def _cols(self, sid):
        return self.db.one("SELECT strategy_version, config_hash, event_id FROM strategy_setups WHERE setup_id=?", (sid,))

    def test_upsert_refreshes_strategy_version_config_hash_event_id(self):
        """chunk_34#8: ON CONFLICT kept the columns of the first write - /api/v1/playbook showed a version different from the plan."""
        self._upd([_cand()], 0)
        self.assertEqual(self._cols("MQA-T1"), {"strategy_version": "1.0", "config_hash": "cfgA", "event_id": "EV-1"})
        self._upd([_cand(ver="2.0", chash="cfgC", event="EV-2")], 1)
        r = self.tr.get("MQA-T1")
        self.assertEqual((r["record"]["strategy_version"], r["record"]["config_hash"]), ("2.0", "cfgC"))
        self.assertEqual(self._cols("MQA-T1"), {"strategy_version": "2.0", "config_hash": "cfgC", "event_id": "EV-2"})

    def test_upsert_keeps_final_status_and_columns_after_reactivation(self):
        """chunk_34#8: a reactivated soft-cancelled row gets the new columns; a final row (ENTERED) is still never overwritten."""
        self._upd([_cand()], 0)
        for k in range(1, self.cfg.cancel_after_misses + 1):
            self._upd([], k)
        self.assertEqual(self.tr.get("MQA-T1")["terminal_reason"], "CONDITIONS_NO_LONGER_MET")
        ev = self._upd([_cand(ver="2.0", chash="cfgC")], 20)
        self.assertEqual([k for k, _ in ev], ["NEW_EARLY"])
        self.assertEqual(self._cols("MQA-T1")["strategy_version"], "2.0")
        self.tr.mark_entered("MQA-T1", "PAPER_DONE", "2026-10-08T10:30:00Z")
        stale = self.tr.get("MQA-T1")
        stale.update(status="ACTIVE", terminal_reason=None)
        stale["record"] = dict(stale["record"], strategy_version="3.0", config_hash="cfgZ")
        self.tr._save(stale)                                   # a stale copy from the scan thread
        self.assertEqual(self.tr.get("MQA-T1")["status"], "ENTERED")
        self.assertEqual(self._cols("MQA-T1")["strategy_version"], "2.0")

    def test_refresh_resets_misses_and_keeps_pending_downgrade(self):
        """chunk_34#9: removing the dead `keep` dict must not change the refreshed record (misses reset, downgrade counter kept)."""
        self._upd([_cand(stage="EARLY")], 0)
        self._upd([], 1)                                       # not reported once -> misses 1
        self.assertEqual(self.tr.get("MQA-T1")["record"]["misses"], 1)
        self._upd([_cand(stage="WATCH")], 2)                   # soft downgrade pending (needs confirmation)
        rec = self.tr.get("MQA-T1")["record"]
        self.assertEqual((rec["misses"], rec["pending_downgrade"], rec["stage"]), (0, 1, "EARLY"))
        self.assertEqual(rec["setup_score"], 60)


# ============================================================================================== S12 (chunk_33#7, chunk_33#11)
class TestS12PerThreadRejections(unittest.TestCase):
    def test_rejections_of_another_thread_do_not_leak(self):
        """chunk_33#7: one S12 instance per process; the ml-backfill thread overwrote last_rejections between detect() and the
        registry's read in the live scan."""
        from masterquo.strategies import adapter
        from masterquo.strategies.registry import STRATEGIES, params_for
        s, p = STRATEGIES["S12"], params_for("S12", None)
        t0 = datetime(2026, 10, 12, tzinfo=UTC)

        def bars(n, minutes):
            return [{"open_utc": (t0 + timedelta(minutes=minutes * k)).isoformat().replace("+00:00", "Z"), "o": 2000.0, "h": 2000.5,
                     "l": 1999.5, "c": 2000.0, "tv": 10, "closed": True} for k in range(n)]
        short_view = adapter.build_view(symbol="XAUUSD-", bars_by_tf={"M1": bars(10, 1), "M5": bars(10, 5)}, bid=2000.0, ask=2000.1,
                                        point=0.01, as_of="2026-10-12T01:00:00Z", synthetic=True)
        self.assertEqual(s.detect(short_view, p), [])
        mine = s.last_rejections
        self.assertEqual(mine["LONG"]["RANGE_RECLAIM"], ["DATA_MISSING"])
        other: dict = {}

        def work():                                            # another thread (ml-backfill) scans its own view meanwhile
            flat = adapter.build_view(symbol="XAUUSD-", bars_by_tf={"M1": bars(200, 1), "M5": bars(200, 5)}, bid=2000.0, ask=2000.1,
                                      point=0.01, as_of="2026-10-13T00:00:00Z", synthetic=True)
            s.detect(flat, p)
            other.update(s.last_rejections)
        th = threading.Thread(target=work)
        th.start()
        th.join()
        self.assertTrue(other)
        self.assertNotEqual(other, mine)                       # the other thread really produced different rejections
        self.assertEqual(s.last_rejections, mine)              # ... and they did not replace this thread's result

    def test_registry_reports_rejections_of_its_own_scan(self):
        from masterquo.strategies import adapter, registry
        t0 = datetime(2026, 10, 12, tzinfo=UTC)
        b = [{"open_utc": (t0 + timedelta(minutes=k)).isoformat().replace("+00:00", "Z"), "o": 2000.0, "h": 2000.5, "l": 1999.5, "c": 2000.0,
              "tv": 10, "closed": True} for k in range(120)]
        v = adapter.build_view(symbol="XAUUSD-", bars_by_tf={"M1": b, "M5": b}, bid=2000.0, ask=2000.1, point=0.01,
                               as_of="2026-10-12T03:00:00Z", synthetic=True)
        res = registry.scan(v, enabled={sid: sid == "S12" for sid in registry.STRATEGIES}, overrides={}, thresholds={"watch": 0, "early": 0,
                            "confirmed": 0}, account_key=None)
        ps = res["per_strategy"]["S12"]
        self.assertEqual(ps["status"], "OK")
        if not ps["drafts"]:
            self.assertEqual(set(ps["rejections"]), {"LONG", "SHORT"})


class TestS12ReferencePriceWithoutQuote(unittest.TestCase):
    def test_watch_draft_without_quote_has_no_zero_reference(self):
        """chunk_33#11: a WATCH draft (no entry, no trigger level) on a view without a quote got reference_price 0.0 (rule 6: missing
        = None), and after the SHORT mirror 2 x centre."""
        from masterquo.strategies.base import MarketView, unmirror_draft
        from masterquo.strategies.registry import STRATEGIES, params_for
        s, p = STRATEGIES["S12"], params_for("S12", None)
        rng = {"status": "OK", "range_id": "R1", "state": "INSIDE", "recognised_bar": "2026-10-12T01:00:00Z"}
        facts = {"variant": "WALL_REJECTION", "touch_bar": "2026-10-12T01:00:00Z"}
        for bid, ask, expect in ((None, None, None), (2000.0, 2000.2, 2000.2)):
            with self.subTest(bid=bid):
                v = MarketView(symbol="XAUUSD-", as_of="2026-10-12T02:00:00Z", tfs={}, bid=bid, ask=ask, point=0.01)
                d = s._draft(v, "WALL_REJECTION", "WATCH", "M5", "WR:W-LOWER-1:WAIT", rng, None, None, None, [], dict(facts), ["NO_WALL_TOUCH"],
                             p, 1.0, components={"structure": 0.5, "formation": 0.3, "trigger": 0.0})
                self.assertEqual(d.entry_plan["reference_price"], expect)
                self.assertIsNone(d.entry_plan["trigger_level"])
                sh = unmirror_draft(d, 2001.0)
                self.assertEqual(sh.entry_plan["reference_price"], None if expect is None else round(4002.0 - expect, 5))


# ============================================================================================== S11 (chunk_33#10)
class TestS11ShortTrendCode(unittest.TestCase):
    @staticmethod
    def _drafts(sign):
        from masterquo.strategies import adapter
        from masterquo.strategies.registry import STRATEGIES, params_for
        t0 = datetime(2026, 1, 5, tzinfo=UTC)

        def series(sec, n, base):
            out, px = [], base
            for k in range(n):
                px += sign * (0.3 if (k // 15) % 3 else -0.25)        # trend with regular pullbacks (sign -1 = down-trend)
                o, c = px - sign * 0.1, px
                out.append({"open_utc": (t0 + timedelta(seconds=sec * k)).isoformat().replace("+00:00", "Z"),
                            "o": o, "h": max(o, c) + 0.5, "l": min(o, c) - 0.5, "c": c, "tv": 10, "closed": True})
            return out
        out = []
        for n in (380, 383, 386):
            bars = {"M15": series(900, n, 2000), "M30": series(1800, n, 2000)}
            last = bars["M15"][-1]["c"]
            view = adapter.build_view(symbol="XAUUSD-", bars_by_tf=bars, bid=last, ask=last + 0.2, point=0.01, as_of="2026-01-10T00:00:00Z",
                                      synthetic=True)
            out += STRATEGIES["S11"].detect(view, params_for("S11", None))
        return out

    def test_short_reports_ema20_below_ema50(self):
        """chunk_33#10: 'EMA20>EMA50' has no '_' tokens, so mirror_code/mirror_text left it unchanged on SHORT setups (EMA20<EMA50)."""
        sh = [d for d in self._drafts(-1) if d.direction == "SHORT"]
        self.assertTrue(sh)
        for d in sh:
            self.assertIn("EMA20<EMA50", d.reason_codes)
            self.assertNotIn("EMA20>EMA50", d.reason_codes)
            self.assertIn("EMA20<EMA50", d.entry_plan["trigger"])
            self.assertNotIn("EMA20>EMA50", d.entry_plan["trigger"])
            self.assertIn("poniżej EMA20", d.entry_plan["trigger"])

    def test_long_unchanged(self):
        lg = [d for d in self._drafts(1) if d.direction == "LONG"]
        self.assertTrue(lg)
        for d in lg:
            self.assertEqual(d.reason_codes[0], "EMA20>EMA50")
            self.assertEqual(d.entry_plan["trigger"], "zamknięcie świecy powyżej EMA20 na świecy PÓŹNIEJSZEJ niż dotknięcie, trend EMA20>EMA50 nadal ważny")


if __name__ == "__main__":
    unittest.main()
