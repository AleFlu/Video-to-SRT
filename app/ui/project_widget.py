"""
project_widget.py — ProjectWidget: contenitore isolato di un singolo progetto.

Racchiude TUTTA la logica che prima viveva in MainWindow per un progetto:
  - TabBar interna (Trascrizione | Editor)
  - TranscriptionTab (Home / Progress / Result)
  - EditorTab (Placeholder / Workspace)
  - Stato: _segments_raw, _source_path, project, worker inline
  - Autosave su file dedicato (<app_cache_dir>/autosave_<pid>_<n>.v2srt): il pid
    del processo nel nome evita che due istanze dell'app si sovrascrivano o si
    cancellino a vicenda i file; un QLockFile per processo dice se il proprietario
    è ancora vivo (vedi autosave_in_use).

API verso MainWindow:
  - title_changed(str)        → MainWindow aggiorna la tab del progetto
  - modified_changed(bool)    → MainWindow aggiorna il badge ● nella ProjectTabBar
  - status_text(str)          → MainWindow aggiorna la status bar

Il ProjectWidget NON conosce la ProjectTabBar né la MainWindow; comunica
solo tramite segnali.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from PySide6.QtCore import Qt, QLockFile, QSettings, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QStackedWidget, QMessageBox,
)

import platform_support
from core.subtitle_model import SubtitleProject
from core.v2srt_io import load_project, is_v2srt, save_project, EXTENSION as V2SRT_EXT
from ui.home_widget import HomeWidget
from ui.progress_widget import ProgressWidget
from ui.result_widget import ResultWidget
from ui.tab_bar import TabBar
from ui.editor_tab import EditorTab
from ui.export_panel import ExportPanel
from ui.export_tab import ExportTab
from ui.prefs import add_recent, write_config

logger = logging.getLogger(__name__)

# ── Autosave per processo ──────────────────────────────────────────────────────

_AUTOSAVE_RE = re.compile(r"^autosave_(?:(\d+)_)?(\d+)\.v2srt$")
_session_lock: QLockFile | None = None


def _lock_path(pid: int) -> Path:
    return platform_support.app_cache_dir() / f"session_{pid}.lock"


def _ensure_session_lock() -> None:
    """Crea (una volta) il lock di sessione di questo processo nella cartella cache."""
    global _session_lock
    path = _lock_path(os.getpid())
    if _session_lock is not None and Path(_session_lock.fileName()) == path:
        return
    lock = QLockFile(str(path))
    lock.setStaleLockTime(0)   # un processo vivo non diventa mai "stale" per età
    if lock.tryLock(0):
        _session_lock = lock
    else:
        logger.warning("Lock di sessione non acquisito: %s", path)


def autosave_name(project_number: int) -> str:
    return f"autosave_{os.getpid()}_{project_number}.v2srt"


def autosave_in_use(path: Path) -> bool:
    """
    True se l'autosave appartiene a un'altra istanza dell'app ancora in esecuzione
    (da non ripristinare né cancellare). I nomi storici senza pid sono liberi.
    """
    m = _AUTOSAVE_RE.match(Path(path).name)
    if not m or not m.group(1):
        return False
    pid = int(m.group(1))
    if pid == os.getpid():
        return True
    lock_file = path.parent / f"session_{pid}.lock"
    if not lock_file.exists():
        return False
    probe = QLockFile(str(lock_file))
    probe.setStaleLockTime(0)
    if probe.tryLock(0):
        # il proprietario non c'è più (QLockFile verifica il pid): lock orfano
        probe.unlock()
        return False
    return True

# Sotto-stati TranscriptionTab
_TRANS_DROP     = 0
_TRANS_PROGRESS = 1
_TRANS_RESULT   = 2

# Indici tab interna
_TAB_TRANSCRIPTION = 0
_TAB_EDITOR        = 1
_TAB_EXPORT        = 2


class ProjectWidget(QWidget):
    """
    Widget isolato per un singolo progetto.
    Contiene tutto lo stato e la logica che prima era in MainWindow.
    """

    # Segnali verso MainWindow / ProjectTabBar
    title_changed    = Signal(str)    # titolo suggerito per la tab
    modified_changed = Signal(bool)   # True = badge ● sulla tab progetto
    status_text      = Signal(str)    # messaggio per la status bar

    def __init__(self, project_number: int, ffmpeg_ok: bool, model_ok: bool,
                 parent=None):
        super().__init__(parent)

        self._project_number = project_number
        self._title = f"Progetto {project_number}"
        # Ultimo messaggio di stato emesso (la MainWindow lo ripristina al cambio tab)
        self.last_status: str = "Pronto"

        self._ffmpeg_ok = ffmpeg_ok
        self._model_ok  = model_ok

        # ── Stato condiviso ──────────────────────────────────────────────────
        self._segments_raw: list = []     # INV1: MAI modificati dall'editor
        self._source_path: str  = ""
        self.project = SubtitleProject()
        self._editor_loaded: bool = False

        # Export panel (finestra di dialogo figlia del progetto: chiusa con il progetto)
        self._export_panel = ExportPanel(get_project_callable=self._current_project,
                                         parent=self)
        self._export_panel.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
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
        self.home.open_requested.connect(self.open_path)

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
        self.workspace.import_requested.connect(self.open_path)

        self.workspace.subtitles_changed.connect(self._on_subtitles_changed)
        self.workspace.export_requested.connect(self.do_export)
        self.workspace.status_text.connect(self.status_text)

        # Le scorciatoie (Ctrl+E, Ctrl+S, Ctrl+Shift+S…) sono azioni di menu della
        # MainWindow che chiamano i metodi pubblici del progetto attivo: registrarle
        # anche qui (una copia per progetto) le renderebbe ambigue.

        # Formati alternativi dalla timeline
        tl = self.workspace.timeline
        tl.act_export_vtt.triggered.connect(self._on_tl_export_vtt)
        tl.act_export_txt.triggered.connect(self._on_tl_export_txt)
        tl.act_export_ass.triggered.connect(self._on_tl_export_ass)
        tl.act_export_v2srt.triggered.connect(self.save_v2srt)

        # ExportTab: bottoni esportazione — usa i sub dell'ExportTab (già pronti in refresh())
        self.export_tab.export_srt_requested.connect(self._on_tab_export_srt)
        self.export_tab.export_vtt_requested.connect(self._on_tab_export_vtt)
        self.export_tab.export_txt_requested.connect(self._on_tab_export_txt)
        self.export_tab.export_ass_requested.connect(self._on_tab_export_ass)
        self.export_tab.save_v2srt_requested.connect(self._export_tab_v2srt)

    # ── Tab switching ──────────────────────────────────────────────────────────

    def title(self) -> str:
        """Titolo corrente del progetto (quello mostrato nella tab)."""
        return self._title

    def pause_playback(self) -> None:
        """Mette in pausa la riproduzione dell'anteprima (senza mai riprenderla da sola)."""
        player = self.workspace.preview.player
        if player.is_playing():
            player.pause()

    def _on_tab_changed(self, index: int):
        if index != _TAB_EDITOR:
            self.pause_playback()
        self._main_stack.setCurrentIndex(index)
        if index == _TAB_EDITOR:
            if self.workspace.get_subtitles():
                # Sub già nell'editor
                self.editor_tab.show_workspace()
            elif self._segments_raw and not self._editor_loaded:
                # Trascrizione completata ma editor non ancora aperto:
                # caricali automaticamente quando l'utente clicca la tab
                if self._load_raw_into_editor():
                    self.editor_tab.show_workspace()
                else:
                    self.editor_tab.show_placeholder()
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

    def _confirm_model_download(self, model_size: str) -> bool:
        """True se il modello c'è già o se l'utente accetta di scaricarlo adesso."""
        from core.whisper_models import MODELS
        from engine import is_model_available
        if not model_size or is_model_available(model_size):
            return True
        gb = f"{MODELS[model_size]['download_gb']:.1f}".replace(".", ",")
        answer = QMessageBox.question(
            self, "Scaricare il modello?",
            f"Il modello {model_size} non è ancora su questo computer: va scaricato una "
            f"volta sola (circa {gb} GB, serve internet).\n\n"
            "Il download parte con la trascrizione e si vede l'avanzamento; se lo "
            "interrompi riprende da dove si era fermato.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        return answer == QMessageBox.Yes

    def _on_start_requested(self, source_path: str, settings: dict):
        if not self._confirm_model_download(settings.get("model_size", "")):
            return
        # Configurazione completa (parametri avanzati inclusi), ricordata come ultima usata
        config = self.home.current_config()
        write_config(QSettings("VideoSRT", "v2"), config, self.home.config_name())
        self._go_progress()
        self._set_title(Path(source_path).stem)
        self.status_text.emit("Trascrizione in corso…")
        self.progress.start(source_path, settings, config=config)

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

    def _on_transcription_failed(self, err: str):
        self.status_text.emit(f"Errore: {err}")

    # ── ResultWidget handlers ──────────────────────────────────────────────────

    def _load_raw_into_editor(self) -> bool:
        """
        Carica i segmenti dell'ultima trascrizione nell'editor, chiedendo conferma
        se l'editor contiene modifiche non salvate. False se l'utente annulla.
        """
        if not self.confirm_discard_changes():
            return False
        self.workspace.load_result(self._segments_raw, self._source_path)
        self._editor_loaded = True
        self._refresh_editor_badge()
        return True

    def _on_open_editor(self):
        if not self._editor_loaded and not self._load_raw_into_editor():
            return
        self.editor_tab.show_workspace()
        self.tab_bar.set_current(_TAB_EDITOR)
        self._main_stack.setCurrentIndex(_TAB_EDITOR)
        self._refresh_editor_badge()

    def _on_new_transcription_from_result(self):
        if not self.confirm_discard_changes():
            return
        self._reset_project()
        self._lock_tabs()
        self._go_drop()

    # ── Load v2srt / srt ──────────────────────────────────────────────────────

    def load_v2srt(self, path: str):
        """Carica un .v2srt direttamente nell'editor (chiede conferma se modificato)."""
        if not self.confirm_discard_changes():
            return
        try:
            project, _ = load_project(path)
        except Exception as e:
            logger.warning("Apertura progetto fallita: %s", path, exc_info=True)
            QMessageBox.critical(self, "Errore apertura",
                                 f"Impossibile aprire il progetto:\n{e}")
            return

        self._apply_loaded_project(project)

        if project.source_path and Path(project.source_path).exists():
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

    def _apply_loaded_project(self, project: SubtitleProject):
        """
        Installa un progetto caricato da file (.v2srt o autosave): stato, editor e
        preview risincronizzati. `_segments_raw` resta sempre una lista di dict.
        """
        self.project = project
        self._source_path = project.source_path
        self._segments_raw = [s.to_dict() for s in project.subtitles]
        self._editor_loaded = True
        self.workspace.load_content(project.subtitles, project.source_path)

    def _load_srt(self, path: str):
        if not self.confirm_discard_changes():
            return
        try:
            from core.srt_io import parse_srt
            subtitles = parse_srt(path)
        except Exception as e:
            logger.warning("Lettura SRT fallita: %s", path, exc_info=True)
            QMessageBox.critical(self, "Errore apertura SRT",
                                 f"Impossibile leggere il file SRT:\n{e}")
            return

        # Stesso percorso del caricamento .v2srt: stato, badge, export, autosave e
        # preview fanno riferimento all'SRT importato
        self._apply_loaded_project(SubtitleProject(source_path=str(path), subtitles=subtitles))
        self.editor_tab.show_workspace()

        n = len(subtitles)
        self._set_title(Path(path).stem)
        self.status_text.emit(f"{n} sottotitoli · SRT importato: {Path(path).name}")
        self._add_to_recent(path)

        self._unlock_tabs()
        self.tab_bar.set_current(_TAB_EDITOR)
        self._main_stack.setCurrentIndex(_TAB_EDITOR)
        self._refresh_editor_badge()

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
        self._export_panel.setWindowTitle("Esporta sottotitoli")
        self._export_panel.adjustSize()
        self._export_panel.resize(max(520, self._export_panel.width()),
                                  self._export_panel.sizeHint().height())
        self._export_panel.show()
        self._export_panel.raise_()
        self._export_panel.activateWindow()

    # Slot senza lambda (una lambda che cattura self crea cicli non raccoglibili)
    def _on_tl_export_vtt(self, *_a) -> None:
        self._do_export_format(".vtt")

    def _on_tl_export_txt(self, *_a) -> None:
        self._do_export_format(".txt")

    def _on_tl_export_ass(self, *_a) -> None:
        self._do_export_format(".ass")

    def _on_tab_export_srt(self, *_a) -> None:
        self._export_tab_format(".srt")

    def _on_tab_export_vtt(self, *_a) -> None:
        self._export_tab_format(".vtt")

    def _on_tab_export_txt(self, *_a) -> None:
        self._export_tab_format(".txt")

    def _on_tab_export_ass(self, *_a) -> None:
        self._export_tab_format(".ass")

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
        self.status_text.emit(f"{n} sottotitoli{'  ·  Modificato' if mod else ''}")
        self.modified_changed.emit(mod)
        self._refresh_editor_badge()
        self._refresh_modified_badge()
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

    def confirm_discard_changes(self) -> bool:
        """
        Punto UNICO di conferma prima di sostituire/scartare il contenuto dell'editor.

        Se l'editor non ha modifiche non salvate ritorna True senza chiedere.
        Altrimenti chiede Salva / Non salvare / Annulla:
          - Salva       → salva il progetto .v2srt; True solo se il salvataggio riesce
          - Non salvare → True (le modifiche verranno scartate dal chiamante)
          - Annulla     → False (il chiamante non deve toccare l'editor)
        """
        if not self.workspace.is_modified():
            return True
        n = len(self.workspace.get_subtitles())
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Modifiche non salvate")
        box.setText("L'editor contiene modifiche non salvate.")
        box.setInformativeText(
            f"{n} sottotitoli. Vuoi salvare il progetto prima di continuare?"
        )
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Save)
        box.setEscapeButton(QMessageBox.Cancel)
        for btn, label in ((QMessageBox.Save, "Salva…"),
                           (QMessageBox.Discard, "Non salvare"),
                           (QMessageBox.Cancel, "Annulla")):
            b = box.button(btn)
            if b is not None:
                b.setText(label)
        ans = box.exec()
        if ans == QMessageBox.Save:
            self.save_v2srt()
            return not self.workspace.is_modified()
        return ans == QMessageBox.Discard

    def can_close(self) -> bool:
        """
        Verifica se il progetto può essere chiuso (chiede conferma all'utente).
        Non ferma nulla: il worker viene annullato solo in teardown(), dopo che
        TUTTE le conferme sono state date.
        """
        if self.progress.is_running():
            ans = QMessageBox.question(
                self, "Trascrizione in corso",
                "La trascrizione è in corso. Chiudere comunque?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return False

        return self.confirm_discard_changes()

    def teardown(self):
        """
        Chiamato da MainWindow prima di rimuovere il widget: ferma timer, annulla
        il worker di trascrizione (sganciandolo: il chiamante attende i thread
        sganciati con wait_detached_threads) e chiude il pannello export flottante.
        """
        self._autosave_timer.stop()
        # Sgancia il QThread dal widget: distruggerlo mentre gira = crash Qt
        self.progress.detach_and_stop()
        self._export_panel.close()
        self._delete_autosave()

    # ── File recenti ──────────────────────────────────────────────────────────

    @staticmethod
    def _add_to_recent(path: str):
        add_recent(QSettings("VideoSRT", "v2"), path)

    # ── Autosave ──────────────────────────────────────────────────────────────

    def _current_project(self) -> SubtitleProject:
        return self.project

    def autosave_path(self) -> Path:
        return platform_support.app_cache_dir() / autosave_name(self._project_number)

    def _autosave(self):
        """Salva una copia di sicurezza solo se ci sono modifiche non salvate."""
        subs = self.workspace.get_subtitles()
        if not subs or not self.workspace.is_modified():
            return
        try:
            _ensure_session_lock()
            self.project.subtitles = list(subs)
            save_project(self.project, str(self.autosave_path()))
        except Exception:
            logger.warning("Scrittura autosave fallita: %s", self.autosave_path(),
                           exc_info=True)

    def _delete_autosave(self):
        try:
            self.autosave_path().unlink(missing_ok=True)
        except Exception:
            logger.warning("Eliminazione autosave fallita: %s", self.autosave_path(),
                           exc_info=True)

    def restore_from_autosave(self, path: str) -> bool:
        """
        Carica un file autosave senza chiedere conferma.
        Ritorna True solo se il ripristino è riuscito: il chiamante elimina il
        file di autosave SOLO in quel caso. Il progetto ripristinato è marcato
        modificato (non è mai stato salvato dall'utente).
        """
        try:
            project, _ = load_project(path)
        except Exception:
            logger.warning("Ripristino autosave fallito: %s", path, exc_info=True)
            return False

        self._apply_loaded_project(project)
        self.workspace.timeline.mark_modified()
        if project.source_path and Path(project.source_path).exists():
            self._set_title(Path(project.source_path).stem)
        else:
            self._set_title(f"Progetto {self._project_number} (ripristinato)")
        self.editor_tab.show_workspace()
        self._unlock_tabs()
        self.tab_bar.set_current(_TAB_EDITOR)
        self._main_stack.setCurrentIndex(_TAB_EDITOR)
        self._refresh_editor_badge()
        self.modified_changed.emit(True)
        return True

    # ── Accesso undo/redo/find (per menu MainWindow) ──────────────────────────

    @property
    def timeline(self):
        return self.workspace.timeline

    def is_editor_current(self) -> bool:
        """True se l'utente sta guardando l'editor con dei sottotitoli caricati."""
        return (self.tab_bar.current() == _TAB_EDITOR
                and bool(self.workspace.get_subtitles()))

    def _show_editor_if_content(self) -> bool:
        if not self.workspace.get_subtitles():
            return False
        self.tab_bar.set_current(_TAB_EDITOR)
        return True

    def find_inline(self):
        """Ctrl+F: porta il focus sulla ricerca inline della timeline."""
        if self._show_editor_if_content():
            self.timeline.focus_search()

    def find_replace(self):
        """Apre il dialog Trova e sostituisci sull'editor."""
        if self._show_editor_if_content():
            self.timeline.open_find_replace()

    def show_export_tab(self):
        """Ctrl+E: apre la tab Esportazione (se sbloccata)."""
        if self.tab_bar.is_unlocked():
            self.tab_bar.set_current(_TAB_EXPORT)
