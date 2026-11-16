"""
test_ui_polish.py — Test del Task 6 (UX, tema, prestazioni, pulizia).

Coprono: trasporto (seek al click, velocità sincronizzata con J/K/L, loop),
follow-playback che non sovrascrive selezione e testo non confermato, click con
modificatori, tema (nessun colore letterale, provider colori della tabella, QPalette,
contrasto WCAG AA), waveform a picchi con memoria limitata, anteprima Result
virtualizzata, debounce delle sincronizzazioni, ExportPanel senza percorsi stantii,
liste QSettings, autosave per processo, accessibilità e drag&drop rifiutato con messaggio.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal, QMimeData, QUrl
from PySide6.QtGui import QDropEvent, QPixmap, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QLabel, QMessageBox,
)

import platform_support
from core.subtitle_model import Subtitle

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeSettings:
    """QSettings in memoria (le preferenze reali dell'utente restano intatte)."""

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
def _isolate(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: cache)
    monkeypatch.setattr(platform_support, "legacy_cache_dirs", lambda: [])
    _FakeSettings.store = {}
    import ui.home_widget as hw
    import ui.main_window as mw
    import ui.project_widget as pwm
    import ui.workspace as wsm
    for mod in (hw, mw, pwm, wsm):
        monkeypatch.setattr(mod, "QSettings", _FakeSettings)
    for name in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: QMessageBox.Ok)
    return cache


def _switch_theme(name: str):
    """
    Cambia il tema come apply_theme ma senza riapplicare il QSS a tutta l'app:
    nei test restano vivi molti widget e il restyle globale sarebbe lentissimo.
    """
    from ui import theme
    theme.set_theme(name)
    theme.MANAGER.theme_changed.emit(name)


@pytest.fixture
def dark_theme(app):
    from ui import theme
    _switch_theme("dark")
    yield theme
    _switch_theme("dark")


def _subs(n=3, step=2.0):
    return [Subtitle(start=i * step, end=i * step + 1.5, text=f"Riga {i + 1}")
            for i in range(n)]


class _StubPlayer(QObject):
    """Player finto: registra seek/rate senza backend multimediale."""

    position_changed = Signal(int)
    duration_changed = Signal(int)
    state_changed = Signal(str)
    source_ready = Signal()
    rate_changed = Signal(float)
    error_occurred = Signal(str)

    def __init__(self):
        super().__init__()
        self.seeks: list = []
        self._pos = 0
        self._rate = 1.0
        self.playing = True

    def seek(self, ms):
        self.seeks.append(ms)
        self._pos = ms

    def seek_relative(self, d):
        self.seek(self._pos + d)

    def position(self):
        return self._pos

    def is_playing(self):
        return self.playing

    def rate(self):
        return self._rate

    def set_rate(self, r):
        self._rate = r
        self.rate_changed.emit(r)

    def pause(self):
        self.playing = False

    def play(self):
        self.playing = True

    def toggle_play_pause(self):
        self.playing = not self.playing

    def set_volume(self, _v):
        pass


@pytest.fixture
def timeline(app):
    from ui.subtitle_timeline import SubtitleTimeline
    tl = SubtitleTimeline()
    player = _StubPlayer()
    tl.set_player(player)
    tl.load_subtitles(_subs(5))
    tl.resize(900, 500)
    tl.show()
    yield tl, player
    tl.hide()
    tl.deleteLater()


# ── Tema: nessun colore letterale nei widget ──────────────────────────────────

_HEX = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?:[0-9a-fA-F]{2})?\b")
_RGB = re.compile(r"\brgba?\s*\(")


