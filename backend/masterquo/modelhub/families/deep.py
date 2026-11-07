"""Bridge to the isolated .venv_deep worker (deep_runtime). Python is found like Kronos: MQ_DEEP_PYTHON, <app>/.venv_deep/Scripts/
python.exe, <app>/.venv_deep/bin/python. Each call is a separate process with a timeout; a late or failed answer is never published as
current (the caller marks the prediction ERROR / BLOCKED). The health check is cached for 10 minutes."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

_HEALTH: dict = {}


def python() -> str | None:
    from ... import paths
    root = paths.ROOT_DIR
    for c in (os.environ.get("MQ_DEEP_PYTHON"), str(root / ".venv_deep" / "Scripts" / "python.exe"), str(root / ".venv_deep" / "bin" / "python")):
        if c and Path(c).is_file():
            return c
    return None


def call(op: str, payload: dict, timeout: float = 600.0) -> dict:
    py = python()
    if py is None:
        return {"ok": False, "error": "DEEP_ENV_NOT_INSTALLED: brak .venv_deep (34_DEEP_INSTALUJ.bat / install-deep)"}
    from ... import paths
    with tempfile.TemporaryDirectory() as td:
        rq, rs = Path(td) / "req.json", Path(td) / "res.json"
        rq.write_text(json.dumps({"op": op, **payload}, default=str), encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(paths.ROOT_DIR / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        try:
            p = subprocess.run([py, "-m", "deep_runtime.worker", str(rq), str(rs)], cwd=str(paths.ROOT_DIR / "backend"), env=env, timeout=timeout,
                               capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"TIMEOUT {timeout:.0f}s"}
        if not rs.exists():
            return {"ok": False, "error": f"WORKER_FAILED rc={p.returncode}: {(p.stderr or '')[-400:]}"}
        return json.loads(rs.read_text(encoding="utf-8"))


def health(force: bool = False) -> dict:
    now = time.time()
    if not force and _HEALTH.get("at") and now - _HEALTH["at"] < 600:
        return _HEALTH["value"]
    v = call("health", {}, timeout=120)
    _HEALTH.update(at=now, value=v)
    return v


def available(deps: tuple[str, ...]) -> tuple[bool, str | None]:
    if python() is None:
        return False, "brak środowiska .venv_deep (instalacja: 34_DEEP_INSTALUJ.bat)"
    h = health()
    if not h.get("ok"):
        return False, f"worker .venv_deep: {h.get('error')}"
    miss = [d for d in deps if not h.get(d)]
    return (not miss), ("brak w .venv_deep: " + ", ".join(miss)) if miss else None
