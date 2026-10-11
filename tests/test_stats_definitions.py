"""Uniform statistics definitions: net winrate with breakeven separate, PF, expectancy in R, ROI with cash flows."""
import unittest

import _env  # noqa: F401

from masterquo import stats  # noqa: E402
from masterquo.markets.signals import stats as signal_stats  # noqa: E402


def t(net, r):
    return {"net_pnl": net, "r_multiple": r, "commission": -1.0, "swap": 0.0}


class TestStatsDefinitions(unittest.TestCase):
    def test_breakeven_is_separate_and_not_a_loss(self):
        a = stats._agg([t(100, 2.0), t(-50, -1.0), t(0.5, 0.01), t(-0.4, -0.02)])
        self.assertEqual((a["wins"], a["losses"], a["breakeven"]), (1, 1, 2))
        self.assertEqual(a["win_rate"], 50.0)                     # 1 / (1 + 1), BE excluded
        self.assertEqual(a["profit_factor"], round(100.5 / 50.4, 2))
        self.assertAlmostEqual(a["expectancy_r"], round((2 - 1 + 0.01 - 0.02) / 4, 3))
        self.assertIn("win_rate", a["definitions"])

    def test_pf_without_losses_is_not_infinite(self):
        a = stats._agg([t(10, 1.0), t(20, 2.0)])
        self.assertIsNone(a["profit_factor"])
        self.assertEqual(a["profit_factor_note"], "BRAK_STRAT")

    def test_roi_excludes_deposits(self):
        # 10 000 start, +5 000 deposit in the middle, end 15 500 -> trading result +500 on ~12 500 average capital
        self.assertEqual(stats.roi_modified_dietz(10000, 15500, [(5000, 0.5)]), 4.0)
        self.assertEqual(stats.roi_modified_dietz(10000, 10500, []), 5.0)
        self.assertEqual(stats.roi_modified_dietz(10000, 9000, [(-2000, 1.0)]), 12.5)   # withdrawal at start is not a loss

    def test_signal_stats_breakeven_band(self):
        rows = [{"status": "WIN", "outcome_r": 2.5}, {"status": "LOSS", "outcome_r": -1.0}, {"status": "TIMEOUT", "outcome_r": 0.03},
                {"status": "TIMEOUT", "outcome_r": 0.6}]
        s = signal_stats(rows)
        self.assertEqual((s["wins"], s["losses"], s["breakeven"], s["win_rate_pct"]), (2, 1, 1, 66.7))
        self.assertEqual(s["profit_factor_r"], round(3.13 / 1.0, 2))
        self.assertEqual(s["basis"], "BRUTTO_R")


if __name__ == "__main__":
    unittest.main()
