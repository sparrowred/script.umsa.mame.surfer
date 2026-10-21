"""Rendering of the screensaver artwork.

The module owns the render loop of the cross, slide and wall modes and
the label fading of the video mode. It drives the Kodi window through the
``Saver`` methods (so the window stays the single owner of the Kodi
controls) and the artwork helpers of ``artwork_selector``.
"""

from random import randint

from .artwork_selector import (
    art_types_for_mode,
    aspect_for,
    left_picture_type,
    needs_snapshot_check,
    source_roots,
)
from .constants import (
    BACKG,
    CROSS_BACKGROUND,
    IMAGE,
    INFO_DETAIL,
    INFO_LABEL,
    PIC_1TO1,
    PIC_3TO4,
    PIC_4TO3,
    PIC_MACHINE,
)
from .wall_layout import next_position

# Screen area the cross mode places its pictures on
CROSS_MAX_X = 1280
CROSS_MAX_Y = 720

# Maximum number of pictures kept on screen in cross mode
CROSS_MAX_PICTURES = 60


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
        # pictures shown in the cross mode
        self.piclist = []


def render_cross(ctx, filename, aspect):
    """Show one picture at a random position (cross mode)."""

    saver = ctx.saver
    x_axis = randint(0, CROSS_MAX_X)
    y_axis = randint(0, CROSS_MAX_Y)
    if aspect == 'Vertical':
        # TODO look up aspect calc from ssaver
        ctx.piclist.append(ctx.gui.ControlImage(x_axis-120, y_axis-160, 240, 320, filename))
    elif aspect == 'NotScaled':
        ctx.piclist.append(ctx.gui.ControlImage(x_axis-180, y_axis-180, 360, 360, filename, 2))
    else:
        ctx.piclist.append(ctx.gui.ControlImage(x_axis-180, y_axis-135, 360, 270, filename))
    # show pic
    saver.addControl(ctx.piclist[-1])
    if len(ctx.piclist) > CROSS_MAX_PICTURES:
        saver.removeControl(ctx.piclist[0])
        del ctx.piclist[0]


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
    """Show one picture in the wall (wall mode)."""

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
            # make image empty
            saver.removeControl(wall['mesh'][tofree])
            wall['mesh'][tofree].setImage('')
            # TODO unneeded?
            saver.addControl(wall['mesh'][tofree])

    # check if image is horizontal, vertical or aspect ratio must be keeped
    # get image position
    pos_x, pos_y = wall['mesh'][lastpos].getPosition()
    # width not standard =
    # image was vertical > correct pos_x position
    if wall['mesh'][lastpos].getWidth() != wall['width']:
        pos_x = pos_x-wall['vert_x']
    # remove image control
    # TODO only when image exists
    saver.removeControl(wall['mesh'][lastpos])
    # TODO switch to create_gui_element, it also does snaporientation
    # create new image control for horz, vert or ar=keep
    if aspect == 'Horizontal':
        wall['mesh'][lastpos] = ctx.gui.ControlImage(
            pos_x, pos_y, wall['width'], wall['height'], '')
    elif aspect == 'Vertical':
        wall['mesh'][lastpos] = ctx.gui.ControlImage(
            pos_x + wall['vert_x'], pos_y,
            wall['vert_width'], wall['height'], '')
    elif aspect == 'NotScaled':
        wall['mesh'][lastpos] = ctx.gui.ControlImage(
            pos_x, pos_y, wall['width'], wall['height'], '', 2)
    # set image
    wall['mesh'][lastpos].setImage(filename, False)
    # add new image control
    saver.addControl(wall['mesh'][lastpos])
    saver.getControl(BACKG[order[0]]).setImage(filename)
    saver.setProperty(f'SlideView.Fade1{order[0]+1}', '0')
    saver.setProperty(f'SlideView.Fade1{order[1]+1}', '1')


def render_left_picture(ctx, art, roots):
    """Show the left picture (snapshot) of the artwork."""

    saver = ctx.saver
    # get left pic
    # TODO get left pic: snap = cross,slide ; cover/flyer = video, wall
    # TODO needs fetch info for snap from db for aspect ratio
    if 'left_pic' in art:
        if art['type'] in ('snap', 'titles', 'videosnaps'):
            saver.getControl(PIC_1TO1).setImage(art['left_pic'])
            saver.getControl(PIC_4TO3).setImage('')
            saver.getControl(PIC_3TO4).setImage('')
        else:
            saver.getControl(PIC_1TO1).setImage('')
            saver.getControl(PIC_4TO3).setImage(art['left_pic'])
            saver.getControl(PIC_3TO4).setImage('')
    elif art['type'] in ('snap', 'titles', 'videosnaps'):
        left_type = left_picture_type(art)
        snapshot = saver.resolve_art_path(art, roots, art_type=left_type)
        saver.getControl(PIC_1TO1).setImage(snapshot, False)
        saver.getControl(PIC_4TO3).setImage('')
        saver.getControl(PIC_3TO4).setImage('')
    else:
        # TODO dirty hack, get from db! maybe get_random_art should return it!
        snapshot = saver.resolve_art_path(
            art, roots, art_type='snap', extension='png')
        snapctrl = PIC_4TO3
        if saver.check_snapshot(snapshot):
            saver.getControl(snapctrl).setImage(snapshot, False)

        # no snapshot = clear all 3 snap views
        else:
            saver.getControl(PIC_4TO3).setImage('')
            saver.getControl(PIC_3TO4).setImage('')
            saver.getControl(PIC_1TO1).setImage('')


