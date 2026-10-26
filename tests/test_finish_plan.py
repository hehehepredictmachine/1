"""Remaining plan items after the audit (REFACTOR_PLAN.md, 1.21): shared portfolio guard of both execution paths (§23, DoD 8),
§22 metrics, outcome distribution and holding time (§8/§19), master models on every closed M5 + calibration drift (AR-08),
stricter legacy ML promotion (O8)."""
import json
import time
import unittest
from datetime import datetime, timezone

import _env  # noqa: F401
from _env import TempData
from test_sh_service import NOW, Log

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.db.database import Database
        self.cfg, self.db = ConfigStore(), Database()

    def tearDown(self):
        self.td.close()

    def trade(self, tid, net, strategy="S01", closed=TODAY, r=None, mode="PAPER"):
        self.db.execute("""INSERT INTO trades(trade_id, mode, source, symbol, side, volume, closed_at, gross_pnl, commission, swap, fee, net_pnl,
                           r_multiple, status, strategy_id) VALUES (?,?,'BOT','XAUUSD-','BUY',0.1,?,?,0,0,0,?,?,'CLOSED',?)""",
                        (tid, mode, closed, net, net, r, strategy))

    def plan(self, pid, net, state="CLOSED", closed=None, strategy="SCALPING"):
        res = json.dumps({"net_money": net, "r_multiple": net / 50.0, "commission_money": 0.0, "commission_known": True}) if state == "CLOSED" else None
        self.db.execute("""INSERT INTO sh_plans(plan_id, signal_id, strategy, instrument, symbol, side, exec_mode, state, config_hash, plan, created_at,
                           updated_at, closed_at, result) VALUES (?,?,?,'XAUUSD','XAUUSD-','BUY','PAPER',?,'h','{}',?,?,?,?)""",
                        (pid, "SH-" + pid, strategy, state, time.time(), time.time(), closed if closed is not None else (time.time() if state == "CLOSED" else None), res))


class PortfolioGuard(Base):
    def modes(self, equity=10000.0):
        from masterquo.events import EventBus
        from masterquo.execution.modes import ModeManager
        return ModeManager(self.cfg, self.db, EventBus(), Log(), account_provider=lambda: ({"trade_mode": "DEMO", "login": 1, "equity": equity}, "srv:1", True))

    def test_losses_of_both_paths_add_up_against_the_stricter_daily_limit(self):
        m = self.modes()
        m.set_primary_path("XAUUSD", "SH")
        self.assertNotIn("PORTFOLIO_DAILY_LOSS_LIMIT", m.gate("srv:1", path="SH")["reason_codes"])
        self.trade("T1", -120.0)                        # S01-S12 loss today (PAPER)
        self.plan("P1", -90.0)                          # SH loss today: alone each is below 2 % of 10 000, together 210 > 200
        g = m.gate("srv:1", path="SH")
        self.assertIn("PORTFOLIO_DAILY_LOSS_LIMIT", g["reason_codes"])
        self.assertEqual(g["portfolio"]["realized_by_path"], {"ACTIVE": -120.0, "SH": -90.0})
        self.assertNotIn("PORTFOLIO_DAILY_LOSS_LIMIT", m.gate("srv:1")["reason_codes"])        # manual trades / management untouched

    def test_yesterdays_losses_and_other_modes_do_not_count(self):
        from masterquo.risk import portfolio as PF
        self.trade("T1", -500.0, closed="2000-01-01T10:00:00Z")
        self.trade("T2", -500.0, mode="AUTO_DEMO")
        self.plan("P1", -500.0, closed=946720800.0)
        st = PF.state(self.db, "PAPER", None, time.time())
        self.assertEqual(st["realized_today"], 0.0)

    def test_open_positions_of_both_paths_count_against_the_smaller_cap(self):
        from masterquo.risk import portfolio as PF
        self.cfg.update({"risk": {"max_open_positions": 2}})
        for i in range(2):
            self.plan(f"O{i}", 0.0, state="OPEN")
        st = PF.state(self.db, "PAPER", None, time.time())
        self.assertEqual(st["open_by_path"], {"ACTIVE": 0, "SH": 2})
        self.assertIn("PORTFOLIO_MAX_OPEN_POSITIONS", PF.check(st, equity=1e4, legacy_limits=self.cfg.get().risk, sh_limits={"max_open_positions": 4}))
        self.assertEqual(PF.check(st, equity=None, legacy_limits=self.cfg.get().risk.model_copy(update={"max_open_positions": None}),
                                  sh_limits={}), [])                                           # no limit configured -> none invented

    def test_guard_error_blocks_new_entries(self):
        m = self.modes()
        m.set_primary_path("XAUUSD", "ACTIVE")
        from unittest import mock
        with mock.patch("masterquo.risk.portfolio.state", side_effect=RuntimeError("db")):
            self.assertTrue(any(r.startswith("PORTFOLIO_GUARD_ERROR") for r in m.gate("srv:1", path="ACTIVE")["reason_codes"]))


