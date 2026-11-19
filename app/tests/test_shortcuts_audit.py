"""
test_shortcuts_audit.py — Audit delle scorciatoie sulla MainWindow reale.

Per ogni scorciatoia della tabella in CLAUDE.md (e per quelle registrate altrove in
`app/ui`) si preme la sequenza VERA (QTest.keySequence, passando dalla mappa delle
scorciatoie di Qt) sul widget col focus in situazioni realistiche — tabella, ricerca,
testo dell'inspector, forma d'onda, pulsante della toolbar, slider, Home, Esportazione —
e si controlla se l'azione attesa è scattata. I tasti di riproduzione non devono
scattare mentre si scrive, né rubare Spazio ai pulsanti o le frecce al volume.

Nessun dialog reale: file dialog, esportazione, Trova e sostituisci, tema e schermo
intero sono sostituiti da registratori; la riproduzione audio non parte mai.
"""

from __future__ import annotations

import os
import struct
import sys
import wave

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QEvent, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton

import platform_support

N_SUBS = 12


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


def _write_wav(path, seconds=30.0, rate=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 800) * int(seconds * rate))
    return str(path)


def _never(*_a, **_k):
    return False


class Env:
    """Finestra reale con un progetto nell'editor (12 sottotitoli + WAV) e un secondo vuoto."""

    def __init__(self, win):
        self.win = win
        self.pw = win._projects[0]
        self.tl = self.pw.timeline
        self.player = self.pw.workspace.preview.player
        self.transport = self.pw.workspace.preview.transport
        self.waveform = self.pw.workspace.preview.waveform
        self.calls: list = []
        self.messages: list = []

    def recorder(self, name):
        def _rec(*_a, **_k):
            self.calls.append(name)
            return ("", "")
        return _rec


@pytest.fixture(autouse=True)
def _cleanup_top_level_widgets():
    """La finestra dell'audit vive per tutto il modulo: niente pulizia dopo ogni test."""
    yield


@pytest.fixture(scope="module")
def env(app, tmp_path_factory):
    import ui.home_widget as hwm
    import ui.main_window as mw
    import ui.project_widget as pwm
    import ui.subtitle_timeline as stl
    import ui.workspace as wsm
    from ui import theme

    mp = pytest.MonkeyPatch()
    for mod in (mw, pwm, wsm, stl, hwm):
        mp.setattr(mod, "QSettings", _FakeSettings)
    cache = tmp_path_factory.mktemp("cache")
    mp.setattr(platform_support, "app_cache_dir", lambda: cache)
    mp.setattr(platform_support, "legacy_cache_dirs", lambda: [])

    messages: list = []
    def _handler(kind, _ctx, msg):
        messages.append(msg)
        if kind in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg, QtMsgType.QtWarningMsg):
            # visibile nel log della CI se Qt fa abortire il processo (qFatal)
            print(f"[qt] {msg}", file=sys.__stderr__, flush=True)

    previous_handler = qInstallMessageHandler(_handler)

    win = mw.MainWindow(ffmpeg_ok=True, model_ok=True)
    e = Env(win)
    e.messages = messages
    mp.setattr(QFileDialog, "getOpenFileName", staticmethod(e.recorder("open_dialog")))
    mp.setattr(QFileDialog, "getSaveFileName", staticmethod(e.recorder("save_dialog")))
    for name in ("critical", "warning", "information", "question"):
        mp.setattr(QMessageBox, name, staticmethod(e.recorder(f"message_{name}")))
    mp.setattr(theme, "toggle_theme", e.recorder("toggle_theme"))

    wav = _write_wav(tmp_path_factory.mktemp("media") / "audio.wav")
    segs = [{"start": i * 2.0, "end": i * 2.0 + 1.5, "text": f"Riga {i + 1}"}
            for i in range(N_SUBS)]
    e.pw._on_transcription_done(segs, wav)
    e.pw._on_open_editor()
    win._new_project()                  # secondo progetto: Ctrl+Shift+] / [
    win.proj_tab_bar.select_tab(0)
    for p in win._projects:
        p.can_close = _never   # Ctrl+W: la richiesta arriva, ma il progetto non si chiude
    # azioni con finestre/dialog: registrate invece di aprirle
    e.pw.do_export = e.recorder("do_export")
    e.pw.save_v2srt = e.recorder("save_v2srt")
    e.pw._on_new_transcription_from_result = e.recorder("new_transcription")
    e.tl.open_find_replace = e.recorder("find_replace")
    win.showFullScreen = e.recorder("fullscreen")
    win.showNormal = e.recorder("fullscreen")
    # nessuna riproduzione reale
    e.player.play = e.recorder("play")
    e.player.pause = e.recorder("pause")
    e.player.toggle_play_pause = e.recorder("play_pause")
    win.proj_tab_bar.tab_close_requested.connect(e.recorder("close_tab"))

    win.resize(1400, 900)
    win.show()
    win.activateWindow()
    for _ in range(150):                 # fino a 3 s per il caricamento del media
        if e.player.is_ready():
            break
        QTest.qWait(20)
    if not e.player.is_ready():          # backend multimediale assente: il trasporto serve
        e.transport._on_source_ready()
    e.waveform.set_duration(30_000)
    e.transport._on_duration_changed(30_000)
    QApplication.processEvents()
    yield e

    qInstallMessageHandler(previous_handler)
    for p in win._projects:
        p.workspace.preview.player.unload()   # nessun media aperto alla distruzione
        p.teardown()
        p._export_panel.close()
    win.hide()
    win.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
    mp.undo()


