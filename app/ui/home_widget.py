"""
home_widget.py — Schermata Home (Stato 0).

Layout (design system "Studio"):
  ┌──────────────────────────────────────────────┐
  │  [DepsBanner — solo se dipendenze mancano]   │
  ├──────────────────────────────────────────────┤
  │  eyebrow "TRASCRIZIONE"                      │
  │  Titolo grande 30px                          │
  │  Sottotitolo descrittivo                     │
  ├──────────────────────────────────────────────┤
  │  DropZone  (idle / hover / loaded / error)   │
  ├──────────────────────────────────────────────┤
  │  Settings card (grid 4 col)                  │
  │   Modello | Lingua | VAD | Alta precisione   │
  ├──────────────────────────────────────────────┤
  │  Action row: stima  ·  [Avvia]               │
  ├──────────────────────────────────────────────┤
  │  [Recenti — solo se QSettings ha file]       │
  └──────────────────────────────────────────────┘

Tema chiaro/scuro: i colori vengono letti da theme.c() e ri-applicati su
theme_changed via _apply_palette().

Segnale start_requested(source_path, settings) → MainWindow.
"""

from __future__ import annotations
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSettings, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QSpinBox, QSizePolicy,
    QFileDialog, QScrollArea,
)

from ui.source_panel import DepsBanner, SUPPORTED_EXTS, FILE_FILTERS, fmt_size
from ui.theme import AuroraMixin
from ui import theme
import platform_support


_MAX_RECENTS = 5


def _combo_ss() -> str:
    c = theme.c
    return (
        f"QComboBox {{ background: {c('card_2')}; border: 1px solid transparent; border-radius: 8px;"
        f" color: {c('text')}; padding: 5px 10px; font-size: 13px; font-weight: 500; min-height: 32px; }}"
        f"QComboBox:hover {{ border-color: {c('line_2')}; }}"
        f"QComboBox:focus {{ border-color: {c('acc')}; }}"
        "QComboBox::drop-down { border: none; width: 22px; }"
        f"QComboBox::down-arrow {{ border-left: 4px solid transparent;"
        f" border-right: 4px solid transparent; border-top: 5px solid {c('muted')}; margin-right: 8px; }}"
        f"QComboBox QAbstractItemView {{ background: {c('card')}; border: 1px solid {c('line_2')};"
        f" color: {c('text')}; selection-background-color: {c('acc_d')}; border-radius: 8px; }}"
    )


