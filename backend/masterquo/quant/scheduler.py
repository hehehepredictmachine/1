"""Computation DAG with single ownership, deadlines and atomic publication (PMW-QUANT-SCHED-1).

* Tasks declare their dependencies; the order is topological and a cycle is refused at registration (CycleError).
* One OWNER per task name (re-registering a task under another owner is refused - no double execution paths).
* A task runs in a bounded worker pool with its own deadline; a task that misses it is TIMEOUT and its late answer is DISCARDED (the
  result is bound to the generation it was started for - a late worker never writes into a newer generation).
* A failed / timed-out task makes its dependents BLOCKED_DEPENDENCY (with the cause); independent branches still run. A SOFT dependency
  (`soft_deps`) that failed is passed as None instead - the task works with the branches that succeeded.
* Every task has its own worker thread: a call that missed its deadline and is still running is never queued again (BUSY_PREVIOUS)
  and cannot starve the other tasks.
* The finished generation is published atomically (one reference swap under a lock + an atomic file replace) with its id, completeness
  and per-task timings; readers always see one consistent generation.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
from pathlib import Path

VERSION = "PMW-QUANT-SCHED-1"


class CycleError(ValueError):
    pass


class OwnershipError(ValueError):
    pass


class Dag:
    def __init__(self, max_workers: int = 2):
        self.tasks: dict[str, dict] = {}
        # 1.46: one shared pool of 2 threads - a task past its deadline kept its thread (fut.cancel() does not stop a running call), two
        # hung tasks starved even the fast snapshot of the next cycles (TIMEOUT) and every generation was published empty. Now one worker
        # thread per task (created on first use) and a task whose previous call still runs is not queued again (BUSY_PREVIOUS).
        self.max_workers = max_workers                    # kept for callers; the per-task workers replace the shared pool
        self._pools: dict[str, ThreadPoolExecutor] = {}
        self._running: dict[str, object] = {}
        self._plock = threading.Lock()

    def _pool(self, name: str) -> ThreadPoolExecutor:
        with self._plock:
            pool = self._pools.get(name)
            if pool is None:
                pool = self._pools[name] = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"quant-task-{name}")
            return pool

    def add(self, name: str, fn, *, deps=(), owner: str, deadline_s: float = 10.0, optional: bool = False, soft_deps=()) -> None:
        if name in self.tasks and self.tasks[name]["owner"] != owner:
            raise OwnershipError(f"TASK_ALREADY_OWNED:{name}:{self.tasks[name]['owner']}")
        self.tasks[name] = {"fn": fn, "deps": tuple(deps), "soft_deps": tuple(soft_deps), "owner": owner, "deadline_s": float(deadline_s),
                            "optional": optional}
        try:
            self.order()
        except CycleError:
            del self.tasks[name]
            raise

    def order(self) -> list[str]:
        seen, temp, out = set(), set(), []

        def visit(n, path):
            if n in temp:
                raise CycleError("CYCLE:" + "->".join(path + [n]))
            if n in seen:
                return
            if n not in self.tasks:
                raise CycleError(f"UNKNOWN_DEPENDENCY:{n}")
            temp.add(n)
            for d in self.tasks[n]["deps"] + self.tasks[n].get("soft_deps", ()):
                visit(d, path + [n])
            temp.discard(n)
            seen.add(n)
            out.append(n)
        for n in self.tasks:
            visit(n, [])
        return out

    def run(self, ctx: dict, generation: int) -> dict:
        res: dict[str, dict] = {}
        t_all = time.perf_counter()
        for name in self.order():
            t = self.tasks[name]
            bad = [d for d in t["deps"] if res.get(d, {}).get("status") != "OK"]
            if bad:
                res[name] = {"status": "BLOCKED_DEPENDENCY", "reason": ",".join(bad), "ms": 0.0, "owner": t["owner"]}
                continue
            prev = self._running.get(name)
            if prev is not None and not prev.done():
                res[name] = {"status": "BUSY_PREVIOUS", "reason": "poprzednie wywołanie zadania jeszcze trwa (po przekroczeniu terminu)", "ms": 0.0,
                             "owner": t["owner"], "generation": generation}
                continue
            t0 = time.perf_counter()
            dv = {d: res[d]["value"] for d in t["deps"]}
            dv.update({d: (res[d]["value"] if res.get(d, {}).get("status") == "OK" else None) for d in t.get("soft_deps", ())})
            fut = self._pool(name).submit(t["fn"], ctx, dv)
            self._running[name] = fut
            try:
                val = fut.result(timeout=t["deadline_s"])
                res[name] = {"status": "OK", "value": val, "ms": round((time.perf_counter() - t0) * 1000, 3), "owner": t["owner"]}
            except FutTimeout:
                fut.cancel()                                  # if already running, its result is never read (bound to this generation)
                res[name] = {"status": "TIMEOUT", "reason": f"deadline {t['deadline_s']}s", "ms": round((time.perf_counter() - t0) * 1000, 3),
                             "owner": t["owner"], "generation": generation}
            except Exception as exc:  # noqa: BLE001 - a task failure is a state, never a crash of the cycle
                res[name] = {"status": "ERROR", "reason": f"{type(exc).__name__}: {exc}"[:240], "ms": round((time.perf_counter() - t0) * 1000, 3),
                             "owner": t["owner"]}
        required = [n for n, t in self.tasks.items() if not t["optional"]]
        complete = all(res[n]["status"] == "OK" for n in required)
        return {"generation": generation, "complete": complete, "tasks": res, "cycle_ms": round((time.perf_counter() - t_all) * 1000, 3)}

    def shutdown(self) -> None:
        with self._plock:
            pools, self._pools = list(self._pools.values()), {}
        for pool in pools:
            pool.shutdown(wait=False, cancel_futures=True)


class Publisher:
    """Atomic publication of one generation (memory + optional JSON file)."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self._lock = threading.Lock()
        self._cur: dict | None = None

    def publish(self, payload: dict) -> None:
        with self._lock:
            if self._cur is not None and payload.get("generation", 0) <= self._cur.get("generation", -1):
                return                                        # never replace a newer generation with an older one
            self._cur = payload
        if self.path is not None:
            write_json_atomic(self.path, payload)

    def current(self) -> dict | None:
        with self._lock:
            return self._cur


def write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}.{threading.get_ident()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)
