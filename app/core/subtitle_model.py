"""
subtitle_model.py — Modello dati per un sottotitolo.

In Step 1 è usato solo come contenitore dopo la trascrizione.
In Step 2 diventerà la base del QAbstractTableModel per l'editor.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple


def is_unedited(text: str, asr_text: str) -> bool:
    """True se il testo è ancora quello della trascrizione (a meno degli spazi)."""
    return bool(asr_text) and " ".join(text.split()) == " ".join(asr_text.split())


@dataclass
class Subtitle:
    """Un singolo sottotitolo con tempi in secondi."""
    start: float
    end: float
    text: str
    # Metadati opzionali dal motore di trascrizione
    confidence: float = 1.0
    # Testo scritto da Whisper e sue parole incerte (``core.spelling``): le parole incerte
    # si evidenziano finché ``text`` è ancora ``asr_text``; le parole di ``asr_text`` non
    # sono segnalate dal controllo ortografico. Vuoti per sottotitoli importati.
    asr_text: str = ""
    uncertain: Tuple[str, ...] = ()

    @property
    def unedited(self) -> bool:
        """True se il testo è ancora quello scritto da Whisper."""
        return is_unedited(self.text, self.asr_text)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        d = {"start": self.start, "end": self.end, "text": self.text}
        if self.confidence != 1.0:
            d["confidence"] = self.confidence
        if self.asr_text:
            d["asr_text"] = self.asr_text
        if self.uncertain:
            d["uncertain"] = list(self.uncertain)
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
        raw_asr = d.get("asr_text")
        asr_text = raw_asr.strip() if isinstance(raw_asr, str) else ""
        raw_unc = d.get("uncertain")
        uncertain = (tuple(str(w) for w in raw_unc if isinstance(w, str))
                     if isinstance(raw_unc, (list, tuple)) else ())
        return cls(start=start, end=end, text=text, confidence=confidence,
                   asr_text=asr_text, uncertain=uncertain)


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
