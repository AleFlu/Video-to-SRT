"""
main.py — Entry point dell'applicazione Video → SRT v2 (PySide6) — Windows.

Splash screen con icona → caricamento progressivo in thread → MainWindow.
"""

from __future__ import annotations
import logging
import sys
import threading
import math
from pathlib import Path

# Configura logging su file e console — utile per diagnosticare crash su Windows
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# PATH setup
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QPainter, QFont, QLinearGradient, QBrush,
    QPainterPath, QPixmap, QIcon,
)
from PySide6.QtWidgets import QApplication, QSplashScreen


# ============================================================
# Generazione icona in memoria
# ============================================================

def _draw_icon_pixmap(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    s = float(size)
    r = s * 0.12

    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0.0, QColor("#1a1a3f"))
    grad.setColorAt(1.0, QColor("#0d0d1f"))
    path_bg = QPainterPath()
    path_bg.addRoundedRect(QRectF(0, 0, s, s), r, r)
    p.fillPath(path_bg, QBrush(grad))

    ciak_h = s * 0.22
    ciak_y = s * 0.10
    ciak_x = s * 0.10
    ciak_w = s * 0.80

    p.setBrush(QColor("#111111"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(ciak_x, ciak_y, ciak_w, ciak_h), s * 0.04, s * 0.04)

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

    font_size = max(8, int(s * 0.175))
    # Font monospace disponibile su Windows
    font = QFont("Segoe UI", font_size)
    font.setBold(True)
    font.setLetterSpacing(QFont.AbsoluteSpacing, s * 0.025)
    p.setFont(font)
    text_rect = QRectF(0, s * 0.72, s, s * 0.22)
    p.setPen(QColor(0, 0, 0, 120))
    p.drawText(text_rect.translated(s * 0.008, s * 0.008), Qt.AlignCenter, "SRT")
    p.setPen(QColor("#e4e4ef"))
    p.drawText(text_rect, Qt.AlignCenter, "SRT")

    glow = QLinearGradient(0, 0, s * 0.5, s * 0.5)
    glow.setColorAt(0.0, QColor(255, 255, 255, 18))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path_bg, QBrush(glow))

    p.end()
    return pix


def _make_app_icon() -> QIcon:
    """
    Costruisce un QIcon multi-risoluzione dall'icona disegnata in memoria.
    Su Windows cerca app.ico se disponibile, altrimenti genera in memoria.
    Non usa app.icns (formato macOS-only).
    """
    ico = script_dir / "assets" / "app.ico"
    if ico.exists():
        logger.debug("[_make_app_icon] usando app.ico da assets/")
        return QIcon(str(ico))

    logger.debug("[_make_app_icon] generazione icona in memoria (nessun app.ico trovato)")
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


