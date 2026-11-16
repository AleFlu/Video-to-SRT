"""
find_replace_dialog.py — Find & Replace per i sottotitoli.

Dialog compatto (mockup "Bianco e nero"): campi Trova / Sostituisci, tre interruttori
bordati (Aa Maiuscole/minuscole, W Parole intere, .* Regex) e i pulsanti in fondo.
Il contatore dei risultati sta DENTRO il campo "Trova", a destra, in forma breve
("1 di 3", "3 risultati", "Nessun risultato"); gli errori (regex o sostituzione non
valide) compaiono nello stesso punto, nel colore d'errore.

Il Find ("Next") emette `match_found(row)` che il MainWindow usa per selezionare
la riga corrispondente nella tabella.
Il Replace All emette `replace_all_requested(replacements)` con la lista di
(row, old_text, new_text) già calcolata — il MainWindow crea un ReplaceAllCommand.
"""

from __future__ import annotations
import re
from typing import Optional

from PySide6.QtCore import Qt, Signal, QRect, QSize
from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QFrame,
)

from core.subtitle_table_model import SubtitleTableModel
from ui import theme
import platform_support

_LABEL_COL = 84   # larghezza della colonna delle etichette (mockup)


def format_count(total: int, position: int = 0) -> str:
    """
    Testo breve del contatore dentro il campo Trova: "1 di 3" mentre si naviga
    (`position` = posizione 1-based del risultato corrente), "3 risultati" dopo una
    ricerca senza navigazione, "Nessun risultato" se non c'è nulla.
    """
    if total <= 0:
        return "Nessun risultato"
    if position > 0:
        return f"{position} di {total}"
    return f"{total} risultat{'o' if total == 1 else 'i'}"


