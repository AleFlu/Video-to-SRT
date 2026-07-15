"""test_export_tab.py — Test per ui/export_tab.py."""

import os
import sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


from core.subtitle_model import Subtitle
from ui.export_tab import ExportTab


@pytest.fixture
def subs():
    return [
        Subtitle(start=0.0, end=2.0, text="Prima"),
        Subtitle(start=3.0, end=5.0, text="Seconda"),
    ]

@pytest.fixture
def raw_segments():
    return [
        {"start": 0.0, "end": 2.0, "text": "Prima"},
        {"start": 3.0, "end": 5.0, "text": "Seconda"},
    ]


# ── Stato iniziale ────────────────────────────────────────────────────────────

def test_initial_shows_placeholder(app):
    et = ExportTab()
    assert et._stack.currentIndex() == 0   # placeholder

def test_current_subtitles_empty_initially(app):
    et = ExportTab()
    assert et.current_subtitles() == []


# ── refresh: nessun sub ───────────────────────────────────────────────────────

def test_refresh_no_subs_shows_placeholder(app):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=[], source_path="", is_modified=False)
    assert et._stack.currentIndex() == 0

def test_refresh_no_subs_current_empty(app):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=[], source_path="", is_modified=False)
    assert et.current_subtitles() == []


# ── refresh: solo raw ─────────────────────────────────────────────────────────

def test_refresh_raw_only_shows_panel(app, raw_segments):
    et = ExportTab()
    et.refresh(segments_raw=raw_segments, editor_subs=[], source_path="/v.mp4", is_modified=False)
    assert et._stack.currentIndex() == 1   # pannello export

def test_refresh_raw_only_count(app, raw_segments):
    et = ExportTab()
    et.refresh(segments_raw=raw_segments, editor_subs=[], source_path="/v.mp4", is_modified=False)
    assert len(et.current_subtitles()) == 2

def test_refresh_raw_badge_not_shown(app, raw_segments):
    et = ExportTab()
    et.refresh(segments_raw=raw_segments, editor_subs=[], source_path="/v.mp4", is_modified=False)
    assert not et._panel._badge_modified.isVisible()


# ── refresh: editor subs priorità su raw ──────────────────────────────────────

def test_refresh_editor_subs_take_priority(app, raw_segments, subs):
    et = ExportTab()
    # raw ha 2 sub identici, editor ne ha 3
    editor_extra = subs + [Subtitle(start=6.0, end=8.0, text="Terza")]
    et.refresh(segments_raw=raw_segments, editor_subs=editor_extra, source_path="", is_modified=False)
    assert len(et.current_subtitles()) == 3

def test_refresh_modified_badge_visible(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=True)
    assert not et._panel._badge_modified.isHidden()   # flag locale

def test_refresh_modified_badge_hidden_if_not_modified(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
    assert et._panel._badge_modified.isHidden()


# ── Segnali export ────────────────────────────────────────────────────────────

def test_signal_srt_emitted(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
    received = []
    et.export_srt_requested.connect(lambda: received.append("srt"))
    et._panel.btn_srt.click()
    assert "srt" in received

def test_signal_vtt_emitted(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
    received = []
    et.export_vtt_requested.connect(lambda: received.append("vtt"))
    et._panel.btn_vtt.click()
    assert "vtt" in received

def test_signal_txt_emitted(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
    received = []
    et.export_txt_requested.connect(lambda: received.append("txt"))
    et._panel.btn_txt.click()
    assert "txt" in received

def test_signal_ass_emitted(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
    received = []
    et.export_ass_requested.connect(lambda: received.append("ass"))
    et._panel.btn_ass.click()
    assert "ass" in received

def test_signal_v2srt_emitted(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
    received = []
    et.save_v2srt_requested.connect(lambda: received.append("v2srt"))
    et._panel.btn_v2srt.click()
    assert "v2srt" in received


# ── refresh multiplo ──────────────────────────────────────────────────────────

def test_refresh_clears_previous_state(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
    assert et._stack.currentIndex() == 1
    # Reset a vuoto
    et.refresh(segments_raw=[], editor_subs=[], source_path="", is_modified=False)
    assert et._stack.currentIndex() == 0
    assert et.current_subtitles() == []


# ── Anteprima SRT ─────────────────────────────────────────────────────────────

def test_preview_populated_with_subs(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
    text = et._panel._preview.toPlainText()
    assert "Prima" in text
    assert "Seconda" in text

def test_preview_empty_when_no_subs(app):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=[], source_path="", is_modified=False)
    # placeholder visibile, panel non usato
    assert et._stack.currentIndex() == 0

def test_preview_truncates_at_five(app):
    many_subs = [Subtitle(start=float(i), end=float(i)+1, text=f"Sub {i}") for i in range(10)]
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=many_subs, source_path="", is_modified=False)
    text = et._panel._preview.toPlainText()
    assert "altri 5 sottotitoli" in text

def test_preview_contains_srt_timestamps(app, subs):
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
    text = et._panel._preview.toPlainText()
    assert "-->" in text   # formato SRT timestamp
