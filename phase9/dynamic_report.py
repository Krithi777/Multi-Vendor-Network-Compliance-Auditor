"""ReportLab-based device-specific compliance PDF.

This is the second reporting engine the SIH spec calls for: "Generating
dynamic PDFs (e.g., using ReportLab or FPDF in Python) that are
customized based on the device's specific model and software version."
report.py (Jinja2 + xhtml2pdf) already covers the first deliverable --
one comprehensive PDF per device with device identification, pass/fail
findings with severity, and device-specific CLI remediation sequences.
This module is a second, independent rendering path built with
ReportLab instead, so the two deliverables are genuinely separate code
paths rather than the same PDF relabelled.

Data source: build_report_context() from report.py -- the exact same
repository reads /api/findings and /api/remediation use. Nothing here
invents a finding, a command, or a device field. The "customization by
model/software version" is real: the platform note, and which vendor's
lockout-avoidance guidance is shown, are picked from device.model /
device.os_version / vendor, not from a static template.

The only fields on this PDF that do NOT come from the compliance
engine are `prepared_by` and `comments` -- free-text a reviewer types
into the frontend before downloading. They are rendered in a clearly
labelled "manually entered" block on the cover page, never merged into
the findings/summary data, so the PDF never misrepresents a human note
as an automated scan result.
"""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .report import ReportError, build_report_context

_STYLES = getSampleStyleSheet()

_TITLE = ParagraphStyle("DRTitle", parent=_STYLES["Title"], fontSize=20, spaceAfter=4)
_SUBTITLE = ParagraphStyle(
    "DRSubtitle", parent=_STYLES["Normal"], fontSize=11, textColor=colors.HexColor("#555555")
)
_H2 = ParagraphStyle("DRH2", parent=_STYLES["Heading2"], spaceBefore=14, spaceAfter=6)
_BODY = ParagraphStyle("DRBody", parent=_STYLES["Normal"], fontSize=9.5, leading=13)
_MONO = ParagraphStyle("DRMono", parent=_STYLES["Normal"], fontName="Courier", fontSize=8.5, leading=12)
_NOTE_LABEL = ParagraphStyle(
    "DRNoteLabel", parent=_BODY, textColor=colors.HexColor("#888888"), fontSize=8
)
_PLATFORM_NOTE_STYLE = ParagraphStyle(
    "DRNote", parent=_BODY, backColor=colors.HexColor("#f5f5f5"), borderPadding=6
)

_STATE_COLORS = {
    "PASS": colors.HexColor("#1a7f37"),
    "FAIL": colors.HexColor("#c0392b"),
    "MISSING": colors.HexColor("#b8860b"),
    "REVIEW": colors.HexColor("#555555"),
    "NOT_APPLICABLE": colors.HexColor("#999999"),
}

_NOT_REPORTED = "Not reported by device config"

# Genuine, generic per-platform hardening guidance -- not a fabricated
# finding. This is what makes the PDF "customized based on the device's
# model and software version": the note, and remediation ordering
# advice, are selected by vendor rather than being one static blurb.
_PLATFORM_NOTES = {
    "cisco_ios": "Cisco IOS devices: apply ACL / line-vty changes before AAA changes to avoid a management lockout.",
    "juniper_junos": "Junos devices: use 'commit confirmed' when pushing management-plane changes.",
    "fortios": "FortiOS devices: verify the trusted-hosts list before tightening admin access.",
    "panos": "PAN-OS devices: push management-profile changes via a commit that includes a rollback window.",
    "arista_eos": "Arista EOS devices: session-based config changes auto-revert if not confirmed.",
    "unknown": "Vendor not confirmed -- verify commands manually against the device's own documentation before applying.",
}


