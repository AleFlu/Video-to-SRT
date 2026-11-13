"""test_v2srt_io.py — Test per core/v2srt_io.py"""

import json
import pytest

from core.subtitle_model import Subtitle, SubtitleProject
from core.v2srt_io import save_project, load_project, is_v2srt, EXTENSION


@pytest.fixture
def project():
    p = SubtitleProject()
    p.source_path = "/video/test.mp4"
    p.subtitles = [
        Subtitle(start=0.0,  end=2.0,  text="Prima"),
        Subtitle(start=3.0,  end=5.5,  text="Seconda"),
        Subtitle(start=6.0,  end=8.0,  text="Terza",  confidence=0.9),
    ]
    return p


# ── is_v2srt ──────────────────────────────────────────────────────────────────

def test_is_v2srt_correct_extension():
    assert is_v2srt("progetto.v2srt") is True

def test_is_v2srt_wrong_extension():
    assert is_v2srt("video.mp4") is False
    assert is_v2srt("sub.srt") is False

def test_is_v2srt_case_insensitive():
    assert is_v2srt("PROGETTO.V2SRT") is True


# ── save_project / load_project roundtrip ─────────────────────────────────────

def test_save_creates_file(tmp_path, project):
    out = tmp_path / "proj.v2srt"
    save_project(project, str(out))
    assert out.exists()

def test_save_valid_json(tmp_path, project):
    out = tmp_path / "proj.v2srt"
    save_project(project, str(out))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["source_path"] == "/video/test.mp4"
    assert len(data["subtitles"]) == 3

def test_roundtrip_text_preserved(tmp_path, project):
    out = tmp_path / "proj.v2srt"
    save_project(project, str(out))
    loaded, _ = load_project(str(out))
    texts = [s.text for s in loaded.subtitles]
    assert texts == ["Prima", "Seconda", "Terza"]

def test_roundtrip_times_preserved(tmp_path, project):
    out = tmp_path / "proj.v2srt"
    save_project(project, str(out))
    loaded, _ = load_project(str(out))
    assert loaded.subtitles[0].start == pytest.approx(0.0)
    assert loaded.subtitles[1].end   == pytest.approx(5.5)

def test_roundtrip_source_path(tmp_path, project):
    out = tmp_path / "proj.v2srt"
    save_project(project, str(out))
    loaded, _ = load_project(str(out))
    assert loaded.source_path == "/video/test.mp4"

def test_roundtrip_settings(tmp_path, project):
    out = tmp_path / "proj.v2srt"
    settings = {"model": "large-v3", "vad": True}
    save_project(project, str(out), settings=settings)
    _, loaded_settings = load_project(str(out))
    assert loaded_settings["model"] == "large-v3"
    assert loaded_settings["vad"] is True

def test_empty_subtitles(tmp_path):
    p = SubtitleProject()
    out = tmp_path / "empty.v2srt"
    save_project(p, str(out))
    loaded, _ = load_project(str(out))
    assert loaded.subtitles == []


# ── load_project error cases ──────────────────────────────────────────────────

def test_load_wrong_version_raises(tmp_path):
    bad = tmp_path / "bad.v2srt"
    bad.write_text(json.dumps({"version": 99, "subtitles": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="versione"):
        load_project(str(bad))

def test_load_not_dict_raises(tmp_path):
    bad = tmp_path / "bad.v2srt"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(str(bad))

def test_load_invalid_subtitle_raises(tmp_path):
    bad = tmp_path / "bad.v2srt"
    data = {
        "version": 1,
        "source_path": "",
        "subtitles": [{"start": "nope", "end": "bad", "text": "x"}],
    }
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(str(bad))

def test_load_missing_required_field_raises(tmp_path):
    bad = tmp_path / "bad.v2srt"
    # manca 'end'
    data = {"version": 1, "source_path": "", "subtitles": [{"start": 0.0, "text": "x"}]}
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(str(bad))


# ── Task 4 ────────────────────────────────────────────────────────────────────

def test_load_missing_source_path_is_empty_string(tmp_path):
    f = tmp_path / "a.v2srt"
    f.write_text(json.dumps({"version": 1, "subtitles": []}), encoding="utf-8")
    proj, _ = load_project(str(f))
    assert proj.source_path == ""

def test_load_invalid_json_raises_valueerror(tmp_path):
    f = tmp_path / "a.v2srt"
    f.write_text("{non json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_project(str(f))

def test_load_future_version_raises(tmp_path):
    f = tmp_path / "a.v2srt"
    f.write_text(json.dumps({"version": 2, "subtitles": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="versione"):
        load_project(str(f))

def test_save_keeps_confidence_and_is_atomic(tmp_path, project):
    project.subtitles[0].confidence = 0.4
    out = tmp_path / "x" / "p.v2srt"
    save_project(project, str(out))
    loaded, _ = load_project(str(out))
    assert loaded.subtitles[0].confidence == pytest.approx(0.4)
    assert [p.name for p in out.parent.iterdir()] == ["p.v2srt"]
