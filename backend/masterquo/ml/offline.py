"""Offline legacy ML training of ONE instrument from a training export (no running bot, no orders).

dataset (M1/M5/M15/H1/H4/D1 CSV of the exact broker symbol) -> backfill replay of S01-S12 with the instrument's symbol
(APPROX labels, own database of the instrument) -> immutable snapshot -> DT + XGBoost trainer (same code as the bot's job)
-> registry of that instrument. include_approx is a parameter of THIS job only (config ml.use_backfill_approx is never
written). Models trained on APPROX labels are stored and evaluated but never promoted to champion (RESEARCH_APPROX); the rule is
training/promotion.ml_champion_policy, shared with the bot's own training job (1.46 D6).
1.46 w2: labels use the bot's label-cost function (labels.label_cost: slippage stress, commission through the tick value - I0048) and
the snapshot is the run's own dataset only (its backfill feed + time window, composition in the manifest - I0061); the bot's live HIGH
samples are trained by the bot's own job, not here.
"""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..db.database import dumps
from ..timeutil import iso, parse_iso, utcnow

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


WARMUP_DAYS = 30


def run_scope(data: dict, feed: str, warmup_days: int = WARMUP_DAYS) -> dict:
    """1.46 w2 (I0061): the training set of an offline run = the samples of THIS dataset only - its own backfill feed (BACKFILL:<feed>)
    and the decision-time window the backfill can produce from the loaded bars (first M15 bar + warm-up .. last M15 bar). Was: every
    sample of the instrument's database (other exports of the same market as separate samples, the bot's live HIGH samples, samples of
    an earlier run with a longer --days)."""
    m15 = data.get("M15") or []
    since = until = None
    if m15:
        since = iso(parse_iso(m15[0]["available_at"]) + timedelta(days=warmup_days))
        until = m15[-1]["available_at"]
    return {"feed_ids": [f"BACKFILL:{feed}"], "since": since, "until": until}


def _positive(v) -> float | None:
    import math
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def cost_of(meta: dict, commission: float | None, *, slippage_points: float | None = None) -> dict:
    """Label costs of the offline backfill - the SAME function as the bot's collector (labels.label_cost, 1.46 w2 I0048; was: slippage 0
    and commission / contract size, so offline samples had a higher net_R than the bot's samples of the same setups):
    * slippage = costs.slippage_stress_points (the user's config, as live; `slippage_points` overrides) x point on fill and stop exits;
    * commission per lot side (account money) -> price units per unit volume with the value of a 1.0 price move per lot =
      trade_tick_value / trade_tick_size of the export (the broker's own conversion, as trainhub 1.46); without them the contract size,
      flagged exactly like the bot (PRICE_VALUE_FROM_CONTRACT_SIZE_..., plus ACCOUNT_CCY_..._CONVERSION_APPROX when the currencies differ);
    * spread from every bar's spread field (backfill._spread); unknown commission -> COMMISSION_UNKNOWN (sample COST_UNKNOWN), never 0."""
    from . import labels as lb
    spec = meta.get("spec") or {}
    flags = ["SPREAD_FROM_BAR_SPREAD_FIELD"]
    src = "USER_ARGUMENT_OR_BOT_CONFIG" if commission is not None else (meta.get("costs") or {}).get("source", "UNKNOWN")
    per_lot = commission if commission is not None else (meta.get("costs") or {}).get("commission_per_lot_side")
    if slippage_points is None:
        from ..config import ConfigStore
        slippage_points = ConfigStore().get().costs.slippage_stress_points
    tv, ts = _positive(spec.get("trade_tick_value")), _positive(spec.get("trade_tick_size"))
    if tv and ts:
        value_1 = tv / ts
        flags.append("PRICE_VALUE_FROM_TICK_VALUE")
    else:
        value_1 = _positive(spec.get("trade_contract_size"))
        flags.append(lb.PRICE_VALUE_FLAG_CONTRACT)
        if meta.get("account_currency") and meta.get("quote_currency") and meta["account_currency"] != meta["quote_currency"]:
            flags.append(f"ACCOUNT_CCY_{meta['account_currency']}_NE_QUOTE_{meta['quote_currency']}_CONVERSION_APPROX")
    out = lb.label_cost(spread=0.0, point=meta.get("_point"), slippage_points=slippage_points, per_lot=per_lot, value_1=value_1, flags=flags,
                        commission_source=src)
    out["point"] = meta.get("_point")
    return out


