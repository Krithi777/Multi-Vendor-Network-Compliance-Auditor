"""DB read/write layer (Phase 9, milestone 5).

Everything here is a thin function over db_models' Table objects and
db.common.get_engine() -- no business logic lives in this module. That
lives in normalizer.py / compliance_diff.py / remediation.py; this file
only persists their output and reads it back for the API layer.

Two things worth knowing before touching this file:
- evidence_line is redacted with sanitizer.redact_line() at write time,
  never before -- compliance_diff.py must run against the real,
  unredacted config, and only the persisted/returned copy is redacted.
- findings has a UNIQUE (scan_id, control_id) constraint. save_findings()
  is safe to call twice for the same scan (e.g. a retry) because it
  upserts on that key rather than duplicating rows.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from db.common import get_engine
from .compliance_diff import EvidenceResult
from .db_models import batches, device_configs, findings, scans
from .device_info import DeviceInfo
from .sanitizer import SanitizeResult, redact_line


def create_scan(filename: str, engine: Engine | None = None, batch_id: str | None = None) -> str:
    """Inserts a new scan row with status='processing' and returns its scan_id.

    batch_id is optional and only set for files uploaded through
    /api/ingest/bulk (milestone 11) -- a plain /api/ingest upload leaves
    it null, same as before this column existed.
    """
    engine = engine or get_engine()
    scan_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(scans.insert().values(
            scan_id=scan_id, filename=filename, status="processing", batch_id=batch_id,
        ))
    return scan_id


def create_batch(file_count: int, engine: Engine | None = None) -> str:
    """Inserts a new batches row and returns its batch_id (milestone 11,
    Section 6B). Called once per /api/ingest/bulk request, before any of
    its per-file scans are created, so every scan in the batch can carry
    a valid batch_id from the start."""
    engine = engine or get_engine()
    batch_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(batches.insert().values(batch_id=batch_id, file_count=file_count))
    return batch_id


def set_scan_vendor(scan_id: str, vendor: str | None, confidence: str,
                     candidates: list[str] | None = None, engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(
            scans.update().where(scans.c.scan_id == scan_id).values(
                vendor=vendor, vendor_confidence=confidence, vendor_candidates=candidates or [],
            )
        )


def set_scan_frameworks(scan_id: str, frameworks: list[str], engine: Engine | None = None) -> None:
    """Persists which frameworks a scan was actually run against (New Scan
    page selector). Replaces the old process-memory `_scan_frameworks`
    dict in api.py, which was silently wiped on every backend restart and
    invisible across multiple workers -- see db/phase9_migration_v3.sql."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(
            scans.update().where(scans.c.scan_id == scan_id).values(frameworks_scanned=frameworks)
        )


