"""
test_seek_selection.py — Click sulla forma d'onda in pausa: selezione e playhead subito.

Bug: cliccando una zona della forma d'onda (o lo slider, o con J/←/→) mentre il player è
in pausa, il playhead, il timecode, l'overlay e la riga selezionata si aggiornavano solo
dopo aver premuto Play: `AudioPlayer.seek` spostava il QMediaPlayer ma in pausa nessun
`position_changed` arrivava all'interfaccia (e prima del caricamento il seek era perso).
"""

from __future__ import annotations

import os
import struct
import sys
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.subtitle_model import Subtitle


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeSettings:
    store: dict = {}

    def __init__(self, *_a, **_k):
        pass

    def value(self, key, default=None, type=None):  # noqa: A002
        return self.store.get(key, default)

    def setValue(self, key, value):  # noqa: N802
        self.store[key] = value

    def remove(self, key):
        self.store.pop(key, None)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    import ui.subtitle_timeline as stl
    import ui.workspace as wsm
    monkeypatch.setattr(stl, "QSettings", _FakeSettings)
    monkeypatch.setattr(wsm, "QSettings", _FakeSettings)


def _subs(n=12):
    # sottotitoli da 1,5 s ogni 2 s: tra x.5 e (x+1).0 non c'è nessun sottotitolo
    return [Subtitle(start=i * 2.0, end=i * 2.0 + 1.5, text=f"Riga {i + 1}") for i in range(n)]


def _write_wav(path, seconds=30.0, rate=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 800) * int(seconds * rate))
    return str(path)


class _FakeMediaPlayer:
    """Sostituto minimo di QMediaPlayer: registra setPosition."""

    def __init__(self, duration=30_000):
        self.positions: list = []
        self._pos = 0
        self._duration = duration

    def setPosition(self, ms):  # noqa: N802
        self.positions.append(ms)
        self._pos = ms

    def position(self):
        return self._pos

    def duration(self):
        return self._duration

    def playbackState(self):  # noqa: N802
        return QMediaPlayer.PausedState


# ── AudioPlayer ──────────────────────────────────────────────────────────────

def test_seek_while_paused_emits_position_immediately(app):
    from core.audio_player import AudioPlayer
    p = AudioPlayer()
    p._player = _FakeMediaPlayer()
    p._is_ready = True
    got, seeked = [], []
    p.position_changed.connect(got.append)
    p.seeked.connect(seeked.append)
    p.seek(7_250)
    assert p._player.positions == [7_250]
    assert got == [7_250] and seeked == [7_250]
    # fuori dai limiti: limitato alla durata (e mai negativo)
    p.seek(99_000)
    assert got[-1] == 30_000
    p.seek(-5)
    assert got[-1] == 0


def test_seek_before_load_is_remembered_and_applied(app):
    from core.audio_player import AudioPlayer
    p = AudioPlayer()
    fake = _FakeMediaPlayer()
    p._player = fake
    p._is_ready = False
    got = []
    p.position_changed.connect(got.append)
    p.seek(4_000)
    assert got == [4_000]               # l'interfaccia si aggiorna subito
    assert p.position() == 4_000        # e i seek relativi partono da lì
    assert fake.positions == []
    p._on_media_status(QMediaPlayer.LoadedMedia)
    assert fake.positions == [4_000]    # applicato al caricamento
    p._on_media_status(QMediaPlayer.BufferedMedia)
    assert fake.positions == [4_000]    # una volta sola


# ── Workspace reale: click sulla forma d'onda in pausa ───────────────────────

@pytest.fixture
def workspace(app, tmp_path):
    from ui.workspace import WorkspaceWidget
    ws = WorkspaceWidget()
    ws.resize(1300, 800)
    ws.load_content(_subs(), _write_wav(tmp_path / "audio.wav"))
    ws.preview.waveform.set_duration(30_000)
    ws.preview.transport._on_duration_changed(30_000)
    ws.show()
    QApplication.processEvents()
    yield ws
    ws.preview.player.unload()
    ws.hide()
    ws.deleteLater()


def _wave_point(wf, ms):
    span = wf._view_end_ms - wf._view_start_ms
    x = int((ms - wf._view_start_ms) / span * wf.width())
    return QPoint(x, 40)      # nell'area della forma d'onda (non nella corsia dei blocchi)


