-- 1. Controls (from control_schema_cis_stig_iso27001.json)
CREATE TABLE compliance_controls (
    control_id          TEXT PRIMARY KEY,          -- 'CTRL-001'
    canonical_field      TEXT NOT NULL UNIQUE,       -- 'management.ssh.version'
    description          TEXT,
    operator              TEXT NOT NULL,              -- eq | lte | gte | ne
    expected_value        JSONB NOT NULL,             -- store as JSONB: 2, true, 10...
    severity               TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
    nist_800_53            TEXT[],
    cis                     JSONB,                     -- array of {vendor,benchmark,rec_id,note}
    stig                    JSONB,                     -- array of {vendor,stig_id,note}
    iso_27001               TEXT[],
    is_mgmt_path            BOOLEAN NOT NULL DEFAULT FALSE   -- Phase 5 step 4 flag
);

-- 2. Vendor command mappings (from vendor_mappings_corrected.json, flattened)
CREATE TABLE vendor_command_mappings (
    id                    SERIAL PRIMARY KEY,
    control_id            TEXT NOT NULL REFERENCES compliance_controls(control_id),
    canonical_field        TEXT NOT NULL REFERENCES compliance_controls(canonical_field),
    vendor                 TEXT NOT NULL,             -- cisco_ios | juniper_junos | fortios | panos | arista_eos
    context_path            TEXT,
    pass_line                TEXT,
    fail_line                 TEXT,
    match_regex               TEXT,
    tri_state_capable          BOOLEAN NOT NULL DEFAULT TRUE,
    always_compliant            BOOLEAN NOT NULL DEFAULT FALSE,
    syntax_confidence            TEXT,                 -- verified | approximate
    notes                          TEXT,
    UNIQUE (control_id, vendor)
);

-- 3. Remediation rules (NEW dataset — author in 5.2b)
CREATE TABLE remediation_rules (
    id                    SERIAL PRIMARY KEY,
    canonical_field        TEXT NOT NULL REFERENCES compliance_controls(canonical_field),
    vendor                  TEXT NOT NULL,
    os_version                TEXT DEFAULT 'any',
    remediation_commands       TEXT[] NOT NULL,        -- ordered CLI sequence
    verification_command        TEXT,
    rollback_commands             TEXT[],
    UNIQUE (canonical_field, vendor, os_version)
);

-- 4. Dependency graph rules (NEW dataset, Phase 8 conflict engine reads this)
CREATE TABLE config_dependency_rules (
    id              SERIAL PRIMARY KEY,
    field_a          TEXT NOT NULL REFERENCES compliance_controls(canonical_field),
    relation_type     TEXT NOT NULL CHECK (relation_type IN
                       ('requires','enables','conflicts_with','shares_path_with')),
    field_b            TEXT NOT NULL REFERENCES compliance_controls(canonical_field),
    rationale            TEXT,
    CHECK (field_a <> field_b)
);

-- 5. Config corpus metadata (Phase 3 + Phase 4 manifests — needed for Phase 6 split)
CREATE TABLE config_corpus (
    id                   SERIAL PRIMARY KEY,
    file_path             TEXT NOT NULL UNIQUE,
    vendor                  TEXT NOT NULL,
    source_type              TEXT NOT NULL CHECK (source_type IN ('real','synthetic')),
    source                     TEXT,                  -- batfish | github | synthetic_mutation
    control_id                 TEXT REFERENCES compliance_controls(control_id),  -- NULL for real configs
    state                        TEXT CHECK (state IN ('PASS','FAIL','MISSING', NULL)),
    sha256                        TEXT,
    label_confidence               TEXT,               -- silver (real) | exact (synthetic)
    collected_at                    TIMESTAMPTZ
);

CREATE INDEX idx_ccr_field_a ON config_dependency_rules(field_a);
CREATE INDEX idx_ccr_field_b ON config_dependency_rules(field_b);
CREATE INDEX idx_corpus_vendor ON config_corpus(vendor);