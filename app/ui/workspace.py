"""
workspace.py — WorkspaceWidget (editor, Stato 2).

Layout (misure del mockup):
  ┌─────────────────────────────────────────────────────────────┐
  │  PreviewArea: monitor 452 px | forma d'onda  (286 px)       │
  │  riga di trasporto (46 px)                                  │
  ├─────────────────────────────────────────────────────────────┤  ← QSplitter verticale
  │  toolbar (42 px, a tutta larghezza)                         │
  ├───────────────────────────────────────────┬─────────────────┤
  │  SubtitleTimeline (tabella)               │  Inspector      │  ← QSplitter orizzontale
  │                                           │  (324 px)       │
  └───────────────────────────────────────────┴─────────────────┘

- Preview e area di lavoro sono divisi da un QSplitter verticale, tabella e
  inspector da uno orizzontale: i valori predefiniti sono quelli del mockup,
  l'utente può ridimensionarli
- Geometria salvata in QSettings
"""

from __future__ import annotations
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, Signal, QSettings, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QSplitter, QSizePolicy

from core.constants import SUPPORTED_SUBTITLE_EXTS
from core.subtitle_model import Subtitle
from ui.preview_area import PreviewArea, TOP_ZONE_HEIGHT
from ui.subtitle_timeline import SubtitleTimeline, SYNC_DEBOUNCE_MS
from ui import theme
from ui.prefs import read_list


# Chiavi nuove (_v2): la struttura è cambiata (toolbar a tutta larghezza, ispettore
# solo accanto alla tabella) e le vecchie proporzioni non vanno più bene.
_SETTINGS_HSPLIT = "workspace/hsplit_sizes_v2"   # [tabella, inspector]
_SETTINGS_VSPLIT = "workspace/vsplit_sizes_v2"   # [preview + trasporto, area di lavoro]

INSPECTOR_WIDTH = 324
_TRANSPORT_HEIGHT = 46


def _splitter_style() -> str:
    return (
        f"QSplitter::handle {{ background: {theme.c('line')}; }}"
        "QSplitter::handle:horizontal { width: 1px; }"
        "QSplitter::handle:vertical { height: 1px; }"
    )


