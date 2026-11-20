"""1.42 (DIRECT_USER_REQUEST "Modele: OBSERVE -> ASSIST, 90 strategii: zlecenia FOREX"): one-time migration of the model roles and of the
FX basket execution, the Kronos ASSIST receiver (may only hold READY -> WAIT) and the unchanged STOP / risk / mode."""
from __future__ import annotations

import os
import tempfile
import types
import unittest
from pathlib import Path

import _env  # noqa: F401


class _Log:
    def __init__(self):
        self.rows = []

    def info(self, *a):
        self.rows.append(a)


class TestAssistMigration(unittest.TestCase):
    def test_apply_142_sets_assist_once_and_keeps_required(self):
        from masterquo.kronos import settings as KS
        from masterquo.kronos.service import KronosService
        from masterquo.tsfm import settings as TS
        from masterquo.tsfm.service import TsfmService
        from masterquo.upgrade import migrate as M
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("MASTERQUO_DATA_DIR")
            os.environ["MASTERQUO_DATA_DIR"] = d
            try:
                ts = types.SimpleNamespace(settings=TS.SettingsStore(Path(d) / "tsfm.json"), applog=_Log())
                ts.set_use = lambda *a, **k: TsfmService.set_use(ts, *a, **k)
                kr = types.SimpleNamespace(settings=KS.SettingsStore(Path(d) / "kronos.json"), applog=_Log())
                kr.set_strategy_use = lambda *a, **k: KronosService.set_strategy_use(kr, *a, **k)
                kr.settings.update({"strategy_use": {"HEDGING": {"use": "REQUIRED", "timeframe": "M15", "validation_report": "KV-x"}}})
                bs = types.SimpleNamespace(patches=[], update_settings=lambda p: bs.patches.append(p))
                rt = types.SimpleNamespace(tsfm=ts, kronos=kr, baskets=bs, log=_Log())
                st = M.apply_142(rt)
                self.assertTrue(st["models_assist_done"], st)
                self.assertEqual(st["errors"], [])
                for mid, mc in ts.settings.get().models.items():
                    for path, u in mc.use.items():
                        self.assertEqual(u.use, "ASSIST", (mid, path))
                        self.assertEqual(u.activation_policy, "DIRECT_USER_REQUEST")
                        self.assertIsNone(u.validation_report)                      # no report is invented
                        self.assertIn(u.timeframe, mc.timeframes)
                ku = kr.settings.get().strategy_use
                self.assertEqual(ku["SCALPING"].use, "ASSIST")
                self.assertEqual(ku["HEDGING"].use, "REQUIRED")                     # a stronger user choice is kept
                self.assertEqual(bs.patches, [{"profiles": {"FOREX_MT5": {"execution": "AUTO_SH"}}}])
                # runs once: a later user change (OBSERVE) is never overwritten
                TsfmService.set_use(ts, "chronos2", "ACTIVE", "OBSERVE")
                M.apply_142(rt)
                self.assertEqual(ts.settings.get().models["chronos2"].use["ACTIVE"].use, "OBSERVE")
                self.assertEqual(len(bs.patches), 1)
            finally:
                if old is None:
                    os.environ.pop("MASTERQUO_DATA_DIR", None)
                else:
                    os.environ["MASTERQUO_DATA_DIR"] = old


class TestKronosAssist(unittest.TestCase):
    def _ctx(self, rel, avail=True):
        f = {"direction_pl": "spadek", "delta_price": -1.2, "horizon_bars": 12}
        return {"use": "ASSIST", "timeframe": "M5", "available": avail, "relation": rel, "forecast": f if avail else None, "reason": None if avail else "brak"}

    def test_assist_holds_only_on_contrary_fresh_forecast(self):
        from masterquo.kronos import predictions as KP
        su = KP.apply_to_setup({"status": "READY", "side": "BUY"}, self._ctx("PRZECIWNY"))
        self.assertEqual(su["status"], "WAIT")
        for rel, av in (("ZGODNY", True), ("NEUTRALNY", True), ("BRAK", False)):
            su = KP.apply_to_setup({"status": "READY", "side": "BUY"}, self._ctx(rel, av))
            self.assertEqual(su["status"], "READY", rel)                            # never a permission, never a block without a forecast
        su = KP.apply_to_setup({"status": "WAIT", "side": "BUY"}, self._ctx("ZGODNY"))
        self.assertEqual(su["status"], "WAIT")                                       # ASSIST never upgrades

    def test_assist_without_report_is_allowed_required_is_not(self):
        from masterquo.kronos import settings as KS
        from masterquo.kronos.service import KronosService
        with tempfile.TemporaryDirectory() as d:
            kr = types.SimpleNamespace(settings=KS.SettingsStore(Path(d) / "k.json"), applog=_Log())
            self.assertTrue(KronosService.set_strategy_use(kr, "SCALPING", "ASSIST")["ok"])
            self.assertEqual(kr.settings.get().strategy_use["SCALPING"].use, "ASSIST")
            self.assertFalse(KronosService.set_strategy_use(kr, "SCALPING", "YOLO")["ok"])


if __name__ == "__main__":
    unittest.main()
