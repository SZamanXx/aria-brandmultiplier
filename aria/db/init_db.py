"""Initialize the SQLite database. Idempotent — safe to run on every startup."""

import sqlite3
from pathlib import Path

from aria.config import settings

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db(db_path: Path | None = None) -> Path:
    target = db_path or settings.db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return target


if __name__ == "__main__":
    p = init_db()
    print(f"DB initialized at {p}")
