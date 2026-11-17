"""Paths of the shared UMSA profile data (databases, filters, scan logs)."""

from dataclasses import dataclass
from os import PathLike
from pathlib import Path

PathInput = str | PathLike


@dataclass(frozen=True)
class CoreDataPaths:
    """Paths rooted in an explicitly supplied, absolute data directory."""

    data_dir: Path

    def __init__(self, data_dir: PathInput, create: bool = False) -> None:
        """Root the paths in ``data_dir``, creating it when ``create`` is set.

        Raises:
            ValueError: If ``data_dir`` is not absolute.
            NotADirectoryError: If ``data_dir`` exists but is no directory.
        """
        root = Path(data_dir)
        if not root.is_absolute():
            raise ValueError(f"data_dir must be an absolute path: {root}")

        if root.exists() and not root.is_dir():
            raise NotADirectoryError(f"data_dir is not a directory: {root}")

        if create:
            root.mkdir(parents=True, exist_ok=True)
            if not root.is_dir():
                raise NotADirectoryError(f"data_dir is not a directory: {root}")

        object.__setattr__(self, "data_dir", root)

    @property
    def umsa_db(self) -> Path:
        """Return the path of umsa.db (downloaded game metadata)."""
        return self.data_dir / "umsa.db"

    @property
    def status_db(self) -> Path:
        """Return the path of status.db (play status, emulators, history)."""
        return self.data_dir / "status.db"

    @property
    def dat_db(self) -> Path:
        """Return the path of dat.db (scanned DAT texts)."""
        return self.data_dir / "dat.db"

    @property
    def artwork_db(self) -> Path:
        """Return the path of artwork.db (scanned artwork)."""
        return self.data_dir / "artwork.db"

    @property
    def filters_dir(self) -> Path:
        """Return the folder of the old ``filter_<name>.txt`` files."""
        return self.data_dir

    @property
    def lastgames_file(self) -> Path:
        """Return the path of the old ``lastgames.txt``."""
        return self.data_dir / "lastgames.txt"

    def filter_file(self, name: str = "default") -> Path:
        """Return the path of ``filter_<name>.txt``.

        Raises:
            ValueError: If ``name`` is empty or not a plain file name.
        """

        if not name or Path(name).name != name or name in (".", ".."):
            raise ValueError("filter name must be a non-empty file name")
        return self.data_dir / f"filter_{name}.txt"

    def scan_log(self, name: str) -> Path:
        """Return the log file of scan ``name`` (``<name>scan.log``).

        Raises:
            ValueError: If ``name`` is empty or not a plain file name.
        """

        if not name or Path(name).name != name or name in (".", ".."):
            raise ValueError("scan log name must be a non-empty file name")
        return self.data_dir / f"{name}scan.log"


# Maintenance commands of the Core settings (maintenance.py).
MAINTENANCE_DELETE_COMMANDS = ("delete_umsa_db", "delete_status_db", "delete_media_db")
MAINTENANCE_COMMANDS = ("clean_status",) + MAINTENANCE_DELETE_COMMANDS


def maintenance_targets(paths: CoreDataPaths, command: str) -> list[Path]:
    """Return the database files a maintenance ``command`` deletes.

    ``clean_status`` and unknown commands delete nothing.
    """

    return {
        "delete_umsa_db": [paths.umsa_db],
        "delete_status_db": [paths.status_db],
        "delete_media_db": [paths.artwork_db, paths.dat_db],
    }.get(command, [])
