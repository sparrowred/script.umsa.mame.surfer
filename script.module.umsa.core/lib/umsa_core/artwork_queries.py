"""Artwork queries across ``umsa.db`` and the attached ``artwork.db``.

Everything here joins the scanned artwork (``art.art_set``, the ``art``
schema attached to the ``umsa.db`` connection) with the game tables
(``sets``/``swl``/``software``), so it is neither artwork-table CRUD
(:mod:`umsa_core.artwork_repository`) nor a plain game lookup
(:mod:`umsa_core.game_repository`):

- random artwork for the screensaver, following the active filter of the
  :class:`~umsa_core.gamelist_filter.Gamelist`;
- artwork of a set with the clone/parent fallback (machine cabinets, left
  picture of the screensaver);
- the preview picture of a software.

Artwork locations are rows with ``source``, ``root_key``, ``relative_path``
and ``archive_member``; :func:`umsa_core.artwork.resolve_artwork_path` turns
them into paths.

The module is Kodi-independent. :class:`ArtworkQueries` never opens, closes
or commits a connection; ``DBMod`` owns one as ``DBMod.art_queries``.
"""

import random
import sqlite3
from array import array

from .artwork import resolve_artwork_path, root_key_for_path
from .artwork_repository import ArtworkRepository
from .game_repository import GameRepository
from .logging import log

# kept candidate lists of get_random_art (artwork types x filter)
_RANDOM_ART_CACHE_SIZE = 8

_ART_COLUMNS = ("id, source, root_key, scan_unit, type, extension, "
                "relative_path, archive_member")


