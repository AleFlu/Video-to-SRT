"""
widgets.py — Piccoli widget riutilizzabili dell'interfaccia.

  - ElidedLabel : QLabel a riga singola che accorcia il testo con "…" invece di
                  imporre una larghezza minima (nomi file lunghi); testo intero nel tooltip.
  - DepsBanner  : avviso in Home quando FFmpeg o il modello Whisper mancano.
  - fmt_size    : dimensione file leggibile ("12.3 MB").
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout

from ui import theme


def fmt_size(path: str) -> str:
    """Dimensione del file in B/KB/MB/GB; stringa vuota se non leggibile."""
    try:
        s = os.path.getsize(path)
    except OSError:
        return ""
    if s < 1024:
        return f"{s} B"
    if s < 1024 ** 2:
        return f"{s / 1024:.1f} KB"
    if s < 1024 ** 3:
        return f"{s / 1024 ** 2:.1f} MB"
    return f"{s / 1024 ** 3:.2f} GB"


class ElidedLabel(QLabel):
    """
    Etichetta che non forza mai la larghezza del layout: il testo viene accorciato
    (di default al centro, utile per i nomi file) e quello completo va nel tooltip.
    """

    def __init__(self, text: str = "", mode=Qt.ElideMiddle, parent=None):
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self._tooltip_override = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)
        self.setText(text)

    def setText(self, text: str):  # noqa: N802 (override Qt)
        self._full = text or ""
        self._update_elided()

    def full_text(self) -> str:
        return self._full

    def set_full_tooltip(self, tip: str):
        """Tooltip esplicito (es. percorso completo) al posto del testo intero."""
        self._tooltip_override = tip
        self._update_elided()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(40, hint.height())

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._full) + 4, super().sizeHint().height())

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._update_elided()

    def _update_elided(self):
        elided = self.fontMetrics().elidedText(self._full, self._mode, max(0, self.width()))
        QLabel.setText(self, elided)
        if self._tooltip_override:
            self.setToolTip(self._tooltip_override)
        else:
            self.setToolTip(self._full if elided != self._full else "")


class DepsBanner(QFrame):
    """
    Banner di avviso in Home quando FFmpeg o il modello Whisper non sono
    disponibili. Si nasconde se tutto è ok. Colori dai token del tema
    (avviso = warn, entrambe mancanti = err) e aggiornati al cambio tema.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("depsBanner")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setVisible(False)
        self._severe = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(6)

        self._title = QLabel("")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setOpenExternalLinks(True)
        self._body.setTextFormat(Qt.RichText)
        layout.addWidget(self._body)

        self._apply_palette()
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    def _apply_palette(self, _name=None):
        c = theme.c
        tone = "err" if self._severe else "warn"
        self.setStyleSheet(
            f"QFrame#depsBanner {{ background-color: {c(tone + '_soft')};"
            f" border: 1px solid {c(tone)}; border-radius: 9px; }}"
        )
        self._title.setStyleSheet(
            f"color: {c(tone)}; font-weight: 600; font-size: 14px; background: transparent;"
        )
        self._body.setStyleSheet(
            f"color: {c('text')}; font-size: 12px; background: transparent;"
        )

    def set_status(self, ffmpeg_ok: bool, model_ok: bool):
        """Mostra o nasconde il banner in base alle dipendenze mancanti."""
        issues: list[str] = []
        hints: list[str] = []

        if not ffmpeg_ok:
            issues.append("FFmpeg non trovato")
            hints.append(
                "• <b>FFmpeg</b>: installalo e assicurati che sia nel PATH "
                "(macOS: <code>brew install ffmpeg</code>)"
            )
        if not model_ok:
            issues.append("Modello Whisper non disponibile")
            hints.append(
                "• <b>Modello Whisper</b>: esegui lo script di setup "
                "(<code>setup_mac.sh</code> o <code>setup_windows.bat</code>) "
                "per scaricarlo (≈ 3 GB)"
            )

        if not issues:
            self.setVisible(False)
            return

        self._severe = not ffmpeg_ok and not model_ok
        self._title.setText("  ·  ".join(issues))
        self._body.setText("<br>".join(hints))
        self._apply_palette()
        self.setVisible(True)