class HomeWidget(AuroraMixin, QWidget):
    """Schermata iniziale: drag&drop + impostazioni + avvia."""

    start_requested = Signal(str, dict)   # (source_path, settings)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentPanel")
        self._source_path: str | None = None
        self._aurora_init()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Scroll area ───────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        root.addWidget(scroll)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        scroll.setWidget(inner)

        lay = QVBoxLayout(inner)
        lay.setContentsMargins(80, 48, 80, 48)
        lay.setSpacing(0)
        lay.addStretch(1)

        # contenuto centrato a max 780px
        content = QWidget()
        content.setMaximumWidth(780)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # ── Banner dipendenze ─────────────────────────────────────────────────
        self.deps_banner = DepsBanner()
        cl.addWidget(self.deps_banner)
        cl.addSpacing(8)

        # ── Header ───────────────────────────────────────────────────────────
        self._eyebrow = QLabel("TRASCRIZIONE")
        cl.addWidget(self._eyebrow)
        cl.addSpacing(10)

        self._title = QLabel("Trasforma il tuo video in sottotitoli SRT.")
        self._title.setWordWrap(True)
        cl.addWidget(self._title)
        cl.addSpacing(10)

        self._sub = QLabel(
            "Trascrizione automatica in italiano, interamente in locale sul tuo Mac. "
            "Trascina un file, scegli il modello e ottieni sottotitoli pronti da rifinire nell'editor."
        )
        self._sub.setWordWrap(True)
        cl.addWidget(self._sub)
        cl.addSpacing(24)

        # ── DropZone ──────────────────────────────────────────────────────────
        self.drop = _DesignDropZone()
        self.drop.file_selected.connect(self._on_file_selected)
        self.drop.file_error.connect(self._on_file_error)
        cl.addWidget(self.drop)
        cl.addSpacing(16)

        # ── Settings card ─────────────────────────────────────────────────────
        self._settings_card = self._build_settings_card()
        cl.addWidget(self._settings_card)
        cl.addSpacing(20)

        # ── Action row ────────────────────────────────────────────────────────
        ar = QHBoxLayout()
        ar.setSpacing(12)
        self._estimate_lbl = QLabel("Stima: –")
        ar.addWidget(self._estimate_lbl)
        ar.addStretch(1)
        self._preview_btn = QPushButton("Anteprima impostazioni")
        self._preview_btn.setObjectName("secondary")
        self._preview_btn.setMinimumHeight(44)
        self._preview_btn.setCursor(Qt.PointingHandCursor)
        self._preview_btn.clicked.connect(self._on_preview_settings)
        ar.addWidget(self._preview_btn)
        self.start_btn = QPushButton("Avvia trascrizione")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(44)
        self.start_btn.setMinimumWidth(200)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start)
        ar.addWidget(self.start_btn)
        cl.addLayout(ar)
        cl.addSpacing(24)

        # ── Recenti ───────────────────────────────────────────────────────────
        self._recents_widget = _RecentsWidget()
        self._recents_widget.file_selected.connect(self._on_file_selected)
        cl.addWidget(self._recents_widget)
        self._refresh_recents()

        # centra content
        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.addStretch(1)
        center_row.addWidget(content, 0)
        center_row.addStretch(1)
        lay.addLayout(center_row)
        lay.addStretch(1)

        self._apply_palette()
        self._set_start_btn_state(False)
        theme.MANAGER.theme_changed.connect(self._on_theme_changed)

    # ── Aurora ────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        self._aurora_paint(p)
        p.end()

    # ── Tema ────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _name: str):
        self._apply_palette()
        self.drop._apply_palette()
        self._recents_widget._apply_palette()
        if hasattr(self, "model_combo"):
            ss = _combo_ss()
            self.model_combo.setStyleSheet(ss)
            self.lang_combo.setStyleSheet(ss)
        self._vad_toggle_refresh()
        self._set_start_btn_state(self._source_path is not None)
        self.update()

    def _apply_palette(self):
        c = theme.c
        self._eyebrow.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {c('muted')};"
            " letter-spacing: 1.6px; background: transparent;"
        )
        self._title.setStyleSheet(
            f"font-size: 30px; font-weight: 600; color: {c('text')};"
            " letter-spacing: -0.6px; background: transparent;"
        )
        self._sub.setStyleSheet(f"font-size: 14.5px; color: {c('dim')}; background: transparent;")
        self._estimate_lbl.setStyleSheet(
            f"font-size: 12px; color: {c('muted')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        if hasattr(self, "_settings_card"):
            self._settings_card.setStyleSheet(
                f"QFrame {{ background-color: {c('card')}; border: 1px solid {c('card_border')}; border-radius: 11px; }}"
            )
        if hasattr(self, "_head_lbl"):
            self._head_lbl.setStyleSheet(
                f"font-size: 10px; font-weight: 600; color: {c('muted')};"
                " letter-spacing: 1.2px; background: transparent;"
            )
            self._preset_lbl.setStyleSheet(
                f"font-size: 10.5px; color: {c('faint')}; background: transparent;"
                f" font-family: {theme.FONT_MONO};"
            )
            for lbl in self._field_labels:
                lbl.setStyleSheet(
                    f"font-size: 10px; font-weight: 600; color: {c('muted')};"
                    " letter-spacing: 1px; background: transparent;"
                )

    def _vad_toggle_refresh(self):
        if hasattr(self, "vad_toggle"):
            self.vad_toggle._apply_palette()
            self.accuracy_toggle._apply_palette()

    # ── Settings card ─────────────────────────────────────────────────────────

    def _build_settings_card(self) -> QFrame:
        from engine import MODELS, DEFAULT_MODEL
        self._models = MODELS
        self._model_keys = list(MODELS.keys())

        card = QFrame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        # header row: titolo a sinistra, riepilogo preset a destra
        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        self._head_lbl = QLabel("IMPOSTAZIONI DI TRASCRIZIONE")
        head_row.addWidget(self._head_lbl)
        head_row.addStretch()
        self._preset_lbl = QLabel("")
        head_row.addWidget(self._preset_lbl)
        lay.addLayout(head_row)

        # grid 4 col: Modello | Lingua | VAD | Alta precisione
        grid = QHBoxLayout()
        grid.setSpacing(14)

        self._field_labels = []
        ss = _combo_ss()

        # Modello
        col_m = self._col("MODELLO WHISPER")
        self.model_combo = QComboBox()
        self.model_combo.setStyleSheet(ss)
        for k in self._model_keys:
            self.model_combo.addItem(self._models[k]["label"], k)
        self.model_combo.setCurrentIndex(self._model_keys.index(DEFAULT_MODEL))
        self.model_combo.currentIndexChanged.connect(self._update_estimate)
        self.model_combo.currentIndexChanged.connect(self._update_preset_label)
        col_m.addWidget(self.model_combo)
        grid.addLayout(col_m, 2)

        # Lingua
        col_l = self._col("LINGUA")
        self.lang_combo = QComboBox()
        self.lang_combo.setStyleSheet(ss)
        self.lang_combo.addItem("Italiano  auto", "it")
        self.lang_combo.addItem("English  auto", "en")
        self.lang_combo.addItem("Español  auto", "es")
        self.lang_combo.addItem("Français  auto", "fr")
        self.lang_combo.addItem("Deutsch  auto", "de")
        self.lang_combo.addItem("Auto-detect", "auto")
        self.lang_combo.setCurrentIndex(0)
        self.lang_combo.currentIndexChanged.connect(self._update_preset_label)
        col_l.addWidget(self.lang_combo)
        grid.addLayout(col_l, 2)

        # VAD
        col_v = self._col("FILTRO VAD")
        self.vad_toggle = _ToggleSwitch("Attivo", "Disattivo")
        self.vad_toggle.setChecked(True)
        self.vad_toggle.toggled.connect(self._update_preset_label)
        col_v.addWidget(self.vad_toggle)
        col_v.addStretch()
        grid.addLayout(col_v, 1)

        # Alta precisione
        col_hp = self._col("ALTA PRECISIONE")
        self.accuracy_toggle = _ToggleSwitch("Attiva", "Standard")
        self.accuracy_toggle.setChecked(False)
        self.accuracy_toggle.setToolTip(
            "Usa WhisperX con allineamento fonetico.\nRichiede: pip install whisperx"
        )
        self.accuracy_toggle.toggled.connect(self._update_preset_label)
        col_hp.addWidget(self.accuracy_toggle)
        col_hp.addStretch()
        grid.addLayout(col_hp, 1)

        # beam_spin non visibile ma mantenuto per compatibilità con _get_settings()
        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 15)
        self.beam_spin.setValue(5)
        self.beam_spin.hide()

        lay.addLayout(grid)
        self._update_preset_label()
        return card

    def _update_preset_label(self):
        """Aggiorna il testo riepilogo preset nell'header della card."""
        active = 0
        parts = []
        if self.vad_toggle.isChecked():
            active += 1
        if self.accuracy_toggle.isChecked():
            active += 1
            parts.append("Alta qualità")
        else:
            parts.append("Standard")
        lang_text = self.lang_combo.currentText().split()[0] if hasattr(self, "lang_combo") else "Italiano"
        parts.insert(0, lang_text)
        active += 1  # lingua sempre attiva
        preset = "  ·  ".join(parts)
        self._preset_lbl.setText(f'{active} attive  ·  preset "{preset}"')

    def _col(self, label: str) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(6)
        lbl = QLabel(label)
        self._field_labels.append(lbl)
        col.addWidget(lbl)
        return col

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_file_selected(self, path: str):
        self._source_path = path
        self.drop.show_loaded(path)
        self._set_start_btn_state(True)
        self._update_estimate()
        self._add_to_recents(path)
        self._refresh_recents()

    def _set_start_btn_state(self, enabled: bool):
        c = theme.c
        if enabled:
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶  Avvia trascrizione")
            self.start_btn.setStyleSheet(
                "QPushButton {"
                f"  background-color: {c('acc')};"
                f"  color: {c('acc_ink')};"
                "  border: none;"
                "  border-radius: 8px;"
                "  font-size: 14px;"
                "  font-weight: 600;"
                "  padding: 0 22px;"
                "  min-height: 44px;"
                "}"
                f"QPushButton:hover {{ background-color: {c('acc_h')}; }}"
                f"QPushButton:pressed {{ background-color: {c('acc_d')}; }}"
            )
        else:
            self.start_btn.setEnabled(False)
            self.start_btn.setText("Avvia trascrizione")
            self.start_btn.setStyleSheet(
                "QPushButton {"
                f"  background-color: {c('card')};"
                f"  color: {c('muted')};"
                f"  border: 1px solid {c('line')};"
                "  border-radius: 8px;"
                "  font-size: 14px;"
                "  font-weight: 500;"
                "  padding: 0 22px;"
                "  min-height: 44px;"
                "}"
            )

    def _on_file_error(self, ext: str):
        self.drop.show_error(ext)
        self._source_path = None
        self._set_start_btn_state(False)
        self._estimate_lbl.setText("Formato non supportato")

    def _on_start(self):
        if not self._source_path:
            return
        self.start_requested.emit(self._source_path, self._get_settings())

    def _get_settings(self) -> dict:
        return {
            "model_size":    self.model_combo.currentData(),
            "language":      self.lang_combo.currentData(),
            "vad_filter":    self.vad_toggle.isChecked(),
            "denoise":       True,
            "high_accuracy": self.accuracy_toggle.isChecked(),
            "beam_size":     self.beam_spin.value(),
        }

    def _update_estimate(self):
        if not self._source_path:
            self._estimate_lbl.setText("Stima: –")
            return
        try:
            size_mb = os.path.getsize(self._source_path) / (1024 * 1024)
            model_key = self.model_combo.currentData() or "large-v3"
            factor = {
                "tiny": 0.15, "base": 0.25, "small": 0.4,
                "medium": 0.65, "large-v2": 1.0, "large-v3": 1.0,
            }.get(model_key, 1.0)
            mins = max(1, int(size_mb * factor / 100 * 1.5))
            srt_kb = max(1, int(size_mb * 0.05))
            self._estimate_lbl.setText(
                f"Stima: ~ {mins}–{mins * 2} min di lavoro  ·  output ~ {srt_kb} KB .srt"
            )
        except OSError:
            self._estimate_lbl.setText("Stima: –")

    def _on_preview_settings(self):
        from PySide6.QtWidgets import QMessageBox
        s = self._get_settings()
        model_lbl = self._models.get(s["model_size"], {}).get("label", s["model_size"])
        lang = self.lang_combo.currentText()
        vad = "Attivo" if s["vad_filter"] else "Disattivo"
        prec = "Alta qualità" if s["high_accuracy"] else "Standard"
        QMessageBox.information(
            self, "Impostazioni di trascrizione",
            f"Modello:        {model_lbl}\n"
            f"Lingua:          {lang}\n"
            f"Filtro VAD:    {vad}\n"
            f"Precisione:    {prec}\n"
            f"Beam size:    {s['beam_size']}",
        )

    # ── Recenti ───────────────────────────────────────────────────────────────

    def _add_to_recents(self, path: str):
        s = QSettings("VideoSRT", "v2")
        recents: list = s.value("recents", []) or []
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        recents = [r for r in recents if os.path.isfile(r)][:_MAX_RECENTS]
        s.setValue("recents", recents)

    def _refresh_recents(self):
        s = QSettings("VideoSRT", "v2")
        recents: list = s.value("recents", []) or []
        recents = [r for r in recents if os.path.isfile(r)][:_MAX_RECENTS]
        self._recents_widget.set_recents(recents)

    # ── API pubblica ──────────────────────────────────────────────────────────

    def set_deps_status(self, ffmpeg_ok: bool, model_ok: bool):
        self.deps_banner.set_status(ffmpeg_ok, model_ok)

    def preload_file(self, path: str):
        self._on_file_selected(path)

    def reset(self):
        self._source_path = None
        self.drop.reset()
        self._set_start_btn_state(False)
        self._estimate_lbl.setText("Stima: –")
        self._refresh_recents()


