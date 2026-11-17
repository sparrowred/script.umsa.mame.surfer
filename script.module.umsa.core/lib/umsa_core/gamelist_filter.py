"""Game list queries: filter, selector, order and the Prev/Next windowing.

The engine functions take the connection and an explicit
:class:`GamelistFilter`; :class:`Gamelist` keeps that state between calls.
Every outside value is a bind parameter; only fixed column/join/order
fragments are interpolated. The connection is never closed or committed.
"""

from __future__ import annotations

import random
import sqlite3
import time
from array import array
from dataclasses import dataclass, field

from .logging import log
from .software_search import SoftwareSearch

# Candidate lists kept by Gamelist.get_random_id (filtered + unfiltered,
# a few filter variants).
_RANDOM_ID_CACHE_SIZE = 4

_ORDER_SQL = {
    "name": "software.name",
    "year": "year.name, software.name",
    "publisher": "maker.name, software.name",
}
_ORDER_FALLBACK = "software.name"
# Sort key columns per order; Prev/Next pages along exactly these columns.
_ORDER_KEYS = {
    "name": ("software.name",),
    "year": ("year.name", "software.name"),
    "publisher": ("maker.name", "software.name"),
}
# Rows per Prev/Next page.
PAGE_SIZE = 100


def _page_condition(keys, values, direction, inclusive=True):
    """Return ``(sql, params)`` for rows at or after/before ``values``.

    Keyset condition over the sort ``keys``: for ``next`` the rows whose key
    tuple is ``>=`` the boundary, for ``prev`` the rows ``<=`` it. Written out
    without row values so old SQLite builds work too. The boundary row itself
    is included, so the page starts (next) or ends (prev) with it;
    ``inclusive=False`` leaves it out (``>`` / ``<``).
    """

    strict = '>' if direction == 'next' else '<'
    inclusive = strict + '=' if inclusive else strict
    clauses, params = [], []
    for index, key in enumerate(keys):
        last = index == len(keys) - 1
        parts = [f"{k} = ?" for k in keys[:index]]
        parts.append(f"{key} {inclusive if last else strict} ?")
        params.extend(values[:index + 1])
        clauses.append("(" + " AND ".join(parts) + ")")
    return "(" + " OR ".join(clauses) + ")", params


def _placeholders(values) -> str:
    """Return ``?,?,…`` for ``values``."""
    return ",".join("?" * len(values))


@dataclass
class GamelistFilter:
    """Snapshot of the :class:`Gamelist` state for one list query.

    Attributes:
        join: Selector join set by the ``get_by_*`` family (empty for the
            complete list).
        where: Selector condition; ``where_params`` binds its values.
        order: ``name``, ``year`` or ``publisher``.
        use_filter: Whether the ``filter_*`` clauses are applied.
        filter_join: Joins built by :func:`define_filter`.
        filter_where: Conditions built by :func:`define_filter`;
            ``filter_where_params`` binds them.
    """

    join: str = ""
    where: str = ""
    order: str = "name"
    use_filter: bool = True
    filter_join: tuple = field(default_factory=tuple)
    filter_where: tuple = field(default_factory=tuple)
    where_params: tuple = field(default_factory=tuple)
    filter_where_params: tuple = field(default_factory=tuple)


def _fetch_scalar(cursor: sqlite3.Cursor) -> int:
    """Return the first column of the next row."""
    return cursor.fetchone()[0]


