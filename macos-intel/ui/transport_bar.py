"""
transport_bar.py — Barra di controllo del player audio/video.

Contiene:
  - Pulsanti ▶/⏸ play-pause e ⏹ stop
  - Timecode corrente / totale
  - Slider di posizione (seek)
  - Slider volume
  - Selettore velocità (0.5× 0.75× 1× 1.25× 1.5× 2×)
  - Toggle "loop sul sottotitolo selezionato"

Si interfaccia con AudioPlayer tramite metodi diretti e ricevendo i suoi segnali.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSlider,
    QComboBox, QToolButton, QFrame, QSizePolicy
)
from PySide6.QtGui import QIcon

from core.audio_player import AudioPlayer


def _ms_to_label(ms: int) -> str:
    """Formatta i millisecondi come HH:MM:SS.mmm (standard NLE)."""
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


class TransportBar(QWidget):
    """
    Widget barra trasporto: si aggancia ad un AudioPlayer esistente
    tramite `bind_player(player)`.

    Segnali:
        loop_toggled(bool)      — l'utente ha attivato/disattivato il loop
    """

    loop_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("transportBar")
        self.setFixedHeight(44)

        self._player: AudioPlayer | None = None
        self._duration_ms: int = 0
        self._dragging_seek: bool = False   # l'utente sta trascinando lo slider

        self._build_ui()

    # ----------------------------------------------------------------
    # Costruzione UI
    # ----------------------------------------------------------------

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # --- Play / Pause ---
        self.btn_play = QToolButton()
        self.btn_play.setText("▶")
        self.btn_play.setToolTip("Play / Pausa  (Space)")
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.clicked.connect(self._on_play_clicked)
        layout.addWidget(self.btn_play)

        # --- Stop ---
        self.btn_stop = QToolButton()
        self.btn_stop.setText("⏹")
        self.btn_stop.setToolTip("Stop")
        self.btn_stop.setFixedSize(32, 32)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self.btn_stop)

        # --- Separatore ---
        layout.addWidget(_make_separator())

        # --- Timecode corrente ---
        self.label_pos = QLabel("00:00.000")
        self.label_pos.setObjectName("timecode")
        self.label_pos.setMinimumWidth(86)
        self.label_pos.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.label_pos.setStyleSheet(
            "font-family: 'SF Mono', 'Menlo', monospace; font-size: 12px;"
        )
        layout.addWidget(self.label_pos)

        layout.addWidget(QLabel("/"))

        self.label_dur = QLabel("00:00.000")
        self.label_dur.setObjectName("timecode")
        self.label_dur.setMinimumWidth(86)
        self.label_dur.setStyleSheet(
            "font-family: 'SF Mono', 'Menlo', monospace; font-size: 12px; color: #8a8a9a;"
        )
        layout.addWidget(self.label_dur)

        # --- Slider seek ---
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setToolTip("Posizione")
        self.seek_slider.setObjectName("seekSlider")
        self.seek_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        layout.addWidget(self.seek_slider, 1)

        # --- Separatore ---
        layout.addWidget(_make_separator())

        # --- Volume ---
        lbl_vol = QLabel("🔊")
        lbl_vol.setToolTip("Volume")
        layout.addWidget(lbl_vol)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(72)
        self.volume_slider.setToolTip("Volume")
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        layout.addWidget(self.volume_slider)

        # --- Separatore ---
        layout.addWidget(_make_separator())

        # --- Velocità ---
        lbl_rate = QLabel("×")
        lbl_rate.setToolTip("Velocità di riproduzione")
        layout.addWidget(lbl_rate)

        self.rate_combo = QComboBox()
        self.rate_combo.setFixedWidth(62)
        for label, value in (
            ("0.5×", 0.5),
            ("0.75×", 0.75),
            ("1×",   1.0),
            ("1.25×", 1.25),
            ("1.5×", 1.5),
            ("2×",   2.0),
        ):
            self.rate_combo.addItem(label, value)
        self.rate_combo.setCurrentIndex(2)   # 1×
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        layout.addWidget(self.rate_combo)

        # --- Separatore ---
        layout.addWidget(_make_separator())

        # --- Toggle loop ---
        self.btn_loop = QToolButton()
        self.btn_loop.setText("⟳")
        self.btn_loop.setToolTip("Loop sul sottotitolo selezionato")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setFixedSize(32, 32)
        self.btn_loop.toggled.connect(self.loop_toggled)
        layout.addWidget(self.btn_loop)

        # --- Separatore ---
        layout.addWidget(_make_separator())

        # --- Indicatore JKL ---
        self._jkl_lbl = QLabel("J·K·L")
        self._jkl_lbl.setObjectName("jklIndicator")
        self._jkl_lbl.setToolTip("J = −2s  ·  K = Pausa  ·  L = Play")
        self._jkl_lbl.setFixedWidth(48)
        self._jkl_lbl.setAlignment(Qt.AlignCenter)
        self._jkl_lbl.setStyleSheet(
            "font-family: 'SF Mono', 'Menlo', monospace;"
            "font-size: 10px;"
            "color: #5a5a6a;"
            "background: transparent;"
            "letter-spacing: 1px;"
        )
        layout.addWidget(self._jkl_lbl)

        # Stato iniziale disabilitato (nessun file caricato)
        self._set_enabled(False)

    # ----------------------------------------------------------------
    # Binding con AudioPlayer
    # ----------------------------------------------------------------

    def bind_player(self, player: AudioPlayer) -> None:
        """Aggancia questo widget a un'istanza AudioPlayer."""
        if self._player is not None:
            self._player.position_changed.disconnect(self._on_position_changed)
            self._player.duration_changed.disconnect(self._on_duration_changed)
            self._player.state_changed.disconnect(self._on_state_changed)
            self._player.source_ready.disconnect(self._on_source_ready)

        self._player = player
        player.position_changed.connect(self._on_position_changed)
        player.duration_changed.connect(self._on_duration_changed)
        player.state_changed.connect(self._on_state_changed)
        player.source_ready.connect(self._on_source_ready)

    # ----------------------------------------------------------------
    # Slot dal player
    # ----------------------------------------------------------------

    @Slot(int)
    def _on_position_changed(self, ms: int):
        if not self._dragging_seek:
            self.label_pos.setText(_ms_to_label(ms))
            if self._duration_ms > 0:
                self.seek_slider.setValue(int(ms * 1000 / self._duration_ms))

    @Slot(int)
    def _on_duration_changed(self, ms: int):
        self._duration_ms = ms
        self.label_dur.setText(_ms_to_label(ms))

    @Slot(str)
    def _on_state_changed(self, state: str):
        if state == "playing":
            self.btn_play.setText("⏸")
            self.btn_play.setToolTip("Pausa  (Space)")
        else:
            self.btn_play.setText("▶")
            self.btn_play.setToolTip("Play  (Space)")

    @Slot()
    def _on_source_ready(self):
        self._set_enabled(True)

    # ----------------------------------------------------------------
    # Slot dai controlli
    # ----------------------------------------------------------------

    def _on_play_clicked(self):
        if self._player:
            self._player.toggle_play_pause()

    def _on_stop_clicked(self):
        if self._player:
            self._player.stop()

    def _on_seek_pressed(self):
        self._dragging_seek = True

    def _on_seek_moved(self, value: int):
        if self._duration_ms > 0:
            ms = int(value * self._duration_ms / 1000)
            self.label_pos.setText(_ms_to_label(ms))

    def _on_seek_released(self):
        self._dragging_seek = False
        if self._player and self._duration_ms > 0:
            ms = int(self.seek_slider.value() * self._duration_ms / 1000)
            self._player.seek(ms)

    def _on_volume_changed(self, value: int):
        if self._player:
            self._player.set_volume(value / 100.0)

    def _on_rate_changed(self, index: int):
        if self._player:
            rate = self.rate_combo.itemData(index)
            if rate:
                self._player.set_rate(float(rate))

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _set_enabled(self, enabled: bool):
        for w in (self.btn_play, self.btn_stop, self.seek_slider, self.btn_loop):
            w.setEnabled(enabled)

    def set_jkl_key(self, key: str):
        """
        Evidenzia il tasto JKL attivo nell'indicatore.
        key: "J" | "K" | "L" | "" (nessuno)
        """
        key = key.upper()
        parts = []
        _colors = {"J": "#7b7bf8", "K": "#f39c12", "L": "#2ecc71"}
        for k in ("J", "K", "L"):
            if k == key:
                col = _colors[k]
                parts.append(f'<span style="color:{col};font-weight:bold;">{k}</span>')
            else:
                parts.append(f'<span style="color:#3a3a4a;">{k}</span>')
        self._jkl_lbl.setText("·".join(parts))
        self._jkl_lbl.setTextFormat(Qt.RichText)

        # Reset automatico dopo 600 ms
        if key:
            QTimer.singleShot(600, lambda: self._jkl_reset())

    def _jkl_reset(self):
        self._jkl_lbl.setText("J·K·L")
        self._jkl_lbl.setTextFormat(Qt.PlainText)
        self._jkl_lbl.setStyleSheet(
            "font-family: 'SF Mono', 'Menlo', monospace;"
            "font-size: 10px;"
            "color: #5a5a6a;"
            "background: transparent;"
            "letter-spacing: 1px;"
        )

    @property
    def loop_active(self) -> bool:
        return self.btn_loop.isChecked()


def _make_separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.VLine)
    sep.setFrameShadow(QFrame.Sunken)
    sep.setFixedWidth(2)
    return sep