# ── _DesignDropZone ───────────────────────────────────────────────────────────

class _DesignDropZone(QWidget):
    """Drop zone con widget fissi — nessun rebuild, nessuna sovrapposizione."""

    file_selected = Signal(str)
    file_error    = Signal(str)

    _IDLE   = "idle"
    _HOVER  = "hover"
    _LOADED = "loaded"
    _ERROR  = "error"

    _H_NORMAL = 196
    _H_LOADED = 78

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self._IDLE
        self._file_path: str | None = None
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(self._H_NORMAL)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Stack: un QWidget per stato, sempre presenti, show/hide
        from PySide6.QtWidgets import QStackedLayout
        stack = QStackedLayout(self)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setStackingMode(QStackedLayout.StackOne)

        # ── Idle ──────────────────────────────────────────────────────────────
        self._w_idle = QWidget()
        lay_idle = QVBoxLayout(self._w_idle)
        lay_idle.setAlignment(Qt.AlignCenter)
        lay_idle.setSpacing(10)
        lay_idle.setContentsMargins(24, 0, 24, 0)

        self._idle_icon = QLabel("↓")
        self._idle_icon.setAlignment(Qt.AlignCenter)
        self._idle_icon.setFixedSize(56, 56)
        lay_idle.addWidget(self._idle_icon, 0, Qt.AlignCenter)
        self._idle_t1 = QLabel("Trascina qui un file video o audio")
        self._idle_t1.setAlignment(Qt.AlignCenter)
        lay_idle.addWidget(self._idle_t1)
        self._idle_t2 = QLabel(
            f"oppure  {platform_support.shortcut_label('Ctrl+O')}  per scegliere"
            "  ·  MP4, MOV, MKV, WAV, MP3 fino a 4 GB"
        )
        self._idle_t2.setAlignment(Qt.AlignCenter)
        lay_idle.addWidget(self._idle_t2)

        # ── Hover ─────────────────────────────────────────────────────────────
        self._w_hover = QWidget()
        lay_hover = QVBoxLayout(self._w_hover)
        lay_hover.setAlignment(Qt.AlignCenter)
        lay_hover.setSpacing(10)
        lay_hover.setContentsMargins(24, 0, 24, 0)
        self._hover_icon = QLabel("↓")
        self._hover_icon.setAlignment(Qt.AlignCenter)
        self._hover_icon.setFixedSize(56, 56)
        lay_hover.addWidget(self._hover_icon, 0, Qt.AlignCenter)
        self._hover_t1 = QLabel("Rilascia per caricare")
        self._hover_t1.setAlignment(Qt.AlignCenter)
        lay_hover.addWidget(self._hover_t1)

        # ── Error ─────────────────────────────────────────────────────────────
        self._w_error = QWidget()
        lay_error = QVBoxLayout(self._w_error)
        lay_error.setAlignment(Qt.AlignCenter)
        lay_error.setSpacing(10)
        lay_error.setContentsMargins(24, 0, 24, 0)
        self._err_icon = QLabel("!")
        self._err_icon.setAlignment(Qt.AlignCenter)
        self._err_icon.setFixedSize(56, 56)
        lay_error.addWidget(self._err_icon, 0, Qt.AlignCenter)
        self._err_t1 = QLabel("Formato non supportato")
        self._err_t1.setAlignment(Qt.AlignCenter)
        lay_error.addWidget(self._err_t1)
        self._err_t2 = QLabel("Usa MP4, MOV, MKV, WAV o MP3.")
        self._err_t2.setAlignment(Qt.AlignCenter)
        lay_error.addWidget(self._err_t2)

        # ── Loaded ────────────────────────────────────────────────────────────
        self._w_loaded = QWidget()
        lay_loaded = QHBoxLayout(self._w_loaded)
        lay_loaded.setSpacing(14)
        lay_loaded.setContentsMargins(20, 0, 20, 0)
        lay_loaded.setAlignment(Qt.AlignVCenter)

        self._loaded_icon = QLabel("▶")
        self._loaded_icon.setAlignment(Qt.AlignCenter)
        self._loaded_icon.setFixedSize(46, 46)
        lay_loaded.addWidget(self._loaded_icon)

        info_col = QVBoxLayout()
        info_col.setSpacing(3)
        self._loaded_name = QLabel("")
        self._loaded_detail = QLabel("")
        info_col.addWidget(self._loaded_name)
        info_col.addWidget(self._loaded_detail)
        lay_loaded.addLayout(info_col, 1)

        self._change_btn = QPushButton("Cambia")
        self._change_btn.setFixedHeight(32)
        self._change_btn.setCursor(Qt.PointingHandCursor)
        self._change_btn.clicked.connect(self._open_dialog)
        lay_loaded.addWidget(self._change_btn)

        # Aggiungi tutti al stack
        stack.addWidget(self._w_idle)    # index 0
        stack.addWidget(self._w_hover)   # index 1
        stack.addWidget(self._w_error)   # index 2
        stack.addWidget(self._w_loaded)  # index 3
        self._stack = stack
        self._stack.setCurrentIndex(0)

        self._apply_palette()

    def _apply_palette(self):
        c = theme.c
        self._idle_icon.setStyleSheet(
            f"font-size: 23px; color: {c('muted')}; background: {c('card_2')};"
            " border: none; border-radius: 14px;"
        )
        self._idle_t1.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {c('text')}; background: transparent;")
        self._idle_t2.setStyleSheet(
            f"font-size: 12px; color: {c('muted')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._hover_icon.setStyleSheet(
            f"font-size: 21px; font-weight: 700; color: {c('acc')};"
            f" background: {c('acc_soft_2')}; border: 1px solid {c('acc')}; border-radius: 14px;"
        )
        self._hover_t1.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {c('text')}; background: transparent;")
        self._err_icon.setStyleSheet(
            f"font-size: 21px; font-weight: 700; color: {c('err')};"
            f" background: {c('err_soft')}; border: 1px solid {c('err')}; border-radius: 14px;"
        )
        self._err_t1.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {c('err')}; background: transparent;")
        self._err_t2.setStyleSheet(f"font-size: 12px; color: {c('muted')}; background: transparent;")
        self._loaded_icon.setStyleSheet(
            f"font-size: 18px; color: {c('acc')}; background: {c('card_2')};"
            " border: none; border-radius: 11px;"
        )
        self._loaded_name.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {c('text')}; background: transparent;"
        )
        self._loaded_detail.setStyleSheet(
            f"font-size: 12px; color: {c('muted')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        self._change_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {c('line_2')};"
            f" border-radius: 7px; color: {c('dim')}; font-size: 12.5px; font-weight: 500; padding: 0 13px; }}"
            f"QPushButton:hover {{ background: {c('card_2')}; border-color: {c('line_2')}; color: {c('text')}; }}"
            f"QPushButton:pressed {{ background: {c('card')}; }}"
        )
        self.update()

    def _set_state(self, state: str):
        self._state = state
        idx = {self._IDLE: 0, self._HOVER: 1, self._ERROR: 2, self._LOADED: 3}[state]
        self._stack.setCurrentIndex(idx)
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        c = theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)

        if self._state == self._IDLE:
            p.setBrush(QColor(c("card")))
            pen = QPen(QColor(c("line_2")))
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(r, 16, 16)

        elif self._state == self._HOVER:
            p.setBrush(QColor(c("acc_soft")))
            pen = QPen(QColor(c("acc")))
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(r, 16, 16)
            glow = QColor(c("acc")); glow.setAlpha(45)
            glow_pen = QPen(glow)
            glow_pen.setWidth(6)
            p.setPen(glow_pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 18, 18)

        elif self._state == self._LOADED:
            p.setBrush(QColor(c("card")))
            p.setPen(QPen(QColor(c("line_2"))))
            p.drawRoundedRect(r, 16, 16)

        elif self._state == self._ERROR:
            p.setBrush(QColor(c("card")))
            pen = QPen(QColor(c("err")))
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(r, 16, 16)

        p.end()

    # ── Drag & drop ───────────────────────────────────────────────────────────

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            path = e.mimeData().urls()[0].toLocalFile()
            if Path(path).suffix.lower() in SUPPORTED_EXTS:
                e.acceptProposedAction()
                self.setFixedHeight(self._H_NORMAL)
                self._set_state(self._HOVER)
                return
        e.ignore()

    def dragLeaveEvent(self, e):
        if self._file_path:
            self.setFixedHeight(self._H_LOADED)
            self._set_state(self._LOADED)
        else:
            self.setFixedHeight(self._H_NORMAL)
            self._set_state(self._IDLE)

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if not urls:
            self.dragLeaveEvent(e)
            return
        path = urls[0].toLocalFile()
        ext = Path(path).suffix.lower()
        if ext in SUPPORTED_EXTS and os.path.isfile(path):
            self.file_selected.emit(path)
            e.acceptProposedAction()
        else:
            self.file_error.emit(ext.lstrip("."))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._open_dialog()

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleziona un file video o audio", "", FILE_FILTERS
        )
        if path:
            ext = Path(path).suffix.lower()
            if ext in SUPPORTED_EXTS:
                self.file_selected.emit(path)
            else:
                self.file_error.emit(ext.lstrip("."))

    # ── API ───────────────────────────────────────────────────────────────────

    def show_loaded(self, path: str):
        self._file_path = path
        self._loaded_name.setText(Path(path).name)
        ext = Path(path).suffix.upper().lstrip(".")
        self._loaded_detail.setText(f"{fmt_size(path)}  ·  {ext}")
        self.setFixedHeight(self._H_LOADED)
        self._set_state(self._LOADED)

    def show_error(self, ext: str):
        self._file_path = None
        self.setFixedHeight(self._H_NORMAL)
        self._set_state(self._ERROR)

    def reset(self):
        self._file_path = None
        self.setFixedHeight(self._H_NORMAL)
        self._set_state(self._IDLE)


