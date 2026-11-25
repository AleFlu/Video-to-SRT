"""
waveform_widget.py — Widget forma d'onda audio con overlay dei sottotitoli.

  - Caricamento in un thread separato: il file viene letto A BLOCCHI
    (`soundfile.blocks`, oppure lo stdout PCM di ffmpeg per i formati che
    soundfile non legge) e ridotto a picchi min/max per bucket. La memoria
    usata è limitata (≤ 2 × TARGET_BUCKETS bucket) qualunque sia la durata.
  - Rendering: lo strato statico (sfondo, forma d'onda, blocchi sottotitolo,
    righello) è in cache in una QPixmap ridisegnata solo su resize, zoom/pan,
    cambio tema o sottotitoli; a ogni tick del player si ridisegna solo il playhead.
  - Interazione (il playhead si sposta SOLO con click, scrub o tastiera):
      · click → seek (o selezione del blocco sottotitolo); tenere premuto e trascinare
        → scrub: il playhead segue il mouse e resta dove lo si lascia (oltre i bordi,
        con zoom, la vista scorre); ⌥/Alt + trascinamento → pan;
      · trascinando il bordo di un blocco se ne cambia l'inizio o la fine, trascinandone
        il centro lo si sposta tutto (regole in ``core.timing_edit``: niente
        sovrapposizioni con i vicini). Il bordo si aggancia al playhead e ai sottotitoli
        vicini (Maiusc lo sgancia), Esc annulla; al rilascio ``timing_edited``.
        Portato oltre i vicini: sopra un altro blocco i due si scambiano il testo
        (``subtitles_swapped``), in una pausa ci entra se c'è posto (``subtitle_moved``);
      · trascinando nella corsia vuota, o con un doppio clic lì, si crea un sottotitolo
        nuovo dentro quella pausa (``subtitle_created``);
      · rotella verticale/orizzontale o due dita sul trackpad → scorrimento della
        finestra visibile (solo se c'è zoom; `pixelDelta` per lo scorrimento fluido,
        verso "naturale" del sistema così come lo consegna Qt);
      · Ctrl/⌘ o Alt + rotella, oppure pizzico sul trackpad → zoom attorno al cursore;
      · doppio clic sulla forma d'onda (non nella corsia) → zoom su tutta la durata;
      · tastiera (con il focus): ←/→ ±1 s, Home/Fine, +/− zoom, 0 tutta la durata.
  - Auto-scroll del playhead: dopo uno scorrimento/zoom manuale è sospeso per
    FOLLOW_HOLD_S secondi dall'ultimo gesto (regola a tempo: semplice e senza stati
    da indovinare); un seek esplicito (click, tasti) lo riattiva subito.
"""

from __future__ import annotations

import bisect
import logging
import math
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QEvent, QRect, QRectF, QObject
from PySide6.QtGui import (
    QPainter, QPainterPath, QPen, QFont, QFontMetrics, QPixmap,
)
from PySide6.QtWidgets import QWidget, QSizePolicy

from core import timing_edit
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
NEW_BLOCK_S = 2.0          # doppio clic nella corsia: durata del sottotitolo nuovo
# Barre della forma d'onda: 2 px di larghezza ogni 3
_BAR_PITCH = 3
_BAR_W = 2
# Zoom: finestra visibile minima (ms)
_MIN_SPAN_MS = 500.0
# Scorrimento con la rotella "a scatti" (angleDelta): frazione della finestra per tacca
_WHEEL_PAN_FRACTION = 0.1
# Auto-scroll del playhead sospeso per N secondi dopo uno scorrimento/zoom manuale
FOLLOW_HOLD_S = 2.0
# Seek da tastiera (←/→) quando la forma d'onda ha il focus
_KEY_SEEK_MS = 1000
# Fattore di zoom dei tasti +/−
_KEY_ZOOM = 0.8
# Modifica dei tempi trascinando i blocchi: distanza dal bordo per afferrarlo e aggancio
_EDGE_GRAB_PX = 6
_SNAP_PX = 8


def waveform_help() -> str:
    """Come si usa la forma d'onda (tooltip e descrizione accessibile)."""
    mod = platform_support.shortcut_label("Ctrl")
    return (f"Scorri con la rotella o con due dita · {mod} + rotella o pizzico per lo zoom"
            " · clic o trascina per spostarti"
            " · trascina i bordi di un sottotitolo per cambiarne i tempi")


