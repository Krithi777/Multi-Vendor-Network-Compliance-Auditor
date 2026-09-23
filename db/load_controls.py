# db/load_controls.py  -- 20 rows -> compliance_controls
import json
from sqlalchemy import text
from common import read_json, validate, get_engine, is_dry_run

# Phase 8 connectivity-conflict check scans these (plan 5.3)
MGMT_PATH_FIELDS = {
    "management.ssh.version", "management.https.enabled", "management.http.enabled",
    "management.telnet.enabled", "management.acl.configured", "management.admin_access.restricted",
}

def build_rows(data):
    return [dict(
        cid=c["control_id"], cf=c["canonical_field"], desc=c.get("description"),
        op=c["operator"], ev=json.dumps(c["expected_value"]), sev=c["severity"],
        nist=c.get("nist_800_53", []), cis=json.dumps(c.get("cis", [])),
        stig=json.dumps(c.get("stig", [])), iso=c.get("iso_27001", []),
        mgmt=c["canonical_field"] in MGMT_PATH_FIELDS,
    ) for c in data]

SQL = text("""
    INSERT INTO compliance_controls
      (control_id, canonical_field, description, operator, expected_value, severity,
       nist_800_53, cis, stig, iso_27001, is_mgmt_path)
    VALUES
      (:cid, :cf, :desc, :op, CAST(:ev AS JSONB), :sev,
       CAST(:nist AS TEXT[]), CAST(:cis AS JSONB), CAST(:stig AS JSONB), CAST(:iso AS TEXT[]), :mgmt)
    ON CONFLICT (control_id) DO UPDATE SET
      canonical_field = EXCLUDED.canonical_field, description = EXCLUDED.description,
      operator = EXCLUDED.operator, expected_value = EXCLUDED.expected_value,
      severity = EXCLUDED.severity, nist_800_53 = EXCLUDED.nist_800_53, cis = EXCLUDED.cis,
      stig = EXCLUDED.stig, iso_27001 = EXCLUDED.iso_27001, is_mgmt_path = EXCLUDED.is_mgmt_path
""")

def load():
    data = read_json("controls/control_schema_cis_stig_iso27001.json")
    validate(data, "schemas/control_schema.schema.json")
    rows = build_rows(data)
    missing = MGMT_PATH_FIELDS - {r["cf"] for r in rows}
    assert not missing, f"is_mgmt_path fields not found in controls: {missing}"
    if is_dry_run():
        print(f"[dry-run] {len(rows)} controls ok, {sum(r['mgmt'] for r in rows)} flagged is_mgmt_path"); return
    with get_engine().begin() as conn:
        for r in rows:
            conn.execute(SQL, r)
        n = conn.execute(text("SELECT count(*) FROM compliance_controls")).scalar()
        m = conn.execute(text("SELECT count(*) FROM compliance_controls WHERE is_mgmt_path")).scalar()
    print(f"loaded {len(rows)} controls; table has {n} rows ({m} is_mgmt_path)")

if __name__ == "__main__":
    load()
