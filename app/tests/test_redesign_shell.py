"""test_redesign_shell.py — Intestazione unica, Home, fasi di Progress, log e Result (redesign)."""

import os
import re
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


# ── Intestazione ─────────────────────────────────────────────────────────────

def test_header_has_single_theme_button(app):
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    win._new_project()
    btns = [b for b in win.findChildren(QPushButton) if b.objectName() == "themeToggle"]
    assert btns == [win.theme_btn]
    assert win._header.height() == win.proj_tab_bar.height()


def test_header_shows_active_project_sections(app):
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    win._new_project()
    p1, p2 = win._projects
    assert win._nav_stack.currentWidget() is p2.tab_bar
    win.proj_tab_bar.select_tab(0)
    assert win._nav_stack.currentWidget() is p1.tab_bar
    assert p1.tab_bar.parent() is win._nav_stack


def test_each_project_keeps_its_section(app):
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    win._new_project()
    p1, p2 = win._projects
    p1.tab_bar.set_unlocked(True)
    p1.tab_bar.set_current(2)
    win.proj_tab_bar.select_tab(1)
    assert p2.tab_bar.current() == 0 and p1.tab_bar.current() == 2
    win.proj_tab_bar.select_tab(0)
    assert win._nav_stack.currentWidget().current() == 2


def test_closing_project_removes_its_sections(app):
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    win._new_project()
    assert win._nav_stack.count() == 2
    win._on_tab_close_requested(1)
    assert win._nav_stack.count() == 1


# ── Home ─────────────────────────────────────────────────────────────────────

def test_home_start_emits_same_settings_keys(app, tmp_path):
    from ui.home_widget import HomeWidget
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x" * 10)
    home = HomeWidget()
    got = []
    home.start_requested.connect(lambda p, s: got.append((p, s)))
    home._on_file_selected(str(f))
    assert home.start_btn.isEnabled()
    home._on_start()
    assert got[0][0] == str(f)
    assert set(got[0][1]) == {"model_size", "language", "vad_filter", "denoise",
                              "high_accuracy", "beam_size"}


def test_home_model_hint_shows_ram_quality_recommended(app):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    text = home._model_hint.full_text()
    # hardware dei test (conftest): 16 GB senza GPU → large-v3 consigliato
    assert "RAM" in text and "qualità 5/5" in text and "consigliato" in text


# ── Progress ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg,idx", [
    ("Pre-elaborazione audio (riduzione rumore)...", 0),
    ("Audio ripulito", 0),
    ("Modello già pronto", 1),
    ("Caricamento modello 'large-v3'...", 1),
    ("Elaborazione audio in corso...", 2),
    ("Lingua: it (100%) · VAD attivo", 2),
    ("Trascrizione in corso... 24%", 2),
    ("Segmentazione sottotitoli...", 3),
    ("Ottimizzazione timing sottotitoli...", 4),
    ("Messaggio inventato domani", None),
])
def test_phase_mapping(msg, idx):
    from ui.progress_widget import phase_for_status
    assert phase_for_status(msg) == idx


def test_phase_states_follow_status_and_ignore_unknown(app):
    from ui.progress_widget import ProgressWidget
    pw = ProgressWidget()
    pw._on_status("Modello già pronto")
    assert pw.phase_states() == ["done", "active", "pending", "pending", "pending"]
    pw._on_status("Qualcosa di nuovo")
    assert pw.status_lbl.text() == "Qualcosa di nuovo"
    assert pw.phase_states() == ["done", "active", "pending", "pending", "pending"]
    pw._on_status("Lingua: it (100%)")
    assert pw.phase_states()[2] == "active"
    assert pw.phase_details()[2].startswith("Lingua")


def test_log_lines_have_time_prefix_and_copy(app):
    from ui.progress_widget import ProgressWidget
    pw = ProgressWidget()
    pw._on_status("Audio ripulito")
    pw._on_status("Modello già pronto")
    lines = pw.log.toPlainText().splitlines()
    assert len(lines) == 2
    assert all(re.match(r"^\d\d:\d\d:\d\d  ", ln) for ln in lines)
    pw._copy_log()
    assert QApplication.clipboard().text() == pw.log.toPlainText()


# ── Result ───────────────────────────────────────────────────────────────────

def test_result_preview_has_end_column(app):
    from ui.result_widget import ResultWidget
    rw = ResultWidget()
    rw.show_result([{"start": 0.0, "end": 1.5, "text": "ciao"}], "/tmp/v.mp4")
    m = rw._preview_model
    assert m.columnCount() == 4
    assert m.data(m.index(0, 2)) == "00:01.500"
    assert "1 sottotitoli" in rw.summary_lbl.text()
