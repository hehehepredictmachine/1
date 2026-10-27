"""1.24 DK6 - signals and orders evaluated separately: the AUTO selection (= what the bot may execute) is made only among
strategies allowed to trade; signal-only strategies (default S11, S12) keep their setups in the ranking but can no longer hold the
selection and block a tradable setup. MANUAL stays the user's explicit choice."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import _env  # noqa: F401

from masterquo.config import AppConfig
from masterquo.db.database import Database
from masterquo.engine.active import trade_allowed
from masterquo.strategies.selector import StrategyAutoSelector

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def row(setup_id, sid, score, direction="SHORT", stage="CONFIRMED", event=None):
    return {"setup_id": setup_id, "status": "ACTIVE", "stale": False, "stage": stage,
            "record": {"strategy_id": sid, "strategy_name": sid, "strategy_version": "1", "direction": direction, "timeframe": "M5",
                       "horizon": "SCALP", "setup_score": score, "strategy_fit_score": 50.0, "countertrend": False,
                       "event_id": event or f"EV-{setup_id}", "score": {"points": score}}}


class TestTradableSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(Path(self.tmp) / "t.sqlite")
        self.cfg = AppConfig().active

    def select(self, sel, rows, cfg=None, tradable="default"):
        cfg = cfg or self.cfg
        sel.configure(cfg)
        fn = (lambda s: trade_allowed(cfg, s)) if tradable == "default" else tradable
        return sel.select(rows, cfg=cfg, regime={"state": "TREND"}, data_ok=True, new_data=True, now=NOW, snapshot_id=None,
                          account_key="k", per_strategy={}, tradable=fn)

    def test_defaults(self):
        self.assertFalse(trade_allowed(self.cfg, "S12"))
        self.assertFalse(trade_allowed(self.cfg, "S11"))
        self.assertTrue(trade_allowed(self.cfg, "S01"))

    def test_signal_only_strategy_no_longer_blocks_a_tradable_setup(self):
        rows = [row("A", "S12", 90.0), row("B", "S01", 70.0)]
        before = self.select(StrategyAutoSelector(self.db), rows, tradable=None)     # 1.23 behaviour: S12 holds the selection
        self.assertEqual(before["selected"]["strategy_id"], "S12")
        after = self.select(StrategyAutoSelector(self.db), rows)
        self.assertEqual(after["selected"]["strategy_id"], "S01")
        rank = {x["strategy_id"]: x for x in after["candidate_ranking"]}
        self.assertEqual(set(rank), {"S01", "S12"})                                   # the S12 signal stays visible
        self.assertFalse(rank["S12"]["trade"])
        self.assertTrue(rank["S01"]["trade"])

    def test_same_event_is_not_hidden_behind_a_signal_only_strategy(self):
        rows = [row("A", "S12", 90.0, event="EV-1"), row("B", "S01", 70.0, event="EV-1")]
        after = self.select(StrategyAutoSelector(self.db), rows)
        self.assertEqual(after["selected"]["setup_id"], "B")

    def test_only_signal_only_setups_means_no_selection(self):
        after = self.select(StrategyAutoSelector(self.db), [row("A", "S12", 90.0)])
        self.assertIsNone(after["selected"])
        self.assertIn("ONLY_SIGNAL_ONLY_STRATEGIES_HAVE_SETUPS", after["reason_codes"])

    def test_user_toggle_and_manual_choice_win(self):
        cfg = self.cfg.model_copy(update={"strategies": {**self.cfg.strategies, "S12": self.cfg.strategies["S12"].model_copy(update={"trade": True})}})
        rows = [row("A", "S12", 90.0), row("B", "S01", 70.0)]
        self.assertEqual(self.select(StrategyAutoSelector(self.db), rows, cfg=cfg)["selected"]["strategy_id"], "S12")
        manual = self.cfg.model_copy(update={"strategy_mode": "MANUAL", "manual_strategy_id": "S12"})
        st = self.select(StrategyAutoSelector(self.db), rows, cfg=manual)
        self.assertEqual(st["selected"]["strategy_id"], "S12")                       # explicit user choice is not filtered

    def test_conflict_counts_only_executable_candidates(self):
        # a signal-only SHORT close to a tradable LONG no longer cancels the tradable selection
        rows = [row("A", "S12", 72.0, direction="SHORT"), row("B", "S01", 70.0, direction="LONG")]
        self.assertIsNone(self.select(StrategyAutoSelector(self.db), rows, tradable=None)["selected"])   # 1.23: conflict, no selection
        self.assertEqual(self.select(StrategyAutoSelector(self.db), rows)["selected"]["strategy_id"], "S01")


if __name__ == "__main__":
    unittest.main()
