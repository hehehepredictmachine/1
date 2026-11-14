"""Installer of the isolated .venv_deep (stdlib only) - used by 34_DEEP_INSTALUJ.bat.

  python tools/deep_setup.py --root <folder programu> [--python EXE] [--log F]

Steps ("[DEEP-SETUP] [k/4] ..."; the last line is "RESULT <json>"):
  1. Python 3.13 / 3.12 x64: runtime\\python from the Windows package first, then --python, then this interpreter.
  2. .venv_deep next to the program (created once; the bot's .venv and .venv_kronos are never modified).
  3. Packages: requirements/requirements-deep-win.txt with --require-hashes --only-binary=:all: (torch CPU from PyPI, gymnasium,
     stable-baselines3). Other systems: the same versions without hashes (development only - stated in the log).
  4. Check: python -m deep_runtime.worker health (versions of torch / gymnasium / SB3, CPU / CUDA).
Nothing here touches MetaTrader 5, account data or the bot's configuration."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

LOG = {"f": None}


def emit(line: str) -> None:
    print(line, flush=True)
    if LOG["f"]:
        LOG["f"].write(line + "\n")
        LOG["f"].flush()


def say(step: int, msg: str) -> None:
    emit(f"[DEEP-SETUP] [{step}/4] {msg}")


def result(ok: bool, step: int, code: str | None = None, **kw) -> int:
    emit("RESULT " + json.dumps({"ok": ok, "step": step, "code": code, **kw}, ensure_ascii=False))
    return 0 if ok else 1


def run(cmd, env=None) -> tuple[int, str]:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kronos_setup as KS  # same clean child environment (the bot's PYTHONPATH never reaches pip in .venv_deep)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=KS.child_env(env))
    last = ""
    for ln in p.stdout:
        ln = ln.rstrip()
        if ln:
            last = ln
            emit("    " + ln)
    return p.wait(), last


def py_ok(exe: str) -> bool:
    try:
        out = subprocess.run([exe, "-c", "import sys,struct;print(sys.version_info[0],sys.version_info[1],struct.calcsize('P')*8)"],
                             capture_output=True, text=True, timeout=30).stdout.split()
        return out[0] == "3" and out[1] in ("12", "13") and out[2] == "64"
    except Exception:  # noqa: BLE001
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--python")
    ap.add_argument("--log")
    a = ap.parse_args(argv)
    if a.log:
        Path(a.log).parent.mkdir(parents=True, exist_ok=True)
        LOG["f"] = open(a.log, "a", encoding="utf-8")
    root = Path(a.root).resolve()
    win = os.name == "nt"
    base = next((c for c in (str(root / "runtime" / "python" / "python.exe"), a.python, getattr(sys, "_base_executable", None), sys.executable)
                 if c and Path(c).is_file() and py_ok(c)), None)
    if not base:
        return result(False, 1, "NO_PYTHON", error="brak Python 3.13/3.12 x64")
    say(1, f"Python do środowiska: {base}")
    venv = root / ".venv_deep"
    vpy = venv / ("Scripts/python.exe" if win else "bin/python")
    if not vpy.is_file():
        say(2, f"tworzę {venv}")
        rc, last = run([base, "-m", "venv", str(venv)])
        if rc != 0 or not vpy.is_file():
            return result(False, 2, "VENV", error=last)
    else:
        say(2, f"{venv} istnieje – używam")
    req = root / "requirements" / "requirements-deep-win.txt"
    pip = [str(vpy), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--only-binary=:all:"]
    if win:
        say(3, "instaluję PyTorch (CPU), Gymnasium, Stable-Baselines3 – tylko pakiety z sumami SHA-256 (~250 MB)")
        rc, last = run(pip + ["--require-hashes", "-r", str(req)])
    else:
        specs = re.findall(r"^([A-Za-z0-9_.\-]+==[^\s\\]+)", req.read_text(encoding="utf-8"), re.M)
        say(3, "system inny niż Windows: te same wersje BEZ sum (tylko środowisko deweloperskie)")
        rc, last = run(pip + specs)
    if rc != 0:
        return result(False, 3, "PIP", error=last)
    env = dict(os.environ, PYTHONPATH=str(root / "backend"), PYTHONIOENCODING="utf-8")
    with tempfile.TemporaryDirectory() as td:
        rq, rs = Path(td) / "q.json", Path(td) / "r.json"
        rq.write_text(json.dumps({"op": "health"}), encoding="utf-8")
        rc, last = run([str(vpy), "-m", "deep_runtime.worker", str(rq), str(rs)], env)
        h = json.loads(rs.read_text(encoding="utf-8")) if rs.exists() else {"ok": False, "error": last}
    say(4, f"sprawdzenie: {h}")
    if not h.get("ok") or not h.get("torch") or not h.get("stable_baselines3"):
        return result(False, 4, "HEALTH", health=h)
    return result(True, 4, None, venv=str(venv), python=str(vpy), health=h)


if __name__ == "__main__":
    sys.exit(main())