def waveform_keys_help() -> str:
    """Tasti della forma d'onda (descrizione accessibile, seconda riga del tooltip)."""
    return ("Doppio clic: tutta la durata · ←/→ ±1 s · Home/Fine: inizio/fine"
            " · +/−: zoom · 0: tutta la durata")


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

class _AudioLoaderRelay(QObject):
    """Unico ponte thread → UI per tutti i loader (crea il primo WaveformWidget, nel thread UI).

    Non viene mai distrutto: se ogni loader avesse il proprio QObject, il thread di sistema ne
    rilascerebbe l'ultimo riferimento a fine lavoro e il QObject verrebbe distrutto fuori dal
    suo thread mentre la UI ne consegna ancora gli eventi (crash casuali).
    Il primo argomento è il loader che ha emesso: ogni widget scarta quelli non suoi.
    """

    done = Signal(object, object)   # (loader, risultato di compute_peaks)
    error = Signal(object, str)     # (loader, messaggio)


_RELAY: _AudioLoaderRelay | None = None


def _loader_relay() -> _AudioLoaderRelay:
    global _RELAY
    if _RELAY is None:
        _RELAY = _AudioLoaderRelay()
    return _RELAY


class _AudioLoader(threading.Thread):
    """Calcola i picchi in un thread di sistema (nessun oggetto Qt creato o posseduto)."""

    def __init__(self, file_path: str, generation: int, target: int = TARGET_BUCKETS):
        super().__init__(daemon=True)
        self.file_path = file_path
        self.generation = generation
        self.target = target
        self.cancel = threading.Event()

    def run(self):
        relay = _RELAY   # creato dal widget prima dello start
        if relay is None:
            return
        try:
            result = compute_peaks(self.file_path, self.target, self.cancel)
            if result is not None and not self.cancel.is_set():
                relay.done.emit(self, result)
        except ImportError as e:
            relay.error.emit(self, f"numpy/soundfile non disponibili ({e})")
        except FileNotFoundError:
            relay.error.emit(self, "ffmpeg non trovato")
        except Exception as e:  # noqa: BLE001
            logger.warning("Calcolo forma d'onda fallito: %s", self.file_path, exc_info=True)
            relay.error.emit(self, str(e) or type(e).__name__)


# -----------------------------------------------------------------------
# Gesti nativi (pizzico) → WaveformWidget
# -----------------------------------------------------------------------

class _GestureFilter(QObject):
    """Inoltra i QNativeGestureEvent del widget a `WaveformWidget.native_gesture`."""

    def eventFilter(self, obj, event):  # noqa: N802 (override Qt)
        if event.type() == QEvent.NativeGesture and isinstance(obj, WaveformWidget):
            return obj.native_gesture(event)
        return False


# -----------------------------------------------------------------------
# Widget principale
# -----------------------------------------------------------------------

@dataclass
class _CreateDrag:
    """Sottotitolo nuovo disegnato nella corsia vuota (ms)."""

    press_ms: float
    times: list
    block: Optional[Tuple[float, float]] = None
    active: bool = False


@dataclass
class _TimingDrag:
    """Trascinamento di un blocco: tempi in ms (originali e nuovi)."""

    row: int
    mode: str                # "start" | "end" | "move"
    times: list              # [(inizio, fine)] di tutti i sottotitoli, per riga
    press_ms: float
    new_start: float
    new_end: float
    active: bool = False     # oltre la soglia del click
    snap_ms: Optional[float] = None
    target: Optional[str] = None   # oltre i vicini: "swap" | "slot" | "none"
    target_row: int = -1           # con "swap": il blocco sotto il mouse

    @property
    def start(self) -> float:
        return self.times[self.row][0]

    @property
    def end(self) -> float:
        return self.times[self.row][1]


