"""1.46 audit group B_studio_th_1 - Data & Training Studio (app / importer / lock / pipeline / queue / settings) and the trainhub CLI.
Each test fails on the 1.45.0 / pre-fix version of the file and passes after the fix. No HTTP server: the Studio app is called in-process."""
from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import signal
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import _env


def _call(app, method: str, path: str, body=None, query: str = ""):
    """One ASGI request (Host 127.0.0.1, as the Studio guard requires). Returns (status, json|None); an unhandled error = 500."""
    sent = []
    raw = json.dumps(body).encode() if body is not None else b""

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def send(msg):
        sent.append(msg)
    hdrs = [(b"host", b"127.0.0.1:8780")] + ([(b"content-type", b"application/json")] if raw else [])
    scope = {"type": "http", "method": method, "path": path, "raw_path": path.encode(), "query_string": query.encode(), "headers": hdrs,
             "scheme": "http", "server": ("127.0.0.1", 8780), "client": ("127.0.0.1", 5555), "http_version": "1.1", "root_path": ""}
    try:
        asyncio.run(app(scope, receive, send))
    except Exception:  # noqa: BLE001 - starlette re-raises after answering 500
        return 500, None
    st = next((m["status"] for m in sent if m["type"] == "http.response.start"), 500)
    txt = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    try:
        return st, json.loads(txt)
    except ValueError:
        return st, None


class StudioEnv(unittest.TestCase):
    """Isolated Studio + bot data dirs (as test_studio_u5)."""

    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="studio146_"))
        self.studio, self.bot = self.td / "studio", self.td / "bot"
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

    def app(self):
        from masterquo.studio.app import create_app
        app = create_app(start_worker=False)
        self.addCleanup(app.state.queue.db.close)
        return app

    def queue(self):
        from masterquo.studio.queue import Queue
        q = Queue(self.td / "q.sqlite", lock_path=self.td / "locks" / "x.lock")
        self.addCleanup(q.db.close)
        return q

    def package(self, task=None, run_id="R1"):
        from masterquo.studio.package import Package
        t = task or {"model_id": "KALMAN_LS", "instrument": "XAUUSD", "base_tf": "M5", "task_key": "K", "task_id": "T"}
        return Package(self.studio, t, run_id)


# ------------------------------------------------------------------ chunk_35#8
class TestStudioReadsBotConfig(StudioEnv):
    def test_models_use_bot_mappings_read_only(self):
        from masterquo.config import ConfigStore
        os.environ["MASTERQUO_DATA_DIR"] = str(self.bot)
        try:
            ConfigStore(self.bot / "config.json").update({"mt5": {"symbol": "GOLD.pro"}, "assets": {"mappings": {
                "XAUUSD": {"broker_symbol": "GOLD.pro", "status": "USER_SPECIFIED"},
                "BTC": {"broker_symbol": "BTCUSD.pro", "status": "USER_SPECIFIED"}}}})
        finally:
            os.environ["MASTERQUO_DATA_DIR"] = str(self.studio)
        before = (self.bot / "config.json").read_bytes()
        st, body = _call(self.app(), "GET", "/api/studio/models")
        self.assertEqual(st, 200)
        sym = {(r["instrument"], r["broker_symbol"]) for r in body["items"]}
        self.assertIn(("XAUUSD", "GOLD.pro"), sym)
        self.assertIn(("BTC", "BTCUSD.pro"), sym)
        self.assertFalse((self.studio / "config.json").exists())                 # no default Studio config any more
        self.assertEqual((self.bot / "config.json").read_bytes(), before)       # the bot's file is never rewritten

    def test_missing_bot_config_is_unavailable(self):
        from masterquo.studio import settings as S
        self.assertIsNone(S.bot_config())
        st, body = _call(self.app(), "GET", "/api/studio/models")
        self.assertEqual(st, 200)
        self.assertEqual({r["broker_symbol"] for r in body["items"]}, {None})   # never a guessed 'XAUUSD-'


