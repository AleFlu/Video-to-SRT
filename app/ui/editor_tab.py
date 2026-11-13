"""
editor_tab.py — EditorTab: stack Placeholder / Workspace dell'editor.

Layout:
  ┌───────────────────────────────────────────────┐
  │  QStackedWidget                               │
  │    [0] PlaceholderWidget  (nessun sub)        │
  │    [1] WorkspaceWidget    (preview+timeline)  │
  └───────────────────────────────────────────────┘

Segnali:
  go_transcription_requested()  — dal placeholder → switch tab Trascrizione
  import_requested(str)         — richiesta apertura file dal placeholder/toolbar
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget, QSizePolicy

from core.constants import FILE_FILTER_IMPORT_ALL
from ui.placeholder_widget import PlaceholderWidget
from ui.workspace import WorkspaceWidget


_SLOT_PLACEHOLDER = 0
_SLOT_WORKSPACE   = 1


class EditorTab(QWidget):
    """Wrapper dell'editor: stack Placeholder/Workspace."""

    go_transcription_requested = Signal()
    import_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.placeholder = PlaceholderWidget()
        self.workspace   = WorkspaceWidget()

        self._stack.addWidget(self.placeholder)   # 0
        self._stack.addWidget(self.workspace)     # 1

        root.addWidget(self._stack, 1)

        self.placeholder.go_transcription_requested.connect(self.go_transcription_requested)
        self.placeholder.import_file_requested.connect(self._on_import_from_toolbar)
        self.placeholder.file_dropped.connect(self.import_requested)

    # ── API pubblica ───────────────────────────────────────────────────────────

    def show_workspace(self):
        self._stack.setCurrentIndex(_SLOT_WORKSPACE)

    def show_placeholder(self):
        self._stack.setCurrentIndex(_SLOT_PLACEHOLDER)

    def _on_import_from_toolbar(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "Apri file…", "", FILE_FILTER_IMPORT_ALL
        )
        if path:
            self.import_requested.emit(path)