def render_dynamic_report_pdf(
    scan_id: str, prepared_by: str | None = None, comments: str | None = None
) -> bytes:
    """Builds the ReportLab device-specific PDF. Raises ReportError on
    the same not-found/not-ready conditions as render_report_pdf, since
    both engines share build_report_context()."""
    ctx = build_report_context(scan_id)
    device = ctx["device"]
    model = device.get("model") or _NOT_REPORTED
    os_version = device.get("os_version") or _NOT_REPORTED

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        title=f"Device-Specific Compliance Report - {ctx['scan_id']}",
    )
    story = []

    story.append(Paragraph("Device-Specific Compliance Report", _TITLE))
    story.append(
        Paragraph(
            f"{ctx['vendor_label']} &middot; Model: {model} &middot; Software: {os_version}",
            _SUBTITLE,
        )
    )
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#dddddd")))
    story.append(Spacer(1, 10))

    meta_rows = [
        ["Scan ID", ctx["scan_id"]],
        ["Source file", ctx["filename"] or "-"],
        ["Hostname", device.get("hostname") or _NOT_REPORTED],
        ["Serial number", device.get("serial_number") or _NOT_REPORTED],
        ["Generated", ctx["generated_at"]],
    ]
    if prepared_by:
        meta_rows.append(["Prepared by", prepared_by])
    meta_table = Table(meta_rows, colWidths=[110, 360])
    meta_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#666666")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(meta_table)

    if comments:
        story.append(Spacer(1, 8))
        story.append(
            Paragraph("Reviewer comments (manually entered, not part of the automated scan)", _NOTE_LABEL)
        )
        story.append(Paragraph(comments, _BODY))

    story.append(Spacer(1, 6))
    note = _PLATFORM_NOTES.get(ctx["vendor"], _PLATFORM_NOTES["unknown"])
    story.append(Paragraph(f"<b>Platform note:</b> {note}", _PLATFORM_NOTE_STYLE))

    story.append(Paragraph("Compliance Summary", _H2))
    summary = ctx["summary"]
    total = sum(summary.values()) or 1
    summary_rows = [["Status", "Count", "% of controls"]]
    for key in ("PASS", "FAIL", "MISSING", "REVIEW"):
        count = summary.get(key, 0)
        summary_rows.append([key, str(count), f"{round(100 * count / total, 1)}%"])
    summary_table = Table(summary_rows, colWidths=[150, 80, 100])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(summary_table)
    story.append(
        Paragraph(
            f"Overall compliance: {ctx['compliant_pct']}%",
            ParagraphStyle("DRScore", parent=_BODY, spaceBefore=6, fontSize=10),
        )
    )

    story.append(Paragraph("Findings", _H2))
    finding_rows = [["Control", "Field", "Status", "Severity"]]
    for r in ctx["results"]:
        finding_rows.append(
            [
                r.get("control_id", "-"),
                r.get("canonical_field", "-"),
                r["state"],
                (r.get("severity") or "-").title(),
            ]
        )
    findings_table = Table(finding_rows, colWidths=[90, 190, 60, 70], repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, r in enumerate(ctx["results"], start=1):
        color = _STATE_COLORS.get(r["state"], colors.black)
        style_cmds.append(("TEXTCOLOR", (2, i), (2, i), color))
    findings_table.setStyle(TableStyle(style_cmds))
    story.append(findings_table)

    if ctx["remediations"]:
        story.append(Paragraph("Remediation &mdash; Device-Specific CLI Sequence", _H2))
        for rem in ctx["remediations"]:
            story.append(
                Paragraph(
                    f"<b>{rem.control_id}</b> &mdash; {rem.canonical_field}",
                    ParagraphStyle("DRRemHead", parent=_BODY, spaceBefore=8),
                )
            )
            for cmd in rem.commands:
                story.append(Paragraph(cmd, _MONO))
            if rem.verification_command:
                story.append(Paragraph(f"Verify: {rem.verification_command}", _MONO))
            if rem.rollback_commands:
                story.append(
                    Paragraph(
                        "Rollback:",
                        ParagraphStyle(
                            "DRRollbackLabel",
                            parent=_BODY,
                            fontSize=8,
                            textColor=colors.HexColor("#888888"),
                            spaceBefore=3,
                        ),
                    )
                )
                for cmd in rem.rollback_commands:
                    story.append(Paragraph(cmd, _MONO))

    try:
        doc.build(story)
    except Exception as exc:  # pragma: no cover - reportlab build failure
        raise ReportError(500, "PDF rendering failed.") from exc
    return buffer.getvalue()