def mark_scan_done(scan_id: str, engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(
            scans.update().where(scans.c.scan_id == scan_id)
            .values(status="done", completed_at=_now())
        )


def mark_scan_error(scan_id: str, message: str, engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(
            scans.update().where(scans.c.scan_id == scan_id)
            .values(status="error", error_message=message, completed_at=_now())
        )


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def save_device_info(scan_id: str, info: DeviceInfo, engine: Engine | None = None) -> None:
    """Persists the extracted hostname/model/serial/os_version onto the
    scan row (milestone 11, Section 6A). Fields device_info.py couldn't
    find stay NULL here too -- this never invents a value to fill a gap."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(
            scans.update().where(scans.c.scan_id == scan_id).values(
                hostname=info.hostname, model=info.model,
                serial_number=info.serial_number, os_version=info.os_version,
            )
        )


def get_scan(scan_id: str, engine: Engine | None = None) -> dict | None:
    engine = engine or get_engine()
    with engine.connect() as conn:
        row = conn.execute(select(scans).where(scans.c.scan_id == scan_id)).mappings().first()
    return dict(row) if row else None


def save_device_config(scan_id: str, result: SanitizeResult, engine: Engine | None = None) -> None:
    """Persists the sanitized copy only -- never the raw upload."""
    engine = engine or get_engine()
    report = result.to_report()
    with engine.begin() as conn:
        stmt = pg_insert(device_configs).values(
            scan_id=scan_id,
            sanitized_text=result.sanitized_text,
            sha256_original=result.sha256_original,
            sha256_sanitized=result.sha256_sanitized,
            redactions=report["redactions"],
            clean=result.clean,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[device_configs.c.scan_id],
            set_={
                "sanitized_text": stmt.excluded.sanitized_text,
                "sha256_original": stmt.excluded.sha256_original,
                "sha256_sanitized": stmt.excluded.sha256_sanitized,
                "redactions": stmt.excluded.redactions,
                "clean": stmt.excluded.clean,
            },
        )
        conn.execute(stmt)


def get_device_config(scan_id: str, engine: Engine | None = None) -> dict | None:
    """Reads back the sanitized config text saved by save_device_config().

    Added for milestone 10 (Training Studio): unmatched-line clusters are
    recomputed on demand from this rather than cached in a process-memory
    dict, so `/api/unmatched/{scan_id}` gives the same answer before and
    after a server restart -- only the *teaching* state (confirmations,
    templates) needs its own persistence, which phase7.db_repository now
    provides."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        row = conn.execute(select(device_configs).where(device_configs.c.scan_id == scan_id)).mappings().first()
    return dict(row) if row else None


def save_findings(scan_id: str, results: list[EvidenceResult], engine: Engine | None = None) -> None:
    """Upserts one findings row per EvidenceResult. Evidence lines are
    redacted here, at the point of storage -- results passed in must
    still carry the real, unredacted evidence_line."""
    if not results:
        return
    engine = engine or get_engine()
    rows = []
    for r in results:
        evidence_line = r.evidence_line
        if evidence_line is not None:
            evidence_line, _label = redact_line(evidence_line)
        rows.append(dict(
            scan_id=scan_id, control_id=r.control_id, canonical_field=r.canonical_field,
            state=r.state, description=r.description, severity=r.severity,
            operator=r.operator, expected_value=r.expected_value, observed_value=r.observed_value,
            evidence_line=evidence_line, evidence_line_number=r.evidence_line_number,
            context_category=r.context_category, is_mgmt_path=r.is_mgmt_path,
            frameworks=r.frameworks, linked_controls=r.linked_controls, notes=r.notes,
        ))
    with engine.begin() as conn:
        for row in rows:
            stmt = pg_insert(findings).values(**row)
            update_cols = {c: stmt.excluded[c] for c in row if c not in ("scan_id", "control_id")}
            stmt = stmt.on_conflict_do_update(
                index_elements=[findings.c.scan_id, findings.c.control_id],
                set_=update_cols,
            )
            conn.execute(stmt)


def get_findings(scan_id: str, engine: Engine | None = None) -> list[dict]:
    engine = engine or get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(findings).where(findings.c.scan_id == scan_id).order_by(findings.c.control_id)
        ).mappings().all()
    return [dict(r) for r in rows]


def get_finding(scan_id: str, control_id: str, engine: Engine | None = None) -> dict | None:
    engine = engine or get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(findings).where(findings.c.scan_id == scan_id, findings.c.control_id == control_id)
        ).mappings().first()
    return dict(row) if row else None


def list_scans(vendor: str | None = None, batch_id: str | None = None,
                engine: Engine | None = None) -> list[dict]:
    """All scans, newest first. Dashboard milestone (8) -- not in the
    original Section 4 contract, added because 'aggregates across scans'
    has no data source without a list endpoint. batch_id filter added in
    milestone 11 so the frontend can show "here's how your bulk upload
    turned out" without the caller re-deriving that from scan_ids."""
    engine = engine or get_engine()
    stmt = select(scans).order_by(scans.c.uploaded_at.desc())
    if vendor:
        stmt = stmt.where(scans.c.vendor == vendor)
    if batch_id:
        stmt = stmt.where(scans.c.batch_id == batch_id)
    with engine.connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [dict(r) for r in rows]


def summarize_findings_by_scan(scan_ids: list[str], engine: Engine | None = None) -> dict[str, dict[str, int]]:
    """One grouped query for {scan_id: {state: count}} across many scans,
    rather than N calls to summarize_findings() -- this is what the
    dashboard's per-row + fleet-wide totals are built from."""
    if not scan_ids:
        return {}
    engine = engine or get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(findings.c.scan_id, findings.c.state, func.count().label("n"))
            .where(findings.c.scan_id.in_(scan_ids))
            .group_by(findings.c.scan_id, findings.c.state)
        ).all()
    out: dict[str, dict[str, int]] = {}
    for scan_id, state, n in rows:
        out.setdefault(str(scan_id), {"PASS": 0, "FAIL": 0, "MISSING": 0, "REVIEW": 0, "NOT_APPLICABLE": 0})
        out[str(scan_id)][state] = n
    return out


def summarize_findings(rows: list[dict]) -> dict[str, int]:
    counts = {"PASS": 0, "FAIL": 0, "MISSING": 0, "REVIEW": 0, "NOT_APPLICABLE": 0}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return counts