# ── _ToggleSwitch ─────────────────────────────────────────────────────────────

class _ToggleSwitch(QWidget):
    """Toggle switch stile design — row con pill + label."""

    toggled = Signal(bool)

    def __init__(self, label_on: str = "Attivo", label_off: str = "Disattivo", parent=None):
        super().__init__(parent)
        self._checked = False
        self._on = label_on
        self._off = label_off
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._pill = _SwitchPill()
        lay.addWidget(self._pill)

        # larghezza fissa per la label — evita resize del layout al cambio testo
        max_w = max(len(label_on), len(label_off)) * 8 + 8
        self._lbl = QLabel(self._off)
        self._lbl.setFixedWidth(max_w)
        lay.addWidget(self._lbl)
        lay.addStretch()

        self._apply_palette()

    def _apply_palette(self):
        c = theme.c
        self.setStyleSheet(
            f"QWidget {{ background: {c('card_2')}; border: 1px solid transparent; border-radius: 8px; }}"
        )
        self._lbl.setStyleSheet(
            f"font-size: 12.5px; font-weight: 500; color: {c('text')};"
            " background: transparent; border: none;"
        )
        self._pill.update()

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool):
        self._checked = val
        self._pill.set_on(val)
        self._lbl.setText(self._on if val else self._off)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)


