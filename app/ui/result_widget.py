"""
result_widget.py — ResultWidget (sotto-stato 0.2 di TranscriptionTab).

Layout (design "Studio"):
  ┌── Header row ──────────────────────────────────────────────────────┐
  │  Titolo + sottotitolo                   [Nuova] [Esporta] [Editor] │
  ├── Badge modificato (nascosto di default) ──────────────────────────┤
  ├── 4 Stat card ──────────────────────────────────────────────────────┤
  ├── Anteprima sottotitoli (altezza fissa 320px, scroll interno) ─────┤
  └────────────────────────────────────────────────────────────────────┘

Tema chiaro/scuro: colori da theme.c(), ri-applicati su theme_changed.
"""

from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSizePolicy, QScrollArea,
)

from ui import theme


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

        self._lbl = QLabel(label.upper())
        self._lbl.setObjectName("statLbl")
        lay.addWidget(self._lbl)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(92)
        self._apply_palette()

    def _apply_palette(self):
        c = theme.c
        self.setStyleSheet(
            f"QFrame#statCard {{ background-color: {c('card')};"
            f" border: 1px solid {c('card_border')}; border-radius: 11px; }}"
        )
        val_color = c("acc") if self._accent else c("text")
        self._val.setStyleSheet(
            f"QLabel#statVal {{ color: {val_color}; font-size: 26px; font-weight: 650;"
            " letter-spacing: -0.5px; background: transparent; border: none; }"
        )
        self._lbl.setStyleSheet(
            f"QLabel#statLbl {{ color: {c('muted')}; font-size: 10.5px; font-weight: 600;"
            " letter-spacing: 0.8px; background: transparent; border: none; }"
        )

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
        c = theme.c
        bg = c("lift") if alt else "transparent"
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"QWidget {{ background-color: {bg}; border: none; }}")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(12)

        num = QLabel(str(idx))
        num.setFixedWidth(34)
        num.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        num.setStyleSheet(
            f"color: {c('muted')}; font-size: 11.5px;"
            f" font-family: {theme.FONT_MONO};"
            " background: transparent; border: none;"
        )
        lay.addWidget(num)

        ts = QLabel(ts_start)
        ts.setFixedWidth(132)
        ts.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ts.setStyleSheet(
            f"color: {c('acc')}; font-size: 11.5px;"
            f" font-family: {theme.FONT_MONO};"
            " background: transparent; border: none;"
        )
        lay.addWidget(ts)

        txt = QLabel(text)
        txt.setWordWrap(True)
        txt.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        txt.setStyleSheet(
            f"color: {c('dim')}; font-size: 13px; background: transparent; border: none;"
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
        title_col.setSpacing(4)

        self._eyebrow = QLabel("✓ COMPLETATA")
        title_col.addWidget(self._eyebrow)

        self.title_lbl = QLabel("Trascrizione completata")
        title_col.addWidget(self.title_lbl)

        self.summary_lbl = QLabel("")
        title_col.addWidget(self.summary_lbl)

        hdr.addLayout(title_col, 1)

        # Bottoni
        self.new_btn = QPushButton("Nuova trascrizione")
        self.new_btn.setObjectName("secondary")
        self.new_btn.setFixedHeight(40)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.clicked.connect(self.new_requested)
        hdr.addWidget(self.new_btn, alignment=Qt.AlignVCenter)

        self.export_btn = QPushButton("↑  Esporta SRT")
        self.export_btn.setObjectName("secondary")
        self.export_btn.setFixedHeight(40)
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.clicked.connect(self.export_requested)
        hdr.addWidget(self.export_btn, alignment=Qt.AlignVCenter)

        self.editor_btn = QPushButton("Apri nell'editor  →")
        self.editor_btn.setObjectName("primary")
        self.editor_btn.setFixedHeight(40)
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
            "⚠️  Versione modificata nell'editor — i sottotitoli qui sono quelli originali"
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
        self._prev_hdr = QLabel("ANTEPRIMA")
        root.addWidget(self._prev_hdr)
        root.addSpacing(10)

        # ── Preview: frame fisso 320px con scroll interno ─────────────────────
        self._preview_outer = QFrame()
        self._preview_outer.setObjectName("previewOuter")
        self._preview_outer.setFixedHeight(320)
        outer_lay = QVBoxLayout(self._preview_outer)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(0)

        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(True)
        self._preview_scroll.setFrameShape(QFrame.NoFrame)
        self._preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._preview_inner = QWidget()
        self._preview_lay = QVBoxLayout(self._preview_inner)
        self._preview_lay.setContentsMargins(0, 0, 0, 0)
        self._preview_lay.setSpacing(0)

        self._preview_scroll.setWidget(self._preview_inner)
        outer_lay.addWidget(self._preview_scroll)

        root.addWidget(self._preview_outer)
        root.addStretch(1)

        self._apply_palette()
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    # ── Tema ─────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _name: str):
        self._apply_palette()
        for card in (self._card_n, self._card_dur, self._card_cps, self._card_cov):
            card._apply_palette()
        # ridisegna le righe preview con i nuovi colori
        if self._segments:
            self.show_result(self._segments, self._source_path)

    def _apply_palette(self):
        c = theme.c
        self._eyebrow.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {c('ok')};"
            " letter-spacing: 1.6px; background: transparent;"
        )
        self.title_lbl.setStyleSheet(
            f"font-size: 30px; font-weight: 600; color: {c('text')};"
            " letter-spacing: -0.6px; background: transparent;"
        )
        self.summary_lbl.setStyleSheet(
            f"color: {c('dim')}; font-size: 14.5px; background: transparent;"
        )
        self.badge_frame.setStyleSheet(
            f"QFrame {{ background-color: {c('warn_soft')};"
            f" border: 1px solid {c('warn')}; border-radius: 9px; }}"
        )
        self.badge_lbl.setStyleSheet(
            f"color: {c('warn')}; font-size: 12.5px; font-weight: 500;"
            " background: transparent; border: none;"
        )
        self._prev_hdr.setStyleSheet(
            f"color: {c('muted')}; font-size: 10px; font-weight: 600;"
            f" letter-spacing: 1px; background: transparent;"
        )
        self._preview_outer.setStyleSheet(
            f"QFrame#previewOuter {{ background: {c('card')};"
            f" border: 1px solid {c('card_border')}; border-radius: 11px; }}"
        )
        self._preview_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self._preview_inner.setStyleSheet("background: transparent;")

    # ── API pubblica ───────────────────────────────────────────────────────────

    def show_result(self, segments: list, source_path: str):
        self._segments = segments
        self._source_path = source_path

        n = len(segments)
        fname = Path(source_path).name if source_path else "—"
        self.title_lbl.setText("Trascrizione completata")
        self.summary_lbl.setText(f"{n} sottotitoli  ·  {fname}")
        self.badge_frame.setVisible(self.badge_frame.isVisible())

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
                _PreviewRow(i + 1, _fmt_ts(start), _fmt_ts(end), text.replace("\n", " "),
                            alt=(i % 2 == 1), parent=self._preview_inner)
            )

        self._preview_lay.addStretch(1)
        self._preview_scroll.verticalScrollBar().setValue(0)

    def set_modified_badge(self, visible: bool):
        self.badge_frame.setVisible(visible)
