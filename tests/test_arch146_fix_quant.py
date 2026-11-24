"""1.46 arch fix wave, group "quant": D4, D8, D9, D11, D17, D21 (scalp A calibration), D22.

S0 rule of this group: Quant ASSIST fails OPEN (an incompatible / unloaded MetaModel never holds an entry), so the existing MetaModels are
NOT invalidated. The feature SEMANTICS are versioned instead: an artifact with feature_schema PMW-QUANT-FEAT-1 gets exactly the input it got
before (bit-for-bit on a frozen input), the fixed meaning (D8 Kalman candidate = 0, D9 stale DXY = mask, D4 regime in the coordinator SH
candidate) applies to PMW-QUANT-FEAT-3; new ledger rows record their version and training never mixes versions.
Isolated MASTERQUO_DATA_DIR, stub runtimes, SYNTHETIC data - no terminal, no orders, no HTTP server."""
from __future__ import annotations

import json
import sqlite3
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import _env  # noqa: F401
import numpy as np
from _env import TempData


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat()


# ================================================================================================ D21 (quant/adapters.py:352 only)
class TestScalpACalibrationD21(unittest.TestCase):
    """scalp A records were UNCALIBRATED for every run, although the trainer stores a calibrator per horizon and the worker applies it."""

    def test_calibration_status_follows_the_registry(self):
        from masterquo.quant import adapters as A
        reg = {"active": "R1", "runs": {"R1": {"models": {"1": {"selected": "LR", "calibrator": {"coef": [[0.1]]}}, "3": {"selected": "PRIOR"}}}}}
        hz = {"1": {"p_down": 0.2, "p_flat": 0.3, "p_up": 0.5}, "3": {"p_down": 0.3, "p_flat": 0.4, "p_up": 0.3}}
        sc = SimpleNamespace(registry=lambda: reg, forecasts=lambda: {"status": "SHADOW", "run_id": "R1", "feature_time_utc": iso(time.time() - 60),
                                                                      "horizons": hz})
        recs = {r["horizon"]["bars"]: r for r in A.scalp_a(SimpleNamespace(scalp=sc), "XAUUSD")}
        self.assertEqual(recs[1]["state"], "READY")
        self.assertEqual(recs[1]["calibration"]["status"], "CALIBRATED_DEV")
        self.assertEqual(recs[3]["calibration"]["status"], "UNCALIBRATED")             # no calibrator stored for that horizon
        self.assertEqual(recs[1]["result"], {"DOWN": 0.2, "FLAT": 0.3, "UP": 0.5})     # values untouched


# ================================================================================================ D22
def acc_one_segment(n_events: int, t0: float = 1_794_000_000.0, step: float = 60.0) -> dict:
    t = t0 + step * np.arange(n_events, dtype=float)
    mid = 2000.0 + np.cumsum(np.sin(np.arange(n_events)) * 0.1)
    return {"t": t, "mid": mid, "spread": np.full(n_events, 0.2), "activity": np.full(n_events, 5.0), "segment": np.zeros(n_events, dtype=int)}


class TestEventUnitsTailAlignedD22(unittest.TestCase):
    """The live Event GRU cut 16-event units from the START of the segment: the newest full unit ended 0-15 events before the newest event
    (BAR_CLOSE_EVENTS: up to 15 min), so the record's data_time lagged and it turned STALE periodically (TTL 900 s)."""

    def test_last_unit_ends_on_the_last_event(self):
        from masterquo.mm import events as EV
        acc = acc_one_segment(1 + 16 * 3 + 7)                     # the first event of a segment has no delta: 55 valid events
        fe = EV.featurize(acc)
        self.assertEqual(int(fe["valid"].sum()), 16 * 3 + 7)
        tail = EV.units(acc, fe, 16, align="end")
        head = EV.units(acc, fe, 16)
        self.assertEqual(tail["t_end"][-1], acc["t"][-1])
        self.assertEqual(head["t_end"][-1], acc["t"][-1 - 7])     # training cut unchanged: 7 events earlier
        self.assertEqual(len(tail["X"]), 3)
        self.assertEqual(tail["X"].shape[1:], (16, len(EV.FEATURES)))
        self.assertEqual(list(tail["first_event"]), [8, 24, 40])  # remainder (7) left out at the start of the run
        self.assertEqual(tail["available_at"][-1], acc["t"][-1])

    def test_units_never_cross_a_segment(self):
        from masterquo.mm import events as EV
        a, b = acc_one_segment(1 + 20), acc_one_segment(1 + 35, t0=1_794_100_000.0)
        acc = {k: np.concatenate([a[k], b[k] + (1 if k == "segment" else 0)]) for k in ("t", "mid", "spread", "activity", "segment")}
        u = EV.units(acc, EV.featurize(acc), 16, align="end")
        self.assertEqual([int(s) for s in u["segment"]], [0, 1, 1])
        self.assertEqual(u["t_end"][0], a["t"][-1])
        self.assertEqual(u["t_end"][-1], b["t"][-1])
        for X, s, f in zip(u["X"], u["segment"], u["first_event"]):
            self.assertTrue(np.all(acc["segment"][f:f + 16] == s))
        with self.assertRaises(ValueError):
            EV.units(acc, EV.featurize(acc), 16, align="middle")

    def test_live_adapter_data_time_is_the_newest_event(self):
        from masterquo.mm import artifacts as MA
        from masterquo.mm import event_engine as EE
        from masterquo.quant import adapters as A
        t0 = 1_794_000_000.0
        n = 1 + 16 * 3 + 7
        bars = [{"open_utc": iso(t0 + 60 * i), "o": 2000.0, "h": 2000.5, "l": 1999.5, "c": 2000.0 + 0.1 * np.sin(i), "tv": 5, "spread": 20,
                 "closed": True} for i in range(n)]
        rt = SimpleNamespace(bridge=SimpleNamespace(bars=lambda tf, include_forming=False: bars, symbol_info={"point": 0.01}, synthetic=True))
        st = {"scaler_med": [0.0] * 8, "scaler_iqr": [1.0] * 8}
        with mock.patch.object(MA, "read_pointer", return_value={"active": {"event_engine_dir3": "EG1"}}), \
             mock.patch.object(MA, "load", return_value=(st, {"event_source": "BAR_CLOSE_EVENTS", "feature_schema": "PMW-MM-EVENTS-1"})), \
             mock.patch.object(EE.EventModel, "from_state", return_value=object()), \
             mock.patch.object(EE, "predict", side_effect=lambda m, X, seg: np.tile([0.2, 0.3, 0.5], (len(X), 1))):
            rec = A.EventGRU().predict(rt, "XAUUSD")
        self.assertEqual(rec["state"], "READY", rec.get("unavailable_reason"))
        newest = t0 + 60 * (n - 1) + 60                           # BAR_CLOSE_EVENTS: event = close of the newest closed M1
        self.assertEqual(datetime.fromisoformat(rec["data_time"]).timestamp(), newest)


if __name__ == "__main__":
    unittest.main()
