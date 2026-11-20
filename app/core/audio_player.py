"""
audio_player.py — Wrapper su QMediaPlayer + QAudioOutput per la riproduzione
di file audio/video all'interno dell'editor sottotitoli.

Funziona nativamente con i formati supportati dal backend multimediale della
piattaforma (vedi platform_support.native_media_exts). Per gli altri formati
tenta comunque di caricare il file originale: non vengono mai cercati WAV
"vicini" o temporanei, per non rischiare di riprodurre audio non correlato.

Segnali pubblici:
    position_changed(ms: int)   — posizione di riproduzione aggiornata (anche dopo
                                  un seek in pausa)
    seeked(ms: int)             — seek esplicito (click, tastiera): emesso prima di
                                  position_changed
    duration_changed(ms: int)   — durata totale del media caricato
    state_changed(state: str)   — "playing" | "paused" | "stopped"
    source_ready()              — media caricato e pronto
    error_occurred(msg: str)    — errore di caricamento/riproduzione
    rate_changed(rate: float)   — velocità di riproduzione cambiata
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot, QTimer
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

import platform_support

logger = logging.getLogger(__name__)


class AudioPlayer(QObject):
    """
    Wrapper thread-safe attorno a QMediaPlayer.
    Deve vivere nel thread principale (QObject con parent Qt).
    """

    position_changed = Signal(int)   # ms
    seeked           = Signal(int)   # ms — seek esplicito (prima di position_changed)
    duration_changed = Signal(int)   # ms
    state_changed    = Signal(str)   # "playing" | "paused" | "stopped"
    source_ready     = Signal()
    error_occurred   = Signal(str)
    rate_changed     = Signal(float)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        # QAudioOutput resta sull'uscita che era di sistema quando è stato creato: cuffie
        # collegate dopo (AirPods) o un cambio dal Centro di controllo non si sentivano.
        self._devices = QMediaDevices(self)
        self._devices.audioOutputsChanged.connect(self._follow_system_output)

        # Stato interno
        self._source_path: str = ""
        self._is_ready: bool = False
        # Seek chiesto prima che il media fosse caricato: applicato al caricamento
        self._pending_seek: int | None = None

        # Timer per emettere position_changed anche a bassa frequenza
        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(40)   # ~25 fps
        self._pos_timer.timeout.connect(self._emit_position)

        # Collega segnali interni Qt
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

        # Volume default
        self._audio_out.setVolume(0.8)

    # ----------------------------------------------------------------
    # API pubblica
    # ----------------------------------------------------------------

    def load(self, file_path: str) -> None:
        """
        Carica un file audio/video. In caso di errore nella risoluzione
        della sorgente emette error_occurred.
        """
        self._is_ready = False
        self._pending_seek = None
        self._source_path = file_path

        path = Path(file_path)
        if not path.exists():
            self.error_occurred.emit(f"File non trovato: {file_path}")
            return

        try:
            target = self._resolve_source(path)
            self._player.setSource(QUrl.fromLocalFile(str(target)))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Caricamento sorgente fallito: %s", file_path)
            self.error_occurred.emit(f"Impossibile caricare il file: {exc}")

    def play(self) -> None:
        if self._is_ready:
            self._follow_system_output()
            self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def toggle_play_pause(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            if self._is_ready:
                self._player.play()

    def stop(self) -> None:
        self._player.stop()

    def seek(self, ms: int) -> None:
        """
        Salta alla posizione indicata in millisecondi (limitata a [0, durata]).

        Emette SUBITO `seeked` e poi `position_changed`, anche in pausa: il timer di
        posizione gira solo in riproduzione, quindi senza questa emissione playhead,
        timecode, overlay e selezione si aggiornerebbero solo dopo Play. Se il media
        non è ancora caricato la richiesta resta in sospeso e viene applicata al
        caricamento (`_on_media_status`).
        """
        ms = max(0, int(ms))
        if self._is_ready:
            duration = self._player.duration()
            if duration > 0:
                ms = min(ms, duration)
            self._pending_seek = None
            self._player.setPosition(ms)
        else:
            self._pending_seek = ms
        self.seeked.emit(ms)
        self.position_changed.emit(ms)

    def seek_relative(self, delta_ms: int) -> None:
        """Sposta la posizione di delta_ms millisecondi rispetto all'attuale."""
        self.seek(self.position() + delta_ms)

    def position(self) -> int:
        """Posizione corrente in ms (quella richiesta, se il seek è ancora in sospeso)."""
        if self._pending_seek is not None:
            return self._pending_seek
        return self._player.position()

    def duration(self) -> int:
        """Durata totale in ms (0 se non ancora caricato)."""
        return self._player.duration()

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def is_ready(self) -> bool:
        return self._is_ready

    def set_volume(self, volume: float) -> None:
        """Volume da 0.0 a 1.0."""
        self._audio_out.setVolume(max(0.0, min(1.0, volume)))

    def volume(self) -> float:
        return self._audio_out.volume()

    def set_rate(self, rate: float) -> None:
        """Velocità di riproduzione (es. 0.5, 1.0, 1.5, 2.0)."""
        rate = max(0.25, min(4.0, rate))
        if abs(rate - self._player.playbackRate()) < 1e-6:
            return
        self._player.setPlaybackRate(rate)
        self.rate_changed.emit(rate)

    def rate(self) -> float:
        return self._player.playbackRate()

    def unload(self) -> None:
        """Ferma e scarica il media corrente."""
        self._player.stop()
        self._player.setSource(QUrl())
        self._pos_timer.stop()
        self._is_ready = False
        self._pending_seek = None
        self._source_path = ""

    # ----------------------------------------------------------------
    # Slot interni
    # ----------------------------------------------------------------

    def _follow_system_output(self) -> None:
        """Usa l'uscita audio di sistema attuale (se è cambiata e ne esiste una)."""
        default = QMediaDevices.defaultAudioOutput()
        if default.isNull() or default == self._audio_out.device():
            return
        logger.info("Uscita audio: %s", default.description())
        self._audio_out.setDevice(default)

    @Slot(int)
    def _on_duration_changed(self, duration_ms: int):
        self.duration_changed.emit(duration_ms)

    @Slot(QMediaPlayer.PlaybackState)
    def _on_state_changed(self, state: QMediaPlayer.PlaybackState):
        if state == QMediaPlayer.PlayingState:
            self._pos_timer.start()
            self.state_changed.emit("playing")
        elif state == QMediaPlayer.PausedState:
            self._pos_timer.stop()
            self._emit_position()   # aggiorna UI all'istante preciso
            self.state_changed.emit("paused")
        else:
            self._pos_timer.stop()
            self._emit_position()
            self.state_changed.emit("stopped")

    @Slot(QMediaPlayer.MediaStatus)
    def _on_media_status(self, status: QMediaPlayer.MediaStatus):
        if status in (
            QMediaPlayer.LoadedMedia,
            QMediaPlayer.BufferedMedia,
        ):
            self._is_ready = True
            if self._pending_seek is not None:
                pending, self._pending_seek = self._pending_seek, None
                self._player.setPosition(pending)
            self.source_ready.emit()
            self.duration_changed.emit(self._player.duration())
        elif status == QMediaPlayer.EndOfMedia:
            self._pos_timer.stop()
            self.state_changed.emit("stopped")
        elif status in (QMediaPlayer.InvalidMedia, QMediaPlayer.NoMedia):
            self._is_ready = False

    @Slot(QMediaPlayer.Error, str)
    def _on_error(self, error: QMediaPlayer.Error, error_string: str):
        if error != QMediaPlayer.NoError:
            self.error_occurred.emit(error_string)

    def _emit_position(self):
        self.position_changed.emit(self._player.position())

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    @staticmethod
    def _resolve_source(path: Path) -> Path:
        """
        Ritorna il path effettivo da caricare. Per i formati non nativi si
        tenta comunque l'originale (il backend potrebbe riuscire a leggerlo).
        """
        if path.suffix.lower() not in platform_support.native_media_exts():
            logger.info("Formato %s non nativo: provo il file originale", path.suffix)
        return path
