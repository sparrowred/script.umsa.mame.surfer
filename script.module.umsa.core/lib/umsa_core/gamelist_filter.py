"""Explicit-state gamelist filter and query composition.

This module holds the query *engine* of the frontend gamelist: the filter
definition behind :meth:`umsa_core.database.DBMod.define_filter`, the
per-selector query state built by the ``DBMod.get_by_*`` family, and the
list fetch/windowing behind :meth:`umsa_core.database.DBMod.execute_statement`.

Unlike the historical implementation, nothing here reads mutable ``DBMod``
attributes. Every entry point receives the caller-owned SQLite connection and
an explicit :class:`GamelistFilter` state value. ``DBMod`` stays the public
compatibility facade and the public state holder; it builds the state per call
and copies the resulting filter clauses back into its own attributes.

All values that originate from outside the module (category/year/player/swl/
source/maker names, filter id lists, software names, art types, id lists) are
passed as SQL bind parameters. Only fixed column/join/order fragments are
interpolated. Each clause therefore carries its own ``(sql, params)`` pair so
the parameter order survives the way the historical code concatenated clauses.

The module is Kodi-independent and imports no GUI/screensaver module. It never
opens, closes or commits the connection it is given and owns only short-lived
cursors that are closed deterministically.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field

from .logging import log

_ORDER_SQL = {
    "name": "software.name",
    "year": "year.name, software.name",
    "publisher": "maker.name, software.name",
}
_ORDER_FALLBACK = "software.name"


def _placeholders(values) -> str:
    return ",".join("?" * len(values))


@dataclass
class GamelistFilter:
    """Explicit filter/query state for one gamelist statement.

    Mirrors the historical public ``DBMod`` attributes:

    - ``join``/``where``: the per-selector state set by the ``get_by_*``
      family (empty for the complete list); ``where_params`` binds its values.
    - ``order``: one of ``name``, ``year``, ``publisher``.
    - ``use_filter``: whether the active ``filter_*`` clauses are applied.
    - ``filter_join``/``filter_where``: the clauses built by
      :func:`define_filter`; ``filter_where_params`` binds ``filter_where``.
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
    return cursor.fetchone()[0]


def define_filter(connection: sqlite3.Connection, filter_lists: dict):
    """Build the filter clauses for ``filter_lists``.

    Returns ``(state, display_string)`` where ``state`` carries the new
    ``filter_join``/``filter_where``/``filter_where_params`` clauses and
    ``display_string`` is the historical ``"count (percent%)"`` label. A join is
    skipped when every value in that category is selected.
    """

    filter_join = []
    filter_where = []
    filter_where_params = []
    cursor = connection.cursor()
    try:
        # swl
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
        # game categories, machines
        if ((filter_lists.get('Game Categories')) or
                (filter_lists.get('Machine Categories'))):
            cursor.execute("SELECT COUNT(id) FROM category")
            cat_count = _fetch_scalar(cursor)
            cat_ids = (filter_lists['Game Categories'] +
                       filter_lists['Machine Categories'])
            log(f"UMSA database: filter categories {cat_count}, {len(cat_ids)}",
                level='debug')
            if cat_count > len(cat_ids):
                filter_join.append(
                    "JOIN category ON category.id = sets.classification_id")
                filter_where.append("category.id IN ({})".format(_placeholders(cat_ids)))
                filter_where_params.extend(cat_ids)
            else:
                log("UMSA database: define_filter: all categories, no filter used",
                    level='debug')
        # players
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
        # years
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
        # count
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
        percent = int(round(count/float(all_count)*100))
    finally:
        cursor.close()

    state = GamelistFilter(
        filter_join=tuple(filter_join),
        filter_where=tuple(filter_where),
        filter_where_params=tuple(filter_where_params),
    )
    return state, f"{count} ({percent}%)"


