"""
progress_widget.py — Schermata Progress (Stato 1), "Bianco e nero".

Colonna sinistra: file e impostazioni, percentuale grande, barra sottile, elenco
delle cinque fasi (ricavato dai messaggi di stato del worker), "Interrompi".
Colonna destra (520 px): pannello "Log" con orario per riga e "Copia log".
Avvia il worker QThread internamente via start(source_path, settings).

Segnali:
  transcription_done(segments: list, source_path: str)
  transcription_cancelled()
  transcription_failed(error: str)
"""

from __future__ import annotations
import logging
import time
import warnings
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QPainter, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
    QPushButton, QProgressBar, QPlainTextEdit, QMessageBox,
)

from core.constants import SUPPORTED_AUDIO_EXTS
from core.transcription_worker import TranscriptionWorker
from ui.widgets import ElidedLabel, fmt_size
from ui import icons, theme
import platform_support

log = logging.getLogger(__name__)

_LANG_NAMES = {"it": "Italiano", "en": "Inglese", "es": "Spagnolo", "fr": "Francese",
               "de": "Tedesco", "auto": "Rilevamento automatico"}

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
    """Attende (con timeout) i thread sganciati — da chiamare alla chiusura app.

    Un thread ancora in esecuzione dopo l'attesa non deve mai essere distrutto da Qt
    ("QThread: Destroyed while thread is still running"): resta referenziato in
    ``_DETACHED`` e senza parent, così il teardown di QApplication non lo elimina.
    """
    for t, _w in list(_DETACHED):
        if t.wait(timeout_ms):
            continue
        log.warning("Thread di trascrizione ancora attivo alla chiusura: lo si lascia "
                    "terminare con il processo")
        t.setParent(None)


def has_running_detached_threads() -> bool:
    """True se esiste un thread sganciato ancora in esecuzione."""
    return any(t.isRunning() for t, _w in _DETACHED)


# ── Fasi della trascrizione ───────────────────────────────────────────────────
# Ricavate dai messaggi di stato già emessi da engine/worker, per parole chiave.
# Un messaggio sconosciuto aggiorna solo la riga di stato: l'elenco non si rompe
# se i testi cambiano.

PHASES = (
    "Pre-elaborazione audio",
    "Caricamento modello",
    "Trascrizione",
    "Segmentazione sottotitoli",
    "Ottimizzazione timing",
)

_PH_PENDING, _PH_ACTIVE, _PH_DONE = "pending", "active", "done"


def phase_for_status(msg: str) -> Optional[int]:
    """Indice (0-4) della fase a cui appartiene il messaggio di stato; None se ignoto."""
    m = (msg or "").lower()
    if "download del modello" in m or m.endswith("scaricato"):
        return None   # download prima della trascrizione: solo riga di stato e barra
    if "ottimizzazione timing" in m or "generazione file" in m or m.startswith("completato"):
        return 4
    if "segmentazione" in m or m.startswith("trascrizione completata"):
        return 3
    if "pre-elaborazione" in m or "audio pre-elaborato" in m or "audio ripulito" in m:
        return 0
    if "caricamento modello" in m or m.startswith("modello") or "pre-caricamento" in m:
        return 1
    if ("trascrizione in corso" in m or "elaborazione audio" in m or m.startswith("lingua:")
            or "allineamento" in m or "trascrizione" in m):
        return 2
    return None


# ── Tempo rimanente ──────────────────────────────────────────────────────────
# Il motore riporta l'avanzamento così: 0–15 % download, audio e modello; 15–90 % la
# trascrizione vera (in proporzione all'audio già trascritto); poi recupero e segmentazione.
_ETA_START = 0.15
_ETA_END = 0.90
_ETA_MIN_SPAN = 0.05      # avanzamento minimo prima di stimare
_ETA_MIN_S = 5.0          # e tempo minimo


def remaining_text(seconds: float) -> str:
    """Testo del tempo rimanente ("Circa 3 min rimanenti", "Meno di un minuto"…)."""
    if seconds < 10:
        return "Quasi finito"
    if seconds < 45:
        return "Meno di un minuto"
    if seconds < 90:
        return "Circa un minuto rimanente"
    return f"Circa {round(seconds / 60)} min rimanenti"


