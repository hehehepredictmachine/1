"""1.33 U5 - Pepe Data & Training Studio: registry (concrete tasks, categories, operations), cross-process lock, persistent sequential
queue (dedup, reorder, cancel, recovery), full process of ONE task into ONE package on SYNTHETIC data (trainhub tabular model and a
family), stage checksums + resume, verify_loader in a clean process, transfer through the bot inbox, import as inactive candidate and
rollback. Studio never imports the bot Runtime and never sends orders."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

import _env  # noqa: F401


class Env(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="studio_"))
        self.studio = self.td / "studio data"                    # path with a space
        self.bot = self.td / "bot data"
        self.studio.mkdir()
        self.bot.mkdir()
        self.old = {k: os.environ.get(k) for k in ("MQ_STUDIO_DATA_DIR", "MQ_BOT_DATA_DIR", "MASTERQUO_DATA_DIR")}
        os.environ.update(MQ_STUDIO_DATA_DIR=str(self.studio), MQ_BOT_DATA_DIR=str(self.bot), MASTERQUO_DATA_DIR=str(self.studio))

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.td, ignore_errors=True)

    def queue(self):
        from masterquo.studio.queue import Queue
        return Queue(env={"MASTERQUO_DATA_DIR": str(self.studio), "MQ_STUDIO_DATA_DIR": str(self.studio), "MQ_BOT_DATA_DIR": str(self.bot),
                          "PYTHONPATH": str(_env.ROOT / "backend")})

    def run_all(self, q, timeout=900):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if q.step() == "IDLE":
                return
            time.sleep(0.5)
        self.fail("queue timeout")

    def key(self, model, inst="XAUUSD"):
        from masterquo.studio import registry as R
        return next(t["task_key"] for t in R.tasks() if t["model_id"] == model and t["instrument"] == inst)


class TestRegistryLock(Env):
    def test_tasks_are_concrete_and_categorised(self):
        from masterquo.studio import registry as R
        ts = R.tasks()
        keys = [t["task_key"] for t in ts]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual({t["instrument"] for t in ts if t["model_id"] == "TH_XGB"}, {"XAUUSD", "BTC"})
        br = next(t for t in ts if t["model_id"] == "BREAKOUT")
        self.assertEqual(br["category"], "CALIBRATABLE")
        self.assertNotIn("TRAIN", R.operations(br))
        self.assertIn("CALIBRATE", R.operations(br))
        det = next(t for t in ts if t["model_id"] == "IND_SEMIVAR")
        self.assertEqual(R.operations(det), ["FULL_EXPORT", "VALIDATE", "EXPORT_FEATURES"])
        self.assertEqual(R.operations(next(t for t in ts if t["model_id"] == "KRONOS_BASE")), [])   # no fake training button
        self.assertEqual(R.matrix()["count"], len(ts))

    def test_cross_process_lock(self):
        import subprocess
        from masterquo.studio.lock import Lock
        p = self.td / "locks" / "x.lock"
        code = ("import sys,time;sys.path.insert(0,%r);from masterquo.studio.lock import Lock;from pathlib import Path;"
                "l=Lock(Path(%r),app='other');print(l.acquire('J1')[0],flush=True);time.sleep(4)") % (str(_env.ROOT / "backend"), str(p))
        pr = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        self.assertEqual(pr.stdout.readline().strip(), "True")
        mine = Lock(p, app="studio")
        ok, owner = mine.acquire("J2")
        self.assertFalse(ok)
        self.assertEqual(owner["app"], "other")
        pr.wait()
        ok, _ = mine.acquire("J2")                                                     # dead owner -> stale lock taken over
        self.assertTrue(ok)
        mine.release()
        self.assertFalse(p.exists())


class TestQueueAndFullProcess(Env):
    def test_dedup_reorder_cancel_recover(self):
        q = self.queue()
        src = {"mode": "SYNTHETIC", "days": 20}
        a = q.submit(self.key("TH_LOGREG"), "BUILD_DATASET", source=src)
        self.assertTrue(q.submit(self.key("TH_LOGREG"), "BUILD_DATASET", source=src)["deduplicated"])
        c = q.submit(self.key("KALMAN_LS"), "FIT", source=src)
        self.assertTrue(q.move(c["job_id"], a["job_id"]))
        self.assertEqual(q.next_job()["job_id"], c["job_id"])
        self.assertTrue(q.cancel(a["job_id"]))
        self.assertEqual(q.job(a["job_id"])["state"], "CANCELLED")
        q.db.execute("UPDATE jobs SET state='TRAINING', pid=999999 WHERE job_id=?", (c["job_id"],))
        q2 = self.queue()                                                              # restart -> orphan becomes INTERRUPTED
        self.assertEqual(q2.job(c["job_id"])["state"], "INTERRUPTED")
        self.assertTrue(q2.resume(c["job_id"]))

    def test_busy_when_other_holds_lock(self):
        from masterquo.studio import settings as S
        from masterquo.studio.lock import Lock
        other = Lock(S.export_lock_path(), app="bot-export")
        self.assertTrue(other.acquire("BOTEXPORT")[0])
        try:
            q = self.queue()
            q.submit(self.key("KALMAN_LS"), "FIT", source={"mode": "SYNTHETIC", "days": 10})
            q.lock.path = S.export_lock_path()
            # the other owner is this test process (alive) - a different job id: Studio must wait
            self.assertTrue(q.step().startswith("BUSY:"))                              # never two exports at once
        finally:
            other.release()

    def test_three_models_sequential_packages_transfer_import_rollback(self):
        q = self.queue()
        src = {"mode": "SYNTHETIC", "days": 25}
        jobs = q.submit_many([self.key("TH_LOGREG"), self.key("KALMAN_LS")], "FULL_PROCESS", source=src)
        jobs.append(q.submit(self.key("IND_SEMIVAR"), "EXPORT_FEATURES", source=src))
        starts = []
        t0 = time.time()
        while time.time() - t0 < 1200:
            st = q.step()
            if st == "STARTED":
                starts.append(q.current)
                self.assertLessEqual(sum(1 for j in q.jobs() if j["state"] not in ("QUEUED",) and j["finished_at"] is None), 1)
            if st == "IDLE":
                break
            time.sleep(0.5)
        self.assertEqual(starts, [j["job_id"] for j in jobs])                          # order kept, one at a time
        res = {j["job_id"]: q.job(j["job_id"]) for j in jobs}
        for jid, j in res.items():
            self.assertIn(j["state"], ("PACKAGED", "FEATURES_EXPORTED"), (jid, j["state"], j["error"]))
        pk = {jid: Path(j["package"]) for jid, j in res.items()}
        self.assertEqual(len(set(pk.values())), 3)                                     # one package per model
        th = pk[jobs[0]["job_id"]]
        self.assertFalse(str(th).endswith(".partial"))
        for f in ("manifest.json", "feature_schema.json", "label_schema.json", "splits.json", "training_config.json", "REPRODUCE.md"):
            self.assertTrue((th / f).exists(), f)
        for d in ("raw", "dataset", "validation", "artifact", "evaluation", "logs"):
            self.assertTrue((th / d).is_dir(), d)
        man = json.loads((th / "manifest.json").read_text())
        self.assertEqual(man["task"]["model_id"], "TH_LOGREG")
        self.assertTrue(json.loads((th / "evaluation" / "verify_loader" / "loader.json").read_text())["ok"])
        self.assertEqual(json.loads((th / "training_config.json").read_text())["package"], str(th))       # explicit dataset path
        self.assertTrue((pk[jobs[2]["job_id"]] / "dataset" / "build_dataset" / "features.csv").exists())
        from masterquo.studio.package import Package
        self.assertTrue(Package(self.studio, man["task"], man["run_id"]).stage_done("export"))
        from masterquo.studio import importer as IM
        inbox = self.bot / "studio_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "x.json").write_text(json.dumps({"package": str(th)}))
        (inbox / "y.json").write_text(json.dumps({"package": str(pk[jobs[1]["job_id"]])}))
        os.environ["MASTERQUO_DATA_DIR"] = str(self.bot)
        try:
            out = IM.process_inbox()
            self.assertTrue(all(r["ok"] for r in out), out)
            from masterquo.trainhub import registry as TR
            self.assertEqual(TR.registry("XAUUSD").get("active") or {}, {})            # never activated by an import
            self.assertFalse(IM.import_package(th)["ok"])                              # same version: nothing overwritten
            for r in out:
                self.assertTrue(IM.rollback(r["import_id"])["ok"])
            self.assertEqual(TR.summary("XAUUSD")["versions"], [])
        finally:
            os.environ["MASTERQUO_DATA_DIR"] = str(self.studio)

    def test_tampered_stage_is_redone(self):
        q = self.queue()
        j = q.submit(self.key("KALMAN_LS"), "BUILD_DATASET", source={"mode": "SYNTHETIC", "days": 10})
        self.run_all(q)
        job = q.job(j["job_id"])
        self.assertEqual(job["state"], "READY_FOR_TRAINING", job["error"])
        d = Path(job["package"])
        man = json.loads((d / "manifest.json").read_text())
        from masterquo.studio.package import Package
        p = Package(self.studio, man["task"], man["run_id"])
        self.assertTrue(p.stage_done("build_dataset"))
        next((d / "dataset" / "build_dataset").glob("bars_*.json")).write_text("[]")
        self.assertFalse(p.stage_done("build_dataset"))


class TestStudioIsolation(unittest.TestCase):
    def test_studio_app_does_not_import_runtime_or_orders(self):
        import subprocess
        code = ("import sys;sys.path.insert(0,%r);import masterquo.studio.app as A;"
                "bad=[m for m in sys.modules if m.startswith(('masterquo.runtime','masterquo.execution','masterquo.engine','masterquo.sh.'))];"
                "print(bad)") % str(_env.ROOT / "backend")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip(), "[]", out.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
