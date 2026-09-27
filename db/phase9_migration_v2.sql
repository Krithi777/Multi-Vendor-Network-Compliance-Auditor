-- Phase 9 migration v2 -- additive only. Run AFTER phase9_migration.sql
-- (already applied). Does not touch findings or device_configs.
--
-- Adds: device metadata columns on scans (milestone 11, Section 6A of
-- the v2 plan) and a batches table for bulk ingestion (milestone 11,
-- Section 6B). Nothing here is a value guess -- device_info.py returns
-- NULL for any field it can't extract, and these columns stay NULL in
-- that case rather than getting a placeholder.

ALTER TABLE scans
  ADD COLUMN IF NOT EXISTS hostname       TEXT,
  ADD COLUMN IF NOT EXISTS model          TEXT,
  ADD COLUMN IF NOT EXISTS serial_number  TEXT,
  ADD COLUMN IF NOT EXISTS os_version     TEXT,
  ADD COLUMN IF NOT EXISTS batch_id       UUID;

CREATE TABLE IF NOT EXISTS batches (
    batch_id     UUID PRIMARY KEY,
    file_count   INTEGER NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Postgres has no "ADD CONSTRAINT IF NOT EXISTS", so guard it explicitly
-- (safe to re-run this migration without erroring on a second pass).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'scans_batch_id_fkey'
  ) THEN
    ALTER TABLE scans
      ADD CONSTRAINT scans_batch_id_fkey
      FOREIGN KEY (batch_id) REFERENCES batches(batch_id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS scans_batch_id_idx ON scans(batch_id);
