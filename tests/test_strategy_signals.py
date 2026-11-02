"""1.27: every strategy of the bot can publish BUY and SELL signals.
- S01-S11 evaluate SHORT with the same rules on the price-mirrored view (base Strategy.detect), S12 arbitrates both directions;
- SCALPING / HEDGING (SH, READY), the scalp profile Range -> Sweep -> Retest (READY_SHADOW) and Double Retest v2
  (RESEARCH_SETUP_COMPLETE) become bot signals: BUY and SELL, one per setup, validated against the live quote, Telegram,
  per-source switches; SHADOW / research strategies are labelled as unvalidated; nothing here places an order."""
import unittest
from datetime import timedelta
from types import SimpleNamespace as NS

import _env
from _env import TempData


def sh_eval(strategy, side, *, status="READY", sid=None):
    up = side == "BUY"
    return {"strategy": strategy, "status": status, "side": side if status == "READY" else None, "signal_id": sid or f"SH-{strategy}-{side}",
            "entry_ref": 2000.0, "sl": 1996.0 if up else 2004.0,
            "tps": [{"name": "TP1", "price": 2002.5 if up else 1997.5, "share": 0.5}, {"name": "TP2", "price": 2003.0 if up else 1997.0, "share": 0.3},
                    {"name": "TP3", "price": 2005.0 if up else 1995.0, "share": 0.2}],
            "model_mode": "DETERMINISTIC", "net_rr": 0.6, "score": {"value": 72}}


