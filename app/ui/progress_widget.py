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
import warnings
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread, QCoreApplication
from PySide6.QtGui import QPainter, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QProgressBar, QPlainTextEdit, QMessageBox,
)

from core.transcription_worker import TranscriptionWorker
from ui.theme import AuroraMixin
from ui.widgets import ElidedLabel
from ui import theme
import platform_support

# Thread sganciati da widget distrutti (vedi detach_and_stop): le tuple (thread,
# worker) tengono vivi i wrapper Python finché il thread non termina.
_DETACHED: list = []


def _release_detached(t):
    for pair in list(_DETACHED):
        if pair[0] is t:
            _DETACHED.remove(pair)
            pair[1].deleteLater()
            t.deleteLater()


def wait_detached_threads(timeout_ms: int = 3000):
    """Attende (con timeout) i thread sganciati — da chiamare alla chiusura app."""
    for t, _w in list(_DETACHED):
        t.wait(timeout_ms)


class _Spinner(QWidget):
    """Spinner circolare animato (come .spinner del design Studio)."""

    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._angle = 0
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)
        # Il timer gira solo quando lo spinner è visibile (vedi show/hideEvent):
        # evita tick a 45ms su tab progetto nascoste

    def showEvent(self, event):
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPen, QColor
        from PySide6.QtCore import QRectF
        c = theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = 2
        rect = QRectF(m, m, self._size - 2 * m, self._size - 2 * m)
        # cerchio di base
        base = QColor(c("acc_soft_2"))
        p.setPen(QPen(base, 2))
        p.drawEllipse(rect)
        # arco accento
        p.setPen(QPen(QColor(c("acc")), 2))
        p.drawArc(rect, -self._angle * 16, 90 * 16)
        p.end()


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

        # ---- Titolo (con spinner) ----
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addStretch(1)
        self._spinner = _Spinner(18)
        title_row.addWidget(self._spinner, 0, Qt.AlignVCenter)
        self.title_lbl = QLabel("Trascrizione in corso…")
        self.title_lbl.setObjectName("title")
        title_row.addWidget(self.title_lbl, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        root.addLayout(title_row)

        root.addSpacing(8)

        # ---- Card riepilogo ----
        summary_card = QFrame()
        summary_card.setObjectName("card")
        sl = QVBoxLayout(summary_card)
        sl.setContentsMargins(20, 14, 20, 14)
        sl.setSpacing(6)

        row_file = QHBoxLayout()
        row_file.addWidget(self._muted("File"))
        self.file_lbl = ElidedLabel("—")
        self.file_lbl.setStyleSheet("font-weight: 600;")
        row_file.addWidget(self.file_lbl, 1)
        sl.addLayout(row_file)

        row_cfg = QHBoxLayout()
        row_cfg.addWidget(self._muted("Configurazione"))
        self.cfg_lbl = QLabel("—")
        self.cfg_lbl.setObjectName("muted")
        self.cfg_lbl.setWordWrap(True)
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
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        # ---- Log ----
        self._log_header = QLabel("LOG")
        root.addWidget(self._log_header)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Il log apparirà qui…")
        self.log.setAccessibleName("Log della trascrizione")
        root.addWidget(self.log, 1)

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

        # ---- Bottone Stop ----
        btn_row = QHBoxLayout()
        # Dopo un errore: copia del log e posizione del file di log completo
        self.copy_log_btn = QPushButton("Copia log")
        self.copy_log_btn.setObjectName("secondary")
        self.copy_log_btn.setMinimumHeight(40)
        self.copy_log_btn.setToolTip(
            f"Copia il log negli appunti (log completo in {platform_support.app_cache_dir()})"
        )
        self.copy_log_btn.clicked.connect(self._copy_log)
        self.copy_log_btn.setVisible(False)
        btn_row.addWidget(self.copy_log_btn)
        btn_row.addStretch(1)
        self.stop_btn = QPushButton("■  Interrompi")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setMinimumWidth(140)
        self.stop_btn.setToolTip("Interrompi la trascrizione  (Esc)")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        btn_row.addWidget(self.stop_btn)
        root.addLayout(btn_row)

        # Esc = Interrompi (con conferma), solo quando questa schermata è visibile
        sc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self._on_escape)

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
        self._spinner.show()
        self.title_lbl.setText("Trascrizione in corso…")
        self.file_lbl.setText(Path(source_path).name)
        self.file_lbl.set_full_tooltip(source_path)
        parts = [
            f"Modello: {settings.get('model_size', '—')}",
            f"VAD: {'attivo' if settings.get('vad_filter') else 'disattivo'}",
            f"Riduzione rumore: {'attiva' if settings.get('denoise') else 'disattiva'}",
            f"Beam: {settings.get('beam_size', 5)}",
        ]
        self.cfg_lbl.setText("  ·  ".join(parts))
        self.log.clear()
        self.progress.setValue(0)
        self.status_lbl.setText("")
        self.copy_log_btn.setVisible(False)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("■  Interrompi")
        self.stop_btn.setToolTip("Interrompi la trascrizione  (Esc)")
        if self.stop_btn.objectName() != "danger":
            # dopo un errore il bottone era diventato "primary" (torna alla home)
            self.stop_btn.setObjectName("danger")
            self.stop_btn.style().unpolish(self.stop_btn)
            self.stop_btn.style().polish(self.stop_btn)

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

    def detach_and_stop(self):
        """
        Da chiamare PRIMA di distruggere il widget con trascrizione in corso.
        Il QThread è figlio del widget: distruggerlo mentre gira causa il fatal
        Qt "QThread: Destroyed while thread is still running" (crash app).
        Qui lo riparentiamo all'applicazione e chiediamo il cancel cooperativo:
        il thread si autodistrugge quando il worker ritorna, senza bloccare la UI.
        """
        if self._thread is None:
            return
        t, w = self._thread, self._worker
        self._thread = None
        self._worker = None
        # Un segnale tardivo del worker non deve più raggiungere questo widget
        # (es. transcription_done su un progetto già chiuso).
        pairs = ((w.status, self._on_status), (w.progress, self._on_progress),
                 (w.finished, self._on_finished), (w.failed, self._on_failed),
                 (w.cancelled, self._on_cancelled), (w.finished, self._cleanup),
                 (w.failed, self._cleanup), (w.cancelled, self._cleanup))
        with warnings.catch_warnings():
            # PySide6 avvisa (RuntimeWarning) se una connessione non esiste già più
            warnings.simplefilter("ignore", RuntimeWarning)
            for sig, slot in pairs:
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        w.request_cancel()
        if not t.isRunning():
            t.deleteLater()
            w.deleteLater()
            return
        t.setParent(QCoreApplication.instance())
        _DETACHED.append((t, w))
        t.quit()   # ha effetto quando worker.run ritorna al loop del thread
        t.finished.connect(lambda: _release_detached(t))

    def is_running(self) -> bool:
        return self._thread is not None

    # ---- Slots worker ----

    def _on_status(self, msg: str):
        self.status_lbl.setText(msg)
        self.log.appendPlainText(msg)

    def _on_progress(self, pct: float):
        self.progress.setValue(int(pct * 1000))

    def _on_finished(self, segments: list):
        self._spinner.hide()
        self.progress.setValue(1000)
        n = len(segments)
        self.title_lbl.setText(f"Completato — {n} sottotitoli trovati")
        self.status_lbl.setText("Trascrizione completata")
        self.log.appendPlainText(f"--- Completato: {n} sottotitoli ---")
        self.stop_btn.setEnabled(False)
        self.transcription_done.emit(segments, self._source_path)

    def _on_failed(self, err: str):
        self._spinner.hide()
        self.title_lbl.setText("Errore trascrizione")
        self.status_lbl.setText(f"Errore: {err}")
        self.log.appendPlainText(f"ERRORE: {err}")
        self.copy_log_btn.setVisible(True)
        self.stop_btn.setText("← Torna alla Home")
        self.stop_btn.setToolTip("Torna alla schermata iniziale")
        self.stop_btn.setObjectName("primary")
        self.stop_btn.style().unpolish(self.stop_btn)
        self.stop_btn.style().polish(self.stop_btn)
        self.transcription_failed.emit(err)

    def _on_cancelled(self):
        self._spinner.hide()
        self.progress.setValue(0)
        self.title_lbl.setText("Trascrizione annullata")
        self.status_lbl.setText("Annullata")
        self.log.appendPlainText("--- Annullata ---")
        self.transcription_cancelled.emit()

    def _on_stop_clicked(self):
        """Click su Interrompi: chiede conferma (un click accidentale non perde il lavoro)."""
        if self._worker and self._thread:
            self._confirm_and_stop()
        else:
            self._on_stop()

    def _copy_log(self):
        QApplication.clipboard().setText(self.log.toPlainText())
        self.status_lbl.setText("Log copiato negli appunti")

    def _on_escape(self):
        if self._worker and self._thread and self.stop_btn.isEnabled():
            self._confirm_and_stop()

    def _confirm_and_stop(self):
        ans = QMessageBox.question(
            self, "Interrompere la trascrizione?",
            "La trascrizione in corso verrà annullata e il lavoro fatto finora andrà perso.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            self._on_stop()

    def _on_stop(self):
        if self._worker and self._thread:
            self._worker.request_cancel()
            self.stop_btn.setEnabled(False)
            self.status_lbl.setText("Annullamento in corso…")
        else:
            # Bottone riconvertito in "torna home" dopo errore
            self.transcription_cancelled.emit()

    def _apply_palette(self, _name=None):
        self._log_header.setStyleSheet(
            f"color: {theme.c('muted')}; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
        )
        self.log.setStyleSheet(
            f"QPlainTextEdit {{ font-family: {theme.FONT_MONO}; font-size: 11.5px;"
            f" background: {theme.c('inset')}; }}"
        )

    def _cleanup(self):
        if self._thread is None:
            return
        t, w = self._thread, self._worker
        self._thread = None
        self._worker = None
        t.quit()
        # Attende la fine reale del thread prima di permettere un nuovo start():
        # senza wait, un riavvio rapido creerebbe due thread vivi insieme.
        # A questo punto worker.run è già ritornato (i segnali arrivano alla
        # fine), quindi l'attesa è in pratica immediata.
        if not t.wait(3000):
            # Fallback: sgancia e lascia che si autodistrugga
            t.setParent(QCoreApplication.instance())
            _DETACHED.append((t, w))
            t.finished.connect(lambda: _release_detached(t))
            return
        t.deleteLater()
        if w:
            w.deleteLater()
