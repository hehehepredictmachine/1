"""1.42.10 – Centrum Treningowe Pepe i naprawy treningu:
* stan modeli z przebiegów `training run` (najnowszy wpis, pominięcie zadań spoza planu, przerwany trening = błąd),
* kolejka: modele głównego treningu w jednym przebiegu, bez duplikatów, jeden trening naraz, historia, anulowanie, niedostępne pominięte,
* rodziny modeli: świece z MT5 na żywo, gdy archiwum eksportu jest puste („0 świec”), najwyżej 2 procesy naraz, martwy proces = FAILED z logiem,
* SDformerFlow zwalnia slot ciężkiego treningu w Memory Governorze (wcześniej blokował Granite / kolejny trening do restartu bota)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import types
import unittest
from pathlib import Path

import _env
from _env import TempData


def _run_state(rid: str, status: str, tasks: list[tuple]) -> dict:
    return {"run_id": rid, "status": status, "tasks": [{"kind": k, "instrument": i, "execution": e, "quality": q, "detail": d, "updated_at": "2026-11-19T05:00:00Z"}
                                                       for k, i, e, q, d in tasks]}


class TestPipelineStatus(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.training import core as tc
        self.tc = tc

    def tearDown(self):
        self.td.close()

    def write(self, rid, st):
        d = self.tc.runs_dir() / rid
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps(st), encoding="utf-8")

    def test_newest_attempt_wins_and_plan_filters(self):
        from masterquo.training import pepe_center as P
        self.write("TR-20261101T000000Z-aaaa", _run_state("TR-20261101T000000Z-aaaa", "FINISHED", [
            ("forecast", "XAUUSD", "UKONCZONE", "ZWALIDOWANY_SHADOW", ""), ("ml", "XAUUSD", "BLAD_TECHNICZNY", "NIE_DOTYCZY", "Traceback: X"),
            ("lab", "XAUUSD", "UKONCZONE", "BRAK_PRZESLANEK", "za mało zdarzeń")]))
        self.write("TR-20261102T000000Z-bbbb", _run_state("TR-20261102T000000Z-bbbb", "FINISHED", [
            ("forecast", "XAUUSD", "POMINIETE", "NIE_DOTYCZY", "nie wybrano w planie"), ("ml", "XAUUSD", "UKONCZONE", "NIEZWALIDOWANY", ""),
            ("scalp_A", "BTC", "W_TOKU", "NIE_DOTYCZY", "")]))
        st = P.pipeline_status()
        self.assertEqual(st[("forecast", "XAUUSD")]["state"], "DONE")                  # starszy wynik, nowy przebieg go nie trenował
        self.assertEqual(st[("forecast", "XAUUSD")]["detail"], "zwalidowany")
        self.assertEqual(st[("ml", "XAUUSD")]["state"], "DONE")                        # najnowsza próba wygrywa z błędem sprzed dnia
        self.assertEqual(st[("lab", "XAUUSD")]["state"], "SKIPPED")                    # BRAK_PRZESLANEK = za mało danych, nie „wytrenowany”
        self.assertEqual(st[("scalp_A", "BTC")]["state"], "FAILED")                    # W_TOKU bez żywego procesu = przerwany
        self.assertIn("przerwany", st[("scalp_A", "BTC")]["detail"])


class FakeTrainhub:
    def __init__(self):
        self.jobs = []

    def list(self, n):
        return self.jobs[::-1][:n]

    def submit(self, kind, inst, params):
        j = {"id": f"TJ-{len(self.jobs)}", "kind": kind, "instrument": inst, "status": "SUCCEEDED", "stage": "ok"}
        self.jobs.append(j)
        return j

    def get(self, jid):
        return next((j for j in self.jobs if j["id"] == jid), None)


class TestQueue(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.training import pepe_center as P
        self.P = P
        rt = types.SimpleNamespace(demo=True, trainhub=FakeTrainhub(), families=None, research=None, tsfm=None)
        self.c = P.PepeTrainingCenter(rt)
        self.ran = []
        gate = self.gate = threading.Event()

        def fake_run(q):
            self.ran.append((q["unit"], tuple(q["instruments"]), tuple(q["tasks"] or ())))
            gate.wait(5)
            return {"state": "DONE", "detail": "ok"}
        self.c._run = fake_run

    def tearDown(self):
        self.gate.set()
        self.td.close()

    def wait_idle(self):
        for _ in range(200):
            if not self.c.current and not self.c.queue:
                return
            time.sleep(0.02)
        self.fail("kolejka nie skończyła")

    def test_all_is_one_pipeline_run_plus_units_one_at_a_time(self):
        r = self.c.enqueue("ALL", ["XAUUSD", "BTC"])
        units = [a["unit"] for a in r["added"]]
        self.assertEqual(units.count("pipeline"), 1)                                     # wszystkie modele głównego treningu w JEDNYM przebiegu
        self.assertIsNone(r["added"][0]["tasks"])                                       # ALL = bez --tasks (pełny plan)
        self.assertIn("trainhub", units)
        self.assertNotIn("families", units)                                             # niedostępne (rt.families None) – pominięte z powodem
        self.assertTrue(any(s["unit"] == "families" for s in r["skipped"]))
        again = self.c.enqueue(["trainhub"], ["XAUUSD"])                                 # już czeka / trwa -> nie dublujemy
        self.assertEqual(again["added"], [])
        self.gate.set()
        self.wait_idle()
        self.assertEqual(self.ran[0][0], "pipeline")
        self.assertEqual(len(self.c.history), len(r["added"]))
        self.assertTrue(all(h["state"] == "DONE" for h in self.c.history))
        self.assertTrue((self.P.center_dir() / "history.json").exists())

    def test_single_units_and_cancel(self):
        self.c.enqueue(["forecast", "ml"], ["XAUUSD"])
        self.c.enqueue(["trainhub"], ["BTC"])
        for _ in range(100):
            if self.c.current:
                break
            time.sleep(0.02)
        self.assertEqual(self.c.current["tasks"], ["forecast", "ml"])
        st = self.c.status()
        row = {u["id"]: u for u in st["units"]}
        self.assertEqual(row["forecast"]["status"]["XAUUSD"]["state"], "RUNNING")
        self.assertEqual(row["trainhub"]["status"]["BTC"]["state"], "QUEUED")
        self.assertEqual(row["forecast"]["status"]["BTC"]["state"], "NOT_TRAINED")
        r = self.c.cancel()
        self.assertEqual(r["dropped"], 1)
        self.gate.set()
        self.wait_idle()
        self.assertEqual(self.c.history[-1]["state"], "CANCELLED")
        with self.assertRaises(ValueError):
            self.c.enqueue(["nie_ma"], None)


class TestCommissionSettings(unittest.TestCase):
    """Prowizja z Centrum trafia do `training run` (bez niej Scalp/ML BTC są pomijane: brak transakcji w historii)."""

    def setUp(self):
        self.td = TempData()
        from masterquo.training import pepe_center as P
        self.P = P
        self.c = P.PepeTrainingCenter(types.SimpleNamespace(demo=False, trainhub=None, families=None, research=None, tsfm=None))

    def tearDown(self):
        self.td.close()

    def test_settings_roundtrip_and_cli_flags(self):
        self.assertEqual(self.c.status()["settings"], {"commission_xauusd": None, "commission_btc": None})
        self.c.set_settings({"commission_btc": "7,5"})
        self.assertEqual(self.c.settings()["commission_btc"], 7.5)
        self.assertIsNone(self.c.settings()["commission_xauusd"])
        with self.assertRaises(ValueError):
            self.c.set_settings({"commission_xauusd": -1})
        seen = {}

        class P:
            returncode = 0
            def __init__(self, cmd, **kw):
                seen["cmd"] = cmd
            def poll(self):
                return 0
        orig = self.P.subprocess.Popen
        self.P.subprocess.Popen = P
        try:
            r = self.c._run_pipeline({"instruments": ["XAUUSD", "BTC"], "tasks": ["scalp_A"], "covers": ["scalp_A"]})
        finally:
            self.P.subprocess.Popen = orig
        self.assertEqual(r["state"], "DONE")
        cmd = seen["cmd"]
        self.assertIn("--commission-btc", cmd)
        self.assertEqual(cmd[cmd.index("--commission-btc") + 1], "7.5")
        self.assertNotIn("--commission-xauusd", cmd)                                   # puste = z historii transakcji
        self.c.set_settings({"commission_btc": ""})
        self.assertIsNone(self.c.settings()["commission_btc"])

    def test_popen_failure_is_failed_not_crash(self):
        orig = self.P.subprocess.Popen

        def boom(*a, **k):
            raise OSError("brak pliku")
        self.P.subprocess.Popen = boom
        try:
            r = self.c._run_pipeline({"instruments": ["XAUUSD"], "tasks": None, "covers": []})
        finally:
            self.P.subprocess.Popen = orig
        self.assertEqual(r["state"], "FAILED")
        self.assertIn("brak pliku", r["detail"])


class TestEnsureBars(unittest.TestCase):
    """Granite / rodziny: przy pustym archiwum świec Centrum najpierw pobiera historię z MT5 (eksport TrainHub), a nie kończy „0 świec”."""

    def setUp(self):
        self.td = TempData()
        from masterquo.training import pepe_center as P
        self.th = FakeTrainhub()
        self.c = P.PepeTrainingCenter(types.SimpleNamespace(demo=True, trainhub=self.th, families=None, research=None, tsfm=None))

    def tearDown(self):
        self.td.close()

    def test_empty_store_runs_export_first(self):
        q = {"unit": "granite", "instruments": ["XAUUSD"]}
        self.assertEqual(self.c._ensure_bars(q, "XAUUSD", "M5", 5000), "")
        self.assertEqual([(j["kind"], j["instrument"]) for j in self.th.jobs], [("EXPORT", "XAUUSD")])
        self.th.submit = lambda kind, inst, params: self.th.jobs.append({"id": "X", "kind": kind, "status": "FAILED", "error": "brak symbolu brokera"}) or self.th.jobs[-1]
        err = self.c._ensure_bars(q, "BTC", "M5", 5000)
        self.assertIn("brak symbolu brokera", err)

    def test_failed_attempt_shown_at_model(self):
        self.c.history.append({"id": "h1", "unit": "trainhub", "instruments": ["BTC"], "state": "FAILED", "detail": "MT5 rozłączony",
                               "finished_at": time.time()})
        row = {u["id"]: u for u in self.c.status()["units"]}["trainhub"]["status"]
        self.assertEqual(row["BTC"]["state"], "FAILED")
        self.assertIn("MT5 rozłączony", row["BTC"]["detail"])
        self.assertEqual(row["XAUUSD"]["state"], "NOT_TRAINED")

    def test_waits_for_other_heavy_training(self):
        gov = types.SimpleNamespace(training={"sdformerflow": "heavy"})
        self.c.rt.governor = gov
        q = {"unit": "granite", "instruments": ["XAUUSD"]}
        threading.Timer(0.3, lambda: gov.training.pop("sdformerflow")).start()
        self.c.clock = time.time
        orig = self.c._wait
        self.c._wait = lambda done, timeout, step=3.0: orig(done, timeout=timeout, step=0.05)
        t0 = time.time()
        self.c._wait_heavy_slot(q)
        self.assertGreaterEqual(time.time() - t0, 0.25)                                 # czekało, nie pominęło
        self.assertEqual(gov.training, {})
        self.assertEqual(q["detail"], "")

    def test_granite_without_weights_is_unavailable(self):
        from masterquo.tsfm import settings as TS
        tmp = Path(self.td.dir)
        tsfm = types.SimpleNamespace(settings=types.SimpleNamespace(get=lambda: types.SimpleNamespace(models={"granite_ttm": {}})),
                                     weights_root=lambda: tmp / "weights")
        self.c.rt.tsfm = tsfm
        orig = TS.find_python
        TS.find_python = lambda mid, c: sys.executable                                  # środowisko jest …
        try:
            why = self.c.availability().get("granite", "")
            self.assertIn("brak wag Granite TTM", why)                                  # … ale wag brak -> NIEDOSTĘPNY z instrukcją
            from tsfm_runtime import manifest as TM
            TM.write(tmp / "weights", "granite_ttm", {"schema": "x", "files": []})
            self.assertNotIn("granite", self.c.availability())
        finally:
            TS.find_python = orig

    def test_no_export_when_archive_long_enough(self):
        self.assertEqual(self.c._ensure_bars({}, "XAUUSD", "M5", 0), "")
        self.assertEqual(self.th.jobs, [])


class FakeBridge:
    def __init__(self, n):
        self.n = n

    def symbol_bars(self, sym, tf, count):
        t0 = 1_790_000_000
        return [{"open_utc": __import__("datetime").datetime.fromtimestamp(t0 + i * 300, __import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z"),
                 "o": 100 + i * .01, "h": 100.2 + i * .01, "l": 99.8 + i * .01, "c": 100.1 + i * .01, "tv": 10, "closed": True}
                for i in range(min(count, self.n))]


class TestFamilies(unittest.TestCase):
    def setUp(self):
        self.td = TempData()
        from masterquo.config import ConfigStore
        from masterquo.modelhub.families.service import FamilyService
        self.cfg = ConfigStore()
        self.FS = FamilyService

    def tearDown(self):
        self.td.close()

    def test_live_bars_when_export_archive_empty(self):
        fs = self.FS(self.cfg, FakeBridge(4000))
        f = fs._live_bars_file("TS_ARIMA", "XAUUSD")
        self.assertIsNotNone(f)
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        self.assertEqual((d["source"], d["tf"]), ("MT5_LIVE_BRIDGE", "M5"))
        self.assertGreaterEqual(len(d["bars"]), 800)
        from masterquo.modelhub.families import run as R
        from masterquo.modelhub.families import registry
        data = R.load_data(registry()["TS_ARIMA"], "XAUUSD", {}, str(f))
        self.assertEqual(data["data_kind"], "MT5_LIVE_BRIDGE")
        ok, why = registry()["TS_ARIMA"].validate_data(data)
        self.assertTrue(ok, why)                                                         # było: „za mało świec M5: 0 < 800”
        self.assertIsNone(self.FS(self.cfg, None)._live_bars_file("TS_ARIMA", "XAUUSD"))   # bez MT5: zostaje komunikat o danych

    def test_train_all_at_most_two_at_once_and_dead_process_is_failed(self):
        fs = self.FS(self.cfg, None)
        started = []

        def fake_submit(fid, inst, profile="smoke"):
            p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
            fs.procs[f"{fid}__{inst}"] = p
            started.append(fid)
            return {"ok": True, "status": "STARTED", "pid": p.pid}
        fs.submit = fake_submit
        out = fs.train_all("XAUUSD", "smoke")
        self.assertEqual(len(out["started"]), fs.MAX_PARALLEL)
        self.assertTrue(out["queued"])
        self.assertTrue(all((fs.job(q["family"], "XAUUSD") or {}).get("state") == "QUEUED" for q in out["queued"]))
        for _ in range(200):
            if len(started) == len(out["started"]) + len(out["queued"]):
                break
            time.sleep(0.05)
        self.assertEqual(len(started), len(out["started"]) + len(out["queued"]))       # kolejka sama dokończyła
        # martwy proces bez wyniku -> FAILED z linią błędu z logu
        fid = "VOL_GARCH"
        p = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
        p.wait()
        fs.procs[f"{fid}__XAUUSD"] = p
        fs._log_file(fid, "XAUUSD").write_text("start\nMemoryError: brak pamięci\n", encoding="utf-8")
        from masterquo.modelhub.families import base as B
        B._atomic_json(fs._job_file(fid, "XAUUSD"), {"state": "RUNNING", "pid": p.pid, "family": fid})
        j = fs.job(fid, "XAUUSD")
        self.assertEqual(j["state"], "FAILED")
        self.assertIn("MemoryError", j["reason"])


class TestSdformerReleasesTrainingSlot(unittest.TestCase):
    def test_training_done_after_job(self):
        td = TempData()
        try:
            from masterquo.research import service as RS
            calls = []
            gov = types.SimpleNamespace(admit_training=lambda *a, **k: (calls.append("admit"), (True, None))[1],
                                        training_done=lambda name: calls.append("done:" + name), register=lambda *a, **k: None)
            svc = RS.ResearchModulesService.__new__(RS.ResearchModulesService)
            svc.governor, svc._sdf_proc, svc.jobs = gov, None, {}
            tmp = Path(td.dir) / "sdf"
            tmp.mkdir()
            svc._sdf_dir = lambda: tmp
            svc.settings = lambda: {"sdformer": {"epochs": 1, "minutes": 1, "batch": 4, "threads": 1, "active_run": None}}
            svc._activate_sdformer = lambda run_id, job: None
            orig_tp, orig_popen = RS.torch_python, RS.subprocess.Popen
            RS.torch_python = lambda: sys.executable
            RS.subprocess.Popen = lambda argv, **kw: orig_popen([sys.executable, "-c", "print('RESULT {\"ok\": false, \"code\": \"X\"}')"], **kw)
            try:
                r = svc.start_training(types.SimpleNamespace(key="K"), [{"t": 1}], op="from_scratch", reason="test")
                self.assertTrue(r["ok"])
                for _ in range(100):
                    if r["job"]["state"] != "RUNNING":
                        break
                    time.sleep(0.05)
            finally:
                RS.torch_python, RS.subprocess.Popen = orig_tp, orig_popen
            self.assertEqual(r["job"]["state"], "FAILED")
            self.assertIn("done:sdformerflow", calls)                                  # slot zwolniony – Granite / kolejny trening mogą ruszyć
        finally:
            td.close()


if __name__ == "__main__":
    unittest.main()
