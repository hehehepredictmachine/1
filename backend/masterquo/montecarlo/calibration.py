"""Isotonic calibrator lookup of Monte Carlo (leaf module). 1.46 arch I0085: engine imported apply_calibrator lazily from validate, which
imports engine (the validate <-> engine cycle). Moved unchanged; montecarlo.validate re-exports it under the old name."""
from __future__ import annotations

import numpy as np


def apply_calibrator(cal: dict, p: float) -> float:
    c = cal.get("calibrator") or cal
    return float(np.interp(p, c["x"], c["y"])) if c.get("x") else float(p)