class WorkspaceWidget(QWidget):
    """
    Layout dell'editor:
      - in alto: preview (monitor + forma d'onda) e trasporto
      - sotto: toolbar a tutta larghezza, poi tabella (sinistra) e inspector (destra)
    Tutti i confini sono QSplitter ridimensionabili.
    """

    subtitles_changed = Signal()
    export_requested  = Signal()
    status_text       = Signal(str)
    import_requested  = Signal(str)   # "+ Importa" dalla toolbar della timeline

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Splitter verticale: [preview + trasporto | area di lavoro] ─────────
        self._vsplit = QSplitter(Qt.Vertical)
        self._vsplit.setChildrenCollapsible(False)
        self._vsplit.setHandleWidth(1)
        self._vsplit.setStyleSheet(_splitter_style())
        root.addWidget(self._vsplit)

        self.preview = PreviewArea()
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setMinimumHeight(190)
        self._vsplit.addWidget(self.preview)

        # ── Area di lavoro: toolbar + splitter orizzontale [tabella | inspector] ──
        lower = QWidget()
        lower_lay = QVBoxLayout(lower)
        lower_lay.setContentsMargins(0, 0, 0, 0)
        lower_lay.setSpacing(0)

        self.timeline = SubtitleTimeline()
        self.timeline.setMinimumHeight(120)
        # La toolbar sta a tutta larghezza, sopra tabella e inspector
        self._toolbar = self.timeline.detach_toolbar()
        lower_lay.addWidget(self._toolbar)

        self._hsplit = QSplitter(Qt.Horizontal)
        self._hsplit.setChildrenCollapsible(False)
        self._hsplit.setHandleWidth(1)
        self._hsplit.setStyleSheet(_splitter_style())
        self._hsplit.addWidget(self.timeline)

        # ── Inspector ──────────────────────────────────────────────────────────
        # Istanza UNICA: è quella della timeline, già collegata all'undo stack
        # in SubtitleTimeline._wire(). Qui viene solo inserita nel layout.
        self.inspector = self.timeline.inspector
        self.inspector.setMinimumWidth(240)
        self.inspector.setMaximumWidth(420)
        self.inspector.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._hsplit.addWidget(self.inspector)
        self._hsplit.setStretchFactor(0, 1)
        self._hsplit.setStretchFactor(1, 0)
        self._hsplit.setSizes([1116, INSPECTOR_WIDTH])
        lower_lay.addWidget(self._hsplit, 1)
        self._vsplit.addWidget(lower)

        # Il top (preview + trasporto) tiene la sua altezza, l'area di lavoro si espande
        self._vsplit.setStretchFactor(0, 0)
        self._vsplit.setStretchFactor(1, 1)
        self._vsplit.setSizes([TOP_ZONE_HEIGHT + _TRANSPORT_HEIGHT, 560])

        # ── Unifica player ─────────────────────────────────────────────────────
        self.timeline.set_player(self.preview.player)

        # ── Inspector toggle dalla toolbar timeline ────────────────────────────
        self.timeline.act_toggle_insp.triggered.connect(self._on_toggle_inspector)

        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(SYNC_DEBOUNCE_MS)
        self._sync_timer.timeout.connect(self.sync_preview_subs)

        # ── Ordine di Tab: toolbar → ricerca → tabella → inspector → forma d'onda
        #    → trasporto (la preview è costruita prima, ma si percorre dopo) ──────
        chain = [*self.timeline.focus_chain(), self.preview.waveform,
                 *self.preview.transport.focus_chain()]
        for a, b in zip(chain, chain[1:]):
            QWidget.setTabOrder(a, b)

        # ── Connessioni generali ───────────────────────────────────────────────
        self._wire()

        # ── Ripristina geometria ───────────────────────────────────────────────
        self._restore_geometry()

        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    def _on_toggle_inspector(self, checked: bool):
        self.inspector.setVisible(bool(checked))

    def _on_theme_changed(self, _name=None):
        self._hsplit.setStyleSheet(_splitter_style())
        self._vsplit.setStyleSheet(_splitter_style())

    # ── Wiring generale ───────────────────────────────────────────────────────

    def _wire(self):
        self.timeline.subtitles_changed.connect(self.subtitles_changed)
        # dataModified (→ subtitles_changed) arriva dopo ogni modifica, inclusi
        # inserimenti, rimozioni e reset: un solo aggancio, con debounce.
        self.timeline.subtitles_changed.connect(self._schedule_sync)
        self.timeline.status_text.connect(self.status_text)
        self.timeline.import_requested.connect(self.import_requested)

        self.timeline.act_export.triggered.connect(self.export_requested)

        self.timeline.view.selectionModel().currentRowChanged.connect(
            self._on_timeline_row_changed
        )

        self.preview.waveform.subtitle_clicked.connect(self._on_waveform_click)
        # position_changed → timeline._on_player_pos è collegato da set_player()
        self.timeline.jkl_pressed.connect(self.preview.transport.set_jkl_key)
        self.preview.transport.loop_toggled.connect(self.timeline.set_loop)

        self._hsplit.splitterMoved.connect(self._save_geometry)
        self._vsplit.splitterMoved.connect(self._save_geometry)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_timeline_row_changed(self, current, _prev):
        row = current.row() if current.isValid() else -1
        self.preview.set_selected_row(row)

    def _schedule_sync(self, *_):
        """Raggruppa le sincronizzazioni O(N) della preview (debounce)."""
        self._sync_timer.start()

    def sync_preview_subs(self, *_):
        """Ricopia subito i sottotitoli correnti su waveform e overlay video."""
        self._sync_timer.stop()
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
        self.load_content(project.subtitles, source_path)

    def load_content(self, subtitles: List[Subtitle], source_path: str):
        """
        Carica sottotitoli + media nell'editor e risincronizza la preview.

        `load_media` resetta waveform e overlay: per questo la sincronizzazione
        dei sottotitoli va fatta DOPO il caricamento del media. Senza media
        valido la preview viene svuotata (niente media del progetto precedente).
        """
        self.timeline.load_subtitles(subtitles)
        # Un .srt/.v2srt come sorgente (import) non è un media da riprodurre
        is_media = bool(source_path) and (
            Path(source_path).suffix.lower() not in SUPPORTED_SUBTITLE_EXTS)
        if is_media and Path(source_path).exists():
            self.preview.load_media(source_path)
        else:
            self.preview.clear_media()
        self.sync_preview_subs()

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
        h = read_list(s, _SETTINGS_HSPLIT)
        v = read_list(s, _SETTINGS_VSPLIT)
        for split, saved in ((self._hsplit, h), (self._vsplit, v)):
            try:
                sizes = [int(x) for x in saved]
            except (TypeError, ValueError):
                continue
            # valori incompleti o nulli (es. chiavi di una versione precedente): si ignorano
            if len(sizes) == split.count() and all(x > 0 for x in sizes):
                split.setSizes(sizes)