def define_filter(connection: sqlite3.Connection, filter_lists: dict):
    """Build the filter clauses for ``filter_lists``.

    Returns ``(state, display_string)``: ``state`` carries the
    ``filter_join``/``filter_where``/``filter_where_params`` clauses,
    ``display_string`` the ``"count (percent%)"`` label. A category with every
    value selected adds no join.
    """

    filter_join = []
    filter_where = []
    filter_where_params = []
    cursor = connection.cursor()
    try:
        if filter_lists.get('Softwarelists'):
            cursor.execute("SELECT COUNT(id) FROM swl")
            swl_count = _fetch_scalar(cursor)
            if swl_count > len(filter_lists['Softwarelists']):
                filter_join.append("JOIN swl ON swl.id = sets.swllink_id")
                filter_where.append(
                    "swl.id IN ({})".format(_placeholders(filter_lists['Softwarelists'])))
                filter_where_params.extend(filter_lists['Softwarelists'])
            else:
                log("UMSA datbase define_filter: all swls, no filter used", level='debug')
        if ((filter_lists.get('Game Categories')) or
                (filter_lists.get('Machine Categories'))):
            cursor.execute("SELECT COUNT(id) FROM category")
            cat_count = _fetch_scalar(cursor)
            cat_ids = (filter_lists.get('Game Categories', []) +
                       filter_lists.get('Machine Categories', []))
            log(f"UMSA database: filter categories {cat_count}, {len(cat_ids)}",
                level='debug')
            if cat_count > len(cat_ids):
                filter_join.append(
                    "JOIN category ON category.id = sets.classification_id")
                filter_where.append(f"category.id IN ({_placeholders(cat_ids)})")
                filter_where_params.extend(cat_ids)
            else:
                log("UMSA database: define_filter: all categories, no filter used",
                    level='debug')
        if filter_lists.get('Players'):
            cursor.execute("SELECT COUNT(id) FROM nplayers")
            players_count = _fetch_scalar(cursor)
            log(f"UMSA database: filter players {players_count}, "
                f"{len(filter_lists['Players'])}", level='debug')
            if players_count > len(filter_lists['Players']):
                filter_join.append("JOIN nplayers ON nplayers.id = sets.nplayers_id")
                filter_where.append("nplayers.id IN ({})".format(
                    _placeholders(filter_lists['Players'])))
                filter_where_params.extend(filter_lists['Players'])
            else:
                log("UMSA database: define_filter: all players, no filter used",
                    level='debug')
        if filter_lists.get('Years'):
            cursor.execute("SELECT COUNT(id) FROM year")
            year_count = _fetch_scalar(cursor)
            if year_count > len(filter_lists['Years']):
                filter_join.append("JOIN year ON year.id = sets.year_id")
                filter_where.append(
                    "year.id IN ({})".format(_placeholders(filter_lists['Years'])))
                filter_where_params.extend(filter_lists['Years'])
            else:
                log("UMSA database: define_filter: all years, no filter used",
                    level='debug')
        filter_where_clause = ''
        count_params = []
        if filter_join and filter_where:
            filter_where_clause = \
                "WHERE sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                    " ".join(filter_join), " AND ".join(filter_where))
            count_params = list(filter_where_params)
        select_statement = f"SELECT COUNT (DISTINCT software.id) \
            FROM sets JOIN software ON software.id = sets.softwarelink_id {filter_where_clause}"
        cursor.execute(select_statement, count_params)
        count = _fetch_scalar(cursor)
        cursor.execute("SELECT COUNT (software.id) FROM software")
        all_count = _fetch_scalar(cursor)
        if all_count > 0:
            percent = round(count / float(all_count) * 100)
        else:
            percent = 0
    finally:
        cursor.close()

    state = GamelistFilter(
        filter_join=tuple(filter_join),
        filter_where=tuple(filter_where),
        filter_where_params=tuple(filter_where_params),
    )
    return state, f"{count} ({percent}%)"


# Sort keys of the boundary row (software of the current set).
_BOUNDARY_SELECT = (
    "SELECT software.name, year.name, maker.name, software.id FROM software "
    "JOIN year ON year.id = software.year_id "
    "JOIN maker ON maker.id = software.developer_id")
# The complete list reads software directly (one row per software, the name
# order follows ix_software_name) instead of DISTINCT over all sets.
_COMPLETE_FROM = (
    "FROM software JOIN year ON year.id = software.year_id "
    "JOIN maker ON maker.id = software.developer_id")
_COMPLETE_SELECT = (
    "SELECT software.id, software.name, year.name as year, maker.name as maker "
    + _COMPLETE_FROM)


