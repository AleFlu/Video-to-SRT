"""
test_toolbar_fit.py — La toolbar dell'editor si compatta invece di nascondere i comandi.

Bug (CI Windows, 39 test falliti): con una finestra stretta, o i font più larghi di Windows,
la casella "Cerca" e "Esporta SRT" finivano nel menu di overflow della toolbar; ⌘F/Ctrl+F
non portava più il focus da nessuna parte. Ora la toolbar toglie prima le scorciatoie
disegnate, poi le etichette (solo icona) e infine accorcia la ricerca; se la casella non si
vede comunque, Ctrl+F apre Trova e sostituisci.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _timeline_at(app, width: int):
    from ui.subtitle_timeline import SubtitleTimeline
    tl = SubtitleTimeline()
    tl.resize(width, 500)
    tl.show()
    for _ in range(3):
        app.processEvents()
    return tl


@pytest.mark.parametrize("width", [1400, 1000, 800, 700])
def test_toolbar_keeps_search_and_export_visible(app, width):
    tl = _timeline_at(app, width)
    tb = tl.toolbar()
    assert tb.sizeHint().width() <= tb.width(), (width, tl.toolbar_level())
    assert tl._search_box.isVisible()
    assert tl._export_btn.isVisible()


def test_toolbar_compacts_only_when_needed(app):
    wide = _timeline_at(app, 1600)
    narrow = _timeline_at(app, 700)
    assert wide.toolbar_level() == 0
    assert narrow.toolbar_level() > 0
    narrow.resize(1600, 500)
    app.processEvents()
    assert narrow.toolbar_level() == 0


def test_ctrl_f_focuses_search_in_a_narrow_window(app):
    tl = _timeline_at(app, 700)
    tl.activateWindow()
    tl.focus_search()
    app.processEvents()
    assert tl._search_box.hasFocus() or tl._search_box.isVisible()
    assert QApplication.focusWidget() is tl._search_box or not tl._search_box.isVisible()
