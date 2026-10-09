"""Agent output contract (structured JSON) and its validation.

The model returns the "assessment" part; the backend adds decision_id, as_of_utc,
expires_at_utc, model_id, prompt_version and schema_version to form the stored decision record.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..version import AGENT_SCHEMA_VERSION


def _nullable(t: dict) -> dict:
    return {"anyOf": [t, {"type": "null"}]}


_STR = {"type": "string"}
_NUM = {"type": "number"}
_STRS = {"type": "array", "items": _STR}
_SCEN = {"type": "object", "additionalProperties": False, "required": ["summary", "activation", "invalidation"],
         "properties": {"summary": _STR, "activation": _STRS, "invalidation": _STRS}}

OUTPUT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["snapshot_id", "setup_id", "analysis_direction", "signal_stage", "proposed_action", "strategy_id",
                 "strategy_version", "entry_zone", "invalidation_level", "proposed_targets", "scenarios", "evidence_refs",
                 "contradictions", "missing_data", "reason_codes", "explanation_pl", "answer_pl", "lessons", "playbook_proposals",
                 "preferred_strategy_id", "scenario_still_valid"],
    "properties": {
        "snapshot_id": _STR,
        "setup_id": _nullable(_STR),
        "analysis_direction": {"type": "string", "enum": ["LONG", "SHORT", "NEUTRAL"]},
        "signal_stage": {"type": "string", "enum": ["WATCH", "EARLY", "CONFIRMED", "EXPIRED", "INVALIDATED"]},
        "proposed_action": {"type": "string", "enum": ["BUY", "SELL", "WAIT", "NO_TRADE"]},
        "strategy_id": _nullable(_STR),
        "preferred_strategy_id": _nullable(_STR),
        "scenario_still_valid": {"type": "boolean"},
        "strategy_version": _nullable(_STR),
        "entry_zone": _nullable({"type": "object", "additionalProperties": False, "required": ["low", "high"],
                                 "properties": {"low": _NUM, "high": _NUM}}),
        "invalidation_level": _nullable(_NUM),
        "proposed_targets": {"type": "array", "items": _NUM},
        "scenarios": {"type": "object", "additionalProperties": False, "required": ["bullish", "bearish", "wait"],
                      "properties": {"bullish": _SCEN, "bearish": _SCEN, "wait": _SCEN}},
        "evidence_refs": _STRS,
        "contradictions": _STRS,
        "missing_data": _STRS,
        "reason_codes": _STRS,
        "explanation_pl": _STR,
        "answer_pl": _nullable(_STR),
        "lessons": _STRS,
        "playbook_proposals": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                          "required": ["title", "change", "rationale", "scope"],
                                                          "properties": {"title": _STR, "change": _STR, "rationale": _STR, "scope": _STR}}},
    },
}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Zone(_M):
    low: float
    high: float


class Scenario(_M):
    summary: str
    activation: list[str]
    invalidation: list[str]


class Scenarios(_M):
    bullish: Scenario
    bearish: Scenario
    wait: Scenario


class PlaybookProposal(_M):
    title: str
    change: str
    rationale: str
    scope: str


class AgentAssessment(_M):
    snapshot_id: str
    setup_id: str | None
    analysis_direction: Literal["LONG", "SHORT", "NEUTRAL"]
    signal_stage: Literal["WATCH", "EARLY", "CONFIRMED", "EXPIRED", "INVALIDATED"]
    proposed_action: Literal["BUY", "SELL", "WAIT", "NO_TRADE"]
    strategy_id: str | None
    strategy_version: str | None
    entry_zone: Zone | None
    invalidation_level: float | None
    proposed_targets: list[float]
    scenarios: Scenarios
    evidence_refs: list[str]
    contradictions: list[str]
    missing_data: list[str]
    reason_codes: list[str]
    explanation_pl: str = Field(max_length=4000)
    answer_pl: str | None
    lessons: list[str]
    playbook_proposals: list[PlaybookProposal]
    preferred_strategy_id: str | None = None
    scenario_still_valid: bool = True


def record(assessment: AgentAssessment, *, decision_id: str, as_of: str, expires_at: str, model_id: str | None,
           prompt_version: str) -> dict:
    d = assessment.model_dump()
    d.update(schema_version=AGENT_SCHEMA_VERSION, decision_id=decision_id, as_of_utc=as_of, expires_at_utc=expires_at,
             model_id=model_id, prompt_version=prompt_version)
    return d
