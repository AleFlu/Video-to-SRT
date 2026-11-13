"""
waveform_widget.py — Widget forma d'onda audio con overlay dei sottotitoli.

Implementazione zero-deps-extra con QWidget + paintEvent:
  - Carica il WAV 16 kHz prodotto da engine.preprocess_audio (o il file
    originale se già WAV/MP3 supportato da soundfile) in un thread
    separato per non bloccare la UI.
  - Pre-calcola i peak (min/max per pixel-bucket) per un rendering veloce.
  - Disegna la finestra visibile con zoom/pan orizzontale.
  - Sovrappone i sottotitoli come blocchi colorati (verde/giallo/rosso).
  - Mostra il playhead verticale mobile.
  - Click → seek; drag → pan; scroll verticale → zoom.
  - Blocco sottotitolo cliccato → emette subtitle_clicked(row: int).

Dipendenze extra usate internamente (già presenti nell'ambiente):
  numpy, soundfile (soundfile è incluso da faster-whisper/onnxruntime).
  Se soundfile non è disponibile, il widget mostra uno sfondo neutro senza crash.
"""

from __future__ import annotations

import threading
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QRect, QPoint, QPointF, QTimer, QThread, QObject
from PySide6.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QBrush, QFont, QFontMetrics
)
from PySide6.QtWidgets import QWidget, QSizePolicy

from core.subtitle_model import Subtitle
from ui import theme


# -----------------------------------------------------------------------
# Colori — derivati dal tema corrente (theme.c) ad ogni paint.
# -----------------------------------------------------------------------

def _sev_qcolor(token: str, alpha: int) -> QColor:
    col = QColor(theme.c(token))
    col.setAlpha(alpha)
    return col


# -----------------------------------------------------------------------
# Worker per il caricamento audio in background
# -----------------------------------------------------------------------

class _AudioLoaderSignals(QObject):
    done = Signal(object, int)   # (peaks_array_or_None, sample_rate)
    error = Signal(str)


