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

_HEALTH: dict = {}     # process cache (TTL 600 s) of the deep worker health; reset_health_cache() is the hook (1.46 arch I0104)


def reset_health_cache() -> None:
    """Forget the cached worker health (tests; after a reinstall of the deep environment)."""
    _HEALTH.clear()


def python() -> str | None:
    # 1.46 arch (I0117): MQ_DEEP_PYTHON -> .venv_deep (is_file), as before
    from ... import runtimes
    return runtimes.find_python("deep")


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
