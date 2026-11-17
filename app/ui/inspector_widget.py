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
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QDoubleSpinBox,
    QPlainTextEdit, QFrame, QPushButton, QScrollArea
)

from core.subtitle_table_model import SubtitleTableModel
from core.transcription_config import active_readability
from ui import icons, theme
import platform_support

# Larghezza della colonna delle etichette Inizio / Fine / Durata (mockup)
_LABEL_COL = 52


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

        self.setObjectName("inspector")
        self.setAttribute(Qt.WA_StyledBackground, True)

        # Scroll per schermi piccoli
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("inspectorContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        fm = self.fontMetrics()

        # ---- Header: "Sottotitolo N" + "N / tot" mono ----
        head_row = QHBoxLayout()
        self.header = QLabel("Nessuna selezione")
        self.header.setObjectName("sectionTitle")
        head_row.addWidget(self.header, 1)
        self.counter_label = QLabel("")
        self.counter_label.setObjectName("inspectorCounter")
        head_row.addWidget(self.counter_label)
        layout.addLayout(head_row)

        # ---- Tempi: griglia etichetta (52 px) + campo ----
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnMinimumWidth(0, _LABEL_COL)
        grid.setColumnStretch(1, 1)

        start_lbl = QLabel("Inizio")
        start_lbl.setObjectName("inspectorLabel")
        grid.addWidget(start_lbl, 0, 0)
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setAccessibleName("Inizio sottotitolo (secondi)")
        start_lbl.setBuddy(self.start_spin)
        self.start_spin.setRange(0.0, 360000.0)
        self.start_spin.setDecimals(3)
        self.start_spin.setSuffix(" s")
        self.start_spin.setFixedHeight(28)
        self.start_spin.setSingleStep(0.1)
        self.start_spin.editingFinished.connect(self._on_start_changed)
        grid.addWidget(self.start_spin, 0, 1)

        end_lbl = QLabel("Fine")
        end_lbl.setObjectName("inspectorLabel")
        grid.addWidget(end_lbl, 1, 0)
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setAccessibleName("Fine sottotitolo (secondi)")
        end_lbl.setBuddy(self.end_spin)
        self.end_spin.setRange(0.0, 360000.0)
        self.end_spin.setDecimals(3)
        self.end_spin.setSuffix(" s")
        self.end_spin.setFixedHeight(28)
        self.end_spin.setSingleStep(0.1)
        self.end_spin.editingFinished.connect(self._on_end_changed)
        grid.addWidget(self.end_spin, 1, 1)

        dur_title = QLabel("Durata")
        dur_title.setObjectName("inspectorLabel")
        grid.addWidget(dur_title, 2, 0)
        self.dur_label = QLabel("—")
        self.dur_label.setObjectName("inspectorValue")
        grid.addWidget(self.dur_label, 2, 1)
        layout.addLayout(grid)

        # ---- Sposta inizio e fine: 4 colonne, ordine −100 −10 +10 +100 ----
        shift_box = QVBoxLayout()
        shift_box.setSpacing(6)
        shift_title = QLabel("Sposta inizio e fine")
        shift_title.setObjectName("inspectorLabel")
        shift_box.addWidget(shift_title)
        shift_grid = QGridLayout()
        shift_grid.setContentsMargins(0, 0, 0, 0)
        shift_grid.setSpacing(4)
        self._shift_buttons = []
        for i, (label, delta) in enumerate((("−100 ms", -0.1), ("−10 ms", -0.01),
                                            ("+10 ms", +0.01), ("+100 ms", +0.1))):
            b = QPushButton(label)
            b.setObjectName("inspectorShift")
            # larghezza dalle metriche del font mono: niente testo tagliato con font grandi
            b.setMinimumWidth(QFontMetrics(self._mono_font(12)).horizontalAdvance(label) + 12)
            b.setToolTip(f"Sposta inizio e fine di {label}")
            b.setAccessibleName(f"Sposta di {label}")
            b.setProperty("shiftDelta", delta)
            b.clicked.connect(self._on_shift_button)
            shift_grid.addWidget(b, 0, i)
            shift_grid.setColumnStretch(i, 1)
            self._shift_buttons.append(b)
        shift_box.addLayout(shift_grid)
        layout.addLayout(shift_box)

        # ---- Testo: etichetta + suggerimento ⌘↵, campo 14 px, contatori ----
        text_box = QVBoxLayout()
        text_box.setSpacing(6)
        text_head = QHBoxLayout()
        text_title = QLabel("Testo")
        text_title.setObjectName("inspectorLabel")
        text_head.addWidget(text_title)
        text_head.addStretch(1)
        # Conferma testo: Ctrl+Invio, oppure uscendo dal campo
        commit_hint = QLabel(f"{platform_support.shortcut_label('Ctrl+Return')} per applicare")
        commit_hint.setObjectName("inspectorLabel")
        commit_hint.setToolTip("Applicato anche uscendo dal campo")
        text_head.addWidget(commit_hint)
        text_box.addLayout(text_head)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setObjectName("inspectorText")
        self.text_edit.setFixedHeight(max(92, fm.lineSpacing() * 4 + 24))   # ~92 px: Diagnostica resta in vista
        self.text_edit.setPlaceholderText("Testo del sottotitolo…")
        self.text_edit.setAccessibleName("Testo del sottotitolo")
        self.text_edit.setTabChangesFocus(True)   # Tab passa al controllo successivo
        self.text_edit.textChanged.connect(self._on_text_changed_live)
        # Uscendo dal campo il testo viene confermato (mai perso in silenzio)
        self.text_edit.installEventFilter(self)
        text_box.addWidget(self.text_edit)

        # Stats testo
        stats_row = QHBoxLayout()
        self.char_count_label = QLabel("0 caratteri")
        self.char_count_label.setObjectName("inspectorStat")
        stats_row.addWidget(self.char_count_label)
        stats_row.addStretch(1)
        self.cps_label = QLabel("— CPS")
        self.cps_label.setObjectName("inspectorStat")
        stats_row.addWidget(self.cps_label)
        text_box.addLayout(stats_row)
        layout.addLayout(text_box)

        # ---- Diagnostica: linea sopra, icona + testo nel colore della gravità ----
        self._diag_sep = QFrame()
        self._diag_sep.setFrameShape(QFrame.NoFrame)
        self._diag_sep.setFixedHeight(1)
        layout.addWidget(self._diag_sep)
        diag_title = QLabel("Diagnostica")
        diag_title.setObjectName("inspectorLabel")
        layout.addWidget(diag_title)

        self._issues_box = QVBoxLayout()   # una riga (icona + testo) per problema
        self._issues_box.setSpacing(6)
        layout.addLayout(self._issues_box)
        self.issues_label = QLabel("—")    # stato senza problemi / nessuna selezione
        self.issues_label.setWordWrap(True)
        self.issues_label.setObjectName("muted")
        layout.addWidget(self.issues_label)
        self._issue_rows: list = []

        layout.addStretch(1)

        # Ordine di tab: Inizio → Fine → spostamenti → Testo
        chain = [self.start_spin, self.end_spin, *self._shift_buttons, self.text_edit]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

        # Stato iniziale: tutto disabilitato
        self._set_enabled(False)

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    # ---- Tema ----
    @staticmethod
    def _mono_font(px: int):
        from PySide6.QtGui import QFont
        f = QFont(platform_support.mono_font_family())
        f.setPixelSize(px)
        return f

    def _apply_palette(self):
        c = theme.c
        mono = theme.FONT_MONO
        self.setStyleSheet(
            f"QWidget#inspector, QWidget#inspectorContent {{ background: {c('panel')}; }}"
            "QScrollArea { background: transparent; border: none; }"
            "QLabel { background: transparent; border: none; }"
            f"QLabel#inspectorLabel {{ color: {c('label')}; font-size: 11px; font-weight: 500; }}"
            f"QLabel#inspectorValue {{ color: {c('text')}; font-family: {mono}; font-size: 13px; }}"
            f"QLabel#inspectorCounter {{ color: {c('dim')}; font-family: {mono}; font-size: 13px; }}"
            f"QLabel#inspectorStat {{ color: {c('dim')}; font-family: {mono}; font-size: 12px; }}"
            f"QDoubleSpinBox {{ font-family: {mono}; font-size: 13px; min-height: 26px;"
            f" padding: 0 8px; background: {c('bg')}; border: 1px solid {c('line')};"
            " border-radius: 4px; }"
            f"QDoubleSpinBox:focus {{ border-color: {c('focus')}; }}"
            f"QPushButton#inspectorShift {{ font-family: {mono}; font-size: 12px; padding: 0 4px;"
            f" color: {c('text')}; }}"
            f"QPlainTextEdit#inspectorText {{ font-size: 14px; padding: 8px 10px; }}"
        )
        self._diag_sep.setStyleSheet(f"background-color: {c('line')}; border: none;")

    def _on_theme_changed(self, _name=None):
        self._apply_palette()
        self._refresh()

    # ---- Utilities UI ----
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
            self.header.setText("Nessuna selezione")
            self.counter_label.setText(f"{total} sottotitoli")
            self._set_enabled(False)
            self._updating = True
            self.start_spin.setValue(0)
            self.end_spin.setValue(0)
            self.text_edit.setPlainText("")
            self._updating = False
            self.dur_label.setText("—")
            self.char_count_label.setText("0 caratteri")
            self.cps_label.setText("— CPS")
            self._clear_issue_rows()
            self.issues_label.setText("—")
            self.issues_label.setVisible(True)
            return

        sub = self._model.subtitle_at(self._current_row)
        if sub is None:
            return

        total = self._model.rowCount()
        self.header.setText(f"Sottotitolo {self._current_row + 1}")
        self.counter_label.setText(f"{self._current_row + 1} / {total}")
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

        self.dur_label.setText(f"{sub.duration:.2f} s")
        self._update_text_stats(sub.text, sub.duration)
        self._update_issues()

    def _update_text_stats(self, text: str, duration: float):
        txt = text.strip()
        n = len(txt)
        self.char_count_label.setText(f"{n} caratteri · {len(txt.split()) if txt else 0} parole")
        color = theme.c("dim")
        if duration > 0 and n > 0:
            cps = n / duration
            self.cps_label.setText(f"{cps:.1f} CPS")
            limits = active_readability()
            if cps > limits.max_cps:
                color = theme.c("err")
            elif cps > limits.warn_cps:
                color = theme.c("warn")
        else:
            self.cps_label.setText("— CPS")
        self.cps_label.setStyleSheet(f"color: {color};")

    def _clear_issue_rows(self):
        for row in self._issue_rows:
            self._issues_box.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._issue_rows = []

    def _add_issue_row(self, text: str, token: str):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(icons.pixmap("alert", theme.qcolor(token), 16))
        icon.setFixedSize(16, 16)
        lay.addWidget(icon, 0, Qt.AlignTop)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {theme.c(token)};")
        lay.addWidget(lbl, 1)
        self._issues_box.addWidget(row)
        self._issue_rows.append(row)

    def _update_issues(self):
        if self._model is None or self._current_row is None:
            return
        self._clear_issue_rows()
        issues = self._model.row_issues(self._current_row)
        if not issues:
            self.issues_label.setText("Nessun problema rilevato")
            self.issues_label.setStyleSheet(f"color: {theme.c('dim')};")
            self.issues_label.setVisible(True)
        else:
            self.issues_label.setText("\n".join(issues))
            self.issues_label.setVisible(False)
            sev = self._model.row_severity(self._current_row)
            token = "err" if sev == "error" else "warn"
            for i in issues:
                self._add_issue_row(i, token)

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

    def _on_shift_button(self, _checked: bool = False) -> None:
        b = self.sender()
        if b is not None:
            self._shift_both(float(b.property("shiftDelta")))

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
