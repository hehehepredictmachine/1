"""Family training job runner (separate process): python -m masterquo.modelhub.families.run --family F --instrument I --profile P
--job-file <status.json>. Writes progress / result to the status file atomically; the parent can cancel (terminate) it and detects an
orphan (status RUNNING with a dead pid). Training never activates or promotes an artifact."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

from ...quant import ids as I
from . import base as B

BUDGETS = {"smoke": {"max_rows": 3000, "timeout_s": 900}, "research": {"max_rows": 20000, "timeout_s": 3600},
           "full": {"max_rows": 200000, "timeout_s": 6 * 3600}}


def _status(p: Path, **kw):
    cur = B._read(p, {}) or {}
    cur.update(kw, updated_at=time.time())
    B._atomic_json(p, cur)


def _pos(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _mapped_symbol(inst: str) -> str | None:
    """The broker symbol of the instrument from the configuration (assets.mappings) - the symbol IndicatorService records books under."""
    try:
        from ...config import ConfigStore
        m = ConfigStore().get().assets.mappings.get(inst)
        return (m.broker_symbol or None) if m is not None else None
    except Exception:  # noqa: BLE001 - no readable configuration = unknown symbol (never "all symbols")
        return None


def load_data(fam, inst: str, cfg: dict, bars_file: str | None = None, max_rows: int | None = None) -> dict:
    """Training data for a family from the controlled stores (MT5 export Store, book archive, NLP corpus)."""
    from ...marketdata.store import Store
    st = Store()
    man = st.manifest(inst) or {}
    # 1.46: the point size comes from the broker's symbol spec written by the export (symbol_spec / costs.spread.point) or by the live
    # bars file; missing = None (the families that convert the spread refuse to train) - 1.45.0 assumed 0.01
    point = _pos((man.get("symbol_spec") or {}).get("point")) or _pos(((man.get("costs") or {}).get("spread") or {}).get("point"))
    out = {"instrument": inst, "point": point, "data_kind": man.get("data_kind") or "UNKNOWN", "symbol": man.get("symbol"),
           "source": "MARKETDATA_STORE", "quality_path": str(st.inst_dir(inst) / "quality_report.json")}
    kind = fam.DATA.get("kind")
    if kind == "BARS":
        try:
            out["bars"] = B.bars_from_store(st, inst, fam.DATA.get("tf") or fam.TF)
        except Exception:  # noqa: BLE001 - brak archiwum eksportu
            out["bars"] = []
        if bars_file and len(out["bars"]) < int(fam.DATA.get("min_bars") or 0):    # 1.42.10: świece z MT5 na żywo (archiwum za krótkie)
            try:
                live = json.loads(Path(bars_file).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                live = {}
            if len(live.get("bars") or []) > len(out["bars"]):
                # 1.46: the demo simulator (MarketBridge.synthetic = True) is SYNTHETIC_TEST - it was labelled MT5_LIVE_BRIDGE (= REAL for ASSIST)
                out.update(bars=live["bars"], data_kind="SYNTHETIC_TEST" if live.get("synthetic") is True else "MT5_LIVE_BRIDGE",
                           symbol=live.get("symbol") or out.get("symbol"), point=_pos(live.get("point")) or out.get("point"),
                           source="MT5_LIVE_BRIDGE", quality_path=None)
    elif kind == "MULTI_SERIES":
        if fam.ID == "PAIR_COINT":
            pair = (cfg.get("pairs") or [None])[0]
            out["pair"] = pair
            if pair:
                out["pair_bars"], out["legs_missing"] = _legs(st, pair, fam.TF)
        else:
            uni = cfg.get("basket") or []
            out["basket"] = uni
            if len(uni) >= 3:
                out["basket_bars"], out["legs_missing"] = _legs(st, uni, fam.TF)
    elif kind == "L2_BOOK":
        out["source"], out["quality_path"] = "BOOK_ARCHIVE", None
        # 1.46: without the instrument's broker symbol the query had no WHERE - snapshots of every symbol (XAUUSD and BTC after an
        # instrument switch) were mixed and the label mid_j - mid_i crossed instruments. Symbol: store manifest -> job config ->
        # assets.mappings; none -> no books (BLOCKED with the reason). Only the newest rows within the budget are read (1.45.0 loaded the
        # whole 14-day archive at 1 s, ~6 GB) and only the book levels the features use.
        sym = out.get("symbol") or cfg.get("broker_symbol") or _mapped_symbol(inst)
        out["symbol"] = sym
        if not sym:
            out["books"] = []
            out["books_reason"] = f"brak symbolu brokera dla {inst} (assets.mappings) – snapshoty arkusza nie są mieszane między symbolami"
        else:
            from .micro import BOOK_LEVELS, MIN_SNAPSHOTS
            lim = max(int(max_rows or BUDGETS["smoke"]["max_rows"]), 4 * MIN_SNAPSHOTS)
            out["books"] = books_from_archive(cfg.get("indicators_db"), sym, limit=lim, levels=BOOK_LEVELS)
    elif kind == "TEXT":
        out["source"], out["quality_path"] = "TEXT_CORPUS", None
        from .nlp import corpus_data_kind, load_corpus
        out["corpus"] = load_corpus()
        # 1.46 arch (I0469 / I0470): the provenance of the CORPUS (recorded per record at import), not of the instrument's candle export -
        # a synthetic corpus gave an artifact labelled REAL_USER_DATA whenever the candles were REAL (ASSIST gate, Quant snapshot)
        out["data_kind"] = corpus_data_kind(out["corpus"])
    return out


def _legs(st, symbols, tf: str) -> tuple[list[list[dict]], list[dict]]:
    """1.46 (I0424): the bars of every leg read on its own. A leg without candles in the store or with an unreadable part file is listed
    in legs_missing (validate_data names it -> BLOCKED with the reason) - 1.45 / 1.46.0 raised out of train() for a damaged file (the job
    stayed RUNNING until the dead process was noticed) and reported a missing leg as 'za mało wspólnych świec: 0'."""
    bars, missing = [], []
    for s in symbols:
        try:
            b = B.bars_from_store(st, s, tf)
            why = None if b else "brak świec"
        except Exception as exc:  # noqa: BLE001 - a damaged part file of one leg
            b, why = [], f"nieczytelne dane: {type(exc).__name__}: {exc}"[:200]
        if why:
            missing.append({"symbol": s, "tf": tf, "reason": why})
        bars.append(b)
    return bars, missing


def books_from_archive(db_path, symbol, limit: int | None = None, levels: int | None = None) -> list[dict]:
    """Book snapshots of ONE broker symbol in time order: the newest `limit` rows (all when None), `levels` levels per side."""
    import sqlite3
    if not db_path or not symbol or not Path(db_path).exists():          # 1.46: no symbol -> nothing (never every symbol's rows)
        return []
    con = sqlite3.connect(str(db_path))
    try:
        if limit:
            cur = con.execute("SELECT t, bids, asks FROM book_snapshots WHERE symbol=? ORDER BY t DESC LIMIT ?", (symbol, int(limit)))
        else:
            cur = con.execute("SELECT t, bids, asks FROM book_snapshots WHERE symbol=? ORDER BY t", (symbol,))
        out = [{"t": float(t), "bids": [tuple(x) for x in json.loads(b)[:levels]], "asks": [tuple(x) for x in json.loads(a)[:levels]]}
               for t, b, a in cur]
    finally:
        con.close()
    if limit:
        out.reverse()
    return out


def _dataset_ref(inst: str, data: dict, dm: dict, bars: list) -> dict:
    """arch146 I0064: DatasetRef (training/dataset_ref.py) of the data this run fitted on - source as load_data read it (Store archive,
    live bot bars, book archive, text corpus), hash / range / rows of the fitted slice, data kind and the Store quality report."""
    # 1.46 arch Etap 4: DatasetRef from the L0 leaf (training/dataset_ref.py is its alias)
    from ...contracts import dataset_ref as DR
    from ...marketdata.store import iso
    rng = dm.get("range")
    if rng and all(isinstance(x, (int, float)) for x in rng):
        rng = [iso(float(x)) for x in rng]
    qp = data.get("quality_path")
    return DR.from_bars(inst, source=data.get("source") or ("MARKETDATA_STORE" if bars else "UNKNOWN"), symbol=data.get("symbol"),
                        data_kind=data.get("data_kind"), sha256=dm.get("hash"), range_utc=rng, rows=dm.get("rows"),
                        quality_path=Path(qp) if qp else None)


def delegated(fid: str, inst: str, profile: str) -> str | None:
    """The reason a family is trained OUTSIDE the family store (None = trained here). 1.46 (I0475): SEQ_GRU_EVENT (adapter of the MM
    event model) was missing - `families train --family SEQ_GRU_EVENT` / POST /api/v1/families/SEQ_GRU_EVENT/train ended FAILED
    NotImplementedError (EventGRU has no fit) after creating a .tmp-run directory; train_all and the CLI train-all already skipped it."""
    if fid in I.TRAINHUB_FAMILY_ALIASES:                  # Etap 4: aliases of trainhub:TH_* from quant/ids (was a copied literal)
        return f"trening w trainhub: python -m masterquo trainhub train --instrument {inst} --models {fid} --profile {profile}"
    if fid == I.EVENT_GRU_FAMILY:
        return "trening w Centrum MM (mm/event_engine) – adapter istniejącego modelu zdarzeń, nie jest trenowany w magazynie rodzin"
    return None


def train(fid: str, inst: str, profile: str, cfg: dict, status_file: Path | None = None, data: dict | None = None, store: B.Store | None = None,
          bars_file: str | None = None) -> dict:
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
    why_d = delegated(fid, inst, profile)
    if why_d:                                            # before load_data / new_run: no data read, no .tmp-run directory
        res = {"state": "DELEGATED", "reason": why_d, "family": fid}
        if sf:
            _status(sf, **res)
        return res
    budget = dict(BUDGETS.get(profile, BUDGETS["smoke"]), profile=profile)
    if data is None:
        try:
            data = load_data(fam, inst, cfg, bars_file, max_rows=budget["max_rows"])
        except Exception as exc:  # noqa: BLE001 - 1.46 (I0424): a data error is BLOCKED with its reason, never an exception out of the job
            res = {"state": "BLOCKED", "reason": f"dane: {type(exc).__name__}: {exc}"[:400], "family": fid}
            if sf:
                _status(sf, **res)
            return res
    ok, why = fam.validate_data(data)
    if not ok:
        res = {"state": "BLOCKED", "reason": why, "family": fid}
        if sf:
            _status(sf, **res)
        return res
    store = store or B.Store()
    rid, tmp = store.new_run(fid, inst)
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
    allbars = data.get("bars") or []
    # 1.46: every bar family fits on the newest budget["max_rows"] bars (fit slices bars[-max_rows:]) - rows / hash / range describe that
    # slice, not the whole archive (1.45.0: the provenance of the model card did not identify the training set); the archive size is
    # kept separately (rows_available)
    bars = allbars[-int(budget["max_rows"]):] if budget.get("max_rows") else allbars
    man = {"name": fam.NAME, "kind": fam.KIND, "task_type": fam.TASK_TYPE, "task": fam.TASK, "unit": fam.UNIT, "tf": fam.TF,
           "horizons": list(fam.HORIZONS), "symbol": data.get("symbol"), "data_kind": data.get("data_kind"), "profile": profile,
           "data": {"rows": len(bars), "hash": B.data_hash(bars) if bars else None, "range": [bars[0]["t"], bars[-1]["t"]] if bars else None,
                    "rows_available": len(allbars), "requirements": fam.data_requirements()},
           "config": cfg, "budget": budget, "seconds": round(time.time() - t0, 2), "deps": B.dep_versions(fam.DEPS),
           "metrics": parts.get("metrics"), "validation": parts.get("validation"), "sample": parts.get("sample"),
           "model_card": {"purpose": fam.TASK, "receivers": list(fam.RECEIVERS), "limits": "ocena na danych historycznych; nie jest obietnicą wyniku",
                          "status": (parts.get("validation") or {}).get("status")}}
    man["dataset_ref"] = _dataset_ref(inst, data, man["data"], bars)    # arch146 I0064: lineage of the exact training slice
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
    ap.add_argument("--bars-file")
    a = ap.parse_args(argv)
    res = train(a.family, a.instrument, a.profile, json.loads(a.config), Path(a.job_file) if a.job_file else None, bars_file=a.bars_file)
    print(json.dumps({k: v for k, v in res.items() if k != "trace"}, ensure_ascii=False))
    return 0 if res["state"] in ("DONE", "DELEGATED") else 3


if __name__ == "__main__":
    sys.exit(main())
