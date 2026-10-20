"""Game database repository.

This module centralises the single-purpose, read-only queries over the general
game tables of ``umsa.db`` (``sets``, ``software``, ``swl``, ``year``,
``maker``, ``category``, ``nplayers``, ``swl_status``, plus the media/device
tables ``part``, ``part_set``, ``device``, ``device_set``, ``sharedfeature``,
``sharedfeature_set``) that neither depend on
:class:`~umsa_core.database.DBMod` filter state nor join into other databases.
It follows the conventions of :mod:`umsa_core.artwork_repository` and
:mod:`umsa_core.dat_repository`.

The repository operates on an existing SQLite connection supplied by the
caller; it never opens or closes that connection. All methods are read-only:
they manage no transactions, never commit, and own only short-lived cursors
that are closed in a ``finally`` block.

No ``sqlite3.Row`` escapes this repository. Public query methods return plain
dicts (or the established scalars/tuples/``None``) so the Core-to-add-on
boundary never leaks SQLite row objects. Connections that do not use
``sqlite3.Row`` are still rejected at construction (step 4.2b contract,
decision Q7): the repository reads columns *by name* internally, which only a
row connection provides. Methods whose public shape was never a row
(``get_machine_name``'s plain tuple, the scalar counts, ``get_set_name``'s
bare name, ``get_set_ids_for_software``'s list of ids,
``get_software_ids_for_name``'s id list, ``get_searchresults``'s
``(entries, pos, count)`` bundle, ``get_machines``'s list of plain dicts and
``get_info_by_set_and_swl``'s dict) keep that shape.

Row-returning behaviour that is intentionally kept *inside* Core and is
documented as such: ``get_parts_for_set_id``, ``get_swl_options``,
``get_machine_id``, ``get_sharedfeat_requirement``, ``get_devices_for_machine``
and ``get_sets_for_software``. Those are consumed by other Core modules only
(never by the GUI or screensaver) and keep the native rows for cheap internal
use.
"""

from __future__ import annotations

import sqlite3

from .sqlite import require_row_connection


