#!/usr/bin/env python3
"""
make_icon.py — Genera app.icns per Video → SRT v2.

Disegna l'icona con QPainter puro (nessuna immagine esterna):
  - Sfondo degradé blu scuro → viola
  - Ciak cinematografico stilizzato
  - Testo "SRT" in basso

Uso:
    cd macos-arm
    python assets/make_icon.py

Output:
    assets/app.icns    ← usato da build_mac.py e QApplication
    assets/app_512.png ← anteprima visibile

Requisiti: PySide6 (già nel venv del progetto)
"""

from __future__ import annotations
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ASSETS_DIR = Path(__file__).parent
ICONSET_DIR = ASSETS_DIR / "app.iconset"
ICNS_PATH   = ASSETS_DIR / "app.icns"
PNG_PATH    = ASSETS_DIR / "app_512.png"

# Dimensioni richieste da macOS iconset
SIZES = [16, 32, 64, 128, 256, 512, 1024]


def draw_icon(size: int) -> "QPixmap":
    """Disegna l'icona alla dimensione richiesta e la restituisce come QPixmap."""
    from PySide6.QtCore import Qt, QRectF, QPointF
    from PySide6.QtGui import (
        QPixmap, QPainter, QLinearGradient, QColor,
        QFont, QPen, QPainterPath, QBrush,
    )

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    s = float(size)
    r = s * 0.12  # raggio angoli

    # ---- Sfondo: degradé blu notte → indaco ----
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0.0, QColor("#1a1a3f"))
    grad.setColorAt(1.0, QColor("#0d0d1f"))
    path_bg = QPainterPath()
    path_bg.addRoundedRect(QRectF(0, 0, s, s), r, r)
    p.fillPath(path_bg, QBrush(grad))

    # ---- Ciak superiore (barra nera e bianca) ----
    ciak_h   = s * 0.22
    ciak_y   = s * 0.10
    ciak_x   = s * 0.10
    ciak_w   = s * 0.80

    # Corpo ciak
    p.setBrush(QColor("#111111"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(ciak_x, ciak_y, ciak_w, ciak_h), s * 0.04, s * 0.04)

    # Strisce diagonali bianche/nere sopra il ciak
    stripe_h = ciak_h * 0.40
    n_stripes = 7
    stripe_w  = ciak_w / n_stripes
    for i in range(n_stripes):
        color = QColor("#ffffff") if i % 2 == 0 else QColor("#111111")
        p.setBrush(color)
        sx = ciak_x + i * stripe_w
        sp = QPainterPath()
        # Parallelogramma inclinato
        offset = stripe_h * 0.6
        sp.moveTo(QPointF(sx + offset, ciak_y))
        sp.lineTo(QPointF(sx + stripe_w + offset, ciak_y))
        sp.lineTo(QPointF(sx + stripe_w, ciak_y + stripe_h))
        sp.lineTo(QPointF(sx, ciak_y + stripe_h))
        sp.closeSubpath()
        # Clipa alle dimensioni del ciak
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(ciak_x, ciak_y, ciak_w, stripe_h), s * 0.04, s * 0.04)
        sp = sp.intersected(clip)
        p.fillPath(sp, color)

    # Cerniera verticale sinistra del ciak
    hinge_w = s * 0.04
    hinge_x = ciak_x + s * 0.06
    p.setBrush(QColor("#333333"))
    p.drawRect(QRectF(hinge_x, ciak_y, hinge_w, ciak_h))

    # ---- Forma d'onda / barre audio ----
    bar_count = 18
    bar_area_x = s * 0.10
    bar_area_w = s * 0.80
    bar_area_y = s * 0.40
    bar_area_h = s * 0.30
    bar_w = bar_area_w / bar_count * 0.6
    bar_gap = bar_area_w / bar_count

    # Altezze variabili per simulare forma d'onda parlato
    import math
    heights = [
        abs(math.sin(i * 0.7 + 0.5)) * 0.7 + 0.15
        for i in range(bar_count)
    ]
    heights[bar_count // 2]     = 1.0
    heights[bar_count // 2 - 1] = 0.85
    heights[bar_count // 2 + 1] = 0.90

    wave_grad = QLinearGradient(0, bar_area_y, 0, bar_area_y + bar_area_h)
    wave_grad.setColorAt(0.0, QColor("#4f8cff"))
    wave_grad.setColorAt(1.0, QColor("#8b5cf6"))

    for i, h in enumerate(heights):
        bh = bar_area_h * h
        bx = bar_area_x + i * bar_gap + (bar_gap - bar_w) / 2
        by = bar_area_y + bar_area_h - bh
        p.setBrush(QBrush(wave_grad))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(bx, by, bar_w, bh), bar_w * 0.4, bar_w * 0.4)

    # ---- Testo "SRT" in basso ----
    font_size = max(8, int(s * 0.175))
    font = QFont("SF Pro Display", font_size)
    font.setBold(True)
    font.setLetterSpacing(QFont.AbsoluteSpacing, s * 0.025)
    p.setFont(font)

    text_rect = QRectF(0, s * 0.72, s, s * 0.22)
    # Ombra
    p.setPen(QColor(0, 0, 0, 120))
    shadow_rect = text_rect.translated(s * 0.008, s * 0.008)
    p.drawText(shadow_rect, Qt.AlignCenter, "SRT")
    # Testo vero
    p.setPen(QColor("#e4e4ef"))
    p.drawText(text_rect, Qt.AlignCenter, "SRT")

    # ---- Bagliore in alto a sinistra ----
    glow = QLinearGradient(0, 0, s * 0.5, s * 0.5)
    glow.setColorAt(0.0, QColor(255, 255, 255, 18))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.fillPath(path_bg, QBrush(glow))

    p.end()
    return pix


def save_png(pix: "QPixmap", path: Path):
    pix.save(str(path), "PNG")


def build_iconset():
    """Genera tutte le dimensioni PNG nell'iconset."""
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    for sz in SIZES:
        pix = draw_icon(sz)
        save_png(pix, ICONSET_DIR / f"icon_{sz}x{sz}.png")
        # macOS vuole anche @2x per le versioni inferiori
        if sz <= 512:
            save_png(pix, ICONSET_DIR / f"icon_{sz}x{sz}@2x.png")
    print(f"✅  Iconset generato in {ICONSET_DIR}/")


def iconset_to_icns():
    """Converte l'iconset in .icns usando iconutil (nativo macOS)."""
    if sys.platform != "darwin":
        print("⚠️   iconutil disponibile solo su macOS — .icns non generato.")
        return False
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"✅  Icona macOS creata: {ICNS_PATH}")
        return True
    else:
        print(f"❌  iconutil fallito: {result.stderr}")
        return False


def main():
    # Bootstrap QApplication (necessario per QPainter/QPixmap)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    print("🎨  Generazione icona Video → SRT...")

    # Genera anteprima 512px
    pix_512 = draw_icon(512)
    save_png(pix_512, PNG_PATH)
    print(f"✅  Anteprima PNG: {PNG_PATH}")

    # Genera iconset completo
    build_iconset()

    # Converti in .icns
    ok = iconset_to_icns()

    if ok:
        print(f"\n📦  Pronto per il build:")
        print(f"    python build_mac.py")
    else:
        print(f"\n📦  Usa {PNG_PATH} come icona alternativa.")

    print(f"\nAnteprima: open \"{PNG_PATH}\"")


if __name__ == "__main__":
    main()
