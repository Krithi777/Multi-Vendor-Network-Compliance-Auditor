"""PDF compliance report generation (Phase 9, milestone 12 of the plan).

Renders a Jinja2 HTML template of a completed scan's real data
(device info, summary, per-framework coverage, findings, remediation
preview) and converts it to PDF bytes with xhtml2pdf.

xhtml2pdf instead of WeasyPrint: same Jinja2-driven approach the plan
asks for, but pure-Python -- no Pango/Cairo/GDK system libraries to
install on a teammate's machine or a judge's laptop the night of the
demo. If a heavier/prettier renderer is wanted later, only
_html_to_pdf_bytes() below needs to change; build_report_context() and
the template are renderer-agnostic.

Nothing here invents data: every value comes from repository.py reads
of the same tables the /api/findings and /api/remediation endpoints
use. A scan that isn't done/found raises ReportError, which api.py
turns into the matching HTTP status.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import repository
from .remediation import build_remediation

TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)

# Display order + labels for the framework-coverage section. Matches the
# frameworks shape get_findings() already returns (Section 4 contract).
FRAMEWORKS = [
    ("cis", "CIS"),
    ("stig", "DISA STIG"),
    ("iso_27001", "ISO 27001"),
    ("nist_800_53", "NIST 800-53"),
]

VENDOR_LABELS = {
    "cisco_ios": "Cisco IOS",
    "juniper_junos": "Juniper Junos",
    "fortios": "FortiOS",
    "panos": "PAN-OS",
    "arista_eos": "Arista EOS",
    "unknown": "Unknown vendor",
}


class ReportError(Exception):
    """Raised for any condition api.py should turn into a 4xx, so the
    HTTP-status decision stays in api.py rather than duplicated here."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class RemediationPreview:
    control_id: str
    canonical_field: str
    commands: list[str]
    verification_command: str | None
    rollback_commands: list[str]
    # Context carried over from the finding row, so the remediation
    # section reads standalone without flipping back to the findings
    # table to see what's actually wrong and how urgent it is.
    severity: str | None = None
    description: str | None = None
    expected_value: str | None = None
    observed_value: str | None = None
    # Surfaced from RemediationProposal -- previously computed by
    # build_remediation() but dropped on the floor before reaching the
    # template, so the PDF understated how much the engine actually
    # knows about each fix.
    requires_parameters: bool = False
    required_parameters: list[str] = None
    syntax_confidence: str | None = None
    rollback_confidence: str | None = None
    manually_authored: bool = False
    notes: str | None = None
    conflict_check: str = "not_available"


def _framework_coverage(results: list[dict], scan_frameworks: list[str]) -> list[dict]:
    """One row per *selected* framework the findings actually reference,
    with a PASS/FAIL/MISSING/REVIEW breakdown -- never a fabricated
    'covered' flag for a framework no control in this scan cites.

    Bug fix: this used to loop over all 4 known frameworks regardless of
    which ones the user picked on the New Scan page, because a control's
    `frameworks` dict carries every framework it maps to (a control can
    legitimately satisfy CIS *and* ISO 27001 *and* NIST at once) -- that
    field was never scoped to what the user selected. So even a scan run
    with only "CIS" chosen would still show DISA STIG/ISO/NIST rows here,
    since some control in the results happened to also cite them. Scoping
    the loop to scan_frameworks (the scan's own frameworks_scanned) is
    what actually makes "pick a framework -> report only covers that
    framework" true."""
    rows = []
    for key, label in FRAMEWORKS:
        if key not in scan_frameworks:
            continue
        refs = 0
        counts = {"PASS": 0, "FAIL": 0, "MISSING": 0, "REVIEW": 0, "NOT_APPLICABLE": 0}
        for r in results:
            fw = (r.get("frameworks") or {}).get(key)
            if fw:
                refs += 1
                counts[r["state"]] = counts.get(r["state"], 0) + 1
        if refs:
            rows.append({"label": label, "control_count": refs, "counts": counts})
    return rows


