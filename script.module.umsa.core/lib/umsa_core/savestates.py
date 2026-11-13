"""MAME save states of a set.

MAME keeps its save states in ``state_directory`` (mame.ini, default ``sta``
in the working directory) below the expanded ``-statename``: arcade sets use
MAME's default ``%g`` (``sta/<set>/``), software-list items get
``-statename %g/%d_<device>`` from :func:`umsa_core.cmdline.get_cmd_line_options`
(``sta/<machine>/<set>/``). One file per slot: ``<slot>.sta``. A state is
loaded at start with ``-state <slot>``.
"""

import os
from dataclasses import dataclass

from .logging import log

STATE_EXTENSION = '.sta'
DEFAULT_STATE_DIRECTORY = 'sta'


@dataclass(frozen=True)
class SaveState:
    """One save state file: slot name (file name without ``.sta``)."""

    slot: str
    path: str
    mtime: float


def state_directory(mame_ini, mame_dir):
    """Absolute MAME state directory: mame.ini value, else ``<mame_dir>/sta``.

    ``mame_ini`` holds already resolved paths
    (:func:`umsa_core.emulation.resolve_mame_paths`).
    """

    return (mame_ini.get('state_directory')
            or os.path.join(mame_dir, DEFAULT_STATE_DIRECTORY))


def state_subdir(actset, args):
    """Folder of the set's states below the state directory, or None.

    None when MAME would not keep the states per set: a software-list start
    without ``-statename`` (no device known) shares the machine's folder.
    """

    swl_name = actset.get('swl_name') or ''
    if swl_name == 'mame':
        return actset.get('name') or None
    if swl_name.startswith('gb64_'):
        return None
    if isinstance(args, list) and '-statename' in args and actset.get('machine_name'):
        return os.path.join(actset['machine_name'], actset['name'])
    return None


def list_savestates(state_dir, subdir):
    """Save states of one set, newest first; [] without folder or states."""

    if not state_dir or not subdir:
        return []
    folder = os.path.join(state_dir, subdir)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    states = []
    for name in names:
        slot, ext = os.path.splitext(name)
        if ext.lower() != STATE_EXTENSION or not slot:
            continue
        path = os.path.join(folder, name)
        try:
            if not os.path.isfile(path):
                continue
            mtime = os.path.getmtime(path)
        except OSError as error:
            log(f"UMSA savestates: skipping {path!r}: {error}", level='debug')
            continue
        states.append(SaveState(slot=slot, path=path, mtime=mtime))
    states.sort(key=lambda state: (-state.mtime, state.slot))
    return states


def with_savestate(args, slot):
    """MAME arguments that load ``slot`` at start (a new list)."""

    if isinstance(args, str):
        args = [args]
    return list(args) + ['-state', slot]
