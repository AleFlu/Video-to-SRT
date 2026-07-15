"""
project_tab_bar.py — ProjectTabBar: tab bar dinamica per i progetti aperti.

Layout:
  ┌────────────────────────────────────────────────────────────────┐
  │  [Progetto 1 ×]  [video.mp4 ● ×]  [Progetto 3 ×]  [+]  spaz │
  └────────────────────────────────────────────────────────────────┘

Ogni tab ha:
  - Titolo (aggiornato da ProjectWidget.title_changed)
  - Badge ● arancio (modificato non salvato, da ProjectWidget.modified_changed)
  - Pulsante × per chiudere

Segnali:
  tab_selected(int)    — indice progetto selezionato (0-based)
  tab_close_requested(int)  — utente ha cliccato × su tab indice
  new_tab_requested()  — utente ha cliccato +
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QSizePolicy,
    QScrollArea, QFrame,
)
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QShortcut


_TAB_MIN_W = 110
_TAB_MAX_W = 200

# Strip background — stessa tinta della drop zone e del tab interno
_BG_STRIP   = "#1a1d24"
_BG_ACTIVE  = "#22262f"
_BG_HOVER   = "#1f232c"
_ACCENT     = "#5b5bf0"
_TEXT_ACTIVE = "#e4e4ef"
_TEXT_INACTIVE = "#6a6a7a"
_BORDER_INNER  = "#1e1e26"   # sottile separatore tra tab, quasi invisibile


class _TabButton(QWidget):
    """Singola tab: titolo + badge + × (nascosta, appare su hover/attivo)."""

    close_clicked = Signal()
    tab_clicked   = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        self._active = False
        self._hovered = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(5)

        self._lbl = QLabel(title)
        self._lbl.setFixedHeight(34)
        self._lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(self._lbl, 1)

        self._badge = QLabel("●")
        self._badge.setStyleSheet(
            "color: #f39c12; font-size: 8px; background: transparent; padding: 0;"
        )
        self._badge.setVisible(False)
        layout.addWidget(self._badge)

        # × — sempre nel layout, visibilità gestita via enterEvent/leaveEvent
        self._close = QPushButton("✕")
        self._close.setObjectName("tabClose")
        self._close.setFixedSize(18, 18)
        self._close.setFlat(True)
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.clicked.connect(self.close_clicked)
        self._close.setVisible(False)
        layout.addWidget(self._close)

        self.set_active(False)

    def set_title(self, title: str):
        fm = QFontMetrics(self._lbl.font())
        elided = fm.elidedText(title, Qt.ElideMiddle, _TAB_MAX_W - 64)
        self._lbl.setText(elided)
        self._lbl.setToolTip(title if elided != title else "")

    def set_modified(self, modified: bool):
        self._badge.setVisible(modified)

    # ── Stile chiusura ─────────────────────────────────────────────────────────
    _CLOSE_STYLE_INACTIVE = (
        "QPushButton#tabClose {"
        "  background: transparent;"
        "  color: #5a5a6e;"
        "  border: none;"
        "  font-size: 11px;"
        "  padding: 0;"
        "  border-radius: 4px;"
        "}"
        "QPushButton#tabClose:hover {"
        "  color: #e45a5a;"
        "  background: rgba(228, 90, 90, 0.15);"
        "}"
    )
    _CLOSE_STYLE_ACTIVE = (
        "QPushButton#tabClose {"
        "  background: transparent;"
        "  color: #7a7a9a;"
        "  border: none;"
        "  font-size: 11px;"
        "  padding: 0;"
        "  border-radius: 4px;"
        "}"
        "QPushButton#tabClose:hover {"
        "  color: #e45a5a;"
        "  background: rgba(228, 90, 90, 0.15);"
        "}"
    )

    def set_active(self, active: bool):
        self._active = active
        if active:
            # Tab attiva: sfondo distinguibile, bordo accent in basso, nessun bordo laterale divisore
            self.setStyleSheet(
                f"QWidget {{"
                f"  background-color: {_BG_ACTIVE};"
                f"  border-bottom: 2px solid {_ACCENT};"
                f"  border-top: 1px solid #2a2a3a;"
                f"  border-left: 1px solid #2a2a3a;"
                f"  border-right: 1px solid #2a2a3a;"
                f"  border-radius: 6px 6px 0 0;"
                f"}}"
            )
            self._lbl.setStyleSheet(
                f"color: {_TEXT_ACTIVE}; font-size: 12px; font-weight: 600; background: transparent;"
            )
            self._close.setStyleSheet(self._CLOSE_STYLE_ACTIVE)
        else:
            self.setStyleSheet(
                "QWidget {"
                "  background-color: transparent;"
                "  border: 1px solid transparent;"
                "  border-bottom: 2px solid transparent;"
                "  border-radius: 6px 6px 0 0;"
                "}"
                f"QWidget:hover {{"
                f"  background-color: {_BG_HOVER};"
                f"  border: 1px solid #22222e;"
                f"  border-bottom: 2px solid transparent;"
                f"}}"
            )
            self._lbl.setStyleSheet(
                f"color: {_TEXT_INACTIVE}; font-size: 12px; font-weight: 400; background: transparent;"
            )
            self._close.setStyleSheet(self._CLOSE_STYLE_INACTIVE)

    def enterEvent(self, event):
        self._hovered = True
        self._close.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if not self._active:
            self._close.setVisible(False)
        else:
            # tab attiva: mostra × solo su hover, nascondi al leaveEvent anche se attiva
            self._close.setVisible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.tab_clicked.emit()
        super().mousePressEvent(event)


class ProjectTabBar(QWidget):
    """
    Barra tab dinamica per N progetti (max 8).
    Scorribile orizzontalmente se le tab non ci stanno.
    """

    tab_selected        = Signal(int)
    tab_close_requested = Signal(int)
    new_tab_requested   = Signal()

    _MAX_PROJECTS = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setStyleSheet(
            f"background-color: {_BG_STRIP};"
            "border-bottom: 1px solid #0d0d12;"
        )

        self._tabs: list[_TabButton] = []
        self._current = -1

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 0, 4, 0)
        outer.setSpacing(0)

        # Area scorribile per le tab
        self._scroll = QScrollArea()
        self._scroll.setFixedHeight(34)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(f"background: {_BG_STRIP}; border: none;")

        self._tabs_widget = QWidget()
        self._tabs_widget.setStyleSheet(f"background: {_BG_STRIP};")
        self._tabs_layout = QHBoxLayout(self._tabs_widget)
        self._tabs_layout.setContentsMargins(0, 0, 0, 0)
        self._tabs_layout.setSpacing(2)   # piccolo gap tra tab invece di bordo divisore
        self._tabs_layout.addStretch(1)

        # Bottone + — vive DENTRO il layout delle tab, subito dopo l'ultima
        self._btn_new = QPushButton("+")
        self._btn_new.setFixedSize(26, 26)
        self._btn_new.setFlat(False)
        self._btn_new.setToolTip("Nuovo progetto  (⌘⇧T)")
        self._btn_new.setCursor(Qt.PointingHandCursor)
        # Font esplicito via Python — immune al tema globale Qt che sovrascrive font-size nel CSS
        _plus_font = QFont()
        _plus_font.setPixelSize(18)
        _plus_font.setWeight(QFont.Light)
        self._btn_new.setFont(_plus_font)
        self._btn_new.setStyleSheet(
            "QPushButton {"
            "  background: #252535;"
            "  color: #b0b0c8;"
            "  border: 1px solid #32324a;"
            "  border-radius: 6px;"
            "  padding: 0;"
            "}"
            "QPushButton:hover {"
            "  background: #2e2e45;"
            "  color: #e4e4ef;"
            "  border-color: #5b5bf0;"
            "}"
            "QPushButton:pressed {"
            "  background: #1e1e34;"
            "}"
        )
        self._btn_new.clicked.connect(self._on_new_clicked)
        # Inserito in posizione 0 nel layout (prima dello stretch);
        # verrà riposizionato da _reinsert_plus_button() dopo ogni add/remove tab
        self._tabs_layout.insertWidget(0, self._btn_new)

        self._scroll.setWidget(self._tabs_widget)
        outer.addWidget(self._scroll, 1)

        # ── Shortcut ──────────────────────────────────────────────────────────
        sc_close = QShortcut(QKeySequence("Ctrl+W"), self)
        sc_close.setContext(Qt.ApplicationShortcut)
        sc_close.activated.connect(self._shortcut_close_current)

        sc_next = QShortcut(QKeySequence("Ctrl+Shift+]"), self)
        sc_next.setContext(Qt.ApplicationShortcut)
        sc_next.activated.connect(self._shortcut_next_tab)

        sc_prev = QShortcut(QKeySequence("Ctrl+Shift+["), self)
        sc_prev.setContext(Qt.ApplicationShortcut)
        sc_prev.activated.connect(self._shortcut_prev_tab)

        sc_new = QShortcut(QKeySequence("Ctrl+Shift+T"), self)
        sc_new.setContext(Qt.ApplicationShortcut)
        sc_new.activated.connect(self._on_new_clicked)

    # ── Shortcut handlers ──────────────────────────────────────────────────────

    def _shortcut_close_current(self):
        if self._current >= 0:
            self.tab_close_requested.emit(self._current)

    def _shortcut_next_tab(self):
        n = len(self._tabs)
        if n > 1:
            self.select_tab((self._current + 1) % n)

    def _shortcut_prev_tab(self):
        n = len(self._tabs)
        if n > 1:
            self.select_tab((self._current - 1) % n)

    # ── API pubblica ───────────────────────────────────────────────────────────

    def _reinsert_plus_button(self):
        """Sposta il + subito dopo l'ultima tab (prima dello stretch)."""
        self._tabs_layout.removeWidget(self._btn_new)
        self._tabs_layout.insertWidget(len(self._tabs), self._btn_new)

    def add_tab(self, title: str) -> int:
        """Aggiunge una tab e la seleziona. Restituisce l'indice."""
        idx = len(self._tabs)
        tab = _TabButton(title)
        tab.set_title(title)

        self._tabs_layout.insertWidget(idx, tab)
        self._tabs.append(tab)

        self._reinsert_plus_button()

        tab.tab_clicked.connect(lambda i=idx: self._on_tab_clicked_by_ref(tab))
        tab.close_clicked.connect(lambda i=idx: self._on_close_clicked_by_ref(tab))

        self.select_tab(idx)
        return idx

    def remove_tab(self, index: int):
        """Rimuove la tab all'indice. Non chiama can_close() — lo fa MainWindow."""
        if index < 0 or index >= len(self._tabs):
            return
        tab = self._tabs.pop(index)
        self._tabs_layout.removeWidget(tab)
        tab.deleteLater()

        n = len(self._tabs)
        if n == 0:
            self._current = -1
        elif self._current >= n:
            self._current = n - 1
            self._tabs[self._current].set_active(True)
        elif self._current == index:
            new = min(index, n - 1)
            self._current = -1
            self.select_tab(new)
        else:
            if self._current > index:
                self._current -= 1
            self._tabs[self._current].set_active(True)

        self._reinsert_plus_button()

    def select_tab(self, index: int):
        if index < 0 or index >= len(self._tabs):
            return
        if index == self._current:
            return
        if self._current >= 0 and self._current < len(self._tabs):
            self._tabs[self._current].set_active(False)
        self._current = index
        self._tabs[index].set_active(True)
        self.tab_selected.emit(index)

    def current_index(self) -> int:
        return self._current

    def set_tab_title(self, index: int, title: str):
        if 0 <= index < len(self._tabs):
            self._tabs[index].set_title(title)

    def set_tab_modified(self, index: int, modified: bool):
        if 0 <= index < len(self._tabs):
            self._tabs[index].set_modified(modified)

    def count(self) -> int:
        return len(self._tabs)

    def can_add(self) -> bool:
        return len(self._tabs) < self._MAX_PROJECTS

    # ── Slot privati ───────────────────────────────────────────────────────────

    def _on_new_clicked(self):
        if not self.can_add():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Limite raggiunto",
                f"Puoi aprire al massimo {self._MAX_PROJECTS} progetti simultaneamente.",
            )
            return
        self.new_tab_requested.emit()

    def _on_tab_clicked_by_ref(self, tab: _TabButton):
        try:
            idx = self._tabs.index(tab)
        except ValueError:
            return
        self.select_tab(idx)

    def _on_close_clicked_by_ref(self, tab: _TabButton):
        try:
            idx = self._tabs.index(tab)
        except ValueError:
            return
        self.tab_close_requested.emit(idx)
