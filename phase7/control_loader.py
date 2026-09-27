"""Load the existing Phase 5 control schema; no duplicate schema is created."""
from __future__ import annotations
import json
from pathlib import Path

def load_controls(path: str | Path) -> dict:
    rows=json.loads(Path(path).read_text(encoding="utf-8"))
    return {row["canonical_field"]: {
        "control_id": row["control_id"], "operator": row["operator"],
        "expected_value": row["expected_value"], "description": row.get("description")
    } for row in rows}
