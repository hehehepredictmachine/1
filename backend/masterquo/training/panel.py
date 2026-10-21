"""Training panel backend (PMW-SH-1 stage 9): one registry of every model with its role and live status, readiness checks,
run history with REAL progress (finished tasks + the trainer's own [POSTEP] counters), lost-worker detection, logs, run
comparison, and export / import of training packages (data, provenance, labels, costs, QC, splits, schemas, configs, code version,
manifest with checksums, reproduction commands - never secrets).

Statuses are read from files written by the trainers and registries - nothing here declares a model ready.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from .. import paths
from . import core

SECRET_KEY = re.compile(r"(secret|token|password|passwd|api[_-]?key|apikey|credential|private)", re.I)
PROGRESS_RE = re.compile(r"\[POSTEP\]\s+(\S+)\s+(\d+)/(\d+)")


def _json(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def scrub(obj):
    """Remove any field whose NAME looks like a secret (recursively)."""
    if isinstance(obj, dict):
        return {k: ("<USUNIĘTO>" if SECRET_KEY.search(str(k)) else scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(x) for x in obj]
    return obj


# ------------------------------------------------------------------ runs, progress, lost worker
def lock_holder() -> dict | None:
    cur = _json(core.lock_path())
    if not cur:
        return None
    return {**cur, "alive": core._pid_alive(int(cur.get("pid", 0)))}


def run_status(state: dict) -> str:
    """Execution status of a run including a LOST worker (state says RUNNING but no live process holds the lock)."""
    st = state.get("status")
    if st == "RUNNING":
        h = lock_holder()
        if not h or h.get("run_id") != state.get("run_id") or not h.get("alive"):
            return "UTRACONY_PROCES"
    return st or "PLANNED"


def progress(state: dict, run_dir: Path) -> dict:
    """Real progress: tasks finished out of the tasks selected in the plan, plus the running task's own counter (if it reports one).
    No time-based or invented percentage."""
    tasks = [t for t in state["tasks"] if t.get("detail") != "nie wybrano w planie" and t["kind"] not in ("scalp_B", "scalp_C")]
    done = sum(1 for t in tasks if t["execution"] in ("UKONCZONE", "POMINIETE", "BLAD_TECHNICZNY", "ANULOWANE"))
    cur = next((t for t in tasks if t["execution"] == "W_TOKU"), None)
    sub = None
    if cur and cur.get("log"):
        tail = log_tail_path(Path(cur["log"]), 4000)
        m = None
        for m in PROGRESS_RE.finditer(tail):
            pass
        if m:
            sub = {"stage": m.group(1), "done": int(m.group(2)), "total": int(m.group(3)),
                   "fraction": round(int(m.group(2)) / max(1, int(m.group(3))), 4), "source": "licznik trenera ([POSTEP] w logu)"}
    return {"tasks_done": done, "tasks_total": len(tasks), "fraction": round(done / max(1, len(tasks)), 4), "current_task": cur["id"] if cur else None,
            "current_title": cur["title"] if cur else None, "current_started_at": cur.get("started_at") if cur else None, "current_counter": sub,
            "note": "postęp = ukończone zadania planu; licznik bieżącego zadania tylko jeśli trener go raportuje (bez szacowania czasu)"}


def runs(limit: int = 50) -> list[dict]:
    out = []
    for p in sorted(core.runs_dir().glob("*/state.json"), reverse=True)[:limit]:
        st = _json(p)
        if not st:
            continue
        ts = st.get("tasks") or []
        out.append({"run_id": st["run_id"], "created_at": st.get("created_at"), "finished_at": st.get("finished_at"), "status": run_status(st),
                    "profile": st["plan"].get("profile"), "instruments": st["plan"].get("instruments"), "origin": st["plan"].get("origin"),
                    "synthetic": st["plan"].get("synthetic"), "requested_tasks": st["plan"].get("requested_tasks"),
                    "counts": {k: sum(1 for t in ts if t["execution"] == k) for k in core.EXEC}})
    return out


def run_detail(rid: str) -> dict:
    run = core.Run.load(rid)
    st = dict(run.state)
    from .report import summary
    st["summary"] = summary(st)
    st["status_effective"] = run_status(st)
    st["progress"] = progress(st, run.dir)
    st["report_available"] = (run.dir / "report.html").exists()
    return scrub(st)


def log_tail_path(p: Path, nbytes: int = 20000) -> str:
    try:
        with open(p, "rb") as fh:
            fh.seek(max(0, fh.seek(0, 2) - nbytes))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def task_log(rid: str, task_id: str, nbytes: int = 20000) -> dict:
    run = core.Run.load(rid)
    t = run.task(task_id)
    lp = Path(t["log"]) if t.get("log") else None
    if not lp or not lp.exists() or run.dir.resolve() not in lp.resolve().parents:
        return {"task": task_id, "log": None, "text": "", "reason": "zadanie nie zapisało logu (nie uruchomione albo zadanie wewnętrzne)"}
    return {"task": task_id, "log": lp.name, "text": log_tail_path(lp, nbytes)}


def compare(a: str, b: str) -> dict:
    ra, rb = core.Run.load(a).state, core.Run.load(b).state
    ta, tb = {t["id"]: t for t in ra["tasks"]}, {t["id"]: t for t in rb["tasks"]}
    rows = []
    for tid in sorted(set(ta) | set(tb)):
        x, y = ta.get(tid) or {}, tb.get(tid) or {}
        diff = {k: [x.get(k), y.get(k)] for k in ("execution", "quality", "integration", "model_id", "detail") if x.get(k) != y.get(k)}
        rows.append({"task": tid, "title": (x or y).get("title"), "a": {k: x.get(k) for k in ("execution", "quality", "integration", "model_id")},
                     "b": {k: y.get(k) for k in ("execution", "quality", "integration", "model_id")}, "changed": sorted(diff)})
    plan_diff = {k: [ra["plan"].get(k), rb["plan"].get(k)] for k in ("profile", "months", "instruments", "symbols", "commissions", "synthetic")
                 if ra["plan"].get(k) != rb["plan"].get(k)}
    return {"a": a, "b": b, "plan_diff": scrub(plan_diff), "tasks": rows}


# ------------------------------------------------------------------ unified model registry
def _last_task(inst: str, kind: str) -> dict | None:
    for p in sorted(core.runs_dir().glob("*/state.json"), reverse=True):
        st = _json(p)
        if not st or inst not in (st["plan"].get("instruments") or []):
            continue
        t = next((x for x in st["tasks"] if x["instrument"] == inst and x["kind"] == kind and x["execution"] != "NIE_URUCHOMIONE"
                  and x.get("detail") != "nie wybrano w planie"), None)
        if t:
            return {**{k: t.get(k) for k in ("execution", "quality", "integration", "model_id", "detail", "updated_at", "started_at", "seconds", "unit")},
                    "run_id": st["run_id"], "synthetic": st["plan"].get("synthetic")}
    return None


def models(rt, inst: str) -> dict:
    from ..sh import models as SHM
    from ..sh import tpmodel as TM
    mx = SHM.matrix(rt, inst)
    out = []
    for r in mx["rows"]:
        kind = r["kind"]
        row = {**r, "requires_training": kind == "TRAINED"}
        if kind != "TRAINED":
            row.update(training="nie wymaga treningu", readiness="DETERMINISTIC_OK" if r["status"] in ("DETERMINISTIC_OK", "SHADOW_ONLY") else r["status"],
                       blockers=[] if r["status"] in ("DETERMINISTIC_OK", "SHADOW_ONLY") else [r["reason"]])
        else:
            last = _last_task(inst, r["train"]) if r.get("train") else None
            row["last_training"] = last
            blockers = []
            if r["status"] in ("NOT_TRAINED", "DATA_MISSING"):
                blockers.append("brak przetrenowanego modelu – uruchom zadanie " + str(r.get("train")))
            if r["status"] == "NOT_CONNECTED":
                blockers.append(r["reason"])
            if r["status"] == "INCOMPATIBLE":
                blockers.append("model niezgodny ze schematem – wymagany ponowny trening")
            if last and last.get("synthetic"):
                blockers.append("ostatni trening na danych syntetycznych (test techniczny)")
            if r["id"] == "sh_tp_model":
                row["per_strategy"] = {}
                for strat in ("SCALPING", "HEDGING"):
                    reg = _json(TM.root(inst, strat) / "registry.json") or {"runs": [], "active": None}
                    act = next((x for x in reg["runs"] if x["run_id"] == reg.get("active")), None)
                    lastr = (reg.get("runs") or [None])[-1]
                    row["per_strategy"][strat] = {"status": TM.status(inst, strat), "active": reg.get("active"),
                                                  "version": TM.VERSION, "features": TM.FEATURES,
                                                  "active_holdout": (act or {}).get("holdout"), "last_run": {k: (lastr or {}).get(k) for k in
                                                  ("run_id", "verdict", "n", "split", "holdout", "provenance", "created_at", "reason", "promoted")},
                                                  "runs": [{k: x.get(k) for k in ("run_id", "verdict", "n", "created_at", "promoted", "imported")}
                                                           for x in reg["runs"][-10:]],
                                                  "validation": _json(paths.data_dir() / "sh" / "validation" / f"{inst}_{strat}.json") is not None}
                row["event"] = "TP2 przed SL w horyzoncie strategii (SCALPING 30 min, HEDGING 240 min)"
            row.update(training=r.get("train"), readiness="READY" if r["status"] == "READY" else ("SHADOW" if r["status"] == "SHADOW_ONLY" else "NIEGOTOWY"),
                       blockers=blockers)
        out.append(row)
    return {"instrument": inst, "mode": mx["mode"], "mode_note": mx["mode_note"], "models": out, "correlation_groups": mx["correlation_groups"],
            "dependency_order": [k for k, _ in __import__("masterquo.training.runner", fromlist=["TASKS"]).TASKS]}


def readiness(rt, inst: str) -> dict:
    """Pre-flight checks before starting training; every failed check names what to do."""
    checks = []

    def add(cid, ok, detail, blocking=True):
        checks.append({"id": cid, "ok": bool(ok), "detail": detail, "blocking": blocking})
    h = lock_holder()
    add("no_running_training", not (h and h.get("alive")), f"trwa trening {h.get('run_id')}" if h and h.get("alive") else "brak innego treningu")
    b = getattr(rt, "bridge", None)
    st = getattr(b, "state", None)
    add("mt5_connected", st == "CONNECTED", f"MT5: {st} (eksport historii wymaga połączonego terminala)")
    try:
        cfg = rt.cfg.get()
        m = cfg.assets.mappings.get(inst)
        sym = m.broker_symbol if m and m.broker_symbol else (cfg.mt5.symbol if inst == "XAUUSD" else None)
    except Exception:  # noqa: BLE001
        sym = None
    add("broker_symbol", bool(sym), f"symbol brokera: {sym or 'BRAK – wybierz w Diagnostyce'} (bez automatycznej podmiany)")
    try:
        free = shutil.disk_usage(paths.data_dir()).free / 2**30
    except OSError:
        free = None
    add("disk", free is None or free >= 3.0, f"wolne miejsce {free:.1f} GB (min. 3 GB)" if free is not None else "nieznane")
    py = core.candles_python()
    add("candles_env", bool(py), "środowisko .venv_candles gotowe" if py else "brak .venv_candles – zadanie prognoz zostanie pominięte (instalator)",
        blocking=False)
    from ..sh import config as SHC
    ic = (SHC.load().get("instruments") or {}).get(inst) or {}
    add("sh_instrument", ic.get("enabled") is not False, f"SH {inst}: {'dopuszczony' if ic.get('enabled') is not False else ic.get('status')}",
        blocking=False)
    add("commission", ic.get("commission_per_lot_side") is not None,
        "prowizja znana" if ic.get("commission_per_lot_side") is not None else "prowizja nieznana w profilu SH – eksport spróbuje odczytać ją z terminala",
        blocking=False)
    last = None
    for p in sorted(core.runs_dir().glob("*/state.json"), reverse=True):
        s = _json(p)
        t = next((x for x in (s or {}).get("tasks", []) if x["instrument"] == inst and x["kind"] == "export" and x["execution"] == "UKONCZONE"), None)
        if t:
            last = {"run_id": s["run_id"], "dataset_id": t.get("dataset_id"), "range": t.get("received_range_utc"), "data_kind": t.get("data_kind")}
            break
    add("previous_dataset", True, f"ostatni eksport: {last['dataset_id']} {last['range']}" if last else "brak wcześniejszego eksportu (zostanie wykonany)",
        blocking=False)
    return {"instrument": inst, "ready": all(c["ok"] for c in checks if c["blocking"]), "checks": checks, "last_dataset": last}


# ------------------------------------------------------------------ export / import packages
def exports_dir() -> Path:
    d = paths.data_dir() / "training" / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def code_version() -> dict:
    from ..version import APP_VERSION
    out = {"app_version": APP_VERSION, "python": platform.python_version()}
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(paths.ROOT_DIR), capture_output=True, text=True, timeout=5)
        out["git_commit"] = r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        out["git_commit"] = None
    try:
        import numpy
        out["numpy"] = numpy.__version__
    except ImportError:
        pass
    return out


def _latest_dataset(inst: str, run_id: str | None) -> tuple[Path | None, dict | None]:
    for p in sorted(core.runs_dir().glob("*/state.json"), reverse=True):
        s = _json(p)
        if not s or (run_id and s["run_id"] != run_id):
            continue
        t = next((x for x in s["tasks"] if x["instrument"] == inst and x["kind"] == "export" and x["execution"] == "UKONCZONE"), None)
        if t and t.get("dataset_dir") and Path(t["dataset_dir"]).exists():
            return Path(t["dataset_dir"]), s
        if run_id:
            return None, s
    return None, None


MODEL_DIRS = {
    "sh_tp_model": lambda inst: [paths.data_dir() / "sh" / "models" / inst, paths.data_dir() / "sh" / "validation"],
    "gold_forecast": lambda inst: [__import__("mq_instruments").root("forecast", inst)],
    "scalp_A": lambda inst: [__import__("mq_instruments").root("scalp", inst)],
    "legacy_ml": lambda inst: [__import__("mq_instruments").root("ml", inst)],
    "lab": lambda inst: [paths.data_dir() / "lab" / "models" / inst],
    "indicator_context": lambda inst: [paths.data_dir() / "indicator_context" / inst],
    "ml_scalp": lambda inst: [paths.data_dir() / "ml_scalp" / inst],
    "nss": lambda inst: [paths.data_dir() / "nss" / inst],
    "si_move": lambda inst: [paths.data_dir() / "structure_intelligence" / inst],
    "flow_reaction": lambda inst: [paths.data_dir() / "flow_context" / inst],
    "context_move": lambda inst: [paths.data_dir() / "context_ind" / inst],
}
SKIP_NAMES = re.compile(r"(secrets|\.env$|config\.json$|\.lock$|\.tmp$)", re.I)


def export_package(inst: str, scope: str = "all", run_id: str | None = None, max_model_mb: float = 400.0) -> dict:
    """ZIP with everything needed to reproduce training of one model (scope = model id) or of all models (scope = all)."""
    if scope != "all" and scope not in MODEL_DIRS:
        raise ValueError(f"NIEZNANY_MODEL:{scope}")
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = f"PMW_TRENING_{inst}_{scope}_{ts}.zip"
    path = exports_dir() / name
    files: list[dict] = []
    missing: list[str] = []
    tmp = path.with_suffix(".tmp")
    ds, run_state = _latest_dataset(inst, run_id)
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        def add_file(src: Path, arc: str):
            if SKIP_NAMES.search(src.name):
                return
            data = src.read_bytes()
            z.writestr(arc, data)
            files.append({"path": arc, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

        def add_json(arc: str, obj):
            data = json.dumps(scrub(obj), indent=1, ensure_ascii=False, default=str).encode("utf-8")
            z.writestr(arc, data)
            files.append({"path": arc, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        # data + provenance + QC
        if ds:
            for f in sorted(ds.iterdir()):
                if f.is_file():
                    add_file(f, f"data/{f.name}")
        else:
            missing.append(f"dane treningowe {inst}: brak ukończonego eksportu historii" + (f" w runie {run_id}" if run_id else ""))
        # configs (single sources) - secrets never included
        for rel in ("config/sh_strategies_v1.json", "config/training_profiles_v1.json", "config/instruments_v1.json", "config/scalp_profile_v1.json",
                    "config/scalp_profile_BTC_v1.json", "config/scalp_variants_v1.json"):
            p = paths.ROOT_DIR / rel
            if p.exists():
                add_file(p, rel)
        ov = paths.data_dir() / "sh" / "config_override.json"
        if ov.exists():
            add_json("config/sh_config_override.json", _json(ov))
        # run (plan, tasks, report, logs)
        if run_state:
            rdir = core.runs_dir() / run_state["run_id"]
            add_json("training/state.json", run_state)
            for n in ("report.json", "report.html"):
                if (rdir / n).exists():
                    add_file(rdir / n, f"training/{n}")
            for f in sorted((rdir / "logs").glob("*.log")) if (rdir / "logs").exists() else []:
                if f.name.startswith(inst):
                    add_file(f, f"training/logs/{f.name}")
            for f in sorted(rdir.glob(f"{inst}_*.json")):
                add_file(f, f"training/{f.name}")
        else:
            missing.append("historia treningu (state.json runu) – brak runu dla instrumentu")
        # models
        scopes = list(MODEL_DIRS) if scope == "all" else [scope]
        for sid in scopes:
            for d in MODEL_DIRS[sid](inst):
                if not d.exists() or not any(d.rglob("*")):
                    missing.append(f"{sid}: brak artefaktów w {d.relative_to(paths.data_dir()) if paths.data_dir() in d.parents else d}")
                    continue
                total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                if total > max_model_mb * 2**20:
                    missing.append(f"{sid}: {total / 2**20:.0f} MB > limit {max_model_mb} MB – dołączono tylko rejestry/manifesty")
                    sel = [f for f in d.rglob("*") if f.is_file() and f.suffix == ".json"]
                else:
                    sel = [f for f in d.rglob("*") if f.is_file()]
                for f in sorted(sel):
                    if sid == "sh_tp_model" and "validation" in d.parts and inst not in f.name:
                        continue
                    add_file(f, f"models/{sid}/{f.relative_to(d.parent).as_posix()}")
        from ..sh import tpmodel as TM
        schema = {"sh_tp_model": {"version": TM.VERSION, "features": TM.FEATURES, "label": "TP2 przed SL w horyzoncie strategii (konserwatywnie, od fill)",
                                  "preprocessing": "standaryzacja (mu/sd z bloku FIT, zapisane w .npz) + regresja logistyczna + Platt (blok CAL)",
                                  "split": "chronologiczny 60/20/20 z embargiem = horyzont strategii; holdout użyty raz",
                                  "seed": "brak losowości (deterministyczny gradient)"}}
        manifest = {"schema": "pmw-training-package-1", "created_at": ts, "instrument": inst, "scope": scope, "run_id": (run_state or {}).get("run_id"),
                    "dataset_id": (ds.name if ds else None), "code": code_version(), "feature_schemas": schema,
                    "instrument_costs": {k: v for k, v in (((_json(paths.ROOT_DIR / "config" / "sh_strategies_v1.json") or {}).get("instruments") or {})
                                                            .get(inst) or {}).items() if k in ("commission_per_lot_side", "slippage_usd", "max_spread_usd")},
                    "reproduce": {
                        "full_run": f"python -m masterquo training run --instruments {inst} --profile {(run_state or {}).get('plan', {}).get('profile', 'PELNY_TRENING')}",
                        "sh_models_from_this_package": f"python -m masterquo sh train --instrument {inst} --dataset <rozpakowany katalog>/data --out sh_models.json",
                        "note": "polecenia uruchamiać z katalogu backend; modele z tym samym kodem (git_commit) i tymi samymi danymi (sha256 w manifeście)"},
                    "missing": missing, "secrets": "pominięte – pakiet nie zawiera kluczy, haseł, tokenów ani danych logowania", "files": files}
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=1, ensure_ascii=False))
        z.writestr("README_REPRODUKCJA.md", "\n".join([
            f"# Pakiet treningowy {inst} ({scope})", "", "Zawartość: data/ (eksport MT5 + jakość danych), config/ (jedno źródło konfiguracji),",
            "training/ (plan, zadania, raport, logi), models/ (rejestry i artefakty), MANIFEST.json (sumy SHA-256, wersja kodu, schematy).", "",
            "Odtworzenie:", "```", manifest["reproduce"]["full_run"], manifest["reproduce"]["sh_models_from_this_package"], "```", "",
            "Brakujące elementy:" if missing else "Brak braków.", *[f"- {m}" for m in missing]]))
    os.replace(tmp, path)
    return {"file": name, "path": str(path), "bytes": path.stat().st_size, "files": len(files), "missing": missing,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def import_package(data: bytes) -> dict:
    """Import of a training package: every file is checked against the manifest; SH event-model runs are added as CANDIDATES
    (never activated by an import). Other model families are reported as not importable automatically."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("TO_NIE_JEST_ZIP") from exc
    if "MANIFEST.json" not in z.namelist():
        raise ValueError("BRAK_MANIFESTU")
    man = json.loads(z.read("MANIFEST.json"))
    bad = []
    for f in man.get("files") or []:
        try:
            if hashlib.sha256(z.read(f["path"])).hexdigest() != f["sha256"]:
                bad.append(f["path"])
        except KeyError:
            bad.append(f["path"] + " (brak)")
    if bad:
        return {"imported": [], "rejected": bad, "reason": "SUMY_KONTROLNE_NIEZGODNE"}
    from ..sh import tpmodel as TM
    inst = man.get("instrument")
    out, skipped = [], []
    for strat in ("SCALPING", "HEDGING"):
        arc = f"models/sh_tp_model/{inst}/{strat}/registry.json"
        if arc not in z.namelist():
            continue
        reg = json.loads(z.read(arc))
        for run in reg.get("runs") or []:
            npz = f"models/sh_tp_model/{inst}/{strat}/{run['run_id']}.npz"
            if npz not in z.namelist():
                continue
            out.append({"strategy": strat, "run_id": run["run_id"], **TM.import_run(inst, strat, run, z.read(npz))})
    other = sorted({p.split("/")[1] for p in z.namelist() if p.startswith("models/") and p.split("/")[1] != "sh_tp_model"})
    if other:
        skipped = [f"{o}: import automatyczny nieobsługiwany – odtwórz trening poleceniem z manifestu" for o in other]
    return {"instrument": inst, "imported": out, "skipped": skipped, "manifest": {k: man.get(k) for k in ("created_at", "scope", "dataset_id", "code")}}
