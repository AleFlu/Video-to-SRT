"""
fonts.py — Registrazione dei font IBM Plex inclusi nell'app.

I file stanno in ``assets/fonts``: nel bundle PyInstaller sotto ``sys._MEIPASS``,
altrimenti accanto a ``app/``. I percorsi passati a Qt sono sempre ASSOLUTI
(quelli relativi falliscono su macOS). Un font mancante o non valido non blocca
l'avvio: si registra l'errore e restano i font di sistema del ripiego.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QFontDatabase

logger = logging.getLogger(__name__)

FONT_FILES = (
    "IBMPlexSans-Regular.ttf",
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-SemiBold.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Medium.ttf",
)


def fonts_dir() -> Path:
    """Cartella assoluta dei font (bundle PyInstaller o sorgenti)."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return (root / "assets" / "fonts").resolve()


def load_app_fonts() -> list[str]:
    """Registra i font IBM Plex; ritorna le famiglie caricate (senza duplicati)."""
    folder = fonts_dir()
    families: list[str] = []
    for name in FONT_FILES:
        path = folder / name
        if not path.is_file():
            logger.warning("Font mancante: %s", path)
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            logger.warning("Font non caricabile: %s", path)
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in families:
                families.append(family)
    if families:
        logger.info("Font caricati: %s", ", ".join(families))
    return families
