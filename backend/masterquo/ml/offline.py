"""Offline legacy ML training of ONE instrument from a training export (no running bot, no orders).

dataset (M1/M5/M15/H1/H4/D1 CSV of the exact broker symbol) -> backfill replay of S01-S12 with the instrument's symbol
(APPROX labels, own database of the instrument) -> immutable snapshot -> DT + XGBoost trainer (same code as the bot's job)
-> registry of that instrument. include_approx is a parameter of THIS job only (config ml.use_backfill_approx is never
written). Models trained on APPROX labels are stored and evaluated but never promoted to champion (RESEARCH_APPROX).
"""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..db.database import dumps
from ..timeutil import iso, utcnow

UTC = timezone.utc
NEED = ("M1", "M5", "M15", "H1", "H4", "D1")
SEC = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


def load_dataset(ds: Path, days: int | None = None) -> tuple[dict, dict]:
    meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    prefix = meta.get("file_prefix") or "XAUUSD"
    point = float(meta["spec"].get("point") or meta["tick_size"])
    data = {}
    for tf in NEED:
        p = ds / f"{prefix}_{tf}.csv"
        if not p.exists():
            raise FileNotFoundError(f"DATASET_MISSING_{tf}")
        rows = []
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                op = datetime.fromisoformat(r["time_open_utc"].replace("Z", "+00:00"))
                rows.append({"open_utc": r["time_open_utc"], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]),
                             "tv": int(float(r["tick_volume"] or 0)), "available_at": iso(op + timedelta(seconds=SEC[tf])),
                             "spread_points": float(r["spread_points"]) if r.get("spread_points") not in (None, "") else None, "closed": True})
        data[tf] = rows
    if days:                                             # tail of the history (+30 days warm-up), never a random subset
        last = datetime.fromisoformat(data["M15"][-1]["open_utc"].replace("Z", "+00:00"))
        lo = iso(last - timedelta(days=days + 30))
        data = {tf: [b for b in rows if b["open_utc"] >= lo] for tf, rows in data.items()}
    return data, dict(meta, _point=point)


def cost_of(meta: dict, commission: float | None) -> dict:
    """Commission per lot side (account money) -> price units per unit volume via the contract size. Unknown -> flag
    COMMISSION_UNKNOWN (samples become COST_UNKNOWN and are not trained on) - never silently 0."""
    spec = meta["spec"]
    flags = ["SPREAD_FROM_BAR_SPREAD_FIELD"]
    src = "USER_ARGUMENT_OR_BOT_CONFIG" if commission is not None else (meta.get("costs") or {}).get("source", "UNKNOWN")
    per_lot = commission if commission is not None else (meta.get("costs") or {}).get("commission_per_lot_side")
    cs = float(spec.get("trade_contract_size") or 0)
    if meta.get("account_currency") and meta.get("quote_currency") and meta["account_currency"] != meta["quote_currency"]:
        flags.append(f"ACCOUNT_CCY_{meta['account_currency']}_NE_QUOTE_{meta['quote_currency']}_CONVERSION_APPROX")
    if per_lot is None or cs <= 0:
        flags.append("COMMISSION_UNKNOWN")
        comm = 0.0
    else:
        comm = float(per_lot) / cs
    return {"spread": 0.0, "slippage": 0.0, "commission": comm, "flags": flags, "commission_source": src, "commission_per_lot_per_side": per_lot,
            "point": meta["_point"]}


