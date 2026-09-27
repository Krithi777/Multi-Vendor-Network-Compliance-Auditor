"""FastAPI app (Phase 9, milestones 4, 9, 10 & 11 of the plan).

Implements the API contract Member B builds the frontend against
verbatim -- field names below are not placeholders, they're the
contract. `/ingest` processing runs in a BackgroundTask so the response
comes back immediately with status="processing"; the frontend polls
GET /api/scans/{id} until status is "done" or "error".

Milestone 10 (Training Studio) persistence: TeachingSessionManager is
backed by phase7.db_repository.PostgresTeachingRepository whenever the
DB engine is reachable, so confirmations/templates/decisions survive a
restart (the phase7_teaching_sessions / phase7_confirmed_examples /
phase7_mapping_decisions tables in db/phase7_migration.sql -- if the
engine can't be built, e.g. running the API without Postgres configured
for local frontend iteration, this falls back to an in-memory
repository and says so at startup rather than crashing.

One thing that is still process-memory only, called out rather than
hidden: `_cluster_sessions` (which phase7 session_id backs which
unmatched-line cluster of which scan) and `_decision_log` (the
human-readable accept/reject feed the Training Studio UI shows). The
underlying teaching state persists; this join/log does not yet. See
IMPLEMENTATION_NOTES.md.
"""
from __future__ import annotations

import time
import uuid
from collections import Counter

from fastapi import BackgroundTasks, FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import repository
from .bulk_ingest import BulkValidationError, decode_batch
from .compliance_diff import run_compliance_diff
from .device_info import extract_device_info
from .mapping_loader import get_default_tables
from .normalizer import normalize_config
from .remediation import build_remediation
from .dynamic_report import render_dynamic_report_pdf
from .report import ReportError, render_report_pdf
from .sanitizer import sanitize_config
from .unmatched_clustering import ClusterInfo, cluster_unmatched_lines, find_cluster_for_line
from .vendor_detect import detect_vendor

from phase7.control_loader import load_controls
from phase7.matcher import Phase7Matcher
from phase7.schemas import TeachingState
from phase7.teaching_session import InMemoryTeachingRepository, TeachingSessionManager
from phase7 import api as phase7_api
from .mapping_loader import CONTROL_SCHEMA_PATH

