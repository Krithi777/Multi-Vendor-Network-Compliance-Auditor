"""Deterministic value/negation classifiers."""
from __future__ import annotations
import ipaddress, re
from dataclasses import dataclass
from typing import Any

NEGATION = {"no", "deny", "disabled", "disable", "off", "false"}
BOOLEAN = {"yes", "true", "on", "enable", "enabled", "false", "no", "off", "disable", "disabled"}
ENUM_HINTS = {"ssh", "telnet", "http", "https", "radius", "tacacs", "public", "private"}

@dataclass(frozen=True)
class ValueInference:
    kind: str
    value: Any
    negated: bool

def infer_value(tokens: list[str]) -> ValueInference:
    if not tokens:
        return ValueInference("string", "", False)
    raw = tokens[-1].strip("\"'")
    lower = raw.lower()
    negated = any(t.lower().strip("\"'") in NEGATION for t in tokens)
    if lower in BOOLEAN:
        return ValueInference("boolean", lower in {"yes","true","on","enable","enabled"}, negated)
    try:
        if "/" in raw:
            ipaddress.ip_network(raw, strict=False)
            return ValueInference("ip", raw, negated)
        ipaddress.ip_address(raw)
        return ValueInference("ip", raw, negated)
    except ValueError:
        pass
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", raw):
        return ValueInference("numeric", float(raw) if "." in raw else int(raw), negated)
    if lower in ENUM_HINTS:
        return ValueInference("enum", lower, negated)
    return ValueInference("string", raw, negated)

def expected_type(expected: Any) -> str:
    if isinstance(expected, bool): return "boolean"
    if isinstance(expected, (int, float)): return "numeric"
    if isinstance(expected, (list, tuple, set)): return "enum"
    if isinstance(expected, str):
        try:
            ipaddress.ip_address(expected); return "ip"
        except ValueError: return "string"
    return "string"

def value_semantics_score(inferred: ValueInference, expected: Any) -> float:
    return 1.0 if inferred.kind == expected_type(expected) else 0.0

def negation_matches(candidate: ValueInference, examples: list[ValueInference]) -> bool:
    """Return whether the candidate's polarity is represented by the examples.

    A single consistent polarity is a hard gate: a mismatch is rejected. If
    confirmed examples legitimately vary between negated/non-negated values,
    the polarity is part of the learned {VALUE} slot and either state is valid.
    """
    if not examples:
        return True
    example_polarities = {example.negated for example in examples}
    return candidate.negated in example_polarities