def train(inst: str, dataset: Path, *, include_approx: bool = True, days: int = 180, commission: float | None = None, threads: int = 2,
          log=print) -> dict:
    import mq_instruments
    from ..config import ConfigStore
    from . import backfill, trainer
    from .dataset import SampleStore
    from .registry import Registry
    from .router import ml_store
    inst = mq_instruments.current(inst)
    data, meta = load_dataset(dataset, days)
    if meta.get("instrument", "XAUUSD") != inst:
        return {"status": "FAILED", "reason": f"INSTRUMENT_MISMATCH:{meta.get('instrument')}!={inst}"}
    synthetic = meta.get("data_kind") != "REAL_USER_DATA"
    db, root = ml_store(inst)
    for sub in ("models", "snapshots", "jobs"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    if commission is None and (meta.get("costs") or {}).get("commission_per_lot_side") is None and inst == "XAUUSD":
        commission = ConfigStore().get().scalp.commission_per_lot_side     # the bot's XAUUSD setting (package 0.50) - never used for BTC
    cost = cost_of(meta, commission)
    feed = f"OFFLINE_{meta.get('dataset_id') or dataset.name}"
    t0 = time.time()
    log(f"backfill {inst} ({meta['symbol']}): {len(data['M15'])} M15, koszty {cost['commission_source']} {cost['commission_per_lot_per_side']}")
    bf = backfill.run(db, data, feed=feed, synthetic=synthetic, cost=cost, symbol=meta["symbol"], warmup_days=30,
                      progress=lambda p: log(f"backfill krok {p['step']}/{p['steps']}, próbki {p['created']}"))
    store = SampleStore(db)
    c = ConfigStore().get().ml
    cnt = store.counts(include_approx, synthetic)
    out = {"instrument": inst, "symbol": meta["symbol"], "dataset_id": meta.get("dataset_id"), "backfill": bf, "counts": cnt, "costs": cost,
           "include_approx": include_approx, "db": str(db.path), "root": str(root)}
    if cnt["labeled"] < 4 * c.min_block_samples:
        out.update(status="INSUFFICIENT_DATA", reason=f"etykiet {cnt['labeled']} < {4 * c.min_block_samples} (4 bloki walidacji)")
        return out
    snap = store.snapshot(root / "snapshots", include_approx=include_approx, synthetic=synthetic)
    reg = Registry(db, root / "models")
    jcfg = {k: getattr(c, k) for k in ("embargo_minutes", "min_block_samples", "min_block_per_class", "dt_tuning_budget", "xgb_tuning_budget",
                                       "xgb_max_trees", "xgb_device", "random_state")}
    jcfg["xgb_threads"] = threads
    jcfg["promotion"] = c.promotion.model_dump()
    job_id = "OFF-" + utcnow().strftime("%Y%m%dT%H%M%S") + "-" + inst
    db.execute("INSERT INTO ml_jobs(job_id, kind, status, created_at, started_at, snapshot_id, detail_json) VALUES (?,?,?,?,?,?,?)",
               (job_id, "TRAIN", "RUNNING", iso(utcnow()), iso(utcnow()), snap["snapshot_id"],
                dumps({"initiated_by": "TRAINING_INSTALLER", "rows": snap["rows"], "include_approx": include_approx, "instrument": inst})))
    res = trainer.run(snap["path"], jcfg, str(root / "models"), reg.last_test_end(), lambda ph: log(f"ML {inst}: {ph}"))
    (root / "jobs" / f"{job_id}.report.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    if res.get("status") != "DONE":
        db.execute("UPDATE ml_jobs SET status=?, finished_at=? WHERE job_id=?", (res.get("status") or "FAILED", iso(utcnow()), job_id))
        out.update(status=res.get("status") or "FAILED", reason=res.get("reason") or res.get("reasons"), job_id=job_id)
        return out
    approx_used = include_approx and snap["rows"] > 0
    decisions = reg.register(res, snap["snapshot_id"], jcfg["promotion"], allow_promotion=not approx_used and not synthetic)
    db.execute("UPDATE ml_jobs SET status='DONE', finished_at=?, detail_json=? WHERE job_id=?",
               (iso(utcnow()), dumps({"decisions": decisions, "instrument": inst, "include_approx": include_approx}), job_id))
    out.update(status="DONE", job_id=job_id, snapshot=snap, decisions=decisions, champion=reg.champion_id,
               models={m: {"family": d["family"], "passed_rules": d["passed"], "reasons": d["reasons"]} for m, d in decisions.items()},
               elapsed_s=round(time.time() - t0, 1),
               role=("FIXTURE_ONLY" if synthetic else "RESEARCH_APPROX" if approx_used else "ELIGIBLE_FOR_CHAMPION"))
    return out
