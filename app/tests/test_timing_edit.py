"""
test_timing_edit.py — Regolare i tempi dei sottotitoli senza scrivere i secondi a mano.

Prima l'unico modo era scrivere inizio e fine nell'Inspector o in tabella (o i pulsanti
±10/±100 ms, che spostano inizio e fine insieme). Ora: trascinare i bordi o il centro di
un blocco sulla forma d'onda, i tasti I/O (inizio/fine al cursore di riproduzione) e la
timeline grande (monitor sopra, forma d'onda a tutta larghezza).
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core import timing_edit as te
from core.subtitle_model import Subtitle


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


# ── Regole (pure) ────────────────────────────────────────────────────────────

TIMES = [(1.0, 3.0), (3.5, 5.0), (6.0, 8.0)]


def test_limits_are_the_neighbours_and_the_media():
    assert te.neighbour_limits(TIMES, 1) == (3.0, 6.0)
    assert te.neighbour_limits(TIMES, 0) == (0.0, 3.5)
    assert te.neighbour_limits(TIMES, 2, media_end=9.0) == (5.0, 9.0)


def test_trim_stops_at_neighbours_and_minimum_duration():
    assert te.trim_start(TIMES, 1, 2.0, 0.2) == 3.0          # non scavalca il precedente
    assert te.trim_start(TIMES, 1, 4.95, 0.2) == pytest.approx(4.8)   # durata minima
    assert te.trim_end(TIMES, 1, 9.0, 0.2) == 6.0            # non scavalca il successivo
    assert te.trim_end(TIMES, 1, 3.0, 0.2) == pytest.approx(3.7)


def test_move_keeps_the_duration_inside_the_gap():
    assert te.move(TIMES, 1, 5.0) == (4.5, 6.0)
    assert te.move(TIMES, 1, -5.0) == (3.0, 4.5)
    assert te.move(TIMES, 0, -5.0) == (0.0, 2.0)


def test_existing_overlap_is_not_forced_apart():
    times = [(1.0, 4.0), (3.5, 5.0)]
    assert te.neighbour_limits(times, 1) == (3.5, float("inf"))   # non peggiora, non salta
    assert te.trim_start(times, 1, 4.2, 0.2) == 4.2


def test_mark_target_prefers_the_selected_subtitle():
    # cursore dentro il selezionato: I e O agiscono su di lui
    assert te.mark_target(TIMES, 1, 4.0, "start") == 1
    assert te.mark_target(TIMES, 1, 4.0, "end") == 1
    # pausa dopo il selezionato: O lo allunga, I va al prossimo che deve ancora arrivare
    assert te.mark_target(TIMES, 1, 5.5, "end") == 1
    assert te.mark_target(TIMES, 1, 5.5, "start") == 2
    # pausa prima del selezionato: O va al precedente
    assert te.mark_target(TIMES, 1, 3.2, "end") == 0
    assert te.mark_target(TIMES, -1, 0.5, "end") == -1
    assert te.mark_target(TIMES, -1, 9.0, "start") == -1


# ── Forma d'onda: trascinamento ──────────────────────────────────────────────

LANE_Y = 190      # dentro i blocchi (altezza 220: corsia da 168, blocchi da 178 a 210)


@pytest.fixture
def wf(app):
    from ui.waveform_widget import WaveformWidget
    w = WaveformWidget()
    w.resize(1000, 220)
    w.set_duration(60_000)
    w.set_subtitles([Subtitle(12.0, 14.0, "uno"), Subtitle(15.0, 17.0, "due")])
    w._view_start_ms, w._view_end_ms = 10_000.0, 20_000.0      # 10 ms per pixel
    w._playhead_ms = 30_000             # fuori vista (set_position sposterebbe la vista)
    w.show()
    edits = []
    w.timing_edited.connect(lambda r, s, e: edits.append((r, round(s, 3), round(e, 3))))
    yield w, edits
    w.hide()
    w.deleteLater()


def _drag(w, xs, mods=Qt.NoModifier, y=LANE_Y, release=True):
    QTest.mousePress(w, Qt.LeftButton, mods, QPoint(xs[0], y))
    for x in xs[1:]:
        QApplication.sendEvent(w, QMouseEvent(QMouseEvent.MouseMove, QPointF(x, y),
                                              QPointF(x, y), Qt.NoButton,
                                              Qt.LeftButton, mods))
    if release:
        QTest.mouseRelease(w, Qt.LeftButton, mods, QPoint(xs[-1], y))


def test_dragging_the_end_edge_changes_only_the_end(wf):
    w, edits = wf
    assert w._hit_block(401, LANE_Y) == (0, "end")
    _drag(w, [400, 420, 450])
    assert edits == [(0, 12.0, 14.5)]
    # il blocco resta dove è stato lasciato, prima che arrivino i sottotitoli nuovi
    assert (12_000.0, 14_500.0, 0) in w._sub_index


def test_dragging_the_start_edge_snaps_to_the_playhead(wf):
    w, edits = wf
    w._playhead_ms = 11_000
    _drag(w, [199, 150, 105])           # 11,05 s: entro 8 px dal playhead
    assert edits == [(0, 11.0, 14.0)]
    _drag(w, [100, 150, 105], mods=Qt.ShiftModifier)   # Maiusc: niente aggancio
    assert edits[-1] == (0, 11.05, 14.0)


def test_moving_a_block_stops_at_the_next_one(wf):
    w, edits = wf
    assert w._hit_block(300, LANE_Y) == (0, "move")
    _drag(w, [300, 350, 600])           # +3 s, ma il successivo comincia a 15 s
    assert edits == [(0, 13.0, 15.0)]


def test_touching_blocks_grab_the_one_on_the_mouse_side(wf):
    w, _ = wf
    w.set_subtitles([Subtitle(12.0, 14.0, "uno"), Subtitle(14.0, 16.0, "due")])
    assert w._hit_block(398, LANE_Y) == (0, "end")
    assert w._hit_block(402, LANE_Y) == (1, "start")


def test_escape_cancels_and_a_click_still_selects(wf):
    w, edits = wf
    clicks = []
    w.subtitle_clicked.connect(clicks.append)
    _drag(w, [401, 450, 480], release=False)
    assert w._timing is not None and w._timing.active
    QTest.keyClick(w, Qt.Key_Escape)
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, QPoint(480, LANE_Y))
    assert edits == [] and w._timing is None
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, QPoint(300, LANE_Y))
    assert clicks == [0] and edits == []


def test_dragging_outside_the_blocks_still_scrubs(wf):
    w, edits = wf
    seeks = []
    w.seek_requested.connect(seeks.append)
    _drag(w, [300, 350, 400], y=60)
    assert edits == [] and seeks[-1] == 14_000


def test_hover_shows_what_the_mouse_would_grab(wf):
    w, _ = wf
    for x, shape in ((401, Qt.SplitHCursor), (300, Qt.OpenHandCursor)):
        QApplication.sendEvent(w, QMouseEvent(QMouseEvent.MouseMove, QPointF(x, LANE_Y),
                                              QPointF(x, LANE_Y), Qt.NoButton,
                                              Qt.NoButton, Qt.NoModifier))
        assert w.cursor().shape() == shape


def test_drag_marks_are_painted(wf):
    """Durante il trascinamento: bordo in accento, linea dell'aggancio e tempi."""
    from PySide6.QtGui import QImage, QPainter
    w, _ = wf
    w._playhead_ms = 14_500
    _drag(w, [401, 449], release=False)
    assert w._timing.snap_ms == 14_500
    image = QImage(1000, 220, QImage.Format_ARGB32)
    painter = QPainter(image)
    w.render_static(painter, 1000, 220)
    painter.end()
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, QPoint(449, LANE_Y))