app = FastAPI(title="Multi-Vendor Network Compliance Auditor -- Phase 9 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before real deployment; fine for hackathon demo
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_teaching_repository():
    """Postgres-backed by default; falls back to in-memory (and says so)
    if the engine can't be constructed, so `uvicorn phase9.api:app` still
    boots for frontend-only iteration without a DATABASE_URL set."""
    try:
        from db.common import get_engine
        from phase7.db_repository import PostgresTeachingRepository

        engine = get_engine()
        with engine.connect():
            pass  # fail fast here, not on the first confirm request
        return PostgresTeachingRepository(engine)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad; any DB problem should degrade, not crash
        print(f"[phase9.api] Teaching sessions are IN-MEMORY ONLY -- Postgres unavailable ({exc}).")
        return InMemoryTeachingRepository()


# bge=None (no vector fallback wired up yet); MEDIUM-bucket matches fall
# straight to ADMIN_REVIEW, which is correct/honest behavior, just not
# the fully-resolved Phase 7 experience.
_matcher = Phase7Matcher(load_controls(CONTROL_SCHEMA_PATH))
_teaching_manager = TeachingSessionManager(_matcher, repository=_build_teaching_repository())

# scan_id -> {cluster_id: phase7 session_id}. Join index only -- the
# session data itself is durable (see module docstring); losing this
# mapping across a restart means a resumed cluster starts a fresh
# session rather than reattaching to its old one. Good enough for a
# hackathon-length build; a follow-up would key sessions deterministically
# off (scan_id, cluster_id) instead of uuid4 to remove this gap entirely.
_cluster_sessions: dict[str, dict[str, str]] = {}
_decision_log: dict[str, list[dict]] = {}  # scan_id -> events, newest last

# Which of the 4 frameworks a scan was run against (New Scan page
# selector). Persisted on the scans table (frameworks_scanned column,
# db/phase9_migration_v3.sql) -- previously a process-memory dict here,
# which meant a backend restart (dev --reload included) or a second
# worker process silently lost the selection and get_scan() fell back to
# "all four", regardless of what was actually picked at ingest time.
ALL_FRAMEWORKS = ["cis", "stig", "iso_27001", "nist_800_53"]


def _parse_frameworks(frameworks: str | None) -> list[str]:
    """?frameworks=cis,stig -- comma-separated, validated against the 4
    known keys. None/empty means "all four" (the pre-existing, unfiltered
    behavior), so this stays backward compatible for any caller that
    doesn't pass the param at all."""
    if not frameworks:
        return list(ALL_FRAMEWORKS)
    requested = [f.strip() for f in frameworks.split(",") if f.strip()]
    unknown = [f for f in requested if f not in ALL_FRAMEWORKS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown framework(s): {unknown}. Valid: {ALL_FRAMEWORKS}")
    if not requested:
        raise HTTPException(status_code=400, detail="At least one framework must be selected.")
    return requested


@app.get("/api/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------------------- controls --

@app.get("/api/controls")
def list_controls():
    """Not in the original Section 4 contract -- added for milestone 10
    (Training Studio). The Accept/Modify decision needs a canonical_field
    picker; this exposes the same control_schema data the normalizer and
    compliance-diff engine already load via mapping_loader, so the
    frontend isn't left guessing field names by hand."""
    tables = get_default_tables()
    return {
        "controls": [
            {
                "control_id": c.control_id,
                "canonical_field": c.canonical_field,
                "description": c.description,
            }
            for c in sorted(tables.controls.values(), key=lambda c: c.control_id)
        ]
    }


# ---------------------------------------------------------------- ingest --

def _process_scan(scan_id: str, raw_text: str, vendor_override: str | None, frameworks: list[str]) -> None:
    try:
        if vendor_override:
            vendor, confidence, candidates = vendor_override, "confirmed", [vendor_override]
        else:
            detection = detect_vendor(raw_text)
            if detection.vendor is None:
                repository.set_scan_vendor(scan_id, None, detection.confidence, detection.candidates)
                repository.mark_scan_error(
                    scan_id,
                    f"Vendor could not be determined ({detection.confidence}). "
                    f"Candidates: {detection.candidates or 'none'}. Re-upload with an explicit vendor.",
                )
                return
            vendor, confidence, candidates = detection.vendor, detection.confidence, detection.candidates

        repository.set_scan_vendor(scan_id, vendor, confidence, candidates)

        tables = get_default_tables()
        sanitized = sanitize_config(raw_text, vendor)
        repository.save_device_config(scan_id, sanitized)

        normalized = normalize_config(raw_text, vendor, tables)
        results = run_compliance_diff(normalized, tables)
        if set(frameworks) != set(ALL_FRAMEWORKS):
            # Only keep findings for controls that map to at least one of
            # the selected frameworks -- a control with no ref in any
            # selected framework isn't part of what this scan was asked
            # to audit against, so it's dropped rather than shown as a
            # stray PASS/FAIL/MISSING with no relevant framework attached.
            #
            # KNOWN LIMITATION (verified, not a bug to chase further): all
            # 20 locked controls in controls/control_schema_cis_stig_iso27001.json
            # carry a non-empty ref for cis, stig, iso_27001 AND nist_800_53
            # simultaneously -- there is no framework-exclusive control in
            # the current schema. So this filter can never actually drop a
            # control today; every combination of selected frameworks keeps
            # all 20. It's left in (harmless, and correct if the schema
            # ever grows a framework-specific control) but don't expect the
            # findings list to shrink when narrowing frameworks pre-scan --
            # only frameworks_scanned (report/UI labeling) changes.
            results = [
                r for r in results
                if any(r.frameworks.get(fw) for fw in frameworks)
            ]
        repository.save_findings(scan_id, results)
        repository.set_scan_frameworks(scan_id, frameworks)

        # Milestone 11 -- best-effort only; extract_device_info() returns
        # None for anything it can't find, and save_device_info() persists
        # those Nones as-is rather than inventing a placeholder.
        device = extract_device_info(raw_text, vendor)
        repository.save_device_info(scan_id, device)

        # Unmatched-line clusters are NOT precomputed/started here -- see
        # _get_clusters_for_scan. Starting one phase7 session per cluster
        # only happens lazily, the first time an admin confirms a mapping
        # for a line in that cluster (milestone 10).

        repository.mark_scan_done(scan_id)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the user via /api/scans, not swallowed
        repository.mark_scan_error(scan_id, str(exc))


def _validate_vendor_override(vendor: str | None) -> None:
    if vendor is not None and vendor not in get_default_tables().vendors_covered:
        raise HTTPException(status_code=400, detail=f"Unknown vendor override: {vendor!r}")


@app.post("/api/detect-vendor")
async def detect_vendor_preview(file: UploadFile):
    """Stateless vendor-detection preview for the New Scan page. Runs the
    same regex-signature detector /api/ingest uses internally, but does
    not create a scan or touch the repository at all -- this lets the
    frontend show "Detected vendor: Ambiguous (Cisco IOS / Arista EOS)"
    and let the person confirm *before* committing to a scan, instead of
    only finding out after a full ingest fails.

    Read-only and side-effect free by design, so it's safe to call once
    per file drop/pick without worrying about orphaned scan rows."""
    raw_bytes = await file.read()
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid UTF-8 text.")

    detection = detect_vendor(raw_text)
    return {
        "vendor": detection.vendor,
        "confidence": detection.confidence,  # "high" | "low" | "ambiguous" | "undetected"
        "candidates": detection.candidates,
        "scores": detection.scores,
    }


@app.post("/api/ingest")
async def ingest(background_tasks: BackgroundTasks, file: UploadFile, vendor: str | None = None, frameworks: str | None = None):
    raw_bytes = await file.read()
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid UTF-8 text.")

    _validate_vendor_override(vendor)
    selected_frameworks = _parse_frameworks(frameworks)

    scan_id = repository.create_scan(filename=file.filename or "unknown")
    background_tasks.add_task(_process_scan, scan_id, raw_text, vendor, selected_frameworks)
    return {"scan_id": scan_id, "status": "processing"}


@app.post("/api/ingest/bulk")
async def ingest_bulk(background_tasks: BackgroundTasks, files: list[UploadFile], vendor: str | None = None, frameworks: str | None = None):
    """Milestone 11, Section 6B. Each file follows the exact same
    vendor-detect -> normalize -> compliance-diff -> device-info pipeline
    as a single /api/ingest upload (see _process_scan) -- the only thing
    bulk about this endpoint is the batch bookkeeping around it."""
    _validate_vendor_override(vendor)
    selected_frameworks = _parse_frameworks(frameworks)

    raw_pairs = [(f.filename, await f.read()) for f in files]
    try:
        decoded = decode_batch(raw_pairs)
    except BulkValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    batch_id = repository.create_batch(file_count=len(decoded))
    scan_ids: list[str] = []
    for upload in decoded:
        scan_id = repository.create_scan(filename=upload.filename, batch_id=batch_id)
        background_tasks.add_task(_process_scan, scan_id, upload.raw_text, vendor, selected_frameworks)
        scan_ids.append(scan_id)

    return {"batch_id": batch_id, "scan_ids": scan_ids, "status": "processing"}


# ----------------------------------------------------------------- scans --

def _device_dict(scan: dict) -> dict:
    """Shapes the device sub-object per the Section 4 contract. None for
    any field device_info.py couldn't extract -- never a placeholder."""
    return {
        "hostname": scan.get("hostname"),
        "vendor": scan.get("vendor"),
        "model": scan.get("model"),
        "serial_number": scan.get("serial_number"),
        "os_version": scan.get("os_version"),
    }


@app.get("/api/scans")
def list_scans(vendor: str | None = None, batch_id: str | None = None):
    """Not in the original Section 4 contract -- added for milestone 8
    (Dashboard + vendor filter), which has no data source without a way
    to list scans. Optional ?vendor= filters server-side; the frontend
    also filters client-side for instant toggling without a refetch.
    ?batch_id= (milestone 11) lets the frontend show "how did my bulk
    upload turn out" as a filtered view of this same endpoint."""
    scan_rows = repository.list_scans(vendor=vendor, batch_id=batch_id)
    scan_ids = [str(r["scan_id"]) for r in scan_rows]
    summaries = repository.summarize_findings_by_scan(scan_ids)
    empty_summary = {"PASS": 0, "FAIL": 0, "MISSING": 0, "REVIEW": 0, "NOT_APPLICABLE": 0}
    return {
        "scans": [
            {
                "scan_id": str(r["scan_id"]),
                "status": r["status"],
                "vendor": r["vendor"] or "unknown",
                "filename": r["filename"],
                "uploaded_at": r["uploaded_at"].isoformat(),
                "batch_id": str(r["batch_id"]) if r["batch_id"] else None,
                "summary": summaries.get(str(r["scan_id"]), empty_summary),
            }
            for r in scan_rows
        ]
    }


@app.get("/api/scans/{scan_id}")
def get_scan(scan_id: str):
    scan = repository.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan_id not found")
    # vendor_confidence/vendor_candidates/error_message were already being
    # written to the scans table (set_scan_vendor / mark_scan_error) but
    # were being dropped here -- the frontend has no way to build a manual
    # vendor-override UI, or show a real failure reason, without them.
    return {
        "scan_id": str(scan["scan_id"]),
        "status": scan["status"],
        "vendor": scan["vendor"] or "unknown",
        "vendor_confidence": scan["vendor_confidence"],
        "vendor_candidates": scan["vendor_candidates"] or [],
        "error_message": scan["error_message"] if scan["status"] == "error" else None,
        "filename": scan["filename"],
        "uploaded_at": scan["uploaded_at"].isoformat(),
        "batch_id": str(scan["batch_id"]) if scan["batch_id"] else None,
        "device": _device_dict(scan),
        "frameworks_scanned": scan["frameworks_scanned"] or ALL_FRAMEWORKS,
    }


# -------------------------------------------------------------- findings --

@app.get("/api/findings/{scan_id}")
def get_findings(scan_id: str):
    scan = repository.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan_id not found")
    if scan["status"] == "processing":
        raise HTTPException(status_code=409, detail="Scan is still processing.")
    if scan["status"] == "error":
        raise HTTPException(status_code=422, detail=scan["error_message"] or "Scan failed.")

    rows = repository.get_findings(scan_id)
    summary = repository.summarize_findings(rows)
    results = [
        {
            "control_id": r["control_id"],
            "canonical_field": r["canonical_field"],
            "state": r["state"],
            "description": r["description"],
            "severity": r["severity"],
            "expected_value": r["expected_value"],
            "observed_value": r["observed_value"],
            "evidence_line": r["evidence_line"],
            "evidence_line_number": r["evidence_line_number"],
            "context_category": r["context_category"],
            "frameworks": r["frameworks"],
            "linked_controls": r["linked_controls"],
            "notes": r["notes"],
        }
        for r in rows
    ]
    return {"scan_id": scan_id, "vendor": scan["vendor"], "summary": summary, "results": results}


# ------------------------------------------------------------ remediation --

@app.get("/api/remediation/{scan_id}/{control_id}")
def get_remediation(scan_id: str, control_id: str):
    scan = repository.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan_id not found")
    if not scan["vendor"]:
        raise HTTPException(status_code=422, detail="Scan has no confirmed vendor yet.")

    proposal = build_remediation(control_id, scan["vendor"])
    if proposal is None:
        raise HTTPException(status_code=404, detail="No remediation defined for this control/vendor.")

    return {
        "control_id": proposal.control_id,
        "canonical_field": proposal.canonical_field,
        "vendor": proposal.vendor,
        "commands": proposal.remediation_commands,
        "verification_command": proposal.verification_command,
        "rollback_commands": proposal.rollback_commands,
        "conflict_check": proposal.conflict_check,
    }


# ----------------------------------------------------------------- reports --
#
# Milestone 12. Same data get_findings()/get_remediation() already serve,
# assembled into one PDF (report.py) rather than duplicated here -- this
# endpoint is a thin HTTP wrapper, same shape as every route above it.

@app.get("/api/reports/{scan_id}/pdf")
def get_report_pdf(scan_id: str):
    try:
        pdf_bytes = render_report_pdf(scan_id)
    except ReportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="compliance-report-{scan_id[:8]}.pdf"'
        },
    )


# Second reporting engine (dynamic_report.py, ReportLab): the "customized
# per device model/software version" deliverable, kept as its own route
# rather than a flag on the endpoint above so the two engines stay easy
# to tell apart from the frontend down to the network request.
class DynamicReportRequest(BaseModel):
    prepared_by: str | None = None
    comments: str | None = None


@app.post("/api/reports/{scan_id}/dynamic-pdf")
def get_dynamic_report_pdf(scan_id: str, body: DynamicReportRequest | None = None):
    prepared_by = body.prepared_by if body else None
    comments = body.comments if body else None
    try:
        pdf_bytes = render_dynamic_report_pdf(scan_id, prepared_by=prepared_by, comments=comments)
    except ReportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="device-report-{scan_id[:8]}.pdf"'
        },
    )