def _severity_breakdown(results: list[dict]) -> dict:
    """Counts open findings (FAIL/MISSING/REVIEW) by severity. Purely a
    re-aggregation of the severity field get_findings() already returns
    per row -- no new data source, just a summary the template can lead
    with instead of forcing the reader to tally the findings table."""
    counts = {"high": 0, "medium": 0, "low": 0}
    for r in results:
        if r["state"] in ("FAIL", "MISSING", "REVIEW"):
            sev = (r.get("severity") or "low").lower()
            if sev in counts:
                counts[sev] += 1
    return counts


def build_report_context(scan_id: str) -> dict:
    """Gathers everything the template needs. Raises ReportError if the
    scan doesn't exist or isn't in a reportable state -- same rules
    get_findings() already applies, so a report is never generated for
    a scan whose findings page would itself 404/409/422."""
    scan = repository.get_scan(scan_id)
    if scan is None:
        raise ReportError(404, "scan_id not found")
    if scan["status"] == "processing":
        raise ReportError(409, "Scan is still processing.")
    if scan["status"] == "error":
        raise ReportError(422, scan.get("error_message") or "Scan failed.")

    rows = repository.get_findings(scan_id)
    summary = repository.summarize_findings(rows)
    total = sum(summary.values()) or 1
    compliant_pct = round(100 * summary.get("PASS", 0) / total, 1)

    vendor = scan["vendor"] or "unknown"
    scan_frameworks = scan.get("frameworks_scanned") or [key for key, _ in FRAMEWORKS]
    remediations: list[RemediationPreview] = []
    for r in rows:
        if r["state"] not in ("FAIL", "MISSING"):
            continue
        proposal = build_remediation(r["control_id"], vendor)
        if proposal is not None:
            remediations.append(
                RemediationPreview(
                    control_id=proposal.control_id,
                    canonical_field=proposal.canonical_field,
                    commands=proposal.remediation_commands,
                    verification_command=proposal.verification_command,
                    rollback_commands=proposal.rollback_commands,
                    severity=r.get("severity"),
                    description=r.get("description") or proposal.canonical_field,
                    expected_value=r.get("expected_value"),
                    observed_value=r.get("observed_value"),
                    requires_parameters=proposal.requires_parameters,
                    required_parameters=proposal.required_parameters,
                    syntax_confidence=proposal.syntax_confidence,
                    rollback_confidence=proposal.rollback_confidence,
                    manually_authored=proposal.manually_authored,
                    notes=proposal.notes,
                    conflict_check=proposal.conflict_check,
                )
            )

    return {
        "scan_id": scan_id,
        "vendor": vendor,
        "vendor_label": VENDOR_LABELS.get(vendor, vendor),
        "filename": scan["filename"],
        "uploaded_at": scan["uploaded_at"].isoformat() if scan.get("uploaded_at") else None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "device": {
            "hostname": scan.get("hostname"),
            "model": scan.get("model"),
            "serial_number": scan.get("serial_number"),
            "os_version": scan.get("os_version"),
        },
        "summary": summary,
        "compliant_pct": compliant_pct,
        "severity_breakdown": _severity_breakdown(rows),
        "framework_coverage": _framework_coverage(rows, scan_frameworks),
        "results": rows,
        "remediations": remediations,
    }


def _html_to_pdf_bytes(html: str) -> bytes:
    # Local import: keeps xhtml2pdf off the import path for every other
    # module that imports phase9.report indirectly (e.g. tests that only
    # need build_report_context / ReportError).
    from io import BytesIO

    from xhtml2pdf import pisa

    buffer = BytesIO()
    result = pisa.CreatePDF(src=html, dest=buffer)
    if result.err:
        raise ReportError(500, "PDF rendering failed.")
    return buffer.getvalue()


def render_report_pdf(scan_id: str) -> bytes:
    """The one function api.py calls. Raises ReportError on any
    not-ready/not-found scan; returns raw PDF bytes on success."""
    context = build_report_context(scan_id)
    template = _env.get_template("compliance_report.html")
    html = template.render(**context)
    return _html_to_pdf_bytes(html)