# ── Timeline: un passo di annullamento, tasti I/O ────────────────────────────

class _FakePlayer:
    def __init__(self, ms):
        self.ms = ms

    def position(self):
        return self.ms

    def duration(self):
        return 60_000


@pytest.fixture
def timeline(app):
    from ui.subtitle_timeline import SubtitleTimeline
    tl = SubtitleTimeline()
    tl.load_subtitles([Subtitle(1.0, 3.0, "uno"), Subtitle(3.5, 5.0, "due"),
                       Subtitle(6.0, 8.0, "tre")])
    yield tl
    tl.deleteLater()


def test_set_timing_is_one_undo_step(timeline):
    tl = timeline
    tl.set_timing(1, 3.6, 5.4)
    sub = tl.model.subtitle_at(1)
    assert (sub.start, sub.end) == (3.6, 5.4)
    assert tl._current_row() == 1
    assert tl.undo_stack.count() == 1 and tl.undo_stack.undoText() == "Sposta sottotitolo"
    tl.undo_stack.undo()
    assert (tl.model.subtitle_at(1).start, tl.model.subtitle_at(1).end) == (3.5, 5.0)
    tl.set_timing(1, 3.5, 5.2)
    assert tl.undo_stack.undoText() == "Modifica fine"


def test_i_and_o_set_start_and_end_at_the_playhead(timeline):
    tl = timeline
    names = {name for name, *_ in __import__("ui.subtitle_timeline",
                                              fromlist=["PLAYBACK_KEYS"]).PLAYBACK_KEYS}
    assert {"mark_in", "mark_out"} <= names
    tl.view.selectRow(1)
    tl.player = _FakePlayer(3_700)
    tl._mark_in()
    assert tl.model.subtitle_at(1).start == 3.7
    tl.player.ms = 5_600                 # pausa dopo il selezionato: O lo allunga
    tl._mark_out()
    assert tl.model.subtitle_at(1).end == 5.6
    tl.player.ms = 2_000                 # dentro il precedente: I si ferma alla sua fine
    tl._mark_in()
    assert tl.model.subtitle_at(1).start == 3.0
    tl.view.selectRow(2)
    tl.player.ms = 5_800
    tl._mark_in()                        # la pausa prima del selezionato: è il suo inizio
    assert tl.model.subtitle_at(2).start == 5.8


