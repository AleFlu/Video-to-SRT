"""
constants.py — Costanti condivise tra core e ui.

Centralizza le definizioni che altrimenti verrebbero duplicate in più moduli.
"""

from __future__ import annotations

# ── Estensioni file supportate ────────────────────────────────────────────────

SUPPORTED_VIDEO_EXTS: frozenset[str] = frozenset({
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v",
})

SUPPORTED_AUDIO_EXTS: frozenset[str] = frozenset({
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma",
})

SUPPORTED_MEDIA_EXTS: frozenset[str] = SUPPORTED_VIDEO_EXTS | SUPPORTED_AUDIO_EXTS

SUPPORTED_SUBTITLE_EXTS: frozenset[str] = frozenset({".srt", ".v2srt"})

SUPPORTED_ALL_EXTS: frozenset[str] = SUPPORTED_MEDIA_EXTS | SUPPORTED_SUBTITLE_EXTS

# ── Filtri dialog apertura file ───────────────────────────────────────────────

FILE_FILTER_OPEN_ANY = (
    "Tutti i file supportati "
    "(*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.m4a *.flac *.webm *.ogg *.v2srt *.srt);;"
    "Progetto V2SRT (*.v2srt);;"
    "SRT (*.srt);;"
    "Video/Audio (*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.m4a *.flac *.webm *.ogg)"
)

FILE_FILTER_IMPORT_ALL = (
    "Tutti i file supportati "
    "(*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.m4a *.flac *.webm *.ogg *.srt *.v2srt);;"
    "Video/Audio (*.mp4 *.mkv *.avi *.mov *.mp3 *.wav *.m4a *.flac *.webm *.ogg);;"
    "Sottotitoli (*.srt *.v2srt);;"
    "Tutti i file (*.*)"
)

FILE_FILTER_IMPORT_SUBTITLES = (
    "Sottotitoli (*.srt *.v2srt);;"
    "Tutti i file (*.*)"
)

# ── Limiti sottotitoli ────────────────────────────────────────────────────────

MAX_CHARS_PER_LINE: int = 42       # caratteri per riga SRT (wrap automatico)
MAX_SUBTITLE_DURATION: float = 7.0  # secondi
MIN_SUBTITLE_DURATION: float = 0.5  # secondi
MAX_CPS: float = 20.0               # caratteri al secondo (soglia warning)
