"""
subtitle_timeline.py — Pannello timeline sottotitoli (A2).

Estrae la logica di tabella + toolbar da editor_panel.py in un widget
autonomo. Pensato per vivere nel pannello inferiore del layout DaVinci.

API pubblica identica a EditorPanel:
  load_subtitles(subtitles)
  load_audio(file_path)
  get_subtitles() → list[Subtitle]
  export_action() → QAction
  is_modified() → bool
  mark_saved()

Il QUndoStack è interno; il chiamante può passarne uno esterno via
set_undo_stack() se vuole un undo globale condiviso.
"""

from __future__ import annotations
from typing import List

from PySide6.QtCore import Qt, Signal, QModelIndex, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoStack, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QMainWindow, QTableView,
    QToolBar, QHeaderView, QAbstractItemView,
    QPushButton, QSizePolicy, QMenu, QLineEdit, QFileDialog,
)

from core.subtitle_model import Subtitle
from core.subtitle_table_model import (
    SubtitleTableModel, COL_INDEX, COL_START, COL_END, COL_DUR, COL_CPS, COL_TEXT
)
from core.undo_commands import (
    EditFieldCommand, DeleteSubtitleCommand,
    SplitSubtitleCommand, MergeWithNextCommand, ReplaceAllCommand
)
from core.audio_player import AudioPlayer

from ui.inspector_widget import InspectorWidget
from ui.find_replace_dialog import FindReplaceDialog
from ui.transport_bar import TransportBar
from ui.waveform_widget import WaveformWidget


