"""One-time import of ``lastgames.txt`` and ``filter_<name>.txt`` into status.db.

Sources are validated all-or-nothing, imported together with a durable marker
and the list of files to delete, and only then deleted. Nothing else is ever
read or deleted. Works on the caller's status.db connection.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .data_paths import CoreDataPaths
from .history_repository import FILTER_CATEGORY_ORDER, HistoryRepository
from .logging import log

_DECIMAL_RE = re.compile(r"^[0-9]+$")

_FILTER_PREFIX = "filter_"
_FILTER_SUFFIX = ".txt"


@dataclass
class ImportResult:
    """Outcome of one :func:`run_legacy_import` / :func:`retry_import` call.

    ``status`` is one of ``completed``, ``completed_discards``,
    ``completed_no_source`` or ``failed``. ``discarded`` holds the file *names*
    of malformed recognized sources (contents never partially imported) and
    ``pending_cleanup`` holds the absolute paths of recognized files whose
    deletion did not succeed (or was not attempted). ``error`` carries the
    diagnostic string for ``failed``.
    """

    status: str
    discarded: list[str] = field(default_factory=list)
    pending_cleanup: list[str] = field(default_factory=list)
    error: str | None = None


def _logical_lines(content: str) -> list[str]:
    """Split ``content`` into logical lines.

    A single trailing newline (the writer's terminator) does not add an extra
    logical line; empty lines elsewhere are preserved.
    """

    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if content == "":
        return []
    lines = content.split("\n")
    if content.endswith("\n") and lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def _read_decodable(path: Path) -> str:
    """Read ``path`` as UTF-8.

    Raises:
        ValueError: For undecodable bytes (the file is discarded).
        OSError: For filesystem failures, which are no content verdict; the
            caller aborts without deleting anything.
    """

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"cannot decode {path.name}: {exc}"
        ) from exc


def _validate_ids(tokens: list[str]) -> list[str]:
    """Return the whitespace-stripped decimal tokens or raise ``ValueError``."""

    values = []
    for token in tokens:
        stripped = token.strip()
        if not stripped or _DECIMAL_RE.match(stripped) is None:
            raise ValueError(f"invalid id token {token!r}")
        values.append(stripped)
    return values


def validate_lastgames(path: Path) -> list[int]:
    """Validate a ``lastgames.txt`` file and return its software ids.

    Only the first line is data: comma-separated decimal ids; an empty file
    means no entries. A non-integer token or undecodable bytes raise
    ``ValueError`` (whole file discarded).
    """

    content = _read_decodable(path)
    lines = _logical_lines(content)
    if not lines or not lines[0].strip():
        return []
    return [int(token) for token in _validate_ids(lines[0].split(","))]


def validate_filter(path: Path) -> dict[str, list[str]]:
    """Validate a ``filter_<name>.txt`` file and return the public mapping.

    Exactly five logical lines, one per category in
    :data:`FILTER_CATEGORY_ORDER`; a non-empty line holds comma-separated
    decimal ids. Anything else raises ``ValueError`` (whole file discarded).
    """

    content = _read_decodable(path)
    lines = _logical_lines(content)
    if len(lines) != 5:
        raise ValueError(
            f"expected 5 logical lines, found {len(lines)}"
        )
    result: dict[str, list[str]] = {}
    for label, line in zip(FILTER_CATEGORY_ORDER, lines):
        if line.strip():
            result[label] = _validate_ids(line.rstrip().split(","))
        else:
            result[label] = []
    return result


def discover_legacy_paths(
    paths: CoreDataPaths,
) -> tuple[Path | None, list[Path]]:
    """Return the recognized legacy sources ``(lastgames, filter_files)``.

    Only files directly inside the profile directory count; a filter name
    must pass :meth:`CoreDataPaths.filter_file`, others are never cleanup
    candidates.
    """

    lastgames = Path(paths.lastgames_file)
    filters: list[Path] = []

    data_dir = Path(paths.data_dir)
    if data_dir.is_dir():
        for entry in sorted(data_dir.iterdir()):
            if not entry.is_file():
                continue
            name = entry.name
            if not (name.startswith(_FILTER_PREFIX) and name.endswith(_FILTER_SUFFIX)):
                continue
            filter_name = name[len(_FILTER_PREFIX):-len(_FILTER_SUFFIX)]
            try:
                paths.filter_file(filter_name)
            except ValueError:
                continue
            filters.append(entry)

    return lastgames, filters


def _delete_paths(pending: list[str]) -> tuple[list[str], list[str]]:
    """Delete ``pending`` paths, returning ``(deleted, still_pending)``.

    A path that no longer exists counts as already deleted.
    """

    deleted: list[str] = []
    still_pending: list[str] = []
    for raw in pending:
        path = Path(raw)
        try:
            if path.exists():
                path.unlink()
            deleted.append(raw)
        except OSError:
            still_pending.append(raw)
    return deleted, still_pending


def _cleanup(
    repo: HistoryRepository, marker: dict, pending: list[str]
) -> list[str]:
    """Delete recognized ``pending`` paths and update the marker durably."""

    _deleted, still_pending = _delete_paths(pending)
    if list(marker.get("pending_cleanup", [])) != still_pending:
        updated = dict(marker)
        updated["pending_cleanup"] = still_pending
        try:
            repo.record_import_marker(updated)
        except sqlite3.Error as exc:  # cleanup bookkeeping must not break startup
            log(f"UMSA legacy import: could not update pending cleanup: {exc}",
                level="warning")
    return still_pending


def _existing_recognized(
    lastgames: Path | None, filters: list[Path]
) -> list[str]:
    """Return the paths of the recognized sources that exist."""
    existing: list[str] = []
    if lastgames is not None and lastgames.exists():
        existing.append(str(lastgames))
    for path in filters:
        if path.exists():
            existing.append(str(path))
    return existing


def _record_failure(repo: HistoryRepository, error: str) -> bool:
    """Record a ``failed`` marker; return ``False`` when that write failed.

    Without a marker the next startup retries the import.
    """

    try:
        repo.record_import_marker(
            {
                "status": "failed",
                "discarded": [],
                "pending_cleanup": [],
                "error": error,
            }
        )
        return True
    except sqlite3.Error as exc:  # a lost marker just means "retry next start"
        log(f"UMSA legacy import: could not record failure: {exc}",
            level="warning")
        return False


def run_legacy_import(connection, paths: CoreDataPaths) -> ImportResult:
    """Run (or resume) the one-time legacy import.

    Discover, validate all, commit data + marker + pending-delete list in one
    transaction, then delete the files and update the pending list. A
    ``completed*`` marker only retries the cleanup; a ``failed`` marker is
    reported and left alone (see :func:`retry_import`). A filesystem failure
    while discovering or reading aborts before the transaction, deletes
    nothing and records ``failed``.
    """

    repo = HistoryRepository(connection)

    marker = repo.get_import_marker()
    if marker is not None:
        status = marker.get("status")
        if status == "failed":
            return ImportResult(
                status="failed",
                discarded=list(marker.get("discarded", [])),
                pending_cleanup=list(marker.get("pending_cleanup", [])),
                error=marker.get("error"),
            )
        if status in ("completed", "completed_discards", "completed_no_source"):
            remaining = _cleanup(
                repo, marker, list(marker.get("pending_cleanup", []))
            )
            return ImportResult(
                status=status,
                discarded=list(marker.get("discarded", [])),
                pending_cleanup=remaining,
            )

    # Discovery touches the filesystem: an enumeration error is not proof that
    # any source is malformed, so abort before validating or deleting anything.
    try:
        lastgames_path, filter_paths = discover_legacy_paths(paths)
    except OSError as exc:
        error = f"legacy discovery failed: {exc}"
        _record_failure(repo, error)
        return ImportResult(status="failed", error=error)

    # Validate every source before the transaction; a read error aborts all.
    lastgames_ids: list[int] = []
    filters: dict[str, dict[str, list[str]]] = {}
    discarded: list[str] = []
    read_errors: list[str] = []

    if lastgames_path is not None:
        try:
            if lastgames_path.exists():
                lastgames_ids = validate_lastgames(lastgames_path)
        except ValueError:
            discarded.append(lastgames_path.name)
        except OSError as exc:
            read_errors.append(f"{lastgames_path.name}: {exc}")

    for filter_path in filter_paths:
        name = filter_path.name[len(_FILTER_PREFIX):-len(_FILTER_SUFFIX)]
        try:
            if not filter_path.exists():
                continue
            filters[name] = validate_filter(filter_path)
        except ValueError:
            discarded.append(filter_path.name)
        except OSError as exc:
            read_errors.append(f"{filter_path.name}: {exc}")

    if read_errors:
        error = "unreadable legacy source(s): " + "; ".join(read_errors)
        _record_failure(repo, error)
        return ImportResult(status="failed", error=error)

    recognized = _existing_recognized(lastgames_path, filter_paths)

    if not recognized:
        marker_data = {
            "status": "completed_no_source",
            "discarded": [],
            "pending_cleanup": [],
        }
        # If even this cannot commit, the exception propagates and the next
        # GUI startup retries because no marker exists.
        repo.record_import_marker(marker_data)
        return ImportResult(status="completed_no_source")

    status = "completed_discards" if discarded else "completed"
    marker_data = {
        "status": status,
        "discarded": discarded,
        "pending_cleanup": recognized,
    }

    in_caller_transaction = connection.in_transaction
    if not in_caller_transaction:
        connection.execute("BEGIN")
    try:
        repo.save_lastgames(lastgames_ids)
        for name, selections in filters.items():
            repo.save_filter_selections(name, selections)
        repo.record_import_marker(marker_data)
        if not in_caller_transaction:
            connection.commit()
    except Exception as exc:
        if not in_caller_transaction:
            connection.rollback()
        # Separate transaction; if it fails too, the next startup retries.
        try:
            repo.record_import_marker(
                {
                    "status": "failed",
                    "discarded": discarded,
                    "pending_cleanup": recognized,
                    "error": str(exc),
                }
            )
        except sqlite3.Error as marker_exc:
            log(f"UMSA legacy import: could not record failure: {marker_exc}",
                level="warning")
        raise

    # Only after the commit: delete recognized files (valid and invalid).
    remaining = _cleanup(repo, marker_data, recognized)
    return ImportResult(
        status=status, discarded=discarded, pending_cleanup=remaining
    )


def retry_import(connection, paths: CoreDataPaths) -> ImportResult:
    """Explicitly clear a recorded ``failed`` marker and re-run the import.

    Only a ``failed`` marker is cleared; a ``completed*`` marker is left in
    place, so this never turns a cleanup-only state into a new import and never
    erases a successful terminal outcome.
    """

    repo = HistoryRepository(connection)
    marker = repo.get_import_marker()
    if marker is not None and marker.get("status") == "failed":
        repo.clear_import_marker()
    return run_legacy_import(connection, paths)
