"""Wiring of the workflow contexts.

Every workflow module gets a context of its own: the shared building blocks
it needs (``umsa_gui.state``), the few callbacks of the window and the
contexts of the modules it calls. ``build_contexts`` creates them once.
"""

from dataclasses import dataclass

from .artwork_presenter import ArtworkCtx
from .emulator_setup import EmulatorSetupCtx
from .filter_ui import FilterCtx
from .gamelist import GamelistUiCtx
from .gamelist_actions import GamelistActionsCtx
from .media_list import MediaCtx
from .menu import MenuCtx
from .scan_orchestrator import ScanCtx
from .screensaver_vgm import ScreensaverCtx
from .software_selector import SoftwareCtx
from .startup_import import ImportCtx


@dataclass
class Contexts:
    """The context of every workflow module, named like its module."""

    menu: MenuCtx
    screensaver_vgm: ScreensaverCtx
    filter_ui: FilterCtx
    artwork_presenter: ArtworkCtx
    emulator_setup: EmulatorSetupCtx
    software_selector: SoftwareCtx
    startup_import: ImportCtx
    gamelist: GamelistUiCtx
    media_list: MediaCtx
    gamelist_actions: GamelistActionsCtx
    scan_orchestrator: ScanCtx


def build_contexts(*, view, services, history, software, filters, listing,
                   settings, settle, run_emulator, exit):
    """Create the contexts of all workflow modules from the shared blocks.

    ``settle`` is the ``GamelistSettle`` of the window, ``run_emulator`` and
    ``exit`` are its callbacks.
    """

    menu = MenuCtx(
        view=view, services=services, software=software, history=history,
        listing=listing, filters=filters)
    artwork = ArtworkCtx(
        view=view, services=services, software=software, settings=settings,
        menu=menu)
    emulator = EmulatorSetupCtx(
        view=view, services=services, software=software, settings=settings,
        run_emulator=run_emulator)
    selector = SoftwareCtx(
        view=view, services=services, software=software, history=history,
        settings=settings, artwork=artwork)
    gamelist = GamelistUiCtx(
        view=view, services=services, listing=listing, software=software,
        history=history, settings=settings, settle=settle, menu=menu,
        selector=selector)
    # the media list fills the game list, the game list opens the media list
    media = MediaCtx(services=services, software=software, gamelist=gamelist)
    gamelist.media = media

    return Contexts(
        menu=menu,
        screensaver_vgm=ScreensaverCtx(
            view=view, services=services, settings=settings),
        filter_ui=FilterCtx(
            view=view, services=services, filters=filters, listing=listing),
        artwork_presenter=artwork,
        emulator_setup=emulator,
        software_selector=selector,
        startup_import=ImportCtx(services=services),
        gamelist=gamelist,
        media_list=media,
        gamelist_actions=GamelistActionsCtx(
            view=view, services=services, software=software, listing=listing,
            settings=settings, run_emulator=run_emulator, exit=exit,
            emulator=emulator, gamelist=gamelist, artwork=artwork,
            selector=selector),
        scan_orchestrator=ScanCtx(
            view=view, services=services, settings=settings, filters=filters,
            listing=listing, exit=exit),
    )
