"""
test_accessibility.py — Accessibilità da tastiera sulla MainWindow reale.

Coprono: ordine di Tab sensato (Home, risultato, Editor: toolbar → ricerca → tabella →
inspector → forma d'onda → trasporto, Esportazione, Trova e sostituisci) senza trappole
(la tabella non cattura Tab); anello di focus visibile su ogni fermata, nei due temi
(confronto dell'immagine con e senza focus, QSS globale applicato); nome accessibile su
ogni controllo raggiungibile (intestazione unificata, forma d'onda, slider, interruttori);
tooltip con la scorciatoia; forma d'onda e slider di posizione usabili da tastiera.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractScrollArea, QApplication, QComboBox, QFileDialog, QLineEdit,
    QMessageBox, QScrollBar, QWidget,
)

import platform_support

_sl = platform_support.shortcut_label


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
def _cleanup_top_level_widgets():
    """La finestra vive per tutto il modulo: niente pulizia dopo ogni test."""
    yield


@pytest.fixture(scope="module")
def win(app, tmp_path_factory):
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
    mp.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    mp.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    for name in ("critical", "warning", "information", "question"):
        mp.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
    previous_theme = theme.get_theme()
    theme.apply_theme(app, previous_theme)      # QSS globale: anelli di focus reali

    w = mw.MainWindow(ffmpeg_ok=True, model_ok=True)
    pw = w._projects[0]
    # Nessun media reale: il trasporto si abilita a mano. (Un QMediaPlayer con un file
    # aperto più il QSS globale applicato/rimosso rendevano instabile la distruzione dei
    # widget nei moduli successivi — crash intermittente di shiboken, solo nei test.)
    wav = str(tmp_path_factory.mktemp("media") / "audio.wav")   # non esiste
    segs = [{"start": i * 2.0, "end": i * 2.0 + 1.5, "text": f"Riga {i + 1}"}
            for i in range(12)]
    pw._on_transcription_done(segs, wav)
    pw._on_open_editor()
    pw.workspace.preview.transport._on_source_ready()
    pw.workspace.preview.waveform.set_duration(24_000)
    w._new_project()                 # secondo progetto: Home vera (zona di rilascio)
    w.proj_tab_bar.select_tab(0)
    w.resize(1400, 900)
    w.show()
    w.activateWindow()
    QApplication.processEvents()
    yield w

    for p in w._projects:
        p.workspace.preview.player.unload()   # nessun media aperto alla distruzione
        p.teardown()
        p._export_panel.close()
    w.hide()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
    theme.set_theme(previous_theme)
    app.setStyleSheet("")
    app.setPalette(app.style().standardPalette())
    mp.undo()


def _tab_walk(start, limit=80):
    """Sequenza dei widget col focus premendo Tab da `start` finché si torna all'inizio."""
    start.window().activateWindow()
    start.setFocus(Qt.TabFocusReason)
    QApplication.processEvents()
    assert QApplication.focusWidget() is start
    seen = [start]
    for _ in range(limit):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Tab)
        QApplication.processEvents()
        fw = QApplication.focusWidget()
        if fw is start:
            return seen
        assert fw not in seen, f"Tab bloccato su {type(fw).__name__} {fw.accessibleName()!r}"
        seen.append(fw)
    pytest.fail("Tab non torna al punto di partenza (trappola per la tastiera)")


def _label(w) -> str:
    return w.accessibleName() or (w.text() if isinstance(w, (QAbstractButton, QLineEdit))
                                  else "")


def _has_focus_ring(w) -> bool:
    w.clearFocus()
    QApplication.processEvents()
    before = w.grab().toImage()
    w.setFocus(Qt.TabFocusReason)
    QApplication.processEvents()
    after = w.grab().toImage()
    return before != after


def _show(win, project, tab):
    win.proj_tab_bar.select_tab(project)
    pw = win._projects[project]
    if tab is not None:
        pw.tab_bar.set_current(tab)
    QApplication.processEvents()
    return pw


def _first_tab(win):
    return win.proj_tab_bar._tabs[win.proj_tab_bar.current_index()]


# ── Ordine di Tab ────────────────────────────────────────────────────────────

