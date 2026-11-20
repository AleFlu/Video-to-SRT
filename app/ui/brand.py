"""
brand.py — Marchio "Bianco e nero" di Video → SRT: icona dell'app e splash di avvio.

Un solo disegno, usato da:
  - main.py: splash di avvio e icona in memoria (Linux, o se mancano i file in assets/);
  - assets/make_icon.py: rigenera app.icns, app.ico e app_512.png.

Icona: quadrato nero arrotondato con una forma d'onda grigia (l'audio) sopra due righe
bianche (il sottotitolo). Niente testo, niente sfumature né colore: si legge anche a 16 px.

Splash: in alto una fascia con la forma d'onda dell'editor, in cui la testina avanza col
caricamento; sotto icona, nome, descrizione, messaggio di avanzamento e versione. Segue il
tema scelto dall'utente; l'icona è sempre quella scura (è l'icona del Dock).

Colori: token di ui/theme, come nel resto dell'interfaccia.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen, QPixmap

import platform_support
from ui import theme

# ── Icona ────────────────────────────────────────────────────────────────────

# Margine attorno al quadrato, in frazione del lato: griglia delle icone macOS (corpo di
# 824 px su 1024) e quasi a filo per Windows/Linux, dove le icone non hanno margine.
MARGIN_MAC = 100 / 1024
MARGIN_FLAT = 0.03

# Altezze della forma d'onda dell'icona (una parola: sale, picco, ricade).
_ICON_WAVE = (0.30, 0.55, 0.85, 0.45, 1.00, 0.70, 0.40, 0.80, 0.50, 0.65, 0.35)
_ICON_WAVE_SMALL = (0.45, 1.00, 0.60, 0.85, 0.40)


SMALL_ICON = 32     # fino a questa misura l'icona è disegnata sulla griglia dei pixel


def draw_app_icon(size: int, margin: float = MARGIN_MAC) -> QPixmap:
    """Icona dell'app (size × size px, sfondo trasparente fuori dal quadrato).

    Fino a SMALL_ICON px barre e righe cadono su pixel interi, senza antialiasing:
    altrimenti a 16 e 32 px la forma d'onda e le due righe si impastano in un grigio.
    """
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    s = float(size)
    small = size <= SMALL_ICON
    if small:   # margine intero (almeno 1 px per il bordo)
        x = float(max(1, int(s * margin)))
    else:
        x = s * margin
    w = s - 2 * x

    # Quadrato con bordo sottile: resta visibile anche su un Dock scuro.
    edge = max(1.0, s * 0.004)
    body = QPainterPath()
    body.addRoundedRect(QRectF(x + edge / 2, x + edge / 2, w - edge, w - edge),
                        w * 0.225, w * 0.225)
    p.fillPath(body, theme.qcolor("bg", "dark"))
    p.setPen(QPen(theme.qcolor("line_2", "dark"), edge))
    p.setBrush(Qt.NoBrush)
    p.drawPath(body)
    p.setPen(Qt.NoPen)

    if small:
        _draw_small_marks(p, int(x), int(w))
        p.end()
        return pix

    # Forma d'onda (l'audio): barre grigie arrotondate, centrate.
    area_x, area_w = x + w * 0.17, w * 0.66
    mid_y, area_h = x + w * 0.38, w * 0.30
    step = area_w / len(_ICON_WAVE)
    bar_w = step * 0.5
    p.setBrush(theme.qcolor("label", "dark"))
    for i, f in enumerate(_ICON_WAVE):
        bh = max(bar_w, area_h * f)
        bx = area_x + i * step + (step - bar_w) / 2
        p.drawRoundedRect(QRectF(bx, mid_y - bh / 2, bar_w, bh), bar_w / 2, bar_w / 2)

    # Due righe di sottotitolo (il testo): bianche, centrate, la seconda più corta.
    line_h = w * 0.068
    gap = line_h * 0.75
    top = x + w * 0.62
    p.setBrush(theme.qcolor("text", "dark"))
    for k, frac in enumerate((0.62, 0.42)):
        lw = w * frac
        p.drawRoundedRect(QRectF(s / 2 - lw / 2, top + k * (line_h + gap), lw, line_h),
                          line_h / 2, line_h / 2)
    p.end()
    return pix


def _draw_small_marks(p: QPainter, x: int, w: int) -> None:
    """Onda e righe dell'icona piccola, su pixel interi (rettangoli pieni).

    Dall'alto: bordo, margine, onda, spazio, due righe, margine, bordo. A 16 px le righe
    sono alte 1 px e la barra centrale 2 px, così tutto resta centrato sull'asse.
    """
    p.setRenderHint(QPainter.Antialiasing, False)
    unit = max(1, round(w / 14))              # 1 px a 16, 2 px a 24-32
    pad, wave_gap = (1, 1) if unit == 1 else (3, 2)
    cx = x + w // 2
    inner_top = x + 1 + pad                   # sotto il bordo
    inner_bottom = x + w - 1 - pad            # sopra il bordo (escluso)
    lines_top = inner_bottom - 3 * unit       # due righe alte `unit`, spazio `unit`
    wave_h = lines_top - wave_gap - inner_top

    # Cinque barre larghe `unit` (la centrale 2 px a 16), distanziate di `unit`.
    widths = [unit] * len(_ICON_WAVE_SMALL)
    if unit == 1:
        widths[len(widths) // 2] = 2
    bx = cx - (sum(widths) + (len(widths) - 1) * unit) // 2
    p.setBrush(theme.qcolor("label", "dark"))
    for bw, f in zip(widths, _ICON_WAVE_SMALL):
        bh = max(unit, round(wave_h * f))
        p.drawRect(bx, inner_top + (wave_h - bh) // 2, bw, bh)
        bx += bw + unit

    # Due righe, la seconda più corta; larghezze pari: centrate esattamente.
    p.setBrush(theme.qcolor("text", "dark"))
    for k, frac in enumerate((0.70, 0.44)):
        lw = 2 * round(w * frac / 2)
        p.drawRect(cx - lw // 2, lines_top + 2 * k * unit, lw, unit)
    p.setRenderHint(QPainter.Antialiasing, True)


# ── Splash di avvio ──────────────────────────────────────────────────────────

SPLASH_W = 560
SPLASH_H = 300
BANNER_H = 150
_PAD = 32           # margine laterale del contenuto (anche della forma d'onda)
_BAR_W = 2.0
_BAR_STEP = 4.0
_TIMELINE_S = 30.0  # durata finta della fascia, per il timecode della testina

TAGLINE = "Trascrizione automatica e editor di sottotitoli"


def _speech_envelope(count: int) -> list[float]:
    """Altezze (0..1) di una forma d'onda di parlato: parole separate da brevi pause.

    Sempre la stessa (seme fisso): lo splash non cambia da un avvio all'altro.
    """
    rnd = random.Random(7)
    out: list[float] = []
    while len(out) < count:
        length = rnd.randint(7, 16)
        peak = rnd.uniform(0.55, 1.0)
        for i in range(length):
            t = (i + 0.5) / length
            out.append(peak * math.sin(math.pi * t) ** 0.6 * rnd.uniform(0.55, 1.0))
        out.extend(rnd.uniform(0.03, 0.08) for _ in range(rnd.randint(2, 4)))
    return out[:count]


def _timecode(seconds: float) -> str:
    """Timecode SRT (HH:MM:SS,mmm)."""
    ms = int(round(seconds * 1000))
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    sec, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def _font(family: str, px: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont(family)
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def splash_pixmap(progress: float, message: str, version: str = "",
                  dpr: float = 1.0, theme_name: str | None = None) -> QPixmap:
    """Immagine dello splash (SPLASH_W × SPLASH_H punti, nitida a `dpr`).

    `progress` (0..1) sposta la testina sulla forma d'onda: la parte già "suonata" è più
    chiara. `theme_name` None = tema corrente.
    """
    def col(token: str):
        return theme.qcolor(token, theme_name)

    progress = max(0.0, min(1.0, progress))
    w, h = SPLASH_W, SPLASH_H
    pix = QPixmap(round(w * dpr), round(h * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    # Finestra: fondo, raggio 6 come i dialog, bordo di 1 px.
    frame = QPainterPath()
    frame.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)
    p.fillPath(frame, col("bg"))

    # Fascia: pannello con la forma d'onda e la testina.
    p.save()
    p.setClipPath(frame)
    p.fillRect(QRectF(0, 0, w, BANNER_H), col("panel"))
    p.restore()
    p.fillRect(QRectF(0, BANNER_H, w, 1), col("line"))

    wave_x0, wave_x1 = float(_PAD), float(w - _PAD)
    # Testina allineata ai pixel dello schermo: resta una linea netta anche a 1x.
    head_x = round((wave_x0 + progress * (wave_x1 - wave_x0)) * dpr) / dpr
    mid_y, amp = BANNER_H * 0.58, BANNER_H * 0.30
    count = int((wave_x1 - wave_x0) // _BAR_STEP)
    p.setPen(Qt.NoPen)
    for i, f in enumerate(_speech_envelope(count)):
        bx = wave_x0 + i * _BAR_STEP
        bh = max(_BAR_W, 2 * amp * f)
        p.setBrush(col("dim") if bx + _BAR_W <= head_x else col("wave"))
        p.drawRoundedRect(QRectF(bx, mid_y - bh / 2, _BAR_W, bh), 1, 1)

    # Testina: linea + triangolo in alto, timecode accanto (a sinistra verso la fine).
    head_top = 34.0
    p.fillRect(QRectF(head_x - 1, head_top, 2, BANNER_H - head_top), col("playhead"))
    tri = QPainterPath()
    tri.moveTo(head_x - 5, head_top - 6)
    tri.lineTo(head_x + 5, head_top - 6)
    tri.lineTo(head_x, head_top + 1)
    tri.closeSubpath()
    p.fillPath(tri, col("playhead"))
    mono = _font(platform_support.mono_font_family(), 11)
    p.setFont(mono)
    p.setPen(col("label"))
    tc = _timecode(progress * _TIMELINE_S)
    tc_w = 96.0
    if head_x + 10 + tc_w <= wave_x1:
        p.drawText(QRectF(head_x + 10, head_top - 12, tc_w, 14),
                   Qt.AlignLeft | Qt.AlignVCenter, tc)
    else:
        p.drawText(QRectF(head_x - 10 - tc_w, head_top - 12, tc_w, 14),
                   Qt.AlignRight | Qt.AlignVCenter, tc)

    # Icona, nome e descrizione.
    icon_size = 56
    icon_y = BANNER_H + 30
    icon = draw_app_icon(round(icon_size * dpr), margin=0.0)
    icon.setDevicePixelRatio(dpr)
    p.drawPixmap(QPointF(_PAD, icon_y), icon)
    text_x = _PAD + icon_size + 18
    p.setPen(col("text"))
    p.setFont(_font(platform_support.ui_font_family(), 22, QFont.DemiBold))
    p.drawText(QRectF(text_x, icon_y, w - text_x - _PAD, 30),
               Qt.AlignLeft | Qt.AlignVCenter, "Video → SRT")
    p.setPen(col("dim"))
    p.setFont(_font(platform_support.ui_font_family(), 13))
    p.drawText(QRectF(text_x, icon_y + 32, w - text_x - _PAD, 20),
               Qt.AlignLeft | Qt.AlignVCenter, TAGLINE)

    # In fondo: messaggio di avanzamento e versione.
    foot_y = h - 40
    p.setPen(col("label"))
    p.setFont(_font(platform_support.ui_font_family(), 12))
    p.drawText(QRectF(_PAD, foot_y, w - 2 * _PAD - 80, 20),
               Qt.AlignLeft | Qt.AlignVCenter, message)
    if version:
        p.setFont(mono)
        p.drawText(QRectF(w - _PAD - 80, foot_y, 80, 20),
                   Qt.AlignRight | Qt.AlignVCenter, f"v{version}")

    # Bordo per ultimo, sopra la fascia.
    p.setPen(QPen(col("line"), 1))
    p.setBrush(Qt.NoBrush)
    p.drawPath(frame)
    p.end()
    return pix
