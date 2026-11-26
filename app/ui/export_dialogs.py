"""
export_dialogs.py — Dialog condivisi dall'esportazione: dove salvare e cosa fare se il
file esiste già. Formati e scrittura in ``core.export_formats``.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from core.export_formats import ExportFormat, with_ext
from core.srt_io import unique_output_path


def resolve_existing(parent: QWidget, path: str) -> str:
    """Il file esiste già: chiede se sostituirlo o salvare con un nuovo nome.

    Ritorna il percorso da usare, "" se l'utente annulla.
    """
    box = QMessageBox(parent)
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


def ask_save_path(parent: QWidget, fmt: ExportFormat, title: str, initial: str = "") -> str:
    """Dialog di salvataggio per ``fmt``; "" se annullato.

    Il dialog chiede già di sostituire il file che l'utente sceglie; se invece l'estensione
    va aggiunta dopo, il file con il nome finale non l'ha visto nessuno: si chiede qui.
    """
    path, _ = QFileDialog.getSaveFileName(parent, title, initial, fmt.file_filter)
    if not path:
        return ""
    final = with_ext(path, fmt.ext)
    if final != path and os.path.exists(final):
        return resolve_existing(parent, final)
    return final