# ------------------------------------------------------------------ chunk_35#20 / focus_X1#0
class TestImporterPathTraversal(StudioEnv):
    def _pkg(self, task: dict, res: dict) -> Path:
        pkg = self.td / "pkg"
        (pkg / "artifact" / "train").mkdir(parents=True)
        (pkg / "evaluation" / "verify_loader").mkdir(parents=True)
        (pkg / "evaluation" / "verify_loader" / "loader.json").write_text(json.dumps({"ok": True}))
        (pkg / "artifact" / "train" / "train_result.json").write_text(json.dumps(res))
        (pkg / "manifest.json").write_text(json.dumps({"task": task, "stages": {"train": {"status": "COMMITTED", "dir": "artifact/train",
                                                                                          "files": {}}}}))
        return pkg

    def test_crafted_names_never_leave_the_registry(self):
        from masterquo.studio import importer as IM
        os.environ["MASTERQUO_DATA_DIR"] = str(self.bot)
        cases = [({"instrument": "XAUUSD", "task_key": "k", "model_id": "TH_LOGREG"}, {"kind": "TRAINHUB", "model_key": "../../../outside", "version": "v"}),
                 ({"instrument": "XAUUSD", "task_key": "k", "model_id": "TH_LOGREG"}, {"kind": "TRAINHUB", "model_key": "K", "version": "../../../../outside"}),
                 ({"instrument": "../../outside", "task_key": "k", "model_id": "TH_LOGREG"}, {"kind": "TRAINHUB", "model_key": "K", "version": "v"}),
                 ({"instrument": "XAUUSD", "task_key": "k", "model_id": "KALMAN_LS"}, {"kind": "FAMILY", "run_id": "../../../outside"})]
        for task, res in cases:
            with self.subTest(task=task, res=res):
                for d in (self.td / "pkg", self.bot / "outside", self.td / "outside"):
                    shutil.rmtree(d, ignore_errors=True)                 # an earlier case must not mask this one ('already exists')
                pkg = self._pkg(task, res)
                for d in (pkg / "outside" / "v", pkg / "artifact" / "outside", pkg / "outside", pkg / "artifact" / "train" / "outside",
                          pkg / "artifact" / "train" / "trainhub" / "K" / "v", pkg / "artifact" / "train" / "families" / "KALMAN_LS" / "XAUUSD"):
                    d.mkdir(parents=True, exist_ok=True)
                    (d / "payload.txt").write_text("x")
                before = {p for p in self.bot.rglob("*")}
                try:
                    r = IM.import_package(pkg)
                except (KeyError, ValueError, OSError):
                    r = {"ok": False}
                self.assertFalse(r.get("ok"), r)
                written = {p for p in self.bot.rglob("*")} - before
                self.assertFalse([p for p in written if "outside" in p.parts], written)
                self.assertFalse((self.td / "outside").exists())

    def test_rollback_of_a_forged_record_removes_nothing(self):
        from masterquo.studio import importer as IM
        from masterquo.trainhub import registry as R
        os.environ["MASTERQUO_DATA_DIR"] = str(self.bot)
        R._save_reg("XAUUSD", {"versions": {"K": []}})
        victim = self.bot / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("user data")
        (self.bot / "studio_imports.json").write_text(json.dumps([{"import_id": "IMP-1", "kind": "TRAINHUB", "instrument": "XAUUSD",
                                                                  "model_key": "K", "version": "../../../../victim", "state": "CANDIDATE"}]))
        try:
            r = IM.rollback("IMP-1")
        except (KeyError, ValueError):
            r = {"ok": False}
        self.assertFalse(r["ok"])
        self.assertTrue((victim / "keep.txt").exists())


# ------------------------------------------------------------------ chunk_35#2
class TestLockStaleTakeoverRace(unittest.TestCase):
    def test_second_takeover_does_not_steal_a_fresh_lock(self):
        from masterquo.studio.lock import Lock
        d = Path(tempfile.mkdtemp(prefix="lock146_"))
        try:
            p = d / "x.lock"
            p.write_text(json.dumps({"pid": os.getpid(), "app": "old", "job": "OLD", "heartbeat": 0, "acquired_at": 0}))   # stale heartbeat
            a, b = Lock(p, app="A"), Lock(p, app="B")
            real = a.stale

            def stale_then_b_takes_over(o):
                res = real(o)
                b.acquire("JB")                            # B judged the same record stale and created a FRESH lock meanwhile
                return res
            a.stale = stale_then_b_takes_over
            ok_a, owner = a.acquire("JA")
            self.assertTrue(b.held)
            self.assertFalse(ok_a and a.held, "both processes hold the lock")
            self.assertEqual(json.loads(p.read_text())["job"], "JB")
            self.assertEqual((owner or {}).get("job"), "JB")
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------ chunk_35#3
class TestVerifyLoaderFailureNotCommitted(StudioEnv):
    def test_failed_loader_stage_is_redone_on_resume(self):
        import subprocess

        from masterquo.studio import pipeline as P
        pkg = self.package()
        ctx = P.Ctx(pkg.task, pkg, source={"mode": "SYNTHETIC"})
        cp = subprocess.CompletedProcess([], 0, stdout='{"ok": false, "error": "rozjazd"}\n', stderr="")
        with mock.patch("subprocess.run", return_value=cp), self.assertRaises(P.Blocked) as cm:
            P.stage_verify_loader(ctx)
        self.assertEqual(cm.exception.state, "FAILED")
        self.assertFalse(pkg.stage_done("verify_loader"))                 # resume must run the loader test again
        self.assertFalse(json.loads((pkg.dir / "evaluation" / "verify_loader" / "loader.json").read_text())["ok"])   # report kept


