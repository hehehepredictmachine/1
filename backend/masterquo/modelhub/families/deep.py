"""Bridge to the isolated .venv_deep worker (deep_runtime). Python is found like Kronos: MQ_DEEP_PYTHON, <app>/.venv_deep/Scripts/
python.exe, <app>/.venv_deep/bin/python. A late or failed answer is never published as current (the caller marks the prediction ERROR /
BLOCKED). The health check is cached for 10 minutes.

Processes (1.46, I0215 / I0218): training and the health check are one-shot processes (`python -m deep_runtime.worker req res`, as
before). The live predictions (SERVED_OPS: predict_seq of SEQ_LSTM / SEQ_GRU, predict_ppo of RL_PPO) go to ONE persistent worker
(`python -m deep_runtime.worker --serve`, one JSON line per request / answer, like kronos_runtime.worker) - 1.45 / 1.46.0 started a new
process with a fresh `import torch` for every new closed bar, synchronously inside the SH cycle and the decision coordinator. Same
synchronous semantics, same per-call timeout (it also covers waiting for a call in progress and the first start of the process), same
error texts (TIMEOUT <n>s / WORKER_FAILED rc=...); on a timeout or a broken answer the process is killed and the next call starts a
new one. The worker ends with the bot (stdin closed / atexit)."""
from __future__ import annotations

import atexit
import contextlib
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

_HEALTH: dict = {}     # process cache (TTL 600 s) of the deep worker health; reset_health_cache() is the hook (1.46 arch I0104)


def reset_health_cache() -> None:
    """Forget the cached worker health (tests; after a reinstall of the deep environment)."""
    _HEALTH.clear()
SERVED_OPS = ("predict_seq", "predict_ppo")
_SRV: dict = {"proc": None, "py": None, "log": None, "starts": 0}
_SRV_LOCK = threading.Lock()                           # one request at a time on the persistent worker


def python() -> str | None:
    # 1.46 arch (I0117): MQ_DEEP_PYTHON -> .venv_deep (is_file), as before
    from ... import runtimes
    return runtimes.find_python("deep")


def _env() -> dict:
    from ... import paths
    return dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")


