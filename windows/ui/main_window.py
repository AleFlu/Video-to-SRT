"""
main_window.py — MainWindow: orchestratore multi-progetto.

Struttura:
  ┌──────────────────────────────────────────────────────────────┐
  │  QMenuBar                                                    │
  ├──────────────────────────────────────────────────────────────┤
  │  ProjectTabBar  [Progetto 1 ×] [video.mp4 ● ×] [+]  spazio │
  ├──────────────────────────────────────────────────────────────┤
  │  QStackedWidget  (un ProjectWidget per tab)                  │
  ├──────────────────────────────────────────────────────────────┤
  │  QStatusBar                                                  │
  └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget, QStatusBar, QLabel, QMessageBox, QWidget, QVBoxLayout,
)

import platform

from core.constants import SUPPORTED_ALL_EXTS, FILE_FILTER_OPEN_ANY
from ui.project_widget import ProjectWidget, _app_cache_dir
from ui.project_tab_bar import ProjectTabBar

logger = logging.getLogger(__name__)

_MAX_RECENT      = 10
_SETTINGS_RECENT = "recent_files"
_SETTINGS_GEOM   = "mainwindow/geometry"


class MainWindow(QMainWindow):
    """Orchestratore multi-progetto: gestisce ProjectTabBar + QStackedWidget."""

    def __init__(self, ffmpeg_ok: bool, model_ok: bool):
        super().__init__()
        self.setWindowTitle("Video → SRT")
        self.resize(1440, 900)
        self.setMinimumSize(900, 600)

        self._ffmpeg_ok = ffmpeg_ok
        self._model_ok  = model_ok
        self._project_counter = 0
        self._projects: list[ProjectWidget] = []

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.proj_tab_bar = ProjectTabBar()
        root_layout.addWidget(self.proj_tab_bar)

        self._stack = QStackedWidget()
        root_layout.addWidget(self._stack, 1)

        self.setCentralWidget(root)
        self.setAcceptDrops(True)

        self._build_menu()
        self._build_status_bar()

        self.proj_tab_bar.tab_selected.connect(self._on_tab_selected)
        self.proj_tab_bar.tab_close_requested.connect(self._on_tab_close_requested)
        self.proj_tab_bar.new_tab_requested.connect(self._new_project)

        self._new_project()
        self._restore_geometry()
        self._check_autosave_restore()

    # ── Progetto attivo ────────────────────────────────────────────────────────

    def _active(self) -> ProjectWidget | None:
        idx = self.proj_tab_bar.current_index()
        if 0 <= idx < len(self._projects):
            return self._projects[idx]
        return None

    # ── Gestione progetti ──────────────────────────────────────────────────────

    def _new_project(self):
        if not self.proj_tab_bar.can_add():
            QMessageBox.information(
                self, "Limite raggiunto",
                f"Puoi aprire al massimo {ProjectTabBar._MAX_PROJECTS} progetti simultaneamente.",
            )
            return

        self._project_counter += 1
        n = self._project_counter
        pw = ProjectWidget(n, self._ffmpeg_ok, self._model_ok, parent=self)

        idx = len(self._projects)
        self._projects.append(pw)
        self._stack.addWidget(pw)

        pw.title_changed.connect(lambda t, i=idx: self._on_project_title_changed(t, i))
        pw.modified_changed.connect(lambda m, i=idx: self._on_project_modified_changed(m, i))
        pw.status_text.connect(self._on_project_status)

        self.proj_tab_bar.add_tab(f"Progetto {n}")
        self._refresh_menu_for_active()

    def _on_tab_selected(self, index: int):
        if 0 <= index < len(self._projects):
            self._stack.setCurrentWidget(self._projects[index])
            self._refresh_menu_for_active()
            self._on_project_status("")

    def _on_tab_close_requested(self, index: int):
        if index < 0 or index >= len(self._projects):
            return

        pw = self._projects[index]

        if len(self._projects) == 1:
            if not pw.can_close():
                return
            pw.teardown()
            self._stack.removeWidget(pw)
            self._projects.clear()
            pw.deleteLater()
            self.proj_tab_bar.remove_tab(0)
            self._new_project()
            return

        if not pw.can_close():
            return

        pw.teardown()
        self._stack.removeWidget(pw)
        self._projects.pop(index)
        pw.deleteLater()
        self.proj_tab_bar.remove_tab(index)

        self._rewire_project_indices()
        self._refresh_menu_for_active()

    def _rewire_project_indices(self):
        for pw in self._projects:
            try:
                pw.title_changed.disconnect()
                pw.modified_changed.disconnect()
                pw.status_text.disconnect()
            except RuntimeError:
                pass

        for i, pw in enumerate(self._projects):
            pw.title_changed.connect(lambda t, idx=i: self._on_project_title_changed(t, idx))
            pw.modified_changed.connect(lambda m, idx=i: self._on_project_modified_changed(m, idx))
            pw.status_text.connect(self._on_project_status)

    # ── Slot dai ProjectWidget ─────────────────────────────────────────────────

    def _on_project_title_changed(self, title: str, index: int):
        self.proj_tab_bar.set_tab_title(index, title)
        if index == self.proj_tab_bar.current_index():
            self.setWindowTitle(f"{title} — Video → SRT")

    def _on_project_modified_changed(self, modified: bool, index: int):
        self.proj_tab_bar.set_tab_modified(index, modified)

    def _on_project_status(self, text: str):
        sender = self.sender()
        active = self._active()
        if sender is active or sender is None:
            self.status_main.setText(text if text else "Pronto")

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        bar = self.menuBar()

        m_file = bar.addMenu("&File")

        act_open = QAction("Apri file…", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self._open_any)
        m_file.addAction(act_open)

        act_open_proj = QAction("Apri progetto .v2srt…", self)
        act_open_proj.triggered.connect(self._open_v2srt_dialog)
        m_file.addAction(act_open_proj)

        self._menu_recent = m_file.addMenu("Apri recenti")
        self._menu_recent.aboutToShow.connect(self._populate_recent_menu)

        m_file.addSeparator()

        act_new_proj = QAction("Nuovo progetto", self)
        act_new_proj.setShortcut("Ctrl+Shift+T")
        act_new_proj.triggered.connect(self._new_project)
        m_file.addAction(act_new_proj)

        act_new_trans = QAction("Nuova trascrizione", self)
        act_new_trans.setShortcut("Ctrl+N")
        act_new_trans.triggered.connect(self._new_transcription_active)
        m_file.addAction(act_new_trans)

        m_file.addSeparator()

        act_save_proj = QAction("Salva progetto .v2srt…", self)
        act_save_proj.setShortcut("Ctrl+Shift+S")
        act_save_proj.triggered.connect(lambda: self._active() and self._active().save_v2srt())
        m_file.addAction(act_save_proj)

        act_export = QAction("Esporta sottotitoli…", self)
        act_export.setShortcut(QKeySequence.Save)
        act_export.triggered.connect(lambda: self._active() and self._active().do_export())
        m_file.addAction(act_export)

        m_file.addSeparator()

        act_quit = QAction("Esci", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        self._menu_edit = bar.addMenu("&Modifica")

        m_view = bar.addMenu("&Vista")
        self._act_fullscreen = QAction("Schermo intero", self)
        # Shortcut cross-platform: F11 su Windows/Linux, Meta+Ctrl+F su macOS
        if platform.system() == "Darwin":
            self._act_fullscreen.setShortcut("Meta+Ctrl+F")
        else:
            self._act_fullscreen.setShortcut("F11")
        self._act_fullscreen.setCheckable(True)
        self._act_fullscreen.triggered.connect(
            lambda checked: self.showFullScreen() if checked else self.showNormal()
        )
        m_view.addAction(self._act_fullscreen)
        self._menu_view = m_view

        m_help = bar.addMenu("&Aiuto")
        act_about = QAction("Informazioni…", self)
        act_about.triggered.connect(self._show_about)
        m_help.addAction(act_about)

    def _refresh_menu_for_active(self):
        for act in self._menu_edit.actions():
            self._menu_edit.removeAction(act)

        active = self._active()
        if active is None:
            return

        tl = active.timeline
        self._menu_edit.addAction(tl.act_undo)
        self._menu_edit.addAction(tl.act_redo)
        self._menu_edit.addSeparator()
        self._menu_edit.addAction(tl.act_split)
        self._menu_edit.addAction(tl.act_merge)
        self._menu_edit.addAction(tl.act_delete)
        self._menu_edit.addSeparator()
        self._menu_edit.addAction(tl.act_find)

        for act in self._menu_view.actions():
            self._menu_view.removeAction(act)

        self._menu_view.addAction(self._act_fullscreen)
        self._menu_view.addSeparator()
        self._menu_view.addAction(tl.act_toggle_insp)

    # ── Status bar ─────────────────────────────────────────────────────────────

    def _build_status_bar(self):
        sb = QStatusBar()
        self.status_main = QLabel("Pronto")
        sb.addWidget(self.status_main)
        sb.addPermanentWidget(QLabel("  "))
        self.status_proj = QLabel("")
        sb.addPermanentWidget(self.status_proj)
        self.setStatusBar(sb)

    # ── Apertura file ──────────────────────────────────────────────────────────

    def _open_any(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Apri file…", "", FILE_FILTER_OPEN_ANY
        )
        if path:
            self._open_path(path)

    def _open_path(self, path: str):
        active = self._active()
        if active is None:
            self._new_project()
            active = self._active()
        if active:
            active.open_path(path)

    def _open_v2srt_dialog(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Apri progetto…", "", "Progetto V2SRT (*.v2srt);;Tutti i file (*.*)"
        )
        if path:
            self._open_path(path)

    def _new_transcription_active(self):
        active = self._active()
        if active:
            active._on_new_transcription_from_result()

    # ── File recenti ───────────────────────────────────────────────────────────

    def _populate_recent_menu(self):
        self._menu_recent.clear()
        s = QSettings("VideoSRT", "v2")
        recent: list[str] = list(s.value(_SETTINGS_RECENT) or [])
        if not recent:
            act = QAction("(nessun file recente)", self)
            act.setEnabled(False)
            self._menu_recent.addAction(act)
            return
        for path in recent:
            p = Path(path)
            act = QAction(f"{p.name}  —  {str(p.parent)}", self)
            act.setData(path)
            act.triggered.connect(lambda checked=False, p=path: self._open_path(p))
            self._menu_recent.addAction(act)
        self._menu_recent.addSeparator()
        clear_act = QAction("Cancella recenti", self)
        clear_act.triggered.connect(self._clear_recent)
        self._menu_recent.addAction(clear_act)

    def _clear_recent(self):
        QSettings("VideoSRT", "v2").remove(_SETTINGS_RECENT)

    # ── Autosave multi-progetto ────────────────────────────────────────────────

    @staticmethod
    def _autosave_dir() -> Path:
        """
        Cartella autosave cross-platform.
        Usa _app_cache_dir() — non usa più os.environ.get("HOME", "/tmp").
        """
        cache = _app_cache_dir()
        return cache

    def _check_autosave_restore(self):
        try:
            autosave_dir = self._autosave_dir()
            autosaves = sorted(autosave_dir.glob("autosave_*.v2srt"))
        except Exception as exc:
            logger.warning("[MainWindow._check_autosave_restore] errore scansione: %s", exc)
            return

        if not autosaves:
            return

        count = len(autosaves)
        noun = "sessione" if count == 1 else f"{count} sessioni"
        ans = QMessageBox.question(
            self, "Ripristina sessione precedente",
            f"È stata trovata {noun} salvata automaticamente.\n"
            "Vuoi ripristinare la/le sessioni precedenti?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if ans != QMessageBox.Yes:
            for f in autosaves:
                try:
                    f.unlink()
                except Exception as exc:
                    logger.debug("[MainWindow._check_autosave_restore] unlink: %s", exc)
            return

        first = True
        for apath in autosaves:
            if first:
                active = self._active()
                if active:
                    active.restore_from_autosave(str(apath))
                first = False
            else:
                if self.proj_tab_bar.can_add():
                    self._new_project()
                    active = self._active()
                    if active:
                        active.restore_from_autosave(str(apath))
            try:
                apath.unlink()
            except Exception as exc:
                logger.debug("[MainWindow._check_autosave_restore] unlink autosave: %s", exc)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _show_about(self):
        QMessageBox.information(
            self, "Video → SRT",
            "Video → SRT v2\n\n"
            "Trascrizione automatica italiana con faster-whisper + large-v3.\n"
            "Editor professionale multi-progetto: undo/redo, find & replace, diagnostica CPS/overlap.\n"
            "Esporta in SRT, VTT, TXT, ASS, V2SRT.",
        )

    def _restore_geometry(self):
        geom = QSettings("VideoSRT", "v2").value(_SETTINGS_GEOM)
        if geom:
            self.restoreGeometry(geom)

    # ── Drag & drop globale ────────────────────────────────────────────────────

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls()]
            if any(Path(p).suffix.lower() in SUPPORTED_ALL_EXTS for p in paths):
                e.acceptProposedAction()
                return
        e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [
            u.toLocalFile()
            for u in e.mimeData().urls()
            if Path(u.toLocalFile()).suffix.lower() in SUPPORTED_ALL_EXTS
        ]
        if not paths:
            e.ignore()
            return

        e.acceptProposedAction()

        for i, path in enumerate(paths):
            if i == 0:
                self._open_path(path)
            else:
                if self.proj_tab_bar.can_add():
                    self._new_project()
                self._open_path(path)

    # ── Close event ────────────────────────────────────────────────────────────

    def closeEvent(self, e):
        QSettings("VideoSRT", "v2").setValue(_SETTINGS_GEOM, self.saveGeometry())

        for pw in list(self._projects):
            if not pw.can_close():
                e.ignore()
                return

        for pw in self._projects:
            pw.teardown()

        super().closeEvent(e)
