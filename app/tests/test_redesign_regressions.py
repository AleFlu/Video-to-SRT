"""test_redesign_regressions.py — audit finale del redesign: nulla di funzionale perso, rifiniture."""

import os
import re
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel

UI = Path(__file__).resolve().parent.parent / "ui"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _window():
    from ui.main_window import MainWindow
    return MainWindow(ffmpeg_ok=True, model_ok=True)


# ── Ispettore: menu, pulsante e azione restano sincronizzati ─────────────────

def test_inspector_toggle_menu_and_button_in_sync(app):
    from core.subtitle_model import Subtitle
    win = _window()
    win.show()
    pw = win._active()
    pw.timeline.load_subtitles([Subtitle(start=0.0, end=1.0, text="a")])
    pw.tab_bar.set_unlocked(True)
    pw.tab_bar.set_current(1)
    tl = pw.timeline
    assert win.act_toggle_insp.shortcut().toString() == "Ctrl+I"
    assert tl.inspector.isVisibleTo(pw.workspace) and tl.act_toggle_insp.isChecked()
    win.act_toggle_insp.trigger()
    assert not tl.inspector.isVisibleTo(pw.workspace)
    assert not tl.act_toggle_insp.isChecked() and not tl._insp_btn.isChecked()
    tl._insp_btn.click()
    assert tl.inspector.isVisibleTo(pw.workspace) and tl.act_toggle_insp.isChecked()
    win.close()


# ── Intestazione: nessuna barra orfana alla chiusura ─────────────────────────

def test_closing_projects_leaves_no_dangling_section_bar(app):
    from PySide6.QtCore import QEvent
    from ui.tab_bar import TabBar
    win = _window()
    win._new_project()
    win._on_tab_close_requested(0)
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert len(win.findChildren(TabBar)) == 1
    win._on_tab_close_requested(0)   # ultima tab: si ricrea un progetto vuoto
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert len(win.findChildren(TabBar)) == 1
    assert win._nav_stack.currentWidget() is win._projects[0].tab_bar


def test_inactive_project_keeps_updating_its_sections(app):
    win = _window()
    win._new_project()
    p1, p2 = win._projects
    p1.tab_bar.set_unlocked(True)
    p1.tab_bar.set_editor_badge(True)
    assert p1.tab_bar.is_unlocked() and p1.tab_bar._badge.isVisibleTo(p1.tab_bar)
    assert not p2.tab_bar.is_unlocked()


# ── Geometria: chiavi vecchie o valori incompleti non rompono il ripristino ──

def test_workspace_restore_ignores_bad_saved_sizes(app):
    from ui.workspace import WorkspaceWidget, _SETTINGS_HSPLIT, _SETTINGS_VSPLIT
    s = QSettings("VideoSRT", "v2")
    old_h, old_v = s.value(_SETTINGS_HSPLIT), s.value(_SETTINGS_VSPLIT)
    try:
        s.setValue(_SETTINGS_HSPLIT, [0, 0])
        s.setValue(_SETTINGS_VSPLIT, [500])
        ws = WorkspaceWidget()
        assert all(x >= 0 for x in ws._hsplit.sizes())
        assert ws._hsplit.count() == 2 and len(ws._vsplit.sizes()) == 2
    finally:
        for key, old in ((_SETTINGS_HSPLIT, old_h), (_SETTINGS_VSPLIT, old_v)):
            s.remove(key) if old is None else s.setValue(key, old)


# ── Forma d'onda: errore del decoder = messaggio nel widget, mai un dialog ───

