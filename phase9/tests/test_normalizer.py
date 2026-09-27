"""Tests for phase9.normalizer + compliance_diff against the phase6_dataset
labeled fixtures (Plan Section 5 / Section 7: "Use these as your test
oracle -- don't hand-write test configs").

Each fixture filename is `<vendor>__<control_id>_<STATE>.cfg` -- the
filename IS the label. This runs the real normalize_config() ->
run_compliance_diff() pipeline (no mocking) against every fixture in
phase6_dataset/test and asserts the predicted state for that one
control_id matches the filename's label.

Milestone 2's own done-condition is "run against all 5 vendors'
fixtures, >=95% correct (ambiguity is expected and should be reported,
not hidden)" -- so this suite doesn't require 100%: it prints every
mismatch and only fails the run if accuracy drops below that bar.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from phase9.mapping_loader import get_default_tables
from phase9.normalizer import normalize_config
from phase9.compliance_diff import run_compliance_diff

DATASET_DIR = Path(__file__).parent.parent.parent / "phase6" / "phase6_dataset" / "test"

FIXTURE_RE = re.compile(r"^(?P<vendor>[a-z0-9_]+)__(?P<control_id>CTRL-\d+)_(?P<state>PASS|FAIL|MISSING)\.cfg$")

MIN_ACCURACY = 0.95


def _load_fixtures() -> list[tuple[str, str, str, Path]]:
    if not DATASET_DIR.is_dir():
        return []
    fixtures = []
    for path in sorted(DATASET_DIR.glob("*.cfg")):
        m = FIXTURE_RE.match(path.name)
        if not m:
            continue
        fixtures.append((m["vendor"], m["control_id"], m["state"], path))
    return fixtures


FIXTURES = _load_fixtures()


@pytest.mark.skipif(not FIXTURES, reason="phase6_dataset/test not present in this checkout")
def test_normalizer_and_diff_accuracy_against_phase6_dataset():
    tables = get_default_tables()
    mismatches = []

    for vendor, control_id, expected_state, path in FIXTURES:
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        normalized = normalize_config(raw_text, vendor, tables)
        results = run_compliance_diff(normalized, tables)
        by_control = {r.control_id: r.state for r in results}
        actual_state = by_control.get(control_id)

        if actual_state != expected_state:
            mismatches.append(
                f"{path.name}: expected {expected_state}, got {actual_state!r}"
            )

    total = len(FIXTURES)
    accuracy = (total - len(mismatches)) / total

    if mismatches:
        print(f"\n{len(mismatches)}/{total} phase6_dataset fixtures mismatched "
              f"(accuracy {accuracy:.1%}):")
        for line in mismatches:
            print(f"  {line}")

    assert accuracy >= MIN_ACCURACY, (
        f"Normalizer/diff accuracy {accuracy:.1%} on phase6_dataset/test is "
        f"below the plan's {MIN_ACCURACY:.0%} bar (see printed mismatches above)."
    )


@pytest.mark.skipif(not FIXTURES, reason="phase6_dataset/test not present in this checkout")
def test_missing_is_never_collapsed_into_pass_or_fail():
    """Section 7's explicit rule: MISSING is its own outcome. Spot-checks
    every fixture labeled MISSING actually comes back MISSING, not
    silently coerced to PASS/FAIL somewhere in the pipeline.

    One documented exception: PAN-OS CTRL-015/CTRL-017 key off the exact
    same `set deviceconfig system permitted-ip ...` line (Section 7 --
    "there's no way to tell them apart from the config alone... don't
    try to force a fake distinction"). When that line is present, this
    fixture's CTRL-015 legitimately reads as PASS via CTRL-017's
    evidence, not a MISSING-collapse bug -- excluded here on purpose
    rather than papering over it with fake control-specific logic.
    """
    KNOWN_SHARED_EVIDENCE_EXCEPTIONS = {("panos", "CTRL-015"), ("panos", "CTRL-017")}

    tables = get_default_tables()
    missing_fixtures = [
        f for f in FIXTURES
        if f[2] == "MISSING" and (f[0], f[1]) not in KNOWN_SHARED_EVIDENCE_EXCEPTIONS
    ]
    assert missing_fixtures, "expected at least one MISSING fixture in the dataset"

    for vendor, control_id, _expected, path in missing_fixtures:
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        normalized = normalize_config(raw_text, vendor, tables)
        results = run_compliance_diff(normalized, tables)
        by_control = {r.control_id: r.state for r in results}
        actual = by_control.get(control_id)
        assert actual in ("MISSING", None), (
            f"{path.name}: MISSING control collapsed into {actual!r}"
        )
