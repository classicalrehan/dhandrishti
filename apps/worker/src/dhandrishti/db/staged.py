"""Staged migrations: reviewed SQL that is not yet allowed near the research databases.

Files in packages/database/migrations-staged/ are never applied by `migrate()` (which the daily jobs run).
`apply_staged` applies them to a database only after checking it is not one of the real ones. Promoting a
staged migration means moving it into migrations/ after review.
"""

import psycopg

from ..paths import STAGED_MIGRATIONS_DIR
from .migrate import migrate

PROTECTED_DATABASES = frozenset({"dhandrishti", "dhandrishti_kite"})


class ProtectedDatabaseError(RuntimeError):
    pass


def apply_staged(conn: psycopg.Connection) -> list[str]:
    name = conn.info.dbname
    if name in PROTECTED_DATABASES or not name.startswith("dd_"):
        raise ProtectedDatabaseError(
            f"refusing to apply staged migrations to database {name!r}: only throwaway test databases (dd_*) allowed")
    migrate(conn)  # the normal migrations first, in order
    return migrate(conn, STAGED_MIGRATIONS_DIR)
