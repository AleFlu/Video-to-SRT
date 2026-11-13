"""
v2srt_io.py — Formato progetto .v2srt (C4).

JSON con sottotitoli + source_path + settings di trascrizione.
Permette di riaprire un progetto senza rifare la trascrizione.

Schema:
{
  "version": 1,
  "source_path": "/path/al/video.mp4",
  "settings": { ... },           # opzionale (salvato se disponibile)
  "subtitles": [
    { "start": 1.23, "end": 4.56, "text": "Ciao mondo" },
    ...
  ]
}
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.srt_io import _write_text
from core.subtitle_model import Subtitle, SubtitleProject

_V2SRT_VERSION = 1
EXTENSION = ".v2srt"


def save_project(project: SubtitleProject, output_path: str,
                 settings: Optional[dict] = None):
    """Salva il progetto in formato .v2srt (scrittura atomica)."""
    data = {
        "version": _V2SRT_VERSION,
        "source_path": project.source_path or "",
        "settings": settings or {},
        "subtitles": [s.to_dict() for s in project.subtitles],
    }
    _write_text(output_path, json.dumps(data, ensure_ascii=False, indent=2))


def load_project(path: str) -> Tuple[SubtitleProject, Dict]:
    """
    Carica un file .v2srt.
    Restituisce (SubtitleProject, settings_dict).
    Lancia ValueError (messaggio in italiano) se il formato non è valido.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"File JSON non valido ({e.msg}): {path}") from e
    except UnicodeDecodeError as e:
        raise ValueError(f"File non leggibile come testo UTF-8: {path}") from e

    if not isinstance(data, dict):
        raise ValueError(f"File non valido: {path}")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(f"File non valido o senza versione: {path}")
    if version > _V2SRT_VERSION:
        raise ValueError(
            f"Progetto con versione non supportata ({version}): "
            f"aggiorna l'applicazione per aprire {path}"
        )

    subs_raw = data.get("subtitles", [])
    if not isinstance(subs_raw, list):
        raise ValueError("Il campo 'subtitles' non è una lista")

    subtitles: List[Subtitle] = []
    for i, item in enumerate(subs_raw):
        if not isinstance(item, dict):
            raise ValueError(f"Sottotitolo {i} non valido: non è un oggetto")
        try:
            subtitles.append(Subtitle.from_dict(item))
        except ValueError as e:
            raise ValueError(f"Sottotitolo {i} non valido: {e}") from e

    project = SubtitleProject()
    project.subtitles = subtitles
    project.source_path = str(data.get("source_path") or "")

    settings = data.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}
    return project, settings


def is_v2srt(path: str) -> bool:
    return Path(path).suffix.lower() == EXTENSION
