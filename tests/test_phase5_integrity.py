# tests/test_phase5_integrity.py -- Phase 5 gate. Must pass clean before Phase 6 starts.
#
#   export DATABASE_URL=postgresql+psycopg2://...
#   pytest tests/ -v
#
# One test per check in db/integrity_check.py. Error-severity checks assert zero offending rows
# (offending rows appear in the failure message). Warn-severity checks are reported as pytest
# warnings and only fail the run when STRICT_INTEGRITY=1.
import os
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "db"))   # loaders use flat imports
import integrity_check as ic                                            # noqa: E402
from common import get_engine                                          # noqa: E402

STRICT = os.environ.get("STRICT_INTEGRITY") == "1"


@pytest.fixture(scope="module")
def conn():
    # A gate that silently skips is not a gate: no DATABASE_URL = hard failure, not a skip.
    if not os.environ.get("DATABASE_URL"):
        pytest.fail("DATABASE_URL is not set - the Phase 5 gate cannot run without the database.",
                    pytrace=False)
    engine = get_engine()
    with engine.connect() as c:
        yield c
    engine.dispose()


@pytest.mark.parametrize("name,severity,sql", ic.CHECKS, ids=[c[0][:70] for c in ic.CHECKS])
def test_check_returns_zero_rows(conn, name, severity, sql):
    cols, rows = ic.run_check(conn, sql)
    if not rows:
        return
    detail = "\n".join(f"    {tuple(r)}" for r in rows[:20])
    msg = f"{name}\n  {len(rows)} offending row(s), columns {cols}:\n{detail}"
    if severity == "error" or STRICT:
        pytest.fail(msg, pytrace=False)
    warnings.warn(msg)


def test_five_tables_stay_separate(conn):
    """No view / materialized view / extra table may join the five datasets into one blob."""
    from sqlalchemy import text
    tables = {r[0] for r in conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE'"))}
    assert ic.EXPECTED_TABLES <= tables, f"missing tables: {ic.EXPECTED_TABLES - tables}"
    views = conn.execute(text(
        "SELECT table_name FROM information_schema.views WHERE table_schema='public' "
        "UNION ALL SELECT matviewname FROM pg_matviews WHERE schemaname='public'")).all()
    assert not views, f"joined views/materialized views found: {[v[0] for v in views]}"
    # Each table is joined to the others only through control_id / canonical_field.
    join_keys = {
        "vendor_command_mappings": {"control_id", "canonical_field"},
        "remediation_rules": {"canonical_field"},
        "config_dependency_rules": {"field_a", "field_b"},
        "config_corpus": {"control_id"},
    }
    for table, keys in join_keys.items():
        fk_cols = {r[0] for r in conn.execute(text("""
            SELECT a.attname FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
            WHERE c.contype = 'f' AND c.conrelid = CAST(:t AS regclass)"""), {"t": f"public.{table}"})}
        assert fk_cols == keys, f"{table}: FK columns {fk_cols}, expected only {keys}"