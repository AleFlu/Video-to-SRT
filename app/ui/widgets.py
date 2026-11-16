"""
widgets.py — Piccoli widget riutilizzabili dell'interfaccia.

  - ElidedLabel : QLabel a riga singola che accorcia il testo con "…" invece di
                  imporre una larghezza minima (nomi file lunghi); testo intero nel tooltip.
  - DepsBanner  : avviso a una riga in Home quando FFmpeg o il modello Whisper mancano.
  - ToggleSwitch: interruttore rettangolare 38×20 con etichetta (acceso/spento/non disponibile).
  - fmt_size    : dimensione file leggibile ("12.3 MB").
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QSize, Signal
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ui import icons, theme


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
    Avviso a una riga sopra la schermata iniziale quando FFmpeg o il modello Whisper
    non sono disponibili: bordo warn (err se mancano entrambi), icona di allerta, nessun
    riempimento. Si nasconde se tutto è ok. Colori dai token, aggiornati al cambio tema.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("depsBanner")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setVisible(False)
        self._severe = False

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        self._icon = QLabel()
        self._icon.setFixedSize(16, 16)
        row.addWidget(self._icon, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._title = QLabel("")
        self._title.setWordWrap(True)
        col.addWidget(self._title)

        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setOpenExternalLinks(True)
        self._body.setTextFormat(Qt.RichText)
        col.addWidget(self._body)
        row.addLayout(col, 1)

        self._apply_palette()
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    def _apply_palette(self, _name=None):
        c = theme.c
        tone = "err" if self._severe else "warn"
        self.setStyleSheet(
            f"QFrame#depsBanner {{ background-color: transparent;"
            f" border: 1px solid {c(tone)}; border-radius: 4px; }}"
        )
        self._icon.setPixmap(icons.pixmap("alert", theme.qcolor(tone), 16))
        self._icon.setStyleSheet("background: transparent; border: none;")
        self._title.setStyleSheet(
            f"color: {c(tone)}; font-weight: 500; font-size: 13px;"
            " background: transparent; border: none;"
        )
        self._body.setStyleSheet(
            f"color: {c('dim')}; font-size: 12px; background: transparent; border: none;"
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


# ── Pulsante di overflow ("»") di toolbar e barra dei menu ───────────────────

_EXT_BUTTON_NAMES = ("qt_toolbar_ext_button", "qt_menubar_ext_button")


def chevron_icon(size: int = 16) -> QIcon:
    """Icona "»" disegnata con i colori del tema corrente (nessuna icona di sistema)."""
    scale = 2
    pix = QPixmap(size * scale, size * scale)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(theme.qcolor("muted"))
        pen.setWidthF(1.6 * scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        u = size * scale / 16.0
        for x0 in (4.0, 9.0):
            p.drawPolyline([QPointF(x0 * u, 4 * u), QPointF((x0 + 3.5) * u, 8 * u),
                            QPointF(x0 * u, 12 * u)])
    finally:
        p.end()
    pix.setDevicePixelRatio(scale)
    return QIcon(pix)


class _ExtensionIconGuard(QObject):
    """Mantiene l'icona disegnata sul pulsante di overflow.

    Qt assegna a quel pulsante un'icona di sistema e la ripristina a ogni cambio di
    stile. Su macOS quell'icona (SF Symbol) può sollevare un'eccezione AppKit durante
    il disegno e chiudere l'app: la si sostituisce prima di ogni paint.
    """

    def __init__(self, button: QToolButton):
        super().__init__(button)
        self._button = button
        self._key = 0
        self.refresh()
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)
        button.installEventFilter(self)

    def refresh(self) -> None:
        icon = chevron_icon()
        self._key = icon.cacheKey()
        self._button.setIcon(icon)

    def _on_theme_changed(self, _name: str) -> None:
        self.refresh()

    def eventFilter(self, obj, event):  # noqa: N802 — override Qt
        if event.type() == QEvent.Paint and self._button.icon().cacheKey() != self._key:
            self.refresh()
        return False


def protect_extension_buttons(bar: QWidget) -> int:
    """Sostituisce l'icona di sistema dei pulsanti di overflow di ``bar``.

    Ritorna il numero di pulsanti protetti. Idempotente.
    """
    count = 0
    for btn in bar.findChildren(QToolButton):
        if btn.objectName() not in _EXT_BUTTON_NAMES:
            continue
        if btn.findChild(_ExtensionIconGuard) is None:
            _ExtensionIconGuard(btn)
        count += 1
    return count


# ── Interruttore ─────────────────────────────────────────────────────────────

class SwitchPill(QWidget):
    """Interruttore rettangolare 38×20 (raggio 3, pomello 16×16 raggio 2), solo disegno."""

    W, H = 38, 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._on = False
        self._available = True
        self._focused = False
        self.setFixedSize(self.W, self.H)

    def set_on(self, val: bool):
        self._on = bool(val)
        self.update()

    def set_available(self, val: bool):
        self._available = bool(val)
        self.update()

    def set_focus_ring(self, val: bool):
        self._focused = bool(val)
        self.update()

    def paintEvent(self, event):  # noqa: N802 (override Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._available:
            border, fill, knob = theme.qcolor("line"), None, theme.qcolor("line")
        elif self._on:
            border, fill, knob = theme.qcolor("acc"), theme.qcolor("acc"), theme.qcolor("knob")
        else:
            border, fill, knob = theme.qcolor("dim"), None, theme.qcolor("dim")
        rect = QRectF(0.5, 0.5, self.W - 1, self.H - 1)
        p.setBrush(fill if fill is not None else Qt.NoBrush)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(rect, 3, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(knob)
        x = self.W - 2 - 16 if self._on else 2
        y = 2
        p.drawRoundedRect(QRectF(x, y, 16, 16), 2, 2)
        if self._focused:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(theme.qcolor("focus"), 1))
            p.drawRoundedRect(QRectF(0.5, 0.5, self.W - 1, self.H - 1), 3, 3)
        p.end()


class ToggleSwitch(QWidget):
    """
    Interruttore (pillola rettangolare + etichetta). Usabile da tastiera (Tab per il
    focus, Spazio/Invio per cambiare) e con nome accessibile. Stati: acceso, spento,
    non disponibile (``set_unavailable``).
    """

    toggled = Signal(bool)

    def __init__(self, label_on: str = "Attivo", label_off: str = "Disattivo",
                 name: str = "", parent=None):
        super().__init__(parent)
        self._checked = False
        self._on = label_on
        self._off = label_off
        self._name = name
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setObjectName("toggleSwitch")
        self.setMinimumHeight(max(28, self.fontMetrics().height() + 8))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self._pill = SwitchPill()
        lay.addWidget(self._pill)

        # larghezza minima dell'etichetta: evita resize del layout al cambio testo
        self._lbl = QLabel(self._off)
        fm = self._lbl.fontMetrics()
        self._lbl.setMinimumWidth(max(fm.horizontalAdvance(label_on),
                                      fm.horizontalAdvance(label_off)) + 8)
        lay.addWidget(self._lbl)
        lay.addStretch()

        self._apply_palette()
        self._update_accessible()
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    def _apply_palette(self, _name=None):
        c = theme.c
        self.setStyleSheet("QWidget#toggleSwitch { background: transparent; border: none; }")
        self._lbl.setStyleSheet(
            f"font-size: 13px; color: {c('text') if self.isEnabled() else c('label')};"
            " background: transparent; border: none;"
        )
        self._pill.update()

    def _update_accessible(self):
        state = self._on if self._checked else self._off
        self.setAccessibleName(f"{self._name}: {state}" if self._name else state)

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, val: bool):  # noqa: N802
        self._checked = bool(val)
        self._pill.set_on(self._checked)
        self._lbl.setText(self._on if self._checked else self._off)
        self._update_accessible()

    def set_unavailable(self, label: str, tooltip: str):
        """Blocca l'interruttore su spento, con etichetta e spiegazione del motivo."""
        self._off = label
        self.setChecked(False)
        self.setEnabled(False)
        self._pill.set_available(False)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip(tooltip)
        self._apply_palette()

    def _toggle(self):
        if not self.isEnabled():
            return
        self.setChecked(not self._checked)
        self.toggled.emit(self._checked)

    def focusInEvent(self, e):  # noqa: N802
        self._pill.set_focus_ring(True)
        super().focusInEvent(e)

    def focusOutEvent(self, e):  # noqa: N802
        self._pill.set_focus_ring(False)
        super().focusOutEvent(e)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self._toggle()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._toggle()
            return
        super().keyPressEvent(e)
