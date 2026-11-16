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
    """Open a SQLite database, optionally configuring its row factory.

    Connection errors and SQLite's normal create/open behavior are allowed to
    propagate unchanged to the caller.
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
    Connection errors are allowed to propagate unchanged to the caller.
    """

    uri = f'file:{pathname2url(os.fspath(database_path))}?mode=ro'
    connection = sqlite3.connect(uri, uri=True)
    if row_factory is not None:
        connection.row_factory = row_factory
    return connection


def require_row_connection(connection: sqlite3.Connection, owner: str) -> None:
    """Enforce the repository row-factory contract (roadmap step 4.2b).

    Repositories hand their rows straight back to callers that use both
    ``row['col']`` and ``row[i]`` access, so they only accept connections
    configured with ``row_factory=sqlite3.Row``. ``connect_sqlite()``'s
    default (``None``) is unchanged for callers that deliberately want plain
    tuples and use no repository.

    Args:
        connection: The connection a repository is about to wrap.
        owner: The repository class name, used in the error message.

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
    """Run the writes of the ``with`` block inside an ownership-aware savepoint.

    The write convention of every repository (C-L4):

    - a savepoint ``name`` is always opened; when no transaction is active
      this also starts one;
    - the block gets a fresh cursor of ``connection``;
    - on success the savepoint is released and only a transaction this call
      started is committed, so a standalone write leaves
      ``connection.in_transaction`` ``False``;
    - on any exception (``BaseException``, so a ``SystemExit`` raised by a
      shutting-down Kodi never leaves a dangling savepoint) the block's
      statements are rolled back to the savepoint, the savepoint is released
      and the exception propagates;
    - a caller's outer transaction and its pending changes are never
      committed and never rolled back; the cursor is always closed.

    Args:
        connection: The connection to write on.
        name: The savepoint name, a plain SQL identifier.

    Raises:
        ValueError: If ``name`` is not a plain identifier (nothing runs).
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
