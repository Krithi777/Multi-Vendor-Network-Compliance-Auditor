"""Dataclasses used at the Phase 7 service boundary."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

class TeachingState(str, Enum):
    WAITING_FOR_ADMIN = "WAITING_FOR_ADMIN"
    TEACHING = "TEACHING"
    GENERALIZING = "GENERALIZING"
    COMPLETED = "COMPLETED"

@dataclass(frozen=True)
class CLIExample:
    raw_line: str
    vendor: str
    canonical_field: str
    context_path: str | None = None
    session_id: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class MatchResult:
    original_line: str
    normalized_line: str
    vendor: str
    candidate_canonical_field: str | None
    syntax_score: float
    context_score: float | None
    value_semantics_score: float
    framework_fit_score: float
    precedent_score: float
    available_signals: list[str]
    effective_weights: dict[str, float]
    fusion_score: float
    confidence_bucket: str
    decision: str
    matched_example: str | None = None
    matched_template: str | None = None
    bge_score: float | None = None
    final_mapping_status: str = "unresolved"
    unavailable_signals: list[str] = field(default_factory=list)
    explanation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