# ------------------------------------------------------------------ chunk_35#6 / chunk_35#7 (runner groups)
class _FakeRun:
    def __init__(self, plan, tasks):
        self.plan, self.run_id, self.state = plan, "RUN-1", {"tasks": tasks, "plan": plan}


class TestRunnerGroupResult(StudioEnv):
    def _ctx(self, inst="BTC", sym="BTCUSD-", broker=None, mode="SYNTHETIC"):
        from masterquo.studio import pipeline as P
        from masterquo.studio.package import RAW
        task = {"model_id": "RUNNER:forecast", "task_id": "forecast", "instrument": inst, "base_tf": "M5", "task_key": "K", "adapter": "RUNNER_GROUP",
                "broker_symbol": broker, "sources": [{"kind": "BARS_RUNNER_EXPORT", "tf": "M5"}]}
        pkg = self.package(task)
        d = pkg.dir / RAW / "runner_dataset"
        d.mkdir(parents=True, exist_ok=True)
        (d / "source_metadata.json").write_text(json.dumps({"instrument": inst, "symbol": sym, "data_kind": "SYNTHETIC"}))
        return P.Ctx(task, pkg, source={"mode": mode})

    def _run(self, ctx, rc, main_exec, *, extra=None):
        from masterquo.studio import pipeline as P
        seen = {}
        inst = ctx.task["instrument"]

        def build_plan(**kw):
            seen.update(kw)
            ts = [{"id": f"{inst}:{k}", "kind": k, "execution": "NIE_URUCHOMIONE"} for k in ("export", "quality", "forecast", "activate", "bot")]
            return {"requested_tasks": ["forecast"]}, ts

        def execute(run):
            for t in run.state["tasks"]:
                if t["kind"] in ("export", "quality"):
                    t["execution"] = "UKONCZONE"
                if t["kind"] == "forecast":
                    t["execution"], t["detail"] = main_exec, "x"
                if extra and t["kind"] in extra:
                    t["execution"] = extra[t["kind"]]
            return rc
        with mock.patch("masterquo.training.runner.build_plan", side_effect=build_plan), \
                mock.patch("masterquo.training.core.Run.create", side_effect=lambda plan, tasks: _FakeRun(plan, tasks)), \
                mock.patch("masterquo.training.runner.execute", side_effect=execute):
            try:
                return P._train_runner(ctx), seen
            except P.Blocked as b:
                return b, seen

    def test_runner_exit_code_and_task_state_decide_the_stage(self):
        from masterquo.studio import pipeline as P
        for rc, main, extra, want in ((2, "NIE_URUCHOMIONE", None, "BLOCKED_DEPENDENCY"), (3, "ANULOWANE", None, "CANCELLED"),
                                      (1, "UKONCZONE", {"quality": "BLAD_TECHNICZNY"}, "FAILED"), (1, "BLAD_TECHNICZNY", None, "FAILED"),
                                      (4, "POMINIETE", None, "BLOCKED_DEPENDENCY")):
            with self.subTest(rc=rc, main=main):
                res, _ = self._run(self._ctx(), rc, main, extra=extra)
                self.assertIsInstance(res, P.Blocked, res)
                self.assertEqual(res.state, want)
        res, _ = self._run(self._ctx(), 4, "UKONCZONE")              # rc 4 from the activate task Studio skips on purpose = success
        self.assertEqual(res["kind"], "RUNNER_GROUP")

    def test_train_symbol_comes_from_the_export_metadata(self):
        _res, seen = self._run(self._ctx(inst="BTC", sym="BTCUSD-"), 0, "UKONCZONE")
        self.assertEqual(seen["symbols"], {"BTC": "BTCUSD-"})        # 1.45.0: 'XAUUSD-' for BTC

    def test_real_export_without_broker_symbol_is_blocked_not_guessed(self):
        from masterquo.studio import pipeline as P
        ctx = self._ctx(inst="BTC", broker=None, mode="MT5_DIRECT")
        with mock.patch("subprocess.run") as run, self.assertRaises(P.Blocked) as cm:
            P._export_runner(ctx)
        self.assertEqual(cm.exception.state, "BLOCKED_DATA")
        run.assert_not_called()