def _render_splash_pixmap(app_icon_pix: QPixmap | None = None) -> QPixmap:
    w, h = SPLASH_W, SPLASH_H
    pix = QPixmap(w, h)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    bg_path = QPainterPath()
    bg_path.addRoundedRect(QRectF(0, 0, w, h), 14, 14)

    grad = QLinearGradient(0, 0, 0, h)
    grad.setColorAt(0.0, QColor("#16162a"))
    grad.setColorAt(1.0, QColor("#0e0e1e"))
    p.fillPath(bg_path, QBrush(grad))

    p.setPen(QPainter(pix).pen())
    from PySide6.QtGui import QPen
    p.setPen(QPen(QColor("#2a2a4a"), 1.5))
    p.setBrush(Qt.NoBrush)
    p.drawPath(bg_path)

    icon_size = 72
    icon_x    = 40
    icon_y    = (h - 60) // 2 - 20

    if app_icon_pix is not None:
        scaled = app_icon_pix.scaled(
            icon_size, icon_size,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        icon_clip = QPainterPath()
        icon_clip.addRoundedRect(
            QRectF(icon_x, icon_y, icon_size, icon_size), 14, 14
        )
        p.save()
        p.setClipPath(icon_clip)
        p.drawPixmap(icon_x, icon_y, scaled)
        p.restore()

    text_x = icon_x + icon_size + 20
    p.setPen(QColor("#e4e4ef"))
    p.setFont(QFont("Segoe UI", 24, QFont.Bold))
    p.drawText(QRectF(text_x, icon_y + 2, w - text_x - 30, 40),
               Qt.AlignLeft | Qt.AlignVCenter, "Video → SRT")

    p.setPen(QColor("#6a6a8a"))
    p.setFont(QFont("Segoe UI", 11))
    p.drawText(QRectF(text_x, icon_y + 44, w - text_x - 30, 24),
               Qt.AlignLeft | Qt.AlignVCenter,
               "Trascrizione automatica italiana · Editor integrato")

    p.setPen(QColor("#3a3a5a"))
    p.setFont(QFont("Segoe UI", 10))
    p.drawText(QRectF(0, h - 22, w - 16, 16),
               Qt.AlignRight | Qt.AlignVCenter, "v2.0")

    p.end()
    return pix


class SplashState(QObject):
    step_changed = Signal(int, str)
    finished     = Signal(bool, bool)   # ffmpeg_ok, model_ok


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

        track_x = 40
        track_y  = h - 52
        track_w  = w - 80
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1e1e3a"))
        painter.drawRoundedRect(track_x, track_y, track_w, 5, 2, 2)

        fill_grad = QLinearGradient(track_x, 0, track_x + track_w, 0)
        fill_grad.setColorAt(0.0, QColor("#4f8cff"))
        fill_grad.setColorAt(1.0, QColor("#8b5cf6"))
        painter.setBrush(QBrush(fill_grad))
        fill_w = int(track_w * self._pct)
        if fill_w > 4:
            painter.drawRoundedRect(track_x, track_y, fill_w, 5, 2, 2)

        painter.setPen(QColor("#6a6a8a"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            QRectF(track_x, track_y + 12, track_w, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._msg,
        )


# ============================================================
# Main
# ============================================================
def main():
    import multiprocessing
    multiprocessing.freeze_support()   # necessario su Windows con PyInstaller

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("Video → SRT")
        app.setApplicationVersion("2.0.0")
        app.setOrganizationName("Video SRT")
    except Exception as exc:
        logger.critical("[main] impossibile creare QApplication: %s", exc)
        raise

    # Icona app — su Windows cerca app.ico, fallback generazione in memoria
    try:
        app_icon = _make_app_icon()
        app.setWindowIcon(app_icon)
    except Exception as exc:
        logger.warning("[main] errore creazione icona: %s", exc)
        app_icon = QIcon()

    # Stylesheet globale
    try:
        from ui.theme import build_stylesheet
        app.setStyleSheet(build_stylesheet())
    except Exception as exc:
        logger.error("[main] errore caricamento stylesheet: %s", exc)

    # ---- Splash ----
    try:
        icon_pix_for_splash = _draw_icon_pixmap(128)
        splash = Splash(icon_pix_for_splash)
        splash.show()
        app.processEvents()
    except Exception as exc:
        logger.warning("[main] errore splash screen: %s", exc)
        splash = None

    state = {"ffmpeg": False, "model": False, "done": False}

    def _worker():
        try:
            if splash:
                splash_state.step_changed.emit(1, "Caricamento interfaccia…")

            splash_state.step_changed.emit(2, "Verifica FFmpeg…")
            try:
                from engine import check_ffmpeg
                state["ffmpeg"] = check_ffmpeg()
                logger.info("[worker] ffmpeg disponibile: %s", state["ffmpeg"])
            except Exception as exc:
                logger.error("[worker] errore check_ffmpeg: %s", exc)
                state["ffmpeg"] = False

            splash_state.step_changed.emit(3, "Caricamento motore IA…")
            try:
                from engine import preload_model, DEFAULT_MODEL
            except Exception as exc:
                logger.critical("[worker] impossibile importare engine: %s", exc)
                state["model"] = False
                state["done"] = True
                splash_state.finished.emit(state["ffmpeg"], state["model"])
                return

            splash_state.step_changed.emit(4, "Caricamento modello Whisper…")

            def _on_status(msg):
                splash_state.step_changed.emit(4, msg)

            try:
                state["model"] = preload_model(model_size=DEFAULT_MODEL, on_status=_on_status)
                logger.info("[worker] modello caricato: %s", state["model"])
            except Exception as exc:
                logger.error("[worker] errore caricamento modello: %s", exc)
                state["model"] = False

            splash_state.step_changed.emit(5, "Pronto!")
            state["done"] = True
            splash_state.finished.emit(state["ffmpeg"], state["model"])

        except Exception as exc:
            logger.critical("[worker] errore non gestito nel thread di caricamento: %s", exc)
            state["done"] = True
            splash_state.finished.emit(False, False)

    splash_state = SplashState()
    if splash:
        splash_state.step_changed.connect(lambda i, m: splash.set_step(i, m))

    main_window_ref = {"win": None}

    def _on_ready(ffmpeg_ok: bool, model_ok: bool):
        try:
            from ui.main_window import MainWindow
            win = MainWindow(ffmpeg_ok=ffmpeg_ok, model_ok=model_ok)
            win.setWindowIcon(app_icon)
            main_window_ref["win"] = win

            def _show_main():
                if splash:
                    splash.close()
                win.show()

            QTimer.singleShot(300, _show_main)
        except Exception as exc:
            logger.critical("[_on_ready] impossibile creare MainWindow: %s", exc)
            if splash:
                splash.close()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                None, "Errore avvio",
                f"Impossibile avviare l'applicazione:\n\n{exc}\n\n"
                "Controlla il terminale per il log completo."
            )
            sys.exit(1)

    splash_state.finished.connect(_on_ready)

    threading.Thread(target=_worker, daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
