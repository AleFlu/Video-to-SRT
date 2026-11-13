"""
subtitle_table_model.py — QAbstractTableModel per i sottotitoli.

Colonne:
  0: # (indice, read-only)
  1: Start (mm:ss.ms — editabile)
  2: End   (mm:ss.ms — editabile)
  3: Durata (calcolata, read-only)
  4: CPS (caratteri/secondo, read-only, warning se > 20)
  5: Testo (editabile)

Segnala come "problematici" (tint rosso/giallo) i sottotitoli che:
  - overlap col successivo
  - end <= start
  - CPS > 20 (troppo veloci da leggere)
  - durata < 0.5s
"""

from __future__ import annotations
import re
from typing import List, Optional

from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, Signal
)
from PySide6.QtGui import QColor, QBrush

from core.subtitle_model import Subtitle


# ---- Parsing timestamp ----
_TS_RE = re.compile(
    r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})[\.,](\d{1,3})\s*$"
    r"|^\s*(\d+)[\.,](\d{1,3})\s*$"              # formato "12.345" (secondi)
    r"|^\s*(\d{1,2}):(\d{1,2})[\.,](\d{1,3})\s*$"  # mm:ss.ms
)


def parse_timestamp(text: str) -> Optional[float]:
    """
    Parsa formati ammessi:
      - HH:MM:SS.mmm  /  HH:MM:SS,mmm
      - MM:SS.mmm
      - 12.345 (secondi)
      - 12,345
    Ritorna None se non parsabile.
    """
    if text is None:
        return None
    s = text.strip().replace(",", ".")

    # HH:MM:SS.mmm
    m = re.match(r"^(\d+):(\d{1,2}):(\d{1,2})\.(\d{1,3})$", s)
    if m:
        h, mnt, sec, ms = m.groups()
        ms_padded = (ms + "000")[:3]
        return int(h) * 3600 + int(mnt) * 60 + int(sec) + int(ms_padded) / 1000.0

    # MM:SS.mmm
    m = re.match(r"^(\d{1,2}):(\d{1,2})\.(\d{1,3})$", s)
    if m:
        mnt, sec, ms = m.groups()
        ms_padded = (ms + "000")[:3]
        return int(mnt) * 60 + int(sec) + int(ms_padded) / 1000.0

    # MM:SS
    m = re.match(r"^(\d{1,2}):(\d{1,2})$", s)
    if m:
        mnt, sec = m.groups()
        return int(mnt) * 60 + int(sec)

    # secondi in decimale
    try:
        return float(s)
    except ValueError:
        return None


def format_timestamp(seconds: float) -> str:
    """Formato editabile compatto: MM:SS.mmm o HH:MM:SS.mmm."""
    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{m:02d}:{s:02d}.{ms:03d}"


# ---- Colonne ----
COL_INDEX = 0
COL_START = 1
COL_END   = 2
COL_DUR   = 3
COL_CPS   = 4
COL_TEXT  = 5

COLUMN_HEADERS = ["#", "Start", "End", "Durata", "CPS", "Testo"]


# Soglie per warning
MAX_CPS = 20.0           # sottotitoli più veloci di così sono difficili da leggere
WARN_CPS = 17.0
MIN_DURATION = 0.5


