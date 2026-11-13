"""
main_window.py — MainWindow: orchestratore multi-progetto.

Struttura:
  ┌──────────────────────────────────────────────────────────────┐
  │  QMenuBar                                                    │
  ├──────────────────────────────────────────────────────────────┤
  │  ProjectTabBar  [Progetto 1 ×] [video.mp4 ● ×] [+]  spazio │
  ├──────────────────────────────────────────────────────────────┤
  │  QStackedWidget  (un ProjectWidget per tab)                  │
  │    [0] ProjectWidget                                         │
  │    [1] ProjectWidget                                         │
  │    ...                                                       │
  ├──────────────────────────────────────────────────────────────┤
  │  QStatusBar                                                  │
  └──────────────────────────────────────────────────────────────┘

MainWindow non contiene stato di progetto: è tutto in ProjectWidget.
Agisce come proxy per menu e status bar verso il progetto attivo.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence, QUndoGroup
from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget, QStatusBar, QLabel, QMessageBox, QWidget, QVBoxLayout,
    QApplication,
)

import platform_support

from core.constants import SUPPORTED_ALL_EXTS, FILE_FILTER_OPEN_ANY
from ui.project_widget import ProjectWidget, autosave_in_use
from ui.project_tab_bar import ProjectTabBar
from ui import theme
from ui.prefs import read_list, RECENT_KEY

_SETTINGS_RECENT = RECENT_KEY
_SETTINGS_GEOM   = "mainwindow/geometry"

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Orchestratore multi-progetto: gestisce ProjectTabBar + QStackedWidget."""

    def __init__(self, ffmpeg_ok: bool, model_ok: bool):
        super().__init__()
        self.setWindowTitle("Video → SRT")
        self.setMinimumSize(900, 600)
        self._fit_to_screen(1440, 900)

        self._ffmpeg_ok = ffmpeg_ok
        self._model_ok  = model_ok

        self._project_counter = 0   # incrementato ad ogni nuovo progetto

        # Lista ProjectWidget (parallelo a ProjectTabBar)
        self._projects: list[ProjectWidget] = []

        # Undo/redo globali: il gruppo segue lo stack del progetto attivo
        self._undo_group = QUndoGroup(self)

        # ── UI ───────────────────────────────────────────────────────────────
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

        # ── Wiring ProjectTabBar ──────────────────────────────────────────────
        self.proj_tab_bar.tab_selected.connect(self._on_tab_selected)
        self.proj_tab_bar.tab_close_requested.connect(self._on_tab_close_requested)
        self.proj_tab_bar.new_tab_requested.connect(self._new_project)

        # ── Primo progetto ────────────────────────────────────────────────────
        self._new_project()   # crea Progetto 1

        # ── Geometria ─────────────────────────────────────────────────────────
        self._restore_geometry()

        # Il ripristino autosave è invocato da main.py dopo la chiusura dello splash.

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

        # Connetti segnali del progetto
        idx = len(self._projects)
        self._projects.append(pw)
        self._stack.addWidget(pw)
        self._undo_group.addStack(pw.timeline.undo_stack)

        pw.title_changed.connect(lambda t, i=idx: self._on_project_title_changed(t, i))
        pw.modified_changed.connect(lambda m, i=idx: self._on_project_modified_changed(m, i))
        pw.status_text.connect(self._on_project_status)

        # Aggiunge tab e seleziona
        self.proj_tab_bar.add_tab(f"Progetto {n}")
        # add_tab già chiama select_tab che emette tab_selected → _on_tab_selected
        # ma i segnali del progetto non sono ancora connessi al momento giusto,
        # quindi aggiorniamo manualmente il menu
        self._refresh_menu_for_active()

    def _on_tab_selected(self, index: int):
        """Mostra il ProjectWidget corrispondente."""
        if 0 <= index < len(self._projects):
            self._stack.setCurrentWidget(self._projects[index])
            self._refresh_menu_for_active()
            # Aggiorna status bar con info del progetto selezionato
            self._on_project_status("")

    def _on_tab_close_requested(self, index: int):
        """
        Chiusura tab richiesta dall'utente (click ×).
        Se è l'ultima tab: svuota il progetto invece di chiuderlo.
        """
        if index < 0 or index >= len(self._projects):
            return

        pw = self._projects[index]

        # Ultima tab → svuota invece di chiudere
        if len(self._projects) == 1:
            if not pw.can_close():
                return
            pw.teardown()
            self._undo_group.removeStack(pw.timeline.undo_stack)
            # Rimuovi e ricrea un progetto vuoto fresco
            self._stack.removeWidget(pw)
            self._projects.clear()
            pw.deleteLater()
            self.proj_tab_bar.remove_tab(0)
            self._new_project()
            return

        # Tab non ultima → verifica e rimuovi
        if not pw.can_close():
            return

        pw.teardown()
        self._undo_group.removeStack(pw.timeline.undo_stack)
        self._stack.removeWidget(pw)
        self._projects.pop(index)
        pw.deleteLater()
        self.proj_tab_bar.remove_tab(index)

        # Riconnetti gli indici dei progetti rimasti
        self._rewire_project_indices()
        self._refresh_menu_for_active()

    def _rewire_project_indices(self):
        """
        I segnali title_changed/modified_changed usano l'indice catturato
        alla creazione. Dopo una rimozione gli indici cambiano → ricolleghiamo.
        Il modo più semplice è disconnettere e riconnettere tutto.
        Usiamo un attributo _signal_connections per tracciare le connessioni.
        """
        # Disconnetti tutte le connessioni precedenti (le ricolleghiamo dopo)
        for pw in self._projects:
            try:
                pw.title_changed.disconnect()
                pw.modified_changed.disconnect()
                pw.status_text.disconnect()
            except RuntimeError:
                pass

        # Riconnetti con indice corretto
        for i, pw in enumerate(self._projects):
            pw.title_changed.connect(lambda t, idx=i: self._on_project_title_changed(t, idx))
            pw.modified_changed.connect(lambda m, idx=i: self._on_project_modified_changed(m, idx))
            pw.status_text.connect(self._on_project_status)

    # ── Slot dai ProjectWidget ─────────────────────────────────────────────────

    def _on_project_title_changed(self, title: str, index: int):
        self.proj_tab_bar.set_tab_title(index, title)
        # Aggiorna titolo finestra se è il progetto attivo
        if index == self.proj_tab_bar.current_index():
            self.setWindowTitle(f"{title} — Video → SRT")

    def _on_project_modified_changed(self, modified: bool, index: int):
        self.proj_tab_bar.set_tab_modified(index, modified)

    def _on_project_status(self, text: str):
        """
        Aggiorna status bar.
        Tutti i ProjectWidget sono connessi a questo slot; filtra per sender().
        """
        sender = self.sender()
        active = self._active()
        if sender is active or sender is None:
            self.status_main.setText(text if text else "Pronto")

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _add_action(self, menu, text: str, slot, shortcuts=None) -> QAction:
        """
        Crea un'azione della finestra. Ogni scorciatoia dell'app è registrata UNA
        sola volta, qui: le azioni inoltrano al progetto attivo.
        """
        act = QAction(text, self)
        if shortcuts is not None:
            if isinstance(shortcuts, (list, tuple)):
                act.setShortcuts([QKeySequence(k) for k in shortcuts])
            else:
                act.setShortcuts(QKeySequence.keyBindings(shortcuts)
                                 if isinstance(shortcuts, QKeySequence.StandardKey)
                                 else [QKeySequence(shortcuts)])
        act.triggered.connect(slot)
        if menu is not None:
            menu.addAction(act)
        return act

    def _on_active(self, fn, editor_only: bool = False):
        """Ritorna uno slot che applica `fn(progetto_attivo)` (se esiste)."""
        def _slot(*_):
            pw = self._active()
            if pw is None:
                return
            if editor_only and not pw.is_editor_current():
                return
            fn(pw)
        return _slot

    def _build_menu(self):
        bar = self.menuBar()

        # ── File ──────────────────────────────────────────────────────────────
        m_file = bar.addMenu("&File")

        self._add_action(m_file, "Apri file…", self._open_any, QKeySequence.Open)
        self._add_action(m_file, "Apri progetto .v2srt…", self._open_v2srt_dialog)

        self._menu_recent = m_file.addMenu("Apri recenti")
        self._menu_recent.aboutToShow.connect(self._populate_recent_menu)

        m_file.addSeparator()

        self._add_action(m_file, "Nuovo progetto", self._new_project, "Ctrl+Shift+T")
        self._add_action(m_file, "Nuova trascrizione", self._new_transcription_active, "Ctrl+N")

        m_file.addSeparator()

        self._add_action(m_file, "Salva progetto .v2srt…",
                         self._on_active(lambda pw: pw.save_v2srt()), "Ctrl+Shift+S")
        self._add_action(m_file, "Esporta sottotitoli…",
                         self._on_active(lambda pw: pw.do_export()), QKeySequence.Save)
        self._add_action(m_file, "Vai a Esportazione",
                         self._on_active(lambda pw: pw.show_export_tab()), "Ctrl+E")

        m_file.addSeparator()

        self._add_action(m_file, "Esci", self.close, QKeySequence.Quit)

        # ── Modifica (inoltra al progetto attivo) ─────────────────────────────
        self._menu_edit = bar.addMenu("&Modifica")
        self.act_undo = self._undo_group.createUndoAction(self, "Annulla")
        self.act_undo.setShortcuts(QKeySequence.keyBindings(QKeySequence.Undo))
        self.act_redo = self._undo_group.createRedoAction(self, "Ripeti")
        self.act_redo.setShortcuts(QKeySequence.keyBindings(QKeySequence.Redo))
        self._menu_edit.addAction(self.act_undo)
        self._menu_edit.addAction(self.act_redo)
        self._menu_edit.addSeparator()
        self.act_split = self._add_action(
            self._menu_edit, "Dividi al cursore",
            self._on_active(lambda pw: pw.timeline.act_split.trigger(), editor_only=True),
            "Ctrl+K")
        self.act_merge = self._add_action(
            self._menu_edit, "Unisci al successivo",
            self._on_active(lambda pw: pw.timeline.act_merge.trigger(), editor_only=True),
            "Ctrl+M")
        self.act_delete = self._add_action(
            self._menu_edit, "Elimina selezionati",
            self._on_active(lambda pw: pw.timeline.act_delete.trigger(), editor_only=True),
            "Ctrl+Shift+K")
        self._menu_edit.addSeparator()
        self.act_find = self._add_action(
            self._menu_edit, "Trova…",
            self._on_active(lambda pw: pw.find_inline()), QKeySequence.Find)
        # Su macOS Cmd+H è "Nascondi applicazione": lì si usa solo Ctrl+Alt+F (⌘⌥F)
        replace_keys = ["Ctrl+Alt+F"] if platform_support.IS_MAC else ["Ctrl+Alt+F", "Ctrl+H"]
        self.act_find_replace = self._add_action(
            self._menu_edit, "Trova e sostituisci…",
            self._on_active(lambda pw: pw.find_replace()), replace_keys)

        # ── Vista ──────────────────────────────────────────────────────────────
        m_view = bar.addMenu("&Vista")
        self._act_fullscreen = QAction("Schermo intero", self)
        self._act_fullscreen.setShortcut(platform_support.fullscreen_shortcut())
        self._act_fullscreen.setCheckable(True)
        self._act_fullscreen.triggered.connect(
            lambda checked: self.showFullScreen() if checked else self.showNormal()
        )
        m_view.addAction(self._act_fullscreen)

        m_view.addSeparator()
        self._act_theme = QAction("Tema chiaro", self)
        self._act_theme.setShortcut("Ctrl+Shift+L")
        self._act_theme.triggered.connect(self._toggle_theme)
        m_view.addAction(self._act_theme)

        self.act_toggle_insp = self._add_action(
            None, "Mostra/nascondi Ispettore",
            self._on_active(lambda pw: pw.timeline.act_toggle_insp.trigger(),
                            editor_only=True),
            "Ctrl+I")
        m_view.insertAction(self._act_theme, self.act_toggle_insp)
        m_view.insertSeparator(self._act_theme)

        self._menu_view = m_view

        # ── Aiuto ──────────────────────────────────────────────────────────────
        m_help = bar.addMenu("&Aiuto")
        act_about = QAction("Informazioni…", self)
        act_about.triggered.connect(self._show_about)
        m_help.addAction(act_about)

        self._refresh_theme_ui()
        # Tiene il menu in sync anche quando il tema cambia dal toggle nella TabBar
        theme.MANAGER.theme_changed.connect(self._refresh_theme_ui)

    # ── Tema chiaro/scuro ───────────────────────────────────────────────────────
    # Il toggle visibile vive nella TabBar di ogni ProjectWidget (la menu bar
    # macOS è nativa e non mostra corner widget). La voce menu Vista resta come
    # scorciatoia (Ctrl+Shift+L) e applica lo stesso cambio.

    def _toggle_theme(self):
        theme.toggle_theme(QApplication.instance())

    def _refresh_theme_ui(self):
        """Aggiorna l'etichetta della voce di menu in base al tema corrente."""
        is_dark = theme.get_theme() == "dark"
        # la voce di menu propone l'AZIONE (passa all'altro tema)
        self._act_theme.setText("Tema chiaro" if is_dark else "Tema scuro")

    def _refresh_menu_for_active(self):
        """I menu sono statici: basta puntare il gruppo undo allo stack del progetto attivo."""
        active = self._active()
        self._undo_group.setActiveStack(active.timeline.undo_stack if active else None)

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
        """Apre un file nel progetto attivo (o in uno nuovo se il progetto attivo è occupato)."""
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

    # ── Nuova trascrizione nel progetto attivo ─────────────────────────────────

    def _new_transcription_active(self):
        active = self._active()
        if active:
            active._on_new_transcription_from_result()

    # ── File recenti ───────────────────────────────────────────────────────────

    def _populate_recent_menu(self):
        self._menu_recent.clear()
        s = QSettings("VideoSRT", "v2")
        recent: list[str] = [str(p) for p in read_list(s, _SETTINGS_RECENT)]
        # Esclude i file nel frattempo cancellati o spostati
        existing = [p for p in recent if Path(p).exists()]
        if existing != recent:
            s.setValue(_SETTINGS_RECENT, existing)
        recent = existing
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
    def _autosave_dirs() -> list:
        """Cartella di cache corrente più le vecchie cartelle (legacy) con autosave."""
        return [platform_support.app_cache_dir()] + platform_support.legacy_cache_dirs()

    def _check_autosave_restore(self):
        """
        All'avvio, cerca file autosave_*.v2srt nella dir cache.
        Per ognuno chiede se ripristinarlo (uno alla volta).
        """
        # Gli autosave di un'altra istanza ancora aperta non si toccano
        autosaves = sorted(
            f for d in self._autosave_dirs() for f in d.glob("autosave_*.v2srt")
            if not autosave_in_use(f)
        )
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
                except Exception:
                    pass
            return

        # Ripristina: il primo progetto è già creato (_new_project nel __init__).
        # Il file di autosave si elimina SOLO dopo un ripristino riuscito.
        failed = []
        first = True
        for apath in autosaves:
            if not first:
                if not self.proj_tab_bar.can_add():
                    break   # i file non ripristinati restano per il prossimo avvio
                self._new_project()
            first = False
            active = self._active()
            if active is None or not active.restore_from_autosave(str(apath)):
                failed.append(apath)
                continue
            try:
                apath.unlink()
            except OSError:
                logger.warning("Impossibile eliminare l'autosave %s", apath, exc_info=True)

        if failed:
            QMessageBox.warning(
                self, "Ripristino non riuscito",
                "Alcune sessioni non sono state ripristinate e restano salvate in:\n"
                + "\n".join(str(p) for p in failed),
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _show_about(self):
        QMessageBox.information(
            self, "Video → SRT",
            "Video → SRT v2\n\n"
            "Trascrizione automatica in locale con faster-whisper "
            "(modelli Whisper selezionabili nella Home).\n"
            "Editor multi-progetto: annulla/ripeti, trova e sostituisci, "
            "diagnostica CPS e sovrapposizioni.\n"
            "Esporta in SRT, VTT, TXT, ASS e progetto .v2srt.",
        )

    def _fit_to_screen(self, width: int, height: int):
        """Dimensione iniziale limitata all'area disponibile dello schermo."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            width = min(width, int(avail.width() * 0.95))
            height = min(height, int(avail.height() * 0.92))
            self.setMinimumSize(min(900, width), min(600, height))
        self.resize(width, height)

    def _restore_geometry(self):
        geom = QSettings("VideoSRT", "v2").value(_SETTINGS_GEOM)
        if geom:
            self.restoreGeometry(geom)

    # ── Drag & drop globale ────────────────────────────────────────────────────

    def dragEnterEvent(self, e):
        """Accetta drag se almeno un file ha estensione supportata."""
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
        """
        Apre i file droppati nel progetto attivo.
        Se vengono droppati più file, il primo va nel progetto attivo;
        ogni file successivo apre un nuovo progetto (se il limite non è raggiunto).
        """
        paths = [
            u.toLocalFile()
            for u in e.mimeData().urls()
            if Path(u.toLocalFile()).suffix.lower() in SUPPORTED_ALL_EXTS
        ]
        if not paths:
            e.ignore()
            return

        e.acceptProposedAction()

        skipped = []
        for i, path in enumerate(paths):
            if i == 0:
                self._open_path(path)
            elif self.proj_tab_bar.can_add():
                self._new_project()
                self._open_path(path)
            else:
                # Limite progetti raggiunto: non sovrascrivere il progetto attivo
                skipped.append(Path(path).name)
        if skipped:
            QMessageBox.warning(
                self, "Limite progetti raggiunto",
                "File non aperti (chiudi un progetto e riprova):\n" + "\n".join(skipped),
            )

    # ── Close event ────────────────────────────────────────────────────────────

    def closeEvent(self, e):
        QSettings("VideoSRT", "v2").setValue(_SETTINGS_GEOM, self.saveGeometry())

        # Verifica tutti i progetti: se uno non può chiudersi, annulla quit
        for i, pw in enumerate(list(self._projects)):
            if not pw.can_close():
                e.ignore()
                return

        # Tutti ok: teardown di tutti i progetti (annulla i worker attivi)
        for pw in self._projects:
            pw.teardown()

        # Attende (max 3s) i thread di trascrizione sganciati: distruggere
        # l'app con un QThread ancora attivo causa un fatal Qt all'uscita
        from ui.progress_widget import wait_detached_threads
        wait_detached_threads(3000)

        super().closeEvent(e)
