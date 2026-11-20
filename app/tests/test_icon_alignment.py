"""
test_icon_alignment.py — Icone centrate in verticale.

Prima: la × delle tab progetto e la lente della ricerca stavano ~4 px sotto il centro. La ×
(20×20) veniva allungata a 28 px dall'altezza minima globale dei pulsanti; i pulsantini
interni del QLineEdit (lente, cancella) erano messi da Qt a y=4 in un campo alto 26–28 px.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QToolButton

import platform_support


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(platform_support, "legacy_cache_dirs", lambda: [])
    from ui import theme
    theme.apply_theme(app, "dark")
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    win.resize(1500, 950)
    win.show()
    app.processEvents()
    yield win
    for pw in win._projects:
        pw.teardown()
    win.deleteLater()


def _center_y(w) -> float:
    return w.y() + w.height() / 2


def test_project_tab_close_is_centered(window, app):
    from ui.project_tab_bar import _TabButton
    tab = window.findChild(_TabButton)
    tab._close.setVisible(True)
    app.processEvents()
    assert tab._close.height() == 20
    assert _center_y(tab._close) == pytest.approx(tab.height() / 2, abs=0.5)


@pytest.mark.parametrize("height", [26, 28, 32])
def test_search_field_icons_are_centered(app, height):
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QLineEdit
    from ui import icons
    from ui.subtitle_timeline import _SearchField
    field = _SearchField("⌘F")
    field.setFixedSize(250, height)
    field.setClearButtonEnabled(True)
    act = QAction(field)
    act.setIcon(icons.icon("search", "dim"))
    field.addAction(act, QLineEdit.LeadingPosition)
    field.show()
    field.setText("ciao")            # mostra anche il pulsante per cancellare
    app.processEvents()
    buttons = [b for b in field.findChildren(QToolButton) if b.isVisible()]
    assert len(buttons) == 2

    def check():
        for b in buttons:
            assert b.height() <= field.height()
            assert _center_y(b) == pytest.approx(field.height() / 2, abs=0.5)

    check()
    # Sul Mac Qt crea i pulsantini alti 28 px e li mette a y=4, anche in un campo di 26:
    # qualunque posizione Qt scelga, vengono ricentrati
    for b in buttons:
        b.setGeometry(b.x(), 4, b.width(), 28)
    app.processEvents()
    check()
    field.setFixedSize(150, height)  # compattazione della toolbar: si riposizionano
    app.processEvents()
    check()


def _off_center_icon_buttons(window):
    bad = []
    for b in window.findChildren(QAbstractButton):
        par = b.parentWidget()
        if (not b.isVisible() or b.icon().isNull() or par is None
                or isinstance(par, QComboBox) or par.height() > 60):
            continue
        if abs(_center_y(b) - par.height() / 2) > 1.0:
            bad.append(f"{type(b).__name__} '{b.objectName() or b.accessibleName()}' "
                       f"y={b.y()} h={b.height()} in {par.objectName()} h={par.height()}")
    return bad


def test_no_icon_button_sits_low_in_home_and_editor(window, app):
    from core.subtitle_model import Subtitle
    assert _off_center_icon_buttons(window) == []
    pw = window._projects[0]
    subs = [Subtitle(i * 2.0, i * 2.0 + 1.5, f"Riga {i}") for i in range(5)]
    pw.workspace.load_result([{"start": s.start, "end": s.end, "text": s.text}
                              for s in subs], "")
    app.processEvents()
    assert _off_center_icon_buttons(window) == []