class Metrics(Base):
    def test_section_22_metrics_per_engine_strategy_and_month(self):
        from masterquo import stats
        self.trade("T1", 30.0, "S01", "2026-09-10T10:00:00Z", 1.5)
        self.trade("T2", -20.0, "S01", "2026-09-11T10:00:00Z", -1.0)
        self.trade("T3", -25.0, "S07", "2026-10-02T10:00:00Z", -1.25)
        self.plan("P1", 40.0)
        s = stats.engine_stats(self.db, "PAPER")
        c = s["combined"]
        self.assertEqual((c["trades"], c["avg_win"], c["avg_loss"]), (4, 35.0, -22.5))
        self.assertEqual(c["max_drawdown"], 45.0)                      # +30, -20, -25 -> trough 45 below the peak, then +40
        self.assertEqual(set(s["per_strategy"]), {"S01", "S07", "SCALPING"})
        self.assertEqual(s["per_month"]["2026-09"]["trades"], 2)
        self.assertIsNotNone(c["expectancy_r_se"])


class OutcomeDistribution(unittest.TestCase):
    def test_hold_time_and_tp_sl_neither_rates(self):
        from masterquo.evaluation import contract as K
        from masterquo.evaluation import outcome as O
        c = K.SetupCandidate(setup_id="X", engine="SH_SCALPING", strategy_id="SCALPING", symbol="XAUUSD-", instrument="XAUUSD", timeframe="M1",
                             decision_ts=NOW, direction="LONG", entry_type="MARKET", entry_price=100.0, stop_loss=99.0,
                             targets=[{"price": 101.0, "weight": 1.0}], horizon_s=600).to_dict()
        bars = [{"t": NOW + 60 * i, "o": 100.0, "h": 100.2 + (0.9 if i == 3 else 0.0), "l": 99.9, "c": 100.0} for i in range(10)]
        out = O.label(c, bars)
        self.assertEqual((out["exit"], out["hold_s"]), ("ALL_TARGETS", 240.0))     # target inside the 4th bar -> its close
        out2 = O.label(c, [{"t": NOW + 60 * i, "o": 100.0, "h": 100.2, "l": 99.9, "c": 100.0} for i in range(10)])
        self.assertEqual((out2["exit"], out2["hold_s"]), ("TIMEOUT", 600.0))


class MasterModelsLoop(unittest.TestCase):
    def test_runs_once_per_new_closed_m5_bar_and_survives_errors(self):
        from masterquo.mm.service import MMService

        class Bridge:
            rows = [{"open_utc": "2026-10-26T08:00:00Z"}]

            def bars(self, tf, include_forming=False):
                return list(self.rows)

        class RT:
            bridge = Bridge()

        svc = MMService(RT())
        svc.loop_interval_s = 0.01
        calls = []
        svc.live = lambda inst: calls.append(inst) or (1 / 0 if len(calls) == 2 else {})
        svc.start()
        time.sleep(0.15)
        RT.bridge.rows = [{"open_utc": "2026-10-26T08:05:00Z"}]
        time.sleep(0.15)
        svc.stop()
        self.assertEqual(len(calls), 2)                                  # one inference per new bar, not per tick
        self.assertIn("ZeroDivisionError", svc.loop["last_error"])       # the error is recorded, the loop keeps running
        self.assertEqual(svc.status.__name__, "status")


class MLPromotion(unittest.TestCase):
    def rules(self, **test):
        from masterquo.config import MLPromotion
        from masterquo.ml.registry import Registry
        t = {"n": 400, "pos": 150, "neg": 250, "brier": 0.20, "ece": 0.02, **test}
        m = {"test": t, "calibration": "PLATT", "policy": {"avg_r": 0.2, "max_dd_r": 3.0}}
        res = {"baselines": {"base_rate": {"brier": 0.23}, "no_ml_policy": {"avg_r": 0.1, "max_dd_r": 3.0}}}
        return Registry._rules(m, res, MLPromotion().model_dump())

    def test_brier_gain_must_exceed_two_standard_errors(self):
        ok, why = self.rules(brier_gain=0.03, brier_gain_se=0.01)
        self.assertTrue(ok, why)
        ok, why = self.rules(brier_gain=0.015, brier_gain_se=0.01)
        self.assertFalse(ok)
        self.assertTrue(any(w.startswith("BRIER_GAIN_") for w in why))
        ok, why = self.rules()                                          # evaluated before 1.21: no SE -> re-train first
        self.assertIn("BRIER_GAIN_SE_UNKNOWN_RETRAIN", why)


if __name__ == "__main__":
    unittest.main()
