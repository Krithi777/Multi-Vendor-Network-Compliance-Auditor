-- Phase 9 migration. Apply after db/ddl.sql and db/phase7_migration.sql,
-- on the SAME PostgreSQL database (confirmed against the live schema:
-- compliance_controls, vendor_command_mappings, remediation_rules,
-- config_dependency_rules, config_corpus, phase7_* tables already exist).
--
-- Adds the persistence layer milestone 5 of the Phase 9 plan needs:
-- one row per uploaded config (scans), one row per control evaluated
-- against it (findings), and the sanitized/redacted text + sanitize
-- report for that scan (device_configs). Raw unredacted config text is
-- never persisted here -- see phase9/sanitizer.py.

CREATE TABLE IF NOT EXISTS scans (
    scan_id                UUID PRIMARY KEY,
    filename                TEXT NOT NULL,
    vendor                  TEXT,                 -- NULL until detected/confirmed
    status                  TEXT NOT NULL CHECK (status IN ('processing','done','error'))
                             DEFAULT 'processing',
    vendor_confidence       TEXT,                 -- high | low | ambiguous | undetected | confirmed
    vendor_candidates       JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ambiguous-case candidate vendors
    error_message           TEXT,                 -- set when status = 'error'
    uploaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at              TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS device_configs (
    scan_id                  UUID PRIMARY KEY REFERENCES scans(scan_id) ON DELETE CASCADE,
    sanitized_text            TEXT NOT NULL,        -- redacted copy only; never the raw upload
    sha256_original            TEXT NOT NULL,
    sha256_sanitized            TEXT NOT NULL,
    redactions                  JSONB NOT NULL DEFAULT '[]'::jsonb,
    clean                         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS findings (
    id                       BIGSERIAL PRIMARY KEY,
    scan_id                  UUID NOT NULL REFERENCES scans(scan_id) ON DELETE CASCADE,
    control_id                TEXT NOT NULL REFERENCES compliance_controls(control_id),
    canonical_field            TEXT NOT NULL REFERENCES compliance_controls(canonical_field),
    state                        TEXT NOT NULL CHECK (state IN
                                  ('PASS','FAIL','MISSING','REVIEW','NOT_APPLICABLE')),
    description                   TEXT,
    severity                       TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
    operator                        TEXT NOT NULL,
    expected_value                   JSONB,
    observed_value                    JSONB,
    evidence_line                       TEXT,          -- redacted before storage (sanitizer.redact_line)
    evidence_line_number                  INTEGER,
    context_category                       TEXT,
    is_mgmt_path                             BOOLEAN NOT NULL DEFAULT FALSE,
    frameworks                                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    linked_controls                              TEXT[] NOT NULL DEFAULT '{}',
    notes                                          TEXT,
    UNIQUE (scan_id, control_id)
);

CREATE INDEX IF NOT EXISTS findings_scan_id_idx ON findings(scan_id);
CREATE INDEX IF NOT EXISTS findings_state_idx ON findings(scan_id, state);
CREATE INDEX IF NOT EXISTS scans_status_idx ON scans(status);