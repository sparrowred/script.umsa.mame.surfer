"""Geometry of the small artwork in the bottom left corner of the overlay.

No Kodi calls here: the module decides the aspect ratio of the left
artwork and the rectangle of its image control. The overlay control
stretches the image into that rectangle, so the rectangle alone decides
the proportions on screen:

- a game screen (snap, title) is shown with the aspect ratio of the
  screen: 4:3, or 3:4 for vertical games, whatever the pixel size of the
  file is;
- every other artwork (flyer, cover, cabinet, ...) has no fixed aspect
  ratio and keeps the proportions of its image file.
"""

# Bounding box of the left artwork (1080i coordinates), anchored at the
# bottom left corner. The square box gives 4:3 and 3:4 snaps the sizes of
# the former 4:3 and 3:4 controls (280x210 and 210x280).
BOX_X = 15
BOX_BOTTOM = 1065
BOX_WIDTH = 280
BOX_HEIGHT = 280

# Kinds of left artwork
SCREEN = 'screen'
ARTWORK = 'artwork'

# Aspect ratio of a game screen per display orientation
SCREEN_ASPECTS = {
    'Horizontal': 4 / 3,
    'Vertical': 3 / 4,
}

# Aspect ratio used when the image file cannot be measured
FALLBACK_ASPECTS = {
    SCREEN: 4 / 3,
    ARTWORK: 3 / 4,
}


def image_aspect(image_size):
    """Return width/height of an image size, ``None`` when it is unusable."""

    if not image_size:
        return None
    width, height = image_size
    if width <= 0 or height <= 0:
        return None
    return width / height


def target_aspect(kind, display=None, image_size=None):
    """Return the aspect ratio the left artwork is shown with.

    ``kind`` is ``SCREEN`` or ``ARTWORK``, ``display`` the display
    orientation of the game (``Horizontal``, ``Vertical`` or
    ``NotScaled``) and ``image_size`` the pixel size of the file, if known.
    """

    file_aspect = image_aspect(image_size)
    if kind == SCREEN:
        if display == 'Horizontal' and file_aspect is not None and file_aspect < 1:
            # the orientation is only known for snap/title rows: a portrait
            # snap file belongs to a vertical game
            return SCREEN_ASPECTS['Vertical']
        if display in SCREEN_ASPECTS:
            return SCREEN_ASPECTS[display]
        # NotScaled (LCD, handhelds, pinball): the screen keeps its own shape
    return file_aspect or FALLBACK_ASPECTS.get(kind, FALLBACK_ASPECTS[ARTWORK])


def fit_rect(aspect, ar_norm, ar_x):
    """Return ``(x, y, width, height)`` of the left artwork control.

    The rectangle is the largest one with the on-screen aspect ratio
    ``aspect`` inside the bounding box, aligned to its bottom left corner.
    ``ar_norm`` (16:9 of the skin coordinates) and ``ar_x`` (aspect ratio
    of the real screen) correct the width for screens that are not 16:9.
    """

    factor = ar_norm / ar_x
    width = BOX_HEIGHT * aspect * factor
    height = BOX_HEIGHT
    if width > BOX_WIDTH:
        width = BOX_WIDTH
        height = BOX_WIDTH / (aspect * factor)
    width = round(width)
    height = round(height)
    return BOX_X, BOX_BOTTOM - height, width, height
