"""
test_burn_in.py — Video con i sottotitoli impressi: lettura del video, disegno dei
sottotitoli, sequenza delle immagini, comando ffmpeg e (se c'è ffmpeg) un'esportazione vera.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from core import burn_in as b


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


# ── Lettura del video (output di ffmpeg -i) ──────────────────────────────────

_REEL = """
  Duration: 00:01:28.08, start: 0.000000, bitrate: 10904 kb/s
  Stream #0:0[0x1](eng): Video: h264 (Main) (avc1 / 0x31637661), yuv420p(progressive), 1080x1920 [SAR 1:1 DAR 9:16], 10581 kb/s, 25 fps, 25 tbr, 25k tbn (default)
  Stream #0:1[0x2](eng): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 317 kb/s (default)
"""
_MOV = """
  Duration: 00:00:49.64, start: 0.000000, bitrate: 18631 kb/s
  Stream #0:0[0x1]: Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709/bt709/unknown, progressive), 1920x1080 [SAR 1:1 DAR 16:9], 16324 kb/s, 25 fps, 25 tbr, 12800 tbn (default)
  Stream #0:1[0x2]: Audio: pcm_s24le (lpcm / 0x6D63706C), 48000 Hz, stereo, s32 (24 bit), 2304 kb/s (default)
  Stream #0:2[0x3](eng): Data: none (tmcd / 0x64636D74) (default)
"""
_PHONE = """
  Duration: 00:00:12.50, start: 0.000000, bitrate: 9000 kb/s
  Stream #0:0[0x1](und): Video: hevc (Main) (hvc1 / 0x31637668), yuv420p(tv), 1920x1080, 8000 kb/s, 30 fps (default)
      Metadata:
        handler_name    : Core Media Video
      Side data:
        displaymatrix: rotation of -90.00 degrees
