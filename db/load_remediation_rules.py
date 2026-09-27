# db/load_remediation_rules.py -- remediation_rules.json (plan 5.2b shape) -> remediation_rules
from sqlalchemy import text
from common import read_json, validate, get_engine, is_dry_run

def build_rows(data):
    rows = []
    for cid, ctrl in data.items():
        for vendor, r in ctrl["vendors"].items():
            rows.append(dict(
                cf=ctrl["canonical_field"], vendor=vendor, osv=r.get("os_version", "any"),
                cmds=r.get("remediation_commands", []), ver=r.get("verification_command"),
                rb=r.get("rollback_commands", []),
            ))
    return rows

SQL = text("""
    INSERT INTO remediation_rules
      (canonical_field, vendor, os_version, remediation_commands, verification_command, rollback_commands)
    VALUES (:cf, :vendor, :osv, CAST(:cmds AS TEXT[]), :ver, CAST(:rb AS TEXT[]))
    ON CONFLICT (canonical_field, vendor, os_version) DO UPDATE SET
      remediation_commands = EXCLUDED.remediation_commands,
      verification_command = EXCLUDED.verification_command,
      rollback_commands = EXCLUDED.rollback_commands
""")

def load():
    data = read_json("remediation/remediation_rules.json")
    validate(data, "schemas/remediation_rules.schema.json")
    rows = build_rows(data)
    if is_dry_run():
        print(f"[dry-run] {len(rows)} remediation rows ok"); return
    with get_engine().begin() as conn:
        for r in rows:
            conn.execute(SQL, r)
        n = conn.execute(text("SELECT count(*) FROM remediation_rules")).scalar()
    print(f"loaded {len(rows)} remediation rules; table has {n} rows")

if __name__ == "__main__":
    load()
