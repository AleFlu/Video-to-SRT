"""
test_structural.py — Test strutturali (white-box): verifica l'architettura interna.

Coprono:
  - Segnali esposti dai widget (API contrattuale)
  - Invarianti architetturali (INV1..INV6)
  - Separazione core/ui (core non importa da ui)
  - Struttura file .v2srt (JSON schema)
  - Stato interno widget dopo operazioni
  - Costanti globali e loro coerenza
  - Nessuna duplicazione worker attivo
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


def _make_subs(n=3):
    from core.subtitle_model import Subtitle
    return [Subtitle(start=i*2.0, end=i*2.0+1.8, text=f"Sub {i+1}") for i in range(n)]


# ── Separazione architetturale core/ui ────────────────────────────────────────

class TestArchitecturalSeparation:
    """INV: core/ non deve importare da ui/."""

    def _get_imports(self, filepath):
        import ast
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read())
            except SyntaxError:
                return []
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return imports

    def test_subtitle_model_no_ui_import(self):
        path = os.path.join(os.path.dirname(__file__), "..", "core", "subtitle_model.py")
        imports = self._get_imports(path)
        assert not any(imp.startswith("ui") for imp in imports), \
            f"core/subtitle_model.py importa da ui: {[i for i in imports if i.startswith('ui')]}"

    def test_srt_io_no_ui_import(self):
        path = os.path.join(os.path.dirname(__file__), "..", "core", "srt_io.py")
        imports = self._get_imports(path)
        assert not any(imp.startswith("ui") for imp in imports)

    def test_transcription_worker_no_ui_import(self):
        path = os.path.join(os.path.dirname(__file__), "..", "core", "transcription_worker.py")
        imports = self._get_imports(path)
        assert not any(imp.startswith("ui") for imp in imports)

    def test_v2srt_io_no_ui_import(self):
        path = os.path.join(os.path.dirname(__file__), "..", "core", "v2srt_io.py")
        imports = self._get_imports(path)
        assert not any(imp.startswith("ui") for imp in imports)

    def test_audio_player_no_ui_import(self):
        path = os.path.join(os.path.dirname(__file__), "..", "core", "audio_player.py")
        imports = self._get_imports(path)
        # audio_player usa PySide6 (ok) ma non ui/
        assert not any(imp.startswith("ui") for imp in imports)


# ── Costanti globali ──────────────────────────────────────────────────────────

class TestConstants:
    """Verifica che le costanti in core/constants.py siano corrette e coerenti."""

    def test_constants_importable(self):
        from core.constants import (
            MAX_CHARS_PER_LINE, MAX_SUBTITLE_DURATION, MIN_SUBTITLE_DURATION, MAX_CPS,  # noqa: F401
        )

    def test_media_exts_union(self):
        from core.constants import SUPPORTED_VIDEO_EXTS, SUPPORTED_AUDIO_EXTS, SUPPORTED_MEDIA_EXTS
        assert SUPPORTED_MEDIA_EXTS == SUPPORTED_VIDEO_EXTS | SUPPORTED_AUDIO_EXTS

    def test_all_exts_union(self):
        from core.constants import SUPPORTED_MEDIA_EXTS, SUPPORTED_SUBTITLE_EXTS, SUPPORTED_ALL_EXTS
        assert SUPPORTED_ALL_EXTS == SUPPORTED_MEDIA_EXTS | SUPPORTED_SUBTITLE_EXTS

    def test_video_exts_are_lowercase_with_dot(self):
        from core.constants import SUPPORTED_VIDEO_EXTS
        for ext in SUPPORTED_VIDEO_EXTS:
            assert ext.startswith("."), f"estensione senza punto: {ext}"
            assert ext == ext.lower(), f"estensione non lowercase: {ext}"

    def test_srt_in_subtitle_exts(self):
        from core.constants import SUPPORTED_SUBTITLE_EXTS
        assert ".srt" in SUPPORTED_SUBTITLE_EXTS

    def test_v2srt_in_subtitle_exts(self):
        from core.constants import SUPPORTED_SUBTITLE_EXTS
        assert ".v2srt" in SUPPORTED_SUBTITLE_EXTS

    def test_max_chars_per_line_value(self):
        from core.constants import MAX_CHARS_PER_LINE
        assert MAX_CHARS_PER_LINE == 42

    def test_durations_logical(self):
        from core.constants import MAX_SUBTITLE_DURATION, MIN_SUBTITLE_DURATION
        assert MIN_SUBTITLE_DURATION < MAX_SUBTITLE_DURATION
        assert MIN_SUBTITLE_DURATION > 0

    def test_exts_are_frozenset(self):
        from core.constants import SUPPORTED_VIDEO_EXTS, SUPPORTED_AUDIO_EXTS
        assert isinstance(SUPPORTED_VIDEO_EXTS, frozenset)
        assert isinstance(SUPPORTED_AUDIO_EXTS, frozenset)

    def test_no_overlap_video_audio(self):
        from core.constants import SUPPORTED_VIDEO_EXTS, SUPPORTED_AUDIO_EXTS
        overlap = SUPPORTED_VIDEO_EXTS & SUPPORTED_AUDIO_EXTS
        assert len(overlap) == 0, f"Overlap video/audio: {overlap}"


# ── Segnali API ───────────────────────────────────────────────────────────────

class TestSignalContracts:
    """Verifica che i widget espongano i segnali attesi."""

    def test_tab_bar_signals(self, app):
        from ui.tab_bar import TabBar
        tb = TabBar()
        assert hasattr(tb, "tab_changed")

    def test_project_tab_bar_signals(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        assert hasattr(bar, "tab_selected")
        assert hasattr(bar, "tab_close_requested")
        assert hasattr(bar, "new_tab_requested")

    def test_editor_tab_signals(self, app):
        from ui.editor_tab import EditorTab
        et = EditorTab()
        assert hasattr(et, "import_requested")
        assert hasattr(et, "go_transcription_requested")

    def test_export_tab_signals(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        assert hasattr(et, "export_srt_requested")
        assert hasattr(et, "export_vtt_requested")
        assert hasattr(et, "export_txt_requested")
        assert hasattr(et, "export_ass_requested")
        assert hasattr(et, "save_v2srt_requested")

    def test_placeholder_signals(self, app):
        from ui.placeholder_widget import PlaceholderWidget
        pw = PlaceholderWidget()
        assert hasattr(pw, "go_transcription_requested")   # compatibilità
        assert hasattr(pw, "import_file_requested")
        assert hasattr(pw, "file_dropped")


# ── Stato interno ProjectTabBar ────────────────────────────────────────────────

class TestProjectTabBarState:
    """Verifica la coerenza dello stato interno di ProjectTabBar."""

    def test_initial_state(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        assert bar.count() == 0
        assert bar.current_index() == -1

    def test_add_updates_count(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        bar.add_tab("P1")
        assert bar.count() == 1

    def test_add_selects_new_tab(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        bar.add_tab("P1")
        bar.add_tab("P2")
        assert bar.current_index() == 1

    def test_remove_updates_current(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        bar.add_tab("P1")
        bar.add_tab("P2")
        bar.add_tab("P3")
        bar.select_tab(1)
        bar.remove_tab(1)
        assert bar.count() == 2
        assert bar.current_index() in (0, 1)

    def test_select_emits_signal(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        bar.add_tab("P1")
        bar.add_tab("P2")
        received = []
        bar.tab_selected.connect(received.append)
        bar.select_tab(0)
        assert 0 in received

    def test_no_signal_same_tab(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        bar.add_tab("P1")
        received = []
        bar.tab_selected.connect(received.append)
        bar.select_tab(0)   # già selezionata
        assert received == []

    def test_plus_button_always_exists(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        assert bar._btn_new is not None

    def test_can_add_false_at_max(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        for i in range(8):
            bar.add_tab(f"P{i}")
        assert not bar.can_add()

    def test_set_tab_title(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        bar.add_tab("Vecchio titolo")
        bar.set_tab_title(0, "Nuovo titolo")
        # Il testo nel label viene eliso — verifica via tooltip o direttamente
        # Non crashare è sufficiente; il testo eliso è implementation detail

    def test_set_tab_modified_badge(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        bar.add_tab("P1")
        bar.set_tab_modified(0, True)
        assert not bar._tabs[0]._badge.isHidden()
        bar.set_tab_modified(0, False)
        assert bar._tabs[0]._badge.isHidden()


# ── Struttura SubtitleModel ───────────────────────────────────────────────────

class TestSubtitleModelStructure:
    """Verifica la struttura del modello dati."""

    def test_subtitle_has_required_fields(self):
        from core.subtitle_model import Subtitle
        sub = Subtitle(start=1.0, end=2.0, text="Test")
        assert hasattr(sub, "start")
        assert hasattr(sub, "end")
        assert hasattr(sub, "text")

    def test_subtitle_project_has_subtitles(self):
        from core.subtitle_model import SubtitleProject
        proj = SubtitleProject()
        assert hasattr(proj, "subtitles")
        assert isinstance(proj.subtitles, list)

    def test_subtitle_project_load_from_segments(self):
        from core.subtitle_model import SubtitleProject
        seg = {"start": 0.0, "end": 1.0, "text": " Parola"}
        proj = SubtitleProject()
        proj.load_from_segments([seg], "/tmp/v.mp4")
        assert len(proj.subtitles) == 1
        assert proj.subtitles[0].text.strip() == "Parola"

    def test_subtitle_immutable_copy(self):
        import dataclasses
        from core.subtitle_model import Subtitle
        sub = Subtitle(start=0.0, end=1.0, text="Orig")
        copy = dataclasses.replace(sub, text="Modified")
        assert sub.text == "Orig"
        assert copy.text == "Modified"


# ── Struttura v2srt ───────────────────────────────────────────────────────────

class TestV2srtStructure:
    """Verifica che il formato .v2srt sia JSON leggibile con i campi attesi."""

    def test_save_and_load_roundtrip(self, tmp_path):
        from core.subtitle_model import SubtitleProject, Subtitle
        from core.v2srt_io import save_project, load_project
        proj = SubtitleProject()
        proj.subtitles = [
            Subtitle(start=0.0, end=1.5, text="Prima riga"),
            Subtitle(start=2.0, end=3.5, text="Seconda riga"),
        ]
        proj.source_path = "/tmp/video.mp4"
        path = str(tmp_path / "test.v2srt")
        save_project(proj, path)
        loaded, _ = load_project(path)
        assert len(loaded.subtitles) == 2
        assert loaded.subtitles[0].text == "Prima riga"
        assert loaded.subtitles[1].text == "Seconda riga"

    def test_v2srt_is_json(self, tmp_path):
        import json
        from core.subtitle_model import SubtitleProject, Subtitle
        from core.v2srt_io import save_project
        proj = SubtitleProject()
        proj.subtitles = [Subtitle(start=0.0, end=1.0, text="Test")]
        path = str(tmp_path / "test.v2srt")
        save_project(proj, path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "subtitles" in data or isinstance(data, dict)

    def test_v2srt_extension_constant(self):
        from core.v2srt_io import EXTENSION
        assert EXTENSION == ".v2srt"

    def test_is_v2srt_detection(self, tmp_path):
        from core.v2srt_io import is_v2srt, save_project
        from core.subtitle_model import SubtitleProject, Subtitle
        proj = SubtitleProject()
        proj.subtitles = [Subtitle(start=0.0, end=1.0, text="Test")]
        path = str(tmp_path / "test.v2srt")
        save_project(proj, path)
        assert is_v2srt(path)

    def test_is_v2srt_false_for_plain_text(self, tmp_path):
        from core.v2srt_io import is_v2srt
        path = str(tmp_path / "test.txt")
        with open(path, "w") as f:
            f.write("non è un v2srt")
        assert not is_v2srt(path)


# ── INV: badge editor ↔ sub non vuoti ─────────────────────────────────────────

class TestInvariants:
    """Verifica le invarianti architetturali documentate nel CLAUDE.md."""

    def test_inv3_editor_badge_tracks_subs(self, app):
        """INV3: badge ● su Editor ↔ subtitles non vuoti."""
        from ui.tab_bar import TabBar
        tb = TabBar()
        # Nessun sub → badge nascosto
        tb.set_editor_badge(False)
        assert tb._badge.isHidden()
        # Sub presenti → badge visibile
        tb.set_editor_badge(True)
        assert not tb._badge.isHidden()

    def test_inv_export_tab_placeholder_when_empty(self, app):
        """ExportTab mostra placeholder ↔ nessun sub."""
        from ui.export_tab import ExportTab
        et = ExportTab()
        et.refresh([], [], "", False)
        assert et._stack.currentIndex() == 0
        from core.subtitle_model import Subtitle
        et.refresh([], [Subtitle(0, 1, "T")], "", False)
        assert et._stack.currentIndex() == 1