# ------------------------------------------------------------------ chunk_35#9
class TestFamilyPointFromSymbolSpec(StudioEnv):
    def test_point_from_package_manifest_and_missing_is_none(self):
        from masterquo.studio import pipeline as P
        pkg = self.package()
        ctx = P.Ctx(pkg.task, pkg, source={"mode": "SYNTHETIC"})
        self.assertIsNone(P.load_family_data(ctx)["point"])                          # unknown spec: never 0.01
        P.raw_store(pkg).write_manifest("XAUUSD", {"symbol_spec": {"point": 0.001}, "costs": {"spread": {"point": 0.001}}})
        self.assertEqual(P.load_family_data(ctx)["point"], 0.001)


# ------------------------------------------------------------------ chunk_35#10
class TestMultiSeriesTaskRefused(StudioEnv):
    def test_pair_basket_dxy_tasks_refused_before_export(self):
        from masterquo.studio import pipeline as P
        calls = []
        for kind in ("BARS_MULTI", "BARS_DXY"):
            task = {"model_id": "PAIR_COINT", "task_id": "T", "instrument": "XAUUSD", "base_tf": "H1", "task_key": "K", "adapter": "FAMILY",
                    "sources": [{"kind": "BARS", "tf": "H1"}, {"kind": kind, "tf": "H1"}]}
            pkg = self.package(task, run_id=f"R-{kind}")
            stages = {k: (lambda ctx, k=k: calls.append(k)) for k in P.STAGES}
            with mock.patch.dict(P.STAGES, stages), self.assertRaises(P.Blocked) as cm:
                P.run_task(task, pkg, "FULL_PROCESS", P.Ctx(task, pkg, source={"mode": "SYNTHETIC"}))
            self.assertEqual(cm.exception.state, "BLOCKED_DEPENDENCY")
        self.assertEqual(calls, [])


# ------------------------------------------------------------------ chunk_35#11
class TestSemivarFeaturesMatchBot(unittest.TestCase):
    def test_features_equal_bot_indicator(self):
        import random

        from masterquo.indicators import semivar as SV
        from masterquo.studio import pipeline as P
        rnd = random.Random(7)
        t0, c, bars = 1_790_000_040, 2400.0, []
        for i in range(160):
            if i in (40, 41, 42, 43, 44, 100):
                continue                                                  # gaps (session break / missing bars)
            c *= 1 + rnd.gauss(0, 0.0005)
            bars.append({"t": t0 + 60 * i, "o": c, "h": c, "l": c, "c": c})
        out = P.deterministic_features({"model_id": "IND_SEMIVAR", "instrument": "XAUUSD", "base_tf": "M1"}, bars, None)
        bot = [{"open_utc": b["t"], "c": b["c"], "closed": True} for b in bars]
        for i, row in enumerate(out):
            v = SV.compute(bot, "M1", as_of=bars[i]["t"] + 60, instrument="XAUUSD")["values"] or {}
            for n in (20, 60):
                want = v.get(f"downside_share_{n}")
                got = row[f"downside_share_{n}"]
                if want is None:
                    self.assertEqual(got, "", (i, n))
                else:
                    self.assertAlmostEqual(got, want, places=12, msg=(i, n))


