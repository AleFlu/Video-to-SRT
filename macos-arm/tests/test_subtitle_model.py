"""test_subtitle_model.py — Test per core/subtitle_model.py"""

import pytest
from core.subtitle_model import Subtitle, SubtitleProject


# ── Subtitle ──────────────────────────────────────────────────────────────────

def test_subtitle_duration():
    s = Subtitle(start=1.0, end=4.5, text="x")
    assert s.duration == pytest.approx(3.5)

def test_subtitle_duration_zero_if_end_before_start():
    s = Subtitle(start=5.0, end=3.0, text="x")
    assert s.duration == 0.0

def test_subtitle_to_dict():
    s = Subtitle(start=1.0, end=2.0, text="Ciao")
    d = s.to_dict()
    assert d == {"start": 1.0, "end": 2.0, "text": "Ciao"}

def test_subtitle_from_dict():
    d = {"start": "1.5", "end": "3.0", "text": " Testo ", "confidence": "0.8"}
    s = Subtitle.from_dict(d)
    assert s.start == pytest.approx(1.5)
    assert s.end   == pytest.approx(3.0)
    assert s.text  == "Testo"
    assert s.confidence == pytest.approx(0.8)

def test_subtitle_from_dict_default_confidence():
    s = Subtitle.from_dict({"start": 0.0, "end": 1.0, "text": "x"})
    assert s.confidence == pytest.approx(1.0)

def test_subtitle_roundtrip():
    original = Subtitle(start=12.345, end=67.89, text="Prova")
    recovered = Subtitle.from_dict(original.to_dict())
    assert recovered.start == pytest.approx(original.start)
    assert recovered.end   == pytest.approx(original.end)
    assert recovered.text  == original.text


# ── SubtitleProject ───────────────────────────────────────────────────────────

def test_project_clear():
    p = SubtitleProject()
    p.source_path = "/some/path.mp4"
    p.subtitles = [Subtitle(0, 1, "x")]
    p.modified = True
    p.clear()
    assert p.source_path == ""
    assert p.subtitles == []
    assert p.modified is False

def test_project_load_from_segments():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Prima"},
        {"start": 2.0, "end": 3.0, "text": "Seconda"},
    ]
    p = SubtitleProject()
    p.load_from_segments(segments, "/video.mp4")
    assert p.source_path == "/video.mp4"
    assert len(p.subtitles) == 2
    assert p.subtitles[0].text == "Prima"
    assert p.modified is False

def test_project_load_from_segments_empty():
    p = SubtitleProject()
    p.load_from_segments([], "/video.mp4")
    assert p.subtitles == []
    assert p.source_path == "/video.mp4"
