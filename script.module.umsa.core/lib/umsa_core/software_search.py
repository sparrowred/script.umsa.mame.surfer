"""Software search over the set names of ``umsa.db``.

The search splits the term into words (:func:`tokenize`) and finds every set
whose ``sets.gamename`` contains each word, in any order. A word ``2`` ...
``10`` also matches its Roman numeral and the other way round. When the word
scan finds fewer than :data:`MAX_RESULTS` software, a second scan compares the
term without separators with the name without spaces, ``-``, ``:``, ``.`` and
``'`` (``pacman`` finds ``Pac-Man``).

The candidates are ranked in Python (exact name, name prefix, phrase, whole
words, word prefixes, substring), grouped by software (the best set of each
software wins) and cut to :data:`MAX_RESULTS` rows. Only when the term finds
nothing at all, also without the filter, every unknown word is widened by
similar words of the names (:mod:`difflib`) and the search runs once more
(:attr:`SearchResult.fuzzy`).

``umsa.db`` has no indexes and is not changed: every scan reads all sets
(about 25 ms on the full database). The active filter is passed as the
trusted clauses of :func:`umsa_core.gamelist_filter.define_filter`; every
value of the term is a bind parameter and every ``LIKE`` escapes ``\\``,
``%`` and ``_``.

The module is Kodi-independent. It never opens, closes or commits the
connection it is given (``get_connection`` like
:class:`~umsa_core.gamelist_filter.Gamelist`, ``sqlite3.Row`` rows) and owns
only short-lived cursors. Rows are plain dicts.
"""

from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field

from .game_labels import split_gamename
from .logging import log

MAX_RESULTS = 100
FUZZY_CUTOFF = 0.75
FUZZY_MATCHES = 8

_WORD = re.compile(r"[^\W_]+")
_ROMAN = {
    "2": "ii", "3": "iii", "4": "iv", "5": "v", "6": "vi",
    "7": "vii", "8": "viii", "9": "ix", "10": "x",
}
_TWINS = {**_ROMAN, **{roman: arabic for arabic, roman in _ROMAN.items()}}
_SQUASHED_NAME = (
    "replace(replace(replace(replace(replace(lower(sets.gamename), "
    "' ', ''), '-', ''), ':', ''), '.', ''), '''', '')")
_CANDIDATE_COLUMNS = "sets.id, sets.gamename, sets.softwarelink_id, sets.cloneof_id"


@dataclass
class SearchResult:
    """Outcome of one software search."""

    rows: list = field(default_factory=list)  # at most MAX_RESULTS dicts, best first
    count: int = 0        # all matching software
    fuzzy: bool = False   # True: nothing matched, similar words were used


def tokenize(term) -> list:
    """Words of ``term``: casefolded runs of letters and digits."""

    return _WORD.findall(term.casefold())


def _escape(text):
    """``text`` for a ``LIKE ... ESCAPE '\\'`` pattern."""

    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _base_variants(word):
    """The word and its Roman/Arabic twin."""

    twin = _TWINS.get(word)
    return (word, twin) if twin else (word,)


def _filter_sql(filter_join, filter_where):
    """The filter condition, or ``''`` when join or where is empty."""

    if filter_join and filter_where:
        return "sets.id IN (SELECT sets.id FROM sets {} WHERE {})".format(
            " ".join(filter_join), " AND ".join(filter_where))
    return ""


def _rank(words, variants, name):
    """Rank 0 (best) to 5 of a set name for the term (see the plan S-1)."""

    name_words = tokenize(split_gamename(name)[0])
    joined = " ".join(name_words)
    phrase = " ".join(words)
    squashed_name = joined.replace(" ", "")
    squashed_phrase = phrase.replace(" ", "")
    if joined == phrase or squashed_name == squashed_phrase:
        rank = 0
    elif joined.startswith(phrase + " ") or squashed_name.startswith(squashed_phrase):
        rank = 1
    elif f" {phrase} " in f" {joined} ":
        rank = 2
    elif all(any(v in name_words for v in options) for options in variants):
        rank = 3
    elif all(any(n.startswith(v) for v in options for n in name_words)
             for options in variants):
        rank = 4
    else:
        rank = 5
    return rank, len(name_words)


