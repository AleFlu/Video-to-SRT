"""
subtitle_model.py — Modello dati per un sottotitolo.

In Step 1 è usato solo come contenitore dopo la trascrizione.
In Step 2 diventerà la base del QAbstractTableModel per l'editor.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class Subtitle:
    """Un singolo sottotitolo con tempi in secondi."""
    start: float
    end: float
    text: str
    # Metadati opzionali dal motore di trascrizione
    confidence: float = 1.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text}

    @classmethod
    def from_dict(cls, d: dict) -> "Subtitle":
        return cls(
            start=float(d["start"]),
            end=float(d["end"]),
            text=str(d.get("text", "")).strip(),
            confidence=float(d.get("confidence", 1.0)),
        )


@dataclass
class SubtitleProject:
    """Stato del progetto corrente: file sorgente + lista sottotitoli."""
    source_path: str = ""
    subtitles: List[Subtitle] = field(default_factory=list)
    modified: bool = False

    def clear(self):
        self.source_path = ""
        self.subtitles = []
        self.modified = False

    def load_from_segments(self, segments: list, source_path: str):
        """Carica i sottotitoli dai segmenti prodotti da engine.transcribe()."""
        self.source_path = source_path
        self.subtitles = [Subtitle.from_dict(s) for s in segments]
        self.modified = False
