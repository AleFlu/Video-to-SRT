"""
test_ui_regressions.py — Test di regressione per i bug UI critici (Task 5).

Coprono: inspector unico collegato all'undo stack, trova/sostituisci raggiungibile,
conferma prima di sovrascrivere l'editor, autosave non distruttivo, risincronizzazione
preview dopo il caricamento, scorciatoie non ambigue, chiusura con worker attivo.

Tutti i dialog modali sono sostituiti con monkeypatch: nessun test blocca.
"""

from __future__ import annotations

import logging
import os
import struct
import sys
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractButton, QApplication, QMessageBox

import platform_support
from core.subtitle_model import Subtitle, SubtitleProject
from core.v2srt_io import save_project


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


# ── Isolamento: niente QSettings reali, cache in tmp ──────────────────────────

class _FakeSettings:
    """QSettings in memoria: evita di sporcare le preferenze reali dell'utente."""

    store: dict = {}

    def __init__(self, *_a, **_k):
        pass

    def value(self, key, default=None, type=None):  # noqa: A002
        return self.store.get(key, default)

    def setValue(self, key, value):
        self.store[key] = value

    def remove(self, key):
        self.store.pop(key, None)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: cache)
    monkeypatch.setattr(platform_support, "legacy_cache_dirs", lambda: [])
    _FakeSettings.store = {}
    import ui.main_window as mw
    import ui.project_widget as pwm
    monkeypatch.setattr(mw, "QSettings", _FakeSettings)
    monkeypatch.setattr(pwm, "QSettings", _FakeSettings)
    # Nessun dialog modale deve restare aperto durante i test
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    return cache


def _subs(n=3):
    return [Subtitle(start=i * 2.0, end=i * 2.0 + 1.5, text=f"Riga {i + 1}") for i in range(n)]


def _write_v2srt(path, n=3, source_path=""):
    save_project(SubtitleProject(source_path=source_path, subtitles=_subs(n)), str(path))
    return str(path)


def _write_srt(path, text="Importato"):
    path.write_text(f"1\n00:00:01,000 --> 00:00:02,000\n{text}\n", encoding="utf-8")
    return str(path)


