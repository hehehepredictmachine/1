"""Cross-process lock (PMW-LOCK-1) shared by Studio instances and the bot's export: lock file created with O_EXCL holding the owner
(pid, app, job, host) and a heartbeat. A lock is stale when its pid is dead or the heartbeat is older than `stale_s`; a stale lock is taken
over atomically (rename + re-create). Only the owner releases it."""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


class Lock:
    def __init__(self, path: Path, *, app: str, stale_s: float = 120.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.app, self.stale_s = app, stale_s
        self.held = False
        self.job = None

    def owner(self) -> dict | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, fd, job):
        rec = {"pid": os.getpid(), "app": self.app, "job": job, "host": socket.gethostname(), "acquired_at": time.time(), "heartbeat": time.time()}
        os.write(fd, json.dumps(rec).encode())
        os.close(fd)

    def stale(self, o: dict | None) -> bool:
        if not o:
            return True
        return (not _alive(o.get("pid"))) or (time.time() - float(o.get("heartbeat") or 0) > self.stale_s)

    def acquire(self, job: str | None = None) -> tuple[bool, dict | None]:
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                self._write(fd, job)
                self.held, self.job = True, job
                return True, None
            except FileExistsError:
                o = self.owner()
                if o and o.get("pid") == os.getpid() and o.get("job") == job:
                    self.held = True
                    return True, None
                if not self.stale(o):
                    return False, o
                tomb = self.path.with_suffix(f".stale-{os.getpid()}")
                try:
                    os.replace(self.path, tomb)
                    tomb.unlink(missing_ok=True)
                except OSError:
                    pass
        return False, self.owner()

    def heartbeat(self) -> None:
        if not self.held:
            return
        o = self.owner() or {}
        if o.get("pid") != os.getpid():
            self.held = False
            return
        o["heartbeat"] = time.time()
        tmp = self.path.with_suffix(".hb")
        tmp.write_text(json.dumps(o), encoding="utf-8")
        os.replace(tmp, self.path)

    def release(self) -> None:
        o = self.owner()
        if o and o.get("pid") == os.getpid():
            self.path.unlink(missing_ok=True)
        self.held = False