# ------------------------------------------------------------------ chunk_35#4 / #5 / #26 / focus_X3#4 / #12 (queue)
class TestQueue(StudioEnv):
    def test_dedup_ignores_the_frozen_cutoff(self):
        q = self.queue()
        a = q.submit("K1", "FIT", source={"mode": "SYNTHETIC", "days": 10, "cutoff": 1_790_000_000})
        b = q.submit("K1", "FIT", source={"mode": "SYNTHETIC", "days": 10, "cutoff": 1_790_000_007})
        self.assertTrue(b.get("deduplicated"), b)
        self.assertEqual(a["job_id"], b["job_id"])
        c = q.submit("K1", "FIT", source={"mode": "SYNTHETIC", "days": 20, "cutoff": 1_790_000_007})
        self.assertFalse(c.get("deduplicated"))                         # a different source is a different job

    def test_jobs_list_keeps_running_and_newest(self):
        q = self.queue()
        ids = [q.submit(f"T{i}", "FIT", source={"i": i})["job_id"] for i in range(206)]
        now = time.time()
        for i, jid in enumerate(ids[:205]):
            q.db.execute("UPDATE jobs SET state='PACKAGED', created_at=?, finished_at=? WHERE job_id=?", (now - 1000 + i, now - 1000 + i + 1, jid))
        q.db.execute("UPDATE jobs SET state='TRAINING', created_at=?, started_at=? WHERE job_id=?", (now - 2000, now, ids[205]))
        got = [j["job_id"] for j in q.jobs(200)]
        self.assertIn(ids[205], got)                                     # the running job
        self.assertIn(ids[204], got)                                     # the newest finished job
        self.assertEqual(got[0], ids[205])

    def test_move_before_never_ties(self):
        q = self.queue()
        a, b, c = (q.submit(k, "FIT", source={"k": k})["job_id"] for k in "ABC")
        self.assertTrue(q.move(c, b))
        self.assertTrue(q.move(b, c))
        self.assertTrue(q.move(c, b))
        order = [j["job_id"] for j in q.jobs() if j["state"] == "QUEUED"]
        self.assertEqual(order, [a, c, b])

    def test_reads_share_the_connection_lock(self):
        q = self.queue()
        jid = q.submit("K", "FIT", source={})["job_id"]
        for fn in (lambda: q.job(jid), lambda: q.jobs(), lambda: q.next_job()):
            held = threading.Event()

            def hold(held=held):
                with q._mu:
                    held.set()
                    time.sleep(0.6)
            th = threading.Thread(target=hold)
            th.start()
            held.wait(5)
            t0 = time.monotonic()
            fn()
            self.assertGreaterEqual(time.monotonic() - t0, 0.3, "read ran on the shared connection without the queue lock")
            th.join()

    @unittest.skipIf(os.name == "nt", "POSIX process groups")
    def test_cancel_ends_the_whole_job_tree(self):
        q = self.queue()
        pidf = self.td / "child.pid"
        script = self.td / "fakejob.sh"
        script.write_text(f'#!/bin/sh\nsleep 300 &\necho $! > "{pidf}"\nwait\n')
        script.chmod(0o755)
        q.python = str(script)                                           # stands in for `python -m masterquo.studio.jobrun`
        jid = q.submit("K", "FIT", source={})["job_id"]
        self.assertEqual(q.step(), "STARTED")
        self.assertTrue(_env.wait_for(lambda: pidf.exists() and pidf.read_text().strip(), 10))
        child = int(pidf.read_text().strip())
        try:
            self.assertTrue(q.cancel(jid))
            q.kill_current_if_cancelled()
            self.assertTrue(_env.wait_for(lambda: _dead(child), 10), "stage subprocess survived the cancel (orphan)")
            self.assertEqual(q.job(jid)["state"], "CANCELLED")
        finally:
            if not _dead(child):
                os.kill(child, signal.SIGKILL)
            if q.proc is not None:
                q.proc.kill()
                q.proc.wait(5)


def _dead(pid: int) -> bool:
    try:
        st = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return True
    return st.rsplit(")", 1)[1].split()[0] in ("Z", "X")


