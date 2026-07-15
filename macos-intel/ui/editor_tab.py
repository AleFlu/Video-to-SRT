"""
editor_tab.py — EditorTab: wrapper dell'editor con InlineProgressBar e Placeholder.

Layout:
  ┌───────────────────────────────────────────────┐
  │  InlineProgressBar (h=28px, hidden by default) │
  ├───────────────────────────────────────────────┤
  │  QStackedWidget                               │
  │    [0] PlaceholderWidget  (nessun sub)        │
  │    [1] WorkspaceWidget    (preview+timeline)  │
  └───────────────────────────────────────────────┘

InlineProgressBar (INV4): visibile ↔ worker attivo.

Segnali:
  go_transcription_requested()  — dal placeholder → switch tab Trascrizione
  import_requested(str)         — richiesta apertura file dal placeholder/toolbar
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QStackedWidget,
    QProgressBar, QLabel, QHBoxLayout, QSizePolicy,
)

from core.constants import FILE_FILTER_IMPORT_ALL
from ui.placeholder_widget import PlaceholderWidget
from ui.workspace import WorkspaceWidget


_SLOT_PLACEHOLDER = 0
_SLOT_WORKSPACE   = 1


class EditorTab(QWidget):
    """Wrapper dell'editor: InlineProgressBar + stack Placeholder/Workspace."""

    go_transcription_requested = Signal()
    import_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── InlineProgressBar ──────────────────────────────────────────────────
        self._inline_bar_container = QWidget()
        self._inline_bar_container.setFixedHeight(28)
        self._inline_bar_container.setStyleSheet("background-color: #111114;")
        self._inline_bar_container.setVisible(False)

        ibl = QHBoxLayout(self._inline_bar_container)
        ibl.setContentsMargins(10, 4, 10, 4)
        ibl.setSpacing(8)

        self._inline_lbl = QLabel("Trascrizione in corso…")
        self._inline_lbl.setStyleSheet(
            "color: #8a8a9a; font-size: 11px; background: transparent;"
        )
        ibl.addWidget(self._inline_lbl)

        self._inline_progress = QProgressBar()
        self._inline_progress.setRange(0, 1000)
        self._inline_progress.setValue(0)
        self._inline_progress.setFixedHeight(4)
        self._inline_progress.setTextVisible(False)
        ibl.addWidget(self._inline_progress, 1)

        root.addWidget(self._inline_bar_container)

        # ── Stack: Placeholder | Workspace ─────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.placeholder = PlaceholderWidget()
        self.workspace   = WorkspaceWidget()

        self._stack.addWidget(self.placeholder)   # 0
        self._stack.addWidget(self.workspace)     # 1

        root.addWidget(self._stack, 1)

        # ── Wiring ─────────────────────────────────────────────────────────────
        self.placeholder.go_transcription_requested.connect(self.go_transcription_requested)
        self.placeholder.import_file_requested.connect(self._on_import_from_toolbar)
        self.placeholder.file_dropped.connect(self.import_requested)

    # ── API pubblica ───────────────────────────────────────────────────────────

    def show_workspace(self):
        self._stack.setCurrentIndex(_SLOT_WORKSPACE)

    def show_placeholder(self):
        self._stack.setCurrentIndex(_SLOT_PLACEHOLDER)

    def has_content(self) -> bool:
        return self._stack.currentIndex() == _SLOT_WORKSPACE

    def _on_import_from_toolbar(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "Apri file…", "", FILE_FILTER_IMPORT_ALL
        )
        if path:
            self.import_requested.emit(path)

    # ── InlineProgressBar ──────────────────────────────────────────────────────

    def inline_progress_show(self, label: str = "Trascrizione in corso…"):
        """INV4: mostra la barra inline (worker attivo)."""
        self._inline_lbl.setText(label)
        self._inline_progress.setValue(0)
        self._inline_bar_container.setVisible(True)

    def inline_progress_update(self, pct: float):
        """Aggiorna la percentuale (0.0–1.0)."""
        self._inline_progress.setValue(int(pct * 1000))

    def inline_progress_hide(self):
        """INV4: nasconde la barra inline (worker terminato)."""
        self._inline_bar_container.setVisible(False)
        self._inline_progress.setValue(0)
