"""
placeholder_widget.py — PlaceholderWidget: schermata vuota dell'EditorTab.

Mostrato quando non ci sono sottotitoli. Accetta apertura file diretta per
compatibilità con il flusso editor/import.

Segnali:
  go_transcription_requested()   — clic su "Trascrivi file…"
  import_file_requested()        — clic su "Apri file…"
  file_dropped(str)              — drop di file supportato
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QSizePolicy,
)

from core.constants import SUPPORTED_ALL_EXTS
from ui import theme


class PlaceholderWidget(QWidget):
    """Schermata vuota: invita l'utente a usare la tab Trascrizione."""

    go_transcription_requested = Signal()
    import_file_requested = Signal()
    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True)
        self._drag_over = False

        root = QVBoxLayout(self)
        root.setContentsMargins(48, 0, 48, 0)
        root.setAlignment(Qt.AlignCenter)
        root.addStretch(1)

        self._icon = QLabel("◻")
        self._icon.setAlignment(Qt.AlignCenter)
        root.addWidget(self._icon)

        root.addSpacing(20)

        self._title = QLabel("Nessuna trascrizione")
        self._title.setAlignment(Qt.AlignCenter)
        root.addWidget(self._title)

        root.addSpacing(10)

        self._desc = QLabel("Apri un file video, audio, SRT o progetto V2SRT.")
        self._desc.setAlignment(Qt.AlignCenter)
        root.addWidget(self._desc)

        root.addSpacing(28)

        self._btn = QPushButton("Apri file…")
        self._btn.setObjectName("primary")
        self._btn.setMinimumHeight(40)
        self._btn.setMinimumWidth(200)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self.import_file_requested)
        root.addWidget(self._btn, 0, Qt.AlignCenter)

        root.addStretch(1)

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    # ── Tema ───────────────────────────────────────────────────────────────────

    def _apply_palette(self, _name=None):
        c = theme.c
        self._icon.setStyleSheet(
            f"font-size: 56px; color: {c('faint')}; background: transparent;"
        )
        self._title.setStyleSheet(
            f"font-size: 18px; font-weight: 600; color: {c('dim')}; background: transparent;"
        )
        self._desc.setStyleSheet(
            f"font-size: 13px; color: {c('muted')}; background: transparent;"
        )

    def _set_hover(self, active: bool):
        self._drag_over = active
        self.setProperty("dragOver", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent):
        path = self._first_supported_path(event)
        if path:
            self._set_hover(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_hover(False)
        event.accept()

    def dropEvent(self, event: QDropEvent):
        self._set_hover(False)
        path = self._first_supported_path(event)
        if path:
            self.file_dropped.emit(path)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _first_supported_path(self, event) -> str:
        if not event.mimeData().hasUrls():
            return ""
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in SUPPORTED_ALL_EXTS:
                return path
        return ""
