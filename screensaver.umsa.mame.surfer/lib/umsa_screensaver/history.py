"""Recording of the screensaver display history.

The screensaver writes the shown set into the shared Core history: once
per completed artwork render and once per started video. A missing or
invalid set id is ignored and a failing database write is logged, never
breaking the screensaver.
"""

from umsa_core.history_repository import normalize_set_id

IMAGE_LOG_PREFIX = "UMSA SSaver"
VIDEO_LOG_PREFIX = "UMSA SSaver Player"


def record_display(ggdb, art, kodi, log_prefix=IMAGE_LOG_PREFIX):
    """Record the displayed set in the shared screensaver history.

    Called once per completed cross/slide/wall render, after the
    display-success boundary and before the wait loop. A missing or
    invalid ``set_id`` is ignored; database failures are logged and never
    allowed to break rendering. Returns ``True`` only when the history
    write succeeded.
    """

    set_id = art.get('id') if art else None
    software_id = art.get('s_id') if art else None
    try:
        normalized_set_id = normalize_set_id(set_id)
    except ValueError:
        kodi.log(
            f"{log_prefix}: no valid set id for history: {set_id!r}",
            kodi.LOGWARNING)
        return False
    try:
        ggdb.record_screensaver_display(
            normalized_set_id, software_id)
    except Exception as error:  # noqa: BLE001 - history must never break rendering
        kodi.log(
            f"{log_prefix}: history recording failed: {error}",
            kodi.LOGWARNING)
        return False
    kodi.log(
        f"{log_prefix}: recorded screensaver history for set {normalized_set_id}",
        kodi.LOGDEBUG)
    return True


def record_video_display(ggdb, video_tag, kodi, read_set_id, read_software_id,
                         log_prefix=VIDEO_LOG_PREFIX):
    """Record the video that is played in the video screensaver.

    The set id comes from the ``umsa_set_id`` unique id of the item (Kodi
    20 and later), the software id from the ``Votes`` label. Missing or
    invalid metadata and a missing database handle are logged, the
    database write itself may raise: the caller keeps the screensaver
    running.
    """

    if video_tag is None or not hasattr(video_tag, 'getUniqueID'):
        kodi.log(
            f"{log_prefix}: video history recording unavailable "
            "(Kodi has no InfoTagVideo.getUniqueID)",
            kodi.LOGWARNING)
        return False
    set_id = read_set_id(video_tag)
    if set_id is None:
        kodi.log(
            f"{log_prefix}: no valid umsa_set_id in video "
            "metadata, history not recorded",
            kodi.LOGWARNING)
        return False
    software_id = read_software_id(video_tag)

    if ggdb is None:
        kodi.log(
            f"{log_prefix}: no database handle, history not recorded",
            kodi.LOGWARNING)
        return False
    ggdb.record_screensaver_display(set_id, software_id)
    kodi.log(
        f"{log_prefix}: recorded screensaver history for "
        f"set {set_id}",
        kodi.LOGDEBUG)
    return True


def playback_token(player, instance):
    """Return an identity for the current playback instance, or ``None``.

    The token combines the playback instance counter (bumped by
    ``onPlayBackStarted``), the playlist position and the playing file,
    so duplicate ``onAVStarted`` callbacks for one playback instance
    collapse to a single record while a later playback of the same set
    (a new instance / playlist position) is recorded again.
    """

    try:
        position = player.parent.saver.playlist.getposition()
    except (AttributeError, TypeError, ValueError, RuntimeError):
        position = None
    try:
        playing_file = player.getPlayingFile()
    except RuntimeError:
        playing_file = None
    if position is None and playing_file is None:
        return None
    return (instance, position, playing_file)


class PlaybackHistoryGuard:
    """Remembers the playback instance whose history was already written."""

    def __init__(self):
        self.recorded_token = None

    def claim(self, token):
        """Return ``True`` when the token was not handled yet.

        The token is remembered either way, so a second callback for the
        same playback instance is rejected and the history is written only
        once per playback.
        """

        if token is not None and token == self.recorded_token:
            return False
        self.recorded_token = token
        return True


def record_video_playback(player, guard, kodi, read_set_id, read_software_id,
                          log_prefix=VIDEO_LOG_PREFIX):
    """Record the video of the current playback instance.

    Nothing is recorded outside the video screensaver and only once per
    playback instance. A missing or invalid ``umsa_set_id`` (including
    Kodi < 20, which has no unique-ID API) and a missing database handle
    are logged; the database write itself may raise and is caught by the
    caller.
    """

    saver = getattr(player.parent, 'saver', None)
    if saver is None or saver.running != 'videos':
        return False

    token = playback_token(player, player._playback_instance)
    if not guard.claim(token):
        kodi.log(
            f"{log_prefix}: onAVStarted duplicate for the current "
            "playback instance, not recording again",
            kodi.LOGDEBUG)
        return False
    # this playback instance is handled from here on, whether or not
    # a record can be written (prevents duplicate log spam too)
    kodi.log(f"{log_prefix}: onAVStarted", kodi.LOGDEBUG)
    try:
        video_tag = player.getVideoInfoTag()
    except (AttributeError, RuntimeError) as error:
        kodi.log(
            f"{log_prefix}: no video info tag yet: {error}",
            kodi.LOGWARNING)
        return False
    ggdb = getattr(getattr(player.parent, 'umsa', None), 'ggdb', None)
    return record_video_display(
        ggdb, video_tag, kodi, read_set_id, read_software_id, log_prefix)