def _prev_row():
    """Return the Prev sentinel row."""
    return {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'}


def _next_row():
    """Return the Next sentinel row."""
    return {'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'}


def _fetch_boundary(cursor, set_id, software_id):
    """Return ``(name, year, maker, software id)`` of the current software."""

    if set_id:
        cursor.execute(
            f"{_BOUNDARY_SELECT} JOIN sets ON software.id = sets.softwarelink_id "
            "WHERE sets.id = ?", (set_id,))
        return cursor.fetchone()
    if software_id:
        cursor.execute(f"{_BOUNDARY_SELECT} WHERE software.id = ?", (software_id,))
        return cursor.fetchone()
    log("UMSA database: execute_statement: no set or software id error",
        level='debug')
    return None


def _order_of(state):
    """Return ``(ORDER BY columns, sort keys)``; resets an unknown order."""

    order = _ORDER_SQL.get(state.order)
    if order is None:
        state.order = _ORDER_FALLBACK
        order = _ORDER_FALLBACK
    return order, _ORDER_KEYS.get(state.order, (_ORDER_FALLBACK,))


def _key_values(keys, boundary):
    """Return the values of the sort ``keys`` of a boundary row."""

    values = {"software.name": boundary[0], "year.name": boundary[1],
              "maker.name": boundary[2]}
    return [values[k] for k in keys]


def _window_rows(window, start, total, index):
    """Add the Prev/Next sentinels to a window of the list.

    ``window`` holds the rows ``start`` … ``start + PAGE_SIZE`` of a list of
    ``total`` rows, ``index`` is the row of the current software. Returns
    ``(slist, pos)``.
    """

    pos = index - start
    if start > 0:
        window.insert(0, _prev_row())
        pos += 1
    if start + PAGE_SIZE < total:
        window.append(_next_row())
    return window, pos


def _window_start(index, total):
    """Return the first row of the window around row ``index``.

    The current software is row 50 (1-based), clamped to the list; a short
    list is shown completely.
    """

    return max(0, min(index - (PAGE_SIZE // 2 - 1), total - PAGE_SIZE))


def _page_rows(slist, prevnext):
    """Turn a fetched Prev/Next page into ``(slist, pos)``.

    A page holds PAGE_SIZE rows including the boundary row; the extra fetched
    row only signals that the list goes on.
    """

    more = len(slist) > PAGE_SIZE
    slist = slist[:PAGE_SIZE]
    if prevnext == 'next':
        # Boundary row first; the way back is always possible.
        slist.insert(0, _prev_row())
        if more:
            slist.append(_next_row())
        return slist, 1
    # Prev: fetched in descending order, boundary row last after reverse.
    slist.reverse()
    slist.append(_next_row())
    if more:
        slist.insert(0, _prev_row())
    return slist, len(slist) - 2  # the boundary row, before the next entry


def _complete_list_clause(state, filtered):
    """Return ``(sql, params)``: software of the complete list.

    A software belongs to the list when one of its sets passes the active
    filter (``filtered``) or, without filter, when it has a set at all.
    """

    if filtered:
        return ("EXISTS (SELECT 1 FROM sets {} WHERE sets.softwarelink_id = "
                "software.id AND {})".format(
                    " ".join(state.filter_join), " AND ".join(state.filter_where)),
                list(state.filter_where_params))
    return "EXISTS (SELECT 1 FROM sets WHERE sets.softwarelink_id = software.id)", []


def _fetch_dict_rows(cursor, sql, params):
    """Run ``sql`` and return its rows as dicts."""
    cursor.execute(sql, params)
    return [dict(row) for row in cursor.fetchall()]


def _complete_window(cursor, cond, params, order, keys, boundary):
    """Return ``(slist, pos, total)``: the window around the current software.

    One pass counts the list, the rows before the current software and
    whether it is part of the list; two keyset queries then read only the
    rows of the window. A software that is not in the list (or no current
    software) starts the window at the top, like the full-list path.
    """

    index = 0
    member = False
    if boundary is None:
        cursor.execute(f"SELECT COUNT(*) {_COMPLETE_FROM} WHERE {cond}", params)
        total = cursor.fetchone()[0]
    else:
        values = _key_values(keys, boundary)
        before_sql, before_params = _page_condition(keys, values, 'prev', inclusive=False)
        cursor.execute(
            f"SELECT COUNT(*), TOTAL({before_sql}), TOTAL(software.id = ?) "
            f"{_COMPLETE_FROM} WHERE {cond}",
            before_params + [boundary[3]] + params)
        total, before, found = cursor.fetchone()
        member = bool(found)
        if member:
            index = int(before)
    if not total:
        return [], 0, 0

    start = _window_start(index, total)
    if not member:
        window = _fetch_dict_rows(
            cursor, f"{_COMPLETE_SELECT} WHERE {cond} ORDER BY {order} "
            f"LIMIT {PAGE_SIZE}", params)
    else:
        n_before = index - start
        window = []
        if n_before:
            desc = ", ".join(f"{k} DESC" for k in keys)
            window = _fetch_dict_rows(
                cursor, f"{_COMPLETE_SELECT} WHERE {before_sql} AND {cond} "
                f"ORDER BY {desc} LIMIT {n_before}", before_params + params)
            window.reverse()
        after_sql, after_params = _page_condition(keys, values, 'next')
        asc = ", ".join(f"{k} ASC" for k in keys)
        window += _fetch_dict_rows(
            cursor, f"{_COMPLETE_SELECT} WHERE {after_sql} AND {cond} "
            f"ORDER BY {asc} LIMIT {PAGE_SIZE - n_before}", after_params + params)
    slist, pos = _window_rows(window, start, total, index)
    return slist, pos, total


def _execute_complete(connection, state, set_id, software_id, prevnext):
    """:func:`execute_statement` for the complete list (no selector).

    Reads only the shown window or page instead of every software; the
    result has the same shape as the full-list path.
    """

    time_start = time.time()
    order, keys = _order_of(state)
    filtered = bool(state.use_filter and state.filter_join and state.filter_where)
    cursor = connection.cursor()
    try:
        boundary = _fetch_boundary(cursor, set_id, software_id)
        if prevnext and boundary is None:
            log("UMSA database: execute_statement: no software name for "
                f"{prevnext}, empty result", level='debug')
            return [], 0, 0
        slist, pos, result_count = [], 0, 0
        # With an active filter that leaves nothing, retry once without it.
        for apply_filter in ((True, False) if filtered else (False,)):
            cond, params = _complete_list_clause(state, apply_filter)
            if prevnext:
                page_where, page_params = _page_condition(
                    keys, _key_values(keys, boundary), prevnext)
                direction = "ASC" if prevnext == 'next' else "DESC"
                page_order = ", ".join(f"{k} {direction}" for k in keys)
                rows = _fetch_dict_rows(
                    cursor, f"{_COMPLETE_SELECT} WHERE {page_where} AND {cond} "
                    f"ORDER BY {page_order} LIMIT {PAGE_SIZE + 1}",
                    page_params + params)
                if rows:
                    slist, pos = _page_rows(rows, prevnext)
            else:
                slist, pos, result_count = _complete_window(
                    cursor, cond, params, order, keys, boundary)
            if slist:
                break
            if apply_filter:
                log("UMSA database: fetch list: no result, retry without filters",
                    level='debug')
    finally:
        cursor.close()
    log(f'UMSA database: execute_statement (complete list) '
        f'{(time.time() - time_start) * 1000:.0f}ms', level='debug')
    return slist, pos, result_count


def execute_statement(connection: sqlite3.Connection, state: GamelistFilter,
                      set_id=None, software_id=None, prevnext=None):
    """Run one game list query for ``state``; return ``(slist, pos, result_count)``.

    Rows are dicts with ``id``/``name``/``year``/``maker``, plus the
    ``prev``/``next`` sentinel rows. An unknown ``state.order`` is reset in
    place to the fallback, so :class:`Gamelist` can take it over. An active
    filter that leaves nothing is retried once without it. The complete list
    reads only the shown window; lists with a selector are read completely.
    An invalid ``prevnext`` gives an empty result.
    """

    if prevnext not in (None, '', 'prev', 'next'):
        log(f"UMSA database: execute_statement: invalid prevnext {prevnext!r}",
            level='debug')
        return [], 0, 0

    if not state.where and not state.join:
        return _execute_complete(connection, state, set_id, software_id, prevnext)

    time_start = time.time()
    result_count = 0
    where = ""
    where_params = []
    filter_join = ""
    filter_where = ""
    filter_join_list = list(state.filter_join)
    filter_where_list = list(state.filter_where)
    filter_where_params = list(state.filter_where_params)
    state_where_params = list(state.where_params)
    if filter_join_list and filter_where_list:
        filter_join = " ".join(filter_join_list)
        filter_where = " AND ".join(filter_where_list)
    s_join, s_where = '', ''
    filters_applied = False
    if state.use_filter and state.where:
        if state.join and state.join not in filter_join_list:
            s_join = f"{state.join} {filter_join}"
        elif filter_join:
            s_join = filter_join
        if state.where and filter_where:
            s_where = f"{state.where} AND {filter_where}"
            s_where_params = state_where_params + filter_where_params
        elif state.where:
            s_where = state.where
            s_where_params = state_where_params
        elif filter_where:
            s_where = filter_where
            s_where_params = filter_where_params
        else:
            s_where_params = []
        if s_join and s_where:
            where = f"sets.id IN (SELECT sets.id FROM sets {s_join} WHERE {s_where})"
            where_params = s_where_params
            filters_applied = bool(filter_where)
        # Only for source.
        elif state.where:
            where = state.where
            where_params = state_where_params
    elif state.use_filter:
        if filter_join and filter_where:
            where = f"sets.id IN (SELECT sets.id FROM sets {filter_join} WHERE {filter_where})"
            where_params = filter_where_params
            filters_applied = True
    elif state.join and state.where:
        where = f"sets.id IN (SELECT sets.id FROM sets {state.join} WHERE {state.where})"
        where_params = state_where_params
    else:
        log("UMSA database: execute_statement: no join and where clause", level='debug')

    # Selector-only retry: keeps the selector and the Prev/Next boundary,
    # drops the filter.
    if state.where:
        retry_where = f"sets.id IN (SELECT sets.id FROM sets {state.join} WHERE {state.where})"
        retry_params = list(state.where_params)
    else:
        retry_where = ""
        retry_params = []

    cursor = connection.cursor()
    try:
        boundary = _fetch_boundary(cursor, set_id, software_id)
        sname = None if boundary is None else boundary[0]
        if prevnext and sname is None:
            log("UMSA database: execute_statement: no software name for "
                f"{prevnext}, empty result", level='debug')
            return [], 0, 0
        order, keys = _order_of(state)
        if prevnext:
            page_where, page_params = _page_condition(
                keys, _key_values(keys, boundary), prevnext)
            direction = "ASC" if prevnext == 'next' else "DESC"
            # One row more than a page tells whether another page follows.
            page_order = ", ".join(f"{k} {direction}" for k in keys)
            page_limit = f"LIMIT {PAGE_SIZE + 1}"
        time_rampup = time.time()

        # At most two attempts: the second is the selector-only retry and only
        # runs when a filter was applied to the first.
        slist = []
        attempt = 0
        while attempt < 2:
            attempt += 1
            if not prevnext:
                if where:
                    i_where = "WHERE "+where
                else:
                    i_where = ""
                i_params = list(where_params)
                limit = ""
                i_order = order
            else:
                if where:
                    i_where = f'WHERE {page_where} AND {where}'
                    i_params = page_params + list(where_params)
                else:
                    i_where = f'WHERE {page_where}'
                    i_params = list(page_params)
                i_order = page_order
                limit = page_limit
            select_statement = f"SELECT DISTINCT \
                    software.id, software.name, year.name as year, maker.name as maker \
                FROM sets \
                    JOIN software ON software.id = sets.softwarelink_id \
                    JOIN year ON year.id = software.year_id \
                    JOIN maker ON maker.id = software.developer_id \
                {i_where} ORDER BY {i_order} {limit}"
            cursor.execute(select_statement, i_params)
            slist = [dict(row) for row in cursor.fetchall()]
            if slist:
                break
            if attempt == 1 and filters_applied:
                log("UMSA database: fetch list: no result, retry without filters",
                    level='debug')
                where = retry_where
                where_params = retry_params
                filters_applied = False
            else:
                break
        time_fetch = time.time()

        if not slist:
            return [], 0, 0

        if not prevnext:
            result_count = len(slist)
            # A current software outside the (filtered) list starts the
            # window at the top.
            index = next(
                (i for i, row in enumerate(slist) if row['name'] == sname), 0)
            start = _window_start(index, len(slist))
            slist, pos = _window_rows(
                slist[start:start + PAGE_SIZE], start, len(slist), index)
        else:
            slist, pos = _page_rows(slist, prevnext)
        time_rest = time.time()
    finally:
        cursor.close()
    log(f'UMSA database: execute_statement: begin {(time_rampup - time_start) * 1000:.0f}ms', level='debug')
    log(f'UMSA database:                   fetch {(time_fetch - time_rampup) * 1000:.0f}ms', level='debug')
    log(f'UMSA database:                   pos   {(time_rest - time_fetch) * 1000:.0f}ms', level='debug')
    log(f'UMSA database:                   all   {(time_rest - time_start) * 1000:.0f}ms', level='debug')
    return slist, pos, result_count


def software_query():
    """Return the selector ``(join, where, params)`` of the complete list."""

    return '', '', []


def source_query(source):
    """Return the selector of a MAME source file."""

    return '', 'sets.source = ?', [source]


def category_query(cat):
    """Return the selector of a category name."""

    return ("JOIN category ON category.id = sets.classification_id",
            'category.name = ?', [cat])


def year_query(year):
    """Return the selector of a year name."""

    return 'JOIN year ON year.id = sets.year_id', 'year.name = ?', [year]


def players_query(players):
    """Return the selector of a player count name."""

    return ('JOIN nplayers ON nplayers.id = sets.nplayers_id',
            'nplayers.name = ?', [players])


def swl_query(swl_name):
    """Return the selector of a software-list name."""

    return 'JOIN swl ON swl.id = sets.swllink_id', 'swl.name = ?', [swl_name]


def maker_query(connection: sqlite3.Connection, maker):
    """Return the selector of a maker name, including its clone family.

    The family is the parent maker and its direct ``cloneof_id`` children;
    deeper descendants are not included.
    """

    cursor = connection.cursor()
    try:
        # An unknown maker has no row: no ids, the name match finds nothing.
        cursor.execute("SELECT id, cloneof_id FROM maker WHERE maker.name = ?", (maker,))
        row = cursor.fetchone()
        cloneof_id = None
        if row is not None:
            cloneof_id = row['cloneof_id'] or row['id']
        all_maker_ids = []
        if cloneof_id:
            cursor.execute("SELECT id FROM maker \
                WHERE cloneof_id = ? OR id = ?", (cloneof_id, cloneof_id))
            for i in cursor.fetchall():
                all_maker_ids.append(str(i['id']))
    finally:
        cursor.close()
    join = 'JOIN maker ON maker.id = sets.publisher_id'
    if all_maker_ids:
        where = 'maker.id IN ({})'.format(
            ",".join("?" * len(all_maker_ids)))
        params = all_maker_ids
    else:
        where = 'maker.name = ?'
        params = [maker]
    return join, where, params


class Gamelist:
    """Filter, order and selector state of the game lists.

    ``get_connection`` is asked on every call, because ``DBMod.open_db``
    replaces the connection after a database update.

    Attributes:
        use_filter: Whether the active filter is applied.
        order: ``name``, ``year`` or ``publisher``.
        filter_join: Clauses of the active filter (with ``filter_where`` and
            ``filter_where_params``), see :meth:`define_filter`.
        join: Selector of the last list (with ``where`` and
            ``where_params``), set by the ``get_by_*`` family and reused for
            its Prev/Next pages.
    """

    def __init__(self, get_connection):
        """Start with the name order, the filter on and no selector."""
        self._get_connection = get_connection
        self.use_filter = True
        self.order = 'name'
        self.join = ''
        self.where = ''
        self.where_params = []
        self.filter_join = []
        self.filter_where = []
        self.filter_where_params = []
        self._search = SoftwareSearch(get_connection)
        self._random_ids_token = None
        self._random_ids_cache = {}

    def search(self, term):
        """Search software by name; return a ``software_search.SearchResult``.

        The active filter applies while ``use_filter`` is on. The selector of
        the last list (``join``/``where``) is left alone.
        """

        if self.use_filter:
            return self._search.search(
                term, tuple(self.filter_join), tuple(self.filter_where),
                tuple(self.filter_where_params))
        return self._search.search(term)

    def set_filter_enabled(self, flag):
        """Enable or disable the active filter for subsequent queries."""

        self.use_filter = flag

    def set_order(self, order):
        """Set the list ordering for subsequent queries.

        Accepts ``name``, ``year`` and ``publisher``;
        :meth:`execute_statement` falls back to the name ordering for any
        other value.
        """

        self.order = order

    def define_filter(self, filter_lists):
        """Make ``filter_lists`` the active filter and return its count label.

        TODO
        - when list smaller then 50% of all do NOT IN = faster?
        - do we need a special field for all as the lists can grow with updates?
          or show new entries after update!
        - make this count always visible in filter list and keep actual, is in gui:
          simply call this more often (:
        """

        state, display = define_filter(self._get_connection(), filter_lists)
        self.filter_join = list(state.filter_join)
        self.filter_where = list(state.filter_where)
        self.filter_where_params = list(state.filter_where_params)
        return display

    def execute_statement(self, set_id=None, software_id=None, prevnext=None):
        """Run the list query of the current selector, filter and order.

        TODO
        - rework var names
        - keep inital count when used with set_id in gui
          so no overwrite with prevnext
        - make number of listmenu entries settings.xml
        - more logic: when swl.name = "gameboy" then no need for swl filter! = faster
        """

        state = GamelistFilter(
            join=self.join,
            where=self.where,
            order=self.order,
            use_filter=self.use_filter,
            filter_join=tuple(self.filter_join),
            filter_where=tuple(self.filter_where),
            where_params=tuple(self.where_params),
            filter_where_params=tuple(self.filter_where_params),
        )
        slist, pos, result_count = execute_statement(
            self._get_connection(), state, set_id, software_id, prevnext)
        self.order = state.order
        return slist, pos, result_count

    def get_by_software(self, set_id):
        """Select the complete list and return it (see :meth:`execute_statement`)."""

        self.join, self.where, self.where_params = software_query()
        return self.execute_statement(set_id)

    def get_software_for_source(self, set_id, source):
        """Select the software of a MAME source file and return the list."""

        self.join, self.where, self.where_params = source_query(source)
        return self.execute_statement(set_id)

    def get_by_cat(self, cat, set_id):
        """Select the software of a category and return the list."""

        self.join, self.where, self.where_params = category_query(cat)
        return self.execute_statement(set_id)

    def get_by_year(self, year, set_id):
        """Select the software of a year and return the list."""

        self.join, self.where, self.where_params = year_query(year)
        return self.execute_statement(set_id)

    def get_by_players(self, players, set_id):
        """Select the software for a number of players and return the list."""

        self.join, self.where, self.where_params = players_query(players)
        return self.execute_statement(set_id)

    def get_by_maker(self, maker, set_id):
        """Select the software of a maker (with clones) and return the list."""

        self.join, self.where, self.where_params = maker_query(
            self._get_connection(), maker)
        return self.execute_statement(set_id)

    def get_by_swl(self, swl_name, set_id):
        """Select the software of a software list and return the list."""

        self.join, self.where, self.where_params = swl_query(swl_name)
        return self.execute_statement(set_id)

    def get_random_id(self):
        """Return the id of a random software, or ``None`` for an empty DB.

        The filter is applied only while ``use_filter`` is on. When it leaves
        nothing, the pick falls back to the whole database (like the
        selector-only retry of :meth:`execute_statement` and the random
        artwork). Every software has the same chance, whatever its number of
        sets.
        """

        if self.use_filter and self.filter_join and self.filter_where:
            ids = self._random_candidates(True)
            if ids:
                return random.choice(ids)
            log("UMSA database: get_random_id: filter leaves nothing, "
                "picking unfiltered", level='debug')
        ids = self._random_candidates(False)
        return random.choice(ids) if ids else None

    def _random_candidates(self, filtered):
        """Return the software ids :meth:`get_random_id` picks from.

        The ids of one filter (or of the whole database) are read once and
        kept, so a pick does not sort all software by ``RANDOM()``. umsa.db is
        read-only, so the lists are dropped only when the connection changes.
        """

        connection = self._get_connection()
        if connection is not self._random_ids_token:
            self._random_ids_cache = {}
            self._random_ids_token = connection
        cache = self._random_ids_cache

        key = None
        where, params = '', []
        if filtered:
            key = (tuple(self.filter_join), tuple(self.filter_where),
                   tuple(self.filter_where_params))
            where = "WHERE sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
                " ".join(self.filter_join), " AND ".join(self.filter_where))
            params = list(self.filter_where_params)
        if key in cache:
            return cache[key]

        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT DISTINCT sets.softwarelink_id FROM sets "
                "JOIN software ON software.id = sets.softwarelink_id "
                f"{where}", params)
            ids = array('q', (row[0] for row in cursor.fetchall()))
        finally:
            cursor.close()

        if len(cache) >= _RANDOM_ID_CACHE_SIZE:
            cache.clear()
        cache[key] = ids
        return ids


def build_filter_lists(filter_lists, category, games):
    """Return ``{'active': […], 'inactive': […]}`` entries of a filter category.

    ``games`` is the game repository. ``active`` holds the entries whose id
    is in ``filter_lists[category]``, in database order. Each entry is
    ``{'id': str, 'name', 'count'}``; an unknown category gives empty lists.
    """

    active_ids = set(filter_lists.get(category, []))
    active = []
    inactive = []
    for entry in (games.get_all_dbentries(category) or []):
        item = {'id': str(entry['id']), 'name': entry['name'], 'count': entry['count']}
        (active if item['id'] in active_ids else inactive).append(item)
    return {'active': active, 'inactive': inactive}
