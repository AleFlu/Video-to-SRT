"""
waveform_widget.py — Widget forma d'onda audio con overlay dei sottotitoli.

  - Caricamento in un thread separato: il file viene letto A BLOCCHI
    (`soundfile.blocks`, oppure lo stdout PCM di ffmpeg per i formati che
    soundfile non legge) e ridotto a picchi min/max per bucket. La memoria
    usata è limitata (≤ 2 × TARGET_BUCKETS bucket) qualunque sia la durata.
  - Rendering: lo strato statico (sfondo, forma d'onda, blocchi sottotitolo,
    righello) è in cache in una QPixmap ridisegnata solo su resize, zoom/pan,
    cambio tema o sottotitoli; a ogni tick del player si ridisegna solo il playhead.
  - Interazione: click → seek (o selezione del blocco sottotitolo); trascinamento →
    pan (senza spostare il playhead); rotella verticale → zoom, orizzontale → pan.
"""

from __future__ import annotations

import bisect
import logging
import math
import subprocess
import threading
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QRect, QRectF, QPointF, QObject
from PySide6.QtGui import (
    QPainter, QPainterPath, QPen, QBrush, QFont, QFontMetrics, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QWidget, QSizePolicy

from core.subtitle_model import Subtitle
from ui import theme
import platform_support

logger = logging.getLogger(__name__)

# Numero di bucket min/max a cui si punta (la memoria resta ≤ 2× questo valore)
TARGET_BUCKETS = 16384
# Campioni letti per blocco (memoria transitoria del loader)
_BLOCK_FRAMES = 65536
# Frequenza del PCM chiesto a ffmpeg nel fallback (basta per i picchi)
_FFMPEG_RATE = 8000
# Soglia (px) sotto cui un trascinamento è considerato un click
_CLICK_SLOP = 5


# -----------------------------------------------------------------------
# Riduzione a picchi
# -----------------------------------------------------------------------

class PeakAccumulator:
    """
    Riduce un flusso di campioni mono in coppie (min, max) per bucket.

    Il numero di bucket resta ≤ 2 × target: quando lo supera, i bucket vengono
    fusi a coppie e la loro dimensione raddoppia (funziona anche se la durata
    totale non è nota in anticipo).
    """

    def __init__(self, target: int = TARGET_BUCKETS, bucket_size: int = 1):
        import numpy as np
        self._np = np
        self.target = max(16, int(target))
        self.bucket = max(1, int(bucket_size))
        self.frames = 0
        self._mins: list = []
        self._maxs: list = []
        self._count = 0
        # bucket parziale (aggregato): campioni accumulati e loro min/max
        self._pc = 0
        self._pmin = 0.0
        self._pmax = 0.0

    @property
    def bucket_count(self) -> int:
        return self._count + (1 if self._pc else 0)

    def add(self, samples) -> None:
        np = self._np
        x = np.asarray(samples, dtype=np.float32).ravel()
        if x.size == 0:
            return
        self.frames += int(x.size)
        i = 0
        if self._pc:
            need = self.bucket - self._pc
            seg = x[:need]
            self._pmin = min(self._pmin, float(seg.min()))
            self._pmax = max(self._pmax, float(seg.max()))
            self._pc += int(seg.size)
            i = int(seg.size)
            if self._pc == self.bucket:
                self._append(np.array([self._pmin], np.float32),
                             np.array([self._pmax], np.float32))
                self._pc = 0
        rest = x[i:]
        n = (rest.size // self.bucket) * self.bucket
        if n:
            r = rest[:n].reshape(-1, self.bucket)
            self._append(r.min(axis=1), r.max(axis=1))
        tail = rest[n:]
        if tail.size:
            self._pmin = float(tail.min())
            self._pmax = float(tail.max())
            self._pc = int(tail.size)

    def _append(self, mins, maxs) -> None:
        self._mins.append(mins)
        self._maxs.append(maxs)
        self._count += int(mins.size)
        while self._count + (1 if self._pc else 0) > 2 * self.target:
            self._merge()

    def _merge(self) -> None:
        np = self._np
        m = np.concatenate(self._mins)
        mx = np.concatenate(self._maxs)
        if m.size % 2:
            # l'ultimo bucket pieno diventa (con l'eventuale parziale) il nuovo parziale
            last_min, last_max = float(m[-1]), float(mx[-1])
            if self._pc:
                last_min = min(last_min, self._pmin)
                last_max = max(last_max, self._pmax)
            self._pmin, self._pmax = last_min, last_max
            self._pc = self.bucket + self._pc
            m, mx = m[:-1], mx[:-1]
        m2 = m.reshape(-1, 2).min(axis=1)
        mx2 = mx.reshape(-1, 2).max(axis=1)
        self.bucket *= 2
        self._mins, self._maxs = [m2], [mx2]
        self._count = int(m2.size)

    def result(self) -> Tuple[object, object, int]:
        """(mins, maxs, campioni_per_bucket), normalizzati in [-1, 1]."""
        np = self._np
        mins = list(self._mins)
        maxs = list(self._maxs)
        if self._pc:
            mins.append(np.array([self._pmin], np.float32))
            maxs.append(np.array([self._pmax], np.float32))
        if not mins:
            empty = np.zeros(0, np.float32)
            return empty, empty, self.bucket
        m = np.concatenate(mins)
        mx = np.concatenate(maxs)
        peak = max(float(np.abs(m).max()), float(np.abs(mx).max()), 1e-6)
        return (m / peak).astype(np.float32), (mx / peak).astype(np.float32), self.bucket


def compute_peaks(file_path: str, target: int = TARGET_BUCKETS,
                  cancel: Optional[threading.Event] = None):
    """
    Legge `file_path` a blocchi e ritorna (mins, maxs, bucket_size, sample_rate, frames).
    Prima prova soundfile; se il formato non è leggibile ripiega su ffmpeg (PCM su stdout).
    """
    try:
        import soundfile as sf
    except ImportError:
        sf = None
        logger.info("soundfile non disponibile: forma d'onda via ffmpeg")
    try:
        if sf is None:
            raise RuntimeError("soundfile assente")
        info = sf.info(file_path)
        sr = int(info.samplerate)
        frames = int(info.frames) if info.frames and info.frames > 0 else 0
        bucket = max(1, math.ceil(frames / target)) if frames else max(1, sr // 200)
        acc = PeakAccumulator(target, bucket)
        for block in sf.blocks(file_path, blocksize=_BLOCK_FRAMES, dtype="float32",
                               always_2d=True):
            if cancel is not None and cancel.is_set():
                return None
            acc.add(block.mean(axis=1) if block.shape[1] > 1 else block[:, 0])
        mins, maxs, bsize = acc.result()
        return mins, maxs, bsize, sr, acc.frames
    except Exception:  # noqa: BLE001 — formato non supportato da libsndfile
        logger.info("soundfile non legge %s: provo ffmpeg", file_path)
    return _compute_peaks_ffmpeg(file_path, target, cancel)


def _compute_peaks_ffmpeg(file_path: str, target: int, cancel: Optional[threading.Event]):
    import numpy as np
    try:
        from engine import get_bundled_ffmpeg
        ffmpeg = get_bundled_ffmpeg() or platform_support.ffmpeg_executable_name()
    except Exception:  # noqa: BLE001
        ffmpeg = platform_support.ffmpeg_executable_name()
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-i", file_path, "-vn", "-ac", "1",
           "-ar", str(_FFMPEG_RATE), "-f", "s16le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            **platform_support.subprocess_kwargs())
    acc = PeakAccumulator(target, max(1, _FFMPEG_RATE // 200))
    try:
        leftover = b""
        while True:
            if cancel is not None and cancel.is_set():
                proc.kill()
                return None
            chunk = proc.stdout.read(_BLOCK_FRAMES * 2)
            if not chunk:
                break
            data = leftover + chunk
            usable = len(data) - (len(data) % 2)
            leftover = data[usable:]
            acc.add(np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0)
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode("utf-8", "replace").strip()
        proc.stderr.close()
        proc.wait()
    if acc.frames == 0:
        raise RuntimeError(err.splitlines()[-1] if err else "nessun audio decodificabile")
    mins, maxs, bsize = acc.result()
    return mins, maxs, bsize, _FFMPEG_RATE, acc.frames


# -----------------------------------------------------------------------
# Worker per il caricamento audio in background
# -----------------------------------------------------------------------

class _AudioLoaderSignals(QObject):
    done = Signal(int, object)   # (generazione, risultato di compute_peaks)
    error = Signal(int, str)     # (generazione, messaggio)


class _AudioLoader(threading.Thread):
    """Calcola i picchi in un thread di sistema (nessun oggetto Qt-widget toccato)."""

    def __init__(self, file_path: str, generation: int, target: int = TARGET_BUCKETS):
        super().__init__(daemon=True)
        self.file_path = file_path
        self.generation = generation
        self.target = target
        self.cancel = threading.Event()
        self.signals = _AudioLoaderSignals()

    def run(self):
        try:
            result = compute_peaks(self.file_path, self.target, self.cancel)
            if result is not None and not self.cancel.is_set():
                self.signals.done.emit(self.generation, result)
        except ImportError as e:
            self.signals.error.emit(self.generation, f"numpy/soundfile non disponibili ({e})")
        except FileNotFoundError:
            self.signals.error.emit(self.generation, "ffmpeg non trovato")
        except Exception as e:  # noqa: BLE001
            logger.warning("Calcolo forma d'onda fallito: %s", self.file_path, exc_info=True)
            self.signals.error.emit(self.generation, str(e) or type(e).__name__)


# -----------------------------------------------------------------------
# Widget principale
# -----------------------------------------------------------------------

class WaveformWidget(QWidget):
    """
    Widget forma d'onda interattivo.

    Segnali:
        seek_requested(ms: int)     — l'utente ha cliccato per spostare il playhead
        subtitle_clicked(row: int)  — l'utente ha cliccato un blocco sottotitolo
    """

    seek_requested    = Signal(int)
    subtitle_clicked  = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("waveformWidget")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(80)
        self.setAccessibleName("Forma d'onda")

        # Dati audio (picchi normalizzati)
        self._mins = None
        self._maxs = None
        self._bucket_ms: float = 0.0
        self._sample_rate: int = 16000
        self._duration_ms: int = 0
        self._loading: bool = False
        self._loader: _AudioLoader | None = None

        # Sottotitoli + indice ordinato per inizio (bisect)
        self._subtitles: List[Subtitle] = []
        self._severity: List[str] = []   # "ok" | "warning" | "error" per ogni sub
        self._selected_row: int = -1
        self._sub_index: list = []       # [(start_ms, end_ms, row)] ordinati
        self._sub_starts: list = []
        self._max_sub_ms: float = 0.0

        # Stato player
        self._playhead_ms: int = 0

        # Vista (zoom/pan): intervallo visibile in ms
        self._view_start_ms: float = 0.0
        self._view_end_ms:   float = 0.0    # 0 = non ancora settato

        # Stato drag
        self._pressed: bool = False
        self._panning: bool = False
        self._press_x: int = 0
        self._press_y: int = 0
        self._drag_start_view: float = 0.0

        # Messaggio di stato
        self._status_msg: str = "Nessun file caricato"

        # Generazione per invalidare i loader obsoleti
        self._load_generation: int = 0

        # Cache dello strato statico
        self._cache: QPixmap | None = None
        self._cache_key = None
        self._content_ver = 0   # incrementato quando cambiano dati/sottotitoli/selezione

        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _name=None):
        self._invalidate()

    def _invalidate(self):
        self._content_ver += 1
        self.update()

    # ----------------------------------------------------------------
    # API pubblica
    # ----------------------------------------------------------------

    def load_audio(self, file_path: str) -> None:
        """Calcola la forma d'onda in background (memoria limitata, file letto a blocchi)."""
        self._cancel_loader()
        self._load_generation += 1
        self._mins = self._maxs = None
        self._loading = True
        self._status_msg = "Caricamento forma d'onda…"
        self._invalidate()

        loader = _AudioLoader(file_path, self._load_generation)
        # Slot bound + QueuedConnection: eseguiti nel thread UI e scollegati
        # automaticamente se il widget viene distrutto prima della fine.
        loader.signals.done.connect(self._on_loader_done, Qt.ConnectionType.QueuedConnection)
        loader.signals.error.connect(self._on_loader_error, Qt.ConnectionType.QueuedConnection)
        self._loader = loader
        loader.start()

    def show_message(self, text: str) -> None:
        """Mostra un messaggio al centro (es. anteprima non disponibile)."""
        self._status_msg = text
        self._invalidate()

    def set_duration(self, ms: int) -> None:
        """Imposta la durata totale (ricevuta da AudioPlayer.duration_changed)."""
        if ms <= 0:
            return
        self._duration_ms = ms
        if self._view_end_ms == 0.0 or self._view_end_ms > ms:
            self._view_start_ms = 0.0
            self._view_end_ms = float(ms)
        self._invalidate()

    def set_position(self, ms: int) -> None:
        """Aggiorna il playhead: ridisegna solo le strisce interessate, salvo auto-scroll."""
        old_x = self._ms_to_x(self._playhead_ms)
        self._playhead_ms = ms
        if self._auto_scroll():
            self.update()
            return
        new_x = self._ms_to_x(ms)
        h = self.height()
        for x in (old_x, new_x):
            if x is not None:
                self.update(QRect(x - 7, 0, 14, h))

    def set_subtitles(self, subtitles: List[Subtitle],
                      severity: List[str] | None = None) -> None:
        """
        Aggiorna la lista di sottotitoli da visualizzare come blocchi.
        `severity` è una lista parallela con valori "ok"/"warning"/"error".
        """
        self._subtitles = list(subtitles)
        if severity is not None and len(severity) == len(subtitles):
            self._severity = list(severity)
        else:
            self._severity = ["ok"] * len(subtitles)
        self._sub_index = sorted(
            (s.start * 1000.0, s.end * 1000.0, row) for row, s in enumerate(self._subtitles)
        )
        self._sub_starts = [e[0] for e in self._sub_index]
        self._max_sub_ms = max((e[1] - e[0] for e in self._sub_index), default=0.0)
        self._invalidate()

    def set_selected_row(self, row: int) -> None:
        """Evidenzia il sottotitolo selezionato."""
        if self._selected_row != row:
            self._selected_row = row
            self._invalidate()

    def reset(self) -> None:
        """Resetta tutto (nuovo file/progetto). Invalida anche i loader in corso."""
        self._cancel_loader()
        self._load_generation += 1
        self._mins = self._maxs = None
        self._loading = False
        self._duration_ms = 0
        self._playhead_ms = 0
        self._view_start_ms = 0.0
        self._view_end_ms = 0.0
        self.set_subtitles([])
        self._selected_row = -1
        self._status_msg = "Nessun file caricato"
        self._invalidate()

    def _cancel_loader(self):
        if self._loader is not None:
            self._loader.cancel.set()
            self._loader = None

    # ----------------------------------------------------------------
    # Slot interni (loader)
    # ----------------------------------------------------------------

    def _on_loader_done(self, generation: int, result):
        if generation != self._load_generation:
            return   # loader obsoleto
        mins, maxs, bucket, sr, frames = result
        self._loader = None
        self._mins, self._maxs = mins, maxs
        self._sample_rate = sr
        self._bucket_ms = bucket * 1000.0 / sr if sr else 0.0
        self._loading = False
        self._status_msg = "" if len(mins) else "Nessun audio nel file"
        if self._duration_ms <= 0 and sr:
            self._duration_ms = int(frames * 1000 / sr)
        if self._view_end_ms == 0.0 and self._duration_ms > 0:
            self._view_end_ms = float(self._duration_ms)
        self._invalidate()

    def _on_loader_error(self, generation: int, msg: str):
        if generation != self._load_generation:
            return
        self._loader = None
        self._loading = False
        self._status_msg = f"Forma d'onda non disponibile: {msg}"
        self._invalidate()

    # ----------------------------------------------------------------
    # Rendering
    # ----------------------------------------------------------------

    def _font(self, delta_pt: float, mono: bool = False) -> QFont:
        family = platform_support.mono_font_family() if mono else platform_support.ui_font_family()
        f = QFont(family)
        base = self.font().pointSizeF()
        f.setPointSizeF(max(7.0, (base if base > 0 else 12.0) + delta_pt))
        return f

    def _static_layer(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, self._view_start_ms, self._view_end_ms,
               self._duration_ms, theme.get_theme(), self._content_ver, self._loading)
        if self._cache is not None and self._cache_key == key:
            return self._cache
        pix = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pix.setDevicePixelRatio(dpr)
        p = QPainter(pix)
        try:
            self.render_static(p, self.width(), self.height())
        finally:
            p.end()
        self._cache, self._cache_key = pix, key
        return pix

    def render_static(self, painter: QPainter, w: int, h: int) -> None:
        """Disegna lo strato statico (sfondo, onda, blocchi, righello) su `painter`."""
        painter.fillRect(0, 0, w, h, theme.qcolor("wave_bg"))
        if self._mins is not None and not self._loading:
            self._draw_waveform(painter, w, h)
        if self._status_msg:
            self._draw_status(painter, w, h)
        if not self._loading:
            self._draw_subtitle_blocks(painter, w, h)
        self._draw_ticks(painter, w, h)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.drawPixmap(0, 0, self._static_layer())
            self._draw_playhead(painter, self.width(), self.height())
        finally:
            painter.end()

    def _draw_status(self, painter: QPainter, w: int, h: int):
        painter.setPen(theme.qcolor("muted"))
        painter.setFont(self._font(-1))
        painter.drawText(QRect(12, 0, w - 24, h), Qt.AlignCenter | Qt.TextWordWrap,
                         self._status_msg)

    def _draw_waveform(self, painter: QPainter, w: int, h: int):
        import numpy as np
        mins, maxs = self._mins, self._maxs
        n = len(mins) if mins is not None else 0
        view_start, view_end = self._view_start_ms, self._view_end_ms
        if n == 0 or w <= 0 or view_end <= view_start or self._bucket_ms <= 0:
            return
        span = view_end - view_start
        # Bucket coperti da ogni colonna di pixel
        edges = np.floor(
            (view_start + np.arange(w + 1) * (span / w)) / self._bucket_ms
        ).astype(np.int64)
        edges = np.clip(edges, 0, n)
        starts = edges[:-1]
        valid = starts < n
        if not valid.any():
            return
        cols = np.nonzero(valid)[0]
        idx = starts[valid]
        col_min = np.minimum.reduceat(mins, idx)
        col_max = np.maximum.reduceat(maxs, idx)

        cy = h / 2.0
        half_h = cy * 0.88
        top = [QPointF(float(x), cy - float(v) * half_h) for x, v in zip(cols, col_max)]
        bottom = [QPointF(float(x), cy - float(v) * half_h)
                  for x, v in zip(cols[::-1], col_min[::-1])]
        path = QPainterPath()
        path.addPolygon(QPolygonF(top + bottom))
        path.closeSubpath()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(path, QBrush(theme.qcolor("wave_fill")))
        painter.setPen(QPen(theme.qcolor("acc"), 0.6))
        painter.drawPath(path)
        painter.setRenderHint(QPainter.Antialiasing, False)

    def _visible_subs(self, view_start: float, view_end: float):
        """Sottotitoli che intersecano la vista (bisect sull'indice ordinato)."""
        lo = bisect.bisect_left(self._sub_starts, view_start - self._max_sub_ms)
        hi = bisect.bisect_right(self._sub_starts, view_end)
        for start, end, row in self._sub_index[lo:hi]:
            if end >= view_start:
                yield start, end, row

    def _block_geometry(self, h: int) -> Tuple[int, int]:
        block_h = max(18, h // 4)
        return h - block_h - 2, block_h

    def _draw_subtitle_blocks(self, painter: QPainter, w: int, h: int):
        if not self._sub_index or self._duration_ms == 0:
            return
        view_start, view_end = self._view_start_ms, self._view_end_ms
        if view_end <= view_start:
            return
        span = view_end - view_start

        block_y, block_h = self._block_geometry(h)
        font = self._font(-3)
        painter.setFont(font)
        fm = QFontMetrics(font)
        colors = {
            "error": theme.qcolor("err"), "warning": theme.qcolor("warn"),
            "ok": theme.qcolor("ok"), "sel": theme.qcolor("acc"),
        }
        for col in colors.values():
            col.setAlpha(120)
        colors["sel"].setAlpha(170)
        outline = QPen(theme.qcolor("wave_outline"), 1)
        text_pen = QPen(theme.qcolor("text"))

        for start, end, row in self._visible_subs(view_start, view_end):
            x1 = max(0, int((start - view_start) / span * w))
            x2 = min(w, int((end - view_start) / span * w))
            if x2 - x1 < 1:
                continue
            if row == self._selected_row:
                color = colors["sel"]
            else:
                sev = self._severity[row] if row < len(self._severity) else "ok"
                color = colors.get(sev, colors["ok"])
            rect = QRect(x1, block_y, x2 - x1, block_h)
            painter.fillRect(rect, color)
            painter.setPen(outline)
            painter.drawRect(rect)
            if x2 - x1 > 20:
                label = self._subtitles[row].text.replace("\n", " ")
                elided = fm.elidedText(label, Qt.ElideRight, x2 - x1 - 6)
                painter.setPen(text_pen)
                painter.drawText(QRect(x1 + 3, block_y + 1, x2 - x1 - 6, block_h - 2),
                                 Qt.AlignVCenter | Qt.AlignLeft, elided)

    def _ms_to_x(self, ms: float) -> Optional[int]:
        span = self._view_end_ms - self._view_start_ms
        if self._duration_ms == 0 or span <= 0:
            return None
        frac = (ms - self._view_start_ms) / span
        if not (0.0 <= frac <= 1.0):
            return None
        return int(frac * self.width())

    def _draw_playhead(self, painter: QPainter, w: int, h: int):
        x = self._ms_to_x(self._playhead_ms)
        if x is None:
            return
        playhead = theme.qcolor("playhead")
        painter.setPen(QPen(playhead, 2))
        painter.drawLine(x, 0, x, h)
        path = QPainterPath()
        path.moveTo(x - 5, 0)
        path.lineTo(x + 5, 0)
        path.lineTo(x, 8)
        path.closeSubpath()
        painter.fillPath(path, playhead)

    def _draw_ticks(self, painter: QPainter, w: int, h: int):
        """Righello temporale: tick ogni N secondi."""
        view_start, view_end = self._view_start_ms, self._view_end_ms
        if view_end <= view_start or w == 0:
            return
        span_s = (view_end - view_start) / 1000.0
        interval_s = 300
        for cand in (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300):
            if span_s / cand <= w / 70:
                interval_s = cand
                break

        font = self._font(-4, mono=True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        tick_pen = QPen(theme.qcolor("faint"))
        label_pen = QPen(theme.qcolor("muted"))
        step = interval_s * 1000
        t = math.floor(view_start / step) * step
        while t <= view_end:
            x = int((t - view_start) / (view_end - view_start) * w)
            painter.setPen(tick_pen)
            painter.drawLine(x, 0, x, 8)
            total_s = t / 1000.0
            m = int(total_s) // 60
            s = total_s % 60
            label = f"{m}:{s:04.1f}" if m > 0 else f"{s:.1f}s"
            painter.setPen(label_pen)
            painter.drawText(QRectF(x + 3, 2, fm.horizontalAdvance(label) + 4,
                                    fm.height()), Qt.AlignLeft | Qt.AlignTop, label)
            t += step

    # ----------------------------------------------------------------
    # Mouse events
    # ----------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Nessun seek alla pressione: un trascinamento è un pan, non uno spostamento
            self._pressed = True
            self._panning = False
            self._press_x = int(event.position().x())
            self._press_y = int(event.position().y())
            self._drag_start_view = self._view_start_ms

    def mouseMoveEvent(self, event):
        if not (self._pressed and (event.buttons() & Qt.LeftButton)):
            return
        dx = int(event.position().x()) - self._press_x
        if not self._panning and abs(dx) < _CLICK_SLOP:
            return
        self._panning = True
        span = self._view_end_ms - self._view_start_ms
        if self.width() > 0 and span > 0:
            new_start = self._drag_start_view - dx * span / self.width()
            new_start = max(0.0, min(float(self._duration_ms) - span, new_start))
            self._view_start_ms = new_start
            self._view_end_ms = new_start + span
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self._pressed:
            return
        self._pressed = False
        if self._panning:
            self._panning = False
            return
        # Click semplice: blocco sottotitolo → selezione, altrimenti seek (una sola volta)
        x, y = event.position().x(), event.position().y()
        row = self._row_at(x, y)
        if row >= 0:
            self.subtitle_clicked.emit(row)
            return
        ms = self._x_to_ms(x)
        if ms >= 0:
            self.seek_requested.emit(int(ms))

    def wheelEvent(self, event):
        """Scroll verticale: zoom; scroll orizzontale: pan."""
        delta = event.angleDelta()
        span = self._view_end_ms - self._view_start_ms
        if span <= 0 or self._duration_ms == 0:
            return

        if abs(delta.y()) >= abs(delta.x()):
            center_ms = self._x_to_ms(event.position().x())
            factor = max(0.1, min(10.0, 1.0 - delta.y() / 1200.0))
            new_span = max(500.0, min(float(self._duration_ms), span * factor))
            frac = (center_ms - self._view_start_ms) / span if span > 0 else 0.5
            new_start = center_ms - frac * new_span
        else:
            new_span = span
            new_start = self._view_start_ms - delta.x() * span / 500.0

        new_start = max(0.0, min(float(self._duration_ms) - new_span, new_start))
        self._view_start_ms = new_start
        self._view_end_ms = new_start + new_span
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
        block_y, block_h = self._block_geometry(self.height())
        if y < block_y or y > block_y + block_h:
            return -1
        ms = self._x_to_ms(x)
        for start, end, row in self._visible_subs(ms, ms):
            if start <= ms <= end:
                return row
        return -1

    def _auto_scroll(self) -> bool:
        """
        Se il playhead esce dalla finestra visibile, sposta la vista per tenerlo
        a circa il 20% da sinistra. Ritorna True se la vista è cambiata.
        """
        if self._duration_ms == 0 or self._view_end_ms == 0.0 or self._pressed:
            return False
        span = self._view_end_ms - self._view_start_ms
        margin = span * 0.15
        if self._view_start_ms + margin <= self._playhead_ms <= self._view_end_ms - margin:
            return False
        new_start = self._playhead_ms - span * 0.2
        new_start = max(0.0, min(float(self._duration_ms) - span, new_start))
        if abs(new_start - self._view_start_ms) < 1e-6:
            return False
        self._view_start_ms = new_start
        self._view_end_ms = new_start + span
        return True
