"""1.46 audit, group G2 (quant/tabicl.py - TabICLv2 confidence estimator): regression tests for
#0 governor released the worker mid load / fit / predict (stale last_used, no busy guard) + EOF reported as TIMEOUT,
#1 results dict grew without limit (trimmed only after READY), #2 stop() spawned a process just to quit it and waited behind an
in-flight request, #3 an idle-tick error (_maybe_reconstruct) killed the quant-tabicl thread, #4 auto-reconstruction gated by the sum
of ALL events' rows + a full ledger read every 5 s, #5 point size always 0.01, #6 data_kind ignored (reconstruction always REAL,
SYNTHETIC rows in a REAL candidate's context), #7 reconstruction row id without TF, #8 context built at the wall clock instead of
the candidate's decision time (look-ahead), #9 sys.path grew on every installed() cache miss, #10 a cancelled reconstruction
overwrote the complete context file."""
from __future__ import annotations

import json
import queue
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import _env
from _env import TempData

INST = "XAUUSD"

# stub of tabicl_runtime.worker: JSON lines; 'load' takes 1.5 s; 'crash' exits without an answer
STUB = r"""
import json, sys, time
for ln in sys.stdin:
    req = json.loads(ln)
    cmd = req.get("cmd")
    if cmd == "crash":
        sys.exit(3)
    if cmd == "load":
        time.sleep(1.5)
    sys.stdout.write(json.dumps({"ok": True, "id": req.get("id"), "cmd": cmd, "info": {"fingerprint": "stub"}}) + "\n")
    sys.stdout.flush()
    if cmd == "quit":
        break
"""


_PROCS: list = []


def _stub_spawn(w):
    w.proc = subprocess.Popen([sys.executable, "-c", STUB], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              text=True, encoding="utf-8", bufsize=1)
    _PROCS.append(w.proc)
    w.loaded_ctx, w.info = None, None


class FakeSettings:
    def __init__(self, d):
        self.d = d

    def get(self):
        return self.d


class FakeLedger:
    def __init__(self, rows=None, exc=None):
        self.rows, self.exc, self.calls = list(rows or []), exc, 0

    def training_rows(self, inst, task_hash=None):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return list(self.rows)


class FakePub:
    def __init__(self, kind):
        self.kind = kind

    def current(self):
        return {"snapshot": {"data_kind": self.kind}} if self.kind else None


class FakeQ:
    def __init__(self, ledger=None, kind="REAL", tabicl=None):
        self.settings = FakeSettings({"estimator": "tabicl_v2", "tabicl": {"enabled": True, **(tabicl or {})}})
        self.ledger = ledger or FakeLedger()
        self.pub = FakePub(kind)

    def instrument(self):
        return INST


def sh_cd(ts, entry=2000.0, engine="SH_SCALPING", strategy="PMW_SC01", ntp=2):
    tg = [{"price": entry + 5.0 * (i + 1), "weight": 1.0 / ntp} for i in range(ntp)]
    return {"instrument": INST, "engine": engine, "strategy_id": strategy, "direction": "LONG", "entry_price": entry, "stop_loss": entry - 5.0,
            "targets": tg, "horizon_s": 3600.0, "decision_ts": float(ts), "entry_type": "MARKET"}


def ledger_row(i, spec, decision_ts, resolve_ts, y, kind="REAL"):
    return {"row_id": f"r{i}", "decision_ts": float(decision_ts), "resolve_ts": float(resolve_ts), "y": int(y), "net_r": None,
            "features": {"a": float(i % 7), "b": float((i * 3) % 5)}, "data_kind": kind, "task_hash": spec.task_hash(), "spec": spec.to_dict()}


class FakeWorkerCalls:
    """Replaces Worker.call: records the requests (the fit request carries the reference context the model sees)."""

    def __init__(self):
        self.reqs = []

    def __call__(self, req, timeout, **kw):
        self.reqs.append(req)
        if req["cmd"] == "load":
            return {"ok": True, "info": {"fingerprint": "fake"}}
        if req["cmd"] == "predict":
            return {"ok": True, "p_event_raw": [0.5]}
        return {"ok": True}

    def fit(self):
        return next(r for r in self.reqs if r["cmd"] == "fit")


