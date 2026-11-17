"""Plain-text log file of a scan (for example ``datscan.log``).

Lines are collected in memory and written to ``<path>.part``, then moved onto
``path``, so a reader never sees a half-written file and a failed write keeps
the previous log.
"""

from __future__ import annotations

import os
from datetime import datetime
from os import PathLike

from .logging import log


def _one_line(text) -> str:
    """Return ``text`` as one line (line breaks become spaces)."""

    return " ".join(str(text).splitlines())


class ScanLog:
    """Lines of one scan log, written atomically by :meth:`write`.

    Args:
        path: Target file.
        title: First line of the log, followed by the current local time
            (``"<title> - YYYY-MM-DD HH:MM:SS"``).
    """

    def __init__(self, path: str | PathLike, title: str) -> None:
        self.path = os.fspath(path)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._lines = [f"{_one_line(title)} - {stamp}"]

    def line(self, text="") -> None:
        """Add one line; line breaks inside ``text`` become spaces."""

        self._lines.append(_one_line(text))

    def section(self, heading, lines=()) -> None:
        """Add an empty line, ``== heading ==`` and then ``lines``."""

        self._lines.append("")
        self._lines.append(f"== {_one_line(heading)} ==")
        for text in lines:
            self.line(text)

    def write(self) -> bool:
        """Write the log (UTF-8) atomically; return ``False`` on failure.

        A failure is logged as an error and keeps an existing file at
        ``path``; the ``.part`` file is removed.
        """

        part = self.path + ".part"
        try:
            with open(part, "w", encoding="utf-8", newline="\n") as fobj:
                for text in self._lines:
                    fobj.write(text)
                    fobj.write("\n")
            os.replace(part, self.path)
            return True
        except (OSError, ValueError) as exc:  # ValueError: text not encodable
            log(f"UMSA scan log: cannot write '{self.path}': {exc}",
                level='error')
            try:
                if os.path.exists(part):
                    os.remove(part)
            except OSError:
                pass
            return False
