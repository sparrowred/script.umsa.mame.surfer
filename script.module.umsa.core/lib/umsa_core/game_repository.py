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
``get_set_name``'s bare name, ``get_set_ids_for_software``'s list of ids,
``get_software_ids_for_name``'s id list, ``get_searchresults``'s
``(rows, pos, count)`` bundle, ``get_machines``'s list of plain dicts and
``get_info_by_set_and_swl``'s dict) normalise at the boundary and keep that
shape.
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

    def get_series(self, software_id):
        """Return the software rows of the series a software id belongs to.

        Row-transparent: each row carries ``s.id, s.name, year, maker``.
        Returns ``None`` when the software has no series at all. The current
        N+1 query pattern and the first-series-wins behaviour (a software in
        several series is resolved against the first one only) are preserved
        verbatim — optimisation is a separate change.
        """
        cursor = self._conn.cursor()
        try:
            # check if software has a series attached
            cursor.execute(
                "SELECT series_id "
                "FROM series_seq WHERE software_id = ?", (software_id,)
            )
            series_ids = cursor.fetchall()
            if not series_ids:
                return None

            # get all entries for the series
            all_series = []
            cursor.execute(
                "SELECT software_id "
                "FROM series_seq, software, year "
                "WHERE series_id = ? AND software_id = software.id "
                "AND software.year_id = year.id "
                "ORDER BY seqno, year.name",
                (series_ids[0]['series_id'],),  # simply use first series
            )
            for i in cursor.fetchall():
                cursor.execute(
                    "SELECT DISTINCT s.id, s.name, y.name as year, m.name as maker "
                    "FROM software s, sets v, "
                    "     year y, maker m "
                    "WHERE s.id = v.softwarelink_id AND y.id = s.year_id "
                    "AND m.id = s.developer_id AND s.id = ?", (i[0],)
                )
                all_series.append(cursor.fetchone())
            return all_series
        finally:
            cursor.close()

    def check_series(self, software_id) -> int | None:
        """Return the number of entries in the software's first series.

        Returns ``None`` when the software has no series row.
        """
        cursor = self._conn.cursor()
        try:
            # first check if series exists
            cursor.execute(
                "SELECT series_id "
                "FROM series_seq WHERE software_id = ?", (software_id,)
            )
            series_exists = cursor.fetchone()
            # now count
            if series_exists:
                cursor.execute(
                    "SELECT COUNT(series_id) "
                    "FROM series_seq WHERE series_id = ?",
                    (series_exists['series_id'],),
                )
                return cursor.fetchone()[0]
            return None
        finally:
            cursor.close()

    def check_compilation(self, software_id) -> int:
        """Return how a software id connects to a compilation.

        2 = Software is on a compilation (a ``compilations.compilation_id``
        row), 1 = Software is a compilation (a ``compilations.software_id``
        row), 0 = no connection found.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT software.id FROM software "
                "JOIN compilations ON compilations.software_id = software.id "
                "WHERE software.id = ?", (software_id,))
            if cursor.fetchone():
                return 1

            cursor.execute(
                "SELECT software.id FROM software "
                "JOIN compilations ON compilations.compilation_id = software.id "
                "WHERE software.id = ?", (software_id,))
            if cursor.fetchone():
                return 2

            return 0
        finally:
            cursor.close()

    def get_all_dbentries(self, cat):
        """Return count rows per filter category (dynamic dispatch).

        Row-transparent: each row carries ``t.id``, the category column
        (``description``/``name``) and ``count(distinct s.id)``; ``None`` is
        returned for an unknown category. The category column name, the join
        column and the extra ``flag`` predicate are chosen exactly as the
        historical ``DBMod`` selection did.
        """
        if cat == "Softwarelists":
            select_placeholders = (
                'description', 'swl', 'swllink', '', 'description'
            )
        elif cat == "Game Categories":
            select_placeholders = (
                'name', 'category', 'classification',
                'AND t.flag = 0', 'name'
            )
        elif cat == "Machine Categories":
            select_placeholders = (
                'name', 'category', 'classification',
                'AND t.flag = 1', 'name'
            )
        elif cat == "Years":
            select_placeholders = (
                'name', 'year', 'year', '', 'name'
            )
        elif cat == "Players":
            select_placeholders = (
                'name', 'nplayers', 'nplayers', '', 'name'
            )
        else:
            return None

        select_statement = "SELECT t.id, t.{}, count(distinct s.id) \
                            FROM {} t, software s, sets v \
                            WHERE t.id = v.{}_id and s.id = v.softwarelink_id {} \
                            GROUP BY t.id ORDER BY t.{}".format(*select_placeholders)
        cursor = self._conn.cursor()
        try:
            cursor.execute(select_statement)
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_searchresults(self, my_search):
        """Return ``(rows, pos, count)`` for a substring search.

        Rows are Row-transparent and name-ordered (LIMIT 100); ``count`` is
        the total number of distinct matching software; ``pos`` is the index
        of the first row whose software name starts with the search term
        (case-insensitively), or 0 when no row starts with it.

        TODO:
        - single word search: split by " ": v.gamename IN ('test', 'wrum')
        - LATER - show button for next/prev page
              - save last 10 search terms and make as a popup for search
                button incl new search
        """
        cursor = self._conn.cursor()
        try:
            # count
            cursor.execute(
                "SELECT COUNT(DISTINCT software.id) "
                "FROM sets "
                "JOIN software ON software.id = sets.softwarelink_id "
                "WHERE sets.gamename LIKE ?", ("%"+my_search+"%",))
            results_count = cursor.fetchone()[0]
            # fetch
            cursor.execute(
                "SELECT DISTINCT software.id, software.name, year.name as year, maker.name as maker "
                "FROM software "
                "JOIN year ON year.id = software.year_id "
                "JOIN maker ON maker.id = software.developer_id "
                "JOIN sets ON sets.softwarelink_id = software.id "
                "WHERE sets.gamename LIKE ? "
                "ORDER BY software.name LIMIT 100", ("%"+my_search+"%",))
            results = cursor.fetchall()
            pos = 0
            for count, i in enumerate(results):
                # check if search is in beginning of s.name and set pos
                if my_search.lower() == i[1][:len(my_search)].lower():
                    pos = count
                    break

            return results, pos, results_count
        finally:
            cursor.close()

    def get_machines(self, swl_name, machine=None):
        """Return ``(machines, pos)`` for a software list.

        The rows are normalised to plain dicts (the public ``DBMod`` shape
        since the original implementation: ``id``, ``name``, ``label2``,
        ``setname``, ``detail``, ``fullname``, ``status``, ``filter``,
        ``year`` and the historical ``"status,filtr"`` ``maker`` string).
        ``pos`` is the index whose set name equals ``machine`` (0 when it is
        never found or ``machine`` is ``None``).

        TODO join
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT DISTINCT "
                "   s.id, s.name, s.gamename, s.detail, "
                "   y.name as year, m.name as maker, ss.status, ss.filtr "
                "FROM "
                "   sets s, swl sw, "
                "   swl_status ss, year y, "
                "   maker m "
                "WHERE "
                "   sw.name = ? "
                "   AND sw.id = ss.swl_id "
                "   AND s.id = ss.system_id "
                "   AND y.id = s.year_id "
                "   AND m.id = s.publisher_id "
                "ORDER BY "
                "   ss.status DESC, y.name, s.name",
                (swl_name,)
            )

            machines = []
            pos = 0
            for count, db_result in enumerate(cursor.fetchall()):
                machines.append(
                    {
                        'id'       : db_result['id'],
                        'name'     : "{}, {}".format(db_result['gamename'], db_result['maker']),
                        'label2'   : db_result['gamename'],
                        'setname'  : db_result['name'],
                        'detail'   : db_result['detail'],
                        'fullname' : db_result['gamename'],
                        'status'   : db_result['status'],
                        'filter'   : db_result['filtr'],
                        'year'     : db_result['year'],
                        'maker'    : "{},{}".format(db_result['status'], db_result['filtr'])
                    }
                )
                if machine == db_result['name']:
                    pos = count

            return machines, pos
        finally:
            cursor.close()

    def get_info_by_set_and_swl(self, setname, swlname) -> dict:
        """Return the info dict for a set name inside a software list.

        Normalised to a plain dict (the public shape: ``software_id``,
        ``set_id``, ``name``, ``year``, ``maker``, ``label``). A set/software
        combination that matches no row raises ``TypeError`` (the historical
        ``db_fetch[4]`` on ``None`` contract — callers pass names obtained
        from list rows).
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT v.id, v.gamename, y.name, m.name, s.id "
                "FROM software s, sets v, "
                "     swl, year y, maker m "
                "WHERE s.id = v.softwarelink_id AND v.swllink_id = swl.id "
                "AND y.id = v.year_id AND m.id = v.publisher_id "
                "AND v.name = ? AND swl.name = ?",
                (setname, swlname)
            )
            db_fetch = cursor.fetchone()

            return {
                'software_id'   : db_fetch[4],
                'set_id'        : db_fetch[0],
                'name'          : db_fetch[1],
                'year'          : db_fetch[2],
                'maker'         : db_fetch[3],
                'label'         : f"{db_fetch[2]} - {db_fetch[1]}, {db_fetch[3]}",
            }
        finally:
            cursor.close()

    def get_sets_for_software(self, software_id):
        """Return every set of a software id with its joined display columns.

        Row-transparent: the multi-join row shape ``get_all_for_software``
        iterates (``sets`` + ``year``/``maker``/``swl``/``category``/
        ``nplayers``), ordered by year, clone parent and gamename.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT "
                "   sets.id, sets.name, sets.gamename, sets.detail, sets.source, "
                "   year.name as year, maker.name as maker, swl.name as swl, swl.system_id, "
                "   sets.display_type, sets.display_rotation, "
                "   category.name as category, category.flag as category_flag, "
                "   nplayers.name as nplayers, sets.cloneof_id "
                "FROM sets "
                "JOIN year ON sets.year_id = year.id "
                "JOIN maker ON sets.publisher_id = maker.id "
                "JOIN swl ON sets.swllink_id = swl.id "
                "JOIN category ON sets.classification_id = category.id "
                "JOIN nplayers ON sets.nplayers_id = nplayers.id "
                "WHERE "
                "   sets.softwarelink_id = ? "
                "ORDER BY "
                "   year.name, sets.cloneof_id, sets.gamename",
                (software_id,)
            )
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_software_name(self, software_id) -> str:
        """Return the name of a software id.

        A truthy id without a matching software raises ``TypeError`` (the raw
        ``fetchone()[0]`` contract the callers rely on).
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT name FROM software WHERE id = ?", (software_id,)
            )
            return cursor.fetchone()[0]
        finally:
            cursor.close()

    def get_software_ids_for_name(self, name) -> list:
        """Return every software id carrying the exact name, in row order."""
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT id FROM software WHERE name = ?", (name,))
            return [row[0] for row in cursor.fetchall()]
        finally:
            cursor.close()