# ── Contesti di focus ────────────────────────────────────────────────────────

_EDITOR, _HOME, _EXPORT = 1, 0, 2


def _focus_target(e, ctx):
    tl = e.tl
    if ctx == "tabella":
        return tl.view
    if ctx == "ricerca":
        return tl._search_box
    if ctx == "inspector":
        return tl.inspector.text_edit
    if ctx == "forma d'onda":
        return e.waveform
    if ctx == "pulsante":
        return next(b for b in tl.toolbar().findChildren(QPushButton)
                    if b.accessibleName() == "Dividi")
    if ctx == "volume":
        return e.transport.volume_slider
    if ctx == "slider posizione":
        return e.transport.seek_slider
    if ctx == "home":
        # tab Trascrizione dopo la trascrizione: schermata del risultato
        return e.pw.result.editor_btn
    if ctx == "esportazione":
        return next(b for b in e.pw.export_tab.findChildren(QPushButton)
                    if b.isVisible() and b.isEnabled())
    raise ValueError(ctx)


def _enter(e, ctx):
    win, pw, tl = e.win, e.pw, e.tl
    if win.proj_tab_bar.current_index() != 0:
        win.proj_tab_bar.select_tab(0)
    # testo dell'inspector non confermato di un caso precedente: scartato
    sub = tl.model.subtitle_at(tl._current_row())
    if sub is not None and tl.inspector.has_uncommitted_text():
        tl.inspector.text_edit.setPlainText(sub.text)
    tl._search_box.clear()
    if not tl.act_toggle_insp.isChecked():
        tl.act_toggle_insp.trigger()
    pw.tab_bar.set_current({"home": _HOME, "esportazione": _EXPORT}.get(ctx, _EDITOR))
    tl.view.selectRow(5)
    e.player.seek(10_000)
    e.calls.clear()
    target = _focus_target(e, ctx)
    win.activateWindow()
    target.setFocus()
    QApplication.processEvents()
    assert QApplication.focusWidget() is target, f"focus non su {ctx}"
    return target


# ── Sonde: preparano lo stato e dicono se l'azione è scattata ────────────────

def _called(name):
    def probe(e):
        return lambda: name in e.calls
    return probe


def _undo_probe(e):
    tl = e.tl
    tl._on_insp_text(0, tl.model.subtitle_at(0).text + " (mod)")
    index = tl.undo_stack.index()
    return lambda: tl.undo_stack.index() == index - 1


def _redo_probe(e):
    tl = e.tl
    tl._on_insp_text(0, tl.model.subtitle_at(0).text + " (mod)")
    tl.undo_stack.undo()
    index = tl.undo_stack.index()
    return lambda: tl.undo_stack.index() == index + 1


def _command_probe(e):
    stack = e.tl.undo_stack
    index = stack.index()
    return lambda: stack.index() == index + 1


def _inspector_probe(e):
    act = e.tl.act_toggle_insp
    before = act.isChecked()
    return lambda: act.isChecked() != before


def _new_project_probe(e):
    n = len(e.win._projects)
    return lambda: len(e.win._projects) == n + 1


def _tab_probe(e):
    return lambda: e.win.proj_tab_bar.current_index() != 0


def _search_focus_probe(e):
    return lambda: (QApplication.focusWidget() is e.tl._search_box
                    and e.pw.tab_bar.current() == _EDITOR)


