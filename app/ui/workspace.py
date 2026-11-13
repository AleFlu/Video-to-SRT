"""
workspace.py — WorkspaceWidget (editor DaVinci, Stato 2).

Layout:
  ┌──────────────────────────────────────────────┬──────────────┐
  │  PreviewArea  (video o waveform)             │              │
  ├──────────────────────────────────────────────┤  Inspector   │
  │  SubtitleTimeline (tabella + toolbar)        │  (full col)  │
  └──────────────────────────────────────────────┴──────────────┘

- Inspector occupa l'intera altezza a destra (QSplitter orizzontale)
- Preview e Timeline divisi da QSplitter verticale nella colonna sinistra
- Tutti i pannelli ridimensionabili con limiti pratici
- Geometria salvata in QSettings
"""

from __future__ import annotations
from typing import List

from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QSizePolicy,
)

from core.subtitle_model import Subtitle
from ui.preview_area import PreviewArea
from ui.subtitle_timeline import SubtitleTimeline
from ui import theme


_SETTINGS_HSPLIT = "workspace/hsplit_sizes"   # [left_col, inspector]
_SETTINGS_VSPLIT = "workspace/vsplit_sizes"   # [preview, timeline]


def _splitter_style() -> str:
    return (
        f"QSplitter::handle {{ background: {theme.c('line')}; }}"
        "QSplitter::handle:horizontal { width: 1px; }"
        "QSplitter::handle:vertical { height: 1px; }"
    )


class WorkspaceWidget(QWidget):
    """
    Editor DaVinci layout:
      - Colonna sinistra: preview (top) + timeline tabella (bottom)
      - Colonna destra: inspector (full height)
    Tutti i confini sono QSplitter ridimensionabili.
    """

    subtitles_changed = Signal()
    export_requested  = Signal()
    status_text       = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Splitter orizzontale: [colonna sinistra | inspector] ──────────────
        self._hsplit = QSplitter(Qt.Horizontal)
        self._hsplit.setChildrenCollapsible(False)
        self._hsplit.setHandleWidth(1)
        self._hsplit.setStyleSheet(_splitter_style())
        root.addWidget(self._hsplit)

        # ── Colonna sinistra: splitter verticale [preview | timeline] ─────────
        self._vsplit = QSplitter(Qt.Vertical)
        self._vsplit.setChildrenCollapsible(False)
        self._vsplit.setHandleWidth(1)
        self._vsplit.setStyleSheet(_splitter_style())

        self.preview = PreviewArea()
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setMinimumHeight(120)
        self._vsplit.addWidget(self.preview)

        self.timeline = SubtitleTimeline()
        self.timeline.setMinimumHeight(160)
        self._vsplit.addWidget(self.timeline)

        # Preview ~38%, timeline ~62%
        self._vsplit.setStretchFactor(0, 2)
        self._vsplit.setStretchFactor(1, 3)

        self._hsplit.addWidget(self._vsplit)

        # ── Inspector — colonna destra full height ────────────────────────────
        from ui.inspector_widget import InspectorWidget
        self.inspector = InspectorWidget()
        self.inspector.bind_model(self.timeline.model)
        self.inspector.setMinimumWidth(240)
        self.inspector.setMaximumWidth(420)
        self.inspector.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._hsplit.addWidget(self.inspector)

        # Inspector width ~280px, left col stretch
        self._hsplit.setStretchFactor(0, 1)
        self._hsplit.setStretchFactor(1, 0)

        # ── Unifica player ─────────────────────────────────────────────────────
        self.timeline.set_player(self.preview.player)

        # ── Inspector wiring — collega timeline → inspector esterno ───────────
        self._wire_inspector()

        # ── Inspector toggle dalla toolbar timeline ────────────────────────────
        self.timeline.act_toggle_insp.triggered.connect(
            lambda checked: self.inspector.setVisible(checked)
        )

        # ── Connessioni generali ───────────────────────────────────────────────
        self._wire()

        # ── Ripristina geometria ───────────────────────────────────────────────
        self._restore_geometry()

        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _name=None):
        self._hsplit.setStyleSheet(_splitter_style())
        self._vsplit.setStyleSheet(_splitter_style())

    # ── Wiring inspector (ora esterno alla timeline) ───────────────────────────

    def _wire_inspector(self):
        # Segnali inspector → undo stack già connessi in SubtitleTimeline._wire().
        # Qui colleghiamo solo la sincronizzazione selezione → inspector display.
        self.timeline.view.selectionModel().currentRowChanged.connect(
            lambda cur, _: self.inspector.show_row(cur.row() if cur.isValid() else None)
        )
        self.timeline.view.clicked.connect(
            lambda idx: self.inspector.show_row(idx.row())
        )

    # ── Wiring generale ───────────────────────────────────────────────────────

    def _wire(self):
        self.timeline.subtitles_changed.connect(self.subtitles_changed)
        self.timeline.subtitles_changed.connect(self._sync_preview_subs)
        self.timeline.status_text.connect(self.status_text)
        self.timeline.model.rowsInserted.connect(self._sync_preview_subs)
        self.timeline.model.rowsRemoved.connect(self._sync_preview_subs)
        self.timeline.model.modelReset.connect(self._sync_preview_subs)

        self.timeline.act_export.triggered.connect(self.export_requested)

        self.timeline.view.selectionModel().currentRowChanged.connect(
            self._on_timeline_row_changed
        )

        self.preview.waveform.subtitle_clicked.connect(self._on_waveform_click)
        self.preview.player.position_changed.connect(self.timeline._on_player_pos)
        self.timeline.jkl_pressed.connect(self.preview.transport.set_jkl_key)

        self._hsplit.splitterMoved.connect(self._save_geometry)
        self._vsplit.splitterMoved.connect(self._save_geometry)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_timeline_row_changed(self, current, _prev):
        row = current.row() if current.isValid() else -1
        self.preview.set_selected_row(row)

    def _sync_preview_subs(self, *_):
        subs = self.timeline.model.subtitles()
        severity = [
            self.timeline.model.row_severity(r)
            for r in range(self.timeline.model.rowCount())
        ]
        self.preview.set_subtitles(subs, severity)

    def _on_waveform_click(self, row: int):
        self.timeline.view.selectRow(row)
        sub = self.timeline.model.subtitle_at(row)
        if sub:
            self.preview.player.seek(int(sub.start * 1000))

    # ── API pubblica ───────────────────────────────────────────────────────────

    def load_result(self, segments: list, source_path: str):
        from core.subtitle_model import SubtitleProject
        project = SubtitleProject()
        project.load_from_segments(segments, source_path)
        self.timeline.load_subtitles(project.subtitles)
        self.preview.load_media(source_path)
        self._sync_preview_subs()

    def get_subtitles(self) -> List[Subtitle]:
        return self.timeline.get_subtitles()

    def is_modified(self) -> bool:
        return self.timeline.is_modified()

    def mark_saved(self):
        self.timeline.mark_saved()

    # ── Persistenza geometria ──────────────────────────────────────────────────

    def _save_geometry(self):
        s = QSettings("VideoSRT", "v2")
        s.setValue(_SETTINGS_HSPLIT, self._hsplit.sizes())
        s.setValue(_SETTINGS_VSPLIT, self._vsplit.sizes())

    def _restore_geometry(self):
        s = QSettings("VideoSRT", "v2")
        h = s.value(_SETTINGS_HSPLIT)
        v = s.value(_SETTINGS_VSPLIT)
        try:
            if h:
                self._hsplit.setSizes([int(x) for x in h])
            if v:
                self._vsplit.setSizes([int(x) for x in v])
        except Exception:
            pass
