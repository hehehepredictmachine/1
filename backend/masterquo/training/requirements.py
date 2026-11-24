"""Data each training task reads from an MT5 export (taken from the trainers' code, not guessed) and the check of ONE export
against them: model -> required timeframes / ticks -> the exact file read -> range -> rows -> status.

Status per model: GOTOWE (every required file present with the expected columns and rows), BRAK_DANYCH (a required timeframe file
is missing or empty), NIEZGODNY_FORMAT (a file without the expected columns, metadata of another instrument), NIEKOMPLETNY_EKSPORT
(the export did not finish - nothing of it may be used). A model without data is reported, it never pretends to be trained;
models with data can still train. `recommended_rows` are orientation values (warm-up + a chronological holdout), not a guarantee
that the model finds anything."""
from __future__ import annotations

import json
from pathlib import Path

from . import tasks as _T

BAR_COLUMNS = ("time_open_utc", "open", "high", "low", "close", "tick_volume")

# kind -> (title, required TFs, optional TFs, reader in code, recommended rows of the first required TF). arch146 I0131: derived from the one
# task registry (training/tasks.py) - the readiness keys are unchanged ('scalp' for the A/B/C unit); the row order is the one of 1.46.0
# (tasks.REQUIREMENTS_ORDER: master_models before monte_carlo), not the runner order.
REQUIREMENTS: dict[str, dict] = _T.requirements()


def _file_info(p: Path) -> dict:
    """Header, rows, first / last time of one CSV without loading it whole."""
    if not p.exists():
        return {"file": p.name, "exists": False, "rows": 0}
    with p.open("rb") as fh:
        header = fh.readline().decode("utf-8", "replace").strip().split(",")
        first = fh.readline().decode("utf-8", "replace").strip()
        rows = (1 if first else 0) + sum(1 for _ in fh)
        last = first
        if rows > 1:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
            tail = fh.read().decode("utf-8", "replace").strip().splitlines()
            last = tail[-1] if tail else first
    return {"file": p.name, "exists": True, "rows": rows, "columns": header, "first_utc": first.split(",")[0] if first else None,
            "last_utc": last.split(",")[0] if last else None}


def check_dataset(ds: Path, kinds: list[str] | None = None) -> dict:
    """Readiness of every (or the given) training task for this export folder. `kinds` may name readiness keys or task ids (scalp_A ->
    'scalp', alias on input only - the rows keep the readiness key)."""
    from ..forecast.export import dataset_state
    if kinds:
        kinds = [k if k in REQUIREMENTS else (_T.requirements_kind(k) or k) for k in kinds]
    ds = Path(ds)
    state = dataset_state(ds)
    meta = None
    try:
        meta = json.loads((ds / "source_metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    prefix = (meta or {}).get("file_prefix") or (meta or {}).get("instrument") or "XAUUSD"
    ticks = None
    try:
        tm = json.loads((ds / "ticks" / "TICKS_MANIFEST.json").read_text(encoding="utf-8"))
        ticks = {"ticks": tm.get("ticks"), "received_utc": tm.get("received_utc")}
    except (OSError, ValueError):
        pass
    infos: dict[str, dict] = {}
    rows = []
    for kind, rq in REQUIREMENTS.items():
        if kinds and kind not in kinds:
            continue
        tfs = list(rq["required"]) + list(rq["optional"])
        for tf in tfs:
            if tf not in infos:
                infos[tf] = _file_info(ds / f"{prefix}_{tf}.csv")
        files = [{"tf": tf, "required": tf in rq["required"], **infos[tf]} for tf in tfs]
        status, reason = "GOTOWE", "wszystkie wymagane pliki są kompletne"
        if not state["usable"]:
            status, reason = "NIEKOMPLETNY_EKSPORT", f"eksport w stanie {state['state']} – uruchom go ponownie (wznowi pobrane partie)"
        elif meta is None:
            status, reason = "NIEZGODNY_FORMAT", "brak source_metadata.json"
        else:
            missing = [f["tf"] for f in files if f["required"] and not f["rows"]]
            badcols = [f["tf"] for f in files if f["exists"] and f["rows"] and not set(BAR_COLUMNS) <= set(f.get("columns") or [])]
            if badcols:
                status, reason = "NIEZGODNY_FORMAT", f"brak kolumn {list(BAR_COLUMNS)} w {badcols}"
            elif missing:
                status, reason = "BRAK_DANYCH", f"brak świec {missing} – wyeksportuj te interwały"
            else:
                base = next(f for f in files if f["required"])
                if base["rows"] < rq["recommended_rows"]:
                    reason = (f"dane są, ale {base['tf']} ma {base['rows']} świec (< ok. {rq['recommended_rows']} zalecanych) – wynik będzie "
                              "testem technicznym albo INSUFFICIENT_DATA")
        req0 = next((f for f in files if f["required"]), None)
        rows.append({"kind": kind, "title": rq["title"], "required": list(rq["required"]), "optional": list(rq["optional"]),
                     "ticks": rq.get("ticks"), "reader": rq["reader"], "status": status, "reason": reason, "files": files,
                     "samples": req0["rows"] if req0 else 0, "range_utc": [req0.get("first_utc"), req0.get("last_utc")] if req0 else None})
    return {"dataset": str(ds), "export_state": state, "instrument": (meta or {}).get("instrument"), "symbol": (meta or {}).get("symbol"),
            "data_kind": (meta or {}).get("data_kind"), "ticks": ticks, "models": rows,
            "note": "Status opisuje DANE dla modelu, nie jego jakość; model bez danych nie jest trenowany ani oznaczany jako wytrenowany."}
