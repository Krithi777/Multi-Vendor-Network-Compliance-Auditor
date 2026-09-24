"""Independent gate for the Phase 6 split. Run: python -m pytest -q test_split.py

Checks the PERSISTED output (manifest + folders) rather than trusting the
script that produced it. Run this before any Phase 7 / Phase 10 work."""
from pathlib import Path
import hashlib
import json
import sys

import pandas as pd
import pytest

ROOT_DIR = Path(__file__).parent
DATA_ROOT = ROOT_DIR / "phase6_dataset"
M = DATA_ROOT / "split_manifest.csv"
REPORT = DATA_ROOT / "split_report.json"
SOURCE_ROOT = ROOT_DIR / "source" / "phase4_synthetic_dataset_4vendors"
SPLITS = ["train", "validation", "test"]
VENDORS = {"cisco_ios", "juniper_junos", "fortios", "panos"}

sys.path.insert(0, str(ROOT_DIR))
from split_dataset import EXCLUDED_INVALID_CASES, find_leaks, load_manifest, split_data  # noqa: E402


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""):
            h.update(c)
    return h.hexdigest()


def load():
    assert M.exists(), f"missing manifest: {M}"
    return pd.read_csv(M)


# ---------------------------------------------------------------- structure
def test_total_and_valid_splits():
    d = load()
    assert len(d) == 193  # 195 Phase 4 files minus 2 invalid PAN-OS PASS cases
    assert set(d["split"]) == set(SPLITS)


def test_invalid_pan_os_cases_are_excluded():
    # CTRL-001/CTRL-002 PASS for PAN-OS were flagged invalid by Phase 5's
    # integrity_check.py (they're the only single-state, PASS-only
    # controls in the dataset -- every other vendor has full PASS/FAIL/
    # MISSING for these same control IDs) and must never reappear.
    d = load()
    present = set(zip(d["vendor"], d["control_id"], d["state"]))
    assert not (present & EXCLUDED_INVALID_CASES)


def test_no_arista_and_only_known_vendors():
    d = load()
    assert set(d["vendor"]) == VENDORS
    assert not d["filename"].str.contains("arista", case=False).any()


def test_all_vendors_present_in_every_split():
    d = load()
    for s in SPLITS:
        assert set(d[d["split"] == s]["vendor"]) == VENDORS, s


def test_split_proportions_are_roughly_80_10_10():
    c = load()["split"].value_counts(normalize=True)
    assert 0.75 <= c["train"] <= 0.85
    assert 0.05 <= c["validation"] <= 0.15
    assert 0.05 <= c["test"] <= 0.15


def test_held_out_splits_contain_fail_and_missing_examples():
    d = load()
    for s in ("validation", "test"):
        states = set(d[d["split"] == s]["state"])
        assert {"FAIL", "MISSING"} <= states, f"{s} lacks FAIL/MISSING: {states}"


# ------------------------------------------------------------------ leakage
def test_no_file_appears_in_multiple_splits():
    # Raw filenames repeat across vendors (every vendor has CTRL-001_PASS.cfg),
    # so the unique identifier is vendor + filename (file_key).
    d = load()
    assert d["file_key"].is_unique
    assert d.groupby("file_key")["split"].nunique().max() == 1


def test_no_identical_content_across_splits():
    # THE key leakage check: byte-identical files must never be in two splits.
    d = load()
    per_hash = d.groupby("sha256")["split"].nunique()
    bad = per_hash[per_hash > 1]
    assert bad.empty, f"{len(bad)} content hashes appear in more than one split"


def test_no_control_group_leakage_across_splits():
    # Non-PASS variants of one (vendor, control) must share a split.
    d = load()
    np_ = d[d["state"] != "PASS"]
    assert np_.groupby("control_group_key")["split"].nunique().max() == 1


def test_pass_files_are_pinned_to_train():
    d = load()
    assert (d[d["state"] == "PASS"]["split"] == "train").all()


def test_held_out_files_are_not_duplicates_of_train_files():
    d = load()
    train_hashes = set(d[d["split"] == "train"]["sha256"])
    held = d[d["split"] != "train"]
    assert not held["sha256"].isin(train_hashes).any()


# ---------------------------------------------------------------- integrity
def test_hashes_match_saved_files_and_folders_match_manifest():
    d = load()
    assert d["sha256"].str.len().eq(64).all()  # full SHA-256, not a prefix
    for _, r in d.iterrows():
        p = DATA_ROOT / r["split_path"]
        assert r["split_path"].split("/")[0] == r["split"]
        assert p.exists(), p
        assert sha256_file(p) == r["sha256"]


def test_no_stray_files_on_disk():
    d = load()
    on_disk = {f"{s}/{p.name}" for s in SPLITS for p in (DATA_ROOT / s).iterdir()}
    assert on_disk == set(d["split_path"])


def test_report_matches_manifest():
    d = load()
    r = json.loads(REPORT.read_text())
    assert r["total_files"] == len(d)
    assert r["counts_by_split"] == {s: int((d["split"] == s).sum()) for s in SPLITS}
    assert r["distinct_contents"] == d["sha256"].nunique()


# ------------------------------------------------ the gate itself must work
def test_leak_detector_catches_a_deliberately_leaky_split():
    d = load().copy()
    # move one held-out file's twin into train -> same hash in two splits
    dup = d[d["state"] == "PASS"].iloc[[0]].copy()
    dup["split"] = "test"
    dup["file_key"] = "fake::" + dup["file_key"]
    leaky = pd.concat([d, dup], ignore_index=True)
    assert "content_hash_in_multiple_splits" in find_leaks(leaky)


def test_clean_manifest_has_no_leaks():
    assert find_leaks(load()) == {}


# ---------------------------------------------- needs the Phase 4 source data
def _require_source():
    if not SOURCE_ROOT.exists():
        pytest.skip(f"source dataset not found at {SOURCE_ROOT}")


def test_labels_match_phase4_manifest():
    _require_source()
    d = load()
    p4 = pd.DataFrame(json.loads(l) for l in open(
        SOURCE_ROOT / "metadata" / "synthetic_manifest.jsonl") if l.strip())
    # p4 is the raw, uncorrected Phase 4 manifest (195 rows); this split
    # intentionally drops EXCLUDED_INVALID_CASES per the Phase 5 finding,
    # so compare against p4 with those same cases removed.
    invalid = pd.DataFrame(EXCLUDED_INVALID_CASES, columns=["vendor", "control_id", "state"])
    p4_clean = p4.merge(invalid, on=["vendor", "control_id", "state"], how="left", indicator=True)
    p4_clean = p4_clean[p4_clean["_merge"] == "left_only"].drop(columns="_merge")
    assert len(p4) - len(p4_clean) == len(EXCLUDED_INVALID_CASES)

    m = d.merge(p4_clean, left_on="relative_path", right_on="file_path", suffixes=("", "_p4"))
    assert len(m) == len(d) == len(p4_clean)
    for col in ("vendor", "control_id", "canonical_field", "state"):
        assert (m[col] == m[col + "_p4"]).all(), col


def test_manifest_matches_regenerated_split():
    # Proves the persisted split is deterministic and hasn't drifted from the script.
    _require_source()
    seed = json.loads(REPORT.read_text())["seed"]
    fresh = split_data(load_manifest(SOURCE_ROOT), seed=seed)
    fresh_map = dict(zip(fresh["file_key"], fresh["split"]))
    saved = load()
    assert set(fresh_map) == set(saved["file_key"])
    for _, r in saved.iterrows():
        assert fresh_map[r["file_key"]] == r["split"]
