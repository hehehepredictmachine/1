"""ONE way to read and write the bot's JSON registries and activation pointers (1.46 arch, PMW-REGISTRY-IO-1).

Before 1.46 each owner (lab ACTIVE.json, mm SHADOW_ACTIVE.json, Monte Carlo registry.json, Quant MetaModel ACTIVE.json, trainhub
registry.json, gold_candles / scalp registries) had its own copy of "read JSON, on any error return an empty view". A writer that
re-read the file through that view and saved it back turned a momentarily unreadable file (locked by an antivirus / indexer, a
truncated write) into an EMPTY registry: the active model, the history (rollback) and the seen-tests list were lost.

Rules (every registry / pointer of the bot):
* readers that only DISPLAY may get the empty view (``strict=False``), marked ``error = REGISTRY_UNREADABLE``;
* every read-modify-write uses ``strict=True`` -> :class:`RegistryUnreadable`, the file stays untouched;
* writes go through a unique temporary file + ``os.replace`` (no shared ``.tmp`` name between processes);
* read-modify-write runs under :func:`file_lock` (OS lock released by the OS when a process dies + a thread lock, re-entrant in the
  same thread).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path


class RegistryUnreadable(RuntimeError):
    """An existing registry / pointer file cannot be read (or is not a JSON object) - the caller must not write it back."""


def read_json(path: Path, default: Callable[[], dict], *, strict: bool) -> dict:
    """-> the JSON object in `path`; `default()` when the file does not exist. Unreadable / not an object: strict -> RegistryUnreadable,
    otherwise `default()` with ``error = "REGISTRY_UNREADABLE"`` (display only - never write that view back)."""
    p = Path(path)
    if not p.exists():
        return default()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError(f"not a JSON object ({type(data).__name__})")
        return data
    except (OSError, ValueError, TypeError) as exc:
        if strict:
            raise RegistryUnreadable(f"REGISTRY_UNREADABLE: {p} ({type(exc).__name__}: {exc}) – plik zostaje bez zmian; zamknij program "
                                     "blokujący plik albo przywróć kopię i powtórz") from None
        view = default()
        view["error"] = "REGISTRY_UNREADABLE"
        return view


def write_json_atomic(path: Path, data, *, indent: int | None = 1) -> None:
    """Unique temporary file next to the target + os.replace (a reader never sees a half-written file, two writers never share a tmp)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)                     # only left over when the write / replace failed


_TLOCK = threading.RLock()
_HELD = threading.local()


@contextmanager
def file_lock(lock_path: Path, timeout_s: float = 60.0):
    """Exclusive OS file lock (fcntl.flock / msvcrt.locking) on `lock_path` plus a thread lock; re-entrant in the same thread.
    Hold it only for re-read -> change -> save. (Moved from trainhub/registry.reg_lock, 1.46 - same behaviour.)"""
    key = str(Path(lock_path).resolve())
    with _TLOCK:
        held = _HELD.__dict__.setdefault("n", {})
        if held.get(key):
            held[key] += 1
            try:
                yield
            finally:
                held[key] -= 1
            return
        p = Path(lock_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        f = open(p, "a+b")  # noqa: SIM115 - the handle IS the lock, closed in finally
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                end = time.monotonic() + timeout_s
                while True:
                    try:
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() > end:
                            raise TimeoutError(f"rejestr {p.parent.name} zajęty przez inny proces dłużej niż {timeout_s:.0f} s") from None
                        time.sleep(0.05)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            held[key] = 1
            try:
                yield
            finally:
                held[key] = 0
                try:
                    if os.name == "nt":
                        import msvcrt
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass                                   # closing the handle releases the lock anyway
        finally:
            f.close()


def lock_for(path: Path) -> Path:
    """Lock file of a registry / pointer: <name>.lock next to it."""
    p = Path(path)
    return p.with_name(p.stem + ".lock")
