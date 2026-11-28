"""DatasetRef (PMW-DATASET-REF-1, arch146 I0064): ONE description of the data a model was trained on, written into the manifest of every
artifact (lineage).

1.46 arch Etap 4: przeniesione do masterquo/contracts/dataset_ref.py (liść L0: trainhub i rodziny modeli zapisują DatasetRef bez importu
orkiestratora treningu), alias zgodności - the same functions (identity); the coverage note is in the moved module.
"""
from __future__ import annotations

from ..contracts.dataset_ref import (
    VERSION,
    _read,
    _sha_of,
    from_bars,
    from_export_dir,
    from_store,
    make,
)

__all__ = ["VERSION", "_read", "_sha_of", "from_bars", "from_export_dir", "from_store", "make"]
