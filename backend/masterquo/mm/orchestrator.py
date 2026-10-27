"""Training / evaluation orchestrator for the master models (PMW-MM-ORCH-1).

Runs a dependency graph of bounded jobs for ONE instrument on ONE explicit dataset snapshot, in its own process (called by the shared
training runner task `master_models` or by `python -m masterquo mm train`). Statuses: QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED,
BLOCKED_DATA_QUALITY, BLOCKED_VALIDATION, BLOCKED_DEPENDENCY, NOT_APPLICABLE. One failing job never marks another as succeeded; jobs whose
dependency did not succeed are BLOCKED_DEPENDENCY; independent jobs continue. Every job writes <run>/<job>.json; the run writes
REPORT.json + REPORT.md and atomically updates <mm root>/LATEST_RUN.json. Nothing here touches execution, the live config or an active
inference model (artifacts are new immutable candidates; only VALIDATED_SHADOW artifacts on REAL data may move the SHADOW pointer).
"""
from __future__ import annotations

import json
import os
import platform
import time
import traceback
from pathlib import Path

import numpy as np

from . import contracts, data, jobs

VERSION = "PMW-MM-ORCH-1"

GRAPH = [
    ("snapshot", "Snapshot danych + kontrola jakości", "DATA_INFRA", []),
    ("align_mean", "Align Mean - wspólna definicja średniej na wszystkich TF", "DETERMINISTIC_INDICATOR", ["snapshot"]),
    ("kalman", "Kalman crossover - równania, zbieżność K, replay vs inkrementalnie, statystyki", "RECURSIVE_FILTER", ["snapshot"]),
    ("kalman_calibration", "BUZOA: kalibracja Q/R/confirm Kalmana (train->val, test raz)", "OPTIMIZER", ["kalman"]),
    ("breakout_zones", "Breakout zones (VWAP/SMA/SMMA/NONE) + robust volatility vs ATR/std/MAD", "DETERMINISTIC_INDICATOR", ["snapshot"]),
    ("multi_indicator", "Multi-Indicator Strategy - dziennik SHADOW + ablacje", "RULE_STRATEGY", ["snapshot"]),
    ("smc_fvg", "SMC BoS/IDM/FVG - setupy z głębokością cofnięcia 73% (+ jawnie profil 50%)", "RULE_STRATEGY", ["snapshot"]),
    ("tsvp", "Tick Session Volume Profile - rebuild vs inkrementalnie, POC", "VISUALIZATION", ["snapshot"]),
    ("buzoa", "BUZOA vs PSO/DE/Random - funkcje testowe, równy budżet", "OPTIMIZER", []),
    ("hdc", "HDC - kwantyzator(train), akumulatory, korekcje, baseline, null", "ONLINE_LEARNER", ["snapshot"]),
    ("gpr", "GPR Matérn 3/2 - walk-forward, kalibracja 1/2 sigma, baseline", "TRAINABLE", ["snapshot"]),
    ("event_engine", "Event engine GRU + state stack + korelacja (+STFS, ablacje, baseline)", "TRAINABLE", ["snapshot"]),
    ("stfs", "STFS - porównanie z/bez na tych samych splitach", "TRAINABLE", ["event_engine"]),
    ("ste_flownet", "STE-FlowNet (adaptacja) - ablacje, baseline", "TRAINABLE", ["snapshot"]),
    ("mathbench", "Math fidelity - eksport float64/ONNX + kontrole Python", "BENCHMARK", []),
    ("fusion_board", "Tablica dowodów (bez łączenia wyników)", "DATA_INFRA", ["align_mean", "kalman", "breakout_zones", "multi_indicator", "smc_fvg", "gpr"]),
]
PROFILES = {"quick": {"m5_bars": 6000, "m1_bars": 24000, "epochs": 3, "gpr_step": 24, "buzoa_evals": 60, "bench_budget": 400, "hdc_D": 1024},
            "standard": {"m5_bars": None, "m1_bars": 160000, "epochs": 10, "gpr_step": 6, "buzoa_evals": 200, "bench_budget": 2000, "hdc_D": 4096}}


class Ctx:
    def __init__(self, inst: str, snap: data.Snapshot, out: Path, profile: str, seed: int, cancel_file: Path | None):
        self.inst, self.snap, self.out, self.profile, self.prof, self.seed = inst, snap, out, profile, PROFILES[profile], seed
        self.cancel_file = cancel_file
        self.results: dict = {}
        self.synthetic = snap.data_kind != "REAL_USER_DATA"
        self.lines: list[str] = []

    def cancel(self) -> bool:
        return bool(self.cancel_file and self.cancel_file.exists())

    def log(self, msg: str):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        self.lines.append(line)
        print(line, flush=True)

    def bars(self, tf: str):
        b = self.snap.bars.get(tf)
        if b is None:
            return None
        lim = self.prof["m5_bars"] if tf != "M1" else self.prof["m1_bars"]
        return b.slice(max(0, len(b) - lim), len(b)) if lim else b


