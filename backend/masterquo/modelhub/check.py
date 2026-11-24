"""`python -m masterquo models check [--smoke] [--live SECONDS] [--only PATTERN] [--area AREA] [--json PATH] [--md PATH]` (1.46 arch).

ONE health check of every model producer of the bot. The list of producers is the canonical registry (quant/ids.py, expanded by
quant/inventory.build - the same rows as docs/quant/INVENTORY.*); nothing here keeps a second list of models.

Layers (each one adds evidence, none replaces another):

1. registry  - the row of the canonical registry (category, environment, code state) and the registry's status claim (the existing
               probes: sh.models.probe, families status, trainhub registry - quant/inventory._probe);
2. env       - the separate environment of the producer (.venv_deep, .venv_kronos, .venv_candles, .venv_tabicl, .venv_tirex2,
               .venv_chronos2, .venv_granite) exists - otherwise every deeper step is NIEZWERYFIKOWANY, never a pass;
3. --smoke   - modelhub/smoke/<area>.py: train on a tiny SYNTHETIC_TEST set through the real trainer, artifact roundtrip, prediction
               through the real predict path and PMW-PRED-2 contract (each area in its own process with a temporary data folder);
4. --live S  - Runtime(demo=True) (the composition of `serve --demo`: FakeMT5 terminal, every service) on the same temporary folder for
               S seconds, then the live adapters (modelhub.adapters.all_predictions + quant.adapters.extended) and the probes: which
               producers publish a record, in which state, and whether it is a valid contract.

Statuses of a producer: DZIAŁA (every exercised step OK), BŁĄD (a step failed), NIEZWERYFIKOWANY (environment / weights / terminal not
available here), NOT_TRAINED (fresh install, correct state), NO_SPEC / NOT_IMPLEMENTED (reported, never implemented by guessing),
TYLKO_REJESTR (no smoke requested / available). Exit code 1 when any producer is BŁĄD.

Never touches the user's data folder (every layer runs on a temporary MASTERQUO_DATA_DIR) and never changes an execution mode.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import smoke as S

ENV_VENVS = (".venv_deep", ".venv_kronos", ".venv_candles", ".venv_tabicl", ".venv_tirex2", ".venv_chronos2", ".venv_granite")
STATUS_ORDER = ("BŁĄD", "NIEZWERYFIKOWANY", "DZIAŁA", "NOT_TRAINED", "TYLKO_REJESTR", "NO_SPEC", "NOT_IMPLEMENTED")


def _venv_of(env: str | None) -> str | None:
    env = str(env or "")
    for v in ENV_VENVS:
        if v in env:
            return v
    return None


def producers(inst: str = "XAUUSD") -> list[dict]:
    """Rows of the canonical registry (groups expanded, aliases folded) with the registry's own status claim (offline probes)."""
    from ..quant import inventory as QI
    inv = QI.build(None, inst)
    out = []
    for e in inv["entries"]:
        if e["code_state"] == "GROUP":
            continue
        out.append({"id": e["id"], "name": e["name"], "aliases": e.get("aliases") or [], "category": e["category"], "env": e["env"],
                    "code_state": e["code_state"], "registry_state": e["runtime_state"], "registry_reason": e.get("state_reason"),
                    "adapter": e.get("adapter"), "files": e.get("files") or [], "source_registry": e.get("source_registry") or []})
    return out


def env_step(p: dict, ctx: S.Ctx) -> dict | None:
    v = _venv_of(p["env"])
    if v is None:
        return None
    py = ctx.env_python(v)
    if py is None:
        return S.unverified(f"brak środowiska {v} w tej instalacji (instalator .bat / zmienna MQ_*_PYTHON)")
    return S.ok(f"{v}: {py}")


def import_step(p: dict) -> dict | None:
    """Import every Python module of the producer's own files in THIS interpreter (main bot venv) - catches a broken module."""
    import importlib
    mods = []
    for f in p["files"]:
        if not f.startswith("backend/masterquo/") or not f.endswith((".py", "/")):
            continue
        rel = f[len("backend/"):].rstrip("/")
        mods.append(rel[:-3].replace("/", ".") if rel.endswith(".py") else rel.replace("/", "."))
    if not mods:
        return None
    errs = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{m}: {type(exc).__name__}: {exc}")
    return S.ok(", ".join(mods)[:400]) if not errs else S.fail("; ".join(errs))


