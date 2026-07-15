"""
progress_widget.py — Schermata Progress (Stato 1).

Mostra avanzamento trascrizione: progress bar + log + bottone Stop.
Avvia il worker QThread internamente via start(source_path, settings).

Segnali:
  transcription_done(segments: list, source_path: str)
  transcription_cancelled()
  transcription_failed(error: str)
"""

from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QProgressBar, QPlainTextEdit,
)

from core.transcription_worker import TranscriptionWorker
from ui.theme import AuroraMixin


class ProgressWidget(AuroraMixin, QWidget):
    """Schermata di trascrizione in corso."""

    transcription_done      = Signal(list, str)   # segments, source_path
    transcription_cancelled = Signal()
    transcription_failed    = Signal(str)          # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._aurora_init()
        self.setObjectName("contentPanel")

        self._thread: QThread | None = None
        self._worker: TranscriptionWorker | None = None
        self._source_path: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(48, 32, 48, 32)
        root.setSpacing(16)

        # ---- Titolo ----
        self.title_lbl = QLabel("Trascrizione in corso…")
        self.title_lbl.setObjectName("title")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.title_lbl)

        root.addSpacing(8)

        # ---- Card riepilogo ----
        summary_card = QFrame()
        summary_card.setObjectName("card")
        sl = QVBoxLayout(summary_card)
        sl.setContentsMargins(20, 14, 20, 14)
        sl.setSpacing(6)

        row_file = QHBoxLayout()
        row_file.addWidget(self._muted("File"))
        self.file_lbl = QLabel("—")
        self.file_lbl.setStyleSheet("font-weight: 600;")
        row_file.addWidget(self.file_lbl, 1)
        sl.addLayout(row_file)

        row_cfg = QHBoxLayout()
        row_cfg.addWidget(self._muted("Configurazione"))
        self.cfg_lbl = QLabel("—")
        self.cfg_lbl.setObjectName("muted")
        row_cfg.addWidget(self.cfg_lbl, 1)
        sl.addLayout(row_cfg)

        root.addWidget(summary_card)

        # ---- Progress bar ----
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        root.addWidget(self.progress)

        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("muted")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.status_lbl)

        # ---- Log ----
        log_header = QLabel("LOG")
        log_header.setStyleSheet(
            "color: #8a8a9a; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
        )
        root.addWidget(log_header)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Il log apparirà qui…")
        self.log.setStyleSheet(
            "QPlainTextEdit { font-family: 'SF Mono', monospace; font-size: 11px; }"
        )
        root.addWidget(self.log, 1)

        # ---- Bottone Stop ----
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setMinimumWidth(140)
        self.stop_btn.clicked.connect(self._on_stop)
        btn_row.addWidget(self.stop_btn)
        root.addLayout(btn_row)

    # ---- Helpers UI ----

    def paintEvent(self, event):
        p = QPainter(self)
        self._aurora_paint(p)
        p.end()

    def _muted(self, txt: str) -> QLabel:
        lbl = QLabel(txt)
        lbl.setObjectName("muted")
        lbl.setStyleSheet("font-size: 11px; min-width: 110px;")
        return lbl

    # ---- API pubblica ----

    def start(self, source_path: str, settings: dict):
        """Avvia trascrizione. Chiamato da MainWindow dopo HomeWidget.start_requested."""
        if self._thread is not None:
            return   # già in corso — non avviare due volte

        self._source_path = source_path

        # Aggiorna riepilogo
        self.title_lbl.setText("Trascrizione in corso…")
        self.file_lbl.setText(Path(source_path).name)
        parts = [
            f"Modello: {settings.get('model_size', '—')}",
            f"VAD: {'on' if settings.get('vad_filter') else 'off'}",
            f"Denoise: {'on' if settings.get('denoise') else 'off'}",
            f"Beam: {settings.get('beam_size', 5)}",
        ]
        self.cfg_lbl.setText("  ·  ".join(parts))
        self.log.clear()
        self.progress.setValue(0)
        self.status_lbl.setText("")
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("■  Stop")

        # Avvia worker
        params = {"input_path": source_path, **settings}
        self._thread = QThread(self)
        self._worker = TranscriptionWorker(params)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self._on_status)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)

        for sig in (self._worker.finished, self._worker.failed, self._worker.cancelled):
            sig.connect(self._cleanup)

        self._thread.start()

    def request_stop(self):
        """Cancella dall'esterno (es. closeEvent MainWindow)."""
        if self._worker:
            self._worker.request_cancel()

    def is_running(self) -> bool:
        return self._thread is not None

    # ---- Slots worker ----

    def _on_status(self, msg: str):
        self.status_lbl.setText(msg)
        self.log.appendPlainText(msg)

    def _on_progress(self, pct: float):
        self.progress.setValue(int(pct * 1000))

    def _on_finished(self, segments: list):
        self.progress.setValue(1000)
        n = len(segments)
        self.title_lbl.setText(f"Completato — {n} sottotitoli trovati")
        self.status_lbl.setText("Trascrizione completata")
        self.log.appendPlainText(f"--- Completato: {n} sottotitoli ---")
        self.stop_btn.setEnabled(False)
        self.transcription_done.emit(segments, self._source_path)

    def _on_failed(self, err: str):
        self.title_lbl.setText("Errore trascrizione")
        self.status_lbl.setText(f"Errore: {err}")
        self.log.appendPlainText(f"ERRORE: {err}")
        self.stop_btn.setText("← Torna alla home")
        self.stop_btn.setObjectName("primary")
        self.stop_btn.style().unpolish(self.stop_btn)
        self.stop_btn.style().polish(self.stop_btn)
        self.transcription_failed.emit(err)

    def _on_cancelled(self):
        self.progress.setValue(0)
        self.title_lbl.setText("Trascrizione annullata")
        self.status_lbl.setText("Annullata")
        self.log.appendPlainText("--- Annullata ---")
        self.transcription_cancelled.emit()

    def _on_stop(self):
        if self._worker and self._thread:
            self._worker.request_cancel()
            self.stop_btn.setEnabled(False)
            self.status_lbl.setText("Annullamento in corso…")
        else:
            # Bottone riconvertito in "torna home" dopo errore
            self.transcription_cancelled.emit()

    def _cleanup(self):
        if self._thread:
            self._thread.quit()
            self._thread.deleteLater()
            self._thread = None
            self._worker = None
