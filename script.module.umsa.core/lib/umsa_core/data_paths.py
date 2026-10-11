"""Explicit paths for shared UMSA profile data."""

from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Union

PathInput = Union[str, PathLike]


@dataclass(frozen=True)
class CoreDataPaths:
    """Paths rooted in an explicitly supplied, absolute data directory."""

    data_dir: Path

    def __init__(self, data_dir: PathInput, create: bool = False) -> None:
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
        return self.data_dir / "umsa.db"

    @property
    def status_db(self) -> Path:
        return self.data_dir / "status.db"

    @property
    def dat_db(self) -> Path:
        return self.data_dir / "dat.db"

    @property
    def artwork_db(self) -> Path:
        return self.data_dir / "artwork.db"

    @property
    def filters_dir(self) -> Path:
        return self.data_dir

    @property
    def lastgames_file(self) -> Path:
        return self.data_dir / "lastgames.txt"

    @property
    def lastsaver_file(self) -> Path:
        return self.data_dir / "lastsaver.txt"

    def filter_file(self, name: str = "default") -> Path:
        """Return a profile-level filter file named ``filter_<name>.txt``."""

        if not name or Path(name).name != name or name in (".", ".."):
            raise ValueError("filter name must be a non-empty file name")
        return self.data_dir / f"filter_{name}.txt"
