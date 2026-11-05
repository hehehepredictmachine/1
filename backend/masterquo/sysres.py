"""System resources for the Infrastructure Monitor of the Control Tower (1.32): CPU and RAM of the computer, memory of the bot
process and its uptime. Standard library only (ctypes on Windows, /proc on Linux) - no psutil. A value the platform does not
provide is None (shown as "brak pomiaru"), never a guess."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time

STARTED_AT = time.time()            # first import = start of the bot process (imported by the API module at start-up)
_lock = threading.Lock()
_last: tuple[float, float] | None = None   # (busy, total) of the previous CPU sample


def _cpu_times() -> tuple[float, float] | None:
    """(busy, total) CPU time since boot, any unit."""
    try:
        if sys.platform == "win32":
            class FT(ctypes.Structure):
                _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]
            idle, kern, user = FT(), FT(), FT()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
                return None
            v = lambda f: (f.hi << 32) | f.lo
            total = v(kern) + v(user)                  # kernel time includes idle time
            return float(total - v(idle)), float(total)
        with open("/proc/stat", encoding="ascii") as f:
            parts = [float(x) for x in f.readline().split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
        total = sum(parts[:8])
        return total - idle, total
    except Exception:
        return None


def cpu_percent() -> float | None:
    """Whole-computer CPU load since the previous call (first call: a 0.25 s sample)."""
    global _last
    with _lock:
        a = _last or _cpu_times()
        if a is None:
            return None
        if _last is None:
            time.sleep(0.25)
        b = _cpu_times()
        if b is None:
            return None
        _last = b
    busy, total = b[0] - a[0], b[1] - a[1]
    return round(100.0 * busy / total, 1) if total > 0 else None


def memory() -> dict:
    out: dict = {"total_mb": None, "used_pct": None, "process_mb": None}
    try:
        if sys.platform == "win32":
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32), ("ullTotalPhys", ctypes.c_uint64),
                            ("ullAvailPhys", ctypes.c_uint64), ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                            ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64), ("ullAvailExtendedVirtual", ctypes.c_uint64)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                out["total_mb"] = round(m.ullTotalPhys / 2**20)
                out["used_pct"] = round(100.0 * (m.ullTotalPhys - m.ullAvailPhys) / m.ullTotalPhys, 1) if m.ullTotalPhys else None

            class PMC(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            h = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                out["process_mb"] = round(pmc.WorkingSetSize / 2**20, 1)
        else:
            info = {}
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    info[k] = float(v.split()[0]) if v.split() else 0.0
            tot, avail = info.get("MemTotal"), info.get("MemAvailable")
            if tot:
                out["total_mb"] = round(tot / 1024)
                out["used_pct"] = round(100.0 * (tot - (avail or 0.0)) / tot, 1) if avail is not None else None
            with open("/proc/self/status", encoding="ascii") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        out["process_mb"] = round(float(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return out


def snapshot() -> dict:
    now = time.time()
    return {"cpu_pct": cpu_percent(), "memory": memory(), "started_at": STARTED_AT, "uptime_s": round(now - STARTED_AT, 1),
            "pid": os.getpid(), "platform": sys.platform, "measured_at": now,
            "note": "CPU i RAM całego komputera; pamięć procesu = proces silnika bota. Brak wartości = system jej nie podał."}