def _export_tab_probe(e):
    return lambda: e.pw.tab_bar.current() == _EXPORT


def _position_probe(delta):
    def probe(e):
        start = e.player.position()
        return lambda: e.player.position() == start + delta
    return probe


def _jkl_probe(key, call):
    def probe(e):
        pressed = []
        e.tl.jkl_pressed.connect(pressed.append)
        e._jkl_conn = pressed
        return lambda: key in pressed and (call is None or call in e.calls)
    return probe


def _row_probe(delta):
    def probe(e):
        row = e.tl._current_row()
        return lambda: e.tl._current_row() == row + delta
    return probe


def _delete_probe(e):
    n = e.tl.model.rowCount()
    return lambda: e.tl.model.rowCount() == n - 1


# (sequenza, descrizione, sonda, gruppo)
SHORTCUTS = [
    ("Ctrl+Z", "Annulla", _undo_probe, "undo"),
    ("Ctrl+Shift+Z", "Ripeti", _redo_probe, "undo"),
    ("Ctrl+K", "Dividi", _command_probe, "editor"),
    ("Ctrl+M", "Unisci col successivo", _command_probe, "editor"),
    ("Ctrl+Shift+K", "Elimina selezionati", _command_probe, "editor"),
    ("Ctrl+F", "Trova (ricerca inline)", _search_focus_probe, "app"),
    ("Ctrl+Alt+F", "Trova e sostituisci", _called("find_replace"), "app"),
    ("Ctrl+I", "Mostra/nascondi Inspector", _inspector_probe, "editor"),
    ("Ctrl+O", "Apri file", _called("open_dialog"), "app"),
    ("Ctrl+N", "Nuova trascrizione", _called("new_transcription"), "app"),
    ("Ctrl+S", "Esporta SRT", _called("do_export"), "app"),
    ("Ctrl+E", "Tab Esportazione", _export_tab_probe, "app"),
    ("Ctrl+Shift+S", "Salva progetto .v2srt", _called("save_v2srt"), "app"),
    ("Ctrl+Shift+T", "Nuovo progetto", _new_project_probe, "app"),
    ("Ctrl+W", "Chiudi tab progetto", _called("close_tab"), "app"),
    ("Ctrl+Shift+]", "Tab progetto successivo", _tab_probe, "app"),
    ("Ctrl+Shift+[", "Tab progetto precedente", _tab_probe, "app"),
    (platform_support.project_tab_shortcuts()[0][1], "Tab progetto successivo (alt.)",
     _tab_probe, "app"),
    (platform_support.project_tab_shortcuts()[1][1], "Tab progetto precedente (alt.)",
     _tab_probe, "app"),
    ("Ctrl+Shift+L", "Cambia tema", _called("toggle_theme"), "app"),
    (platform_support.fullscreen_shortcut(), "Schermo intero", _called("fullscreen"), "app"),
    ("Space", "Play/Pausa", _called("play_pause"), "playback"),
    ("K", "Pausa", _jkl_probe("K", "pause"), "playback"),
    ("J", "Indietro 2 s", _position_probe(-2000), "playback"),
    ("L", "Play", _jkl_probe("L", "play"), "playback"),
    ("Left", "Seek −1 s", _position_probe(-1000), "playback"),
    ("Right", "Seek +1 s", _position_probe(+1000), "playback"),
    ("Shift+Left", "Sottotitolo precedente", _row_probe(-1), "playback"),
    ("Shift+Right", "Sottotitolo successivo", _row_probe(+1), "playback"),
    ("Delete", "Elimina (sulla tabella)", _delete_probe, "table"),
]

CONTEXTS = ("tabella", "ricerca", "inspector", "home", "esportazione")

# Dove ogni gruppo deve scattare (negli altri contesti il tasto resta al widget o
# l'azione non si applica: es. Dividi fuori dall'editor, J mentre si scrive)
EXPECTED = {
    "app": set(CONTEXTS),
    "editor": {"tabella", "ricerca", "inspector"},
    # nei campi di testo Annulla/Ripeti agiscono sul campo (comportamento standard)
    "undo": {"tabella", "home", "esportazione"},
    "playback": {"tabella"},
    "table": {"tabella"},
}


def _press(target, seq):
    QTest.keySequence(target, QKeySequence(seq))
    QApplication.processEvents()


