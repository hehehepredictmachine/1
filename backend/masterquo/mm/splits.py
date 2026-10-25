"""Chronological splits with purge / embargo + a one-shot holdout guard (PMW-MM-SPLITS-1).

Every supervised sample i has an observation time t_obs[i] (when its features are known) and a label end time t_end[i] (when its
target is fully realised). Partitions are contiguous in time: TRAIN | VAL | TEST. A sample belongs to a partition only if its whole
[t_obs, t_end] interval lies inside it (purge), and the first `embargo_s` seconds after a boundary are dropped. Walk-forward folds
reuse the existing lab implementation (lab/protocol.walk_forward) on the development (TRAIN+VAL) indices.

The final TEST block is behind `HoldoutGuard`: optimizers and model selection only see TRAIN/VAL; the guard releases the TEST indices
once, after the candidate is frozen, and records the hash of the frozen candidate - a second request raises.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from ..lab.protocol import walk_forward  # noqa: F401  (re-exported: the shared purged walk-forward)

VERSION = "PMW-MM-SPLITS-1"


def chrono_split(t_obs: np.ndarray, t_end: np.ndarray, fracs=(0.6, 0.2, 0.2), embargo_s: float = 0.0) -> dict:
    t_obs, t_end = np.asarray(t_obs, float), np.asarray(t_end, float)
    if len(t_obs) != len(t_end) or not len(t_obs):
        raise ValueError("SPLIT_EMPTY_OR_MISMATCH")
    if np.any(t_end < t_obs):
        raise ValueError("LABEL_ENDS_BEFORE_OBSERVATION")
    if abs(sum(fracs) - 1.0) > 1e-9 or min(fracs) <= 0:
        raise ValueError("SPLIT_FRACTIONS_INVALID")
    lo, hi = float(t_obs.min()), float(t_end.max())
    c1 = lo + (hi - lo) * fracs[0]
    c2 = lo + (hi - lo) * (fracs[0] + fracs[1])
    tr = np.where(t_end < c1)[0]
    va = np.where((t_obs >= c1 + embargo_s) & (t_end < c2))[0]
    te = np.where(t_obs >= c2 + embargo_s)[0]
    return {"version": VERSION, "train": tr, "val": va, "test": te, "cuts": [c1, c2], "embargo_s": embargo_s,
            "purged": int(len(t_obs) - len(tr) - len(va) - len(te)),
            "intervals": {"train": [lo, c1], "val": [c1 + embargo_s, c2], "test": [c2 + embargo_s, hi]}}


def assert_no_overlap(split: dict, t_obs: np.ndarray, t_end: np.ndarray) -> None:
    """Leakage check: no training label may end after the earliest validation/test observation, etc."""
    tr, va, te = split["train"], split["val"], split["test"]
    if len(tr) and len(va) and t_end[tr].max() >= t_obs[va].min():
        raise AssertionError("TRAIN_LABEL_OVERLAPS_VAL")
    if len(va) and len(te) and t_end[va].max() >= t_obs[te].min():
        raise AssertionError("VAL_LABEL_OVERLAPS_TEST")
    if len(tr) and len(te) and t_end[tr].max() >= t_obs[te].min():
        raise AssertionError("TRAIN_LABEL_OVERLAPS_TEST")


class HoldoutGuard:
    def __init__(self, test_idx: np.ndarray):
        self._idx = np.asarray(test_idx)
        self.opened_for: str | None = None
        self.idx_hash = hashlib.sha256(self._idx.tobytes()).hexdigest()[:16]

    def open(self, frozen_candidate: dict) -> np.ndarray:
        if self.opened_for is not None:
            raise RuntimeError("HOLDOUT_ALREADY_OPENED")
        self.opened_for = hashlib.sha256(json.dumps(frozen_candidate, sort_keys=True, default=str).encode()).hexdigest()[:16]
        return self._idx

    def record(self) -> dict:
        return {"test_idx_hash": self.idx_hash, "n": int(len(self._idx)), "opened_for_candidate": self.opened_for}
