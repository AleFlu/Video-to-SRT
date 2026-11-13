"""
tab_bar.py — TabBar custom con 3 tab: "Trascrizione" | "Editor [●]" | "Esportazione".

All'avvio "Trascrizione" è attiva. Editor ed Esportazione restano visibili ma
"bloccati" (lucchetto 🔒) finché non chiamato set_unlocked(True), cioè quando
ci sono sottotitoli disponibili (post-trascrizione o import).

Tema chiaro/scuro: legge i colori da theme.c() e si ri-applica su theme_changed.

Segnali:
  tab_changed(int)   — 0 = Trascrizione, 1 = Editor, 2 = Esportazione
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QSizePolicy

from ui import theme


_TAB_TRANSCRIPTION = 0
_TAB_EDITOR        = 1
_TAB_EXPORT        = 2


class TabBar(QWidget):
    """Barra tab: Trascrizione | Editor [●] | Esportazione.
    Editor e Esportazione mostrano un lucchetto finché non sbloccati.
    """

    tab_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._current = _TAB_TRANSCRIPTION
        self._unlocked = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(2)

        # ── Tab Trascrizione ───────────────────────────────────────────────────
        self._btn_transcription = QPushButton("Trascrizione")
        self._btn_transcription.setFixedHeight(46)
        self._btn_transcription.setCursor(Qt.PointingHandCursor)
        self._btn_transcription.clicked.connect(lambda: self.set_current(_TAB_TRANSCRIPTION))
        layout.addWidget(self._btn_transcription)

        # ── Tab Editor (con badge ● / lucchetto) ───────────────────────────────
        self._editor_container = QWidget()
        self._editor_container.setFixedHeight(46)
        self._editor_container.setStyleSheet("background: transparent;")
        ec_layout = QHBoxLayout(self._editor_container)
        ec_layout.setContentsMargins(0, 0, 0, 0)
        ec_layout.setSpacing(6)

        self._btn_editor = QPushButton("Editor")
        self._btn_editor.setFixedHeight(46)
        self._btn_editor.setCursor(Qt.PointingHandCursor)
        self._btn_editor.clicked.connect(lambda: self.set_current(_TAB_EDITOR))
        ec_layout.addWidget(self._btn_editor)

        self._badge = QLabel("●")
        self._badge.setVisible(False)
        ec_layout.addWidget(self._badge)

        # lucchetto rimosso (widget tenuto nascosto per compat con set_unlocked)
        self._editor_lock = QLabel("")
        self._editor_lock.setVisible(False)

        # badge legacy nascosto (compat: alcuni test/codice lo referenziano)
        self._export_badge = QLabel("")
        self._export_badge.setVisible(False)

        layout.addWidget(self._editor_container)

        # ── Tab Esportazione ───────────────────────────────────────────────────
        self._export_container = QWidget()
        self._export_container.setFixedHeight(46)
        self._export_container.setStyleSheet("background: transparent;")
        exp_layout = QHBoxLayout(self._export_container)
        exp_layout.setContentsMargins(0, 0, 8, 0)
        exp_layout.setSpacing(6)

        self._btn_export = QPushButton("Esportazione")
        self._btn_export.setFixedHeight(46)
        self._btn_export.setCursor(Qt.PointingHandCursor)
        self._btn_export.clicked.connect(lambda: self.set_current(_TAB_EXPORT))
        exp_layout.addWidget(self._btn_export)

        self._export_lock = QLabel("")
        self._export_lock.setVisible(False)

        layout.addWidget(self._export_container)

        layout.addStretch(1)

        # ── Toggle tema chiaro/scuro (sempre visibile nella finestra) ───────────
        self._theme_btn = QPushButton()
        self._theme_btn.setFixedHeight(28)
        self._theme_btn.setCursor(Qt.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self._theme_btn, 0, Qt.AlignVCenter)

        self._apply_palette()
        self._refresh_styles()
        self._refresh_theme_btn()
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    # ── Toggle tema ─────────────────────────────────────────────────────────

    def _toggle_theme(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        new = "light" if theme.get_theme() == "dark" else "dark"
        theme.apply_theme(QApplication.instance(), new)
        QSettings("VideoSRT", "v2").setValue("theme", new)

    def _refresh_theme_btn(self):
        c = theme.c
        is_dark = theme.get_theme() == "dark"
        self._theme_btn.setText("☾  Scuro" if is_dark else "☀  Chiaro")
        self._theme_btn.setToolTip("Passa al tema chiaro" if is_dark else "Passa al tema scuro")
        self._theme_btn.setStyleSheet(
            "QPushButton {"
            f"  background: {c('card_2')}; color: {c('dim')};"
            f"  border: 1px solid {c('line')}; border-radius: 7px;"
            "  font-size: 11.5px; padding: 0 11px; min-height: 28px;"
            "}"
            f"QPushButton:hover {{ color: {c('text')}; border-color: {c('line_2')}; }}"
        )

    # ── API pubblica ───────────────────────────────────────────────────────────

    def set_unlocked(self, unlocked: bool):
        """
        True  → Editor e Esportazione cliccabili (ci sono sottotitoli), lucchetti nascosti.
        False → Editor e Esportazione bloccati con lucchetto, torna a Trascrizione.
        """
        if self._unlocked == unlocked:
            return
        self._unlocked = unlocked
        self._editor_lock.setVisible(not unlocked)
        self._export_lock.setVisible(not unlocked)
        self._btn_editor.setEnabled(unlocked)
        self._btn_export.setEnabled(unlocked)
        self._btn_editor.setCursor(Qt.PointingHandCursor if unlocked else Qt.ForbiddenCursor)
        self._btn_export.setCursor(Qt.PointingHandCursor if unlocked else Qt.ForbiddenCursor)
        if not unlocked and self._current != _TAB_TRANSCRIPTION:
            self.set_current(_TAB_TRANSCRIPTION)
        self._refresh_styles()

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
        pass

    # ── Tema ─────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _name: str):
        self._apply_palette()
        self._refresh_styles()
        self._refresh_theme_btn()

    def _apply_palette(self):
        c = theme.c
        self.setStyleSheet(
            f"background-color: {c('bg')}; border-bottom: 1px solid {c('line')};"
        )
        self._badge.setStyleSheet(
            f"color: {c('acc')}; font-size: 11px; background: transparent;"
            f" border: 3px solid {c('acc_soft')}; border-radius: 7px;"
        )
        lock_ss = f"color: {c('faint')}; font-size: 11px; background: transparent;"
        self._editor_lock.setStyleSheet(lock_ss)
        self._export_lock.setStyleSheet(lock_ss)

    # ── Privato ────────────────────────────────────────────────────────────────

    def _style_for(self, active: bool, locked: bool) -> str:
        c = theme.c
        if locked:
            color = c("faint")
            weight = 400
        elif active:
            color = c("text")
            weight = 600
        else:
            color = c("muted")
            weight = 500
        underline = c("acc") if active else "transparent"
        hover = "" if (active or locked) else (
            f"QPushButton:hover {{ color: {c('dim')}; }}"
        )
        return (
            "QPushButton {"
            "  background-color: transparent;"
            f"  color: {color};"
            "  border: none;"
            f"  border-bottom: 2px solid {underline};"
            "  font-size: 13px;"
            f"  font-weight: {weight};"
            "  padding: 0 18px;"
            "}"
            f"{hover}"
        )

    def _refresh_styles(self):
        self._btn_transcription.setStyleSheet(
            self._style_for(self._current == _TAB_TRANSCRIPTION, locked=False)
        )
        self._btn_editor.setStyleSheet(
            self._style_for(self._current == _TAB_EDITOR, locked=not self._unlocked)
        )
        self._btn_export.setStyleSheet(
            self._style_for(self._current == _TAB_EXPORT, locked=not self._unlocked)
        )
