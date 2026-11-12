"""Localized texts of the UMSA screensaver.

The notifications of the screensaver come from
``resources/language/*/strings.po`` of the screensaver add-on; the constants
below name the string ids (range 32300-32399, the settings use 30xxx/320xx).
``tr()`` returns the text in the language of Kodi.

``tests/arch/test_localized_strings.py`` keeps this module and the English
``strings.po`` in step.
"""

import xbmc
import xbmcaddon

ADDON_ID = 'screensaver.umsa.mame.surfer'

# notifications
NOTIFICATION_HEADING = 32300
NO_ARTWORK = 32301
NO_USABLE_ARTWORK = 32302
ARTWORK_CHECK_FAILED = 32303
NO_VIDEOS = 32304
NO_VIDEOS_FOUND = 32305
NO_VIDEO_MODE_WITH_MUSIC = 32306


def tr(string_id, *args):
    """Return the localized text ``string_id`` with ``args`` filled in."""

    text = xbmcaddon.Addon(id=ADDON_ID).getLocalizedString(string_id)
    if not args:
        return text
    try:
        return text.format(*args)
    except (IndexError, KeyError, ValueError) as error:
        # a broken translation must not stop the screensaver
        xbmc.log(
            f"UMSA Screensaver: text {string_id} has bad placeholders: {error}",
            xbmc.LOGWARNING)
        return text
