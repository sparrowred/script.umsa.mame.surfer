"""Workflow modules of the UMSA frontend.

The package holds the GUI workflows that were extracted from the former
``resources/lib/gui.py`` god class. ``resources/lib/gui.py`` stays the public
entry module of the add-on: it keeps the ``UMSA`` Kodi dialog adapter and
re-exports the names that existed before the split.

A workflow module never gets the ``UMSA`` window: its functions take the
context of the module (``MenuCtx``, ``SoftwareCtx`` ...), which holds the
shared state blocks it needs (``state``), a few callbacks of the window and
the contexts of the modules it calls directly. ``wiring.build_contexts``
creates all contexts once, so the workflows stay independently testable with
Kodi stubs.
"""