def call(op: str, payload: dict, timeout: float = 600.0) -> dict:
    py = python()
    if py is None:
        return {"ok": False, "error": "DEEP_ENV_NOT_INSTALLED: brak .venv_deep (34_DEEP_INSTALUJ.bat / install-deep)"}
    if op in SERVED_OPS:
        return _served(py, op, payload, timeout)
    from ... import paths
    with tempfile.TemporaryDirectory() as td:
        rq, rs = Path(td) / "req.json", Path(td) / "res.json"
        rq.write_text(json.dumps({"op": op, **payload}, default=str), encoding="utf-8")
        try:
            p = subprocess.run([py, "-m", "deep_runtime.worker", str(rq), str(rs)], cwd=str(paths.ROOT_DIR / "backend"), env=_env(), timeout=timeout,
                               capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"TIMEOUT {timeout:.0f}s"}
        if not rs.exists():
            return {"ok": False, "error": f"WORKER_FAILED rc={p.returncode}: {(p.stderr or '')[-400:]}"}
        return json.loads(rs.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ persistent prediction worker (I0215)
def _log_tail(n: int = 400) -> str:
    p = _SRV.get("log")
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")[-n:] if p else ""
    except OSError:
        return ""


def _start(py: str):
    from ... import paths
    try:
        log = paths.logs_dir() / "deep_worker.log"                      # library warnings / tracebacks of the worker
    except OSError:
        log = None
    argv = [py, "-m", "deep_runtime.worker", "--serve"]
    kw = {"cwd": str(paths.ROOT_DIR / "backend"), "env": _env(), "text": True, "encoding": "utf-8", "stdin": subprocess.PIPE,
          "stdout": subprocess.PIPE, "bufsize": 1, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    if log is None:
        p = subprocess.Popen(argv, stderr=subprocess.DEVNULL, **kw)
    else:
        with open(log, "a", encoding="utf-8") as errlog:                # the child holds its own handle
            p = subprocess.Popen(argv, stderr=errlog, **kw)
    _SRV.update(proc=p, py=py, log=str(log) if log else None, starts=_SRV["starts"] + 1)
    return p


def _stop(graceful: bool = False) -> None:
    p, _SRV["proc"] = _SRV.get("proc"), None
    if p is None:
        return
    with contextlib.suppress(Exception):                                # already gone
        if p.poll() is None:
            done = False
            if graceful:
                with contextlib.suppress(Exception):                    # not answering -> killed below
                    p.stdin.write('{"op": "quit"}\n')
                    p.stdin.flush()
                    p.wait(timeout=5)
                    done = True
            if not done:
                p.kill()
                with contextlib.suppress(Exception):
                    p.wait(timeout=5)
    for s in (getattr(p, "stdin", None), getattr(p, "stdout", None)):
        with contextlib.suppress(Exception):
            s.close()


def shutdown() -> None:
    """Ends the persistent worker (bot exit, tests). The next served call starts a new one."""
    with _SRV_LOCK:
        _stop(graceful=True)


atexit.register(lambda: _stop(graceful=False))


def _served(py: str, op: str, payload: dict, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    if not _SRV_LOCK.acquire(timeout=max(0.0, timeout)):
        return {"ok": False, "error": f"TIMEOUT {timeout:.0f}s"}
    try:
        p = _SRV.get("proc")
        if p is None or p.poll() is not None or _SRV.get("py") != py:
            _stop(graceful=p is not None and p.poll() is None)
            try:
                p = _start(py)
            except OSError as exc:
                return {"ok": False, "error": f"WORKER_FAILED: {type(exc).__name__}: {exc}"[:500]}
        rid = uuid.uuid4().hex[:12]
        try:
            p.stdin.write(json.dumps({"op": op, "id": rid, **payload}, default=str) + "\n")
            p.stdin.flush()
        except (OSError, ValueError) as exc:
            rc = p.poll()
            _stop()
            return {"ok": False, "error": f"WORKER_FAILED rc={rc}: {type(exc).__name__}: {exc} {_log_tail()}"[:600]}
        box: dict = {}
        th = threading.Thread(target=lambda: box.update(line=p.stdout.readline()), daemon=True, name="deep-worker-read")
        th.start()
        th.join(max(0.0, deadline - time.monotonic()))
        if th.is_alive():
            _stop()                                                     # a late answer is never read as current
            return {"ok": False, "error": f"TIMEOUT {timeout:.0f}s"}
        line = box.get("line")
        if not line:
            rc = p.poll()
            _stop()
            return {"ok": False, "error": f"WORKER_FAILED rc={rc}: {_log_tail()}"[:600]}
        try:
            res = json.loads(line)
        except ValueError:
            _stop()
            return {"ok": False, "error": f"WORKER_PROTOCOL: {line[:200]}"}
        if not isinstance(res, dict) or res.pop("id", None) != rid:
            _stop()
            return {"ok": False, "error": "WORKER_PROTOCOL_DESYNC"}
        return res
    finally:
        _SRV_LOCK.release()


def health(force: bool = False) -> dict:
    now = time.time()
    if not force and _HEALTH.get("at") and now - _HEALTH["at"] < 600:
        return _HEALTH["value"]
    v = call("health", {}, timeout=120)
    _HEALTH.update(at=now, value=v)
    return v


def health_age() -> float | None:
    """Seconds since the cached health check (None = never checked). 1.46 arch (I0790): FamilyService refreshes it in its background
    thread before the 600 s cache expires, so the SH cycle does not run the health process synchronously."""
    at = _HEALTH.get("at")
    return None if not at else time.time() - at


def available(deps: tuple[str, ...]) -> tuple[bool, str | None]:
    if python() is None:
        return False, "brak środowiska .venv_deep (instalacja: 34_DEEP_INSTALUJ.bat)"
    h = health()
    if not h.get("ok"):
        return False, f"worker .venv_deep: {h.get('error')}"
    miss = [d for d in deps if not h.get(d)]
    return (not miss), ("brak w .venv_deep: " + ", ".join(miss)) if miss else None
