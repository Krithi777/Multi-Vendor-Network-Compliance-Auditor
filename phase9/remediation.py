"""Remediation engine (Phase 9, decision step 5) -- deliberately WITHOUT
Phase 8 conflict-checking, per the build decision to defer Phase 8.

Every RemediationProposal carries `conflict_check = "not_available"`
rather than omitting the field or faking a result, so the frontend can
show an honest "not yet checked for conflicts" notice instead of
implying a safety check happened that didn't. When Phase 8 is built,
wire it in at the single marked TODO below -- nothing else in this
module should need to change.

This module only looks things up; it never executes a command against a
device. Preview / copy / export only, per the project's own scope rules.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .mapping_loader import RuleTables, get_default_tables

PLACEHOLDER_RE = re.compile(r"<([A-Z0-9_]+)>")

# Only these evidence states warrant a remediation proposal. PASS and
# NOT_APPLICABLE mean there's nothing to fix; REVIEW is included because
# an unclassified value is still worth proposing a *known-good* target
# for, clearly labeled as such.
REMEDIABLE_STATES = ("FAIL", "MISSING", "REVIEW")


@dataclass
class RemediationProposal:
    control_id: str
    canonical_field: str
    vendor: str
    remediation_commands: list[str]
    rollback_commands: list[str]
    verification_command: str | None
    requires_parameters: bool
    required_parameters: list[str] = field(default_factory=list)
    syntax_confidence: str | None = None
    rollback_confidence: str | None = None
    manually_authored: bool = False
    notes: str | None = None
    linked_controls: list[str] = field(default_factory=list)
    conflict_check: str = "not_available"  # TODO(Phase 8): replace once the CDG conflict checker exists


def _extract_placeholders(commands: list[str]) -> list[str]:
    seen: list[str] = []
    for line in commands:
        for name in PLACEHOLDER_RE.findall(line):
            if name not in seen:
                seen.append(name)
    return seen


def build_remediation(control_id: str, vendor: str, tables: RuleTables | None = None) -> RemediationProposal | None:
    """Looks up the remediation rule for one control/vendor pair.
    Returns None if no remediation rule is defined (e.g. always_compliant
    controls like PAN-OS SSHv2, which have empty command lists)."""
    tables = tables or get_default_tables()
    meta = tables.controls.get(control_id)
    if meta is None:
        return None
    rdef = tables.remediation.get((meta.canonical_field, vendor))
    if rdef is None:
        return None
    commands = rdef.get("remediation_commands") or []
    if not commands:
        return None  # e.g. platform-inherent controls with nothing to remediate

    rollback = rdef.get("rollback_commands") or []
    all_commands = commands + rollback
    required_params = _extract_placeholders(all_commands)

    return RemediationProposal(
        control_id=control_id,
        canonical_field=meta.canonical_field,
        vendor=vendor,
        remediation_commands=commands,
        rollback_commands=rollback,
        verification_command=rdef.get("verification_command"),
        requires_parameters=bool(rdef.get("requires_parameters")) or bool(required_params),
        required_parameters=required_params,
        syntax_confidence=rdef.get("syntax_confidence"),
        rollback_confidence=rdef.get("rollback_confidence"),
        manually_authored=bool(rdef.get("manually_authored")),
        notes=rdef.get("notes"),
        linked_controls=tables.linked_controls_for(control_id, vendor),
    )


def propose_remediation_for_evidence(evidence, tables: RuleTables | None = None) -> RemediationProposal | None:
    """Convenience wrapper: takes a compliance_diff.EvidenceResult and only
    proposes remediation when the state actually warrants it."""
    if evidence.state not in REMEDIABLE_STATES:
        return None
    return build_remediation(evidence.control_id, evidence.vendor, tables)


def fill_parameters(commands: list[str], values: dict[str, str]) -> list[str]:
    """Substitutes <PLACEHOLDER> tokens with caller-supplied values.
    Raises KeyError naming the first missing placeholder rather than
    silently emitting a command with an unfilled <TOKEN> in it -- a
    half-filled remediation command is worse than an explicit error."""
    filled = []
    for line in commands:
        def _sub(m: re.Match) -> str:
            name = m.group(1)
            if name not in values:
                raise KeyError(f"Missing required parameter: {name}")
            return values[name]
        filled.append(PLACEHOLDER_RE.sub(_sub, line))
    return filled