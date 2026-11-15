"""Shared building blocks of the frontend workflows.

The ``UMSA`` window creates one object of each class once and never replaces
it. The context of a workflow module (``MenuCtx``, ``SoftwareCtx``, ...) holds
references to the blocks the module needs, so a changed value - a new
``ggdb`` after the database update, the history pointer - is seen by every
module without copying it back.
"""

from dataclasses import dataclass, field

from .constants import KIND_SOFTWARE, SOFTWARE_BUTTON


class View:
    """Access to the skin controls of the window, and nothing else."""

    def __init__(self, window):
        self._window = window

    def getControl(self, control_id):
        return self._window.getControl(control_id)

    def setFocus(self, control):
        self._window.setFocus(control)


@dataclass
class Services:
    """Objects the window creates in ``onInit`` (and replaces: ``ggdb``)."""

    ggdb: object = None
    emulation: object = None
    player: object = None
    dialog: object = None
    emu_dialog: object = None
    progress_dialog: object = None
    # scan entry points and the progress of the active scan
    scans: object = None
    # abort-aware wait for long Core loops (umsa_core.abort.Wait)
    abort_wait: object = None
    # ProcessRunner of the external PDF viewer (gamelist_actions.open_manual)
    manual_viewer: object = None


@dataclass
class History:
    """Last selected software: only the ids, and the pointer into them."""

    last: list = field(default_factory=list)
    lastptr: int = 0


@dataclass
class SoftwareState:
    """The software the window shows."""

    # all sets of the software, one list per machine
    info: object = None
    # the selected set
    actset: object = None
    # (swl, set) the text list was built for
    oldset: tuple = ()
    all_art: object = None
    all_dat: object = None
    played: object = None
    # number of (videos, manuals)
    vidman: object = None
    # vgmplay sets of the software and their titles
    vgms: object = None
    vgm_titles: dict = field(default_factory=dict)
    # scanned machine cabinets (machine wraplist)
    machine_cabinets: dict = field(default_factory=dict)
    # a video played already when the add-on started: never stop it
    already_playing: object = None


@dataclass
class FilterState:
    """The filter that is edited and applied."""

    filter_lists: object = None
    act_filter: object = None
    # filter category shown in the filter content lists
    act_filter_category: object = None


@dataclass
class ListState:
    """What the game list shows and where the focus returns to."""

    # what the game list holds (KIND_*) and, for a "Select ..." list, the
    # menu code it was opened for
    gamelist_kind: str = KIND_SOFTWARE
    gamelist_select: object = None
    # submenu entry (M_*) whose list the game list shows, None otherwise
    listmode_shown: object = None
    # old search
    searchold: object = None
    # set when a gamelist select happens
    enter: object = None
    # remember main select when in gamelist
    main_focus: int = SOFTWARE_BUTTON
