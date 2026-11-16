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
from ui import icons, theme
import platform_support


class PlaceholderWidget(QWidget):
    """Schermata vuota: invita l'utente a usare la tab Trascrizione."""

    go_transcription_requested = Signal()
    import_file_requested = Signal()
    file_dropped = Signal(str)

    _DESC = "Apri o trascina qui un file video, audio, SRT o progetto V2SRT."

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True)
        self.setObjectName("editorPlaceholder")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._drag_over = False

        root = QVBoxLayout(self)
        root.setContentsMargins(48, 0, 48, 0)
        root.setAlignment(Qt.AlignCenter)
        root.addStretch(1)

        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignCenter)
        root.addWidget(self._icon)

        root.addSpacing(14)

        self._title = QLabel("Nessuna trascrizione")
        self._title.setAlignment(Qt.AlignCenter)
        root.addWidget(self._title)

        root.addSpacing(10)

        self._desc = QLabel(self._DESC)
        self._desc.setAlignment(Qt.AlignCenter)
        self._desc.setWordWrap(True)
        root.addWidget(self._desc)

        root.addSpacing(28)

        self._btn = QPushButton("Apri file…")
        self._btn.setObjectName("primary")
        self._btn.setMinimumHeight(32)
        self._btn.setMinimumWidth(200)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setToolTip(f"Apri file  {platform_support.shortcut_label('Ctrl+O')}")
        self._btn.clicked.connect(self.import_file_requested)
        root.addWidget(self._btn, 0, Qt.AlignCenter)

        root.addStretch(1)

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    # ── Tema ───────────────────────────────────────────────────────────────────

    def _apply_palette(self, _name=None):
        c = theme.c
        # Rilascio di un file: bordo da 1 px in accento (nessuna card, nessuna ombra)
        self.setStyleSheet(
            f"QWidget#editorPlaceholder {{ background: {c('bg')}; border: 1px solid transparent; }}"
            f"QWidget#editorPlaceholder[dragOver=\"true\"] {{ border: 1px solid {c('acc')}; }}"
        )
        self._icon.setStyleSheet("background: transparent; border: none;")
        self._icon.setPixmap(icons.pixmap("document", theme.qcolor("dim"), 32))
        self._title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {c('dim')}; background: transparent;"
        )
        self._set_desc(self._desc.text(), error=getattr(self, "_desc_error", False))

    def _set_desc(self, text: str, error: bool = False):
        self._desc_error = error
        self._desc.setText(text)
        self._desc.setStyleSheet(
            f"font-size: 13px; color: {theme.c('err' if error else 'dim')};"
            " background: transparent;"
        )

    def _set_hover(self, active: bool):
        self._drag_over = active
        self.setProperty("dragOver", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent):
        # Si accettano tutti i file locali: quelli non supportati vengono rifiutati
        # al rilascio con un messaggio (non ignorati in silenzio).
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
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
            self._set_desc(self._DESC)
            self.file_dropped.emit(path)
            event.acceptProposedAction()
            return
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        ext = Path(urls[0]).suffix.lower() if urls else ""
        self._set_desc(
            f"Formato {ext or 'del file'} non supportato. " + self._DESC, error=True
        )
        event.acceptProposedAction()

    def _first_supported_path(self, event) -> str:
        if not event.mimeData().hasUrls():
            return ""
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in SUPPORTED_ALL_EXTS:
                return path
        return ""
