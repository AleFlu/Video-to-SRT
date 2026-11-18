"""
test_redesign_editor.py — Redesign "Bianco e nero", parte Editor / Esportazione / Trova.

Coprono: la toolbar espone le stesse azioni e queste producono gli stessi comandi sul
QUndoStack; le parole d'avviso della tabella per ogni codice problema; il contatore
breve dentro il campo Trova; le righe di esportazione con gli stessi gestori; il monitor
che si chiude per i soli audio e resta con i video.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton

from core.subtitle_model import Subtitle
from core import subtitle_table_model as stm


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _subs(n=3):
    return [Subtitle(i * 2.0, i * 2.0 + 1.5, f"Testo numero {i} di prova") for i in range(n)]


def _write_wav(path, seconds=2.0, rate=8000):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x20" * int(rate * seconds))
    return str(path)


# ── Toolbar ──────────────────────────────────────────────────────────────────

def test_toolbar_exposes_same_actions(app):
    from ui.subtitle_timeline import SubtitleTimeline
    tl = SubtitleTimeline()
    for name in ("act_undo", "act_redo", "act_toggle_insp", "act_export", "act_export_vtt",
                 "act_export_txt", "act_export_ass", "act_export_v2srt", "act_split",
                 "act_merge", "act_delete", "act_find", "act_find_replace", "btn_find_replace"):
        assert hasattr(tl, name), name
    names = {b.accessibleName() for b in tl.toolbar().findChildren(QPushButton)}
    assert {"Dividi", "Unisci", "Elimina", "Importa", "Trova e sostituisci",
            "Esporta SRT"} <= names
    # le scorciatoie sono solo disegnate: nome accessibile pulito
    assert all("⌘" not in n and "Ctrl" not in n for n in names)
    assert tl.act_toggle_insp.isCheckable() and tl.act_toggle_insp.isChecked()


def test_toolbar_buttons_push_undo_commands(app):
    from ui.subtitle_timeline import SubtitleTimeline
    tl = SubtitleTimeline()
    tl.load_subtitles(_subs(3))
    btn = {b.accessibleName(): b for b in tl.toolbar().findChildren(QPushButton)}

    tl.view.selectRow(0)
    btn["Dividi"].click()
    assert tl.model.rowCount() == 4 and tl.undo_stack.count() == 1
    assert tl.act_undo.isEnabled()

    btn["Unisci"].click()
    assert tl.model.rowCount() == 3 and tl.undo_stack.count() == 2

    btn["Elimina"].click()
    assert tl.model.rowCount() == 2 and tl.undo_stack.count() == 3

    tl.act_undo.trigger()
    assert tl.model.rowCount() == 3
    tl.act_redo.trigger()
    assert tl.model.rowCount() == 2


def test_toolbar_detach_keeps_wiring(app):
    from ui.workspace import WorkspaceWidget
    ws = WorkspaceWidget()
    tb = ws.timeline.toolbar()
    assert tb.parent() is not ws.timeline          # a tutta larghezza sopra tabella e ispettore
    ws.timeline.act_toggle_insp.trigger()
    assert ws.inspector.isHidden()
    ws.timeline.act_toggle_insp.trigger()
    assert not ws.inspector.isHidden()


# ── Parole d'avviso ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,word,token", [
    (stm.ISSUE_EMPTY, "vuoto", "err"),
    (stm.ISSUE_OVERLAP, "sovrapposto", "err"),
    (stm.ISSUE_TOO_FAST, "troppo veloce", "err"),
    (stm.ISSUE_TOO_SHORT, "troppo breve", "warn"),
    (stm.ISSUE_END_BEFORE_START, "tempi errati", "err"),
])
def test_issue_word_for_each_code(code, word, token):
    from ui.subtitle_timeline import issue_word
    assert issue_word([code]) == (word, token)


def test_issue_word_priority_and_fast_warning():
    from core.constants import MAX_CPS, WARN_CPS
    from ui.subtitle_timeline import issue_word
    assert issue_word([stm.ISSUE_TOO_SHORT, stm.ISSUE_EMPTY])[0] == "vuoto"
    assert issue_word([], cps=(WARN_CPS + MAX_CPS) / 2) == ("veloce", "warn")
    assert issue_word([], cps=5.0) is None
    assert issue_word([]) is None


def test_table_delegate_paints_all_rows(app):
    from ui.subtitle_timeline import SubtitleTimeline
    tl = SubtitleTimeline()
    tl.load_subtitles([Subtitle(0, 0.5, "x" * 40), Subtitle(1, 2, ""), Subtitle(2, 3, "ok")])
    tl.resize(800, 300)
    tl.view.selectRow(1)
    tl.show()
    pix = tl.view.viewport().grab()
    assert not pix.isNull()
    assert tl.view.verticalHeader().defaultSectionSize() >= 34


# ── Trova: contatore dentro il campo ─────────────────────────────────────────

def test_format_count_texts():
    from ui.find_replace_dialog import format_count
    assert format_count(3, 1) == "1 di 3"
    assert format_count(3) == "3 risultati"
    assert format_count(1) == "1 risultato"
    assert format_count(0) == "Nessun risultato"


def test_find_dialog_counter_in_field(app):
    from core.subtitle_table_model import SubtitleTableModel
    from ui.find_replace_dialog import FindReplaceDialog
    model = SubtitleTableModel(_subs(3))
    dlg = FindReplaceDialog(model)
    assert dlg.count_label.parent() is dlg.find_edit
    assert dlg.count_label.text() == ""
    dlg.find_edit.setText("prova")
    assert dlg.count_label.text() == "3 risultati"
    found = []
    dlg.match_found.connect(found.append)
    dlg.find_next_btn.click()
    assert found == [0] and dlg.count_label.text() == "1 di 3"
    dlg.find_next_btn.click()
    assert dlg.count_label.text() == "2 di 3"
    dlg.find_edit.setText("assente")
    assert dlg.count_label.text() == "Nessun risultato"
    # regex non valida e sostituzione non valida restano visibili
    dlg.regex_check.setChecked(True)
    assert not dlg.word_check.isEnabled()
    dlg.find_edit.setText("(")
    assert dlg.count_label.text() == "Pattern non valido"
    dlg.find_edit.setText("(prova)")
    dlg.replace_edit.setText(r"\3")
    dlg.replace_all_btn.click()
    assert "non valido" in dlg.count_label.text()
    dlg.find_edit.setText("")
    assert dlg.count_label.text() == ""


# ── Esportazione ─────────────────────────────────────────────────────────────

def test_export_rows_trigger_same_handlers(app, monkeypatch):
    from ui.export_tab import ExportTab, _ExportButton
    et = ExportTab()
    et.refresh([], _subs(3), "/tmp/video.mp4", True)
    fired = []
    for sig, name in ((et.export_srt_requested, "srt"), (et.export_vtt_requested, "vtt"),
                      (et.export_txt_requested, "txt"), (et.export_ass_requested, "ass"),
                      (et.save_v2srt_requested, "v2srt")):
        sig.connect(lambda n=name: fired.append(n))
    for b in (et._panel.btn_srt, et._panel.btn_vtt, et._panel.btn_txt, et._panel.btn_ass,
              et._panel.btn_v2srt):
        assert isinstance(b, _ExportButton)
        assert b.minimumHeight() == b.maximumHeight() == 56
        b.click()
    assert fired == ["srt", "vtt", "txt", "ass", "v2srt"]

    et._panel._btn_clipboard.click()
    assert "Testo numero 0 di prova" in QApplication.clipboard().text()
    assert et._panel._btn_clipboard.accessibleName() == "Copia negli appunti"
    assert et._panel.btn_srt.tag_lbl.text() == "SRT"


def test_export_info_band_flags(app):
    from ui.export_tab import ExportTab
    et = ExportTab()
    et.refresh([], [Subtitle(0, 1, "a"), Subtitle(1, 2, "")], "/tmp/v.mp4", True)
    p = et._panel
    assert not p._badge_modified.isHidden()
    assert not p._lbl_empty_warn.isHidden() and not p._warn_icon.isHidden()
    assert p._lbl_origin.text() == "Versione dell'editor"
    et.refresh([], [Subtitle(0, 1, "a")], "/tmp/v.mp4", False)
    assert p._badge_modified.isHidden() and p._lbl_empty_warn.isHidden()


# ── Monitor / forma d'onda ───────────────────────────────────────────────────

def test_monitor_mode_decision():
    from ui.preview_area import monitor_mode, MODE_AUDIO, MODE_EMPTY, MODE_VIDEO
    assert monitor_mode("", True) == MODE_EMPTY
    assert monitor_mode("/tmp/film.mp4", True) == MODE_VIDEO
    assert monitor_mode("/tmp/film.MKV", True) == MODE_VIDEO
    assert monitor_mode("/tmp/film.mp4", False) == MODE_AUDIO   # senza uscita video
    assert monitor_mode("/tmp/voce.wav", True) == MODE_AUDIO


def test_monitor_collapses_for_audio_and_shows_for_video(app, tmp_path):
    from ui.preview_area import PreviewArea, MODE_AUDIO, MODE_EMPTY, MODE_VIDEO
    pa = PreviewArea()
    assert pa.mode == MODE_EMPTY and not pa._monitor.isHidden()
    assert pa._monitor_msg.text() == "Nessun file caricato"

    pa.load_media(_write_wav(tmp_path / "voce.wav"))
    assert pa.mode == MODE_AUDIO and pa._monitor.isHidden()

    pa.clear_media()
    assert pa.mode == MODE_EMPTY and not pa._monitor.isHidden()

    pa._set_mode(MODE_VIDEO)                  # decisione video: monitor + onda affiancati
    assert not pa._monitor.isHidden() and not pa.waveform.isHidden()
    # 452 px all'inizio, poi allargabile trascinando il bordo (test_video_monitor)
    assert pa._top_split.sizes()[0] > 0 and pa._monitor.minimumWidth() == 240
    pa.player.unload()


# ── Forma d'onda ─────────────────────────────────────────────────────────────

def test_waveform_layers_are_cached(app):
    import numpy as np
    from ui.waveform_widget import WaveformWidget
    wf = WaveformWidget()
    wf.resize(800, 260)
    wf.set_duration(10_000)
    mins = -np.abs(np.sin(np.linspace(0, 20, 500))).astype("float32")
    wf._on_loader_done(wf._load_generation, (mins, -mins, 160, 8000, 80000))
    wf.set_subtitles(_subs(3), ["ok", "warning", "error"])
    wf.set_selected_row(1)
    wf.set_position(4000)
    wf.grab()
    first, played = wf._cache, wf._played_cache
    assert first is not None and played is not None
    wf.set_position(5000)           # il tick del player non ridisegna gli strati statici
    wf.grab()
    assert wf._cache is first and wf._played_cache is played
    # il blocco sta nella corsia da 52 px
    y, h = wf._block_geometry(260)
    assert 260 - 52 <= y and y + h <= 260
    assert wf._row_at(10, y + 5) == 0
    pix = QPixmap(800, 260)
    p = QPainter(pix)
    wf.render_static(p, 800, 260)
    p.end()


def test_transport_has_no_vol_text_and_line_sliders(app):
    from ui.transport_bar import TransportBar, RATE_STEPS
    bar = TransportBar()
    assert bar.height() == 46
    assert bar._lbl_vol.text() == "" and bar._lbl_vol.accessibleName() == "Volume"
    assert bar.volume_slider.width() == 84
    assert bar.btn_play.width() == 36 and bar.btn_play.height() == 28
    assert [bar.rate_combo.itemData(i) for i in range(bar.rate_combo.count())] == list(RATE_STEPS)
    assert bar.label_dur.text().startswith("/ ")
    bar.btn_loop.setEnabled(True)
    got = []
    bar.loop_toggled.connect(got.append)
    bar.btn_loop.setChecked(True)
    assert got == [True]
