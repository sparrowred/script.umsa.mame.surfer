"""Kodi-independent SQLite connection helpers."""

import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from os import PathLike
from typing import Any
from urllib.request import pathname2url

DatabasePath = str | PathLike
RowFactory = Callable[..., Any] | None

_SAVEPOINT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def connect_sqlite(
    database_path: DatabasePath,
    row_factory: RowFactory = None,
) -> sqlite3.Connection:
    """Open (or create) a SQLite database, optionally setting its row factory.

    Connection errors propagate to the caller.
    """

    connection = sqlite3.connect(os.fspath(database_path))
    if row_factory is not None:
        connection.row_factory = row_factory
    return connection


def connect_sqlite_readonly(
    database_path: DatabasePath,
    row_factory: RowFactory = None,
) -> sqlite3.Connection:
    """Open an existing SQLite database read-only via URI mode ``ro``.

    The file must already exist: a missing database raises and is never
    created. ``immutable=1`` is deliberately not used because the file may be
    replaced (for example by a download) while the connection exists.
    Connection errors propagate to the caller.
    """

    uri = f'file:{pathname2url(os.fspath(database_path))}?mode=ro'
    connection = sqlite3.connect(uri, uri=True)
    if row_factory is not None:
        connection.row_factory = row_factory
    return connection


def require_row_connection(connection: sqlite3.Connection, owner: str) -> None:
    """Require ``row_factory=sqlite3.Row`` on a connection a repository wraps.

    Repositories hand their rows straight back to callers that use both
    ``row['col']`` and ``row[i]`` access. ``owner`` names the repository in
    the error message.

    Raises:
        ValueError: If ``connection.row_factory`` is not ``sqlite3.Row``.
    """

    row_factory = getattr(connection, "row_factory", None)
    if row_factory is not sqlite3.Row:
        raise ValueError(
            f"{owner} requires a connection with row_factory=sqlite3.Row, "
            f"got {row_factory!r}; open it with "
            "connect_sqlite(path, row_factory=sqlite3.Row)"
        )


@contextmanager
def write_savepoint(
    connection: sqlite3.Connection, name: str
) -> Iterator[sqlite3.Cursor]:
    """Run the writes of the ``with`` block in savepoint ``name``; yield a fresh cursor.

    The write convention of every repository. On success only a transaction
    this call started is committed, so a standalone write leaves
    ``in_transaction`` ``False``; a caller's outer transaction is never
    committed or rolled back. Any ``BaseException`` (also a ``SystemExit`` of
    a shutting-down Kodi) rolls back to the savepoint, releases it and
    propagates. The cursor is always closed.

    Raises:
        ValueError: If ``name`` is not a plain SQL identifier (nothing runs).
    """

    if not _SAVEPOINT_NAME.fullmatch(name):
        raise ValueError(f"invalid savepoint name {name!r}")
    had_transaction = connection.in_transaction
    cursor = connection.cursor()
    try:
        cursor.execute(f"SAVEPOINT {name}")
        try:
            yield cursor
        except BaseException:
            cursor.execute(f"ROLLBACK TO {name}")
            cursor.execute(f"RELEASE {name}")
            raise
        cursor.execute(f"RELEASE {name}")
        if not had_transaction:
            connection.commit()
    finally:
        cursor.close()
