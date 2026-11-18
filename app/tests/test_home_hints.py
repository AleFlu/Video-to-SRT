"""Home senza frasi di istruzione superflue: sotto Avvia compaiono solo gli errori."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication

import platform_support


@pytest.fixture
def ui_env(monkeypatch, tmp_path):
    """Cache in tmp (le QSettings sono già isolate da conftest)."""
    QApplication.instance() or QApplication(sys.argv)
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(platform_support, "legacy_cache_dirs", lambda: [])


def test_no_instruction_text_under_start(ui_env, tmp_path):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    assert home._hint_lbl.isHidden() and home._hint_lbl.text() == ""
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 10)
    home._on_file_selected(str(clip))
    # file scelto: nessun "Premi Invio per avviare"
    assert home._hint_lbl.isHidden() and home._hint_lbl.text() == ""


def test_errors_still_shown(ui_env):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    home._on_file_error("xyz")
    assert not home._hint_lbl.isHidden() and ".xyz" in home._hint_lbl.text()


def test_redundant_descriptions_hidden(ui_env):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    assert home._src_note.isHidden()
    assert home._vad_desc.isHidden()
    assert home.drop._idle_t2.isHidden()
    # il perché del Filtro VAD resta nel tooltip
    assert "senza parlato" in home.vad_toggle.toolTip()
