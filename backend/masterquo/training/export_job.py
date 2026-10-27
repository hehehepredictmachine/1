"""Panel "Eksportuj dane z MT5": one export job at a time, run as its own process (`training export`, read only - its MT5 connection
is wrapped so that order functions raise), never inside the bot process and never blocking the panel or the MT5 worker of the bot.

The job file names the export folder; progress, the result and failures come from that folder's EXPORT_STATUS.json (the same file the
command writes in the console), the console output goes to export.log in the folder. Cancel terminates the process and marks the
export CANCELLED; starting it again with the same choice continues from the chunks already fetched."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import paths
from . import core

TFS = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
INSTR = ("XAUUSD", "BTC")
_PROCS: dict[int, subprocess.Popen] = {}             # children started by this server (poll() also reaps them - no zombie "alive")


def _alive(pid: int) -> bool:
    p = _PROCS.get(pid)
    if p is not None:
        return p.poll() is None
    return core._pid_alive(pid)


def _job_path() -> Path:
    return core.training_dir() / "export_job.json"


def _job() -> dict | None:
    try:
        return json.loads(_job_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _date(s) -> str | None:
    if s in (None, ""):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z?)?", str(s)):
        raise ValueError("BAD_DATE")
    return str(s)


def start(body: dict, *, demo: bool = False, default_symbol=None) -> dict:
    inst = str(body.get("instrument") or "").upper()
    if inst not in INSTR:
        raise ValueError("BAD_INSTRUMENT")
    sym = str(body.get("symbol") or (default_symbol(inst) if default_symbol else "") or "").strip()
    if not sym or len(sym) > 64 or any(c in sym for c in "\\/\"'\r\n"):
        raise ValueError("BAD_SYMBOL")
    tfs = [t for t in (body.get("timeframes") or ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]) if t in TFS]
    if not tfs:
        raise ValueError("NO_TIMEFRAMES")
    d_from, d_to = _date(body.get("from")), _date(body.get("to"))
    months = int(body.get("months") or 12)
    if not d_from and not 1 <= months <= 36:
        raise ValueError("BAD_MONTHS")
    ticks = float(body.get("ticks_days") or 0)
    if not 0 <= ticks <= 31:
        raise ValueError("BAD_TICK_DAYS")
    cur = status()
    if cur.get("running"):
        return {"started": False, "reason": "EXPORT_ALREADY_RUNNING", "job": cur}
    from .panel import lock_holder
    held = lock_holder()
    if held and held.get("alive"):
        return {"started": False, "reason": f"TRAINING_RUNNING:{held.get('run_id')}"}
    if body.get("resume_dir"):                        # continue a cancelled / failed export into the same folder
        out = Path(body["resume_dir"]).resolve()
        if paths.data_dir().resolve() not in out.parents:
            raise ValueError("BAD_DIR")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = paths.data_dir() / "training" / "datasets" / inst / f"EXP-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "masterquo", "training", "export", "--instrument", inst, "--symbol", sym, "--out", str(out),
           "--tfs", ",".join(tfs), "--ticks-days", str(ticks)]
    cmd += ["--from", d_from] + (["--to", d_to] if d_to else []) if d_from else ["--months", str(months)]
    if demo:
        cmd.append("--synthetic")
    log = open(out / "export.log", "a", encoding="utf-8")
    kw = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)} if os.name == "nt" \
        else {"start_new_session": True}
    p = subprocess.Popen(cmd, cwd=str(paths.ROOT_DIR / "backend"), env=dict(os.environ, PYTHONIOENCODING="utf-8"), stdout=log,
                         stderr=subprocess.STDOUT, **kw)
    _PROCS[p.pid] = p
    core.write_json_atomic(_job_path(), {"pid": p.pid, "out": str(out), "instrument": inst, "symbol": sym, "timeframes": tfs, "from": d_from,
                                         "to": d_to, "months": None if d_from else months, "ticks_days": ticks, "started_at": core.now(),
                                         "synthetic": bool(demo)})
    return {"started": True, "out": str(out), "pid": p.pid}


def status() -> dict:
    from ..forecast.export import dataset_state, read_status
    j = _job()
    if not j:
        return {"job": None, "running": False}
    out = Path(j["out"])
    alive = _alive(int(j.get("pid") or 0))
    st = read_status(out) or {}
    if st.get("status") in ("COMPLETE", "FAILED", "CANCELLED"):
        alive = alive and st.get("pid") != j.get("pid")                # the export said it ended: never shown as running
    ds = dataset_state(out)
    log_tail = ""
    try:
        txt = (out / "export.log").read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = "\n".join([x for x in txt if not x.startswith("[POSTEP]")][-25:])
    except OSError:
        pass
    state = ds["state"] if not (alive and ds["state"] in ("MISSING", "LEGACY_COMPLETE")) else "STARTING"
    if not alive and state in ("MISSING",):
        state = "FAILED"
    readiness = None
    try:
        readiness = json.loads((out / "MODEL_DATA_READINESS.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"job": j, "running": alive, "state": state, "usable": ds["usable"], "progress": st.get("progress"), "reason": st.get("reason"),
            "range_utc": st.get("range_utc"), "data_kind": st.get("data_kind"), "log_tail": log_tail, "readiness": readiness}


def cancel() -> dict:
    from ..forecast.export import STATUS_FILE, read_status
    j = _job()
    if not j:
        return {"ok": False, "reason": "NO_EXPORT"}
    pid = int(j.get("pid") or 0)
    if _alive(pid):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20)
            else:
                import signal
                os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass
        for _ in range(40):
            if not _alive(pid):
                break
            time.sleep(0.25)
    out = Path(j["out"])
    st = read_status(out)
    if st and st.get("status") == "IN_PROGRESS":
        st.update(status="CANCELLED", reason="przerwane w panelu – ponowny eksport z tym samym wyborem wznowi pobrane partie",
                  updated_at=core.now())
        core.write_json_atomic(out / STATUS_FILE, st)
    return {"ok": True, "out": str(out)}


def datasets(inst: str) -> list[dict]:
    """Exports of one instrument (newest first) with their state - the panel lets the user pick one for training."""
    from ..forecast.export import dataset_state, read_status
    base = paths.data_dir() / "training" / "datasets" / inst
    out = []
    for d in sorted((x for x in base.glob("*") if x.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        ds = dataset_state(d)
        if ds["state"] == "MISSING":
            continue
        meta = None
        try:
            meta = json.loads((d / "source_metadata.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        st = read_status(d) or {}
        out.append({"dir": str(d), "name": d.name, "state": ds["state"], "usable": ds["usable"], "symbol": (meta or {}).get("symbol") or
                    (st.get("request") or {}).get("symbol"), "range_utc": (meta or {}).get("range_utc") or st.get("range_utc"),
                    "timeframes": (meta or {}).get("timeframes") or (st.get("request") or {}).get("timeframes"),
                    "data_kind": (meta or {}).get("data_kind"), "ticks": bool((meta or {}).get("ticks")), "reason": ds.get("reason")})
    return out
