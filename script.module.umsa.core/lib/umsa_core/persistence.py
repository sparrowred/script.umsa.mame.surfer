"""Kodi-independent persistence helpers for UMSA profile files."""

from collections.abc import Iterator
from os import PathLike
from typing import Union

PathInput = Union[str, PathLike]


def load_filter(filter_path: PathInput) -> dict[str, list[str]]:
    """Load a five-line filter file, returning empty lists when it is missing."""

    filter_lists = {
        "Softwarelists": [],
        "Game Categories": [],
        "Machine Categories": [],
        "Players": [],
        "Years": [],
    }

    try:
        filter_file = open(filter_path, "r", encoding="utf-8")
    except OSError:
        return filter_lists

    with filter_file:
        lines = filter_file.readlines()

    keys = (
        "Softwarelists",
        "Game Categories",
        "Machine Categories",
        "Years",
        "Players",
    )
    for index, key in enumerate(keys):
        if lines[index].rstrip():
            filter_lists[key] = lines[index].rstrip().split(",")
    return filter_lists


def save_filter(
    filter_path: PathInput, filter_lists: dict[str, list[str]]
) -> None:
    """Save a filter using the existing five-line comma-separated format."""

    try:
        filter_file = open(filter_path, "w", encoding="utf-8")
    except OSError:
        return

    with filter_file:
        for key in (
            "Softwarelists",
            "Game Categories",
            "Machine Categories",
            "Years",
            "Players",
        ):
            values = ",".join(str(value) for value in filter_lists[key])
            filter_file.write(values + "\n")


def load_lastsaver(lastsaver_path: PathInput) -> Iterator[list[str]]:
    """Load the screensaver session list in reverse file order."""

    last_list = []
    try:
        lastsaver_file = open(lastsaver_path, "r", encoding="utf-8")
    except OSError:
        return reversed(last_list)

    with lastsaver_file:
        for line in lastsaver_file:
            last_list.append(line.strip().split(","))
    return reversed(last_list)


def load_software_list(software_list_path: PathInput) -> list[int]:
    """Load the comma-separated software IDs from a session file."""

    software_list = []
    try:
        software_file = open(software_list_path, "r", encoding="utf-8")
    except OSError:
        return software_list

    with software_file:
        line = software_file.readline()

    if line:
        software_list = [int(value) for value in line.split(",")]
    return software_list


def save_software_list(
    software_list_path: PathInput, software_list: list[int]
) -> None:
    """Save software IDs as a comma-separated line without a trailing newline."""

    try:
        software_file = open(software_list_path, "w", encoding="utf-8")
    except OSError:
        return

    with software_file:
        software_file.write(",".join(str(value) for value in software_list))
