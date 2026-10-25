"""Shared, versioned contracts (PMW-MM-CONTRACTS-1).

Envelope = common metadata; payloads stay task-specific (a GP predictive distribution, an HDC similarity, a Kalman state and an SMC
setup are different quantities and are never merged into one score). Times are UTC epoch seconds (float); `source_ts` is the time of
the observation (bar open / tick time), `available_at` the earliest time the value could have been known (bar close, confirmation bar
close, label maturation) and `ingested_at` the local processing time.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = "PMW-MM-CONTRACTS-1"

CATEGORIES = ("TRAINABLE", "ONLINE_LEARNER", "RECURSIVE_FILTER", "DETERMINISTIC_INDICATOR", "RULE_STRATEGY", "OPTIMIZER",
              "DATA_INFRA", "VISUALIZATION", "BENCHMARK")
JOB_STATUS = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED_DATA_QUALITY", "BLOCKED_VALIDATION", "NOT_APPLICABLE",
              "BLOCKED_SPEC_MISSING", "BLOCKED_DEPENDENCY")
FEATURE_STATUS = ("VERIFIED_IN_CODE", "IMPLEMENTED", "UNIT_TESTED", "INTEGRATION_TESTED", "TRAINING_EXECUTED", "VALIDATION_PASSED",
                  "SHADOW_OBSERVED", "BLOCKED", "NOT_APPLICABLE", "NOT_IMPLEMENTED")
OUTPUT_KINDS = ("RETURN_PREDICTION", "CLASS_PROBABILITIES", "GAUSSIAN_PREDICTIVE", "HDC_SIMILARITY", "STATE_CORRELATION",
                "INDICATOR_STATE", "STRUCTURE_EVENT", "RULE_SIGNAL", "OPTIMIZER_RESULT", "DATA_EXPORT", "BENCHMARK_RESULT")
DATA_QUALITY = ("OK", "DEGRADED", "STALE", "MISSING", "INVALID", "SYNTHETIC_TEST")


def now() -> float:
    return time.time()


def stable_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass
class Envelope:
    source_id: str
    symbol: str
    timeframe: str
    source_ts: float
    available_at: float
    data_quality: str = "OK"
    event_id: str = ""
    feature_schema: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    run_id: str | None = None
    ingested_at: float = field(default_factory=now)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        if self.data_quality not in DATA_QUALITY:
            raise ValueError(f"DATA_QUALITY_INVALID:{self.data_quality}")
        if self.available_at < self.source_ts:
            raise ValueError("AVAILABLE_BEFORE_SOURCE")       # a value can never be known before its observation
        if not self.event_id:
            self.event_id = stable_hash([self.source_id, self.symbol, self.timeframe, self.source_ts, self.model_id, self.model_version])


@dataclass
class ModelOutput:
    """Envelope + typed payload. `execution_allowed` is a constant False: outputs are observations, never order instructions."""
    envelope: Envelope
    kind: str
    payload: dict
    status: str = "OK"
    diagnostics: dict = field(default_factory=dict)
    execution_allowed: bool = False

    def __post_init__(self):
        if self.kind not in OUTPUT_KINDS:
            raise ValueError(f"OUTPUT_KIND_INVALID:{self.kind}")
        if self.execution_allowed:
            raise ValueError("EXECUTION_NOT_ALLOWED_IN_SHADOW")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["execution_allowed"] = False
        return d


def new_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}"
