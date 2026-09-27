# Milestone 10 — Training Studio: what changed and why

Scope for this pass, per the plan: milestone 10 only. Milestone 9
(remediation) is untouched — left as future work, as requested.

Files touched are listed at the bottom. This note explains the design,
not just the diff.

## Why the old `/api/unmatched` shape had to go

The original Section 4 contract sketch returned a flat list of unmatched
raw lines. That's honest but not teachable: Phase 7 needs 3-4 confirmed
examples of the *same* canonical_field before it can induce a template,
and a flat unordered list makes the admin do that grouping by eye across
however many lines a config has. It also made every `suggested_canonical_field`
/ `fused_confidence` / `component_scores` field in the contract permanently
null, because nothing upstream ever computed them.

## What's new

**`phase9/unmatched_clustering.py`** — groups unmatched lines by a
deterministic structural skeleton (mask tokens that look like values —
digits, ALL-CAPS identifiers, IPv6-style tokens — keep the rest as fixed
syntax), keyed by `(context_category, skeleton)`. The context_category is
part of the key on purpose: Section 6 of the Phase 9 plan calls out that
FortiOS's `set server \S+` matches both syslog and NTP lines with an
identical shape but different block context, and clustering on skeleton
alone would merge them. Tested in `phase9/tests/test_unmatched_clustering.py`,
including that exact case.

Clusters are **recomputed on demand** from the persisted sanitized config
(`device_configs.sanitized_text`, already saved at ingest for the sanitizer's
own purposes) rather than cached in a process-memory dict — so
`GET /api/unmatched/{scan_id}` gives the same clustering before and after
a restart.

**Per-cluster teaching sessions.** The old code started one phase7
`TeachingSession` for the *entire scan's* unmatched lines. That's a latent
bug: `TeachingSession._generalize()` induces one template from all
confirmations mixed together and requires them to share one
`canonical_field` — fine if the admin only ever teaches one field per
scan, wrong the moment they teach two different clusters. This pass starts
one session per **cluster**, lazily, on the first confirm for a line in
that cluster. Multiple clusters can now be taught independently and
correctly in the same scan.

**Real persistence for teaching state.** `TeachingSessionManager` is now
constructed with `phase7.db_repository.PostgresTeachingRepository` (which
already existed in the repo, unused) instead of the in-memory default.
Confirmations, induced templates, and every generalized `MatchResult`
persist to `phase7_teaching_sessions` / `phase7_confirmed_examples` /
`phase7_learned_templates` / `phase7_mapping_decisions` — the tables
already in the Supabase schema. If the DB engine can't be reached (e.g.
someone runs the API standalone against the frontend without Postgres
configured), it falls back to in-memory and logs that plainly at startup
rather than crashing — same "degrade honestly" pattern the rest of Phase 9
already uses for `conflict_check: "not_available"`.

**`GET /api/unmatched/{scan_id}`** now returns clusters, not lines:
`coverage_before_pct` (real, from `normalizer.total_lines` vs the unmatched
count — not the 20-canonical-controls ratio, the actual line-level parse
coverage), each cluster's sample lines (flagged `resolved: true/false`),
and a `suggestion` block that is **only populated once a cluster's session
has actually generalized** — every number in it (`fused_confidence`, the
five component scores, `generalized_count`/`remaining_count`) is an
aggregate over real `phase7.schemas.MatchResult` objects. Nothing is
estimated for an untaught cluster; the frontend says so explicitly instead
of showing a fake number.

**`POST /api/training/{scan_id}/decision`** now takes a `cluster_id`
(falls back to searching for the line's cluster if omitted, for
compatibility), resolves/creates that cluster's session, confirms or
rejects, and returns the freshly recomputed suggestion inline — so the
frontend doesn't need a second round-trip after a confirm crosses the
3-example generalization threshold.

## Frontend — SentinelGrid density

`frontend/app/training/[scanId]/page.tsx` was rebuilt as the 3-column
layout from SentinelGrid's own Training Studio wireframe (`p-train`):
cluster list → selected cluster's sample lines + per-line accept/reject +
generalization progress → fusion signal breakdown (5 mini bars, real
component scores, `n/a` shown honestly for the `context` signal when a
vendor's lines carry no context_path) + a decision log fed by actual
accept/edit/reject actions taken this session. It reuses the app's
existing `ink/paper/panel/line/pass/fail/review/missing` design tokens
(already SentinelGrid-derived, see `tailwind.config.js`) rather than
introducing a second visual language.

`frontend/lib/api.ts` — replaced the flat `UnmatchedLine` type with
`UnmatchedCluster` / `ClusterSuggestion` / `DecisionLogEntry` /
`UnmatchedResponse`, matching the new backend shape. `findings/[scanId]/page.tsx`
was touched in one line (`total_unresolved` instead of
`unmatched_lines.length`) to match.

## Verified, not just written

- `python -m py_compile` on every changed backend module.
- `phase9/tests/test_unmatched_clustering.py` — 7/7 passing, including the
  FortiOS dual-context case.
- `npx tsc --noEmit` — clean.
- `npx next build` — compiles; the only failure in this sandbox is Google
  Fonts being unreachable (no network egress to fonts.googleapis.com here),
  unrelated to these changes and pre-existing in the repo.

## Honestly still open (didn't paper over these)

- `_cluster_sessions` (scan_id → cluster_id → phase7 session_id) and
  `_decision_log` are process memory, not Postgres. The teaching *state*
  itself now survives a restart; this join index and the human-readable
  log do not yet. A follow-up could key phase7 sessions deterministically
  off `(scan_id, cluster_id)` instead of `uuid4` to remove the gap, and/or
  read the decision log back from `phase7_confirmed_examples` instead of
  logging it separately.
- No BGE/vector fallback is wired up (`bge=None`, same as before this
  pass) — MEDIUM-bucket matches still fall to admin review rather than
  auto-resolving against precedent embeddings.
- Milestone 9 (remediation conflict-checking) is unchanged and still
  honestly reports `conflict_check: "not_available"`, as scoped.

## Files touched

```
phase9/unmatched_clustering.py          new
phase9/tests/__init__.py                new
phase9/tests/test_unmatched_clustering.py new
phase9/api.py                           rewritten (unmatched/training sections; teaching repo wiring)
phase9/repository.py                    + get_device_config()
frontend/lib/api.ts                     unmatched/training types + calls
frontend/app/training/[scanId]/page.tsx rewritten
frontend/app/findings/[scanId]/page.tsx 1-line change (total_unresolved)
```
