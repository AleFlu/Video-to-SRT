"""
test_nonfunctional.py — Test non-funzionali: performance, memoria, robustezza.

Coprono:
  - Tempi di creazione widget (< soglie ragionevoli)
  - Gestione input estremi (0 sub, 10000 sub, testo vuoto, caratteri speciali)
  - Formato timestamp con valori limite
  - Wrap testo long-line
  - SRT con blocchi malformati
  - Export tab con 10k sub senza crash
  - Robustezza parse SRT con encoding
"""

import os
import sys
import time
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _make_subs(n, text="Testo"):
    from core.subtitle_model import Subtitle
    return [Subtitle(start=i*2.0, end=i*2.0+1.8, text=f"{text} {i+1}") for i in range(n)]


# ── Performance ────────────────────────────────────────────────────────────────

class TestPerformance:
    """I widget devono crearsi in tempi ragionevoli."""

    def test_tab_bar_creation_time(self, app):
        from ui.tab_bar import TabBar
        t0 = time.perf_counter()
        for _ in range(20):
            TabBar()
        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, f"20x TabBar in {elapsed:.2f}s — troppo lento"

    def test_export_tab_creation_time(self, app):
        from ui.export_tab import ExportTab
        t0 = time.perf_counter()
        for _ in range(10):
            ExportTab()
        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, f"10x ExportTab in {elapsed:.2f}s — troppo lento"

    def test_export_tab_refresh_1000_subs(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        subs = _make_subs(1000)
        t0 = time.perf_counter()
        et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"refresh 1000 sub in {elapsed:.3f}s"

    def test_srt_serialization_1000_subs(self, app):
        from core.srt_io import subtitles_to_srt
        subs = _make_subs(1000)
        t0 = time.perf_counter()
        result = subtitles_to_srt(subs)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5
        assert "1000" in result or len(result) > 1000

    def test_project_tab_bar_add_max_tabs(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        t0 = time.perf_counter()
        for i in range(8):
            bar.add_tab(f"Progetto {i+1}")
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0
        assert bar.count() == 8


# ── Robustezza input ───────────────────────────────────────────────────────────

class TestRobustness:
    """L'app non deve crashare con input estremi o malformati."""

    def test_export_tab_zero_subs(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        et.refresh(segments_raw=[], editor_subs=[], source_path="", is_modified=False)
        assert et._stack.currentIndex() == 0
        assert et.current_subtitles() == []

    def test_export_tab_empty_source_path(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        subs = _make_subs(2)
        # Non deve crashare con source_path vuoto
        et.refresh(segments_raw=[], editor_subs=subs, source_path="", is_modified=False)
        assert et._stack.currentIndex() == 1

    def test_export_tab_unicode_source_path(self, app):
        from ui.export_tab import ExportTab
        et = ExportTab()
        subs = _make_subs(2)
        et.refresh(segments_raw=[], editor_subs=subs,
                   source_path="/tmp/video con spazi é ü 日本語.mp4", is_modified=False)
        assert "video con spazi" in et._panel._lbl_source.text()

    def test_subtitle_with_empty_text(self, app):
        from core.srt_io import subtitles_to_srt
        from core.subtitle_model import Subtitle
        subs = [
            Subtitle(start=0.0, end=1.0, text=""),
            Subtitle(start=1.0, end=2.0, text="Testo valido"),
            Subtitle(start=2.0, end=3.0, text="   "),
        ]
        result = subtitles_to_srt(subs)
        # Solo il sottotitolo valido deve apparire
        assert "Testo valido" in result
        lines = [l for l in result.strip().splitlines() if l.strip().isdigit()]
        assert len(lines) == 1

    def test_subtitle_with_special_chars(self, app):
        from core.srt_io import subtitles_to_srt
        from core.subtitle_model import Subtitle
        subs = [Subtitle(start=0.0, end=2.0, text='<b>Testo</b> "citazione" & più')]
        result = subtitles_to_srt(subs)
        assert "Testo" in result

    def test_timestamp_zero(self):
        from core.srt_io import format_timestamp_srt
        assert format_timestamp_srt(0.0) == "00:00:00,000"

    def test_timestamp_negative_clamped(self):
        from core.srt_io import format_timestamp_srt
        assert format_timestamp_srt(-5.0) == "00:00:00,000"

    def test_timestamp_large_value(self):
        from core.srt_io import format_timestamp_srt
        # 2h 30m 15.5s
        ts = format_timestamp_srt(2*3600 + 30*60 + 15.5)
        assert ts == "02:30:15,500"

    def test_timestamp_precision(self):
        from core.srt_io import format_timestamp_srt
        # 1ms
        assert format_timestamp_srt(0.001) == "00:00:00,001"

    def test_wrap_text_short_no_wrap(self):
        from core.srt_io import wrap_subtitle_text
        text = "Testo corto"
        assert wrap_subtitle_text(text) == text

    def test_wrap_text_long_splits(self):
        from core.srt_io import wrap_subtitle_text
        text = "Questo è un testo molto lungo che dovrebbe essere spezzato su due righe"
        result = wrap_subtitle_text(text)
        assert "\n" in result
        lines = result.split("\n")
        assert len(lines) == 2

    def test_parse_srt_malformed_no_timestamp(self, app, tmp_path):
        from core.srt_io import parse_srt
        f = tmp_path / "bad.srt"
        f.write_text("Questo non è un SRT valido\n\nNessun timestamp qui\n", encoding="utf-8")
        with pytest.raises(ValueError):
            parse_srt(str(f))

    def test_parse_srt_valid_minimal(self, app, tmp_path):
        from core.srt_io import parse_srt
        content = "1\n00:00:01,000 --> 00:00:03,500\nCiao mondo\n\n"
        f = tmp_path / "minimal.srt"
        f.write_text(content, encoding="utf-8")
        subs = parse_srt(str(f))
        assert len(subs) == 1
        assert subs[0].text == "Ciao mondo"
        assert subs[0].start == 1.0
        assert subs[0].end == 3.5

    def test_parse_srt_with_bom(self, app, tmp_path):
        from core.srt_io import parse_srt
        content = "1\n00:00:00,500 --> 00:00:02,000\nTesto con BOM\n\n"
        f = tmp_path / "bom.srt"
        f.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        subs = parse_srt(str(f))
        assert len(subs) == 1
        assert "BOM" in subs[0].text

    def test_project_tab_bar_max_limit(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        for i in range(8):
            bar.add_tab(f"P{i}")
        assert not bar.can_add()
        assert bar.count() == 8

    def test_project_tab_bar_remove_only_tab(self, app):
        from ui.project_tab_bar import ProjectTabBar
        bar = ProjectTabBar()
        bar.add_tab("Solo progetto")
        bar.remove_tab(0)
        assert bar.count() == 0
        assert bar.current_index() == -1

    def test_inline_progress_value_clamp(self, app):
        from ui.editor_tab import EditorTab
        et = EditorTab()
        et.inline_progress_show()
        et.inline_progress_update(0.0)
        assert et._inline_progress.value() == 0
        et.inline_progress_update(1.0)
        assert et._inline_progress.value() == 1000
        # Valori fuori range non devono crashare
        et.inline_progress_update(2.0)
        et.inline_progress_update(-0.5)


# ── Formato VTT ────────────────────────────────────────────────────────────────

class TestVttFormat:
    def test_vtt_header(self):
        from core.srt_io import subtitles_to_vtt
        subs = _make_subs(1)
        result = subtitles_to_vtt(subs)
        assert result.startswith("WEBVTT")

    def test_vtt_timestamp_dot_separator(self):
        from core.srt_io import format_timestamp_vtt
        ts = format_timestamp_vtt(1.5)
        assert "." in ts
        assert "," not in ts

    def test_vtt_and_srt_same_content(self):
        from core.srt_io import subtitles_to_srt, subtitles_to_vtt
        subs = _make_subs(3)
        srt = subtitles_to_srt(subs)
        vtt = subtitles_to_vtt(subs)
        # Stesso testo nei due formati
        for sub in subs:
            assert sub.text.strip() in srt
            assert sub.text.strip() in vtt


# ── Formato ASS ────────────────────────────────────────────────────────────────

class TestAssFormat:
    def test_ass_has_script_info(self):
        from core.srt_io import subtitles_to_ass
        subs = _make_subs(2)
        result = subtitles_to_ass(subs)
        assert "[Script Info]" in result
        assert "[Events]" in result

    def test_ass_dialogue_count(self):
        from core.srt_io import subtitles_to_ass
        subs = _make_subs(5)
        result = subtitles_to_ass(subs)
        dialogues = [l for l in result.splitlines() if l.startswith("Dialogue:")]
        assert len(dialogues) == 5

    def test_ass_newline_replacement(self):
        from core.srt_io import subtitles_to_ass
        from core.subtitle_model import Subtitle
        sub = Subtitle(start=0.0, end=2.0, text="Riga 1\nRiga 2")
        result = subtitles_to_ass([sub])
        assert "\\N" in result