class RemainingEstimate:
    """Stima del tempo rimanente dalla velocità della trascrizione vera e propria."""

    def __init__(self):
        self._start: Optional[tuple] = None     # (istante, avanzamento) a inizio trascrizione
        self._estimate: Optional[tuple] = None  # (istante, secondi rimanenti)

    def update(self, pct: float, now: float) -> Optional[float]:
        """Nuovo avanzamento; restituisce i secondi rimanenti o None se è presto."""
        if pct < _ETA_START:
            return None
        if self._start is None:
            self._start = (now, pct)
            return None
        t0, p0 = self._start
        done, elapsed = pct - p0, now - t0
        if done < _ETA_MIN_SPAN or elapsed < _ETA_MIN_S:
            return None
        left = max(0.0, (_ETA_END - min(pct, _ETA_END)) * elapsed / done)
        self._estimate = (now, left)
        return left

    def remaining(self, now: float) -> Optional[float]:
        """Ultima stima, scalata del tempo passato da allora (mai negativa)."""
        if self._estimate is None:
            return None
        t, left = self._estimate
        return max(0.0, left - (now - t))


def elapsed_text(seconds: float, prefix: str = "In corso da") -> str:
    """Tempo trascorso: "In corso da 0:42", "Completata in 1:05:30"."""
    total = int(max(0.0, seconds))
    h, rest = divmod(total, 3600)
    m, sec = divmod(rest, 60)
    clock = f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
    return f"{prefix} {clock}"


