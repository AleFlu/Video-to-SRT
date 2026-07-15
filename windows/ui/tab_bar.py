"""
tab_bar.py — TabBar custom con 3 tab: "Trascrizione" | "Editor [●]" | "Esportazione".

All'avvio solo "Trascrizione" è visibile e cliccabile.
Editor ed Esportazione appaiono solo dopo set_unlocked(True), cioè quando
ci sono sottotitoli disponibili (post-trascrizione o import).

Segnali:
  tab_changed(int)   — 0 = Trascrizione, 1 = Editor, 2 = Esportazione
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QSizePolicy


_TAB_TRANSCRIPTION = 0
_TAB_EDITOR        = 1
_TAB_EXPORT        = 2

_STYLE_ACTIVE = """
    QPushButton {
        background-color: #1a1d24;
        color: #e8eaf0;
        border: none;
        border-bottom: 2px solid #5b8cff;
        font-size: 13px;
        font-weight: 600;
        padding: 0 24px;
    }
"""

_STYLE_INACTIVE = """
    QPushButton {
        background-color: transparent;
        color: #6c727f;
        border: none;
        border-bottom: 2px solid transparent;
        font-size: 13px;
        font-weight: 400;
        padding: 0 24px;
    }
    QPushButton:hover {
        color: #a8aebb;
    }
"""


class TabBar(QWidget):
    """Barra tab: Trascrizione | Editor [●] | Esportazione.
    Editor e Esportazione nascosti finché non chiamato set_unlocked(True).
    """

    tab_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setStyleSheet("background-color: #1a1d24; border-bottom: 1px solid #000000;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._current = _TAB_TRANSCRIPTION
        self._unlocked = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(0)

        # ── Tab Trascrizione ───────────────────────────────────────────────────
        self._btn_transcription = QPushButton("Trascrizione")
        self._btn_transcription.setFixedHeight(40)
        self._btn_transcription.setCursor(Qt.PointingHandCursor)
        self._btn_transcription.clicked.connect(lambda: self.set_current(_TAB_TRANSCRIPTION))
        layout.addWidget(self._btn_transcription)

        # ── Tab Editor (con badge ●) ───────────────────────────────────────────
        self._editor_container = QWidget()
        self._editor_container.setFixedHeight(40)
        self._editor_container.setStyleSheet("background: transparent;")
        ec_layout = QHBoxLayout(self._editor_container)
        ec_layout.setContentsMargins(0, 0, 0, 0)
        ec_layout.setSpacing(4)

        self._btn_editor = QPushButton("Editor")
        self._btn_editor.setFixedHeight(40)
        self._btn_editor.setCursor(Qt.PointingHandCursor)
        self._btn_editor.clicked.connect(lambda: self.set_current(_TAB_EDITOR))
        ec_layout.addWidget(self._btn_editor)

        self._badge = QLabel("●")
        self._badge.setStyleSheet("color: #5b8cff; font-size: 10px; background: transparent;")
        self._badge.setVisible(False)
        ec_layout.addWidget(self._badge)

        self._editor_container.setVisible(False)   # nascosto fino a unlock
        layout.addWidget(self._editor_container)

        # ── Tab Esportazione ───────────────────────────────────────────────────
        self._export_container = QWidget()
        self._export_container.setFixedHeight(40)
        self._export_container.setStyleSheet("background: transparent;")
        exp_layout = QHBoxLayout(self._export_container)
        exp_layout.setContentsMargins(0, 0, 8, 0)
        exp_layout.setSpacing(6)

        self._btn_export = QPushButton("Esportazione")
        self._btn_export.setFixedHeight(40)
        self._btn_export.setCursor(Qt.PointingHandCursor)
        self._btn_export.clicked.connect(lambda: self.set_current(_TAB_EXPORT))
        exp_layout.addWidget(self._btn_export)

        self._export_badge = QLabel("")
        self._export_badge.setStyleSheet(
            "color: #e4e4ef; background-color: #3b3b8a; font-size: 10px;"
            " font-weight: 700; padding: 1px 5px; border-radius: 7px;"
        )
        self._export_badge.setVisible(False)
        exp_layout.addWidget(self._export_badge)

        self._export_container.setVisible(False)   # nascosto fino a unlock
        layout.addWidget(self._export_container)

        layout.addStretch(1)

        self._refresh_styles()

    # ── API pubblica ───────────────────────────────────────────────────────────

    def set_unlocked(self, unlocked: bool):
        """
        True  → mostra Editor e Esportazione (ci sono sottotitoli).
        False → nasconde Editor e Esportazione, torna a Trascrizione.
        """
        if self._unlocked == unlocked:
            return
        self._unlocked = unlocked
        self._editor_container.setVisible(unlocked)
        self._export_container.setVisible(unlocked)
        if not unlocked and self._current != _TAB_TRANSCRIPTION:
            self.set_current(_TAB_TRANSCRIPTION)

    def is_unlocked(self) -> bool:
        return self._unlocked

    def set_current(self, index: int):
        if index not in (_TAB_TRANSCRIPTION, _TAB_EDITOR, _TAB_EXPORT):
            return
        if index == self._current:
            return
        self._current = index
        self._refresh_styles()
        self.tab_changed.emit(index)

    def current(self) -> int:
        return self._current

    def set_editor_badge(self, visible: bool):
        """INV3: badge ● visibile ↔ project.subtitles non vuoti."""
        self._badge.setVisible(visible)

    def set_export_badge(self, count: int):
        # Mantenuto per compatibilità, badge non mostrato
        self._export_badge.setVisible(False)

    # ── Privato ────────────────────────────────────────────────────────────────

    def _refresh_styles(self):
        self._btn_transcription.setStyleSheet(
            _STYLE_ACTIVE if self._current == _TAB_TRANSCRIPTION else _STYLE_INACTIVE
        )
        self._btn_editor.setStyleSheet(
            _STYLE_ACTIVE if self._current == _TAB_EDITOR else _STYLE_INACTIVE
        )
        self._btn_export.setStyleSheet(
            _STYLE_ACTIVE if self._current == _TAB_EXPORT else _STYLE_INACTIVE
        )
