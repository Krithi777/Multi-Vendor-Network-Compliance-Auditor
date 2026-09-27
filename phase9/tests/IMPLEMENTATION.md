# Implementation Notes — Phase 9

Running log of things that are true about the current implementation
but don't belong in a docstring or the plan doc itself -- known gaps,
deliberate non-goals, and anything a future contributor would otherwise
have to rediscover by reading code.

## Known in-memory-only state (api.py)

`_cluster_sessions` and `_decision_log` in `phase9/api.py` (milestone 10,
Training Studio) live in process memory, not Postgres:

- `_cluster_sessions` -- maps which phase7 `session_id` backs which
  unmatched-line cluster, for which scan.
- `_decision_log` -- the human-readable accept/reject feed the Training
  Studio UI renders.

The underlying teaching state itself (`TeachingSessionManager`, backed by
`phase7.db_repository.PostgresTeachingRepository` when the DB engine is
reachable) **does** persist across a restart. This join/log on top of it
does not -- after a restart, existing confirmations/templates are still
there, but the Training Studio UI's per-cluster session mapping and
decision feed reset. Not a milestone-10 blocker (the plan's own done
condition doesn't require the decision log to survive a restart), just
worth knowing before treating a restart as fully stateless.

## Milestone 12 -- PDF rendering choice

The plan's Section 6C names Jinja2 + WeasyPrint. This is built with
**Jinja2 + xhtml2pdf** instead: same template-driven approach, but
xhtml2pdf is pure-Python with no Pango/Cairo/GDK system libraries to
install per machine before a demo. `phase9/report.py`'s
`_html_to_pdf_bytes()` is the one function to swap if a heavier/prettier
renderer (WeasyPrint, or something else) is wanted later --
`build_report_context()` and the Jinja2 template are renderer-agnostic.

## Milestone 2/7 -- known dataset ambiguity, not a bug

`panos__CTRL-015_MISSING.cfg` in `phase6/phase6_dataset/test` evaluates
to PASS, not MISSING, against the real pipeline. This is the exact
PAN-OS CTRL-015/CTRL-017 shared-evidence-line case the plan's Section 7
calls out: both controls key off the identical
`set deviceconfig system permitted-ip ...` line, and the plan is
explicit that forcing a fake distinction between them is the wrong fix.
`phase9/tests/test_normalizer.py` excludes this one fixture from its
strict MISSING-never-collapses assertion, with the same citation, rather
than special-casing compliance_diff.py to paper over it. Overall
normalizer/diff accuracy against `phase6_dataset/test` is 21/22 (95.5%),
at the plan's own >=95% bar.

## Test coverage vs. the plan's Section 5 layout

Section 5 names `test_normalizer.py`, `test_device_info.py`, and
`test_reports.py` under `phase9/tests/`, run against `phase6_dataset` as
the accuracy oracle. All three now exist. `test_reports.py` mocks the DB
layer (`repository.get_scan`/`get_findings`) rather than requiring a live
Postgres instance, so it runs in any environment; it validates
`report.py`'s own assembly and rendering logic, not the DB round-trip --
that's exercised by hitting `/api/reports/{scan_id}/pdf` against a real
scan (see `demo/run_5vendor_demo.sh`, milestone 13).
