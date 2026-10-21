"""PMW-SH-1 stage 2 fixes (docs/strategie_sh/01_AUDYT_ARCHITEKTURY.md F-03..F-15): tick alignment of SL/TP/BE, manual
partial-close lot checks, bounded BE retries, EXCHANGE treated as netting, ML bundle integrity / feature schema on load,
scalp size re-floor. Simulated terminal only, no real account."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import _env  # noqa: F401
from _env import TempData


class TickAlignment(unittest.TestCase):
    def test_align_stops_conservative(self):
        from masterquo.execution.gateway import align_stops, snap_tick
        info = {"trade_tick_size": 0.05, "digits": 2}
        self.assertEqual(align_stops(info, "BUY", 1997.03, 2003.01), (1997.0, 2003.05))     # SL down, TP up
        self.assertEqual(align_stops(info, "SELL", 2003.01, 1996.99), (2003.05, 1996.95))   # SL up, TP down
        self.assertEqual(snap_tick(info, 2000.026, "nearest"), 2000.05)
        self.assertEqual(align_stops(info, "BUY", 0, 0), (0.0, 0.0))


class RiskNetting(unittest.TestCase):
    def test_exchange_mode_counts_as_netting(self):
        import inspect
        from masterquo.risk import engine
        self.assertIn('("NETTING", "EXCHANGE")', inspect.getsource(engine.evaluate))


class MlIntegrity(unittest.TestCase):
    def test_tampered_or_unverified_pickle_refused(self):
        from masterquo.ml.models import INTEGRITY, verify_integrity, write_integrity
        d = Path(tempfile.mkdtemp())
        for f, txt in (("meta.json", "{}"), ("preprocessor.json", "{}"), ("calibrator.json", "{}"), ("model.joblib", "PICKLE")):
            (d / f).write_text(txt)
        with self.assertRaises(ValueError):
            verify_integrity(d)                                          # pickle without manifest is never opened
        write_integrity(d)
        self.assertEqual(verify_integrity(d), "VERIFIED")
        (d / "model.joblib").write_text("EVIL")
        with self.assertRaises(ValueError) as cm:
            verify_integrity(d)
        self.assertIn("INTEGRITY_MISMATCH", str(cm.exception))
        (d / "model.joblib").unlink()
        (d / INTEGRITY).unlink()
        self.assertEqual(verify_integrity(d), "UNVERIFIED_LEGACY")      # xgboost-only legacy bundle: loads, flagged


class ScalpSize(unittest.TestCase):
    def test_size_refloors_after_vmax(self):
        from masterquo.scalp import strategy as S
        prof = json.loads((_env.ROOT / "config" / "scalp_profile_v1.json").read_text(encoding="utf-8"))
        r = S.size(0.5, 100, 10_000_000, prof, 0.01, 0.01, 1.005)
        k = r["lots"] / 0.01
        self.assertAlmostEqual(k, round(k))
        self.assertLessEqual(r["lots"], 1.005)


class ManagerBeAndManualPartial(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def test_be_retries_bounded_with_backoff(self):
        from masterquo.execution.manager import PositionManager

        class Bridge:
            symbol_info = {"point": 0.01, "trade_tick_size": 0.01, "digits": 2, "trade_stops_level": 0, "trade_freeze_level": 0}
            calls = 0

            def quote_status(self):
                return {"bid": 2003.0, "ask": 2003.1}

            def raw_call(self, fn, prio=0, timeout=None):
                Bridge.calls += 1

                class R:
                    retcode = 10016                                   # INVALID_STOPS
                return R()

        class Log:
            def __init__(self):
                self.msgs = []

            def info(self, *a): self.msgs.append(a)
            def warn(self, *a): self.msgs.append(a)
            def error(self, *a): self.msgs.append(a)

        class Cfg:
            def get(self):
                from masterquo.config import AppConfig
                return AppConfig()

        class DB:
            def execute(self, *a): pass

        m = PositionManager.__new__(PositionManager)
        m.bridge, m.log, m.cfg_store, m.db, m._be_tries = Bridge(), Log(), Cfg(), DB(), {}
        mp = {"position_key": "k", "entry_price": 2000.004, "side": "BUY", "position_ticket": 1, "symbol": "XAUUSD-"}
        for _ in range(20):
            m._move_be(mp, {"sl": 1997.0, "tp": 0})
        self.assertEqual(Bridge.calls, 1)                                   # back-off: not one request per tick
        for _ in range(10):
            m._be_tries["k"]["next"] = 0.0
            m._move_be(mp, {"sl": 1997.0, "tp": 0})
        self.assertEqual(Bridge.calls, 6)                                   # bounded attempts
        self.assertTrue(any("GAVE_UP" in str(x) for x in m.log.msgs))


if __name__ == "__main__":
    unittest.main()