class TestStrategySignals(unittest.TestCase):
    def setUp(self):
        from masterquo.markets.signals import BotSignalService
        self.td = TempData()
        self.cfg, self.db, self.bus, self.log, self.fake, self.worker, self.bridge = _env.core()
        self.bridge.quote_status = lambda: {"bid": 2000.0, "ask": 2000.2, "age_seconds": 0.5}
        self.sent = []
        self.svc = BotSignalService(self.cfg, self.bridge, self.db, self.bus, self.log, telegram=NS(signal=lambda k, d: self.sent.append((k, d))))

    def tearDown(self):
        self.worker.stop()
        self.td.close()

    def rows(self):
        return self.db.query("SELECT strategy_id, action, status, trigger FROM ai_signals WHERE source='BOT' ORDER BY created_at")

    def test_s01_s12_evaluate_both_directions(self):
        from masterquo.strategies import registry
        from masterquo.strategies.base import Strategy
        for sid, strat in registry.STRATEGIES.items():
            own = type(strat).detect is not Strategy.detect
            if not own:
                continue                                            # base detect = LONG rules + the same rules on the mirrored view (SHORT)
            self.assertEqual(sid, "S12", f"{sid} overrides detect - it must still produce both directions")
        import inspect
        src = inspect.getsource(type(registry.STRATEGIES["S12"]))
        self.assertIn("SHORT", src)

    def test_sh_ready_buy_and_sell_become_signals(self):
        self.svc.on_sh_cycle({"SCALPING": sh_eval("SCALPING", "BUY"), "HEDGING": sh_eval("HEDGING", "SELL")}, inst="XAUUSD", symbol="XAUUSD-")
        rows = {(r["strategy_id"], r["action"]): r for r in self.rows()}
        self.assertEqual(rows[("SCALPING", "BUY")]["status"], "OPEN")      # TP closer than SL: the S01-S12 R:R floor does not apply to SH
        self.assertEqual(rows[("HEDGING", "SELL")]["status"], "OPEN")
        self.assertEqual({r["trigger"] for r in rows.values()}, {"SH"})
        self.assertEqual(len(self.sent), 2)                                 # Telegram for both
        self.assertEqual({d["side"] for _, d in self.sent}, {"BUY", "SELL"})
        # same setup again -> no duplicate; WAIT / NO_TRADE -> nothing
        self.svc.on_sh_cycle({"SCALPING": sh_eval("SCALPING", "BUY"), "HEDGING": sh_eval("HEDGING", "SELL", status="WAIT", sid="X")},
                             inst="XAUUSD", symbol="XAUUSD-")
        self.assertEqual(len(self.rows()), 2)

    def test_source_switch_and_global_switch(self):
        self.cfg.update({"signals": {"strategy_sources": {"scalping": False}}})
        self.svc.on_sh_cycle({"SCALPING": sh_eval("SCALPING", "SELL", sid="A"), "HEDGING": sh_eval("HEDGING", "BUY", sid="B")}, inst="XAUUSD", symbol="XAUUSD-")
        self.assertEqual([(r["strategy_id"], r["action"]) for r in self.rows()], [("HEDGING", "BUY")])
        self.cfg.update({"signals": {"enabled": False}})
        self.svc.on_sh_cycle({"HEDGING": sh_eval("HEDGING", "SELL", sid="C")}, inst="XAUUSD", symbol="XAUUSD-")
        self.assertEqual(len(self.rows()), 1)

    def test_scalp_shadow_profile(self):
        plan = {"setup_id": "RSR-1", "direction": "SELL", "fill_shadow": 2000.0, "sl": 2003.0, "tp1": 1997.5, "tp2": 1996.0}
        self.svc.on_scalp_setup(plan, status="BLOCKED", reasons=["x"], instrument="XAUUSD", symbol="XAUUSD-", f1=0.5)
        self.svc.on_scalp_setup({**plan, "setup_id": "RSR-0", "fill_shadow": None}, status="READY_SHADOW", reasons=[], instrument="XAUUSD", symbol="XAUUSD-")
        self.assertEqual(self.rows(), [])
        self.svc.on_scalp_setup(plan, status="READY_SHADOW", reasons=[], instrument="XAUUSD", symbol="XAUUSD-", f1=0.5, horizon_s=900)
        r = self.db.one("SELECT * FROM ai_signals WHERE source='BOT'")
        self.assertEqual((r["strategy_id"], r["action"], r["status"], r["trigger"]), ("RANGE_SWEEP_RETEST", "SELL", "OPEN", "SHADOW"))
        self.assertIn("niezweryfikowana", r["strategy_name"])

    def test_double_retest_recent_complete_only(self):
        from masterquo.timeutil import iso, utcnow
        now = utcnow()

        def st(sid, ended):
            return {"setup_id": sid, "state": "RESEARCH_SETUP_COMPLETE", "deep_zone": [1995.0, 1996.0], "epsilon": 0.2, "L": 1997.0,
                    "targets_hypothetical": [2002.0, 2007.0], "trigger": {"close": 1998.0}, "ended_at": iso(ended)}
        setup = {"states": {"BUY": {"recent": [st("DR-new", now - timedelta(minutes=2)), st("DR-old", now - timedelta(hours=2)),
                                              {**st("DR-inv", now), "state": "INVALIDATED"}]},
                            "SELL": {"recent": [{**st("DR-sell", now - timedelta(minutes=1)), "deep_zone": [2003.0, 2004.0], "targets_hypothetical": [1998.0, 1993.0]}]}}}
        self.assertEqual(self.svc.on_double_retest(setup, symbol="XAUUSD-"), 2)
        self.assertEqual(self.svc.on_double_retest(setup, symbol="XAUUSD-"), 0)            # replay of the same buffer: no duplicates
        rows = {r["action"]: r for r in self.db.query("SELECT * FROM ai_signals WHERE source='BOT'")}
        self.assertEqual(set(rows), {"BUY", "SELL"})
        self.assertAlmostEqual(rows["BUY"]["stop_loss"], 1994.8)                            # below the deep zone by epsilon
        self.assertAlmostEqual(rows["SELL"]["stop_loss"], 2004.2)
        self.assertTrue(all(r["strategy_id"] == "DOUBLE_RETEST_V2" for r in rows.values()))

    def test_status_lists_all_sources(self):
        st = self.svc.status()
        self.assertEqual(set(st["strategy_sources"]), {"scalping", "hedging", "range_sweep_retest", "double_retest"})
        self.assertEqual(len(st["strategies"]), 5)


if __name__ == "__main__":
    unittest.main()
