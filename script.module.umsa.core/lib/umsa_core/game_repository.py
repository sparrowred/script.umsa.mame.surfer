"""Game database repository.

This module centralises the single-purpose, read-only queries over the general
game tables of ``umsa.db`` (``sets``, ``software``, ``swl``, ``year``,
``maker``, ``category``, ``nplayers``, ``swl_status``) that neither depend on
:class:`~umsa_core.database.DBMod` filter state nor join into other databases.
It follows the conventions of :mod:`umsa_core.artwork_repository` and
:mod:`umsa_core.dat_repository`.

The repository operates on an existing SQLite connection supplied by the
caller; it never opens or closes that connection. All methods are read-only:
they manage no transactions, never commit, and own only short-lived cursors
that are closed in a ``finally`` block.

Row shapes are transparent: query methods return the connection's native rows
untouched — a ``sqlite3.Row`` keeps both ``row['col']`` and ``row[i]`` access,
exactly what the historical ``DBMod`` methods returned. Connections that do not
use ``sqlite3.Row`` are rejected at construction (step 4.2b contract,
decision Q7). Methods whose public
shape was never a row (``get_machine_name``'s plain tuple, the scalar counts,
``get_set_name``'s bare name, ``get_set_ids_for_software``'s list of ids)
normalise at the boundary and keep that shape.
"""

from __future__ import annotations

import sqlite3

from .sqlite import require_row_connection


class GameRepository:
    """Read-only game-table operations on an externally owned connection.

    The repository never opens or closes the supplied connection and never
    manages transactions; query methods leave both to the caller.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialise the repository.

        Args:
            connection: An existing SQLite connection to operate on. The
                repository does not own this connection.

        Raises:
            ValueError: If the connection does not use ``sqlite3.Row``.
        """
        require_row_connection(connection, "GameRepository")
        self._conn = connection

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the underlying connection (read-only access)."""
        return self._conn

    def get_maker(self) -> list:
        """Return the list of makers (clones excluded), ordered by name.

        Row-transparent: each row carries ``name as id, name`` and supports
        both named and positional access on a ``sqlite3.Row`` connection.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT name as id, name FROM maker "
                "WHERE cloneof_id IS NULL ORDER BY name"
            )
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_swl(self) -> list:
        """Return the list of software lists, ordered by name.

        Row-transparent: each row carries ``name as id, description as name``.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT name as id, description as name FROM swl ORDER BY name"
            )
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_source(self) -> list:
        """Return the distinct source files of the sets, ordered by source.

        Row-transparent: each row carries a single ``source`` column.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT source FROM sets ORDER BY source")
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_year(self) -> list:
        """Return the list of years, ordered by name.

        Row-transparent: each row carries ``name as id, name``.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT name as id, name FROM year ORDER BY name")
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_players(self) -> list:
        """Return the list of player counts, ordered by name.

        Row-transparent: each row carries ``name as id, name``.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT name as id, name FROM nplayers ORDER BY name")
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_categories(self) -> list:
        """Return the list of categories, ordered by name.

        Row-transparent: each row carries ``name as id, name``.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT name as id, name FROM category ORDER BY name")
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_set_name(self, set_id) -> str | None:
        """Return the set name for a set id, or ``None`` for a falsy id.

        A truthy id without a matching set raises ``TypeError`` (the raw
        ``fetchone()[0]`` contract the callers rely on).
        """
        if not set_id:
            return None
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT name FROM sets WHERE id = ?", (set_id,))
            return cursor.fetchone()[0]
        finally:
            cursor.close()

    def get_machine_name(self, machine_id) -> tuple:
        """Return the ``(name, gamename)`` tuple of a set id.

        The public shape is a plain positional tuple; a missing id raises
        ``TypeError`` (callers only pass ids obtained from list rows).
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT name, gamename FROM sets WHERE id = ?", (machine_id,)
            )
            machine = cursor.fetchone()
            return machine[0], machine[1]
        finally:
            cursor.close()

    def get_set_ids_for_software(self, software_id) -> list:
        """Return all set ids belonging to a software id, in row order."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT id FROM sets WHERE softwarelink_id = ?",
                (software_id,),
            )
            return [row[0] for row in cursor.fetchall()]
        finally:
            cursor.close()

    def count_source(self, source) -> int:
        """Count the distinct software shipped by one source file."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(DISTINCT software.id) FROM sets "
                "JOIN software ON software.id = sets.softwarelink_id "
                "WHERE sets.source = ?",
                (source,),
            )
            return cursor.fetchone()[0]
        finally:
            cursor.close()

    def count_machines_for_swl(self, swl_name) -> int:
        """Count the distinct machines linked to one software list."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(DISTINCT sets.id) FROM swl_status "
                "JOIN sets ON sets.id = swl_status.system_id "
                "JOIN swl ON swl.id = swl_status.swl_id "
                "WHERE swl.name = ?",
                (swl_name,),
            )
            return cursor.fetchone()[0]
        finally:
            cursor.close()

    def search_single(self, my_search):
        """Return the first software whose set name starts with a prefix.

        Row-transparent: the single row carries ``software.id``,
        ``software.name``, ``year.name as year`` and ``maker.name as maker``;
        ``None`` is returned when nothing matches.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT DISTINCT software.id, software.name, "
                "year.name as year, maker.name as maker "
                "FROM software "
                "JOIN year ON software.year_id = year.id "
                "JOIN maker ON software.developer_id = maker.id "
                "JOIN sets ON software.id = sets.softwarelink_id "
                "WHERE sets.gamename LIKE ? "
                "ORDER BY software.name LIMIT 1",
                (my_search + "%",),
            )
            return cursor.fetchone()
        finally:
            cursor.close()
