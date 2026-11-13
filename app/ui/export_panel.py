"""
export_panel.py — Esportazione sottotitoli in più formati (C3).

Formati supportati: SRT, VTT, TXT, ASS, V2SRT (progetto).
Può essere aperto come finestra standalone (da MainWindow) o come widget.
"""

from __future__ import annotations
import os
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QLineEdit, QFileDialog, QMessageBox, QComboBox
)

import platform_support
from core.srt_io import (
    write_srt, write_vtt, write_txt, write_ass, default_output_for, unique_output_path,
)
from core.v2srt_io import save_project


# Formato → (etichetta, estensione, filtro dialog)
_FORMATS = [
    ("SRT — SubRip",          ".srt",   "SubRip SRT (*.srt)"),
    ("VTT — WebVTT",          ".vtt",   "WebVTT (*.vtt)"),
    ("TXT — Testo semplice",  ".txt",   "Testo (*.txt)"),
    ("ASS — Advanced Sub",    ".ass",   "ASS (*.ass)"),
    ("V2SRT — Progetto",      ".v2srt", "Progetto V2SRT (*.v2srt)"),
]


class ExportPanel(QWidget):
    exported = Signal(str)   # path del file salvato

    def __init__(self, get_project_callable, parent=None):
        super().__init__(parent)
        self.setObjectName("contentPanel")
        self._get_project = get_project_callable
        self._last_saved: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.setSpacing(14)

        title = QLabel("Esporta sottotitoli")
        title.setObjectName("title")
        outer.addWidget(title)

        sub = QLabel("Scegli il formato e il percorso di destinazione.")
        sub.setObjectName("subtitle")
        outer.addWidget(sub)
        outer.addSpacing(6)

        # ---- Card formato ----
        card_fmt = QFrame()
        card_fmt.setObjectName("card")
        fl = QVBoxLayout(card_fmt)
        fl.setContentsMargins(18, 14, 18, 14)
        fl.setSpacing(8)
        fl.addWidget(self._section("Formato"))

        self.fmt_combo = QComboBox()
        self.fmt_combo.setAccessibleName("Formato di esportazione")
        for label, ext, _ in _FORMATS:
            self.fmt_combo.addItem(label, ext)
        self.fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        fl.addWidget(self.fmt_combo)

        fmt_desc = {
            ".srt":   "Compatibile con tutti i player e piattaforme.",
            ".vtt":   "Per il web, YouTube, HTML5 video.",
            ".txt":   "Solo testo, senza timing.",
            ".ass":   "Styling avanzato per video amatoriali/anime.",
            ".v2srt": "Progetto Video→SRT: riapri per continuare a editare.",
        }
        self._fmt_desc = fmt_desc
        self.fmt_hint = QLabel(fmt_desc[".srt"])
        self.fmt_hint.setObjectName("muted")
        self.fmt_hint.setStyleSheet("font-size: 11px;")
        fl.addWidget(self.fmt_hint)
        outer.addWidget(card_fmt)

        # ---- Card percorso ----
        card_path = QFrame()
        card_path.setObjectName("card")
        pl = QVBoxLayout(card_path)
        pl.setContentsMargins(18, 14, 18, 14)
        pl.setSpacing(8)
        pl.addWidget(self._section("Percorso di destinazione"))

        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Il file verrà salvato qui…")
        self.path_edit.setAccessibleName("Percorso del file da salvare")
        self.path_edit.textEdited.connect(self._on_path_edited)
        browse = QPushButton("Sfoglia…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        pl.addLayout(row)
        outer.addWidget(card_path)

        # ---- Bottone salva ----
        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Salva")
        self.save_btn.setDefault(True)
        self.save_btn.setObjectName("primary")
        self.save_btn.setMinimumHeight(40)
        self.save_btn.clicked.connect(self._save)
        btn_row.addStretch(1)
        btn_row.addWidget(self.save_btn)
        outer.addLayout(btn_row)

        # ---- Risultato ----
        self.result_card = QFrame()
        self.result_card.setObjectName("card")
        self.result_card.setVisible(False)
        rl = QVBoxLayout(self.result_card)
        rl.setContentsMargins(18, 14, 18, 14)
        rl.setSpacing(6)
        self.result_lbl = QLabel("")
        self.result_lbl.setObjectName("success")
        rl.addWidget(self.result_lbl)
        self.result_detail = QLabel("")
        self.result_detail.setObjectName("muted")
        self.result_detail.setWordWrap(True)
        rl.addWidget(self.result_detail)

        open_row = QHBoxLayout()
        self.open_folder_btn = QPushButton("Apri nella cartella")
        self.open_folder_btn.clicked.connect(self._open_folder)
        open_row.addWidget(self.open_folder_btn)
        open_row.addStretch(1)
        rl.addLayout(open_row)
        outer.addWidget(self.result_card)
        outer.addStretch(1)

        # Percorso proposto automaticamente vs scelto dall'utente (per questo progetto)
        self._path_is_auto = True
        self._path_source = None

    # ---- Helpers UI ----

    def _section(self, txt: str) -> QLabel:
        lbl = QLabel(txt)
        lbl.setObjectName("sectionTitle")
        return lbl

    def _current_ext(self) -> str:
        return self.fmt_combo.currentData() or ".srt"

    def _current_filter(self) -> str:
        idx = self.fmt_combo.currentIndex()
        _, _, flt = _FORMATS[idx]
        return flt + ";;Tutti i file (*.*)"

    # ---- Aggiornamento path al cambio formato ----

    def _on_format_changed(self, _idx: int):
        ext = self._current_ext()
        self.fmt_hint.setText(self._fmt_desc.get(ext, ""))
        # Aggiorna estensione nel path se già presente
        current = self.path_edit.text().strip()
        if current:
            p = Path(current)
            self.path_edit.setText(str(p.with_suffix(ext)))

    # ---- API pubblica ----

    def _on_path_edited(self, _text: str):
        self._path_is_auto = False

    def refresh_from_project(self):
        """
        Allinea il pannello al progetto corrente. Il percorso viene ricalcolato
        dal sorgente ogni volta che il progetto (sorgente) cambia, o se non è stato
        scelto dall'utente: mai un percorso rimasto da un file precedente.
        """
        proj = self._get_project()
        source = proj.source_path if proj else ""
        if source != self._path_source or self._path_is_auto:
            self._path_source = source
            self._path_is_auto = True
            if source:
                base = default_output_for(source)
                self.path_edit.setText(str(Path(base).with_suffix(self._current_ext())))
            else:
                self.path_edit.clear()
        self.save_btn.setEnabled(bool(proj and proj.subtitles))
        self.result_card.setVisible(False)

    # ---- Browse ----

    def _browse(self):
        proj = self._get_project()
        ext = self._current_ext()
        initial = self.path_edit.text().strip()
        if not initial and proj and proj.source_path:
            initial = str(Path(default_output_for(proj.source_path)).with_suffix(ext))
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva sottotitoli", initial, self._current_filter()
        )
        if path:
            if not path.lower().endswith(ext):
                path += ext
            self.path_edit.setText(path)
            self._path_is_auto = False

    # ---- Salvataggio ----

    def _save(self):
        proj = self._get_project()
        if not proj or not proj.subtitles:
            QMessageBox.warning(self, "Nessun sottotitolo",
                                "Non ci sono sottotitoli da esportare.")
            return

        ext = self._current_ext()
        path = self.path_edit.text().strip()
        if not path:
            if proj.source_path:
                path = str(Path(default_output_for(proj.source_path)).with_suffix(ext))
            else:
                self._browse()
                path = self.path_edit.text().strip()
                if not path:
                    return

        if not path.lower().endswith(ext):
            path += ext

        if os.path.exists(path):
            path = self._resolve_existing(path)
            if not path:
                return

        try:
            self._write(proj, path, ext)
            self._last_saved = path
            self._show_result(path)
            self.exported.emit(path)
        except Exception as e:
            QMessageBox.critical(self, "Errore salvataggio",
                                 f"Impossibile salvare il file:\n{e}")

    def _resolve_existing(self, path: str) -> str:
        """Il file esiste già: chiede se sovrascriverlo o salvare con un nuovo nome."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("File già esistente")
        box.setText(f"«{Path(path).name}» esiste già.")
        box.setInformativeText("Vuoi sostituirlo o salvare una copia con un nuovo nome?")
        overwrite = box.addButton("Sostituisci", QMessageBox.DestructiveRole)
        copy = box.addButton("Salva con nuovo nome", QMessageBox.AcceptRole)
        box.addButton("Annulla", QMessageBox.RejectRole)
        box.setDefaultButton(copy)
        box.exec()
        clicked = box.clickedButton()
        if clicked is overwrite:
            return path
        if clicked is copy:
            return unique_output_path(path)
        return ""

    def _write(self, proj, path: str, ext: str):
        subs = proj.subtitles
        if ext == ".srt":
            write_srt(subs, path)
        elif ext == ".vtt":
            write_vtt(subs, path)
        elif ext == ".txt":
            write_txt(subs, path)
        elif ext == ".ass":
            write_ass(subs, path, title=Path(proj.source_path or path).stem)
        elif ext == ".v2srt":
            save_project(proj, path)
        else:
            write_srt(subs, path)

    # ---- Risultato ----

    def _show_result(self, path: str):
        self.result_card.setVisible(True)
        self.result_lbl.setText(f"Salvato: {Path(path).name}")
        try:
            size = os.path.getsize(path)
            size_str = f"{size/1024:.1f} KB" if size < 1024**2 else f"{size/1024**2:.2f} MB"
            self.result_detail.setText(f"{size_str}  ·  {path}")
        except OSError:
            self.result_detail.setText(path)

    def _open_folder(self):
        if not self._last_saved or not os.path.exists(self._last_saved):
            return
        platform_support.reveal_in_file_manager(self._last_saved)