def _dict_or_none(row):
    """Return ``row`` as a plain dict, or ``None`` when the row is missing.

    Preserves the historical "append whatever ``fetchone()`` gave us" shape for
    queries whose match is optional, without letting a ``sqlite3.Row`` escape.
    """
    return None if row is None else dict(row)


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

    @staticmethod
    def _as_dicts(rows) -> list:
        """Return the given rows as plain dicts, never ``sqlite3.Row``.

        Single conversion point for every read that crosses the Core-to-add-on
        boundary (step 4.8).
        """
        return [dict(row) for row in rows]

    def _fetch_dicts(self, sql: str, params: tuple = ()) -> list:
        """Execute a read and return its rows as plain dicts."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(sql, params)
            return self._as_dicts(cursor.fetchall())
        finally:
            cursor.close()

    def get_maker(self) -> list:
        """Return the list of makers (clones excluded), ordered by name.

        Each entry is a plain dict ``{'id', 'name'}`` (``name as id, name``).
        """
        return self._fetch_dicts(
            "SELECT name as id, name FROM maker "
            "WHERE cloneof_id IS NULL ORDER BY name"
        )

    def get_swl(self) -> list:
        """Return the list of software lists, ordered by name.

        Each entry is a plain dict ``{'id', 'name'}``
        (``name as id, description as name``).
        """
        return self._fetch_dicts(
            "SELECT name as id, description as name FROM swl ORDER BY name"
        )

    def get_source(self) -> list:
        """Return the distinct source files of the sets, ordered by source.

        Each entry is a plain dict with the single ``source`` key.
        """
        return self._fetch_dicts("SELECT DISTINCT source FROM sets ORDER BY source")

    def get_year(self) -> list:
        """Return the list of years, ordered by name.

        Each entry is a plain dict ``{'id', 'name'}``.
        """
        return self._fetch_dicts("SELECT name as id, name FROM year ORDER BY name")

    def get_players(self) -> list:
        """Return the list of player counts, ordered by name.

        Each entry is a plain dict ``{'id', 'name'}``.
        """
        return self._fetch_dicts(
            "SELECT name as id, name FROM nplayers ORDER BY name"
        )

    def get_categories(self) -> list:
        """Return the list of categories, ordered by name.

        Each entry is a plain dict ``{'id', 'name'}``.
        """
        return self._fetch_dicts("SELECT name as id, name FROM category ORDER BY name")

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

    def get_set_info_by_id(self, set_id) -> dict | None:
        """Return the info dict for a set by its ID.

        Returns a plain dict with keys: ``software_id``, ``set_id``, ``name``,
        ``year``, ``maker``, ``label``. Returns ``None`` if the set does not
        exist. This method is read-only and never commits.
        """
        if not set_id:
            return None
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT v.id, v.gamename, y.name, m.name, s.id "
                "FROM software s, sets v, "
                "     swl, year y, maker m "
                "WHERE s.id = v.softwarelink_id AND v.swllink_id = swl.id "
                "AND y.id = v.year_id AND m.id = v.publisher_id "
                "AND v.id = ?",
                (set_id,)
            )
            db_fetch = cursor.fetchone()
            if db_fetch is None:
                return None
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

        Returns a plain dict with ``id``, ``name``, ``year`` and ``maker``, or
        ``None`` when nothing matches.
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
            row = cursor.fetchone()
            return None if row is None else dict(row)
        finally:
            cursor.close()

    def get_series(self, software_id):
        """Return the software entries of the series an id belongs to.

        Each entry is a plain dict ``{'id', 'name', 'year', 'maker'}``.
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
                    "AND m.id = s.developer_id AND s.id = ?", (i['software_id'],)
                )
                all_series.append(_dict_or_none(cursor.fetchone()))
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
        """Return count entries per filter category (dynamic dispatch).

        Each entry is a plain dict ``{'id', 'name', 'count'}`` where ``name``
        is the category label (``description``/``name``, depending on the
        category) and ``count`` is ``count(distinct s.id)``; ``None`` is
        returned for an unknown category. The category column name, the join
        column and the extra ``flag`` predicate are chosen exactly as the
        historical ``DBMod`` selection did.

        The SQL is deliberately left un-aliased, so the aggregate has no
        column name and is read positionally (``row[2]``) inside Core only —
        the caller only ever sees the ``count`` key of the returned dict.
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

        label_column = select_placeholders[0]
        select_statement = "SELECT t.id, t.{}, count(distinct s.id) \
                            FROM {} t, software s, sets v \
                            WHERE t.id = v.{}_id and s.id = v.softwarelink_id {} \
                            GROUP BY t.id ORDER BY t.{}".format(*select_placeholders)
        cursor = self._conn.cursor()
        try:
            cursor.execute(select_statement)
            return [
                {'id': row['id'], 'name': row[label_column], 'count': row[2]}
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()

    def get_searchresults(self, my_search):
        """Return ``(entries, pos, count)`` for a substring search.

        Entries are plain dicts (``id``, ``name``, ``year``, ``maker``) in
        name order (LIMIT 100); ``count`` is the total number of distinct
        matching software; ``pos`` is the index of the first entry whose
        software name starts with the search term (case-insensitively), or 0
        when no entry starts with it.

        TODO:
        - single word search: split by " ": v.gamename IN ('test', 'wrum')
        - LATER - show button for next/prev page
              - save last 10 search terms and make as a popup for search
                button incl new search
        """
        cursor = self._conn.cursor()
        try:
            # count: the aggregate column is unnamed, so it is read by
            # position here inside Core and never returned to a caller.
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
            results = self._as_dicts(cursor.fetchall())
            pos = 0
            for count, i in enumerate(results):
                # check if search is in beginning of s.name and set pos
                if my_search.lower() == i['name'][:len(my_search)].lower():
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

        Intentionally Row-returning (Core-internal contract): the multi-join
        row shape ``get_all_for_software`` iterates (``sets`` +
        ``year``/``maker``/``swl``/``category``/``nplayers``), ordered by year,
        clone parent and gamename. Only Core consumes this; nothing here
        crosses the add-on boundary.
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

    # --- step 4.4: media/parts/device reads feeding the command line --------

    def get_parts_for_set_id(self, set_id) -> list:
        """Return the parts (media) attached to a set, ordered by part name.

        Intentionally Row-returning (Core-internal contract): each row is
        ``p.name, pv.name, pv.disk`` (media name, interface, optional disk
        value). A set can have more than one media (two floppies, floppy +
        cd-rom, ...). Returns an empty list when no parts match — including
        unknown set ids. The only consumer is ``DBMod.create_cmdline``, which
        indexes positionally (``part[0]``/``part[1]``); the rows never leave
        Core.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT   p.name, pv.name, pv.disk \
                 FROM     part_set pv, part p \
                 WHERE    p.id = pv.part_id AND pv.variant_id = ? \
                 ORDER BY p.name", (set_id,))
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_disks(self, swl_name, set_name):
        """Return the disk values of a set inside a software list, or ``None``.

        Two queries by design (set id first, then its ``part_set`` rows): the
        software-list name and set name must match; a missing set, a missing
        software list, or a set without ``part_set`` rows all return ``None``.

        Each entry is a plain dict with the single ``disk`` key (consumers use
        ``entry['disk']``). Nothing is filtered and there is no ``ORDER BY``:
        every ``part_set`` row of the set comes back in rowid order, including
        rows whose disk value is ``NULL``.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT sets.id FROM sets \
                    JOIN swl ON swl.id = sets.swllink_id \
                 WHERE sets.name = ? AND swl.name = ?",
                (set_name, swl_name))
            set_id = cursor.fetchone()
            if set_id:
                cursor.execute(
                    "SELECT disk FROM part_set WHERE variant_id = ?", (set_id['id'],))
                disks = self._as_dicts(cursor.fetchall())
                if disks:
                    return disks
            return None
        finally:
            cursor.close()

    def get_swl_options(self, swl_name):
        """Return the raw options row of a software list, or ``None``.

        Intentionally Row-returning (Core-internal contract): the row carries
        the single ``options`` column. A ``NULL`` options value stays ``None``
        inside the row (the facade branches on ``row[0]`` truthiness); an
        unknown software list returns ``None`` — the facade then raises
        ``TypeError`` on ``row[0]``, the historical valid-input assumption.
        Only Core consumes this; it never crosses the add-on boundary.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT options FROM swl WHERE name = ?", (swl_name,))
            return cursor.fetchone()
        finally:
            cursor.close()

    def get_machine_id(self, machine_name):
        """Return the machine's set row under the ``mame`` software list.

        Intentionally Row-returning (Core-internal contract): the row carries
        the single ``id`` column (the sets id used as the device variant id).
        Machine rows resolve only under the software list ``mame`` — that name
        is hardcoded in the query, as it always was inside
        ``DBMod.get_cmd_line_options``. An unknown machine returns ``None``;
        the facade then raises ``TypeError`` on ``row[0]`` (the historical
        valid-input assumption). Only Core consumes this.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT v.id \
                 FROM sets v, swl \
                 WHERE v.swllink_id = swl.id AND swl.name = ? AND v.name = ?",
                ('mame', machine_name)
            )
            return cursor.fetchone()
        finally:
            cursor.close()

    def get_devices_for_machine(self, machine_id) -> list:
        """Return the devices of a machine, ordered by device name.

        Intentionally Row-returning (Core-internal contract): each row is
        ``d.name, dv.name`` (device, interface list). The interface may hold a
        comma-separated list (e.g. ``cart64,c128_cart``) which
        ``DBMod.create_cmdline`` splits. Returns an empty list for a machine
        without devices. The only consumer indexes positionally
        (``device[0]``/``device[1]``); the rows never leave Core.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT d.name, dv.name \
                 FROM device_set dv, device d \
                 WHERE d.id = dv.device_id AND dv.variant_id = ? \
                 ORDER BY d.name", (machine_id,))
            return cursor.fetchall()
        finally:
            cursor.close()

    def get_sharedfeat_requirement(self, set_id):
        """Return the raw ``requirement`` shared-feature row of a set, or ``None``.

        Intentionally Row-returning (Core-internal contract): the row carries
        the single ``sfv.name`` column — normally an ``swl:set`` string that
        ``DBMod.get_cmd_line_options`` expands into a chained command line.
        Sets without a requirement (or unknown ids) return ``None``. Only Core
        consumes this; it never crosses the add-on boundary.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT sfv.name FROM sharedfeature sf, sharedfeature_set sfv \
                 WHERE sf.name = 'requirement' AND sf.id = sfv.sharedfeat_id AND sfv.variant_id = ? \
                 ORDER BY sf.name", (set_id,)
            )
            return cursor.fetchone()
        finally:
            cursor.close()
