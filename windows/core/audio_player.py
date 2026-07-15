"""
audio_player.py — Wrapper su QMediaPlayer + QAudioOutput per la riproduzione
di file audio/video all'interno dell'editor sottotitoli.

Funziona su Windows via DirectShow / Media Foundation (Qt Multimedia).
Per MKV o formati non supportati, cade in automatico sul WAV 16 kHz
prodotto da engine.preprocess_audio (nella stessa cartella o in TEMP).

Segnali pubblici:
    position_changed(ms: int)   — posizione di riproduzione aggiornata
    duration_changed(ms: int)   — durata totale del media caricato
    state_changed(state: str)   — "playing" | "paused" | "stopped"
    source_ready()              — media caricato e pronto
    error_occurred(msg: str)    — errore di caricamento/riproduzione
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

logger = logging.getLogger(__name__)


class AudioPlayer(QObject):
    """
    Wrapper thread-safe attorno a QMediaPlayer.
    Deve vivere nel thread principale (QObject con parent Qt).
    """

    position_changed = Signal(int)   # ms
    duration_changed = Signal(int)   # ms
    state_changed    = Signal(str)   # "playing" | "paused" | "stopped"
    source_ready     = Signal()
    error_occurred   = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)

        self._source_path: str = ""
        self._is_ready: bool = False

        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(40)   # ~25 fps
        self._pos_timer.timeout.connect(self._emit_position)

        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

        self._audio_out.setVolume(0.8)

    # ----------------------------------------------------------------
    # API pubblica
    # ----------------------------------------------------------------

    def load(self, file_path: str) -> None:
        self._is_ready = False
        self._source_path = file_path

        path = Path(file_path)
        if not path.exists():
            msg = f"File non trovato: {file_path}"
            logger.error("[AudioPlayer.load] %s", msg)
            self.error_occurred.emit(msg)
            return

        try:
            target = self._resolve_source(path)
            logger.debug("[AudioPlayer.load] sorgente risolta: %s", target)
            self._player.setSource(QUrl.fromLocalFile(str(target)))
        except Exception as exc:
            msg = f"Errore caricamento sorgente: {exc}"
            logger.exception("[AudioPlayer.load] eccezione inattesa")
            self.error_occurred.emit(msg)

    def play(self) -> None:
        if self._is_ready:
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
        if self._is_ready:
            self._player.setPosition(max(0, ms))

    def seek_relative(self, delta_ms: int) -> None:
        self.seek(self.position() + delta_ms)

    def position(self) -> int:
        return self._player.position()

    def duration(self) -> int:
        return self._player.duration()

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlayingState

    def is_ready(self) -> bool:
        return self._is_ready

    def set_volume(self, volume: float) -> None:
        self._audio_out.setVolume(max(0.0, min(1.0, volume)))

    def volume(self) -> float:
        return self._audio_out.volume()

    def set_rate(self, rate: float) -> None:
        self._player.setPlaybackRate(max(0.25, min(4.0, rate)))

    def rate(self) -> float:
        return self._player.playbackRate()

    def unload(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        self._pos_timer.stop()
        self._is_ready = False
        self._source_path = ""

    # ----------------------------------------------------------------
    # Slot interni
    # ----------------------------------------------------------------

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
            self._emit_position()
            self.state_changed.emit("paused")
        else:
            self._pos_timer.stop()
            self._emit_position()
            self.state_changed.emit("stopped")

    @Slot(QMediaPlayer.MediaStatus)
    def _on_media_status(self, status: QMediaPlayer.MediaStatus):
        if status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            self._is_ready = True
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
            logger.error("[AudioPlayer] errore Qt Multimedia: %s", error_string)
            self.error_occurred.emit(error_string)

    def _emit_position(self):
        self.position_changed.emit(self._player.position())

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    @staticmethod
    def _resolve_source(path: Path) -> Path:
        """
        Ritorna il path effettivo da caricare.
        Su Windows usa tempfile.gettempdir() invece di /tmp (non esiste).
        Formati nativi Qt Multimedia su Windows: mp4/mp3/wav/m4a via Media Foundation.
        MKV/AVI/FLAC: cerca il WAV pre-processato da engine.preprocess_audio.
        """
        NATIVE = {".mp4", ".mov", ".m4a", ".m4v", ".mp3", ".wav", ".aac", ".wma"}
        if path.suffix.lower() in NATIVE:
            return path

        tmp_dir = Path(tempfile.gettempdir())
        wav_candidates = [
            path.with_suffix(".wav"),
            tmp_dir / (path.stem + "_16k.wav"),
            tmp_dir / (path.stem + ".wav"),
        ]
        for c in wav_candidates:
            if c.exists():
                logger.debug("[AudioPlayer._resolve_source] WAV trovato: %s", c)
                return c

        logger.debug("[AudioPlayer._resolve_source] nessun WAV trovato, uso originale: %s", path)
        return path
