"""
test_waveform_scroll.py — Forma d'onda: scorrimento con rotella/trackpad, zoom e follow.

Bug: la rotella verticale del mouse e lo scorrimento a due dita in verticale del trackpad
facevano zoom invece di scorrere. Ora: rotella/due dita (verticale e orizzontale) →
scorrimento della finestra visibile; Ctrl/⌘ o Alt + rotella e il pizzico → zoom attorno
al cursore; doppio clic sullo sfondo → tutta la durata. Il playhead non si muove mai
scorrendo, e l'auto-scroll non "combatte" lo scorrimento manuale.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QNativeGestureEvent, QPointingDevice, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import platform_support
from core.subtitle_model import Subtitle

W = 1000


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def wf(app):
    from ui.waveform_widget import WaveformWidget
    w = WaveformWidget()
    w.resize(W, 220)
    w.set_duration(60_000)
    w.set_subtitles([Subtitle(start=12.0, end=14.0, text="blocco")])
    w._clock = _Clock()
    w._view_start_ms, w._view_end_ms = 10_000.0, 20_000.0      # zoom: 10–20 s
    w.set_position(15_000)
    w.show()
    yield w
    w.hide()
    w.deleteLater()


def _wheel(w, angle=(0, 0), pixel=(0, 0), mods=Qt.NoModifier, x=500):
    pos = QPointF(x, 60)
    ev = QWheelEvent(pos, w.mapToGlobal(pos), QPoint(*pixel), QPoint(*angle),
                     Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(w, ev)
    return ev


def _view(w):
    return round(w._view_start_ms), round(w._view_end_ms)


# ── Scorrimento ──────────────────────────────────────────────────────────────

def test_vertical_mouse_wheel_scrolls_instead_of_zooming(wf):
    _wheel(wf, angle=(0, -120))                 # rotella verso di sé: avanti nel tempo
    assert _view(wf) == (11_000, 21_000)        # stessa ampiezza, spostata di 1/10
    _wheel(wf, angle=(0, 120))
    assert _view(wf) == (10_000, 20_000)
    assert wf._playhead_ms == 15_000            # il playhead non si muove


def test_trackpad_two_finger_vertical_uses_pixel_delta(wf):
    _wheel(wf, angle=(0, -30), pixel=(0, -50))  # pixelDelta ha la precedenza
    assert _view(wf) == (10_500, 20_500)        # 50 px su 1000 px di 10 s = 500 ms
    assert wf._playhead_ms == 15_000


def test_horizontal_wheel_and_swipe_scroll(wf):
    _wheel(wf, angle=(-120, 0))
    assert _view(wf) == (11_000, 21_000)
    _wheel(wf, angle=(0, 0), pixel=(100, 0))
    assert _view(wf) == (10_000, 20_000)


def test_scroll_is_clamped_to_duration(wf):
    for _ in range(100):
        _wheel(wf, angle=(0, 120))
    assert _view(wf) == (0, 10_000)
    for _ in range(100):
        _wheel(wf, angle=(0, -120))
    assert _view(wf) == (50_000, 60_000)


def test_no_scroll_when_whole_duration_visible(wf):
    wf.reset_zoom()
    ev = _wheel(wf, angle=(0, -120))
    assert _view(wf) == (0, 60_000)
    assert not ev.isAccepted()


# ── Zoom ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mods", [Qt.ControlModifier, Qt.MetaModifier, Qt.AltModifier])
def test_modifier_wheel_zooms_around_cursor(wf, mods):
    x = 250                                     # 12,5 s sotto il cursore
    _wheel(wf, angle=(0, 120), mods=mods, x=x)
    start, end = wf._view_start_ms, wf._view_end_ms
    assert end - start == pytest.approx(9_000)
    assert wf._x_to_ms(x) == pytest.approx(12_500)
    _wheel(wf, angle=(0, -240), mods=mods, x=x)
    assert wf._view_end_ms - wf._view_start_ms > 10_000
    assert wf._playhead_ms == 15_000


def test_alt_wheel_delivered_as_horizontal_still_zooms(wf):
    _wheel(wf, angle=(120, 0), mods=Qt.AltModifier)
    assert wf._view_end_ms - wf._view_start_ms == pytest.approx(9_000)


def test_pinch_gesture_zooms_around_cursor(wf):
    dev = QPointingDevice.primaryPointingDevice()
    pos = QPointF(750, 60)                      # 17,5 s
    ev = QNativeGestureEvent(Qt.ZoomNativeGesture, dev, 2, pos, pos, wf.mapToGlobal(pos),
                             0.25, QPointF(0, 0))
    QApplication.sendEvent(wf, ev)
    assert ev.isAccepted()
    assert wf._view_end_ms - wf._view_start_ms == pytest.approx(8_000)
    assert wf._x_to_ms(750) == pytest.approx(17_500)
    smart = QNativeGestureEvent(Qt.SmartZoomNativeGesture, dev, 2, pos, pos,
                                wf.mapToGlobal(pos), 0.0, QPointF(0, 0))
    QApplication.sendEvent(wf, smart)
    assert _view(wf) == (0, 60_000)


def test_zoom_by_pinch_helper(wf):
    wf.zoom_by_pinch(500, -0.5)                 # dita che si chiudono: allontana
    assert wf._view_end_ms - wf._view_start_ms == pytest.approx(20_000)


def test_double_click_background_resets_zoom(wf):
    QTest.mouseDClick(wf, Qt.LeftButton, Qt.NoModifier, QPoint(500, 60))
    assert _view(wf) == (0, 60_000)


def test_double_click_on_block_does_not_reset_zoom(wf):
    block_y, block_h = wf._block_geometry(wf.height())
    QTest.mouseDClick(wf, Qt.LeftButton, Qt.NoModifier, QPoint(250, block_y + block_h // 2))
    assert _view(wf) == (10_000, 20_000)


# ── Auto-scroll del playhead e scorrimento manuale ───────────────────────────

def test_manual_scroll_suspends_follow_for_hold_time(wf):
    from ui.waveform_widget import FOLLOW_HOLD_S
    _wheel(wf, angle=(0, -240))                 # 12–22 s
    wf.set_position(30_000)                     # riproduzione: playhead fuori vista
    assert _view(wf) == (12_000, 22_000)        # la vista resta dove l'ha messa l'utente
    wf._clock.t += FOLLOW_HOLD_S + 0.1
    wf.set_position(30_040)
    assert wf._view_start_ms <= 30_040 <= wf._view_end_ms   # poi il follow riprende


def test_explicit_seek_resumes_follow(wf):
    _wheel(wf, angle=(0, -240))
    wf.on_seeked(40_000)                        # es. Maiusc+→ verso un punto fuori vista
    wf.set_position(40_000)
    assert wf._view_start_ms <= 40_000 <= wf._view_end_ms


def test_click_near_edge_does_not_jump_the_view(wf):
    wf.on_seeked(19_500)                        # click a 19,5 s: dentro la vista
    wf.set_position(19_500)
    assert _view(wf) == (10_000, 20_000)


# ── Tastiera e accessibilità ─────────────────────────────────────────────────

def test_waveform_keyboard(wf):
    seeks = []
    wf.seek_requested.connect(seeks.append)
    assert wf.focusPolicy() & Qt.TabFocus
    QTest.keyClick(wf, Qt.Key_Right)
    QTest.keyClick(wf, Qt.Key_Left)
    QTest.keyClick(wf, Qt.Key_Home)
    QTest.keyClick(wf, Qt.Key_End)
    assert seeks == [16_000, 14_000, 0, 60_000]
    QTest.keyClick(wf, Qt.Key_Plus)
    assert wf._view_end_ms - wf._view_start_ms == pytest.approx(8_000)
    QTest.keyClick(wf, Qt.Key_0)
    assert _view(wf) == (0, 60_000)


def test_waveform_help_text(wf):
    mod = platform_support.shortcut_label("Ctrl")
    expected = (f"Scorri con la rotella o con due dita · {mod} + rotella o pizzico per lo zoom"
                " · clic per spostarti")
    assert expected in wf.toolTip()
    assert expected in wf.accessibleDescription()
    assert wf.accessibleName() == "Forma d'onda"