# ---------------------------------------------------------------------------------------------------------------- smoke (per area)
def _run_area_proc(area: str, data_dir: Path, inst: str, only: str | None, timeout: float) -> list[dict]:
    env = dict(os.environ, MASTERQUO_DATA_DIR=str(data_dir), PMW_BOOTSTRAP="0", PYTHONDONTWRITEBYTECODE="1",
               MQ_FAKE_MARKET_ALWAYS_OPEN="1", OMP_NUM_THREADS=os.environ.get("OMP_NUM_THREADS", "1"))
    backend = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(backend) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    cmd = [sys.executable, "-m", "masterquo", "models", "_area", area, "--inst", inst] + (["--only", only] if only else [])
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=str(backend), env=env, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return [{"id": f"area:{area}", "area": area, "steps": {"train": S.fail(f"przekroczony limit czasu obszaru {timeout:.0f} s")},
                 "ms": int((time.monotonic() - t0) * 1000)}]
    for line in reversed(r.stdout.splitlines()):
        if line.startswith("@@MODELS_CHECK@@"):
            return json.loads(line[len("@@MODELS_CHECK@@"):])
    tail = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
    return [{"id": f"area:{area}", "area": area, "steps": {"import": S.fail(f"proces obszaru zakończony kodem {r.returncode}: {' | '.join(tail)}")},
             "ms": int((time.monotonic() - t0) * 1000)}]


def smoke_all(areas, data_dir: Path, inst: str, only: str | None, timeout: float, log=print) -> dict[str, dict]:
    res: dict[str, dict] = {}
    for a in areas:
        t0 = time.monotonic()
        rows = _run_area_proc(a, data_dir, inst, only, timeout)
        log(f"  obszar {a}: {len(rows)} pozycji, {time.monotonic() - t0:.0f} s")
        for r in rows:
            res.setdefault(r["id"], r)
    return res


