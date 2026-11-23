"""Bot-side import of Studio packages (PMW-STUDIO-IMPORT-1). Used by the bot API (bot running) and by the inbox at bot start (bot off).
The package is re-verified (checksums of the artifact stage + a positive loader test), copied into the right registry as a NEW version and
left INACTIVE (trainhub: registered version, not active; families: run present, not active -> nothing influences decisions). Every import
is logged with an id; rollback removes that imported version unless it has been activated meanwhile. Archives are never extracted here -
only package directories on the local disk."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from pathlib import Path

from .package import ARTIFACT, LOADER

# 1.46: every path segment taken from the package (manifest task / train_result) is checked before it becomes a path - 1.45.0 joined
# instrument / model_key / version / run_id / model_id as given: '../..' in a crafted package wrote (and the import rollback rmtree'd)
# outside the registries. Same rules as the SH training-package import (sh/tpmodel.import_run).
IMPORT_INSTRUMENTS = ("XAUUSD", "BTC")
SEGMENT_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")


def _segments_ok(inst, *names) -> str | None:
    if inst not in IMPORT_INSTRUMENTS:
        return f"instrument {inst!r} spoza {'/'.join(IMPORT_INSTRUMENTS)}"
    bad = [n for n in names if not isinstance(n, str) or not SEGMENT_RX.match(n)]
    return f"niedozwolona nazwa w paczce: {bad[0]!r}"[:200] if bad else None


def _inside(p: Path, base: Path) -> bool:
    try:
        return p.resolve().is_relative_to(base.resolve())
    except (OSError, ValueError):
        return False


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _log_path() -> Path:
    from ..paths import data_dir
    return data_dir() / "studio_imports.json"


def _log() -> list:
    try:
        return json.loads(_log_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(items: list) -> None:
    p = _log_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def verify_stage(pkg: Path) -> tuple[bool, str | None]:
    m = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    st = (m.get("stages") or {}).get("train") or {}
    if st.get("status") != "COMMITTED":
        return False, "etap treningu nie jest zatwierdzony"
    base = pkg / st["dir"]
    for rel, h in (st.get("files") or {}).items():
        p = base / rel
        if not p.is_file() or _sha(p) != h:
            return False, f"suma kontrolna {rel} niezgodna"
    lo = json.loads((pkg / LOADER / "loader.json").read_text(encoding="utf-8")) if (pkg / LOADER / "loader.json").exists() else {}
    if not lo.get("ok"):
        return False, "paczka bez pozytywnego testu loadera (verify_loader)"
    return True, None


def import_package(pkg: str | Path) -> dict:
    pkg = Path(pkg).resolve()
    if not (pkg / "manifest.json").is_file():
        return {"ok": False, "reason": "to nie jest katalog paczki Studio (brak manifest.json)"}
    ok, why = verify_stage(pkg)
    if not ok:
        return {"ok": False, "reason": why}
    m = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    task, res = m["task"], json.loads((pkg / ARTIFACT / "train_result.json").read_text(encoding="utf-8"))
    inst = task["instrument"]
    iid = "IMP-" + uuid.uuid4().hex[:10]
    if res["kind"] == "TRAINHUB":
        from ..trainhub import registry as R
        why = _segments_ok(inst, res["model_key"], res["version"])
        if why:
            return {"ok": False, "reason": why}
        dst = R.root() / "models" / inst / res["model_key"] / res["version"]
        src = pkg / ARTIFACT / "trainhub" / res["model_key"] / res["version"]
        if not _inside(dst, R.root()) or not _inside(src, pkg):
            return {"ok": False, "reason": "ścieżka paczki poza rejestrem – nic nie zapisano"}
        if dst.exists():
            return {"ok": False, "reason": f"wersja {res['version']} już istnieje w rejestrze – nic nie nadpisano"}
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".importing")
        shutil.copytree(src, tmp)
        tmp.replace(dst)
        reg = R._reg(inst)
        from ..marketdata.store import iso as _iso                     # 1.46: ISO text like native versions (a float broke summary() sorting)
        reg.setdefault("versions", {}).setdefault(res["model_key"], []).append({"version": res["version"], "created_at": _iso(time.time()),
                                                                                "source": "STUDIO", "import_id": iid, "package": str(pkg)})
        R._save_reg(inst, reg)
        rec = {"import_id": iid, "kind": "TRAINHUB", "instrument": inst, "model_key": res["model_key"], "version": res["version"]}
    elif res["kind"] == "FAMILY":
        from ..modelhub.families import base as FB
        from ..modelhub.families import registry as famreg
        why = _segments_ok(inst, task["model_id"], res["run_id"])
        if why or task["model_id"] not in famreg():
            return {"ok": False, "reason": why or f"nieznana rodzina {task['model_id']!r}"[:200]}
        st = FB.Store()
        dst = st.fam_dir(task["model_id"], inst) / res["run_id"]
        src = pkg / ARTIFACT / "families" / task["model_id"] / inst / res["run_id"]
        if not _inside(dst, st.base) or not _inside(src, pkg):
            return {"ok": False, "reason": "ścieżka paczki poza magazynem rodzin – nic nie zapisano"}
        if dst.exists():
            return {"ok": False, "reason": f"run {res['run_id']} już istnieje – nic nie nadpisano"}
        tmp = dst.with_name(".importing-" + dst.name)
        shutil.copytree(src, tmp)
        tmp.replace(dst)
        rec = {"import_id": iid, "kind": "FAMILY", "instrument": inst, "family": task["model_id"], "run_id": res["run_id"]}
    else:
        return {"ok": False, "reason": f"adapter {res['kind']}: przekazanie przez rejestr zadania w Centrum treningu bota"}
    rec.update(at=time.time(), package=str(pkg), task_key=task["task_key"], state="CANDIDATE",
               note="zaimportowano jako kandydata – aktywacja / rola SHADOW-ASSIST jawnie w bocie")
    items = _log()
    items.append(rec)
    _save(items)
    return {"ok": True, **rec}


def rollback(import_id: str) -> dict:
    items = _log()
    rec = next((r for r in items if r["import_id"] == import_id and r.get("state") == "CANDIDATE"), None)
    if rec is None:
        return {"ok": False, "reason": "nieznany import albo już wycofany"}
    # 1.46: the rollback removes directories (rmtree) - names of a record written by 1.45.0 (unchecked import) are checked first
    why = _segments_ok(rec.get("instrument"), *((rec.get("model_key"), rec.get("version")) if rec["kind"] == "TRAINHUB"
                                                 else (rec.get("family"), rec.get("run_id"))))
    if why:
        return {"ok": False, "reason": why}
    if rec["kind"] == "TRAINHUB":
        from ..trainhub import registry as R
        if (R._reg(rec["instrument"]).get("active") or {}).get(rec["model_key"]) == rec["version"]:
            return {"ok": False, "reason": "wersja jest aktywna – najpierw rollback/dezaktywacja w Centrum treningu"}
        R.remove_version(rec["instrument"], rec["model_key"], rec["version"])
    else:
        from ..modelhub.families import base as FB
        st = FB.Store()
        if st.state(rec["family"], rec["instrument"]).get("active") == rec["run_id"]:
            return {"ok": False, "reason": "artefakt jest aktywny – najpierw rollback rodziny"}
        st.remove(rec["family"], rec["instrument"], rec["run_id"])
    rec["state"] = "ROLLED_BACK"
    rec["rolled_back_at"] = time.time()
    _save(items)
    return {"ok": True, "import_id": import_id, "state": "ROLLED_BACK"}


def inbox_dir() -> Path:
    from ..paths import data_dir
    d = data_dir() / "studio_inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def process_inbox() -> list[dict]:
    """At bot start: import every pending pointer file written by Studio while the bot was off."""
    out = []
    for p in sorted(inbox_dir().glob("*.json")):
        try:
            r = import_package(json.loads(p.read_text(encoding="utf-8"))["package"])
        except Exception as exc:  # noqa: BLE001
            r = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
        r["pointer"] = p.name
        out.append(r)
        p.rename(p.with_suffix(".done" if r.get("ok") else ".failed"))
    return out


def history() -> list[dict]:
    return _log()
