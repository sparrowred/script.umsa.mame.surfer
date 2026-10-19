"""Versioned ``status.db`` schema migrations.

``status.db`` is migrated with SQLite's built-in ``PRAGMA user_version``. A
single migration entry (version 0 → 1) declares the full current schema: the
three pre-existing tables through their authoritative repository helpers plus
the four new history/meta tables through
:func:`umsa_core.history_repository.create_history_tables`.

The migration body runs in one transaction together with the
``PRAGMA user_version`` bump, so a failure rolls the whole thing back and the
exception propagates (never swallowed). A database that is newer than this
module understands fails explicitly instead of being downgraded.

The module is Kodi-independent and never *opens* a connection: callers hand it
an existing ``status.db`` connection (``DBMod`` supplies ``self.sdb`` during
``_open_persistent_databases``). It never touches ``umsa.db``, ``dat.db`` or
``artwork.db``.
"""

from __future__ import annotations

import sqlite3

from .emulator_repository import create_emulator_tables
from .history_repository import create_history_tables
from .status_repository import create_status_tables

CURRENT_VERSION = 1


def _apply_version_1(connection: sqlite3.Connection) -> None:
    """Declare the complete version-1 ``status.db`` schema."""

    cursor = connection.cursor()
    try:
        create_status_tables(cursor)
        create_emulator_tables(cursor)
        create_history_tables(cursor)
        cursor.execute("PRAGMA user_version = 1")
    finally:
        cursor.close()


MIGRATIONS = {1: _apply_version_1}


def apply_migrations(connection: sqlite3.Connection) -> int:
    """Migrate ``status.db`` up to :data:`CURRENT_VERSION`.

    Returns the resulting ``user_version``. A version already at (or, for the
    unsupported-newer case, beyond) :data:`CURRENT_VERSION` is handled as
    documented:

    - version == CURRENT_VERSION: no-op, returns it unchanged;
    - version == 0: runs the single migration and the version bump in one
      transaction, committing when it opened that transaction itself and
      rolling back + re-raising on any failure;
    - version > CURRENT_VERSION: raises ``RuntimeError`` (never downgrades).

    The caller keeps ownership of the connection: an already-open caller
    transaction is not committed here (the migration joins it) and no
    savepoint or transaction is left open on either path.
    """

    cursor = connection.cursor()
    try:
        row = cursor.execute("PRAGMA user_version").fetchone()
        version = int(row[0]) if row else 0
    finally:
        cursor.close()

    if version == CURRENT_VERSION:
        return version

    if version > CURRENT_VERSION:
        raise RuntimeError(
            f"status.db user_version {version} is newer than the supported "
            f"version {CURRENT_VERSION}"
        )

    # version < CURRENT_VERSION: currently exactly the 0 -> 1 migration.
    in_caller_transaction = connection.in_transaction
    if not in_caller_transaction:
        connection.execute("BEGIN")
    try:
        _apply_version_1(connection)
        if not in_caller_transaction:
            connection.commit()
    except Exception:
        if not in_caller_transaction:
            connection.rollback()
        raise
    return CURRENT_VERSION
