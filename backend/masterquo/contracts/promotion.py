"""One champion-promotion policy of the legacy ML registry (Decision Tree / XGBoost, ml/registry.py) - 1.46 arch D6 / D7.

Used by BOTH paths that register ML models: the bot's own training job (ml/service.py MLService._handle_result) and the offline training
of the training installer (ml/offline.py, `python -m masterquo training ml-offline`). Until 1.46 only the offline path applied the rule
"a model trained on APPROX labels (backfill OHLC) or on synthetic data never becomes the champion"; the bot's job registered every result
with promotion allowed, so a simulator / APPROX model could become the champion that drives the ML gate in ASSIST.

The policy only decides WHETHER a passing candidate may become the champion; the promotion rules themselves (metrics vs baselines,
comparison with the current champion on the same test block) stay in ml/registry.Registry. A blocked candidate is stored and evaluated
(status RESEARCH_APPROX - research only, never champion, never a shadow-scored challenger); the current champion stays.

1.46 arch Etap 4: moved here from training/promotion.py (which stays as the alias zgodności and the documented entry of the policy) -
a neutral leaf (stdlib only), so ml/ takes the one policy without an upward import into the training orchestrator (layer guard).
"""
from __future__ import annotations

ELIGIBLE = "ELIGIBLE_FOR_CHAMPION"


def _block(role: str, event: str, reason: str) -> dict:
    return {"allow_promotion": False, "role": role, "event": event, "reason": reason}


def ml_champion_policy(*, approx: bool | None, synthetic: bool | None, activate: bool = True) -> dict:
    """approx: the training snapshot contains APPROX labels (backfill OHLC); synthetic: samples of the terminal simulator (SYNTHETIC_TEST);
    activate: the plan allows activation (False = profile TEST_INSTALACJI / `--no-activate`). None = provenance unknown (e.g. a job file
    of an older version without the information) - treated as not proven clean, never promoted.

    Returns {allow_promotion, role, event, reason}; role is the `role` field of the offline result (FIXTURE_ONLY / RESEARCH_APPROX /
    ELIGIBLE_NOT_ACTIVATED / PROVENANCE_UNKNOWN / ELIGIBLE_FOR_CHAMPION), event the ml_events kind written for a blocked candidate."""
    if synthetic is None or approx is None:
        return _block("PROVENANCE_UNKNOWN", "NOT_PROMOTED_PROVENANCE_UNKNOWN",
                      "nieznane pochodzenie danych treningu (APPROX / syntetyczne) – model tylko do badań, champion bez zmian")
    if synthetic:
        return _block("FIXTURE_ONLY", "NOT_PROMOTED_SYNTHETIC", "dane syntetyczne (symulator terminala) – model techniczny, nigdy champion")
    if approx:
        return _block("RESEARCH_APPROX", "NOT_PROMOTED_APPROX", "trening na etykietach APPROX (backfill OHLC) – tylko do badań")
    if not activate:
        return _block("ELIGIBLE_NOT_ACTIVATED", "NOT_PROMOTED_NO_ACTIVATE",
                      "plan treningu bez aktywacji (TEST_INSTALACJI / --no-activate) – champion bez zmian")
    return {"allow_promotion": True, "role": ELIGIBLE, "event": None, "reason": None}


def approx_rows_in_snapshot(db, manifest: dict) -> int:
    """APPROX labels inside a snapshot written by ml/dataset.SampleStore.snapshot: the same selection as SampleStore.eligible (labelled,
    cost known, one sample world, label known at the cutoff) restricted to quality != HIGH. A snapshot without APPROX rows is HIGH-only
    whatever the include_approx flag was. Rows labelled after the snapshot can only raise the count (the conservative direction)."""
    if not manifest.get("include_approx"):
        return 0
    r = db.one("SELECT COUNT(*) AS n FROM ml_samples WHERE status='LABELED' AND quality NOT IN ('HIGH','COST_UNKNOWN') AND synthetic=? "
               "AND label_known_utc <= ?", (1 if manifest.get("synthetic") else 0, manifest["cutoff_utc"]))
    return int((r or {}).get("n") or 0)
