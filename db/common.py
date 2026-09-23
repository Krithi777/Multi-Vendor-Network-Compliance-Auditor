# db/common.py -- shared helpers for every Phase 5 script.

import json
import os
from pathlib import Path

from jsonschema import validate as jsonschema_validate
from sqlalchemy import create_engine


# Repository root = parent of the db/ directory.
ROOT = Path(__file__).resolve().parent.parent

_ENGINE = None

_DEV_DEFAULT = "postgresql+psycopg2://postgres:devpass@localhost:5432/postgres"


def get_engine():
    """Return a process-wide SQLAlchemy engine.

    DATABASE_URL controls the database connection.
    Falls back to the local Docker/Postgres development database.
    """
    global _ENGINE

    if _ENGINE is None:
        url = os.environ.get("DATABASE_URL", _DEV_DEFAULT)
        _ENGINE = create_engine(url, pool_pre_ping=True)

    return _ENGINE


def read_json(relative_path):
    """Read and return a JSON file relative to the repository root."""
    path = ROOT / relative_path

    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(relative_path):
    """Read a JSONL file and return a list of parsed JSON objects."""
    path = ROOT / relative_path

    if not path.exists():
        raise FileNotFoundError(f"JSONL file not found: {path}")

    rows = []

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()

            # Ignore blank lines.
            if not line:
                continue

            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number} of {path}: {exc}"
                ) from exc

    return rows


def validate(data, schema_path):
    """Validate JSON data against a JSON Schema file."""
    schema = read_json(schema_path)
    jsonschema_validate(instance=data, schema=schema)
    return True


def is_dry_run():
    """Return True when DRY_RUN is enabled."""
    return os.environ.get("DRY_RUN", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }