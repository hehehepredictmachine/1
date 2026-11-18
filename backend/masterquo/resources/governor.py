"""1.40 Memory Governor + AI inference scheduler (ONE resource manager for the model processes; profiles are its configurations).

What it does (measured, never guessed - a value the platform does not give is None):
  * reads the RAM of the computer (total / available / used %) and the memory of the bot process + every registered model process
    (Kronos, Chronos-2, Granite TTM workers, training jobs): current RSS / working set and the PEAK of each process;
  * computes a level from the profile thresholds: OK < WARN (warn_pct, default 75 %) < LIMIT_HEAVY (80 %) < PAUSE_OPTIONAL (85 %);
    the PMW budget (sum of the processes above budget_max_mb) also gives LIMIT_HEAVY;
  * admission of AI work (`admit`): forecasts of the foundation models are OPTIONAL information (OBSERVE by default):
      - PAUSE_OPTIONAL -> no new optional inference (the model state shows the reason; no neutral vote is produced);
      - LIMIT_HEAVY    -> a heavy model that is NOT loaded is not started (no new big allocation); loaded ones may still answer;
      - the light model (Granite TTM) runs until PAUSE_OPTIONAL;
    market data, open positions, risk engine and execution are NEVER gated here (they do not ask the governor);
  * one shared slot for heavy inference / loading across services (`heavy(...)`, default parallelism 1): Kronos and Chronos-2 never
    load or compute at the same time on a 16 GB computer (their own queues already deduplicate per closed bar);
  * idle release of heavy model processes: only when the profile says so (ECO) or when the level is >= WARN - never a load / unload loop
    (a released model is started again on the next closed bar it is needed for);
  * CPU threads per model process from the profile; heavy training is refused while AUTO trading runs unless the profile allows it, and
    two heavy trainings never run together;
  * statistics: load time, inference p50 / p95 per model, peak RSS, admissions refused, released processes.
Standard library only (ctypes on Windows, /proc on Linux) - no psutil in the bot environment.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from contextlib import contextmanager

from .. import sysres

LEVELS = ("OK", "WARN", "LIMIT_HEAVY", "PAUSE_OPTIONAL")
LEVEL_PL = {"OK": "pamięć w normie", "WARN": "wysokie użycie RAM – ostrzeżenie", "LIMIT_HEAVY": "ograniczenie: brak nowych ciężkich modeli",
            "PAUSE_OPTIONAL": "awaryjne wstrzymanie opcjonalnych prognoz AI"}
HEAVY = ("kronos", "chronos2", "tirex2", "tabicl", "sdformerflow")   # >= ~0.6-1 GB per process (measured on CPU, float32; TiRex-2 1.06 GB, TabICL 0.66 GB)
LIGHT = ("granite_ttm",)                 # ~0.35 GB per process
PROFILE_KEYS = ("warn_pct", "limit_heavy_pct", "pause_optional_pct", "reserve_os_mb", "budget_preferred_mb", "budget_max_mb",
                "heavy_parallelism", "idle_release_s", "release_on_pressure", "threads_heavy", "threads_light", "lazy_loading", "dedup",
                "forecast_cache", "background_training", "auto_download", "cpu_fallback", "monitoring", "auto_throttle",
                "heavy_allowed", "max_resident_heavy")


def _cores() -> int:
    return max(1, os.cpu_count() or 2)


def profiles() -> dict[str, dict]:
    c = _cores()
    low = {"warn_pct": 75.0, "limit_heavy_pct": 80.0, "pause_optional_pct": 85.0, "reserve_os_mb": 4096, "budget_preferred_mb": 6144,
           "budget_max_mb": 8192, "heavy_parallelism": 1, "idle_release_s": None, "release_on_pressure": True,
           "threads_heavy": max(1, min(4, c // 2)), "threads_light": max(1, min(2, c // 4 or 1)), "lazy_loading": True, "dedup": True,
           "forecast_cache": True, "background_training": False, "auto_download": False, "cpu_fallback": True, "monitoring": True,
           "auto_throttle": True, "heavy_allowed": None, "max_resident_heavy": None}
    return {
        "LOW_MEMORY_16GB": low,
        # 1.42.4 (measured peaks, CPU float32: Kronos 1.07 GB, TiRex-2 0.94, Chronos-2 0.84, TabICLv2 0.67, Granite TTM 0.37; bot ~0.7):
        # 8 GB computer - Windows + MT5 take ~4.5-5 GB, PMW gets ~2.5-3 GB: Granite TTM + ONE heavy model resident at a time (every model may
        # run - the others are released before it loads, a heavy model is released 90 s after its last use); SDformerFlow training off.
        "LOW_MEMORY_8GB": {**low, "warn_pct": 85.0, "limit_heavy_pct": 90.0, "pause_optional_pct": 94.0, "reserve_os_mb": 1536,
                           "budget_preferred_mb": 2560, "budget_max_mb": 3328, "idle_release_s": 90, "threads_heavy": max(1, min(2, c // 2)),
                           "threads_light": 1, "heavy_allowed": ["tirex2", "tabicl", "kronos", "chronos2"], "max_resident_heavy": 1},
        # 12 GB computer - PMW gets ~4-5 GB: Granite TTM + TWO heavy models resident, idle heavy released after 5 min.
        "LOW_MEMORY_12GB": {**low, "warn_pct": 82.0, "limit_heavy_pct": 87.0, "pause_optional_pct": 93.0, "reserve_os_mb": 2560,
                            "budget_preferred_mb": 3584, "budget_max_mb": 5120, "idle_release_s": 300, "threads_heavy": max(1, min(3, c // 2)),
                            "threads_light": 1, "heavy_allowed": None, "max_resident_heavy": 2},
        "ECO": {**low, "warn_pct": 70.0, "limit_heavy_pct": 75.0, "pause_optional_pct": 80.0, "budget_preferred_mb": 4096, "budget_max_mb": 6144,
                "idle_release_s": 600, "threads_heavy": max(1, min(2, c // 4 or 1)), "threads_light": 1},
        "BALANCED": {**low, "warn_pct": 80.0, "limit_heavy_pct": 85.0, "pause_optional_pct": 90.0, "budget_preferred_mb": 8192,
                     "budget_max_mb": 10240, "threads_heavy": max(1, min(6, c - 2)), "threads_light": max(1, min(4, c // 2))},
    }


PROFILE_PL = {"LOW_MEMORY_16GB": "Niska pamięć – komputer 16 GB (domyślny)",
              "LOW_MEMORY_8GB": "Komputer 8 GB – Granite TTM + jeden ciężki model naraz (pozostałe zwalniane przed załadowaniem)",
              "LOW_MEMORY_12GB": "Komputer 12 GB – Granite TTM + dwa ciężkie modele naraz",
              "AUTO": "AUTO – profil dobierany do RAM komputera (≤ 10 GB → 8 GB, ≤ 14 GB → 12 GB, więcej → 16 GB)", "ECO": "ECO – najmniej pamięci i CPU, ciężkie modele zwalniane po bezczynności",
              "BALANCED": "BALANCED – więcej wątków, wyższe progi (komputer z zapasem RAM)", "MANUAL": "MANUAL – własne wartości"}


_WIN_API = None


def _win_api():
    """kernel32/psapi with explicit prototypes (64-bit HANDLE, BOOL) - without them ctypes passes/returns a C int, which truncates
    handles on 64-bit Windows. Built once; on any problem the governor simply reports 'unknown' (None), it never guesses."""
    global _WIN_API
    if _WIN_API is None:
        from ctypes import wintypes as W

        class PMC(ctypes.Structure):
            _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        k32.OpenProcess.restype = W.HANDLE
        k32.CloseHandle.argtypes = [W.HANDLE]
        k32.CloseHandle.restype = W.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [W.HANDLE, ctypes.POINTER(PMC), W.DWORD]
        psapi.GetProcessMemoryInfo.restype = W.BOOL
        _WIN_API = (k32, psapi, PMC)
    return _WIN_API


def _win_proc_mem(pid: int) -> tuple[float | None, float | None]:
    k32, psapi, PMC = _win_api()
    h = k32.OpenProcess(0x1000 | 0x0010, False, pid)                        # QUERY_LIMITED_INFORMATION | VM_READ
    if not h:
        return None, None
    try:
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return round(pmc.WorkingSetSize / 2**20, 1), round(pmc.PeakWorkingSetSize / 2**20, 1)
        return None, None
    finally:
        k32.CloseHandle(h)


def _proc_mem(pid: int) -> tuple[float | None, float | None]:
    """(rss_mb, peak_mb) of one process; (None, None) when the platform does not tell (never a guess)."""
    try:
        if sys.platform == "win32":
            return _win_proc_mem(int(pid))
        rss = peak = None
        with open(f"/proc/{int(pid)}/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = round(float(line.split()[1]) / 1024, 1)
                elif line.startswith("VmHWM:"):
                    peak = round(float(line.split()[1]) / 1024, 1)
        return rss, peak
    except Exception:  # noqa: BLE001
        return None, None


class Governor:
    def __init__(self, cfg_store, log_=None, *, memory=sysres.memory, proc_mem=_proc_mem, clock=time.monotonic):
        self.cfg_store, self.applog, self._memory, self._proc_mem, self.clock = cfg_store, log_, memory, proc_mem, clock
        self._lock = threading.RLock()
        self.sources: dict[str, dict] = {}          # name -> {"pid": callable, "kind": heavy|light|training|bot, "release": callable|None, "idle": callable}
        self.peaks: dict[str, float] = {}
        self.timings: dict[str, list[float]] = {}
        self.loads: dict[str, list[float]] = {}
        self.counters = {"admitted": 0, "refused": 0, "released": 0, "heavy_waits": 0, "training_refused": 0}
        self.events: list[dict] = []
        self.last: dict | None = None
        self._slot_n = None
        self._slot = threading.BoundedSemaphore(1)
        self._slot_holder: str | None = None
        self._stop = threading.Event()
        self.training: dict[str, str] = {}          # job name -> kind

    # ------------------------------------------------------------------ profile
    def profile_name(self) -> str:
        try:
            return self.cfg_store.get().resources.profile
        except Exception:  # noqa: BLE001
            return "LOW_MEMORY_16GB"

    AUTO_CAPPED = ("AUTO", "LOW_MEMORY_16GB", "BALANCED")      # 1.42.4: these never use more than the computer's RAM allows

    def effective_name(self) -> str:
        """The profile actually applied: AUTO / LOW_MEMORY_16GB / BALANCED are lowered to LOW_MEMORY_12GB or LOW_MEMORY_8GB on a computer
        with <= 14 / <= 10 GB of RAM (measured total; unknown total -> the configured profile, AUTO -> LOW_MEMORY_16GB)."""
        name = self.profile_name()
        if name not in self.AUTO_CAPPED:
            return name
        try:
            total = (self._memory() or {}).get("total_mb")
        except Exception:  # noqa: BLE001
            total = None
        if total:
            if total <= 10 * 1024:
                return "LOW_MEMORY_8GB"
            if total <= 14 * 1024:
                return "LOW_MEMORY_12GB"
        return "LOW_MEMORY_16GB" if name == "AUTO" else name

    def profile(self) -> dict:
        name = self.effective_name()
        ps = profiles()
        if name == "MANUAL":
            try:
                manual = dict(self.cfg_store.get().resources.manual or {})
            except Exception:  # noqa: BLE001
                manual = {}
            return {**ps["LOW_MEMORY_16GB"], **{k: v for k, v in manual.items() if k in PROFILE_KEYS}}
        return ps.get(name, ps["LOW_MEMORY_16GB"])

    def threads_for(self, mid: str) -> int:
        p = self.profile()
        return int(p["threads_light"] if mid in LIGHT else p["threads_heavy"])

    # ------------------------------------------------------------------ registration
    def register(self, name: str, kind: str, pid, release=None, idle=None) -> None:
        """pid: callable -> int | None (the process may come and go); release(): stop the process (it restarts on demand); idle(): seconds."""
        with self._lock:
            self.sources[name] = {"pid": pid, "kind": kind, "release": release, "idle": idle}

    # ------------------------------------------------------------------ measurement
    def sample(self) -> dict:
        mem = self._memory() or {}
        procs = {}
        total_pmw = 0.0
        known = True
        for name, src in list(self.sources.items()):
            try:
                pid = src["pid"]()
            except Exception:  # noqa: BLE001
                pid = None
            if not pid:
                procs[name] = {"kind": src["kind"], "running": False, "rss_mb": None, "peak_mb": self.peaks.get(name)}
                continue
            rss, peak = self._proc_mem(pid)
            if rss is None:
                known = False
            else:
                total_pmw += rss
            if peak is not None or rss is not None:
                self.peaks[name] = max(self.peaks.get(name) or 0.0, peak or 0.0, rss or 0.0)
            procs[name] = {"kind": src["kind"], "running": True, "pid": pid, "rss_mb": rss, "peak_mb": self.peaks.get(name)}
        used = mem.get("used_pct")
        total = mem.get("total_mb")
        avail = round(total * (100 - used) / 100) if (total and used is not None) else None
        p = self.profile()
        level = "OK"
        if used is not None:
            level = ("PAUSE_OPTIONAL" if used >= p["pause_optional_pct"] else "LIMIT_HEAVY" if used >= p["limit_heavy_pct"] else
                     "WARN" if used >= p["warn_pct"] else "OK")
        if known and total_pmw > p["budget_max_mb"] and LEVELS.index(level) < LEVELS.index("LIMIT_HEAVY"):
            level = "LIMIT_HEAVY"
        elif known and total_pmw > p["budget_preferred_mb"] and level == "OK":
            level = "WARN"
        if avail is not None and avail < p["reserve_os_mb"] * 0.5 and LEVELS.index(level) < LEVELS.index("LIMIT_HEAVY"):
            level = "LIMIT_HEAVY"                         # less than half of the Windows reserve is left
        out = {"level": level, "level_pl": LEVEL_PL[level], "system": {"total_mb": total, "used_pct": used, "available_mb": avail},
               "pmw_total_mb": round(total_pmw, 1) if known else None, "processes": procs, "profile": self.profile_name(),
               "measured_at": time.time()}
        prev = (self.last or {}).get("level")
        self.last = out
        if prev and prev != level:
            self._event("LEVEL", f"poziom pamięci {prev} → {level} (RAM {used} %, PMW {out['pmw_total_mb']} MB)")
        return out

    def level(self) -> str:
        """Fresh measurement for every decision (cheap: /proc or one WinAPI call per process) - never an old cached level."""
        return self.sample()["level"]

    # ------------------------------------------------------------------ admission + heavy slot
    def admit(self, model: str, *, loaded: bool, optional: bool = True) -> tuple[bool, str | None]:
        """May this model start an inference now? Returns (ok, reason). Never asked for market data, positions, risk or execution."""
        p = self.profile()
        if not p["auto_throttle"]:
            return True, None
        lv = self.level()
        if optional and lv == "PAUSE_OPTIONAL":
            return self._refuse(model, f"RAM ≥ {p['pause_optional_pct']:.0f} % – opcjonalne prognozy AI wstrzymane (Memory Governor)")
        allowed = p.get("heavy_allowed")
        if model in HEAVY and allowed is not None and model not in allowed:
            return self._refuse(model, f"profil {self.effective_name()}: model {model} nie jest uruchamiany (dozwolone ciężkie: {', '.join(allowed) or 'brak'})")
        if model in HEAVY and not loaded and p.get("max_resident_heavy"):
            self._make_room(model, int(p["max_resident_heavy"]))
        if model in HEAVY and not loaded and lv in ("LIMIT_HEAVY", "PAUSE_OPTIONAL"):
            return self._refuse(model, f"RAM ≥ {p['limit_heavy_pct']:.0f} % lub budżet PMW przekroczony – nowy ciężki model nie jest ładowany (Memory Governor)")
        self.counters["admitted"] += 1
        return True, None

    def _make_room(self, model: str, keep: int) -> list[str]:
        """Before a heavy model loads: release other RUNNING heavy processes that are not computing now (not the slot holder) so that at
        most `keep` heavy processes stay resident. They start again on demand (lazy loading)."""
        out = []
        running = []
        for name, src in list(self.sources.items()):
            if name == model or src["kind"] != "heavy" or not src.get("release"):
                continue
            try:
                pid = src["pid"]()
            except Exception:  # noqa: BLE001
                pid = None
            if pid:
                running.append((name, src))
        for name, src in running[:max(0, len(running) - keep + 1)]:
            if self._slot_holder == name:
                continue
            try:
                src["release"]()
                self.counters["released"] += 1
                out.append(name)
                self._event("RELEASED", f"{name}: zwolniony przed załadowaniem {model} (profil: max {keep} ciężki model w pamięci)")
            except Exception:  # noqa: BLE001
                pass
        return out

    def _refuse(self, model: str, reason: str) -> tuple[bool, str]:
        self.counters["refused"] += 1
        self._event("REFUSED", f"{model}: {reason}")
        return False, reason

    def _semaphore(self) -> threading.BoundedSemaphore:
        n = max(1, int(self.profile()["heavy_parallelism"]))
        if n != self._slot_n:
            self._slot_n, self._slot = n, threading.BoundedSemaphore(n)
        return self._slot

    @contextmanager
    def heavy(self, model: str, timeout: float = 600.0):
        """Shared slot for heavy loading / inference (Kronos, Chronos-2) across services. Light models do not take it."""
        if model not in HEAVY:
            yield True
            return
        sem = self._semaphore()
        t0 = self.clock()
        got = sem.acquire(timeout=0)
        if not got:
            self.counters["heavy_waits"] += 1
            got = sem.acquire(timeout=timeout)
        try:
            self._slot_holder = model if got else self._slot_holder
            yield got
        finally:
            if got:
                self._slot_holder = None
                sem.release()
            waited = self.clock() - t0
            if waited > 1.0:
                self._event("WAIT", f"{model} czekał {waited:.1f} s na wolny slot ciężkiej inferencji")

    # ------------------------------------------------------------------ statistics
    def record(self, model: str, ms: float | None = None, load_ms: float | None = None) -> None:
        with self._lock:
            if ms is not None:
                self.timings.setdefault(model, []).append(float(ms))
                self.timings[model] = self.timings[model][-500:]
            if load_ms is not None:
                self.loads.setdefault(model, []).append(float(load_ms))
                self.loads[model] = self.loads[model][-20:]

    @staticmethod
    def _pct(xs: list[float]) -> dict:
        xs = sorted(xs)
        if not xs:
            return {"n": 0}
        pick = lambda q: round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 2)  # noqa: E731
        return {"n": len(xs), "p50_ms": pick(0.5), "p95_ms": pick(0.95), "max_ms": round(xs[-1], 2)}

    def _event(self, kind: str, msg: str) -> None:
        self.events = (self.events + [{"at": time.time(), "kind": kind, "message": msg}])[-100:]
        if self.applog is not None and kind in ("LEVEL", "RELEASED", "TRAINING_REFUSED"):
            try:
                self.applog.info("RESOURCES", kind, msg)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ release of idle heavy processes
    def maintain(self) -> list[str]:
        """Called periodically: release heavy model processes that are idle - ECO after idle_release_s, any profile under pressure (>= WARN)
        after 120 s idle. Light models and running work are never released; nothing is released in a loop (idle time resets on use)."""
        p = self.profile()
        snap = self.sample()
        out = []
        pressure = LEVELS.index(snap["level"]) >= LEVELS.index("WARN") and p["release_on_pressure"]
        for name, src in list(self.sources.items()):
            if src["kind"] != "heavy" or not src.get("release") or not snap["processes"].get(name, {}).get("running"):
                continue
            try:
                idle = float(src["idle"]()) if src.get("idle") else 0.0
            except Exception:  # noqa: BLE001
                idle = 0.0
            limit = 120.0 if pressure else p["idle_release_s"]
            if limit is not None and idle >= limit and self._slot_holder != name:
                try:
                    src["release"]()
                    self.counters["released"] += 1
                    out.append(name)
                    self._event("RELEASED", f"{name}: proces zwolniony po {idle:.0f} s bezczynności ({'presja pamięci' if pressure else 'profil'}) – "
                                            "zostanie uruchomiony przy następnej potrzebnej prognozie")
                except Exception:  # noqa: BLE001
                    pass
        return out

    def start(self, every: float = 15.0) -> None:
        def loop():
            while not self._stop.is_set():
                try:
                    self.maintain()
                except Exception:  # noqa: BLE001 - monitoring never affects the bot
                    pass
                self._stop.wait(every)
        threading.Thread(target=loop, name="pmw-governor", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ training gate
    def admit_training(self, name: str, kind: str, *, trading_active: bool, force: bool = False) -> tuple[bool, str | None]:
        p = self.profile()
        heavy_now = [n for n, k in self.training.items() if k == "heavy"]
        if heavy_now:
            self.counters["training_refused"] += 1
            return False, f"trwa inny trening ({', '.join(heavy_now)}) – na komputerze 16 GB treningi nie są uruchamiane równolegle"
        if trading_active and not p["background_training"] and not force:
            self.counters["training_refused"] += 1
            return False, "aktywny handel AUTO – trening w tle wyłączony w profilu (uruchom świadomie z potwierdzeniem albo w trybie SIGNALS/PAPER)"
        if self.level() in ("LIMIT_HEAVY", "PAUSE_OPTIONAL"):
            self.counters["training_refused"] += 1
            return False, f"za mało pamięci ({self.level()}) – trening wstrzymany"
        self.training[name] = kind
        return True, None

    def training_done(self, name: str) -> None:
        self.training.pop(name, None)

    # ------------------------------------------------------------------ view
    def public(self) -> dict:
        snap = self.sample()
        p = self.profile()
        eff = self.effective_name()
        return {"version": "PMW-GOV-1", **snap, "profile_pl": PROFILE_PL.get(self.profile_name()), "settings": p, "effective_profile": eff,
                "effective_profile_pl": PROFILE_PL.get(eff),
                "profiles": {k: {"label": PROFILE_PL[k], "settings": v} for k, v in profiles().items()} | {"AUTO": {"label": PROFILE_PL["AUTO"]}, "MANUAL": {"label": PROFILE_PL["MANUAL"]}},
                "cpu_pct": sysres.cpu_percent(), "cpu_count": _cores(),
                "inference": {k: self._pct(v) for k, v in self.timings.items()}, "load": {k: self._pct(v) for k, v in self.loads.items()},
                "heavy_slot": {"parallelism": p["heavy_parallelism"], "holder": self._slot_holder}, "counters": dict(self.counters),
                "training": dict(self.training), "events": self.events[-20:],
                "rule": "Memory Governor reguluje wyłącznie opcjonalne prognozy AI i trening – dane rynkowe, pozycje, ryzyko i wykonanie nie czekają "
                        "na model. Prognoza wstrzymana = stan niedostępny z powodem (nigdy głos neutralny)."}
