"""
result_widget.py — ResultWidget (sotto-stato 0.2 di TranscriptionTab), "Bianco e nero".

Layout (mockup Result.dc.html):
  ┌── Fascia su "panel" ───────────────────────────────────────────────┐
  │ [✓] Trascrizione completata   N sottotitoli · file   [azioni]       │
  │     (avviso "Versione modificata nell'editor", se serve)            │
  ├── Anteprima (vista virtualizzata: QTableView + model, righe 36 px) ─┤
  └─────────────────────────────────────────────────────────────────────┘

L'anteprima usa un modello Qt: anche con migliaia di segmenti si creano solo
le righe visibili (nessun widget per segmento).

Tema chiaro/scuro: colori da theme.c(), ri-applicati su theme_changed.
"""

from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSizePolicy, QTableView, QHeaderView, QAbstractItemView, QStackedWidget,
)

import platform_support
from ui import icons, theme
from ui.widgets import ElidedLabel

_ROW_H = 36


def _fmt_ts(s: float) -> str:
    m = int(s) // 60
    sec = int(s) % 60
    ms = int((s - int(s)) * 1000)
    return f"{m:02d}:{sec:02d}.{ms:03d}"


# ── Modello anteprima ─────────────────────────────────────────────────────────

def _seg_fields(seg) -> tuple:
    """(start, end, testo) da un segmento dict o Subtitle."""
    if isinstance(seg, dict):
        return (float(seg.get("start", 0)), float(seg.get("end", 0)),
                str(seg.get("text", "")))
    return float(getattr(seg, "start", 0.0)), float(getattr(seg, "end", 0.0)), \
        str(getattr(seg, "text", "") or "")


class _PreviewModel(QAbstractTableModel):
    """Modello a sola lettura: # | inizio | fine | testo (una riga per segmento)."""

    _HEADERS = ("#", "Inizio", "Fine", "Testo")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []

    def set_segments(self, segments: list):
        self.beginResetModel()
        self._rows = [_seg_fields(seg) for seg in segments]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._HEADERS[section]
        if role == Qt.TextAlignmentRole and orientation == Qt.Horizontal:
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        start, end, text = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return index.row() + 1
            if col == 1:
                return _fmt_ts(start)
            if col == 2:
                return _fmt_ts(end)
            return text.strip().replace("\n", " ")
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.FontRole and col < 3:
            f = QFont(platform_support.mono_font_family())
            f.setPixelSize(13)
            return f
        if role == Qt.ForegroundRole:
            if col == 0:
                return theme.qcolor("label")
            if col < 3:
                return theme.qcolor("dim")
            return theme.qcolor("text")
        if role == Qt.ToolTipRole and col == 3:
            return text.strip()
        return None

    def refresh_colors(self):
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, 3), [Qt.ForegroundRole])


# ── ResultWidget ──────────────────────────────────────────────────────────────

