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


def gov(used=50.0, rss=None, profile="LOW_MEMORY_16GB", manual=None, total_mb=16384):
    from masterquo.resources.governor import Governor
    state = {"used": used, "rss": rss or {}}
    g = Governor(Store(Cfg(profile, manual)), memory=lambda: {"total_mb": total_mb, "used_pct": state["used"], "process_mb": 300.0},
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
        for m in ("granite_ttm", "chronos2", "tirex2"):
            self.assertFalse(g.admit(m, loaded=True)[0], m)
        self.assertTrue(g.admit("kronos", loaded=True)[0])                     # 1.42.9: Kronos zawsze
        self.assertGreaterEqual(g.counters["refused"], 4)
        g2, _ = gov(used=95.0, profile="MANUAL", manual={"auto_throttle": False})   # MANUAL can switch throttling off
        self.assertTrue(g2.admit("kronos", loaded=False)[0])

    def test_assist_model_under_pause(self):
        """1.42.6: at PAUSE_OPTIONAL a model used in decisions (ASSIST) gets memory from OTHER idle heavy processes at once; loaded it keeps
        answering; not loaded it starts only after the level drops; OBSERVE models (essential=False) pause as before."""
        g, st = gov(used=88.0)
        released, alive = [], {"chronos2": 11, "tirex2": 12}
        g.register("chronos2", "heavy", lambda: alive.get("chronos2"), release=lambda: (released.append("chronos2"), alive.pop("chronos2", None)), idle=lambda: 45.0)
        g.register("tirex2", "heavy", lambda: alive.get("tirex2"), release=lambda: released.append("tirex2"), idle=lambda: 5.0)   # computes now
        g.register("tabicl", "heavy", lambda: 13, release=lambda: released.append("tabicl"), idle=lambda: 999.0)
        self.assertFalse(g.admit("tabicl", loaded=True)[0])                          # OBSERVE: paused
        self.assertEqual(released, [])
        self.assertTrue(g.admit("tabicl", loaded=True, essential=True)[0])           # ASSIST + loaded: answers
        self.assertEqual(released, ["chronos2"])                                     # idle 45 s released, TiRex-2 (5 s) and TabICL kept
        ok, why = g.admit("chronos2", loaded=False, essential=True)                  # ASSIST, not loaded, still >= 85 % -> not loaded
        self.assertFalse(ok)
        self.assertIn("ASSIST", why)
        st["used"] = 70.0
        self.assertTrue(g.admit("chronos2", loaded=False, essential=True)[0])        # below the pause -> normal rules

    def test_kronos_small_is_light(self):
        """1.42.8: Kronos-small (~0,47 GB) to model lekki – nie zajmuje gniazda ciężkich. 1.42.9 (decyzja użytkownika): Kronos liczy ZAWSZE –
        bez względu na zajętość RAM, profil i rolę (OBSERVE / ASSIST); governor nigdy go nie zwalnia."""
        from masterquo.resources import governor as GV
        self.assertIn("kronos", GV.LIGHT)
        self.assertNotIn("kronos", GV.HEAVY)
        self.assertIn("kronos", GV.ALWAYS_ON)
        for used in (90.0, 99.0):
            for prof in ("LOW_MEMORY_16GB", "LOW_MEMORY_8GB", "ECO"):
                g, st = gov(used=used, profile=prof, total_mb=8192)
                for ess in (False, True):
                    for loaded in (False, True):
                        self.assertEqual(g.admit("kronos", loaded=loaded, essential=ess), (True, None), (used, prof, ess, loaded))
        released = []
        for kind in ("light", "heavy"):                                              # nawet zarejestrowany jako ciężki – nie zwalniany
            g, st = gov(used=99.0, profile="ECO")
            g.register("kronos", kind, lambda: 13, release=lambda: released.append("kronos"), idle=lambda: 9999.0)
            g.maintain()
            g._release_idle_heavy(except_model="x", min_idle_s=0.0, why="t")
            g._make_room("chronos2", 0)
        self.assertEqual(released, [])
        g, st = gov(used=90.0)
        st["used"] = 82.0                                                            # LIMIT_HEAVY: light model still starts
        self.assertTrue(g.admit("kronos", loaded=False)[0])
        with g.heavy("chronos2") as a:
            with g.heavy("kronos") as b:                                             # does not wait for the heavy slot
                self.assertTrue(a and b)
        self.assertEqual(g.threads_for("kronos"), g.profile()["threads_heavy"])     # keeps the faster thread count

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
        ths = [threading.Thread(target=work, args=(m,)) for m in ("tirex2", "chronos2", "tirex2", "chronos2")]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(peak[0], 1)                                            # never two heavy models at once (parallelism 1)
        self.assertGreater(g.counters["heavy_waits"], 0)
        with g.heavy("granite_ttm") as got:                                     # light model does not take the slot
            with g.heavy("chronos2") as got2:
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
        eco.register("tirex2", "heavy", lambda: 11, release=lambda: released.append("tirex2"), idle=lambda: 601.0)
        self.assertEqual(eco.maintain(), ["tirex2"])
        busy, _ = gov(used=90.0, rss={11: 1200.0})
        busy.register("tirex2", "heavy", lambda: 11, release=lambda: released.append("busy"), idle=lambda: 0.0)   # running -> idle 0
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

    def test_low_memory_8gb_profile(self):
        """8 GB computer - Granite TTM + ONE heavy model resident; every model may run, the others are released before it loads."""
        g, st = gov(used=70.0, profile="LOW_MEMORY_8GB")
        p = g.profile()
        self.assertEqual((p["budget_max_mb"], p["max_resident_heavy"], p["idle_release_s"], p["threads_light"]), (3328, 1, 90, 1))
        self.assertTrue(g.admit("kronos", loaded=False)[0])
        self.assertFalse(g.admit("sdformerflow", loaded=False)[0])                    # not in heavy_allowed
        self.assertTrue(g.admit("granite_ttm", loaded=False)[0])                      # light model
        released = []
        alive = {"tabicl": 11}
        g.register("tabicl", "heavy", lambda: alive.get("tabicl"), release=lambda: (released.append("tabicl"), alive.pop("tabicl", None)), idle=lambda: 5)
        g.register("tirex2", "heavy", lambda: alive.get("tirex2"), release=lambda: released.append("tirex2"), idle=lambda: 0)
        st["rss"] = {11: 700.0}
        self.assertTrue(g.admit("tirex2", loaded=False)[0])                          # TabICL released BEFORE TiRex-2 loads
        self.assertEqual(released, ["tabicl"])
        self.assertTrue(g.admit("tirex2", loaded=True)[0])                           # already loaded: nothing else released
        self.assertEqual(released, ["tabicl"])
        st["used"] = 88.0                                                               # 88 % on 8 GB: still OK for the light model
        self.assertTrue(g.admit("granite_ttm", loaded=True)[0])
        st["used"] = 95.0
        self.assertFalse(g.admit("granite_ttm", loaded=True)[0])

    def test_12gb_and_auto_by_ram(self):
        """1.42.4: 12 GB profile keeps TWO heavy models; AUTO / 16GB / BALANCED are lowered to the computer's RAM, ECO / MANUAL / explicit kept."""
        g, st = gov(used=60.0, profile="LOW_MEMORY_12GB", total_mb=12 * 1024)
        self.assertEqual((g.profile()["max_resident_heavy"], g.profile()["budget_max_mb"]), (2, 5120))
        released = []
        alive = {"tabicl": 1, "chronos2": 2}
        for n in ("tabicl", "chronos2", "tirex2"):
            g.register(n, "heavy", (lambda n=n: alive.get(n)), release=(lambda n=n: (released.append(n), alive.pop(n, None))), idle=lambda: 10)
        self.assertTrue(g.admit("tirex2", loaded=False)[0])
        self.assertEqual(len(released), 1)                                            # one released, two stay resident
        for prof, total, want in (("AUTO", 8 * 1024, "LOW_MEMORY_8GB"), ("AUTO", 12 * 1024, "LOW_MEMORY_12GB"), ("AUTO", 16 * 1024, "LOW_MEMORY_16GB"),
                                  ("LOW_MEMORY_16GB", 8 * 1024, "LOW_MEMORY_8GB"), ("BALANCED", 12 * 1024, "LOW_MEMORY_12GB"),
                                  ("BALANCED", 32 * 1024, "BALANCED"), ("ECO", 8 * 1024, "ECO"), ("LOW_MEMORY_12GB", 32 * 1024, "LOW_MEMORY_12GB")):
            g, _ = gov(profile=prof, total_mb=total)
            self.assertEqual(g.effective_name(), want, (prof, total))
        g, _ = gov(profile="AUTO", total_mb=8 * 1024)
        v = g.public()
        self.assertEqual((v["profile"], v["effective_profile"]), ("AUTO", "LOW_MEMORY_8GB"))
        self.assertIn("AUTO", v["profiles"])

    def test_profiles_threads_and_view(self):
        from masterquo.resources.governor import PROFILE_KEYS, profiles
        ps = profiles()
        self.assertEqual(set(ps), {"LOW_MEMORY_16GB", "LOW_MEMORY_12GB", "LOW_MEMORY_8GB", "ECO", "BALANCED"})
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
