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
import os
from pathlib import Path
from typing import List

from core.subtitle_model import Subtitle, SubtitleProject

_V2SRT_VERSION = 1
EXTENSION = ".v2srt"


def save_project(project: SubtitleProject, output_path: str, settings: dict | None = None):
    """Salva il progetto in formato .v2srt."""
    os.makedirs(str(Path(output_path).parent), exist_ok=True)
    data = {
        "version": _V2SRT_VERSION,
        "source_path": project.source_path or "",
        "settings": settings or {},
        "subtitles": [
            {"start": s.start, "end": s.end, "text": s.text}
            for s in project.subtitles
        ],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_project(path: str) -> tuple[SubtitleProject, dict]:
    """
    Carica un file .v2srt.
    Restituisce (SubtitleProject, settings_dict).
    Lancia ValueError se il formato non è valido.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or data.get("version") != _V2SRT_VERSION:
        raise ValueError(f"File non valido o versione non supportata: {path}")

    subs_raw = data.get("subtitles", [])
    if not isinstance(subs_raw, list):
        raise ValueError("Campo 'subtitles' non è una lista")

    subtitles: List[Subtitle] = []
    for i, item in enumerate(subs_raw):
        try:
            subtitles.append(Subtitle(
                start=float(item["start"]),
                end=float(item["end"]),
                text=str(item.get("text", "")),
            ))
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Sottotitolo {i} non valido: {e}")

    project = SubtitleProject()
    project.subtitles = subtitles
    project.source_path = data.get("source_path") or None

    settings = data.get("settings") or {}
    return project, settings


def is_v2srt(path: str) -> bool:
    return Path(path).suffix.lower() == EXTENSION
