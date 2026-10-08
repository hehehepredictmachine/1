"""Time contract for MT5 data.

The MetaTrader5 Python documentation states that the terminal stores tick and bar open times
"in UTC time zone (without the shift)" and that datetime arguments must be created in UTC.
In practice brokers' raw epochs are the *broker server wall clock* encoded as an epoch, which is
why raw values can appear hours ahead of real UTC (the FUTURE_CANDLE / BROKER_TICK_AHEAD_OF_UTC
symptoms of the previous package).

This module never assumes a fixed shift. It *measures* the server offset from fresh ticks:

    delta_i = tick.time_msc/1000 (raw) - utc_now_at_receipt

and accepts an offset only if several fresh samples agree and their best value lies within
`tolerance` of a multiple of `granularity` (time-zone offsets are 15-minute aligned). The
evidence (samples, residual) is kept for the diagnostic report. Without a verified or stored
offset the data stay displayable but are flagged TIME_OFFSET_UNVERIFIED and entries are blocked.

Bars keep both representations: `open_raw` (as received) and `open_utc` (raw - offset).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from ..timeutil import UTC, from_epoch, iso


@dataclass
class OffsetEvidence:
    offset_seconds: int | None = None
    status: str = "UNKNOWN"  # UNKNOWN | MEASURING | VERIFIED | STORED_UNVERIFIED | INCONSISTENT
    samples: int = 0
    residual_seconds: float | None = None
    measured_at: datetime | None = None
    last_raw_delta_seconds: float | None = None
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"offset_seconds": self.offset_seconds, "offset_hours": (self.offset_seconds / 3600.0) if self.offset_seconds is not None else None,
                "status": self.status, "samples": self.samples, "residual_seconds": self.residual_seconds,
                "measured_at": iso(self.measured_at), "last_raw_delta_seconds": self.last_raw_delta_seconds,
                "reasons": list(self.reasons)}


class ServerClock:
    def __init__(self, granularity: int = 900, tolerance: float = 90.0, min_samples: int = 5, window: int = 30):
        self.granularity = granularity
        self.tolerance = tolerance
        self.min_samples = min_samples
        self.window = window
        self._deltas: list[float] = []
        self._last_tick_msc: int | None = None
        self._lock = threading.Lock()
        self.evidence = OffsetEvidence()
        self.changes: list[dict] = []  # history of verified offset changes (DST / server switch)

    def reset(self) -> None:
        with self._lock:
            self._deltas.clear()
            self._last_tick_msc = None
            self.evidence = OffsetEvidence()

    def load_stored(self, offset_seconds: int, measured_at: datetime) -> None:
        with self._lock:
            if self.evidence.status != "VERIFIED":
                self.evidence = OffsetEvidence(offset_seconds=int(offset_seconds), status="STORED_UNVERIFIED",
                                               measured_at=measured_at, reasons=["OFFSET_FROM_PREVIOUS_SESSION"])

    def observe_tick(self, tick_time_msc: int, received_utc: datetime) -> OffsetEvidence:
        """Feed a tick. Only *new* ticks (time_msc changed) are used as samples."""
        with self._lock:
            if self._last_tick_msc is not None and tick_time_msc <= self._last_tick_msc:
                if self._last_tick_msc - tick_time_msc < 30 * 60 * 1000:
                    return self.evidence  # same/older tick: not a new sample
                # raw time jumped back >30 min: server clock change (DST/server switch) -> re-measure
                self._deltas.clear()
                self.evidence.reasons = ["RAW_TIME_JUMPED_BACK_REMEASURING"]
            self._last_tick_msc = tick_time_msc
            delta = tick_time_msc / 1000.0 - received_utc.timestamp()
            self.evidence.last_raw_delta_seconds = round(delta, 3)
            self._deltas.append(delta)
            self._deltas = self._deltas[-self.window:]
            if len(self._deltas) < self.min_samples:
                if self.evidence.status == "UNKNOWN":
                    self.evidence.status = "MEASURING"
                self.evidence.samples = len(self._deltas)
                return self.evidence
            # The freshest tick has the smallest latency => the largest delta is closest to the offset.
            best = max(self._deltas)
            candidate = round(best / self.granularity) * self.granularity
            residual = best - candidate
            spread = best - sorted(self._deltas)[len(self._deltas) // 2]
            reasons = []
            ok = abs(residual) <= self.tolerance
            if not ok:
                reasons.append("DELTA_NOT_ALIGNED_TO_TIMEZONE_GRID_CHECK_PC_CLOCK")
            if spread > 600:
                reasons.append("TICK_LATENCY_SPREAD_LARGE")
            prev = self.evidence.offset_seconds if self.evidence.status == "VERIFIED" else None
            if ok:
                if prev is not None and prev != candidate:
                    reasons.append(f"OFFSET_CHANGED_{prev}_TO_{candidate}_DST_OR_SERVER_CHANGE")
                    self.changes.append({"from": prev, "to": int(candidate), "at": iso(received_utc)})
                    self.changes = self.changes[-10:]
                self.evidence = OffsetEvidence(offset_seconds=int(candidate), status="VERIFIED", samples=len(self._deltas),
                                               residual_seconds=round(residual, 3), measured_at=received_utc,
                                               last_raw_delta_seconds=round(delta, 3), reasons=reasons)
            else:
                self.evidence = OffsetEvidence(offset_seconds=self.evidence.offset_seconds, status="INCONSISTENT",
                                               samples=len(self._deltas), residual_seconds=round(residual, 3),
                                               measured_at=self.evidence.measured_at,
                                               last_raw_delta_seconds=round(delta, 3), reasons=reasons)
            return self.evidence

    @property
    def offset(self) -> int | None:
        with self._lock:
            if self.evidence.status in ("VERIFIED", "STORED_UNVERIFIED", "INCONSISTENT"):
                return self.evidence.offset_seconds
            return None

    @property
    def verified(self) -> bool:
        with self._lock:
            return self.evidence.status == "VERIFIED"

    def raw_to_utc(self, raw_epoch: int | float) -> datetime | None:
        off = self.offset
        if off is None:
            return None
        return from_epoch(float(raw_epoch) - off)

    def utc_to_raw(self, d: datetime) -> float | None:
        off = self.offset
        if off is None:
            return None
        return d.astimezone(UTC).timestamp() + off
