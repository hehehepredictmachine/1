"""Paths, bar conversion, model registry (atomic) and run logging for the candle runtime."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYMBOL = "XAUUSD-"


def data_dir() -> Path:
    return Path(os.environ.get("MASTERQUO_DATA_DIR") or (ROOT / "data"))


def instrument() -> str:
    """Instrument of this process (MQ_INSTRUMENT, default XAUUSD). XAUUSD keeps data/forecast and data/scalp."""
    import mq_instruments
    return mq_instruments.current()


def use_instrument(inst: str | None, symbol: str | None = None) -> str:
    """Selects the instrument space of this process and registers its exact broker symbol for gold_candles.Config."""
    import mq_instruments
    from gold_candles import data as gd
    inst = mq_instruments.current(inst)
    os.environ["MQ_INSTRUMENT"] = inst
    if symbol and inst != "XAUUSD":
        gd.REGISTERED_SYMBOLS.add(symbol)
    return inst


def make_config(symbol: str, tick_size: float, inst: str | None = None, grid_step: float | None = None):
    """gold_candles Config of the instrument profile (XAUUSD: reference defaults, unchanged contract hash)."""
    import mq_instruments
    from gold_candles.data import Config
    inst = use_instrument(inst, symbol)
    if inst == "XAUUSD":
        return Config(symbol=symbol, tick_size=tick_size)
    prof = mq_instruments.profile(inst)["forecast"]
    return Config(symbol=symbol, tick_size=tick_size, grid_step=float(grid_step or prof["grid_step"]), neutral_atr=float(prof["neutral_atr"]))


def forecast_dir() -> Path:
    import mq_instruments
    return mq_instruments.root("forecast")


def relocated(path: str | Path, root: Path) -> Path:
    """Registry paths are absolute; after the whole project folder was moved, the same artefact is found under the current
    data root (…/runs/<run>/<file>). The checksum check that follows still decides whether it may be used."""
    p = Path(path)
    if p.exists() or "runs" not in p.parts:
        return p
    i = len(p.parts) - 1 - p.parts[::-1].index("runs")
    q = root.joinpath(*p.parts[i:])
    return q if q.exists() else p


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_fingerprint() -> dict:
    """git commit (if available) + sha256 of every file of gold_candles and this runtime."""
    files = sorted(list((ROOT / "backend" / "gold_candles").glob("*.py")) + list((ROOT / "backend" / "gold_candles_runtime").glob("*.py")))
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    sha = None
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return {"git_commit": sha, "code_sha256": h.hexdigest(), "files": [f.name for f in files]}


def versions() -> dict:
    import numpy
    import pandas
    import sklearn
    return {"python": platform.python_version(), "numpy": numpy.__version__, "pandas": pandas.__version__, "scikit_learn": sklearn.__version__,
            "platform": platform.platform()}


def write_json_atomic(path: Path, payload) -> None:
    from gold_candles.data import clean_json
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(clean_json(payload), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def bars_frame(rows: list[dict], minutes: int, as_of, symbol: str = SYMBOL):
    """Bot bar JSON (open_utc, o, h, l, c, tv) -> validated gold_candles frame. Only closed bars are passed by the bot;
    validate_bars additionally drops anything not closed at as_of."""
    import pandas as pd
    from gold_candles.data import validate_bars
    frame = pd.DataFrame([{"time_open_utc": r["open_utc"], "open": r["o"], "high": r["h"], "low": r["l"], "close": r["c"],
                           "tick_volume": r.get("tv")} for r in rows if r.get("open_utc")])
    return validate_bars(frame, minutes, as_of, symbol)


# ------------------------------------------------------------------ registry
def registry_path() -> Path:
    return forecast_dir() / "registry.json"


def read_registry() -> dict:
    p = registry_path()
    if not p.exists():
        return {"schema": "masterquo-forecast-registry-1", "active": None, "history": [], "runs": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": "masterquo-forecast-registry-1", "active": None, "history": [], "runs": {}, "error": "REGISTRY_UNREADABLE"}


def write_registry(reg: dict) -> None:
    write_json_atomic(registry_path(), reg)


def activatable(entry: dict, current_contract: str | None = None) -> tuple[bool, str | None]:
    if entry.get("data_kind") != "REAL_USER_DATA" and not (entry.get("data_kind") == "SYNTHETIC_TEST" and os.environ.get("MQ_FORECAST_TEST_ALLOW_SYNTHETIC") == "1"):
        return False, "NOT_REAL_USER_DATA"            # the override exists only for automated tests of the code path
    if sorted(entry.get("horizons_trained") or []) != ["1", "3", "6"]:
        return False, "NOT_ALL_HORIZONS_TRAINED"
    model = relocated(entry["model_path"], forecast_dir())
    if not model.exists() or sha256_file(model) != entry.get("artifact_sha256"):
        return False, "ARTIFACT_MISSING_OR_CHECKSUM_MISMATCH"
    if current_contract and entry.get("contract_hash") != current_contract:
        return False, "CONTRACT_MISMATCH"
    return True, None


def activate(run_id: str, *, reason: str) -> dict:
    """Atomic switch of the active observational model; the previous one is kept for rollback."""
    reg = read_registry()
    entry = reg["runs"].get(run_id)
    if not entry:
        raise SystemExit(f"[BLAD] Nieznany run_id {run_id}")
    ok, why = activatable(entry, make_config(entry["symbol"], entry["tick_size"], entry.get("instrument"), entry.get("grid_step")).contract_hash())
    if not ok:
        raise SystemExit(f"[BLAD] Model {run_id} nie może być aktywny: {why}")
    if reg.get("active") and reg["active"] != run_id:
        reg["history"].append(reg["active"])
    reg["active"] = run_id
    reg.setdefault("events", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": "ACTIVATE", "run_id": run_id, "reason": reason})
    write_registry(reg)
    return reg


class RunLog:
    """JSON-lines log of a run: time, step, message, elapsed, peak memory."""
    def __init__(self, path: Path):
        self.path = path
        self.t0 = time.monotonic()
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, step: str, msg: str, **kw) -> None:
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_s": round(time.monotonic() - self.t0, 2),
               "peak_rss_mb": peak_rss_mb(), "step": step, "msg": msg, **kw}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        print(f"[{rec['elapsed_s']:>8.1f}s] {step}: {msg}", flush=True)


def peak_rss_mb() -> float | None:
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / 1024 / (1024 if sys.platform == "darwin" else 1), 1)
    except ImportError:                       # Windows
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
            return round(pmc.PeakWorkingSetSize / 1024 / 1024, 1)
        except Exception:
            return None
