"""
inspector_widget.py — Pannello Inspector (destra).

Mostra i dettagli del sottotitolo selezionato e permette di modificarli
con controlli più comodi della tabella (spinbox per i tempi, textarea
per il testo, contatori live).

Quando l'utente conferma, emette segnali che il MainWindow userà per
creare QUndoCommand (l'Inspector stesso non tocca il model direttamente,
per evitare cicli).
"""

from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox,
    QPlainTextEdit, QFrame, QPushButton, QScrollArea
)

from core.subtitle_model import Subtitle
from core.subtitle_table_model import SubtitleTableModel, MAX_CPS, WARN_CPS
from ui import theme


class InspectorWidget(QWidget):
    # Emessi quando l'utente modifica qualcosa
    text_committed       = Signal(int, str)       # row, new_text
    start_committed      = Signal(int, float)     # row, new_start
    end_committed        = Signal(int, float)     # row, new_end
    shift_requested      = Signal(int, float)     # row, delta_seconds (sposta start+end atomicamente)
    split_requested      = Signal(int, int)       # row, cursor_pos
    merge_prev_requested = Signal(int)
    merge_next_requested = Signal(int)
    delete_requested     = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_row: Optional[int] = None
        self._model: Optional[SubtitleTableModel] = None
        self._updating = False  # evita loop durante refresh
        self._sections: list = []   # (sep, label) per re-tematizzazione

        # Scroll per schermi piccoli
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ---- Header ----
        self.header = QLabel("Nessuna selezione")
        self.header.setObjectName("sectionTitle")
        layout.addWidget(self.header)

        # sub_count kept for API compat but hidden (merged into header)
        self.sub_count = QLabel("")
        self.sub_count.setVisible(False)
        layout.addWidget(self.sub_count)

        # ---- Timing ----
        self._section(layout, "Timing")

        # Start
        start_row = QHBoxLayout()
        start_row.addWidget(QLabel("Start"))
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0.0, 360000.0)
        self.start_spin.setDecimals(3)
        self.start_spin.setSuffix(" s")
        self.start_spin.setSingleStep(0.1)
        self.start_spin.editingFinished.connect(self._on_start_changed)
        start_row.addWidget(self.start_spin, 1)
        layout.addLayout(start_row)

        # End
        end_row = QHBoxLayout()
        end_row.addWidget(QLabel("End"))
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.0, 360000.0)
        self.end_spin.setDecimals(3)
        self.end_spin.setSuffix(" s")
        self.end_spin.setSingleStep(0.1)
        self.end_spin.editingFinished.connect(self._on_end_changed)
        end_row.addWidget(self.end_spin, 1)
        layout.addLayout(end_row)

        # Offset helpers — ordine: −100 −10 +10 +100
        shift_row = QHBoxLayout()
        shift_row.setSpacing(4)
        for label, delta in (("−100ms", -0.1), ("−10ms", -0.01),
                             ("+10ms", +0.01), ("+100ms", +0.1)):
            b = QPushButton(label)
            b.setFixedWidth(58)
            b.setToolTip(f"Sposta inizio e fine di {label}")
            b.clicked.connect(lambda _=False, d=delta: self._shift_both(d))
            shift_row.addWidget(b)
        shift_row.addStretch(1)
        layout.addLayout(shift_row)

        # Info durata/CPS
        self.dur_label = QLabel("—")
        self.dur_label.setObjectName("muted")
        layout.addWidget(self.dur_label)

        # ---- Testo ----
        self._section(layout, "Testo")

        self.text_edit = QPlainTextEdit()
        self.text_edit.setMinimumHeight(110)
        self.text_edit.setPlaceholderText("Testo del sottotitolo…")
        self.text_edit.textChanged.connect(self._on_text_changed_live)
        layout.addWidget(self.text_edit)

        # Stats testo
        stats_row = QHBoxLayout()
        self.char_count_label = QLabel("0 caratteri")
        self.char_count_label.setObjectName("subtitle")
        stats_row.addWidget(self.char_count_label)
        stats_row.addStretch(1)
        self.cps_label = QLabel("— CPS")
        self.cps_label.setObjectName("subtitle")
        stats_row.addWidget(self.cps_label)
        layout.addLayout(stats_row)

        # Commit testo: solo shortcut ⌘↵ (il bottone è ridondante)
        self.commit_text_btn = QPushButton()  # hidden, per _set_enabled compatibility
        self.commit_text_btn.setVisible(False)
        self.commit_text_btn.clicked.connect(self._commit_text)

        commit_hint = QLabel("⌘↵ per applicare")
        commit_hint.setObjectName("subtitle")
        commit_hint.setAlignment(Qt.AlignRight)
        layout.addWidget(commit_hint)

        # ---- Problemi ----
        self._section(layout, "Diagnostica")
        self.issues_label = QLabel("—")
        self.issues_label.setWordWrap(True)
        self.issues_label.setObjectName("muted")
        layout.addWidget(self.issues_label)

        # Bottoni azione nascosti (usati solo per _set_enabled ma non mostrati —
        # le azioni sono nella toolbar dell'EditorPanel)
        self.split_btn = QPushButton()
        self.split_btn.setVisible(False)
        self.split_btn.clicked.connect(self._on_split)

        self.merge_prev_btn = QPushButton()
        self.merge_prev_btn.setVisible(False)
        self.merge_prev_btn.clicked.connect(lambda: self.merge_prev_requested.emit(self._current_row))

        self.merge_next_btn = QPushButton()
        self.merge_next_btn.setVisible(False)
        self.merge_next_btn.clicked.connect(lambda: self.merge_next_requested.emit(self._current_row))

        self.delete_btn = QPushButton()
        self.delete_btn.setVisible(False)
        self.delete_btn.clicked.connect(lambda: self.delete_requested.emit(self._current_row))

        layout.addStretch(1)

        # Stato iniziale: tutto disabilitato
        self._set_enabled(False)

        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    # ---- Tema ----
    def _on_theme_changed(self, _name=None):
        c = theme.c
        for sep, lbl in self._sections:
            sep.setStyleSheet(f"background-color: {c('line')}; max-height: 1px; margin: 6px 0;")
            lbl.setStyleSheet(f"color: {c('muted')}; letter-spacing: 1px; background: transparent;")
        self._refresh()

    # ---- Utilities UI ----
    def _section(self, layout: QVBoxLayout, title: str):
        c = theme.c
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background-color: {c('line')}; max-height: 1px; margin: 6px 0;")
        layout.addWidget(sep)
        lbl = QLabel(title.upper())
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color: {c('muted')}; letter-spacing: 1px; background: transparent;")
        layout.addWidget(lbl)
        self._sections.append((sep, lbl))

    def _set_enabled(self, on: bool):
        for w in (self.start_spin, self.end_spin, self.text_edit,
                  self.commit_text_btn, self.split_btn,
                  self.merge_prev_btn, self.merge_next_btn, self.delete_btn):
            w.setEnabled(on)

    # ---- Interfaccia pubblica ----
    def bind_model(self, model: SubtitleTableModel):
        self._model = model
        model.dataChanged.connect(self._on_model_data_changed)
        model.rowsRemoved.connect(self._on_rows_changed)
        model.rowsInserted.connect(self._on_rows_changed)
        model.modelReset.connect(self._on_rows_changed)

    def show_row(self, row: Optional[int]):
        self._current_row = row
        self._refresh()

    def _on_model_data_changed(self, top, bot, roles):
        if self._current_row is None:
            return
        if top.row() <= self._current_row <= bot.row():
            self._refresh()

    def _on_rows_changed(self, *a):
        # Se la riga corrente non esiste più, deseleziona
        if self._model is None:
            return
        total = self._model.rowCount()
        if self._current_row is None or self._current_row >= total:
            self._current_row = None
        self._refresh()

    # ---- Refresh ----
    def _refresh(self):
        if self._model is None or self._current_row is None:
            total = self._model.rowCount() if self._model else 0
            self.header.setText(f"Nessuna selezione  ·  {total} sottotitoli")
            self._set_enabled(False)
            self._updating = True
            self.start_spin.setValue(0)
            self.end_spin.setValue(0)
            self.text_edit.setPlainText("")
            self._updating = False
            self.dur_label.setText("—")
            self.char_count_label.setText("0 caratteri")
            self.cps_label.setText("— CPS")
            self.issues_label.setText("—")
            return

        sub = self._model.subtitle_at(self._current_row)
        if sub is None:
            return

        total = self._model.rowCount()
        self.header.setText(f"Sottotitolo  {self._current_row + 1} / {total}")
        self._set_enabled(True)

        self._updating = True
        self.start_spin.setValue(sub.start)
        self.end_spin.setValue(sub.end)
        # Evita di spaccare il cursore se l'utente sta scrivendo
        if self.text_edit.toPlainText() != sub.text:
            cur_pos = self.text_edit.textCursor().position()
            self.text_edit.setPlainText(sub.text)
            cur = self.text_edit.textCursor()
            cur.setPosition(min(cur_pos, len(sub.text)))
            self.text_edit.setTextCursor(cur)
        self._updating = False

        self.dur_label.setText(f"Durata: {sub.duration:.2f} s")
        self._update_text_stats(sub.text, sub.duration)
        self._update_issues()

        # Abilita/disabilita merge a seconda dei vicini
        self.merge_prev_btn.setEnabled(self._current_row > 0)
        self.merge_next_btn.setEnabled(self._current_row < total - 1)

    def _update_text_stats(self, text: str, duration: float):
        txt = text.strip()
        n = len(txt)
        self.char_count_label.setText(f"{n} caratteri · {len(txt.split()) if txt else 0} parole")
        if duration > 0 and n > 0:
            cps = n / duration
            self.cps_label.setText(f"{cps:.1f} CPS")
            if cps > MAX_CPS:
                self.cps_label.setStyleSheet(f"color: {theme.c('err')}; font-weight: bold;")
            elif cps > WARN_CPS:
                self.cps_label.setStyleSheet(f"color: {theme.c('warn')};")
            else:
                self.cps_label.setStyleSheet("")
        else:
            self.cps_label.setText("— CPS")
            self.cps_label.setStyleSheet("")

    def _update_issues(self):
        if self._model is None or self._current_row is None:
            return
        issues = self._model.row_issues(self._current_row)
        if not issues:
            self.issues_label.setText("✅  Nessun problema rilevato")
            self.issues_label.setStyleSheet(f"color: {theme.c('ok')};")
        else:
            self.issues_label.setText("⚠️  " + "\n⚠️  ".join(issues))
            self.issues_label.setStyleSheet(f"color: {theme.c('warn')};")

    # ---- Event handlers ----
    def _on_start_changed(self):
        if self._updating or self._current_row is None:
            return
        new_val = self.start_spin.value()
        self.start_committed.emit(self._current_row, float(new_val))

    def _on_end_changed(self):
        if self._updating or self._current_row is None:
            return
        new_val = self.end_spin.value()
        self.end_committed.emit(self._current_row, float(new_val))

    def _on_text_changed_live(self):
        """Aggiorna solo le stats live, il commit avviene con il bottone/shortcut."""
        if self._updating:
            return
        sub = self._model.subtitle_at(self._current_row) if (self._model and self._current_row is not None) else None
        duration = sub.duration if sub else 0.0
        self._update_text_stats(self.text_edit.toPlainText(), duration)

    def _commit_text(self):
        if self._current_row is None:
            return
        new_text = self.text_edit.toPlainText().strip()
        self.text_committed.emit(self._current_row, new_text)

    def _on_split(self):
        if self._current_row is None:
            return
        cur_pos = self.text_edit.textCursor().position()
        if cur_pos <= 0 or cur_pos >= len(self.text_edit.toPlainText()):
            return
        self.split_requested.emit(self._current_row, cur_pos)

    def _shift_both(self, delta: float):
        if self._current_row is None or self._model is None:
            return
        sub = self._model.subtitle_at(self._current_row)
        if sub is None:
            return
        # Emette un segnale atomico: EditorPanel lo gestisce con un macro undo
        self.shift_requested.emit(self._current_row, delta)

    def keyPressEvent(self, e):
        # Cmd/Ctrl + Enter = commit testo
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and (e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)):
            self._commit_text()
            return
        super().keyPressEvent(e)
