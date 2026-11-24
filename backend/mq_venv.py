"""1.42.2: repair of the model environments (.venv_*) after the program folder was MOVED or COPIED to another place / user.

A Python venv stores the ABSOLUTE path of its base interpreter in <venv>/pyvenv.cfg ("home", "executable", "command"). On Windows
<venv>\\Scripts\\python.exe is only a launcher that reads that path - after moving the folder (e.g. C:\\Users\\A\\Desktop\\Pepe\\... ->
C:\\Users\\B\\Desktop\\...) every call ends with "did not find executable at '<old path>\\runtime\\python\\python.exe'".

check(venv) -> (state, detail): OK | MISSING | MOVED (base interpreter of pyvenv.cfg does not exist) | BROKEN (no pyvenv.cfg / no python)
repair(venv, base):
  * MOVED with the SAME Python major.minor as `base` -> pyvenv.cfg is re-pointed to `base` (home / executable / command); the
    installed packages stay (no download). The result is checked by running the venv interpreter.
  * anything else that does not run -> the folder is renamed to <venv>_old_<time> (never deleted) and the caller creates a new venv.
Standard library only (used by the bot, the .bat installers and tools/*_setup.py).
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

VENVS = (".venv_kronos", ".venv_chronos2", ".venv_granite", ".venv_tirex2", ".venv_tabicl", ".venv_candles", ".venv_deep", ".venv_sdformer",
         ".venv_train")


def vpy(venv: Path) -> Path:
    venv = Path(venv)
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def read_cfg(venv: Path) -> dict:
    out = {}
    try:
        for line in (Path(venv) / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip().lower()] = v.strip()
    except OSError:
        pass
    return out


def _base_in(home: str) -> Path | None:
    if not home:
        return None
    for n in (("python.exe",) if os.name == "nt" else ("python3", "python")):
        p = Path(home) / n
        if p.is_file():
            return p
    return None


def check(venv: Path) -> tuple[str, str | None]:
    venv = Path(venv)
    if not venv.exists():
        return "MISSING", None
    cfg = read_cfg(venv)
    if not cfg:
        return "BROKEN", "brak pyvenv.cfg"
    if not vpy(venv).is_file():
        return "BROKEN", f"brak {vpy(venv).name}"
    if _base_in(cfg.get("home", "")) is None:
        return "MOVED", f"Python bazowy z pyvenv.cfg nie istnieje: {cfg.get('home')}"
    return "OK", None


def _version(py: str) -> tuple[int, int] | None:
    try:
        r = subprocess.run([py, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"], capture_output=True, text=True, timeout=60)
        m = re.match(r"(\d+)\.(\d+)", r.stdout.strip())
        return (int(m.group(1)), int(m.group(2))) if r.returncode == 0 and m else None
    except Exception:  # noqa: BLE001
        return None


def runs(venv: Path) -> bool:
    try:
        return subprocess.run([str(vpy(venv)), "-c", "import sys"], capture_output=True, timeout=60).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def retarget(venv: Path, base: str) -> None:
    """Re-point pyvenv.cfg to `base` (keeps every other line, e.g. include-system-site-packages, version)."""
    p = Path(venv) / "pyvenv.cfg"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    home = str(Path(base).parent)
    new, seen = [], set()
    for line in lines:
        k = line.split("=", 1)[0].strip().lower() if "=" in line else ""
        if k == "home":
            line = f"home = {home}"
        elif k == "executable":
            line = f"executable = {base}"
        elif k == "command":
            line = f"command = {base} -m venv {Path(venv)}"
        seen.add(k)
        new.append(line)
    if "home" not in seen:
        new.insert(0, f"home = {home}")
    bak = p.with_name("pyvenv.cfg.moved_bak")
    if not bak.exists():
        bak.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp = p.with_name("pyvenv.cfg.tmp")
    tmp.write_text("\n".join(new) + "\n", encoding="utf-8")
    tmp.replace(p)


def set_aside(venv: Path) -> Path:
    dst = Path(venv).with_name(f"{Path(venv).name}_old_{time.strftime('%Y%m%d_%H%M%S')}")
    os.replace(venv, dst)
    return dst


def repair(venv: Path, base: str | None, say=None, *, allow_set_aside: bool = True) -> dict:
    """Returns {"state": OK|MISSING|REPAIRED|SET_ASIDE|FAILED, "detail"}. MISSING / SET_ASIDE: the caller creates a new venv."""
    say = say or (lambda m: None)
    venv = Path(venv)
    st, why = check(venv)
    if st == "MISSING":
        return {"state": "MISSING", "detail": None}
    if st == "OK" and runs(venv):
        return {"state": "OK", "detail": None}
    if st == "MOVED" and base:
        want = _version(base)
        have = re.match(r"(\d+)\.(\d+)", read_cfg(venv).get("version", "") or read_cfg(venv).get("version_info", ""))
        if want and have and (int(have.group(1)), int(have.group(2))) == want:
            say(f"{venv.name}: folder programu przeniesiony ({why}) – przepinam środowisko na {base} (pakiety zostają, bez pobierania)")
            try:
                retarget(venv, base)
            except OSError as exc:
                why = f"nie można zapisać pyvenv.cfg: {exc}"
            else:
                if runs(venv):
                    return {"state": "REPAIRED", "detail": why}
                why = "po przepięciu interpreter środowiska nie uruchamia się"
        else:
            why = f"{why}; wersja Pythona środowiska {have.group(0) if have else '?'} ≠ {'%d.%d' % want if want else '?'}"
    if not allow_set_aside:                          # the running bot only re-points; recreating is the installer's job
        return {"state": "FAILED", "detail": why}
    try:
        old = set_aside(venv)
    except OSError as exc:
        return {"state": "FAILED", "detail": f"{why}; nie można odsunąć {venv}: {exc} – zamknij bota i usuń folder ręcznie"}
    say(f"{venv.name}: środowisko niesprawne ({why}) – odsunięte do {old.name}, zostanie utworzone od nowa")
    return {"state": "SET_ASIDE", "detail": why}


def repair_all(root: Path, base: str | None, say=None, *, allow_set_aside: bool = False) -> dict:
    return {v: repair(Path(root) / v, base, say, allow_set_aside=allow_set_aside) for v in VENVS if (Path(root) / v).exists()}
