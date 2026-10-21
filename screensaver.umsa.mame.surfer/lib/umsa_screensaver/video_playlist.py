"""Playlist items of the video screensaver.

The module owns the metadata contract of a queued video: the software id
travels in the ``Votes`` label (context handoff to the frontend) and the
set id travels as ``umsa_set_id`` unique id (history recording), which
exists only from Kodi 20 on.
"""

import xbmc
from umsa_core.history_repository import normalize_set_id

# Unique-ID type label carrying the UMSA set id (sets.id) with a video.
# InfoTagVideo.setUniqueID()/getUniqueID() exist only from Kodi 20
# (@python_v20); every use below is capability-guarded, so on Kodi 19 the
# value simply never travels with the item and video history is not
# recorded (logged), while the Votes-based software-id handoff keeps working.
SET_ID_UNIQUE_TYPE = 'umsa_set_id'


def attach_set_id(video_item, set_id):
    """Attach the UMSA set id to a playlist item as ``umsa_set_id``.

    Argument order matters: the official API is
    ``setUniqueID(uniqueid, type)`` - the id value first, the type label
    second. Returns ``True`` when the value was written, ``False`` when the
    runtime lacks the Kodi 20 unique-ID API, the id is invalid or the write
    failed (each case is logged; the caller is never interrupted).
    """

    try:
        normalized = normalize_set_id(set_id)
    except ValueError:
        xbmc.log(f"UMSA SSaver: not attaching invalid set id {set_id!r}", xbmc.LOGWARNING)
        return False
    try:
        video_tag = video_item.getVideoInfoTag()
    except (AttributeError, RuntimeError) as error:
        xbmc.log(f"UMSA SSaver: no video info tag for set id: {error}", xbmc.LOGDEBUG)
        return False
    if video_tag is None or not hasattr(video_tag, 'setUniqueID'):
        xbmc.log(
            "UMSA SSaver: Kodi has no InfoTagVideo.setUniqueID (Kodi < 20); "
            "screensaver video history recording is unavailable",
            xbmc.LOGDEBUG)
        return False
    try:
        video_tag.setUniqueID(str(normalized), SET_ID_UNIQUE_TYPE)
    except (TypeError, ValueError, RuntimeError) as error:
        xbmc.log(f"UMSA SSaver: could not attach umsa_set_id {normalized}: {error}", xbmc.LOGWARNING)
        return False
    return True


def read_set_id(video_tag):
    """Return the positive ``set_id`` carried by ``video_tag``, or ``None``.

    ``None`` means "no recordable set id": the runtime has no
    ``InfoTagVideo.getUniqueID`` (Kodi < 20), the ``umsa_set_id`` value is
    absent, or it does not validate as a positive decimal ``sets.id`` (the
    latter is logged). The value is never replaced by any other id.
    """

    if video_tag is None or not hasattr(video_tag, 'getUniqueID'):
        return None
    try:
        raw = video_tag.getUniqueID(SET_ID_UNIQUE_TYPE)
    except (TypeError, ValueError, RuntimeError) as error:
        xbmc.log(f"UMSA SSaver: could not read umsa_set_id: {error}", xbmc.LOGWARNING)
        return None
    if raw is None or raw == '':
        return None
    try:
        return normalize_set_id(raw)
    except ValueError:
        xbmc.log(f"UMSA SSaver: ignoring invalid umsa_set_id {raw!r}", xbmc.LOGWARNING)
        return None


def read_software_id(video_tag):
    """Return the software id carried in the video ``Votes`` label, or ``None``.

    ``Votes`` keeps holding the software id (``sets.softwarelink_id``) exactly
    as the context-menu handoff reads it today; it is never repurposed for the
    set id.
    """

    if video_tag is None or not hasattr(video_tag, 'getVotes'):
        return None
    try:
        return int(video_tag.getVotes())
    except (TypeError, ValueError):
        return None


def build_video_item(art, machine_pic, snapshot, attach, gui):
    """Return the playlist item of a video.

    The item carries the title, the genre, the machine picture as trailer
    and the left picture as director; the software id travels in ``Votes``
    and the set id as unique id.
    """

    video_item = gui.ListItem(art['gamename'])
    video_item.setInfo('video', {
        'Title': art['gamename'],
        'Genre': "{}, {}".format(art['year'], art['maker']),
        'Trailer': machine_pic,
        'Director': snapshot,
        'Votes': art['s_id']})
    # carry the set id alongside the Votes software id so the playback
    # callback can record history; degrades to a logged no-op on Kodi < 20
    attach(video_item, art.get('id'))
    return video_item