class Base(unittest.TestCase):
    def setUp(self):
        self.td = TempData()

    def tearDown(self):
        while _PROCS:                                             # reap the stub processes (no zombies / unclosed pipes)
            p = _PROCS.pop()
            if p.poll() is None:
                p.kill()
            p.wait(10)
            for f in (p.stdin, p.stdout):
                try:
                    f.close()
                except OSError:
                    pass
        self.td.close()

    def svc(self, **kw):
        from masterquo.quant.tabicl import TabICLService
        return TabICLService(FakeQ(**kw))


# ---------------------------------------------------------------------------------------------------------------- #0 governor race
class TestWorkerGovernorRace(Base):
    def _governor_lambdas(self, tb):
        """Verbatim copy of runtime.py _wire_governor for the tabicl source (runtime.py is not changed by the fix)."""
        import time as _time
        pid = lambda: tb.worker.proc.pid if (tb.worker.proc and tb.worker.proc.poll() is None) else None
        release = lambda: tb.jobs.empty() and tb.worker.kill()
        idle = lambda: _time.monotonic() - tb.worker.last_used
        return pid, release, idle

    def test_release_never_kills_an_in_flight_load(self):
        tb = self.svc()
        w = tb.worker
        w._spawn = lambda: _stub_spawn(w)
        w.last_used = time.monotonic() - 1000.0                 # the worker was idle long BEFORE this request (LOW_MEMORY_8GB limit = 90 s)
        pid, release, idle = self._governor_lambdas(tb)
        res = {}

        def run():
            try:
                res["r"] = w.call({"cmd": "load"}, 30)
            except Exception as exc:  # noqa: BLE001
                res["e"] = exc
        th = threading.Thread(target=run)
        th.start()
        try:
            self.assertTrue(_env.wait_for(lambda: pid() is not None, 10))
            time.sleep(0.3)                                       # the load is in flight now
            self.assertLess(idle(), 5.0, "a request in flight is not idle time")
            self.assertFalse(release(), "the governor must not kill a process that is loading")
            self.assertIsNotNone(pid(), "process killed mid-load")
        finally:
            th.join(20)
        self.assertNotIn("e", res, res.get("e"))
        self.assertTrue(res["r"]["ok"])
        self.assertEqual((w.restarts, w.retry_at), (0, 0.0))
        self.assertTrue(release())                                # idle again: the governor may release it
        self.assertIsNone(pid())

    def test_governor_maintain_and_make_room_skip_busy_tabicl(self):
        from test_resources_governor import gov
        tb = self.svc()
        w = tb.worker
        w._spawn = lambda: _stub_spawn(w)
        w.last_used = time.monotonic() - 1000.0
        g, st = gov(used=70.0, profile="LOW_MEMORY_8GB")
        pid, release, idle = self._governor_lambdas(tb)
        g.register("tabicl", "heavy", pid, release=release, idle=idle)
        res = {}

        def run():
            try:
                res["r"] = w.call({"cmd": "load"}, 30)
            except Exception as exc:  # noqa: BLE001
                res["e"] = exc
        th = threading.Thread(target=run)
        th.start()
        try:
            self.assertTrue(_env.wait_for(lambda: pid() is not None, 10))
            time.sleep(0.2)
            st["rss"] = {pid(): 700.0}
            g.maintain()                                          # idle limit 90 s: a loading process is not idle
            g.admit("tirex2", loaded=False)                       # _make_room: max 1 heavy resident -> tries to release tabicl
            self.assertIsNotNone(pid(), "TabICL killed by the governor mid-load")
        finally:
            th.join(20)
        self.assertNotIn("e", res, res.get("e"))
        self.assertEqual(w.restarts, 0)
        w.kill(force=True)

    def test_process_exit_is_worker_exited_not_timeout(self):
        tb = self.svc()
        w = tb.worker
        w._spawn = lambda: _stub_spawn(w)
        t0 = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "^WORKER_EXITED"):
            w.call({"cmd": "crash"}, 30)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(w.restarts, 1)                           # crash-loop backoff kept
        self.assertIn("WORKER_EXITED", w.reason or "")
        with self.assertRaisesRegex(RuntimeError, "WORKER_BACKOFF: WORKER_EXITED"):
            w.call({"cmd": "ping"}, 5)