# ---------------------------------------------------------------------------------------------------------------- live (serve --demo)
def live(data_dir: Path, inst: str, seconds: float, log=print) -> dict:
    """Runtime(demo=True) on `data_dir` for `seconds`; -> {canonical_id: {"state", "contract", "records"}} + probe states."""
    os.environ["MASTERQUO_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("PMW_BOOTSTRAP", "0")
    from ..quant import adapters as QA
    from ..quant import ids as I
    from ..quant import inventory as QI
    from ..runtime import Runtime
    from . import adapters as MA
    from . import contract as C
    rt = Runtime(demo=True)
    out: dict = {"records": {}, "probe": {}, "error": None}
    # LIVE stays locked (rule 1): the check only runs on the synthetic terminal in PAPER / SIGNALS and never changes the mode
    from .. import runtime as RT
    mode = getattr(getattr(rt, "modes", None), "mode", None)
    if mode not in ("PAPER", "SIGNALS") or not rt.demo or getattr(rt.worker, "_factory", None) is RT.real_mt5_factory:
        raise RuntimeError(f"models check --live odmawia: tryb {mode}, demo={rt.demo} (wymagany PAPER/SIGNALS na terminalu syntetycznym)")
    try:
        rt.start()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            time.sleep(min(5.0, max(0.0, deadline - time.monotonic())))
        recs = []
        for fn in (lambda: MA.all_predictions(rt, inst), lambda: QA.extended(rt, inst, getattr(getattr(rt, "quant", None), "event_gru", None))):
            try:
                recs += list(fn() or [])
            except Exception as exc:  # noqa: BLE001
                out["error"] = f"{type(exc).__name__}: {exc}"[:300]
        for p in recs:
            cid = I.canonical(p)
            for g in ("research:graph50:",):
                if cid.startswith(g):
                    cid = g[:-1]
            try:
                C.validate(p)
                cerr = None
            except Exception as exc:  # noqa: BLE001
                cerr = f"{type(exc).__name__}: {exc}"[:200]
            d = out["records"].setdefault(cid, {"states": [], "contract_errors": [], "n": 0})
            d["n"] += 1
            d["states"].append(p.get("state"))
            if cerr:
                d["contract_errors"].append(cerr)
        inv = QI.build(rt, inst)
        out["probe"] = {e["id"]: {"state": e["runtime_state"], "reason": e.get("state_reason"), "live_output": e.get("live_output")}
                        for e in inv["entries"]}
    finally:
        try:
            rt.stop()
        except Exception:  # noqa: BLE001
            log("  (zatrzymanie runtime z błędem – wynik zachowany)")
    return out


# ---------------------------------------------------------------------------------------------------------------- verdict
def verdict(p: dict, steps: dict, live_rec: dict | None, probe: dict | None, not_checkable: str | None) -> tuple[str, str]:
    if p["code_state"] in ("NO_SPEC", "NOT_IMPLEMENTED"):
        return p["code_state"], p.get("registry_reason") or ""
    if not_checkable:
        return "NIEZWERYFIKOWANY", not_checkable
    sts = {k: v["status"] for k, v in steps.items()}
    if S.FAIL in sts.values():
        bad = [f"{k}: {steps[k]['detail']}" for k, v in sts.items() if v == S.FAIL]
        return "BŁĄD", "; ".join(bad)[:400]
    if live_rec and live_rec.get("contract_errors"):
        return "BŁĄD", "żywy rekord łamie kontrakt: " + "; ".join(live_rec["contract_errors"][:2])
    if S.UNVERIFIED in sts.values():              # any part that could not run here (environment, weights, terminal, API key) -> never DZIAŁA
        why = [f"{k}: {steps[k]['detail']}" for k, v in sts.items() if v == S.UNVERIFIED]
        okd = [k for k, v in sts.items() if v == S.OK]
        return "NIEZWERYFIKOWANY", ("; ".join(why) + (f" | sprawdzone tutaj: {', '.join(okd)}" if okd else ""))[:400]
    deep = {k: v for k, v in sts.items() if k in ("train", "artifact", "predict", "contract")}
    ran = {k: v for k, v in deep.items() if v != S.SKIP}
    if ran and all(v == S.OK for v in ran.values()):
        skipped = [f"{k}: {steps[k]['detail']}" for k, v in deep.items() if v == S.SKIP]
        return "DZIAŁA", ("ścieżka sprawdzona na danych SYNTHETIC_TEST (technicznie, nie jakość)" +
                          (f"; pominięte: {'; '.join(skipped)}"[:300] if skipped else ""))
    st = (probe or {}).get("state") or p["registry_state"]
    if st == "NOT_TRAINED":
        return "NOT_TRAINED", "świeża instalacja – poprawny stan"
    return "TYLKO_REJESTR", f"stan rejestru: {st}"


def _cell(steps: dict, k: str) -> str:
    v = steps.get(k)
    return "–" if v is None else v["status"]


def build_report(prods: list[dict], smoke: dict, lv: dict | None, ctx: S.Ctx) -> list[dict]:
    rows = []
    for p in prods:
        sm = smoke.get(p["id"]) or {}
        steps = dict(sm.get("steps") or {})
        e = env_step(p, ctx)
        if e is not None:
            steps.setdefault("env", e)
        if "import" not in steps and p["code_state"] == "IMPLEMENTED":
            i = import_step(p)
            if i is not None:
                steps["import"] = i
        live_rec = (lv or {}).get("records", {}).get(p["id"]) if lv else None
        probe = (lv or {}).get("probe", {}).get(p["id"]) if lv else None
        if lv is not None:
            if live_rec:
                states = sorted({str(s) for s in live_rec["states"]})
                steps["live"] = (S.fail("; ".join(live_rec["contract_errors"][:2])) if live_rec["contract_errors"]
                                 else S.ok(f"{live_rec['n']} rekord(y), stany: {', '.join(states)}"))
            elif probe:
                steps.setdefault("live", S.skip(f"brak publikowanego rekordu; sonda: {probe['state']} ({probe.get('reason') or ''})"[:300]))
        status, why = verdict(p, steps, live_rec, probe, sm.get("not_checkable"))
        rows.append({**p, "steps": steps, "status": status, "why": why, "ms": sm.get("ms", 0), "probe_live": probe})
    return rows


def to_markdown(rows: list[dict], meta: dict) -> str:
    L = [f"# models check – {meta['generated_at']}", "",
         f"Instrument {meta['inst']}; warstwy: rejestr + środowisko + import" + (" + smoke" if meta["smoke"] else "") +
         (f" + na żywo ({meta['live_s']} s, Runtime demo)" if meta["live_s"] else "") + ". Dane: SYNTHETIC_TEST (technicznie, nie jakość).", "",
         "| kanoniczne id | kategoria | środowisko | env | import | trening | artefakt | predykcja | kontrakt | na żywo | stan rejestru | status | uzasadnienie |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (STATUS_ORDER.index(r["status"]) if r["status"] in STATUS_ORDER else 9, r["id"])):
        s = r["steps"]
        why = str(r["why"]).replace("|", "\\|").replace("\n", " ")[:220]
        L.append(f"| `{r['id']}` | {r['category']} | {r['env']} | {_cell(s, 'env')} | {_cell(s, 'import')} | {_cell(s, 'train')} | "
                 f"{_cell(s, 'artifact')} | {_cell(s, 'predict')} | {_cell(s, 'contract')} | {_cell(s, 'live')} | {r['registry_state']} | "
                 f"**{r['status']}** | {why} |")
    cnt: dict[str, int] = {}
    for r in rows:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    L += ["", "Podsumowanie: " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda kv: STATUS_ORDER.index(kv[0])
                                                                       if kv[0] in STATUS_ORDER else 9)), ""]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------------------------------------------- CLI