# -------------------------------------------------------- unmatched/train --
#
# Milestone 10 (Training Studio). The flat "list of raw lines" shape from
# the original Section 4 contract sketch is gone -- it made every admin
# eyeball 40+ unrelated lines to find 3 that teach the same field. This
# groups them into clusters first (phase9.unmatched_clustering) so the
# frontend can show "14 lines look like this one" the way SentinelGrid's
# Training Studio wireframe does, and only surfaces a fusion-score
# suggestion once one is real (>=3 confirmations + generalization ran --
# never fabricated for an untaught cluster).


def _get_clusters_for_scan(scan_id: str) -> tuple[dict, list[ClusterInfo]]:
    """Recomputes unmatched-line clusters from the persisted sanitized
    config, rather than caching normalizer output in memory -- so this
    endpoint gives the same answer before and after a restart. Redoing a
    regex pass over one config on each request is cheap; it is not run
    inside a hot loop."""
    scan = repository.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan_id not found")
    if scan["status"] == "processing":
        raise HTTPException(status_code=409, detail="Scan is still processing.")
    if scan["status"] == "error":
        raise HTTPException(status_code=422, detail=scan["error_message"] or "Scan failed.")

    device_config = repository.get_device_config(scan_id)
    if device_config is None:
        return scan, []

    tables = get_default_tables()
    normalized = normalize_config(device_config["sanitized_text"], scan["vendor"], tables)
    clusters = cluster_unmatched_lines(normalized.unmatched)
    scan = dict(scan)
    scan["_total_lines"] = normalized.total_lines
    scan["_unmatched_total"] = len(normalized.unmatched)
    return scan, clusters


