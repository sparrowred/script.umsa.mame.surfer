"""Shared startup dispatch for both Kodi screensaver entry points."""


def run_automatic():
    """Start using this add-on's persisted settings."""

    from .runtime import ScreensaverRuntime

    ScreensaverRuntime().run_automatic()


def run_script(arguments):
    """Start from a script invocation using validated per-run arguments."""

    from .runtime import ScreensaverRuntime

    ScreensaverRuntime().run_script(arguments)
