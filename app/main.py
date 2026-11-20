"""
main.py — Entry point dell'applicazione Video → SRT v2 (PySide6).

Splash screen (ui/brand) → caricamento progressivo in thread → MainWindow.
"""

from __future__ import annotations
import logging
import os
import sys
import threading
import traceback
from pathlib import Path

# PATH setup
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QObject
from PySide6.QtGui import QFont, QPixmap, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

import platform_support
from ui import brand

logger = logging.getLogger(__name__)


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
    return brand.draw_app_icon(size)


def _make_app_icon() -> QIcon:
    """Costruisce un QIcon: dal file se esiste, altrimenti multi-risoluzione in memoria."""
    path = _icon_file()
    if path is not None:
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon

    icon = QIcon()
    for sz in (16, 32, 64, 128, 256, 512, 1024):
        icon.addPixmap(brand.draw_app_icon(sz))
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


class SplashState(QObject):
    """Segnali emessi dal thread worker; i ricevitori vivono nel thread GUI."""

    step_changed = Signal(int, str)
    finished     = Signal(bool, str)    # ok, messaggio di errore (vuoto se ok)


class Splash(QSplashScreen):
    """Splash di avvio: la testina sulla forma d'onda avanza a ogni passo.

    Disegno in ui/brand (nel tema già applicato, nitido alla densità dello schermo).
    """

    def __init__(self):
        screen = QApplication.primaryScreen()
        self._dpr = screen.devicePixelRatio() if screen is not None else 1.0
        self._pct = 0.0
        self._msg = STEPS[0]
        super().__init__(self._render())
        self.setWindowFlags(
            Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

    def _render(self) -> QPixmap:
        return brand.splash_pixmap(self._pct, self._msg,
                                   QApplication.applicationVersion(), self._dpr)

    def set_step(self, idx: int, msg: str | None = None):
        self._msg = msg or (STEPS[idx] if idx < len(STEPS) else "Pronto!")
        self._pct = (idx + 1) / len(STEPS)
        self.setPixmap(self._render())
        self.repaint()


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

    # Autotest dell'app (anche compilata): niente finestre, esito nel codice di uscita
    if "--self-test" in sys.argv:
        import self_test
        sys.exit(self_test.main(sys.argv))

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
    splash = Splash()
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
            from engine import preload_model, recommended_model
            from PySide6.QtCore import QSettings
            from ui.prefs import read_config

            splash_state.step_changed.emit(4, "Caricamento modello Whisper…")

            def _on_status(msg):
                splash_state.step_changed.emit(4, msg)

            # Il modello che la Home proporrà (ultimo usato o consigliato per il computer),
            # solo se è già scaricato: mai un download durante lo splash.
            model = read_config(QSettings("VideoSRT", "v2"),
                                default_model=recommended_model())[0].model_size
            result["model"] = preload_model(model_size=model, on_status=_on_status)
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
