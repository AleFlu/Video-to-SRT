"""
transport_bar.py — Barra di controllo del player audio/video.

Contiene:
  - Pulsanti ▶/⏸ play-pausa e ⏹ stop
  - Timecode corrente / totale
  - Slider di posizione (click = salto alla posizione cliccata, trascinamento, tastiera)
  - Slider volume
  - Selettore velocità (scala RATE_STEPS, sincronizzata anche con J/K/L)
  - Toggle "loop sul sottotitolo selezionato" (gestito da SubtitleTimeline.set_loop)

Si interfaccia con AudioPlayer tramite metodi diretti e ricevendo i suoi segnali.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QSlider, QStyle, QStyleOptionSlider,
    QComboBox, QToolButton, QFrame, QSizePolicy
)

from core.audio_player import AudioPlayer
from ui import theme

# Scala delle velocità: la combo e i tasti J/L (in riproduzione) la percorrono a passi
RATE_STEPS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0)


def _rate_label(rate: float) -> str:
    return f"{rate:g}×"


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


class _SeekSlider(QSlider):
    """Slider che salta direttamente alla posizione cliccata (non a passi di pagina)."""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            handle = self.style().subControlRect(
                QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self
            )
            if not handle.contains(event.position().toPoint()):
                groove = self.style().subControlRect(
                    QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self
                )
                span = max(1, groove.width() - handle.width())
                x = int(event.position().x()) - groove.x() - handle.width() // 2
                value = QStyle.sliderValueFromPosition(
                    self.minimum(), self.maximum(), x, span, opt.upsideDown
                )
                self.setValue(value)
        super().mousePressEvent(event)


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
        # Altezza minima dalle metriche del font (niente altezze fisse che tagliano)
        self.setMinimumHeight(max(44, self.fontMetrics().height() * 2 + 12))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._player: AudioPlayer | None = None
        self._duration_ms: int = 0
        self._dragging_seek: bool = False   # l'utente sta trascinando lo slider
        self._syncing: bool = False         # aggiornamento programmatico dello slider

        self._jkl_timer = QTimer(self)
        self._jkl_timer.setSingleShot(True)
        self._jkl_timer.setInterval(600)
        self._jkl_timer.timeout.connect(self._jkl_reset)

        self._build_ui()
        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

    # ----------------------------------------------------------------
    # Costruzione UI
    # ----------------------------------------------------------------

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # --- Play / Pausa ---
        self.btn_play = QToolButton()
        self.btn_play.setText("▶")
        self.btn_play.setToolTip("Riproduci  (Spazio)")
        self.btn_play.setAccessibleName("Riproduci")
        self.btn_play.setMinimumSize(34, 32)
        self.btn_play.clicked.connect(self._on_play_clicked)
        layout.addWidget(self.btn_play)

        # --- Stop ---
        self.btn_stop = QToolButton()
        self.btn_stop.setText("⏹")
        self.btn_stop.setToolTip("Ferma")
        self.btn_stop.setAccessibleName("Ferma")
        self.btn_stop.setMinimumSize(32, 32)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self.btn_stop)

        layout.addWidget(_make_separator())

        # --- Timecode corrente ---
        tc_w = self.fontMetrics().horizontalAdvance("00:00:00.000") + 12
        self.label_pos = QLabel("00:00.000")
        self.label_pos.setObjectName("timecode")
        self.label_pos.setMinimumWidth(tc_w)
        self.label_pos.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.label_pos.setAccessibleName("Posizione corrente")
        layout.addWidget(self.label_pos)

        self._sep_label = QLabel("/")
        layout.addWidget(self._sep_label)

        self.label_dur = QLabel("00:00.000")
        self.label_dur.setObjectName("timecode")
        self.label_dur.setMinimumWidth(tc_w)
        self.label_dur.setAccessibleName("Durata totale")
        layout.addWidget(self.label_dur)

        # --- Slider seek ---
        self.seek_slider = _SeekSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setSingleStep(5)
        self.seek_slider.setPageStep(50)
        self.seek_slider.setToolTip("Posizione: clicca o trascina per spostarti")
        self.seek_slider.setAccessibleName("Posizione di riproduzione")
        self.seek_slider.setObjectName("seekSlider")
        self.seek_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        # click sul binario e tastiera: valueChanged fuori da un trascinamento
        self.seek_slider.valueChanged.connect(self._on_seek_value_changed)
        layout.addWidget(self.seek_slider, 1)

        layout.addWidget(_make_separator())

        # --- Volume ---
        self._lbl_vol = QLabel("Vol")
        self._lbl_vol.setToolTip("Volume")
        layout.addWidget(self._lbl_vol)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(72)
        self.volume_slider.setToolTip("Volume")
        self.volume_slider.setAccessibleName("Volume")
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self._lbl_vol.setBuddy(self.volume_slider)
        layout.addWidget(self.volume_slider)

        layout.addWidget(_make_separator())

        # --- Velocità ---
        self.rate_combo = QComboBox()
        for value in RATE_STEPS:
            self.rate_combo.addItem(_rate_label(value), value)
        self.rate_combo.setCurrentIndex(RATE_STEPS.index(1.0))
        self.rate_combo.setToolTip("Velocità di riproduzione")
        self.rate_combo.setAccessibleName("Velocità di riproduzione")
        self.rate_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        layout.addWidget(self.rate_combo)

        layout.addWidget(_make_separator())

        # --- Toggle loop ---
        self.btn_loop = QToolButton()
        self.btn_loop.setText("⟳")
        self.btn_loop.setToolTip("Ripeti il sottotitolo selezionato")
        self.btn_loop.setAccessibleName("Ripeti il sottotitolo selezionato")
        self.btn_loop.setCheckable(True)
        self.btn_loop.setMinimumSize(32, 32)
        self.btn_loop.toggled.connect(self.loop_toggled)
        layout.addWidget(self.btn_loop)

        layout.addWidget(_make_separator())

        # --- Indicatore JKL ---
        self._jkl_lbl = QLabel("J·K·L")
        self._jkl_lbl.setObjectName("jklIndicator")
        self._jkl_lbl.setToolTip(
            "J: indietro di 2 s (in riproduzione: più lento)\n"
            "K: pausa e velocità 1×\n"
            "L: riproduci (in riproduzione: più veloce)"
        )
        self._jkl_lbl.setMinimumWidth(self.fontMetrics().horizontalAdvance("J·K·L") + 12)
        self._jkl_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._jkl_lbl)

        # Stato iniziale disabilitato (nessun file caricato)
        self._set_enabled(False)

    # ----------------------------------------------------------------
    # Tema
    # ----------------------------------------------------------------

    def _apply_palette(self):
        c = theme.c
        tc_ss = (
            f"font-family: {theme.FONT_MONO}; font-size: 14px; font-weight: 600;"
            f" color: {c('text')}; background: transparent;"
        )
        self.label_pos.setStyleSheet(tc_ss)
        self.label_dur.setStyleSheet(
            f"font-family: {theme.FONT_MONO}; font-size: 12px; color: {c('muted')};"
            " background: transparent;"
        )
        self._sep_label.setStyleSheet(f"color: {c('muted')}; background: transparent;")
        self._lbl_vol.setStyleSheet(
            f"color: {c('muted')}; font-size: 11px; background: transparent;"
        )
        self._jkl_reset()
        # play button accentato
        self.btn_play.setStyleSheet(
            f"QToolButton {{ background: {c('acc_fill')}; color: {c('acc_ink')};"
            " border: none; border-radius: 7px; font-size: 13px; }"
            f"QToolButton:hover {{ background: {c('acc_fill_h')}; }}"
            f"QToolButton:disabled {{ background: {c('card_2')}; color: {c('faint')}; }}"
            + theme.focus_rule("QToolButton", 7)
        )

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
            self._player.rate_changed.disconnect(self.sync_rate)

        self._player = player
        player.position_changed.connect(self._on_position_changed)
        player.duration_changed.connect(self._on_duration_changed)
        player.state_changed.connect(self._on_state_changed)
        player.source_ready.connect(self._on_source_ready)
        player.rate_changed.connect(self.sync_rate)

    # ----------------------------------------------------------------
    # Slot dal player
    # ----------------------------------------------------------------

    @Slot(int)
    def _on_position_changed(self, ms: int):
        if not self._dragging_seek:
            self.label_pos.setText(_ms_to_label(ms))
            if self._duration_ms > 0:
                self._syncing = True
                self.seek_slider.setValue(int(ms * 1000 / self._duration_ms))
                self._syncing = False

    @Slot(int)
    def _on_duration_changed(self, ms: int):
        self._duration_ms = ms
        self.label_dur.setText(_ms_to_label(ms))

    @Slot(str)
    def _on_state_changed(self, state: str):
        if state == "playing":
            self.btn_play.setText("⏸")
            self.btn_play.setToolTip("Pausa  (Spazio)")
            self.btn_play.setAccessibleName("Pausa")
        else:
            self.btn_play.setText("▶")
            self.btn_play.setToolTip("Riproduci  (Spazio)")
            self.btn_play.setAccessibleName("Riproduci")

    @Slot()
    def _on_source_ready(self):
        self._set_enabled(True)

    @Slot(float)
    def sync_rate(self, rate: float):
        """Allinea la combo alla velocità effettiva del player (anche da J/K/L)."""
        idx = self.rate_combo.findData(rate)
        if idx < 0:
            # velocità fuori scala: la mostra comunque, senza mentire all'utente
            self.rate_combo.addItem(_rate_label(rate), rate)
            idx = self.rate_combo.count() - 1
        if idx != self.rate_combo.currentIndex():
            self.rate_combo.blockSignals(True)
            self.rate_combo.setCurrentIndex(idx)
            self.rate_combo.blockSignals(False)

    # ----------------------------------------------------------------
    # Slot dai controlli
    # ----------------------------------------------------------------

    def _on_play_clicked(self):
        if self._player:
            self._player.toggle_play_pause()

    def _on_stop_clicked(self):
        if self._player:
            self._player.stop()

    def _value_to_ms(self, value: int) -> int:
        return int(value * self._duration_ms / 1000)

    def _on_seek_pressed(self):
        self._dragging_seek = True

    def _on_seek_moved(self, value: int):
        if self._duration_ms > 0:
            self.label_pos.setText(_ms_to_label(self._value_to_ms(value)))

    def _on_seek_released(self):
        self._dragging_seek = False
        if self._player and self._duration_ms > 0:
            self._player.seek(self._value_to_ms(self.seek_slider.value()))

    def _on_seek_value_changed(self, value: int):
        """Click sul binario o tasti freccia: seek immediato (il trascinamento seeka al rilascio)."""
        if self._syncing or self._dragging_seek or self.seek_slider.isSliderDown():
            return
        if self._player and self._duration_ms > 0:
            ms = self._value_to_ms(value)
            self.label_pos.setText(_ms_to_label(ms))
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
        c = theme.c
        parts = []
        _colors = {"J": c("acc"), "K": c("warn"), "L": c("ok")}
        for k in ("J", "K", "L"):
            if k == key:
                parts.append(f'<span style="color:{_colors[k]};font-weight:bold;">{k}</span>')
            else:
                parts.append(f'<span style="color:{c("muted")};">{k}</span>')
        self._jkl_lbl.setTextFormat(Qt.RichText)
        self._jkl_lbl.setText("·".join(parts))

        # Reset automatico dopo 600 ms (timer figlio: muore con la barra)
        if key:
            self._jkl_timer.start()

    def _jkl_reset(self):
        self._jkl_lbl.setTextFormat(Qt.PlainText)
        self._jkl_lbl.setText("J·K·L")
        self._jkl_lbl.setStyleSheet(
            f"font-family: {theme.FONT_MONO};"
            "font-size: 11px;"
            f"color: {theme.c('muted')};"
            "background: transparent;"
            "letter-spacing: 1px;"
        )


def _make_separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.VLine)
    sep.setFrameShadow(QFrame.Sunken)
    sep.setFixedWidth(2)
    return sep