def execute_statement(connection: sqlite3.Connection, state: GamelistFilter,
                      set_id=None, software_id=None, prevnext=None):
    """Compose and run one gamelist query from explicit ``state``.

    Returns the historical ``(slist, pos, result_count)`` tuple. The list mixes
    ``sqlite3.Row`` entries with plain-dictionary ``prev``/``next`` sentinel
    entries. When ``state.order`` is not a known order name it is reset in place
    to the safe fallback so the facade can mirror the historical reset.
    """

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
    # prepare joins and wheres from filters
    s_join, s_where = '', ''
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
        # only for source
        elif state.where:
            where = state.where
            where_params = state_where_params
    elif state.use_filter:
        if filter_join and filter_where:
            where = f"sets.id IN (SELECT sets.id FROM sets {filter_join} WHERE {filter_where})"
            where_params = filter_where_params
    elif state.join and state.where:
        where = f"sets.id IN (SELECT sets.id FROM sets {state.join} WHERE {state.where})"
        where_params = state_where_params
    else:
        log("UMSA database: execute_statement: no join and where clause", level='debug')

    cursor = connection.cursor()
    try:
        # get software name
        if set_id:
            name_statement = "SELECT software.name FROM software \
                    JOIN sets ON software.id = sets.softwarelink_id \
                    WHERE sets.id = ?"
            cursor.execute(name_statement, (set_id,))
            sname = cursor.fetchone()[0]
        elif software_id:
            cursor.execute(
                "SELECT software.name FROM software WHERE software.id = ?",
                (software_id,)
            )
            sname = cursor.fetchone()[0]
        else:
            log("UMSA database: execute_statement: no set or software id error",
                level='debug')
        # add ordering
        order = _ORDER_SQL.get(state.order)
        if order is None:
            state.order = _ORDER_FALLBACK
            order = _ORDER_FALLBACK
        time_rampup = time.time()

        # fetch
        slist = []
        while not slist:
            # normal, previous or next
            if not prevnext:
                if where:
                    i_where = "WHERE "+where
                else:
                    i_where = ""
                i_params = list(where_params)
                limit = ""
            elif prevnext == 'prev':
                if where:
                    i_where = f'WHERE software.name <= ? AND {where}'
                    i_params = [sname] + list(where_params)
                else:
                    i_where = 'WHERE software.name <= ?'
                    i_params = [sname]
                limit = "DESC LIMIT 100"
            elif prevnext == 'next':
                if where:
                    i_where = f'WHERE software.name >= ? AND {where}'
                    i_params = [sname] + list(where_params)
                else:
                    i_where = 'WHERE software.name >= ?'
                    i_params = [sname]
                limit = "ASC LIMIT 100"
            else:
                log("UMSA database execute_statement: prevnext error {prevnext}",
                    level='debug')
            # fetch software list
            select_statement = f"SELECT DISTINCT \
                    software.id, software.name, year.name as year, maker.name as maker \
                FROM sets \
                    JOIN software ON software.id = sets.softwarelink_id \
                    JOIN year ON year.id = software.year_id \
                    JOIN maker ON maker.id = software.developer_id \
                {i_where} ORDER BY {order} {limit}"
            cursor.execute(select_statement, i_params)
            slist = cursor.fetchall()
            # no results: try without filter
            if len(slist) == 0:
                log("UMSA database: fetch list: no result, retry without filters",
                    level='debug')
                if state.where:
                    where = f"sets.id IN (SELECT sets.id FROM sets {state.join} WHERE {state.where})"
                    where_params = list(state.where_params)
                else:
                    where = ""
                    where_params = []
        time_fetch = time.time()

        # get position and set prevnext
        if not prevnext:
            result_count = len(slist)
            # search for name
            # TODO rework
            count, pos = 0, 0
            for i in slist:
                count += 1
                if sname == i['name']:
                    pos = count
                    break
            # TODO do we need new_slist?
            if count < 50: # begin of list
                pos -= 1
                # TODO get rid of flag, try without new_slist
                flag = None
                if len(slist) > 100:
                    flag = True
                new_slist = slist[:count+50+(50-count)]
                if flag:
                    new_slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
            elif count > len(slist)-100: # end of list
                pos = pos-(len(slist)-100)
                new_slist = slist[count-(count-(len(slist)-100)):]
                new_slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
            else: # middle of list
                pos = 50
                new_slist = slist[count-50:count+50]
                new_slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
                new_slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
            slist = new_slist
        elif prevnext == 'next':
            pos = 1
            slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
            if len(slist) == 100:
                slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
        else: # prev
            pos = len(slist)
            slist.reverse()
            slist.append({'id': "next", 'name': "", 'year': ">>>", 'maker': '>>>'})
            if len(slist) == 100:
                slist.insert(0, {'id': "prev", 'name': "", 'year': "<<<", 'maker': '<<<'})
        time_rest = time.time()
    finally:
        cursor.close()
    log(f'UMSA database: execute_statement: begin {(time_rampup - time_start) * 1000:.0f}ms', level='debug')
    log(f'UMSA database:                   fetch {(time_fetch - time_rampup) * 1000:.0f}ms', level='debug')
    log(f'UMSA database:                   pos   {(time_rest - time_fetch) * 1000:.0f}ms', level='debug')
    log(f'UMSA database:                   all   {(time_rest - time_start) * 1000:.0f}ms', level='debug')
    return slist, pos, result_count


def software_query():
    """Selector state for the complete list."""

    return '', '', []


def source_query(source):
    """Selector state for a MAME source file."""

    return '', 'sets.source = ?', [source]


def category_query(cat):
    """Selector state for a category name."""

    return ("JOIN category ON category.id = sets.classification_id",
            'category.name = ?', [cat])


def year_query(year):
    """Selector state for a year name."""

    return 'JOIN year ON year.id = sets.year_id', 'year.name = ?', [year]


def players_query(players):
    """Selector state for a player count name."""

    return ('JOIN nplayers ON nplayers.id = sets.nplayers_id',
            'nplayers.name = ?', [players])


def swl_query(swl_name):
    """Selector state for a software-list name."""

    return 'JOIN swl ON swl.id = sets.swllink_id', 'swl.name = ?', [swl_name]


def maker_query(connection: sqlite3.Connection, maker):
    """Selector state for a maker name, resolving clones.

    The maker's direct clone family (the resolved maker plus its direct
    ``cloneof_id`` children) is selected; deeper descendants are not included.
    """

    cursor = connection.cursor()
    try:
        # get parent if maker is clone
        cursor.execute("SELECT cloneof_id FROM maker WHERE maker.name = ?", (maker,))
        cloneof_id = cursor.fetchone()[0]
        if not cloneof_id:
            cursor.execute("SELECT id FROM maker WHERE maker.name = ?", (maker,))
            cloneof_id = cursor.fetchone()[0]
        # get all maker ids
        all_maker_ids = []
        if cloneof_id:
            cursor.execute("SELECT id FROM maker \
                WHERE cloneof_id = ? OR id = ?", (cloneof_id, cloneof_id))
            for i in cursor.fetchall():
                all_maker_ids.append(str(i['id']))
    finally:
        cursor.close()
    # set join and where
    join = 'JOIN maker ON maker.id = sets.publisher_id'
    if all_maker_ids:
        where = 'maker.id IN ({})'.format(
            ",".join("?" * len(all_maker_ids)))
        params = all_maker_ids
    else:
        where = 'maker.name = ?'
        params = [maker]
    return join, where, params
