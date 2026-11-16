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

from PySide6.QtCore import Qt, Signal, QRect, QRectF, QObject
from PySide6.QtGui import (
    QPainter, QPainterPath, QPen, QFont, QFontMetrics, QPixmap,
)
from PySide6.QtWidgets import QWidget, QSizePolicy

from core.subtitle_model import Subtitle
from ui import theme
from ui.transport_bar import _ms_to_label
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
# Geometria (mockup): righello 22 px in alto, corsia dei blocchi 52 px in basso
_RULER_H = 22
_LANE_H = 52
# Barre della forma d'onda: 2 px di larghezza ogni 3
_BAR_PITCH = 3
_BAR_W = 2


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
        self.setMinimumHeight(_RULER_H + _LANE_H + 41)
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
        self._played_cache: QPixmap | None = None   # barre in accento (parte già suonata)
        self._played_key = None
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
        xs = [x for x in (old_x, new_x) if x is not None]
        if xs:
            # tra i due playhead cambia anche il colore delle barre; il flag è largo ~70 px
            left, right = min(xs) - 45, max(xs) + 45
            self.update(QRect(left, 0, right - left, self.height()))

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

    def _font(self, px: int, mono: bool = False, weight=None) -> QFont:
        """Font a dimensione in pixel (11 px per righello, blocchi e flag)."""
        family = platform_support.mono_font_family() if mono else platform_support.ui_font_family()
        f = QFont(family)
        f.setPixelSize(px)
        if weight is not None:
            f.setWeight(weight)
        return f

    def _cache_signature(self):
        dpr = self.devicePixelRatioF()
        return (self.width(), self.height(), dpr, self._view_start_ms, self._view_end_ms,
                self._duration_ms, theme.get_theme(), self._content_ver, self._loading)

    def _new_layer(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pix = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pix.setDevicePixelRatio(dpr)
        return pix

    def _static_layer(self) -> QPixmap:
        key = self._cache_signature()
        if self._cache is not None and self._cache_key == key:
            return self._cache
        pix = self._new_layer()
        p = QPainter(pix)
        try:
            self.render_static(p, self.width(), self.height())
        finally:
            p.end()
        self._cache, self._cache_key = pix, key
        return pix

    def _played_layer(self) -> QPixmap:
        """Strato (trasparente) con le sole barre in accento: se ne copia la parte già suonata."""
        key = self._cache_signature()
        if self._played_cache is not None and self._played_key == key:
            return self._played_cache
        pix = self._new_layer()
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        try:
            if self._mins is not None and not self._loading:
                self._draw_bars(p, self.width(), self.height(), theme.qcolor("acc"))
        finally:
            p.end()
        self._played_cache, self._played_key = pix, key
        return pix

    def render_static(self, painter: QPainter, w: int, h: int) -> None:
        """Disegna lo strato statico (sfondo, onda, righello, corsia e blocchi) su `painter`."""
        painter.fillRect(0, 0, w, h, theme.qcolor("wave_bg"))
        if self._mins is not None and not self._loading:
            self._draw_bars(painter, w, h, theme.qcolor("wave"))
        if self._status_msg:
            self._draw_status(painter, w, h)
        self._draw_ruler(painter, w, h)
        self._draw_lane(painter, w, h)
        if not self._loading:
            self._draw_subtitle_blocks(painter, w, h)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            w, h = self.width(), self.height()
            painter.drawPixmap(0, 0, self._static_layer())
            x = self._ms_to_x(self._playhead_ms)
            if x is not None and self._mins is not None and not self._loading:
                # parte già suonata: copia delle barre in accento fino al playhead
                dpr = self.devicePixelRatioF()
                painter.drawPixmap(QRect(0, 0, x, h), self._played_layer(),
                                   QRect(0, 0, int(x * dpr), int(h * dpr)))
            self._draw_playhead(painter, w, h)
        finally:
            painter.end()

    def _wave_area(self, h: int) -> Tuple[int, int]:
        """(y alto, y basso) dell'area della forma d'onda, tra righello e corsia."""
        return _RULER_H, max(_RULER_H + 1, h - _LANE_H - 1)

    def _draw_status(self, painter: QPainter, w: int, h: int):
        top, bottom = self._wave_area(h)
        painter.setPen(theme.qcolor("dim"))
        painter.setFont(self._font(12))
        painter.drawText(QRect(12, top, w - 24, bottom - top), Qt.AlignCenter | Qt.TextWordWrap,
                         self._status_msg)

    def _draw_bars(self, painter: QPainter, w: int, h: int, color):
        """Barre sottili (2 px ogni 3) con l'ampiezza massima del tratto di tempo coperto."""
        import numpy as np
        mins, maxs = self._mins, self._maxs
        n = len(mins) if mins is not None else 0
        view_start, view_end = self._view_start_ms, self._view_end_ms
        if n == 0 or w <= 0 or view_end <= view_start or self._bucket_ms <= 0:
            return
        top, bottom = self._wave_area(h)
        nb = max(1, w // _BAR_PITCH)
        per_bar = (view_end - view_start) / w * _BAR_PITCH
        edges = np.floor(
            (view_start + np.arange(nb + 1) * per_bar) / self._bucket_ms
        ).astype(np.int64)
        edges = np.clip(edges, 0, n)
        starts = edges[:-1]
        valid = starts < n
        if not valid.any():
            return
        cols = np.nonzero(valid)[0]
        idx = starts[valid]
        end = max(int(edges.max()), int(idx.max()) + 1)
        col_min = np.minimum.reduceat(mins[:end], idx)
        col_max = np.maximum.reduceat(maxs[:end], idx)
        amp = np.maximum(np.abs(col_min), np.abs(col_max))
        cy = (top + bottom) / 2.0
        half = max(2.0, (bottom - top) / 2.0 - 6.0)
        heights = np.maximum(2, np.rint(amp * half * 2)).astype(np.int64)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        for c, bh in zip(cols.tolist(), heights.tolist()):
            painter.drawRect(c * _BAR_PITCH, int(cy - bh / 2), _BAR_W, bh)

    def _visible_subs(self, view_start: float, view_end: float):
        """Sottotitoli che intersecano la vista (bisect sull'indice ordinato)."""
        lo = bisect.bisect_left(self._sub_starts, view_start - self._max_sub_ms)
        hi = bisect.bisect_right(self._sub_starts, view_end)
        for start, end, row in self._sub_index[lo:hi]:
            if end >= view_start:
                yield start, end, row

    def _block_geometry(self, h: int) -> Tuple[int, int]:
        """(y, altezza) dei blocchi: dentro la corsia da 52 px, 10 px sotto il suo bordo."""
        lane_y = h - _LANE_H
        return lane_y + 10, 32

    def _draw_lane(self, painter: QPainter, w: int, h: int):
        lane_y = h - _LANE_H
        painter.fillRect(0, lane_y, w, _LANE_H, theme.qcolor("panel"))
        painter.fillRect(0, lane_y - 1, w, 1, theme.qcolor("line"))

    def _draw_subtitle_blocks(self, painter: QPainter, w: int, h: int):
        if not self._sub_index or self._duration_ms == 0:
            return
        view_start, view_end = self._view_start_ms, self._view_end_ms
        if view_end <= view_start:
            return
        span = view_end - view_start

        block_y, block_h = self._block_geometry(h)
        font = self._font(11)
        painter.setFont(font)
        fm = QFontMetrics(font)
        border = {"error": theme.qcolor("err"), "warning": theme.qcolor("warn"),
                  "ok": theme.qcolor("line")}
        sel_border = theme.qcolor("acc")
        fill = theme.qcolor("raise")
        sel_fill = theme.qcolor("sel")
        text_dim = theme.qcolor("dim")
        text_sel = theme.qcolor("text")

        for start, end, row in self._visible_subs(view_start, view_end):
            x1 = max(0, int((start - view_start) / span * w))
            x2 = min(w, int((end - view_start) / span * w))
            if x2 - x1 < 1:
                continue
            selected = row == self._selected_row
            sev = self._severity[row] if row < len(self._severity) else "ok"
            rect = QRect(x1, block_y, max(1, x2 - x1 - 1), block_h - 1)
            painter.fillRect(rect, sel_fill if selected else fill)
            painter.setPen(QPen(sel_border if selected else border.get(sev, border["ok"]), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            if x2 - x1 > 20:
                label = self._subtitles[row].text.replace("\n", " ")
                elided = fm.elidedText(label, Qt.ElideRight, x2 - x1 - 14)
                painter.setPen(text_sel if selected else text_dim)
                painter.drawText(QRect(x1 + 6, block_y, x2 - x1 - 12, block_h - 1),
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
        """Linea da 1 px in accento su tutta l'altezza + flag mono con il tempo in alto."""
        x = self._ms_to_x(self._playhead_ms)
        if x is None:
            return
        acc = theme.qcolor("acc")
        painter.fillRect(x, 0, 1, h, acc)
        font = self._font(11, mono=True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        text = _ms_to_label(self._playhead_ms)
        fw = fm.horizontalAdvance(text) + 10
        fx = max(0, min(w - fw, x - fw // 2))
        flag = QRect(fx, 2, fw, fm.height() + 2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(flag), 2, 2)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(path, acc)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(theme.qcolor("acc_ink"))
        painter.drawText(flag, Qt.AlignCenter, text)

    @staticmethod
    def _tick_label(t_ms: float, interval_s: float) -> str:
        total = max(0.0, t_ms / 1000.0)
        hrs, rem = divmod(int(total), 3600)
        mins, secs = divmod(rem, 60)
        if interval_s < 1:
            frac = f".{int(round((total - int(total)) * 10)) % 10}"
        else:
            frac = ""
        if hrs:
            return f"{hrs}:{mins:02d}:{secs:02d}{frac}"
        return f"{mins}:{secs:02d}{frac}"

    def _draw_ruler(self, painter: QPainter, w: int, h: int):
        """Righello da 22 px: tick da 1 px ogni N secondi con etichette mono da 11 px."""
        painter.fillRect(0, _RULER_H - 1, w, 1, theme.qcolor("line"))
        view_start, view_end = self._view_start_ms, self._view_end_ms
        if view_end <= view_start or w == 0:
            return
        span_s = (view_end - view_start) / 1000.0
        interval_s = 300
        for cand in (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300):
            if span_s / cand <= w / 70:
                interval_s = cand
                break

        font = self._font(11, mono=True)
        painter.setFont(font)
        line = theme.qcolor("line")
        label_col = theme.qcolor("muted")
        step = interval_s * 1000
        t = math.floor(view_start / step) * step
        while t <= view_end:
            x = int((t - view_start) / (view_end - view_start) * w)
            painter.fillRect(x, 0, 1, _RULER_H - 1, line)
            painter.setPen(label_col)
            painter.drawText(QRect(x + 6, 0, 120, _RULER_H - 1), Qt.AlignLeft | Qt.AlignVCenter,
                             self._tick_label(t, interval_s))
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
