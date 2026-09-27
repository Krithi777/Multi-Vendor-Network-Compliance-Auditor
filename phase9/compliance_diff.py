"""Compliance evaluation + evidence model (Phase 9, decision steps 3 & 4).

Takes a NormalizedConfig (from normalizer.py) and produces one
EvidenceResult per control -- PASS / FAIL / MISSING / REVIEW -- with
enough attached evidence (raw line, line number, context, framework
mappings, severity, "why it matters") for a findings UI to explain the
result without going back to raw config text.

State semantics (per vendor_mappings' own `tri_state_capable` flag,
matching the PASS/FAIL/MISSING fixture convention used throughout this
project):
- PASS    -- a line was found and it is the known-good literal form
             (or, for a non-literal variant, the extracted value
             satisfies the control's operator/expected_value).
- FAIL    -- a line was found and it is the known-bad literal form (or
             a non-literal variant that fails the operator check).
- MISSING -- no line for this canonical_field was found in the
             relevant context at all. This is a *distinct* state from
             FAIL, not a synonym for "assumed compliant" or "assumed
             non-compliant" -- that's the whole point of the tri-state
             design this project already commits to.
- REVIEW  -- a line was found, it's neither the known pass nor known
             fail literal, and the operator-based evaluator could not
             confidently classify it either. Reported as evidence-backed
             but flagged for human review rather than silently guessed.
- NOT_APPLICABLE (a 5th, structural state, not part of tri_state) -- the
  vendor's platform makes this control moot by design (always_compliant
  in vendor_mappings, e.g. PAN-OS SSHv2-only with no CLI toggle). Kept
  distinct from PASS so reports can say *why* -- "no toggle exists" is a
  different fact than "the toggle is set correctly".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .mapping_loader import RuleTables, get_default_tables
from .normalizer import NormalizedConfig

VALID_STATES = ("PASS", "FAIL", "MISSING", "REVIEW", "NOT_APPLICABLE")

_TRUE_TOKENS = {"enable", "enabled", "true", "yes", "permit", "up", "on"}
_FALSE_TOKENS = {"disable", "disabled", "false", "no", "deny", "down", "off"}


@dataclass
class EvidenceResult:
    control_id: str
    canonical_field: str
    vendor: str
    state: str
    description: str | None
    severity: str
    operator: str
    expected_value: Any
    observed_value: Any
    evidence_line: str | None
    evidence_line_number: int | None
    context_category: str | None
    is_mgmt_path: bool
    frameworks: dict
    linked_controls: list[str] = field(default_factory=list)
    notes: str | None = None


def _apply_operator(operator: str, expected: Any, observed_raw: str) -> bool | None:
    """Returns True/False if the raw extracted token can be confidently
    evaluated against the control's operator/expected_value, else None
    (caller should treat as REVIEW, not guess)."""
    if observed_raw is None:
        return None
    token = observed_raw.strip().lower()

    if isinstance(expected, bool):
        if token in _TRUE_TOKENS:
            observed = True
        elif token in _FALSE_TOKENS:
            observed = False
        else:
            return None
        return observed == expected if operator == "eq" else None

    if isinstance(expected, (int, float)):
        try:
            observed_num = float(token)
        except ValueError:
            return None
        if operator == "eq":
            return observed_num == expected
        if operator == "lte":
            return observed_num <= expected
        if operator == "gte":
            return observed_num >= expected
        return None

    if isinstance(expected, str):
        if operator == "eq":
            return token == expected.strip().lower()
        return None

    return None


def evaluate_control(control_id: str, vendor: str, normalized: NormalizedConfig,
                      tables: RuleTables | None = None) -> EvidenceResult:
    tables = tables or get_default_tables()
    meta = tables.controls[control_id]
    frameworks = {
        "nist_800_53": meta.nist_800_53,
        "cis": meta.cis,
        "stig": meta.stig,
        "iso_27001": meta.iso_27001,
    }
    rule = next((r for r in tables.rules_for_vendor(vendor) if r.control_id == control_id), None)

    if rule is None:
        return EvidenceResult(
            control_id=control_id, canonical_field=meta.canonical_field, vendor=vendor,
            state="NOT_APPLICABLE", description=meta.description, severity=meta.severity,
            operator=meta.operator, expected_value=meta.expected_value, observed_value=None,
            evidence_line=None, evidence_line_number=None, context_category=None,
            is_mgmt_path=meta.is_mgmt_path, frameworks=frameworks,
            notes="No vendor_mappings rule defined for this vendor/control pair.",
        )

    if rule.always_compliant:
        return EvidenceResult(
            control_id=control_id, canonical_field=meta.canonical_field, vendor=vendor,
            state="NOT_APPLICABLE", description=meta.description, severity=meta.severity,
            operator=meta.operator, expected_value=meta.expected_value, observed_value=None,
            evidence_line=None, evidence_line_number=None, context_category=rule.context_path,
            is_mgmt_path=meta.is_mgmt_path, frameworks=frameworks,
            linked_controls=tables.linked_controls_for(control_id, vendor),
            notes=rule.notes or "Platform-inherent; no configurable toggle exists for this control.",
        )

    mf = normalized.fields.get(meta.canonical_field)
    linked = tables.linked_controls_for(control_id, vendor)

    if mf is None:
        return EvidenceResult(
            control_id=control_id, canonical_field=meta.canonical_field, vendor=vendor,
            state="MISSING", description=meta.description, severity=meta.severity,
            operator=meta.operator, expected_value=meta.expected_value, observed_value=None,
            evidence_line=None, evidence_line_number=None, context_category=rule.context_path,
            is_mgmt_path=meta.is_mgmt_path, frameworks=frameworks, linked_controls=linked,
            notes="No matching configuration line found for this control.",
        )

    if mf.matched_pass_literal:
        state = "PASS"
        notes = None
    elif mf.matched_fail_literal:
        state = "FAIL"
        notes = None
    else:
        resolved = _apply_operator(meta.operator, meta.expected_value, mf.extracted_value)
        if resolved is True:
            state, notes = "PASS", "Value differs from the known-good example line but satisfies the control."
        elif resolved is False:
            state, notes = "FAIL", "Value differs from the known-bad example line but fails the control."
        else:
            state, notes = "REVIEW", "A configuration line was found but its value could not be confidently classified -- needs human review."

    link_note = None
    if linked:
        link_note = f"Evidence line is shared with: {', '.join(linked)} (same underlying config line -- not independently verifiable)."
    combined_notes = " ".join(n for n in (notes, link_note) if n) or None

    return EvidenceResult(
        control_id=control_id, canonical_field=meta.canonical_field, vendor=vendor,
        state=state, description=meta.description, severity=meta.severity,
        operator=meta.operator, expected_value=meta.expected_value,
        observed_value=mf.extracted_value, evidence_line=mf.raw_line,
        evidence_line_number=mf.line_number, context_category=mf.context_category,
        is_mgmt_path=meta.is_mgmt_path, frameworks=frameworks, linked_controls=linked,
        notes=combined_notes,
    )


def run_compliance_diff(normalized: NormalizedConfig, tables: RuleTables | None = None) -> list[EvidenceResult]:
    """Evaluates every control in the schema for one normalized config."""
    tables = tables or get_default_tables()
    return [evaluate_control(cid, normalized.vendor, normalized, tables) for cid in tables.controls]


def summarize(results: list[EvidenceResult]) -> dict:
    counts = {s: 0 for s in VALID_STATES}
    for r in results:
        counts[r.state] += 1
    return counts