class ArtworkQueries:
    """Artwork lookups on the ``umsa.db`` connection with attached ``art``.

    ``get_connection`` returns the current connection (``sqlite3.Row`` rows)
    and is asked on every call, because ``DBMod.open_db`` replaces the
    connection after a database update. ``gamelist`` supplies the active
    filter, ``get_nonmame`` the configured roots of the other collections
    (``{'exodos': ..., 'gb64': ...}`` or ``None``; the settings can change
    them while the object lives).
    """

    def __init__(self, get_connection, gamelist, get_nonmame):
        self._get_connection = get_connection
        self._gamelist = gamelist
        self._get_nonmame = get_nonmame
        # candidate ids of get_random_art, see _random_art_candidates
        self._random_art_cache = {}
        self._random_art_token = None
        # (source, root_key) pairs the random selection may pick from;
        # None = no root filter, see set_source_roots
        self._root_filter = None

    def _execute(self, statement, params=()):
        return self._get_connection().execute(statement, params)

    def set_source_roots(self, source_roots):
        """Restrict the random selection to the configured artwork roots.

        ``source_roots`` maps an artwork source to its configured folder
        (as for :func:`umsa_core.artwork.resolve_artwork_path`). Rows of a
        moved folder (other ``root_key``) or of a source without a folder
        can never be resolved, so ``has_artwork`` and ``get_random_art``
        skip them. ``None`` removes the restriction.
        """

        if source_roots is None:
            self._root_filter = None
            return
        self._root_filter = tuple(sorted(
            (source, root_key_for_path(path))
            for source, path in source_roots.items() if path))

    def _root_clause(self):
        """SQL condition and parameters of the root restriction, or None.

        Rows without a root key of a configured source are kept: the
        resolver accepts them too.
        """

        if self._root_filter is None:
            return None
        if not self._root_filter:
            return "0", []
        pairs = " OR ".join(
            "(art.source = ? AND art.root_key IN ('', ?))" for _ in self._root_filter)
        params = [value for pair in self._root_filter for value in pair]
        return f"({pairs})", params

    def _artwork_conditions(self, types_in, types, filtered):
        """WHERE clause and parameters shared by the random artwork queries."""

        gamelist = self._gamelist
        conditions = [f"art.type IN ({types_in})"]
        params = list(types)
        if filtered:
            conditions.extend(gamelist.filter_where)
            params.extend(gamelist.filter_where_params)
        root = self._root_clause()
        if root is not None:
            conditions.append(root[0])
            params.extend(root[1])
        return " AND ".join(conditions), params

    def has_artwork(self, art_types):
        """Return whether any artwork of the given types can be selected.

        The check uses the same joined tables, the same artwork database
        (``art.art_set``) and the same active filter as
        :meth:`get_random_art`, so a positive answer means the random
        selection can really return a row. It stops at the first hit and
        never loads a whole artwork collection.

        ``art_types`` may be empty (the answer is then ``False``) and may
        contain duplicates.
        """

        types = list(dict.fromkeys(art_types or []))
        if not types:
            return False
        types_in = ",".join("?" * len(types))
        gamelist = self._gamelist

        # with the active filter first, like the random selection
        # (an empty filter would produce an invalid "AND" clause)
        if gamelist.use_filter and gamelist.filter_where:
            where, params = self._artwork_conditions(types_in, types, True)
            statement = (
                "SELECT 1 FROM art.art_set art JOIN sets ON sets.id = art.id "
                f"{' '.join(gamelist.filter_join)} WHERE {where} LIMIT 1")
            if self._execute(statement, params).fetchone():
                return True

        # and without filter if the filter found nothing
        where, params = self._artwork_conditions(types_in, types, False)
        statement = ("SELECT 1 FROM art.art_set art JOIN sets ON sets.id = art.id "
                     f"WHERE {where} LIMIT 1")
        return bool(self._execute(statement, params).fetchone())

    def get_random_art(self, art_types):
        """Get 1 random artwork

        TODO
        - check where get_random_art is used and if machine, left is always needed
           if not make optional
        - get machine pic, see screensaver/get_machine_pic
        - get bottom left, type video/snap/title = cover/flyer
                           type cover/flyer = snap
          needs fetch info for snap from db for aspect ratio

        Takes a list of artwork types
        Returns a dictonary with informations or None if nothing is found

        The row carries the artwork location (``source``, ``root_key``,
        ``relative_path``, ``archive_member``); callers resolve it with
        :func:`umsa_core.artwork.resolve_artwork_path`. The additional left
        image of the eXoDOS/GB64 sets is resolved here for the screensaver.
        """

        rand_art = self._pick_random_art(art_types)
        if not rand_art:
            log(f"UMSA database get_random art: no artwork for {art_types}", level='warning')
            return None
        end_result = {}
        end_result.update(rand_art)

        # get needed infos
        art_info = self._execute(
            "SELECT sets.name, swl.name as swl_name, gamename, \
                    year.name as year, maker.name as maker, softwarelink_id as s_id, \
                    swl.system_id as swl_system_id, cat.name as category, cat.flag as is_machine \
             FROM sets, swl, year, maker, category cat \
             WHERE sets.id = ? \
             AND sets.year_id = year.id AND sets.publisher_id = maker.id \
             AND sets.swllink_id = swl.id AND sets.classification_id = cat.id",
            (rand_art['id'],)
        ).fetchone()
        end_result.update(art_info)
        games = GameRepository(self._get_connection())
        end_result.update(
            {'machine_name': games.get_machine_name(end_result['swl_system_id'])[0]})

        # snap/title: get display
        if 'snap' in art_types or 'titles' in art_types:
            if end_result['swl_name'] == 'mame':
                machine = rand_art['id']
            else:
                machine = end_result['swl_system_id']
            art_displayinfo = self._execute(
                "SELECT display_rotation, display_type \
                FROM sets WHERE id = ?", (machine,)
            ).fetchone()
            end_result.update(art_displayinfo)
        else:
            end_result.update({'display_rotation': 0, 'display_type': ''})

        # get left pic if swl is nonmame
        if (end_result['swl_name'] == 'exodos') or (end_result['swl_name'].startswith('gb64_')):
            if end_result['type'] in ('snap', 'titles', 'videosnaps'):
                lefttype = 'covers'
            else:
                lefttype = 'snap'
            artwork = ArtworkRepository(self._get_connection(), schema="art")
            leftpic = artwork.get_artwork_record_for_set_type(
                rand_art['id'], lefttype
            )
            if leftpic:
                left_path = resolve_artwork_path(
                    leftpic, end_result, self._art_source_roots())
                if left_path:
                    end_result.update({'left_pic': left_path})

        return end_result

    def _random_art_candidates(self, art_types, filtered):
        """Return the ``art_id`` values ``get_random_art`` may pick from.

        The ids of one artwork type selection (with or without the active
        filter) are read once and kept, so a random pick no longer sorts the
        whole joined artwork table (``ORDER BY RANDOM()``) for every picture.

        The lists are dropped when ``artwork.db`` changes
        (``PRAGMA art.data_version`` moves as soon as another connection
        commits, e.g. an artwork scan of the frontend) and when ``open_db``
        replaced the ``umsa.db`` connection. The filter clauses are part of
        the key, so a changed filter gets its own list.
        """

        connection = self._get_connection()
        token = (connection,
                 connection.execute("PRAGMA art.data_version").fetchone()[0])
        if self._random_art_token != token:
            self._random_art_cache = {}
            self._random_art_token = token
        cache = self._random_art_cache

        gamelist = self._gamelist
        types = tuple(sorted(set(art_types)))
        signature = None
        if filtered:
            signature = (tuple(gamelist.filter_join), tuple(gamelist.filter_where),
                         tuple(gamelist.filter_where_params))
        # the root restriction is part of the key: other roots, other ids
        key = (types, signature, self._root_filter)
        if key in cache:
            return cache[key]

        types_in = ",".join("?" * len(types))
        where, params = self._artwork_conditions(types_in, types, filtered)
        join = " ".join(gamelist.filter_join) if filtered else ""
        statement = ("SELECT art.art_id FROM art.art_set art "
                     f"JOIN sets ON sets.id = art.id {join} WHERE {where}")
        ids = array('q', (row[0] for row in connection.execute(statement, params)))

        if len(cache) >= _RANDOM_ART_CACHE_SIZE:
            cache.clear()
        cache[key] = ids
        return ids

    def _pick_random_art(self, art_types):
        """Return one random artwork row of the given types, or ``None``.

        Picks with the active filter first and without it when the filter
        leaves nothing. A candidate whose row has gone meanwhile drops the
        candidate lists and is retried once.
        """

        if not art_types:
            return None

        # an empty filter would produce an invalid "AND" clause
        filtered = bool(self._gamelist.use_filter and self._gamelist.filter_where)
        for _attempt in range(2):
            ids = None
            if filtered:
                ids = self._random_art_candidates(art_types, True)
            if not ids:
                ids = self._random_art_candidates(art_types, False)
            if not ids:
                return None
            rand_art = self._execute(
                "SELECT sets.id, art.source, art.root_key, art.scan_unit, \
                        art.type, art.extension, art.relative_path, \
                        art.archive_member \
                 FROM art.art_set art JOIN sets ON sets.id = art.id \
                 WHERE art.art_id = ?", (random.choice(ids),)).fetchone()
            if rand_art:
                return rand_art
            self._random_art_cache = {}
        return None

    def _art_source_roots(self):
        """Return configured roots for the non-MAME artwork sources.

        ``get_random_art`` only resolves the additional left image, which is
        picked from the eXoDOS/GB64 sources whose roots are held here.
        """

        nonmame = self._get_nonmame() or {}
        return {
            'exodos': nonmame.get('exodos', ''),
            'gb64': nonmame.get('gb64', ''),
        }

    def get_artwork_by_software_id(self, software_id, artwork, source_roots=None):
        """get artwork by software id

        fetch given artwork type and all machines for a software id.

        Returns a two element list ``[art_path, machines]`` where ``art_path``
        is the fully resolved location of a random matching artwork (empty
        string when none is found) and ``machines`` is a comma separated list
        of machine abbreviations.
        """

        all_machines = [
            row[0] for row in self._execute(
                "SELECT DISTINCT system_abbr FROM swl, sets \
                   WHERE sets.softwarelink_id = ? AND sets.swllink_id = swl.id",
                (software_id,)
            ).fetchall()]

        snap_info = self._execute(
            "SELECT sets.name, swl.name as swl_name, \
                   art.source, art.root_key, art.scan_unit, \
                   art.type, art.extension, art.relative_path, \
                   art.archive_member \
             FROM sets, swl, art.art_set art \
             WHERE sets.softwarelink_id = ? \
             AND swl.id = sets.swllink_id \
             AND art.id = sets.id \
             AND art.type = ? \
             ORDER BY RANDOM() LIMIT 1",
            (software_id, artwork)
        ).fetchone()

        art_path = ''
        if snap_info:
            art = dict(snap_info)
            art_path = resolve_artwork_path(art, art, source_roots or {})

        return [art_path, ', '.join(all_machines)]

    def _artwork_rows_for_ids(self, set_ids, art_type):
        """Return the ``art_set`` rows of ``art_type`` for the given set ids."""

        ids = sorted(set(set_ids))
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        # "+type" keeps SQLite on the id index: the type index would walk
        # every row of a big artwork type
        rows = self._execute(
            f"SELECT {_ART_COLUMNS} FROM art.art_set \
             WHERE id IN ({placeholders}) AND +type = ?",
            (*ids, art_type),
        ).fetchall()
        return [dict(row) for row in rows]

    def _family_artwork(self, sets, art_type):
        """Return ``{key: [art rows]}`` for sets with clone/parent fallback.

        ``sets`` holds ``(key, set id, set name, cloneof_id)`` tuples. The
        rows of a key are ordered: the set itself, its parent, the other
        clones of the family (by name); within each step own artwork comes
        first. Every row carries ``set_name``, the set the artwork belongs
        to. umsa.db keeps clones in the software list and software of their
        parent and has no clones of clones, so the family is the parent and
        all its clones. Families are only looked up for sets without own
        artwork of that type.
        """

        def source_rank(row):
            return 0 if row["source"] == "own_artwork" else 1

        own = {}
        for row in self._artwork_rows_for_ids([s[1] for s in sets], art_type):
            own.setdefault(row["id"], []).append(row)

        result = {}
        missing = []
        for key, set_id, set_name, cloneof_id in sets:
            rows = sorted(own.get(set_id, []), key=source_rank)
            if rows:
                result[key] = [dict(row, set_name=set_name) for row in rows]
            else:
                missing.append((key, set_id, cloneof_id))
        if not missing:
            return result

        heads = sorted({cloneof_id or set_id for _key, set_id, cloneof_id in missing})
        placeholders = ",".join("?" * len(heads))
        members = {}
        names = {}
        for member_id, member_name, member_parent in self._execute(
                f"SELECT id, name, cloneof_id FROM sets \
                 WHERE id IN ({placeholders}) OR cloneof_id IN ({placeholders})",
                (*heads, *heads)).fetchall():
            names[member_id] = member_name
            members.setdefault(member_parent or member_id, []).append(member_id)

        art = {}
        for row in self._artwork_rows_for_ids(names, art_type):
            art.setdefault(row["id"], []).append(row)

        for key, set_id, cloneof_id in missing:
            head = cloneof_id or set_id
            family = [m for m in members.get(head, []) if m != set_id]
            ordered = sorted(
                family, key=lambda m: (0 if m == head else 1, names[m]))
            rows = [
                dict(row, set_name=names[member])
                for member in ordered
                for row in sorted(art.get(member, []), key=source_rank)
            ]
            if rows:
                result[key] = rows
        return result

    def get_machine_cabinets(self, machine_names):
        """Return ``{machine set name: art row}`` of scanned cabinets.

        Looks up the ``cabinets`` artwork of the MAME sets named in
        ``machine_names``: the machine itself, else its parent, else another
        clone of the family; own artwork wins over progettosnaps on each
        step. ``set_name`` of a row names the set the picture belongs to.
        Machines without a scanned cabinet are missing from the result, so
        callers fall back to the fixed progettosnaps path. Never raises.
        """

        names = sorted({name for name in machine_names if name})
        if not names:
            return {}
        placeholders = ",".join("?" * len(names))
        try:
            rows = self._execute(
                f"SELECT sets.name, sets.id, sets.cloneof_id \
                 FROM sets JOIN swl ON swl.id = sets.swllink_id \
                 WHERE swl.name = 'mame' AND sets.name IN ({placeholders})",
                names,
            ).fetchall()
            sets = [(row[0], row[1], row[0], row[2]) for row in rows]
            family = self._family_artwork(sets, "cabinets")
        except sqlite3.Error as error:
            log(f"UMSA database get_machine_cabinets: {error}", level='warning')
            return {}
        return {name: rows[0] for name, rows in family.items()}

    def get_set_artwork(self, set_id, art_type, source_roots=None):
        """Return the resolved path of an artwork of a set, ``''`` if none.

        Uses the clone/parent fallback of ``_family_artwork``; rows whose
        source root no longer matches the configuration are skipped. Never
        raises.
        """

        try:
            row = self._execute(
                "SELECT sets.name, sets.cloneof_id, swl.name \
                 FROM sets JOIN swl ON swl.id = sets.swllink_id WHERE sets.id = ?",
                (set_id,),
            ).fetchone()
            if row is None:
                return ''
            set_name, cloneof_id, swl_name = row[0], row[1], row[2]
            family = self._family_artwork(
                [(set_id, set_id, set_name, cloneof_id)], art_type)
        except sqlite3.Error as error:
            log(f"UMSA database get_set_artwork: {error}", level='warning')
            return ''
        for art in family.get(set_id, []):
            path = resolve_artwork_path(
                art, {"name": art["set_name"], "swl_name": swl_name}, source_roots or {})
            if path:
                return path
        return ''
