"""Pure geometry of the wall screensaver layout.

No Kodi calls here: the module computes rows, cell sizes, cell positions,
the geometry of a picture inside its cell and the free-slot count. The
Kodi window creates the image controls from the returned values.
"""

from random import randint, sample, shuffle

from .constants import SCREEN_WIDTH

# Spacing and screen area the wall is laid out on
X_SPACE = 30
Y_SPACE = 15
X_MAX = SCREEN_WIDTH
# the bottom 90 pixels stay free for the game info
Y_MAX = 990
Y_MARGIN = 30

# Reference aspect ratio of the artwork (4:3)
ASPECT_BASE = 1.3333

# Image control variants of a wall cell: a stretched picture (horizontal
# and vertical games) and one that keeps the aspect ratio of the file
# (NotScaled). Kodi sets the aspect mode only in the control constructor,
# so every cell owns one control of each variant.
STRETCH = 'stretch'
KEEP = 'keep'

# Wall titles modes
TITLES = "Titles"
RANDOM = "Random"


def resolve_rows(wall, row_picker=randint):
    """Return the row count to use for the current wall.

    ``wall`` is the wall settings dictionary. The returned flag is
    ``False`` when the configured titles mode is unknown - the caller logs
    that, the layout continues with the snap rows.
    """

    rows = wall['srows']
    rows_b = wall['srows_b']
    known = True
    if wall['titles'] == TITLES:
        rows = wall['trows']
        rows_b = wall['trows_b']
    elif wall['titles'] == RANDOM:
        if row_picker(0, 1):
            rows = wall['trows']
            rows_b = wall['trows_b']
    else:
        known = False

    if rows < rows_b:
        rows = row_picker(rows, rows_b)
    else:
        rows = row_picker(rows_b, rows)
    return rows, known


def compute_grid(rows, ar_norm, ar_x):
    """Return the cell geometry of a wall with ``rows`` rows.

    The result holds the cell width/height, the number of columns, the
    vertical spacing, the geometry of vertical images and the total number
    of cells.
    """

    width = int((X_MAX-(rows+1)*X_SPACE)/rows)
    height = int(width/ASPECT_BASE/ar_norm*ar_x)
    cols = int((Y_MAX-Y_MARGIN)/height)
    evspace = int((Y_MAX-height*cols)/(cols+1))
    if cols > 1:
        # cell_positions starts at Y_SPACE: the last row must not pass Y_MAX
        evspace = min(evspace, int((Y_MAX-Y_SPACE-height*cols)/(cols-1)))
    vert_width = int(height/ASPECT_BASE*ar_norm/ar_x)
    vert_x = int((width-vert_width)/2)
    return {
        'width': width,
        'height': height,
        'cols': cols,
        'evspace': evspace,
        'vert_width': vert_width,
        'vert_x': vert_x,
        'pics': rows*cols,
    }


def cell_positions(rows, cols, width, height, evspace):
    """Return the (x, y) position of every wall cell, row by row."""

    positions = []
    actual_x = X_SPACE
    actual_y = Y_SPACE
    for _column in range(cols):
        for _row in range(rows):
            positions.append((actual_x, actual_y))
            actual_x += width+X_SPACE
        actual_y += height+evspace
        actual_x = X_SPACE
    return positions


def cell_geometry(cell, aspect, grid):
    """Return ``(variant, x, y, width, height)`` of a picture in a wall cell.

    ``cell`` is the (x, y) position of the cell, ``aspect`` the aspect
    handling of the artwork and ``grid`` the cell geometry (``width``,
    ``height``, ``vert_width``, ``vert_x``). A vertical picture is narrower
    and centered in its cell; a ``NotScaled`` picture uses the ``KEEP``
    control, every other picture the ``STRETCH`` control.
    """

    pos_x, pos_y = cell
    if aspect == 'Vertical':
        return (STRETCH, pos_x + grid['vert_x'], pos_y,
                grid['vert_width'], grid['height'])
    if aspect == 'NotScaled':
        return KEEP, pos_x, pos_y, grid['width'], grid['height']
    return STRETCH, pos_x, pos_y, grid['width'], grid['height']


def free_slot_count(pics, free_percent):
    """Return how many wall cells are kept free for the background."""

    if free_percent == 0:
        return 0
    return round(pics-(pics*free_percent/100))


def shuffle_positions(positions):
    """Shuffle the position list of the wall in place."""

    shuffle(positions)
    return positions


def next_position(wall, lastpos, position_sampler=sample):
    """Return the next free wall position.

    The position list is refilled when it ran empty; the last element is
    popped first, so it must not repeat the previous position.
    """

    if not wall['pos']:
        pos = position_sampler(range(wall['pics']), wall['pics'])
        # the last element is popped first: it must not repeat the previous
        # position
        if len(pos) > 1 and pos[-1] == lastpos:
            pos[0], pos[-1] = pos[-1], pos[0]
        wall['pos'] = pos
    return wall['pos'].pop()
