# db/load_vendor_mappings.py -- flatten controls[cid].vendors[vendor] -> 1 row per (control_id, vendor)
from sqlalchemy import text
from common import read_json, validate, get_engine, is_dry_run

def build_rows(data):
    rows = []
    for cid, ctrl in data["controls"].items():
        for vendor, m in ctrl["vendors"].items():
            rows.append(dict(
                cid=cid, cf=ctrl["canonical_field"], vendor=vendor,
                ctx=m.get("context_path"), pl=m.get("pass_line"), fl=m.get("fail_line"),
                rx=m.get("match_regex"),
                tri=m.get("tri_state_capable", True),
                ac=m.get("always_compliant", False),
                conf=m.get("syntax_confidence"), notes=m.get("notes"),
            ))
    return rows

SQL = text("""
    INSERT INTO vendor_command_mappings
      (control_id, canonical_field, vendor, context_path, pass_line, fail_line, match_regex,
       tri_state_capable, always_compliant, syntax_confidence, notes)
    VALUES (:cid, :cf, :vendor, :ctx, :pl, :fl, :rx, :tri, :ac, :conf, :notes)
    ON CONFLICT (control_id, vendor) DO UPDATE SET
      canonical_field = EXCLUDED.canonical_field, context_path = EXCLUDED.context_path,
      pass_line = EXCLUDED.pass_line, fail_line = EXCLUDED.fail_line,
      match_regex = EXCLUDED.match_regex, tri_state_capable = EXCLUDED.tri_state_capable,
      always_compliant = EXCLUDED.always_compliant, syntax_confidence = EXCLUDED.syntax_confidence,
      notes = EXCLUDED.notes
""")

def load():
    data = read_json("mappings/vendor_mappings_corrected.json")
    validate(data, "schemas/vendor_mappings.schema.json")
    rows = build_rows(data)
    if is_dry_run():
        print(f"[dry-run] {len(rows)} (control, vendor) rows ok"); return
    with get_engine().begin() as conn:
        # guard: each mapping's canonical_field must match the control's own (FK alone can't check the pair)
        db = dict(conn.execute(text("SELECT control_id, canonical_field FROM compliance_controls")).all())
        if not db:
            raise SystemExit("compliance_controls is empty - run load_controls.py first.")
        bad = [(r["cid"], r["cf"], db.get(r["cid"])) for r in rows if db.get(r["cid"]) != r["cf"]]
        if bad:
            raise SystemExit(f"canonical_field mismatch vs compliance_controls: {bad[:5]}")
        for r in rows:
            conn.execute(SQL, r)
        n = conn.execute(text("SELECT count(*) FROM vendor_command_mappings")).scalar()
    print(f"loaded {len(rows)} vendor mappings; table has {n} rows")

if __name__ == "__main__":
    load()
