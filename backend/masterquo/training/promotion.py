"""One champion-promotion policy of the legacy ML registry (Decision Tree / XGBoost) - 1.46 arch D6 / D7.

1.46 arch Etap 4: przeniesione do masterquo/contracts/promotion.py (liść L0: ml/service.py i ml/offline.py biorą tę samą politykę bez
importu orkiestratora treningu), alias zgodności - the same functions (identity), the documented entry of the policy stays here.
"""
from __future__ import annotations

from ..contracts.promotion import (
    ELIGIBLE,
    _block,
    approx_rows_in_snapshot,
    ml_champion_policy,
)

__all__ = ["ELIGIBLE", "_block", "approx_rows_in_snapshot", "ml_champion_policy"]
