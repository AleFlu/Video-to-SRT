"""
icons.py — Icone a tratto dell'interfaccia (path SVG dei mockup di redesign).

Tutte su viewBox 24×24, tratto 1.6, estremità e giunzioni arrotondate; solo
``play`` e ``stop`` sono piene. Le icone vengono rese con ``QSvgRenderer`` a
risoluzione doppia (HiDPI) nel colore di un token del tema, con cache per
(nome, colore, dimensione, dpr).

Uso:
    from ui import icons
    btn.setIcon(icons.icon("export", "acc_ink"))      # statica
    icons.bind_icon(btn, "export", "dim")              # segue il cambio tema
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton

from ui import theme

logger = logging.getLogger(__name__)

STROKE_WIDTH = 1.6

# Nome → path SVG (viewBox 0 0 24 24), copiati dai mockup.
ICON_PATHS: dict[str, str] = {
    "play": "M8 5l11 7-11 7z",
    "stop": "M7 7h10v10H7z",
    "pause": "M9 5v14M15 5v14",
    "loop": "M17 2l4 4-4 4M3 12v-2a4 4 0 0 1 4-4h14M7 22l-4-4 4-4M21 12v2a4 4 0 0 1-4 4H3",
    "undo": "M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3",
    "redo": "M15 14l5-5-5-5M20 9H10a6 6 0 0 0 0 12h3",
    "split": "M12 3v18M5 8l4 4-4 4M19 8l-4 4 4 4",
    "merge": "M4 8l4 4-4 4M20 8l-4 4 4 4M8 12h8",
    "trash": "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
    "import": "M12 4v11M7.5 10.5L12 15l4.5-4.5M5 20h14",
    "replace": "M4 7h11l-3-3M20 17H9l3 3",
    "panel_right": "M4 5h16v14H4zM15 5v14",
    "search": "M4 11a7 7 0 1 0 14 0 7 7 0 1 0-14 0M21 21l-5-5",
    "export": "M12 21V9M7 14l5-5 5 5M5 3h14",
    "chevron_down": "M6 9l6 6 6-6",
    "close": "M6 6l12 12M18 6L6 18",
    "plus": "M12 5v14M5 12h14",
    "moon": "M20 14A8 8 0 0 1 10 4a8 8 0 1 0 10 10z",
    "sun": ("M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4 12H2M22 12h-2"
            "M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"),
    "lock": "M6 11h12v9H6zM8 11V7a4 4 0 0 1 8 0v4",
    "alert": "M12 4l9 16H3zM12 10v4M12 17v.5",
    "volume": "M4 10v4h4l5 4V6l-5 4zM17 9a4 4 0 0 1 0 6",
    "check": "M5 12l5 5 9-10",
    "copy": "M9 9h10v11H9zM5 15V4h10",
    "download": "M12 3v12M7 10l5 5 5-5M5 21h14",
    "arrow_right": "M5 12h14M13 6l6 6-6 6",
    "video": "M4 6h11v12H4zM15 10l5-3v10l-5-3",
    "audio": ("M9 18V6l10-2v12M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0"
              "M19 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0"),
    "document": "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h5",
}

# Icone piene (fill = colore, nessun tratto)
FILLED = frozenset({"play", "stop"})

_PIXMAP_CACHE: dict = {}
_ICON_CACHE: dict = {}


def names() -> list[str]:
    """Nomi delle icone disponibili."""
    return sorted(ICON_PATHS)


def svg_markup(name: str, color: QColor) -> str:
    """SVG completo dell'icona ``name`` nel colore indicato."""
    path = ICON_PATHS[name]
    rgb = color.name(QColor.HexRgb)
    opacity = f' opacity="{color.alphaF():.3f}"' if color.alpha() < 255 else ""
    if name in FILLED:
        body = (f'<path d="{path}" fill="{rgb}" stroke="{rgb}" stroke-width="{STROKE_WIDTH}" '
                f'stroke-linejoin="round"{opacity}/>')
    else:
        body = (f'<path d="{path}" fill="none" stroke="{rgb}" stroke-width="{STROKE_WIDTH}" '
                f'stroke-linecap="round" stroke-linejoin="round"{opacity}/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'


def _as_color(color) -> QColor:
    """Accetta un QColor o il valore di un token (hex/rgba) del tema."""
    if isinstance(color, QColor):
        return color
    return theme.qcolor(str(color)) if str(color) in theme.tokens() else QColor(str(color))


def pixmap(name: str, color, size: int = 16, dpr: float = 2.0) -> QPixmap:
    """Pixmap dell'icona ``name`` (``size`` px logici) nel colore dato, a ``dpr``."""
    col = _as_color(color)
    key = (name, col.rgba(), size, dpr)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    side = max(1, int(round(size * dpr)))
    pix = QPixmap(side, side)
    pix.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg_markup(name, col).encode("utf-8")))
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, side, side))
    finally:
        painter.end()
    pix.setDevicePixelRatio(dpr)
    if len(_PIXMAP_CACHE) > 600:
        _PIXMAP_CACHE.clear()
    _PIXMAP_CACHE[key] = pix
    return pix


def icon(name: str, color_token: str = "dim", size: int = 16) -> QIcon:
    """
    QIcon dell'icona ``name`` nel colore del token (tema corrente). Lo stato
    disabilitato usa ``faint``. Non segue il cambio tema da sola: vedi ``bind_icon``.
    """
    key = (name, color_token, size, theme.get_theme())
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    ic = QIcon()
    normal = pixmap(name, theme.qcolor(color_token), size)
    ic.addPixmap(normal, QIcon.Normal, QIcon.Off)
    ic.addPixmap(normal, QIcon.Normal, QIcon.On)
    ic.addPixmap(normal, QIcon.Active, QIcon.Off)
    ic.addPixmap(normal, QIcon.Active, QIcon.On)
    ic.addPixmap(pixmap(name, theme.qcolor("faint"), size), QIcon.Disabled, QIcon.Off)
    ic.addPixmap(pixmap(name, theme.qcolor("faint"), size), QIcon.Disabled, QIcon.On)
    _ICON_CACHE[key] = ic
    return ic


class _IconBinding(QObject):
    """Riapplica l'icona al widget/azione quando cambia il tema."""

    def __init__(self, target, name: str, color_token: str, size: int):
        super().__init__(target)
        self._target = target
        self._name: str | None = name
        self._token = color_token
        self._size = size
        self.refresh()
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    def set_icon(self, name: str | None, color_token: str | None = None) -> None:
        """Cambia icona (es. play ↔ pausa; ``None`` la toglie) mantenendo il legame col tema."""
        self._name = name
        if color_token is not None:
            self._token = color_token
        self.refresh()

    def refresh(self) -> None:
        if self._name is None:
            self._target.setIcon(QIcon())
            return
        ic = icon(self._name, self._token, self._size)
        self._target.setIcon(ic)
        if isinstance(self._target, QAbstractButton):
            self._target.setIconSize(QSize(self._size, self._size))

    def _on_theme_changed(self, _name: str) -> None:
        self.refresh()


def bind_icon(target: QAbstractButton | QAction, name: str, color_token: str = "dim",
              size: int = 16) -> _IconBinding:
    """
    Imposta l'icona su un pulsante o una QAction e la ri-rende al cambio tema.
    Ritorna il legame (figlio del target): ``binding.set_icon(nome)`` per cambiarla.
    """
    return _IconBinding(target, name, color_token, size)
