# Phase 6 - Leakage-free split (final, corrected)

## Layout
    split_dataset.py            splitter + validation (run to regenerate)
    test_split.py               independent pytest gate (18 tests)
    phase6_dataset/
        train/ validation/ test/   files named <vendor>__<filename>
        split_manifest.csv         one row per file -> split (+ labels, full SHA-256)
        split_report.json          seed, counts, exclusions, leakage-check results
    source/phase4_synthetic_dataset_4vendors/   Phase 4 input (needed by 2 tests)

## Regenerate / verify
    pip install pandas pytest
    python split_dataset.py --dataset-root source/phase4_synthetic_dataset_4vendors --output phase6_dataset
    python -m pytest -q test_split.py

## Data correction (Phase 5 integrity finding)
The Phase 4 source manifest has 195 files, but 2 are excluded here:
- `panos/CTRL-001/PASS` (PAN-OS SSH version)
- `panos/CTRL-002/PASS` (PAN-OS Telnet enabled)

Phase 5's `integrity_check.py` flagged both as invalid PASS cases. Independently confirmed:
these are the *only* single-state, PASS-only controls anywhere in the dataset -- every other
vendor has full PASS/FAIL/MISSING for these same control IDs, and PAN-OS itself has full
three-state coverage for every other control. The exclusion is implemented as an explicit,
documented list (`EXCLUDED_INVALID_CASES` in `split_dataset.py`), not a silent edit to the
Phase 4 source files, so it's traceable and reversible if Phase 4/5 data changes.
**Result: 193 files, not 195.**

## Rules enforced
1. Split by file/group, never by line; stratified by vendor (all 4 vendors in every split).
2. PASS files are pinned to train: each vendor's PASS files are byte-identical copies of its baseline.
3. Non-PASS files stay grouped by (vendor, control); groups whose files share a SHA-256 are merged
   (e.g. cisco CTRL-015/017, fortios CTRL-015/017 and CTRL-003/004 MISSING files are identical).
4. No SHA-256 and no file_key (vendor::filename) appears in more than one split.
5. FAIL files are balanced as a secondary target so validation/test contain non-compliant examples.
6. Arista EOS excluded (held out for the Phase 11 demo). Seed 42; output is deterministic.
7. The 2 invalid PAN-OS PASS cases above are excluded per the Phase 5 finding.

## Result (193 files, 116 distinct contents)
| split | files | share | FAIL | MISSING | PASS |
|---|---|---|---|---|---|
| train | 153 | 79.3% | 27 | 48 | 78 |
| validation | 18 | 9.3% | 8 | 10 | 0 |
| test | 22 | 11.4% | 6 | 16 | 0 |

Per vendor:
| vendor | train | validation | test |
|---|---|---|---|
| cisco_ios | 42 | 5 | 5 |
| fortios | 41 | 6 | 6 |
| juniper_junos | 36 | 3 | 6 |
| panos | 34 | 4 | 5 |

## Limits to keep in mind
* Every file is its vendor's baseline plus one changed line, so this split measures generalisation to
  unseen mutations of one device per vendor - not to unseen devices. Arista in Phase 11 is the real test.
* Validation/test hold no PASS-labelled files (PASS content is identical to train by construction).
* Whole controls are held out, so a validation/test control has no FAIL/MISSING examples in that vendor's train.
* PAN-OS now has 18 controls represented instead of 20 (CTRL-001/CTRL-002 dropped entirely, since their
  only generated variant was the invalid PASS case) -- its own FAIL/MISSING coverage for those two controls
  never existed in Phase 4, this isn't new data loss from the split.
* Sets are small (18 / 22 files): report per-field metrics with caution.
