-- Phase 9 migration v3 -- additive only. Run AFTER phase9_migration_v2.sql
-- (already applied). Does not touch findings or device_configs.
--
-- Replaces the process-memory `_scan_frameworks` dict in phase9/api.py
-- with a real column. That dict was scan_id -> [selected frameworks],
-- populated at ingest time and read back by GET /api/scans/{scan_id} --
-- but being process-memory only, it was wiped on every backend restart
-- (dev --reload included) and never shared across multiple workers, so
-- GET /api/scans/{scan_id} silently fell back to "all four frameworks"
-- regardless of what was actually selected on the New Scan page. This
-- column is the fix: the selection now survives restarts and is visible
-- to every worker, same as vendor_confidence/vendor_candidates already are.
--
-- NULL means "all four" -- same fallback semantics the in-memory dict
-- used, so existing rows (scanned before this migration) behave exactly
-- as they did before.

ALTER TABLE scans
  ADD COLUMN IF NOT EXISTS frameworks_scanned JSONB;