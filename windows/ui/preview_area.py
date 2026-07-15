"""
preview_area.py — Area preview centrale (Editor, Stato 2).

Mostra video oppure waveform in base al tipo di file:
  - Video (.mp4 .mkv .mov .avi .webm) → QVideoWidget embedded
  - Solo audio (.mp3 .wav .flac .m4a .ogg .aac) → WaveformWidget

Layout:
  ┌─────────────────────────────────────────┐
  │  timecode bar  (HH:MM:SS.mmm / totale)  │
  ├─────────────────────────────────────────┤
  │  QStackedWidget                         │
  │    [0] VideoWidget  (QVideoWidget)      │
  │    [1] WaveformWidget                   │
  ├─────────────────────────────────────────┤
  │  TransportBar                           │
  └─────────────────────────────────────────┘
"""

from __future__ import annotations
import logging
import tempfile
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, Signal, QRectF, QSizeF
from PySide6.QtGui import QFont, QPainter, QColor, QFontMetrics, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QSizePolicy, QStackedWidget, QGraphicsView, QGraphicsScene,
)

from core.subtitle_model import Subtitle
from core.audio_player import AudioPlayer
from core.constants import SUPPORTED_VIDEO_EXTS
from ui.waveform_widget import WaveformWidget
from ui.transport_bar import TransportBar

logger = logging.getLogger(__name__)

_PREVIEW_VIDEO    = 0
_PREVIEW_WAVEFORM = 1


