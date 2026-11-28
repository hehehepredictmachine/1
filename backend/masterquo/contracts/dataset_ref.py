"""DatasetRef (PMW-DATASET-REF-1, arch146 I0064): ONE description of the data a model was trained on, written into the manifest of every
artifact (lineage) - the trainers of one instrument read five+ different sources (runner export folder, marketdata Store, the live bot bars,
the Quant ledger ...) with different quality reports and nothing named them the same way.

This step only DESCRIBES the source each trainer already reads - no trainer reads anything else, no training data change. Unifying the
sources (e.g. the runner exporting into the marketdata Store) is a separate decision.

Fields: version, instrument, symbol, source (MT5_EXPORT_RUN | MARKETDATA_STORE | MT5_LIVE_BRIDGE | ...), location (folder / store), range_utc
[first, last], sha256 (identity of the exact data: files / rows hash), data_kind (as the source names it: REAL_USER_DATA, REAL, SYNTHETIC,
SYNTHETIC_TEST, MT5_LIVE_BRIDGE ...), quality {report, status} and optional rows / files. Pure functions over files already on disk.

Coverage of this step (krok 1 - the rest is a separate item, not done here):
  * runner (`masterquo training run`): the export task and every model task finished on that export carry `dataset_ref` in the RUN STATE
    (training/runs/<run_id>/state.json) - NOT in the registries / manifests of the single trainers (forecast, scalp, lab, ...); the lineage of
    such an artifact is reached through its run_id;
  * trainhub: data_manifest.json of every package (the marketdata Store + quality_report.json; included in the package checksums);
  * model families: manifest.json of every run (Store / live bot bars / sheet archive / NLP corpus);
  * NOT covered yet: Legacy ML (snapshot in the bot), Quant (ledger), SDformer (live H1 context), Granite and the per-trainer manifests of the
    runner tasks.

1.46 arch Etap 4: moved here from training/dataset_ref.py (alias zgodności there) - a record shape shared by every trainer (producer) and
every reader of a manifest, stdlib only, so trainhub / model families write it without an upward import into the training orchestrator.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

VERSION = "PMW-DATASET-REF-1"


def _read(p: Path) -> dict | None:
    try:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _sha_of(obj) -> str | None:
    if not obj:
        return None
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def make(*, instrument: str, source: str, sha256: str | None, data_kind: str | None, range_utc=None, symbol: str | None = None,
         location: str | None = None, quality: dict | None = None, rows: int | None = None, files: dict | None = None) -> dict:
    return {"version": VERSION, "instrument": instrument, "symbol": symbol, "source": source, "location": location,
            "range_utc": list(range_utc) if range_utc else None, "sha256": sha256, "data_kind": data_kind,
            "quality": quality or {"report": None, "status": None}, "rows": rows, "files": files}


def from_export_dir(ds: Path) -> dict | None:
    """The runner's explicit export folder (training/datasets/<inst>/<run>): source_metadata.json + DATA_QUALITY_REPORT.json."""
    ds = Path(ds)
    meta = _read(ds / "source_metadata.json")
    if not meta:
        return None
    dq = _read(ds / "DATA_QUALITY_REPORT.json") or {}
    files = meta.get("files_sha256") if isinstance(meta.get("files_sha256"), dict) else None
    suff = (dq.get("sufficiency") or {}).get("status") if isinstance(dq.get("sufficiency"), dict) else None
    return make(instrument=meta.get("instrument"), symbol=meta.get("symbol"), source="MT5_EXPORT_RUN", location=str(ds),
                range_utc=meta.get("range_utc"), sha256=_sha_of(files) or meta.get("dataset_id"), data_kind=meta.get("data_kind"),
                quality={"report": str(ds / "DATA_QUALITY_REPORT.json") if dq else None, "status": suff}, files=files)


def from_store(inst: str, store_manifest: dict, *, sha256: str | None, quality_path: Path | None = None, range_utc=None,
               rows: int | None = None) -> dict:
    """The marketdata Store (data/marketdata/<inst>, quality_report.json) - trainhub, families, Studio."""
    q = _read(quality_path) if quality_path else None
    st = None
    if q:
        bad = [tf for tf, r in (q.get("timeframes") or {}).items() if isinstance(r, dict) and r.get("status") != "OK"]
        st = "OK" if not bad else "BŁĘDY: " + ", ".join(bad)
    return make(instrument=inst, symbol=(store_manifest or {}).get("symbol"), source="MARKETDATA_STORE",
                location=str(quality_path.parent) if quality_path else None, range_utc=range_utc, sha256=sha256,
                data_kind=(store_manifest or {}).get("data_kind"), quality={"report": str(quality_path) if q else None, "status": st}, rows=rows)


def from_bars(inst: str, *, source: str, symbol: str | None, data_kind: str | None, sha256: str | None, range_utc=None, rows: int | None = None,
              quality_path: Path | None = None) -> dict:
    """Bars handed to a trainer (families: Store archive or the live bot bars) - the hash / range of the exact training slice."""
    q = _read(quality_path) if quality_path else None
    st = None
    if q:
        bad = [tf for tf, r in (q.get("timeframes") or {}).items() if isinstance(r, dict) and r.get("status") != "OK"]
        st = "OK" if not bad else "BŁĘDY: " + ", ".join(bad)
    return make(instrument=inst, symbol=symbol, source=source, location=str(quality_path.parent) if q else None, range_utc=range_utc,
                sha256=sha256, data_kind=data_kind, quality={"report": str(quality_path) if q else None, "status": st}, rows=rows)
