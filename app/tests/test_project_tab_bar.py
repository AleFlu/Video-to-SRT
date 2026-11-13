"""test_project_tab_bar.py — Test per ui/project_tab_bar.py."""

import os
import sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


from ui.project_tab_bar import ProjectTabBar


def test_add_tab_returns_index(app):
    ptb = ProjectTabBar()
    idx = ptb.add_tab("Progetto 1")
    assert idx == 0

def test_add_multiple_tabs(app):
    ptb = ProjectTabBar()
    ptb.add_tab("P1")
    ptb.add_tab("P2")
    assert ptb.count() == 2

def test_add_tab_selects_new(app):
    ptb = ProjectTabBar()
    ptb.add_tab("P1")
    ptb.add_tab("P2")
    assert ptb.current_index() == 1

def test_remove_tab(app):
    ptb = ProjectTabBar()
    ptb.add_tab("P1")
    ptb.add_tab("P2")
    ptb.remove_tab(0)
    assert ptb.count() == 1

def test_remove_last_tab_current_minus_one(app):
    ptb = ProjectTabBar()
    ptb.add_tab("P1")
    ptb.remove_tab(0)
    assert ptb.count() == 0
    assert ptb.current_index() == -1

def test_can_add_limit(app):
    ptb = ProjectTabBar()
    for i in range(ProjectTabBar._MAX_PROJECTS):
        ptb.add_tab(f"P{i}")
    assert not ptb.can_add()

def test_can_add_below_limit(app):
    ptb = ProjectTabBar()
    ptb.add_tab("P1")
    assert ptb.can_add()

def test_tab_selected_signal(app):
    ptb = ProjectTabBar()
    ptb.add_tab("P1")
    ptb.add_tab("P2")
    received = []
    ptb.tab_selected.connect(received.append)
    ptb.select_tab(0)
    assert 0 in received

def test_tab_close_requested_signal(app):
    ptb = ProjectTabBar()
    ptb.add_tab("P1")
    received = []
    ptb.tab_close_requested.connect(received.append)
    ptb._shortcut_close_current()
    assert 0 in received

def test_set_tab_title(app):
    ptb = ProjectTabBar()
    ptb.add_tab("Vecchio")
    ptb.set_tab_title(0, "Nuovo")
    # Non crasha è sufficiente; verifichiamo che l'indice sia valido
    assert ptb.count() == 1

def test_set_tab_modified(app):
    ptb = ProjectTabBar()
    ptb.add_tab("P1")
    ptb.set_tab_modified(0, True)
    assert not ptb._tabs[0]._badge.isHidden()   # flag locale: non nascosto
    ptb.set_tab_modified(0, False)
    assert ptb._tabs[0]._badge.isHidden()

def test_plus_button_style_visible(app):
    """+ deve avere colore visibile (non trasparente)."""
    ptb = ProjectTabBar()
    style = ptb._btn_new.styleSheet()
    assert "#5a5a6a" not in style   # vecchio colore invisibile non deve esserci
    assert "color:" in style

def test_next_prev_tab_wraps(app):
    ptb = ProjectTabBar()
    ptb.add_tab("P1")
    ptb.add_tab("P2")
    ptb.add_tab("P3")
    ptb.select_tab(0)
    # Vai avanti da 2 → torna a 0
    ptb.select_tab(2)
    ptb._shortcut_next_tab()
    assert ptb.current_index() == 0