"""


def test_probe_reads_size_duration_and_audio():
    assert b.parse_probe(_REEL) == b.VideoInfo(1080, 1920, pytest.approx(88.08), True, 10904)
    assert b.parse_probe(_MOV) == b.VideoInfo(1920, 1080, pytest.approx(49.64), True, 18631)


def test_probe_applies_phone_rotation_and_no_audio():
    assert b.parse_probe(_PHONE) == b.VideoInfo(1080, 1920, pytest.approx(12.5), False, 9000)


def test_probe_without_video_track():
    audio_only = "  Duration: 00:00:05.00\n  Stream #0:0: Audio: mp3, 44100 Hz, stereo\n"
    assert b.parse_probe(audio_only) is None


# ── Sequenza delle immagini ──────────────────────────────────────────────────

def test_timeline_covers_the_whole_video():
    cues = [(1.0, 2.5, "Uno"), (3.0, 4.0, "Due")]
    seq = b.overlay_timeline(cues, 6.0)
    assert seq == [(None, pytest.approx(1.0)), (0, pytest.approx(1.5)),
                   (None, pytest.approx(0.5)), (1, pytest.approx(1.0)),
                   (None, pytest.approx(2.0))]
    assert sum(d for _i, d in seq) == pytest.approx(6.0)


def test_timeline_clips_overlaps_empty_text_and_the_end():
    cues = [(2.0, 3.0, "Dopo"), (0.0, 2.5, "Prima"), (3.0, 3.5, "   "), (5.5, 9.0, "Coda")]
    seq = b.overlay_timeline(cues, 6.0)
    # "Prima" 0–2,5, poi "Dopo" da dove finisce "Prima"; il vuoto è saltato; "Coda" fino a 6
    assert seq[:2] == [(1, pytest.approx(2.5)), (0, pytest.approx(0.5))]
    assert (3, pytest.approx(0.5)) in seq
    assert sum(d for _i, d in seq) == pytest.approx(6.0, abs=0.05)


def test_overlay_listing_reuses_the_blank_image(app, tmp_path):
    info = b.VideoInfo(320, 180, 4.0, True)
    listing = b.write_overlay_sequence([(1.0, 2.0, "Ciao"), (2.5, 3.0, "a tutti")], info,
                                       tmp_path)
    text = listing.read_text(encoding="utf-8")
    assert text.startswith("ffconcat version 1.0")
    assert text.count("vuoto.png") >= 3
    assert "sub_00000.png" in text and "sub_00001.png" in text
    assert text.rstrip().splitlines()[-1].startswith("file ")


def test_overlay_listing_quotes_apostrophes(app, tmp_path):
    folder = tmp_path / "l'archivio"
    folder.mkdir()
    listing = b.write_overlay_sequence([(0.0, 1.0, "x")], b.VideoInfo(64, 64, 2.0, False),
                                       folder)
    assert "l'\\''archivio" in listing.read_text(encoding="utf-8")


def test_cancel_while_preparing_images(app, tmp_path):
    ev = threading.Event()
    ev.set()
    with pytest.raises(b.BurnInCancelled):
        b.write_overlay_sequence([(0.0, 1.0, "x")], b.VideoInfo(64, 64, 2.0, False), tmp_path,
                                 cancel_event=ev)


# ── Disegno ──────────────────────────────────────────────────────────────────

def _opaque_rows(img: QImage):
    return [y for y in range(img.height())
            if any(img.pixelColor(x, y).alpha() > 0 for x in range(0, img.width(), 4))]


def test_subtitle_is_drawn_at_the_bottom_on_transparent_frame(app):
    img = b.render_subtitle("Cos'è l'intelligenza artificiale civica?", 1920, 1080)
    assert (img.width(), img.height()) == (1920, 1080)
    rows = _opaque_rows(img)
    assert rows and rows[0] > 1080 * 0.7 and rows[-1] < 1080
    assert img.pixelColor(10, 10).alpha() == 0


def test_vertical_video_keeps_subtitles_above_social_buttons(app):
    img = b.render_subtitle("Ciao a tutti", 1080, 1920)
    rows = _opaque_rows(img)
    assert rows[-1] < 1920 * 0.82          # sopra pulsanti e didascalia dei reel
    assert rows[0] > 1920 * 0.6


def test_long_line_wraps_inside_the_frame(app):
    img = b.render_subtitle("parola " * 30, 640, 360)
    cols = [x for x in range(img.width())
            if any(img.pixelColor(x, y).alpha() > 0 for y in range(0, img.height(), 2))]
    assert cols[0] > 0 and cols[-1] < 639
    assert len(_opaque_rows(img)) > b.style_for(640, 360).font_px * 2   # più righe


def test_empty_text_is_fully_transparent(app):
    assert _opaque_rows(b.render_subtitle("  ", 100, 60)) == []


# ── Comando ffmpeg ───────────────────────────────────────────────────────────

def test_command_overlays_and_reencodes_audio(tmp_path):
    info = b.VideoInfo(1080, 1920, 10.0, True)
    cmd = b.build_command("ffmpeg", "in.mov", tmp_path / "l.ffconcat", "out.mp4", info,
                          ["-c:v", "libx264"])
    joined = " ".join(cmd)
    assert "-f concat -safe 0" in joined and "overlay=0:0" in joined
    assert "-map 0:a:0 -c:a aac" in joined         # PCM del .mov non va nell'MP4
    assert cmd[-1] == "out.mp4" and "-progress pipe:1" in joined


def test_command_without_audio(tmp_path):
    cmd = b.build_command("ffmpeg", "in.mp4", tmp_path / "l", "o.mp4",
                          b.VideoInfo(64, 64, 1.0, False), [])
    assert "0:a:0" not in cmd


def test_encoders_prefer_mac_hardware_at_the_source_bitrate(monkeypatch):
    listing = (" V....D libx264              libx264 H.264\n"
               " V....D h264_videotoolbox    VideoToolbox H.264 Encoder (codec h264)\n"
               " A....D aac                  AAC\n")
    monkeypatch.setattr(b.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, ""))
    encs = b.video_encoders("ffmpeg", b.VideoInfo(1080, 1920, 88.0, True, 10904))
    assert encs[0] == ["-c:v", "h264_videotoolbox", "-b:v", "10904k"]
    assert encs[1][:2] == ["-c:v", "libx264"] and encs[-1][:2] == ["-c:v", "mpeg4"]
    # bitrate sconosciuto o altissimo: limiti ragionevoli
    assert b.video_encoders("ffmpeg", b.VideoInfo(64, 64, 1.0, False))[0][-1] == "10000k"
    assert b.video_encoders("ffmpeg", b.VideoInfo(64, 64, 1.0, False, 90000))[0][-1] == "20000k"


def test_output_cannot_replace_the_source(tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"x")
    with pytest.raises(b.BurnInError, match="originale"):
        b.burn_in(str(src), [], str(src), ffmpeg="ffmpeg")


# ── Esportazione vera (solo se c'è ffmpeg) ───────────────────────────────────

_FFMPEG = shutil.which("ffmpeg")


def _frame(video, t, out):
    subprocess.run([_FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", str(t), "-i",
                    str(video), "-frames:v", "1", "-y", str(out)], check=True)
    return QImage(str(out))


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg non installato")
def test_real_export_burns_subtitles_only_while_they_are_on(app, tmp_path):
    src = tmp_path / "sorgente.mov"
    subprocess.run([_FFMPEG, "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=white:size=320x240:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3",
                    "-c:v", "mpeg4", "-c:a", "pcm_s16le", "-y", str(src)], check=True)
    out = tmp_path / "con sottotitoli.mp4"
    progress = []
    b.burn_in(str(src), [(1.0, 2.0, "MMMMMM")], str(out), on_progress=progress.append)
    assert out.exists() and progress[-1] == 1.0
    assert progress == sorted(progress)

    style = b.style_for(320, 240)
    y = 240 - style.bottom_margin - style.pad_v - 2     # dentro il riquadro, sotto il testo
    before = _frame(out, 0.4, tmp_path / "a.png").pixelColor(160, y)
    during = _frame(out, 1.5, tmp_path / "b.png").pixelColor(160, y)
    after = _frame(out, 2.6, tmp_path / "c.png").pixelColor(160, y)
    assert before.lightness() > 230 and after.lightness() > 230      # fondo bianco
    assert during.lightness() < 160                                  # riquadro scuro
    probe = b.probe(_FFMPEG, str(out))
    assert (probe.width, probe.height, probe.has_audio) == (320, 240, True)
    assert probe.duration == pytest.approx(3.0, abs=0.1)


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg non installato")
def test_real_export_can_be_cancelled(app, tmp_path):
    src = tmp_path / "s.mp4"
    subprocess.run([_FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=white:size=64x64:rate=25", "-t", "1", "-c:v", "mpeg4", "-y",
                    str(src)], check=True)
    ev = threading.Event()
    out = tmp_path / "o.mp4"
    ev.set()
    with pytest.raises(b.BurnInCancelled):
        b.burn_in(str(src), [(0.0, 0.5, "x")], str(out), cancel_event=ev)
    assert not out.exists()



@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg non installato")
def test_real_export_falls_back_when_an_encoder_fails(app, tmp_path, monkeypatch):
    """Caso VideoToolbox su un Mac senza codifica hardware: si passa all'encoder dopo."""
    src = tmp_path / "s.mp4"
    subprocess.run([_FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=white:size=64x64:rate=25", "-t", "1", "-c:v", "mpeg4", "-y",
                    str(src)], check=True)
    monkeypatch.setattr(b, "video_encoders", lambda ff, info: [
        ["-c:v", "encoder_che_non_esiste"], ["-c:v", "mpeg4", "-q:v", "2"]])
    out = tmp_path / "o.mp4"
    progress = []
    b.burn_in(str(src), [(0.0, 0.5, "x")], str(out), on_progress=progress.append)
    assert out.exists() and progress == sorted(progress) and progress[-1] == 1.0
