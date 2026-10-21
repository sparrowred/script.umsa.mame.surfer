"""Optional Kodi plugin bridges.

The PDF reader and the YouTube plugin are optional add-on dependencies: the
frontend must start when they are missing.
"""

try:
    from pdf import play_pdf
    KODIPDF = True
except Exception:
    KODIPDF = False
    play_pdf = None

try:
    import youtube_plugin  # noqa: F401
    KODIYT = True
except ImportError:
    KODIYT = False