def _write(p: Path, obj) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=_jsonable), encoding="utf-8")
    os.replace(tmp, p)


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def run(dataset_dir: str, inst: str, out_dir: str, profile: str = "standard", only: list[str] | None = None, seed: int = 20261025,
        cancel_file: str | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = contracts.new_id("MMRUN")
    t0 = time.time()
    try:
        snap = data.open_snapshot(dataset_dir, ("M1", "M5", "M15", "M30"))
    except Exception as exc:  # noqa: BLE001
        rep = {"run_id": run_id, "status": "BLOCKED_DATA_QUALITY", "reason": f"{type(exc).__name__}: {exc}"[:300], "jobs": {}}
        _write(out / "REPORT.json", rep)
        return rep
    ctx = Ctx(inst, snap, out, profile, seed, Path(cancel_file) if cancel_file else None)
    status: dict[str, dict] = {}
    for jid, title, cat, deps in GRAPH:
        status[jid] = {"id": jid, "title": title, "category": cat, "deps": deps, "status": "QUEUED"}
    for jid, title, cat, deps in GRAPH:
        st = status[jid]
        if only and jid not in only and jid != "snapshot":
            st.update(status="NOT_APPLICABLE", reason="nie wybrano w planie")
            continue
        if ctx.cancel():
            st.update(status="CANCELLED")
            continue
        bad = [d for d in deps if status[d]["status"] != "SUCCEEDED"]
        if bad:
            st.update(status="BLOCKED_DEPENDENCY", reason="zależność nie zakończona sukcesem: " + ", ".join(f"{d}={status[d]['status']}" for d in bad))
            continue
        st.update(status="RUNNING", started_at=time.time())
        ctx.log(f"[{jid}] {title}")
        try:
            res = getattr(jobs, "job_" + jid)(ctx)
        except Exception as exc:  # noqa: BLE001 - one job never stops the others
            res = {"status": "FAILED", "reason": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
        res.setdefault("status", "SUCCEEDED")
        res["data_kind"] = snap.data_kind
        ctx.results[jid] = res
        st.update(status=res["status"], finished_at=time.time(), duration_s=round(time.time() - st["started_at"], 2), reason=res.get("reason"),
                  training_executed=bool(res.get("training_executed")), validation_passed=bool(res.get("validation_passed")),
                  artifact_id=res.get("artifact_id"), gates=res.get("gates"))
        _write(out / f"{jid}.json", res)
        ctx.log(f"[{jid}] -> {res['status']}" + (f" ({res.get('reason')})" if res.get("reason") else ""))
    rep = {"run_id": run_id, "version": VERSION, "instrument": inst, "profile": profile, "seed": seed, "started_at": t0, "finished_at": time.time(),
           "snapshot": snap.lineage(), "jobs": status, "status": _run_status(status, ctx.cancel()),
           "environment": {"python": platform.python_version(), "numpy": np.__version__, "platform": platform.platform()},
           "safety": {"orders_sent": 0, "execution_paths_imported": False, "shadow_only": True,
                      "promotion": "tylko VALIDATED_SHADOW na REAL_USER_DATA przesuwa wskaźnik SHADOW; brak wskaźnika LIVE"},
           "log": ctx.lines[-400:]}
    _write(out / "REPORT.json", rep)
    (out / "REPORT.md").write_text(markdown(rep), encoding="utf-8")
    from . import artifacts
    _write(artifacts.root(inst) / "LATEST_RUN.json", {k: v for k, v in rep.items() if k != "log"} | {"run_dir": str(out)})
    return rep


def _run_status(status: dict, cancelled: bool) -> str:
    """CANCELLED > FAILED > BLOCKED_DATA_QUALITY (snapshot rejected) > FINISHED_WITH_BLOCKED (some job blocked) > FINISHED."""
    if cancelled:
        return "CANCELLED"
    if any(s["status"] == "FAILED" for s in status.values()):
        return "FAILED"
    if status["snapshot"]["status"] == "BLOCKED_DATA_QUALITY":
        return "BLOCKED_DATA_QUALITY"
    return "FINISHED_WITH_BLOCKED" if any(s["status"].startswith("BLOCKED") for s in status.values()) else "FINISHED"


def markdown(rep: dict) -> str:
    L = [f"# Master models – run {rep['run_id']}", "", f"Instrument {rep['instrument']}, profil {rep['profile']}, dane "
         f"**{rep['snapshot']['data_kind']}** ({rep['snapshot']['snapshot_id']}, {rep['snapshot'].get('actual_range_utc')}).", "",
         "| Zadanie | Kategoria | Status | Trening | Walidacja | Artefakt | Powód |", "|---|---|---|---|---|---|---|"]
    for j in rep["jobs"].values():
        L.append(f"| {j['id']} | {j['category']} | {j['status']} | {'tak' if j.get('training_executed') else '-'} | "
                 f"{'PASS' if j.get('validation_passed') else '-'} | {j.get('artifact_id') or '-'} | {(j.get('reason') or '')[:160]} |")
    L += ["", "Brak wysłanych zleceń; tryb SHADOW/OBSERVE. Wyniki na danych SYNTHETIC_TEST są testem technicznym, nie dowodem przewagi."]
    return "\n".join(L) + "\n"
