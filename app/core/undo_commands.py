"""
undo_commands.py — QUndoCommand per operazioni sull'editor.

Ogni comando conosce il model e ha undo()/redo() simmetrici.
Il `command_id` abilita il merge di comandi consecutivi dello stesso tipo
(es: typing nel testo → un solo undo).
"""

from __future__ import annotations
from dataclasses import replace

from PySide6.QtGui import QUndoCommand

from core.subtitle_model import Subtitle
from core.subtitle_table_model import (
    SubtitleTableModel, COL_START, COL_END, COL_TEXT
)


# Tutti i merge ID devono essere positivi e distinti per tipo di operazione
CMD_EDIT_TEXT  = 1001
CMD_EDIT_START = 1002
CMD_EDIT_END   = 1003


class EditFieldCommand(QUndoCommand):
    """Modifica singola cella (testo/start/end) con merge di edit consecutivi."""

    def __init__(self, model: SubtitleTableModel, row: int, col: int,
                 old_value, new_value, description: str):
        super().__init__(description)
        self.model = model
        self.row = row
        self.col = col
        self.old_value = old_value
        self.new_value = new_value

    def id(self) -> int:
        if self.col == COL_TEXT:
            return CMD_EDIT_TEXT
        if self.col == COL_START:
            return CMD_EDIT_START
        if self.col == COL_END:
            return CMD_EDIT_END
        return -1

    def mergeWith(self, other: QUndoCommand) -> bool:
        # Si uniscono solo edit di testo (typing continuo): ogni modifica di
        # start/end deve restare un passo di undo separato.
        if not isinstance(other, EditFieldCommand):
            return False
        if self.col != COL_TEXT or other.col != COL_TEXT:
            return False
        if other.row != self.row or other.col != self.col:
            return False
        # Assorbi il nuovo valore mantenendo l'old originale
        self.new_value = other.new_value
        return True

    def redo(self):
        self.model.apply_edit_raw(self.row, self.col, self.new_value)

    def undo(self):
        self.model.apply_edit_raw(self.row, self.col, self.old_value)


class DeleteSubtitleCommand(QUndoCommand):
    """Elimina una o più righe (selezione multipla)."""

    def __init__(self, model: SubtitleTableModel, rows: list[int]):
        super().__init__(f"Elimina {len(rows)} sottotitolo/i")
        self.model = model
        # Conserva riga + oggetto (copia) per poterli ripristinare
        rows_sorted = sorted(set(rows))
        self._backup = [(r, replace(model.subtitle_at(r))) for r in rows_sorted
                        if model.subtitle_at(r) is not None]

    def redo(self):
        # Rimuovi dall'alto verso il basso: rimuovi prima gli indici più alti
        for r, _sub in sorted(self._backup, key=lambda x: -x[0]):
            self.model.remove_subtitle(r)

    def undo(self):
        # Reinserisci dal basso verso l'alto
        for r, sub in sorted(self._backup, key=lambda x: x[0]):
            self.model.insert_subtitle(r, replace(sub))


