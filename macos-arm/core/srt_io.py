"""
srt_io.py — Lettura e scrittura file SRT.

Wrapper attorno alle funzioni esistenti in engine.py, così l'editor
può rigenerare SRT dopo le modifiche dell'utente senza rifare la
trascrizione.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import List

from core.subtitle_model import Subtitle
from core.constants import MAX_CHARS_PER_LINE


def format_timestamp_srt(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_secs = total_ms // 1000
    secs = total_secs % 60
    total_mins = total_secs // 60
    mins = total_mins % 60
    hrs = total_mins // 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def wrap_subtitle_text(text: str) -> str:
    """Spezza su max 2 righe da ~42 caratteri cercando uno spazio vicino al centro."""
    if len(text) <= MAX_CHARS_PER_LINE:
        return text
    mid = len(text) // 2
    for offset in range(0, mid):
        for pos in [mid + offset, mid - offset]:
            if 0 <= pos < len(text) and text[pos] == " ":
                return text[:pos] + "\n" + text[pos + 1:]
    return text


def subtitles_to_srt(subtitles: List[Subtitle]) -> str:
    lines = []
    idx = 1
    for sub in subtitles:
        text = sub.text.strip()
        if not text:
            continue
        start = format_timestamp_srt(sub.start)
        end = format_timestamp_srt(sub.end)
        lines.append(f"{idx}\n{start} --> {end}\n{wrap_subtitle_text(text)}\n")
        idx += 1
    return "\n".join(lines)


def write_srt(subtitles: List[Subtitle], output_path: str):
    os.makedirs(str(Path(output_path).parent), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(subtitles_to_srt(subtitles))


# ── Formati aggiuntivi (C3) ──────────────────────────────────────────────────

def format_timestamp_vtt(seconds: float) -> str:
    """HH:MM:SS.mmm per WebVTT."""
    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    secs = total_s % 60
    total_m = total_s // 60
    mins = total_m % 60
    hrs = total_m // 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{ms:03d}"


def subtitles_to_vtt(subtitles: List[Subtitle]) -> str:
    """WebVTT (.vtt)."""
    lines = ["WEBVTT", ""]
    idx = 1
    for sub in subtitles:
        text = sub.text.strip()
        if not text:
            continue
        start = format_timestamp_vtt(sub.start)
        end   = format_timestamp_vtt(sub.end)
        lines.append(f"{idx}")
        lines.append(f"{start} --> {end}")
        lines.append(wrap_subtitle_text(text))
        lines.append("")
        idx += 1
    return "\n".join(lines)


def subtitles_to_txt(subtitles: List[Subtitle]) -> str:
    """Testo semplice (.txt) — solo il contenuto, un sottotitolo per riga."""
    lines = []
    for sub in subtitles:
        text = sub.text.strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def subtitles_to_ass(subtitles: List[Subtitle], title: str = "Video → SRT") -> str:
    """Advanced SubStation Alpha (.ass) con stile default."""
    header = (
        "[Script Info]\n"
        f"Title: {title}\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,2,1,2,10,10,18,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def _ass_ts(s: float) -> str:
        s = max(0.0, s)
        total_cs = round(s * 100)
        cs = total_cs % 100
        total_sec = total_cs // 100
        sec = total_sec % 60
        total_min = total_sec // 60
        mins = total_min % 60
        hrs = total_min // 60
        return f"{hrs}:{mins:02d}:{sec:02d}.{cs:02d}"

    events = []
    for sub in subtitles:
        text = sub.text.strip()
        if not text:
            continue
        ass_text = text.replace("\n", "\\N")
        events.append(
            f"Dialogue: 0,{_ass_ts(sub.start)},{_ass_ts(sub.end)},"
            f"Default,,0,0,0,,{ass_text}"
        )
    return header + "\n".join(events) + "\n"


def write_vtt(subtitles: List[Subtitle], output_path: str):
    os.makedirs(str(Path(output_path).parent), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(subtitles_to_vtt(subtitles))


def write_txt(subtitles: List[Subtitle], output_path: str):
    os.makedirs(str(Path(output_path).parent), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(subtitles_to_txt(subtitles))


def write_ass(subtitles: List[Subtitle], output_path: str, title: str = ""):
    os.makedirs(str(Path(output_path).parent), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(subtitles_to_ass(subtitles, title or Path(output_path).stem))


def unique_output_path(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return path
    counter = 2
    while True:
        candidate = p.parent / f"{p.stem}_{counter}{p.suffix}"
        if not candidate.exists():
            return str(candidate)
        counter += 1


def default_output_for(source: str) -> str:
    return str(Path(source).with_suffix(".srt"))


def parse_srt(path: str) -> List[Subtitle]:
    """
    Legge un file .srt e restituisce una lista di Subtitle.
    Formato atteso:
        1
        00:00:01,000 --> 00:00:03,500
        Testo del sottotitolo

    Lancia ValueError se il file non contiene blocchi validi.
    """
    import re

    _TS = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
        r"\s*-->\s*"
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})"
    )

    def _to_sec(h, m, s, ms) -> float:
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    subtitles: List[Subtitle] = []
    blocks = re.split(r"\n{2,}", content.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        # Salta indice numerico se presente
        start_line = 0
        if lines[0].strip().isdigit():
            start_line = 1
        if start_line >= len(lines):
            continue
        m = _TS.match(lines[start_line].strip())
        if not m:
            continue
        start = _to_sec(*m.group(1, 2, 3, 4))
        end   = _to_sec(*m.group(5, 6, 7, 8))
        text  = "\n".join(lines[start_line + 1:]).strip()
        if text:
            subtitles.append(Subtitle(start=start, end=end, text=text))

    if not subtitles:
        raise ValueError(f"Nessun sottotitolo valido trovato in: {path}")
    return subtitles
