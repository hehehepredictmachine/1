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
# Process caches of this module (1.46 arch I0104): STARTED_AT (by design, once per process) and the CPU samplers below - each consumer owns
# one (API snapshot -> API_SAMPLER, Memory Governor -> its own instance); reset_cpu_samplers() is the test hook.


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


class CpuSampler:
    """Whole-computer CPU load since this sampler's previous call (first call: a 0.25 s sample).

    1.46 arch (I0104): 1.45 kept ONE module-level previous sample for every caller - the API snapshot and the Memory Governor
    (resources/governor.py public()) moved each other's measuring window; two calls a few ms apart measured a random few-ms window or
    nothing at all (None = 'brak pomiaru'). Now each consumer has its own sampler, and a call within MIN_WINDOW_S of the previous sample
    returns the last value of THIS sampler without moving its window. Display only - no decision reads it."""

    MIN_WINDOW_S = 0.5

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._prev: tuple[float, float] | None = None     # (busy, total) of the previous sample
        self._prev_at: float | None = None
        self._value: float | None = None

    def reset(self) -> None:
        with self._lock:
            self._prev, self._prev_at, self._value = None, None, None

    def percent(self) -> float | None:
        with self._lock:
            now = self._clock()
            if self._prev is not None and self._value is not None and self._prev_at is not None and now - self._prev_at < self.MIN_WINDOW_S:
                return self._value
            a = self._prev or _cpu_times()
            if a is None:
                return None
            if self._prev is None:
                time.sleep(0.25)
            b = _cpu_times()
            if b is None:
                return None
            busy, total = b[0] - a[0], b[1] - a[1]
            if total <= 0:                       # no CPU time elapsed: keep the window (and the last value of this sampler)
                if self._prev is None:
                    self._prev, self._prev_at = b, self._clock()
                return self._value
            self._prev, self._prev_at = b, self._clock()
            self._value = round(100.0 * busy / total, 1)
            return self._value


API_SAMPLER = CpuSampler()          # the API snapshot (/api/v1/system/resources)
_DEFAULT_SAMPLER = CpuSampler()     # cpu_percent() of any other caller


def reset_cpu_samplers() -> None:
    """Test hook: forget the previous samples of the module's samplers."""
    API_SAMPLER.reset()
    _DEFAULT_SAMPLER.reset()


def cpu_percent() -> float | None:
    """Whole-computer CPU load since the previous call of THIS module-level sampler (kept for compatibility; consumers own a CpuSampler)."""
    return _DEFAULT_SAMPLER.percent()


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
    return {"cpu_pct": API_SAMPLER.percent(), "memory": memory(), "started_at": STARTED_AT, "uptime_s": round(now - STARTED_AT, 1),
            "pid": os.getpid(), "platform": sys.platform, "measured_at": now,
            "note": "CPU i RAM całego komputera; pamięć procesu = proces silnika bota. Brak wartości = system jej nie podał."}
