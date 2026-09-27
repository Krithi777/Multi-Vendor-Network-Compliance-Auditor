"""Loads the existing Phase 2/5 datasets (control schema, vendor_mappings,
remediation_rules) and reshapes them into the per-vendor rule tables the
Phase 9 normalizer, compliance-diff engine, and remediation engine need.

No new source-of-truth data is created here -- this only re-indexes what
Phase 1-5 already produced (controls/control_schema_cis_stig_iso27001.json,
mappings/vendor_mappings.json, remediation/remediation_rules.json).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

CONTROL_SCHEMA_PATH = ROOT / "controls" / "control_schema_cis_stig_iso27001.json"
VENDOR_MAPPINGS_PATH = ROOT / "mappings" / "vendor_mappings.json"
REMEDIATION_RULES_PATH = ROOT / "remediation" / "remediation_rules.json"

KNOWN_VENDORS = ("cisco_ios", "juniper_junos", "fortios", "panos", "arista_eos")

# Vendors whose config syntax is "flat" (the full hierarchy is embedded in
# each line, e.g. Junos/PAN-OS `set a b c d`) vs vendors that need an actual
# block/indent stack to know what context a line sits in.
FLAT_VENDORS = {"juniper_junos", "panos"}
BLOCK_VENDORS = {"cisco_ios", "arista_eos", "fortios"}


@dataclass(frozen=True)
class FieldRule:
    """One canonical_field's matching rule for one vendor."""
    control_id: str
    canonical_field: str
    vendor: str
    context_path: str | None
    match_regex: re.Pattern | None
    pass_line: str | None
    fail_line: str | None
    tri_state_capable: bool
    always_compliant: bool
    syntax_confidence: str | None
    notes: str | None
    operator: str
    expected_value: Any


@dataclass(frozen=True)
class ControlMeta:
    control_id: str
    canonical_field: str
    description: str | None
    operator: str
    expected_value: Any
    severity: str
    nist_800_53: list[str] = field(default_factory=list)
    cis: list[dict] = field(default_factory=list)
    stig: list[dict] = field(default_factory=list)
    iso_27001: list[str] = field(default_factory=list)
    is_mgmt_path: bool = False


def _compile(pattern: str | None) -> re.Pattern | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        # Vendor mapping regexes are hand-authored; fail loudly rather than
        # silently never matching a control.
        raise ValueError(f"Invalid match_regex: {pattern!r}")


class RuleTables:
    """In-memory index built once from the JSON source-of-truth files.

    - controls: control_id -> ControlMeta
    - by_canonical_field: canonical_field -> ControlMeta
    - by_vendor: vendor -> [FieldRule, ...]  (all controls that vendor has
      a rule for, in control_id order -- used by the normalizer)
    - remediation: (canonical_field, vendor) -> remediation rule dict
    """

    def __init__(self, controls_path=CONTROL_SCHEMA_PATH,
                 vendor_mappings_path=VENDOR_MAPPINGS_PATH,
                 remediation_path=REMEDIATION_RULES_PATH):
        control_rows = json.loads(Path(controls_path).read_text(encoding="utf-8"))
        self.controls: dict[str, ControlMeta] = {}
        self.by_canonical_field: dict[str, ControlMeta] = {}
        for row in control_rows:
            meta = ControlMeta(
                control_id=row["control_id"],
                canonical_field=row["canonical_field"],
                description=row.get("description"),
                operator=row["operator"],
                expected_value=row["expected_value"],
                severity=row["severity"],
                nist_800_53=row.get("nist_800_53", []),
                cis=row.get("cis", []),
                stig=row.get("stig", []),
                iso_27001=row.get("iso_27001", []),
                is_mgmt_path=row.get("is_mgmt_path", False),
            )
            self.controls[meta.control_id] = meta
            self.by_canonical_field[meta.canonical_field] = meta

        vendor_doc = json.loads(Path(vendor_mappings_path).read_text(encoding="utf-8"))
        self.vendors_covered: list[str] = vendor_doc.get("vendors_covered", list(KNOWN_VENDORS))

        self.by_vendor: dict[str, list[FieldRule]] = {v: [] for v in self.vendors_covered}
        for control_id, cdef in vendor_doc["controls"].items():
            canonical_field = cdef["canonical_field"]
            operator = cdef.get("operator")
            expected_value = cdef.get("expected_value")
            for vendor, vdef in cdef["vendors"].items():
                rule = FieldRule(
                    control_id=control_id,
                    canonical_field=canonical_field,
                    vendor=vendor,
                    context_path=vdef.get("context_path"),
                    match_regex=_compile(vdef.get("match_regex")),
                    pass_line=vdef.get("pass_line"),
                    fail_line=vdef.get("fail_line"),
                    tri_state_capable=vdef.get("tri_state_capable", True),
                    always_compliant=vdef.get("always_compliant", False),
                    syntax_confidence=vdef.get("syntax_confidence"),
                    notes=vdef.get("notes"),
                    operator=operator,
                    expected_value=expected_value,
                )
                self.by_vendor.setdefault(vendor, []).append(rule)

        remediation_doc = json.loads(Path(remediation_path).read_text(encoding="utf-8"))
        self.remediation: dict[tuple[str, str], dict] = {}
        for control_id, rdef in remediation_doc.items():
            canonical_field = rdef["canonical_field"]
            for vendor, vdef in rdef["vendors"].items():
                self.remediation[(canonical_field, vendor)] = {
                    "control_id": control_id,
                    "canonical_field": canonical_field,
                    "vendor": vendor,
                    **vdef,
                }

        # Linked controls: two (control_id, vendor) rules whose match_regex is
        # byte-identical share detection evidence -- there is no config-level
        # way to tell which control a matching line "belongs to" (e.g. PAN-OS
        # CTRL-015/CTRL-017 both key off the same `set ... permitted-ip` line).
        # Surfacing this explicitly in reports beats pretending they're
        # independently verified.
        self.linked_controls: dict[tuple[str, str], list[str]] = {}
        by_pattern: dict[tuple[str, str], list[str]] = {}
        for vendor, rules in self.by_vendor.items():
            per_vendor_patterns: dict[str, list[str]] = {}
            for rule in rules:
                if rule.match_regex is None:
                    continue
                per_vendor_patterns.setdefault(rule.match_regex.pattern, []).append(rule.control_id)
            for pattern, control_ids in per_vendor_patterns.items():
                if len(control_ids) > 1:
                    for cid in control_ids:
                        others = [c for c in control_ids if c != cid]
                        self.linked_controls[(cid, vendor)] = others

    def rules_for_vendor(self, vendor: str) -> list[FieldRule]:
        if vendor not in self.by_vendor:
            raise KeyError(f"Unknown/unsupported vendor: {vendor!r}. "
                            f"Known vendors: {sorted(self.by_vendor)}")
        return self.by_vendor[vendor]

    def linked_controls_for(self, control_id: str, vendor: str) -> list[str]:
        """Other control_ids (same vendor) whose match_regex is identical to
        this control's -- i.e. detection evidence is shared, not independent."""
        return self.linked_controls.get((control_id, vendor), [])


_default_tables: RuleTables | None = None


def get_default_tables() -> RuleTables:
    global _default_tables
    if _default_tables is None:
        _default_tables = RuleTables()
    return _default_tables