def run_playback_labels(player, kodi):
    """Fade the screensaver labels in and out while a video plays.

    The video length decides when the label appears and disappears: the
    label is shown after a few seconds and hidden shortly before the end
    of the video.
    """

    saver = player.parent.saver
    # clear video label
    saver.setProperty('LabelView.Fade', '1')
    # get total time in sec
    total_time = int(player.getTotalTime())
    # wait until video starts
    while total_time == 0:
        kodi.sleep(250)
        total_time = int(player.getTotalTime())
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
    saver.getControl(INFO_LABEL).setLabel(
        player.getVideoInfoTag().getTitle()
    )
    saver.getControl(INFO_DETAIL).setLabel(
        player.getVideoInfoTag().getGenre()
    )
    saver.getControl(PIC_MACHINE).setImage(
        player.getVideoInfoTag().getTrailer()
    )
    kodi.log(f"UMSA SSaver Player: director {player.getVideoInfoTag().getDirector()}", kodi.LOGINFO)
    saver.getControl(PIC_1TO1).setImage(
        player.getVideoInfoTag().getDirector()
    )

    while player.runp:
        if player.isPlayingVideo():
            if count_seconds == timecount1:
                saver.setProperty('LabelView.Fade', '0')
            elif count_seconds == timecount2:
                saver.setProperty('LabelView.Fade', '1')
                player.runp = False
                continue
        else:
            player.runp = False
            continue
        kodi.sleep(1000)
        count_seconds += 1


class RenderSession:
    """Drives the render loop of one screensaver session."""

    def __init__(self, saver, gui, kodi):
        self.saver = saver
        self.gui = gui
        self.kodi = kodi

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
            saver.getControl(IMAGE[0]).setImage('blank.png')
            saver.getControl(IMAGE[1]).setImage('blank.png')
            saver.getControl(BACKG[0]).setImage('blank.png')
            saver.getControl(BACKG[1]).setImage('blank.png')
        elif saver.running == 'cross':
            ctx.piclist.reverse()
            for control in ctx.piclist:
                saver.removeControl(control)
        elif saver.running == 'wall':
            for control in saver.wall['mesh']:
                saver.removeControl(control)
                #control.setImage('blank.png')
            saver.getControl(BACKG[0]).setImage('blank.png')
            saver.getControl(BACKG[1]).setImage('blank.png')

    def run(self):
        """Run the screensaver until it is stopped.

        Returns ``False`` when the video mode took over (the window stays
        open until the playback ends) and ``True`` when the render loop
        was left.
        """

        saver = self.saver
        kodi = self.kodi
        ctx = RenderContext(saver, self.gui, kodi)

        if not saver.art_types:
            saver.art_types = art_types_for_mode(saver.running)
            if saver.running == 'wall':
                saver.create_wall()

        if saver.running == 'videos':
            kodi.log("UMSA SSaver: screensaver: video", kodi.LOGDEBUG)
            saver.add_video_to_playlist()
            saver.add_video_to_playlist()
            saver.parent.player.play(saver.playlist)
            return False

        if saver.running == 'wall':
            saver.create_wall()
            ctx.lastpos = None
            saver.setProperty('SlideView.Background', 'show')

        elif saver.running == 'slide':
            saver.setProperty('SlideView.Background', 'show')

        elif saver.running == 'cross':
            saver.getControl(CROSS_BACKGROUND).setVisible(False)
            saver.getControl(BACKG[0]).setVisible(False)
            saver.getControl(BACKG[1]).setVisible(False)

        # screensaver loop
        while saver.running != 'no':
            art = saver.parent.umsa.ggdb.get_random_art(saver.art_types)
            # remember the software being rendered for the context handoff
            saver.remember_art(art)
            # no artwork to render: nothing was displayed, so nothing may be
            # recorded (and there is no path to resolve)
            if not art:
                kodi.log("UMSA SSaver: no artwork returned, skipping iteration", kodi.LOGDEBUG)
                continue

            roots = source_roots(saver.path, saver.parent.umsa)
            filename = saver.resolve_art_path(art, roots)

            # check for bad image
            if needs_snapshot_check(art['type']) and not saver.check_snapshot(filename):
                continue

            # set scaling
            aspect = aspect_for(art)

            # get machine pic
            saver.getControl(PIC_MACHINE).setImage(
                saver.get_machine_pic(art), False)

            render_left_picture(ctx, art, roots)

            # set info label
            saver.getControl(INFO_LABEL).setLabel(f"{art['gamename']}")
            saver.getControl(INFO_DETAIL).setLabel(
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

            # set wait_time
            wait_time = self._wait_time()

            # wait_loop
            count = 0
            while count < wait_time:
                if count == 1:
                    saver.setProperty('LabelView.Fade', '0')
                if count == wait_time-1:
                    saver.setProperty('LabelView.Fade', '1')
                count += 1
                kodi.sleep(1000)
                if saver.running == 'no':
                    break

            ctx.order.reverse()

        # cleanup
        self._cleanup(ctx)
        return True
