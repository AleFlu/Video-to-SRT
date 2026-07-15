"""
result_widget.py — ResultWidget (sotto-stato 0.2 di TranscriptionTab).

Layout:
  ┌── Header row ──────────────────────────────────────────────────────┐
  │  Titolo + sottotitolo                   [Nuova] [Esporta] [Editor] │
  ├── Badge modificato (nascosto di default) ──────────────────────────┤
  ├── 4 Stat card ──────────────────────────────────────────────────────┤
  ├── Anteprima sottotitoli (altezza fissa 320px, scroll interno) ─────┤
  └────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSizePolicy, QScrollArea,
)


def _fmt_ts(s: float) -> str:
    m = int(s) // 60
    sec = int(s) % 60
    ms = int((s - int(s)) * 10)
    return f"{m:02d}:{sec:02d}.{ms}"


# ── Stat card ─────────────────────────────────────────────────────────────────

_CARD_SS = (
    # Selector specifico su QFrame con objectName per non "trapassare" nei figli
    "QFrame#statCard {"
    "  background-color: #1a1d24;"
    "  border: 1px solid #262a33;"
    "  border-radius: 11px;"
    "}"
)

class _StatCard(QFrame):
    def __init__(self, value: str, label: str, accent: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setStyleSheet(_CARD_SS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(5)
        lay.setAlignment(Qt.AlignCenter)

        val_color = "#5b8cff" if accent else "#e8eaf0"
        self._val = QLabel(value)
        self._val.setObjectName("statVal")
        self._val.setAlignment(Qt.AlignCenter)
        # stylesheet diretto sul QLabel — non eredita il bordo del frame
        self._val.setStyleSheet(
            f"QLabel#statVal {{ color: {val_color}; font-size: 28px; font-weight: 700;"
            " letter-spacing: -1px; background: transparent; border: none; }"
        )
        lay.addWidget(self._val)

        self._lbl = QLabel(label.upper())
        self._lbl.setObjectName("statLbl")
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setStyleSheet(
            "QLabel#statLbl { color: #6c727f; font-size: 10px; font-weight: 600;"
            " letter-spacing: 1px; background: transparent; border: none; }"
        )
        lay.addWidget(self._lbl)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(96)

    def set_value(self, v: str):
        self._val.setText(v)

    def set_label(self, l: str):
        self._lbl.setText(l.upper())


# ── Preview row ───────────────────────────────────────────────────────────────

class _PreviewRow(QWidget):
    """Riga anteprima: num | timestamp | testo. Sfondo alternato."""

    def __init__(self, idx: int, ts_start: str, ts_end: str, text: str,
                 alt: bool = False, parent=None):
        super().__init__(parent)
        # Sfondo esplicito su ogni riga — evita il nero del tema globale
        bg = "#1e2128" if alt else "#1a1d24"
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"QWidget {{ background-color: {bg}; border: none; }}")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 9, 16, 9)
        lay.setSpacing(14)

        num = QLabel(str(idx))
        num.setFixedWidth(28)
        num.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        num.setStyleSheet(
            "color: #4a4f5a; font-size: 11px;"
            " font-family: 'SF Mono','Menlo',monospace;"
            " background: transparent; border: none;"
        )
        lay.addWidget(num)

        ts = QLabel(f"{ts_start} → {ts_end}")
        ts.setFixedWidth(148)
        ts.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ts.setStyleSheet(
            "color: #6c727f; font-size: 11px;"
            " font-family: 'SF Mono','Menlo',monospace;"
            " background: transparent; border: none;"
        )
        lay.addWidget(ts)

        txt = QLabel(text)
        txt.setWordWrap(True)
        txt.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        txt.setStyleSheet(
            "color: #a8aebb; font-size: 13px; background: transparent; border: none;"
        )
        lay.addWidget(txt, 1)


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
        title_col.setSpacing(3)

        self.title_lbl = QLabel("Trascrizione completata")
        self.title_lbl.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #e8eaf0; letter-spacing: -0.3px;"
        )
        title_col.addWidget(self.title_lbl)

        self.summary_lbl = QLabel("")
        self.summary_lbl.setStyleSheet("color: #6c727f; font-size: 13px;")
        title_col.addWidget(self.summary_lbl)

        hdr.addLayout(title_col, 1)

        # Bottoni
        self.new_btn = QPushButton("Nuova trascrizione")
        self.new_btn.setFixedHeight(36)
        self.new_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #a8aebb;"
            " border: 1px solid #2f343e; border-radius: 8px;"
            " font-size: 13px; font-weight: 500; padding: 0 16px; }"
            "QPushButton:hover { background: #1f232c; color: #e8eaf0; border-color: #3a404e; }"
        )
        self.new_btn.clicked.connect(self.new_requested)
        hdr.addWidget(self.new_btn, alignment=Qt.AlignVCenter)

        self.export_btn = QPushButton("↑  Esporta SRT")
        self.export_btn.setFixedHeight(36)
        self.export_btn.setStyleSheet(
            "QPushButton { background: #1a1d24; color: #e8eaf0;"
            " border: 1px solid #2f343e; border-radius: 8px;"
            " font-size: 13px; font-weight: 500; padding: 0 16px; }"
            "QPushButton:hover { background: #1f232c; border-color: #3a404e; }"
        )
        self.export_btn.clicked.connect(self.export_requested)
        hdr.addWidget(self.export_btn, alignment=Qt.AlignVCenter)

        self.editor_btn = QPushButton("Apri nell'editor  →")
        self.editor_btn.setFixedHeight(36)
        self.editor_btn.setStyleSheet(
            "QPushButton { background: #5b8cff; color: #fff;"
            " border: none; border-radius: 8px;"
            " font-size: 13px; font-weight: 600; padding: 0 18px; }"
            "QPushButton:hover { background: #7aa2ff; }"
            "QPushButton:pressed { background: #3f6fd8; }"
        )
        self.editor_btn.clicked.connect(self.open_editor_requested)
        hdr.addWidget(self.editor_btn, alignment=Qt.AlignVCenter)

        root.addLayout(hdr)
        root.addSpacing(20)

        # ── Badge modificato ───────────────────────────────────────────────────
        self.badge_frame = QFrame()
        self.badge_frame.setStyleSheet(
            "QFrame { background-color: rgba(245,180,97,0.08);"
            " border: 1px solid rgba(245,180,97,0.35); border-radius: 9px; }"
        )
        badge_lay = QHBoxLayout(self.badge_frame)
        badge_lay.setContentsMargins(14, 9, 14, 9)
        self.badge_lbl = QLabel(
            "⚠️  Versione modificata nell'editor — i sottotitoli qui sono quelli originali"
        )
        self.badge_lbl.setStyleSheet(
            "color: #f5b461; font-size: 12px; background: transparent; border: none;"
        )
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
        prev_hdr = QLabel("ANTEPRIMA SOTTOTITOLI")
        prev_hdr.setStyleSheet(
            "color: #4a4f5a; font-size: 10px; font-weight: 700;"
            " letter-spacing: 1.5px; font-family: 'SF Mono',monospace;"
        )
        root.addWidget(prev_hdr)
        root.addSpacing(8)

        # ── Preview: frame fisso 320px con scroll interno ─────────────────────
        preview_outer = QFrame()
        preview_outer.setObjectName("previewOuter")
        preview_outer.setStyleSheet(
            "QFrame#previewOuter { background: #1a1d24;"
            " border: 1px solid #262a33; border-radius: 11px; }"
        )
        preview_outer.setFixedHeight(320)
        outer_lay = QVBoxLayout(preview_outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(True)
        self._preview_scroll.setFrameShape(QFrame.NoFrame)
        self._preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._preview_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: #1a1d24; width: 6px; border: none; }"
            "QScrollBar::handle:vertical { background: #2f343e; border-radius: 3px; min-height: 20px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._preview_inner = QWidget()
        self._preview_inner.setStyleSheet("background: #1a1d24;")
        self._preview_lay = QVBoxLayout(self._preview_inner)
        self._preview_lay.setContentsMargins(0, 0, 0, 0)
        self._preview_lay.setSpacing(0)

        self._preview_scroll.setWidget(self._preview_inner)
        outer_lay.addWidget(self._preview_scroll)

        root.addWidget(preview_outer)
        root.addStretch(1)

    # ── API pubblica ───────────────────────────────────────────────────────────

    def show_result(self, segments: list, source_path: str):
        self._segments = segments
        self._source_path = source_path

        n = len(segments)
        fname = Path(source_path).name if source_path else "—"
        self.title_lbl.setText("Trascrizione completata")
        self.summary_lbl.setText(f"{fname}  ·  {n} segmenti")
        self.badge_frame.setVisible(False)

        # Statistiche
        durations, cpss, covered, total_audio = [], [], 0.0, 0.0
        for seg in segments:
            start = end = 0.0
            text = ""
            if hasattr(seg, "start"):
                start, end, text = seg.start, seg.end, (seg.text or "")
            elif isinstance(seg, dict):
                start = float(seg.get("start", 0))
                end   = float(seg.get("end", 0))
                text  = str(seg.get("text", ""))
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

        # Rebuild righe — sfondo alternato, no stretcher vuoto
        while self._preview_lay.count():
            item = self._preview_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, seg in enumerate(segments):
            start = end = 0.0
            text = ""
            if hasattr(seg, "start"):
                start, end, text = seg.start, seg.end, (seg.text or "").strip()
            elif isinstance(seg, dict):
                start = float(seg.get("start", 0))
                end   = float(seg.get("end", 0))
                text  = str(seg.get("text", "")).strip()
            self._preview_lay.addWidget(
                _PreviewRow(i + 1, _fmt_ts(start), _fmt_ts(end), text,
                            alt=(i % 2 == 1), parent=self._preview_inner)
            )

        # Padding finale per evitare che l'ultima riga sia a bordo
        self._preview_lay.addSpacing(4)
        self._preview_scroll.verticalScrollBar().setValue(0)

    def set_modified_badge(self, visible: bool):
        self.badge_frame.setVisible(visible)
