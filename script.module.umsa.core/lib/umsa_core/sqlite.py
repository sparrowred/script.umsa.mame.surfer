"""Kodi-independent SQLite connection helpers."""

import os
import sqlite3
from collections.abc import Callable
from os import PathLike
from typing import Any, Union
from urllib.request import pathname2url

DatabasePath = Union[str, PathLike]
RowFactory = Union[Callable[..., Any], None]


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