_HEADER = ["Progetto", "Nuovo progetto", "Passa al tema", "Trascrizione", "Editor",
           "Esportazione"]


def _assert_order(names, expected):
    """Le etichette attese compaiono in quest'ordine (prefisso) nella sequenza di Tab."""
    pos = -1
    for exp in expected:
        idx = next((i for i, n in enumerate(names) if i > pos and n.startswith(exp)), None)
        assert idx is not None, f"{exp!r} non raggiunto con Tab (o fuori ordine): {names}"
        pos = idx


def test_tab_order_editor(win):
    _show(win, 0, 1)
    names = [_label(w) for w in _tab_walk(_first_tab(win))]
    _assert_order(names, _HEADER + [
        "Dividi", "Unisci", "Elimina", "Importa", "Trova e sostituisci", "Ispettore",
        "Cerca nei sottotitoli", "Esporta SRT", "Altri formati di esportazione",
        "Elenco sottotitoli", "Inizio sottotitolo", "Fine sottotitolo", "Sposta di −100 ms",
        "Sposta di +100 ms", "Testo del sottotitolo", "Forma d'onda", "Riproduci", "Ferma",
        "Posizione di riproduzione", "Volume", "Velocità di riproduzione",
        "Ripeti il sottotitolo selezionato",
    ])
    # la tabella è UNA fermata (Tab non salta di cella in cella)
    assert names.count("Elenco sottotitoli") == 1


def test_tab_order_result_and_export(win):
    _show(win, 0, 0)
    names = [_label(w) for w in _tab_walk(_first_tab(win))]
    _assert_order(names, _HEADER + ["Nuova trascrizione", "Esporta SRT", "Apri nell'editor"])
    _show(win, 0, 2)
    names = [_label(w) for w in _tab_walk(_first_tab(win))]
    _assert_order(names, _HEADER + ["SRT", "VTT", "TXT", "ASS", "Progetto .v2srt",
                                    "Anteprima SRT"])


def test_tab_order_home(win):
    pw = _show(win, 1, None)
    names = [_label(w) for w in _tab_walk(_first_tab(win))]
    assert pw.home.drop.accessibleName() in names
    assert any(n.startswith("Filtro VAD") for n in names)


def test_tab_order_find_replace_dialog(win):
    pw = _show(win, 0, 1)
    pw.timeline.open_find_replace()
    dlg = pw.timeline._find_dialog
    QApplication.processEvents()
    names = [_label(w) for w in _tab_walk(dlg.find_edit)]
    _assert_order(names, ["Testo da cercare", "Testo sostitutivo", "Maiuscole", "Parole",
                          "Regex", "Chiudi", "Sostituisci", "Sostituisci tutto",
                          "Trova successivo"])
    dlg.close()


# ── Anello di focus visibile su ogni fermata, nei due temi ───────────────────

@pytest.mark.parametrize("theme_name", ["dark", "light"])
@pytest.mark.parametrize("screen", ["editor", "risultato", "esportazione", "home", "dialog"])
def test_every_tab_stop_has_visible_focus_ring(win, app, theme_name, screen):
    from ui import theme
    theme.apply_theme(app, theme_name)
    try:
        if screen == "dialog":
            pw = _show(win, 0, 1)
            pw.timeline.open_find_replace()
            dlg = pw.timeline._find_dialog
            QApplication.processEvents()
            stops = _tab_walk(dlg.find_edit)
        else:
            project, tab = {"editor": (0, 1), "risultato": (0, 0), "esportazione": (0, 2),
                            "home": (1, None)}[screen]
            _show(win, project, tab)
            stops = _tab_walk(_first_tab(win))
        missing = [f"{type(w).__name__} {_label(w)!r}" for w in stops if not _has_focus_ring(w)]
        assert missing == [], f"senza anello di focus ({theme_name}): {missing}"
    finally:
        if screen == "dialog":
            win._projects[0].timeline._find_dialog.close()
        theme.apply_theme(app, "dark")


# ── Nomi accessibili su tutto l'albero della MainWindow ──────────────────────