def _cleanup(e):
    """Riporta la finestra allo stato iniziale dopo azioni con effetti reali."""
    win = e.win
    while len(win._projects) > 2:      # Ctrl+Shift+T
        win._on_tab_close_requested(len(win._projects) - 1)
    if win.proj_tab_bar.current_index() != 0:
        win.proj_tab_bar.select_tab(0)
    stack = e.tl.undo_stack
    if stack.count() > 40:
        stack.setIndex(0)
    if e.tl.model.rowCount() < 6:
        stack.setIndex(0)
    for conn in ("_jkl_conn",):
        if hasattr(e, conn):
            try:
                e.tl.jkl_pressed.disconnect()
            except (RuntimeError, TypeError):
                pass
            delattr(e, conn)


@pytest.mark.parametrize("ctx", CONTEXTS)
@pytest.mark.parametrize("seq,label,probe,group", SHORTCUTS,
                         ids=[s[0] for s in SHORTCUTS])
def test_shortcut(env, seq, label, probe, group, ctx):
    target = _enter(env, ctx)
    fired = probe(env)
    _press(target, seq)
    ok = fired()
    _cleanup(env)
    expected = ctx in EXPECTED[group]
    assert ok == expected, (
        f"{seq} ({label}) con il focus su {ctx}: "
        f"{'scattata' if ok else 'non scattata'}, attesa {'sì' if expected else 'no'}")


# ── Tasti di riproduzione e widget che li usano da sé ────────────────────────

def test_space_on_focused_button_clicks_it_instead_of_playing(env):
    target = _enter(env, "pulsante")
    index = env.tl.undo_stack.index()
    _press(target, "Space")
    assert env.tl.undo_stack.index() == index + 1, "Spazio deve premere «Dividi»"
    assert "play_pause" not in env.calls
    _cleanup(env)


def test_arrows_on_volume_slider_change_volume_not_position(env):
    target = _enter(env, "volume")
    vol, pos = target.value(), env.player.position()
    _press(target, "Left")
    assert target.value() < vol
    assert env.player.position() == pos
    _cleanup(env)


@pytest.mark.parametrize("ctx", ["forma d'onda", "slider posizione"])
def test_arrows_seek_when_waveform_or_position_slider_focused(env, ctx):
    target = _enter(env, ctx)
    pos = env.player.position()
    _press(target, "Right")
    assert env.player.position() == pos + 1000
    _press(target, "Left")
    _press(target, "Left")
    assert env.player.position() == pos - 1000
    _cleanup(env)


@pytest.mark.parametrize("seq", ["Space", "K", "L", "Shift+Right"])
def test_playback_keys_work_with_waveform_focused(env, seq):
    target = _enter(env, "forma d'onda")
    row = env.tl._current_row()
    pressed = []
    env.tl.jkl_pressed.connect(pressed.append)
    _press(target, seq)
    env.tl.jkl_pressed.disconnect(pressed.append)
    fired = {"Space": "play_pause" in env.calls, "K": "K" in pressed, "L": "L" in pressed,
             "Shift+Right": env.tl._current_row() == row + 1}[seq]
    assert fired
    _cleanup(env)


def test_typing_in_search_field_keeps_letters_and_space(env):
    target = _enter(env, "ricerca")
    QTest.keyClicks(target, "j k l")
    assert target.text() == "j k l"
    assert "play_pause" not in env.calls
    _cleanup(env)


def test_ctrl_return_commits_inspector_text(env):
    target = _enter(env, "inspector")
    row = env.tl._current_row()
    target.selectAll()
    QTest.keyClicks(target, "Nuovo testo")
    _press(target, "Ctrl+Return")
    assert env.tl.model.subtitle_at(row).text == "Nuovo testo"
    env.tl.undo_stack.undo()
    _cleanup(env)


def test_close_tab_shortcut_only_in_main_window(env):
    """Ctrl+W non deve chiudere un progetto quando il focus è in un'altra finestra."""
    from ui.find_replace_dialog import FindReplaceDialog
    dlg = FindReplaceDialog(env.tl.model)
    dlg.show()
    dlg.activateWindow()
    dlg.find_edit.setFocus()
    QApplication.processEvents()
    if QApplication.activeWindow() is not dlg:
        pytest.skip("la piattaforma non attiva il dialog")
    env.calls.clear()
    _press(dlg.find_edit, "Ctrl+W")
    assert "close_tab" not in env.calls
    assert not dlg.isVisible()          # Ctrl+W / ⌘W chiude il dialog
    dlg.close()
    _cleanup(env)


def test_no_ambiguous_shortcut_warnings(env):
    ambiguous = [m for m in env.messages if "mbiguous" in m]
    assert ambiguous == []