class ResultWidget(QWidget):
    export_requested      = Signal()
    open_editor_requested = Signal()
    new_requested         = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentPanel")

        self._segments: list = []
        self._source_path: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Fascia superiore su "panel" ───────────────────────────────────────
        self._band = QFrame()
        self._band.setObjectName("resultBand")
        band = QVBoxLayout(self._band)
        band.setContentsMargins(40, 22, 40, 22)
        band.setSpacing(12)

        hdr = QHBoxLayout()
        hdr.setSpacing(16)

        self._check_box = QLabel()
        self._check_box.setFixedSize(40, 40)
        self._check_box.setAlignment(Qt.AlignCenter)
        hdr.addWidget(self._check_box, 0, Qt.AlignVCenter)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title_lbl = QLabel("Trascrizione completata")
        title_col.addWidget(self.title_lbl)
        self.summary_lbl = ElidedLabel("")
        title_col.addWidget(self.summary_lbl)
        hdr.addLayout(title_col, 1)

        # Azioni
        self.new_btn = QPushButton("Nuova trascrizione")
        self.new_btn.setObjectName("secondary")
        self.new_btn.setMinimumHeight(36)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.clicked.connect(self.new_requested)
        hdr.addWidget(self.new_btn, alignment=Qt.AlignVCenter)

        self.export_btn = QPushButton("Esporta SRT")
        self.export_btn.setObjectName("secondary")
        icons.bind_icon(self.export_btn, "export", "text")
        self.export_btn.setMinimumHeight(36)
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self.export_requested)
        hdr.addWidget(self.export_btn, alignment=Qt.AlignVCenter)

        self.editor_btn = QPushButton("Apri nell'editor")
        self.editor_btn.setObjectName("primary")
        icons.bind_icon(self.editor_btn, "arrow_right", "acc_ink")
        self.editor_btn.setLayoutDirection(Qt.RightToLeft)   # icona dopo il testo
        self.editor_btn.setMinimumHeight(36)
        self.editor_btn.setCursor(Qt.PointingHandCursor)
        self.editor_btn.clicked.connect(self.open_editor_requested)
        hdr.addWidget(self.editor_btn, alignment=Qt.AlignVCenter)
        band.addLayout(hdr)

        # ── Avviso: versione modificata nell'editor (nascosto di default) ─────
        self.badge_frame = QFrame()
        self.badge_frame.setObjectName("resultNotice")
        badge_lay = QHBoxLayout(self.badge_frame)
        badge_lay.setContentsMargins(12, 8, 12, 8)
        badge_lay.setSpacing(10)
        self._badge_icon = QLabel()
        self._badge_icon.setFixedSize(16, 16)
        badge_lay.addWidget(self._badge_icon, 0, Qt.AlignTop)
        self.badge_lbl = QLabel(
            "Versione modificata nell'editor — i sottotitoli qui sono quelli originali"
        )
        self.badge_lbl.setWordWrap(True)
        badge_lay.addWidget(self.badge_lbl, 1)
        self.badge_frame.setVisible(False)
        band.addWidget(self.badge_frame)
        root.addWidget(self._band)

        # ── Corpo: anteprima ──────────────────────────────────────────────────
        body = QVBoxLayout()
        body.setContentsMargins(40, 20, 40, 0)
        body.setSpacing(6)
        prev_row = QHBoxLayout()
        self._prev_hdr = QLabel("Anteprima")
        prev_row.addWidget(self._prev_hdr)
        prev_row.addStretch(1)
        self._prev_note = QLabel("Trascrizione originale, sola lettura")
        prev_row.addWidget(self._prev_note)
        body.addLayout(prev_row)

        # ── Preview: vista virtualizzata (solo le righe visibili vengono disegnate)
        self._preview_outer = QFrame()
        self._preview_outer.setObjectName("previewOuter")
        self._preview_outer.setMinimumHeight(200)
        self._preview_outer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer_lay = QVBoxLayout(self._preview_outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        self._preview_stack = QStackedWidget()
        self._preview_model = _PreviewModel(self)
        self._preview_view = QTableView()
        self._preview_view.setObjectName("resultPreview")
        self._preview_view.setModel(self._preview_model)
        self._preview_view.setAccessibleName("Anteprima dei sottotitoli trascritti")
        self._preview_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._preview_view.setSelectionMode(QAbstractItemView.NoSelection)
        self._preview_view.setFocusPolicy(Qt.NoFocus)
        self._preview_view.setShowGrid(False)
        self._preview_view.setAlternatingRowColors(False)
        self._preview_view.setWordWrap(False)
        self._preview_view.setFrameShape(QFrame.NoFrame)
        self._preview_view.verticalHeader().setVisible(False)
        self._preview_view.verticalHeader().setDefaultSectionSize(
            max(_ROW_H, self._preview_view.fontMetrics().lineSpacing() + 16)
        )
        hh = self._preview_view.horizontalHeader()
        hh.setVisible(True)
        hh.setHighlightSections(False)
        hh.setSectionsClickable(False)
        hh.setFixedHeight(30)
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self._preview_view.setColumnWidth(0, 56)
        self._preview_view.setColumnWidth(1, 120)
        self._preview_view.setColumnWidth(2, 120)
        self._preview_stack.addWidget(self._preview_view)       # 0

        # Stato vuoto: nessun parlato rilevato
        self._empty = QWidget()
        el = QVBoxLayout(self._empty)
        el.setAlignment(Qt.AlignCenter)
        el.setSpacing(10)
        self._empty_title = QLabel("Nessun parlato rilevato")
        self._empty_title.setAlignment(Qt.AlignCenter)
        self._empty_desc = QLabel(
            "La trascrizione non ha prodotto sottotitoli. Verifica che il file contenga "
            "audio parlato, prova a disattivare il filtro VAD o scegli un altro modello."
        )
        self._empty_desc.setAlignment(Qt.AlignCenter)
        self._empty_desc.setWordWrap(True)
        self._retry_btn = QPushButton("Riprova con altre impostazioni")
        self._retry_btn.setObjectName("secondary")
        self._retry_btn.clicked.connect(self.new_requested)
        el.addWidget(self._empty_title)
        el.addWidget(self._empty_desc)
        el.addWidget(self._retry_btn, 0, Qt.AlignCenter)
        self._preview_stack.addWidget(self._empty)               # 1

        outer_lay.addWidget(self._preview_stack)
        body.addWidget(self._preview_outer, 1)
        root.addLayout(body, 1)

        self._apply_palette()
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    # ── Tema ─────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _name: str):
        self._apply_palette()
        self._preview_model.refresh_colors()

    def _apply_palette(self):
        c = theme.c
        self._band.setStyleSheet(
            f"QFrame#resultBand {{ background-color: {c('panel')}; border: none;"
            f" border-bottom: 1px solid {c('line')}; }}"
        )
        self._check_box.setStyleSheet(
            f"background: transparent; border: 1px solid {c('line_2')}; border-radius: 4px;"
        )
        self._check_box.setPixmap(icons.pixmap("check", theme.qcolor("text"), 20))
        self.title_lbl.setStyleSheet(
            f"font-size: 22px; font-weight: 500; color: {c('text')}; background: transparent;"
        )
        self.summary_lbl.setStyleSheet(
            f"color: {c('dim')}; font-size: 12px; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self.badge_frame.setStyleSheet(
            f"QFrame#resultNotice {{ background-color: transparent;"
            f" border: 1px solid {c('warn')}; border-radius: 4px; }}"
        )
        self._badge_icon.setPixmap(icons.pixmap("alert", theme.qcolor("warn"), 16))
        self._badge_icon.setStyleSheet("background: transparent; border: none;")
        self.badge_lbl.setStyleSheet(
            f"color: {c('warn')}; font-size: 13px; font-weight: 500;"
            " background: transparent; border: none;"
        )
        self._prev_hdr.setStyleSheet(
            f"color: {c('text')}; font-size: 12px; font-weight: 600; background: transparent;"
        )
        self._prev_note.setStyleSheet(
            f"color: {c('dim')}; font-size: 12px; background: transparent;"
        )
        self._preview_outer.setStyleSheet(
            "QFrame#previewOuter { background: transparent; border: none; }"
        )
        self._preview_view.setStyleSheet(
            f"QTableView#resultPreview {{ background: transparent; border: none;"
            f" font-size: 14px; color: {c('text')}; }}"
            f"QTableView#resultPreview::item {{ padding: 0 10px; border: none;"
            f" border-bottom: 1px solid {c('line')}; }}"
            f"QTableView#resultPreview QHeaderView::section {{ background: transparent;"
            f" color: {c('label')}; font-size: 11px; font-weight: 500; border: none;"
            f" border-bottom: 1px solid {c('line')}; padding: 0 10px; text-align: left; }}"
            f"QTableView#resultPreview QTableCornerButton::section {{ background: transparent;"
            " border: none; }"
        )
        self._empty.setStyleSheet("background: transparent;")
        self._empty_title.setStyleSheet(
            f"color: {c('text')}; font-size: 15px; font-weight: 600; background: transparent;"
        )
        self._empty_desc.setStyleSheet(
            f"color: {c('muted')}; font-size: 12.5px; background: transparent;"
        )

    # ── API pubblica ───────────────────────────────────────────────────────────

    def show_result(self, segments: list, source_path: str):
        self._segments = segments
        self._source_path = source_path

        n = len(segments)
        fname = Path(source_path).name if source_path else "—"
        self.title_lbl.setText("Trascrizione completata")
        self.summary_lbl.setText(f"{n} sottotitoli · {fname}")
        self.summary_lbl.set_full_tooltip(source_path)
        self.editor_btn.setEnabled(n > 0)
        self.export_btn.setEnabled(n > 0)

        self._preview_model.set_segments(segments)
        self._preview_stack.setCurrentIndex(0 if n else 1)
        self._preview_view.scrollToTop()

    def set_modified_badge(self, visible: bool):
        self.badge_frame.setVisible(visible)
