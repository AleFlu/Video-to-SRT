"""
find_replace_dialog.py — Find & Replace per i sottotitoli.

Stile VSCode: search box + replace box + checkbox case-sensitive/whole-word/regex.
Mostra il numero di match e permette Replace All.

Il Find ("Next") emette `match_found(row)` che il MainWindow usa per selezionare
la riga corrispondente nella tabella.
Il Replace All emette `replace_all_requested(replacements)` con la lista di
(row, old_text, new_text) già calcolata — il MainWindow crea un ReplaceAllCommand.
"""

from __future__ import annotations
import re
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QFrame
)

from core.subtitle_table_model import SubtitleTableModel
from ui import theme


class FindReplaceDialog(QDialog):
    match_found = Signal(int)                   # row
    replace_all_requested = Signal(list)        # list[(row, old, new)]

    def __init__(self, model: SubtitleTableModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._last_match_row = -1

        self.setWindowTitle("Trova e sostituisci")
        self.setModal(False)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Find
        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("Trova"))
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Testo da cercare…")
        self.find_edit.textChanged.connect(self._update_count)
        self.find_edit.returnPressed.connect(self._find_next)
        find_row.addWidget(self.find_edit, 1)
        layout.addLayout(find_row)

        # Replace
        replace_row = QHBoxLayout()
        replace_row.addWidget(QLabel("Sostituisci"))
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Sostituisci con…")
        replace_row.addWidget(self.replace_edit, 1)
        layout.addLayout(replace_row)

        # Opzioni
        opts = QHBoxLayout()
        self.case_check = QCheckBox("Aa  Maiuscole/minuscole")
        self.word_check = QCheckBox("W  Parole intere")
        self.regex_check = QCheckBox(".* Regex")
        for cb in (self.case_check, self.word_check, self.regex_check):
            cb.stateChanged.connect(self._update_count)
            opts.addWidget(cb)
        opts.addStretch(1)
        layout.addLayout(opts)

        # Separator
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.HLine)
        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il dialog viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)
        layout.addWidget(self._sep)

        # Count + buttons
        self.count_label = QLabel("Nessuna ricerca")
        self.count_label.setObjectName("muted")
        layout.addWidget(self.count_label)

        btn_row = QHBoxLayout()
        self.find_next_btn = QPushButton("Trova successivo  (↵)")
        self.find_next_btn.clicked.connect(self._find_next)
        btn_row.addWidget(self.find_next_btn)

        self.replace_btn = QPushButton("Sostituisci")
        self.replace_btn.clicked.connect(self._replace_current)
        btn_row.addWidget(self.replace_btn)

        self.replace_all_btn = QPushButton("Sostituisci tutto")
        self.replace_all_btn.setObjectName("primary")
        self.replace_all_btn.clicked.connect(self._replace_all)
        btn_row.addWidget(self.replace_all_btn)

        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.close)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ---- Pattern builder ----
    def _build_pattern(self) -> Optional[re.Pattern]:
        needle = self.find_edit.text()
        if not needle:
            return None
        flags = 0 if self.case_check.isChecked() else re.IGNORECASE
        try:
            if self.regex_check.isChecked():
                pattern = needle
            else:
                pattern = re.escape(needle)
                if self.word_check.isChecked():
                    pattern = r"\b" + pattern + r"\b"
            return re.compile(pattern, flags)
        except re.error:
            return None

    # ---- Count ----
    def _update_count(self):
        pat = self._build_pattern()
        if pat is None:
            self.count_label.setText("—" if not self.find_edit.text() else "Pattern non valido")
            self.count_label.setStyleSheet(f"color: {theme.c('err')};" if self.find_edit.text() else "")
            return

        total_matches = 0
        total_rows = 0
        for sub in self._model.subtitles():
            matches = pat.findall(sub.text)
            if matches:
                total_rows += 1
                total_matches += len(matches)

        self.count_label.setStyleSheet("")
        if total_matches == 0:
            self.count_label.setText("Nessun risultato")
        else:
            self.count_label.setText(f"{total_matches} occorrenze in {total_rows} sottotitoli")

    # ---- Find ----
    def _find_next(self):
        pat = self._build_pattern()
        if pat is None:
            return
        subs = self._model.subtitles()
        n = len(subs)
        if n == 0:
            return

        start = (self._last_match_row + 1) % n
        for offset in range(n):
            r = (start + offset) % n
            if pat.search(subs[r].text):
                self._last_match_row = r
                self.match_found.emit(r)
                return
        self._last_match_row = -1

    # ---- Replace ----
    def _replace_current(self):
        pat = self._build_pattern()
        if pat is None or self._last_match_row < 0:
            self._find_next()
            return
        sub = self._model.subtitle_at(self._last_match_row)
        if sub is None:
            return
        try:
            new_text = pat.sub(self.replace_edit.text(), sub.text, count=1)
        except re.error:
            self._show_replace_error()
            return
        if new_text != sub.text:
            self.replace_all_requested.emit([(self._last_match_row, sub.text, new_text)])
        self._find_next()

    def _replace_all(self):
        pat = self._build_pattern()
        if pat is None:
            return
        replacement = self.replace_edit.text()
        changes = []
        try:
            for i, sub in enumerate(self._model.subtitles()):
                new_text = pat.sub(replacement, sub.text)
                if new_text != sub.text:
                    changes.append((i, sub.text, new_text))
        except re.error:
            self._show_replace_error()
            return
        if changes:
            self.replace_all_requested.emit(changes)
            self._update_count()

    def _apply_palette(self, _name=None):
        self._sep.setStyleSheet(f"background-color: {theme.c('line')}; max-height: 1px;")

    def _show_replace_error(self):
        """Backreference invalida (es. \\1 senza gruppo) nel testo di sostituzione."""
        self.count_label.setText("Testo di sostituzione non valido")
        self.count_label.setStyleSheet(f"color: {theme.c('err')};")

    # ---- Focus ----
    def focus_find(self):
        self.find_edit.setFocus()
        self.find_edit.selectAll()