# ---------------------------------------------------------------------------------------------------------------- #1 bounded results
class TestResultsBounded(Base):
    def test_not_installed_results_are_trimmed(self):
        from masterquo.quant import tabicl as QT
        tb = self.svc()
        with mock.patch.object(QT, "find_python", lambda: None):
            for i in range(1200):
                tb._score({"plan_hash": f"p{i}", "instrument": INST, "event_key": "k", "features": {}, "ident": {"plan_hash": f"p{i}"},
                           "enqueued_at": time.time()})
        self.assertLessEqual(len(tb.results), 500)
        self.assertIn("p1199", tb.results)                       # the newest are kept
        self.assertNotIn("p0", tb.results)

    def test_queued_and_dropped_results_are_trimmed(self):
        from masterquo.quant import events as EV
        tb = self.svc()
        for i in range(1200):
            cd = sh_cd(time.time(), entry=2000.0 + 0.01 * i)
            tb.submit(cd, EV.spec_from_candidate(cd), {}, 1)
        self.assertLessEqual(len(tb.results), 500)
        self.assertLessEqual(len(tb.status()["last_results"]), 10)


# ---------------------------------------------------------------------------------------------------------------- #2 stop()
class TestStop(Base):
    def test_stop_without_process_spawns_nothing(self):
        tb = self.svc()
        spawned = []
        tb.worker._spawn = lambda: spawned.append(1)
        tb.stop()
        self.assertEqual(spawned, [])

    def test_stop_does_not_wait_behind_an_in_flight_request(self):
        tb = self.svc()
        w = tb.worker
        w._spawn = lambda: _stub_spawn(w)
        w._spawn()
        p = w.proc
        hold = threading.Event()
        rel = threading.Event()

        def busy():                                              # an in-flight load / fit holds the worker lock
            with w.lock:
                hold.set()
                rel.wait(8)
        th = threading.Thread(target=busy)
        th.start()
        try:
            self.assertTrue(hold.wait(5))
            t0 = time.monotonic()
            tb.stop()
            took = time.monotonic() - t0
        finally:
            rel.set()
            th.join(10)
        self.assertLess(took, 4.0, f"stop() blocked {took:.1f} s behind the in-flight request")
        self.assertIsNone(w.proc)
        self.assertIsNotNone(p.wait(5))                          # the process is gone

    def test_stop_quits_a_running_idle_process(self):
        tb = self.svc()
        w = tb.worker
        w._spawn = lambda: _stub_spawn(w)
        w._spawn()
        p = w.proc
        tb.stop()
        self.assertEqual(p.wait(5), 0)                            # graceful 'quit' answered, exit code 0 (not killed)
        self.assertEqual(w.restarts, 0)


# ---------------------------------------------------------------------------------------------------------------- #3 thread survives
class TestRunSurvivesIdleTickError(Base):
    def test_maybe_reconstruct_error_does_not_kill_the_loop(self):
        tb = self.svc(ledger=FakeLedger(exc=sqlite3.OperationalError("database is locked")))

        class Q(queue.Queue):
            n = 0

            def get(self, block=True, timeout=None):
                Q.n += 1
                if Q.n <= 2:
                    raise queue.Empty
                return super().get(block, timeout)
        tb.jobs = Q()
        tb.jobs.put(None)                                         # stop sentinel after two idle ticks
        try:
            with self.assertLogs("masterquo.quant.tabicl", "WARNING"):
                tb._run()
        except sqlite3.OperationalError:
            self.fail("an idle-tick error escaped _run() - the quant-tabicl thread would die")
        self.assertIn("OperationalError", tb.last_error or "")
        self.assertEqual(Q.n, 3)                                  # the loop went on after the error


