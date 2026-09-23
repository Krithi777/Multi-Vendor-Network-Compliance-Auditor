# db/common.py -- shared engine helper for every Phase 5 script (loaders, integrity_check, tests).
#
# Centralizing this means DATABASE_URL is read in exactly one place. If you keep the inline
# `create_engine("postgresql+psycopg2://postgres:devpass@localhost:5432/postgres")` in the
# individual load_*.py scripts from the plan doc, switch those over to `from common import
# get_engine` too, so a single env var controls where every script points (local dev vs CI vs
# whatever Phase 6+ ends up using).
import os
from sqlalchemy import create_engine

_ENGINE = None

_DEV_DEFAULT = "postgresql+psycopg2://postgres:devpass@localhost:5432/postgres"


def get_engine():
    """Return a process-wide SQLAlchemy engine, built from DATABASE_URL.

    Falls back to the docker-compose dev default so a bare `python db/load_controls.py`
    still works during local development without exporting anything.
    """
    global _ENGINE
    if _ENGINE is None:
        url = os.environ.get("DATABASE_URL", _DEV_DEFAULT)
        _ENGINE = create_engine(url, pool_pre_ping=True)
    return _ENGINE