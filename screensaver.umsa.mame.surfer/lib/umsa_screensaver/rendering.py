"""Rendering of the screensaver artwork.

The module owns the render loop of the cross, slide and wall modes (the
video mode lives in ``video_session``). It drives the Kodi window through the
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
    screen, the flyer/cover with the proportions of its file. Both come from
    the artwork database with the clone/parent fallback of Core
    (``DBMod.get_set_artwork``); eXoDOS/GB64 rows bring ``left_pic`` along.
    """

    saver = ctx.saver
    if art['type'] in SCREEN_ROW_TYPES:
        if 'left_pic' in art:
            snapshot = art['left_pic']
        else:
            snapshot = saver.get_set_artwork(art, left_picture_type(art), roots)
        saver.show_left_art(snapshot, left_art.ARTWORK, use_cache=False)
    elif 'left_pic' in art:
        saver.show_left_art(
            art['left_pic'], left_art.SCREEN, display_for(art), use_cache=False)
    else:
        snapshot = saver.get_set_artwork(art, 'snap', roots)
        if snapshot and saver.check_snapshot(snapshot):
            saver.show_left_art(
                snapshot, left_art.SCREEN, display_for(art), use_cache=False)
        else:
            # no snapshot = clear the left picture
            saver.show_left_art('')


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
        # the mode the render loop runs, set when the loop starts
        self._mode = None

    def _wait_time(self):
        """Return how long the artwork stays on screen."""

        return self.saver.settings['time']

    def _cleanup(self, ctx):
        """Clear the images of the finished screensaver.

        Works on the mode captured at the start of the render loop. A
        session that never reached the loop has nothing to clear.
        """

        saver = self.saver
        if self._mode == 'slide':
            saver.getControl(IMAGE[0]).setImage('')
            saver.getControl(IMAGE[1]).setImage('')
            saver.getControl(BACKG[0]).setImage('')
            saver.getControl(BACKG[1]).setImage('')
        elif self._mode == 'cross':
            ctx.piclist.reverse()
            for _variant, control in ctx.piclist:
                saver.removeControl(control)
        elif self._mode == 'wall':
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

    def run(self):
        """Run the render loop of an image mode until it is left.

        The loop ends when the saver stops (``saver.running == 'no'``) or
        the timed mode switch continues with ``next_mode``. The video mode
        has its own loop (``video_session.VideoSession``).
        """

        saver = self.saver
        kodi = self.kodi
        ctx = RenderContext(saver, self.gui, kodi)
        self._failures = 0

        try:
            # the skin shows the black base, the background and the slide
            # images by the mode property (UMSA.Screensaver.Mode)
            if saver.running == 'wall':
                saver.create_wall()
                ctx.lastpos = None
                # the wall setting decides between titles and snaps; the
                # artwork types of an explicit request win
                if not saver.art_types:
                    saver.art_types = saver.wall.get('art_types')

            if not saver.art_types:
                saver.art_types = art_types_for_mode(saver.running)

            # the cleanup needs the mode of this session: a normal stop has
            # already set saver.running to 'no' when the loop ends
            self._mode = saver.running

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
