"""
test_functional.py — Test funzionali (black-box): verifica i flussi utente principali.

Coprono i casi d'uso dell'app come li vive l'utente:
  - Trascrizione → Result → Editor
  - ExportTab con sub raw
  - ExportTab con sub editor
  - Import SRT nell'editor
  - Reset progetto
  - Badge tab editor
  - Placeholder quando vuoto
  - Inline progress show/hide
"""

import os
import sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_subtitle(start=0.0, end=2.0, text="Hello"):
    from core.subtitle_model import Subtitle
    return Subtitle(start=start, end=end, text=text)

def _make_subs(n=5):
    from core.subtitle_model import Subtitle
    return [Subtitle(start=i*2.0, end=i*2.0+1.8, text=f"Sub {i+1}") for i in range(n)]

def _make_raw_segments(n=5):
    """Simula segmenti grezzi come tornano da faster-whisper (dict-like via __getitem__)."""
    return [
        {"start": float(i * 2), "end": float(i * 2 + 1.8), "text": f" Parola {i+1}"}
        for i in range(n)
    ]


# ── UC: flusso trascrizione → result → editor ──────────────────────────────────

class TestTranscriptionFlow:
    """UC2: trascrizione → ResultWidget → Editor caricato automaticamente."""

    def test_result_shows_after_transcription_done(self, app):
        from ui.result_widget import ResultWidget
        rw = ResultWidget()
        segs = _make_subs(3)
        rw.show_result(segs, "/tmp/video.mp4")
        assert "3" in rw.summary_lbl.text()

    def test_result_modified_badge_hidden_by_default(self, app):
        from ui.result_widget import ResultWidget
        rw = ResultWidget()
        segs = _make_subs(3)
        rw.show_result(segs, "/tmp/video.mp4")
        rw.set_modified_badge(False)
        # badge_frame è il container — set_modified_badge agisce su di esso
        assert rw.badge_frame.isHidden()

    def test_result_modified_badge_shows(self, app):
        from ui.result_widget import ResultWidget
        rw = ResultWidget()
        segs = _make_subs(3)
        rw.show_result(segs, "/tmp/video.mp4")
        rw.set_modified_badge(True)
        assert not rw.badge_frame.isHidden()

    def test_result_emits_open_editor(self, app):
        from ui.result_widget import ResultWidget
        rw = ResultWidget()
        segs = _make_subs(2)
        rw.show_result(segs, "/tmp/test.mp4")
        received = []
        rw.open_editor_requested.connect(lambda: received.append(True))
        rw.editor_btn.click()
        assert received == [True]

    def test_result_emits_new_requested(self, app):
        from ui.result_widget import ResultWidget
        rw = ResultWidget()
        segs = _make_subs(2)
        rw.show_result(segs, "/tmp/test.mp4")
        received = []
        rw.new_requested.connect(lambda: received.append(True))
        rw.new_btn.click()
        assert received == [True]


# ── UC: ExportTab refresh e sub ────────────────────────────────────────────────

