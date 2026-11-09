"""Kronos installer (stdlib only) - used by 33_KRONOS_INSTALUJ.bat and by the panel button "Zainstaluj model Kronos".

  python tools/kronos_setup.py --root <folder programu> --weights-dir <folder wag | auto> [--cuda cu126|cu128] [--status-file F] [--python EXE]

Steps (progress lines "[KRONOS-SETUP] [k/5] ..."; the last line is "RESULT <json>"):
  1. Python 3.13 / 3.12 x64 for the environment: runtime\\python from the Windows package first, then --python, then this interpreter.
  2. .venv_kronos next to the program (created once; the main .venv of the bot is never modified).
  3. Packages: requirements/requirements-kronos-win.txt with --require-hashes --only-binary=:all: (torch from PyPI = CPU build on
     Windows). --cuda: torch from the official PyTorch index for that CUDA variant (no hashes in our file - stated in the log),
     the rest still hash-checked. Other systems: same versions without hashes (development only).
  4. Weights: python -m kronos_runtime.install download (pinned revisions, files checked against the source metadata).
  5. Check: python -m kronos_runtime.install verify --reference (checksums offline, load once, short real forecast, upstream comparison).
Nothing here touches MetaTrader 5, account data or the bot's configuration.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TOTAL = 5
TORCH = "torch==2.14.1"


LOG = {"f": None}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(line: str) -> None:
    """Console + optional UTF-8 log file (--log) - the .bat checks the exit code, not the log."""
    try:
        print(line, flush=True)
    except UnicodeEncodeError:                     # old Windows console code page
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    if LOG["f"]:
        LOG["f"].write(line + "\n")
        LOG["f"].flush()


class Out:
    def __init__(self, status_file: str | None):
        self.status_file = status_file
        self.log: list[str] = []

    def say(self, step: int, msg: str, state: str = "RUNNING") -> None:
        line = f"[KRONOS-SETUP] [{step}/{TOTAL}] {msg}"
        emit(line)
        self.log = (self.log + [line])[-60:]
        if self.status_file:
            try:
                p = Path(self.status_file)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"state": state, "step": step, "total": TOTAL, "message": msg, "log": self.log, "updated_at": now()},
                                        ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass


def result(out: Out, step: int, ok: bool, code: str | None = None, **kw) -> int:
    out.say(step, "GOTOWE" if ok else f"BŁĄD {code}: {kw.get('error', '')}", state="DONE" if ok else "FAILED")
    emit("RESULT " + json.dumps({"ok": ok, "code": code, **kw}, ensure_ascii=False))
    return 0 if ok else 1


CHILD = {"result": None}
HINT = {"NETWORK": "brak połączenia z huggingface.co (internet, zapora albo proxy) – odblokuj huggingface.co i powtórz",
        "REVISION_NOT_FOUND": "przypięta rewizja nie istnieje w źródle", "REVISION_MISMATCH": "źródło zwróciło inną rewizję niż przypięta",
        "REPO_NOT_FOUND": "repozytorium modelu niedostępne", "FILE_MISSING": "brak wymaganego pliku w przypiętej rewizji",
        "CHECKSUM_MISMATCH": "plik niezgodny z sumą ze źródła – nic nie zostało zainstalowane",
        "MISSING_DEPENDENCY": "brak pakietu w .venv_kronos – powtórz instalację", "CHECKSUM": "pliki wag zmienione na dysku – zainstaluj ponownie",
        "INCOMPATIBLE": "model i tokenizer nie pasują do siebie", "NO_WEIGHTS": "brak zweryfikowanych wag"}


def run(cmd: list[str], out: Out, step: int, env: dict | None = None) -> tuple[int, str]:
    """Run a child process, stream its output (prefixed), return (rc, last line); the child's RESULT is kept in CHILD."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    last = ""
    CHILD["result"] = None
    for line in p.stdout:
        line = line.rstrip()
        if not line:
            continue
        last = line
        if line.startswith("RESULT "):
            emit(line.replace("RESULT ", "CHILD_RESULT ", 1))
            try:
                CHILD["result"] = json.loads(line[7:])
            except ValueError:
                pass
        else:
            emit("    " + line[-400:])
    return p.wait(), last


def child_error(last: str) -> tuple[str | None, str]:
    r = CHILD["result"] or {}
    code = r.get("code")
    msg = (r.get("error") or last or "")[:300]
    return code, (f"{HINT[code]}. " if code in HINT else "") + msg


def default_weights_dir(root: Path) -> Path:
    """Same folder as the bot uses: <data>/kronos/models, or weights_dir from <data>/kronos/settings.json (data = MASTERQUO_DATA_DIR or
    the program's data folder - mq_instruments.default_data_dir, the rules of the Windows app)."""
    if os.environ.get("MASTERQUO_DATA_DIR"):
        data = Path(os.environ["MASTERQUO_DATA_DIR"]).resolve()
    else:
        sys.path.insert(0, str(root / "backend"))
        from mq_instruments import default_data_dir
        data = default_data_dir(root)
    try:
        wd = json.loads((data / "kronos" / "settings.json").read_text(encoding="utf-8")).get("weights_dir")
        if wd:
            return Path(wd)
    except (OSError, ValueError):
        pass
    return data / "kronos" / "models"


