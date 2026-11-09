"""1.40 Memory Governor + AI scheduler (resources/governor.py) on measured values from test doubles (RAM %, process RSS):
levels 75 / 80 / 85 % and the PMW budget, admission (optional forecasts paused at 85 %, heavy model not started at 80 %, a loaded one and the
light Granite TTM still answer), ONE shared heavy slot (Kronos and Chronos-2 never load / compute together), idle release only under
pressure or in ECO (never the light model, never the running one), training gate (no parallel heavy training, none during AUTO trading
unless confirmed), profiles LOW_MEMORY_16GB / ECO / BALANCED / MANUAL from the configuration, and the TSFM path: a paused forecast is
STALE with the reason and NO value (never a neutral vote)."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

import _env
from _env import TempData

sys.path.insert(0, str(Path(__file__).resolve().parent))


class Cfg:
    def __init__(self, profile="LOW_MEMORY_16GB", manual=None):
        from masterquo.config import ResourcesConfig
        self.resources = ResourcesConfig(profile=profile, manual=manual or {})


class Store:
    def __init__(self, cfg):
        self.cfg = cfg

    def get(self):
        return self.cfg


def gov(used=50.0, rss=None, profile="LOW_MEMORY_16GB", manual=None):
    from masterquo.resources.governor import Governor
    state = {"used": used, "rss": rss or {}}
    g = Governor(Store(Cfg(profile, manual)), memory=lambda: {"total_mb": 16384, "used_pct": state["used"], "process_mb": 300.0},
                 proc_mem=lambda pid: (state["rss"].get(pid), state["rss"].get(pid)))
    return g, state


class TestGovernor(unittest.TestCase):
    def test_levels_thresholds_and_budget(self):
        g, st = gov(used=60.0, rss={1: 400.0})
        g.register("bot", "bot", lambda: 1)
        self.assertEqual(g.sample()["level"], "OK")
        for used, lv in ((75.0, "WARN"), (80.0, "LIMIT_HEAVY"), (85.0, "PAUSE_OPTIONAL"), (40.0, "OK")):
            st["used"] = used
            self.assertEqual(g.sample()["level"], lv, used)
        st["rss"] = {1: 9000.0}                                                  # PMW above budget_max (8 GB) -> LIMIT_HEAVY even at 40 %
        snap = g.sample()
        self.assertEqual((snap["level"], snap["pmw_total_mb"]), ("LIMIT_HEAVY", 9000.0))
        st["rss"] = {1: 7000.0}                                                  # above the preferred 6 GB -> WARN
        self.assertEqual(g.sample()["level"], "WARN")
        self.assertEqual(g.peaks["bot"], 9000.0)                                 # peak is kept

    def test_admission_rules(self):
        g, st = gov(used=81.0)
        ok, why = g.admit("chronos2", loaded=False)
        self.assertFalse(ok)
        self.assertIn("ciężki", why)
        self.assertTrue(g.admit("chronos2", loaded=True)[0])                    # a loaded heavy model may still answer
        self.assertTrue(g.admit("granite_ttm", loaded=False)[0])                # light model runs until 85 %
        st["used"] = 86.0
        for m in ("granite_ttm", "chronos2", "kronos"):
            self.assertFalse(g.admit(m, loaded=True)[0], m)
        self.assertGreaterEqual(g.counters["refused"], 4)
        g2, _ = gov(used=95.0, profile="MANUAL", manual={"auto_throttle": False})   # MANUAL can switch throttling off
        self.assertTrue(g2.admit("kronos", loaded=False)[0])

    def test_one_heavy_slot_shared_by_services(self):
        g, _ = gov()
        active, peak = [0], [0]
        lock = threading.Lock()

        def work(m):
            with g.heavy(m) as got:
                self.assertTrue(got)
                with lock:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                time.sleep(0.05)
                with lock:
                    active[0] -= 1
        ths = [threading.Thread(target=work, args=(m,)) for m in ("kronos", "chronos2", "kronos", "chronos2")]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(peak[0], 1)                                            # never two heavy models at once (parallelism 1)
        self.assertGreater(g.counters["heavy_waits"], 0)
        with g.heavy("granite_ttm") as got:                                     # light model does not take the slot
            with g.heavy("kronos") as got2:
                self.assertTrue(got and got2)

    def test_idle_release_only_under_pressure_or_eco(self):
        g, st = gov(used=50.0, rss={11: 1200.0, 12: 350.0})
        released = []
        g.register("chronos2", "heavy", lambda: 11, release=lambda: released.append("chronos2"), idle=lambda: 3600.0)
        g.register("granite_ttm", "light", lambda: 12, release=lambda: released.append("granite_ttm"), idle=lambda: 3600.0)
        self.assertEqual(g.maintain(), [])                                       # LOW_MEMORY, no pressure: models stay loaded (no reload loop)
        st["used"] = 76.0
        self.assertEqual(g.maintain(), ["chronos2"])                            # pressure: idle heavy model released, light one never
        self.assertEqual(released, ["chronos2"])
        eco, st2 = gov(used=50.0, rss={11: 1200.0}, profile="ECO")
        eco.register("kronos", "heavy", lambda: 11, release=lambda: released.append("kronos"), idle=lambda: 601.0)
        self.assertEqual(eco.maintain(), ["kronos"])
        busy, _ = gov(used=90.0, rss={11: 1200.0})
        busy.register("kronos", "heavy", lambda: 11, release=lambda: released.append("busy"), idle=lambda: 0.0)   # running -> idle 0
        self.assertEqual(busy.maintain(), [])

    def test_training_gate(self):
        g, st = gov(used=50.0)
        ok, why = g.admit_training("granite_train", "heavy", trading_active=True)
        self.assertFalse(ok)
        self.assertIn("AUTO", why)
        self.assertTrue(g.admit_training("granite_train", "heavy", trading_active=True, force=True)[0])
        ok, why = g.admit_training("kronos_train", "heavy", trading_active=False)
        self.assertFalse(ok)
        self.assertIn("równolegle", why)
        g.training_done("granite_train")
        st["used"] = 82.0
        self.assertFalse(g.admit_training("kronos_train", "heavy", trading_active=False)[0])

    def test_profiles_threads_and_view(self):
        from masterquo.resources.governor import PROFILE_KEYS, profiles
        ps = profiles()
        self.assertEqual(set(ps), {"LOW_MEMORY_16GB", "ECO", "BALANCED"})
        low = ps["LOW_MEMORY_16GB"]
        self.assertEqual((low["warn_pct"], low["limit_heavy_pct"], low["pause_optional_pct"], low["reserve_os_mb"], low["budget_preferred_mb"],
                          low["budget_max_mb"], low["heavy_parallelism"], low["background_training"], low["auto_download"], low["lazy_loading"]),
                         (75.0, 80.0, 85.0, 4096, 6144, 8192, 1, False, False, True))
        self.assertTrue(all(set(p) == set(PROFILE_KEYS) for p in ps.values()))
        g, _ = gov(profile="MANUAL", manual={"threads_heavy": 3, "warn_pct": 70.0})
        self.assertEqual((g.threads_for("chronos2"), g.profile()["warn_pct"]), (3, 70.0))
        g.record("granite_ttm", ms=2.0)
        g.record("granite_ttm", ms=4.0)
        v = g.public()
        self.assertEqual((v["profile"], v["inference"]["granite_ttm"]["n"]), ("MANUAL", 2))
        self.assertIn("nigdy głos neutralny", v["rule"])
        json.dumps(v)                                                           # API-serializable


@unittest.skipUnless(os.name != "nt", "stub worker uses a POSIX shell wrapper")
class TestTsfmUnderGovernor(unittest.TestCase):
    def test_paused_forecast_is_stale_without_value(self):
        import kronos_testkit as K
        from test_tsfm_bot import WED_1200, fixture_weights, stub_python
        from masterquo.db.database import Database
        from masterquo.tsfm import predictions as TP
        from masterquo.tsfm.service import TsfmService
        from masterquo.tsfm.settings import SettingsStore
        td = TempData()
        os.environ["MQ_TSFM_ALLOW_FIXTURE"] = "1"
        try:
            d = Path(td.dir)
            bridge = K.FakeBridge({("XAUUSD-", "M5"): K.make_bars(600, WED_1200, 10)})
            cfg = K.FakeCfgStore(K.FakeCfg({"XAUUSD": K.FakeMapping("XAUUSD-")}))
            st = SettingsStore(d / "tsfm" / "settings.json")
            root = d / "w"
            for m in ("chronos2", "granite_ttm"):
                fixture_weights(root, m)
            py = stub_python(d, "ok")
            st.update({"weights_root": str(root), "models": {m: {"python_path": py, "timeframes": ["M5"], "instruments": ["XAUUSD"],
                                                                     "request_timeout_s": 5.0} for m in ("chronos2", "granite_ttm")}})
            svc = TsfmService(cfg, bridge, Database(d / "t.sqlite"), K.Bus(), K.Log(), clock=lambda: WED_1200, settings=st)
            g, state = gov(used=86.0)
            svc.governor = g
            svc.tick()
            for k, job in list(svc.queue.items()):
                svc.queue.pop(k)
                self.assertIsNone(svc.run_job(job))
            rows = {r["model_id"]: r for r in TP.contract_predictions(svc, "XAUUSD")}
            for m in ("tsfm:chronos2", "tsfm:granite_ttm"):
                self.assertEqual((rows[m]["state"], rows[m]["result"]), ("STALE", None), m)
                self.assertIn("Memory Governor", rows[m]["unavailable_reason"])
            self.assertTrue(all(w.proc is None for w in svc.workers.values()))   # nothing was started under pressure
            state["used"] = 50.0                                                  # pressure gone -> real (stub) forecasts again
            svc.tick(force=("XAUUSD", "M5"))
            for k, job in list(svc.queue.items()):
                svc.queue.pop(k)
                self.assertIsNotNone(svc.run_job(job))
            self.assertEqual(g.timings.keys(), {"chronos2", "granite_ttm"})
            self.assertEqual(svc.workers["granite_ttm"].state["status"], "READY")
            svc.stop()
        finally:
            os.environ.pop("MQ_TSFM_ALLOW_FIXTURE", None)
            td.close()


if __name__ == "__main__":
    unittest.main()