class SubtitleTableModel(QAbstractTableModel):
    """Modello Qt per la lista di Subtitle. Editing + validazione + flag issues."""

    # Emesso quando i dati cambiano in modo rilevante per il salvataggio
    dataModified = Signal()

    def __init__(self, subtitles: List[Subtitle] | None = None, parent=None):
        super().__init__(parent)
        self._subs: List[Subtitle] = list(subtitles) if subtitles else []
        self._edit_handler = None  # Callable[[row, col, value], bool]

    # ---- API ----
    def subtitles(self) -> List[Subtitle]:
        return self._subs

    def set_subtitles(self, subs: List[Subtitle]):
        self.beginResetModel()
        self._subs = list(subs)
        self.endResetModel()
        self.dataModified.emit()

    def subtitle_at(self, row: int) -> Optional[Subtitle]:
        if 0 <= row < len(self._subs):
            return self._subs[row]
        return None

    def replace_subtitle(self, row: int, sub: Subtitle):
        """Sostituzione diretta, bypassando setData (usato dai QUndoCommand)."""
        if 0 <= row < len(self._subs):
            self._subs[row] = sub
            top = self.index(row, 0)
            bot = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(top, bot, [Qt.DisplayRole, Qt.EditRole])
            # La modifica può aver impattato le righe adiacenti (overlap)
            self._emit_adjacent(row)
            self.dataModified.emit()

    def insert_subtitle(self, row: int, sub: Subtitle):
        self.beginInsertRows(QModelIndex(), row, row)
        self._subs.insert(row, sub)
        self.endInsertRows()
        self._emit_adjacent(row)
        self.dataModified.emit()

    def remove_subtitle(self, row: int):
        if not (0 <= row < len(self._subs)):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        self._subs.pop(row)
        self.endRemoveRows()
        self._emit_adjacent(row)
        self.dataModified.emit()

    def _emit_adjacent(self, row: int):
        """Forza il refresh delle righe adiacenti (per overlap warnings)."""
        for r in (row - 1, row + 1):
            if 0 <= r < len(self._subs):
                top = self.index(r, 0)
                bot = self.index(r, self.columnCount() - 1)
                self.dataChanged.emit(top, bot, [Qt.BackgroundRole, Qt.ToolTipRole])

    # ---- Problems detection ----
    def row_issues(self, row: int) -> list[str]:
        """Restituisce lista di problemi per la riga (stringhe leggibili)."""
        if not (0 <= row < len(self._subs)):
            return []
        issues = []
        sub = self._subs[row]

        if sub.end <= sub.start:
            issues.append("End precede o coincide con Start")
        if sub.duration < MIN_DURATION and sub.end > sub.start:
            issues.append(f"Durata troppo breve ({sub.duration:.2f}s < {MIN_DURATION}s)")

        text_len = len(sub.text.strip())
        if sub.duration > 0 and text_len > 0:
            cps = text_len / sub.duration
            if cps > MAX_CPS:
                issues.append(f"Troppo veloce ({cps:.1f} CPS, max {MAX_CPS:.0f})")

        # Overlap col successivo
        if row + 1 < len(self._subs):
            nxt = self._subs[row + 1]
            if sub.end > nxt.start + 0.001:
                issues.append("Overlap con il sottotitolo successivo")

        if not sub.text.strip():
            issues.append("Testo vuoto")

        return issues

    def row_severity(self, row: int) -> str:
        """'error' | 'warning' | 'ok'."""
        issues = self.row_issues(row)
        if not issues:
            return "ok"
        error_keywords = ("precede", "vuoto", "Overlap")
        if any(k in "|".join(issues) for k in error_keywords):
            return "error"
        return "warning"

    # ---- QAbstractTableModel API ----
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._subs)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMN_HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return COLUMN_HEADERS[section]
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        col = index.column()
        if col in (COL_START, COL_END, COL_TEXT):
            return base | Qt.ItemIsEditable
        return base

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if not (0 <= row < len(self._subs)):
            return None
        sub = self._subs[row]

        if role in (Qt.DisplayRole, Qt.EditRole):
            if col == COL_INDEX:
                return row + 1
            if col == COL_START:
                return format_timestamp(sub.start)
            if col == COL_END:
                return format_timestamp(sub.end)
            if col == COL_DUR:
                return f"{sub.duration:.2f}s"
            if col == COL_CPS:
                t = sub.text.strip()
                if sub.duration > 0 and t:
                    return f"{len(t) / sub.duration:.1f}"
                return "—"
            if col == COL_TEXT:
                return sub.text

        if role == Qt.TextAlignmentRole:
            if col in (COL_INDEX, COL_START, COL_END, COL_DUR, COL_CPS):
                return int(Qt.AlignCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)

        if role == Qt.ForegroundRole:
            if col == COL_INDEX:
                return QBrush(QColor("#6a6a7a"))
            if col == COL_CPS:
                t = sub.text.strip()
                if sub.duration > 0 and t:
                    cps = len(t) / sub.duration
                    if cps > MAX_CPS:
                        return QBrush(QColor("#ff6b6b"))
                    if cps > WARN_CPS:
                        return QBrush(QColor("#f39c12"))

        if role == Qt.BackgroundRole:
            sev = self.row_severity(row)
            if sev == "error":
                return QBrush(QColor(231, 76, 60, 40))
            if sev == "warning":
                return QBrush(QColor(243, 156, 18, 30))

        if role == Qt.ToolTipRole:
            issues = self.row_issues(row)
            if issues:
                return "⚠️  " + "\n⚠️  ".join(issues)

        return None

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        """
        Editing diretto dal QTableView. Delega tutte le modifiche alla
        funzione `edit_handler` se settata (tipicamente: crea un QUndoCommand).
        Altrimenti applica la modifica direttamente.
        """
        if role != Qt.EditRole or not index.isValid():
            return False

        row = index.row()
        col = index.column()
        if not (0 <= row < len(self._subs)):
            return False

        if self._edit_handler is not None:
            # Lascia decidere al chiamante (QUndoStack)
            return self._edit_handler(row, col, value)

        return self._apply_edit(row, col, value)

    # ---- Edit handler injection ----
    def set_edit_handler(self, handler):
        """Registra una callback che riceve (row, col, value) e può creare QUndoCommand."""
        self._edit_handler = handler

    def apply_edit_raw(self, row: int, col: int, value) -> bool:
        """API pubblica per i QUndoCommand: scrive senza richiamare il handler."""
        return self._apply_edit(row, col, value)

    def _apply_edit(self, row: int, col: int, value) -> bool:
        sub = self._subs[row]

        if col == COL_TEXT:
            new_text = str(value).strip()
            if new_text == sub.text:
                return False
            sub.text = new_text
        elif col == COL_START:
            new_val = parse_timestamp(str(value))
            if new_val is None:
                return False
            if abs(new_val - sub.start) < 0.0005:
                return False
            sub.start = max(0.0, new_val)
        elif col == COL_END:
            new_val = parse_timestamp(str(value))
            if new_val is None:
                return False
            if abs(new_val - sub.end) < 0.0005:
                return False
            sub.end = max(0.0, new_val)
        else:
            return False

        # Refresh riga + righe adiacenti (overlap)
        top = self.index(row, 0)
        bot = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(top, bot, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])
        self._emit_adjacent(row)
        self.dataModified.emit()
        return True
