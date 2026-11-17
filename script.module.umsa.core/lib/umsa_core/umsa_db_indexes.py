"""Indexes of umsa.db that the queries of UMSA rely on.

The download may come without indexes (a smaller archive); they are built on
the downloaded file before it replaces the live database, because umsa.db is
opened read-only everywhere else.
"""

import time

from .logging import log

# (index name, table, indexed expression) – the 30 indexes of the
# umsa.info build of 2026-11-15
UMSA_INDEXES = (
    ('ix_compilations_compilation_id', 'compilations', 'compilation_id'),
    ('ix_compilations_software_id', 'compilations', 'software_id'),
    ('ix_device_set_device_id', 'device_set', 'device_id'),
    ('ix_device_set_variant_id', 'device_set', 'variant_id'),
    ('ix_feature_set_feature_id', 'feature_set', 'feature_id'),
    ('ix_feature_set_variant_id', 'feature_set', 'variant_id'),
    ('ix_maker_cloneof_id', 'maker', 'cloneof_id'),
    ('ix_part_set_part_id', 'part_set', 'part_id'),
    ('ix_part_set_variant_id', 'part_set', 'variant_id'),
    ('ix_series_seq_series_id', 'series_seq', 'series_id'),
    ('ix_series_seq_software_id', 'series_seq', 'software_id'),
    ('ix_sets_classification_id', 'sets', 'classification_id'),
    ('ix_sets_cloneof_id', 'sets', 'cloneof_id'),
    ('ix_sets_gamename', 'sets', 'gamename COLLATE NOCASE'),
    ('ix_sets_name', 'sets', 'name'),
    ('ix_sets_nplayers_id', 'sets', 'nplayers_id'),
    ('ix_sets_publisher_id', 'sets', 'publisher_id'),
    ('ix_sets_softwarelink_id', 'sets', 'softwarelink_id'),
    ('ix_sets_source', 'sets', 'source'),
    ('ix_sets_swllink_id', 'sets', 'swllink_id'),
    ('ix_sets_year_id', 'sets', 'year_id'),
    ('ix_sharedfeature_set_sharedfeat_id', 'sharedfeature_set', 'sharedfeat_id'),
    ('ix_sharedfeature_set_variant_id', 'sharedfeature_set', 'variant_id'),
    ('ix_software_developer_id', 'software', 'developer_id'),
    ('ix_software_name', 'software', 'name'),
    ('ix_software_year_id', 'software', 'year_id'),
    ('ix_swl_name', 'swl', 'name'),
    ('ix_swl_system_id', 'swl', 'system_id'),
    ('ix_swl_status_swl_id', 'swl_status', 'swl_id'),
    ('ix_swl_status_system_id', 'swl_status', 'system_id'),
)


def _index_exists(connection, name):
    """Return whether an index ``name`` exists."""
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
        (name,)).fetchone() is not None


def _columns(connection, table):
    """Column names of ``table``; empty when the table does not exist."""

    if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,)).fetchone() is None:
        return set()
    # The table name comes from UMSA_INDEXES, never from the database.
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def build_indexes(connection, progress=None):
    """Create the missing ``UMSA_INDEXES`` on ``connection`` and analyse.

    ``progress(index, total)`` is called before every index and may raise to
    cancel; any exception rolls back and propagates. Commits once at the end.

    Returns:
        ``(built, skipped)``: names of the indexes created and of those skipped
        because their table or column does not exist.
    """

    started = time.monotonic()
    built, skipped = [], []
    total = len(UMSA_INDEXES)
    if not connection.in_transaction:
        connection.execute("BEGIN")
    try:
        for index, (name, table, expression) in enumerate(UMSA_INDEXES, 1):
            if progress is not None:
                progress(index, total)
            if _index_exists(connection, name):
                continue
            column = expression.split()[0]
            if column not in _columns(connection, table):
                log(f"umsa.db: index {name} skipped, {table}.{column} missing",
                    level='debug')
                skipped.append(name)
                continue
            # Name, table and expression come from UMSA_INDEXES only, so the
            # f-string SQL is safe.
            connection.execute(
                f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({expression})')
            built.append(name)
        if built:
            connection.execute("ANALYZE")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    elapsed_ms = (time.monotonic() - started) * 1000
    log(f"umsa.db: built {len(built)} indexes in {elapsed_ms:.0f} ms",
        level='info')
    return built, skipped
