"""Game name splitting and elapsed-time formatting for the lists."""

from __future__ import annotations

import time
from re import findall, search


def split_gamename(complete_name):
    """Return ``(gamename, detail)`` of a MAME description.

    ``detail`` joins the parenthesised parts, led by a ``vX.Y`` version of
    the name.
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
    """Return a short elapsed time like ``05s``, ``3:07M``, ``2:05H``, ``4:12d``.

    With ``now=True`` ``timestamp`` is a ``%Y-%m-%d %H:%M`` time and the
    time since then is shown; otherwise it is a number of seconds. Months
    have 30 days, years 360. Invalid input gives ``''``.
    """

    if timestamp is None or timestamp == '':
        return ''

    if now is True:
        try:
            timestamp_seconds = time.mktime(time.strptime(str(timestamp), "%Y-%m-%d %H:%M"))
            elapsed = int(time.time() - timestamp_seconds)
        except Exception:
            return ''
    else:
        try:
            elapsed = int(timestamp)
        except Exception:
            return ''

    elapsed = max(elapsed, 0)

    if elapsed < 60:
        return f'{elapsed:02d}s'

    if elapsed < 3600:
        total_minutes = elapsed // 60
        seconds = elapsed % 60
        return f'{total_minutes}:{seconds:02d}M'

    if elapsed < 86400:
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        return f'{hours}:{minutes:02d}H'

    if elapsed < 30 * 86400:
        days = elapsed // 86400
        hours = (elapsed % 86400) // 3600
        return f'{days}:{hours:02d}d'

    if elapsed < 360 * 86400:
        months = elapsed // (30 * 86400)
        days = (elapsed % (30 * 86400)) // 86400
        return f'{months}:{days:02d}m'

    years = elapsed // (360 * 86400)
    months = (elapsed % (360 * 86400)) // (30 * 86400)
    return f'{years}:{months:02d}y'