def _field_to_control_id() -> dict[str, str]:
    tables = get_default_tables()
    return {c.canonical_field: c.control_id for c in tables.controls.values()}


def _cluster_suggestion(cluster: ClusterInfo, session_id: str | None) -> tuple[str, dict | None]:
    """Returns (state, suggestion|None). suggestion is only non-None once
    the cluster's session has generalized -- every number in it is an
    aggregate of real phase7.schemas.MatchResult objects, never a guess."""
    if session_id is None:
        return "untaught", None
    session = _teaching_manager.status(session_id)
    if session.state != TeachingState.COMPLETED or not session.results:
        return session.state.value.lower(), None

    results = session.results
    n = len(results)
    context_scores = [r.context_score for r in results if r.context_score is not None]
    generalized = sum(1 for r in results if r.final_mapping_status in ("auto_applied", "bge_resolved"))
    bucket = Counter(r.confidence_bucket for r in results).most_common(1)[0][0]
    field_to_control = _field_to_control_id()
    canonical_field = session.confirmations[0].canonical_field

    suggestion = {
        "canonical_field": canonical_field,
        "control_id": field_to_control.get(canonical_field),
        "matched_example": session.confirmations[0].raw_line,
        "template": session.template.text if session.template else None,
        "fused_confidence": round(sum(r.fusion_score for r in results) / n, 3),
        "confidence_bucket": bucket,
        "component_scores": {
            "syntax": round(sum(r.syntax_score for r in results) / n, 3),
            "context": round(sum(context_scores) / len(context_scores), 3) if context_scores else None,
            "value_semantics": round(sum(r.value_semantics_score for r in results) / n, 3),
            "framework_fit": round(sum(r.framework_fit_score for r in results) / n, 3),
            "precedent": round(sum(r.precedent_score for r in results) / n, 3),
        },
        "generalized_count": generalized,
        "remaining_count": n - generalized,
        "evaluated_count": n,
    }
    return session.state.value.lower(), suggestion


