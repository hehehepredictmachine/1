"""Training job process: python -m masterquo.trainhub.worker <jobs.sqlite> <job_id>. Runs DATASET / TRAIN / EVALUATE / FULL stages for
one instrument, writes progress / result into the job row and logs to stdout (captured into the job's log file). No MT5 connection,
no order path, no configuration writes: it reads the candle store and writes datasets / model packages only."""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    from . import jobs as J
    db = J.connect(Path(argv[0]))
    jid = argv[1]
    job = J.row(db, jid)
    if job is None:
        print(f"brak zadania {jid}")
        return 2
    from ..config import ConfigStore
    from ..marketdata.store import Store
    from . import pipeline as P
    params = job["params"] or {}
    inst = job["instrument"]
    result = job.get("result") or {}
    store = Store()

    def log(msg):
        print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}", flush=True)

    def cancel():
        r = db.execute("SELECT cancel FROM jobs WHERE id=?", (jid,)).fetchone()
        return bool(r and r["cancel"])

    state = {"p": 0.5 if job["kind"] == "FULL" else 0.05}

    def progress(p):
        st = p.get("stage", "")
        if p.get("model"):
            st += f" {p['model']}"
        if p.get("fold"):
            st += f" – konfiguracja {p['config']}/{p['configs']}, fold {p['fold']}/{p['folds']}"
            state["p"] = min(0.97, state["p"] + 0.004)
        J.update(db, jid, stage=st, progress=round(state["p"], 3))
        log(st)

    try:
        cost_cfg = ConfigStore().get().costs
        cfg = P.config(params, store.manifest(inst), cost_cfg)
        log(f"Zadanie {job['kind']} {inst}: {json.dumps({k: cfg[k] for k in ('base_tf', 'horizon', 'k_atr', 'models', 'start', 'end')})}")
        log(f"Koszty: prowizja {cfg['commission_price']:.6f}, poślizg {cfg['slippage_price']:.6f} (cena, round-trip 1 lot); {cfg['cost_status']}")
        if job["kind"] == "EVALUATE":
            key, version = params["model_key"], params["version"]
            J.update(db, jid, stage=f"ocena {key} {version}")
            result["evaluation"] = P.stage_evaluate(store, inst, key, version)
        else:
            J.update(db, jid, stage="walidacja danych", progress=max(state["p"], 0.06))
            result["validation"] = P.stage_validate(store, inst)
            log(f"Walidacja danych: {json.dumps(result['validation'], ensure_ascii=False)[:600]}")
            ds, desc = P.stage_dataset(store, inst, cfg, progress)
            result["dataset"] = {k: desc[k] for k in ("rows_total", "rows_usable", "dropped", "class_counts", "range_utc", "hash", "data_kind")}
            log(f"Dataset: {json.dumps(result['dataset'], ensure_ascii=False)}")
            if job["kind"] in ("TRAIN", "FULL"):
                tr = P.stage_train(store, inst, cfg, progress, cancel, ds=ds, desc=desc)
                result["training"] = {k: v for k, v in tr.items() if k != "dataset"}
                for pk in tr["packages"]:
                    log(f"Zapisano {pk['model_key']} {pk['version']}: holdout log loss {pk['holdout']['log_loss']} (bazowy "
                        f"{pk['holdout']['baseline_log_loss']}), ECE {pk['holdout']['ece']}")
        J.update(db, jid, status="SUCCEEDED", result=result, progress=1.0, finished_at=time.time(), stage="zakończone")
        log("Zakończone. Żaden model nie został aktywowany automatycznie.")
        return 0
    except InterruptedError:
        J.update(db, jid, status="CANCELLED", result=result, finished_at=time.time(), stage="anulowane")
        log("Anulowane.")
        return 3
    except Exception as exc:  # noqa: BLE001
        from .dataset import InsufficientData
        msg = f"{type(exc).__name__}: {exc}"[:800]
        J.update(db, jid, status="FAILED", result=result, error=msg, finished_at=time.time(),
                 stage="za mało danych" if isinstance(exc, InsufficientData) else "błąd")
        log("[BŁĄD] " + msg)
        if not isinstance(exc, (InsufficientData, ValueError)):
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
