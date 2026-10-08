"""Apply SQL migrations from packages/database/migrations in filename order.

    uv run python -m dhandrishti.db.migrate

Each file runs in its own transaction and is recorded with its SHA-256; editing an
already-applied migration is an error (add a new migration instead).
"""

import hashlib
import sys
from pathlib import Path

import psycopg

from ..paths import MIGRATIONS_DIR
from . import connect


def pending(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[tuple[str, str, str]]:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          filename   text PRIMARY KEY,
          sha256     text NOT NULL,
          applied_at timestamptz NOT NULL DEFAULT now())""")
    applied = dict(conn.execute("SELECT filename, sha256 FROM schema_migrations").fetchall())
    todo = []
    for path in sorted(directory.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(sql.encode()).hexdigest()
        if path.name in applied:
            if applied[path.name] != digest:
                raise RuntimeError(f"migration {path.name} was modified after being applied")
            continue
        todo.append((path.name, digest, sql))
    return todo


def migrate(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    # Autocommit so each `conn.transaction()` below is a real transaction, not a savepoint.
    conn.commit()
    conn.autocommit = True
    done = []
    for name, digest, sql in pending(conn, directory):
        with conn.transaction():
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (filename, sha256) VALUES (%s, %s)", (name, digest))
        done.append(name)
    return done


def main() -> None:
    with connect() as conn:
        applied = migrate(conn)
    print("applied: " + (", ".join(applied) if applied else "nothing (up to date)"))


if __name__ == "__main__":
    sys.exit(main())