class WaveformWidget(QWidget):
    """
    Widget forma d'onda interattivo.

    Segnali:
        seek_requested(ms: int)     — l'utente ha cliccato per spostare il playhead
        subtitle_clicked(row: int)  — l'utente ha cliccato un blocco sottotitolo
        timing_edited(row, start_s, end_s) — l'utente ha trascinato un blocco o un bordo
        subtitles_swapped(row, other)      — blocco lasciato sopra un altro: scambio testi
        subtitle_moved(row, start_s, end_s) — blocco portato in un'altra pausa
        subtitle_created(start_s, end_s)   — sottotitolo nuovo disegnato nella corsia
    """

    seek_requested    = Signal(int)
    subtitle_clicked  = Signal(int)
    timing_edited     = Signal(int, float, float)   # riga, inizio, fine (s)
    subtitles_swapped = Signal(int, int)
    subtitle_moved    = Signal(int, float, float)
    subtitle_created  = Signal(float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("waveformWidget")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(_RULER_H + _LANE_H + 41)
        self.setAccessibleName("Forma d'onda")
        self.setAccessibleDescription(f"{waveform_help()}. {waveform_keys_help()}.")
        self.setToolTip(f"{waveform_help()}\n{waveform_keys_help()}")
        # Raggiungibile con Tab e con il click (le frecce spostano il playhead)
        self.setFocusPolicy(Qt.StrongFocus)

        # Dati audio (picchi normalizzati)
        self._mins = None
        self._maxs = None
        self._bucket_ms: float = 0.0
        self._sample_rate: int = 16000
        self._duration_ms: int = 0
        self._loading: bool = False
        self._loader: _AudioLoader | None = None
        # Relay condiviso (thread UI). Slot bound + QueuedConnection: eseguiti nel thread UI
        # e scollegati automaticamente se il widget viene distrutto prima della fine.
        relay = _loader_relay()
        relay.done.connect(self._on_relay_done, Qt.ConnectionType.QueuedConnection)
        relay.error.connect(self._on_relay_error, Qt.ConnectionType.QueuedConnection)

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
        self._scrubbing: bool = False
        self._timing: Optional[_TimingDrag] = None   # blocco afferrato
        self._creating: Optional[_CreateDrag] = None   # blocco nuovo in disegno

        # Auto-scroll sospeso fino a questo istante (orologio monotòno, s)
        self._clock = time.monotonic
        self._follow_hold_until: float = 0.0
        self._seek_target: Optional[int] = None   # posizione dell'ultimo seek esplicito

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
        self._gesture_filter = _GestureFilter(self)
        self.installEventFilter(self._gesture_filter)

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
        scrolled = self._auto_scroll()
        self._seek_target = None
        if scrolled:
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
        self._follow_hold_until = 0.0
        self._seek_target = None
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

    def _on_relay_done(self, loader, result):
        if loader is self._loader:
            self._on_loader_done(loader.generation, result)

    def _on_relay_error(self, loader, msg: str):
        if loader is self._loader:
            self._on_loader_error(loader.generation, msg)

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
            if self.hasFocus():
                # anello di focus da tastiera (1 px, token `focus`)
                painter.setPen(QPen(theme.qcolor("focus"), 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(0, 0, w - 1, h - 1)
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
        if self._duration_ms == 0 or (not self._sub_index and self._creating is None):
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
        drag = self._timing if self._timing is not None and self._timing.active else None

        swap_row = drag.target_row if drag is not None and drag.target == "swap" else -1

        def draw_block(start: float, end: float, row: int, pen: Optional[QPen] = None,
                       label: Optional[str] = None) -> None:
            x1 = max(0, int((start - view_start) / span * w))
            x2 = min(w, int((end - view_start) / span * w))
            if x2 - x1 < 1:
                return
            selected = (row == self._selected_row or row == swap_row
                        or (drag is not None and row == drag.row))
            sev = self._severity[row] if 0 <= row < len(self._severity) else "ok"
            rect = QRect(x1, block_y, max(1, x2 - x1 - 1), block_h - 1)
            painter.fillRect(rect, sel_fill if selected else fill)
            if pen is None:
                pen = QPen(sel_border if selected else border.get(sev, border["ok"]),
                           2 if row == swap_row else 1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            if x2 - x1 > 20:
                if label is None:
                    label = self._subtitles[row].text.replace("\n", " ")
                elided = fm.elidedText(label, Qt.ElideRight, x2 - x1 - 14)
                painter.setPen(text_sel if selected else text_dim)
                painter.drawText(QRect(x1 + 6, block_y, x2 - x1 - 12, block_h - 1),
                                 Qt.AlignVCenter | Qt.AlignLeft, elided)

        for start, end, row in self._visible_subs(view_start, view_end):
            if drag is None or row != drag.row:
                draw_block(start, end, row)
        if drag is not None:
            # dove non si può lasciare: bordo tratteggiato nel colore d'errore
            if drag.target == "swap":
                draw_block(drag.start, drag.end, drag.row, QPen(sel_border, 1, Qt.DashLine))
            else:
                pen = QPen(theme.qcolor("err"), 1, Qt.DashLine) if drag.target == "none" \
                    else None
                draw_block(drag.new_start, drag.new_end, drag.row, pen)
            self._draw_drag_marks(painter, w, h, drag)
        create = self._creating if self._creating is not None and self._creating.active \
            else None
        if create is not None and create.block is not None:
            draw_block(create.block[0], create.block[1], -1,
                       QPen(theme.qcolor("acc"), 1, Qt.DashLine), "Nuovo sottotitolo")

    def _draw_drag_marks(self, painter: QPainter, w: int, h: int, drag: _TimingDrag) -> None:
        """Bordo trascinato in accento, linea dell'aggancio e tempi sopra il blocco."""
        acc = theme.qcolor("acc")
        block_y, block_h = self._block_geometry(h)
        if drag.snap_ms is not None:
            x = self._ms_to_x(drag.snap_ms)
            if x is not None:
                painter.setPen(QPen(acc, 1, Qt.DashLine))
                painter.drawLine(x, 0, x, h)
        edges = {"start": [drag.new_start], "end": [drag.new_end],
                 "move": [drag.new_start, drag.new_end]}[drag.mode]
        if drag.target in ("swap", "none"):
            edges = []                       # il blocco non va lì: niente tempi
        for ms in edges:
            x = self._ms_to_x(ms)
            if x is not None:
                painter.fillRect(max(0, x - 1), block_y - 2, 3, block_h + 3, acc)
        # etichetta: tempo del bordo (o dell'inizio) e durata
        shown = drag.new_end if drag.mode == "end" else drag.new_start
        duration = f"{(drag.new_end - drag.new_start) / 1000:.2f}".replace(".", ",")
        text = f"{_ms_to_label(int(round(shown)))} · {duration} s"
        if drag.target == "swap":
            text = f"Scambia il testo con il n. {drag.target_row + 1}"
        elif drag.target == "none":
            text = "Qui non c'è spazio"
        font = self._font(11, mono=True)
        painter.setFont(font)
        fm = QFontMetrics(font)
        fw = fm.horizontalAdvance(text) + 10
        x = self._ms_to_x(shown)
        x = (0 if shown < self._view_start_ms else w) if x is None else x
        fx = max(0, min(w - fw, x - fw // 2))
        flag = QRect(fx, block_y - fm.height() - 8, fw, fm.height() + 2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(flag), 2, 2)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(path, acc)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(theme.qcolor("acc_ink"))
        painter.drawText(flag, Qt.AlignCenter, text)

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
            # Nessun seek alla pressione: un click su un blocco lo seleziona soltanto; se
            # il mouse si sposta oltre _CLICK_SLOP parte lo scrub (o il pan con ⌥/Alt),
            # oppure, partendo da un blocco, la modifica dei suoi tempi
            self._pressed = True
            self._panning = False
            self._scrubbing = False
            self._press_x = int(event.position().x())
            self._press_y = int(event.position().y())
            self._drag_start_view = self._view_start_ms
            self._timing = None
            self._creating = None
            if not event.modifiers() & Qt.AltModifier:
                row, mode = self._hit_block(event.position().x(), event.position().y())
                if row >= 0:
                    times = self._times()
                    start, end = times[row]
                    self._timing = _TimingDrag(row, mode, times, self._x_to_ms(self._press_x),
                                               start, end)
                elif self._in_lane(event.position().y()) and self._duration_ms > 0:
                    self._creating = _CreateDrag(self._x_to_ms(self._press_x), self._times())

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if not (self._pressed and (event.buttons() & Qt.LeftButton)):
            if not self._pressed:
                self._update_hover_cursor(x, event.position().y())
            return
        dx = int(x) - self._press_x
        if self._creating is not None:
            if not self._creating.active:
                if abs(dx) < _CLICK_SLOP:
                    return
                self._creating.active = True
                self.setCursor(Qt.SplitHCursor)
            self._drag_create(x)
            return
        if self._timing is not None:
            if not self._timing.active:
                if abs(dx) < _CLICK_SLOP:
                    return
                self._timing.active = True
                self.setCursor(Qt.ClosedHandCursor if self._timing.mode == "move"
                               else Qt.SplitHCursor)
            self._drag_timing(x, snap=not event.modifiers() & Qt.ShiftModifier)
            return
        if not (self._panning or self._scrubbing):
            if abs(dx) < _CLICK_SLOP:
                return
            if event.modifiers() & Qt.AltModifier:
                self._panning = True
                self.setCursor(Qt.ClosedHandCursor)
            else:
                self._scrubbing = True
                self.setCursor(Qt.SizeHorCursor)
        span = self._view_end_ms - self._view_start_ms
        if self.width() <= 0 or span <= 0:
            return
        if self._panning:
            self._set_view(self._drag_start_view - dx * span / self.width(), span)
            self._hold_follow()
        else:
            self._scrub_to(x)

    def _scrub_to(self, x: float) -> None:
        """Scrub: il playhead segue il mouse. Oltre i bordi, con zoom, la vista scorre."""
        span = self._view_end_ms - self._view_start_ms
        w = self.width()
        if x < 0 or x > w:
            over = x if x < 0 else x - w
            self._set_view(self._view_start_ms + over * span / w, span)
        x = min(max(x, 0.0), float(w))
        ms = self._view_start_ms + x / w * span
        ms = int(min(max(ms, 0.0), float(self._duration_ms)))
        if ms != self._playhead_ms:
            self.seek_requested.emit(ms)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self._pressed:
            return
        self._pressed = False
        drag, self._timing = self._timing, None
        create, self._creating = self._creating, None
        if create is not None and create.active:
            self.unsetCursor()
            self._invalidate()
            if create.block is not None:
                s, e = create.block
                self.subtitle_created.emit(s / 1000.0, e / 1000.0)
            return
        if drag is not None and drag.active:
            self._finish_timing(drag)
            self._update_hover_cursor(event.position().x(), event.position().y())
            return
        if self._panning or self._scrubbing:
            # lo scrub ha già spostato il playhead: resta dove si è lasciato il mouse
            self._panning = self._scrubbing = False
            self.unsetCursor()
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

    def mouseDoubleClickEvent(self, event):
        """Doppio clic: nella corsia vuota crea un sottotitolo (``NEW_BLOCK_S``), sulla forma
        d'onda torna a tutta la durata. Su un blocco: come un click."""
        pos = event.position()
        if event.button() == Qt.LeftButton and self._row_at(pos.x(), pos.y()) < 0:
            self._pressed = False      # il rilascio che segue non è un secondo click
            self._creating = None
            if self._in_lane(pos.y()) and self._duration_ms > 0:
                block = timing_edit.default_block(
                    self._times(), self._x_to_ms(pos.x()), NEW_BLOCK_S * 1000.0,
                    timing_edit.MIN_DURATION_S * 1000.0, self._duration_ms)
                if block is not None:
                    self.subtitle_created.emit(block[0] / 1000.0, block[1] / 1000.0)
            else:
                self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        """
        Rotella / due dita: scorre la finestra visibile (solo se c'è zoom).
        Ctrl/⌘ o Alt + rotella: zoom attorno al cursore. Il playhead non si muove.
        """
        span = self._view_end_ms - self._view_start_ms
        if span <= 0 or self._duration_ms == 0:
            event.ignore()
            return
        angle = event.angleDelta()
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier):
            # con Alt alcune piattaforme consegnano la rotella verticale come orizzontale
            d = angle.y() if abs(angle.y()) >= abs(angle.x()) else angle.x()
            if d:
                self.zoom_at(event.position().x(), max(0.1, min(10.0, 1.0 - d / 1200.0)))
            event.accept()
            return
        pixel = event.pixelDelta()
        if not pixel.isNull():
            # trackpad: spostamento in pixel 1:1 con le dita (verso già "naturale")
            px = pixel.x() if abs(pixel.x()) > abs(pixel.y()) else pixel.y()
            delta_ms = -px * span / max(1, self.width())
        else:
            d = angle.x() if abs(angle.x()) > abs(angle.y()) else angle.y()
            delta_ms = -d / 120.0 * span * _WHEEL_PAN_FRACTION
        if span >= self._duration_ms:
            event.ignore()             # tutta la durata già visibile: niente da scorrere
            return
        if delta_ms:
            self.pan_by(delta_ms)
        event.accept()

    def native_gesture(self, event) -> bool:
        """
        Pizzico sul trackpad (macOS): zoom attorno al cursore; doppio tocco: tutto.
        Chiamato da `_GestureFilter` (niente override di `event()`: riceverebbe anche
        gli eventi della distruzione del widget). True se il gesto è stato gestito.
        """
        gesture = event.gestureType()
        if gesture == Qt.ZoomNativeGesture:
            self.zoom_by_pinch(event.position().x(), event.value())
        elif gesture == Qt.SmartZoomNativeGesture:
            self.reset_zoom()
        elif gesture not in (Qt.BeginNativeGesture, Qt.EndNativeGesture):
            return False
        event.accept()
        return True

    def keyPressEvent(self, event):
        """←/→ ±1 s, Home/Fine, +/− zoom attorno al playhead, 0 tutta la durata."""
        key = event.key()
        if key == Qt.Key_Escape and (self._timing is not None or self._creating is not None):
            # annulla il trascinamento in corso: il blocco torna dov'era
            self._timing = None
            self._creating = None
            self._pressed = False
            self.unsetCursor()
            self._invalidate()
            event.accept()
            return
        if event.modifiers() & ~Qt.KeypadModifier:
            super().keyPressEvent(event)
            return
        if key in (Qt.Key_Left, Qt.Key_Right) and self._duration_ms > 0:
            step = -_KEY_SEEK_MS if key == Qt.Key_Left else _KEY_SEEK_MS
            self.seek_requested.emit(max(0, min(self._duration_ms, self._playhead_ms + step)))
        elif key == Qt.Key_Home and self._duration_ms > 0:
            self.seek_requested.emit(0)
        elif key == Qt.Key_End and self._duration_ms > 0:
            self.seek_requested.emit(self._duration_ms)
        elif key in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus):
            x = self._ms_to_x(self._playhead_ms)
            x = self.width() / 2 if x is None else x
            self.zoom_at(x, _KEY_ZOOM if key != Qt.Key_Minus else 1.0 / _KEY_ZOOM)
        elif key == Qt.Key_0:
            self.reset_zoom()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    # ----------------------------------------------------------------
    # Modifica dei tempi trascinando i blocchi
    # ----------------------------------------------------------------

    def _hit_block(self, x: float, y: float) -> Tuple[int, Optional[str]]:
        """(riga, "start" | "end" | "move") del blocco sotto (x, y), oppure (-1, None).

        I bordi si afferrano a ±_EDGE_GRAB_PX; tra due blocchi che si toccano vince
        quello dal lato del mouse.
        """
        block_y, block_h = self._block_geometry(self.height())
        span = self._view_end_ms - self._view_start_ms
        if (y < block_y or y > block_y + block_h or self._duration_ms == 0
                or span <= 0 or self.width() <= 0):
            return -1, None
        ms = self._x_to_ms(x)
        grab = _EDGE_GRAB_PX * span / self.width()
        best_row, best_mode, best_d = -1, None, math.inf
        inside = -1
        for start, end, row in self._visible_subs(ms - grab, ms + grab):
            for edge, mode, own_side in ((start, "start", ms >= start),
                                         (end, "end", ms <= end)):
                d = abs(ms - edge) + (0.0 if own_side else grab * 1e-3)
                if d <= grab and d < best_d:
                    best_row, best_mode, best_d = row, mode, d
            if start <= ms <= end:
                inside = row
        if best_row >= 0:
            return best_row, best_mode
        if inside >= 0:
            return inside, "move"
        return -1, None

    def _update_hover_cursor(self, x: float, y: float) -> None:
        _, mode = self._hit_block(x, y)
        if mode in ("start", "end"):
            self.setCursor(Qt.SplitHCursor)
        elif mode == "move":
            self.setCursor(Qt.OpenHandCursor)
        elif self._in_lane(y) and self._duration_ms > 0:
            self.setCursor(Qt.CrossCursor)      # qui si disegna un sottotitolo nuovo
        else:
            self.unsetCursor()

    def _snap(self, value: float, tol: float, drag: _TimingDrag) -> Tuple[float, Optional[float]]:
        """``value`` agganciato al playhead o ai bordi dei vicini, se è entro ``tol``."""
        lo, hi = timing_edit.neighbour_limits(drag.times, drag.row, self._duration_ms or None)
        best = None
        for target in (self._playhead_ms, lo, hi):
            if math.isfinite(target) and abs(target - value) <= tol and (
                    best is None or abs(target - value) < abs(best - value)):
                best = target
        return (value, None) if best is None else (best, best)

    def _drag_timing(self, x: float, snap: bool = True) -> None:
        """Nuovi tempi del blocco afferrato per il mouse in ``x``."""
        drag = self._timing
        w = self.width()
        span = self._view_end_ms - self._view_start_ms
        if drag is None or w <= 0 or span <= 0:
            return
        if (x < 0 or x > w) and self.is_zoomed():
            # oltre i bordi la vista scorre, come nello scrub
            over = x if x < 0 else x - w
            self._set_view(self._view_start_ms + over * span / w, span)
        x = min(max(x, 0.0), float(w))
        delta = self._x_to_ms(x) - drag.press_ms
        tol = _SNAP_PX * span / w if snap else -1.0
        media_end = self._duration_ms or None
        min_ms = timing_edit.MIN_DURATION_S * 1000.0
        drag.snap_ms = None
        if drag.mode == "start":
            value, snapped = self._snap(drag.start + delta, tol, drag)
            drag.new_start = timing_edit.trim_start(drag.times, drag.row, value, min_ms,
                                                    media_end)
            drag.new_end = drag.end
            drag.snap_ms = snapped if snapped == drag.new_start else None
        elif drag.mode == "end":
            value, snapped = self._snap(drag.end + delta, tol, drag)
            drag.new_end = timing_edit.trim_end(drag.times, drag.row, value, min_ms,
                                                media_end)
            drag.new_start = drag.start
            drag.snap_ms = snapped if snapped == drag.new_end else None
        else:
            s_val, s_snap = self._snap(drag.start + delta, tol, drag)
            e_val, e_snap = self._snap(drag.end + delta, tol, drag)
            if s_snap is not None and (e_snap is None or abs(s_val - drag.start - delta)
                                       <= abs(e_val - drag.end - delta)):
                delta, snapped = s_val - drag.start, s_snap
            elif e_snap is not None:
                delta, snapped = e_val - drag.end, e_snap
            else:
                snapped = None
            drag.new_start, drag.new_end = timing_edit.move(drag.times, drag.row, delta,
                                                            media_end)
            if snapped is not None and snapped in (drag.new_start, drag.new_end):
                drag.snap_ms = snapped
            self._cross_neighbours(drag, self._x_to_ms(x), media_end)
        self._invalidate()

    def _cross_neighbours(self, drag: _TimingDrag, at: float,
                          media_end: Optional[float]) -> None:
        """Mouse oltre lo spazio del blocco: scambio con il blocco sotto il mouse, posto in
        un'altra pausa o niente (il blocco segue il mouse e al rilascio torna indietro)."""
        drag.target, drag.target_row = None, -1
        lo, hi = timing_edit.neighbour_limits(drag.times, drag.row, media_end)
        if lo <= at <= hi:
            return
        drag.snap_ms = None
        offset = drag.press_ms - drag.start          # punto del blocco preso col mouse
        ghost = (at - offset, at - offset + (drag.end - drag.start))
        other = timing_edit.row_at(drag.times, at, drag.row)
        if other >= 0:
            # il blocco resta al suo posto (tratteggiato): si vede bene quello di arrivo
            drag.target, drag.target_row = "swap", other
            drag.new_start, drag.new_end = drag.times[other]
            return
        slot = timing_edit.free_slot(drag.times, drag.row, at, media_end)
        if slot is not None:
            drag.target = "slot"
            drag.new_start, drag.new_end = slot
        else:
            drag.target = "none"
            drag.new_start, drag.new_end = ghost

    def _drag_create(self, x: float) -> None:
        """Sottotitolo nuovo da dove si è premuto fino al mouse, dentro quella pausa."""
        create = self._creating
        w = self.width()
        span = self._view_end_ms - self._view_start_ms
        if create is None or w <= 0 or span <= 0:
            return
        if (x < 0 or x > w) and self.is_zoomed():
            over = x if x < 0 else x - w
            self._set_view(self._view_start_ms + over * span / w, span)
        x = min(max(x, 0.0), float(w))
        create.block = timing_edit.new_block(
            create.times, create.press_ms, self._x_to_ms(x),
            timing_edit.MIN_DURATION_S * 1000.0, self._duration_ms or None)
        self._invalidate()

    def _finish_timing(self, drag: _TimingDrag) -> None:
        """Fine del trascinamento: segnale con i nuovi tempi (se sono cambiati)."""
        self.unsetCursor()
        if drag.target in ("swap", "none"):
            self._invalidate()
            if drag.target == "swap":
                self.subtitles_swapped.emit(drag.row, drag.target_row)
            return
        if abs(drag.new_start - drag.start) < 0.5 and abs(drag.new_end - drag.end) < 0.5:
            self._invalidate()
            return
        # I blocchi restano dove sono stati lasciati finché arrivano i sottotitoli nuovi
        # (la sincronizzazione della preview è raggruppata): niente salto indietro
        self._sub_index = sorted(
            (drag.new_start, drag.new_end, r) if r == drag.row else (s, e, r)
            for s, e, r in self._sub_index)
        self._sub_starts = [e[0] for e in self._sub_index]
        self._max_sub_ms = max((e[1] - e[0] for e in self._sub_index), default=0.0)
        self._invalidate()
        signal = self.subtitle_moved if drag.target == "slot" else self.timing_edited
        signal.emit(drag.row, drag.new_start / 1000.0, drag.new_end / 1000.0)

    # ----------------------------------------------------------------
    # Zoom / scorrimento della vista (mai il playhead)
    # ----------------------------------------------------------------

    def is_zoomed(self) -> bool:
        """True se la finestra visibile è più corta della durata."""
        return 0 < self._view_end_ms - self._view_start_ms < self._duration_ms

    def _set_view(self, start_ms: float, span_ms: float) -> bool:
        """Imposta la finestra visibile (limitata alla durata). True se è cambiata."""
        if self._duration_ms <= 0 or span_ms <= 0:
            return False
        span_ms = min(float(self._duration_ms), span_ms)
        start_ms = max(0.0, min(float(self._duration_ms) - span_ms, start_ms))
        if (abs(start_ms - self._view_start_ms) < 1e-6
                and abs(start_ms + span_ms - self._view_end_ms) < 1e-6):
            return False
        self._view_start_ms = start_ms
        self._view_end_ms = start_ms + span_ms
        self.update()
        return True

    def pan_by(self, delta_ms: float) -> bool:
        """Scorre la finestra visibile di `delta_ms` (solo con zoom attivo)."""
        if not self.is_zoomed():
            return False
        span = self._view_end_ms - self._view_start_ms
        self._hold_follow()
        return self._set_view(self._view_start_ms + delta_ms, span)

    def zoom_at(self, x: float, factor: float) -> bool:
        """Zoom di `factor` (< 1 avvicina) tenendo fermo l'istante sotto la x data."""
        span = self._view_end_ms - self._view_start_ms
        if span <= 0 or self._duration_ms == 0 or factor <= 0:
            return False
        center_ms = self._x_to_ms(x)
        new_span = max(_MIN_SPAN_MS, min(float(self._duration_ms), span * factor))
        frac = (center_ms - self._view_start_ms) / span
        self._hold_follow()
        return self._set_view(center_ms - frac * new_span, new_span)

    def zoom_by_pinch(self, x: float, value: float) -> bool:
        """Pizzico: `value` è la variazione di scala del gesto (> 0 = dita che si aprono)."""
        return self.zoom_at(x, 1.0 / (1.0 + max(-0.9, value)))

    def zoom_around_playhead(self, span_ms: float) -> None:
        """Mostra ``span_ms`` attorno al playhead (solo se la vista è più larga)."""
        span = self._view_end_ms - self._view_start_ms
        if self._duration_ms <= 0 or span <= span_ms:
            return
        self.resume_follow()
        self._set_view(self._playhead_ms - span_ms * 0.3, span_ms)

    def reset_zoom(self) -> None:
        """Mostra tutta la durata (e riattiva subito l'auto-scroll)."""
        self.resume_follow()
        if self._duration_ms > 0:
            self._set_view(0.0, float(self._duration_ms))

    def _hold_follow(self) -> None:
        self._follow_hold_until = self._clock() + FOLLOW_HOLD_S

    def resume_follow(self) -> None:
        """Riattiva subito l'auto-scroll del playhead."""
        self._follow_hold_until = 0.0

    def on_seeked(self, ms: int) -> None:
        """
        Seek esplicito (AudioPlayer.seeked, emesso prima di position_changed): riattiva
        l'auto-scroll e, per la posizione appena chiesta, la vista si sposta solo se il
        playhead finisce FUORI dalla finestra (un click vicino al bordo non la fa saltare).
        """
        self.resume_follow()
        self._seek_target = int(ms)

    def _follow_suspended(self) -> bool:
        return self._clock() < self._follow_hold_until

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _times(self) -> list:
        """[(inizio, fine)] in ms di ogni sottotitolo, per riga."""
        times = [(0.0, 0.0)] * len(self._subtitles)
        for start, end, r in self._sub_index:
            if r < len(times):
                times[r] = (start, end)
        return times

    def _in_lane(self, y: float) -> bool:
        """True se ``y`` è nella corsia dei blocchi, sotto la forma d'onda."""
        return y >= self.height() - _LANE_H

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
        if self._follow_suspended():
            return False
        span = self._view_end_ms - self._view_start_ms
        # in riproduzione si scorre prima del bordo; dopo un seek solo se è fuori vista
        margin = 0.0 if self._playhead_ms == self._seek_target else span * 0.15
        if self._view_start_ms + margin <= self._playhead_ms <= self._view_end_ms - margin:
            return False
        new_start = self._playhead_ms - span * 0.2
        new_start = max(0.0, min(float(self._duration_ms) - span, new_start))
        if abs(new_start - self._view_start_ms) < 1e-6:
            return False
        self._view_start_ms = new_start
        self._view_end_ms = new_start + span
        return True