class SplitSubtitleCommand(QUndoCommand):
    """
    Divide un sottotitolo in due a una posizione del testo (split_pos).
    Il tempo viene diviso proporzionalmente alla lunghezza del testo.
    """

    def __init__(self, model: SubtitleTableModel, row: int, split_pos: int):
        super().__init__("Dividi sottotitolo")
        self.model = model
        self.row = row
        self.split_pos = split_pos
        sub = model.subtitle_at(row)
        self._original = replace(sub) if sub else None

    def redo(self):
        orig = self._original
        if orig is None:
            return
        text = orig.text
        pos = max(1, min(len(text) - 1, self.split_pos))

        # Aggiusta pos al confine di parola più vicino per non spezzare una parola.
        # Cerca uno spazio a sinistra e uno a destra, prende quello più vicino.
        left_space  = text.rfind(" ", 0, pos)    # ultimo spazio prima di pos
        right_space = text.find(" ", pos)         # primo spazio dopo pos

        if left_space == -1 and right_space == -1:
            # Nessuno spazio nel testo → non si può dividere
            return

        if left_space == -1:
            pos = right_space
        elif right_space == -1:
            pos = left_space
        else:
            # Prende il confine più vicino a pos originale
            if (pos - left_space) <= (right_space - pos):
                pos = left_space
            else:
                pos = right_space

        # pos è ora sull'indice dello spazio: left finisce qui, right inizia dopo
        left_text  = text[:pos].rstrip()
        right_text = text[pos:].lstrip()

        if not left_text or not right_text:
            # Split non produce 2 testi validi → no-op
            return

        # Tempo proporzionale alla lunghezza
        total = len(text.strip()) or 1
        ratio = len(left_text) / total
        duration = orig.end - orig.start
        mid_time = orig.start + duration * ratio

        # Testo non ancora modificato: ogni metà resta "di Whisper" (parole incerte
        # evidenziate); altrimenti entrambe tengono la trascrizione intera (ortografia).
        fresh = orig.unedited
        left = Subtitle(start=orig.start, end=mid_time, text=left_text,
                        confidence=orig.confidence,
                        asr_text=left_text if fresh else orig.asr_text,
                        uncertain=orig.uncertain)
        right = Subtitle(start=mid_time, end=orig.end, text=right_text,
                         confidence=orig.confidence,
                         asr_text=right_text if fresh else orig.asr_text,
                         uncertain=orig.uncertain)

        self.model.replace_subtitle(self.row, left)
        self.model.insert_subtitle(self.row + 1, right)

    def undo(self):
        if self._original is None:
            return
        # Rimuovi la riga inserita e ripristina l'originale
        self.model.remove_subtitle(self.row + 1)
        self.model.replace_subtitle(self.row, replace(self._original))


class MergeWithNextCommand(QUndoCommand):
    """Unisce la riga `row` con la riga `row+1` in un unico sottotitolo."""

    def __init__(self, model: SubtitleTableModel, row: int):
        super().__init__("Unisci con successivo")
        self.model = model
        self.row = row
        cur = model.subtitle_at(row)
        nxt = model.subtitle_at(row + 1)
        self._current = replace(cur) if cur else None
        self._next = replace(nxt) if nxt else None

    def redo(self):
        if self._current is None or self._next is None:
            return
        merged_text = (self._current.text + " " + self._next.text).strip()
        merged = Subtitle(
            start=self._current.start,
            end=self._next.end,
            text=merged_text,
            confidence=min(self._current.confidence, self._next.confidence),
            asr_text=" ".join(t for t in (self._current.asr_text, self._next.asr_text) if t),
            uncertain=self._current.uncertain + tuple(
                w for w in self._next.uncertain if w not in self._current.uncertain),
        )
        self.model.remove_subtitle(self.row + 1)
        self.model.replace_subtitle(self.row, merged)

    def undo(self):
        if self._current is None or self._next is None:
            return
        self.model.replace_subtitle(self.row, replace(self._current))
        self.model.insert_subtitle(self.row + 1, replace(self._next))


class ReplaceAllCommand(QUndoCommand):
    """Find & Replace su tutti i sottotitoli. Atomico: un solo undo."""

    def __init__(self, model: SubtitleTableModel,
                 replacements: list[tuple[int, str, str]]):
        """
        replacements: lista di (row, old_text, new_text) — già calcolata.
        """
        super().__init__(f"Sostituisci {len(replacements)} occorrenze")
        self.model = model
        self.replacements = replacements

    def redo(self):
        for row, _old, new in self.replacements:
            self.model.apply_edit_raw(row, COL_TEXT, new)

    def undo(self):
        for row, old, _new in self.replacements:
            self.model.apply_edit_raw(row, COL_TEXT, old)
