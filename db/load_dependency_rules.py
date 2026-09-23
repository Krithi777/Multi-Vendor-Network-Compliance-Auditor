# db/load_dependency_rules.py -- 36 rows -> config_dependency_rules (needs uq_dep_rule from phase5_3_setup.sql)
from sqlalchemy import text
from common import read_json, validate, get_engine, is_dry_run

SQL = text("""
    INSERT INTO config_dependency_rules (field_a, relation_type, field_b, rationale)
    VALUES (:a, :t, :b, :why)
    ON CONFLICT (field_a, relation_type, field_b) DO UPDATE SET rationale = EXCLUDED.rationale
""")

def build_rows(data):
    return [dict(a=r["field_a"], t=r["relation_type"], b=r["field_b"], why=r.get("rationale")) for r in data]

def load():
    data = read_json("dependencies/config_dependency_rules.json")
    validate(data, "schemas/config_dependency_rules.schema.json")
    rows = build_rows(data)
    if is_dry_run():
        print(f"[dry-run] {len(rows)} dependency rules ok"); return
    with get_engine().begin() as conn:
        known = {r[0] for r in conn.execute(text("SELECT canonical_field FROM compliance_controls"))}
        bad = [r for r in rows if r["a"] not in known or r["b"] not in known]
        if bad:
            raise SystemExit(f"Unknown canonical_field (run load_controls.py first?): {bad[:3]}")
        for r in rows:
            conn.execute(SQL, r)
        n = conn.execute(text("SELECT count(*) FROM config_dependency_rules")).scalar()
    print(f"loaded {len(rows)} rules; table has {n} rows")

if __name__ == "__main__":
    load()
