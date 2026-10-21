"""Workflow modules of the UMSA frontend.

The package holds the GUI workflows that were extracted from the former
``resources/lib/gui.py`` god class. ``resources/lib/gui.py`` stays the public
entry module of the add-on: it keeps the ``UMSA`` Kodi dialog adapter and
re-exports the names that existed before the split.

Every module in this package receives the ``UMSA`` instance (or an explicit
context) as an argument instead of importing ``UMSA`` back, so the workflows
stay independently testable with Kodi stubs.
"""
