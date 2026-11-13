"""test_tab_bar.py — Test per ui/tab_bar.py (no Qt display required con offscreen)."""

import os
import sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    return a


from ui.tab_bar import TabBar, _TAB_TRANSCRIPTION, _TAB_EDITOR, _TAB_EXPORT


def test_tab_bar_initial_state(app):
    tb = TabBar()
    assert tb.current() == _TAB_TRANSCRIPTION

def test_tab_bar_set_current_editor(app):
    tb = TabBar()
    received = []
    tb.tab_changed.connect(received.append)
    tb.set_current(_TAB_EDITOR)
    assert tb.current() == _TAB_EDITOR
    assert received == [_TAB_EDITOR]

def test_tab_bar_set_current_export(app):
    tb = TabBar()
    received = []
    tb.tab_changed.connect(received.append)
    tb.set_current(_TAB_EXPORT)
    assert tb.current() == _TAB_EXPORT
    assert received == [_TAB_EXPORT]

def test_tab_bar_no_signal_on_same_tab(app):
    tb = TabBar()
    received = []
    tb.tab_changed.connect(received.append)
    tb.set_current(_TAB_TRANSCRIPTION)   # già su Trascrizione
    assert received == []

def test_tab_bar_editor_badge_hidden_by_default(app):
    tb = TabBar()
    # Non mostrato esplicitamente → isHidden() è il flag locale
    assert tb._badge.isHidden()

def test_tab_bar_editor_badge_show_hide(app):
    tb = TabBar()
    tb.set_editor_badge(True)
    assert not tb._badge.isHidden()   # flag locale: non nascosto
    tb.set_editor_badge(False)
    assert tb._badge.isHidden()

def test_tab_bar_three_tabs_exist(app):
    tb = TabBar()
    # Tutti e tre i bottoni devono esistere
    assert tb._btn_transcription is not None
    assert tb._btn_editor is not None
    assert tb._btn_export is not None

def test_tab_bar_constants():
    assert _TAB_TRANSCRIPTION == 0
    assert _TAB_EDITOR == 1
    assert _TAB_EXPORT == 2

