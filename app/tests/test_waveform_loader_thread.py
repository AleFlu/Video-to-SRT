"""
test_waveform_loader_thread.py — Il thread che calcola la forma d'onda non possiede oggetti Qt.

Bug (crash casuali in CI su Linux e macOS, "Segmentation fault" / "Aborted" in test diversi):
ogni `_AudioLoader` creava un proprio QObject per i segnali nel thread UI; a fine lavoro il
thread di sistema rilasciava l'ultimo riferimento e il QObject veniva distrutto lì, fuori dal
suo thread, mentre la UI poteva ancora consegnarne gli eventi in coda. Ora i segnali passano da
un unico relay che vive per tutta la sessione nel thread UI e non viene mai distrutto.
"""

from __future__ import annotations

import os
import sys
import time
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def _write_wav(path, seconds: float = 1.0, rate: int = 8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00\xf0\xff" * int(seconds * rate / 2))
    return str(path)


def _wait(app, cond, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_loader_thread_holds_no_qt_object(app, tmp_path):
    from ui.waveform_widget import WaveformWidget

    wf = WaveformWidget()
    wf.load_audio(_write_wav(tmp_path / "a.wav"))
    loader = wf._loader
    owned = [name for name, value in vars(loader).items() if isinstance(value, QObject)]
    assert owned == [], f"il thread possiede oggetti Qt: {owned}"
    assert _wait(app, lambda: wf._mins is not None)
    loader.join(2)


def test_two_widgets_get_their_own_waveform(app, tmp_path):
    from ui.waveform_widget import WaveformWidget

    short = _write_wav(tmp_path / "corto.wav", seconds=1.0)
    long_ = _write_wav(tmp_path / "lungo.wav", seconds=3.0)
    a, b = WaveformWidget(), WaveformWidget()
    a.load_audio(short)
    b.load_audio(long_)
    assert _wait(app, lambda: a._mins is not None and b._mins is not None)
    assert a._duration_ms == 1000
    assert b._duration_ms == 3000


def test_widget_destroyed_while_loading_is_safe(app, tmp_path):
    from ui.waveform_widget import WaveformWidget

    wf = WaveformWidget()
    wf.load_audio(_write_wav(tmp_path / "b.wav", seconds=2.0))
    loader = wf._loader
    wf.deleteLater()
    del wf
    app.processEvents()
    loader.join(5)
    # eventi accodati dal thread dopo la distruzione del widget: nessun crash
    for _ in range(5):
        app.processEvents()
