"""Compatibility shim (1.46 arch, I0076): the causal indicator functions live in masterquo.indicators.series (moved byte for byte).

Re-exports the SAME function objects (strategies.indicators.atr is indicators.series.atr), so the strategies, the regime engine, the
ML / SH / MM features and every other importer of this module keep working unchanged. The analysis layer imports
masterquo.indicators.series directly (no analysis -> strategies dependency).
"""
from __future__ import annotations

from ..indicators.series import *  # re-export shim (same function objects)
from ..indicators.series import __all__  # noqa: F401 - the public names of the shim = those of indicators.series
