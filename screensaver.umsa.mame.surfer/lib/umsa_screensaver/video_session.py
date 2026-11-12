"""The video mode of the screensaver.

One loop drives the whole video mode. It runs inside ``Saver.onInit``
like the render loop of the image modes and is the only place that waits
(``kodi.sleep``): Kodi delivers the player callbacks and the actions in
that wait. The player callbacks only put events into a queue, so they
return at once and never nest; the loop takes the events, feeds the
playlist, fades the labels and asks for Kodi's abort request on every
pass - also for a video that never reports its duration.
"""

from time import monotonic

from . import left_art
from . import strings as S
from .constants import INFO_DETAIL, INFO_LABEL, MODE_VIDEOS, PIC_MACHINE
from .strings import tr

# Poll interval of the video loop (ms)
WAIT_POLL_INTERVAL = 250

# Maximum time the label fading waits for the duration of a video (s)
VIDEO_STARTUP_TIMEOUT = 15.0

# Player events the callbacks put into the queue
EVENT_STARTED = 'started'
EVENT_ENDED = 'ended'


def label_times(total_time):
    """Return ``(show_at, hide_at)`` in seconds for a video length.

    The label appears a few seconds after the start and disappears
    shortly before the end of the video.
    """

    if total_time > 28:
        return 10, total_time-10
    if total_time > 16:
        return 8, total_time-2
    return 4, total_time-1


class VideoLabels:
    """Fades the game info in and out while a video plays.

    A small state machine the video loop ticks: after ``start()`` it waits
    until the player reports the duration of the video, then it sets the
    labels and fades them by the monotonic clock. A video that never
    reports a duration leaves the labels hidden.
    """

    IDLE = 'idle'
    WAITING = 'waiting'
    SHOWING = 'showing'

    def __init__(self, saver, player, kodi, clock=monotonic):
        self.saver = saver
        self.player = player
        self.kodi = kodi
        self._clock = clock
        self.state = self.IDLE
        # the playback instance the labels belong to
        self._instance = None
        self._since = 0.0
        self._show_at = 0
        self._hide_at = 0
        self._shown = False

    def start(self, instance):
        """Begin the labels of a new video: hide the old info at once."""

        self.saver.hide_label_now()
        self._instance = instance
        self._since = self._clock()
        self._shown = False
        self.state = self.WAITING

    def stop(self, instance):
        """End the labels of the video ``instance``.

        The end of an older video does not touch the labels of the video
        that plays now.
        """

        if instance == self._instance:
            self.state = self.IDLE

    def _total_time(self):
        try:
            return int(self.player.getTotalTime())
        except (TypeError, ValueError, RuntimeError):
            # RuntimeError: Kodi is not playing (anymore)
            return 0

    def _begin(self, total_time):
        """Set the labels of the playing video and start the fade times."""

        kodi = self.kodi
        saver = self.saver
        self._show_at, self._hide_at = label_times(total_time)
        kodi.log(
            f"UMSA SSaver Player: time: {total_time}, start {self._show_at}, "
            f"end {self._hide_at}", kodi.LOGINFO)
        try:
            tag = self.player.getVideoInfoTag()
            saver.overlay_control(INFO_LABEL).setLabel(tag.getTitle())
            saver.overlay_control(INFO_DETAIL).setLabel(tag.getGenre())
            saver.overlay_control(PIC_MACHINE).setImage(tag.getTrailer())
            saver.show_left_art(tag.getDirector(), left_art.ARTWORK)
        except RuntimeError:
            # the playback ended meanwhile: nothing to label
            self.state = self.IDLE
            return
        self._since = self._clock()
        self._shown = False
        self.state = self.SHOWING

    def tick(self):
        """Advance the labels; called on every pass of the video loop."""

        if self.state == self.WAITING:
            total_time = self._total_time()
            if total_time > 0:
                self._begin(total_time)
            elif self._clock() - self._since >= VIDEO_STARTUP_TIMEOUT:
                self.kodi.log(
                    "UMSA SSaver Player: no video duration after "
                    f"{int(VIDEO_STARTUP_TIMEOUT)} seconds, giving up",
                    self.kodi.LOGWARNING)
                self.state = self.IDLE
        elif self.state == self.SHOWING:
            elapsed = self._clock() - self._since
            if elapsed >= self._hide_at:
                self.saver.set_label_fade('1')
                self.state = self.IDLE
            elif not self._shown and elapsed >= self._show_at:
                self.saver.set_label_fade('0')
                self._shown = True


