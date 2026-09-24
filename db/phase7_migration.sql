-- Phase 7 migration. Apply after db/ddl.sql using the SAME PostgreSQL database.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS phase7_teaching_sessions (
    session_id UUID PRIMARY KEY,
    vendor TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN
      ('WAITING_FOR_ADMIN','TEACHING','GENERALIZING','COMPLETED')),
    unmatched_lines JSONB NOT NULL,
    unmatched_context_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    unmatched_source_metadata JSONB NOT NULL DEFAULT '[]'::jsonb,
    confirmations JSONB NOT NULL DEFAULT '[]'::jsonb,
    learned_template TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS phase7_confirmed_examples (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES phase7_teaching_sessions(session_id) ON DELETE CASCADE,
    raw_line TEXT NOT NULL,
    vendor TEXT NOT NULL,
    canonical_field TEXT NOT NULL REFERENCES compliance_controls(canonical_field),
    template_signature TEXT,
    context_path TEXT,
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS phase7_learned_templates (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES phase7_teaching_sessions(session_id) ON DELETE SET NULL,
    vendor TEXT NOT NULL,
    canonical_field TEXT NOT NULL REFERENCES compliance_controls(canonical_field),
    template TEXT NOT NULL,
    signature TEXT NOT NULL,
    example_count INTEGER NOT NULL CHECK (example_count >= 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vendor, canonical_field, signature)
);

CREATE TABLE IF NOT EXISTS phase7_embedding_records (
    id BIGSERIAL PRIMARY KEY,
    raw_line TEXT NOT NULL,
    vendor TEXT NOT NULL,
    canonical_field TEXT NOT NULL REFERENCES compliance_controls(canonical_field),
    template_signature TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    session_id UUID REFERENCES phase7_teaching_sessions(session_id) ON DELETE SET NULL,
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS phase7_embedding_records_embedding_idx
ON phase7_embedding_records USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS phase7_mapping_decisions (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES phase7_teaching_sessions(session_id) ON DELETE SET NULL,
    original_line TEXT NOT NULL,
    normalized_line TEXT NOT NULL,
    vendor TEXT NOT NULL,
    candidate_canonical_field TEXT,
    syntax_score DOUBLE PRECISION,
    context_score DOUBLE PRECISION,
    value_semantics_score DOUBLE PRECISION,
    framework_fit_score DOUBLE PRECISION,
    precedent_score DOUBLE PRECISION,
    available_signals JSONB NOT NULL,
    effective_weights JSONB NOT NULL,
    fusion_score DOUBLE PRECISION NOT NULL,
    confidence_bucket TEXT NOT NULL CHECK (confidence_bucket IN ('HIGH','MEDIUM','LOW')),
    decision TEXT NOT NULL,
    matched_example TEXT,
    matched_template TEXT,
    bge_score DOUBLE PRECISION,
    final_mapping_status TEXT NOT NULL,
    explanation JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_phase7_examples_lookup
ON phase7_confirmed_examples(vendor, canonical_field, template_signature);
CREATE INDEX IF NOT EXISTS idx_phase7_decisions_session
ON phase7_mapping_decisions(session_id);


-- Backward-compatible columns for repositories created by the earlier Phase 7 ZIP.
ALTER TABLE phase7_teaching_sessions
  ADD COLUMN IF NOT EXISTS unmatched_context_paths JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE phase7_teaching_sessions
  ADD COLUMN IF NOT EXISTS unmatched_source_metadata JSONB NOT NULL DEFAULT '[]'::jsonb;
