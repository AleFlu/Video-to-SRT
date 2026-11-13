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
        d = {"start": self.start, "end": self.end, "text": self.text}
        if self.confidence != 1.0:
            d["confidence"] = self.confidence
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Subtitle":
        """Crea un Subtitle da un dict; `start`/`end` sono obbligatori."""
        for key in ("start", "end"):
            if key not in d:
                raise ValueError(f"Campo obbligatorio mancante: '{key}'")
        try:
            start = float(d["start"])
            end = float(d["end"])
        except (TypeError, ValueError) as e:
            raise ValueError(f"Tempo non numerico: {e}") from e
        raw_text = d.get("text")
        text = "" if raw_text is None else str(raw_text).strip()
        try:
            confidence = float(d.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        return cls(start=start, end=end, text=text, confidence=confidence)


@dataclass
class SubtitleProject:
    """Stato del progetto corrente: file sorgente + lista sottotitoli."""
    source_path: str = ""
    subtitles: List[Subtitle] = field(default_factory=list)
    modified: bool = False

    def __post_init__(self):
        # source_path è sempre una stringa (mai None)
        if self.source_path is None:
            self.source_path = ""

    def clear(self):
        self.source_path = ""
        self.subtitles = []
        self.modified = False

    def load_from_segments(self, segments: list, source_path: str):
        """Carica i sottotitoli dai segmenti prodotti da engine.transcribe()."""
        self.source_path = source_path or ""
        self.subtitles = [Subtitle.from_dict(s) for s in segments]
        self.modified = False
