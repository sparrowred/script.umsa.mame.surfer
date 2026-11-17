"""Versioned ``status.db`` schema migrations via ``PRAGMA user_version``.

Each migration runs in one transaction with its version bump; a failure rolls
it back and propagates. A newer database fails instead of being downgraded.
Works on a caller-owned connection.
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


def apply_migrations(connection: sqlite3.Connection) -> int:
    """Migrate ``status.db`` up to :data:`CURRENT_VERSION` and return the version.

    Commits only a transaction it opened itself; an open caller transaction is
    joined, not committed. A failure rolls back and re-raises.

    Raises:
        RuntimeError: If the database version is newer than
            :data:`CURRENT_VERSION`.
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
