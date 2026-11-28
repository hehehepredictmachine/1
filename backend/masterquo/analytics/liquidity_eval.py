"""Alias (1.46, I0078): the B0-B3 liquidity-context evaluation moved to masterquo.evaluation.liquidity_eval.

Kept so existing imports (`from masterquo.analytics import liquidity_eval`, the `liquidity` CLI) keep working. The target is resolved lazily
by name on first attribute access, so the analytics package has no import edge to evaluation / scalp / ml (analytics stays a leaf domain).
"""
from __future__ import annotations

import importlib

_TARGET = "masterquo.evaluation.liquidity_eval"


def __getattr__(name: str):
    return getattr(importlib.import_module(_TARGET), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(importlib.import_module(_TARGET))))