class SubtitleTimeline(QWidget):
    """
    Timeline sottotitoli con toolbar compatta integrata.
    Usa un QMainWindow interno per supportare il QDockWidget dell'Inspector.
    """

    subtitles_changed = Signal()
    jkl_pressed = Signal(str)   # "J" | "K" | "L"
    status_text = Signal(str)   # testo per la status bar esterna

    def __init__(self, parent=None):
        super().__init__(parent)

        self.model = SubtitleTableModel()
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(500)

        self._find_dialog: FindReplaceDialog | None = None

        # Player: usa sempre quello esterno passato da workspace via set_player().
        # AudioPlayer interno come fallback solo se set_player() non viene chiamato.
        self._own_player = AudioPlayer(self)
        self.player: AudioPlayer = self._own_player
        self._loop_timer = QTimer(self)
        self._loop_timer.timeout.connect(self._check_loop)

        # Layout radice — QMainWindow interno per QDockWidget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._inner = QMainWindow()
        self._inner.setDockOptions(
            QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks
        )
        layout.addWidget(self._inner)

        self._build_toolbar()

        # TableView
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.view.verticalHeader().setVisible(False)
        self.view.setWordWrap(True)
        self.view.verticalHeader().setDefaultSectionSize(52)

        h = self.view.horizontalHeader()
        h.setSectionResizeMode(COL_INDEX, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_START, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_END,   QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_DUR,   QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_CPS,   QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_TEXT,  QHeaderView.Stretch)
        h.setStretchLastSection(True)

        self._inner.setCentralWidget(self.view)

        # Inspector: creato ma non aggiunto come dock — gestito esternamente da WorkspaceWidget.
        # Workspace chiama inspector.bind_model(self.model) e wira i segnali.
        self.inspector = InspectorWidget()
        self.inspector.bind_model(self.model)

        # Nessuna status bar interna — evita il doppio footer con QStatusBar di MainWindow.
        # Lo stato viene emesso via status_text signal.

        self._wire()

    # ---- Toolbar ----

    def _build_toolbar(self):
        _TB_STYLE = (
            "QToolBar {"
            "  background: #15171d;"
            "  border-bottom: 1px solid #000000;"
            "  spacing: 2px;"
            "  padding: 3px 6px;"
            "}"
            "QToolBar::separator {"
            "  background: #262a33;"
            "  width: 1px;"
            "  margin: 4px 4px;"
            "}"
        )
        _BTN_STYLE = (
            "QPushButton {"
            "  background: #1a1d24;"
            "  border: 1px solid #262a33;"
            "  border-radius: 5px;"
            "  color: #a8aebb;"
            "  font-size: 12px;"
            "  font-weight: 500;"
            "  padding: 0 10px;"
            "  min-height: 26px;"
            "  max-height: 26px;"
            "}"
            "QPushButton:hover { background: #1f232c; color: #e8eaf0; border-color: #3a404e; }"
            "QPushButton:pressed { background: #262a33; }"
        )

        tb = QToolBar("TimelineToolbar", self._inner)
        tb.setMovable(False)
        tb.setStyleSheet(_TB_STYLE)
        self._inner.addToolBar(tb)

        # ── Undo / Redo ────────────────────────────────────────────────────────
        self.act_undo = self.undo_stack.createUndoAction(self, "↩")
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_undo.setToolTip("Annulla  ⌘Z")
        self.act_redo = self.undo_stack.createRedoAction(self, "↪")
        self.act_redo.setShortcut(QKeySequence.Redo)
        self.act_redo.setToolTip("Ripeti  ⌘⇧Z")
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        tb.addSeparator()

        # ── Operazioni sottotitoli ─────────────────────────────────────────────
        def _tb_btn(text, tooltip, shortcut=None):
            b = QPushButton(text)
            b.setStyleSheet(_BTN_STYLE)
            b.setToolTip(tooltip)
            b.setCursor(Qt.PointingHandCursor)
            if shortcut:
                b.setShortcut(shortcut)
            return b

        btn_split = _tb_btn("÷ Dividi", "Dividi sottotitolo al cursore  ⌘K", "Ctrl+K")
        btn_split.clicked.connect(self._split_current)
        tb.addWidget(btn_split)

        btn_merge = _tb_btn("⊔ Unisci", "Unisci al successivo  ⌘M", "Ctrl+M")
        btn_merge.clicked.connect(self._merge_next)
        tb.addWidget(btn_merge)

        btn_del = _tb_btn("× Elimina", "Elimina selezionati  ⌘⇧K", "Ctrl+Shift+K")
        btn_del.clicked.connect(self._delete_selected)
        tb.addWidget(btn_del)

        tb.addSeparator()

        # ── Importa ────────────────────────────────────────────────────────────
        btn_import = _tb_btn("+ Importa", "Importa file SRT o progetto .v2srt")
        btn_import.clicked.connect(self._import_file)
        tb.addWidget(btn_import)

        tb.addSeparator()

        # ── Inspector toggle ───────────────────────────────────────────────────
        self.act_toggle_insp = QAction("◧ Ispettore", self)
        self.act_toggle_insp.setCheckable(True)
        self.act_toggle_insp.setChecked(True)
        self.act_toggle_insp.setShortcut("Ctrl+I")
        self.act_toggle_insp.setToolTip("Mostra/nascondi Ispettore  ⌘I")
        # Il toggle_insp ora controlla l'inspector esterno — segnale gestito da workspace
        tb.addAction(self.act_toggle_insp)

        # ── Spacer ────────────────────────────────────────────────────────────
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        # ── Ricerca inline ────────────────────────────────────────────────────
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("⌕  Cerca sottotitolo…")
        self._search_box.setFixedWidth(220)
        self._search_box.setFixedHeight(26)
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setStyleSheet(
            "QLineEdit {"
            "  background: #1a1d24; border: 1px solid #262a33; border-radius: 5px;"
            "  color: #e8eaf0; font-size: 12px; padding: 0 8px;"
            "}"
            "QLineEdit:focus { border-color: #5b8cff; }"
        )
        self._search_box.textChanged.connect(self._on_search)
        self._search_box.returnPressed.connect(self._on_search_next)
        QShortcut(QKeySequence.Find, self, activated=self._focus_search)
        tb.addWidget(self._search_box)
        self._search_idx = -1   # indice corrente ricerca

        tb.addSeparator()

        # ── Esporta (btn + freccia dropdown) ──────────────────────────────────
        self._export_btn = QPushButton("↑ Esporta SRT")
        self._export_btn.setToolTip("Esporta SRT  ⌘S")
        self._export_btn.setFixedHeight(26)
        self._export_btn.setStyleSheet(
            "QPushButton {"
            "  background: #5b8cff; color: #fff; font-weight: 600; font-size: 12px;"
            "  border: none; border-radius: 5px 0 0 5px; padding: 0 12px;"
            "}"
            "QPushButton:hover { background: #7aa2ff; }"
            "QPushButton:pressed { background: #3f6fd8; }"
        )
        tb.addWidget(self._export_btn)

        self._export_arrow = QPushButton("▾")
        self._export_arrow.setToolTip("Scegli formato di esportazione")
        self._export_arrow.setFixedHeight(26)
        self._export_arrow.setFixedWidth(20)
        self._export_arrow.setStyleSheet(
            "QPushButton {"
            "  background: #3f6fd8; color: #fff; font-size: 10px;"
            "  border: none; border-radius: 0 5px 5px 0; padding: 0;"
            "}"
            "QPushButton:hover { background: #5b8cff; }"
        )
        self._export_arrow.clicked.connect(self._show_export_menu)
        tb.addWidget(self._export_arrow)

        right_margin = QWidget()
        right_margin.setFixedWidth(4)
        tb.addWidget(right_margin)

        # ── Actions ────────────────────────────────────────────────────────────
        self.act_export = QAction("Esporta SRT", self)
        self.act_export.setShortcut(QKeySequence.Save)
        self._export_btn.clicked.connect(self.act_export.trigger)

        self.act_export_vtt   = QAction("Esporta VTT…", self)
        self.act_export_txt   = QAction("Esporta TXT…", self)
        self.act_export_ass   = QAction("Esporta ASS…", self)
        self.act_export_v2srt = QAction("Salva progetto .v2srt…", self)

        # act_split/merge/delete/find come QAction per compatibilità
        self.act_split  = QAction("Dividi", self); self.act_split.triggered.connect(self._split_current)
        self.act_merge  = QAction("Unisci", self); self.act_merge.triggered.connect(self._merge_next)
        self.act_delete = QAction("Elimina", self); self.act_delete.triggered.connect(self._delete_selected)
        self.act_find   = QAction("Trova", self); self.act_find.triggered.connect(self._focus_search)

        self._toolbar = tb

    def _show_export_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #1a1d24; border: 1px solid #262a33; border-radius: 8px; padding: 4px; }"
            "QMenu::item { color: #e8eaf0; padding: 7px 20px; font-size: 12px; border-radius: 5px; }"
            "QMenu::item:selected { background: #3f6fd8; color: #fff; }"
            "QMenu::separator { height: 1px; background: #262a33; margin: 3px 6px; }"
        )
        menu.addAction(self.act_export)
        menu.addSeparator()
        menu.addAction(self.act_export_vtt)
        menu.addAction(self.act_export_txt)
        menu.addAction(self.act_export_ass)
        menu.addSeparator()
        menu.addAction(self.act_export_v2srt)
        pos = self._export_arrow.mapToGlobal(self._export_arrow.rect().bottomLeft())
        menu.exec(pos)

    # ---- Ricerca inline ----

    def _focus_search(self):
        self._search_box.setFocus()
        self._search_box.selectAll()

    def _on_search(self, text: str):
        self._search_idx = -1
        if not text:
            self._clear_search_highlight()
            return
        self._do_search(text, forward=True)

    def _on_search_next(self):
        text = self._search_box.text()
        if text:
            self._do_search(text, forward=True)

    def _do_search(self, text: str, forward: bool = True):
        n = self.model.rowCount()
        if n == 0:
            return
        start = (self._search_idx + 1) % n if forward else (self._search_idx - 1) % n
        for i in range(n):
            row = (start + i) % n
            sub = self.model.subtitle_at(row)
            if sub and text.lower() in sub.text.lower():
                self._search_idx = row
                self.view.selectRow(row)
                self.view.scrollTo(
                    self.model.index(row, COL_TEXT),
                    QAbstractItemView.PositionAtCenter
                )
                return

    def _clear_search_highlight(self):
        self._search_idx = -1

    # ---- Importa file ----

    def _import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importa file",
            "",
            "File supportati (*.srt *.v2srt);;"
            "SRT (*.srt);;"
            "Progetto V2SRT (*.v2srt)"
        )
        if not path:
            return
        from pathlib import Path as _Path
        ext = _Path(path).suffix.lower()
        try:
            if ext == ".srt":
                from core.srt_io import parse_srt
                subs = parse_srt(path)
                self.load_subtitles(subs)
            elif ext == ".v2srt":
                from core.v2srt_io import load_v2srt
                project = load_v2srt(path)
                self.load_subtitles(project.subtitles)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Errore importazione", str(e))

    # ---- Wiring ----

    def _wire(self):
        self.model.set_edit_handler(self._handle_table_edit)

        self.inspector.text_committed.connect(self._on_insp_text)
        self.inspector.start_committed.connect(self._on_insp_start)
        self.inspector.end_committed.connect(self._on_insp_end)
        self.inspector.shift_requested.connect(self._on_insp_shift)
        self.inspector.split_requested.connect(lambda r, p: self.undo_stack.push(SplitSubtitleCommand(self.model, r, p)))
        self.inspector.merge_prev_requested.connect(self._on_insp_merge_prev)
        self.inspector.merge_next_requested.connect(self._on_insp_merge_next)
        self.inspector.delete_requested.connect(lambda r: self.undo_stack.push(DeleteSubtitleCommand(self.model, [r])))

        self.view.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self.view.clicked.connect(self._on_cell_clicked)

        self.model.dataModified.connect(self._update_status)
        self.model.rowsInserted.connect(self._update_status)
        self.model.rowsRemoved.connect(self._update_status)
        self.model.modelReset.connect(self._update_status)
        self.model.dataModified.connect(self.subtitles_changed)
        self.undo_stack.cleanChanged.connect(lambda _: self._update_status())

        # Inspector toggle: segnale gestito da WorkspaceWidget via act_toggle_insp.triggered

        # Player
        self.player.position_changed.connect(self._on_player_pos)
        self.player.duration_changed.connect(lambda _: None)   # gestito da PreviewArea
        self.player.source_ready.connect(lambda: None)

        # Shortcut playback NLE
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._shortcut_play_pause)
        QShortcut(QKeySequence(Qt.Key_K),     self, activated=lambda: self._if_not_typing(self._jkl_k))
        QShortcut(QKeySequence(Qt.Key_J),     self, activated=lambda: self._if_not_typing(self._jkl_j))
        QShortcut(QKeySequence(Qt.Key_L),     self, activated=lambda: self._if_not_typing(self._jkl_l))
        QShortcut(QKeySequence(Qt.Key_Left),  self, activated=lambda: self._if_not_typing(lambda: self.player.seek_relative(-1000)))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self._if_not_typing(lambda: self.player.seek_relative(1000)))
        QShortcut(QKeySequence("Shift+Left"),  self, activated=lambda: self._if_not_typing(self._go_prev_sub))
        QShortcut(QKeySequence("Shift+Right"), self, activated=lambda: self._if_not_typing(self._go_next_sub))
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.undo_stack.redo)

    # ---- API pubblica ----

    def load_subtitles(self, subtitles: List[Subtitle]):
        self.undo_stack.clear()
        self.model.set_subtitles(subtitles)
        if subtitles:
            self.view.selectRow(0)
        self._update_status()

    def load_audio(self, file_path: str):
        self.player.load(file_path)

    def get_subtitles(self) -> List[Subtitle]:
        return self.model.subtitles()

    def export_action(self) -> QAction:
        return self.act_export

    def is_modified(self) -> bool:
        return not self.undo_stack.isClean()

    def mark_saved(self):
        self.undo_stack.setClean()
        self._update_status()

    def set_player(self, player: AudioPlayer):
        """
        Collega un player esterno (da PreviewArea/WorkspaceWidget).
        Disconnette il player interno e usa quello condiviso.
        Da chiamare prima di load_audio() o load_subtitles().
        """
        # Disconnetti segnali dal player interno (se diverso)
        if player is self.player:
            return
        try:
            self._own_player.position_changed.disconnect(self._on_player_pos)
        except RuntimeError:
            pass
        self.player = player
        # Riconnetti shortcut al nuovo player
        self.player.position_changed.connect(self._on_player_pos)

    def set_undo_stack(self, stack: QUndoStack):
        """Sostituisce lo stack interno con uno condiviso (opzionale)."""
        self.undo_stack = stack
        self.act_undo = stack.createUndoAction(self, "Annulla")
        self.act_redo = stack.createRedoAction(self, "Ripeti")

    # ---- Selezione → Inspector ----

    def _on_row_changed(self, current: QModelIndex, _prev: QModelIndex):
        row = current.row() if current.isValid() else None
        self.inspector.show_row(row)

    def _on_cell_clicked(self, index: QModelIndex):
        """
        Click singolo su cella:
          - Colonna TESTO → entra subito in editing (nessun seek)
          - Altre colonne  → seek player all'inizio del sottotitolo
        Se la view è già in EditingState non fa nulla.
        """
        try:
            if self.view.state() == QAbstractItemView.State.EditingState:
                return
        except AttributeError:
            pass

        if index.column() == COL_TEXT:
            self.view.edit(index)
            return

        row = index.row()
        sub = self.model.subtitle_at(row)
        if sub is not None:
            self.player.seek(int(sub.start * 1000))

    # ---- Edit handler ----

    def _handle_table_edit(self, row: int, col: int, value) -> bool:
        sub = self.model.subtitle_at(row)
        if sub is None:
            return False
        if col == COL_TEXT:
            new_text = str(value).strip()
            if new_text == sub.text:
                return False
            self.undo_stack.push(EditFieldCommand(self.model, row, COL_TEXT, sub.text, new_text, "Modifica testo"))
            return True
        if col in (COL_START, COL_END):
            from core.subtitle_table_model import parse_timestamp
            new_val = parse_timestamp(str(value))
            if new_val is None:
                return False
            old_val = sub.start if col == COL_START else sub.end
            if abs(new_val - old_val) < 0.0005:
                return False
            label = "Modifica start" if col == COL_START else "Modifica end"
            self.undo_stack.push(EditFieldCommand(
                self.model, row, col, f"{old_val:.3f}", f"{new_val:.3f}", label
            ))
            return True
        return False

    # ---- Inspector handlers ----

    def _on_insp_text(self, row: int, new_text: str):
        sub = self.model.subtitle_at(row)
        if sub and sub.text != new_text:
            self.undo_stack.push(EditFieldCommand(self.model, row, COL_TEXT, sub.text, new_text, "Modifica testo"))

    def _on_insp_start(self, row: int, new_val: float):
        sub = self.model.subtitle_at(row)
        if sub and abs(new_val - sub.start) >= 0.0005:
            self.undo_stack.push(EditFieldCommand(self.model, row, COL_START, f"{sub.start:.3f}", f"{new_val:.3f}", "Modifica start"))

    def _on_insp_end(self, row: int, new_val: float):
        sub = self.model.subtitle_at(row)
        if sub and abs(new_val - sub.end) >= 0.0005:
            self.undo_stack.push(EditFieldCommand(self.model, row, COL_END, f"{sub.end:.3f}", f"{new_val:.3f}", "Modifica end"))

    def _on_insp_shift(self, row: int, delta: float):
        sub = self.model.subtitle_at(row)
        if sub is None:
            return
        new_start = max(0.0, sub.start + delta)
        new_end   = max(0.0, sub.end   + delta)
        if abs(new_start - sub.start) < 0.0005:
            return
        self.undo_stack.beginMacro(f"Sposta {delta*1000:+.0f}ms")
        self.undo_stack.push(EditFieldCommand(self.model, row, COL_START, f"{sub.start:.3f}", f"{new_start:.3f}", "Sposta start"))
        self.undo_stack.push(EditFieldCommand(self.model, row, COL_END,   f"{sub.end:.3f}",   f"{new_end:.3f}",   "Sposta end"))
        self.undo_stack.endMacro()

    def _on_insp_merge_prev(self, row: int):
        if row and row > 0:
            self.undo_stack.push(MergeWithNextCommand(self.model, row - 1))
            self.view.selectRow(row - 1)

    def _on_insp_merge_next(self, row: int):
        if row is not None and row < self.model.rowCount() - 1:
            self.undo_stack.push(MergeWithNextCommand(self.model, row))

    # ---- Toolbar actions ----

    def _current_row(self) -> int:
        idx = self.view.currentIndex()
        return idx.row() if idx.isValid() else -1

    def _split_current(self):
        row = self._current_row()
        if row < 0:
            return
        sub = self.model.subtitle_at(row)
        if sub is None or len(sub.text) < 3:
            return
        pos = len(sub.text) // 2
        try:
            if self.inspector.text_edit.hasFocus():
                p = self.inspector.text_edit.textCursor().position()
                if 0 < p < len(sub.text):
                    pos = p
        except Exception:
            pass
        self.undo_stack.push(SplitSubtitleCommand(self.model, row, pos))

    def _merge_next(self):
        row = self._current_row()
        if 0 <= row < self.model.rowCount() - 1:
            self.undo_stack.push(MergeWithNextCommand(self.model, row))

    def _delete_selected(self):
        rows = sorted({idx.row() for idx in self.view.selectionModel().selectedRows()})
        if not rows:
            r = self._current_row()
            if r >= 0:
                rows = [r]
        if not rows:
            return
        first = rows[0]
        self.undo_stack.push(DeleteSubtitleCommand(self.model, rows))
        remaining = self.model.rowCount()
        if remaining > 0:
            self.view.selectRow(min(first, remaining - 1))

    # ---- Find & Replace ----

    def _open_find_replace(self):
        if self._find_dialog is None:
            self._find_dialog = FindReplaceDialog(self.model, self)
            self._find_dialog.match_found.connect(
                lambda r: self.view.selectRow(r) or self.view.scrollTo(
                    self.model.index(r, COL_TEXT), QAbstractItemView.PositionAtCenter
                )
            )
            self._find_dialog.replace_all_requested.connect(
                lambda reps: self.undo_stack.push(ReplaceAllCommand(self.model, reps)) if reps else None
            )
        self._find_dialog.show()
        self._find_dialog.raise_()
        self._find_dialog.activateWindow()
        self._find_dialog.focus_find()

    # ---- Player ----

    def _on_player_pos(self, ms: int):
        if self.model.rowCount() == 0:
            return
        pos_s = ms / 1000.0
        for row in range(self.model.rowCount()):
            sub = self.model.subtitle_at(row)
            if sub and sub.start <= pos_s <= sub.end:
                if self.view.currentIndex().row() != row:
                    try:
                        editing = (self.view.state() == QAbstractItemView.State.EditingState)
                    except AttributeError:
                        editing = False
                    if not editing:
                        self.view.selectRow(row)
                        self.view.scrollTo(self.model.index(row, COL_TEXT), QAbstractItemView.EnsureVisible)
                break

    def _check_loop(self):
        row = self._current_row()
        if row < 0:
            return
        sub = self.model.subtitle_at(row)
        if sub and self.player.is_playing():
            if self.player.position() >= int(sub.end * 1000):
                self.player.seek(int(sub.start * 1000))

    # ---- Shortcut playback ----

    @staticmethod
    def _focus_is_text_input() -> bool:
        from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox
        fw = QApplication.focusWidget()
        return isinstance(fw, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox))

    def _if_not_typing(self, fn):
        if not self._focus_is_text_input():
            fn()

    def _shortcut_play_pause(self):
        self._if_not_typing(self.player.toggle_play_pause)

    def _shortcut_rewind(self):
        if self.player.is_playing():
            self.player.set_rate(max(0.25, self.player.rate() / 2.0))
        else:
            self.player.seek_relative(-2000)

    def _shortcut_forward(self):
        if self.player.is_playing():
            self.player.set_rate(min(4.0, self.player.rate() * 2.0))
        else:
            self.player.play()

    # ---- JKL con indicatore visivo ----

    def _jkl_j(self):
        self._shortcut_rewind()
        self.jkl_pressed.emit("J")

    def _jkl_k(self):
        self.player.pause()
        self.jkl_pressed.emit("K")

    def _jkl_l(self):
        self._shortcut_forward()
        self.jkl_pressed.emit("L")

    def _go_prev_sub(self):
        n = self.model.rowCount()
        if n == 0:
            return
        row = max(0, self._current_row())
        target = max(0, row - 1)
        sub = self.model.subtitle_at(target)
        if sub:
            self.player.seek(int(sub.start * 1000))
            self.view.selectRow(target)

    def _go_next_sub(self):
        n = self.model.rowCount()
        if n == 0:
            return
        row = max(0, self._current_row())
        target = min(n - 1, row + 1)
        sub = self.model.subtitle_at(target)
        if sub:
            self.player.seek(int(sub.start * 1000))
            self.view.selectRow(target)

    # ---- Status bar ----

    def _update_status(self):
        total = self.model.rowCount()
        count_txt = f"{total} sottotitoli"
        if total == 0:
            issues_txt = ""
        else:
            errors   = sum(1 for r in range(total) if self.model.row_severity(r) == "error")
            warnings = sum(1 for r in range(total) if self.model.row_severity(r) == "warning")
            parts = []
            if errors:   parts.append(f"❌ {errors} errori")
            if warnings: parts.append(f"⚠️  {warnings} warning")
            if not parts: parts.append("✅ Tutto ok")
            issues_txt = "  ·  ".join(parts)
        mod_txt = "  ●  Modificato" if self.is_modified() else ""
        status = count_txt
        if issues_txt:
            status += f"  ·  {issues_txt}"
        status += mod_txt
        self.status_text.emit(status)