# ---------------------------------------------------------------------------------------------------------------- #4 reconstruction gate
class TestReconstructionGate(Base):
    def _rows(self, n, cd_kw):
        from masterquo.quant import events as EV
        now = time.time()
        spec = EV.spec_from_candidate(sh_cd(now, **cd_kw))
        return [ledger_row(i, spec, now - 9000 + i, now - 8000 + i, i % 2) for i in range(n)]

    def test_short_event_is_reconstructed_although_other_events_have_many_rows(self):
        from masterquo.quant import events as EV
        from masterquo.quant import tabicl as QT
        led = FakeLedger(self._rows(600, {"engine": "ACTIVE_S01_S12", "strategy": "S01", "ntp": 1}))   # ACTIVE TP1, no BE
        tb = self.svc(ledger=led)
        calls = []
        tb.run_reconstruction = lambda inst, days=30, background=True: calls.append(inst) or {"ok": True}
        sh = EV.spec_from_candidate(sh_cd(time.time()))                                                   # SH TP2, BE after TP2
        ctx = tb.context(INST, QT.event_key(sh))
        self.assertEqual(ctx["n"], 0)                            # NO_CONTEXT for the SH event
        tb._maybe_reconstruct()
        self.assertEqual(calls, [INST], "the SH context must be reconstructed although ACTIVE has >= 512 rows")

    def test_full_ledger_is_not_read_on_every_idle_tick(self):
        led = FakeLedger(self._rows(600, {}))
        tb = self.svc(ledger=led)
        calls = []
        tb.run_reconstruction = lambda inst, days=30, background=True: calls.append(inst) or {"ok": True}
        for _ in range(10):
            tb._maybe_reconstruct()
        self.assertEqual(calls, [])                              # enough rows: nothing to reconstruct
        self.assertLessEqual(led.calls, 1, f"training_rows() full loads in 10 idle ticks: {led.calls}")