class _AudioLoader(threading.Thread):
    """Carica il file audio e pre-calcola i peak in un thread di sistema."""

    def __init__(self, file_path: str, pixels_hint: int = 4000, generation: int = 0):
        super().__init__(daemon=True)
        self.file_path = file_path
        self.pixels_hint = max(1000, pixels_hint)
        self.generation = generation
        self.signals = _AudioLoaderSignals()

    def run(self):
        try:
            import numpy as np
            try:
                import soundfile as sf
                data, sr = sf.read(self.file_path, dtype="float32", always_2d=False)
            except Exception:
                # Fallback su scipy se soundfile non è disponibile
                from scipy.io import wavfile
                sr, data = wavfile.read(self.file_path)
                data = data.astype("float32")
                if data.max() > 1.0:
                    data /= 32768.0

            # Mono
            if data.ndim > 1:
                data = data.mean(axis=1)

            # Pre-calcola peak per bucket
            n = len(data)
            bucket = max(1, n // self.pixels_hint)
            n_buckets = n // bucket
            trimmed = data[:n_buckets * bucket].reshape(n_buckets, bucket)
            peaks_max = trimmed.max(axis=1)
            peaks_min = trimmed.min(axis=1)
            # Normalizza in [-1, 1] rispetto al massimo assoluto
            peak_abs = max(np.abs(peaks_max).max(), np.abs(peaks_min).max(), 1e-6)
            peaks_max = peaks_max / peak_abs
            peaks_min = peaks_min / peak_abs

            # (n_buckets, 2) → peaks_min, peaks_max
            peaks = np.stack([peaks_min, peaks_max], axis=1)
            self.signals.done.emit(peaks, sr)

        except ImportError as e:
            self.signals.error.emit(f"numpy/soundfile non disponibili: {e}")
        except Exception as e:
            self.signals.error.emit(str(e))


# -----------------------------------------------------------------------
# Widget principale
# -----------------------------------------------------------------------

class WaveformWidget(QWidget):
    """
    Widget forma d'onda interattivo.

    Segnali:
        seek_requested(ms: int)     — l'utente ha cliccato/trascinato per cercare
        subtitle_clicked(row: int)  — l'utente ha cliccato un blocco sottotitolo
    """

    seek_requested    = Signal(int)
    subtitle_clicked  = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("waveformWidget")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(80)

        # Dati audio
        self._peaks = None          # np.ndarray (n, 2) o None
        self._sample_rate: int = 16000
        self._duration_ms: int = 0
        self._loading: bool = False

        # Sottotitoli
        self._subtitles: List[Subtitle] = []
        self._severity: List[str] = []   # "ok" | "warning" | "error" per ogni sub
        self._selected_row: int = -1

        # Stato player
        self._playhead_ms: int = 0

        # Vista (zoom/pan): intervallo visibile in ms
        self._view_start_ms: float = 0.0
        self._view_end_ms:   float = 0.0    # 0 = non ancora settato

        # Stato drag
        self._dragging: bool = False
        self._drag_start_x: int = 0
        self._drag_start_view: float = 0.0

        # Messaggio di stato
        self._status_msg: str = "Nessun file caricato"

        # Generazione per invalidare i loader obsoleti
        self._load_generation: int = 0

        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _name=None):
        self.update()

    # ----------------------------------------------------------------
    # API pubblica
    # ----------------------------------------------------------------

    def load_audio(self, file_path: str) -> None:
        """Carica il file audio in background e aggiorna la forma d'onda."""
        self._load_generation += 1
        gen = self._load_generation
        self._peaks = None
        self._loading = True
        self._status_msg = "Caricamento forma d'onda…"
        self.update()

        loader = _AudioLoader(file_path, pixels_hint=max(self.width() * 4, 4000),
                              generation=gen)
        # Usa lambda per catturare la generazione e ignorare i loader obsoleti
        loader.signals.done.connect(
            lambda peaks, sr, g=gen: self._on_audio_loaded(peaks, sr) if g == self._load_generation else None,
            Qt.ConnectionType.QueuedConnection
        )
        loader.signals.error.connect(
            lambda msg, g=gen: self._on_audio_error(msg) if g == self._load_generation else None,
            Qt.ConnectionType.QueuedConnection
        )
        loader.start()

    def set_duration(self, ms: int) -> None:
        """Imposta la durata totale (ricevuta da AudioPlayer.duration_changed)."""
        self._duration_ms = ms
        if self._view_end_ms == 0.0 or self._view_end_ms > ms:
            self._view_start_ms = 0.0
            self._view_end_ms = float(ms)
        self.update()

    def set_position(self, ms: int) -> None:
        """Aggiorna il playhead (ricevuto da AudioPlayer.position_changed)."""
        self._playhead_ms = ms
        self._auto_scroll()
        self.update()

    def set_subtitles(self, subtitles: List[Subtitle],
                      severity: List[str] | None = None) -> None:
        """
        Aggiorna la lista di sottotitoli da visualizzare come blocchi.
        `severity` è una lista parallela con valori "ok"/"warning"/"error".
        """
        self._subtitles = subtitles
        if severity is not None and len(severity) == len(subtitles):
            self._severity = severity
        else:
            self._severity = ["ok"] * len(subtitles)
        self.update()

    def set_selected_row(self, row: int) -> None:
        """Evidenzia il sottotitolo selezionato."""
        if self._selected_row != row:
            self._selected_row = row
            self.update()

    def reset(self) -> None:
        """Resetta tutto (nuovo file/progetto). Invalida anche i loader in corso."""
        self._load_generation += 1   # invalida qualsiasi loader pendente
        self._peaks = None
        self._loading = False
        self._duration_ms = 0
        self._playhead_ms = 0
        self._view_start_ms = 0.0
        self._view_end_ms = 0.0
        self._subtitles = []
        self._severity = []
        self._selected_row = -1
        self._status_msg = "Nessun file caricato"
        self.update()

    def zoom_to_subtitle(self, row: int, padding_ms: int = 2000) -> None:
        """Zoom sulla finestra del sottotitolo indicato."""
        if row < 0 or row >= len(self._subtitles):
            return
        sub = self._subtitles[row]
        start = sub.start * 1000 - padding_ms
        end = sub.end * 1000 + padding_ms
        self._view_start_ms = max(0.0, start)
        self._view_end_ms = min(float(self._duration_ms), end)
        self.update()

    # ----------------------------------------------------------------
    # Slot interni (loader)
    # ----------------------------------------------------------------

    def _on_audio_loaded(self, peaks, sr: int):
        self._peaks = peaks
        self._sample_rate = sr
        self._loading = False
        self._status_msg = ""
        # Imposta la vista completa se la durata è già nota
        if self._duration_ms > 0 and self._view_end_ms == 0.0:
            self._view_end_ms = float(self._duration_ms)
        elif self._peaks is not None:
            # Stima durata dai peak
            n = len(peaks)
            # campioni per bucket: supponiamo pixels_hint=4000
            bucket = max(1, int(sr * (self._duration_ms / 1000.0) / n)) if self._duration_ms > 0 else 1
            dur_s = n * bucket / sr
            self._duration_ms = int(dur_s * 1000)
            if self._view_end_ms == 0.0:
                self._view_end_ms = float(self._duration_ms)
        self.update()

    def _on_audio_error(self, msg: str):
        self._loading = False
        self._status_msg = f"Errore: {msg}"
        self.update()

    # ----------------------------------------------------------------
    # Rendering
    # ----------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()

        # Sfondo
        painter.fillRect(0, 0, w, h, QColor(theme.c("wave_bg")))

        if self._loading or self._peaks is None:
            self._draw_status(painter, w, h)
            if not self._loading:
                self._draw_subtitle_blocks(painter, w, h)
            self._draw_playhead(painter, w, h)
            self._draw_ticks(painter, w, h)
            return

        self._draw_waveform(painter, w, h)
        self._draw_subtitle_blocks(painter, w, h)
        self._draw_playhead(painter, w, h)
        self._draw_ticks(painter, w, h)

        painter.end()

    def _draw_status(self, painter: QPainter, w: int, h: int):
        if not self._status_msg:
            return
        painter.setPen(QColor(theme.c("muted")))
        painter.setFont(QFont("SF Pro Text", 11))
        painter.drawText(QRect(0, 0, w, h), Qt.AlignCenter, self._status_msg)

    def _draw_waveform(self, painter: QPainter, w: int, h: int):
        import numpy as np
        peaks = self._peaks
        if peaks is None:
            return

        view_start = self._view_start_ms
        view_end = self._view_end_ms
        if view_end <= view_start:
            return

        # Determina il range di bucket visibili
        total_dur_ms = self._duration_ms if self._duration_ms > 0 else (view_end - view_start)
        n = len(peaks)
        bucket_ms = total_dur_ms / n if n > 0 else 1.0

        b_start = int(view_start / bucket_ms)
        b_end   = int(view_end   / bucket_ms) + 1
        b_start = max(0, b_start)
        b_end   = min(n, b_end)

        visible_buckets = b_end - b_start
        if visible_buckets <= 0:
            return

        cy = h / 2.0
        half_h = cy * 0.88   # lascia un po' di margine

        path = QPainterPath()
        # Traccia il bordo superiore (max) da sx a dx, poi inferiore (min) da dx a sx
        xs = []
        y_maxs = []
        y_mins = []
        for i, b in enumerate(range(b_start, b_end)):
            frac = (b * bucket_ms - view_start) / (view_end - view_start)
            x = frac * w
            xs.append(x)
            y_maxs.append(cy - peaks[b, 1] * half_h)
            y_mins.append(cy - peaks[b, 0] * half_h)

        if not xs:
            return

        path.moveTo(xs[0], y_maxs[0])
        for x, y in zip(xs[1:], y_maxs[1:]):
            path.lineTo(x, y)
        for x, y in zip(reversed(xs), reversed(y_mins)):
            path.lineTo(x, y)
        path.closeSubpath()

        wave_fill = QColor(theme.c("wave_fill"))
        wave_border = QColor(theme.c("acc"))
        painter.fillPath(path, QBrush(wave_fill))
        painter.setPen(QPen(wave_border, 0.5))
        painter.drawPath(path)

    def _draw_subtitle_blocks(self, painter: QPainter, w: int, h: int):
        if not self._subtitles or self._duration_ms == 0:
            return

        view_start = self._view_start_ms
        view_end = self._view_end_ms
        if view_end <= view_start:
            return
        span = view_end - view_start

        block_h = max(16, h // 4)
        block_y = h - block_h - 2
        font = QFont("SF Pro Text", 9)
        painter.setFont(font)
        fm = QFontMetrics(font)

        for row, sub in enumerate(self._subtitles):
            sub_start_ms = sub.start * 1000.0
            sub_end_ms   = sub.end   * 1000.0

            # Clip alla vista
            if sub_end_ms < view_start or sub_start_ms > view_end:
                continue

            x1 = int((sub_start_ms - view_start) / span * w)
            x2 = int((sub_end_ms   - view_start) / span * w)
            x1 = max(0, x1)
            x2 = min(w, x2)
            if x2 - x1 < 1:
                continue

            # Colore per severity
            if row == self._selected_row:
                color = _sev_qcolor("acc", 160)
            elif row < len(self._severity):
                sev = self._severity[row]
                if sev == "error":
                    color = _sev_qcolor("err", 120)
                elif sev == "warning":
                    color = _sev_qcolor("warn", 120)
                else:
                    color = _sev_qcolor("ok", 120)
            else:
                color = _sev_qcolor("ok", 120)

            rect = QRect(x1, block_y, x2 - x1, block_h)
            painter.fillRect(rect, color)
            painter.setPen(QPen(QColor(255, 255, 255, 60), 1))
            painter.drawRect(rect)

            # Testo se c'è spazio
            if x2 - x1 > 20:
                label = sub.text.replace("\n", " ")
                elided = fm.elidedText(label, Qt.ElideRight, x2 - x1 - 4)
                painter.setPen(QColor(theme.c("text")))
                painter.drawText(QRect(x1 + 2, block_y + 1, x2 - x1 - 4, block_h - 2),
                                 Qt.AlignVCenter | Qt.AlignLeft, elided)

    def _draw_playhead(self, painter: QPainter, w: int, h: int):
        if self._duration_ms == 0:
            return
        view_start = self._view_start_ms
        view_end = self._view_end_ms
        if view_end <= view_start:
            return
        frac = (self._playhead_ms - view_start) / (view_end - view_start)
        if not (0.0 <= frac <= 1.0):
            return
        x = int(frac * w)
        playhead = QColor(theme.c("playhead"))
        painter.setPen(QPen(playhead, 2))
        painter.drawLine(x, 0, x, h)

        # Triangolino in cima
        path = QPainterPath()
        path.moveTo(x - 5, 0)
        path.lineTo(x + 5, 0)
        path.lineTo(x, 8)
        path.closeSubpath()
        painter.fillPath(path, playhead)

    def _draw_ticks(self, painter: QPainter, w: int, h: int):
        """Righello temporale: tick ogni N secondi."""
        view_start = self._view_start_ms
        view_end   = self._view_end_ms
        if view_end <= view_start or w == 0:
            return

        span_s = (view_end - view_start) / 1000.0
        # Scegli intervallo tick
        for interval_s in [0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300]:
            if span_s / interval_s <= w / 60:
                break

        tick_color = QColor(theme.c("faint"))
        tick_label = QColor(theme.c("muted"))
        font = QFont("SF Pro Mono", 8)
        painter.setFont(font)
        painter.setPen(tick_color)

        t = (int(view_start / (interval_s * 1000)) * interval_s * 1000)
        while t <= view_end:
            frac = (t - view_start) / (view_end - view_start)
            x = int(frac * w)
            painter.drawLine(x, 0, x, 8)
            # Label
            total_s = t / 1000.0
            m = int(total_s) // 60
            s = total_s % 60
            label = f"{m}:{s:04.1f}" if m > 0 else f"{s:.1f}s"
            painter.setPen(tick_label)
            painter.drawText(x + 2, 16, label)
            painter.setPen(tick_color)
            t += interval_s * 1000

    # ----------------------------------------------------------------
    # Mouse events
    # ----------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Controlla se ha cliccato un blocco sottotitolo
            row = self._row_at(event.position().x(), event.position().y())
            if row >= 0:
                self.subtitle_clicked.emit(row)
            else:
                # Seek
                ms = self._x_to_ms(event.position().x())
                if ms >= 0:
                    self.seek_requested.emit(int(ms))
            self._dragging = True
            self._drag_start_x = int(event.position().x())
            self._drag_start_view = self._view_start_ms

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.LeftButton):
            dx = int(event.position().x()) - self._drag_start_x
            span = self._view_end_ms - self._view_start_ms
            if self.width() > 0 and span > 0:
                delta_ms = -dx * span / self.width()
                new_start = self._drag_start_view + delta_ms
                new_start = max(0.0, min(float(self._duration_ms) - span, new_start))
                self._view_start_ms = new_start
                self._view_end_ms = new_start + span
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Se non è stato un drag significativo, fa seek
            if abs(int(event.position().x()) - self._drag_start_x) < 5:
                ms = self._x_to_ms(event.position().x())
                if ms >= 0:
                    self.seek_requested.emit(int(ms))
            self._dragging = False

    def wheelEvent(self, event):
        """Scroll verticale: zoom; scroll orizzontale: pan."""
        delta = event.angleDelta()
        span = self._view_end_ms - self._view_start_ms
        if span <= 0 or self._duration_ms == 0:
            return

        if abs(delta.y()) >= abs(delta.x()):
            # Zoom centrato sul cursore del mouse
            center_ms = self._x_to_ms(event.position().x())
            factor = 1.0 - delta.y() / 1200.0
            factor = max(0.1, min(10.0, factor))
            new_span = span * factor
            new_span = max(500.0, min(float(self._duration_ms), new_span))
            frac = (center_ms - self._view_start_ms) / span if span > 0 else 0.5
            new_start = center_ms - frac * new_span
        else:
            # Pan orizzontale
            new_span = span
            new_start = self._view_start_ms - delta.x() * span / 500.0

        new_start = max(0.0, min(float(self._duration_ms) - new_span, new_start))
        self._view_start_ms = new_start
        self._view_end_ms   = new_start + new_span
        self.update()
        event.accept()

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _x_to_ms(self, x: float) -> float:
        w = self.width()
        if w == 0:
            return -1.0
        span = self._view_end_ms - self._view_start_ms
        return self._view_start_ms + (x / w) * span

    def _row_at(self, x: float, y: float) -> int:
        """Ritorna l'indice del sottotitolo sotto (x, y) oppure -1."""
        h = self.height()
        block_h = max(16, h // 4)
        block_y = h - block_h - 2

        if y < block_y or y > h - 2:
            return -1

        ms = self._x_to_ms(x)
        for row, sub in enumerate(self._subtitles):
            if sub.start * 1000.0 <= ms <= sub.end * 1000.0:
                return row
        return -1

    def _auto_scroll(self):
        """
        Se il playhead esce dalla finestra visibile, sposta la vista
        per tenerlo a circa il 20% da sinistra.
        """
        if self._duration_ms == 0 or self._view_end_ms == 0.0:
            return
        span = self._view_end_ms - self._view_start_ms
        margin = span * 0.15
        if self._playhead_ms < self._view_start_ms + margin or \
           self._playhead_ms > self._view_end_ms - margin:
            new_start = self._playhead_ms - span * 0.2
            new_start = max(0.0, min(float(self._duration_ms) - span, new_start))
            self._view_start_ms = new_start
            self._view_end_ms   = new_start + span
