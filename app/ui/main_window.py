"""
main_window.py — MainWindow: orchestratore multi-progetto.

Struttura:
  ┌──────────────────────────────────────────────────────────────┐
  │  QMenuBar                                                    │
  ├──────────────────────────────────────────────────────────────┤
  │  Intestazione 40 px: ProjectTabBar | sezioni del progetto    │
  │  attivo (Trascrizione/Editor/Esportazione) | tema            │
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

import html
import logging
import os
import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDir, QSettings, QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QUndoGroup
from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget, QStatusBar, QLabel, QMessageBox, QWidget, QVBoxLayout,
    QApplication, QHBoxLayout, QPushButton, QSizePolicy,
)

import platform_support

from core.constants import SUPPORTED_ALL_EXTS, FILE_FILTER_OPEN_ANY
from core.transcription_config import (
    EXTENSION as CONFIG_EXT, FILE_FILTER as CONFIG_FILE_FILTER, TranscriptionConfig,
    load_config, save_config, set_active_readability,
)
from ui.project_widget import ProjectWidget, autosave_in_use
from ui.project_tab_bar import ProjectTabBar
from ui import icons, theme
from ui.prefs import CONFIG_DIR_KEY, read_config, read_list, write_config, RECENT_KEY
from ui.widgets import protect_extension_buttons

_SETTINGS_RECENT = RECENT_KEY
_SETTINGS_GEOM   = "mainwindow/geometry"

logger = logging.getLogger(__name__)



class _StatusLabel(QLabel):
    """
    Etichetta della status bar: `text()` resta il testo semplice (chi legge lo stato non
    cambia), ma il disegno colora i conteggi di errori e avvisi (token `err` / `warn`).
    """

    _COUNT_RE = re.compile(r"^\s*(\d+)\s+(error|avvis)", re.IGNORECASE)

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.RichText)
        self._plain = ""
        self.setText(text)
        theme.MANAGER.theme_changed.connect(self._render)

    def text(self) -> str:  # noqa: A003 (override Qt)
        return self._plain

    def setText(self, text: str) -> None:  # noqa: N802 (override Qt)
        self._plain = text or ""
        self._render()

    def _render(self, _name: str = "") -> None:
        parts = []
        for seg in self._plain.split("·"):
            m = self._COUNT_RE.match(seg)
            token = None
            if m and int(m.group(1)) > 0:
                token = "err" if m.group(2).lower().startswith("error") else "warn"
            esc = html.escape(seg.strip()).replace(" ", "&nbsp;")
            parts.append(f'<span style="color:{theme.c(token)};">{esc}</span>' if token else esc)
        QLabel.setText(self, "&nbsp;&nbsp;·&nbsp;&nbsp;".join(parts))


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

        # Intestazione unica da 40 px: tab progetti | sezioni del progetto attivo | tema
        self.proj_tab_bar = ProjectTabBar()
        self._nav_stack = QStackedWidget()   # una TabBar (sezioni) per progetto
        self._nav_stack.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._nav_stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
        self.theme_btn = self._build_theme_button()
        root_layout.addWidget(self._build_header())

        self._stack = QStackedWidget()
        root_layout.addWidget(self._stack, 1)

        self.setCentralWidget(root)
        self.setAcceptDrops(True)

        self._build_menu()
        self._build_status_bar()
        self._refresh_theme_btn()
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

        # ── Wiring ProjectTabBar ──────────────────────────────────────────────
        self.proj_tab_bar.tab_selected.connect(self._on_tab_selected)
        self.proj_tab_bar.tab_close_requested.connect(self._on_tab_close_requested)
        self.proj_tab_bar.new_tab_requested.connect(self._new_project)

        # ── Primo progetto ────────────────────────────────────────────────────
        self._new_project()   # crea Progetto 1 (con l'ultima configurazione usata)
        self._fit_min_height()
        # Limiti di leggibilità dell'editor: quelli della configurazione appena applicata
        if self._projects:
            set_active_readability(self._projects[0].home.current_config().readability)

        # ── Geometria ─────────────────────────────────────────────────────────
        self._restore_geometry()

        # Il ripristino autosave è invocato da main.py dopo la chiusura dello splash.

    # ── Intestazione ───────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        """Riga unica: tab progetti (sinistra), sezioni (centro), tema (destra)."""
        header = QWidget()
        header.setObjectName("mainHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header.setFixedHeight(self.proj_tab_bar.height() or 40)
        self._header = header
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(0)
        row.addWidget(self.proj_tab_bar, 1)
        row.addWidget(self._nav_stack, 0)
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.addStretch(1)
        right.addWidget(self.theme_btn, 0, Qt.AlignVCenter)
        row.addLayout(right, 1)
        self._apply_header_palette()
        return header

    def _apply_header_palette(self):
        c = theme.c
        self._header.setStyleSheet(
            f"QWidget#mainHeader {{ background-color: {c('panel')};"
            f" border-bottom: 1px solid {c('line')}; }}"
        )

    def _build_theme_button(self) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("themeToggle")
        btn.setFixedHeight(28)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._toggle_theme)
        return btn

    def _refresh_theme_btn(self):
        c = theme.c
        is_dark = theme.get_theme() == "dark"
        btn = self.theme_btn
        btn.setText("Scuro" if is_dark else "Chiaro")
        btn.setIcon(icons.icon("moon" if is_dark else "sun", "dim"))
        btn.setIconSize(QSize(16, 16))
        tip = "Passa al tema chiaro" if is_dark else "Passa al tema scuro"
        btn.setToolTip(f"{tip}  {platform_support.shortcut_label('Ctrl+Shift+L')}")
        btn.setAccessibleName(tip)
        btn.setStyleSheet(
            "QPushButton {"
            f"  background: transparent; color: {c('dim')};"
            "  border: 1px solid transparent; border-radius: 4px;"
            "  font-size: 13px; padding: 0 9px; min-height: 26px;"
            "}"
            f"QPushButton:hover {{ color: {c('text')}; background: {c('raise')}; }}"
            + theme.focus_rule("QPushButton", 4)
        )

    def _apply_status_style(self):
        """Barra di stato: 26 px, `panel`, linea di 1 px sopra, mono 11 px in `dim`."""
        c = theme.c
        self._status_bar.setStyleSheet(
            f"QStatusBar {{ background: {c('panel')}; border-top: 1px solid {c('line')}; }}"
            f"QStatusBar QLabel {{ background: transparent; color: {c('dim')};"
            f" font-family: {theme.FONT_MONO}; font-size: 11px; }}"
        )

    def _on_theme_changed(self, _name: str = ""):
        self._apply_status_style()
        self._apply_header_palette()
        self._refresh_theme_btn()

    def _attach_project_nav(self, pw: ProjectWidget):
        """Sposta nell'intestazione la TabBar (sezioni) del progetto: resta sua, con tutti i segnali."""
        self._nav_stack.addWidget(pw.tab_bar)

    def _detach_project_nav(self, pw: ProjectWidget):
        self._nav_stack.removeWidget(pw.tab_bar)
        pw.tab_bar.deleteLater()

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
        pw.home.min_height_changed.connect(self._fit_min_height)

        # Connetti segnali del progetto
        self._projects.append(pw)
        self._stack.addWidget(pw)
        self._attach_project_nav(pw)
        self._undo_group.addStack(pw.timeline.undo_stack)
        self._apply_saved_config(pw)

        pw.title_changed.connect(self._on_project_title_changed)
        pw.modified_changed.connect(self._on_project_modified_changed)
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
            previous = self._stack.currentWidget()
            new = self._projects[index]
            if isinstance(previous, ProjectWidget) and previous is not new:
                previous.pause_playback()
            self._stack.setCurrentWidget(new)
            self._nav_stack.setCurrentWidget(new.tab_bar)
            self._refresh_menu_for_active()
            # Status bar e titolo finestra seguono il progetto selezionato
            self.status_main.setText(new.last_status or "Pronto")
            self._refresh_window_title()

    def _refresh_window_title(self):
        active = self._active()
        title = active.title() if active else ""
        self.setWindowTitle(f"{title} — Video → SRT" if title else "Video → SRT")

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
            self._detach_project_nav(pw)
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
        self._detach_project_nav(pw)
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
            pw.title_changed.connect(self._on_project_title_changed)
            pw.modified_changed.connect(self._on_project_modified_changed)
            pw.status_text.connect(self._on_project_status)

    # ── Slot dai ProjectWidget ─────────────────────────────────────────────────

    def _sender_project_index(self) -> int:
        """Indice del ProjectWidget che ha emesso il segnale corrente (-1 se ignoto)."""
        sender = self.sender()
        for i, pw in enumerate(self._projects):
            if pw is sender:
                return i
        return -1

    def _on_project_title_changed(self, title: str, index: Optional[int] = None):
        if index is None:
            index = self._sender_project_index()
        if index < 0:
            return
        self.proj_tab_bar.set_tab_title(index, title)
        # Aggiorna titolo finestra se è il progetto attivo
        if index == self.proj_tab_bar.current_index():
            self._refresh_window_title()

    def _on_project_modified_changed(self, modified: bool, index: Optional[int] = None):
        if index is None:
            index = self._sender_project_index()
        if index < 0:
            return
        self.proj_tab_bar.set_tab_modified(index, modified)

    def _on_project_status(self, text: str):
        """
        Aggiorna status bar.
        Tutti i ProjectWidget sono connessi a questo slot; filtra per sender().
        """
        sender = self.sender()
        if isinstance(sender, ProjectWidget):
            sender.last_status = text if text else "Pronto"
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
        protect_extension_buttons(bar)

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

        # Configurazione dei parametri di trascrizione (file .vsrtconfig)
        self.act_import_config = self._add_action(
            m_file, "Importa configurazione…", self._import_config)
        self.act_export_config = self._add_action(
            m_file, "Esporta configurazione…", self._export_config)
        self.act_reset_config = self._add_action(
            m_file, "Ripristina predefiniti", self._reset_config)
        for act in (self.act_import_config, self.act_export_config, self.act_reset_config):
            # macOS non deve spostarle nel menu dell'app (euristica sul testo)
            act.setMenuRole(QAction.NoRole)

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
        # Tiene il menu in sync anche quando il tema cambia dal toggle nell'intestazione
        theme.MANAGER.theme_changed.connect(self._refresh_theme_ui)

    # ── Tema chiaro/scuro ───────────────────────────────────────────────────────
    # Il toggle visibile vive nell'intestazione (la menu bar
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
        sb.setFixedHeight(26)
        sb.setSizeGripEnabled(False)
        self.status_main = _StatusLabel("Pronto")
        self.status_main.setContentsMargins(10, 0, 0, 0)
        sb.addWidget(self.status_main)
        self.status_proj = QLabel("")
        self.status_proj.setContentsMargins(0, 0, 10, 0)
        sb.addPermanentWidget(self.status_proj)
        self._status_bar = sb
        self.setStatusBar(sb)
        self._apply_status_style()

    # ── Apertura file ──────────────────────────────────────────────────────────

    def _open_any(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Apri file…", "", FILE_FILTER_OPEN_ANY
        )
        if path:
            self._open_path(path)

    def _on_recent_action(self, _checked: bool = False):
        act = self.sender()
        if act is not None and act.data():
            self._open_path(str(act.data()))

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

    # ── Configurazione dei parametri di trascrizione ───────────────────────────

    def _apply_saved_config(self, pw: ProjectWidget):
        """Mostra nella Home di ``pw`` l'ultima configurazione usata."""
        from engine import recommended_model
        config, name = read_config(QSettings("VideoSRT", "v2"),
                                   default_model=recommended_model())
        try:
            pw.home.apply_config(config, name)
        except ValueError as e:
            logger.warning("Configurazione salvata non applicabile, uso i predefiniti: %s", e)

    def _apply_config_everywhere(self, config: TranscriptionConfig, name: str) -> None:
        """Applica la configurazione a tutte le Home, la ricorda e aggiorna i controlli
        dell'editor. ValueError (nessuna modifica) se un progetto non può usarla."""
        for pw in self._projects:
            pw.home.check_config(config)
        for pw in self._projects:
            pw.home.apply_config(config, name)
        write_config(QSettings("VideoSRT", "v2"), config, name)
        set_active_readability(config.readability)
        for pw in self._projects:
            pw.timeline.model.refresh_checks()

    def _config_dir(self) -> str:
        d = QSettings("VideoSRT", "v2").value(CONFIG_DIR_KEY, "")
        return d if isinstance(d, str) and os.path.isdir(d) else ""

    def _remember_config_dir(self, path: str) -> None:
        QSettings("VideoSRT", "v2").setValue(CONFIG_DIR_KEY, str(Path(path).parent))

    def _import_config(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Importa configurazione", self._config_dir(), CONFIG_FILE_FILTER
        )
        if path:
            self.import_config_file(path)

    def import_config_file(self, path: str) -> bool:
        """Carica una configurazione da file e la mostra nella schermata iniziale."""
        name = Path(path).stem
        try:
            self._apply_config_everywhere(load_config(path), name)
        except ValueError as e:
            QMessageBox.warning(
                self, "Configurazione non importata",
                f"Impossibile importare \"{Path(path).name}\".\n\n{e}",
            )
            return False
        self._remember_config_dir(path)
        self.status_main.setText(f"Configurazione importata: {name}")
        return True

    def _export_config(self):
        from PySide6.QtWidgets import QFileDialog
        pw = self._active()
        name = (pw.home.config_name() if pw else "") or "configurazione"
        start = os.path.join(self._config_dir(), name + CONFIG_EXT)
        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta configurazione", start, CONFIG_FILE_FILTER
        )
        if path:
            self.export_config_file(path)

    def export_config_file(self, path: str) -> Optional[str]:
        """Salva la configurazione del progetto attivo. Ritorna il percorso scritto."""
        if not Path(path).suffix:
            path += CONFIG_EXT
        pw = self._active()
        try:
            config = (pw.home.current_config() if pw
                      else read_config(QSettings("VideoSRT", "v2"))[0])
        except ValueError as e:      # glossario scritto non valido
            QMessageBox.warning(self, "Configurazione non esportata", str(e))
            return None
        try:
            save_config(config, path)
        except OSError as e:
            QMessageBox.critical(
                self, "Configurazione non esportata",
                f"Impossibile salvare \"{Path(path).name}\".\n\n{e.strerror or e}",
            )
            return None
        self._remember_config_dir(path)
        self.status_main.setText(f"Configurazione esportata: {Path(path).name}")
        return path

    def _reset_config(self):
        pw = self._active()
        default = TranscriptionConfig()
        try:
            current = pw.home.current_config() if pw is not None else default
        except ValueError:           # glossario non valido: è comunque una modifica
            current = None
        changed = current != default or (pw is not None and bool(pw.home.config_name()))
        if changed and not self._confirm_reset_config():
            return
        self._apply_config_everywhere(default, "")
        self.status_main.setText("Parametri di trascrizione predefiniti ripristinati")

    def _confirm_reset_config(self) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Ripristina predefiniti")
        box.setText("Ripristinare i parametri di trascrizione predefiniti?")
        box.setInformativeText(
            "La configurazione attuale verrà sostituita in tutti i progetti. Per "
            "conservarla, esportala prima con File → Esporta configurazione…."
        )
        reset = box.addButton("Ripristina", QMessageBox.AcceptRole)
        cancel = box.addButton("Annulla", QMessageBox.RejectRole)
        box.setDefaultButton(reset)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is reset

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
            act.triggered.connect(self._on_recent_action)
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

    def _fit_min_height(self):
        """Altezza minima = quella che serve alla Home: le impostazioni di trascrizione non
        scorrono, quindi la finestra non deve poterle schiacciare (entro lo schermo)."""
        needed = QMainWindow.minimumSizeHint(self).height()
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            needed = min(needed, screen.availableGeometry().height())
        if needed > self.minimumHeight():
            self.setMinimumHeight(needed)
            if self.height() < needed:
                self.resize(self.width(), needed)

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
            QDir.toNativeSeparators(u.toLocalFile())
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
