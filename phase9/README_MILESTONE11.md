# Milestone 11 delta — device metadata + bulk ingestion

Drop these files into your repo at the same paths (they overwrite the
existing versions of `phase9/db_models.py`, `phase9/repository.py`,
`phase9/api.py`, `frontend/lib/api.ts`, `frontend/app/page.tsx`, and
`frontend/app/findings/[scanId]/page.tsx`; `phase9/bulk_ingest.py` and
`frontend/app/batch/[batchId]/page.tsx` are new files).

## What changed

**Backend**
- `phase9/db_models.py` — added `hostname/model/serial_number/os_version/batch_id`
  columns to `scans`, and a new `batches` table. These match
  `db/phase9_migration_v2.sql`, which was already in your repo but unused.
- `phase9/repository.py` — `create_batch()`, `save_device_info()`,
  `create_scan()` now accepts `batch_id`, `list_scans()` now accepts `batch_id`.
- `phase9/bulk_ingest.py` — **new**. Validates a batch (file count, UTF-8
  decode) before any scan rows are created.
- `phase9/api.py`:
  - `_process_scan` now calls `extract_device_info()` (already existed
    in `device_info.py`, just wasn't wired in) and saves it.
  - `GET /api/scans/{scan_id}` now returns the `device` object and
    `batch_id` per the Section 4 contract.
  - `GET /api/scans` now accepts `?batch_id=` and returns `batch_id`
    per row.
  - **New**: `POST /api/ingest/bulk` — multipart `files` (repeated
    field) → `{ batch_id, scan_ids, status }`, per the contract.

**Frontend**
- `lib/api.ts` — `DeviceInfo` type, `Scan.device`/`Scan.batch_id`,
  `ingestBulk()`, `listScans()` takes an optional `batchId`.
- `app/page.tsx` — the drop zone now accepts multiple files; 2+ files
  goes through `ingestBulk()` and redirects to `/batch/{batchId}`.
- `app/batch/[batchId]/page.tsx` — **new**. Polls the batch's scans
  until all are done/error, links to findings for each finished one.
- `app/findings/[scanId]/page.tsx` — shows a device-info line (host /
  model / serial / OS) under the header when any of it was extracted;
  renders nothing when the config didn't carry any of it.

## Before running

Apply `db/phase9_migration_v2.sql` to your Postgres instance if you
haven't already — it's the one that adds the columns/table above. It's
additive-only and safe to re-run.

## Not touched

Phase 8 conflict-checking, PDF reporting (Milestone 12), and the
`is_mgmt_path` / `syntax_confidence` / `config_dependency_rules` /
`config_corpus` additions from the schema you pasted — those weren't
part of this milestone.
