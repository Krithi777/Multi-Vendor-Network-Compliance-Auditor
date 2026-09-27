"""SQLAlchemy Core table definitions for the Phase 9 persistence layer.

Matches db/phase9_migration.sql + db/phase9_migration_v2.sql column-for-
column. Deliberately Core
(sqlalchemy.Table), not the declarative ORM -- every other db/ script in
this repo (load_controls.py, load_vendor_mappings.py, ...) talks to
Postgres with engine.begin() + text()/Table.insert() through
db.common.get_engine(), and repository.py follows that same pattern
rather than introducing a second, ORM-based way of talking to the same
database.

These Table objects are metadata only -- they do NOT create or alter
anything. The migrations (db/phase9_migration.sql, then
db/phase9_migration_v2.sql) are the one source of truth for schema; if
the two drift, the migrations win and this file should be updated to
match them, never the other way around.
"""
from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

batches = Table(
    "batches",
    metadata,
    Column("batch_id", UUID(as_uuid=True), primary_key=True),
    Column("file_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

scans = Table(
    "scans",
    metadata,
    Column("scan_id", UUID(as_uuid=True), primary_key=True),
    Column("filename", Text, nullable=False),
    Column("vendor", Text, nullable=True),
    Column("status", Text, nullable=False, server_default="processing"),
    Column("vendor_confidence", Text, nullable=True),
    Column("vendor_candidates", JSONB, nullable=False, server_default="[]"),
    Column("error_message", Text, nullable=True),
    Column("uploaded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    # Milestone 11 (Section 6A/6B of the v2 plan) -- device.* fields are
    # None until a scan reaches the normalize step and only ever hold
    # what device_info.py actually found in the config text; batch_id is
    # null for anything uploaded through the single-file /api/ingest path.
    Column("hostname", Text, nullable=True),
    Column("model", Text, nullable=True),
    Column("serial_number", Text, nullable=True),
    Column("os_version", Text, nullable=True),
    Column("batch_id", UUID(as_uuid=True), ForeignKey("batches.batch_id", ondelete="SET NULL"), nullable=True),
    # Phase 9 milestone (New Scan page framework selector). NULL means
    # "all four" -- the same fallback semantics as the pre-migration
    # in-memory dict this column replaces, so a row from before this
    # migration behaves exactly as it did before (see
    # db/phase9_migration_v3.sql).
    Column("frameworks_scanned", JSONB, nullable=True),
    CheckConstraint("status IN ('processing','done','error')", name="scans_status_check"),
)

device_configs = Table(
    "device_configs",
    metadata,
    Column("scan_id", UUID(as_uuid=True), ForeignKey("scans.scan_id", ondelete="CASCADE"), primary_key=True),
    Column("sanitized_text", Text, nullable=False),
    Column("sha256_original", Text, nullable=False),
    Column("sha256_sanitized", Text, nullable=False),
    Column("redactions", JSONB, nullable=False, server_default="[]"),
    Column("clean", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

findings = Table(
    "findings",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("scan_id", UUID(as_uuid=True), ForeignKey("scans.scan_id", ondelete="CASCADE"), nullable=False),
    Column("control_id", Text, ForeignKey("compliance_controls.control_id"), nullable=False),
    Column("canonical_field", Text, ForeignKey("compliance_controls.canonical_field"), nullable=False),
    Column("state", Text, nullable=False),
    Column("description", Text, nullable=True),
    Column("severity", Text, nullable=False),
    Column("operator", Text, nullable=False),
    Column("expected_value", JSONB, nullable=True),
    Column("observed_value", JSONB, nullable=True),
    Column("evidence_line", Text, nullable=True),
    Column("evidence_line_number", Integer, nullable=True),
    Column("context_category", Text, nullable=True),
    Column("is_mgmt_path", Boolean, nullable=False, server_default="false"),
    Column("frameworks", JSONB, nullable=False, server_default="{}"),
    Column("linked_controls", ARRAY(Text), nullable=False, server_default="{}"),
    Column("notes", Text, nullable=True),
    CheckConstraint(
        "state IN ('PASS','FAIL','MISSING','REVIEW','NOT_APPLICABLE')",
        name="findings_state_check",
    ),
    CheckConstraint("severity IN ('low','medium','high')", name="findings_severity_check"),
    UniqueConstraint("scan_id", "control_id", name="findings_scan_id_control_id_key"),
)