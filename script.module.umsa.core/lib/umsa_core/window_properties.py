"""Names of the Kodi window properties shared by the UMSA add-ons.

Frontend, screensaver and the Kodi adapter exchange state through properties
on Kodi's home window. A property name is only a string, so it is defined here
once and every add-on imports it; a copy in one add-on would silently break the
coupling when the other side is renamed. The screensaver skin
(``umsa_saver.xml``) has to repeat ``SCREENSAVER_MODE_PROPERTY`` literally; a
test keeps it in sync. Kodi-free: only names, no Kodi calls.
"""

SHARED_WINDOW_ID = 10000

SCREENSAVER_MODE_PROPERTY = "UMSA.Screensaver.Mode"
SCREENSAVER_RUNNING_PROPERTY = "UMSA.Screensaver.Running"
SCREENSAVER_MANUAL_PROPERTY = "UMSA.Screensaver.Manual"
EMULATOR_RUNNING_PROPERTY = "UMSA.Emulator.Running"
# set while the frontend window is open (maintenance closes it first)
FRONTEND_RUNNING_PROPERTY = "UMSA.Frontend.Running"
