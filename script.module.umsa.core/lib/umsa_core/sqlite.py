"""Kodi-independent SQLite connection helpers."""

import os
import sqlite3
from collections.abc import Callable
from os import PathLike
from typing import Any, Union

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
