"""
preview_area.py — Zona alta dell'editor: monitor video + forma d'onda + trasporto.

Il monitor (sinistra, 452 px) e la forma d'onda (destra) sono affiancati quando il
file è un video; per un file solo audio il monitor si chiude e la forma d'onda
occupa tutta la larghezza. Senza media il monitor mostra "Nessun file caricato".

Layout:
  ┌────────────────┬──────────────────────────────────────┐
  │ monitor video  │ riga info (nome file · durata)  26px │
  │ (QStackedLayout│ righello 22 px                       │
  │  video / testo)│ forma d'onda                         │
  │   452 px       │ corsia sottotitoli 52 px             │
  ├────────────────┴──────────────────────────────────────┤
  │ TransportBar (46 px)                                  │
  └───────────────────────────────────────────────────────┘
"""

from __future__ import annotations
import bisect
import logging
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QSizeF
from PySide6.QtGui import QFont, QPainter, QFontMetrics, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLayout, QFrame,
    QSizePolicy, QStackedLayout, QGraphicsView, QGraphicsScene,
)

from core.subtitle_model import Subtitle
from core.audio_player import AudioPlayer
from core.constants import SUPPORTED_VIDEO_EXTS
from ui.waveform_widget import WaveformWidget
from ui.transport_bar import TransportBar, _ms_to_full_label
from ui import theme
from ui.widgets import ElidedLabel
import platform_support

logger = logging.getLogger(__name__)


# Pagine del monitor
_MONITOR_VIDEO   = 0
_MONITOR_MESSAGE = 1

# Misure del mockup
MONITOR_WIDTH = 452
TOP_ZONE_HEIGHT = 286
_INFO_LINE_HEIGHT = 26

# Modalità del monitor
MODE_EMPTY = "empty"   # nessun media: monitor con "Nessun file caricato"
MODE_VIDEO = "video"   # video: monitor e forma d'onda affiancati
MODE_AUDIO = "audio"   # solo audio: il monitor si chiude

_EMPTY_TEXT = "Nessun file caricato"