def _is_qt_internal(w) -> bool:
    if w.objectName().startswith("qt_") or isinstance(w, QScrollBar):
        return True
    parent = w.parentWidget()
    # pulsante "cancella" dei QLineEdit, campo interno delle combo, viewport delle viste
    return isinstance(parent, (QLineEdit, QComboBox)) or (
        isinstance(parent, QAbstractScrollArea) and w is parent.viewport())


def test_every_focusable_control_has_accessible_name(win):
    from ui.find_replace_dialog import FindReplaceDialog
    pw = win._projects[0]
    dlg = FindReplaceDialog(pw.timeline.model)
    missing = []
    for root in (win, dlg):
        for w in root.findChildren(QWidget):
            if not (w.focusPolicy() & Qt.TabFocus) or _is_qt_internal(w):
                continue
            if w.window() is not root:       # popup interni (elenco delle combo)
                continue
            label = _label(w).replace("&", "")
            if not any(ch.isalpha() for ch in label):
                missing.append(f"{type(w).__name__}#{w.objectName()} in "
                               f"{type(w.parentWidget()).__name__}")
    dlg.deleteLater()
    assert not missing, "senza nome accessibile: " + ", ".join(missing)


def test_named_controls_in_header_waveform_transport_and_switches(win):
    pw = win._projects[0]
    preview = pw.workspace.preview
    assert preview.waveform.accessibleName() == "Forma d'onda"
    assert "rotella" in preview.waveform.accessibleDescription()
    assert preview.transport.seek_slider.accessibleName() == "Posizione di riproduzione"
    assert "±1" in preview.transport.seek_slider.accessibleDescription()
    assert preview.transport.volume_slider.accessibleName() == "Volume"
    assert win.theme_btn.accessibleName().startswith("Passa al tema")
    assert pw.home.vad_toggle.accessibleName().startswith("Filtro VAD")
    assert all(t.accessibleName().startswith("Progetto") for t in win.proj_tab_bar._tabs)


# ── Tooltip con la scorciatoia ───────────────────────────────────────────────

def test_tooltips_include_shortcut(win):
    pw = win._projects[0]
    tl = pw.timeline
    btn = {b.accessibleName(): b for b in tl._tb_buttons}
    tips = {
        "Dividi": (btn["Dividi"].toolTip(), _sl("Ctrl+K")),
        "Unisci": (btn["Unisci"].toolTip(), _sl("Ctrl+M")),
        "Elimina": (btn["Elimina"].toolTip(), _sl("Ctrl+Shift+K")),
        "Sostituisci": (btn["Trova e sostituisci"].toolTip(), _sl("Ctrl+Alt+F")),
        "Ispettore": (tl.act_toggle_insp.toolTip(), _sl("Ctrl+I")),
        "Cerca": (tl._search_box.toolTip(), _sl("Ctrl+F")),
        "Esporta": (tl._export_btn.toolTip(), _sl("Ctrl+S")),
        "Annulla": (tl.act_undo.toolTip(), _sl("Ctrl+Z")),
        "Ripeti": (tl.act_redo.toolTip(), _sl("Ctrl+Shift+Z")),
        "Play": (pw.workspace.preview.transport.btn_play.toolTip(), "Spazio"),
        "Posizione": (pw.workspace.preview.transport.seek_slider.toolTip(), "←/→"),
        "Forma d'onda": (pw.workspace.preview.waveform.toolTip(), _sl("Ctrl")),
        "Tema": (win.theme_btn.toolTip(), _sl("Ctrl+Shift+L")),
        "Nuovo progetto": (win.proj_tab_bar._btn_new.toolTip(), _sl("Ctrl+Shift+T")),
        "Esportazione": (pw.tab_bar._btn_export.toolTip(), _sl("Ctrl+E")),
    }
    missing = {k: tip for k, (tip, sc) in tips.items() if sc not in tip}
    assert missing == {}


# ── Slider di posizione: valore ↔ ms senza deriva ────────────────────────────

def test_seek_slider_value_roundtrip_has_no_drift(app):
    from ui.transport_bar import TransportBar
    bar = TransportBar()
    bar._on_duration_changed(7_777)
    for value in range(0, 1001, 7):
        ms = bar._value_to_ms(value)
        bar._on_position_changed(ms)
        assert bar.seek_slider.value() == value
    bar.deleteLater()