def _string_literals(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_no_color_literals_outside_theme():
    offenders = []
    for path in sorted(UI_DIR.glob("*.py")):
        if path.name == "theme.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, value in _string_literals(tree):
            if _HEX.search(value) or _RGB.search(value):
                offenders.append(f"{path.name}:{lineno}: {value[:60]!r}")
        # QColor(255, 255, 255, …) / QColor("…") costruiti con numeri letterali
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "QColor"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                offenders.append(f"{path.name}:{node.lineno}: QColor letterale")
    assert offenders == []


def test_source_panel_removed():
    assert not (UI_DIR / "source_panel.py").exists()


# ── Tema: token, provider colori, QPalette, contrasto ─────────────────────────

def test_palettes_have_same_keys():
    from ui import theme
    assert set(theme.PALETTE_DARK) == set(theme.PALETTE_LIGHT)
    for key in ("row_error_bg", "row_warning_bg", "acc_fill", "focus", "knob",
                "video_bg", "overlay_bg", "overlay_fg", "wave_outline"):
        assert key in theme.PALETTE_DARK


def test_qcolor_parses_rgba():
    from ui import theme
    col = theme.qcolor("row_error_bg", "dark")
    assert col.isValid() and 0 < col.alpha() < 255


def _lum(hexcol: str) -> float:
    h = hexcol.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


@pytest.mark.parametrize("name", ["dark", "light"])
def test_text_tokens_meet_wcag_aa(name):
    from ui import theme
    t = theme.tokens(name)
    pairs = [(fg, bg) for fg in ("text", "dim", "muted")
             for bg in ("bg", "surface", "card", "card_2")]
    pairs += [(fg, bg) for fg in ("acc", "ok", "warn", "err") for bg in ("bg", "card", "card_2")]
    pairs += [("acc_ink", "acc_fill"), ("acc_ink", "acc_fill_h"), ("acc_ink", "acc_fill_d")]
    low = [(fg, bg, round(_contrast(t[fg], t[bg]), 2)) for fg, bg in pairs
           if _contrast(t[fg], t[bg]) < 4.5]
    assert low == []


def test_apply_theme_sets_palette(dark_theme, monkeypatch):
    from PySide6.QtGui import QPalette

    class _App:
        palette = sheet = None

        def setPalette(self, p):  # noqa: N802
            self.palette = p

        def setStyleSheet(self, s):  # noqa: N802
            self.sheet = s

    fake = _App()
    dark_theme.apply_theme(fake, "light")
    assert fake.palette.color(QPalette.Window) == dark_theme.qcolor("bg", "light")
    assert fake.palette.color(QPalette.Highlight) == dark_theme.qcolor("acc_fill", "light")
    assert dark_theme.c("focus", "light") in fake.sheet
    dark_theme.apply_theme(fake, "dark")
    assert fake.palette.color(QPalette.Window) == dark_theme.qcolor("bg", "dark")


def test_table_colors_follow_theme(dark_theme, app):
    from core.subtitle_table_model import COL_INDEX
    from ui.subtitle_timeline import SubtitleTimeline
    tl = SubtitleTimeline()
    tl.load_subtitles([Subtitle(0.0, 1.0, "")])   # testo vuoto → riga in errore
    idx = tl.model.index(0, COL_INDEX)
    bg_dark = tl.model.data(idx, Qt.BackgroundRole).color()
    assert bg_dark == dark_theme.qcolor("row_error_bg", "dark")

    changed = []
    tl.model.dataChanged.connect(lambda *a: changed.append(a))
    _switch_theme("light")
    assert changed, "al cambio tema la tabella deve riemettere dataChanged"
    assert tl.model.data(idx, Qt.BackgroundRole).color() == \
        dark_theme.qcolor("row_error_bg", "light")
    assert tl.model.data(idx, Qt.ForegroundRole).color() == dark_theme.qcolor("muted", "light")


# ── Transport ────────────────────────────────────────────────────────────────

def test_seek_slider_click_seeks(app):
    from ui.transport_bar import TransportBar
    bar = TransportBar()
    player = _StubPlayer()
    bar.bind_player(player)
    bar._on_duration_changed(10_000)
    bar._on_source_ready()
    bar.resize(900, 48)
    bar.show()
    slider = bar.seek_slider
    slider.resize(600, 24)
    x = int(slider.width() * 0.75)
    QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier, QPoint(x, slider.height() // 2))
    assert player.seeks, "il click sul binario deve fare seek"
    assert 6000 <= player.seeks[-1] <= 9000

    # Aggiornamenti dal player non generano seek
    player.seeks.clear()
    bar._on_position_changed(2000)
    assert player.seeks == []
    bar.deleteLater()


def test_rate_combo_follows_player(app):
    from ui.transport_bar import TransportBar
    bar = TransportBar()
    player = _StubPlayer()
    bar.bind_player(player)
    player.set_rate(2.0)
    assert bar.rate_combo.currentData() == 2.0
    player.set_rate(0.25)
    assert bar.rate_combo.currentText() == "0.25×"
    bar.deleteLater()


def test_jkl_rate_steps_and_k_resets(timeline):
    tl, player = timeline
    player.playing = True
    tl._jkl_l()
    assert player.rate() == 1.25
    tl._jkl_l()
    assert player.rate() == 1.5
    tl._jkl_j()
    assert player.rate() == 1.25
    tl._jkl_k()
    assert player.rate() == 1.0 and not player.playing
    # Da fermo: J torna indietro di 2 s
    player._pos = 5000
    tl._jkl_j()
    assert player.seeks[-1] == 3000


def test_audio_player_emits_rate_changed(app):
    from core.audio_player import AudioPlayer
    p = AudioPlayer()
    got = []
    p.rate_changed.connect(got.append)
    p.set_rate(1.5)
    assert got == [1.5]


def test_loop_returns_to_subtitle_start(timeline):
    tl, player = timeline
    tl.view.selectRow(1)                     # sottotitolo 2: 2.0–3.5 s
    tl.set_loop(True)
    assert player.seeks[-1] == 2000          # fuori dal sottotitolo → salta all'inizio
    player.position_changed.emit(3600)       # oltre la fine
    assert player.seeks[-1] == 2000
    assert tl._current_row() == 1            # il loop non sposta la selezione


def test_transport_loop_button_wired(app):
    from ui.workspace import WorkspaceWidget
    ws = WorkspaceWidget()
    ws.preview.transport.btn_loop.setEnabled(True)
    ws.preview.transport.btn_loop.setChecked(True)
    assert ws.timeline.is_looping()
    ws.deleteLater()


# ── Follow-playback ──────────────────────────────────────────────────────────

def test_follow_playback_moves_selection(timeline):
    tl, player = timeline
    player.position_changed.emit(int(4.5 * 1000))   # dentro il sottotitolo 3
    assert tl._current_row() == 2


def test_follow_playback_keeps_multi_selection(timeline):
    tl, player = timeline
    sm = tl.view.selectionModel()
    from PySide6.QtCore import QItemSelectionModel
    for r in (0, 1, 2):
        sm.select(tl.model.index(r, 0),
                  QItemSelectionModel.Select | QItemSelectionModel.Rows)
    player.position_changed.emit(8200)              # dentro il sottotitolo 5
    assert len(sm.selectedRows()) == 3


def test_follow_playback_keeps_uncommitted_inspector_text(timeline):
    tl, player = timeline
    tl.view.selectRow(0)
    tl.inspector.text_edit.setPlainText("Testo in corso di modifica")
    player.position_changed.emit(4500)
    assert tl._current_row() == 0
    assert tl.inspector.text_edit.toPlainText() == "Testo in corso di modifica"
    assert tl.undo_stack.count() == 0


def test_follow_playback_paused_while_inspector_has_focus(timeline, monkeypatch):
    tl, player = timeline
    tl.view.selectRow(0)
    # La piattaforma offscreen non assegna il focus reale: lo si simula
    monkeypatch.setattr(QApplication, "focusWidget",
                        staticmethod(lambda: tl.inspector.start_spin))
    player.position_changed.emit(4500)
    assert tl._current_row() == 0


def test_inspector_commits_text_on_focus_out(timeline):
    tl, _player = timeline
    tl.view.selectRow(0)
    tl.inspector.text_edit.setPlainText("Nuovo testo")
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    QApplication.sendEvent(tl.inspector.text_edit, QFocusEvent(QEvent.FocusOut))
    assert tl.model.subtitle_at(0).text == "Nuovo testo"
    assert tl.undo_stack.count() == 1
    tl.undo_stack.undo()
    assert tl.model.subtitle_at(0).text == "Riga 1"


def test_row_at_time_uses_index(timeline):
    tl, _ = timeline
    assert tl.row_at_time(0.5) == 0
    assert tl.row_at_time(1.8) == -1     # tra due sottotitoli
    assert tl.row_at_time(8.1) == 4


# ── Tabella: click con modificatori, Canc ─────────────────────────────────────

def test_modifier_click_on_text_does_not_edit(timeline, monkeypatch):
    from core.subtitle_table_model import COL_TEXT
    tl, player = timeline
    monkeypatch.setattr(QApplication, "keyboardModifiers",
                        staticmethod(lambda: Qt.ShiftModifier))
    tl._on_cell_clicked(tl.model.index(2, COL_TEXT))
    assert tl.view.state() != QAbstractItemView.EditingState
    assert player.seeks == []


def test_delete_key_removes_selected_rows(timeline):
    from PySide6.QtGui import QShortcut
    tl, _ = timeline
    tl.view.selectRow(1)
    shortcuts = [sc for sc in tl.view.findChildren(QShortcut)
                 if sc.key().matches(Qt.Key_Delete) and sc.context() == Qt.WidgetShortcut]
    assert shortcuts, "Canc sulla tabella deve eliminare le righe selezionate"
    shortcuts[0].activated.emit()
    assert tl.model.rowCount() == 4
    assert tl.undo_stack.count() == 1


def test_empty_table_shows_placeholder(timeline):
    tl, _ = timeline
    tl.load_subtitles([])
    assert tl._central_stack.currentWidget() is tl._empty_lbl
    tl.load_subtitles(_subs(1))
    assert tl._central_stack.currentWidget() is tl.view


# ── Debounce sincronizzazioni ─────────────────────────────────────────────────

def test_preview_sync_is_debounced(app):
    from ui.workspace import WorkspaceWidget
    ws = WorkspaceWidget()
    ws.timeline.load_subtitles(_subs(20))
    calls = []
    orig = ws.preview.set_subtitles
    ws.preview.set_subtitles = lambda *a: (calls.append(1), orig(*a))
    for r in range(10):
        ws.timeline._on_insp_text(r, f"modificato {r}")
    assert calls == []           # nessuna sincronizzazione O(N) per ogni modifica
    assert ws._sync_timer.isActive() and ws._sync_timer.isSingleShot()
    assert ws.timeline._status_timer.isActive()
    ws._sync_timer.timeout.emit()   # scadenza del debounce (senza girare l'event loop)
    assert len(calls) == 1
    ws.deleteLater()


# ── Waveform ─────────────────────────────────────────────────────────────────

def _write_wav(path: Path, seconds: float, rate: int = 16000):
    import numpy as np
    import soundfile as sf
    t = np.arange(int(seconds * rate)) / rate
    data = (0.5 * np.sin(2 * np.pi * 220 * t)).astype("float32")
    data[: rate] *= 0.1      # primo secondo più basso
    sf.write(str(path), np.stack([data, data * 0.5], axis=1), rate)
    return str(path)


def test_waveform_peaks_bounded_and_paint(app, tmp_path):
    pytest.importorskip("soundfile")
    from ui.waveform_widget import compute_peaks, WaveformWidget
    path = _write_wav(tmp_path / "lungo.wav", 60.0)
    target = 512
    mins, maxs, bucket, sr, frames = compute_peaks(path, target=target)
    assert sr == 16000 and frames == 60 * 16000
    assert 0 < len(mins) == len(maxs) <= 2 * target
    assert float(maxs.max()) == pytest.approx(1.0, abs=1e-3)
    assert (mins <= maxs).all()

    wf = WaveformWidget()
    wf.resize(800, 160)
    wf.set_duration(60_000)
    wf._on_loader_done(wf._load_generation, (mins, maxs, bucket, sr, frames))
    wf.set_subtitles(_subs(10, step=5.0), ["ok", "warning", "error"] * 3 + ["ok"])
    wf.set_selected_row(2)
    wf.set_position(12_000)
    pix = QPixmap(800, 160)
    p = QPainter(pix)
    wf.render_static(p, 800, 160)
    p.end()
    # Anche il paintEvent reale (con cache)
    wf.grab()
    assert wf._cache is not None


def test_peak_accumulator_bounded_for_unknown_length():
    import numpy as np
    from ui.waveform_widget import PeakAccumulator
    acc = PeakAccumulator(target=100, bucket_size=1)
    rng = np.random.default_rng(0)
    for _ in range(300):                       # flusso lungo, durata non nota
        acc.add(rng.uniform(-1, 1, 4096).astype("float32"))
        assert acc.bucket_count <= 200
    mins, maxs, bucket = acc.result()
    assert len(mins) <= 200
    assert bucket * (len(mins) - 1) < acc.frames <= bucket * len(mins)


def test_waveform_background_loader(app, tmp_path):
    pytest.importorskip("soundfile")
    from ui.waveform_widget import WaveformWidget
    wf = WaveformWidget()
    wf.resize(400, 120)
    wf.load_audio(_write_wav(tmp_path / "breve.wav", 2.0))
    wf._loader.join(10)
    # consegna solo le chiamate accodate al widget (QueuedConnection)
    QApplication.sendPostedEvents(wf, 0)
    assert not wf._loading and wf._mins is not None
    assert wf._duration_ms == 2000


def test_waveform_click_seeks_once_and_drag_pans(app):
    from ui.waveform_widget import WaveformWidget
    wf = WaveformWidget()
    wf.resize(1000, 200)
    wf.set_duration(10_000)
    wf._view_start_ms, wf._view_end_ms = 2000.0, 6000.0
    seeks = []
    wf.seek_requested.connect(seeks.append)
    QTest.mouseClick(wf, Qt.LeftButton, Qt.NoModifier, QPoint(500, 20))
    assert len(seeks) == 1 and seeks[0] == pytest.approx(4000, abs=10)

    seeks.clear()
    QTest.mousePress(wf, Qt.LeftButton, Qt.NoModifier, QPoint(500, 20))
    QTest.mouseMove(wf, QPoint(400, 20))
    from PySide6.QtGui import QMouseEvent
    move = QMouseEvent(QMouseEvent.MouseMove, QPointF(300, 20), QPointF(300, 20),
                       Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(wf, move)
    QTest.mouseRelease(wf, Qt.LeftButton, Qt.NoModifier, QPoint(300, 20))
    assert seeks == []                         # il pan non sposta il playhead
    assert wf._view_start_ms > 2000.0


# ── ResultWidget virtualizzato ───────────────────────────────────────────────

def test_result_preview_is_virtualized(app):
    from ui.result_widget import ResultWidget
    rw = ResultWidget()
    labels_before = len(rw.findChildren(QLabel))
    segs = [{"start": i * 1.0, "end": i * 1.0 + 0.8, "text": f"seg {i}"} for i in range(3000)]
    rw.show_result(segs, "/tmp/video.mp4")
    assert rw._preview_model.rowCount() == 3000
    assert len(rw.findChildren(QLabel)) == labels_before   # nessun widget per segmento
    assert rw._preview_stack.currentIndex() == 0


def test_result_empty_state(app):
    from ui.result_widget import ResultWidget
    rw = ResultWidget()
    fired = []
    rw.new_requested.connect(lambda: fired.append(1))
    rw.show_result([], "/tmp/video.mp4")
    assert rw._preview_stack.currentIndex() == 1
    assert not rw.editor_btn.isEnabled()
    rw._retry_btn.click()
    assert fired == [1]


# ── ExportPanel: niente percorsi stantii ─────────────────────────────────────

def test_export_panel_path_follows_project(app, tmp_path):
    from core.subtitle_model import SubtitleProject
    from ui.export_panel import ExportPanel
    proj = {"p": SubtitleProject(source_path=str(tmp_path / "primo.mp4"), subtitles=_subs(1))}
    panel = ExportPanel(get_project_callable=lambda: proj["p"])
    panel.refresh_from_project()
    assert Path(panel.path_edit.text()).stem.startswith("primo")
    proj["p"] = SubtitleProject(source_path=str(tmp_path / "secondo.mp4"), subtitles=_subs(1))
    panel.refresh_from_project()
    assert Path(panel.path_edit.text()).stem.startswith("secondo")
    proj["p"] = SubtitleProject(source_path="", subtitles=_subs(1))
    panel.refresh_from_project()
    assert panel.path_edit.text() == ""


def test_export_panel_is_child_of_project(app):
    from ui.project_widget import ProjectWidget
    pw = ProjectWidget(1, ffmpeg_ok=True, model_ok=True)
    assert pw._export_panel.parent() is pw
    pw.teardown()
    pw.deleteLater()


# ── QSettings: liste ─────────────────────────────────────────────────────────

def test_read_list_handles_single_string():
    from ui.prefs import read_list, add_recent

    class S(_FakeSettings):
        pass
    s = S()
    S.store = {"recent_files": "/percorso/unico.mp4"}
    assert read_list(s, "recent_files") == ["/percorso/unico.mp4"]
    S.store = {}
    assert read_list(s, "recent_files") == []
    add_recent(s, "/a.mp4")
    add_recent(s, "/b.mp4")
    add_recent(s, "/a.mp4")
    assert S.store["recent_files"] == ["/a.mp4", "/b.mp4"]


def test_recent_menu_survives_single_string(app):
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    existing = str(Path(__file__))
    _FakeSettings.store["recent_files"] = existing
    win._populate_recent_menu()
    texts = [a.text() for a in win._menu_recent.actions()]
    assert any(Path(existing).name in t for t in texts)
    for pw in win._projects:
        pw.teardown()
    win.deleteLater()


# ── Autosave per processo ────────────────────────────────────────────────────

def test_autosave_name_is_per_process(app, _isolate):
    from ui.project_widget import ProjectWidget, autosave_in_use
    pw = ProjectWidget(3, ffmpeg_ok=True, model_ok=True)
    path = pw.autosave_path()
    assert path.name == f"autosave_{os.getpid()}_3.v2srt"
    assert autosave_in_use(path)                       # questo processo è vivo
    assert not autosave_in_use(_isolate / "autosave_7.v2srt")   # nome storico
    stale = _isolate / "session_999999.lock"
    from PySide6.QtCore import QSysInfo
    # formato QLockFile: pid, nome app, host — stesso host, processo inesistente
    stale.write_text(f"999999\n{QApplication.applicationName()}\n"
                     f"{QSysInfo.machineHostName()}\n")
    assert not autosave_in_use(_isolate / "autosave_999999_1.v2srt")
    pw.teardown()
    pw.deleteLater()


def test_restore_skips_autosaves_of_live_instances(app, _isolate, monkeypatch):
    from core.subtitle_model import SubtitleProject
    from core.v2srt_io import save_project
    from ui.main_window import MainWindow
    mine = _isolate / f"autosave_{os.getpid()}_5.v2srt"
    save_project(SubtitleProject(subtitles=_subs(2)), str(mine))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(1))
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    win._check_autosave_restore()
    assert asked == []            # nessuna domanda: il file è di un'istanza viva
    assert mine.exists()          # e non viene cancellato
    for pw in win._projects:
        pw.teardown()
    win.deleteLater()


# ── Home: tastiera, drag&drop rifiutato con messaggio ─────────────────────────

def _drop(widget, path: str):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    widget.dropEvent(ev)


def test_home_drop_unsupported_shows_error(app, tmp_path):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    bad = tmp_path / "documento.pdf"
    bad.write_bytes(b"%PDF")
    _drop(home.drop, str(bad))
    assert home.drop._state == home.drop._ERROR
    assert "pdf" in home.drop._err_t1.text()
    assert not home.start_btn.isEnabled()


def test_home_drop_subtitle_forwards_to_editor(app, tmp_path):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    srt = tmp_path / "sub.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nCiao\n", encoding="utf-8")
    got = []
    home.open_requested.connect(got.append)
    _drop(home.drop, str(srt))
    assert got == [str(srt)]


def test_home_preload_rejects_unknown_extension(app, tmp_path):
    from ui.home_widget import HomeWidget
    home = HomeWidget()
    f = tmp_path / "strano.xyz"
    f.write_text("x")
    home.preload_file(str(f))
    assert home._source_path is None
    assert home.drop._state == home.drop._ERROR


def test_toggle_switch_keyboard(app):
    from ui.home_widget import _ToggleSwitch
    sw = _ToggleSwitch("Attivo", "Disattivo", name="Filtro VAD")
    assert sw.focusPolicy() & Qt.TabFocus
    QTest.keyClick(sw, Qt.Key_Space)
    assert sw.isChecked()
    assert sw.accessibleName() == "Filtro VAD: Attivo"


# ── Accessibilità ────────────────────────────────────────────────────────────

def test_glyph_only_buttons_have_accessible_names(app):
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    pw = win._active()
    pw.workspace.timeline.load_subtitles(_subs(2))
    missing = []
    from PySide6.QtWidgets import QLineEdit
    for btn in win.findChildren(QAbstractButton):
        # pulsanti interni di Qt (estensione toolbar/menu, angolo tabella, clear dei campi)
        if btn.objectName().startswith("qt_") or isinstance(btn.parent(), QLineEdit):
            continue
        text = btn.text().replace("&", "")
        if not any(ch.isalpha() for ch in text) and not btn.accessibleName():
            missing.append(f"{type(btn).__name__}({text!r})")
    assert missing == []
    for p in win._projects:
        p.teardown()
    win.deleteLater()


def test_inspector_labels_are_italian(app):
    from ui.inspector_widget import InspectorWidget
    insp = InspectorWidget()
    texts = {lbl.text() for lbl in insp.findChildren(QLabel)}
    assert "Inizio" in texts and "Fine" in texts
    assert "Start" not in texts and "End" not in texts


def test_export_panel_no_second_overwrite_prompt_after_file_dialog(app, tmp_path, monkeypatch):
    from core.subtitle_model import SubtitleProject
    from PySide6.QtWidgets import QFileDialog
    from ui.export_panel import ExportPanel
    target = tmp_path / "esistente.srt"
    target.write_text("vecchio", encoding="utf-8")
    proj = SubtitleProject(source_path="", subtitles=_subs(1))
    panel = ExportPanel(get_project_callable=lambda: proj)
    try:
        panel.refresh_from_project()
        asked = []
        monkeypatch.setattr(panel, "_resolve_existing", lambda p: asked.append(p) or p)
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(target), "")))
        panel._browse()
        panel._save()
        assert asked == []
        assert "vecchio" not in target.read_text(encoding="utf-8")
        # percorso digitato a mano e già esistente: la conferma serve ancora
        other = tmp_path / "altro.srt"
        other.write_text("x", encoding="utf-8")
        panel.path_edit.setText(str(other))
        panel._save()
        assert asked == [str(other)]
    finally:
        panel.close()
        panel.deleteLater()


