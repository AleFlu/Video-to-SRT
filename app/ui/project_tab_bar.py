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

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QScrollArea, QFrame,
)
from PySide6.QtGui import QFontMetrics, QKeySequence, QShortcut

from ui import icons, theme
import platform_support


_TAB_MIN_W = 110
_TAB_MAX_W = 200


class _TabButton(QWidget):
    """Singola tab: titolo + badge + × (nascosta, appare su hover/attivo)."""

    close_clicked = Signal()
    tab_clicked   = Signal()

    def __init__(self, title: str, height: int = 34, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setMinimumWidth(_TAB_MIN_W)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        # Selezionabile da tastiera (Tab + Invio/Spazio); Ctrl+W chiude il progetto attivo
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("projectTab")

        self._active = False
        self._hovered = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(5)

        self._lbl = QLabel(title)
        self._lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(self._lbl, 1)

        self._badge = QLabel()
        self._badge.setFixedSize(6, 6)
        self._badge.setStyleSheet(self._badge_style())
        self._badge.setToolTip("Modifiche non salvate")
        self._badge.setVisible(False)
        layout.addWidget(self._badge)

        # × — sempre nel layout, visibilità gestita via enterEvent/leaveEvent
        self._close = QPushButton()
        self._close.setIconSize(QSize(12, 12))
        self._close.setObjectName("tabClose")
        self._close.setFixedSize(18, 18)
        self._close.setFlat(True)
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.setToolTip(f"Chiudi progetto  {platform_support.shortcut_label('Ctrl+W')}")
        self._close.setAccessibleName("Chiudi progetto")
        self._close.setFocusPolicy(Qt.NoFocus)
        self._close.clicked.connect(self.close_clicked)
        self._close.setVisible(False)
        layout.addWidget(self._close)

        self.set_active(False)

    def set_title(self, title: str):
        self._title = title
        fm = QFontMetrics(self._lbl.font())
        elided = fm.elidedText(title, Qt.ElideMiddle, _TAB_MAX_W - 64)
        self._lbl.setText(elided)
        self._lbl.setToolTip(title if elided != title else "")
        self._update_accessible()

    def set_modified(self, modified: bool):
        self._badge.setVisible(modified)
        self._update_accessible()

    def _update_accessible(self):
        title = getattr(self, "_title", self._lbl.text())
        parts = [f"Progetto {title}"]
        if self._badge.isVisibleTo(self):
            parts.append("modificato")
        if self._active:
            parts.append("selezionato")
        self.setAccessibleName(", ".join(parts))

    @staticmethod
    def _badge_style() -> str:
        """Punto da 6 px (avviso: modifiche non salvate)."""
        return (f"background-color: {theme.c('warn')}; border: none; border-radius: 3px;")

    # ── Stile chiusura (theme-aware) ─────────────────────────────────────────────
    def _close_style(self, active: bool) -> str:
        c = theme.c
        col = c("dim") if active else c("muted")
        return (
            "QPushButton#tabClose {"
            "  background: transparent;"
            f"  color: {col};"
            "  border: none;"
            "  padding: 0;"
            "  border-radius: 4px;"
            "}"
            "QPushButton#tabClose:hover {"
            f"  color: {c('err')};"
            f"  background: {c('err_soft')};"
            "}"
        )

    def set_active(self, active: bool):
        self._active = active
        c = theme.c
        if active:
            # Tab attiva: sfondo distinguibile, bordo accent in basso
            self.setStyleSheet(
                "QWidget#projectTab {"
                "  background-color: transparent;"
                f"  border-bottom: 2px solid {c('acc')};"
                "  border-top: 1px solid transparent;"
                "  border-left: 1px solid transparent;"
                "  border-right: 1px solid transparent;"
                "  border-radius: 0;"
                "}"
                f"QWidget#projectTab:focus {{ border: 1px solid {c('focus')}; }}"
            )
            self._lbl.setStyleSheet(
                f"color: {c('text')}; font-size: 12px; font-weight: 600; background: transparent;"
            )
            self._close.setStyleSheet(self._close_style(True))
            self._close.setIcon(icons.icon("close", "dim", 12))
        else:
            self.setStyleSheet(
                "QWidget#projectTab {"
                "  background-color: transparent;"
                "  border: 1px solid transparent;"
                "  border-bottom: 2px solid transparent;"
                "  border-radius: 0;"
                "}"
                "QWidget#projectTab:hover {"
                f"  background-color: {c('raise')};"
                "  border: 1px solid transparent;"
                "  border-bottom: 2px solid transparent;"
                "}"
                f"QWidget#projectTab:focus {{ border: 1px solid {c('focus')}; }}"
            )
            self._lbl.setStyleSheet(
                f"color: {c('muted')}; font-size: 12px; font-weight: 400; background: transparent;"
            )
            self._close.setStyleSheet(self._close_style(False))
            self._close.setIcon(icons.icon("close", "muted", 12))
        self._update_accessible()

    def apply_palette(self):
        """Ri-applica i colori del tema corrente (chiamato su theme_changed)."""
        self._badge.setStyleSheet(self._badge_style())
        self.set_active(self._active)

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

    def focusInEvent(self, event):
        self._close.setVisible(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        if not self._hovered:
            self._close.setVisible(False)
        super().focusOutEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.tab_clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.tab_clicked.emit()
            return
        super().keyPressEvent(event)


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
        # Altezza dalle metriche del font: niente titoli tagliati con font grandi
        self._bar_h = max(34, self.fontMetrics().height() + 16)
        self.setFixedHeight(self._bar_h)

        self._tabs: list[_TabButton] = []
        self._current = -1

        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 0, 4, 0)
        outer.setSpacing(0)

        # Area scorribile per le tab
        self._scroll = QScrollArea()
        self._scroll.setFixedHeight(self._bar_h)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)

        self._tabs_widget = QWidget()
        self._tabs_layout = QHBoxLayout(self._tabs_widget)
        self._tabs_layout.setContentsMargins(0, 0, 0, 0)
        self._tabs_layout.setSpacing(2)   # piccolo gap tra tab invece di bordo divisore
        self._tabs_layout.addStretch(1)

        # Bottone + — vive DENTRO il layout delle tab, subito dopo l'ultima
        self._btn_new = QPushButton()
        icons.bind_icon(self._btn_new, "plus", "dim")
        self._btn_new.setFixedSize(26, 26)
        self._btn_new.setFlat(False)
        self._btn_new.setToolTip(f"Nuovo progetto  ({platform_support.shortcut_label('Ctrl+Shift+T')})")
        self._btn_new.setAccessibleName("Nuovo progetto")
        self._btn_new.setCursor(Qt.PointingHandCursor)
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

        # Ctrl+Shift+T (nuovo progetto) è l'azione del menu File della MainWindow:
        # registrarla anche qui la renderebbe ambigua.

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    # ── Tema ─────────────────────────────────────────────────────────────────

    def _apply_palette(self):
        c = theme.c
        self.setStyleSheet(
            f"background-color: {c('panel')}; border-bottom: 1px solid {c('line')};"
        )
        self._scroll.setStyleSheet(f"background: {c('panel')}; border: none;")
        self._tabs_widget.setStyleSheet(f"background: {c('panel')};")
        self._btn_new.setStyleSheet(
            "QPushButton {"
            "  background: transparent;"
            f"  color: {c('dim')};"
            "  border: 1px solid transparent;"
            "  border-radius: 4px;"
            "  padding: 0;"
            "}"
            "QPushButton:hover {"
            f"  background: {c('raise')};"
            f"  color: {c('text')};"
            "}"
            f"QPushButton:pressed {{ background: {c('raise')}; }}"
            + theme.focus_rule("QPushButton", 4)
        )
        for tab in self._tabs:
            tab.apply_palette()

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
        tab = _TabButton(title, height=self._bar_h)
        tab.set_title(title)

        self._tabs_layout.insertWidget(idx, tab)
        self._tabs.append(tab)

        self._reinsert_plus_button()

        tab.tab_clicked.connect(self._on_tab_clicked_by_ref)
        tab.close_clicked.connect(self._on_close_clicked_by_ref)

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

    def _on_tab_clicked_by_ref(self, tab: Optional[_TabButton] = None):
        tab = tab if tab is not None else self.sender()
        try:
            idx = self._tabs.index(tab)
        except ValueError:
            return
        self.select_tab(idx)

    def _on_close_clicked_by_ref(self, tab: Optional[_TabButton] = None):
        tab = tab if tab is not None else self.sender()
        try:
            idx = self._tabs.index(tab)
        except ValueError:
            return
        self.tab_close_requested.emit(idx)
