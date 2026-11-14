"""Installer of Chronos-2 and Granite TTM (stdlib only; 1.40: FinCast retired) - used by 38_MODELE_CHRONOS2_GRANITE.bat and by the panel buttons "Zainstaluj".

  python tools/tsfm_setup.py --model chronos2|granite_ttm|all --root <folder programu> --weights-root <folder wag | auto>
                             [--cuda cu126|cu128] [--from-dir DIR] [--status-file F] [--python EXE] [--log F]

Steps per model (progress lines "[TSFM-SETUP] [k/5] ..."; the last line is "RESULT <json>"):
  1. Python 3.13 / 3.12 x64 for the environment (runtime\\python of the Windows package first, then --python, then this interpreter)
     + a report of RAM, free disk and CUDA (nvidia-smi if present) - drivers are never changed.
  2. Own environment next to the program: .venv_chronos2 / .venv_granite (the bot's .venv and .venv_kronos are never modified).
  3. Packages: requirements/requirements-<model>-win.txt with --require-hashes --only-binary=:all: (torch from PyPI = CPU build on
     Windows). --cuda: torch from the official PyTorch index for that CUDA variant (no hashes in our file - stated in the log), the rest
     still hash-checked. Other systems: the same versions without hashes (development only).
  4. Weights: python -m tsfm_runtime.install download (pinned revision, size + SHA-256 of every file, resume after an interruption,
     manifest written last and atomically). No internet / disk -> error, the model is NOT ready. --from-dir: files copied and verified.
  5. Check: python -m tsfm_runtime.install verify --selftest (checksums offline, load once, real forecast, parity with the official API).
After a successful installation the models run offline (HF_HUB_OFFLINE=1 in the model processes). Nothing here touches MetaTrader 5,
account data or the bot's decision settings (roles stay OBSERVE).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kronos_setup as KS  # noqa: E402 - same process helpers (streaming, RESULT parsing, python detection)

TOTAL = 5
TORCH = {"chronos2": "torch==2.14.1", "granite_ttm": "torch==2.14.1"}        # = the pins of the requirement files
VENV = {"chronos2": ".venv_chronos2", "granite_ttm": ".venv_granite"}
NAME = {"chronos2": "Chronos-2 (amazon/chronos-2, ~0,5 GB wag)", "granite_ttm": "Granite TTM R2 (ibm-granite/granite-timeseries-ttm-r2, ~3 MB wag, ~0,35 GB RAM)"}
NEED_DISK = {"chronos2": 0.6e9 + 1.2e9, "granite_ttm": 0.01e9 + 1.7e9}      # weights + environment (approx.)
HINT = {"NETWORK": "brak połączenia z huggingface.co (internet, zapora albo proxy) – odblokuj huggingface.co i jego CDN, potem powtórz "
                   "(częściowo pobrany plik zostanie wznowiony)",
        "CHECKSUM": "plik niezgodny z przypiętą sumą SHA-256 – odrzucony, nic nie zostało oznaczone jako gotowe",
        "DISK_SPACE": "za mało miejsca na dysku", "SOURCE_MISSING": "brak pliku w folderze --from-dir",
        "MISSING_DEPENDENCY": "brak pakietu w środowisku modelu – powtórz instalację", "INCOMPATIBLE": "inny checkpoint niż przypięty",
        "RESOURCE_LIMIT": "za mało pamięci RAM / VRAM na załadowanie modelu", "SELFTEST": "test ładowania / zgodności nie przeszedł"}


class Out(KS.Out):
    def say(self, step: int, msg: str, state: str = "RUNNING") -> None:
        line = f"[TSFM-SETUP] [{step}/{TOTAL}] {msg}"
        KS.emit(line)
        self.log = (self.log + [line])[-60:]
        if self.status_file:
            try:
                p = Path(self.status_file)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({"state": state, "step": step, "total": TOTAL, "message": msg, "log": self.log, "updated_at": KS.now()},
                                        ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass


def result(out: Out, step: int, ok: bool, code: str | None = None, **kw) -> dict:
    out.say(step, "GOTOWE" if ok else f"BŁĄD {code}: {kw.get('error', '')}", state="DONE" if ok else "FAILED")
    return {"ok": ok, "code": code, **kw}


def child_error(last: str) -> tuple[str | None, str]:
    r = KS.CHILD["result"] or {}
    msg = (r.get("error") or last or "")[:300]
    if any(k in msg for k in KS.APP_CONTROL):       # 1.40.6: Windows refused a library - explained, not "missing package"
        return KS.child_error(last)
    code = r.get("code")
    return code, (f"{HINT[code]}. " if code in HINT else "") + msg


def default_weights_root(root: Path) -> Path:
    """Same folder as the bot: <data>/tsfm/models or weights_root from <data>/tsfm/settings.json."""
    if os.environ.get("MASTERQUO_DATA_DIR"):
        data = Path(os.environ["MASTERQUO_DATA_DIR"]).resolve()
    else:
        sys.path.insert(0, str(root / "backend"))
        from mq_instruments import default_data_dir
        data = default_data_dir(root)
    try:
        w = json.loads((data / "tsfm" / "settings.json").read_text(encoding="utf-8")).get("weights_root")
        if w:
            return Path(w)
    except (OSError, ValueError):
        pass
    return data / "tsfm" / "models"


def hardware() -> dict:
    out = {"cpu_count": os.cpu_count(), "platform": platform.platform()}
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong),
                            ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            out["ram_total_gb"], out["ram_free_gb"] = round(m.ullTotalPhys / 1e9, 1), round(m.ullAvailPhys / 1e9, 1)
        else:
            pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
            out["ram_total_gb"] = round(pages * size / 1e9, 1)
    except Exception:  # noqa: BLE001
        pass
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            r = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
            out["gpu"] = r.stdout.strip() or None
        except Exception:  # noqa: BLE001
            out["gpu"] = None
    else:
        out["gpu"] = None
    return out


def install_one(mid: str, a, root: Path, base: str, out: Out) -> dict:
    win = os.name == "nt"
    hw = hardware()
    free = shutil.disk_usage(Path(a.weights_root).parent if Path(a.weights_root).parent.exists() else root).free
    out.say(1, f"{NAME[mid]}: Python {base}; RAM {hw.get('ram_total_gb', '?')} GB, wolne {free / 1e9:.1f} GB, GPU {hw.get('gpu') or 'brak (CPU)'}")
    if free < NEED_DISK[mid]:
        return result(out, 1, False, "DISK_SPACE", error=f"potrzeba ok. {NEED_DISK[mid] / 1e9:.1f} GB, wolne {free / 1e9:.1f} GB", model=mid)
    venv = root / VENV[mid]
    vpy = venv / ("Scripts/python.exe" if win else "bin/python")
    if not vpy.is_file():
        out.say(2, f"tworzę {venv}")
        rc, last = KS.run([base, "-m", "venv", str(venv)], out, 2)
        if rc != 0 or not vpy.is_file():
            return result(out, 2, False, "VENV", error=f"python -m venv nie powiodło się: {last}", model=mid)
    else:
        out.say(2, f"{venv} istnieje – używam")
    if subprocess.run([str(vpy), "-m", "pip", "--version"], capture_output=True, env=KS.child_env()).returncode != 0:
        out.say(2, "w środowisku brak pip – instaluję go z modułu ensurepip (offline, z biblioteki standardowej)")
        rc, last = KS.run([str(vpy), "-m", "ensurepip", "--upgrade"], out, 2)
        if rc != 0:
            return result(out, 2, False, "VENV", error=f"brak pip i ensurepip nie powiodło się: {last}; usuń {venv} i uruchom ponownie", model=mid)
    req = root / "requirements" / f"requirements-{"granite" if mid == "granite_ttm" else mid}-win.txt"
    pip = [str(vpy), "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    if mid == "granite_ttm":                 # 1.40.6: every package is pinned; granite-tsfm's declared torch<2.12 would block torch 2.14.1
        pip.append("--no-deps")
    if win:
        if a.cuda:
            lines = req.read_text(encoding="utf-8").splitlines()
            keep, skip = [], False
            for ln in lines:
                if ln.startswith("torch=="):
                    skip = True
                    continue
                if skip and ln.startswith("    --hash"):
                    continue
                skip = False
                keep.append(ln)
            tmp = venv / f"requirements-{mid}-nocuda.txt"
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
            out.say(3, f"instaluję zależności (z sumami) bez torch, potem {TORCH[mid]} z indeksu PyTorch {a.cuda} (bez sum w naszym pliku)")
            rc, last = KS.run(pip + ["--require-hashes", "--only-binary=:all:", "-r", str(tmp)], out, 3)
            if rc == 0:
                rc, last = KS.run(pip + ["--only-binary=:all:", "--force-reinstall", "--no-deps", TORCH[mid], "--index-url",
                                         f"https://download.pytorch.org/whl/{a.cuda}"], out, 3)
        else:
            out.say(3, "instaluję PyTorch (CPU) i zależności – tylko pakiety z sumami SHA-256")
            rc, last = KS.run(pip + ["--require-hashes", "--only-binary=:all:", "-r", str(req)], out, 3)
    else:
        pins = [ln.split(" ")[0] for ln in req.read_text(encoding="utf-8").splitlines() if "==" in ln and not ln.startswith("#")]
        out.say(3, f"{platform.system()}: plik z sumami dotyczy Windows – instaluję te same wersje bez sum (tryb deweloperski)")
        rc, last = KS.run(pip + ["--only-binary=:all:", "--extra-index-url", "https://download.pytorch.org/whl/cpu"] + pins, out, 3)
    if rc != 0:
        return result(out, 3, False, "PIP", error=f"instalacja pakietów nie powiodła się: {last[-300:]}", model=mid)
    env = dict(os.environ, PYTHONPATH=str(root / "backend"), PYTHONIOENCODING="utf-8", HF_HUB_DISABLE_TELEMETRY="1")
    out.say(4, f"pobieram oficjalne wagi {NAME[mid]} (przypięta rewizja, rozmiar + SHA-256 każdego pliku)")
    cmd = [str(vpy), "-m", "tsfm_runtime.install", "download", "--model", mid, "--weights-root", str(a.weights_root)]
    if a.from_dir:
        cmd += ["--from-dir", a.from_dir]
    rc, last = KS.run(cmd, out, 4, env)
    if rc != 0:
        code, msg = child_error(last)
        return result(out, 4, False, "DOWNLOAD", error=msg, detail_code=code, model=mid)
    out.say(5, "sprawdzam instalację: sumy, ładowanie (raz), prognoza testowa, zgodność z oficjalnym API")
    env["HF_HUB_OFFLINE"] = "1"
    rc, last = KS.run([str(vpy), "-m", "tsfm_runtime.install", "verify", "--model", mid, "--weights-root", str(a.weights_root), "--selftest"],
                      out, 5, env)
    if rc != 0:
        code, msg = child_error(last)
        return result(out, 5, False, "VERIFY", error=msg, detail_code=code, model=mid)
    ch = KS.CHILD["result"] or {}
    return result(out, 5, True, None, model=mid, venv=str(venv), python=str(vpy), weights_root=str(a.weights_root), cuda=a.cuda,
                  device=(ch.get("load") or {}).get("device"), params=(ch.get("load") or {}).get("params"),
                  load_ms=(ch.get("load") or {}).get("load_ms"), parity=((ch.get("selftest") or {}).get("parity") or {}).get("status"),
                  hardware=hw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=("chronos2", "granite_ttm", "all"))
    ap.add_argument("--root", required=True)
    ap.add_argument("--weights-root", required=True)
    ap.add_argument("--cuda", choices=("cu126", "cu128"))
    ap.add_argument("--from-dir")
    ap.add_argument("--status-file")
    ap.add_argument("--python")
    ap.add_argument("--log")
    a = ap.parse_args(argv)
    if a.log:
        Path(a.log).parent.mkdir(parents=True, exist_ok=True)
        KS.LOG["f"] = open(a.log, "a", encoding="utf-8")
    root = Path(a.root).resolve()
    out = Out(a.status_file)
    if a.weights_root == "auto":
        a.weights_root = str(default_weights_root(root))
    base = None
    for c in (str(root / "runtime" / "python" / "python.exe"), a.python, getattr(sys, "_base_executable", None), sys.executable):
        if c and Path(c).is_file():
            v = KS.py_version(c)
            if v and v[0] == 3 and v[1] in (12, 13) and v[2] == 64:
                base = c
                break
    if not base:
        r = result(out, 1, False, "NO_PYTHON", error="brak Python 3.13/3.12 x64 (runtime\\python z paczki, --python albo bieżący)")
        KS.emit("RESULT " + json.dumps(r, ensure_ascii=False))
        return 1
    models = ["chronos2", "granite_ttm"] if a.model == "all" else [a.model]
    res = [install_one(m, a, root, base, out) for m in models]
    ok = all(r["ok"] for r in res)
    first_bad = next((r for r in res if not r["ok"]), {})
    KS.emit("RESULT " + json.dumps({"ok": ok, "code": first_bad.get("code"), "error": first_bad.get("error"), "models": res}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