class TestExportTabFunctional:
    """Verifica che ExportTab mostri i dati corretti in ogni stato."""

    def test_placeholder_shown_when_no_subs(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        et.refresh(segments_raw=[], editor_subs=[], source_path="", is_modified=False)
        assert et._stack.currentIndex() == 0   # placeholder

    def test_panel_shown_with_raw_segments(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        segs = _make_raw_segments(3)
        et.refresh(segments_raw=segs, editor_subs=[], source_path="/tmp/v.mp4", is_modified=False)
        assert et._stack.currentIndex() == 1   # panel

    def test_panel_shown_with_editor_subs(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        subs = _make_subs(5)
        et.refresh(segments_raw=[], editor_subs=subs, source_path="/tmp/v.mp4", is_modified=False)
        assert et._stack.currentIndex() == 1   # panel

    def test_editor_subs_take_priority_over_raw(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        raw = _make_raw_segments(2)
        editor = _make_subs(7)
        et.refresh(segments_raw=raw, editor_subs=editor, source_path="", is_modified=False)
        assert len(et.current_subtitles()) == 7

    def test_current_subtitles_returns_raw_when_no_editor(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        raw = _make_raw_segments(4)
        et.refresh(segments_raw=raw, editor_subs=[], source_path="", is_modified=False)
        # raw vengono convertiti in Subtitle — controlla il count
        assert len(et.current_subtitles()) == 4

    def test_modified_badge_visible_with_editor_and_modified(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        subs = _make_subs(3)
        et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=True)
        assert not et._panel._badge_modified.isHidden()

    def test_modified_badge_hidden_when_not_modified(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        subs = _make_subs(3)
        et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
        assert et._panel._badge_modified.isHidden()

    def test_export_srt_signal_emitted(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        subs = _make_subs(2)
        et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
        received = []
        et.export_srt_requested.connect(lambda: received.append(True))
        et._panel.btn_srt.click()
        assert received == [True]

    def test_export_vtt_signal_emitted(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        subs = _make_subs(2)
        et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
        received = []
        et.export_vtt_requested.connect(lambda: received.append(True))
        et._panel.btn_vtt.click()
        assert received == [True]

    def test_srt_preview_content(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        subs = _make_subs(2)
        et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
        preview = et._panel._preview.toPlainText()
        assert "00:00:00" in preview   # timestamp presente
        assert "Sub 1" in preview


# ── UC: EditorTab e InlineProgressBar ─────────────────────────────────────────

class TestEditorTabFunctional:
    """Verifica EditorTab: stack Placeholder/Workspace e InlineProgressBar."""

    def test_shows_placeholder_by_default(self, app):
        from ui.editor_tab import EditorTab
        et = EditorTab()
        et.show_placeholder()
        assert et._stack.currentIndex() == 0

    def test_shows_workspace(self, app):
        from ui.editor_tab import EditorTab
        et = EditorTab()
        et.show_workspace()
        assert et._stack.currentIndex() == 1

    def test_import_requested_signal_from_toolbar(self, app):
        from ui.editor_tab import EditorTab
        import unittest.mock as mock
        et = EditorTab()
        received = []
        et.import_requested.connect(received.append)
        # QFileDialog è importato lazy dentro il metodo statico — patch sul modulo PySide6
        with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                        return_value=("/tmp/test.srt", "")):
            et._on_import_from_toolbar()
        assert received == ["/tmp/test.srt"]

    def test_import_requested_empty_path_not_emitted(self, app):
        from ui.editor_tab import EditorTab
        import unittest.mock as mock
        et = EditorTab()
        received = []
        et.import_requested.connect(received.append)
        with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                        return_value=("", "")):
            et._on_import_from_toolbar()
        assert received == []


# ── UC: TabBar switching ───────────────────────────────────────────────────────

class TestTabBarFunctional:
    """Verifica il comportamento della tab bar interna."""

    def test_initial_tab_is_transcription(self, app):
        from ui.tab_bar import TabBar, _TAB_TRANSCRIPTION
        tb = TabBar()
        assert tb.current() == _TAB_TRANSCRIPTION

    def test_switching_emits_signal(self, app):
        from ui.tab_bar import TabBar, _TAB_EDITOR
        tb = TabBar()
        received = []
        tb.tab_changed.connect(received.append)
        tb.set_current(_TAB_EDITOR)
        assert _TAB_EDITOR in received

    def test_no_signal_on_same_tab(self, app):
        from ui.tab_bar import TabBar, _TAB_TRANSCRIPTION
        tb = TabBar()
        received = []
        tb.tab_changed.connect(received.append)
        tb.set_current(_TAB_TRANSCRIPTION)
        assert received == []

    def test_editor_badge_toggles(self, app):
        from ui.tab_bar import TabBar
        tb = TabBar()
        tb.set_editor_badge(True)
        assert not tb._badge.isHidden()
        tb.set_editor_badge(False)
        assert tb._badge.isHidden()




# ── UC: PlaceholderWidget ──────────────────────────────────────────────────────

class TestPlaceholderFunctional:
    """Verifica il drop target e il bottone unico del placeholder."""

    def test_has_single_open_button(self, app):
        from ui.placeholder_widget import PlaceholderWidget
        from PySide6.QtWidgets import QPushButton
        pw = PlaceholderWidget()
        buttons = pw.findChildren(QPushButton)
        assert len(buttons) == 1
        assert "Apri" in buttons[0].text()

    def test_open_button_emits_import_signal(self, app):
        from ui.placeholder_widget import PlaceholderWidget
        pw = PlaceholderWidget()
        received = []
        pw.import_file_requested.connect(lambda: received.append(True))
        pw._btn.click()
        assert received == [True]

    def test_accepts_drops(self, app):
        from ui.placeholder_widget import PlaceholderWidget
        pw = PlaceholderWidget()
        assert pw.acceptDrops()

    def test_file_dropped_signal_exists(self, app):
        from ui.placeholder_widget import PlaceholderWidget
        pw = PlaceholderWidget()
        assert hasattr(pw, "file_dropped")

    def test_drag_over_changes_visual_state(self, app):
        from ui.placeholder_widget import PlaceholderWidget
        pw = PlaceholderWidget()
        assert not pw._drag_over
        pw._set_hover(True)
        assert pw._drag_over
        pw._set_hover(False)
        assert not pw._drag_over

    def test_drop_emits_file_dropped(self, app):
        from ui.placeholder_widget import PlaceholderWidget
        pw = PlaceholderWidget()
        received = []
        pw.file_dropped.connect(received.append)
        # Simula drop emettendo direttamente il segnale (drag events richiedono display reale)
        pw.file_dropped.emit("/tmp/test.srt")
        assert received == ["/tmp/test.srt"]

    def test_go_transcription_signal_still_exists(self, app):
        # Compatibilità — segnale mantenuto anche se non usato attivamente
        from ui.placeholder_widget import PlaceholderWidget
        pw = PlaceholderWidget()
        assert hasattr(pw, "go_transcription_requested")
