"""Deterministic canonical-field/operator/expected-value compatibility."""
from __future__ import annotations
from typing import Any
from .value_semantics import ValueInference

def _numeric_compare(operator: str, actual: Any, expected: Any) -> bool:
    try:
        a, e = float(actual), float(expected)
    except (TypeError, ValueError):
        return False
    return {"eq": a == e, "ne": a != e, "lte": a <= e, "gte": a >= e}.get(operator, False)

def framework_fit(inferred: ValueInference, operator: str, expected: Any) -> float:
    if inferred.kind == "boolean" and isinstance(expected, bool):
        return 1.0
    if inferred.kind == "numeric" and isinstance(expected, (int, float)):
        return 1.0 if _numeric_compare(operator, inferred.value, expected) else 0.0
    if inferred.kind == "ip":
        return 1.0 if isinstance(expected, str) else 0.0
    if inferred.kind in {"enum", "string"} and isinstance(expected, str):
        if operator == "eq":
            return 1.0 if str(inferred.value).lower() == expected.lower() else 0.0
        return 1.0
    if isinstance(expected, (list, tuple, set)):
        return 1.0 if str(inferred.value).lower() in {str(x).lower() for x in expected} else 0.0
    return 0.0
