"""
main.py — Entry point dell'applicazione Video → SRT v2 (PySide6).

Splash screen con icona → caricamento progressivo in thread → MainWindow.
"""

from __future__ import annotations
import sys
import threading
import math
from pathlib import Path

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
    font = QFont("Helvetica Neue", font_size)
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


def _make_app_icon() -> QIcon:
    """Costruisce un QIcon multi-risoluzione dall'icona disegnata."""
    # Prima cerca il file .icns se già generato
    icns = script_dir / "assets" / "app.icns"
    if icns.exists():
        return QIcon(str(icns))

    # Altrimenti genera in memoria
    icon = QIcon()
    for sz in (16, 32, 64, 128, 256, 512):
        icon.addPixmap(_draw_icon_pixmap(sz))
    return icon


def _set_dock_icon_macos(pixmap: QPixmap) -> None:
    """
    Imposta l'icona Dock di macOS a livello di processo (NSApp).
    In modalità sviluppo (python main.py) questo sostituisce l'icona Python
    nel Dock per tutta la durata dell'app, inclusa la fase di chiusura.
    Fallisce silenziosamente su non-macOS o se pyobjc non è disponibile.
    """
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSData, NSImage
        from PySide6.QtCore import QBuffer, QIODevice

        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        pixmap.save(buf, "PNG")
        buf.close()
        png_bytes = bytes(buf.data())

        ns_img = NSImage.alloc().initWithData_(
            NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
        )
        NSApplication.sharedApplication().setApplicationIconImage_(ns_img)
    except Exception:
        pass  # Non critico — l'icona Dock rimarrà quella di Python


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
    bg_path.addRoundedRect(QRectF(0, 0, w, h), 14, 14)

    grad = QLinearGradient(0, 0, 0, h)
    grad.setColorAt(0.0, QColor("#16162a"))
    grad.setColorAt(1.0, QColor("#0e0e1e"))
    p.fillPath(bg_path, QBrush(grad))

    # Bordo sottile
    from PySide6.QtGui import QPen
    p.setPen(QPen(QColor("#2a2a4a"), 1.5))
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
            QRectF(icon_x, icon_y, icon_size, icon_size), 14, 14
        )
        p.save()
        p.setClipPath(icon_clip)
        p.drawPixmap(icon_x, icon_y, scaled)
        p.restore()

    # Titolo
    text_x = icon_x + icon_size + 20
    p.setPen(QColor("#e4e4ef"))
    p.setFont(QFont("Helvetica Neue", 26, QFont.Bold))
    p.drawText(QRectF(text_x, icon_y + 2, w - text_x - 30, 40),
               Qt.AlignLeft | Qt.AlignVCenter, "Video → SRT")

    # Sottotitolo
    p.setPen(QColor("#6a6a8a"))
    p.setFont(QFont("Helvetica Neue", 12))
    p.drawText(QRectF(text_x, icon_y + 44, w - text_x - 30, 24),
               Qt.AlignLeft | Qt.AlignVCenter,
               "Trascrizione automatica italiana · Editor integrato")

    # Versione
    p.setPen(QColor("#3a3a5a"))
    p.setFont(QFont("Helvetica Neue", 10))
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

        # Progress track
        track_x = 40
        track_y  = h - 52
        track_w  = w - 80
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1e1e3a"))
        painter.drawRoundedRect(track_x, track_y, track_w, 5, 2, 2)

        # Progress fill
        fill_grad = QLinearGradient(track_x, 0, track_x + track_w, 0)
        fill_grad.setColorAt(0.0, QColor("#4f8cff"))
        fill_grad.setColorAt(1.0, QColor("#8b5cf6"))
        painter.setBrush(QBrush(fill_grad))
        fill_w = int(track_w * self._pct)
        if fill_w > 4:
            painter.drawRoundedRect(track_x, track_y, fill_w, 5, 2, 2)

        # Messaggio
        painter.setPen(QColor("#6a6a8a"))
        painter.setFont(QFont("Helvetica Neue", 11))
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
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)
    app.setApplicationName("Video → SRT")
    app.setApplicationVersion("2.0.0")
    app.setOrganizationName("Video SRT")

    # ---- Icona app (Dock macOS + titolo finestra) ----
    app_icon = _make_app_icon()
    app.setWindowIcon(app_icon)

    # Imposta icona a livello di processo NSApp — sovrascrive l'icona Python nel Dock
    # in modalità sviluppo (python main.py) e la mantiene fino alla chiusura del processo.
    _set_dock_icon_macos(_draw_icon_pixmap(512))

    # Stylesheet globale — applica il tema salvato (default scuro)
    from PySide6.QtCore import QSettings
    from ui import theme as _theme
    saved_theme = QSettings("VideoSRT", "v2").value("theme", "dark")
    if saved_theme not in ("dark", "light"):
        saved_theme = "dark"
    _theme.apply_theme(app, saved_theme)

    # ---- Splash ----
    # Usa il pixmap 128px dell'icona per la splash
    icon_pix_for_splash = _draw_icon_pixmap(128)
    splash = Splash(icon_pix_for_splash)
    splash.show()
    app.processEvents()

    state = {"ffmpeg": False, "model": False, "done": False}

    def _worker():
        splash_state.step_changed.emit(1, "Caricamento interfaccia…")

        splash_state.step_changed.emit(2, "Verifica FFmpeg…")
        from engine import check_ffmpeg
        state["ffmpeg"] = check_ffmpeg()

        splash_state.step_changed.emit(3, "Caricamento motore IA…")
        from engine import preload_model, DEFAULT_MODEL

        splash_state.step_changed.emit(4, "Caricamento modello Whisper…")

        def _on_status(msg):
            splash_state.step_changed.emit(4, msg)

        state["model"] = preload_model(model_size=DEFAULT_MODEL, on_status=_on_status)

        splash_state.step_changed.emit(5, "Pronto!")
        state["done"] = True
        splash_state.finished.emit(state["ffmpeg"], state["model"])

    splash_state = SplashState()
    splash_state.step_changed.connect(lambda i, m: splash.set_step(i, m))

    main_window_ref = {"win": None}

    def _on_ready(ffmpeg_ok: bool, model_ok: bool):
        from ui.main_window import MainWindow
        win = MainWindow(ffmpeg_ok=ffmpeg_ok, model_ok=model_ok)
        win.setWindowIcon(app_icon)
        main_window_ref["win"] = win

        # Mostra la finestra principale solo dopo che la splash è chiusa:
        # evita il flash di UI dietro la splash e garantisce una transizione pulita.
        def _show_main():
            splash.close()
            win.show()

        QTimer.singleShot(300, _show_main)

    splash_state.finished.connect(_on_ready)

    threading.Thread(target=_worker, daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