# ------------------------------------------------------------------ chunk_35#19 / chunk_35#29 / chunk_35#21 / chunk_35#31 (app)
class TestStudioApi(StudioEnv):
    def _key(self):
        from masterquo.studio import registry as R
        return next(t["task_key"] for t in R.tasks() if t["model_id"] == "KALMAN_LS" and t["instrument"] == "XAUUSD")

    def test_settings_validated(self):
        app = self.app()
        for bad in ({"bot_port": "abc"}, {"bot_port": None}, {"port": 70000}, {"profile": "turbo"}, {"continue_after_failure": "yes"},
                    {"bot_data_dir": str(self.td / "missing")}):
            with self.subTest(bad=bad):
                self.assertEqual(_call(app, "POST", "/api/studio/settings", bad)[0], 400)
        st, body = _call(app, "POST", "/api/studio/settings", {"bot_port": 8766, "bot_data_dir": str(self.bot)})
        self.assertEqual((st, body["bot_port"]), (200, 8766))
        (self.studio / "settings.json").write_text(json.dumps({"bot_port": "abc", "profile": None}))   # written by 1.45.0
        from masterquo.studio import settings as S
        self.assertEqual((S.load()["bot_port"], S.load()["profile"]), (8765, "smoke"))

    def test_bad_days_profile_and_range_answer_400(self):
        app = self.app()
        k = self._key()
        for body in ({"task_key": k, "op": "FIT", "source": "SYNTHETIC", "days": "abc"},
                     {"task_key": k, "op": "FIT", "source": "SYNTHETIC", "profile": "bogus"},
                     {"task_key": k, "op": "FIT", "source": "SYNTHETIC", "start": "garbage"}):
            with self.subTest(body=body):
                self.assertEqual(_call(app, "POST", "/api/studio/jobs", body)[0], 400)
        st, body = _call(app, "POST", "/api/studio/jobs", {"task_key": k, "op": "FIT", "source": "SYNTHETIC", "start": "2026-01-02T00:00:00Z",
                                                           "end": 1_767_400_000})
        self.assertEqual(st, 200)
        src = app.state.queue.job(body["items"][0]["job_id"])["source"]
        self.assertEqual((src["start"], src["end"]), (1_767_312_000, 1_767_400_000))

    def test_display_name_is_apollo23_ids_unchanged(self):
        app = self.app()
        self.assertEqual(app.title, "Apollo23 Data & Training Studio")
        st, body = _call(app, "GET", "/api/studio/health")
        self.assertEqual((st, body["app"]), (200, "PepeTrainingStudio"))

    def _packaged(self, app):
        q = app.state.queue
        jid = q.submit("K", "FULL_PROCESS", source={})["job_id"]
        pk = self.td / "pkgdir"
        pk.mkdir(exist_ok=True)
        q.db.execute("UPDATE jobs SET state='PACKAGED', package=? WHERE job_id=?", (str(pk), jid))
        return q, jid, pk

    def test_transfer_bot_errors_and_timed_out_import(self):
        app = self.app()
        q, jid, pk = self._packaged(app)

        class NoSession:
            def __init__(self, port):
                pass

            def login(self):
                raise RuntimeError("SESSION_FAILED 403")

        class TimesOut(NoSession):
            def login(self):
                pass

            def _req(self, *a, **k):
                raise TimeoutError("timed out")

        class AlreadyImported(TimesOut):
            def _req(self, method, path, body=None, timeout=30):
                if method == "POST":
                    return 409, {"detail": "wersja v już istnieje w rejestrze – nic nie nadpisano"}
                return 200, {"items": [{"import_id": "IMP-9", "package": str(pk.resolve()), "state": "CANDIDATE"}]}
        with mock.patch("masterquo.studio.app._bot_health", return_value={"ok": True}):
            for cls in (NoSession, TimesOut):
                with mock.patch("masterquo.localapi.Bot", cls):
                    self.assertEqual(_call(app, "POST", f"/api/studio/jobs/{jid}/transfer", {})[0], 503, cls.__name__)
            self.assertEqual(q.job(jid)["state"], "PACKAGED")
            with mock.patch("masterquo.localapi.Bot", AlreadyImported):
                st, body = _call(app, "POST", f"/api/studio/jobs/{jid}/transfer", {})
        self.assertEqual(st, 200)
        self.assertEqual(body["import"]["import_id"], "IMP-9")
        self.assertEqual(q.job(jid)["state"], "TRANSFERRED")


