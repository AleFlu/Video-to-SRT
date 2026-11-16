"""
result_widget.py — ResultWidget (sotto-stato 0.2 di TranscriptionTab).

Layout (design "Studio"):
  ┌── Header row ──────────────────────────────────────────────────────┐
  │  Titolo + sottotitolo                   [Nuova] [Esporta] [Editor] │
  ├── Badge modificato (nascosto di default) ──────────────────────────┤
  ├── 4 Stat card ──────────────────────────────────────────────────────┤
  ├── Anteprima sottotitoli (vista virtualizzata: QTableView + model) ─┤
  └────────────────────────────────────────────────────────────────────┘

L'anteprima usa un modello Qt: anche con migliaia di segmenti si creano solo
le righe visibili (nessun widget per segmento).

Tema chiaro/scuro: colori da theme.c(), ri-applicati su theme_changed.
"""

from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSizePolicy, QTableView, QHeaderView, QAbstractItemView, QStackedWidget,
)

from ui import icons, theme
from ui.widgets import ElidedLabel


def _fmt_ts(s: float) -> str:
    m = int(s) // 60
    sec = int(s) % 60
    ms = int((s - int(s)) * 1000)
    return f"{m:02d}:{sec:02d}.{ms:03d}"


# ── Stat card ─────────────────────────────────────────────────────────────────

