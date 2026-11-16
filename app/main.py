"""
main.py — Entry point dell'applicazione Video → SRT v2 (PySide6).

Splash screen con icona → caricamento progressivo in thread → MainWindow.
"""

from __future__ import annotations
import logging
import math
import os
import sys
import threading
import traceback
from pathlib import Path

# PATH setup
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QObject, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QPainter, QFont, QLinearGradient, QBrush,
    QPainterPath, QPixmap, QIcon,
)
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

import platform_support
from ui import theme

logger = logging.getLogger(__name__)


# ============================================================
# Generazione icona in memoria (identica a make_icon.py)
# ============================================================

def _draw_icon_pixmap(size: int) -> QPixmap:
    """
    Disegna l'icona dell'app alla dimensione richiesta.
    Ciak + forma d'onda + testo "SRT" su sfondo blu scuro.
    """
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    s = float(size)
    r = s * 0.12

    # Sfondo degradé
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0.0, QColor("#1a1a3f"))
    grad.setColorAt(1.0, QColor("#0d0d1f"))
    path_bg = QPainterPath()
    path_bg.addRoundedRect(QRectF(0, 0, s, s), r, r)
    p.fillPath(path_bg, QBrush(grad))

    # Ciak superiore
    ciak_h = s * 0.22
    ciak_y = s * 0.10
    ciak_x = s * 0.10
    ciak_w = s * 0.80

    p.setBrush(QColor("#111111"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(ciak_x, ciak_y, ciak_w, ciak_h), s * 0.04, s * 0.04)

    # Strisce diagonali
    stripe_h = ciak_h * 0.40
    n_stripes = 7
    stripe_w = ciak_w / n_stripes
    for i in range(n_stripes):
        color = QColor("#ffffff") if i % 2 == 0 else QColor("#111111")
        sx = ciak_x + i * stripe_w
        offset = stripe_h * 0.6
        sp = QPainterPath()
        sp.moveTo(QPointF(sx + offset, ciak_y))
        sp.lineTo(QPointF(sx + stripe_w + offset, ciak_y))
        sp.lineTo(QPointF(sx + stripe_w, ciak_y + stripe_h))
        sp.lineTo(QPointF(sx, ciak_y + stripe_h))
        sp.closeSubpath()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(ciak_x, ciak_y, ciak_w, stripe_h), s * 0.04, s * 0.04)
        p.fillPath(sp.intersected(clip), color)

    # Forma d'onda (barre)
    bar_count = 18
    bar_area_x = s * 0.10
    bar_area_w = s * 0.80
    bar_area_y = s * 0.40
    bar_area_h = s * 0.30
    bar_w   = bar_area_w / bar_count * 0.6
    bar_gap = bar_area_w / bar_count

    heights = [abs(math.sin(i * 0.7 + 0.5)) * 0.7 + 0.15 for i in range(bar_count)]
    heights[bar_count // 2]     = 1.0
    heights[bar_count // 2 - 1] = 0.85
    heights[bar_count // 2 + 1] = 0.90

    wave_grad = QLinearGradient(0, bar_area_y, 0, bar_area_y + bar_area_h)
    wave_grad.setColorAt(0.0, QColor("#4f8cff"))
    wave_grad.setColorAt(1.0, QColor("#8b5cf6"))

    p.setPen(Qt.NoPen)
    for i, h in enumerate(heights):
        bh = bar_area_h * h
        bx = bar_area_x + i * bar_gap + (bar_gap - bar_w) / 2
        by = bar_area_y + bar_area_h - bh
        p.setBrush(QBrush(wave_grad))
        p.drawRoundedRect(QRectF(bx, by, bar_w, bh), bar_w * 0.4, bar_w * 0.4)

    # Testo "SRT"
    font_size = max(8, int(s * 0.175))
    font = QFont(platform_support.ui_font_family(), font_size)
    font.setBold(True)
    font.setLetterSpacing(QFont.AbsoluteSpacing, s * 0.025)
    p.setFont(font)
    text_rect = QRectF(0, s * 0.72, s, s * 0.22)
    p.setPen(QColor(0, 0, 0, 120))
    p.drawText(text_rect.translated(s * 0.008, s * 0.008), Qt.AlignCenter, "SRT")
    p.setPen(QColor("#e4e4ef"))
    p.drawText(text_rect, Qt.AlignCenter, "SRT")

    # Bagliore
    glow = QLinearGradient(0, 0, s * 0.5, s * 0.5)
    glow.setColorAt(0.0, QColor(255, 255, 255, 18))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path_bg, QBrush(glow))

    p.end()
    return pix


def _icon_file() -> Path | None:
    """Percorso del file icona della piattaforma, se presente in assets/."""
    return platform_support.app_icon_path(script_dir / "assets")


def _icon_pixmap(size: int) -> QPixmap:
    """Pixmap dell'icona dal file se esiste, altrimenti disegnata in memoria."""
    path = _icon_file()
    if path is not None:
        pix = QIcon(str(path)).pixmap(size, size)
        if not pix.isNull():
            return pix
    return _draw_icon_pixmap(size)


def _make_app_icon() -> QIcon:
    """Costruisce un QIcon: dal file se esiste, altrimenti multi-risoluzione in memoria."""
    path = _icon_file()
    if path is not None:
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon

    icon = QIcon()
    for sz in (16, 32, 64, 128, 256, 512):
        icon.addPixmap(_draw_icon_pixmap(sz))
    return icon


# ============================================================
# Splash Screen
# ============================================================
STEPS = [
    "Inizializzazione…",
    "Caricamento interfaccia…",
    "Verifica FFmpeg…",
    "Caricamento motore IA…",
    "Caricamento modello Whisper…",
    "Pronto!",
]

SPLASH_W = 520
SPLASH_H = 300


def _splash_color(token: str) -> QColor:
    """Colore del tema scuro (lo splash compare prima che il tema utente sia applicato)."""
    return theme.qcolor(token, "dark")


def _render_splash_pixmap(app_icon_pix: QPixmap | None = None) -> QPixmap:
    """
    Disegna la splash screen con:
      - Sfondo scuro con bordo arrotondato
      - Icona app (se disponibile) a sinistra del titolo
      - Titolo + sottotitolo
      - Barra di progresso (dipinta da drawContents)
    """
    w, h = SPLASH_W, SPLASH_H
    pix = QPixmap(w, h)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    # Sfondo con bordo arrotondato
    bg_path = QPainterPath()
    bg_path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)

    p.fillPath(bg_path, QBrush(_splash_color("bg")))

    # Bordo sottile
    from PySide6.QtGui import QPen
    p.setPen(QPen(_splash_color("line"), 1))
    p.setBrush(Qt.NoBrush)
    p.drawPath(bg_path)

    # Icona app a sinistra (64×64)
    icon_size = 72
    icon_x    = 40
    icon_y    = (h - 60) // 2 - 20  # centrata verticalmente (sopra la barra)

    if app_icon_pix is not None:
        scaled = app_icon_pix.scaled(
            icon_size, icon_size,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        # Clip circolare per l'icona
        icon_clip = QPainterPath()
        icon_clip.addRoundedRect(
            QRectF(icon_x, icon_y, icon_size, icon_size), 6, 6
        )
        p.save()
        p.setClipPath(icon_clip)
        p.drawPixmap(icon_x, icon_y, scaled)
        p.restore()

    # Titolo
    text_x = icon_x + icon_size + 20
    p.setPen(_splash_color("text"))
    title_font = QFont(platform_support.ui_font_family(), 26)
    title_font.setWeight(QFont.Medium)
    p.setFont(title_font)
    p.drawText(QRectF(text_x, icon_y + 2, w - text_x - 30, 40),
               Qt.AlignLeft | Qt.AlignVCenter, "Video → SRT")

    # Sottotitolo
    p.setPen(_splash_color("dim"))
    p.setFont(QFont(platform_support.ui_font_family(), 12))
    p.drawText(QRectF(text_x, icon_y + 44, w - text_x - 30, 24),
               Qt.AlignLeft | Qt.AlignVCenter,
               "Trascrizione automatica italiana · Editor integrato")

    # Versione
    p.setPen(_splash_color("label"))
    p.setFont(QFont(platform_support.mono_font_family(), 10))
    p.drawText(QRectF(0, h - 22, w - 16, 16),
               Qt.AlignRight | Qt.AlignVCenter, "v2.0")

    p.end()
    return pix


class SplashState(QObject):
    """Segnali emessi dal thread worker; i ricevitori vivono nel thread GUI."""

    step_changed = Signal(int, str)
    finished     = Signal(bool, str)    # ok, messaggio di errore (vuoto se ok)


class Splash(QSplashScreen):
    def __init__(self, icon_pix: QPixmap | None = None):
        super().__init__(_render_splash_pixmap(icon_pix))
        self.setWindowFlags(
            Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._pct = 0.0
        self._msg = STEPS[0]

    def set_step(self, idx: int, msg: str | None = None):
        self._msg = msg or (STEPS[idx] if idx < len(STEPS) else "Pronto!")
        self._pct = (idx + 1) / len(STEPS)
        self.repaint()

    def drawContents(self, painter: QPainter):
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        # Progress track
        track_x = 40
        track_y  = h - 52
        track_w  = w - 80
        painter.setPen(Qt.NoPen)
        painter.setBrush(_splash_color("line"))
        painter.drawRect(track_x, track_y, track_w, 4)

        # Progress fill (piatto, accento monocromatico)
        painter.setBrush(_splash_color("acc"))
        fill_w = int(track_w * self._pct)
        if fill_w > 0:
            painter.drawRect(track_x, track_y, fill_w, 4)

        # Messaggio
        painter.setPen(_splash_color("dim"))
        painter.setFont(QFont(platform_support.ui_font_family(), 11))
        painter.drawText(
            QRectF(track_x, track_y + 12, track_w, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._msg,
        )


# ============================================================
# Main
# ============================================================
class _StartupController(QObject):
    """
    Vive nel thread GUI: riceve (in coda) i segnali del worker di avvio,
    chiude lo splash, crea la MainWindow o mostra l'errore.
    """

    def __init__(self, app: QApplication, splash: Splash, app_icon: QIcon,
                 result: dict, parent: QObject | None = None):
        super().__init__(parent)
        self._app = app
        self._splash = splash
        self._icon = app_icon
        self._result = result
        self.window = None

    @Slot(int, str)
    def on_step(self, idx: int, msg: str) -> None:
        self._splash.set_step(idx, msg)

    @Slot(bool, str)
    def on_finished(self, ok: bool, error: str) -> None:
        if not ok:
            self._splash.close()
            logger.error("Avvio fallito: %s", error)
            QMessageBox.critical(
                None, "Video → SRT",
                "Impossibile avviare l'applicazione.\n\n" + (error or "Errore sconosciuto"),
            )
            self._app.exit(1)
            return

        from ui.main_window import MainWindow
        win = MainWindow(ffmpeg_ok=self._result["ffmpeg"], model_ok=self._result["model"])
        win.setWindowIcon(self._icon)
        self.window = win

        # Finestra principale solo dopo la chiusura dello splash; il dialog di
        # ripristino autosave va mostrato dopo, con lo splash già chiuso.
        def _show_main():
            self._splash.close()
            win.show()
            QTimer.singleShot(0, win._check_autosave_restore)

        QTimer.singleShot(300, _show_main)


def main():
    import multiprocessing
    multiprocessing.freeze_support()

    log_path = platform_support.configure_logging()
    logger.info("Avvio Video → SRT (log: %s)", log_path)

    app = QApplication(sys.argv)
    app.setApplicationName("Video → SRT")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("Video SRT")

    # ---- Font IBM Plex (prima del tema: il QSS li richiama per nome) ----
    from ui.fonts import load_app_fonts
    load_app_fonts()
    app_font = QFont(platform_support.ui_font_family())
    app_font.setPixelSize(13)
    app.setFont(app_font)

    # ---- Icona app (Dock macOS + titolo finestra) ----
    app_icon = _make_app_icon()
    app.setWindowIcon(app_icon)

    # Icona Dock a livello di processo (solo macOS; no-op altrove)
    platform_support.set_dock_icon(_icon_pixmap(512))

    # Stylesheet globale — applica il tema salvato (default scuro)
    from PySide6.QtCore import QSettings
    from ui import theme as _theme
    if platform_support.IS_WIN:
        app.setStyle("Fusion")
    saved_theme = QSettings("VideoSRT", "v2").value("theme", "dark")
    if saved_theme not in ("dark", "light"):
        saved_theme = "dark"
    _theme.apply_theme(app, saved_theme)

    # ---- Splash ----
    splash = Splash(_icon_pixmap(128))
    splash.show()
    app.processEvents()

    result = {"ffmpeg": False, "model": False}
    splash_state = SplashState()
    controller = _StartupController(app, splash, app_icon, result)
    splash_state.step_changed.connect(controller.on_step, Qt.QueuedConnection)
    splash_state.finished.connect(controller.on_finished, Qt.QueuedConnection)

    def _worker():
        ok, error = True, ""
        try:
            splash_state.step_changed.emit(1, "Caricamento interfaccia…")

            splash_state.step_changed.emit(2, "Verifica FFmpeg…")
            from engine import check_ffmpeg
            result["ffmpeg"] = check_ffmpeg()

            splash_state.step_changed.emit(3, "Caricamento motore IA…")
            from engine import preload_model, DEFAULT_MODEL

            splash_state.step_changed.emit(4, "Caricamento modello Whisper…")

            def _on_status(msg):
                splash_state.step_changed.emit(4, msg)

            result["model"] = preload_model(model_size=DEFAULT_MODEL, on_status=_on_status)
            splash_state.step_changed.emit(5, "Pronto!")
        except BaseException as exc:  # noqa: BLE001 — qualsiasi errore deve chiudere lo splash
            logger.error("Errore nel worker di avvio:\n%s", traceback.format_exc())
            ok, error = False, f"{type(exc).__name__}: {exc}"
        finally:
            splash_state.finished.emit(ok, error)

    threading.Thread(target=_worker, daemon=True).start()

    code = app.exec()

    # Un thread di trascrizione ancora attivo (es. ffmpeg bloccato) non deve essere
    # distrutto da Qt/interprete: si esce subito, dopo aver svuotato i log.
    from ui.progress_widget import has_running_detached_threads
    if has_running_detached_threads():
        logger.warning("Uscita forzata: thread di trascrizione ancora in esecuzione")
        logging.shutdown()
        os._exit(code)

    sys.exit(code)


if __name__ == "__main__":
    main()
