"""
test_export_formats.py — Una sola strada per esportare: formati, scrittura e dialog
condivisi da finestra Esporta, tab Esportazione e menu dell'editor.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from core import export_formats
from core.export_formats import BY_EXT, FORMATS, with_ext
from core.subtitle_model import Subtitle, SubtitleProject
from core.v2srt_io import load_project


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _subs():
    return [Subtitle(0.0, 1.5, "Prima riga"), Subtitle(2.0, 3.0, "Seconda")]


# ── Formati e scrittura ──────────────────────────────────────────────────────

def test_every_format_has_label_filter_and_hint():
    assert [f.ext for f in FORMATS] == [".srt", ".vtt", ".txt", ".ass", ".v2srt"]
    for f in FORMATS:
        assert f.label and f.hint and f"*{f.ext}" in f.file_filter
    assert [f.ext for f in FORMATS if f.is_project] == [".v2srt"]


def test_with_ext_adds_only_when_missing():
    assert with_ext("/a/b", ".srt") == "/a/b.srt"
    assert with_ext("/a/B.SRT", ".srt") == "/a/B.SRT"
    assert with_ext("/a/b.srt", ".vtt") == "/a/b.srt.vtt"


@pytest.mark.parametrize("ext, needle", [(".srt", "00:00:00,000 --> 00:00:01,500"),
                                         (".vtt", "WEBVTT"), (".txt", "Prima riga"),
                                         (".ass", "Title: intervista")])
def test_write_each_text_format(tmp_path, ext, needle):
    path = str(tmp_path / f"uscita{ext}")
    export_formats.write(_subs(), path, ext, source_path="/video/intervista.mp4")
    assert needle in open(path, encoding="utf-8").read()


def test_ass_title_falls_back_to_file_name(tmp_path):
    path = str(tmp_path / "solo file.ass")
    export_formats.write(_subs(), path, ".ass")
    assert "Title: solo file" in open(path, encoding="utf-8").read()


def test_project_keeps_subtitles_and_source(tmp_path):
    path = str(tmp_path / "p.v2srt")
    export_formats.write(_subs(), path, ".v2srt", source_path="/video/a.mp4")
    loaded, _ = load_project(path)
    assert loaded.source_path == "/video/a.mp4"
    assert [s.text for s in loaded.subtitles] == ["Prima riga", "Seconda"]
    project = SubtitleProject(source_path="/video/b.mp4")
    export_formats.write(_subs()[:1], path, ".v2srt", project=project)
    assert [s.text for s in project.subtitles] == ["Prima riga"]
    assert load_project(path)[0].source_path == "/video/b.mp4"


def test_unknown_format_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        export_formats.write(_subs(), str(tmp_path / "x.doc"), ".doc")


# ── Dialog di salvataggio ────────────────────────────────────────────────────

def test_added_extension_asks_before_replacing(app, tmp_path, monkeypatch):
    """Il dialog ha confermato «nome», non «nome.srt» che esiste già: si chiede."""
    from ui import export_dialogs
    existing = tmp_path / "nome.srt"
    existing.write_text("vecchio", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "nome"), "")))
    asked = []
    monkeypatch.setattr(export_dialogs, "resolve_existing",
                        lambda _parent, p: asked.append(p) or "")
    assert export_dialogs.ask_save_path(None, BY_EXT[".srt"], "Esporta") == ""
    assert asked == [str(existing)]
    # nome scelto con l'estensione: il dialog ha già chiesto, nessuna seconda domanda
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(existing), "")))
    assert export_dialogs.ask_save_path(None, BY_EXT[".srt"], "Esporta") == str(existing)
    assert len(asked) == 1


# ── ProjectWidget: menu dell'editor, tab Esportazione, Salva progetto ────────

@pytest.fixture
def project(app):
    from ui.project_widget import ProjectWidget
    pw = ProjectWidget(1, ffmpeg_ok=True, model_ok=True)
    yield pw
    pw.teardown()
    pw._export_panel.close()
    pw.deleteLater()


def _save_to(monkeypatch, path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(path), "")))


def test_editor_menu_exports_editor_subtitles(project, tmp_path, monkeypatch):
    project.workspace.timeline.load_subtitles(_subs())
    _save_to(monkeypatch, tmp_path / "menu")           # estensione aggiunta
    project._on_tl_export_vtt()
    assert "Seconda" in (tmp_path / "menu.vtt").read_text(encoding="utf-8")


def test_export_tab_and_project_save(project, tmp_path, monkeypatch):
    project.export_tab.refresh([], _subs(), "/video/clip.mp4", False)
    _save_to(monkeypatch, tmp_path / "tab.srt")
    project._on_tab_export_srt()
    assert "Prima riga" in (tmp_path / "tab.srt").read_text(encoding="utf-8")
    _save_to(monkeypatch, tmp_path / "tab.v2srt")
    project._on_tab_save_v2srt()
    assert len(load_project(str(tmp_path / "tab.v2srt"))[0].subtitles) == 2


def test_save_project_uses_transcription_before_editor_opens(project, tmp_path, monkeypatch):
    """⇧⌘S appena finita la trascrizione (editor ancora vuoto): si salva quella."""
    project._segments_raw = [{"start": 0.0, "end": 1.0, "text": "Dalla trascrizione"}]
    project._source_path = "/video/clip.mp4"
    _save_to(monkeypatch, tmp_path / "subito.v2srt")
    project.save_v2srt()
    loaded, _ = load_project(str(tmp_path / "subito.v2srt"))
    assert [s.text for s in loaded.subtitles] == ["Dalla trascrizione"]


def test_nothing_to_export_warns_without_dialog(project, monkeypatch):
    warned, opened = [], []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: warned.append(a[2])))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: opened.append(1) or ("", "")))
    project._on_tab_export_ass()
    project.save_v2srt()
    assert warned == ["Non ci sono sottotitoli da esportare.",
                      "Non ci sono sottotitoli da salvare."]
    assert opened == []


def test_write_error_is_shown(project, tmp_path, monkeypatch):
    project.export_tab.refresh([], _subs(), "", False)
    _save_to(monkeypatch, tmp_path / "manca" / "x.srt")
    monkeypatch.setattr(export_formats, "write_srt",
                        lambda *a: (_ for _ in ()).throw(OSError("disco pieno")))
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a: errors.append(a[2])))
    project._on_tab_export_srt()
    assert errors and "disco pieno" in errors[0]