# ── Pulsante di overflow della toolbar: mai l'icona di sistema ───────────────

def test_extension_buttons_use_painted_icon_and_survive_style_change(app):
    """Regressione: su macOS l'icona di sistema del pulsante "»" mandava in crash
    l'app al primo disegno dell'editor. Deve restare la nostra anche dopo un cambio
    di stile (Qt la ripristina) e un cambio di tema."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QToolButton
    from ui import theme
    from ui.main_window import MainWindow
    from ui.widgets import _ExtensionIconGuard

    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    buttons = [b for b in win.findChildren(QToolButton)
               if b.objectName() in ("qt_toolbar_ext_button", "qt_menubar_ext_button")]
    assert buttons, "nessun pulsante di overflow trovato"

    def assert_guarded():
        for b in buttons:
            guard = b.findChild(_ExtensionIconGuard)
            assert guard is not None, b.objectName()
            b.grab()   # forza un paint: il guard deve aver rimesso la nostra icona
            assert b.icon().cacheKey() == guard._key, b.objectName()

    assert_guarded()
    for b in buttons:   # Qt reimposta l'icona di sistema a ogni StyleChange
        QApplication.sendEvent(b, QEvent(QEvent.StyleChange))
    assert_guarded()
    theme.toggle_theme(app)
    try:
        assert_guarded()
    finally:
        theme.toggle_theme(app)


# ── "Alta precisione": mai un'opzione che non fa nulla ───────────────────────

def test_accuracy_toggle_disabled_when_whisperx_missing(app, monkeypatch):
    import engine
    from ui.home_widget import HomeWidget
    monkeypatch.setattr(engine, "high_accuracy_unavailable_reason",
                        lambda: "WhisperX non è installato (pip install whisperx)")
    home = HomeWidget()
    tog = home.accuracy_toggle
    assert not tog.isEnabled()
    assert not tog.isChecked()
    assert "WhisperX" in tog.toolTip()
    tog._toggle()                       # click/tastiera non devono attivarla
    assert not tog.isChecked()
    assert home._get_settings()["high_accuracy"] is False


def test_accuracy_toggle_enabled_when_whisperx_present(app, monkeypatch):
    import engine
    from ui.home_widget import HomeWidget
    monkeypatch.setattr(engine, "high_accuracy_unavailable_reason", lambda: "")
    home = HomeWidget()
    assert home.accuracy_toggle.isEnabled()
    home.accuracy_toggle._toggle()
    assert home._get_settings()["high_accuracy"] is True


# ── Cambio tab progetto: status bar, titolo finestra, riproduzione ───────────

def _two_project_window(app):
    from ui.main_window import MainWindow
    win = MainWindow(ffmpeg_ok=True, model_ok=True)
    win._new_project()
    assert len(win._projects) == 2
    return win


def _dispose_window(win):
    for pw in win._projects:
        pw.teardown()
    win.deleteLater()


def test_switching_project_tab_refreshes_status_bar_and_title(app):
    win = _two_project_window(app)
    p1, p2 = win._projects
    p1._set_title("Alfa")
    p1.status_text.emit("5 sottotitoli  ●  Modificato")
    p2._set_title("Beta")
    p2.status_text.emit("2 sottotitoli")
    # p2 è attivo: lo stato di p1 (emesso in background) non deve sovrascriverlo
    assert win.status_main.text() == "2 sottotitoli"
    assert win.windowTitle().startswith("Beta")

    win.proj_tab_bar.select_tab(0)
    assert win.status_main.text() == "5 sottotitoli  ●  Modificato"
    assert win.windowTitle().startswith("Alfa")

    win.proj_tab_bar.select_tab(1)
    assert win.status_main.text() == "2 sottotitoli"
    assert win.windowTitle().startswith("Beta")
    _dispose_window(win)


def test_status_survives_closing_another_project_tab(app):
    win = _two_project_window(app)
    win._new_project()
    p1, p2, p3 = win._projects
    p1.status_text.emit("7 sottotitoli")
    win._on_tab_close_requested(2)           # ricollega i segnali dei rimasti
    p1.status_text.emit("8 sottotitoli")
    win.proj_tab_bar.select_tab(1)
    win.proj_tab_bar.select_tab(0)
    assert win.status_main.text() == "8 sottotitoli"
    _dispose_window(win)


def _spy_playback(pw, monkeypatch):
    calls = []
    player = pw.workspace.preview.player
    monkeypatch.setattr(player, "is_playing", lambda: True)
    monkeypatch.setattr(player, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(player, "play", lambda: calls.append("play"))
    return calls


def test_leaving_editor_tab_pauses_playback(app, monkeypatch):
    from ui.project_widget import ProjectWidget
    pw = ProjectWidget(1, ffmpeg_ok=True, model_ok=True)
    calls = _spy_playback(pw, monkeypatch)
    pw._on_tab_changed(1)
    assert calls == []
    pw._on_tab_changed(2)        # Editor → Esportazione
    assert calls == ["pause"]
    pw._on_tab_changed(1)
    pw._on_tab_changed(0)        # Editor → Trascrizione
    assert calls == ["pause", "pause"]
    assert "play" not in calls   # nessuna ripresa automatica
    pw.teardown()
    pw.deleteLater()


def test_switching_project_tab_pauses_previous_player(app, monkeypatch):
    win = _two_project_window(app)
    p1, p2 = win._projects
    c1 = _spy_playback(p1, monkeypatch)
    c2 = _spy_playback(p2, monkeypatch)
    win.proj_tab_bar.select_tab(0)       # da p2 a p1
    assert c2 == ["pause"] and c1 == []
    win.proj_tab_bar.select_tab(1)       # da p1 a p2
    assert c1 == ["pause"] and c2 == ["pause"]
    _dispose_window(win)


# ── Larghezze colonne tabella sottotitoli persistite ─────────────────────────

def test_table_header_state_is_persisted(app, monkeypatch):
    import ui.subtitle_timeline as stl
    from PySide6.QtTest import QTest
    monkeypatch.setattr(stl, "QSettings", _FakeSettings, raising=False)
    tl = stl.SubtitleTimeline()
    tl.view.horizontalHeader().resizeSection(stl.COL_START, 187)
    QTest.qWait(700)                      # debounce del salvataggio
    assert _FakeSettings.store.get("subtitle_table_header")
    tl.deleteLater()

    tl2 = stl.SubtitleTimeline()
    assert tl2.view.horizontalHeader().sectionSize(stl.COL_START) == 187
    tl2.deleteLater()


@pytest.mark.parametrize("bad", [b"garbage", b"", "stringa", 42])
def test_table_header_state_stale_is_ignored(app, monkeypatch, bad):
    import ui.subtitle_timeline as stl
    monkeypatch.setattr(stl, "QSettings", _FakeSettings, raising=False)
    _FakeSettings.store["subtitle_table_header"] = bad
    tl = stl.SubtitleTimeline()          # non deve sollevare
    assert tl.view.horizontalHeader().count() == 6
    tl.deleteLater()


# ── Freccia dei combo: chevron PNG, non triangolo CSS ────────────────────────

@pytest.mark.parametrize("name", ["dark", "light"])
def test_combo_arrow_uses_chevron_image(app, name):
    from ui import theme
    qss = theme.build_stylesheet(name)
    block = qss.split("QComboBox::down-arrow")[1].split("}")[0]
    assert "image: url(" in block
    assert "border-top" not in block and "transparent" not in block
    url = block.split("url(")[1].split(")")[0].strip("\"'")
    assert "\\" not in url
    img = QPixmap(url)
    assert not img.isNull()
    # il chevron è disegnato col colore "muted" del tema
    want = theme.qcolor("muted", name)
    seen = {img.toImage().pixelColor(x, y).rgb()
            for x in range(img.width()) for y in range(img.height())
            if img.toImage().pixelColor(x, y).alpha() > 200}
    assert want.rgb() in seen
    assert Path(url).name.startswith("chevron")


def test_combo_arrow_falls_back_when_cache_unwritable(app, monkeypatch, tmp_path):
    from ui import theme
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(platform_support, "app_cache_dir", lambda: blocker)
    theme._CHEVRON_CACHE.clear()
    qss = theme.build_stylesheet("dark")        # non deve sollevare
    assert "QComboBox::down-arrow" in qss
    assert "QComboBox::down-arrow {\n        image: none" in qss or "url(" not in \
        qss.split("QComboBox::down-arrow")[1].split("}")[0]


def test_home_combo_uses_chevron_image(app):
    from ui import home_widget
    ss = home_widget._combo_ss()
    assert "image: url(" in ss and "border-top: 5px" not in ss
