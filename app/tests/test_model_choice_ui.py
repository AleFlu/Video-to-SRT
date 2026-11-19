"""
test_model_choice_ui.py — Home e progetto: modello consigliato, modelli da scaricare e
conferma prima del download.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication, QMessageBox

import platform_support
from core import whisper_models as wm

GIB = 1024 ** 3


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(platform_support, "legacy_cache_dirs", lambda: [])
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=False)
    yield win
    for pw in win._projects:
        pw.teardown()
        pw._export_panel.close()
    win.deleteLater()


def _ram(monkeypatch, gib):
    import engine
    monkeypatch.setitem(engine._hardware_cache, "hw", (int(gib * GIB), False))


# ── Primo avvio: il modello consigliato per il computer ─────────────────────

def test_first_run_selects_the_recommended_model(app, monkeypatch, tmp_path):
    _ram(monkeypatch, 8)
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: tmp_path)
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=False)
    assert win._projects[0].home.model_combo.currentData() == "large-v3-turbo"
    win._projects[0].teardown()
    win.deleteLater()


def test_saved_choice_wins_over_the_recommendation(app, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    from core.transcription_config import TranscriptionConfig
    from ui.prefs import write_config
    write_config(QSettings("VideoSRT", "v2"), TranscriptionConfig(model_size="small"))
    _ram(monkeypatch, 64)
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: tmp_path)
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=False)
    assert win._projects[0].home.model_combo.currentData() == "small"
    win._projects[0].teardown()
    win.deleteLater()


# ── Home: consigliato, scaricato / da scaricare ─────────────────────────────

def test_home_marks_recommended_and_missing_models(app, monkeypatch):
    _ram(monkeypatch, 8)
    wm._fetch("large-v3-turbo")
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    combo = home.model_combo
    text = {combo.itemData(i): combo.itemText(i) for i in range(combo.count())}
    assert "consigliato" in text["large-v3-turbo"]
    assert "da scaricare" not in text["large-v3-turbo"]
    assert "da scaricare" in text["large-v3"] and "3,1 GB" in text["large-v3"]
    assert "consigliato" not in text["large-v3"]

    combo.setCurrentIndex(combo.findData("large-v3-turbo"))
    hint = home._model_hint.full_text()
    assert "consigliato per questo computer" in hint and "scaricato" in hint
    combo.setCurrentIndex(combo.findData("medium"))
    hint = home._model_hint.full_text()
    assert "da scaricare" in hint and "1,5 GB" in hint


def test_home_refreshes_after_a_download(app):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    i = home.model_combo.findData("small")
    assert "da scaricare" in home.model_combo.itemText(i)
    wm._fetch("small")
    home.refresh_models()
    assert "da scaricare" not in home.model_combo.itemText(i)


# ── Avvio con un modello da scaricare: prima si chiede ───────────────────────

def _start(window, monkeypatch, tmp_path, answer):
    pw = window._projects[0]
    started, asked = [], []
    monkeypatch.setattr(pw.progress, "start", lambda *a, **k: started.append(a))

    def question(parent, title, text, *a, **k):
        asked.append(text)
        return answer

    monkeypatch.setattr(QMessageBox, "question", question)
    media = tmp_path / "voce.wav"
    media.write_bytes(b"RIFF")
    pw._on_start_requested(str(media), pw.home._get_settings())
    return started, asked


def test_missing_model_asks_before_downloading(window, monkeypatch, tmp_path):
    window._projects[0].home.model_combo.setCurrentIndex(
        window._projects[0].home.model_combo.findData("large-v3"))
    started, asked = _start(window, monkeypatch, tmp_path, QMessageBox.No)
    assert len(asked) == 1 and "3,1 GB" in asked[0] and "large-v3" in asked[0]
    assert started == []
    started, asked = _start(window, monkeypatch, tmp_path, QMessageBox.Yes)
    assert len(started) == 1


def test_downloaded_model_starts_without_asking(window, monkeypatch, tmp_path):
    wm._fetch("large-v3")
    started, asked = _start(window, monkeypatch, tmp_path, QMessageBox.No)
    assert asked == [] and len(started) == 1


# ── Avviso nella Home quando il modello manca ────────────────────────────────

def test_missing_model_banner_explains_the_download(app):
    from ui.widgets import DepsBanner
    banner = DepsBanner()
    banner.set_status(ffmpeg_ok=True, model_ok=False)
    text = banner._title.text() + " " + banner._body.text()
    assert "prima trascrizione" in text
    assert "setup_mac.sh" not in text
