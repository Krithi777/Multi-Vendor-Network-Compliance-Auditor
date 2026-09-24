"""Phase 6 - leakage-free train / validation / test split.

Design (see split_data docstring for the reasoning):
  * PASS files are pinned to train (each vendor's PASS files are byte-identical
    copies of its baseline config).
  * Every remaining (vendor, control) group stays together, and groups whose
    files share identical content (same SHA-256) are merged into one unit.
  * Whole units are assigned to splits, stratified by vendor, ~80/10/10 by
    file count.
  * validate_split() enforces the guarantees at generation time; test_split.py
    re-checks them independently against the persisted output.
"""
from pathlib import Path
import argparse
import hashlib
import json
import random
import shutil

import pandas as pd

SPLITS = ("train", "validation", "test")
KNOWN_VENDORS = ("cisco_ios", "fortios", "juniper_junos", "panos")
SCRIPT_VERSION = "2.2"

# Cases the Phase 4/5 team flagged as invalid during Phase 5 integrity
# validation (integrity_check.py) and excluded from the corrected dataset.
# Both are PAN-OS "always compliant" controls that only ever had a PASS
# variant generated (no FAIL/MISSING counterpart exists for them, unlike
# every other vendor's CTRL-001/CTRL-002), so they were not usable test
# cases. Kept here as an explicit, documented exclusion rather than
# silently editing the Phase 4 source manifest, so the removal has a
# traceable reason and is easy to revisit if Phase 4/5 data changes.
EXCLUDED_INVALID_CASES = {
    ("panos", "CTRL-001", "PASS"),  # PAN-OS SSH version - invalid PASS case
    ("panos", "CTRL-002", "PASS"),  # PAN-OS Telnet enabled - invalid PASS case
}


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(root: Path) -> pd.DataFrame:
    """Read the Phase 4 manifest; hash every file with the FULL SHA-256
    (the Phase 4 manifest only stores a 16-char prefix). Drops any case
    in EXCLUDED_INVALID_CASES."""
    rows = []
    with open(root / "metadata" / "synthetic_manifest.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                if (r["vendor"], r["control_id"], r["state"]) in EXCLUDED_INVALID_CASES:
                    continue
                p = root / r["file_path"]
                rows.append({
                    "filename": p.name,
                    "relative_path": p.relative_to(root).as_posix(),
                    "vendor": r["vendor"],
                    "control_id": r["control_id"],
                    "canonical_field": r["canonical_field"],
                    "state": r["state"],
                    "sha256": sha256_file(p),
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------
def link_control_groups(vg: pd.DataFrame) -> dict:
    """Map control_id -> unit id for ONE vendor's non-PASS files.

    Two controls are merged into one unit when any of their files share a
    SHA-256 (e.g. Cisco CTRL-015/CTRL-017 MISSING files are byte-identical),
    so identical content can never be split across train/val/test.
    """
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for cid in vg["control_id"].unique():
        find(cid)
    for _, g in vg.groupby("sha256"):
        ids = sorted(g["control_id"].unique())
        for other in ids[1:]:
            parent[find(other)] = find(ids[0])

    members = {}
    for cid in vg["control_id"].unique():
        members.setdefault(find(cid), []).append(cid)
    return {cid: "+".join(sorted(m)) for m in members.values() for cid in m}


# --------------------------------------------------------------------------
# splitting
# --------------------------------------------------------------------------
def split_data(df: pd.DataFrame, seed: int = 42,
               train_frac: float = 0.8, val_frac: float = 0.1) -> pd.DataFrame:
    """Assign every file to train / validation / test.

    1. PASS files -> train. Within a vendor all PASS files are byte-identical
       (a copy of the baseline), so any of them in validation/test would be an
       exact duplicate of a training file.
    2. Non-PASS files are grouped by (vendor, control_id); groups whose files
       share content are merged (link_control_groups). Every state-variant of a
       control therefore stays together, and identical files never straddle a
       split boundary.
    3. Within each vendor, units are shuffled with a per-vendor seed, ordered
       largest-first (stable), and greedily given to the split that is furthest
       below its targets. Two targets are tracked, each as a fraction of what
       that split still needs: total file count (~80/10/10, with pinned PASS
       files counting toward train) and FAIL-file count (so validation and test
       actually contain non-compliant examples instead of only MISSING ones).
       This keeps vendor stratification and lands close to 80/10/10.
    """
    test_frac = 1 - train_frac - val_frac
    parts = []
    for vendor, vg in df.groupby("vendor", sort=True):
        vg = vg.copy()
        n_total = len(vg)
        is_pass = vg["state"] == "PASS"

        unit_of = link_control_groups(vg[~is_pass])
        vg["split_unit"] = vg["control_id"].map(unit_of)
        vg.loc[is_pass, "split_unit"] = "PASS-pinned"

        nonpass = vg[~is_pass]
        sizes = nonpass["split_unit"].value_counts().to_dict()
        fails = nonpass[nonpass["state"] == "FAIL"]["split_unit"].value_counts().to_dict()
        units = sorted(sizes)
        rng = random.Random(f"{seed}-{vendor}")
        rng.shuffle(units)
        units.sort(key=lambda u: -sizes[u])  # stable: ties keep shuffled order

        target = {
            "train": train_frac * n_total - int(is_pass.sum()),
            "validation": val_frac * n_total,
            "test": test_frac * n_total,
        }
        total_fail = sum(fails.values())
        target_fail = {s: total_fail * target[s] / sum(target.values()) for s in target}
        remaining = dict(target)
        remaining_fail = dict(target_fail)

        unit_split = {}
        for u in units:
            # dict order (train, validation, test) breaks exact ties deterministically
            score = {s: remaining[s] / target[s]
                        + (remaining_fail[s] / target_fail[s] if total_fail else 0.0)
                     for s in target}
            dest = max(score, key=score.get)
            unit_split[u] = dest
            remaining[dest] -= sizes[u]
            remaining_fail[dest] -= fails.get(u, 0)

        vg["split"] = vg["split_unit"].map(unit_split)
        vg.loc[is_pass, "split"] = "train"
        parts.append(vg)

    result = pd.concat(parts, ignore_index=True)
    result["file_key"] = result["vendor"] + "::" + result["filename"]
    result["control_group_key"] = result["vendor"] + "::" + result["control_id"]
    validate_split(result)
    return result


# --------------------------------------------------------------------------
# validation (used at generation time AND by tests)
# --------------------------------------------------------------------------
def find_leaks(df: pd.DataFrame) -> dict:
    """Return every leakage violation found in a split frame (empty = clean)."""
    out = {}
    by_key = df.groupby("file_key")["split"].nunique()
    out["file_key_in_multiple_splits"] = sorted(by_key[by_key > 1].index)
    by_hash = df.groupby("sha256")["split"].nunique()
    out["content_hash_in_multiple_splits"] = sorted(by_hash[by_hash > 1].index)
    np_ = df[df["state"] != "PASS"]
    by_grp = np_.groupby("control_group_key")["split"].nunique()
    out["control_group_in_multiple_splits"] = sorted(by_grp[by_grp > 1].index)
    return {k: v for k, v in out.items() if v}


def validate_split(df: pd.DataFrame) -> None:
    leaks = find_leaks(df)
    assert not leaks, f"leakage detected: {leaks}"
    assert set(df["vendor"]) <= set(KNOWN_VENDORS), "unexpected vendor (Arista must stay held out)"
    assert (df.loc[df["state"] == "PASS", "split"] == "train").all(), "PASS file outside train"
    for s in SPLITS:
        assert set(df.loc[df["split"] == s, "vendor"]) == set(KNOWN_VENDORS), f"vendor missing in {s}"
    present = set(zip(df["vendor"], df["control_id"], df["state"]))
    leaked_invalid = present & EXCLUDED_INVALID_CASES
    assert not leaked_invalid, f"invalid Phase 5 cases present: {leaked_invalid}"


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def build_report(df: pd.DataFrame, seed: int, source_manifest: Path) -> dict:
    def table(a, b):
        return {str(k): {str(c): int(v) for c, v in row.items()}
                for k, row in pd.crosstab(df[a], df[b]).to_dict("index").items()}

    leaks = find_leaks(df)
    return {
        "script_version": SCRIPT_VERSION,
        "seed": seed,
        "source_manifest_sha256": sha256_file(source_manifest),
        "total_files": int(len(df)),
        "distinct_contents": int(df["sha256"].nunique()),
        "excluded_invalid_cases": sorted(
            f"{v}/{c}/{s}" for v, c, s in EXCLUDED_INVALID_CASES
        ),
        "counts_by_split": {s: int((df["split"] == s).sum()) for s in SPLITS},
        "fractions_by_split": {s: round(float((df["split"] == s).mean()), 4) for s in SPLITS},
        "vendor_by_split": table("vendor", "split"),
        "state_by_split": table("state", "split"),
        "leakage_checks": {
            "file_key_in_multiple_splits": len(leaks.get("file_key_in_multiple_splits", [])),
            "content_hash_in_multiple_splits": len(leaks.get("content_hash_in_multiple_splits", [])),
            "control_group_in_multiple_splits": len(leaks.get("control_group_in_multiple_splits", [])),
        },
        "rules": [
            "PASS files pinned to train (byte-identical baseline copies)",
            "non-PASS files grouped by (vendor, control_id); groups sharing content are merged",
            "whole units assigned to splits, stratified by vendor, ~80/10/10 by file count",
            "no SHA-256 appears in more than one split",
            "Arista EOS excluded (held out for the Phase 11 demo)",
            "2 invalid PAN-OS PASS cases excluded per Phase 5 integrity_check.py finding",
        ],
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    df = split_data(load_manifest(args.dataset_root), seed=args.seed)

    args.output.mkdir(parents=True, exist_ok=True)
    for s in SPLITS:  # wipe stale files from any earlier run
        if (args.output / s).exists():
            shutil.rmtree(args.output / s)
        (args.output / s).mkdir()

    for _, r in df.iterrows():
        src = args.dataset_root / r["relative_path"]
        dst = args.output / r["split"] / f'{r["vendor"]}__{r["filename"]}'
        shutil.copy2(src, dst)

    df["split_path"] = df.apply(
        lambda r: f'{r["split"]}/{r["vendor"]}__{r["filename"]}', axis=1)
    cols = ["filename", "relative_path", "vendor", "control_id", "canonical_field",
            "state", "sha256", "split", "file_key", "control_group_key",
            "split_unit", "split_path"]
    df[cols].to_csv(args.output / "split_manifest.csv", index=False, lineterminator="\n")

    report = build_report(df, args.seed,
                          args.dataset_root / "metadata" / "synthetic_manifest.jsonl")
    with open(args.output / "split_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(df["split"].value_counts())
    print(pd.crosstab(df["vendor"], df["split"]))
    print(pd.crosstab(df["state"], df["split"]))