# ---------------------------------------------------------------------------------------------------------------- #5 / #6 store spec + kind
class TestStoreBarsSpecAndKind(Base):
    def _store(self, manifest: dict | None):
        from masterquo.marketdata.store import Store
        st = Store()
        t0 = (int(time.time()) // 60) * 60 - 4000 * 60
        rows = [(t0 + 60 * i, 2000.0, 2000.5, 1999.5, 2000.2, 10, 25, 0, t0 + 60 * i, 0) for i in range(3200)]
        st.merge(INST, "M1", rows)
        if manifest is not None:
            st.write_manifest(INST, manifest)

    def test_point_and_kind_come_from_the_store_manifest(self):
        from masterquo.quant import tabicl as QT
        self._store({"data_kind": "SYNTHETIC_TEST", "symbol_spec": {"point": 0.001, "trade_tick_size": 0.001, "digits": 3}})
        bars, meta = QT.store_bars(INST, 30)
        self.assertEqual(meta["spec"]["point"], 0.001)
        self.assertEqual(meta["spec"]["trade_tick_size"], 0.001)
        self.assertAlmostEqual(bars["M1"][0]["spread_price"], 25 * 0.001)   # 25 points x the broker's point, not x 0.01
        self.assertEqual(meta["data_kind"], "SYNTHETIC_TEST")               # never relabelled REAL

    def test_costs_point_fallback_and_unknown_kind(self):
        from masterquo.quant import tabicl as QT
        self._store({"costs": {"spread": {"point": 0.01}}})
        _bars, meta = QT.store_bars(INST, 30)
        self.assertEqual(meta["spec"]["point"], 0.01)
        self.assertEqual(meta["data_kind"], "UNKNOWN_SOURCE")              # missing kind = UNKNOWN, not REAL

    def test_no_spec_is_not_guessed(self):
        from masterquo.quant import tabicl as QT
        self._store(None)
        r = QT.store_bars(INST, 30)
        self.assertIsInstance(r, dict, f"store_bars returned {type(r).__name__} (an assumed point size)")
        self.assertEqual((r["ok"], r["code"]), (False, "NO_SPEC"))
        self.assertEqual(QT.reconstruct(INST, days=30)["code"], "NO_SPEC")
        self.assertFalse(QT.recon_path(INST).exists())


class TestContextDataKind(Base):
    def test_real_candidate_gets_only_real_rows(self):
        from masterquo.quant import events as EV
        from masterquo.quant import tabicl as QT
        now = time.time()
        D = now - 7200
        spec = EV.spec_from_candidate(sh_cd(D))
        rows = [ledger_row(i, spec, D - 9000 + i, D - 5000 + i, i % 2, kind="REAL") for i in range(30)]
        rows += [ledger_row(100 + i, spec, D - 9000 + i, D - 5000 + i, i % 2, kind="SYNTHETIC") for i in range(30)]
        tb = self.svc(ledger=FakeLedger(rows), kind="REAL")
        fake = FakeWorkerCalls()
        tb.worker.call = fake
        tb.submit(sh_cd(D), spec, {"a": 1.0}, 1)
        with mock.patch.object(QT, "find_python", lambda: "/stub/python"):
            tb._score(tb.jobs.get_nowait())
        r = tb.results[spec.plan_hash()]
        self.assertEqual(r["state"], "READY", r)
        self.assertEqual(len(fake.fit()["y"]), 30, "SYNTHETIC ledger rows entered a REAL candidate's context")
        self.assertEqual(r["context"]["data_kinds"], {"REAL": 30})

    def test_reconstructed_rows_filtered_by_kind(self):
        from masterquo.quant import tabicl as QT
        p = QT.recon_path(INST)
        rows = [{"id": f"R{i}", "event_key": "K", "decision_ts": 100.0 + i, "resolve_ts": 200.0 + i, "y": i % 2, "features": {},
                 "data_kind": "SYNTHETIC_TEST" if i % 3 == 0 else ("REAL_USER_DATA" if i % 3 == 1 else None)} for i in range(9)]
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.assertEqual(len(QT.recon_rows(INST, "K", 1e12)), 9)
        self.assertEqual([r["id"] for r in QT.recon_rows(INST, "K", 1e12, real_only=True)], ["R1", "R4", "R7"])


# ---------------------------------------------------------------------------------------------------------------- #8 look-ahead
class TestContextAsOfDecision(Base):
    def test_rows_resolved_after_the_decision_are_not_in_the_context(self):
        from masterquo.quant import events as EV
        from masterquo.quant import tabicl as QT
        now = time.time()
        D = now - 7200                                           # a candidate of 2 h ago (queue delay / POST /quant/assessment)
        spec = EV.spec_from_candidate(sh_cd(D))
        before = [ledger_row(i, spec, D - 9000 + i, D - 5000 + i, i % 2) for i in range(30)]
        after = [ledger_row(100 + i, spec, D - 3000 + i, D + 100 + i, i % 2) for i in range(30)]   # known only AFTER the decision
        tb = self.svc(ledger=FakeLedger(before + after))
        fake = FakeWorkerCalls()
        tb.worker.call = fake
        tb.submit(sh_cd(D), spec, {"a": 1.0}, 1)
        with mock.patch.object(QT, "find_python", lambda: "/stub/python"):
            tb._score(tb.jobs.get_nowait())
        r = tb.results[spec.plan_hash()]
        self.assertEqual(r["state"], "READY", r)
        self.assertEqual(len(fake.fit()["y"]), 30, "look-ahead: rows resolved after decision_ts entered the context")
        self.assertLessEqual(r["context"]["last_ts"], D)

    def test_cached_newer_context_is_not_reused_for_an_older_decision(self):
        from masterquo.quant import events as EV
        from masterquo.quant import tabicl as QT
        now = time.time()
        spec = EV.spec_from_candidate(sh_cd(now))
        key = QT.event_key(spec)
        rows = [ledger_row(i, spec, now - 9000 + 10 * i, now - 8000 + 100 * i, i % 2) for i in range(60)]   # resolved up to now - 2100
        tb = self.svc(ledger=FakeLedger(rows))
        self.assertEqual(tb.context(INST, key, as_of=now)["n"], 60)
        self.assertEqual(tb.context(INST, key, as_of=now - 5050)["n"], 30)         # not the cached as-of-now context
        self.assertEqual(tb.context(INST, key, as_of=now)["n"], 60)                # nor the older one for a newer decision


# ---------------------------------------------------------------------------------------------------------------- #7 / #10 reconstruction
def _bars_meta(t0, n=300):
    from datetime import UTC, datetime
    m1 = []
    for i in range(n):
        px = 2000.0 if i <= 120 else 2000.0 + 0.1 * (i - 120)
        m1.append({"open_utc": datetime.fromtimestamp(t0 + 60 * i, UTC).isoformat().replace("+00:00", "Z"), "o": px, "h": px + 0.05,
                   "l": px - 0.05, "c": px, "spread_price": 0.2})
    return {"M1": m1}, {"instrument": INST, "symbol": INST, "data_kind": "REAL_USER_DATA", "spec": {"point": 0.01}}


def _su(sl, tp1, tp2):
    return {"side": "BUY", "entry_ref": 2000.0, "sl": sl, "tps": [{"price": tp1, "share": 0.5}, {"price": tp2, "share": 0.5}],
            "position_max_minutes": 30}


class TestReconstruction(Base):
    def test_same_variant_on_two_tfs_keeps_both_rows(self):
        from masterquo.quant import tabicl as QT
        t0 = 1_793_990_000 - (1_793_990_000 % 3600)
        t = t0 + 120 * 60

        def fake_run(bars, meta, on_ready=None, **kw):
            on_ready(t, "PMW_HG01", "M5", _su(1995.0, 2001.0, 2002.0))     # TP2 reached -> y = 1
            on_ready(t, "PMW_HG01", "M15", _su(1990.0, 2050.0, 2100.0))    # never reached -> y = 0
            return {}
        with mock.patch("masterquo.sh.pack.replay.run", fake_run):
            r = QT.reconstruct(INST, bars_meta=_bars_meta(t0))
        self.assertTrue(r["ok"], r)
        rows = [json.loads(x) for x in QT.recon_path(INST).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({x["id"] for x in rows}), 2, [x["id"] for x in rows])
        self.assertEqual(sorted(x["tf"] for x in rows), ["M15", "M5"])
        self.assertEqual(sorted(x["y"] for x in QT.select(rows, 512, 1024)), [0, 1])   # neither plan silently dropped

    def test_cancelled_reconstruction_keeps_the_previous_file(self):
        from masterquo.quant import tabicl as QT
        t0 = 1_793_990_000 - (1_793_990_000 % 3600)
        p = QT.recon_path(INST)
        p.write_text('{"id": "OLD"}\n', encoding="utf-8")

        def fake_run(bars, meta, on_ready=None, cancel=None, **kw):
            on_ready(t0 + 120 * 60, "PMW_SC01", "M1", _su(1995.0, 2001.0, 2002.0))
            return {}                                             # interrupted by cancel() after the first bar
        with mock.patch("masterquo.sh.pack.replay.run", fake_run):
            r = QT.reconstruct(INST, bars_meta=_bars_meta(t0), cancel=lambda: True)
        self.assertEqual((r["ok"], r.get("code")), (False, "CANCELLED"))
        self.assertEqual(p.read_text(encoding="utf-8"), '{"id": "OLD"}\n')


# ---------------------------------------------------------------------------------------------------------------- #9 sys.path
class TestInstalledSysPath(Base):
    def test_sys_path_does_not_grow(self):
        from masterquo import paths
        from masterquo.quant import tabicl as QT
        p = str(paths.ROOT_DIR / "backend")
        QT._installed()
        before = sys.path.count(p)
        for _ in range(5):
            QT._installed()
        self.assertEqual(sys.path.count(p), before)
        self.assertGreaterEqual(before, 1)


if __name__ == "__main__":
    unittest.main()