class _StatCard(QFrame):
    def __init__(self, value: str, label: str, accent: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self._accent = accent

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(4)

        self._val = QLabel(value)
        self._val.setObjectName("statVal")
        lay.addWidget(self._val)

        self._lbl = QLabel(label)
        self._lbl.setObjectName("statLbl")
        lay.addWidget(self._lbl)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(92)
        self._apply_palette()

    def _apply_palette(self):
        c = theme.c
        self.setStyleSheet(
            f"QFrame#statCard {{ background-color: {c('card')};"
            f" border: 1px solid {c('card_border')}; border-radius: 4px; }}"
        )
        val_color = c("acc") if self._accent else c("text")
        self._val.setStyleSheet(
            f"QLabel#statVal {{ color: {val_color}; font-size: 26px; font-weight: 650;"
            " background: transparent; border: none; }"
        )
        self._lbl.setStyleSheet(
            f"QLabel#statLbl {{ color: {c('muted')}; font-size: 10.5px; font-weight: 600;"
            " background: transparent; border: none; }"
        )

    def set_value(self, v: str):
        self._val.setText(v)

    def set_label(self, l: str):
        self._lbl.setText(l)


# ── Modello anteprima ─────────────────────────────────────────────────────────

def _seg_fields(seg) -> tuple:
    """(start, end, testo) da un segmento dict o Subtitle."""
    if isinstance(seg, dict):
        return (float(seg.get("start", 0)), float(seg.get("end", 0)),
                str(seg.get("text", "")))
    return float(getattr(seg, "start", 0.0)), float(getattr(seg, "end", 0.0)), \
        str(getattr(seg, "text", "") or "")


class _PreviewModel(QAbstractTableModel):
    """Modello a sola lettura: # | inizio | testo (una riga per segmento)."""

    _HEADERS = ("#", "Inizio", "Testo")

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
        return 3

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        start, _end, text = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return index.row() + 1
            if col == 1:
                return _fmt_ts(start)
            return text.strip().replace("\n", " ")
        if role == Qt.TextAlignmentRole:
            if col == 0:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ForegroundRole:
            if col == 0:
                return theme.qcolor("muted")
            if col == 1:
                return theme.qcolor("acc")
            return theme.qcolor("dim")
        if role == Qt.ToolTipRole and col == 2:
            return text.strip()
        return None

    def refresh_colors(self):
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, 2), [Qt.ForegroundRole])


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
        root.setContentsMargins(48, 32, 48, 32)
        root.setSpacing(0)

        # ── Header: titolo sinistra, bottoni destra ────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        eyebrow_row = QHBoxLayout()
        eyebrow_row.setSpacing(6)
        self._eyebrow_icon = QLabel()
        self._eyebrow_icon.setFixedSize(14, 14)
        eyebrow_row.addWidget(self._eyebrow_icon)
        self._eyebrow = QLabel("Completata")
        eyebrow_row.addWidget(self._eyebrow)
        eyebrow_row.addStretch(1)
        title_col.addLayout(eyebrow_row)

        self.title_lbl = QLabel("Trascrizione completata")
        title_col.addWidget(self.title_lbl)

        self.summary_lbl = ElidedLabel("")
        title_col.addWidget(self.summary_lbl)

        hdr.addLayout(title_col, 1)

        # Bottoni
        self.new_btn = QPushButton("Nuova trascrizione")
        self.new_btn.setObjectName("secondary")
        self.new_btn.setMinimumHeight(40)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.clicked.connect(self.new_requested)
        hdr.addWidget(self.new_btn, alignment=Qt.AlignVCenter)

        self.export_btn = QPushButton("Esporta SRT")
        self.export_btn.setObjectName("secondary")
        self.export_btn.setMinimumHeight(40)
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self.export_requested)
        hdr.addWidget(self.export_btn, alignment=Qt.AlignVCenter)

        self.editor_btn = QPushButton("Apri nell'editor  →")
        self.editor_btn.setObjectName("primary")
        self.editor_btn.setMinimumHeight(40)
        self.editor_btn.setCursor(Qt.PointingHandCursor)
        self.editor_btn.clicked.connect(self.open_editor_requested)
        hdr.addWidget(self.editor_btn, alignment=Qt.AlignVCenter)

        root.addLayout(hdr)
        root.addSpacing(20)

        # ── Badge modificato ───────────────────────────────────────────────────
        self.badge_frame = QFrame()
        badge_lay = QHBoxLayout(self.badge_frame)
        badge_lay.setContentsMargins(13, 9, 13, 9)
        self.badge_lbl = QLabel(
            "Versione modificata nell'editor — i sottotitoli qui sono quelli originali"
        )
        self.badge_lbl.setWordWrap(True)
        badge_lay.addWidget(self.badge_lbl)
        self.badge_frame.setVisible(False)
        root.addWidget(self.badge_frame)
        root.addSpacing(4)

        # ── 4 Stat card ───────────────────────────────────────────────────────
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self._card_n   = _StatCard("—", "Sottotitoli", accent=True)
        self._card_dur = _StatCard("—", "Durata media")
        self._card_cps = _StatCard("—", "CPS medio")
        self._card_cov = _StatCard("—", "Copertura")
        for c in (self._card_n, self._card_dur, self._card_cps, self._card_cov):
            cards.addWidget(c)
        root.addLayout(cards)
        root.addSpacing(24)

        # ── Header anteprima ──────────────────────────────────────────────────
        self._prev_hdr = QLabel("Anteprima")
        root.addWidget(self._prev_hdr)
        root.addSpacing(10)

        # ── Preview: vista virtualizzata (solo le righe visibili vengono disegnate)
        self._preview_outer = QFrame()
        self._preview_outer.setObjectName("previewOuter")
        self._preview_outer.setMinimumHeight(240)
        self._preview_outer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer_lay = QVBoxLayout(self._preview_outer)
        outer_lay.setContentsMargins(1, 1, 1, 1)
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
        self._preview_view.setAlternatingRowColors(True)
        self._preview_view.setWordWrap(False)
        self._preview_view.verticalHeader().setVisible(False)
        self._preview_view.horizontalHeader().setVisible(False)
        self._preview_view.verticalHeader().setDefaultSectionSize(
            self._preview_view.fontMetrics().lineSpacing() + 16
        )
        hh = self._preview_view.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
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
        root.addWidget(self._preview_outer, 1)

        self._apply_palette()
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    # ── Tema ─────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _name: str):
        self._apply_palette()
        for card in (self._card_n, self._card_dur, self._card_cps, self._card_cov):
            card._apply_palette()
        self._preview_model.refresh_colors()

    def _apply_palette(self):
        c = theme.c
        self._eyebrow.setStyleSheet(
            f"font-size: 12px; font-weight: 500; color: {c('ok')}; background: transparent;"
        )
        self._eyebrow_icon.setPixmap(icons.pixmap("check", theme.qcolor("ok"), 14))
        self._eyebrow_icon.setStyleSheet("background: transparent;")
        self.title_lbl.setStyleSheet(
            f"font-size: 22px; font-weight: 500; color: {c('text')}; background: transparent;"
        )
        self.summary_lbl.setStyleSheet(
            f"color: {c('dim')}; font-size: 14.5px; background: transparent;"
        )
        self.badge_frame.setStyleSheet(
            f"QFrame {{ background-color: {c('warn_soft')};"
            f" border: 1px solid {c('warn')}; border-radius: 4px; }}"
        )
        self.badge_lbl.setStyleSheet(
            f"color: {c('warn')}; font-size: 12.5px; font-weight: 500;"
            " background: transparent; border: none;"
        )
        self._prev_hdr.setStyleSheet(
            f"color: {c('muted')}; font-size: 10px; font-weight: 600;"
            f" background: transparent;"
        )
        self._preview_outer.setStyleSheet(
            f"QFrame#previewOuter {{ background: {c('card')};"
            f" border: 1px solid {c('card_border')}; border-radius: 4px; }}"
        )
        self._preview_view.setStyleSheet(
            f"QTableView#resultPreview {{ background: transparent; border: none;"
            f" alternate-background-color: {c('lift')}; font-size: 13px; }}"
            "QTableView#resultPreview::item { padding: 0 10px; border: none; }"
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
        self.summary_lbl.setText(f"{n} sottotitoli  ·  {fname}")
        self.summary_lbl.set_full_tooltip(source_path)
        self.editor_btn.setEnabled(n > 0)
        self.export_btn.setEnabled(n > 0)

        # Statistiche
        durations, cpss, covered, total_audio = [], [], 0.0, 0.0
        for seg in segments:
            start, end, text = _seg_fields(seg)
            dur = max(0.0, end - start)
            durations.append(dur)
            covered += dur
            if dur > 0:
                cpss.append(len(text.strip()) / dur)
            if end > total_audio:
                total_audio = end

        avg_dur = sum(durations) / len(durations) if durations else 0.0
        avg_cps = sum(cpss) / len(cpss) if cpss else 0.0
        cov_pct = (covered / total_audio * 100) if total_audio > 0 else 0.0

        self._card_n.set_value(str(n))
        self._card_dur.set_value(f"{avg_dur:.1f}s")
        self._card_cps.set_value(f"{avg_cps:.1f}")
        self._card_cov.set_value(f"{cov_pct:.0f}%")

        self._preview_model.set_segments(segments)
        self._preview_stack.setCurrentIndex(0 if n else 1)
        self._preview_view.scrollToTop()

    def set_modified_badge(self, visible: bool):
        self.badge_frame.setVisible(visible)