def test_waveform_click_while_paused_selects_row_and_moves_playhead(workspace):
    ws = workspace
    tl, wf, player = ws.timeline, ws.preview.waveform, ws.preview.player
    assert not player.is_playing()
    assert tl._current_row() == 0
    QTest.mouseClick(wf, Qt.LeftButton, Qt.NoModifier, _wave_point(wf, 8_700))
    t = wf._playhead_ms
    assert abs(t - 8_700) < 60                      # playhead subito al click
    assert tl._current_row() == 4                   # Riga 5: 8,0–9,5 s
    assert ws.preview.transport.label_pos.text().startswith("00:00:08.")
    assert wf._selected_row == 4
    assert not player.is_playing()


def test_waveform_click_between_subtitles_keeps_selection(workspace):
    ws = workspace
    tl, wf = ws.timeline, ws.preview.waveform
    tl.view.selectRow(2)
    QTest.mouseClick(wf, Qt.LeftButton, Qt.NoModifier, _wave_point(wf, 7_750))  # 7,5–8,0: vuoto
    assert abs(wf._playhead_ms - 7_750) < 60
    assert tl._current_row() == 2


def test_waveform_block_click_moves_playhead_now(workspace):
    ws = workspace
    tl, wf = ws.timeline, ws.preview.waveform
    block_y, block_h = wf._block_geometry(wf.height())
    pt = _wave_point(wf, 12_500)
    QTest.mouseClick(wf, Qt.LeftButton, Qt.NoModifier, QPoint(pt.x(), block_y + block_h // 2))
    assert tl._current_row() == 6                   # Riga 7: 12,0–13,5 s
    assert wf._playhead_ms == 12_000                # all'inizio del blocco, subito


def test_user_seek_overrides_focus_and_multiselection(workspace, monkeypatch):
    """Il click dell'utente sposta sempre la selezione (non è il follow della riproduzione)."""
    from PySide6.QtCore import QItemSelectionModel
    ws = workspace
    tl, wf = ws.timeline, ws.preview.waveform
    sm = tl.view.selectionModel()
    for r in (0, 1):
        sm.select(tl.model.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    monkeypatch.setattr(QApplication, "focusWidget",
                        staticmethod(lambda: tl.inspector.start_spin))
    QTest.mouseClick(wf, Qt.LeftButton, Qt.NoModifier, _wave_point(wf, 16_500))
    assert tl._current_row() == 8


def test_user_seek_keeps_uncommitted_inspector_text(workspace):
    ws = workspace
    tl, wf = ws.timeline, ws.preview.waveform
    tl.view.selectRow(0)
    tl.inspector.text_edit.setPlainText("Testo che sto scrivendo")
    QTest.mouseClick(wf, Qt.LeftButton, Qt.NoModifier, _wave_point(wf, 16_500))
    assert tl._current_row() == 0
    assert tl.inspector.text_edit.toPlainText() == "Testo che sto scrivendo"


def test_transport_slider_click_while_paused_updates_everything(workspace):
    ws = workspace
    tl, wf, bar = ws.timeline, ws.preview.waveform, ws.preview.transport
    bar._on_source_ready()
    slider = bar.seek_slider
    x = int(slider.width() * 0.5)
    QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier, QPoint(x, slider.height() // 2))
    t = wf._playhead_ms
    assert 14_200 <= t <= 15_400                    # metà dello slider ≈ 15 s
    assert tl._current_row() == 7                   # Riga 8: 14,0–15,5 s
    assert bar.label_pos.text().startswith("00:00:1")


def test_keyboard_seeks_while_paused_move_playhead(workspace):
    ws = workspace
    tl, wf, player = ws.timeline, ws.preview.waveform, ws.preview.player
    player.seek(0)
    tl._seek_relative(1000)
    assert wf._playhead_ms == 1000
    tl._go_next_sub()
    assert tl._current_row() == 1 and wf._playhead_ms == 2000
    tl._jkl_j()                                     # da fermo: indietro di 2 s
    assert wf._playhead_ms == 0 and tl._current_row() == 0