class _CounterField(QLineEdit):
    """Campo di testo con un'etichetta a destra, dentro il bordo (contatore dei risultati)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.counter = QLabel("", self)
        self.counter.setObjectName("findCounter")
        self.counter.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.counter.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def set_counter(self, text: str, token: str = "dim") -> None:
        self.counter.setText(text)
        self.counter.setStyleSheet(
            f"color: {theme.c(token)}; background: transparent; border: none;"
            f" font-family: {theme.FONT_MONO}; font-size: 11px;"
        )
        w = self.counter.sizeHint().width() if text else 0
        # il testo digitato non deve finire sotto il contatore
        self.setTextMargins(0, 0, w + 8 if text else 0, 0)
        self._place()

    def _place(self) -> None:
        w = self.counter.sizeHint().width()
        self.counter.setGeometry(self.width() - w - 9, 0, w, self.height())

    def resizeEvent(self, event):  # noqa: N802 (override Qt)
        super().resizeEvent(event)
        self._place()


class _OptionToggle(QPushButton):
    """Interruttore bordato con prefisso mono ("Aa", "W", ".*"): acceso = `sel` + bordo accento."""

    def __init__(self, prefix: str, label: str, parent=None):
        super().__init__(label, parent)
        self._prefix = prefix
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(label)
        self.setFixedHeight(28)

    def _fonts(self):
        mono = QFont(platform_support.mono_font_family())
        mono.setPixelSize(13)
        ui = QFont(platform_support.ui_font_family())
        ui.setPixelSize(13)
        return mono, ui

    def sizeHint(self):  # noqa: N802 (override Qt)
        mono, ui = self._fonts()
        w = (QFontMetrics(mono).horizontalAdvance(self._prefix) + 6
             + QFontMetrics(ui).horizontalAdvance(self.text()) + 18)
        return QSize(w, 28)

    def paintEvent(self, event):  # noqa: N802 (override Qt)
        on = self.isChecked()
        enabled = self.isEnabled()
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            r = self.rect().adjusted(0, 0, -1, -1)
            if on and enabled:
                p.setBrush(theme.qcolor("sel"))
            elif self.underMouse() and enabled:
                p.setBrush(theme.qcolor("raise"))
            else:
                p.setBrush(Qt.NoBrush)
            if self.hasFocus():
                border = theme.qcolor("focus")
            elif on and enabled:
                border = theme.qcolor("acc")
            else:
                border = theme.qcolor("line")
            p.setPen(border)
            p.drawRoundedRect(r, 4, 4)
            p.setRenderHint(QPainter.Antialiasing, False)
            color = theme.qcolor("text" if enabled else "faint")
            mono, ui = self._fonts()
            p.setPen(color)
            p.setFont(mono)
            pw = QFontMetrics(mono).horizontalAdvance(self._prefix)
            p.drawText(QRect(9, 0, pw, self.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       self._prefix)
            p.setFont(ui)
            p.drawText(QRect(9 + pw + 6, 0, self.width() - pw - 24, self.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, self.text())
        finally:
            p.end()


class FindReplaceDialog(QDialog):
    match_found = Signal(int)                   # row
    replace_all_requested = Signal(list)        # list[(row, old, new)]

    def __init__(self, model: SubtitleTableModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._last_match_row = -1
        self._nav_row = -1   # solo visualizzazione: riga raggiunta con "Trova successivo"

        self.setWindowTitle("Trova e sostituisci")
        self.setModal(False)
        self.setMinimumWidth(500)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Corpo: griglia etichetta (84 px) + campo ──────────────────────────
        body = QGridLayout()
        body.setContentsMargins(14, 14, 14, 14)
        body.setHorizontalSpacing(10)
        body.setVerticalSpacing(10)
        body.setColumnMinimumWidth(0, _LABEL_COL)
        body.setColumnStretch(1, 1)

        find_lbl = QLabel("Trova")
        find_lbl.setObjectName("findLabel")
        body.addWidget(find_lbl, 0, 0)
        self.find_edit = _CounterField()
        self.find_edit.setAccessibleName("Testo da cercare")
        find_lbl.setBuddy(self.find_edit)
        self.find_edit.setPlaceholderText("Testo da cercare…")
        self.find_edit.textChanged.connect(self._on_query_changed)
        self.find_edit.returnPressed.connect(self._find_next)
        body.addWidget(self.find_edit, 0, 1)
        # Il contatore dei risultati vive dentro il campo Trova (etichetta di stato)
        self.count_label = self.find_edit.counter

        repl_lbl = QLabel("Sostituisci")
        repl_lbl.setObjectName("findLabel")
        body.addWidget(repl_lbl, 1, 0)
        self.replace_edit = QLineEdit()
        self.replace_edit.setAccessibleName("Testo sostitutivo")
        repl_lbl.setBuddy(self.replace_edit)
        self.replace_edit.setPlaceholderText("Sostituisci con…")
        body.addWidget(self.replace_edit, 1, 1)

        # Opzioni: interruttori bordati con prefisso mono
        opts = QHBoxLayout()
        opts.setSpacing(6)
        self.case_check = _OptionToggle("Aa", "Maiuscole/minuscole")
        self.word_check = _OptionToggle("W", "Parole intere")
        self.regex_check = _OptionToggle(".*", "Regex")
        for cb in (self.case_check, self.word_check, self.regex_check):
            cb.toggled.connect(self._on_query_changed)
            opts.addWidget(cb)
        # "Parole intere" non si applica in modalità regex: lo disabilitiamo
        self.regex_check.toggled.connect(self._on_regex_toggled)
        opts.addStretch(1)
        body.addLayout(opts, 2, 1)
        root.addLayout(body)

        # ── Piede: linea sopra, pulsanti a destra ─────────────────────────────
        self._footer = QFrame()
        self._footer.setObjectName("findFooter")
        btn_row = QHBoxLayout(self._footer)
        btn_row.setContentsMargins(14, 10, 14, 10)
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        close_btn = QPushButton("Chiudi")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        self.replace_btn = QPushButton("Sostituisci")
        self.replace_btn.clicked.connect(self._replace_current)
        btn_row.addWidget(self.replace_btn)

        self.replace_all_btn = QPushButton("Sostituisci tutto")
        self.replace_all_btn.clicked.connect(self._replace_all)
        btn_row.addWidget(self.replace_all_btn)

        self.find_next_btn = QPushButton("Trova successivo  ↵")
        self.find_next_btn.setObjectName("primary")
        self.find_next_btn.clicked.connect(self._find_next)
        btn_row.addWidget(self.find_next_btn)
        root.addWidget(self._footer)

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il dialog viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

        # Ordine di tab: campi → opzioni → azioni
        chain = [self.find_edit, self.replace_edit, self.case_check, self.word_check,
                 self.regex_check, close_btn, self.replace_btn,
                 self.replace_all_btn, self.find_next_btn]
        for a, b in zip(chain, chain[1:]):
            self.setTabOrder(a, b)

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

    def _replacement(self):
        """
        Sostituzione da passare a `re.sub`: in modalità regex è un template
        (con \\1, \\g<nome>…); altrimenti è testo letterale (es. "C:\\nuovo").
        """
        text = self.replace_edit.text()
        if self.regex_check.isChecked():
            return text
        return lambda _m: text

    # ---- Count ----
    def _on_regex_toggled(self, on: bool) -> None:
        """"Parole intere" non ha senso in modalità regex."""
        self.word_check.setEnabled(not on)

    def _on_query_changed(self, *_):
        """Cambia testo o opzione: la navigazione ricomincia, il contatore torna a "N risultati"."""
        self._nav_row = -1
        self._update_count()

    def _matching_rows(self, pat) -> list:
        return [i for i, sub in enumerate(self._model.subtitles()) if pat.search(sub.text)]

    def _update_count(self):
        pat = self._build_pattern()
        if pat is None:
            invalid = bool(self.find_edit.text())
            self._set_counter("Pattern non valido" if invalid else "", "err")
            return

        rows = self._matching_rows(pat)
        position = rows.index(self._nav_row) + 1 if self._nav_row in rows else 0
        text = format_count(len(rows), position)
        self._set_counter(text, "dim" if rows else "err")

    def _set_counter(self, text: str, token: str):
        """Mostra il testo breve nel campo; il tooltip/nome accessibile riporta il dettaglio."""
        self.find_edit.set_counter(text, token)
        self.count_label.setAccessibleName(text)
        self.count_label.setToolTip(self._detail_text(text))

    def _detail_text(self, short: str) -> str:
        """Descrizione estesa (come l'ex riga a sé): occorrenze totali e sottotitoli."""
        pat = self._build_pattern()
        if pat is None or not short or short == "Nessun risultato":
            return short
        total_matches = total_rows = 0
        for sub in self._model.subtitles():
            n = len(pat.findall(sub.text))
            if n:
                total_rows += 1
                total_matches += n
        return f"{total_matches} occorrenze in {total_rows} sottotitoli"

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
                self._nav_row = r
                self._update_count()
                self.match_found.emit(r)
                return
        self._last_match_row = -1
        self._nav_row = -1

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
            new_text = pat.sub(self._replacement(), sub.text, count=1)
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
        replacement = self._replacement()
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
        c = theme.c
        self.setStyleSheet(
            f"QDialog {{ background: {c('panel')}; }}"
            "QLabel#findLabel { background: transparent;"
            f" color: {c('label')}; font-size: 11px; font-weight: 500; }}"
            f"QLineEdit {{ background: {c('panel')}; }}"
            f"QFrame#findFooter {{ background: {c('panel')}; border: none;"
            f" border-top: 1px solid {c('line')}; }}"
            "QPushButton { min-height: 26px; }"
            "QPushButton#primary { min-height: 26px; padding: 0 12px; }"
        )
        self._set_counter(self.count_label.text(), self._counter_token())

    def _counter_token(self) -> str:
        return "err" if self.count_label.text() in ("Nessun risultato", "Pattern non valido",
                                                      "Testo di sostituzione non valido") \
            else "dim"

    def _show_replace_error(self):
        """Backreference invalida (es. \\1 senza gruppo) nel testo di sostituzione."""
        self._set_counter("Testo di sostituzione non valido", "err")

    # ---- Focus ----
    def focus_find(self):
        self.find_edit.setFocus()
        self.find_edit.selectAll()