class VideoSession:
    """Drives the video mode of one screensaver session.

    ``run()`` returns when the video mode is over: the saver was stopped
    (``saver.running == 'no'``), the timed mode switch continues with
    ``next_mode``, or the videos ran out and the saver already switched to
    an artwork mode (``saver.running`` is that mode, ``next_mode`` stays
    ``None``).
    """

    def __init__(self, saver, kodi, clock=monotonic):
        self.saver = saver
        self.kodi = kodi
        self.next_mode = None
        self._labels = VideoLabels(saver, saver.parent.player, kodi, clock)

    def _start(self):
        """Queue the screensaver videos and start the playback.

        Returns ``False`` when no video was available at all.
        """

        saver = self.saver
        # leftovers of a previous session must not pile up
        saver.cleanup_temp_videos()
        # a video mode entered by the timed mode switch starts with the
        # screensaver's own empty playlist, not with the old videos
        saver.playlist.clear()
        saver._video_playlist_urls = []
        queued = 0
        while queued < 2 and saver.add_video_to_playlist():
            queued += 1
        if queued == 0:
            self.kodi.log("UMSA SSaver: no screensaver videos available", self.kodi.LOGWARNING)
            return False
        saver._playback_owned = True
        # mute (or stop a running VGM) before the playback starts
        saver.mute_videos()
        saver.parent.player.play(saver.playlist)
        saver.mark_video_start()
        return True

    def _fall_back(self, message):
        """Leave the video mode because the database holds no video.

        The user is told and the saver continues with an artwork mode
        whose artwork is available; without any artwork it stops.
        """

        saver = self.saver
        saver.notify_user(message)
        new_mode = saver.prepare_artwork_mode()
        if new_mode is None:
            saver.notify_user(tr(S.NO_ARTWORK))
            saver.running = 'no'
            return
        self.kodi.log(f"UMSA SSaver: continuing with the {new_mode} mode", self.kodi.LOGINFO)

    def _playback_ended(self, instance):
        """Handle the end of a video: the safe point of the mode switch."""

        saver = self.saver
        self._labels.stop(instance)
        # the extracted file of the video that ended is not needed anymore
        saver.release_playing_video()
        if saver.video_teardown:
            return
        if saver.video_drain_done():
            # the last queued video ended with the playlist
            self.next_mode = saver.end_video_drain()
            return
        if saver.video_mode_expired() and saver.start_video_drain():
            # queue nothing: the video Kodi just started is the last
            return
        self.kodi.log("UMSA SSaver Player: add video to playlist", self.kodi.LOGINFO)
        if not saver.add_video_to_playlist():
            self._fall_back(tr(S.NO_VIDEOS_FOUND))

    def _handle(self, event):
        kind, instance, playing_file = event
        if kind == EVENT_STARTED:
            # remember the extracted file of the video that plays now
            self.saver.note_playing_video(playing_file)
            self._labels.start(instance)
        elif kind == EVENT_ENDED:
            self._playback_ended(instance)

    def _active(self):
        return self.saver.running == MODE_VIDEOS and self.next_mode is None

    def run(self):
        """Run the video mode until it is left."""

        saver = self.saver
        kodi = self.kodi
        player = saver.parent.player
        try:
            kodi.log("UMSA SSaver: screensaver: video", kodi.LOGDEBUG)
            # events of an earlier playback do not belong to this session
            player.take_events()
            saver.take_video_fallback_request()
            if not self._start():
                self._fall_back(tr(S.NO_VIDEOS))
                return
            while self._active():
                if saver.abort_requested():
                    saver.abort_screensaver('video')
                    break
                for event in player.take_events():
                    self._handle(event)
                    if not self._active():
                        break
                if not self._active():
                    break
                if saver.take_video_fallback_request():
                    # "next video" found no video anymore
                    self._fall_back(tr(S.NO_VIDEOS_FOUND))
                    break
                self._labels.tick()
                # Kodi delivers the player callbacks and the actions here
                kodi.sleep(WAIT_POLL_INTERVAL)
        except SystemExit as err:
            # Kodi is killing the script: end the screensaver cleanly
            kodi.log(f"UMSA SSaver SystemExit in the video loop: {err}", kodi.LOGWARNING)
            saver.abort_screensaver('SystemExit')
