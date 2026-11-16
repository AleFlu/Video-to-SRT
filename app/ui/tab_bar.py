"""
tab_bar.py — TabBar custom con 3 tab: "Trascrizione" | "Editor [●]" | "Esportazione".

All'avvio "Trascrizione" è attiva. Editor ed Esportazione restano visibili ma
"bloccati" (non cliccabili) finché non chiamato set_unlocked(True), cioè quando
ci sono sottotitoli disponibili (post-trascrizione o import).

Tema chiaro/scuro: legge i colori da theme.c() e si ri-applica su theme_changed.

Segnali:
  tab_changed(int)   — 0 = Trascrizione, 1 = Editor, 2 = Esportazione
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QSizePolicy

from ui import icons, theme
import platform_support


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
        # Altezza dalle metriche del font (mai testo tagliato con font grandi)
        bar_h = max(46, self.fontMetrics().height() + 26)
        self.setFixedHeight(bar_h)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._current = _TAB_TRANSCRIPTION
        self._unlocked = False
        self.setObjectName("innerTabBar")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(2)

        # ── Tab Trascrizione ───────────────────────────────────────────────────
        self._btn_transcription = QPushButton("Trascrizione")
        self._btn_transcription.setFixedHeight(bar_h)
        self._btn_transcription.setCursor(Qt.PointingHandCursor)
        self._btn_transcription.setCheckable(True)   # stato "selezionato" leggibile dagli screen reader
        self._btn_transcription.clicked.connect(self._on_transcription_clicked)
        layout.addWidget(self._btn_transcription)

        # ── Tab Editor (con badge ● / lucchetto) ───────────────────────────────
        self._editor_container = QWidget()
        self._editor_container.setFixedHeight(bar_h)
        self._editor_container.setStyleSheet("background: transparent;")
        ec_layout = QHBoxLayout(self._editor_container)
        ec_layout.setContentsMargins(0, 0, 0, 0)
        ec_layout.setSpacing(6)

        self._btn_editor = QPushButton("Editor")
        self._btn_editor.setFixedHeight(bar_h)
        self._btn_editor.setCursor(Qt.PointingHandCursor)
        self._btn_editor.setCheckable(True)   # stato "selezionato" leggibile dagli screen reader
        self._btn_editor.clicked.connect(self._on_editor_clicked)
        ec_layout.addWidget(self._btn_editor)

        self._badge = QLabel()
        self._badge.setFixedSize(6, 6)
        self._badge.setToolTip("L'editor contiene sottotitoli")
        self._badge.setVisible(False)
        ec_layout.addWidget(self._badge)

        layout.addWidget(self._editor_container)

        # ── Tab Esportazione ───────────────────────────────────────────────────
        self._export_container = QWidget()
        self._export_container.setFixedHeight(bar_h)
        self._export_container.setStyleSheet("background: transparent;")
        exp_layout = QHBoxLayout(self._export_container)
        exp_layout.setContentsMargins(0, 0, 8, 0)
        exp_layout.setSpacing(6)

        self._btn_export = QPushButton("Esportazione")
        self._btn_export.setFixedHeight(bar_h)
        self._btn_export.setCursor(Qt.PointingHandCursor)
        self._btn_export.setCheckable(True)   # stato "selezionato" leggibile dagli screen reader
        self._btn_export.clicked.connect(self._on_export_clicked)
        exp_layout.addWidget(self._btn_export)

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
        theme.toggle_theme()

    def _refresh_theme_btn(self):
        c = theme.c
        is_dark = theme.get_theme() == "dark"
        self._theme_btn.setText("Scuro" if is_dark else "Chiaro")
        self._theme_btn.setIcon(icons.icon("moon" if is_dark else "sun", "dim"))
        self._theme_btn.setIconSize(QSize(16, 16))
        tip = "Passa al tema chiaro" if is_dark else "Passa al tema scuro"
        self._theme_btn.setToolTip(f"{tip}  {platform_support.shortcut_label('Ctrl+Shift+L')}")
        self._theme_btn.setAccessibleName(tip)
        self._theme_btn.setStyleSheet(
            "QPushButton {"
            f"  background: transparent; color: {c('dim')};"
            "  border: 1px solid transparent; border-radius: 4px;"
            "  font-size: 13px; padding: 0 9px; min-height: 26px;"
            "}"
            f"QPushButton:hover {{ color: {c('text')}; background: {c('raise')}; }}"
            + theme.focus_rule("QPushButton", 4)
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

    def _on_transcription_clicked(self) -> None:
        self._on_clicked(_TAB_TRANSCRIPTION)

    def _on_editor_clicked(self) -> None:
        self._on_clicked(_TAB_EDITOR)

    def _on_export_clicked(self) -> None:
        self._on_clicked(_TAB_EXPORT)

    def _on_clicked(self, index: int):
        self.set_current(index)
        self._sync_checked()   # un click sulla tab attiva non deve "spegnerla"

    def _sync_checked(self):
        for i, btn in ((_TAB_TRANSCRIPTION, self._btn_transcription),
                       (_TAB_EDITOR, self._btn_editor), (_TAB_EXPORT, self._btn_export)):
            btn.setChecked(i == self._current)

    def current(self) -> int:
        return self._current

    def set_editor_badge(self, visible: bool):
        """INV3: badge ● visibile ↔ project.subtitles non vuoti."""
        self._badge.setVisible(visible)

    # ── Tema ─────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _name: str):
        self._apply_palette()
        self._refresh_styles()
        self._refresh_theme_btn()

    def _apply_palette(self):
        c = theme.c
        # Selettore esplicito: il bordo inferiore non deve propagarsi ai figli
        self.setStyleSheet(
            f"QWidget#innerTabBar {{ background-color: {c('panel')};"
            f" border-bottom: 1px solid {c('line')}; }}"
        )
        self._badge.setStyleSheet(
            f"background-color: {c('acc')}; border: none; border-radius: 3px;"
        )

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
            f"QPushButton:focus {{ border: 1px solid {c('focus')}; border-radius: 4px; }}"
        )

    def _refresh_styles(self):
        self._sync_checked()
        self._btn_transcription.setStyleSheet(
            self._style_for(self._current == _TAB_TRANSCRIPTION, locked=False)
        )
        self._btn_editor.setStyleSheet(
            self._style_for(self._current == _TAB_EDITOR, locked=not self._unlocked)
        )
        self._btn_export.setStyleSheet(
            self._style_for(self._current == _TAB_EXPORT, locked=not self._unlocked)
        )
