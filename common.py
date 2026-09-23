"""Shared helpers for all db/load_*.py scripts."""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # repo root (compliance-engine/)

def read_json(rel):
    with open(ROOT / rel, encoding="utf-8") as f:
        return json.load(f)

def read_jsonl(rel):
    with open(ROOT / rel, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def validate(data, schema_rel):
    """Step 2 of every loader: validate against the JSON Schema from 5.4."""
    import jsonschema
    schema_path = ROOT / schema_rel
    if not schema_path.exists():
        sys.exit(f"Missing schema file: {schema_rel} (5.4). Loaders must validate before touching the DB.")
    try:
        jsonschema.validate(data, json.load(open(schema_path, encoding="utf-8")))
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path)
        sys.exit(f"Schema validation FAILED for {schema_rel} at [{path}]: {e.message}")

def get_engine():
    """Set DATABASE_URL, e.g.
       postgresql+psycopg2://postgres:<url-encoded-password>@db.<ref>.supabase.co:5432/postgres
    """
    from sqlalchemy import create_engine
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set (Supabase connection string, postgresql+psycopg2://...).")
    return create_engine(url, pool_pre_ping=True)

def is_dry_run():
    return "--dry-run" in sys.argv     # validate + transform only, no DB connection
