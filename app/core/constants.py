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

# ── Filtri dialog apertura file (generati dai set di estensioni) ──────────────

def _glob(exts) -> str:
    """Elenco ordinato di pattern '*.ext' per un filtro QFileDialog."""
    return " ".join(f"*{e}" for e in sorted(exts))


_MEDIA_GLOB = _glob(SUPPORTED_MEDIA_EXTS)
_SUBTITLE_GLOB = _glob(SUPPORTED_SUBTITLE_EXTS)
_ALL_GLOB = _glob(SUPPORTED_ALL_EXTS)

FILE_FILTER_OPEN_ANY = (
    f"Tutti i file supportati ({_ALL_GLOB});;"
    "Progetto V2SRT (*.v2srt);;"
    "SRT (*.srt);;"
    f"Video/Audio ({_MEDIA_GLOB})"
)

FILE_FILTER_IMPORT_ALL = (
    f"Tutti i file supportati ({_ALL_GLOB});;"
    f"Video/Audio ({_MEDIA_GLOB});;"
    f"Sottotitoli ({_SUBTITLE_GLOB});;"
    "Tutti i file (*.*)"
)

FILE_FILTER_IMPORT_SUBTITLES = (
    f"Sottotitoli ({_SUBTITLE_GLOB});;"
    "Tutti i file (*.*)"
)

# ── Limiti sottotitoli ────────────────────────────────────────────────────────

MAX_CHARS_PER_LINE: int = 42       # caratteri per riga SRT (wrap automatico)
MAX_SUBTITLE_DURATION: float = 7.0  # secondi
MIN_SUBTITLE_DURATION: float = 0.5  # secondi
MAX_CPS: float = 20.0               # caratteri al secondo (soglia errore di leggibilità)
WARN_CPS: float = 17.0              # caratteri al secondo (soglia di attenzione)