class SoftwareSearch:
    """Search over ``sets.gamename``; ``get_connection`` like ``Gamelist``."""

    def __init__(self, get_connection):
        self._get_connection = get_connection
        self._vocabulary_cache = None
        self._vocabulary_connection = None

    def search(self, term, filter_join=(), filter_where=(),
               filter_where_params=()) -> SearchResult:
        """Search software whose set names contain every word of ``term``.

        ``filter_*`` are the clauses of the active filter (empty: no filter).
        """

        words = tokenize(term)
        if not words:
            return SearchResult([], 0)
        start = time.time()
        connection = self._get_connection()
        filter_sql = _filter_sql(filter_join, filter_where)
        filter_params = list(filter_where_params) if filter_sql else []
        variants = [_base_variants(word) for word in words]

        candidates = self._word_scan(connection, variants, filter_sql, filter_params)
        squashed = "".join(words)
        if (len(squashed) >= 3
                and len(self._software_ids(candidates)) < MAX_RESULTS):
            candidates.update(self._squashed_scan(
                connection, squashed, filter_sql, filter_params))
        fuzzy = False
        if not candidates:
            if filter_sql and self._word_scan(connection, variants, "", []):
                log("UMSA search: the filter hides every hit", level='debug')
                return SearchResult([], 0)
            fuzzy_variants = self._fuzzy_variants(connection, words, variants)
            if fuzzy_variants is None:
                return SearchResult([], 0)
            variants = fuzzy_variants
            candidates = self._word_scan(
                connection, variants, filter_sql, filter_params)
            if not candidates:
                return SearchResult([], 0)
            fuzzy = True

        result = self._result(connection, words, variants, candidates, fuzzy)
        log(f"UMSA search: {term!r} {result.count} software, fuzzy={fuzzy}, "
            f"{(time.time() - start) * 1000:.0f}ms", level='debug')
        return result

    # scans ---------------------------------------------------------------

    @staticmethod
    def _run_candidates(connection, where, params):
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"SELECT {_CANDIDATE_COLUMNS} FROM sets WHERE {where}", params)
            return {row['id']: dict(row) for row in cursor.fetchall()}
        finally:
            cursor.close()

    def _word_scan(self, connection, variants, filter_sql, filter_params):
        """Sets that contain every word (one of its variants)."""

        clauses, params = [], []
        for options in variants:
            clauses.append("(" + " OR ".join(
                "sets.gamename LIKE ? ESCAPE '\\'" for _ in options) + ")")
            params.extend(f"%{_escape(v)}%" for v in options)
        if filter_sql:
            clauses.append(filter_sql)
            params.extend(filter_params)
        return self._run_candidates(connection, " AND ".join(clauses), params)

    def _squashed_scan(self, connection, squashed, filter_sql, filter_params):
        """Sets whose name without separators contains ``squashed``."""

        where = f"{_SQUASHED_NAME} LIKE ? ESCAPE '\\'"
        params = [f"%{_escape(squashed)}%"]
        if filter_sql:
            where += f" AND {filter_sql}"
            params.extend(filter_params)
        return self._run_candidates(connection, where, params)

    @staticmethod
    def _software_ids(candidates):
        return {row['softwarelink_id'] for row in candidates.values()
                if row['softwarelink_id'] is not None}

    # fuzzy ---------------------------------------------------------------

    def _vocabulary(self, connection):
        """Sorted words of all set names, read once per connection object."""

        if self._vocabulary_connection is not connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT gamename FROM sets")
                vocabulary = set()
                for row in cursor.fetchall():
                    vocabulary.update(tokenize(row['gamename'] or ""))
            finally:
                cursor.close()
            self._vocabulary_cache = sorted(vocabulary)
            self._vocabulary_connection = connection
        return self._vocabulary_cache

    def _fuzzy_variants(self, connection, words, variants):
        """Variants widened by similar words; ``None`` when nothing new."""

        vocabulary = self._vocabulary(connection)
        known = set(vocabulary)
        widened, changed = [], False
        for word, options in zip(words, variants):
            if word in known:
                widened.append(options)
                continue
            similar = [match for match in difflib.get_close_matches(
                word, vocabulary, n=FUZZY_MATCHES, cutoff=FUZZY_CUTOFF)
                if match not in options]
            if similar:
                changed = True
            widened.append(tuple(options) + tuple(similar))
        return widened if changed else None

    # ranking and details -------------------------------------------------

    def _result(self, connection, words, variants, candidates, fuzzy):
        best = {}
        for row in candidates.values():
            software_id = row['softwarelink_id']
            if software_id is None:
                continue
            rank, word_count = _rank(words, variants, row['gamename'])
            key = (rank, 0 if row['cloneof_id'] is None else 1, word_count,
                   row['gamename'].casefold(), row['id'])
            if software_id not in best or key < best[software_id][0]:
                best[software_id] = (key, row)
        ordered = sorted(best.items(), key=lambda item: item[1][0])[:MAX_RESULTS]
        details, series = self._details(connection, [sid for sid, _ in ordered])
        rows = []
        for software_id, (_key, candidate) in ordered:
            detail = details.get(software_id)
            if detail is None:
                log(f"UMSA search: software {software_id} missing, dropped",
                    level='debug')
                continue
            series_id, series_name = series.get(software_id, (None, None))
            rows.append({
                'id': software_id,
                'name': detail['name'],
                'year': detail['year'] or '',
                'maker': detail['maker'] or '',
                'set_id': candidate['id'],
                'set_name': candidate['gamename'],
                'series_id': series_id,
                'series_name': series_name,
            })
        return SearchResult(rows, len(best), fuzzy)

    @staticmethod
    def _details(connection, software_ids):
        """Name/year/maker and the first series of each software id."""

        if not software_ids:
            return {}, {}
        marks = ",".join("?" * len(software_ids))
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT software.id, software.name, year.name AS year, "
                "maker.name AS maker FROM software "
                "LEFT JOIN year ON year.id = software.year_id "
                "LEFT JOIN maker ON maker.id = software.developer_id "
                f"WHERE software.id IN ({marks})", software_ids)
            details = {row['id']: dict(row) for row in cursor.fetchall()}
            cursor.execute(
                "SELECT series_seq.software_id, series.id AS series_id, "
                "series.name AS series_name "
                "FROM series_seq JOIN series ON series.id = series_seq.series_id "
                f"WHERE series_seq.software_id IN ({marks}) "
                "ORDER BY series_seq.id", software_ids)
            series = {}
            for row in cursor.fetchall():
                series.setdefault(
                    row['software_id'], (row['series_id'], row['series_name']))
        finally:
            cursor.close()
        return details, series
