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

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox,
    QPlainTextEdit, QFrame, QPushButton, QScrollArea
)

from core.subtitle_table_model import SubtitleTableModel, MAX_CPS, WARN_CPS
from ui import theme
import platform_support


class InspectorWidget(QWidget):
    # Emessi quando l'utente modifica qualcosa
    text_committed       = Signal(int, str)       # row, new_text
    start_committed      = Signal(int, float)     # row, new_start
    end_committed        = Signal(int, float)     # row, new_end
    shift_requested      = Signal(int, float)     # row, delta_seconds (sposta start+end atomicamente)

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

        # ---- Tempi ----
        self._section(layout, "Tempi")

        fm = self.fontMetrics()
        lbl_w = max(fm.horizontalAdvance("Inizio"), fm.horizontalAdvance("Fine")) + 8

        # Inizio
        start_row = QHBoxLayout()
        start_lbl = QLabel("Inizio")
        start_lbl.setMinimumWidth(lbl_w)
        start_row.addWidget(start_lbl)
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setAccessibleName("Inizio sottotitolo (secondi)")
        start_lbl.setBuddy(self.start_spin)
        self.start_spin.setRange(0.0, 360000.0)
        self.start_spin.setDecimals(3)
        self.start_spin.setSuffix(" s")
        self.start_spin.setSingleStep(0.1)
        self.start_spin.editingFinished.connect(self._on_start_changed)
        start_row.addWidget(self.start_spin, 1)
        layout.addLayout(start_row)

        # Fine
        end_row = QHBoxLayout()
        end_lbl = QLabel("Fine")
        end_lbl.setMinimumWidth(lbl_w)
        end_row.addWidget(end_lbl)
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setAccessibleName("Fine sottotitolo (secondi)")
        end_lbl.setBuddy(self.end_spin)
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
        self._shift_buttons = []
        for label, delta in (("−100 ms", -0.1), ("−10 ms", -0.01),
                             ("+10 ms", +0.01), ("+100 ms", +0.1)):
            b = QPushButton(label)
            # larghezza dalle metriche del font: niente testo tagliato con font grandi
            b.setMinimumWidth(fm.horizontalAdvance(label) + 16)
            b.setStyleSheet("QPushButton { padding: 4px 6px; font-size: 12px; }")
            b.setToolTip(f"Sposta inizio e fine di {label}")
            b.setAccessibleName(f"Sposta di {label}")
            b.clicked.connect(lambda _=False, d=delta: self._shift_both(d))
            shift_row.addWidget(b, 1)
            self._shift_buttons.append(b)
        layout.addLayout(shift_row)

        # Info durata/CPS
        self.dur_label = QLabel("—")
        self.dur_label.setObjectName("muted")
        layout.addWidget(self.dur_label)

        # ---- Testo ----
        self._section(layout, "Testo")

        self.text_edit = QPlainTextEdit()
        self.text_edit.setMinimumHeight(fm.lineSpacing() * 4 + 24)
        self.text_edit.setPlaceholderText("Testo del sottotitolo…")
        self.text_edit.setAccessibleName("Testo del sottotitolo")
        self.text_edit.setTabChangesFocus(True)   # Tab passa al controllo successivo
        self.text_edit.textChanged.connect(self._on_text_changed_live)
        # Uscendo dal campo il testo viene confermato (mai perso in silenzio)
        self.text_edit.installEventFilter(self)
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

        # Conferma testo: Ctrl+Invio, oppure uscendo dal campo
        commit_hint = QLabel(
            f"{platform_support.shortcut_label('Ctrl+Return')} per applicare"
            "  ·  applicato anche uscendo dal campo"
        )
        commit_hint.setWordWrap(True)
        commit_hint.setObjectName("subtitle")
        commit_hint.setAlignment(Qt.AlignRight)
        layout.addWidget(commit_hint)

        # ---- Problemi ----
        self._section(layout, "Diagnostica")
        self.issues_label = QLabel("—")
        self.issues_label.setWordWrap(True)
        self.issues_label.setObjectName("muted")
        layout.addWidget(self.issues_label)

        layout.addStretch(1)

        # Ordine di tab: Inizio → Fine → spostamenti → Testo
        chain = [self.start_spin, self.end_spin, *self._shift_buttons, self.text_edit]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

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
        for w in (self.start_spin, self.end_spin, self.text_edit, *self._shift_buttons):
            w.setEnabled(on)

    # ---- Interfaccia pubblica ----
    def bind_model(self, model: SubtitleTableModel):
        self._model = model
        model.dataChanged.connect(self._on_model_data_changed)
        model.rowsRemoved.connect(self._on_rows_changed)
        model.rowsInserted.connect(self._on_rows_changed)
        model.modelReset.connect(self._on_rows_changed)

    def show_row(self, row: Optional[int]):
        if row != self._current_row:
            # Il testo non confermato della riga precedente non va perso
            self._commit_text()
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
            self.issues_label.setText("Nessun problema rilevato")
            self.issues_label.setStyleSheet(f"color: {theme.c('ok')};")
        else:
            self.issues_label.setText("\n".join(f"• {i}" for i in issues))
            sev = self._model.row_severity(self._current_row)
            self.issues_label.setStyleSheet(
                f"color: {theme.c('err' if sev == 'error' else 'warn')};"
            )

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

    def has_uncommitted_text(self) -> bool:
        """True se il campo testo contiene modifiche non ancora confermate."""
        if self._model is None or self._current_row is None:
            return False
        sub = self._model.subtitle_at(self._current_row)
        return sub is not None and self.text_edit.toPlainText().strip() != sub.text

    def _commit_text(self):
        if self._current_row is None or not self.has_uncommitted_text():
            return
        new_text = self.text_edit.toPlainText().strip()
        self.text_committed.emit(self._current_row, new_text)

    def eventFilter(self, obj, event):
        if obj is self.text_edit and event.type() == QEvent.FocusOut:
            self._commit_text()
        return super().eventFilter(obj, event)

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
