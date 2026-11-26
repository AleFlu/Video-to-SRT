"""
export_panel.py — Esportazione sottotitoli in più formati (C3).

Formati supportati: SRT, VTT, TXT, ASS, V2SRT (progetto).
Può essere aperto come finestra standalone (da MainWindow) o come widget.
Stile "Bianco e nero": niente card, sezioni con etichetta, campi e pulsanti di tema.
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
from ui import theme
from core import export_formats
from core.export_formats import BY_EXT, FORMATS, with_ext
from core.srt_io import default_output_for
from ui.export_dialogs import resolve_existing


class ExportPanel(QWidget):
    exported = Signal(str)   # path del file salvato

    def __init__(self, get_project_callable, parent=None):
        super().__init__(parent)
        self.setObjectName("contentPanel")
        self._get_project = get_project_callable
        self._last_saved: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 28, 40, 28)
        outer.setSpacing(14)

        title = QLabel("Esporta sottotitoli")
        title.setObjectName("title")
        outer.addWidget(title)

        sub = QLabel("Scegli il formato e il percorso di destinazione.")
        sub.setObjectName("homeSub")
        outer.addWidget(sub)
        outer.addSpacing(6)

        # ---- Formato ----
        outer.addWidget(self._section("Formato"))
        self.fmt_combo = QComboBox()
        self.fmt_combo.setAccessibleName("Formato di esportazione")
        for fmt in FORMATS:
            self.fmt_combo.addItem(fmt.label, fmt.ext)
        self.fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        outer.addWidget(self.fmt_combo)

        self.fmt_hint = QLabel(FORMATS[0].hint)
        self.fmt_hint.setObjectName("exportPanelHint")
        outer.addWidget(self.fmt_hint)
        outer.addSpacing(8)

        # ---- Percorso ----
        outer.addWidget(self._section("Percorso di destinazione"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Il file verrà salvato qui…")
        self.path_edit.setAccessibleName("Percorso del file da salvare")
        self.path_edit.textEdited.connect(self._on_path_edited)
        browse = QPushButton("Sfoglia…")
        browse.setObjectName("secondary")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        outer.addLayout(row)

        # ---- Bottone salva ----
        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Salva")
        self.save_btn.setDefault(True)
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._save)
        btn_row.addStretch(1)
        btn_row.addWidget(self.save_btn)
        outer.addLayout(btn_row)

        # ---- Risultato (linea sopra, niente card) ----
        self.result_card = QFrame()
        self.result_card.setObjectName("exportPanelResult")
        self.result_card.setVisible(False)
        rl = QVBoxLayout(self.result_card)
        rl.setContentsMargins(0, 14, 0, 0)
        rl.setSpacing(6)
        self.result_lbl = QLabel("")
        self.result_lbl.setObjectName("success")
        rl.addWidget(self.result_lbl)
        self.result_detail = QLabel("")
        self.result_detail.setObjectName("exportPanelHint")
        self.result_detail.setWordWrap(True)
        rl.addWidget(self.result_detail)

        open_row = QHBoxLayout()
        self.open_folder_btn = QPushButton("Apri nella cartella")
        self.open_folder_btn.setObjectName("secondary")
        self.open_folder_btn.clicked.connect(self._open_folder)
        open_row.addWidget(self.open_folder_btn)
        open_row.addStretch(1)
        rl.addLayout(open_row)
        outer.addWidget(self.result_card)
        outer.addStretch(1)

        self._apply_palette()
        # Metodo bound (non lambda): si auto-disconnette quando il widget viene distrutto
        theme.MANAGER.theme_changed.connect(self._apply_palette)

        # Percorso proposto automaticamente vs scelto dall'utente (per questo progetto)
        self._path_is_auto = True
        self._path_source = None
        # Percorso scelto nel QFileDialog (che ha già chiesto di sovrascrivere)
        self._dialog_confirmed_path = ""

    # ---- Helpers UI ----

    def _section(self, txt: str) -> QLabel:
        lbl = QLabel(txt)
        lbl.setObjectName("exportPanelSection")
        return lbl

    def _apply_palette(self, _name=None):
        c = theme.c
        self.setStyleSheet(
            "QLabel { background: transparent; }"
            f"QLabel#exportPanelSection {{ color: {c('text')}; font-size: 12px; font-weight: 600; }}"
            f"QLabel#exportPanelHint {{ color: {c('dim')}; font-size: 12px; }}"
            f"QFrame#exportPanelResult {{ background: transparent; border: none;"
            f" border-top: 1px solid {c('line')}; }}"
        )

    def _current_ext(self) -> str:
        return self.fmt_combo.currentData() or ".srt"

    def _current_filter(self) -> str:
        return BY_EXT[self._current_ext()].file_filter + ";;Tutti i file (*.*)"

    # ---- Aggiornamento path al cambio formato ----

    def _on_format_changed(self, _idx: int):
        ext = self._current_ext()
        self.fmt_hint.setText(BY_EXT[ext].hint)
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
            # Con l'estensione già corretta il dialog ha già chiesto conferma
            self._dialog_confirmed_path = path if path.lower().endswith(ext) else ""
            self.path_edit.setText(with_ext(path, ext))
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

        path = with_ext(path, ext)
        if os.path.exists(path) and path != self._dialog_confirmed_path:
            path = resolve_existing(self, path)
            if not path:
                return

        try:
            export_formats.write(proj.subtitles, path, ext, proj.source_path, proj)
            self._last_saved = path
            self._show_result(path)
            self.exported.emit(path)
        except Exception as e:
            QMessageBox.critical(self, "Errore salvataggio",
                                 f"Impossibile salvare il file:\n{e}")

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