@app.get("/api/unmatched/{scan_id}")
def get_unmatched(scan_id: str):
    scan, clusters = _get_clusters_for_scan(scan_id)
    cluster_sessions = _cluster_sessions.get(scan_id, {})

    out_clusters = []
    total_unresolved = 0
    for c in clusters:
        session_id = cluster_sessions.get(c.cluster_id)
        resolved_lines: set[str] = set()
        if session_id is not None:
            resolved_lines = {e.raw_line for e in _teaching_manager.status(session_id).confirmations}
        state, suggestion = _cluster_suggestion(c, session_id)
        unresolved_members = [m for m in c.members if m.raw_line not in resolved_lines]
        total_unresolved += len(unresolved_members)

        out_clusters.append({
            "cluster_id": c.cluster_id,
            "context_category": c.context_category,
            "representative_line": c.representative_line,
            "count": c.count,
            "resolved_count": len(resolved_lines),
            "state": state,
            "sample_lines": [
                {
                    "raw_line": m.raw_line, "line_number": m.line_number, "context_path": m.context_path,
                    "resolved": m.raw_line in resolved_lines,
                }
                for m in c.members[:6]
            ],
            "suggestion": suggestion,
        })

    total_lines = scan.get("_total_lines") or 0
    unmatched_total = scan.get("_unmatched_total") or 0
    coverage_before_pct = round(100 * (total_lines - unmatched_total) / total_lines, 1) if total_lines else None

    return {
        "scan_id": scan_id,
        "vendor": scan["vendor"],
        "coverage_before_pct": coverage_before_pct,
        "total_unresolved": total_unresolved,
        "clusters": out_clusters,
        "decision_log": list(reversed(_decision_log.get(scan_id, [])))[:20],
    }


