# db/integrity_check.py -- Phase 5.6 referential-integrity gate
#
# Usage:   python db/integrity_check.py            (needs DATABASE_URL, like the loaders)
#          python db/integrity_check.py --strict   (warnings also fail the run)
#
# Exit code 0 = every ERROR check returned zero offending rows. Offending rows are printed.
# tests/test_phase5_integrity.py runs the same CHECKS as a pytest gate.
import sys
from sqlalchemy import text
from common import get_engine

# Expected shape of the Phase 5 data (plan 5.8 "definition of done").
EXPECTED_TABLES = {
    "compliance_controls", "vendor_command_mappings", "remediation_rules",
    "config_dependency_rules", "config_corpus",
}
EXPECTED_VENDORS = 5
EXPECTED_CONTROLS = 20
DEP_RULES_RANGE = (30, 40)
CORPUS_REAL, CORPUS_SYNTHETIC = 903, 195

# The 6 mgmt-path fields named explicitly in plan 5.3 -- Phase 8's connectivity-conflict
# check scans these for shares_path_with edges, so it matters that it's exactly THESE six,
# not just any six.
EXPECTED_MGMT_PATH_FIELDS = [
    "management.ssh.version",
    "management.https.enabled",
    "management.http.enabled",
    "management.telnet.enabled",
    "management.acl.configured",
    "management.admin_access.restricted",
]
_MGMT_PATH_ARRAY_SQL = "ARRAY[" + ",".join(f"'{f}'" for f in EXPECTED_MGMT_PATH_FIELDS) + "]"

# FK columns we expect the DDL to actually declare, one row per (child table, column, parent
# table). vendor_command_mappings has TWO separate FKs to compliance_controls (control_id AND
# canonical_field) -- checking at the table level would miss it if only one got created.
EXPECTED_FK_COLUMNS = [
    ("vendor_command_mappings", "control_id", "compliance_controls"),
    ("vendor_command_mappings", "canonical_field", "compliance_controls"),
    ("remediation_rules", "canonical_field", "compliance_controls"),
    ("config_dependency_rules", "field_a", "compliance_controls"),
    ("config_dependency_rules", "field_b", "compliance_controls"),
    ("config_corpus", "control_id", "compliance_controls"),
]
_FK_VALUES_SQL = ",\n            ".join(
    f"('{child}','{parent}','{col}')" for child, col, parent in EXPECTED_FK_COLUMNS
)

