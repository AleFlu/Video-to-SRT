"""
test_audio_output.py — L'audio dell'editor segue l'uscita di sistema.

Caso reale: AirPods collegati dopo l'apertura del progetto; il player aveva scelto le
casse all'avvio e continuava a suonare lì (in cuffia non si sentiva nulla).
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication

from core import audio_player as ap


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication(sys.argv)


class _Device:
    def __init__(self, name: str, null: bool = False):
        self.name, self._null = name, null

    def isNull(self):  # noqa: N802 (come QAudioDevice)
        return self._null

    def description(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, _Device) and other.name == self.name


class _Output:
    def __init__(self, device):
        self.current = device
        self.changes = []

    def device(self):
        return self.current

    def setDevice(self, device):  # noqa: N802 (come QAudioOutput)
        self.current = device
        self.changes.append(device.name)


@pytest.fixture
def player(monkeypatch):
    p = ap.AudioPlayer()
    out = _Output(_Device("Altoparlanti MacBook Pro"))
    monkeypatch.setattr(p, "_audio_out", out)
    system = {"default": _Device("Altoparlanti MacBook Pro")}
    monkeypatch.setattr(ap.QMediaDevices, "defaultAudioOutput",
                        staticmethod(lambda: system["default"]))
    return p, out, system


def test_output_follows_headphones_connected_later(player):
    p, out, system = player
    system["default"] = _Device("AirPods")
    p._devices.audioOutputsChanged.emit()
    assert out.current.name == "AirPods"


def test_play_rechecks_the_system_output(player):
    """Cambio dal Centro di controllo senza segnale: al play si riallinea."""
    p, out, system = player
    system["default"] = _Device("AirPods")
    p._is_ready = True
    p.play()
    p.pause()
    assert out.current.name == "AirPods"


def test_same_or_missing_device_changes_nothing(player):
    p, out, system = player
    p._devices.audioOutputsChanged.emit()               # stessa uscita
    system["default"] = _Device("", null=True)          # nessuna uscita
    p._devices.audioOutputsChanged.emit()
    assert out.changes == []
