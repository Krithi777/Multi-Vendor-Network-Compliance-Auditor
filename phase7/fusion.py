"""Five-signal fusion and mutually-exclusive confidence buckets."""
from __future__ import annotations
from .config import Phase7Config

SIGNAL_KEYS = ("syntax", "context", "value_semantics", "framework_fit", "precedent")

def fuse(scores: dict[str, float | None], config: Phase7Config, *, negation_mismatch=False):
    if negation_mismatch:
        return 0.0, "LOW", {"syntax":0,"context":0,"value_semantics":0,"framework_fit":0,"precedent":0}, ["negation_gate"]
    weights = {
        "syntax": config.syntax_weight, "context": config.context_weight,
        "value_semantics": config.value_weight, "framework_fit": config.framework_weight,
        "precedent": config.precedent_weight,
    }
    available = [k for k in SIGNAL_KEYS if scores.get(k) is not None]
    if not available:
        return 0.0, "LOW", {}, []
    total = sum(weights[k] for k in available)
    effective = {k: weights[k] / total for k in available}
    score = sum(float(scores[k]) * effective[k] for k in available)
    score = max(0.0, min(1.0, score))
    if score >= config.high_threshold:
        bucket = "HIGH"
    elif score >= config.medium_threshold:
        bucket = "MEDIUM"
    else:
        bucket = "LOW"
    return score, bucket, effective, available
