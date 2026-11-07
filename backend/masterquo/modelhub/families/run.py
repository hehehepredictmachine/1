"""Family training job runner (separate process): python -m masterquo.modelhub.families.run --family F --instrument I --profile P
--job-file <status.json>. Writes progress / result to the status file atomically; the parent can cancel (terminate) it and detects an
orphan (status RUNNING with a dead pid). Training never activates or promotes an artifact."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

from . import base as B

BUDGETS = {"smoke": {"max_rows": 3000, "timeout_s": 900}, "research": {"max_rows": 20000, "timeout_s": 3600},
           "full": {"max_rows": 200000, "timeout_s": 6 * 3600}}


def _status(p: Path, **kw):
    cur = B._read(p, {}) or {}
    cur.update(kw, updated_at=time.time())
    B._atomic_json(p, cur)


def load_data(fam, inst: str, cfg: dict) -> dict:
    """Training data for a family from the controlled stores (MT5 export Store, book archive, NLP corpus)."""
    from ...marketdata.store import Store
    st = Store()
    man = st.manifest(inst) or {}
    point = float(((man.get("costs") or {}).get("spread") or {}).get("point") or 0.01)
    out = {"instrument": inst, "point": point, "data_kind": man.get("data_kind") or "UNKNOWN", "symbol": man.get("symbol")}
    kind = fam.DATA.get("kind")
    if kind == "BARS":
        out["bars"] = B.bars_from_store(st, inst, fam.DATA.get("tf") or fam.TF)
    elif kind == "MULTI_SERIES":
        if fam.ID == "PAIR_COINT":
            pair = (cfg.get("pairs") or [None])[0]
            out["pair"] = pair
            if pair:
                out["pair_bars"] = [B.bars_from_store(st, s, fam.TF) for s in pair]
        else:
            uni = cfg.get("basket") or []
            out["basket"] = uni
            if len(uni) >= 3:
                out["basket_bars"] = [B.bars_from_store(st, s, fam.TF) for s in uni]
    elif kind == "L2_BOOK":
        out["books"] = books_from_archive(cfg.get("indicators_db"), out.get("symbol"))
    elif kind == "TEXT":
        from .nlp import load_corpus
        out["corpus"] = load_corpus()
    return out


def books_from_archive(db_path, symbol) -> list[dict]:
    import sqlite3
    if not db_path or not Path(db_path).exists():
        return []
    con = sqlite3.connect(str(db_path))
    q = "SELECT t, bids, asks FROM book_snapshots" + (" WHERE symbol=?" if symbol else "") + " ORDER BY t"
    rows = con.execute(q, (symbol,) if symbol else ()).fetchall()
    con.close()
    return [{"t": float(t), "bids": [tuple(x) for x in json.loads(b)], "asks": [tuple(x) for x in json.loads(a)]} for t, b, a in rows]


def train(fid: str, inst: str, profile: str, cfg: dict, status_file: Path | None = None, data: dict | None = None, store: B.Store | None = None) -> dict:
    from . import registry
    fam = registry()[fid]
    sf = status_file
    if sf:
        _status(sf, state="RUNNING", pid=os.getpid(), family=fid, instrument=inst, profile=profile, stage="dane")
    impl, why = fam.implementation()
    if impl != "AVAILABLE":
        res = {"state": "BLOCKED", "reason": why, "family": fid}
        if sf:
            _status(sf, **res)
        return res
    if fid in ("TH_RF", "TH_XGB", "TH_SVM"):
        res = {"state": "DELEGATED", "reason": "trening w trainhub: python -m masterquo trainhub train --instrument "
                                              f"{inst} --models {fid} --profile {profile}", "family": fid}
        if sf:
            _status(sf, **res)
        return res
    data = data if data is not None else load_data(fam, inst, cfg)
    ok, why = fam.validate_data(data)
    if not ok:
        res = {"state": "BLOCKED", "reason": why, "family": fid}
        if sf:
            _status(sf, **res)
        return res
    store = store or B.Store()
    rid, tmp = store.new_run(fid, inst)
    budget = dict(BUDGETS.get(profile, BUDGETS["smoke"]), profile=profile)
    t0 = time.time()
    try:
        if sf:
            _status(sf, stage=fam.FIT_LABEL, run_id=rid)
        parts = fam.fit(data, cfg, tmp, budget)
    except B.Unavailable as u:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        res = {"state": "FAILED" if u.state in ("ERROR",) else "BLOCKED", "reason": u.reason, "family": fid, "validation_state": u.state}
        if sf:
            _status(sf, **res)
        return res
    except Exception as exc:  # noqa: BLE001
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        res = {"state": "FAILED", "reason": f"{type(exc).__name__}: {exc}"[:400], "trace": traceback.format_exc()[-1500:], "family": fid}
        if sf:
            _status(sf, **res)
        return res
    bars = data.get("bars") or []
    man = {"name": fam.NAME, "kind": fam.KIND, "task_type": fam.TASK_TYPE, "task": fam.TASK, "unit": fam.UNIT, "tf": fam.TF,
           "horizons": list(fam.HORIZONS), "symbol": data.get("symbol"), "data_kind": data.get("data_kind"), "profile": profile,
           "data": {"rows": len(bars), "hash": B.data_hash(bars) if bars else None, "range": [bars[0]["t"], bars[-1]["t"]] if bars else None,
                    "requirements": fam.data_requirements()},
           "config": cfg, "budget": budget, "seconds": round(time.time() - t0, 2), "deps": B.dep_versions(fam.DEPS),
           "metrics": parts.get("metrics"), "validation": parts.get("validation"), "sample": parts.get("sample"),
           "model_card": {"purpose": fam.TASK, "receivers": list(fam.RECEIVERS), "limits": "ocena na danych historycznych; nie jest obietnicą wyniku",
                          "status": (parts.get("validation") or {}).get("status")}}
    final = store.commit(fid, inst, rid, tmp, man)
    res = {"state": "DONE", "family": fid, "run_id": rid, "dir": str(final), "validation": (parts.get("validation") or {}).get("status")}
    if sf:
        _status(sf, **res)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", required=True)
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--profile", default="smoke", choices=list(BUDGETS))
    ap.add_argument("--job-file")
    ap.add_argument("--config", default="{}")
    a = ap.parse_args(argv)
    res = train(a.family, a.instrument, a.profile, json.loads(a.config), Path(a.job_file) if a.job_file else None)
    print(json.dumps({k: v for k, v in res.items() if k != "trace"}, ensure_ascii=False))
    return 0 if res["state"] in ("DONE", "DELEGATED") else 3


if __name__ == "__main__":
    sys.exit(main())
