"""
transcription_worker.py — Worker QThread per eseguire la trascrizione
senza bloccare la UI.

Usa il motore esistente (engine.transcribe + post_process_timing),
ma restituisce i segmenti alla UI invece di scrivere direttamente il SRT:
l'utente li modifica nell'editor e poi esporta.
"""

from __future__ import annotations
import threading

from PySide6.QtCore import QObject, QThread, Signal


class TranscriptionWorker(QObject):
    """
    Eseguibile in un QThread separato.
    Segnali:
      - status(str)      : messaggio da mostrare in UI
      - progress(float)  : 0.0 .. 1.0
      - finished(list)   : lista di dict {start,end,text}
      - failed(str)      : errore
      - cancelled()      : annullato dall'utente
    """

    status = Signal(str)
    progress = Signal(float)
    finished = Signal(list)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, params: dict):
        super().__init__()
        self.params = params
        self._cancel_event = threading.Event()

    def request_cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            # Import lazy (così QThread può partire subito)
            from engine import transcribe, post_process_timing, TranscriptionCancelled

            segments = transcribe(
                input_path=self.params["input_path"],
                model_size=self.params.get("model_size", "large-v3"),
                beam_size=self.params.get("beam_size", 5),
                vad_filter=self.params.get("vad_filter", True),
                denoise=self.params.get("denoise", True),
                high_accuracy=self.params.get("high_accuracy", False),
                cancel_event=self._cancel_event,
                on_status=lambda m: self.status.emit(m),
                on_progress=lambda p: self.progress.emit(float(p)),
            )

            if self._cancel_event.is_set():
                self.cancelled.emit()
                return

            self.status.emit("Ottimizzazione timing sottotitoli...")
            segments = post_process_timing(segments)
            self.progress.emit(1.0)
            self.status.emit(f"Completato · {len(segments)} sottotitoli")
            self.finished.emit(segments)

        except TranscriptionCancelled:
            self.cancelled.emit()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e) or type(e).__name__)
