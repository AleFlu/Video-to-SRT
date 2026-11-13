"""conftest.py — fixture condivise: QApplication unica e pulizia dei top-level widget."""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    """QApplication condivisa da tutti i test."""
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _cleanup_top_level_widgets():
    """Dopo ogni test chiude e distrugge i widget top-level rimasti (dialog senza parent
    inclusi), così non sopravvivono fino alla chiusura dell'interprete."""
    yield
    qapp = QApplication.instance()
    if qapp is None:
        return
    for w in QApplication.topLevelWidgets():
        try:
            w.close()
            w.deleteLater()
        except RuntimeError:
            pass
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
