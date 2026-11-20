"""
test_burn_in_ui.py — Esportazione "Video con sottotitoli" dalla tab Esportazione.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

import platform_support
from core.subtitle_model import Subtitle

SUBS = [Subtitle(0.5, 1.5, "Ciao a tutti"), Subtitle(2.0, 3.0, "")]


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


# ── Tab Esportazione ─────────────────────────────────────────────────────────

def test_video_row_is_offered_for_a_video_source(app):
    from ui.export_tab import ExportTab
    tab = ExportTab()
    tab.refresh([], SUBS, "/video/reel.mp4", False)
    btn = tab._panel.btn_video
    assert btn.isEnabled() and "MP4" in btn.tag_lbl.text()
    fired = []
    tab.export_video_requested.connect(lambda: fired.append(1))
    btn.click()
    assert fired == [1]


def test_video_row_disabled_for_audio_only(app):
    from ui.export_tab import ExportTab
    tab = ExportTab()
    tab.refresh([], SUBS, "/audio/podcast.mp3", False)
    btn = tab._panel.btn_video
    assert not btn.isEnabled()
    assert "video" in btn.toolTip().lower()
    tab.refresh([], SUBS, "/video/clip.MOV", False)
    assert btn.isEnabled()


# ── Progetto: scelta del file, avanzamento, esito ────────────────────────────

class _FakeWorker(QObject):
    progress = Signal(float)
    done = Signal(str)
    failed = Signal(str)
    cancelled = Signal()
    created = []
    outcome = ("done", None)

    def __init__(self, source, cues, output, parent=None):
        super().__init__(parent)
        self.source, self.cues, self.output = source, cues, output
        self.cancel_requested = False
        _FakeWorker.created.append(self)

    def request_cancel(self):
        self.cancel_requested = True

    def isRunning(self):  # noqa: N802 (API Qt)
        return False

    def wait(self, *_a):
        return True

    def start(self):
        self.progress.emit(0.5)
        kind, arg = _FakeWorker.outcome
        if kind == "done":
            self.done.emit(self.output)
        elif kind == "failed":
            self.failed.emit(arg)
        else:
            self.cancelled.emit()


@pytest.fixture
def project(app, tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(platform_support, "legacy_cache_dirs", lambda: [])
    from ui import project_widget
    from ui.main_window import MainWindow
    from core import burn_in
    monkeypatch.setattr(project_widget, "BurnInWorker", _FakeWorker, raising=False)
    monkeypatch.setattr(burn_in, "ffmpeg_path", lambda: "ffmpeg")
    _FakeWorker.created = []
    _FakeWorker.outcome = ("done", None)
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    pw = win._projects[0]
    src = tmp_path / "reel.mp4"
    src.write_bytes(b"x")
    pw._source_path = str(src)
    pw.export_tab.refresh([], SUBS, str(src), False)
    yield pw, tmp_path
    pw.teardown()
    win.deleteLater()


def test_export_video_runs_with_the_subtitles_of_the_export_tab(project, monkeypatch):
    pw, tmp = project
    suggested = []

    def save_name(parent, title, initial, filt, *a, **k):
        suggested.append(initial)
        return str(tmp / "uscita"), filt

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_name)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    pw._on_tab_export_video()
    assert suggested[0].endswith("reel sottotitolato.mp4")
    w = _FakeWorker.created[0]
    assert w.output == str(tmp / "uscita.mp4")          # estensione aggiunta
    assert w.cues == [(0.5, 1.5, "Ciao a tutti")]        # i vuoti non servono
    assert any("uscita.mp4" in str(s) for s in shown)


def test_export_video_failure_is_shown(project, monkeypatch):
    pw, tmp = project
    _FakeWorker.outcome = ("failed", "ffmpeg non è riuscito")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp / "o.mp4"), ""))
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: errors.append(a[2]))
    pw._on_tab_export_video()
    assert errors and "ffmpeg non è riuscito" in errors[0]


def test_export_video_cancelled_dialog_does_nothing(project, monkeypatch):
    pw, _tmp = project
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    pw._on_tab_export_video()
    assert _FakeWorker.created == []


def test_export_video_never_overwrites_the_source(project, monkeypatch):
    pw, _tmp = project
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (pw._source_path, ""))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    pw._on_tab_export_video()
    assert _FakeWorker.created == [] and warned and "originale" in warned[0]


def test_export_video_without_ffmpeg_explains(project, monkeypatch):
    pw, tmp = project
    from core import burn_in
    monkeypatch.setattr(burn_in, "ffmpeg_path", lambda: None)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp / "o.mp4"), ""))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    pw._on_tab_export_video()
    assert _FakeWorker.created == [] and "ffmpeg" in warned[0]
