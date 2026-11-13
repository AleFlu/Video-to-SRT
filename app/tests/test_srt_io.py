"""test_srt_io.py — Test per core/srt_io.py"""

import pytest

from core.subtitle_model import Subtitle
from core.srt_io import (
    format_timestamp_srt, format_timestamp_vtt,
    wrap_subtitle_text, subtitles_to_srt, subtitles_to_vtt,
    subtitles_to_txt, subtitles_to_ass,
    write_srt, write_vtt, write_txt, write_ass,
    parse_srt, unique_output_path,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def subs():
    return [
        Subtitle(start=1.0,  end=3.5,  text="Ciao mondo"),
        Subtitle(start=4.0,  end=6.0,  text="Seconda riga"),
        Subtitle(start=7.0,  end=9.0,  text=""),          # testo vuoto → ignorato
    ]


# ── format_timestamp_srt ──────────────────────────────────────────────────────

def test_format_timestamp_srt_basic():
    assert format_timestamp_srt(0.0) == "00:00:00,000"

def test_format_timestamp_srt_one_hour():
    assert format_timestamp_srt(3661.5) == "01:01:01,500"

def test_format_timestamp_srt_negative_clamped():
    assert format_timestamp_srt(-5.0) == "00:00:00,000"

def test_format_timestamp_srt_milliseconds():
    assert format_timestamp_srt(1.001) == "00:00:01,001"

def test_format_timestamp_srt_rounding():
    # 1.0014 → round(1001.4) = 1001 ms
    assert format_timestamp_srt(1.0014) == "00:00:01,001"


# ── format_timestamp_vtt ──────────────────────────────────────────────────────

def test_format_timestamp_vtt_uses_dot():
    ts = format_timestamp_vtt(61.0)
    assert "." in ts
    assert "," not in ts
    assert ts == "00:01:01.000"

def test_format_timestamp_vtt_zero():
    assert format_timestamp_vtt(0.0) == "00:00:00.000"


# ── wrap_subtitle_text ────────────────────────────────────────────────────────

def test_wrap_short_text():
    t = "Ciao"
    assert wrap_subtitle_text(t) == t   # corto → invariato

def test_wrap_long_text_splits():
    t = "Questa è una frase molto lunga che deve essere spezzata su due righe"
    result = wrap_subtitle_text(t)
    assert "\n" in result
    parts = result.split("\n")
    assert len(parts) == 2
    assert parts[0].strip() and parts[1].strip()

def test_wrap_exactly_42_chars_no_split():
    t = "A" * 42
    assert wrap_subtitle_text(t) == t

def test_wrap_43_chars_with_space():
    # 21 chars + spazio + 21 chars = 43, split al centro
    t = ("A" * 21) + " " + ("B" * 21)
    result = wrap_subtitle_text(t)
    assert "\n" in result


# ── subtitles_to_srt ──────────────────────────────────────────────────────────

def test_subtitles_to_srt_skips_empty(subs):
    result = subtitles_to_srt(subs)
    assert "Ciao mondo" in result
    assert "Seconda riga" in result
    # Sottotitolo con testo vuoto non appare
    lines = result.split("\n")
    indices = [l for l in lines if l.strip().isdigit()]
    assert indices == ["1", "2"]   # solo 2 blocchi

def test_subtitles_to_srt_format(subs):
    result = subtitles_to_srt(subs)
    assert "00:00:01,000 --> 00:00:03,500" in result
    assert "00:00:04,000 --> 00:00:06,000" in result

def test_subtitles_to_srt_empty_list():
    assert subtitles_to_srt([]) == ""


# ── subtitles_to_vtt ──────────────────────────────────────────────────────────

def test_subtitles_to_vtt_header(subs):
    result = subtitles_to_vtt(subs)
    assert result.startswith("WEBVTT")

def test_subtitles_to_vtt_uses_dot(subs):
    result = subtitles_to_vtt(subs)
    assert "00:00:01.000 --> 00:00:03.500" in result

def test_subtitles_to_vtt_skips_empty(subs):
    result = subtitles_to_vtt(subs)
    assert result.count("-->") == 2   # solo 2 blocchi validi


# ── subtitles_to_txt ──────────────────────────────────────────────────────────

def test_subtitles_to_txt_only_text(subs):
    result = subtitles_to_txt(subs)
    assert "00:" not in result
    assert "Ciao mondo" in result
    assert "Seconda riga" in result

def test_subtitles_to_txt_skips_empty(subs):
    result = subtitles_to_txt(subs)
    lines = [l for l in result.split("\n") if l.strip()]
    assert len(lines) == 2


# ── subtitles_to_ass ──────────────────────────────────────────────────────────

def test_subtitles_to_ass_header(subs):
    result = subtitles_to_ass(subs)
    assert "[Script Info]" in result
    assert "[V4+ Styles]" in result
    assert "[Events]" in result

def test_subtitles_to_ass_dialogue(subs):
    result = subtitles_to_ass(subs)
    assert "Dialogue:" in result
    assert "Ciao mondo" in result

def test_subtitles_to_ass_newline_escaped():
    s = [Subtitle(start=0.0, end=1.0, text="Riga uno\nRiga due")]
    result = subtitles_to_ass(s)
    assert "\\N" in result
    assert "\nRiga due" not in result   # non deve restare newline nuda nel Dialogue


# ── parse_srt ─────────────────────────────────────────────────────────────────

_SRT_CONTENT = """\
1
00:00:01,000 --> 00:00:03,500
Ciao mondo

2
00:00:04,000 --> 00:00:06,000
Seconda riga
"""

def test_parse_srt_basic(tmp_path):
    f = tmp_path / "test.srt"
    f.write_text(_SRT_CONTENT, encoding="utf-8")
    subs = parse_srt(str(f))
    assert len(subs) == 2
    assert subs[0].text == "Ciao mondo"
    assert subs[0].start == pytest.approx(1.0)
    assert subs[0].end   == pytest.approx(3.5)
    assert subs[1].text == "Seconda riga"

def test_parse_srt_empty_raises(tmp_path):
    f = tmp_path / "empty.srt"
    f.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_srt(str(f))

def test_parse_srt_no_valid_blocks_raises(tmp_path):
    f = tmp_path / "bad.srt"
    f.write_text("questo non è un srt\n\nrandomtext", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_srt(str(f))

def test_parse_srt_roundtrip(tmp_path):
    """Scrivi SRT → rileggi → i testi devono essere identici."""
    original = [
        Subtitle(start=0.5, end=2.0, text="Prima"),
        Subtitle(start=3.0, end=5.5, text="Seconda"),
    ]
    out = tmp_path / "rt.srt"
    write_srt(original, str(out))
    parsed = parse_srt(str(out))
    assert len(parsed) == 2
    assert parsed[0].text == "Prima"
    assert parsed[1].text == "Seconda"


# ── write_* ───────────────────────────────────────────────────────────────────

def test_write_srt_creates_file(tmp_path, subs):
    out = tmp_path / "out.srt"
    write_srt(subs, str(out))
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "Ciao mondo" in content

def test_write_vtt_creates_file(tmp_path, subs):
    out = tmp_path / "out.vtt"
    write_vtt(subs, str(out))
    assert out.exists()
    assert out.read_text().startswith("WEBVTT")

def test_write_txt_creates_file(tmp_path, subs):
    out = tmp_path / "out.txt"
    write_txt(subs, str(out))
    assert out.exists()
    assert "Ciao mondo" in out.read_text()

def test_write_ass_creates_file(tmp_path, subs):
    out = tmp_path / "out.ass"
    write_ass(subs, str(out))
    assert out.exists()
    assert "[Script Info]" in out.read_text()


# ── unique_output_path ────────────────────────────────────────────────────────

def test_unique_output_path_no_conflict(tmp_path):
    p = str(tmp_path / "out.srt")
    assert unique_output_path(p) == p   # file non esiste → stesso path

def test_unique_output_path_conflict(tmp_path):
    p = tmp_path / "out.srt"
    p.write_text("x")
    result = unique_output_path(str(p))
    assert result != str(p)
    assert "out_2" in result
