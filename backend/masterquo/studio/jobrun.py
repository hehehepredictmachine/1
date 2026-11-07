"""python -m masterquo.studio.jobrun <queue.sqlite> <job_id> - executes ONE job in its own process (export / validation / dataset /
training of one task into one package). Writes state, stage, progress and heartbeat to the queue db; reads pause / cancel flags between
chunks and stages."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import traceback


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    dbp, jid = argv[0], argv[1]
    db = sqlite3.connect(dbp, isolation_level=None, timeout=15)
    db.row_factory = sqlite3.Row
    j = dict(db.execute("SELECT * FROM jobs WHERE job_id=?", (jid,)).fetchone())
    db.execute("UPDATE jobs SET pid=? WHERE job_id=?", (os.getpid(), jid))
    from ..config import ConfigStore
    from . import pipeline as P
    from . import registry as R
    from . import settings as S
    from .package import Package
    cfg = ConfigStore()
    task = R.by_key(cfg).get(j["task_key"])
    if task is None:
        db.execute("UPDATE jobs SET state='FAILED', error=?, finished_at=? WHERE job_id=?", ("nieznane zadanie (zmiana rejestru)", time.time(), jid))
        return 2
    if task["state"] != "SUPPORTED":
        st = "BLOCKED_DEPENDENCY" if task["state"] == "BLOCKED_DEPENDENCY" else "FAILED"
        db.execute("UPDATE jobs SET state=?, error=?, finished_at=? WHERE job_id=?", (st, task.get("reason") or task["state"], time.time(), jid))
        return 3
    source = json.loads(j["source"] or "{}")
    source.setdefault("cutoff", int(time.time()))
    pkg = Package(S.data_dir(), task, j["run_id"])
    db.execute("UPDATE jobs SET package=? WHERE job_id=?", (str(pkg.dir), jid))
    last = {"t": 0.0}

    def flag(col):
        r = db.execute(f"SELECT {col} FROM jobs WHERE job_id=?", (jid,)).fetchone()
        return bool(r and r[0])

    def progress(d):
        now = time.time()
        if "state" in d:
            db.execute("UPDATE jobs SET state=?, stage=? WHERE job_id=?", (d["state"], d.get("stage"), jid))
        if now - last["t"] > 0.5 or "state" in d:
            last["t"] = now
            db.execute("UPDATE jobs SET progress=?, heartbeat=? WHERE job_id=?", (json.dumps(d, default=str), now, jid))

    ctx = P.Ctx(task, pkg, source=source, profile=j["profile"] or "smoke", cancel=lambda: flag("cancel"), pause=lambda: flag("pause"),
                progress=progress, cfg_store=cfg)
    try:
        res = P.run_task(task, pkg, j["op"], ctx)
        db.execute("UPDATE jobs SET state=?, package=?, finished_at=?, progress=? WHERE job_id=?",
                   (res["status"], res["package"], time.time(), json.dumps(res, default=str), jid))
        return 0
    except P.Blocked as b:
        pkg.fail(j["op"], b.state, b.reason)
        db.execute("UPDATE jobs SET state=?, error=?, finished_at=? WHERE job_id=?", (b.state, b.reason, time.time(), jid))
        return 0 if b.state == "PAUSED" else 4
    except Exception as exc:  # noqa: BLE001
        pkg.log(traceback.format_exc())
        db.execute("UPDATE jobs SET state='FAILED', error=?, finished_at=? WHERE job_id=?", (f"{type(exc).__name__}: {exc}"[:1000], time.time(), jid))
        return 1


if __name__ == "__main__":
    sys.exit(main())