def _area_worker(argv) -> int:
    ap = argparse.ArgumentParser(prog="masterquo models _area")
    ap.add_argument("area", choices=S.AREAS)
    ap.add_argument("--inst", default=None, help="instrument z config/instruments_v1.json (domyślnie MQ_INSTRUMENT / domyślny projektu)")
    ap.add_argument("--only")
    a = ap.parse_args(argv)
    import mq_instruments
    a.inst = mq_instruments.current(a.inst)
    if not os.environ.get("MASTERQUO_DATA_DIR"):
        print("_area wymaga tymczasowego MASTERQUO_DATA_DIR (uruchamiane przez models check)", file=sys.stderr)
        return 2
    only = (lambda cid: fnmatch.fnmatch(cid, a.only)) if a.only else None
    rows = S.run_area(a.area, a.inst, only)
    print("@@MODELS_CHECK@@" + json.dumps(rows, ensure_ascii=False, default=str), flush=True)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_area"]:
        return _area_worker(argv[1:])
    ap = argparse.ArgumentParser(prog="masterquo models", description="Kontrola zdrowia wszystkich modeli (rejestr kanoniczny quant/ids.py).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="sprawdź każdy model: rejestr, środowisko, import [, smoke, ścieżka na żywo]")
    c.add_argument("--smoke", action="store_true", help="trening/artefakt/predykcja na danych SYNTHETIC_TEST (osobny folder tymczasowy)")
    c.add_argument("--live", type=float, default=0.0, metavar="SEKUNDY", help="uruchom Runtime demo (jak serve --demo) na N sekund")
    c.add_argument("--only", help="wzorzec id (fnmatch), np. 'family:*'")
    c.add_argument("--area", action="append", choices=S.AREAS, help="tylko wybrane obszary smoke (można powtórzyć)")
    c.add_argument("--inst", default=None, help="instrument z config/instruments_v1.json (domyślnie MQ_INSTRUMENT / domyślny projektu)")
    c.add_argument("--timeout", type=float, default=900.0, help="limit czasu jednego obszaru smoke [s]")
    c.add_argument("--json", help="zapisz wynik JSON")
    c.add_argument("--md", help="zapisz tabelę Markdown")
    c.add_argument("--keep", action="store_true", help="nie usuwaj folderu tymczasowego (do analizy)")
    a = ap.parse_args(argv)
    import mq_instruments
    try:
        a.inst = mq_instruments.current(a.inst)
    except ValueError as exc:
        print(f"models check: {exc} (instrumenty: {', '.join(mq_instruments.profiles())})", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    tmp = Path(tempfile.mkdtemp(prefix="pmw_models_check_"))
    old = os.environ.get("MASTERQUO_DATA_DIR")
    os.environ["MASTERQUO_DATA_DIR"] = str(tmp)        # registry probes and import side effects never reach the user's data folder
    os.environ.setdefault("PMW_BOOTSTRAP", "0")
    try:
        prods = producers(a.inst)
        if a.only:
            prods = [p for p in prods if fnmatch.fnmatch(p["id"], a.only)]
        print(f"models check: {len(prods)} producentów z rejestru kanonicznego (quant/ids.py); folder tymczasowy {tmp}")
        smoke: dict = {}
        if a.smoke:
            smoke = smoke_all(a.area or S.AREAS, tmp, a.inst, a.only, a.timeout)
        lv = live(tmp, a.inst, a.live) if a.live > 0 else None
        ctx = S.Ctx(a.inst)
        rows = build_report(prods, smoke, lv, ctx)
        unknown = sorted(set(smoke) - {p["id"] for p in prods})
        meta = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "inst": a.inst, "smoke": a.smoke, "live_s": a.live,
                "elapsed_s": round(time.monotonic() - t0, 1), "smoke_ids_outside_registry": unknown,
                "live_error": (lv or {}).get("error")}
        md = to_markdown(rows, meta)
        if unknown:
            md += "\nId z modułów smoke spoza rejestru kanonicznego (błąd spójności): " + ", ".join(f"`{u}`" for u in unknown) + "\n"
        if a.md:
            Path(a.md).write_text(md, encoding="utf-8")
        if a.json:
            Path(a.json).write_text(json.dumps({"meta": meta, "rows": rows}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(md)
        failed = [r["id"] for r in rows if r["status"] == "BŁĄD"]
        if unknown:
            failed += unknown
        print(f"models check: {'BŁĘDY: ' + ', '.join(failed) if failed else 'bez błędów'} ({meta['elapsed_s']} s)")
        return 1 if failed else 0
    finally:
        if old is None:
            os.environ.pop("MASTERQUO_DATA_DIR", None)
        else:
            os.environ["MASTERQUO_DATA_DIR"] = old
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
