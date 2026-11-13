"""
project_widget.py — ProjectWidget: contenitore isolato di un singolo progetto.

Racchiude TUTTA la logica che prima viveva in MainWindow per un progetto:
  - TabBar interna (Trascrizione | Editor)
  - TranscriptionTab (Home / Progress / Result)
  - EditorTab (Placeholder / Workspace)
  - Stato: _segments_raw, _source_path, project, worker inline
  - Autosave su file dedicato (~/.cache/VideoSRT/autosave_<uid>.v2srt)

API verso MainWindow:
  - title_changed(str)        → MainWindow aggiorna la tab del progetto
  - modified_changed(bool)    → MainWindow aggiorna il badge ● nella ProjectTabBar
  - status_text(str)          → MainWindow aggiorna la status bar
  - request_close()           → l'utente vuole chiudere questo progetto

Il ProjectWidget NON conosce la ProjectTabBar né la MainWindow; comunica
solo tramite segnali.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QStackedWidget, QMessageBox,
)

from core.subtitle_model import SubtitleProject
from core.v2srt_io import load_project, is_v2srt, save_project, EXTENSION as V2SRT_EXT
from ui.home_widget import HomeWidget
from ui.progress_widget import ProgressWidget
from ui.result_widget import ResultWidget
from ui.tab_bar import TabBar
from ui.editor_tab import EditorTab
from ui.export_panel import ExportPanel
from ui.export_tab import ExportTab

# Sotto-stati TranscriptionTab
_TRANS_DROP     = 0
_TRANS_PROGRESS = 1
_TRANS_RESULT   = 2

# Indici tab interna
_TAB_TRANSCRIPTION = 0
_TAB_EDITOR        = 1
_TAB_EXPORT        = 2

# Limite autosave
_AUTOSAVE_DIR_ENV = "HOME"


class ProjectWidget(QWidget):
    """
    Widget isolato per un singolo progetto.
    Contiene tutto lo stato e la logica che prima era in MainWindow.
    """

    # Segnali verso MainWindow / ProjectTabBar
    title_changed    = Signal(str)    # titolo suggerito per la tab
    modified_changed = Signal(bool)   # True = badge ● sulla tab progetto
    status_text      = Signal(str)    # messaggio per la status bar
    request_close    = Signal()       # utente vuole chiudere la tab

    def __init__(self, project_number: int, ffmpeg_ok: bool, model_ok: bool,
                 parent=None):
        super().__init__(parent)

        # Slot numerico per autosave (stabile per tutta la vita del widget)
        self._uid = str(project_number)
        self._project_number = project_number
        self._title = f"Progetto {project_number}"

        self._ffmpeg_ok = ffmpeg_ok
        self._model_ok  = model_ok

        # ── Stato condiviso ──────────────────────────────────────────────────
        self._segments_raw: list = []     # INV1: MAI modificati dall'editor
        self._source_path: str  = ""
        self.project = SubtitleProject()
        self._editor_loaded: bool = False

        # Export panel (floating, uno per progetto)
        self._export_panel = ExportPanel(get_project_callable=lambda: self.project)
        self._export_panel.exported.connect(self._on_exported)

        # ── UI ───────────────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Tab bar interna (Trascrizione | Editor)
        self.tab_bar = TabBar()
        root.addWidget(self.tab_bar)

        # Stack principale: TranscriptionTab | EditorTab
        self._main_stack = QStackedWidget()
        root.addWidget(self._main_stack, 1)

        # TranscriptionTab
        self._trans_stack = QStackedWidget()
        self.home     = HomeWidget()
        self.progress = ProgressWidget()
        self.result   = ResultWidget()
        self._trans_stack.addWidget(self.home)      # 0 Drop
        self._trans_stack.addWidget(self.progress)  # 1 Progress
        self._trans_stack.addWidget(self.result)    # 2 Result
        self._main_stack.addWidget(self._trans_stack)  # tab 0

        # EditorTab
        self.editor_tab = EditorTab()
        self._main_stack.addWidget(self.editor_tab)    # tab 1

        self.workspace = self.editor_tab.workspace
        self.inspector = self.workspace.inspector

        # ExportTab
        self.export_tab = ExportTab()
        self._main_stack.addWidget(self.export_tab)    # tab 2

        # ── Stato iniziale ───────────────────────────────────────────────────
        self.home.set_deps_status(ffmpeg_ok, model_ok)
        self._go_drop()
        self.tab_bar.set_current(_TAB_TRANSCRIPTION)
        self._main_stack.setCurrentIndex(_TAB_TRANSCRIPTION)

        self._wire()

        # ── Autosave ─────────────────────────────────────────────────────────
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(120_000)   # 2 minuti
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()

    # ── Wiring ────────────────────────────────────────────────────────────────

    def _wire(self):
        self.tab_bar.tab_changed.connect(self._on_tab_changed)

        self.home.start_requested.connect(self._on_start_requested)

        self.progress.transcription_done.connect(self._on_transcription_done)
        self.progress.transcription_cancelled.connect(self._go_drop)
        self.progress.transcription_failed.connect(self._on_transcription_failed)

        self.result.export_requested.connect(self.do_export)
        self.result.open_editor_requested.connect(self._on_open_editor)
        self.result.new_requested.connect(self._on_new_transcription_from_result)

        self.editor_tab.go_transcription_requested.connect(
            lambda: self.tab_bar.set_current(_TAB_TRANSCRIPTION)
        )
        self.editor_tab.import_requested.connect(self.open_path)

        self.workspace.subtitles_changed.connect(self._on_subtitles_changed)
        self.workspace.export_requested.connect(self.do_export)
        self.workspace.status_text.connect(self.status_text)

        # ── Shortcut esportazione (ApplicationShortcut: funzionano da qualsiasi tab) ──
        # ⌘E → apri tab Esportazione
        sc_exp = QShortcut(QKeySequence("Ctrl+E"), self)
        sc_exp.setContext(Qt.ApplicationShortcut)
        sc_exp.activated.connect(lambda: self.tab_bar.set_current(_TAB_EXPORT))

        # ⌘S → esporta SRT (già funziona dal menu, ma anche qui per coerenza)
        sc_srt = QShortcut(QKeySequence("Ctrl+S"), self)
        sc_srt.setContext(Qt.ApplicationShortcut)
        sc_srt.activated.connect(self.do_export)

        # ⌘⇧S → salva progetto .v2srt
        sc_v2srt = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        sc_v2srt.setContext(Qt.ApplicationShortcut)
        sc_v2srt.activated.connect(self.save_v2srt)

        # Formati alternativi dalla timeline
        tl = self.workspace.timeline
        tl.act_export_vtt.triggered.connect(lambda: self._do_export_format(".vtt"))
        tl.act_export_txt.triggered.connect(lambda: self._do_export_format(".txt"))
        tl.act_export_ass.triggered.connect(lambda: self._do_export_format(".ass"))
        tl.act_export_v2srt.triggered.connect(self.save_v2srt)

        # ExportTab: bottoni esportazione — usa i sub dell'ExportTab (già pronti in refresh())
        self.export_tab.export_srt_requested.connect(lambda: self._export_tab_format(".srt"))
        self.export_tab.export_vtt_requested.connect(lambda: self._export_tab_format(".vtt"))
        self.export_tab.export_txt_requested.connect(lambda: self._export_tab_format(".txt"))
        self.export_tab.export_ass_requested.connect(lambda: self._export_tab_format(".ass"))
        self.export_tab.save_v2srt_requested.connect(self._export_tab_v2srt)

    # ── Tab switching ──────────────────────────────────────────────────────────

    def _on_tab_changed(self, index: int):
        self._main_stack.setCurrentIndex(index)
        if index == _TAB_EDITOR:
            if self.workspace.get_subtitles():
                # Sub già nell'editor
                self.editor_tab.show_workspace()
            elif self._segments_raw and not self._editor_loaded:
                # Trascrizione completata ma editor non ancora aperto:
                # caricali automaticamente quando l'utente clicca la tab
                self.workspace.load_result(self._segments_raw, self._source_path)
                self._editor_loaded = True
                self.editor_tab.show_workspace()
                self._refresh_editor_badge()
            else:
                # Nessun sub da nessuna parte → placeholder
                self.editor_tab.show_placeholder()
        elif index == _TAB_TRANSCRIPTION:
            self._refresh_modified_badge()
        elif index == _TAB_EXPORT:
            self._refresh_export_tab()

    # ── Sotto-stati TranscriptionTab ───────────────────────────────────────────

    def _go_drop(self):
        self.home.reset()
        self._trans_stack.setCurrentIndex(_TRANS_DROP)
        self.status_text.emit("Pronto")
        self._set_title(self._title)   # title invariato

    def _go_progress(self):
        self._trans_stack.setCurrentIndex(_TRANS_PROGRESS)

    def _go_result(self):
        self._trans_stack.setCurrentIndex(_TRANS_RESULT)

    # ── Flusso trascrizione ────────────────────────────────────────────────────

    def _on_start_requested(self, source_path: str, settings: dict):
        self._go_progress()
        self._set_title(Path(source_path).stem)
        self.status_text.emit("Trascrizione in corso…")
        self.progress.start(source_path, settings)

    def _on_transcription_done(self, segments: list, source_path: str):
        self._segments_raw = segments
        self._source_path  = source_path
        self._editor_loaded = False

        self.project.load_from_segments(segments, source_path)

        n = len(segments)
        self.status_text.emit(f"{n} sottotitoli · Trascrizione completata")
        self._set_title(Path(source_path).stem)

        self._add_to_recent(source_path)
        self.result.show_result(segments, source_path)
        self.result.set_modified_badge(False)
        self._go_result()
        self._unlock_tabs()
        self._refresh_editor_badge()
        self._refresh_export_badge()

    def _on_transcription_failed(self, err: str):
        self.status_text.emit(f"Errore: {err}")

    # ── ResultWidget handlers ──────────────────────────────────────────────────

    def _on_open_editor(self):
        if not self._editor_loaded:
            self.workspace.load_result(self._segments_raw, self._source_path)
            self._editor_loaded = True
        self.editor_tab.show_workspace()
        self.tab_bar.set_current(_TAB_EDITOR)
        self._main_stack.setCurrentIndex(_TAB_EDITOR)
        self._refresh_editor_badge()

    def _on_new_transcription_from_result(self):
        if not self._confirm_discard_editor():
            return
        self._reset_project()
        self._lock_tabs()
        self._go_drop()

    # ── Load v2srt / srt ──────────────────────────────────────────────────────

    def load_v2srt(self, path: str):
        """Carica un .v2srt direttamente nell'editor."""
        try:
            project, _ = load_project(path)
        except Exception as e:
            QMessageBox.critical(self, "Errore apertura",
                                 f"Impossibile aprire il progetto:\n{e}")
            return

        self.project = project
        self._segments_raw = list(project.subtitles)
        self._editor_loaded = True

        self.workspace.timeline.load_subtitles(project.subtitles)
        self.workspace.inspector.bind_model(self.workspace.timeline.model)

        if project.source_path and Path(project.source_path).exists():
            self.workspace.preview.load_media(project.source_path)
            media_name = Path(project.source_path).stem
        else:
            media_name = Path(path).stem

        n = len(project.subtitles)
        self.status_text.emit(f"{n} sottotitoli · Progetto aperto: {Path(path).name}")
        self._set_title(media_name)
        self._add_to_recent(path)

        self.editor_tab.show_workspace()
        self._unlock_tabs()
        self.tab_bar.set_current(_TAB_EDITOR)
        self._main_stack.setCurrentIndex(_TAB_EDITOR)
        self._refresh_editor_badge()
        self._refresh_export_badge()

    def _load_srt(self, path: str):
        try:
            from core.srt_io import parse_srt
            subtitles = parse_srt(path)
        except Exception as e:
            QMessageBox.critical(self, "Errore apertura SRT",
                                 f"Impossibile leggere il file SRT:\n{e}")
            return

        self.workspace.timeline.load_subtitles(subtitles)
        self._editor_loaded = True
        self.editor_tab.show_workspace()

        n = len(subtitles)
        self._set_title(Path(path).stem)
        self.status_text.emit(f"{n} sottotitoli · SRT importato: {Path(path).name}")
        self._add_to_recent(path)

        self._unlock_tabs()
        self.tab_bar.set_current(_TAB_EDITOR)
        self._main_stack.setCurrentIndex(_TAB_EDITOR)
        self._refresh_editor_badge()
        self._refresh_export_badge()

    # ── Apertura file generica ─────────────────────────────────────────────────

    def open_path(self, path: str):
        """Dispatch: .v2srt → editor, .srt → editor, video/audio → Drop pre-caricato."""
        # INV5: non sovrascrivere lo stato mentre un worker è attivo
        if self.progress.is_running():
            QMessageBox.warning(
                self, "Trascrizione in corso",
                "C'è una trascrizione in corso. Attendi il completamento "
                "o annullala prima di aprire un altro file.",
            )
            return
        ext = Path(path).suffix.lower()
        if ext == ".v2srt" or is_v2srt(path):
            self.load_v2srt(path)
        elif ext == ".srt":
            self._load_srt(path)
        else:
            self.tab_bar.set_current(_TAB_TRANSCRIPTION)
            self._main_stack.setCurrentIndex(_TAB_TRANSCRIPTION)
            self._go_drop()
            self.home.preload_file(path)

    # ── Export ────────────────────────────────────────────────────────────────

    def do_export(self):
        subs = self.workspace.get_subtitles()
        if not subs:
            if self._segments_raw:
                self.project.load_from_segments(self._segments_raw, self._source_path)
            else:
                QMessageBox.warning(self, "Nessun sottotitolo",
                                    "Non ci sono sottotitoli da esportare.")
                return
        else:
            self.project.subtitles = subs

        self._export_panel.refresh_from_project()
        self._export_panel.setWindowTitle("Esporta SRT")
        self._export_panel.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self._export_panel.resize(500, 280)
        self._export_panel.show()
        self._export_panel.raise_()
        self._export_panel.activateWindow()

    def _do_export_format(self, ext: str):
        from PySide6.QtWidgets import QFileDialog
        from core.srt_io import write_vtt, write_txt, write_ass

        subs = self.workspace.get_subtitles()
        if not subs:
            if self._segments_raw:
                self.project.load_from_segments(self._segments_raw, self._source_path)
                subs = self.project.subtitles
            else:
                QMessageBox.warning(self, "Nessun sottotitolo",
                                    "Non ci sono sottotitoli da esportare.")
                return
        else:
            self.project.subtitles = subs

        _filters = {
            ".vtt": "WebVTT (*.vtt)",
            ".txt": "Testo semplice (*.txt)",
            ".ass": "Advanced SubStation Alpha (*.ass)",
        }
        initial = ""
        if self.project.source_path:
            initial = str(Path(self.project.source_path).with_suffix(ext))

        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta…", initial, _filters.get(ext, f"*{ext}")
        )
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext

        try:
            if ext == ".vtt":
                write_vtt(subs, path)
            elif ext == ".txt":
                write_txt(subs, path)
            elif ext == ".ass":
                write_ass(subs, path)
            self._mark_exported(path)
        except Exception as e:
            QMessageBox.critical(self, "Errore esportazione", str(e))

    def _export_tab_format(self, ext: str):
        """
        Esporta direttamente il formato richiesto usando i sub già pronti in ExportTab.
        Chiamato dai bottoni della tab Esportazione — nessun pannello floating.
        """
        from PySide6.QtWidgets import QFileDialog
        from core.srt_io import write_srt, write_vtt, write_txt, write_ass

        subs = self.export_tab.current_subtitles()
        if not subs:
            QMessageBox.warning(self, "Nessun sottotitolo",
                                "Non ci sono sottotitoli da esportare.")
            return

        _filters = {
            ".srt":  "SubRip Subtitle (*.srt)",
            ".vtt":  "WebVTT (*.vtt)",
            ".txt":  "Testo semplice (*.txt)",
            ".ass":  "Advanced SubStation Alpha (*.ass)",
        }
        initial = ""
        if self._source_path:
            initial = str(Path(self._source_path).with_suffix(ext))

        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta…", initial, _filters.get(ext, f"*{ext}")
        )
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext

        try:
            if ext == ".srt":
                write_srt(subs, path)
            elif ext == ".vtt":
                write_vtt(subs, path)
            elif ext == ".txt":
                write_txt(subs, path)
            elif ext == ".ass":
                write_ass(subs, path)
            self._mark_exported(path)
        except Exception as e:
            QMessageBox.critical(self, "Errore esportazione", str(e))

    def _export_tab_v2srt(self):
        """Salva progetto .v2srt usando i sub dell'ExportTab."""
        from PySide6.QtWidgets import QFileDialog

        subs = self.export_tab.current_subtitles()
        if not subs:
            QMessageBox.warning(self, "Nessun sottotitolo",
                                "Non ci sono sottotitoli da salvare.")
            return

        self.project.subtitles = subs
        initial = ""
        if self._source_path:
            initial = str(Path(self._source_path).with_suffix(V2SRT_EXT))

        path, _ = QFileDialog.getSaveFileName(
            self, "Salva progetto", initial, "Progetto V2SRT (*.v2srt)"
        )
        if not path:
            return
        if not path.lower().endswith(V2SRT_EXT):
            path += V2SRT_EXT

        try:
            save_project(self.project, path)
            self._mark_exported(path, "Progetto salvato")
        except Exception as e:
            QMessageBox.critical(self, "Errore salvataggio", str(e))

    def _on_exported(self, path: str):
        self._mark_exported(path, "Salvato")

    def _mark_exported(self, path: str, label: str = "Esportato"):
        """Allinea lo stato dopo un salvataggio riuscito (INV2: badge ↔ modifiche)."""
        self.workspace.mark_saved()
        self.project.modified = False
        self.status_text.emit(f"{label}: {Path(path).name}")
        self.modified_changed.emit(False)
        self.result.set_modified_badge(False)
        self._delete_autosave()

    def save_v2srt(self):
        from PySide6.QtWidgets import QFileDialog
        subs = self.workspace.get_subtitles()
        if not subs:
            QMessageBox.warning(self, "Nessun sottotitolo",
                                "Non ci sono sottotitoli da salvare.")
            return
        self.project.subtitles = subs
        initial = ""
        if self.project.source_path:
            initial = str(Path(self.project.source_path).with_suffix(V2SRT_EXT))
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva progetto", initial, "Progetto V2SRT (*.v2srt)"
        )
        if not path:
            return
        if not path.lower().endswith(V2SRT_EXT):
            path += V2SRT_EXT
        try:
            save_project(self.project, path)
            self._mark_exported(path, "Progetto salvato")
        except Exception as e:
            QMessageBox.critical(self, "Errore salvataggio", str(e))

    # ── Status / badge ────────────────────────────────────────────────────────

    def _on_subtitles_changed(self):
        subs = self.workspace.get_subtitles()
        self.project.subtitles = subs
        self.project.modified  = self.workspace.is_modified()
        n = len(subs)
        mod = self.workspace.is_modified()
        self.status_text.emit(f"{n} sottotitoli{'  ●  Modificato' if mod else ''}")
        self.modified_changed.emit(mod)
        self._refresh_editor_badge()
        self._refresh_modified_badge()
        self._refresh_export_badge()
        # Aggiorna export tab in tempo reale se già visibile
        if self.tab_bar.current() == _TAB_EXPORT:
            self._refresh_export_tab()

    def _refresh_export_tab(self):
        """Aggiorna ExportTab con lo stato corrente del progetto."""
        editor_subs = self.workspace.get_subtitles()
        self.export_tab.refresh(
            segments_raw=self._segments_raw,
            editor_subs=editor_subs,
            source_path=self._source_path,
            is_modified=self.workspace.is_modified(),
        )

    def _refresh_editor_badge(self):
        has_subs = bool(self.workspace.get_subtitles())
        self.tab_bar.set_editor_badge(has_subs)

    def _refresh_export_badge(self):
        """Aggiorna il badge numerico sulla tab Esportazione."""
        editor_subs = self.workspace.get_subtitles()
        if editor_subs:
            count = len(editor_subs)
        elif self._segments_raw:
            count = len(self._segments_raw)
        else:
            count = 0
        self.tab_bar.set_export_badge(count)

    def _refresh_modified_badge(self):
        if not self._editor_loaded:
            self.result.set_modified_badge(False)
            return
        editor_subs = self.workspace.get_subtitles()
        if not editor_subs or not self._segments_raw:
            self.result.set_modified_badge(False)
            return
        diverged = (len(editor_subs) != len(self._segments_raw)) or self.workspace.is_modified()
        self.result.set_modified_badge(diverged)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _unlock_tabs(self):
        """Sblocca Editor e Esportazione — chiamato quando arrivano i primi sub."""
        self.tab_bar.set_unlocked(True)

    def _lock_tabs(self):
        """Blocca Editor e Esportazione, torna a Trascrizione — chiamato al reset."""
        self.tab_bar.set_unlocked(False)

    def _set_title(self, title: str):
        self._title = title
        self.title_changed.emit(title)

    def _reset_project(self):
        """Resetta lo stato del progetto a vuoto."""
        self._segments_raw = []
        self._source_path  = ""
        self.project = SubtitleProject()
        self._editor_loaded = False
        # Svuota anche la timeline e azzera lo stato modificato: l'utente ha già
        # confermato lo scarto — senza questo can_close() richiederebbe una
        # seconda conferma per modifiche ormai scartate
        self.workspace.timeline.load_subtitles([])
        self.workspace.mark_saved()

    def _confirm_discard_editor(self) -> bool:
        subs = self.workspace.get_subtitles()
        if subs and self.workspace.is_modified():
            ans = QMessageBox.question(
                self, "Modifiche non esportate",
                f"Hai {len(subs)} sottotitoli con modifiche non esportate. Continuare?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return ans == QMessageBox.Yes
        return True

    def can_close(self) -> bool:
        """
        Verifica se il progetto può essere chiuso.
        Se ci sono modifiche, chiede conferma all'utente.
        """
        # Trascrizione nella tab Progress?
        if self._trans_stack.currentIndex() == _TRANS_PROGRESS and self.progress.is_running():
            ans = QMessageBox.question(
                self, "Trascrizione in corso",
                "La trascrizione è in corso. Chiudere comunque?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return False
            self.progress.request_stop()

        # Modifiche non salvate?
        if self.workspace.is_modified():
            ans = QMessageBox.question(
                self, "Modifiche non salvate",
                "Ci sono modifiche non esportate. Chiudere comunque?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return False

        return True

    def teardown(self):
        """Chiamato da MainWindow prima di rimuovere il widget. Ferma timer e thread."""
        self._autosave_timer.stop()
        # Sgancia il QThread dal widget: distruggerlo mentre gira = crash Qt
        self.progress.detach_and_stop()
        self._delete_autosave()

    # ── File recenti ──────────────────────────────────────────────────────────

    @staticmethod
    def _add_to_recent(path: str):
        _MAX_RECENT = 10
        _KEY = "recent_files"
        s = QSettings("VideoSRT", "v2")
        recent: list[str] = list(s.value(_KEY) or [])
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        recent = recent[:_MAX_RECENT]
        s.setValue(_KEY, recent)

    # ── Autosave ──────────────────────────────────────────────────────────────

    def autosave_path(self) -> Path:
        import os
        cache = Path(os.environ.get("HOME", "/tmp")) / ".cache" / "VideoSRT"
        cache.mkdir(parents=True, exist_ok=True)
        return cache / f"autosave_{self._uid}.v2srt"

    def _autosave(self):
        subs = self.workspace.get_subtitles()
        if not subs:
            return
        try:
            self.project.subtitles = subs
            save_project(self.project, str(self.autosave_path()))
        except Exception:
            pass

    def _delete_autosave(self):
        try:
            self.autosave_path().unlink(missing_ok=True)
        except Exception:
            pass

    def restore_from_autosave(self, path: str):
        """Carica da un file autosave senza chiedere conferma."""
        try:
            project, _ = load_project(path)
            self.project = project
            self._segments_raw = list(project.subtitles)
            self._editor_loaded = True
            self.workspace.timeline.load_subtitles(project.subtitles)
            self.workspace.inspector.bind_model(self.workspace.timeline.model)
            if project.source_path and Path(project.source_path).exists():
                self.workspace.preview.load_media(project.source_path)
                self._set_title(Path(project.source_path).stem)
            else:
                self._set_title(f"Progetto {self._project_number} (ripristinato)")
            self.editor_tab.show_workspace()
            self._unlock_tabs()
            self.tab_bar.set_current(_TAB_EDITOR)
            self._main_stack.setCurrentIndex(_TAB_EDITOR)
            self._refresh_editor_badge()
        except Exception:
            pass   # autosave corrotto → ignora silenziosamente

    # ── Accesso undo/redo/find (per menu MainWindow) ──────────────────────────

    @property
    def timeline(self):
        return self.workspace.timeline