def train(inst: str, dataset: Path, *, include_approx: bool = True, days: int = 180, commission: float | None = None, threads: int = 2,
          log=print, activate: bool = True) -> dict:
    """activate=False (1.46 D7: `training ml-offline --no-activate`, profile TEST_INSTALACJI): models are evaluated and stored, the current
    champion stays. The champion rule is the one shared with the bot's job (training/promotion.ml_champion_policy)."""
    import mq_instruments
    from ..config import ConfigStore
    from ..training.promotion import approx_rows_in_snapshot, ml_champion_policy
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
    cost = cost_of(meta, commission, slippage_points=ConfigStore().get().costs.slippage_stress_points)
    feed = f"OFFLINE_{meta.get('dataset_id') or dataset.name}"
    t0 = time.time()
    log(f"backfill {inst} ({meta['symbol']}): {len(data['M15'])} M15, koszty {cost['commission_source']} {cost['commission_per_lot_per_side']}")
    bf = backfill.run(db, data, feed=feed, synthetic=synthetic, cost=cost, symbol=meta["symbol"], warmup_days=WARMUP_DAYS,
                      progress=lambda p: log(f"backfill krok {p['step']}/{p['steps']}, próbki {p['created']}"),
                      cfg=ConfigStore().get().active)          # 1.46: the user's thresholds / regime / tracker settings (was package defaults)
    store = SampleStore(db)
    c = ConfigStore().get().ml
    scope = run_scope(data, feed)
    cnt = store.counts(include_approx, synthetic, **scope)
    out = {"instrument": inst, "symbol": meta["symbol"], "dataset_id": meta.get("dataset_id"), "backfill": bf, "counts": cnt, "costs": cost,
           "include_approx": include_approx, "db": str(db.path), "root": str(root), "scope": scope}
    if cnt["labeled"] < 4 * c.min_block_samples:
        why = f"etykiet {cnt['labeled']} < {4 * c.min_block_samples} (4 bloki walidacji) w zbiorze tego runu ({scope['feed_ids'][0]})"
        if not include_approx:
            why += " – próbki backfillu są APPROX, a --no-approx je wyklucza (próbki HIGH bota uczy zadanie treningu w bocie)"
        out.update(status="INSUFFICIENT_DATA", reason=why)
        return out
    snap = store.snapshot(root / "snapshots", include_approx=include_approx, synthetic=synthetic, **scope)
    reg = Registry(db, root / "models")
    jcfg = {k: getattr(c, k) for k in ("embargo_minutes", "min_block_samples", "min_block_per_class", "dt_tuning_budget", "xgb_tuning_budget",
                                       "xgb_max_trees", "xgb_device", "random_state")}
    jcfg["xgb_threads"] = threads
    jcfg["promotion"] = c.promotion.model_dump()
    job_id = "OFF-" + utcnow().strftime("%Y%m%dT%H%M%S") + "-" + inst
    db.execute("INSERT INTO ml_jobs(job_id, kind, status, created_at, started_at, snapshot_id, detail_json) VALUES (?,?,?,?,?,?,?)",
               (job_id, "TRAIN", "RUNNING", iso(utcnow()), iso(utcnow()), snap["snapshot_id"],
                dumps({"initiated_by": "TRAINING_INSTALLER", "rows": snap["rows"], "include_approx": include_approx, "instrument": inst})))
    try:
        res = trainer.run(snap["path"], jcfg, str(root / "models"), reg.last_test_end(), lambda ph: log(f"ML {inst}: {ph}"))
    except Exception as exc:          # 1.46: an exception of the trainer left the ml_jobs row RUNNING (until an MLService restart)
        db.execute("UPDATE ml_jobs SET status='FAILED', finished_at=?, detail_json=? WHERE job_id=?",
                   (iso(utcnow()), dumps({"initiated_by": "TRAINING_INSTALLER", "rows": snap["rows"], "include_approx": include_approx, "instrument": inst,
                                          "reason": f"{type(exc).__name__}: {exc}"[:300]}), job_id))
        raise
    (root / "jobs" / f"{job_id}.report.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    if res.get("status") != "DONE":
        db.execute("UPDATE ml_jobs SET status=?, finished_at=? WHERE job_id=?", (res.get("status") or "FAILED", iso(utcnow()), job_id))
        out.update(status=res.get("status") or "FAILED", reason=res.get("reason") or res.get("reasons"), job_id=job_id)
        return out
    # 1.46 D6: APPROX = the snapshot really holds APPROX labels (was: include_approx and any row - the same in practice, the backfill
    # writes APPROX samples); one policy with the bot's job; D7: activate=False keeps the champion
    approx_used = approx_rows_in_snapshot(db, snap) > 0
    pol = ml_champion_policy(approx=approx_used, synthetic=synthetic, activate=activate)
    decisions = reg.register(res, snap["snapshot_id"], jcfg["promotion"], policy=pol)
    db.execute("UPDATE ml_jobs SET status='DONE', finished_at=?, detail_json=? WHERE job_id=?",
               (iso(utcnow()), dumps({"decisions": decisions, "instrument": inst, "include_approx": include_approx, "promotion_policy": pol}), job_id))
    out.update(status="DONE", job_id=job_id, snapshot=snap, decisions=decisions, champion=reg.champion_id,
               models={m: {"family": d["family"], "passed_rules": d["passed"], "reasons": d["reasons"]} for m, d in decisions.items()},
               elapsed_s=round(time.time() - t0, 1), role=pol["role"], activate=activate, promotion_policy=pol)
    return out
