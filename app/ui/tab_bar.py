"""
tab_bar.py — TabBar custom con 3 tab: "Trascrizione" | "Editor [●]" | "Esportazione".

All'avvio "Trascrizione" è attiva. Editor ed Esportazione restano visibili ma
"bloccati" (non cliccabili) finché non chiamato set_unlocked(True), cioè quando
ci sono sottotitoli disponibili (post-trascrizione o import).

Nell'intestazione da 40 px della MainWindow questa barra occupa la parte centrale
(la MainWindow mostra quella del progetto attivo); il toggle del tema vive nell'intestazione.

Tema chiaro/scuro: legge i colori da theme.c() e si ri-applica su theme_changed.

Segnali:
  tab_changed(int)   — 0 = Trascrizione, 1 = Editor, 2 = Esportazione
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
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
        bar_h = max(40, self.fontMetrics().height() + 22)
        self.setFixedHeight(bar_h)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)

        self._current = _TAB_TRANSCRIPTION
        self._unlocked = False
        self.setObjectName("innerTabBar")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

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
        ec_layout.setSpacing(0)

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
        exp_layout.setContentsMargins(0, 0, 0, 0)
        exp_layout.setSpacing(0)

        self._btn_export = QPushButton("Esportazione")
        self._btn_export.setToolTip(
            f"Esportazione  {platform_support.shortcut_label('Ctrl+E')}")
        self._btn_export.setFixedHeight(bar_h)
        self._btn_export.setCursor(Qt.PointingHandCursor)
        self._btn_export.setCheckable(True)   # stato "selezionato" leggibile dagli screen reader
        self._btn_export.clicked.connect(self._on_export_clicked)
        exp_layout.addWidget(self._btn_export)

        layout.addWidget(self._export_container)

        self._apply_palette()
        self._refresh_styles()
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

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

    def _apply_palette(self):
        c = theme.c
        # Sfondo e linea inferiore sono dell'intestazione della MainWindow
        self.setStyleSheet("QWidget#innerTabBar { background: transparent; border: none; }")
        self._badge.setStyleSheet(
            f"background-color: {c('acc')}; border: none; border-radius: 3px;"
        )

    # ── Privato ────────────────────────────────────────────────────────────────

    def _style_for(self, active: bool, locked: bool) -> str:
        c = theme.c
        if active:
            color, weight = c("text"), 500
        elif locked:
            color, weight = c("label"), 400
        else:
            color, weight = c("dim"), 400
        underline = c("acc") if active else "transparent"
        hover = "" if (active or locked) else (
            f"QPushButton:hover {{ color: {c('text')}; }}"
        )
        return (
            "QPushButton {"
            "  background-color: transparent;"
            f"  color: {color};"
            "  border: none;"
            f"  border-bottom: 2px solid {underline};"
            "  font-size: 13px;"
            f"  font-weight: {weight};"
            "  padding: 0 14px;"
            "}"
            f"{hover}"
            f"QPushButton:focus {{ border: 1px solid {c('focus')}; border-radius: 4px; }}"
        )

    def _refresh_styles(self):
        self._sync_checked()
        self._btn_transcription.setStyleSheet(
            self._style_for(self._current == _TAB_TRANSCRIPTION, locked=False)
        )
        locked = not self._unlocked
        for btn, idx in ((self._btn_editor, _TAB_EDITOR), (self._btn_export, _TAB_EXPORT)):
            btn.setStyleSheet(self._style_for(self._current == idx, locked=locked))
            if locked:
                # il lucchetto non ha stato disabilitato proprio: colore "label" fisso
                pix = icons.pixmap("lock", theme.qcolor("label"), 12)
                lock = QIcon()
                for mode in (QIcon.Normal, QIcon.Disabled):
                    lock.addPixmap(pix, mode, QIcon.Off)
                btn.setIcon(lock)
                btn.setIconSize(QSize(12, 12))
            else:
                btn.setIcon(QIcon())
