"""Compatibility alias (w2 I0082): the unified prediction contract PMW-PRED-2 lives in masterquo/contracts/prediction.py - a neutral leaf
the producers (kronos, tsfm, trainhub) import without depending on modelhub (they import each other: modelhub aggregates them).

`from masterquo.modelhub import contract` (and `from . import contract` inside modelhub) returns THE SAME module object, so every name,
private helper and monkeypatch keeps working exactly as before the move.
"""
from __future__ import annotations

import sys

from ..contracts import prediction as _prediction

sys.modules[__name__] = _prediction
