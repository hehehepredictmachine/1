"""Training child processes started by the bot server (arch146 I0100): one registry and one way to end a process tree.

Until 1.46 arch the training processes of the Centrum Treningowe Pepe (`training run`), of the model families, of the panel's training
buttons (api train_procs) and of the panel export (training/export_job) lived in four separate places and Runtime.stop() ended none of
them - only TrainingCenter (trainhub) killed its child. Now:

* ProcessRegistry keeps ONLY training / export / fine-tune processes of THIS server (Popen objects - never a pid read from a file, which
  could be reused by another program). The MT5 worker / bridge and every process of the execution path are never registered (KINDS).
* kill_tree() ends one child and its tree WITHOUT the MetaTrader terminal: POSIX - the process group only when the child leads its own group
  (start_new_session=True, os.getpgid(pid) == pid), otherwise the process itself; Windows - the process and its python descendants
  (taskkill /T would also end terminal64.exe started by MetaTrader5.initialize() inside an export / training child, with the user's EA).
* stop_all() never blocks long: signal every child, wait at most `timeout_s` together, then kill the processes themselves.
Standard library only (ctypes on Windows) - no psutil in the bot environment.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

log = logging.getLogger(__name__)

KINDS = ("training", "export", "fine_tune")
MT5_IMAGES = ("terminal64.exe", "terminal.exe", "metaeditor64.exe", "metaeditor.exe")


class ProcessRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._procs: dict[str, tuple[subprocess.Popen, str]] = {}

    def register(self, name: str, proc: subprocess.Popen, kind: str = "training") -> subprocess.Popen:
        if kind not in KINDS:
            raise ValueError(f"ProcessRegistry: rodzaj {kind!r} spoza {KINDS} (tylko trening / eksport / dostrajanie)")
        with self._lock:
            for n in [n for n, (p, _) in self._procs.items() if p.poll() is not None]:
                self._procs.pop(n, None)                          # finished children leave (poll() also reaps them)
            self._procs[name] = (proc, kind)
        return proc

    # 1.46 arch (Etap 4, martwy kod): unregister() had no caller (AST + grep) - register() already drops finished children.

    def running(self) -> dict[str, dict]:
        with self._lock:
            items = list(self._procs.items())
        return {n: {"pid": p.pid, "kind": k} for n, (p, k) in items if p.poll() is None}

    def stop_all(self, timeout_s: float = 3.0) -> list[str]:
        """Ends every registered live child (tree without the MT5 terminal). Returns the names it ended."""
        with self._lock:
            items = [(n, p) for n, (p, _) in self._procs.items() if p.poll() is None]
        return stop_procs(items, timeout_s)

    def stop(self) -> list[str]:
        """Runtime.stop() part 'procs' (after engine / manager - the trading stop is never delayed by it)."""
        return self.stop_all()


def stop_procs(items: list[tuple[str, subprocess.Popen]], timeout_s: float = 3.0) -> list[str]:
    """kill_tree for each live (name, Popen), then wait at most `timeout_s` for all of them together; a child still alive after that is
    killed (the process itself). Never raises."""
    live = [(n, p) for n, p in items if p is not None and p.poll() is None]
    for _, p in live:
        kill_tree(p)
    end = time.monotonic() + max(0.0, float(timeout_s))
    for _, p in live:
        try:
            p.wait(max(0.0, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                p.kill()
            except OSError:
                pass
        except OSError:
            pass
    return [n for n, _ in live]


def kill_tree(p: subprocess.Popen | None) -> None:
    """Ends a child of this server and its tree, never the MetaTrader terminal. Never raises."""
    if p is None or p.poll() is not None:
        return
    try:
        if os.name == "nt":
            for pid in _win_python_descendants(p.pid):
                _win_terminate(pid)
            p.terminate()
            return
        import signal
        if os.getpgid(p.pid) == p.pid:                            # started with start_new_session=True: the group is its own tree
            os.killpg(p.pid, signal.SIGTERM)
        else:
            p.terminate()
    except (OSError, ValueError, subprocess.SubprocessError):
        try:
            p.terminate()
        except OSError:
            pass


# ------------------------------------------------------------------ Windows: process tree without the MT5 terminal
def _win_processes() -> list[tuple[int, int, str]]:
    """(pid, parent pid, image name) of every process (CreateToolhelp32Snapshot)."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x00000002, 0)              # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out = []
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(e))
        while ok:
            out.append((int(e.th32ProcessID), int(e.th32ParentProcessID), str(e.szExeFile)))
            ok = k.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(e))
    finally:
        k.CloseHandle(wintypes.HANDLE(snap))
    return out


def _python_tree(root: int, procs: list[tuple[int, int, str]], started=None) -> list[int]:
    """Descendants of `root` that are python processes (python.exe / pythonw.exe), deepest first; the MetaTrader terminal and every other
    program are left alone (also their own children). `started(pid)` - creation time, used to drop a child whose parent pid was reused."""
    kids: dict[int, list[tuple[int, str]]] = {}
    for pid, ppid, name in procs:
        if pid != ppid:
            kids.setdefault(ppid, []).append((pid, name))
    out, todo, seen = [], [root], {root}
    while todo:
        cur = todo.pop()
        t0 = started(cur) if started else None
        for pid, name in kids.get(cur, []):
            low = name.lower()
            if pid in seen or low in MT5_IMAGES or "metatrader" in low or not low.startswith("python"):
                continue
            t1 = started(pid) if started else None
            if t0 is not None and t1 is not None and t1 < t0:      # older than its "parent": the parent pid was reused
                continue
            seen.add(pid)
            out.append(pid)
            todo.append(pid)
    return out[::-1]


def _win_python_descendants(root: int) -> list[int]:
    try:
        from .training.core import _proc_start
        return _python_tree(root, _win_processes(), _proc_start)
    except Exception:  # noqa: BLE001 - no snapshot: the process itself is still ended by the caller
        return []


def _win_terminate(pid: int) -> None:
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = wintypes.HANDLE
        h = k.OpenProcess(0x0001, False, int(pid))                # PROCESS_TERMINATE
        if h:
            try:
                k.TerminateProcess(wintypes.HANDLE(h), 1)
            finally:
                k.CloseHandle(wintypes.HANDLE(h))
    except Exception:  # noqa: BLE001, S110 - best effort; the caller still ends the process itself
        pass


REGISTRY = ProcessRegistry()          # one per server process: api train_procs, panel export, Centrum Pepe, model families
