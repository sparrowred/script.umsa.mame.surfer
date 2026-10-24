"""Pure game-label and formatting helpers."""

from __future__ import annotations

from re import findall, search
import time


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
    """Format elapsed time."""

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

    if elapsed < 0:
        elapsed = 0

    # Match legacy format used by existing tests
    if now is False or now is None:
        minute = divmod(elapsed, 60)[0]
        hour, minute_rem = divmod(minute, 60)
        return "%d:%02d" % (hour, minute_rem)

    if elapsed < 60:
        return f'0:{elapsed:02d}'

    if elapsed < 3600:
        total_minutes = elapsed // 60
        seconds = elapsed % 60
        hours = total_minutes // 60
        minutes = total_minutes % 60
        if hours > 0:
            return f'{hours}:{minutes:02d}'
        return f'{total_minutes}:{seconds:02d}'

    if elapsed < 86400:
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        return f'{hours}:{minutes:02d}'

    if elapsed < 30 * 86400:
        days = elapsed // 86400
        hours = (elapsed % 86400) // 3600
        return f'{days}:{hours:02d}'

    if elapsed < 365 * 86400:
        months = elapsed // (30 * 86400)
        hours = (elapsed % (30 * 86400)) // 3600
        return f'{months}:{hours:02d}'

    years = elapsed // (365 * 86400)
    months = (elapsed % (365 * 86400)) // (30 * 86400)
    return f'{years}:{months:02d}'