class _SwitchPill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._on = False
        self.setFixedSize(32, 19)

    def set_on(self, val: bool):
        self._on = val
        self.update()

    def paintEvent(self, event):
        c = theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(c("acc")) if self._on else QColor(c("inset")))
        p.setPen(QPen(QColor(c("acc")) if self._on else QColor(c("line_2"))))
        p.drawRoundedRect(0, 0, 32, 19, 10, 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff") if self._on else QColor(c("muted")))
        x = 14 if self._on else 1
        p.drawEllipse(x, 1, 16, 16)
        p.end()


# ── _RecentsWidget ────────────────────────────────────────────────────────────

class _RecentsWidget(QWidget):
    """Riga file recenti — visibile solo se ci sono file."""

    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self.setVisible(False)
        self.setStyleSheet("background: transparent;")
        self._paths: list = []

    def _apply_palette(self):
        if self._paths:
            self.set_recents(self._paths)

    def set_recents(self, paths: list):
        self._paths = list(paths)
        c = theme.c
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

        if not paths:
            self.setVisible(False)
            return

        lbl = QLabel("RECENTI")
        lbl.setStyleSheet(
            f"font-size: 10px; font-weight: 600; color: {c('muted')};"
            " letter-spacing: 1.2px; background: transparent;"
        )
        self._lay.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(12)
        for path in paths[:3]:
            row.addWidget(self._make_card(path), 1)
        self._lay.addLayout(row)
        self.setVisible(True)

    def _make_card(self, path: str) -> QFrame:
        c = theme.c
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {c('card')}; border: 1px solid {c('card_border')}; border-radius: 10px; }}"
            f"QFrame:hover {{ border-color: {c('acc')}; background: {c('card_2')}; }}"
        )
        card.setCursor(Qt.PointingHandCursor)
        card.setFixedHeight(54)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(13, 0, 13, 0)
        lay.setSpacing(11)

        ic = QLabel("▦")
        ic.setFixedSize(32, 32)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(
            f"background: {c('card_2')}; border: none; border-radius: 8px;"
            f" color: {c('muted')}; font-size: 14px;"
        )
        lay.addWidget(ic)

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(Path(path).name)
        name.setStyleSheet(f"font-size: 12.5px; font-weight: 500; color: {c('text')}; background: transparent;")
        try:
            size_str = fmt_size(path)
        except Exception:
            size_str = ""
        meta = QLabel(size_str)
        meta.setStyleSheet(
            f"font-size: 10.5px; color: {c('muted')}; background: transparent;"
            f" font-family: {theme.FONT_MONO};"
        )
        info.addWidget(name)
        info.addWidget(meta)
        lay.addLayout(info, 1)

        card.mousePressEvent = lambda e, p=path: self.file_selected.emit(p)
        return card
