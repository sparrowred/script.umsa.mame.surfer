"""Rendering of the screensaver artwork.

The module owns the render loop of the cross, slide and wall modes and
the label fading of the video mode. It drives the Kodi window through the
``Saver`` methods (so the window stays the single owner of the Kodi
controls) and the artwork helpers of ``artwork_selector``.
"""

from random import randint
from time import monotonic

from . import left_art
from .artwork_selector import (
    art_types_for_mode,
    aspect_for,
    display_for,
    left_picture_type,
    needs_snapshot_check,
    source_roots,
)
from .availability import IMAGE_MODES
from .constants import (
    BACKG,
    IMAGE,
    INFO_DETAIL,
    INFO_LABEL,
    PIC_MACHINE,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from .wall_layout import KEEP, STRETCH, cell_geometry, next_position

# Screen area the cross mode places its pictures on
CROSS_MAX_X = SCREEN_WIDTH
CROSS_MAX_Y = SCREEN_HEIGHT

# Artwork rows that show a game screen; their left picture is the flyer/cover
SCREEN_ROW_TYPES = ('snap', 'titles', 'videosnaps')

# Maximum number of pictures kept on screen in cross mode
CROSS_MAX_PICTURES = 60

# Maximum number of consecutive artwork failures before the screensaver stops
MAX_ARTWORK_FAILURES = 10

# Delay before the next artwork attempt (ms)
ARTWORK_RETRY_DELAY = 500

# Poll interval of the interruptible waits (ms)
WAIT_POLL_INTERVAL = 250

# Pause between two pictures of the cross prefill (ms): short, but the
# sleep lets Kodi deliver the pending actions (stop, volume) to the saver
CROSS_PREFILL_PAUSE = 100

# Maximum time the label fading waits for the duration of a video (s)
VIDEO_STARTUP_TIMEOUT = 15.0

# Number of polls in a row without an active playback before the wait gives up
VIDEO_STARTUP_INACTIVE_POLLS = 4


class RenderContext:
    """State of one screensaver render loop."""

    def __init__(self, saver, gui, kodi):
        self.saver = saver
        self.gui = gui
        self.kodi = kodi
        # the two image/background controls are flipped on every iteration
        self.order = [0, 1]
        # position used last in the wall mode
        self.lastpos = None
        # pictures shown in the cross mode, oldest first: (variant, control)
        self.piclist = []
        # cross controls that left the window and wait for reuse, per variant
        self.spare = {STRETCH: [], KEEP: []}


def cross_geometry(aspect, x_axis, y_axis):
    """Return ``(variant, x, y, width, height)`` of a cross picture.

    ``x_axis``/``y_axis`` is the random center of the picture. A
    ``NotScaled`` picture needs the ``KEEP`` control variant, every other
    picture the ``STRETCH`` variant.
    """

    if aspect == 'Vertical':
        return STRETCH, x_axis-180, y_axis-240, 360, 480
    if aspect == 'NotScaled':
        return KEEP, x_axis-270, y_axis-270, 540, 540
    return STRETCH, x_axis-270, y_axis-202, 540, 405


def render_cross(ctx, filename, aspect):
    """Show one picture at a random position (cross mode).

    At most ``CROSS_MAX_PICTURES`` controls are in the window. When the
    screen is full, the oldest control leaves the window and is reused:
    it gets the new picture and geometry and comes back on top. The other
    pictures keep their image, position and order.
    """

    saver = ctx.saver
    variant, pos_x, pos_y, width, height = cross_geometry(
        aspect, randint(0, CROSS_MAX_X), randint(0, CROSS_MAX_Y))
    if len(ctx.piclist) >= CROSS_MAX_PICTURES:
        old_variant, oldest = ctx.piclist.pop(0)
        saver.removeControl(oldest)
        ctx.spare[old_variant].append(oldest)
    if ctx.spare[variant]:
        # a removed control takes the new picture and geometry before it is
        # added again: re-adding puts it on top of the window
        control = ctx.spare[variant].pop()
        control.setImage(filename)
        control.setPosition(pos_x, pos_y)
        control.setWidth(width)
        control.setHeight(height)
    elif variant == KEEP:
        control = ctx.gui.ControlImage(pos_x, pos_y, width, height, filename, 2)
    else:
        control = ctx.gui.ControlImage(pos_x, pos_y, width, height, filename)
    ctx.piclist.append((variant, control))
    saver.addControl(control)


def render_slide(ctx, filename, aspect):
    """Show one picture in the slide view (slide mode)."""

    saver = ctx.saver
    order = ctx.order
    saver.getControl(IMAGE[order[0]]).setImage(filename)
    saver.setProperty(f'SlideView.Slide{order[0]+1}', '0')
    saver.setProperty(f'SlideView.Slide{order[1]+1}', '1')
    saver.setProperty(f'SlideView.Fade1{order[0]+1}', '0')
    saver.setProperty(f'SlideView.Fade1{order[1]+1}', '1')
    saver.getControl(BACKG[order[0]]).setImage(filename)


def render_wall(ctx, filename, aspect):
    """Show one picture in the wall (wall mode).

    The controls of the cell are reused: only the picture, the position and
    the size change, no control is created or removed.
    """

    saver = ctx.saver
    wall = saver.wall
    order = ctx.order
    # pop new position from list
    lastpos = next_position(wall, ctx.lastpos)
    ctx.lastpos = lastpos

    if wall['free'] != 0:
        wall['freelist'].append(lastpos)
        if len(wall['freelist']) == wall['free']:
            tofree = wall['freelist'].pop(
                randint(0, round(len(wall['freelist'])/2)))
            wall['pos'].insert(0, tofree)
            # make the cell empty
            for control in wall['slots'][tofree].values():
                control.setImage('')

    # horizontal and vertical pictures are stretched, NotScaled keeps its
    # aspect ratio: each needs its own control variant
    variant, pos_x, pos_y, width, height = cell_geometry(
        wall['cells'][lastpos], aspect, wall)
    slot = wall['slots'][lastpos]
    for name, control in slot.items():
        if name != variant:
            control.setImage('')
    control = slot[variant]
    control.setPosition(pos_x, pos_y)
    control.setWidth(width)
    control.setHeight(height)
    control.setImage(filename, False)
    saver.getControl(BACKG[order[0]]).setImage(filename)
    saver.setProperty(f'SlideView.Fade1{order[0]+1}', '0')
    saver.setProperty(f'SlideView.Fade1{order[1]+1}', '1')


def render_left_picture(ctx, art, roots):
    """Show the left picture of the artwork in the overlay.

    A snap/title/video row gets the flyer or cover of the set, every other
    row gets the snap. The snap is shown with the aspect ratio of the game
    screen, the flyer/cover with the proportions of its file.
    """

    saver = ctx.saver
    # TODO get left pic: snap = cross,slide ; cover/flyer = video, wall
    if art['type'] in SCREEN_ROW_TYPES:
        if 'left_pic' in art:
            snapshot = art['left_pic']
        else:
            left_type = left_picture_type(art)
            snapshot = saver.resolve_art_path(art, roots, art_type=left_type)
        saver.show_left_art(snapshot, left_art.ARTWORK, use_cache=False)
    elif 'left_pic' in art:
        saver.show_left_art(
            art['left_pic'], left_art.SCREEN, display_for(art), use_cache=False)
    else:
        # TODO dirty hack, get from db! maybe get_random_art should return it!
        snapshot = saver.resolve_art_path(
            art, roots, art_type='snap', extension='png')
        if saver.check_snapshot(snapshot):
            saver.show_left_art(
                snapshot, left_art.SCREEN, display_for(art), use_cache=False)
        else:
            # no snapshot = clear the left picture
            saver.show_left_art('')


def playback_active(player):
    """Return whether the player still plays something.

    ``isPlaying()`` is used when the runtime provides it, otherwise the
    older ``isPlayingVideo()`` is asked. A player that does not answer at
    all is treated as active: the caller has its own timeout.
    """

    for name in ('isPlaying', 'isPlayingVideo'):
        probe = getattr(player, name, None)
        if probe is None:
            continue
        try:
            return bool(probe())
        except RuntimeError:
            return False
    return True


def player_abort_requested(player):
    """Return whether Kodi asked the screensaver script of ``player`` to end."""

    saver = getattr(getattr(player, 'parent', None), 'saver', None)
    probe = getattr(saver, 'abort_requested', None)
    return bool(probe()) if callable(probe) else False


def wait_for_duration(player, kodi, timeout=VIDEO_STARTUP_TIMEOUT):
    """Wait until the player reports the duration of the video.

    The wait is bounded and interruptible: it gives up when the playback
    stops before a duration is known and when the video does not start
    within the timeout or Kodi asks the script to end. Returns the
    duration in seconds, ``0`` when no valid duration was reported.
    """

    waited = 0.0
    inactive_polls = 0
    while True:
        try:
            total_time = int(player.getTotalTime())
        except (TypeError, ValueError, RuntimeError):
            # RuntimeError: Kodi is not playing (anymore)
            total_time = 0
        if total_time > 0:
            return total_time
        if waited >= timeout:
            kodi.log(
                "UMSA SSaver Player: no video duration after "
                f"{int(timeout)} seconds, giving up",
                kodi.LOGWARNING)
            return 0
        if playback_active(player):
            inactive_polls = 0
        else:
            inactive_polls += 1
            if inactive_polls >= VIDEO_STARTUP_INACTIVE_POLLS:
                kodi.log(
                    "UMSA SSaver Player: playback stopped before the "
                    "video duration was known",
                    kodi.LOGWARNING)
                return 0
        if player_abort_requested(player):
            return 0
        kodi.sleep(WAIT_POLL_INTERVAL)
        waited += WAIT_POLL_INTERVAL / 1000


def run_playback_labels(player, kodi):
    """Fade the screensaver labels in and out while a video plays.

    The video length decides when the label appears and disappears: the
    label is shown after a few seconds and hidden shortly before the end
    of the video. A video that never reports its duration leaves the
    screensaver untouched: the labels stay hidden and the label loop is
    not started.

    Kodi delivers the callback of a newer video while an older label loop
    sleeps (quick "next video"); a loop whose video is no longer the
    current playback instance ends at once and leaves the labels to the
    newer one.

    The loop watches the whole video - in the video mode it is the only
    Python code that runs - and ends the screensaver within a second when
    Kodi asks the script to end.
    """

    saver = player.parent.saver
    instance = getattr(player, '_playback_instance', None)

    def superseded():
        return getattr(player, '_playback_instance', None) != instance

    # hide the info of the previous video at once, before the new content
    saver.hide_label_now()
    # wait until the video starts, bounded and interruptible
    total_time = wait_for_duration(player, kodi)
    if superseded():
        return
    if player_abort_requested(player):
        saver.abort_screensaver('video')
        return
    if total_time <= 0:
        # no valid duration: leave the label state consistent and stop
        player.runp = False
        return
    # calc show times
    if total_time > 28:
        timecount1 = 10
        timecount2 = total_time-10
    elif total_time > 16:
        timecount1 = 8
        timecount2 = total_time-2
    else:
        timecount1 = 4
        timecount2 = total_time-1
    player.runp = True
    count_seconds = 0
    kodi.log(f"UMSA SSaver Player: time: {total_time}, start {timecount1}, end {timecount2}", kodi.LOGINFO)
    # set labels
    try:
        tag = player.getVideoInfoTag()
        saver.overlay_control(INFO_LABEL).setLabel(tag.getTitle())
        saver.overlay_control(INFO_DETAIL).setLabel(tag.getGenre())
        saver.overlay_control(PIC_MACHINE).setImage(tag.getTrailer())
        kodi.log(f"UMSA SSaver Player: director {tag.getDirector()}", kodi.LOGINFO)
        saver.show_left_art(tag.getDirector(), left_art.ARTWORK)
    except RuntimeError:
        # the playback ended meanwhile: nothing to label
        player.runp = False
        return

    while player.runp:
        if superseded():
            return
        if player_abort_requested(player):
            saver.abort_screensaver('video')
            return
        if player.isPlayingVideo():
            if count_seconds == timecount1:
                saver.set_label_fade('0')
            elif count_seconds == timecount2:
                saver.set_label_fade('1')
            # keep watching until the video ends
        else:
            player.runp = False
            continue
        kodi.sleep(1000)
        count_seconds += 1


class RenderSession:
    """Drives the render loop of one screensaver session."""

    def __init__(self, saver, gui, kodi, clock=monotonic):
        self.saver = saver
        self.gui = gui
        self.kodi = kodi
        # consecutive failed artwork attempts
        self._failures = 0
        # timed mode switch: the monotonic clock, the start of the mode and
        # the image mode the screensaver continues with after this session
        self._clock = clock
        self._mode_started = None
        self.next_mode = None

    def _wait_time(self):
        """Return how long the artwork stays on screen."""

        saver = self.saver
        kodi = self.kodi
        if saver.running == 'videos':
            kodi.log(f"UMSA SSaver isPlayingVideo {saver.parent.player.isPlayingVideo()}", kodi.LOGDEBUG)
            while not saver.parent.player.isPlayingVideo():
                kodi.sleep(250)
                kodi.log(f"UMSA SSaver isPlayingVideo {saver.parent.player.isPlayingVideo()}", kodi.LOGDEBUG)
            # get total time in sec
            wait_time = int(saver.parent.player.getTotalTime())+1
            kodi.log("UMSA SSaver wait_time {wait_time}", kodi.LOGDEBUG)
            return wait_time
        return saver.settings['time']

    def _cleanup(self, ctx):
        """Clear the images of the finished screensaver."""

        saver = self.saver
        if saver.running == 'slide':
            saver.getControl(IMAGE[0]).setImage('')
            saver.getControl(IMAGE[1]).setImage('')
            saver.getControl(BACKG[0]).setImage('')
            saver.getControl(BACKG[1]).setImage('')
        elif saver.running == 'cross':
            ctx.piclist.reverse()
            for _variant, control in ctx.piclist:
                saver.removeControl(control)
        elif saver.running == 'wall':
            for slot in saver.wall.get('slots', []):
                for control in slot.values():
                    saver.removeControl(control)
            saver.getControl(BACKG[0]).setImage('')
            saver.getControl(BACKG[1]).setImage('')

    def _abort_requested(self):
        """Stop the screensaver when Kodi asked the script to end.

        Returns ``True`` when the render loop has to end. The loop's
        ``finally`` closes the windows as for every other stop.
        """

        if not self.saver.abort_requested():
            return False
        self.kodi.log("UMSA SSaver: Kodi asked to stop, ending the render loop", self.kodi.LOGWARNING)
        self._stop_saver()
        return True

    def _stop_saver(self):
        """Stop the screensaver through the established lifecycle path."""

        parent = getattr(self.saver, 'parent', None)
        deactivate = getattr(parent, 'reallyDeactivateScreensaver', None)
        if callable(deactivate):
            deactivate()
        else:
            self.saver.running = 'no'

    def _mode_expired(self):
        """Return whether the image mode ran for ``ssaver_mode_switch_minutes``.

        Only image modes of an automatically started screensaver rotate;
        ``0`` minutes switches the rotation off.
        """

        minutes = self.saver.settings.get('mode_switch_minutes') or 0
        if minutes <= 0 or self._mode_started is None:
            return False
        if self.saver.running not in IMAGE_MODES or not self.saver.rotate_modes:
            return False
        return self._clock() - self._mode_started >= minutes * 60

    def _switch_mode(self):
        """Handle an expired image mode at a safe point of the render loop.

        Returns ``True`` when the session ends because another image mode
        follows (``next_mode``). Without another mode the current one keeps
        running and its time starts again.
        """

        next_mode = self.saver.next_rotation_mode()
        if next_mode is None:
            self._mode_started = self._clock()
            return False
        self.next_mode = next_mode
        return True

    def _cross_prefill(self, ctx):
        """Return whether the cross prefill still fills the screen.

        With ``ssaver_cross_prefill`` the first pictures of a cross session
        follow each other without the ``ssaver_time`` pause until the
        screen holds ``CROSS_MAX_PICTURES``; the render context (and with
        it the picture list) is new for every cross session.
        """

        saver = self.saver
        return (saver.running == 'cross'
                and bool(saver.settings.get('cross_prefill'))
                and len(ctx.piclist) < CROSS_MAX_PICTURES)

    def _wait_before_retry(self):
        """Wait a short moment before the next artwork attempt.

        The wait is interruptible: a screensaver that is switched off
        ends the wait at once.
        """

        remaining = ARTWORK_RETRY_DELAY
        while remaining > 0:
            if self.saver.running == 'no' or self._abort_requested():
                return
            step = min(WAIT_POLL_INTERVAL, remaining)
            self.kodi.sleep(step)
            remaining -= step

    def _artwork_failure(self):
        """Handle one failed artwork attempt.

        Returns ``False`` when the render loop has to end, ``True`` when
        the next attempt may follow. A normal shutdown is not counted as
        a failed attempt.
        """

        if self.saver.running == 'no':
            return False
        self._failures += 1
        if self._failures >= MAX_ARTWORK_FAILURES:
            self.kodi.log(
                f"UMSA SSaver: no usable artwork after {self._failures} "
                "attempts, stopping the screensaver",
                self.kodi.LOGERROR)
            self.saver.notify_user("no usable screensaver artwork found")
            self._stop_saver()
            return False
        self._wait_before_retry()
        return True

    def _start_video_mode(self):
        """Queue the screensaver videos and start the playback.

        Returns ``True`` when the video mode took over and ``False`` when
        no video was available at all - the mode was then switched to an
        artwork mode by the caller.
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
        # mute before the playback starts, so no sound gets through
        saver.mute_videos()
        saver.parent.player.play(saver.playlist)
        saver.mark_video_start()
        return True

    def run(self):
        """Run the screensaver until it is stopped.

        Returns ``False`` when the video mode took over (the window stays
        open until the playback ends) and ``True`` when the render loop
        was left.
        """

        saver = self.saver
        kodi = self.kodi
        ctx = RenderContext(saver, self.gui, kodi)
        self._failures = 0

        try:
            if saver.running == 'videos':
                kodi.log("UMSA SSaver: screensaver: video", kodi.LOGDEBUG)
                if self._start_video_mode():
                    # the video mode took over: the window stays open and the
                    # playback is driven by the player callbacks
                    return False
                # no video at all: continue with an artwork mode
                saver.notify_user("no screensaver videos available")
                new_mode = saver.prepare_artwork_mode()
                if new_mode is None:
                    saver.notify_user("no screensaver artwork available")
                    return True
                kodi.log(f"UMSA SSaver: continuing with the {new_mode} mode", kodi.LOGINFO)

            if not saver.art_types:
                saver.art_types = art_types_for_mode(saver.running)

            # the skin shows the black base, the background and the slide
            # images by the mode property (UMSA.Screensaver.Mode)
            if saver.running == 'wall':
                saver.create_wall()
                ctx.lastpos = None

            # the mode time starts when the mode really runs
            self._mode_started = self._clock()

            # screensaver loop
            while saver.running != 'no':
                # safe point: the previous artwork is complete
                if self._abort_requested():
                    break
                if self._mode_expired() and self._switch_mode():
                    break
                art = saver.parent.umsa.ggdb.get_random_art(saver.art_types)
                # remember the software being rendered for the context handoff
                saver.remember_art(art)
                # no artwork to render: nothing was displayed, so nothing may be
                # recorded (and there is no path to resolve)
                if not art:
                    kodi.log("UMSA SSaver: no artwork returned, skipping iteration", kodi.LOGDEBUG)
                    if not self._artwork_failure():
                        break
                    continue

                roots = source_roots(saver.path, saver.parent.umsa)
                filename = saver.resolve_art_path(art, roots)

                # the artwork has no usable file: try the next one
                if not filename:
                    kodi.log("UMSA SSaver: artwork has no usable file, skipping iteration", kodi.LOGWARNING)
                    if not self._artwork_failure():
                        break
                    continue

                # check for bad image
                if needs_snapshot_check(art['type']) and not saver.check_snapshot(filename):
                    if not self._artwork_failure():
                        break
                    continue

                # set scaling
                aspect = aspect_for(art)

                # the new content must not show up in a running fade-out
                saver.hide_label_now()

                # get machine pic
                saver.overlay_control(PIC_MACHINE).setImage(
                    saver.get_machine_pic(art), False)

                render_left_picture(ctx, art, roots)

                # set info label
                saver.overlay_control(INFO_LABEL).setLabel(f"{art['gamename']}")
                saver.overlay_control(INFO_DETAIL).setLabel(
                    "{}, {}".format(art['year'], art['maker']))

                # call saver
                if saver.running == 'cross':
                    render_cross(ctx, filename, aspect)
                elif saver.running == 'slide':
                    render_slide(ctx, filename, aspect)
                elif saver.running == 'wall':
                    render_wall(ctx, filename, aspect)

                # the render path completed for cross/slide/wall: this is the
                # display-success boundary (Kodi gives no image-load callback),
                # so record the set now, once, immediately before the wait loop.
                # Anything raised above skips this call - no partial render is
                # ever recorded.
                saver.record_display(art)

                # the artwork was displayed: the failure counter starts again
                self._failures = 0

                if self._cross_prefill(ctx):
                    # no ssaver_time pause while the cross fills up; the
                    # game info stays hidden instead of flickering
                    saver.set_label_fade('1')
                    kodi.sleep(CROSS_PREFILL_PAUSE)
                    continue

                # set wait_time
                wait_time = self._wait_time()

                # wait_loop
                count = 0
                while count < wait_time:
                    if count == 1:
                        saver.set_label_fade('0')
                    if count == wait_time-1:
                        saver.set_label_fade('1')
                    count += 1
                    kodi.sleep(1000)
                    # the mode switch does not wait for the whole ssaver_time
                    if (saver.running == 'no' or self._abort_requested()
                            or self._mode_expired()):
                        break

                ctx.order.reverse()

        finally:
            # Ensure cleanup happens even on unexpected exceptions
            self._cleanup(ctx)
        return True
