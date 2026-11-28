"""API routes: Studio.

register(app, ctx): Pepe Data & Training Studio (status, uruchomienie, import)
    (5 routes; create_app before the split, 7ba7ab0: lines 2555-2665)

The handlers are the ones create_app defined before the split (Etap 4 krok B, docs/arch146/ETAP2_PROJEKT.md §3 / §5):
same function names, signatures, decorators, Pydantic models, error codes and body - the block of create_app is copied
verbatim, the only edit is one more dot in a relative import (the package is one level deeper). The create_app locals the
block used (rt, helpers, handlers called by name) are bound from ctx at the top of the function under the same names;
registration order: api/routes/__init__.REGISTRATION.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import Body, HTTPException

from ... import paths

STUDIO_LAUNCH_WAIT_S = 5.0     # 1.46 arch (I0846): how long POST /api/v1/studio/launch checks that Studio really started


def register(app, ctx) -> None:
    """Block of create_app before the split (7ba7ab0), lines 2555-2665: 5 routes."""
    rt = ctx.rt

    # ---------------------------------------------------------------- Pepe Data & Training Studio: status + launch from the bot menu (1.33)
    def _studio_dirs() -> tuple[Path, Path]:
        bot = paths.data_dir()
        return bot, (bot.parent / "data_studio") if bot.name == "data" else (bot / "studio_data")

    def _studio_port(sdir: Path) -> int:
        try:
            return int(json.loads((sdir / "settings.json").read_text(encoding="utf-8")).get("port") or 8780)
        except (OSError, ValueError, TypeError):
            return 8780

    def _studio_probe() -> dict:
        import urllib.request
        _, sdir = _studio_dirs()
        port = _studio_port(sdir)
        out = {"port": port, "url": f"http://127.0.0.1:{port}/", "running": False, "health": None}
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/studio/health", timeout=0.8) as r:
                h = json.loads(r.read().decode("utf-8"))
            out.update(running=h.get("app") == "PepeTrainingStudio", health={k: h.get(k) for k in ("app", "studio", "version", "orders")})
        except Exception:  # noqa: BLE001 - not running / port taken by something else
            pass
        exe = os.environ.get("PMW_DESKTOP_EXE")
        st_exe = Path(exe).with_name("PepeTrainingStudio.exe") if exe else None
        out["launcher"] = "EXE" if st_exe is not None and st_exe.exists() else "PYTHON"
        return out

    @app.get("/api/v1/studio/status")
    def studio_status():
        return _studio_probe()

    @app.post("/api/v1/studio/launch")
    def studio_launch():
        """Start Pepe Training Studio as a SEPARATE process (never inside the bot). Already running -> its address."""
        import subprocess
        st = _studio_probe()
        if st["running"]:
            return {**st, "started": False, "note": "Studio już działa"}
        bot, sdir = _studio_dirs()
        sdir.mkdir(parents=True, exist_ok=True)
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)) if os.name == "nt" else 0
        # 1.46: Studio stayed in the engine's Job Object (KILL_ON_JOB_CLOSE) and was killed with every engine restart / app exit.
        # CREATE_BREAKAWAY_FROM_JOB takes it out (the desktop shell's job allows breakaway); a job without BREAKAWAY_OK refuses the flag,
        # then it starts as before (inside the job). Only Studio - the MT5 terminal start is not changed here.
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000) if os.name == "nt" else 0
        if st["launcher"] == "EXE":
            cmd, env = [str(Path(os.environ["PMW_DESKTOP_EXE"]).with_name("PepeTrainingStudio.exe"))], dict(os.environ)
        else:
            env = {k: v for k, v in os.environ.items() if k not in ("MASTERQUO_DATA_DIR",)}
            env.update(MQ_BOT_DATA_DIR=str(bot), MQ_STUDIO_DATA_DIR=str(sdir), MASTERQUO_DATA_DIR=str(sdir))
            cmd = [sys.executable, "-m", "masterquo", "studio", "--port", str(st["port"])]

        def start(fl: int):
            return subprocess.Popen(cmd, cwd=str(paths.BACKEND_DIR), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, creationflags=fl, start_new_session=os.name != "nt")
        try:
            try:
                p, broke_away = start(flags | breakaway), (True if breakaway else None)
            except OSError:
                if not breakaway:
                    raise
                p, broke_away = start(flags), False       # ERROR_ACCESS_DENIED: this job does not allow breakaway (any other error repeats)
        except OSError as exc:
            raise HTTPException(500, f"STUDIO_START_FAILED:{type(exc).__name__}") from None
        # 1.46 arch (I0846): started:true was returned right after Popen - an Studio that ended at once (e.g. the single-instance check
        # of the launcher) was reported as started. Wait up to STUDIO_LAUNCH_WAIT_S (this route is a sync def - a threadpool thread, the
        # event loop is not blocked): an exit before Studio answers -> started False, reason STUDIO_EXITED:<code>; alive but not yet
        # answering (first start) -> started True, starting True. Nothing is killed; the bot and MT5 are not touched.
        poll = getattr(p, "poll", None)
        rc, starting = None, True
        if callable(poll):
            import time as _time
            end = _time.monotonic() + STUDIO_LAUNCH_WAIT_S
            while True:
                if _studio_probe()["running"]:
                    starting = False
                    break
                rc = poll()
                if rc is not None or _time.monotonic() >= end:
                    break
                _time.sleep(0.5)
        if rc is not None and starting:
            rt.log.write("WARNING", "STUDIO", "LAUNCH_EXITED", f"Pepe Training Studio zakończyło się od razu (kod {rc}) – nie uruchomiono")
            return {**st, "started": False, "starting": False, "pid": p.pid, "job_breakaway": broke_away, "reason": f"STUDIO_EXITED:{rc}"}
        rt.log.info("STUDIO", "LAUNCH", f"Uruchomiono Pepe Training Studio ({st['launcher']}, pid {p.pid}, port {st['port']}"
                    + (", w zadaniu silnika – zamknie się razem z nim" if broke_away is False else "") + ")")
        return {**st, "started": True, "starting": starting, "pid": p.pid, "job_breakaway": broke_away}

    # ---------------------------------------------------------------- Pepe Data & Training Studio import (1.33) - candidates only
    @app.post("/api/v1/studio/import")
    def studio_import(body: dict = Body(...)):
        from ...studio import importer as _IM
        try:
            r = _IM.import_package(str(body.get("package") or ""))
        except (KeyError, TypeError, ValueError, OSError) as exc:      # 1.46: a package with a bad manifest / result file was a 500
            raise HTTPException(400, f"STUDIO_PACKAGE_INVALID: {type(exc).__name__}: {exc}"[:300]) from None
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r

    @app.get("/api/v1/studio/imports")
    def studio_imports():
        from ...studio import importer as _IM
        return {"items": _IM.history(), "startup_inbox": getattr(rt, "studio_imports", [])}

    @app.delete("/api/v1/studio/import/{import_id}")
    def studio_import_rollback(import_id: str):
        from ...studio import importer as _IM
        r = _IM.rollback(import_id)
        if not r.get("ok"):
            raise HTTPException(409, r.get("reason"))
        return r