def py_version(exe: str) -> tuple[int, int, int] | None:
    try:
        r = subprocess.run([exe, "-c", "import sys,struct;print(sys.version_info[0],sys.version_info[1],struct.calcsize('P')*8)"],
                           capture_output=True, text=True, timeout=60)
        a, b, bits = (int(x) for x in r.stdout.split())
        return a, b, bits
    except Exception:  # noqa: BLE001
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--weights-dir", required=True)
    ap.add_argument("--cuda", choices=("cu126", "cu128"))
    ap.add_argument("--status-file")
    ap.add_argument("--python")
    ap.add_argument("--log")
    a = ap.parse_args(argv)
    if a.log:
        Path(a.log).parent.mkdir(parents=True, exist_ok=True)
        LOG["f"] = open(a.log, "a", encoding="utf-8")
    root = Path(a.root).resolve()
    out = Out(a.status_file)
    if a.weights_dir == "auto":
        a.weights_dir = str(default_weights_dir(root))
    win = os.name == "nt"
    # 1. base interpreter
    cands = [str(root / "runtime" / "python" / "python.exe"), a.python, getattr(sys, "_base_executable", None), sys.executable]
    base = None
    for c in cands:
        if c and Path(c).is_file():
            v = py_version(c)
            if v and v[0] == 3 and v[1] in (12, 13) and v[2] == 64:
                base = c
                break
    if not base:
        return result(out, 1, False, "NO_PYTHON", error="brak Python 3.13/3.12 x64 (runtime\\python z paczki, --python albo bieżący)")
    out.say(1, f"Python do środowiska: {base}")
    # 2. venv
    venv = root / ".venv_kronos"
    vpy = venv / ("Scripts/python.exe" if win else "bin/python")
    if not vpy.is_file():
        out.say(2, f"tworzę {venv}")
        rc, last = run([base, "-m", "venv", str(venv)], out, 2)
        if rc != 0 or not vpy.is_file():
            return result(out, 2, False, "VENV", error=f"python -m venv nie powiodło się: {last}")
    else:
        out.say(2, f"{venv} istnieje – używam")
    # 3. packages
    req = root / "requirements" / "requirements-kronos-win.txt"
    pip = [str(vpy), "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    if win:
        if a.cuda:
            lines = req.read_text(encoding="utf-8").splitlines()
            keep, skip = [], False
            for ln in lines:                                   # drop the torch block (+ its hash lines); everything else stays hash-checked
                if ln.startswith("torch=="):
                    skip = True
                    continue
                if skip and ln.startswith("    --hash"):
                    continue
                skip = False
                keep.append(ln)
            tmp = venv / "requirements-kronos-nocuda.txt"
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
            out.say(3, f"instaluję zależności (z sumami) bez torch, potem {TORCH} z indeksu PyTorch {a.cuda} (bez sum w naszym pliku)")
            rc, last = run(pip + ["--require-hashes", "--only-binary=:all:", "-r", str(tmp)], out, 3)
            if rc == 0:
                rc, last = run(pip + ["--only-binary=:all:", TORCH, "--index-url", f"https://download.pytorch.org/whl/{a.cuda}"], out, 3)
        else:
            out.say(3, "instaluję PyTorch (CPU) i zależności – tylko pakiety z sumami SHA-256 (~250 MB)")
            rc, last = run(pip + ["--require-hashes", "--only-binary=:all:", "-r", str(req)], out, 3)
    else:
        pins = [ln.split(" ")[0] for ln in req.read_text(encoding="utf-8").splitlines() if "==" in ln and not ln.startswith("#")]
        out.say(3, f"{platform.system()}: plik z sumami dotyczy Windows – instaluję te same wersje bez sum (tryb deweloperski)")
        rc, last = run(pip + ["--only-binary=:all:"] + pins, out, 3)
    if rc != 0:
        return result(out, 3, False, "PIP", error=f"instalacja pakietów nie powiodła się: {last[-300:]}")
    env = dict(os.environ, PYTHONPATH=str(root / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_DISABLE_TELEMETRY="1")
    # 4. weights
    out.say(4, "pobieram oficjalne wagi NeoQuasar/Kronos-base (największy publicznie dostępny wariant) i NeoQuasar/Kronos-Tokenizer-base (przypięte rewizje) i sprawdzam sumy")
    rc, last = run([str(vpy), "-m", "kronos_runtime.install", "download", "--weights-dir", a.weights_dir], out, 4, env)
    if rc != 0:
        code, msg = child_error(last)
        return result(out, 4, False, "DOWNLOAD", error=msg, detail_code=code)
    # 5. verify
    out.say(5, "sprawdzam instalację: sumy, ładowanie, prognoza testowa, porównanie z wynikiem autorów")
    env["HF_HUB_OFFLINE"] = "1"
    rc, last = run([str(vpy), "-m", "kronos_runtime.install", "verify", "--weights-dir", a.weights_dir, "--reference"], out, 5, env)
    if rc != 0:
        code, msg = child_error(last)
        return result(out, 5, False, "VERIFY", error=msg, detail_code=code)
    ref = ((CHILD["result"] or {}).get("selftest") or {}).get("reference") or {}
    return result(out, 5, True, None, venv=str(venv), python=str(vpy), weights_dir=a.weights_dir, cuda=a.cuda,
                  reference_comparison=ref.get("status"), device=((CHILD["result"] or {}).get("load") or {}).get("device"))


if __name__ == "__main__":
    raise SystemExit(main())
