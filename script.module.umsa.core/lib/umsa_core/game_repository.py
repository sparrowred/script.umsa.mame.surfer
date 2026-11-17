"""Read-only queries over the game tables of umsa.db that need no filter state.

Public methods return plain dicts, tuples or scalars; the few methods that
return ``sqlite3.Row`` say so and are used inside Core only (command line,
software details).
"""

from __future__ import annotations

import os
import sqlite3

from .data_paths import CoreDataPaths
from .logging import log
from .sqlite import connect_sqlite_readonly, require_row_connection

# Ids per ``IN (...)`` statement, below the 999-variable limit of older SQLite.
_IN_BLOCK = 500


def _dict_or_none(row):
    """Return ``row`` as a plain dict, or ``None`` when the row is missing."""
    return None if row is None else dict(row)


class GameRepository:
    """Read-only game-table queries on a caller-owned connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Wrap a umsa.db connection.

        Raises:
            ValueError: If the connection does not use ``sqlite3.Row``
                (:func:`umsa_core.sqlite.require_row_connection`).
        """
        require_row_connection(connection, "GameRepository")
        self._conn = connection

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @staticmethod
    def _as_dicts(rows) -> list:
        """Return the given rows as plain dicts."""
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
        """Return the makers (clones excluded) as ``{'id', 'name'}``, ordered by name."""
        return self._fetch_dicts(
            "SELECT name as id, name FROM maker "
            "WHERE cloneof_id IS NULL ORDER BY name"
        )

    def get_swl(self) -> list:
        return self._fetch_dicts(
            "SELECT name as id, description as name FROM swl ORDER BY name"
        )

    def get_source(self) -> list:
        return self._fetch_dicts("SELECT DISTINCT source FROM sets ORDER BY source")

    def get_year(self) -> list:
        return self._fetch_dicts("SELECT name as id, name FROM year ORDER BY name")

    def get_players(self) -> list:
        return self._fetch_dicts(
            "SELECT name as id, name FROM nplayers ORDER BY name"
        )

    def get_categories(self) -> list:
        return self._fetch_dicts("SELECT name as id, name FROM category ORDER BY name")

    def get_set_name(self, set_id) -> str | None:
        """Return the set name for a set id, or ``None`` for a falsy id.

        Raises:
            TypeError: If a truthy id matches no set.
        """
        if not set_id:
            return None
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT name FROM sets WHERE id = ?", (set_id,))
            return cursor.fetchone()[0]
        finally:
            cursor.close()

    def get_set_source(self, set_id) -> str | None:
        """Return the driver source file of a set, or ``None`` if unknown or empty."""
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT source FROM sets WHERE id = ?", (set_id,))
            row = cursor.fetchone()
            return (row[0] or None) if row else None
        finally:
            cursor.close()

    def get_machine_name(self, machine_id) -> tuple:
        """Return the ``(name, gamename)`` tuple of a set id.

        Raises:
            TypeError: If the id matches no set.
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
        """Return the info dict of a set, or ``None`` if it does not exist.

        Keys: ``software_id``, ``set_id``, ``name``, ``year``, ``maker``,
        ``label``.
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
        """Return the first software with a set name starting with ``my_search``.

        The dict has ``id``, ``name``, ``year`` and ``maker``; ``None`` if none.
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
        """Return the entries of the first series the software belongs to.

        ``None`` when the software has no series. See
        :meth:`get_series_entries`.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT series_id "
                "FROM series_seq WHERE software_id = ?", (software_id,)
            )
            series_ids = cursor.fetchall()
        finally:
            cursor.close()
        if not series_ids:
            return None
        return self.get_series_entries(series_ids[0]['series_id'])

    def get_series_entries(self, series_id):
        """Return the software entries (``id``, ``name``, ``year``, ``maker``) of a series.

        Ordered by ``seqno``, then year; ``[]`` for an unknown series id.
        """
        cursor = self._conn.cursor()
        try:
            all_series = []
            cursor.execute(
                "SELECT software_id "
                "FROM series_seq, software, year "
                "WHERE series_id = ? AND software_id = software.id "
                "AND software.year_id = year.id "
                "ORDER BY seqno, year.name",
                (series_id,),
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

    def has_software(self) -> bool:
        """Return whether umsa.db holds any software with a set.

        False for a database without rows (a broken download); the GUI then
        fetches umsa.db again.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM sets JOIN software "
                "ON software.id = sets.softwarelink_id LIMIT 1")
            return cursor.fetchone() is not None
        finally:
            cursor.close()

    def check_series(self, software_id) -> int | None:
        """Return the number of entries in the software's first series, or ``None``."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT series_id "
                "FROM series_seq WHERE software_id = ?", (software_id,)
            )
            series_exists = cursor.fetchone()
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
        """Return ``{'id', 'name', 'count'}`` per entry of a filter category.

        ``count`` is the number of distinct software; ``None`` for an unknown
        category.
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

    def get_machines(self, swl_name, machine=None):
        """Return ``(machines, pos)`` for a software list.

        Each machine is a dict with ``id``, ``name``, ``label2``, ``setname``,
        ``detail``, ``fullname``, ``status``, ``filter``, ``year``, ``source``
        (driver file) and ``maker`` (the string ``"status,filtr"``). ``pos``
        is the index whose set name equals ``machine``, else 0.

        TODO join
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT DISTINCT "
                "   s.id, s.name, s.gamename, s.detail, s.source, "
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
                        'source'   : db_result['source'],
                        'maker'    : "{},{}".format(db_result['status'], db_result['filtr'])
                    }
                )
                if machine == db_result['name']:
                    pos = count

            return machines, pos
        finally:
            cursor.close()

    def get_software_for_sets(self, set_ids) -> dict:
        """Return ``{set id: {'id', 'name', 'year', 'maker'}}`` of each set's software.

        Set ids without software are missing. The ids are queried in blocks
        below SQLite's variable limit.
        """
        ids = list(set_ids)
        result = {}
        cursor = self._conn.cursor()
        try:
            for start in range(0, len(ids), _IN_BLOCK):
                block = ids[start:start + _IN_BLOCK]
                placeholders = ",".join(["?"] * len(block))
                cursor.execute(
                    "SELECT sets.id AS set_id, software.id, software.name, "
                    "       year.name AS year, maker.name AS maker "
                    "FROM software "
                    "   JOIN year ON software.year_id = year.id "
                    "   JOIN maker ON software.developer_id = maker.id "
                    "   JOIN sets ON software.id = sets.softwarelink_id "
                    f"WHERE sets.id IN ({placeholders})",
                    block,
                )
                for row in cursor.fetchall():
                    result[row["set_id"]] = {
                        'id': row["id"],
                        'name': row["name"],
                        'year': row["year"],
                        'maker': row["maker"],
                    }
            return result
        finally:
            cursor.close()

    def get_info_by_set_and_swl(self, setname, swlname) -> dict:
        """Return the info dict of a set name inside a software list.

        Same keys as :meth:`get_set_info_by_id`.

        Raises:
            TypeError: If the combination matches no row.
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
        """Return every set of a software with its joined display columns.

        Returns ``sqlite3.Row`` (Core only), ordered by year, clone parent and
        gamename.
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

        Raises:
            TypeError: If the id matches no software.
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

    # --- media/parts/device reads feeding the command line --------

    def get_parts_for_set_id(self, set_id) -> list:
        """Return the parts (media) of a set, ordered by part name.

        Returns ``sqlite3.Row`` (Core only): ``(media name, interface, disk)``.
        A set can have several media (two floppies, floppy + cd-rom).
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
        """Return the ``{'disk'}`` dicts of a set inside a software list, or ``None``.

        Every ``part_set`` row of the set comes back in rowid order, including
        ``NULL`` disks. A missing set or a set without parts gives ``None``.
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
        """Return the ``options`` row of a software list, or ``None`` if unknown.

        Returns ``sqlite3.Row`` (Core only); a ``NULL`` value stays ``None``
        inside the row.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT options FROM swl WHERE name = ?", (swl_name,))
            return cursor.fetchone()
        finally:
            cursor.close()

    def get_machine_id(self, machine_name):
        """Return the ``id`` row of a machine in the ``mame`` software list, or ``None``.

        Returns ``sqlite3.Row`` (Core only); the id is the device variant id.
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

        Returns ``sqlite3.Row`` (Core only): ``(device, interfaces)``; the
        interfaces may be a comma-separated list (``cart64,c128_cart``).
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
        """Return the ``requirement`` shared-feature row of a set, or ``None``.

        Returns ``sqlite3.Row`` (Core only) with one column, normally an
        ``swl:set`` string.
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


def parse_recommended_games(rec_text, games):
    """Parse the 'Rec' DAT field into popup entries; return ``(rec_list, pos)``.

    Separator entries (names starting with ``-``) are
    ``{'name', 'id': 0, 'year', 'maker'}`` and each increments ``pos``; found
    games are ``{'id', 'name', 'year', 'maker'}``; names not found are ``None``.
    """

    rec_list = []
    pos = 0
    for rec_gamename in rec_text.split('[CR]'):
        if rec_gamename == '':
            continue
        if rec_gamename[0] == '-':
            rec_list.append({'name': rec_gamename, 'id': 0, 'year': '', 'maker': ''})
            pos += 1
        else:
            found = games.search_single(rec_gamename)
            rec_list.append(
                None if found is None else
                {'id': found['id'], 'name': found['name'],
                 'year': found['year'], 'maker': found['maker']})
    return rec_list, pos


def random_vgm_batch(db_path, limit=100):
    """Return up to ``limit`` random ``{'name', 'gamename'}`` sets of the vgmplay list.

    ``db_path`` is the Core data directory. Uses its own short-lived
    read-only connection; returns ``[]`` on a database error. Callers check
    which entries are playable.
    """

    db_paths = CoreDataPaths(os.path.abspath(db_path))
    try:
        db_conn = connect_sqlite_readonly(db_paths.umsa_db)
    except sqlite3.Error as error:
        log(f"UMSA database random_vgm_batch: open failed: {error}", level='warning')
        return []

    dbc = None
    try:
        dbc = db_conn.cursor()
        vgmplay_row = dbc.execute(
            "SELECT id FROM swl WHERE name = 'vgmplay'").fetchone()
        if vgmplay_row is None:
            log("UMSA database random_vgm_batch: no vgmplay software list",
                level='warning')
            return []
        rows = dbc.execute(
            "SELECT name, gamename FROM sets \
             WHERE swllink_id = ? ORDER BY RANDOM() LIMIT ?",
            (vgmplay_row[0], limit)).fetchall()
    except sqlite3.Error as error:
        log(f"UMSA database random_vgm_batch: read failed: {error}",
            level='warning')
        return []
    finally:
        if dbc is not None:
            dbc.close()
        db_conn.close()

    return [{'name': row[0], 'gamename': row[1]} for row in rows]