def _is_video(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTS


class PreviewArea(QWidget):
    """Zona preview: video o waveform + transport bar."""

    seek_requested = Signal(int)   # ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.player = AudioPlayer(self)
        self._overlay_subs: List[Subtitle] = []
        self._subtitle_overlay = None
        self._video_player_view: _VideoPlayerView | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Timecode bar ───────────────────────────────────────────────────────
        tc_bar = QWidget()
        tc_bar.setFixedHeight(28)
        tc_bar.setStyleSheet("background-color: #111114; border-bottom: 1px solid #22222a;")
        tc_layout = QHBoxLayout(tc_bar)
        tc_layout.setContentsMargins(12, 0, 12, 0)

        self.timecode_lbl = QLabel("00:00.000")
        # Font monospace: "Consolas" presente su Windows, "SF Mono" su macOS
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(11)
        font.setWeight(QFont.Medium)
        self.timecode_lbl.setFont(font)
        self.timecode_lbl.setStyleSheet("color: #e4e4ef; background: transparent;")
        tc_layout.addWidget(self.timecode_lbl)

        self.duration_lbl = QLabel("/ 00:00.000")
        self.duration_lbl.setStyleSheet(
            "color: #5a5a6a; font-size: 11px; background: transparent;"
        )
        tc_layout.addWidget(self.duration_lbl)
        tc_layout.addStretch(1)

        self.file_lbl = QLabel("")
        self.file_lbl.setStyleSheet(
            "color: #5a5a6a; font-size: 11px; background: transparent;"
        )
        tc_layout.addWidget(self.file_lbl)
        layout.addWidget(tc_bar)

        # ── Area preview (stack: video | waveform) ─────────────────────────────
        self._preview_stack = QStackedWidget()
        self._preview_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._video_widget = self._build_video_widget()
        self._preview_stack.addWidget(self._video_widget)   # index 0

        self.waveform = WaveformWidget()
        self.waveform.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._preview_stack.addWidget(self.waveform)        # index 1

        layout.addWidget(self._preview_stack, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #111114; max-height: 1px;")
        layout.addWidget(sep)

        # ── Transport bar ──────────────────────────────────────────────────────
        self.transport = TransportBar()
        self.transport.bind_player(self.player)
        layout.addWidget(self.transport)

        # ── Wiring player ──────────────────────────────────────────────────────
        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.position_changed.connect(self.waveform.set_position)
        self.player.duration_changed.connect(self.waveform.set_duration)
        self.player.source_ready.connect(
            lambda: self.waveform.set_duration(self.player.duration())
        )
        self.player.error_occurred.connect(
            lambda msg: logger.error("[PreviewArea] errore player: %s", msg)
        )
        self.waveform.seek_requested.connect(self.player.seek)
        self.waveform.seek_requested.connect(self.seek_requested)
        self.player.position_changed.connect(self._update_subtitle_overlay)

    # ── Build video widget ─────────────────────────────────────────────────────

    def _build_video_widget(self) -> QWidget:
        """
        Crea un _VideoPlayerView (QGraphicsView + QGraphicsVideoItem).
        Su Windows QGraphicsVideoItem usa Direct3D / Media Foundation.
        Se PySide6-QtMultimediaWidgets non è installato, mostra placeholder.
        """
        try:
            from PySide6.QtMultimediaWidgets import QGraphicsVideoItem  # noqa: F401
            view = _VideoPlayerView()
            view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self._qvideo_widget = view
            self._video_player_view = view
            self._subtitle_overlay = view
            logger.debug("[PreviewArea] VideoPlayerView creato con QGraphicsVideoItem")
            return view
        except ImportError:
            logger.warning(
                "[PreviewArea] PySide6-QtMultimediaWidgets non disponibile: "
                "player video disabilitato"
            )
            self._qvideo_widget = None
            self._subtitle_overlay = None
            self._video_player_view = None
            placeholder = QLabel(
                "Video preview non disponibile\n"
                "(PySide6-QtMultimediaWidgets non installato)"
            )
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: #5a5a6a; background: #0a0a0d;")
            return placeholder
        except Exception as exc:
            logger.exception("[PreviewArea._build_video_widget] errore inatteso: %s", exc)
            self._qvideo_widget = None
            self._subtitle_overlay = None
            self._video_player_view = None
            placeholder = QLabel(f"Errore inizializzazione video:\n{exc}")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: #c0392b; background: #0a0a0d;")
            return placeholder

    # ── API pubblica ───────────────────────────────────────────────────────────

    def load_media(self, file_path: str):
        """
        Carica un file media nel player.
        Video → mostra QVideoWidget; audio → mostra WaveformWidget.
        """
        self.waveform.reset()
        self._overlay_subs = []
        if self._subtitle_overlay is not None:
            self._subtitle_overlay.set_text("")
        self.player.load(file_path)
        self.file_lbl.setText(Path(file_path).name)
        logger.debug("[PreviewArea.load_media] caricamento: %s", file_path)

        if _is_video(file_path) and self._qvideo_widget is not None:
            try:
                self.player._player.setVideoOutput(self._video_player_view.video_item())
            except (AttributeError, Exception) as exc:
                logger.warning("[PreviewArea.load_media] setVideoOutput fallito: %s", exc)
            self._preview_stack.setCurrentIndex(_PREVIEW_VIDEO)
        else:
            self._preview_stack.setCurrentIndex(_PREVIEW_WAVEFORM)
            wav_path = self._resolve_wav(file_path)
            self.waveform.load_audio(wav_path)

    def load_audio(self, file_path: str):
        """Alias mantenuto per compatibilità con codice esistente."""
        self.load_media(file_path)

    def set_subtitles(self, subs: List[Subtitle], severity: List[str]):
        self._overlay_subs = list(subs)
        self.waveform.set_subtitles(subs, severity)
        self._update_subtitle_overlay(self.player.position())

    def set_selected_row(self, row: int):
        self.waveform.set_selected_row(row)

    # ── Slots player ───────────────────────────────────────────────────────────

    def _on_position(self, ms: int):
        self.timecode_lbl.setText(_fmt_tc(ms))

    def _on_duration(self, ms: int):
        self.duration_lbl.setText(f"/ {_fmt_tc(ms)}")

    def _update_subtitle_overlay(self, ms: int):
        if self._subtitle_overlay is None:
            return
        if self._preview_stack.currentIndex() != _PREVIEW_VIDEO:
            return
        pos_s = ms / 1000.0
        text = ""
        for sub in self._overlay_subs:
            if sub.start <= pos_s <= sub.end:
                text = sub.text.strip()
                break
        self._subtitle_overlay.set_text(text)

    # ── Utility ────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_wav(file_path: str) -> str:
        """
        Cerca un file WAV pre-estratto dal worker.
        Usa tempfile.gettempdir() — cross-platform, funziona su Windows.
        """
        path = Path(file_path)
        tmp_dir = Path(tempfile.gettempdir())
        candidates = [
            path.with_suffix(".wav"),
            tmp_dir / (path.stem + "_16k.wav"),
            tmp_dir / (path.stem + ".wav"),
        ]
        for c in candidates:
            if c.exists():
                logger.debug("[PreviewArea._resolve_wav] WAV trovato: %s", c)
                return str(c)
        logger.debug("[PreviewArea._resolve_wav] nessun WAV trovato, uso originale")
        return file_path


class _VideoPlayerView(QGraphicsView):
    """
    Player video con overlay sottotitoli: QGraphicsView + QGraphicsVideoItem.
    Su Windows usa Direct3D 11 via Qt Multimedia (Media Foundation backend).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

        self._subtitle_text = ""
        self._font = QFont("Segoe UI", 10)
        self._font.setWeight(QFont.DemiBold)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._vitem = QGraphicsVideoItem()
        self._scene.addItem(self._vitem)

        self.setStyleSheet("background: #0a0a0d; border: none;")
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.Antialiasing)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def video_item(self):
        return self._vitem

    def set_text(self, text: str):
        if text != self._subtitle_text:
            self._subtitle_text = text
            self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_video()

    def _fit_video(self):
        vp = self.viewport()
        w, h = vp.width(), vp.height()
        if w <= 0 or h <= 0:
            return
        self._vitem.setSize(QSizeF(w, h))
        self._vitem.setPos(0, 0)
        self.setSceneRect(0, 0, w, h)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._subtitle_text:
            return

        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setFont(self._font)

        fm = QFontMetrics(self._font)
        vp_w = self.viewport().width()
        vp_h = self.viewport().height()
        padding_h = 14
        padding_v = 7
        max_text_w = int(vp_w * 0.88)

        lines: list[str] = []
        for raw_line in self._subtitle_text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            words = raw_line.split()
            current = ""
            for word in words:
                test = (current + " " + word).strip()
                if fm.horizontalAdvance(test) <= max_text_w - padding_h * 2:
                    current = test
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)

        if not lines:
            p.end()
            return

        line_h = fm.height()
        box_h = line_h * len(lines) + padding_v * 2
        box_w = min(
            max(fm.horizontalAdvance(l) for l in lines) + padding_h * 2,
            max_text_w,
        )
        box_x = (vp_w - box_w) // 2
        box_y = vp_h - box_h - 14

        p.setBrush(QBrush(QColor(0, 0, 0, 178)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(box_x, box_y, box_w, box_h, 5, 5)

        p.setPen(QPen(QColor(255, 255, 255)))
        for i, line in enumerate(lines):
            lw = fm.horizontalAdvance(line)
            lx = box_x + (box_w - lw) // 2
            ly = box_y + padding_v + fm.ascent() + i * line_h
            p.drawText(lx, ly, line)

        p.end()


def _fmt_tc(ms: int) -> str:
    """ms → MM:SS.mmm  (ore solo se > 0)."""
    total_ms = max(0, ms)
    mmm = total_ms % 1000
    total_s = total_ms // 1000
    secs = total_s % 60
    total_m = total_s // 60
    mins = total_m % 60
    hrs = total_m // 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}.{mmm:03d}"
    return f"{mins:02d}:{secs:02d}.{mmm:03d}"
