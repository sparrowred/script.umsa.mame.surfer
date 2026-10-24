"""Pure game-label and formatting helpers."""

from __future__ import annotations

from re import findall, search


def split_gamename(complete_name):
    """Split the complete name of a MAME description into the name and details plus version.

    Return: gamename, detail
    """

    gamename, detail, details = '', '', []
    for name, detail in findall(r'(.*?) (\([^(]*?\))', complete_name):
        gamename += name.strip()
        details.append(detail[1:-1])
    detail = ', '.join(details)
    if not gamename:
        gamename = complete_name

    version = search(r'([vV]\d+\.\d+)', gamename)
    if version:
        if not detail:
            detail = version.group()
        else:
            detail = f'{version.group()} {detail}'

    return gamename, detail


def make_time_nice(timestamp, now=None):
    """Return a human-readable age string for a timestamp."""

    if timestamp is None:
        return ''
    if now is None:
        import time

        now = time.time()
    try:
        seconds = int(now) - int(timestamp)
    except Exception:
        return ''
    if seconds < 60:
        return str(seconds) + ' s'
    if seconds < 3600:
        minutes = seconds // 60
        return str(minutes) + ' min'
    if seconds < 86400:
        hours = seconds // 3600
        return str(hours) + ' h'
    days = seconds // 86400
    return str(days) + ' d'
