"""Marchio "Bianco e nero": icona dell'app, file in assets/ e splash di avvio (ui/brand)."""

from __future__ import annotations

import importlib.util
import re
import struct
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage, QImageReader

from ui import brand, theme

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _image(pix) -> QImage:
    return pix.toImage().convertToFormat(QImage.Format_ARGB32)


def _max_saturation(img: QImage, step: int = 1) -> int:
    """Massima distanza tra i canali RGB dei pixel visibili (0 = solo grigi)."""
    worst = 0
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            c = img.pixelColor(x, y)
            if c.alpha() == 0:
                continue
            rgb = (c.red(), c.green(), c.blue())
            worst = max(worst, max(rgb) - min(rgb))
    return worst


def _rgb(color: QColor) -> tuple[int, int, int]:
    return color.red(), color.green(), color.blue()


def _make_icon():
    """Lo script assets/make_icon.py come modulo (non sta nel sys.path dei test)."""
    spec = importlib.util.spec_from_file_location("make_icon", ASSETS / "make_icon.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Icona ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("size", [16, 24, 32, 64, 128, 512])
@pytest.mark.parametrize("margin", [brand.MARGIN_MAC, brand.MARGIN_FLAT])
def test_icon_is_black_and_white_with_subtitle_lines(app, size, margin):
    img = _image(brand.draw_app_icon(size, margin))
    assert (img.width(), img.height()) == (size, size)
    assert _max_saturation(img) <= 2           # niente blu/viola della vecchia icona
    colors = {_rgb(img.pixelColor(x, y)) for y in range(size) for x in range(size)
              if img.pixelColor(x, y).alpha() == 255}
    assert _rgb(theme.qcolor("bg", "dark")) in colors        # quadrato nero
    assert _rgb(theme.qcolor("text", "dark")) in colors      # righe di sottotitolo
    assert _rgb(theme.qcolor("label", "dark")) in colors     # forma d'onda


def test_icon_mac_margin_leaves_transparent_border(app):
    img = _image(brand.draw_app_icon(1024, brand.MARGIN_MAC))
    assert img.pixelColor(0, 0).alpha() == 0
    assert img.pixelColor(512, 50).alpha() == 0              # dentro i 100 px di margine
    assert img.pixelColor(512, 150).alpha() == 255           # corpo dell'icona


@pytest.mark.parametrize("size", [16, 32])
def test_small_icon_marks_sit_on_whole_pixels(app, size):
    """A 16 e 32 px onda e righe non sono sfumate (prima si impastavano in un grigio)."""
    img = _image(brand.draw_app_icon(size))
    x0 = max(1, int(size * brand.MARGIN_MAC))
    allowed = {_rgb(theme.qcolor(t, "dark")) for t in ("bg", "text", "label")}
    inner = range(x0 + 3, size - x0 - 3)
    seen = {_rgb(img.pixelColor(x, y)) for y in inner for x in inner}
    assert seen <= allowed, seen - allowed
    assert _rgb(theme.qcolor("text", "dark")) in seen


def test_brand_uses_theme_tokens_only():
    """Disegno solo da token del tema: niente colori fissi nel modulo del marchio."""
    source = Path(brand.__file__).read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{6}\b", source)


# ── File in assets/ ─────────────────────────────────────────────────────────

def test_asset_png_is_the_black_and_white_icon(app):
    img = QImage(str(ASSETS / "app_512.png")).convertToFormat(QImage.Format_ARGB32)
    assert (img.width(), img.height()) == (512, 512)
    assert _max_saturation(img, step=2) <= 2
    assert img.pixelColor(0, 0).alpha() == 0                 # margini macOS


def test_asset_ico_has_every_windows_size(app):
    make_icon = _make_icon()
    data = (ASSETS / "app.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1)
    sides = []
    for i in range(count):
        dim, _h, _c, _r, _planes, _bpp, size, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * i)
        assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert offset + size <= len(data)
        sides.append(dim or 256)
    assert sides == make_icon.ICO_SIZES
    reader = QImageReader(str(ASSETS / "app.ico"))
    assert reader.imageCount() == count
    assert _max_saturation(reader.read().convertToFormat(QImage.Format_ARGB32)) <= 2


def test_asset_icns_is_a_mac_icon():
    assert (ASSETS / "app.icns").read_bytes()[:4] == b"icns"


def test_ico_bytes_layout():
    make_icon = _make_icon()
    data = make_icon.ico_bytes([(16, b"a" * 5), (256, b"b" * 7)])
    assert struct.unpack_from("<HHH", data, 0) == (0, 1, 2)
    first = struct.unpack_from("<BBBBHHII", data, 6)
    second = struct.unpack_from("<BBBBHHII", data, 22)
    assert first[0] == 16 and first[6:] == (5, 38)
    assert second[0] == 0 and second[6:] == (7, 43)          # 0 = 256 px
    assert data[38:43] == b"a" * 5 and data[43:] == b"b" * 7


# ── Splash ──────────────────────────────────────────────────────────────────

def _playhead_x(img: QImage, dpr: float, theme_name: str) -> float:
    """Centro della testina sotto la forma d'onda, in punti (pixel pieni: niente sfumature)."""
    y = int((brand.BANNER_H - 6) * dpr)
    head = _rgb(theme.qcolor("playhead", theme_name))
    xs = [x for x in range(img.width()) if _rgb(img.pixelColor(x, y)) == head]
    assert xs, "testina non trovata"
    assert len(xs) == round(2 * dpr), xs                     # linea netta di 2 punti
    return (sum(xs) / len(xs) + 0.5) / dpr


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_splash_follows_theme_and_is_monochrome(app, theme_name):
    pix = brand.splash_pixmap(0.4, "Caricamento motore IA…", "2.0.0", dpr=2.0,
                              theme_name=theme_name)
    assert pix.devicePixelRatio() == 2.0
    img = _image(pix)
    assert (img.width(), img.height()) == (brand.SPLASH_W * 2, brand.SPLASH_H * 2)
    assert _rgb(img.pixelColor(img.width() // 2, img.height() - 12)) == _rgb(
        theme.qcolor("bg", theme_name))
    assert _rgb(img.pixelColor(img.width() // 2, 10)) == _rgb(
        theme.qcolor("panel", theme_name))
    assert _max_saturation(img, step=2) <= 2
    assert img.pixelColor(0, 0).alpha() == 0                 # angoli arrotondati


@pytest.mark.parametrize("progress", [0.0, 0.2, 0.8, 1.0])
def test_splash_playhead_follows_progress(app, progress):
    img = _image(brand.splash_pixmap(progress, "", dpr=1.0, theme_name="dark"))
    left, right = 32, brand.SPLASH_W - 32
    assert _playhead_x(img, 1.0, "dark") == pytest.approx(
        left + progress * (right - left), abs=1.5)


def test_splash_timecode_format():
    assert brand._timecode(0) == "00:00:00,000"
    assert brand._timecode(27.6) == "00:00:27,600"
    assert brand._timecode(3725.042) == "01:02:05,042"


def test_startup_splash_advances_with_steps(app):
    import main

    splash = main.Splash()
    try:
        first = splash.pixmap().toImage()
        splash.set_step(3, "Caricamento motore IA…")
        assert splash._pct == pytest.approx(4 / len(main.STEPS))
        after = splash.pixmap().toImage()
        assert after != first
        dpr = splash.pixmap().devicePixelRatio()
        expected = 32 + splash._pct * (brand.SPLASH_W - 64)
        assert _playhead_x(after.convertToFormat(QImage.Format_ARGB32), dpr,
                           theme.get_theme()) == pytest.approx(expected, abs=1.5)
    finally:
        splash.close()
