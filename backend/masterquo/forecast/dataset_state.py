"""State of an MT5 training export folder (leaf module). 1.46 arch I0085: training.requirements imported dataset_state lazily from
forecast.export, which imports training.requirements after an export (the export <-> requirements cycle). Moved unchanged;
forecast.export re-exports STATUS_FILE / META_FILE / read_status / dataset_state under the old names."""
from __future__ import annotations

import json
from pathlib import Path

STATUS_FILE = "EXPORT_STATUS.json"
META_FILE = "source_metadata.json"


def read_status(ds: Path) -> dict | None:
    try:
        return json.loads((Path(ds) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def dataset_state(ds: Path) -> dict:
    """COMPLETE | LEGACY_COMPLETE (export older than 1.25: metadata, no status file) | IN_PROGRESS | INTERRUPTED (process gone) |
    FAILED | CANCELLED | MISSING. Only COMPLETE / LEGACY_COMPLETE may be used for training."""
    ds = Path(ds)
    st = read_status(ds)
    has_meta = (ds / META_FILE).exists()
    if st is None:
        return {"state": "LEGACY_COMPLETE" if has_meta else "MISSING", "usable": has_meta}
    s = st.get("status")
    if s == "IN_PROGRESS":
        # 1.46 arch Etap 4: owner liveness of the lock service (masterquo/locks.pid_alive = training.core._pid_alive)
        from ..locks import pid_alive as _pid_alive
        if not _pid_alive(int(st.get("pid") or 0)):
            s = "INTERRUPTED"
    return {"state": s, "usable": s == "COMPLETE" and has_meta, "reason": st.get("reason"), "progress": st.get("progress"),
            "updated_at": st.get("updated_at")}