class TrainingDecision(BaseModel):
    raw_line: str
    canonical_field: str
    decision: str  # accept | modify | reject
    cluster_id: str | None = None


def _log_decision(scan_id: str, event: dict) -> None:
    event = {**event, "at": time.time()}
    _decision_log.setdefault(scan_id, []).append(event)


@app.post("/api/training/{scan_id}/decision")
def post_training_decision(scan_id: str, body: TrainingDecision):
    scan, clusters = _get_clusters_for_scan(scan_id)

    cluster = next((c for c in clusters if c.cluster_id == body.cluster_id), None) if body.cluster_id else None
    if cluster is None:
        cluster = find_cluster_for_line(clusters, body.raw_line)
    if cluster is None:
        raise HTTPException(status_code=404, detail="raw_line is not an unresolved unmatched line for this scan.")

    if body.decision not in ("accept", "modify", "reject"):
        raise HTTPException(status_code=400, detail="decision must be accept|modify|reject")

    if body.decision == "reject":
        _log_decision(scan_id, {
            "type": "rejected", "raw_line": body.raw_line, "cluster_id": cluster.cluster_id,
            "canonical_field": None,
        })
        return {"status": "ok", "updated_mapping": None}

    cluster_sessions = _cluster_sessions.setdefault(scan_id, {})
    session_id = cluster_sessions.get(cluster.cluster_id)
    if session_id is None:
        session = _teaching_manager.start(
            scan["vendor"],
            [m.raw_line for m in cluster.members],
            unmatched_context_paths=[m.context_path for m in cluster.members],
            unmatched_source_metadata=[{"line_number": m.line_number} for m in cluster.members],
        )
        session_id = session.session_id
        cluster_sessions[cluster.cluster_id] = session_id

    updated = phase7_api.submit_admin_confirmation(
        _teaching_manager, session_id, body.raw_line, body.canonical_field,
    )
    _log_decision(scan_id, {
        "type": "edited" if body.decision == "modify" else "accepted",
        "raw_line": body.raw_line, "cluster_id": cluster.cluster_id,
        "canonical_field": body.canonical_field,
    })
    _, suggestion = _cluster_suggestion(cluster, session_id)
    return {"status": "ok", "updated_mapping": {
        "session_id": updated.session_id, "state": updated.state.value,
        "confirmed_count": len(updated.confirmations),
        "cluster_id": cluster.cluster_id,
        "suggestion": suggestion,
    }}