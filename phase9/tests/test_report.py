"""Tests for phase9.report (milestone 12).

No Postgres involved: repository.get_scan/get_findings and
remediation.build_remediation are monkeypatched with fixed, realistic
return shapes (the same dict/dataclass shapes repository.py and
remediation.py actually produce) so this suite runs anywhere, same as
the rest of phase9/tests. What's under test is report.py's own
assembly and rendering logic, not the DB layer -- that's exercised by
hitting /api/reports/{scan_id}/pdf against a live Postgres instance
(see demo/run_5vendor_demo.sh), which this suite doesn't replace.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from phase9 import report


SCAN = {
    "scan_id": "11111111-1111-1111-1111-111111111111",
    "status": "done",
    "vendor": "cisco_ios",
    "filename": "router1-running-config.txt",
    "uploaded_at": datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc),
    "hostname": "core-sw-1",
    "model": None,
    "serial_number": None,
    "os_version": "16.9.4",
    "error_message": None,
}

FINDINGS_ROWS = [
    {
        "control_id": "CTRL-001",
        "canonical_field": "password_encryption",
        "state": "FAIL",
        "description": "Enable password encryption",
        "severity": "high",
        "expected_value": "enabled",
        "observed_value": "disabled",
        "evidence_line": "no service password-encryption",
        "evidence_line_number": 42,
        "context_category": None,
        "frameworks": {"cis": [{"rec_id": "5.1"}], "stig": [], "iso_27001": ["A.9.4"], "nist_800_53": []},
        "linked_controls": [],
        "notes": None,
    },
    {
        "control_id": "CTRL-002",
        "canonical_field": "ntp_auth",
        "state": "PASS",
        "description": "NTP authentication",
        "severity": "medium",
        "expected_value": "enabled",
        "observed_value": "enabled",
        "evidence_line": "ntp authenticate",
        "evidence_line_number": 88,
        "context_category": None,
        "frameworks": {"cis": [{"rec_id": "2.3"}], "stig": [], "iso_27001": [], "nist_800_53": []},
        "linked_controls": [],
        "notes": None,
    },
    {
        "control_id": "CTRL-003",
        "canonical_field": "banner_configured",
        "state": "MISSING",
        "description": "Login banner configured",
        "severity": "low",
        "expected_value": True,
        "observed_value": None,
        "evidence_line": None,
        "evidence_line_number": None,
        "context_category": None,
        "frameworks": {"cis": [], "stig": [], "iso_27001": [], "nist_800_53": []},
        "linked_controls": [],
        "notes": None,
    },
]

REMEDIATION_PROPOSAL = SimpleNamespace(
    control_id="CTRL-001",
    canonical_field="password_encryption",
    vendor="cisco_ios",
    remediation_commands=["service password-encryption"],
    verification_command="show running-config | include password-encryption",
    rollback_commands=["no service password-encryption"],
    conflict_check={"status": "future_work", "phase": 8, "message": "..."},
)


@pytest.fixture(autouse=True)
def _patch_repository(monkeypatch):
    monkeypatch.setattr(report.repository, "get_scan", lambda scan_id, engine=None: dict(SCAN))
    monkeypatch.setattr(report.repository, "get_findings", lambda scan_id, engine=None: FINDINGS_ROWS)
    monkeypatch.setattr(
        report.repository, "summarize_findings",
        lambda rows: {"PASS": 1, "FAIL": 1, "MISSING": 1, "REVIEW": 0, "NOT_APPLICABLE": 0},
    )
    monkeypatch.setattr(
        report, "build_remediation",
        lambda control_id, vendor: REMEDIATION_PROPOSAL if control_id == "CTRL-001" else None,
    )


def test_build_report_context_uses_real_findings_not_placeholders():
    ctx = report.build_report_context(SCAN["scan_id"])
    assert ctx["scan_id"] == SCAN["scan_id"]
    assert ctx["vendor"] == "cisco_ios"
    assert ctx["summary"] == {"PASS": 1, "FAIL": 1, "MISSING": 1, "REVIEW": 0, "NOT_APPLICABLE": 0}
    assert ctx["compliant_pct"] == pytest.approx(100 / 3, abs=0.1)
    assert ctx["results"] == FINDINGS_ROWS


def test_remediation_only_included_for_fail_and_missing_with_a_rule():
    ctx = report.build_report_context(SCAN["scan_id"])
    control_ids = {r.control_id for r in ctx["remediations"]}
    # CTRL-001 is FAIL and has a rule -> included.
    # CTRL-002 is PASS -> never eligible, regardless of a rule existing.
    # CTRL-003 is MISSING but build_remediation() returns None for it here
    # (no rule) -> correctly excluded rather than fabricated.
    assert control_ids == {"CTRL-001"}


def test_framework_coverage_only_lists_frameworks_actually_cited():
    ctx = report.build_report_context(SCAN["scan_id"])
    labels = {row["label"] for row in ctx["framework_coverage"]}
    # CIS and ISO 27001 are cited by the fixture rows above; STIG and
    # NIST are not cited by any row and must not appear as a fabricated
    # "0 controls" entry.
    assert labels == {"CIS", "ISO 27001"}


def test_report_error_for_processing_scan(monkeypatch):
    monkeypatch.setattr(report.repository, "get_scan", lambda scan_id, engine=None: {**SCAN, "status": "processing"})
    with pytest.raises(report.ReportError) as exc_info:
        report.build_report_context(SCAN["scan_id"])
    assert exc_info.value.status_code == 409


def test_report_error_for_missing_scan(monkeypatch):
    monkeypatch.setattr(report.repository, "get_scan", lambda scan_id, engine=None: None)
    with pytest.raises(report.ReportError) as exc_info:
        report.build_report_context("does-not-exist")
    assert exc_info.value.status_code == 404


def test_report_error_for_errored_scan(monkeypatch):
    monkeypatch.setattr(
        report.repository, "get_scan",
        lambda scan_id, engine=None: {**SCAN, "status": "error", "error_message": "vendor could not be determined"},
    )
    with pytest.raises(report.ReportError) as exc_info:
        report.build_report_context(SCAN["scan_id"])
    assert exc_info.value.status_code == 422


def test_render_report_pdf_produces_real_pdf_bytes():
    pdf_bytes = report.render_report_pdf(SCAN["scan_id"])
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500
