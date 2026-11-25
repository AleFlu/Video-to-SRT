"""
transcription_worker.py — Worker QThread per eseguire la trascrizione
senza bloccare la UI.

Usa engine.transcribe, che restituisce sottotitoli con tempi già definitivi
(core.subtitle_layout): il worker non li ritocca. I segmenti tornano alla UI invece
di essere scritti in un SRT: l'utente li modifica nell'editor e poi esporta.
"""

from __future__ import annotations
import logging
import threading
from dataclasses import dataclass, field, fields
from typing import Any, Dict, Optional, Union

from PySide6.QtCore import QObject, Signal

from core.constants import normalize_language
from core.transcription_config import TranscriptionConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptionParams:
    """Parametri di una trascrizione (immutabili).

    I campi espliciti (modello, beam, VAD, riduzione rumore, alta precisione, lingua)
    sono quelli scelti nella schermata iniziale; ``config`` fornisce i parametri avanzati
    (decodifica, VAD Silero, limiti di leggibilità), predefiniti se non indicata.
    """
    input_path: str
    model_size: str = "large-v3"
    beam_size: int = 5
    vad_filter: bool = True
    denoise: bool = True
    high_accuracy: bool = False
    language: Optional[str] = "it"   # None = rilevamento automatico
    config: TranscriptionConfig = field(default_factory=TranscriptionConfig)

    def __post_init__(self) -> None:
        # "auto" / "" / None -> None: faster-whisper non accetta "auto" come codice lingua
        object.__setattr__(self, "language", normalize_language(self.language))
        if self.config is None:
            object.__setattr__(self, "config", TranscriptionConfig())
        elif isinstance(self.config, dict):
            object.__setattr__(self, "config", TranscriptionConfig.from_dict(self.config))
        elif not isinstance(self.config, TranscriptionConfig):
            raise ValueError("Parametro 'config' non valido: atteso TranscriptionConfig")

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TranscriptionParams":
        """Crea i parametri da un dict (chiavi sconosciute ignorate)."""
        if not d.get("input_path"):
            raise ValueError("Parametro obbligatorio mancante: 'input_path'")
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    @classmethod
    def from_config(cls, input_path: str, config: TranscriptionConfig) -> "TranscriptionParams":
        """Parametri completi da una configurazione (es. un file .vsrtconfig importato)."""
        return cls(
            input_path=input_path, model_size=config.model_size, beam_size=config.beam_size,
            vad_filter=config.vad_filter, denoise=config.denoise,
            high_accuracy=config.high_accuracy, language=config.language, config=config,
        )


class TranscriptionWorker(QObject):
    """
    Eseguibile in un QThread separato.
    Segnali:
      - status(str)      : messaggio da mostrare in UI
      - progress(float)  : 0.0 .. 1.0
      - text(float, str) : frase appena trascritta (inizio in secondi, testo)
      - finished(list)   : lista di dict {start,end,text,confidence}
      - failed(str)      : errore
      - cancelled()      : annullato dall'utente
    """

    status = Signal(str)
    progress = Signal(float)
    text = Signal(float, str)
    finished = Signal(list)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, params: Union[TranscriptionParams, Dict[str, Any]]):
        super().__init__()
        if not isinstance(params, TranscriptionParams):
            params = TranscriptionParams.from_dict(params)
        self.params = params
        self._cancel_event = threading.Event()

    def request_cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            # Import lazy (così QThread può partire subito)
            from engine import transcribe, TranscriptionCancelled
        except Exception as e:
            log.exception("Impossibile caricare il motore di trascrizione")
            self.failed.emit(str(e) or type(e).__name__)
            return

        p = self.params
        try:
            segments = transcribe(
                input_path=p.input_path,
                model_size=p.model_size,
                beam_size=p.beam_size,
                vad_filter=p.vad_filter,
                denoise=p.denoise,
                high_accuracy=p.high_accuracy,
                language=p.language,
                config=p.config,
                cancel_event=self._cancel_event,
                on_status=lambda m: self.status.emit(m),
                on_progress=lambda v: self.progress.emit(float(v)),
                on_text=lambda start, t: self.text.emit(float(start), t),
            )

            if self._cancel_event.is_set():
                self.cancelled.emit()
                return

            self.progress.emit(1.0)
            self.status.emit(f"Completato · {len(segments)} sottotitoli")
            self.finished.emit(segments)

        except TranscriptionCancelled:
            self.cancelled.emit()
        except Exception as e:
            log.exception("Trascrizione fallita")
            self.failed.emit(str(e) or type(e).__name__)
