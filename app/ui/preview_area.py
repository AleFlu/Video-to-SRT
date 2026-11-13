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
from ui import theme
import platform_support

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

        # Sottotitoli correnti per l'overlay video
        self._overlay_subs: List[Subtitle] = []
        self._subtitle_overlay = None   # impostato da _build_video_widget
        self._video_player_view: _VideoPlayerView | None = None   # idem

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Timecode bar ───────────────────────────────────────────────────────
        self._tc_bar = QWidget()
        self._tc_bar.setFixedHeight(34)
        tc_layout = QHBoxLayout(self._tc_bar)
        tc_layout.setContentsMargins(16, 0, 16, 0)
        tc_layout.setSpacing(14)

        self.timecode_lbl = QLabel("00:00.000")
        font = QFont(platform_support.mono_font_family(), 14)
        font.setStyleHint(QFont.Monospace)
        font.setWeight(QFont.DemiBold)
        self.timecode_lbl.setFont(font)
        tc_layout.addWidget(self.timecode_lbl)

        self.duration_lbl = QLabel("durata 00:00.000")
        tc_layout.addWidget(self.duration_lbl)
        tc_layout.addStretch(1)

        self.file_lbl = QLabel("")
        tc_layout.addWidget(self.file_lbl)

        layout.addWidget(self._tc_bar)

        # ── Area preview (stack: video | waveform) ─────────────────────────────
        self._preview_stack = QStackedWidget()
        self._preview_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Slot 0: VideoWidget
        self._video_widget = self._build_video_widget()
        self._preview_stack.addWidget(self._video_widget)   # index 0

        # Collega il player al video item UNA SOLA VOLTA durante costruzione
        if self._video_player_view is not None:
            try:
                self.player._player.setVideoOutput(self._video_player_view.video_item())
            except Exception:  # noqa: BLE001
                logger.warning("Collegamento uscita video fallito", exc_info=True)

        # Slot 1: WaveformWidget
        self.waveform = WaveformWidget()
        self.waveform.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._preview_stack.addWidget(self.waveform)         # index 1

        layout.addWidget(self._preview_stack, 1)

        # ── Separatore ────────────────────────────────────────────────────────
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.HLine)
        layout.addWidget(self._sep)

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
        self.waveform.seek_requested.connect(self.player.seek)
        self.waveform.seek_requested.connect(self.seek_requested)

        # Aggiorna overlay sottotitoli ad ogni tick player
        self.player.position_changed.connect(self._update_subtitle_overlay)

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    # ── Tema ─────────────────────────────────────────────────────────────────

    def _apply_palette(self):
        c = theme.c
        self._tc_bar.setStyleSheet(
            f"background-color: {c('surface')}; border-bottom: 1px solid {c('line')};"
        )
        self.timecode_lbl.setStyleSheet(f"color: {c('text')}; background: transparent;")
        self.duration_lbl.setStyleSheet(
            f"color: {c('muted')}; font-size: 12px; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self.file_lbl.setStyleSheet(
            f"color: {c('muted')}; font-size: 11px; background: transparent;"
        )
        self._sep.setStyleSheet(f"background-color: {c('line')}; max-height: 1px;")

    # ── Build video widget ─────────────────────────────────────────────────────

    def _build_video_widget(self) -> QWidget:
        """
        Crea un VideoPlayerView (QGraphicsView + QGraphicsVideoItem).

        Su macOS QVideoWidget usa NSView nativa che si renderizza sopra qualsiasi
        widget Qt — nessun overlay è possibile. QGraphicsVideoItem invece è
        renderizzato interamente da Qt, quindi QGraphicsTextItem/paintEvent
        sopra di esso funziona correttamente.

        Il QMediaPlayer viene collegato a QGraphicsVideoItem come output.
        """
        try:
            from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

            view = _VideoPlayerView()
            view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            # _qvideo_widget è usato da load_media() per setVideoOutput
            # qui usiamo il QGraphicsVideoItem come output
            self._qvideo_widget = view   # segnala "video disponibile"
            self._video_player_view = view
            self._subtitle_overlay = view   # stessa API: set_text()
            return view

        except ImportError:
            self._qvideo_widget = None
            self._subtitle_overlay = None
            self._video_player_view = None
            placeholder = QLabel("Video preview non disponibile\n(PySide6-QtMultimediaWidgets non installato)")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(
                f"color: {theme.c('muted')}; background: {theme.c('surface')};"
            )
            return placeholder
        except Exception:  # noqa: BLE001
            logger.exception("Creazione del widget video fallita")
            self._qvideo_widget = None
            self._subtitle_overlay = None
            self._video_player_view = None
            placeholder = QLabel("Errore nell'inizializzazione dell'anteprima video\n(vedi il file di log)")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(
                f"color: {theme.c('muted')}; background: {theme.c('surface')};"
            )
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
        if platform_support.IS_WIN and self._video_player_view is not None:
            # Su Windows l'uscita video va ricollegata a ogni caricamento
            try:
                self.player._player.setVideoOutput(self._video_player_view.video_item())
            except Exception:  # noqa: BLE001
                logger.warning("Ricollegamento uscita video fallito", exc_info=True)
        self.file_lbl.setText(Path(file_path).name)

        if _is_video(file_path) and self._qvideo_widget is not None:
            self._preview_stack.setCurrentIndex(_PREVIEW_VIDEO)
        else:
            # Fallback waveform
            self._preview_stack.setCurrentIndex(_PREVIEW_WAVEFORM)
            self.waveform.load_audio(file_path)

    def clear_media(self):
        """Nessun media associato al progetto: svuota player, waveform e overlay."""
        self.waveform.reset()
        self._overlay_subs = []
        if self._subtitle_overlay is not None:
            self._subtitle_overlay.set_text("")
        self.player.unload()
        self.file_lbl.setText("")
        self._preview_stack.setCurrentIndex(_PREVIEW_WAVEFORM)

    # Alias mantenuto per compatibilità con codice esistente
    def load_audio(self, file_path: str):
        self.load_media(file_path)

    def set_subtitles(self, subs: List[Subtitle], severity: List[str]):
        self._overlay_subs = list(subs)
        self.waveform.set_subtitles(subs, severity)
        # Aggiorna subito l'overlay alla posizione corrente
        self._update_subtitle_overlay(self.player.position())

    def set_selected_row(self, row: int):
        self.waveform.set_selected_row(row)

    # ── Slots player ───────────────────────────────────────────────────────────

    def _on_position(self, ms: int):
        self.timecode_lbl.setText(_fmt_tc(ms))

    def _on_duration(self, ms: int):
        self.duration_lbl.setText(f"durata {_fmt_tc(ms)}")

    def _update_subtitle_overlay(self, ms: int):
        """
        Aggiorna il testo dell'overlay in base alla posizione corrente.
        Attivo solo quando è visibile il video (non la waveform).
        """
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