# ---------------------------------------------------------------------------
# CHECKS: (name, severity, sql). Every query must return the OFFENDING rows,
# so "passes" == zero rows. Written with NOT EXISTS (not NOT IN) so a stray
# NULL can never make a check silently pass.
# ---------------------------------------------------------------------------
CHECKS = [
    # ---- the four from plan 5.6 ------------------------------------------
    ("remediation_rules canonical_field must exist in compliance_controls", "error",
     """SELECT r.id, r.canonical_field, r.vendor FROM remediation_rules r
        WHERE NOT EXISTS (SELECT 1 FROM compliance_controls c WHERE c.canonical_field = r.canonical_field)"""),
    ("dependency field_a must exist in compliance_controls", "error",
     """SELECT d.id, d.field_a FROM config_dependency_rules d
        WHERE NOT EXISTS (SELECT 1 FROM compliance_controls c WHERE c.canonical_field = d.field_a)"""),
    ("dependency field_b must exist in compliance_controls", "error",
     """SELECT d.id, d.field_b FROM config_dependency_rules d
        WHERE NOT EXISTS (SELECT 1 FROM compliance_controls c WHERE c.canonical_field = d.field_b)"""),
    ("vendor_command_mappings control_id must exist in compliance_controls", "error",
     """SELECT m.id, m.control_id FROM vendor_command_mappings m
        WHERE NOT EXISTS (SELECT 1 FROM compliance_controls c WHERE c.control_id = m.control_id)"""),

    # ---- gaps the plan's four checks leave open --------------------------
    # The two FKs on vendor_command_mappings are checked independently, so a row could point at
    # CTRL-001 with CTRL-002's canonical_field and still pass. Check the PAIR.
    ("vendor_command_mappings (control_id, canonical_field) must be the same pair as in compliance_controls", "error",
     """SELECT m.id, m.control_id, m.canonical_field AS mapping_field, c.canonical_field AS control_field
        FROM vendor_command_mappings m JOIN compliance_controls c ON c.control_id = m.control_id
        WHERE m.canonical_field <> c.canonical_field"""),
    ("config_corpus control_id must exist in compliance_controls (when set)", "error",
     """SELECT k.id, k.file_path, k.control_id FROM config_corpus k
        WHERE k.control_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM compliance_controls c WHERE c.control_id = k.control_id)"""),
    # Every (control, vendor) needs a remediation row, and vice versa (both directions).
    # NOTE: this pair of checks is the real guard on remediation/mapping parity. It's robust to
    # always_compliant vendors collapsing the row count below 20*5=100 (see plan 5.5), unlike a
    # hardcoded exact-count check would be -- so we don't also assert row counts below.
    ("every vendor_command_mappings (canonical_field, vendor) has a remediation_rules row", "error",
     """SELECT m.canonical_field, m.vendor FROM vendor_command_mappings m
        WHERE NOT EXISTS (SELECT 1 FROM remediation_rules r
                          WHERE r.canonical_field = m.canonical_field AND r.vendor = m.vendor)"""),
    ("every remediation_rules (canonical_field, vendor) has a vendor_command_mappings row", "error",
     """SELECT r.canonical_field, r.vendor FROM remediation_rules r
        WHERE NOT EXISTS (SELECT 1 FROM vendor_command_mappings m
                          WHERE m.canonical_field = r.canonical_field AND m.vendor = r.vendor)"""),
    # Corpus label rules (plan 5.5): real = unlabeled/silver, synthetic = exact labels.
    ("real config_corpus rows must have NULL control_id and NULL state", "error",
     """SELECT id, file_path, control_id, state FROM config_corpus
        WHERE source_type = 'real' AND (control_id IS NOT NULL OR state IS NOT NULL)"""),
    ("synthetic config_corpus rows must have control_id, state and label_confidence='exact'", "error",
     """SELECT id, file_path, control_id, state, label_confidence FROM config_corpus
        WHERE source_type = 'synthetic'
          AND (control_id IS NULL OR state IS NULL OR label_confidence IS DISTINCT FROM 'exact')"""),
    # A synthetic file's vendor must be a vendor that actually has a mapping for that control.
    ("synthetic config_corpus (control_id, vendor) must exist in vendor_command_mappings", "error",
     """SELECT k.id, k.file_path, k.control_id, k.vendor FROM config_corpus k
        WHERE k.source_type = 'synthetic'
          AND NOT EXISTS (SELECT 1 FROM vendor_command_mappings m
                          WHERE m.control_id = k.control_id AND m.vendor = k.vendor)"""),
    # A PASS/FAIL file for an always-compliant or non-tri-state control is a labelling error.
    ("synthetic FAIL/PASS files must not target always_compliant mappings", "error",
     """SELECT k.id, k.file_path, k.state FROM config_corpus k
        JOIN vendor_command_mappings m ON m.control_id = k.control_id AND m.vendor = k.vendor
        WHERE k.source_type = 'synthetic' AND m.always_compliant"""),
    # Dependency graph hygiene.
    ("duplicate dependency rules (same field_a, relation_type, field_b)", "error",
     """SELECT field_a, relation_type, field_b, count(*) FROM config_dependency_rules
        GROUP BY 1,2,3 HAVING count(*) > 1"""),
    ("self-referencing dependency rules (field_a = field_b)", "error",
     """SELECT id, field_a FROM config_dependency_rules WHERE field_a = field_b"""),
    # CHANGED: was a bare count(*) <> 6 check, which passes as long as *some* 6 controls are
    # flagged -- it wouldn't notice if the wrong 6 got flagged (e.g. a typo'd canonical_field).
    # Checks identity in both directions instead: each named field must be flagged, and nothing
    # else may be.
    ("is_mgmt_path must be set on exactly the 6 fields named in plan 5.3, no more no less", "error",
     f"""SELECT canonical_field, 'should be flagged but is not' AS problem
        FROM compliance_controls
        WHERE canonical_field = ANY({_MGMT_PATH_ARRAY_SQL}) AND NOT is_mgmt_path
        UNION ALL
        SELECT canonical_field, 'flagged but not one of the 6 named mgmt-path fields' AS problem
        FROM compliance_controls
        WHERE is_mgmt_path AND NOT (canonical_field = ANY({_MGMT_PATH_ARRAY_SQL}))"""),
    # Row-count expectations from plan 5.8.
    # NOTE: vendor_command_mappings / remediation_rules deliberately do NOT get a hardcoded
    # "must equal 20*5=100" check here -- plan 5.5 says explicitly some rows "collapse" for
    # always_compliant vendors, so an exact count would false-fail on correct data. The
    # bijection checks above are the real guard on those two tables' consistency; the DB's own
    # UNIQUE(control_id, vendor) / UNIQUE(canonical_field, vendor, os_version) constraints
    # already cap them at <=100.
    (f"compliance_controls must have exactly {EXPECTED_CONTROLS} rows", "error",
     f"SELECT count(*) AS n FROM compliance_controls HAVING count(*) <> {EXPECTED_CONTROLS}"),
    (f"config_dependency_rules must have {DEP_RULES_RANGE[0]}-{DEP_RULES_RANGE[1]} rows", "error",
     f"""SELECT count(*) AS n FROM config_dependency_rules
         HAVING count(*) NOT BETWEEN {DEP_RULES_RANGE[0]} AND {DEP_RULES_RANGE[1]}"""),
    (f"config_corpus must have {CORPUS_REAL} real + {CORPUS_SYNTHETIC} synthetic rows", "error",
     f"""SELECT count(*) FILTER (WHERE source_type='real') AS real_rows,
                count(*) FILTER (WHERE source_type='synthetic') AS synthetic_rows
         FROM config_corpus
         HAVING count(*) FILTER (WHERE source_type='real') <> {CORPUS_REAL}
             OR count(*) FILTER (WHERE source_type='synthetic') <> {CORPUS_SYNTHETIC}"""),

    # ---- "the 5 tables stay separate" (plan 5.6) -------------------------
    ("no views or materialized views in public (no query-joined 'blob' table)", "error",
     """SELECT schemaname || '.' || matviewname AS name, 'materialized view' AS kind FROM pg_matviews
        WHERE schemaname = 'public'
        UNION ALL
        SELECT table_schema || '.' || table_name, 'view' FROM information_schema.views
        WHERE table_schema = 'public'"""),
    ("all 5 Phase 5 tables must exist as base tables", "error",
     """SELECT t AS missing_table FROM unnest(ARRAY['compliance_controls','vendor_command_mappings',
            'remediation_rules','config_dependency_rules','config_corpus']) AS t
        WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables i
                          WHERE i.table_schema='public' AND i.table_name=t AND i.table_type='BASE TABLE')"""),
    ("unexpected extra tables in public (possible denormalised copy)", "warn",
     """SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_type='BASE TABLE'
          AND table_name NOT IN ('compliance_controls','vendor_command_mappings','remediation_rules',
                                 'config_dependency_rules','config_corpus')"""),
    # CHANGED: was table-level (child, parent) existence only, which can't tell the two FKs on
    # vendor_command_mappings apart -- if only one of {control_id, canonical_field} actually got
    # declared as a FK, the old check still passed. Now checks the specific column via conkey.
    ("declared foreign keys are missing from the schema (checked per column, not just per table)", "error",
     f"""SELECT expected.child, expected.parent, expected.col
        FROM (VALUES
            {_FK_VALUES_SQL}
        ) AS expected(child, parent, col)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.contype = 'f'
              AND c.conrelid = ('public.' || expected.child)::regclass
              AND c.confrelid = ('public.' || expected.parent)::regclass
              AND a.attname = expected.col
        )"""),

    # ---- warnings (do not fail the run unless --strict) ------------------
    ("conflicts_with / shares_path_with stored in both directions (A,B) and (B,A)", "warn",
     """SELECT a.field_a, a.relation_type, a.field_b FROM config_dependency_rules a
        JOIN config_dependency_rules b ON a.field_a = b.field_b AND a.field_b = b.field_a
                                      AND a.relation_type = b.relation_type
        WHERE a.relation_type IN ('conflicts_with','shares_path_with') AND a.field_a < a.field_b"""),
    ("mutual 'requires' cycle (A requires B and B requires A)", "warn",
     """SELECT a.field_a, a.field_b FROM config_dependency_rules a
        JOIN config_dependency_rules b ON a.field_a = b.field_b AND a.field_b = b.field_a
        WHERE a.relation_type='requires' AND b.relation_type='requires' AND a.field_a < a.field_b"""),
    ("controls with no dependency rule at all (isolated in the graph)", "warn",
     """SELECT c.control_id, c.canonical_field FROM compliance_controls c
        WHERE NOT EXISTS (SELECT 1 FROM config_dependency_rules d
                          WHERE d.field_a = c.canonical_field OR d.field_b = c.canonical_field)"""),
]


def run_check(conn, sql):
    """Return (column_names, rows) for one check."""
    res = conn.execute(text(sql))
    return list(res.keys()), res.all()


def run_all(conn):
    """Yield (name, severity, columns, offending_rows) for every check."""
    for name, severity, sql in CHECKS:
        cols, rows = run_check(conn, sql)
        yield name, severity, cols, rows


def main():
    strict = "--strict" in sys.argv
    errors = warnings = 0
    with get_engine().connect() as conn:
        for name, severity, cols, rows in run_all(conn):
            if not rows:
                print(f"  ok    {name}")
                continue
            tag = "FAIL" if severity == "error" else "WARN"
            print(f"  {tag}  {name}  ({len(rows)} row(s))")
            print(f"        columns: {cols}")
            for r in rows[:10]:
                print(f"        {tuple(r)}")
            if len(rows) > 10:
                print(f"        ... and {len(rows) - 10} more")
            if severity == "error":
                errors += 1
            else:
                warnings += 1
    print(f"\n{len(CHECKS)} checks: {errors} failed, {warnings} warning(s)")
    if errors or (strict and warnings):
        sys.exit(1)


if __name__ == "__main__":
    main()
