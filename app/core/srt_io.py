"""
srt_io.py — Lettura e scrittura file di sottotitoli (SRT, VTT, TXT, ASS).

Permette all'editor di rigenerare i file dopo le modifiche dell'utente senza
rifare la trascrizione. Tutte le scritture sono atomiche.
"""

from __future__ import annotations
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

from core.subtitle_layout import LayoutRules, wrap_lines
from core.subtitle_model import Subtitle
from core.transcription_config import active_readability

log = logging.getLogger(__name__)

# Timestamp SRT: ore 1+ cifre, millisecondi 1-3 cifre, separatore "," o "."
# Dopo il secondo timestamp sono tollerati tag di posizione (es. "X1:10 Y1:20").
_TS_RE = re.compile(
    r"^\s*(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
    r"\s*-->\s*"
    r"(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
)
_BLOCK_SPLIT_RE = re.compile(r"\n[ \t]*\n")


def _split_ms(seconds: float) -> Tuple[int, int, int, int]:
    """Scompone i secondi in (ore, minuti, secondi, millisecondi), arrotondando al ms."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    total_s, ms = divmod(total_ms, 1000)
    total_m, secs = divmod(total_s, 60)
    hrs, mins = divmod(total_m, 60)
    return hrs, mins, secs, ms


def _replace_with_retry(src: str, dst: str, attempts: int = 3, delay: float = 0.1) -> None:
    """``os.replace`` con retry su PermissionError (antivirus/indicizzatore su Windows)."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _write_text(path: str, text: str) -> None:
    """Scrive `text` in modo atomico: file temporaneo nella stessa cartella + os.replace."""
    parent = Path(path).parent
    os.makedirs(str(parent), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(parent), prefix=".tmp_", suffix=Path(path).suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        # mkstemp crea il file con permessi 0600: si ripristinano quelli usuali
        try:
            mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o644
            os.chmod(tmp, mode)
        except OSError:
            pass
        _replace_with_retry(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def format_timestamp_srt(seconds: float) -> str:
    h, m, s, ms = _split_ms(seconds)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def wrap_subtitle_text(text: str, max_chars: Optional[int] = None,
                       max_lines: Optional[int] = None) -> str:
    """
    Va a capo con le stesse regole del motore (``core.subtitle_layout.wrap_lines``).

    Il testo che contiene già degli a capo (scelti dall'utente) viene rispettato.
    Altrimenti, se supera `max_chars`, va a capo nel punto linguisticamente migliore
    (mai dopo articoli/preposizioni, righe bilanciate, quella in basso più lunga) su al
    massimo `max_lines` righe. None = valori della configurazione corrente (predefiniti
    MAX_CHARS_PER_LINE e 2 righe; almeno 2 anche con "Una riga per sottotitolo", che
    decide come il motore divide il parlato: un testo allungato a mano nell'editor va
    a capo invece di uscire dallo schermo su una riga sola).
    """
    limits = active_readability()
    if max_chars is None:
        max_chars = limits.max_chars_per_line
    if max_lines is None:
        max_lines = max(2, limits.max_lines)
    if "\n" in text or len(text) <= max_chars:
        return text
    return wrap_lines(text, LayoutRules(max_chars_per_line=max_chars, max_lines=max_lines))


def subtitles_to_srt(subtitles: List[Subtitle], max_chars: Optional[int] = None,
                     max_lines: Optional[int] = None) -> str:
    lines = []
    idx = 1
    for sub in subtitles:
        text = sub.text.strip()
        if not text:
            continue
        start = format_timestamp_srt(sub.start)
        end = format_timestamp_srt(sub.end)
        wrapped = wrap_subtitle_text(text, max_chars, max_lines)
        lines.append(f"{idx}\n{start} --> {end}\n{wrapped}\n")
        idx += 1
    return "\n".join(lines)


def write_srt(subtitles: List[Subtitle], output_path: str, max_chars: Optional[int] = None,
              max_lines: Optional[int] = None):
    _write_text(output_path, subtitles_to_srt(subtitles, max_chars, max_lines))


# ── Formati aggiuntivi (C3) ──────────────────────────────────────────────────

def format_timestamp_vtt(seconds: float) -> str:
    """HH:MM:SS.mmm per WebVTT."""
    h, m, sec, ms = _split_ms(seconds)
    return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"


def _vtt_escape(text: str) -> str:
    """Evita che il testo sia interpretato come cue timing o markup WebVTT."""
    return text.replace("-->", "->").replace("&", "&amp;").replace("<", "&lt;")


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
        lines.append(_vtt_escape(wrap_subtitle_text(text)))
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
        # Centisecondi: si arrotonda prima per evitare riporti a 100
        h, m, sec, ms = _split_ms(round(max(0.0, s) * 100) / 100.0)
        return f"{h}:{m:02d}:{sec:02d}.{ms // 10:02d}"

    events = []
    for sub in subtitles:
        text = sub.text.strip()
        if not text:
            continue
        ass_text = (text.replace("{", "\\{").replace("}", "\\}")
                    .replace("\n", "\\N"))
        events.append(
            f"Dialogue: 0,{_ass_ts(sub.start)},{_ass_ts(sub.end)},"
            f"Default,,0,0,0,,{ass_text}"
        )
    return header + "\n".join(events) + "\n"


def write_vtt(subtitles: List[Subtitle], output_path: str):
    _write_text(output_path, subtitles_to_vtt(subtitles))


def write_txt(subtitles: List[Subtitle], output_path: str):
    _write_text(output_path, subtitles_to_txt(subtitles))


def write_ass(subtitles: List[Subtitle], output_path: str, title: str = ""):
    _write_text(output_path, subtitles_to_ass(subtitles, title or Path(output_path).stem))


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


def _ts_to_sec(h: str, m: str, s: str, frac: str) -> float:
    """I millisecondi (1-3 cifre) sono una frazione decimale: "5" = 0,5 s."""
    return int(h) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000.0


def parse_srt(path: str) -> List[Subtitle]:
    """
    Legge un file .srt e restituisce una lista di Subtitle.

    Tollera BOM, CRLF, righe "vuote" con spazi, millisecondi a 1-3 cifre con
    "," o ".", ore a più cifre, blocchi senza indice e tag di posizione dopo
    il timestamp. I blocchi malformati vengono saltati.

    Lancia ValueError se il file non contiene alcun sottotitolo valido.
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    content = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")

    subtitles: List[Subtitle] = []
    for block in _BLOCK_SPLIT_RE.split(content.strip()):
        lines = block.strip("\n").split("\n")
        # Il timestamp è sulla prima riga, o sulla seconda se c'è un indice
        ts_idx = -1
        m = None
        for i in (0, 1):
            if i < len(lines):
                m = _TS_RE.match(lines[i])
                if m:
                    ts_idx = i
                    break
        if m is None:
            log.debug("Blocco SRT senza timestamp valido, saltato")
            continue
        start = _ts_to_sec(*m.group(1, 2, 3, 4))
        end = _ts_to_sec(*m.group(5, 6, 7, 8))
        text = "\n".join(ln.rstrip() for ln in lines[ts_idx + 1:]).strip()
        if text:
            subtitles.append(Subtitle(start=start, end=end, text=text))

    if not subtitles:
        raise ValueError(f"Nessun sottotitolo valido trovato in: {path}")
    return subtitles