class _VideoPlayerView(QGraphicsView):
    """
    Player video con overlay sottotitoli basato su QGraphicsView + QGraphicsVideoItem.

    QGraphicsVideoItem è renderizzato interamente da Qt (non NSView nativa),
    quindi qualsiasi QGraphicsItem disegnato sopra di esso è visibile.
    Il testo del sottotitolo viene disegnato direttamente nel paintEvent
    della view, sopra la scena video.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

        self._subtitle_text = ""
        self._font = QFont()
        self._font.setPixelSize(18)
        self._font.setWeight(QFont.DemiBold)

        # Scena e item video
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._vitem = QGraphicsVideoItem()
        self._scene.addItem(self._vitem)

        # Stile view: niente bordi, sfondo nero
        self.setStyleSheet("background: #0a0a0d; border: none;")
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.Antialiasing)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def video_item(self):
        """Restituisce il QGraphicsVideoItem da passare a setVideoOutput()."""
        return self._vitem

    def set_text(self, text: str):
        """Aggiorna il testo del sottotitolo overlay."""
        if text != self._subtitle_text:
            self._subtitle_text = text
            self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_video()

    def _fit_video(self):
        """Adatta il QGraphicsVideoItem alle dimensioni correnti della view."""
        vp = self.viewport()
        w, h = vp.width(), vp.height()
        if w <= 0 or h <= 0:
            return
        self._vitem.setSize(QSizeF(w, h))
        self._vitem.setPos(0, 0)
        self.setSceneRect(0, 0, w, h)

    def paintEvent(self, event):
        # Prima disegna il video (la scena)
        super().paintEvent(event)

        # Poi disegna il testo in overlay se presente
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

        # Wrapping manuale
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
        box_y = vp_h - box_h - 14   # 14px dal fondo

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