# ------------------------------------------------------------------ chunk_35#27 / chunk_35#28 / chunk_35#29 (pipeline)
class TestPipelineSmall(StudioEnv):
    def test_runner_build_dataset_is_final(self):
        from masterquo.studio import pipeline as P
        task = {"model_id": "RUNNER:forecast", "task_id": "forecast", "instrument": "XAUUSD", "base_tf": "M5", "horizon": None, "task_key": "K",
                "adapter": "RUNNER_GROUP", "sources": []}
        pkg = self.package(task)
        with mock.patch.dict(P.STAGES, {k: (lambda ctx: None) for k in P.STAGES}):
            res = P.run_task(task, pkg, "BUILD_DATASET", P.Ctx(task, pkg, source={"mode": "SYNTHETIC"}))
        self.assertEqual(res["status"], "READY_FOR_TRAINING")
        self.assertFalse(res["package"].endswith(".partial"))

    def test_missing_holdout_skill_is_unavailable(self):
        from masterquo.studio import pipeline as P
        from masterquo.studio.package import ARTIFACT
        pkg = self.package()
        (pkg.dir / ARTIFACT).mkdir(parents=True)
        (pkg.dir / ARTIFACT / "train_result.json").write_text(json.dumps({"kind": "TRAINHUB", "holdout": {}}))
        self.assertEqual(P.stage_evaluate(P.Ctx(pkg.task, pkg, source={}))["decision"], "UNAVAILABLE")

    def test_bot_cache_export_applies_start_and_end(self):
        from masterquo.marketdata.store import Store
        from masterquo.studio import pipeline as P
        src = Store(self.td / "src")
        t0 = 1_767_225_600                                                 # 2026-01-01T00:00:00Z
        src.merge("XAUUSD", "M5", [(t0 + 300 * i, 1.0, 1.0, 1.0, 1.0, 1, 1, 0, t0 + 300 * i, 0) for i in range(100)])
        src.write_manifest("XAUUSD", {"instrument": "XAUUSD", "data_kind": "REAL_USER_DATA"})
        task = {"model_id": "KALMAN_LS", "task_id": "T", "instrument": "XAUUSD", "base_tf": "M5", "task_key": "K", "adapter": "FAMILY",
                "sources": [{"kind": "BARS", "tf": "M5"}]}
        for i, (start, end) in enumerate(((t0 + 3000, t0 + 6000), ("2026-01-01T00:50:00Z", "2026-01-01T01:40:00Z"))):
            with self.subTest(start=start):
                pkg = self.package(task, run_id=f"R{i}")
                ctx = P.Ctx(task, pkg, source={"mode": "BOT_CACHE", "store_root": str(self.td / "src"), "cutoff": t0 + 10 ** 6,
                                               "start": start, "end": end})
                rep = P.stage_export(ctx)["timeframes"]["M5"]
                self.assertEqual((rep["from"], rep["to"]), (t0 + 3000, t0 + 6000 - 300))   # bars closed by `end`
                self.assertEqual(rep["rows"], 10)


# ------------------------------------------------------------------ chunk_36#11 / chunk_36#13 (trainhub CLI)
class TestTrainhubCli(unittest.TestCase):
    def setUp(self):
        from _env import TempData
        self.td = TempData()

    def tearDown(self):
        self.td.close()

    def _main(self, argv):
        from masterquo.trainhub import cli
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue()

    def test_demo_never_touches_the_real_registry(self):
        from masterquo.trainhub import registry as R
        real = Path(self.td.dir).resolve() / "trainhub"
        with mock.patch.object(R, "summary", side_effect=lambda inst: {"root": str(R.root())}):
            rc, out = self._main(["list", "--instrument", "XAUUSD", "--demo"])
        self.assertEqual(rc, 0)
        root = Path(json.loads(out)["root"])
        self.assertNotEqual(root, real)                                   # datasets / packages of synthetic data stay in the sandbox
        self.assertFalse(str(root).startswith(str(real) + os.sep))
        self.assertEqual(os.environ["MASTERQUO_DATA_DIR"], self.td.dir)   # process env restored
        with mock.patch.object(R, "summary", side_effect=lambda inst: {"root": str(R.root())}):
            rc, out = self._main(["list", "--instrument", "XAUUSD"])
        self.assertEqual(Path(json.loads(out)["root"]), real)            # without --demo: the real registry

    def test_exit_codes(self):
        from masterquo.trainhub import registry as R
        with mock.patch.object(R, "rollback", return_value={"ok": False, "status": "INCOMPATIBLE", "reason": "x"}):
            self.assertEqual(self._main(["rollback", "--instrument", "XAUUSD", "--model-key", "K"])[0], 3)
        for cmd in (["evaluate", "--instrument", "XAUUSD"], ["package-zip", "--instrument", "BTC", "--model-key", "K"]):
            with self.subTest(cmd=cmd):
                try:
                    rc = self._main(cmd)[0]
                except TypeError:
                    rc = "traceback"
                self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