def audio_clock(seconds: float) -> str:
    """Posizione nell'audio per le frasi nel log: "01:23" o "1:02:03"."""
    total = int(max(0.0, seconds))
    h, rest = divmod(total, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


class SmoothProgress:
    """Percentuale che sale anche tra un aggiornamento del motore e l'altro.

    Whisper riporta l'avanzamento solo a fine di ogni blocco di 30 s di audio: su file
    lunghi la percentuale restava ferma minuti interi. Tra due aggiornamenti la si fa
    salire alla velocità misurata, ma al massimo di quanto è salito il salto più grande
    visto finora (circa un blocco) e mai oltre il 90 %: se il blocco tarda, si ferma lì
    e aspetta il valore vero. Non scende mai.
    """

    def __init__(self):
        self._start: Optional[tuple] = None     # (istante, avanzamento) a inizio trascrizione
        self._real: Optional[tuple] = None      # (istante, ultimo avanzamento vero)
        self._step = 0.0                        # salto vero più grande nella trascrizione
        self._shown = 0.0

    def real(self, pct: float, now: float) -> float:
        """Nuovo avanzamento dal motore; restituisce la percentuale da mostrare."""
        if self._real is not None and _ETA_START <= self._real[1] < pct <= _ETA_END:
            self._step = max(self._step, pct - self._real[1])
        if pct >= _ETA_START and self._start is None:
            self._start = (now, pct)
        self._real = (now, pct)
        return self.shown(now)

    def shown(self, now: float) -> float:
        if self._real is None:
            return self._shown
        t, pct = self._real
        value = pct
        if self._start is not None and self._step > 0 and _ETA_START <= pct < _ETA_END:
            t0, p0 = self._start
            if t > t0 and pct > p0:
                rate = (pct - p0) / (t - t0)
                cap = min(pct + self._step, _ETA_END - 0.005)
                value = min(pct + rate * (now - t), cap)
        self._shown = max(self._shown, value)
        return self._shown


def _clock() -> str:
    """Orario locale HH:MM:SS per le righe del log."""
    return time.strftime("%H:%M:%S")


class _Spinner(QWidget):
    """Spinner circolare animato (come .spinner del design Studio)."""

    def __init__(self, size: int = 16, parent=None):
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


class _PhaseRow(QWidget):
    """Riga di una fase: indicatore (fatto / in corso / in attesa), nome, ultimo dettaglio."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._state = _PH_PENDING
        self.setMinimumHeight(max(36, self.fontMetrics().height() + 16))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self._mark = QLabel()
        self._mark.setFixedSize(16, 16)
        lay.addWidget(self._mark)
        self._spinner = _Spinner(16)
        self._spinner.hide()
        lay.addWidget(self._spinner)
        self._name = QLabel(name)
        lay.addWidget(self._name)
        self._detail = ElidedLabel("", Qt.ElideRight)
        self._detail.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self._detail, 1)
        self.apply_palette()

    def state(self) -> str:
        return self._state

    def detail(self) -> str:
        return self._detail.full_text()

    def set_state(self, state: str):
        self._state = state
        self.apply_palette()

    def set_detail(self, text: str):
        self._detail.setText(text)

    def apply_palette(self):
        c = theme.c
        st = self._state
        self._spinner.setVisible(st == _PH_ACTIVE)
        self._mark.setVisible(st != _PH_ACTIVE)
        if st == _PH_DONE:
            self._mark.setPixmap(icons.pixmap("check", theme.qcolor("dim"), 16))
        elif st == _PH_PENDING:
            from PySide6.QtGui import QPixmap
            pix = QPixmap(32, 32)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            from PySide6.QtGui import QPen
            p.setPen(QPen(theme.qcolor("line"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(2, 2, 28, 28)
            p.end()
            pix.setDevicePixelRatio(2.0)
            self._mark.setPixmap(pix)
        name_color = {_PH_DONE: c("dim"), _PH_ACTIVE: c("text"), _PH_PENDING: c("label")}[st]
        weight = 500 if st == _PH_ACTIVE else 400
        self._name.setStyleSheet(
            f"font-size: 13px; font-weight: {weight}; color: {name_color};"
            " background: transparent;"
        )
        det = c("acc") if st == _PH_ACTIVE else c("dim")
        self._detail.setStyleSheet(
            f"font-size: 12px; color: {det}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )


class ProgressWidget(QWidget):
    """Schermata di trascrizione in corso."""

    transcription_done      = Signal(list, str)   # segments, source_path
    transcription_cancelled = Signal()
    transcription_failed    = Signal(str)          # error message

    _LOG_W = 520

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentPanel")

        self._thread: QThread | None = None
        self._worker: TranscriptionWorker | None = None
        self._source_path: str = ""
        self._phase_idx = -1          # fase corrente (-1 = non iniziata, 5 = tutte fatte)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Colonna sinistra ──────────────────────────────────────────────────
        left_w = QWidget()
        left_w.setStyleSheet("background: transparent;")
        root = QVBoxLayout(left_w)
        root.setContentsMargins(40, 36, 40, 36)
        root.setSpacing(0)
        outer.addWidget(left_w, 1)

        # File: icona, nome, dimensione · estensione, impostazioni a destra
        file_row = QHBoxLayout()
        file_row.setSpacing(12)
        self._file_icon = QLabel()
        self._file_icon.setFixedSize(20, 20)
        file_row.addWidget(self._file_icon)
        self.file_lbl = ElidedLabel("—")
        file_row.addWidget(self.file_lbl, 3)
        self._file_meta = QLabel("")
        file_row.addWidget(self._file_meta)
        self.cfg_lbl = ElidedLabel("—", Qt.ElideRight)
        self.cfg_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        file_row.addWidget(self.cfg_lbl, 4)
        root.addLayout(file_row)
        root.addSpacing(56)

        # Percentuale grande + titolo e stato
        pct_row = QHBoxLayout()
        pct_row.setSpacing(18)
        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setTextFormat(Qt.RichText)
        pct_row.addWidget(self.pct_lbl, 0, Qt.AlignBottom)
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        self.title_lbl = QLabel("Trascrizione in corso…")
        title_col.addWidget(self.title_lbl)
        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        title_col.addWidget(self.status_lbl)
        time_row = QHBoxLayout()
        time_row.setSpacing(16)
        self.elapsed_lbl = QLabel("")           # "In corso da 2:15": scorre ogni secondo
        time_row.addWidget(self.elapsed_lbl)
        self.eta_lbl = QLabel("")
        self.eta_lbl.setObjectName("etaLabel")
        time_row.addWidget(self.eta_lbl)
        time_row.addStretch(1)
        title_col.addLayout(time_row)
        self._eta = RemainingEstimate()
        self._smooth = SmoothProgress()
        self._t_start: Optional[float] = None
        # Ogni secondo: tempo trascorso, percentuale tra un blocco e l'altro, stima
        self._eta_timer = QTimer(self)
        self._eta_timer.setInterval(1000)
        self._eta_timer.timeout.connect(self._tick)
        pct_row.addLayout(title_col, 1)
        root.addLayout(pct_row)
        root.addSpacing(22)

        # Barra piatta da 4 px
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        root.addWidget(self.progress)
        root.addSpacing(44)

        # Elenco delle fasi
        phases_w = QWidget()
        phases_w.setMaximumWidth(640)
        pl = QVBoxLayout(phases_w)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self._phase_rows = [_PhaseRow(name) for name in PHASES]
        for row in self._phase_rows:
            pl.addWidget(row)
        root.addWidget(phases_w)
        root.addStretch(1)

        # Interrompi + nota
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.stop_btn = QPushButton("Interrompi")
        self._stop_icon = icons.bind_icon(self.stop_btn, "stop", "err", 14)
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setProperty("stopButton", True)
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setMinimumWidth(190)
        self.stop_btn.setToolTip("Interrompi la trascrizione  (Esc)")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        btn_lay = QHBoxLayout(self.stop_btn)
        btn_lay.setContentsMargins(0, 0, 14, 0)
        btn_lay.setSpacing(0)
        btn_lay.addStretch(1)
        self._stop_kbd = QLabel("Esc")
        self._stop_kbd.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        btn_lay.addWidget(self._stop_kbd)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # ── Colonna destra: Log (520 px) ──────────────────────────────────────
        self._log_panel = QFrame()
        self._log_panel.setObjectName("logPanel")
        self._log_panel.setFixedWidth(self._LOG_W)
        ll = QVBoxLayout(self._log_panel)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        head = QFrame()
        head.setObjectName("logHead")
        head.setFixedHeight(44)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setAlignment(Qt.AlignVCenter)
        self._log_header = QLabel("Log")
        hl.addWidget(self._log_header)
        hl.addStretch(1)
        self.copy_log_btn = QPushButton("Copia log")
        self.copy_log_btn.setObjectName("secondary")
        icons.bind_icon(self.copy_log_btn, "copy", "text")
        self.copy_log_btn.setProperty("compact", True)
        self.copy_log_btn.setFixedHeight(28)
        self.copy_log_btn.setToolTip(
            f"Copia il log negli appunti (log completo in {platform_support.app_cache_dir()})"
        )
        self.copy_log_btn.clicked.connect(self._copy_log)
        hl.addWidget(self.copy_log_btn)
        ll.addWidget(head)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFrameShape(QFrame.NoFrame)
        self.log.setPlaceholderText("Il log apparirà qui…")
        self.log.setAccessibleName("Log della trascrizione")
        ll.addWidget(self.log, 1)
        outer.addWidget(self._log_panel)

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

        # Esc = Interrompi (con conferma), solo quando questa schermata è visibile
        sc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self._on_escape)

    # ---- Helpers UI ----

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.qcolor("bg"))
        p.end()

    def phase_states(self) -> list:
        """Stato di ciascuna fase: "done" / "active" / "pending" (per i test)."""
        return [r.state() for r in self._phase_rows]

    def phase_details(self) -> list:
        return [r.detail() for r in self._phase_rows]

    def _set_pct(self, pct: int):
        c = theme.c
        self.pct_lbl.setText(
            f"<span style=\"font-size: 88px; font-weight: 500;\">{pct}</span>"
            f"<span style=\"font-size: 40px; color: {c('dim')};\">%</span>"
        )

    def _reset_phases(self):
        self._phase_idx = -1
        for row in self._phase_rows:
            row.set_detail("")
            row.set_state(_PH_PENDING)

    def _advance_phase(self, msg: str):
        """Aggiorna le fasi dal messaggio di stato (solo in avanti, mai errori)."""
        idx = phase_for_status(msg)
        if idx is None:
            return
        if idx > self._phase_idx:
            self._phase_idx = idx
        for i, row in enumerate(self._phase_rows):
            want = (_PH_DONE if i < self._phase_idx else
                    _PH_ACTIVE if i == self._phase_idx else _PH_PENDING)
            if row.state() != want:
                row.set_state(want)
        if idx == self._phase_idx or idx < self._phase_idx:
            row = self._phase_rows[idx]
            # la percentuale è già in alto: non sovrascrive il dettaglio della fase
            if not (idx == 2 and msg.lower().startswith("trascrizione in corso")
                    and row.detail()):
                row.set_detail(msg)

    def _finish_phases(self):
        self._phase_idx = len(PHASES)
        for row in self._phase_rows:
            row.set_state(_PH_DONE)

    def _freeze_phases(self):
        """Dopo errore o annullamento nessuna fase resta "in corso"."""
        for row in self._phase_rows:
            if row.state() == _PH_ACTIVE:
                row.set_state(_PH_PENDING)

    def _append_log(self, msg: str, color: str = "dim"):
        """Aggiunge una riga "HH:MM:SS  messaggio" (orario in colore etichetta)."""
        cur = QTextCursor(self.log.document())
        cur.movePosition(QTextCursor.End)
        if not self.log.document().isEmpty():
            cur.insertBlock()
        t_fmt = QTextCharFormat()
        t_fmt.setForeground(theme.qcolor("label"))
        m_fmt = QTextCharFormat()
        m_fmt.setForeground(theme.qcolor(color))
        cur.insertText(_clock() + "  ", t_fmt)
        cur.insertText(msg, m_fmt)
        self.log.setTextCursor(cur)
        self.log.ensureCursorVisible()

    # ---- API pubblica ----

    def start(self, source_path: str, settings: dict, config=None):
        """Avvia trascrizione. Chiamato da MainWindow dopo HomeWidget.start_requested.

        ``config`` (TranscriptionConfig) porta i parametri avanzati; None = predefiniti.
        """
        if self._thread is not None:
            return   # già in corso — non avviare due volte

        self._source_path = source_path

        # Aggiorna riepilogo
        self.title_lbl.setText("Trascrizione in corso…")
        self.file_lbl.setText(Path(source_path).name)
        self.file_lbl.set_full_tooltip(source_path)
        ext = Path(source_path).suffix.upper().lstrip(".")
        size = fmt_size(source_path).replace(".", ",")
        self._file_meta.setText(f"{size} · {ext}" if size else ext)
        self._file_icon.setPixmap(icons.pixmap(
            "audio" if Path(source_path).suffix.lower() in SUPPORTED_AUDIO_EXTS else "video",
            theme.qcolor("dim"), 20))
        lang = _LANG_NAMES.get(settings.get("language"), str(settings.get("language") or "—"))
        parts = [
            str(settings.get("model_size", "—")),
            lang,
            f"VAD {'attivo' if settings.get('vad_filter') else 'disattivo'}",
            f"Beam {settings.get('beam_size', 5)}",
        ]
        if settings.get("high_accuracy"):
            parts.insert(3, "alta precisione")
        self.cfg_lbl.setText("  ·  ".join(parts))
        self.log.clear()
        self.progress.setValue(0)
        self._set_pct(0)
        self._reset_phases()
        self.status_lbl.setText("")
        self._reset_eta()
        self._t_start = time.monotonic()
        self._tick()
        self._eta_timer.start()
        self._stop_kbd.setVisible(True)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("Interrompi")
        self._stop_icon.set_icon("stop", "err")
        self.stop_btn.setToolTip("Interrompi la trascrizione  (Esc)")
        if self.stop_btn.objectName() != "danger":
            # dopo un errore il bottone era diventato "primary" (torna alla home)
            self.stop_btn.setObjectName("danger")
            self.stop_btn.style().unpolish(self.stop_btn)
            self.stop_btn.style().polish(self.stop_btn)

        # Avvia worker
        params = {"input_path": source_path, **settings}
        if config is not None:
            params["config"] = config
        self._thread = QThread(self)
        self._worker = TranscriptionWorker(params)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self._on_status)
        self._worker.progress.connect(self._on_progress)
        self._worker.text.connect(self._on_text)
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
                 (w.text, self._on_text),
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
        t.setParent(None)   # niente parent: il teardown di Qt non lo distrugge mentre gira
        _DETACHED.append((t, w))
        t.quit()   # ha effetto quando worker.run ritorna al loop del thread
        t.finished.connect(lambda: _release_detached(t))

    def is_running(self) -> bool:
        return self._thread is not None

    # ---- Slots worker ----

    def _on_status(self, msg: str):
        self.status_lbl.setText(msg)
        self._append_log(msg)
        self._advance_phase(msg)

    def _on_progress(self, pct: float):
        now = time.monotonic()
        self._show_progress(self._smooth.real(pct, now))
        if self._eta.update(pct, now) is not None:
            self._show_eta(now)

    def _on_text(self, start: float, text: str):
        """Frase appena trascritta: nel log, col punto dell'audio (si vede che lavora)."""
        self._append_log(f"{audio_clock(start)}  {text}", "text")

    def _show_progress(self, pct: float):
        self.progress.setValue(int(pct * 1000))
        self._set_pct(int(pct * 100))

    def _tick(self):
        now = time.monotonic()
        if self._t_start is not None:
            self.elapsed_lbl.setText(elapsed_text(now - self._t_start))
        self._show_progress(self._smooth.shown(now))
        self._show_eta(now)

    def _stop_clock(self, prefix: Optional[str] = None):
        """Ferma il tempo trascorso: con ``prefix`` resta la durata, altrimenti sparisce."""
        if self._t_start is not None and prefix:
            self.elapsed_lbl.setText(elapsed_text(time.monotonic() - self._t_start, prefix))
        else:
            self.elapsed_lbl.setText("")
        self._t_start = None

    def _show_eta(self, now: Optional[float] = None):
        left = self._eta.remaining(time.monotonic() if now is None else now)
        self.eta_lbl.setText("" if left is None else remaining_text(left))

    def _reset_eta(self):
        """Ferma il conteggio (fine, errore, annullamento o nuova trascrizione)."""
        self._eta = RemainingEstimate()
        self._smooth = SmoothProgress()
        self._eta_timer.stop()
        self.eta_lbl.setText("")

    def _on_finished(self, segments: list):
        self.progress.setValue(1000)
        self._set_pct(100)
        self._finish_phases()
        n = len(segments)
        self.title_lbl.setText(f"Completato — {n} sottotitoli trovati")
        self.status_lbl.setText("Trascrizione completata")
        self._stop_clock("Completata in")
        self._reset_eta()
        self._append_log(f"--- Completato: {n} sottotitoli ---")
        self.stop_btn.setEnabled(False)
        self.transcription_done.emit(segments, self._source_path)

    def _on_failed(self, err: str):
        self._freeze_phases()
        self.title_lbl.setText("Errore trascrizione")
        self.status_lbl.setText(f"Errore: {err}")
        self._stop_clock()
        self._reset_eta()
        self._append_log(f"ERRORE: {err}")
        self._stop_kbd.setVisible(False)
        self.stop_btn.setText("Torna alla Home")
        self._stop_icon.set_icon(None)
        self.stop_btn.setToolTip("Torna alla schermata iniziale")
        self.stop_btn.setObjectName("primary")
        self.stop_btn.style().unpolish(self.stop_btn)
        self.stop_btn.style().polish(self.stop_btn)
        self.transcription_failed.emit(err)

    def _on_cancelled(self):
        self._freeze_phases()
        self.progress.setValue(0)
        self._set_pct(0)
        self.title_lbl.setText("Trascrizione annullata")
        self.status_lbl.setText("Annullata")
        self._stop_clock()
        self._reset_eta()
        self._append_log("--- Annullata ---")
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
        c = theme.c
        self._file_icon.setStyleSheet("background: transparent;")
        self._file_icon.setPixmap(icons.pixmap(
            "audio" if Path(self._source_path).suffix.lower() in SUPPORTED_AUDIO_EXTS
            else "video", theme.qcolor("dim"), 20))
        self.file_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 500; color: {c('text')}; background: transparent;"
        )
        mono = f"font-size: 12px; color: {c('dim')}; background: transparent;" \
               f" font-family: {theme.FONT_MONO};"
        self._file_meta.setStyleSheet(mono)
        self.cfg_lbl.setStyleSheet(mono)
        self.pct_lbl.setStyleSheet(
            f"color: {c('text')}; background: transparent; font-family: {theme.FONT_MONO};"
        )
        self._set_pct(self.progress.value() // 10)
        self.title_lbl.setStyleSheet(
            f"font-size: 20px; font-weight: 500; color: {c('text')}; background: transparent;"
        )
        self.status_lbl.setStyleSheet(
            f"font-size: 13px; color: {c('dim')}; background: transparent;"
        )
        for lbl in (self.eta_lbl, self.elapsed_lbl):
            lbl.setStyleSheet(
                f"font-size: 13px; color: {c('dim')}; background: transparent;"
                f" font-family: {theme.FONT_MONO};")
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: {c('line')}; border: none; border-radius: 0; }}"
            f"QProgressBar::chunk {{ background: {c('acc')}; border-radius: 0; }}"
        )
        for row in self._phase_rows:
            row.apply_palette()
        self._stop_kbd.setStyleSheet(
            f"font-size: 11px; color: {c('err')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._log_panel.setStyleSheet(
            f"QFrame#logPanel {{ background: {c('panel')}; border: none;"
            f" border-left: 1px solid {c('line')}; }}"
            f"QFrame#logHead {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {c('line')}; }}"
        )
        self._log_header.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c('text')}; background: transparent;"
        )
        self.log.setStyleSheet(
            f"QPlainTextEdit {{ font-family: {theme.FONT_MONO}; font-size: 12px;"
            f" background: transparent; border: none; padding: 10px 16px; color: {c('dim')}; }}"
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
            t.setParent(None)   # niente parent: il teardown di Qt non lo distrugge mentre gira
            _DETACHED.append((t, w))
            t.finished.connect(lambda: _release_detached(t))
            return
        t.deleteLater()
        if w:
            w.deleteLater()
