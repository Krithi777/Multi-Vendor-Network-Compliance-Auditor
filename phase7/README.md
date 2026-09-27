# Phase 7 — Multi-Evidence Matching Engine

Phase 7 is integrated as a package at the repository root because the inspected Phase 1–6 repository currently has no `backend/`, `src/`, or existing parser service package. It does **not** create a parallel application.

## Flow

Deterministic parser → unmatched lines only → admin teaching session → 3–4 confirmed examples → common syntax template → five-signal fusion → HIGH auto-apply / MEDIUM BGE fallback / LOW admin review.

Recognized parser output bypasses Phase 7.

## Signals

- syntax: 0.35
- context: 0.15
- value semantics: 0.25
- framework fit: 0.15
- precedent: 0.10

If a signal is unavailable, its weight is removed and remaining weights are renormalized. Negation mismatch is a hard gate and forces fusion to 0.

## Thresholds

- HIGH: `score >= 0.85`
- MEDIUM: `0.60 <= score < 0.85`
- LOW: `score < 0.60`

BGE is called **only** for MEDIUM. LOW never auto-maps and HIGH never calls BGE.

`BGE_SIMILARITY_THRESHOLD` is intentionally unset by default. It must be calibrated from validation/admin-confirmed data; no scientifically invented fixed threshold is shipped.

## BGE / pgvector

Model: `BAAI/bge-small-en-v1.5`, 384 dimensions. Only confirmed examples are embedded. Production storage is PostgreSQL + pgvector with cosine distance.

If the threshold, model, or vector DB is unavailable, the candidate is routed to admin review.

## Integration seam

`phase7/api.py` exposes service-level functions. The deterministic parser should pass its raw unmatched line, vendor, and existing hierarchy `context_path`. Phase 7 never reparses the configuration and never changes recognized parser output.

The repository inspected for this phase contains Phase 5 data/DDL but no parser/backend package, so no parser code was duplicated.

## Database

Apply `db/phase7_migration.sql` to the existing Phase 5 PostgreSQL database. Do not create a second database.

## Example

```python
from phase7.matcher import Phase7Matcher
from phase7.teaching_session import TeachingSessionManager
```

A teaching session is non-blocking: API calls submit confirmations; once the configured seed count (default 3) is reached, the same session generalizes all remaining unmatched lines.