def test_waveform_failure_degrades_without_dialog(app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    import ui.waveform_widget as ww

    def boom(*_a, **_k):
        raise FileNotFoundError("ffmpeg")

    shown = []
    monkeypatch.setattr(ww, "compute_peaks", boom)
    monkeypatch.setattr(QMessageBox, "exec", lambda *_a, **_k: shown.append(1))
    w = ww.WaveformWidget()
    w.load_audio("/inesistente.mp4")
    for _ in range(100):
        app.processEvents()
        if not w._loading:
            break
        time.sleep(0.02)
    assert not w._loading and w._mins is None
    assert "non disponibile" in w._status_msg and not shown


# ── Nessun uso residuo di cose rimosse; token esistenti; niente glifi-icona ──

def test_removed_preview_timecode_has_no_users(app):
    for f in list(UI.glob("*.py")):
        assert "timecode_lbl" not in f.read_text(encoding="utf-8"), f.name


def test_every_theme_token_used_in_ui_exists(app):
    from ui import theme
    keys = set(theme.tokens("dark"))
    used = set()
    for f in UI.glob("*.py"):
        if f.name == "theme.py":
            continue
        used |= set(re.findall(r"""\b(?:c|qcolor)\(\s*['"](\w+)['"]""", f.read_text(encoding="utf-8")))
    assert used - keys == set()


def test_no_text_glyph_icons_in_ui_strings(app):
    glyphs = "●▶■←→★✓⚠◧↑↩"
    bad = []
    for f in UI.glob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#")[0]
            if re.search(r"""(QLabel|QPushButton|QToolButton|QAction|setText|emit)\(\s*f?["'][^"']*[%s]"""
                         % glyphs, code):
                bad.append(f"{f.name}:{n}")
    assert bad == []


# ── Rifiniture ───────────────────────────────────────────────────────────────

def test_progress_buttons_have_clean_sizes(app):
    from ui.progress_widget import ProgressWidget
    w = ProgressWidget()
    assert w.stop_btn.height() == 36 or w.stop_btn.minimumHeight() == 36
    assert w.copy_log_btn.minimumHeight() == 28 and w.copy_log_btn.maximumHeight() == 28


def test_status_label_colours_counts_but_keeps_plain_text(app):
    from ui import theme
    from ui.main_window import _StatusLabel
    lbl = _StatusLabel("12 sottotitoli  ·  1 errore  ·  2 avvisi  ·  Modificato")
    assert lbl.text() == "12 sottotitoli  ·  1 errore  ·  2 avvisi  ·  Modificato"
    html = QLabel.text(lbl)
    assert theme.c("err") in html and theme.c("warn") in html
    assert theme.c("err") not in QLabel.text(_StatusLabel("12 sottotitoli  ·  nessun problema"))
    win = _window()
    assert win._status_bar.height() == 26 or win._status_bar.maximumHeight() == 26


def test_export_rows_are_square(app):
    from ui.export_tab import _ExportButton
    row = _ExportButton("SRT", "d", tag="SRT")
    assert "border-radius: 0" in row.styleSheet()


def test_inspector_text_box_and_spin_heights(app):
    from ui.inspector_widget import InspectorWidget
    i = InspectorWidget()
    assert i.text_edit.minimumHeight() == i.text_edit.maximumHeight() <= 110
    assert i.start_spin.height() == 28 or i.start_spin.maximumHeight() == 28
    assert "monospace" in i.styleSheet().lower() or "mono" in i.styleSheet().lower()


def test_export_badge_uses_drawn_dot(app):
    from ui.export_tab import ExportTab
    et = ExportTab()
    texts = [lbl.text() for lbl in et._panel._badge_modified.findChildren(QLabel)]
    assert "modificato nell'editor" in texts and not any("●" in t for t in texts)


def test_result_keeps_transcription_statistics(app):
    """Le statistiche della schermata 'completata' (prima nelle 4 card) restano visibili."""
    from ui.result_widget import ResultWidget
    w = ResultWidget()
    segs = [{"start": 0.0, "end": 2.0, "text": "a" * 20},
            {"start": 2.0, "end": 4.0, "text": "b" * 40}]
    w.show_result(segs, "/tmp/x.mov")
    txt = w.stats_lbl.text()
    assert "durata media 2.0 s" in txt
    assert "CPS medio 15.0" in txt
    assert "copertura 100%" in txt
    w.show_result([], "/tmp/x.mov")
    assert w.stats_lbl.text() == ""