def _write_wav(path, seconds=0.2, rate=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return str(path)


def _make_modified(pw):
    """Carica sottotitoli nell'editor e applica una modifica tramite undo stack."""
    tl = pw.workspace.timeline
    tl.load_subtitles(_subs(3))
    tl._on_insp_text(0, "Modificato")
    assert pw.workspace.is_modified()


@pytest.fixture
def project(app):
    from ui.project_widget import ProjectWidget
    pw = ProjectWidget(1, ffmpeg_ok=True, model_ok=True)
    yield pw
    pw.teardown()
    pw._export_panel.close()
    pw.deleteLater()


@pytest.fixture
def window(app):
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    yield win
    for pw in win._projects:
        pw.teardown()
        pw._export_panel.close()
    win.deleteLater()


# ── Inspector unico ───────────────────────────────────────────────────────────

class TestInspector:
    def test_single_inspector_instance(self, app):
        from ui.inspector_widget import InspectorWidget
        from ui.workspace import WorkspaceWidget
        ws = WorkspaceWidget()
        assert ws.inspector is ws.timeline.inspector
        assert len(ws.findChildren(InspectorWidget)) == 1

    def test_visible_inspector_edits_go_through_undo(self, app):
        from ui.workspace import WorkspaceWidget
        ws = WorkspaceWidget()
        tl = ws.timeline
        tl.load_subtitles(_subs(3))
        tl.view.selectRow(1)
        insp = ws.inspector

        insp.start_spin.setValue(2.5)
        insp.start_spin.editingFinished.emit()
        insp.end_spin.setValue(3.9)
        insp.end_spin.editingFinished.emit()
        insp.text_edit.setPlainText("Testo nuovo")
        insp._commit_text()

        sub = tl.model.subtitle_at(1)
        assert sub.start == pytest.approx(2.5)
        assert sub.end == pytest.approx(3.9)
        assert sub.text == "Testo nuovo"
        assert tl.undo_stack.count() == 3

        for _ in range(3):
            tl.undo_stack.undo()
        sub = tl.model.subtitle_at(1)
        assert sub.start == pytest.approx(2.0)
        assert sub.end == pytest.approx(3.5)
        assert sub.text == "Riga 2"


# ── Trova e sostituisci ───────────────────────────────────────────────────────

class TestFindReplace:
    def test_action_opens_dialog(self, window):
        from ui.find_replace_dialog import FindReplaceDialog
        pw = window._active()
        pw.workspace.timeline.load_subtitles(_subs(2))
        window.act_find_replace.trigger()
        dlg = pw.timeline._find_dialog
        assert isinstance(dlg, FindReplaceDialog)
        assert dlg.isVisible()
        dlg.close()

    def test_action_in_edit_menu_with_shortcuts(self, window):
        assert window.act_find_replace in window._menu_edit.actions()
        assert window.act_find in window._menu_edit.actions()
        keys = {s.toString() for s in window.act_find_replace.shortcuts()}
        assert "Ctrl+Alt+F" in keys
        assert window.act_find.shortcut() == QKeySequence(QKeySequence.Find)

    def test_toolbar_button_opens_dialog(self, app):
        from ui.workspace import WorkspaceWidget
        ws = WorkspaceWidget()
        ws.timeline.load_subtitles(_subs(2))
        ws.timeline.btn_find_replace.click()
        assert ws.timeline._find_dialog is not None
        assert ws.timeline._find_dialog.isVisible()
        ws.timeline._find_dialog.close()

    def test_plain_replacement_is_literal(self, app):
        from core.subtitle_table_model import SubtitleTableModel
        from ui.find_replace_dialog import FindReplaceDialog
        model = SubtitleTableModel()
        model.set_subtitles([Subtitle(0.0, 1.0, "vai a casa")])
        dlg = FindReplaceDialog(model)
        try:
            got = []
            dlg.replace_all_requested.connect(got.append)
            dlg.find_edit.setText("casa")
            dlg.replace_edit.setText(r"C:\new\d")
            dlg._replace_all()
            assert got == [[(0, "vai a casa", r"vai a C:\new\d")]]
        finally:
            dlg.close()
            dlg.deleteLater()

    def test_regex_toggle_disables_whole_word(self, app):
        from core.subtitle_table_model import SubtitleTableModel
        from ui.find_replace_dialog import FindReplaceDialog
        dlg = FindReplaceDialog(SubtitleTableModel())
        try:
            assert hasattr(dlg, "_on_regex_toggled")
            dlg.regex_check.setChecked(True)
            assert not dlg.word_check.isEnabled()
            dlg.regex_check.setChecked(False)
            assert dlg.word_check.isEnabled()
        finally:
            dlg.close()
            dlg.deleteLater()


# ── Conferma prima di sovrascrivere ───────────────────────────────────────────

def _answer(monkeypatch, button):
    """Sostituisce QMessageBox.exec; ritorna la lista delle chiamate registrate."""
    calls = []

    def fake_exec(self):
        calls.append(self.text())
        return button

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return calls


class TestConfirmDiscard:
    def test_unmodified_does_not_ask(self, project, monkeypatch):
        calls = _answer(monkeypatch, QMessageBox.Cancel)
        project.workspace.timeline.load_subtitles(_subs(2))
        assert project.confirm_discard_changes() is True
        assert calls == []

    def test_cancel_keeps_editor(self, project, monkeypatch, tmp_path):
        _make_modified(project)
        calls = _answer(monkeypatch, QMessageBox.Cancel)
        project.open_path(_write_v2srt(tmp_path / "altro.v2srt", n=7))
        assert len(calls) == 1
        assert project.workspace.timeline.model.rowCount() == 3
        assert project.workspace.timeline.model.subtitle_at(0).text == "Modificato"

    def test_discard_loads_v2srt(self, project, monkeypatch, tmp_path):
        _make_modified(project)
        calls = _answer(monkeypatch, QMessageBox.Discard)
        project.open_path(_write_v2srt(tmp_path / "altro.v2srt", n=7))
        assert len(calls) == 1
        assert project.workspace.timeline.model.rowCount() == 7

    def test_cancel_keeps_editor_on_srt(self, project, monkeypatch, tmp_path):
        _make_modified(project)
        calls = _answer(monkeypatch, QMessageBox.Cancel)
        project.open_path(_write_srt(tmp_path / "a.srt"))
        assert len(calls) == 1
        assert project.workspace.timeline.model.rowCount() == 3

    def test_save_then_load(self, project, monkeypatch, tmp_path):
        _make_modified(project)
        _answer(monkeypatch, QMessageBox.Save)
        saved = []

        def fake_save():
            saved.append(True)
            project.workspace.mark_saved()

        monkeypatch.setattr(project, "save_v2srt", fake_save)
        project.open_path(_write_srt(tmp_path / "a.srt"))
        assert saved == [True]
        assert project.workspace.timeline.model.rowCount() == 1

    def test_save_cancelled_aborts(self, project, monkeypatch, tmp_path):
        _make_modified(project)
        _answer(monkeypatch, QMessageBox.Save)
        monkeypatch.setattr(project, "save_v2srt", lambda: None)   # dialog annullato
        project.open_path(_write_srt(tmp_path / "a.srt"))
        assert project.workspace.timeline.model.rowCount() == 3

    def test_toolbar_import_asks(self, project, monkeypatch, tmp_path):
        import ui.subtitle_timeline as stl
        _make_modified(project)
        calls = _answer(monkeypatch, QMessageBox.Cancel)
        srt = _write_srt(tmp_path / "a.srt")
        monkeypatch.setattr(stl.QFileDialog, "getOpenFileName", lambda *a, **k: (srt, ""))
        project.workspace.timeline._import_file()
        assert len(calls) == 1
        assert project.workspace.timeline.model.rowCount() == 3

    def test_result_open_editor_asks(self, project, monkeypatch):
        _make_modified(project)
        project._on_transcription_done(
            [{"start": 0.0, "end": 1.0, "text": "nuovo"}], "/tmp/video.mp4"
        )
        calls = _answer(monkeypatch, QMessageBox.Cancel)
        project._on_open_editor()
        assert len(calls) == 1
        assert project.workspace.timeline.model.rowCount() == 3

        _answer(monkeypatch, QMessageBox.Discard)
        project._on_open_editor()
        assert project.workspace.timeline.model.rowCount() == 1


# ── Autosave ──────────────────────────────────────────────────────────────────

class TestAutosave:
    def test_failed_restore_keeps_file(self, window, monkeypatch, _isolate):
        bad = _isolate / "autosave_9.v2srt"
        bad.write_text("{non è json", encoding="utf-8")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        window._check_autosave_restore()
        assert bad.exists()

    def test_successful_restore_deletes_and_marks_modified(self, window, monkeypatch,
                                                           _isolate):
        good = _write_v2srt(_isolate / "autosave_9.v2srt", n=4)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        window._check_autosave_restore()
        assert not os.path.exists(good)
        pw = window._active()
        assert pw.workspace.timeline.model.rowCount() == 4
        assert pw.workspace.is_modified()

    def test_autosave_write_error_is_logged(self, project, monkeypatch, caplog):
        import ui.project_widget as pwm
        _make_modified(project)

        def boom(*_a, **_k):
            raise OSError("disco pieno")

        monkeypatch.setattr(pwm, "save_project", boom)
        with caplog.at_level(logging.WARNING, logger="ui.project_widget"):
            project._autosave()
        assert any("autosave" in r.getMessage().lower() for r in caplog.records)


# ── Risincronizzazione dopo il caricamento ────────────────────────────────────

@pytest.fixture
def _no_media_io(monkeypatch):
    """Evita thread di decodifica audio reali: basta che load_media resetti la waveform."""
    from core.audio_player import AudioPlayer
    from ui.waveform_widget import WaveformWidget
    monkeypatch.setattr(WaveformWidget, "load_audio", lambda self, path: None)
    monkeypatch.setattr(AudioPlayer, "load", lambda self, path: None)


@pytest.mark.usefixtures("_no_media_io")
class TestResync:
    def test_load_v2srt_resyncs_preview_and_exports(self, project, monkeypatch, tmp_path):
        media = _write_wav(tmp_path / "audio.wav")
        path = _write_v2srt(tmp_path / "p.v2srt", n=4, source_path=media)
        project.load_v2srt(path)

        wf = project.workspace.preview.waveform
        assert len(wf._subtitles) == 4
        assert len(project.workspace.preview._overlay_subs) == 4
        assert all(isinstance(s, dict) for s in project._segments_raw)

        # Editor svuotato → l'export ricade sui segmenti grezzi senza eccezioni
        tl = project.workspace.timeline
        tl.view.selectAll()
        tl._delete_selected()
        assert tl.model.rowCount() == 0
        project._refresh_export_tab()
        assert len(project.export_tab.current_subtitles()) == 4
        project.do_export()
        assert len(project.project.subtitles) == 4

    def test_restore_resyncs_preview(self, project, tmp_path):
        media = _write_wav(tmp_path / "audio.wav")
        path = _write_v2srt(tmp_path / "autosave_1.v2srt", n=2, source_path=media)
        assert project.restore_from_autosave(path) is True
        assert len(project.workspace.preview.waveform._subtitles) == 2
        assert all(isinstance(s, dict) for s in project._segments_raw)


# ── Scorciatoie non ambigue ───────────────────────────────────────────────────

class TestShortcuts:
    def test_no_duplicate_shortcuts(self, window):
        window._new_project()   # due progetti aperti
        owners: dict = {}
        for act in window.findChildren(QAction):
            for seq in act.shortcuts():
                if not seq.isEmpty():
                    owners.setdefault(seq.toString(), []).append(act.text())
        for btn in window.findChildren(QAbstractButton):
            seq = btn.shortcut()
            if not seq.isEmpty():
                owners.setdefault(seq.toString(), []).append(btn.text())
        dups = {k: v for k, v in owners.items() if len(v) > 1}
        assert dups == {}

        # Le QShortcut contestuali (playback) non devono collidere con le azioni,
        # e quelle a livello applicazione devono essere uniche.
        app_keys = []
        for sc in window.findChildren(QShortcut):
            key = sc.key().toString()
            assert key not in owners, f"{key} registrata sia come azione che come QShortcut"
            if sc.context() == sc.context().ApplicationShortcut:
                app_keys.append(key)
        assert len(app_keys) == len(set(app_keys))

    def test_menu_actions_delegate_to_active(self, window):
        pw = window._active()
        tl = pw.workspace.timeline
        tl.load_subtitles(_subs(2))
        tl._on_insp_text(0, "x")
        assert tl.model.subtitle_at(0).text == "x"
        window.act_undo.trigger()
        assert tl.model.subtitle_at(0).text == "Riga 1"
        window.act_redo.trigger()
        assert tl.model.subtitle_at(0).text == "x"


# ── Badge export ──────────────────────────────────────────────────────────────

def test_export_badge_attribute(app):
    from ui.export_tab import ExportTab
    et = ExportTab()
    et.refresh(segments_raw=[], editor_subs=_subs(1), source_path="", is_modified=True)
    assert not et._panel._badge_modified.isHidden()


# ── Chiusura con worker attivo ────────────────────────────────────────────────

class _FakeWorker(QObject):
    status = Signal(str)
    progress = Signal(float)
    text = Signal(float, str)
    audio = Signal(float, float)
    finished = Signal(list)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.cancel_requested = False

    def request_cancel(self):
        self.cancel_requested = True


def _attach_running_worker(pw):
    t = QThread(pw.progress)
    w = _FakeWorker()
    t.start()
    pw.progress._thread = t
    pw.progress._worker = w
    return t, w


class TestClose:
    def test_close_cancels_and_waits_worker(self, window, monkeypatch):
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        pw = window._active()
        t, w = _attach_running_worker(pw)
        window.close()
        assert w.cancel_requested
        assert t.isFinished()

    def test_declined_close_does_not_cancel_worker(self, window, monkeypatch):
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        pw = window._active()
        _make_modified(pw)
        _answer(monkeypatch, QMessageBox.Cancel)   # "Annulla" sulle modifiche non salvate
        t, w = _attach_running_worker(pw)
        try:
            assert window.close() is False
            assert not w.cancel_requested
        finally:
            t.quit()
            t.wait(2000)
            pw.progress._thread = None
            pw.progress._worker = None


# ── Thread sganciati ancora attivi alla chiusura ──────────────────────────────

class TestDetachedThreads:
    def test_running_detached_thread_is_unparented_and_kept(self, app, monkeypatch):
        from ui import progress_widget as pwm

        class FakeThread:
            parent_set = "unset"

            def wait(self, ms):
                return False

            def isRunning(self):
                return True

            def setParent(self, p):
                self.parent_set = p

        t = FakeThread()
        monkeypatch.setattr(pwm, "_DETACHED", [(t, object())])
        pwm.wait_detached_threads(1)
        assert t.parent_set is None
        assert len(pwm._DETACHED) == 1          # riferimento forte mantenuto
        assert pwm.has_running_detached_threads() is True

    def test_no_detached_running(self, app, monkeypatch):
        from ui import progress_widget as pwm
        monkeypatch.setattr(pwm, "_DETACHED", [])
        assert pwm.has_running_detached_threads() is False


# ── Import SRT: stesso percorso del .v2srt ────────────────────────────────────

class TestLoadSrtState:
    def test_srt_import_updates_project_state(self, project, tmp_path):
        from core.srt_io import write_srt
        srt = tmp_path / "ciao.srt"
        write_srt([Subtitle(0.0, 1.0, "uno"), Subtitle(1.0, 2.0, "due")], str(srt))
        project.open_path(str(srt))
        assert project._source_path == str(srt)
        assert project.project.source_path == str(srt)
        assert [s["text"] for s in project._segments_raw] == ["uno", "due"]
        assert len(project.project.subtitles) == 2
        assert project._editor_loaded is True
        assert len(project.workspace.get_subtitles()) == 2
