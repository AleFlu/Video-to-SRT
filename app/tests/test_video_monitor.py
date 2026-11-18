"""Monitor video: riquadro allargabile e schermo intero con i sottotitoli."""
from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.subtitle_model import Subtitle  # noqa: E402


@pytest.fixture
def preview():
    QApplication.instance() or QApplication(sys.argv)
    from ui.preview_area import MODE_VIDEO, PreviewArea
    p = PreviewArea()
    p.resize(1200, 320)
    p.show()
    if p._video_player_view is None:
        pytest.skip("QtMultimediaWidgets non disponibile")
    p._set_mode(MODE_VIDEO)
    yield p
    p.exit_fullscreen()
    p.hide()
    p.deleteLater()


def test_monitor_width_is_resizable_and_remembered(preview):
    from ui.preview_area import MONITOR_MIN_WIDTH, _SETTINGS_MONITOR_W
    split = preview._top_split
    split.setSizes([700, 500])
    QApplication.processEvents()
    assert preview._monitor.width() >= 650          # prima: fisso a 452 px
    split.splitterMoved.emit(700, 1)
    assert int(QSettings("VideoSRT", "v2").value(_SETTINGS_MONITOR_W)) == preview._monitor.width()
    assert preview._monitor.minimumWidth() == MONITOR_MIN_WIDTH


def test_fullscreen_button_only_with_video(preview):
    from ui.preview_area import MODE_AUDIO, MODE_VIDEO
    assert preview.transport.btn_fullscreen.isEnabled()
    preview._set_mode(MODE_AUDIO)
    assert not preview.transport.btn_fullscreen.isEnabled()
    preview.enter_fullscreen()
    assert not preview.is_fullscreen()              # niente schermo intero per l'audio
    preview._set_mode(MODE_VIDEO)


def test_fullscreen_shows_subtitles_and_esc_returns(preview):
    preview._set_overlay_subs([Subtitle(0.0, 5.0, "Ciao a tutti")])
    preview.transport.btn_fullscreen.click()
    assert preview.is_fullscreen()
    fs = preview._fullscreen
    assert fs.isFullScreen()
    assert preview._subtitle_overlay is fs.view
    assert fs.view._subtitle_text == "Ciao a tutti"
    QTest.keyClick(fs, Qt.Key_Escape)
    QApplication.processEvents()
    assert not preview.is_fullscreen()
    assert preview._subtitle_overlay is preview._video_player_view
    assert preview._video_player_view._subtitle_text == "Ciao a tutti"


def test_double_click_on_video_enters_fullscreen(preview):
    view = preview._video_player_view
    QTest.mouseDClick(view.viewport(), Qt.LeftButton)
    assert preview.is_fullscreen()
    QTest.mouseDClick(preview._fullscreen.view.viewport(), Qt.LeftButton)
    QApplication.processEvents()
    assert not preview.is_fullscreen()