def _is_video(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTS


def monitor_mode(media_path: str, video_available: bool) -> str:
    """
    Decide come mostrare il monitor per `media_path`: vuoto (nessun media),
    video (monitor + forma d'onda) oppure audio (monitor chiuso). Un video senza
    uscita video disponibile (modulo multimediale assente) vale come solo audio.
    """
    if not media_path:
        return MODE_EMPTY
    if _is_video(media_path) and video_available:
        return MODE_VIDEO
    return MODE_AUDIO


class PreviewArea(QWidget):
    """Zona preview: monitor video + forma d'onda affiancati, poi la transport bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.player = AudioPlayer(self)

        # Sottotitoli correnti per l'overlay video
        self._overlay_subs: List[Subtitle] = []
        self._overlay_index: list = []    # [(start, end, testo)] ordinati per start
        self._overlay_starts: list = []
        self._media_path: str = ""
        self._mode: str = MODE_EMPTY
        self._subtitle_overlay = None   # impostato da _build_video_widget
        self._video_player_view: _VideoPlayerView | None = None   # idem

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Zona alta: monitor | colonna forma d'onda ──────────────────────────
        top = QWidget()
        top.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(0)

        # Monitor: cornice 452 px (padding 12) con il riquadro scuro da 1 px di linea
        self._monitor = QFrame()
        self._monitor.setObjectName("previewMonitor")
        mon_lay = QVBoxLayout(self._monitor)
        mon_lay.setContentsMargins(12, 12, 12, 12)
        mon_lay.setSpacing(0)
        mon_lay.setSizeConstraint(QLayout.SetNoConstraint)
        self._monitor.setFixedWidth(MONITOR_WIDTH)

        self._monitor_box = QFrame()
        self._monitor_box.setObjectName("previewMonitorBox")
        box_lay = QStackedLayout(self._monitor_box)
        box_lay.setContentsMargins(1, 1, 1, 1)
        self._monitor_stack = box_lay

        self._video_widget = self._build_video_widget()
        box_lay.addWidget(self._video_widget)               # 0: video

        self._monitor_msg = QLabel(_EMPTY_TEXT)
        self._monitor_msg.setAlignment(Qt.AlignCenter)
        self._monitor_msg.setWordWrap(True)
        box_lay.addWidget(self._monitor_msg)                # 1: testo (vuoto / errore)
        mon_lay.addWidget(self._monitor_box, 1)
        top_lay.addWidget(self._monitor)

        # Collega il player al video item UNA SOLA VOLTA durante costruzione
        if self._video_player_view is not None:
            try:
                self.player._player.setVideoOutput(self._video_player_view.video_item())
            except Exception:  # noqa: BLE001
                logger.warning("Collegamento uscita video fallito", exc_info=True)

        # Colonna destra: riga info (26 px) + forma d'onda (righello, onda, corsia)
        right = QWidget()
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        self._info_bar = QFrame()
        self._info_bar.setObjectName("previewInfo")
        info_lay = QHBoxLayout(self._info_bar)
        info_lay.setContentsMargins(12, 0, 12, 0)
        info_lay.setSpacing(12)
        info_lay.setSizeConstraint(QLayout.SetNoConstraint)
        self._info_bar.setFixedHeight(_INFO_LINE_HEIGHT)

        self.file_lbl = ElidedLabel("")
        self.file_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        info_lay.addWidget(self.file_lbl, 1)

        self.duration_lbl = QLabel("durata " + _ms_to_full_label(0))
        self.duration_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_lay.addWidget(self.duration_lbl)
        right_lay.addWidget(self._info_bar)

        self.waveform = WaveformWidget()
        self.waveform.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_lay.addWidget(self.waveform, 1)
        top_lay.addWidget(right, 1)

        layout.addWidget(top, 1)

        # ── Transport bar (46 px, con il proprio bordo inferiore) ──────────────
        self.transport = TransportBar()
        self.transport.bind_player(self.player)
        layout.addWidget(self.transport)

        # ── Wiring player ──────────────────────────────────────────────────────
        self.player.duration_changed.connect(self._on_duration)
        # seeked arriva prima di position_changed: la forma d'onda sa che è un seek
        # esplicito (riattiva l'auto-scroll, niente salto della vista per un click)
        self.player.seeked.connect(self.waveform.on_seeked)
        self.player.position_changed.connect(self.waveform.set_position)
        self.player.duration_changed.connect(self.waveform.set_duration)
        self.player.source_ready.connect(self._on_source_ready)
        self.waveform.seek_requested.connect(self.player.seek)
        # Errori di caricamento/decodifica: mai uno schermo nero muto
        self.player.error_occurred.connect(self._on_player_error)

        # Aggiorna overlay sottotitoli ad ogni tick player
        self.player.position_changed.connect(self._update_subtitle_overlay)

        self._set_mode(MODE_EMPTY)
        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    def sizeHint(self):  # noqa: N802 (override Qt)
        from PySide6.QtCore import QSize
        return QSize(900, TOP_ZONE_HEIGHT + self.transport.height())

    # ── Modalità del monitor ───────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        """Modalità corrente: "empty", "video" o "audio" (vedi `monitor_mode`)."""
        return self._mode

    def _set_mode(self, mode: str):
        """Applica la modalità: audio chiude il monitor, gli altri casi lo mostrano."""
        self._mode = mode
        self._monitor.setVisible(mode != MODE_AUDIO)
        if mode == MODE_VIDEO and self._qvideo_widget is not None:
            self._monitor_stack.setCurrentIndex(_MONITOR_VIDEO)
        else:
            self._monitor_msg.setText(_EMPTY_TEXT)
            self._monitor_stack.setCurrentIndex(_MONITOR_MESSAGE)

    # ── Tema ─────────────────────────────────────────────────────────────────

    def _apply_palette(self, _name=None):
        c = theme.c
        self._monitor.setStyleSheet(
            f"QFrame#previewMonitor {{ background: {c('bg')};"
            f" border: none; border-right: 1px solid {c('line')}; }}"
            f"QFrame#previewMonitorBox {{ background: {c('video_bg')};"
            f" border: 1px solid {c('line')}; }}"
        )
        self._monitor_msg.setStyleSheet(
            f"color: {c('dim')}; font-size: 13px; background: transparent; border: none;"
        )
        self._info_bar.setStyleSheet(
            f"QFrame#previewInfo {{ background: {c('bg')}; border: none;"
            f" border-bottom: 1px solid {c('line')}; }}"
        )
        self.duration_lbl.setStyleSheet(
            f"color: {c('dim')}; font-size: 11px; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._style_file_lbl()

    def _style_file_lbl(self, error: bool = False):
        self.file_lbl.setStyleSheet(
            f"color: {theme.c('err' if error else 'dim')}; font-size: 12px;"
            " background: transparent;"
        )

    def _on_player_error(self, msg: str):
        """Mostra l'errore del player; nel monitor resta un messaggio al posto del video."""
        logger.warning("Errore player: %s", msg)
        text = f"Impossibile riprodurre il file: {msg}" if msg else "Impossibile riprodurre il file"
        self.file_lbl.setText(text)
        self.file_lbl.set_full_tooltip(f"{text}\n{self._media_path}")
        self._style_file_lbl(error=True)
        if self._mode == MODE_VIDEO:
            self._monitor_msg.setText(
                "Anteprima video non disponibile per questo formato.\n"
                "I sottotitoli restano modificabili."
            )
            self._monitor_stack.setCurrentIndex(_MONITOR_MESSAGE)

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
            from PySide6.QtMultimediaWidgets import QGraphicsVideoItem  # noqa: F401 (verifica disponibilità)

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
            placeholder = QLabel(
                "Anteprima video non disponibile\n(modulo PySide6 QtMultimediaWidgets assente)"
            )
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
        Video → monitor e forma d'onda affiancati; solo audio → il monitor si chiude.
        """
        self.waveform.reset()
        self._set_overlay_subs([])
        if self._subtitle_overlay is not None:
            self._subtitle_overlay.set_text("")
        self._media_path = file_path
        self._style_file_lbl()
        self.file_lbl.setText(Path(file_path).name)
        self.file_lbl.set_full_tooltip(file_path)
        self.player.load(file_path)
        if platform_support.IS_WIN and self._video_player_view is not None:
            # Su Windows l'uscita video va ricollegata a ogni caricamento
            try:
                self.player._player.setVideoOutput(self._video_player_view.video_item())
            except Exception:  # noqa: BLE001
                logger.warning("Ricollegamento uscita video fallito", exc_info=True)

        self._set_mode(monitor_mode(file_path, self._qvideo_widget is not None))
        # La forma d'onda c'è sempre, anche per i video (picchi a blocchi, memoria limitata)
        self.waveform.load_audio(file_path)

    def clear_media(self):
        """Nessun media associato al progetto: svuota player, waveform e overlay."""
        self.waveform.reset()
        self._set_overlay_subs([])
        if self._subtitle_overlay is not None:
            self._subtitle_overlay.set_text("")
        self.player.unload()
        self._media_path = ""
        self.file_lbl.setText("")
        self.file_lbl.set_full_tooltip("")
        self._style_file_lbl()
        self.duration_lbl.setText("durata " + _ms_to_full_label(0))
        self.waveform.show_message("")
        self._set_mode(MODE_EMPTY)

    def _set_overlay_subs(self, subs: List[Subtitle]):
        self._overlay_subs = list(subs)
        self._overlay_index = sorted((s.start, s.end, s.text.strip()) for s in self._overlay_subs)
        self._overlay_starts = [e[0] for e in self._overlay_index]

    def set_subtitles(self, subs: List[Subtitle], severity: List[str]):
        self._set_overlay_subs(subs)
        self.waveform.set_subtitles(subs, severity)
        # Aggiorna subito l'overlay alla posizione corrente
        self._update_subtitle_overlay(self.player.position())

    def set_selected_row(self, row: int):
        self.waveform.set_selected_row(row)

    # ── Slots player ───────────────────────────────────────────────────────────

    def _on_source_ready(self):
        self.waveform.set_duration(self.player.duration())

    def _on_duration(self, ms: int):
        self.duration_lbl.setText("durata " + _ms_to_full_label(ms))

    def _update_subtitle_overlay(self, ms: int):
        """
        Aggiorna il testo dell'overlay in base alla posizione corrente.
        Attivo solo quando nel monitor è visibile il video.
        """
        if self._subtitle_overlay is None:
            return
        if self._mode != MODE_VIDEO or self._monitor_stack.currentIndex() != _MONITOR_VIDEO:
            return

        pos_s = ms / 1000.0
        text = ""
        i = bisect.bisect_right(self._overlay_starts, pos_s) - 1
        for j in range(i, max(-1, i - 3), -1):   # O(log N); tollera sovrapposizioni
            start, end, txt = self._overlay_index[j]
            if start <= pos_s <= end:
                text = txt
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
        self._font.setPixelSize(16)
        self._font.setWeight(QFont.Normal)

        # Scena e item video
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._vitem = QGraphicsVideoItem()
        self._scene.addItem(self._vitem)

        # Stile view: niente bordi, sfondo "video" (nero in entrambi i temi)
        self._apply_palette()
        theme.MANAGER.theme_changed.connect(self._apply_palette)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.Antialiasing)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Solo visualizzazione: nessuna fermata di Tab (i comandi sono nel trasporto)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAccessibleName("Anteprima video")

    def _apply_palette(self, _name=None):
        self.setStyleSheet(f"background: {theme.c('video_bg')}; border: none;")

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
        padding_h = 12
        padding_v = 5
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
        box_y = vp_h - box_h - 22   # 22 px dal fondo

        p.setBrush(QBrush(theme.qcolor("overlay_bg")))
        p.setPen(Qt.NoPen)
        p.drawRect(box_x, box_y, box_w, box_h)

        p.setPen(QPen(theme.qcolor("overlay_fg")))
        for i, line in enumerate(lines):
            lw = fm.horizontalAdvance(line)
            lx = box_x + (box_w - lw) // 2
            ly = box_y + padding_v + fm.ascent() + i * line_h
            p.drawText(lx, ly, line)

        p.end()

