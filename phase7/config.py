"""Central Phase 7 configuration. Environment variables may override defaults."""
from __future__ import annotations
import os
import math
from dataclasses import dataclass, field

def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)

@dataclass(frozen=True)
class Phase7Config:
    syntax_weight: float = field(default_factory=lambda: _float("FUSION_SYNTAX_WEIGHT", 0.35))
    context_weight: float = field(default_factory=lambda: _float("FUSION_CONTEXT_WEIGHT", 0.15))
    value_weight: float = field(default_factory=lambda: _float("FUSION_VALUE_WEIGHT", 0.25))
    framework_weight: float = field(default_factory=lambda: _float("FUSION_FRAMEWORK_WEIGHT", 0.15))
    precedent_weight: float = field(default_factory=lambda: _float("FUSION_PRECEDENT_WEIGHT", 0.10))
    high_threshold: float = field(default_factory=lambda: _float("HIGH_THRESHOLD", 0.85))
    medium_threshold: float = field(default_factory=lambda: _float("MEDIUM_THRESHOLD", 0.60))
    bge_model: str = field(default_factory=lambda: os.getenv("BGE_MODEL", "BAAI/bge-small-en-v1.5"))
    bge_similarity_threshold: float | None = field(
        default_factory=lambda: (float(os.environ["BGE_SIMILARITY_THRESHOLD"])
                                 if os.getenv("BGE_SIMILARITY_THRESHOLD") else None)
    )
    seed_example_count: int = 3

    def __post_init__(self):
        weights = (self.syntax_weight, self.context_weight, self.value_weight,
                   self.framework_weight, self.precedent_weight)
        if any(w < 0 for w in weights):
            raise ValueError("Fusion weights must be non-negative")
        if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
            raise ValueError("Fusion weights must sum to 1.0")
        if not (0 <= self.medium_threshold < self.high_threshold <= 1):
            raise ValueError("Thresholds must satisfy 0 <= medium < high <= 1")
        if self.bge_similarity_threshold is not None and not 0 <= self.bge_similarity_threshold <= 1:
            raise ValueError("BGE_SIMILARITY_THRESHOLD must be in [0,1]")
