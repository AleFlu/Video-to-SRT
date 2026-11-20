#!/usr/bin/env python3
"""
make_icon.py — Rigenera le icone di Video → SRT dal disegno di ui/brand.py.

L'icona "Bianco e nero" (quadrato nero, forma d'onda grigia, due righe di sottotitolo
bianche) è disegnata con QPainter in ui/brand.draw_app_icon: questo script la salva nei
formati che servono ai build e all'avvio.

Uso (dalla root del repository):
    python app/assets/make_icon.py

Output in app/assets/:
    app.icns    ← macOS: build_mac.py, Dock e finestra (solo su macOS: serve iconutil)
    app.ico     ← Windows: build_windows.py, barra delle applicazioni e finestra
    app_512.png ← anteprima e ripiego (sfondo dell'installer .pkg)

Requisiti: PySide6 (già nel venv del progetto).
"""

from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QPixmap

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import platform_support  # noqa: E402

ASSETS_DIR = Path(__file__).resolve().parent
ICNS_PATH = ASSETS_DIR / "app.icns"
ICO_PATH = ASSETS_DIR / "app.ico"
PNG_PATH = ASSETS_DIR / "app_512.png"

# Iconset macOS: (nome, lato in pixel). Le @2x hanno il doppio dei pixel della misura.
ICONSET = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]
# Misure dell'.ico (Windows sceglie la più adatta a schermo e scala).
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def png_bytes(pix: "QPixmap") -> bytes:
    """PNG in memoria."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    pix.save(buf, "PNG")
    buf.close()
    return bytes(data)


def ico_bytes(images: list[tuple[int, bytes]]) -> bytes:
    """File .ico con le immagini PNG date [(lato, png)] (formato valido da Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for side, png in images:
        dim = 0 if side >= 256 else side            # 0 = 256 px
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return header + entries + blobs


def build_icns() -> bool:
    """app.icns via iconutil (solo macOS)."""
    from ui.brand import MARGIN_MAC, draw_app_icon

    if not platform_support.IS_MAC:
        print("iconutil c'è solo su macOS: app.icns non rigenerato.")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "app.iconset"
        iconset.mkdir()
        for name, side in ICONSET:
            draw_app_icon(side, MARGIN_MAC).save(str(iconset / name), "PNG")
        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS_PATH)],
            capture_output=True, text=True,
        )
    if result.returncode != 0:
        print(f"iconutil non riuscito: {result.stderr.strip()}")
        return False
    print(f"Icona macOS: {ICNS_PATH}")
    return True


def build_ico() -> None:
    """app.ico (Windows): quadrato quasi a filo, come le icone di sistema."""
    from ui.brand import MARGIN_FLAT, draw_app_icon

    images = [(side, png_bytes(draw_app_icon(side, MARGIN_FLAT))) for side in ICO_SIZES]
    ICO_PATH.write_bytes(ico_bytes(images))
    print(f"Icona Windows: {ICO_PATH}")


def build_png() -> None:
    """app_512.png: anteprima con i margini macOS."""
    from ui.brand import MARGIN_MAC, draw_app_icon

    draw_app_icon(512, MARGIN_MAC).save(str(PNG_PATH), "PNG")
    print(f"Anteprima: {PNG_PATH}")


def main() -> None:
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841  (serve a QPixmap)
    build_png()
    build_ico()
    build_icns()


if __name__ == "__main__":
    main()