# ── Timeline grande ──────────────────────────────────────────────────────────

@pytest.fixture
def workspace(app):
    from ui.workspace import WorkspaceWidget
    ws = WorkspaceWidget()
    ws.resize(1300, 900)
    ws.load_content([Subtitle(1.0, 3.0, "uno")], "")
    ws.preview.waveform.set_duration(120_000)
    ws.show()
    QApplication.processEvents()
    yield ws
    ws.hide()
    ws.deleteLater()


def test_tall_timeline_puts_the_waveform_under_the_monitor(workspace):
    ws = workspace
    normal = ws._vsplit.sizes()
    ws.preview.transport.btn_tall.click()
    QApplication.processEvents()
    assert ws.is_tall_timeline() and ws.preview.is_tall_timeline()
    assert ws.preview._top_split.orientation() == Qt.Vertical
    top, lower = ws._vsplit.sizes()
    assert lower <= 230 < top
    wf = ws.preview.waveform
    assert wf._view_end_ms - wf._view_start_ms == pytest.approx(15_000)
    ws._save_geometry()          # in timeline grande si salvano le misure normali
    ws.toggle_tall_timeline()    # menu Vista / Ctrl+Shift+E
    QApplication.processEvents()
    assert not ws.preview.transport.btn_tall.isChecked()
    assert ws.preview._top_split.orientation() == Qt.Horizontal
    assert ws._vsplit.sizes() == normal


def test_editor_always_opens_side_by_side(app):
    """La timeline grande è un'opzione del momento: l'editor riparte affiancato."""
    from PySide6.QtCore import QSettings
    from ui.workspace import WorkspaceWidget
    QSettings("VideoSRT", "v2").setValue("workspace/tall_timeline", True)   # versioni vecchie
    ws = WorkspaceWidget()
    assert not ws.is_tall_timeline() and not ws.preview.transport.btn_tall.isChecked()
    assert ws.preview._top_split.orientation() == Qt.Horizontal
    ws.set_tall_timeline(True)
    # la durata del media arriva dopo: lo zoom si applica allora
    ws.preview.waveform.set_duration(120_000)
    ws.preview.player.duration_changed.emit(120_000)
    wf = ws.preview.waveform
    assert wf._view_end_ms - wf._view_start_ms == pytest.approx(15_000)
    ws.deleteLater()


def test_waveform_edits_reach_the_undo_stack(workspace):
    ws = workspace
    ws.preview.waveform.timing_edited.emit(0, 1.2, 3.0)
    assert ws.timeline.model.subtitle_at(0).start == 1.2
    assert ws.timeline.undo_stack.count() == 1


def test_fullscreen_button_sits_in_the_video_corner(workspace, monkeypatch):
    from ui import preview_area as pa
    pv = workspace.preview
    assert pv.monitor_fullscreen_btn.isHidden()          # nessun video: niente pulsante
    if pv._video_player_view is None:
        pytest.skip("uscita video non disponibile")
    pv._set_mode(pa.MODE_VIDEO)
    box, btn = pv._monitor_box, pv.monitor_fullscreen_btn
    box.resize(400, 240)
    QApplication.processEvents()
    assert not btn.isHidden()
    assert btn.geometry().bottomRight().x() == 400 - 8 - 1
    assert btn.geometry().bottomRight().y() == 240 - 8 - 1
    calls = []
    monkeypatch.setattr(pv, "enter_fullscreen", lambda: calls.append(1))
    pv.monitor_fullscreen_btn.clicked.disconnect()
    pv.monitor_fullscreen_btn.clicked.connect(pv.enter_fullscreen)
    btn.click()
    assert calls == [1]
    pv._set_mode(pa.MODE_AUDIO)
    assert btn.isHidden()


def test_section_borders_are_easy_to_grab(workspace):
    from ui.workspace import SPLIT_HANDLE
    assert SPLIT_HANDLE >= 5
    assert workspace._vsplit.handleWidth() == SPLIT_HANDLE
    assert workspace._hsplit.handleWidth() == SPLIT_HANDLE
